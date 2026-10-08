const tokenStorageKey = 'financial-rag.auth-token.v1';

export function getAccessToken(): string | null {
  try {
    return window.localStorage.getItem(tokenStorageKey);
  } catch {
    return null;
  }
}

export function setAccessToken(token: string): void {
  window.localStorage.setItem(tokenStorageKey, token);
}

export function clearAccessToken(): void {
  window.localStorage.removeItem(tokenStorageKey);
}
