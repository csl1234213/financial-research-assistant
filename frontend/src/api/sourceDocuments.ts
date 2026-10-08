import { getAuthorizationHeaders, toApiUrl } from './client';

/** Bearer stays in headers. Only validated source identity enters the URL. */
export async function fetchSourceDocument(documentId: string | number, version: string, page: number): Promise<Blob> {
  if (!/^[1-9][0-9]*$/.test(String(documentId)) || !/^[0-9a-f]{64}$/.test(version)
      || !Number.isSafeInteger(page) || page < 1) throw new Error('Invalid source identity.');
  const response = await fetch(toApiUrl(`/v1/documents/${documentId}/source?version=${version}&page=${page}`), {
    headers: getAuthorizationHeaders(),
  });
  if (!response.ok) throw new Error(`Source unavailable (${response.status}).`);
  if (!response.headers.get('Content-Type')?.startsWith('application/pdf')
      || response.headers.get('X-Source-SHA256') !== version) throw new Error('Source identity mismatch.');
  const pageCount = Number(response.headers.get('X-PDF-Page-Count'));
  if (!Number.isSafeInteger(pageCount) || page > pageCount) throw new Error('Invalid source page.');
  return response.blob();
}
