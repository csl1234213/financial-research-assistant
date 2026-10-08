import assert from 'node:assert/strict';
import test from 'node:test';
import { authenticatedGateway, recoverableTransportState, verifyReselectedPdf, verifyRecoverySelection, parseTusSession, parseIngestionProgress } from '../src/api/resumableUploadContract.ts';

test('persisted upload progress is bounded and legacy absence is explicit', () => {
  const value = { upload_id: 'a'.repeat(32), protocol: 'tus', status: 'UPLOADING',
    filename: 'report.pdf', expected_size: 100, expected_sha256: 'a'.repeat(64),
    expires_at: '2026-10-02T00:00:00+00:00', document_id: null, ingestion_job_id: null };
  assert.equal(parseTusSession(value).bytesReceived, null);
  assert.equal(parseTusSession({ ...value, bytes_received: 80,
    updated_at: '2026-10-01T00:00:00+00:00' }).bytesReceived, 80);
  for (const offset of [-1, 101, true, '80', 1.5]) {
    assert.throws(() => parseTusSession({ ...value, bytes_received: offset }));
  }
  for (const time of ['bad', '2026-10-01T00:00:00', 1]) {
    assert.throws(() => parseTusSession({ ...value, updated_at: time }));
  }
});
import { createResumableUpload } from '../src/api/resumableUpload.ts';
import { uploadRecoveryKey, readUploadRecovery, rememberUploadRecovery } from '../src/api/uploadRecovery.ts';
import { parseReadyDocumentPage } from '../src/api/readyDocumentContract.ts';
import { createGroundedChatRequest } from '../src/api/groundedChatContract.ts';

const id = 'a'.repeat(32);
const path = `/api/upload-transport/${id}`;
test('ready report options require source identity and never accept local READY assertions', () => {
  const item = { upload_id: id, ingestion_job_id: 'job-1', document_id: 1,
    filename: 'report.pdf', content_sha256: 'a'.repeat(64) };
  const page = { schema: 'ready-document-options.v1', items: [item], next_offset: null };
  assert.equal(parseReadyDocumentPage(page).items[0].ingestionJobId, 'job-1');
  for (const changed of [{ document_id: null }, { content_sha256: 'unknown' },
    { filename: '../secret.pdf' }, { ingestion_job_id: ' ' }]) {
    assert.throws(() => parseReadyDocumentPage({ ...page, items: [{ ...item, ...changed }] }));
  }
  assert.throws(() => parseReadyDocumentPage({ ...page, items: [item, item] }));
  assert.throws(() => parseReadyDocumentPage({ ...page, next_offset: -1 }));
});
test('multi-report request keeps job identities distinct with a bounded selection', () => {
  assert.deepEqual(createGroundedChatRequest('primary', '跨文档说明', 'zh-CN', true, ['second']),
    { ingestion_job_id: 'primary', question: '跨文档说明', answer_language: 'zh-CN', stream: true,
      additional_ingestion_job_ids: ['second'] });
  for (const ids of [['primary'], ['second', 'second'], [' '], ['a', 'b', 'c', 'd', 'e']]) {
    assert.throws(() => createGroundedChatRequest('primary', '问题', 'zh-CN', false, ids));
  }
});
test('refresh recovery hints are isolated by both authenticated user and tenant', () => {
  const values = new Map<string, string>();
  const storage = { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); } };
  const key = uploadRecoveryKey(1, 2);
  assert.equal(rememberUploadRecovery(storage, key, id), true);
  assert.equal(readUploadRecovery(storage, key), id);
  assert.equal(readUploadRecovery(storage, uploadRecoveryKey(1, 3)), null);
  assert.equal(readUploadRecovery(storage, uploadRecoveryKey(2, 2)), null);
  assert.equal(values.get(key), id); // No token, PDF bytes or READY state persisted.
  values.set(key, '{"status":"READY"}');
  assert.equal(readUploadRecovery(storage, key), null);
  assert.throws(() => uploadRecoveryKey(0, 2));
  assert.throws(() => rememberUploadRecovery(storage, key, '../escape'));
});
test('unavailable browser storage does not fabricate a recovery record', () => {
  const storage = { getItem: () => { throw new Error('unavailable'); },
    setItem: () => { throw new Error('unavailable'); } };
  assert.equal(readUploadRecovery(storage, uploadRecoveryKey(1, 2)), null);
  assert.equal(rememberUploadRecovery(storage, uploadRecoveryKey(1, 2), id), false);
});
test('completed transport still requires original selected PDF before verify or finalize', async () => {
  const file = new File(['%PDF-1.7\nfixture'], 'report.pdf');
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer())),
    (byte) => byte.toString(16).padStart(2, '0')).join('');
  const other = new File(['%PDF-1.7\nanother'], 'report.pdf');
  assert.equal(other.size, file.size);
  for (const status of ['CREATED', 'UPLOADING', 'UPLOADED', 'VERIFYING', 'VERIFIED', 'FINALIZED']) {
    const session = { status, expectedSize: file.size, expectedSha256: hash };
    await assert.rejects(verifyRecoverySelection(other, session));
    assert.equal(await verifyRecoverySelection(file, session), recoverableTransportState(status));
  }
  await assert.rejects(verifyRecoverySelection(file, { status: 'EXPIRED', expectedSize: file.size, expectedSha256: hash }));
});
test('query-ready display requires quality PASS and all persisted stages', () => {
  const value = { schema: 'financial-ingestion-progress.v1', upload_id: id, upload_status: 'FINALIZED',
    status: 'ready', stage: 'READY', quality_status: 'PASS', ingestion_job_id: 'c'.repeat(32),
    completed_stages: ['PARSING', 'QUALITY_CHECK', 'BUILDING_FACTS', 'BUILDING_TREE', 'INDEXING'] };
  assert.equal(parseIngestionProgress(value, id).status, 'ready');
  assert.equal(parseIngestionProgress(value, id).ingestionJobId, 'c'.repeat(32));
  assert.notEqual(parseIngestionProgress(value, id).ingestionJobId, id);
  for (const change of [{ quality_status: 'FAIL' }, { quality_status: ['PASS'] },
    { completed_stages: ['PARSING'] }, { completed_stages: Array(5).fill('PARSING') },
    { stage: 'INDEXING' }, { upload_id: 'b'.repeat(32) }, { upload_status: 'VERIFIED' },
    { ingestion_job_id: null }, { ingestion_job_id: '' }]) {
    assert.throws(() => parseIngestionProgress({ ...value, ...change }, id));
  }
});
test('recovery session requires server identity and finalized ingestion bindings', () => {
  const value = { upload_id: id, protocol: 'tus', status: 'UPLOADING', filename: 'report.pdf',
    expected_size: 15, expected_sha256: 'a'.repeat(64), expires_at: '2026-10-02T00:00:00+00:00',
    document_id: null, ingestion_job_id: null };
  assert.equal(parseTusSession(value).expectedSha256, value.expected_sha256);
  for (const change of [{ protocol: 'legacy_multipart' }, { expected_size: '15' },
    { expected_sha256: 'invalid' }, { filename: '../report.pdf' }, { status: 'READY' },
    { expires_at: '2026-10-02T00:00:00' }, { status: 'FINALIZED' }]) {
    assert.throws(() => parseTusSession({ ...value, ...change }));
  }
  assert.equal(parseTusSession({ ...value, status: 'FINALIZED', document_id: 'doc',
    ingestion_job_id: 'job' }).ingestionJobId, 'job');
});
test('controller rejects mismatched bytes before registering a file', async () => {
  const file = new File(['%PDF-1.7\nfixture'], 'report.pdf', { type: 'application/pdf' });
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer())),
    (byte) => byte.toString(16).padStart(2, '0')).join('');
  const controller = createResumableUpload({ uploadId: id, gatewayUrl: path,
    origin: 'http://localhost:3000', getToken: () => 'test-token', onProgress: () => {},
    expectedSize: file.size, expectedSha256: hash });
  try {
    assert.equal('addFile' in controller, false);
    await assert.rejects(controller.selectFile(new File(['%PDF-1.7\nchanged'], 'report.pdf')));
    // A rejected selection must not consume the one-file slot.
    assert.equal(typeof await controller.selectFile(file), 'string');
  } finally {
    controller.destroy();
  }
});
test('transport is bound to the same authenticated origin and upload identity', () => {
  assert.equal(authenticatedGateway(id, path, 'http://localhost:3000'), `http://localhost:3000${path}`);
  for (const invalid of [`http://evil.test${path}`, `${path}?token=secret`, `${path}#fragment`, '/files/raw']) {
    assert.throws(() => authenticatedGateway(id, invalid, 'http://localhost:3000'));
  }
  assert.throws(() => authenticatedGateway('../escape', path, 'http://localhost:3000'));
});

