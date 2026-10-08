/** One notification per observed state, never a replacement for server reads. */
export function createIngestionInvalidator(refresh: () => void | Promise<void>) {
  let lastKey: string | null = null;
  return (uploadId: string, state: string): boolean => {
    const key = `${uploadId}:${state}`;
    if (key === lastKey) return false;
    lastKey = key;
    // Parent owns refresh errors. They must not relabel a valid upload as failed.
    void Promise.resolve().then(refresh).catch(() => {});
    return true;
  };
}
