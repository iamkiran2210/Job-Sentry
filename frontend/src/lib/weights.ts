// Preferred requirement weights are fractions that must total exactly 1.0 before a job can be published.
// We work in basis points (1/10000) so decimal arithmetic never drifts.
export const toBps = (w: unknown): number => Math.round(Number(w ?? 0) * 10000) || 0;
export const fmtPct = (bps: number) => `${(bps / 100).toFixed(bps % 100 === 0 ? 0 : 2)}%`;
export function weightStatus(items: { is_mandatory: boolean; weight?: number | null }[]) {
  const pref = items.filter((i) => !i.is_mandatory);
  const totalBps = pref.reduce((a, i) => a + toBps(i.weight), 0);
  return { preferred: pref.length, totalBps, ok: pref.length === 0 || totalBps === 10000 };
}
/** Splits 100% across n items; the remainder goes to the first so the total is exactly 10000. */
export function evenBps(n: number): number[] {
  if (n <= 0) return [];
  const base = Math.floor(10000 / n);
  return Array.from({ length: n }, (_, i) => (i === 0 ? base + (10000 - base * n) : base));
}

/** Scales an array of preferred weights proportionally so their basis points total exactly 10000 (100%). */
export function normalizeBps(weights: (number | null | undefined)[]): number[] {
  const n = weights.length;
  if (n <= 0) return [];
  const raw = weights.map((w) => Math.max(0, toBps(w)));
  const total = raw.reduce((a, b) => a + b, 0);
  if (total === 10000) return raw;
  if (total <= 0) return evenBps(n);
  const scaled = raw.map((b) => Math.max(1, Math.round((b / total) * 10000)));
  const sum = scaled.reduce((a, b) => a + b, 0);
  scaled[0] += 10000 - sum;
  return scaled;
}

/** Returns a shallow copy of requirements where mandatory weights are 0 and preferred weights sum to 1.0 (10000 bps). */
export function normalizeRequirements<
  T extends { is_mandatory: boolean; requirement_type?: 'mandatory' | 'preferred'; weight?: number }
>(items: T[]): T[] {
  const prefIndices = items.map((r, i) => (r.is_mandatory ? -1 : i)).filter((i) => i >= 0);
  const bps = normalizeBps(prefIndices.map((i) => items[i].weight));
  const bpsByIdx = new Map(prefIndices.map((idx, k) => [idx, bps[k]]));
  return items.map((r, idx) =>
    r.is_mandatory
      ? { ...r, requirement_type: 'mandatory' as const, weight: 0 }
      : { ...r, requirement_type: 'preferred' as const, weight: (bpsByIdx.get(idx) ?? 0) / 10000 }
  );
}
