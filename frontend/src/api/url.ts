export function normalizeApiBaseUrl(baseUrl: string): string {
  const normalized = baseUrl.trim();
  if (!normalized || normalized === '/') {
    return '';
  }
  return normalized.replace(/\/+$/, '');
}

export function buildApiUrl(baseUrl: string, path: string): string {
  const normalizedBaseUrl = normalizeApiBaseUrl(baseUrl);
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${normalizedBaseUrl}${normalizedPath}`;
}
