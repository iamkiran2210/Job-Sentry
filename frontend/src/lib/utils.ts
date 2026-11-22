import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export type WithElementRef<T, E extends HTMLElement = HTMLElement> = T & {
  ref?: E | null;
};

export type WithoutChild<T> = T extends { child?: unknown } ? Omit<T, 'child'> : T;
export type WithoutChildren<T> = T extends { children?: unknown } ? Omit<T, 'children'> : T;
export type WithoutChildrenOrChild<T> = WithoutChildren<WithoutChild<T>>;

export const humanize = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
export const fmtDate = (s?: string) => (s ? new Date(s).toLocaleDateString() : '—');
export const fmtDateTime = (s?: string) => {
  if (!s) return '—';
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
};
export const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
/** Candidate display name. The API returns `full_name`; older shapes used display_name / candidate_name / name. */
export function nameOf(o: unknown): string | null {
  if (!isObj(o)) return null;
  for (const k of ['full_name', 'display_name', 'candidate_name', 'name']) { const v = o[k]; if (typeof v === 'string' && v.trim()) return v.trim(); }
  return isObj(o.candidate) ? nameOf(o.candidate) : null;
}
export const num = (v: unknown): number | null => (v === null || v === undefined || v === '' ? null : Number.isFinite(Number(v)) ? Number(v) : null);
/** Display-only formatting. Scores come from the backend; Decimals may arrive as strings. Values <= 1 are shown as fractions of 100. */
import { SCORE_SCALE } from '$lib/config';
/** 0-100 value for a backend SCORE (scale set by PUBLIC_SCORE_SCALE, or 0..1 ratio), or null while pending. */
export const pctNum = (v: unknown, alreadyPercent = false): number | null => {
  const n = num(v);
  if (n === null) return null;
  const scaled = alreadyPercent ? n : SCORE_SCALE === 1 || (n > 0 && n <= 1) ? n * 100 : n;
  return Math.max(0, Math.min(100, scaled));
};
export const fmtScore = (v: unknown, alreadyPercent = false) => { const n = pctNum(v, alreadyPercent); return n === null ? 'Pending' : `${n.toFixed(1)}%`; };
/** Weights, completeness and contributions: ratios shown as percent (values <= 1 are treated as fractions). */
export const fmtRatio = (v: unknown) => { const n = num(v); return n === null ? '—' : `${(n <= 1 ? n * 100 : n).toFixed(1)}%`; };
export const shortId = (s: string) => s.slice(0, 8);
export const fmtBytes = (n: number) => (n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`);
/** Depth-first search for the first string value under any of `keys`. */
export function findStr(o: unknown, keys: string[]): string | null {
  if (Array.isArray(o)) { for (const x of o) { const r = findStr(x, keys); if (r) return r; } return null; }
  if (!isObj(o)) return null;
  for (const k of keys) if (typeof o[k] === 'string') return o[k] as string;
  for (const v of Object.values(o)) { const r = findStr(v, keys); if (r) return r; }
  return null;
}
