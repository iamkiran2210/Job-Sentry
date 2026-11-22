import { api, ApiError } from './api-client';

export const TABS = ['overview', 'jobs', 'candidates', 'skills', 'pipeline'] as const;
export type Tab = (typeof TABS)[number];
export interface AnalyticsQuery { from?: string; to?: string; jobId?: string; interval?: 'day' | 'week' | 'month'; page?: number; pageSize?: number; sort?: string; limit?: number }
// Free-form objects in OpenAPI, so keep them loose and render what is returned.
export const getOverview = () => api<Record<string, unknown>>('/analytics/overview');
function query(tab: Tab, q: AnalyticsQuery, sort: string | null) {
  const p = new URLSearchParams();
  if (q.from) p.set('date_from', q.from);
  if (q.to) p.set('date_to', q.to);
  if (q.jobId && tab !== 'jobs') p.set('job_id', q.jobId);
  if (tab === 'overview' && q.interval) p.set('interval', q.interval);
  if (tab === 'jobs') { p.set('page', String(q.page ?? 1)); p.set('page_size', String(q.pageSize ?? 20)); if (sort) p.set('sort', sort); }
  if (tab === 'skills' && q.limit) p.set('limit', String(q.limit));
  const qs = p.toString();
  return api<unknown>(`/analytics/${tab}${qs ? `?${qs}` : ''}`);
}

// The backend accepts these fields but its direction syntax is not documented, so try the usual ones and remember what works.
const SORT_FORMATS: ((f: string, d: string) => string | null)[] = [(f, d) => `${f}:${d}`, (f, d) => (d === 'desc' ? `-${f}` : f), (f) => f, () => null];
let sortFormat = 0;

/** Sorts the first list of rows found in the response (used when the server cannot apply the direction). */
function sortRows(data: unknown, field: string, dir: string): unknown {
  const sortList = (rows: Record<string, unknown>[]) => [...rows].sort((a, b) => {
    const x = a[field], y = b[field]; const r = typeof x === 'number' && typeof y === 'number' ? x - y : String(x ?? '').localeCompare(String(y ?? ''));
    return dir === 'desc' ? -r : r;
  });
  if (Array.isArray(data)) return sortList(data as Record<string, unknown>[]);
  if (data && typeof data === 'object') {
    const o = data as Record<string, unknown>;
    for (const [k, v] of Object.entries(o)) if (Array.isArray(v) && v.every((r) => r && typeof r === 'object')) return { ...o, [k]: sortList(v as Record<string, unknown>[]) };
  }
  return data;
}

export async function getAnalytics(tab: Tab, q: AnalyticsQuery = {}) {
  if (tab !== 'jobs') return query(tab, q, null);
  const [field, dir = 'desc'] = (q.sort ?? 'created_at:desc').split(':');
  let last: unknown;
  for (let k = sortFormat; k < SORT_FORMATS.length; k++) {
    try {
      const data = await query(tab, q, SORT_FORMATS[k](field, dir));
      sortFormat = k;
      return k >= 2 ? sortRows(data, field, dir) : data;
    } catch (e) {
      last = e;
      if (!(e instanceof ApiError && [400, 422].includes(e.status) && /sort/i.test(e.message))) throw e;
    }
  }
  throw last;
}
