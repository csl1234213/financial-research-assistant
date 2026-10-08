import { getAuthorizationHeaders, getJson, postJson, toApiUrl } from './client';
import { parseFormalSession } from './resumableUploadContract';

export async function readFormalSession(uploadId: string) {
  if (!/^[a-f0-9]{32}$/.test(uploadId)) throw new Error('Invalid upload identity');
  const session = parseFormalSession(await getJson(`/v1/upload-sessions/${uploadId}`));
  if (session.uploadId !== uploadId) throw new Error('Upload identity mismatch');
  return session;
}

export async function uploadFormalPdf(file: File) {
  if (!file.name.toLowerCase().endsWith('.pdf') || file.size < 1 || file.size > 50 * 1024 * 1024) {
    throw new Error('PDF required (maximum 50 MiB)');
  }
  const bytes = await file.arrayBuffer();
  if (new TextDecoder().decode(bytes.slice(0, 5)) !== '%PDF-') throw new Error('PDF content required');
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  const sha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  const session = parseFormalSession(await postJson('/v1/upload-sessions', {
    filename: file.name, mime_type: 'application/pdf', expected_size: file.size, expected_sha256: sha256,
  }));
  if (session.expectedSha256 !== sha256 || session.expectedSize !== file.size) throw new Error('Upload binding mismatch');
  const data = new FormData();
  data.append('file', file);
  const response = await fetch(toApiUrl(`/v1/upload-sessions/${session.uploadId}/content`), {
    method: 'POST', headers: getAuthorizationHeaders(), body: data,
  });
  if (!response.ok) throw new Error(`Upload failed (${response.status})`);
  const finalized = parseFormalSession(await postJson(`/v1/upload-sessions/${session.uploadId}/finalize`, {}));
  if (finalized.uploadId !== session.uploadId || finalized.status !== 'FINALIZED'
      || finalized.expectedSha256 !== sha256) throw new Error('Finalization binding mismatch');
  return finalized;
}
