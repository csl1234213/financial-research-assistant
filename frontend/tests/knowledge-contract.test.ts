import assert from 'node:assert/strict';
import test from 'node:test';

import {
  formatByteSize,
  MAX_PDF_UPLOAD_BYTES,
  mapKnowledgeDocument,
  parseDeleteDocumentResponse,
  parseDocumentQuota,
  parseDiscoveryResponse,
  parseTaskResponse,
  parseUploadResponse,
  validateDocumentUpload,
  validatePdfUpload,
} from '../src/api/knowledgeContract.ts';

test('quarantine and unknown states never become indexed cards', () => {
  const item = { id: 'doc', filename: 'annual.pdf' };
  assert.equal(mapKnowledgeDocument({ ...item, status: 'quarantined' })?.status, 'quarantined');
  for (const status of ['READY_TAMPERED', 'failed', undefined, null]) {
    assert.equal(mapKnowledgeDocument({ ...item, status })?.status, 'failed');
  }
  for (const status of ['ready', 'indexed']) {
    assert.equal(mapKnowledgeDocument({ ...item, status })?.status, 'indexed');
  }
  for (const status of ['registered', 'pending', 'processing']) {
    assert.equal(mapKnowledgeDocument({ ...item, status })?.status, 'processing');
  }
});

test('parses the quota contract without accepting widened values', () => {
  assert.deepEqual(parseDocumentQuota({
    used: 1,
    limit: 10,
    remaining: 9,
    bypassed: false,
  }), {
    used: 1,
    limit: 10,
    remaining: 9,
    bypassed: false,
  });
  assert.throws(
    () => parseDocumentQuota({ used: '1', limit: 10, remaining: 9, bypassed: false }),
    /used must be a non-negative integer/,
  );
});

test('parses upload, task, and deletion responses at the API boundary', () => {
  assert.deepEqual(parseUploadResponse({
    message: 'upload success',
    file: 'report.pdf',
    document_id: 7,
    task_id: 'task-7',
    status: 'pending',
  }).task_id, 'task-7');
  assert.deepEqual(parseTaskResponse({
    id: 'task-7',
    status: 'success',
    progress: 100,
    error: null,
  }), {
    id: 'task-7',
    status: 'success',
    progress: 100,
    error: null,
  });
  assert.deepEqual(parseDeleteDocumentResponse({
    deleted: true,
    document_id: 7,
  }), {
    deleted: true,
    document_id: 7,
  });
  assert.throws(
    () => parseTaskResponse({
      id: 'task-7',
      status: 'success',
      progress: 101,
      error: null,
    }),
    /progress must be a finite number between 0 and 100/,
  );
});

test('maps stable knowledge item fields from the backend contract', () => {
  const document = mapKnowledgeDocument({
    id: 42,
    filename: 'Tesla_Q2_2025.pdf',
    company: 'Tesla',
    period: 'Q2_2025',
    status: 'indexed',
    chunk_count: 63,
    byte_size: 2_621_440,
    content_sha256: 'a'.repeat(64),
    uploaded_at: '2026-07-29T12:00:00Z',
    can_delete: true,
  });

  assert.deepEqual(document, {
    id: '42',
    filename: 'Tesla_Q2_2025.pdf',
    company: 'Tesla',
    period: 'Q2_2025',
    status: 'indexed',
    pages: 0,
    chunkCount: 63,
    byteSize: 2_621_440,
    size: '2.5 MB',
    contentSha256: 'a'.repeat(64),
    sourceUrl: undefined,
    uploadedAt: '2026-07-29T12:00:00Z',
    canDelete: true,
  });
});

test('parses the SEC discovery contract and preserves source provenance', () => {
  assert.deepEqual(parseDiscoveryResponse({
    status: 'downloaded',
    filename: 'Microsoft_10Q_2025-01-01_000000000000000001.html',
    document_id: 8,
    task_id: 'task-8',
    company: 'Microsoft Corporation',
    period: '2025-01-01',
    source_url: 'https://www.sec.gov/Archives/edgar/data/1/report.html',
    source_type: 'sec_edgar',
    source_form: '10-Q',
  }).source_form, '10-Q');
  assert.throws(
    () => parseDiscoveryResponse({
      status: 'downloaded',
      filename: 'filing.html',
      document_id: 8,
      company: 'Microsoft',
      source_url: 42,
    }),
    /source_url must be a string/,
  );
});

test('parses CNINFO audited annual report discovery metadata', () => {
  const parsed = parseDiscoveryResponse({
    status: 'downloaded',
    filename: '贵州茅台_2025年度报告_审计_2026-04-17.pdf',
    document_id: 9,
    task_id: 'task-9',
    company: '贵州茅台',
    period: '2025-12-31',
    source_url: 'https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF',
    source_type: 'cninfo',
    source_stock_code: '600519',
    source_exchange: 'sse',
    source_report_type: 'annual',
    source_report_year: 2025,
    source_audited: true,
  });

  assert.equal(parsed.source_type, 'cninfo');
  assert.equal(parsed.source_stock_code, '600519');
  assert.equal(parsed.source_report_year, 2025);
  assert.equal(parsed.source_audited, true);
});

test('legacy filename responses remain readable without a stable delete id', () => {
  assert.deepEqual(mapKnowledgeDocument('NVIDIA.pdf'), {
    id: 'NVIDIA.pdf',
    filename: 'NVIDIA.pdf',
    company: 'Unknown',
    status: 'indexed',
    pages: 0,
    uploadedAt: '',
    canDelete: false,
  });
});

test('formats document byte sizes without losing small-file visibility', () => {
  assert.equal(formatByteSize(124), '124 B');
  assert.equal(formatByteSize(1536), '1.5 KB');
  assert.equal(formatByteSize(2_621_440), '2.5 MB');
});

test('accepts PDF filenames at the 50 MB upload boundary', () => {
  assert.equal(
    validatePdfUpload({
      name: 'Quarterly Report.PDF',
      size: MAX_PDF_UPLOAD_BYTES,
    }),
    null,
  );
});

test('rejects non-PDF files before upload', () => {
  assert.equal(
    validatePdfUpload({ name: 'financials.xlsx', size: 1024 }),
    'invalid-type',
  );
});

test('accepts supported financial report formats through the multi-format contract', () => {
  for (const name of ['report.pdf', 'quarterly.xlsx', 'filing.docx', 'facts.csv']) {
    assert.equal(validateDocumentUpload({ name, size: 1024 }), null);
  }
});

test('rejects unsupported financial report formats before upload', () => {
  assert.equal(
    validateDocumentUpload({ name: 'quarterly.xls', size: 1024 }),
    'invalid-type',
  );
});

test('rejects PDFs larger than the backend upload limit', () => {
  assert.equal(
    validatePdfUpload({
      name: 'annual-report.pdf',
      size: MAX_PDF_UPLOAD_BYTES + 1,
    }),
    'too-large',
  );
});
