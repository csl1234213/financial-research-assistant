import { getJson, postJson } from './client';
import { parseTusSession, parseIngestionProgress } from './resumableUploadContract';
import { parseReadyDocumentPage } from './readyDocumentContract';

const endpoint = '/v1/upload-sessions';

export async function listReadyDocuments(offset = 0, signal?: AbortSignal) {
  if (!Number.isSafeInteger(offset) || offset < 0) throw new Error('Invalid report list page.');
  const page = parseReadyDocumentPage(await getJson(`${endpoint}/ready-documents?offset=${offset}`, { signal }));
  if (page.nextOffset !== null && page.nextOffset <= offset) throw new Error('Invalid report list continuation.');
  return page;
}

export async function readIngestionProgress(uploadId: string, signal?: AbortSignal) {
  return parseIngestionProgress(await getJson(`${sessionPath(uploadId)}/ingestion`, { signal }), uploadId);
}

function sessionPath(uploadId: string): string {
  if (!/^[a-f0-9]{32}$/.test(uploadId)) throw new Error('Invalid upload identity');
  return `${endpoint}/${uploadId}`;
}

/** Opt-in API; no legacy upload replacement until browser acceptance passes. */
export async function createTusSession(filename: string, size: number, sha256: string) {
  return parseTusSession(await postJson(endpoint, { filename, mime_type: 'application/pdf',
    expected_size: size, expected_sha256: sha256 }));
}

export async function readTusSession(uploadId: string) {
  const value = parseTusSession(await getJson(sessionPath(uploadId)));
  if (value.uploadId !== uploadId) throw new Error('Upload session identity mismatch');
  return value;
}

/** Transport completion is followed by server checksum verification, not READY. */
export async function verifyTusSession(uploadId: string) {
  const value = parseTusSession(await postJson(`${sessionPath(uploadId)}/verify`, {}));
  if (value.uploadId !== uploadId || !['VERIFIED', 'FINALIZED'].includes(value.status)) {
    throw new Error('Upload verification did not complete');
  }
  return value;
}

export async function finalizeTusSession(uploadId: string) {
  const value = parseTusSession(await postJson(`${sessionPath(uploadId)}/finalize`, {}));
  if (value.uploadId !== uploadId || value.status !== 'FINALIZED') throw new Error('Upload finalization did not complete');
  return value;
}
