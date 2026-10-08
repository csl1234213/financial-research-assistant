import type { Language } from '../../types/language';

export function formatGenerationDuration(
  durationMs: number | undefined,
  language: Language,
): string | null {
  if (durationMs === undefined || !Number.isFinite(durationMs) || durationMs < 0) {
    return null;
  }

  // Round before splitting so a minute boundary never reads as "60.0 s".
  const tenths = Math.round(durationMs / 100);
  const minutes = Math.floor(tenths / 600);
  const seconds = ((tenths % 600) / 10).toFixed(1);

  if (language === 'zh-CN') {
    return minutes > 0
      ? `用时 ${minutes} 分 ${seconds} 秒`
      : `用时 ${seconds} 秒`;
  }
  return minutes > 0
    ? `Generated in ${minutes} min ${seconds} s`
    : `Generated in ${seconds} s`;
}
