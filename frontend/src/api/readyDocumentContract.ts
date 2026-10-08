export interface ReadyDocumentOption {
  uploadId: string;
  ingestionJobId: string;
  documentId: number;
  filename: string;
  contentSha256: string;
}

/** A server discovery snapshot, not lasting authorization or readiness. */
export function parseReadyDocumentPage(value: unknown) {
  if (!value || typeof value !== 'object') throw new Error('Invalid ready document list.');
  const page = value as Record<string, unknown>;
  if (page.schema !== 'ready-document-options.v1' || !Array.isArray(page.items) || page.items.length > 50
    || (page.next_offset !== null && (!Number.isSafeInteger(page.next_offset) || Number(page.next_offset) < 0))) {
    throw new Error('Invalid ready document page.');
  }
  const items = page.items.map((value: unknown): ReadyDocumentOption => {
    if (!value || typeof value !== 'object') throw new Error('Invalid ready document.');
    const item = value as Record<string, unknown>;
    if (typeof item.upload_id !== 'string' || !/^[a-f0-9]{32}$/.test(item.upload_id)
      || typeof item.ingestion_job_id !== 'string' || !item.ingestion_job_id.trim()
      || item.ingestion_job_id !== item.ingestion_job_id.trim() || item.ingestion_job_id.length > 128
      || !Number.isSafeInteger(item.document_id) || Number(item.document_id) <= 0
      || typeof item.filename !== 'string' || !item.filename.trim() || item.filename.length > 255
      || /[\\/\x00-\x1f]/.test(item.filename)
      || typeof item.content_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(item.content_sha256)) {
      throw new Error('Unbound ready document.');
    }
    return { uploadId: item.upload_id, ingestionJobId: item.ingestion_job_id, documentId: Number(item.document_id),
      filename: item.filename, contentSha256: item.content_sha256 };
  });
  if (new Set(items.map(item => item.documentId)).size !== items.length
    || new Set(items.map(item => item.uploadId)).size !== items.length
    || new Set(items.map(item => item.ingestionJobId)).size !== items.length) {
    throw new Error('Duplicate ready document identity.');
  }
  return { items, nextOffset: page.next_offset as number | null };
}
