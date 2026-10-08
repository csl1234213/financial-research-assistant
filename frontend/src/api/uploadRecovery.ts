/** Browser data is only a scoped resume hint, never upload or READY authority. */
export function uploadRecoveryKey(tenantId: number, userId: number): string {
  if (![tenantId, userId].every((id) => Number.isSafeInteger(id) && id > 0)) {
    throw new Error('Authenticated recovery owner required');
  }
  return `financial-rag.upload-recovery.v1:${tenantId}:${userId}`;
}

export function readUploadRecovery(storage: Pick<Storage, 'getItem'>, key: string): string | null {
  try {
    const value = storage.getItem(key);
    return value && /^[a-f0-9]{32}$/.test(value) ? value : null;
  } catch { return null; }
}

export function rememberUploadRecovery(storage: Pick<Storage, 'setItem'>, key: string, uploadId: string): boolean {
  if (!/^[a-f0-9]{32}$/.test(uploadId)) throw new Error('Invalid recovery identity');
  try { storage.setItem(key, uploadId); return true; } catch { return false; }
}
