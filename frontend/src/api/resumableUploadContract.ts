export function authenticatedGateway(uploadId: string, gatewayUrl: string, origin: string): string {
  if (!/^[a-f0-9]{32}$/.test(uploadId)) throw new Error('Invalid upload identity');
  const gateway = new URL(gatewayUrl, origin);
  if (gateway.origin !== new URL(origin).origin || gateway.search || gateway.hash
      || gateway.username || gateway.password
      || !gateway.pathname.endsWith(`/upload-transport/${uploadId}`)) {
    throw new Error('Authenticated same-origin upload gateway required');
  }
  return gateway.href;
}

export function recoverableTransportState(value: unknown): 'create' | 'resume' | 'complete' {
  if (value === 'CREATED') return 'create';
  if (value === 'UPLOADING') return 'resume';
  if (value === 'UPLOADED' || value === 'VERIFYING' || value === 'VERIFIED' || value === 'FINALIZED') return 'complete';
  throw new Error('Upload session cannot be recovered');
}

/** Completion is server state, not permission to accept a different selected PDF. */
export async function verifyRecoverySelection(file: File, session: {
  status: unknown; expectedSize: number; expectedSha256: string;
}): Promise<'create' | 'resume' | 'complete'> {
  const state = recoverableTransportState(session.status);
  await verifyReselectedPdf(file, session.expectedSize, session.expectedSha256);
  return state;
}

/** Parse authenticated server state; browser persistence is not authoritative. */
export function parseTusSession(value: unknown) {
  return parseUploadSession(value, 'tus');
}

export function parseFormalSession(value: unknown) {
  return parseUploadSession(value, 'legacy_multipart');
}

function parseUploadSession(value: unknown, protocol: 'tus' | 'legacy_multipart') {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('Invalid upload session');
  const item = value as Record<string, unknown>;
  const states = ['CREATED', 'UPLOADING', 'UPLOADED', 'VERIFYING', 'VERIFIED', 'FINALIZED', 'FAILED', 'EXPIRED'];
  if (typeof item.upload_id !== 'string' || !/^[a-f0-9]{32}$/.test(item.upload_id)
      || item.protocol !== protocol || typeof item.status !== 'string' || !states.includes(item.status)
      || typeof item.filename !== 'string' || !item.filename.toLowerCase().endsWith('.pdf')
      || /[\\/\u0000]/.test(item.filename)
      || typeof item.expected_size !== 'number' || !Number.isSafeInteger(item.expected_size)
      || item.expected_size <= 0 || item.expected_size > 50 * 1024 * 1024
      || typeof item.expected_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(item.expected_sha256)
      || typeof item.expires_at !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(item.expires_at)
      || !Number.isFinite(Date.parse(item.expires_at))) throw new Error('Invalid upload session');
  const nullableId = (input: unknown): string | null => {
    if (input === null) return null;
    if (typeof input !== 'string' || !input.trim()) throw new Error('Invalid upload binding');
    return input;
  };
  const documentId = nullableId(item.document_id);
  const ingestionJobId = nullableId(item.ingestion_job_id);
  // Accept older deployments without these fields; never accept malformed
  // progress from a newer server or replace tusd's authoritative HEAD offset.
  const bytesReceived = item.bytes_received === undefined ? null : item.bytes_received;
  if (bytesReceived !== null && (typeof bytesReceived !== 'number'
      || !Number.isSafeInteger(bytesReceived) || bytesReceived < 0
      || bytesReceived > item.expected_size)) throw new Error('Invalid persisted upload progress');
  const updatedAt = item.updated_at === undefined ? null : item.updated_at;
  if (updatedAt !== null && (typeof updatedAt !== 'string'
      || !/(Z|[+-]\d{2}:\d{2})$/.test(updatedAt)
      || !Number.isFinite(Date.parse(updatedAt)))) throw new Error('Invalid upload update time');
  if (item.status === 'FINALIZED' && (!documentId || !ingestionJobId)) throw new Error('Unbound finalized upload');
  return { uploadId: item.upload_id, status: item.status, filename: item.filename,
    expectedSize: item.expected_size, expectedSha256: item.expected_sha256,
    expiresAt: item.expires_at, documentId, ingestionJobId, bytesReceived, updatedAt };
}

const ingestionStages = ['PARSING', 'QUALITY_CHECK', 'BUILDING_FACTS', 'BUILDING_TREE', 'INDEXING'];
export function parseIngestionProgress(value: unknown, uploadId: string) {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('Invalid ingestion progress');
  const item = value as Record<string, unknown>;
  if (item.schema !== 'financial-ingestion-progress.v1' || item.upload_id !== uploadId
      || item.upload_status !== 'FINALIZED' || typeof item.status !== 'string'
      || !['pending', 'leased', 'ready', 'failed', 'quarantined'].includes(item.status)
      || typeof item.stage !== 'string' || ![...ingestionStages, 'READY'].includes(item.stage)
      || typeof item.quality_status !== 'string' || !['UNKNOWN', 'PASS', 'FAIL'].includes(item.quality_status)
      || !Array.isArray(item.completed_stages)
      || item.completed_stages.some((stage) => typeof stage !== 'string' || !ingestionStages.includes(stage))
      || new Set(item.completed_stages).size !== item.completed_stages.length) throw new Error('Invalid ingestion progress');
  if (item.status === 'ready' && (item.stage !== 'READY' || item.quality_status !== 'PASS'
      || item.completed_stages.length !== ingestionStages.length)) throw new Error('Unverified READY state');
  const ingestionJobId = item.ingestion_job_id;
  if (typeof ingestionJobId !== 'string' || !ingestionJobId.trim() || ingestionJobId.length > 128) {
    throw new Error('Missing ingestion job identity');
  }
  return { status: item.status, stage: item.stage, completedStages: item.completed_stages as string[], ingestionJobId };
}

/** Refresh recovery may require reselecting the file; bind it to server digest. */
export async function verifyReselectedPdf(file: File, expectedSize: number, expectedSha256: string): Promise<void> {
  if (!Number.isSafeInteger(expectedSize) || expectedSize <= 0 || expectedSize > 50 * 1024 * 1024
      || !/^[a-f0-9]{64}$/.test(expectedSha256) || file.size !== expectedSize
      || !file.name.toLowerCase().endsWith('.pdf')) {
    throw new Error('Reselected file does not match upload session');
  }
  const bytes = await file.arrayBuffer();
  const signature = new TextDecoder().decode(bytes.slice(0, 5));
  if (signature !== '%PDF-') throw new Error('PDF content required');
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  const actual = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
  if (actual !== expectedSha256) throw new Error('Reselected file checksum mismatch');
}
