export function getCitationTargetId(rank: number): string {
  return `evidence-${rank}`;
}

export function getCitationTargetHash(rank: number): string {
  return `#${getCitationTargetId(rank)}`;
}

export function getCitationRankFromHash(hash: string): number | null {
  const match = /^#(?:.*-)?evidence-(\d+)$/.exec(hash);
  if (!match) return null;

  const rank = Number.parseInt(match[1], 10);
  return Number.isSafeInteger(rank) && rank > 0 ? rank : null;
}

export function hashTargetsCitationRank(hash: string, rank: number): boolean {
  return getCitationRankFromHash(hash) === rank;
}