test('reselected file is bound to size, PDF signature and server SHA', async () => {
  const file = new File(['%PDF-1.7\nfixture'], 'report.pdf');
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  const hash = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
  await verifyReselectedPdf(file, file.size, hash);
  await assert.rejects(verifyReselectedPdf(file, file.size, '0'.repeat(64)));
  await assert.rejects(verifyReselectedPdf(file, file.size + 1, hash));
  await assert.rejects(verifyReselectedPdf(new File(['not PDF content'], 'report.pdf'), 15, hash));
});
test('recovery distinguishes byte transport from completed business processing', () => {
  assert.equal(recoverableTransportState('CREATED'), 'create');
  assert.equal(recoverableTransportState('UPLOADING'), 'resume');
  for (const state of ['UPLOADED', 'VERIFYING', 'VERIFIED', 'FINALIZED']) {
    assert.equal(recoverableTransportState(state), 'complete');
  }
  for (const state of ['FAILED', 'EXPIRED', 'READY', null, {}]) {
    assert.throws(() => recoverableTransportState(state));
  }
});
import { createIngestionInvalidator } from '../src/api/ingestionInvalidation.ts';

test('ingestion state invalidation deduplicates polls but refreshes every transition', async () => {
  let reads = 0;
  const notify = createIngestionInvalidator(() => { reads += 1; });
  assert.equal(notify('upload-a', 'registered'), true);
  assert.equal(notify('upload-a', 'registered'), false);
  assert.equal(notify('upload-a', 'leased:PARSING'), true);
  assert.equal(notify('upload-a', 'leased:PARSING'), false);
  assert.equal(notify('upload-a', 'ready:READY'), true);
  assert.equal(notify('upload-a', 'ready:READY'), false);
  await Promise.resolve();
  assert.equal(reads, 3);
});

test('new uploads and quarantine invalidate independently; refresh failure is contained', async () => {
  let reads = 0;
  const notify = createIngestionInvalidator(async () => { reads += 1; throw new Error('refresh unavailable'); });
  notify('upload-a', 'quarantined:QUALITY_CHECK');
  assert.equal(notify('upload-a', 'quarantined:QUALITY_CHECK'), false);
  notify('upload-b', 'quarantined:QUALITY_CHECK');
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(reads, 2);
});
