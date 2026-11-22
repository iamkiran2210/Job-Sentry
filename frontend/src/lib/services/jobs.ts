import { api } from './api-client';
import { REQ_CATEGORIES, IMPORTANCE, type Job, type JobInput, type Requirement, type RequirementInput } from '$lib/types/job';
import { pageTitleStore } from '$lib/stores/page-title.svelte';
import { invalidateDirectoryCache } from './directory';

/** List/suggestion bodies are untyped in OpenAPI, so accept an array or a wrapper object. */
export function toList<T>(x: unknown, keys = ['items', 'jobs', 'requirements', 'suggestions']): T[] {
  if (Array.isArray(x)) return x as T[];
  if (x && typeof x === 'object') for (const k of keys) { const v = (x as Record<string, unknown>)[k]; if (Array.isArray(v)) return v as T[]; }
  return [];
}

const jobsInflight = new Map<string, Promise<Job[]>>();

export function invalidateJobsCache() {
  jobsInflight.clear();
  invalidateDirectoryCache();
}

export const listJobs = async (status?: string) => {
  const key = status ?? '__all__';
  const existing = jobsInflight.get(key);
  if (existing) return existing;
  const p = (async () => {
    try {
      const jobs = toList<Job>(await api<unknown>(`/jobs${status ? `?status=${encodeURIComponent(status)}` : ''}`));
      for (const j of jobs) {
        if (j?.id && j?.title) pageTitleStore.setTitle(j.id, j.title);
      }
      return jobs;
    } finally {
      jobsInflight.delete(key);
    }
  })();
  jobsInflight.set(key, p);
  return p;
};

export const getJob = async (id: string) => {
  const job = await api<Job>(`/jobs/${id}`);
  if (job?.id && job?.title) pageTitleStore.setTitle(job.id, job.title);
  return job;
};

export const createJob = async (b: JobInput) => {
  const j = await api<Job>('/jobs', { method: 'POST', body: JSON.stringify(b) });
  invalidateJobsCache();
  return j;
};
// The action response is only { job_id, status }, so callers should re-fetch the job.
export const jobAction = async (id: string, a: 'publish' | 'pause' | 'close' | 'archive') => {
  const res = await api<{ job_id: string; status: string }>(`/jobs/${id}/${a}`, { method: 'POST' });
  invalidateJobsCache();
  return res;
};

export const listRequirements = async (id: string) => toList<Requirement>(await api<unknown>(`/jobs/${id}/requirements`));
export const addRequirement = (id: string, b: RequirementInput) => api<Requirement>(`/jobs/${id}/requirements`, { method: 'POST', body: JSON.stringify(b) });
export const deleteRequirement = (id: string, rid: string) => api<unknown>(`/jobs/${id}/requirements/${rid}`, { method: 'DELETE' });
/** Suggestions are NOT saved by the backend. The recruiter edits them and adds each one explicitly. */
type Hint = 'mandatory' | 'preferred' | undefined;
const NAME_KEYS = ['name', 'requirement', 'title', 'skill', 'text', 'value', 'label', 'keyword', 'description'];

/** Collects suggestion objects from any wrapper shape: arrays, {suggestions}, {requirements}, {mandatory:[], preferred:[]}, arrays of strings. */
function collect(x: unknown, hint: Hint, out: Record<string, unknown>[], depth = 0): void {
  if (depth > 4) return;
  if (Array.isArray(x)) {
    for (const it of x) {
      if (typeof it === 'string' && it.trim()) out.push({ name: it, __hint: hint });
      else if (it && typeof it === 'object' && !Array.isArray(it)) out.push({ ...(it as Record<string, unknown>), __hint: hint });
    }
    return;
  }
  if (x && typeof x === 'object')
    for (const [k, v] of Object.entries(x as Record<string, unknown>)) {
      if (typeof v !== 'object' || v === null) continue;
      collect(v, /mandatory|required|must/i.test(k) ? 'mandatory' : /preferred|nice|optional|bonus/i.test(k) ? 'preferred' : hint, out, depth + 1);
    }
}
function toSuggestion(r: Record<string, unknown>): RequirementInput {
  const hint = r.__hint as Hint;
  const mandatory = r.is_mandatory === true || r.requirement_type === 'mandatory' || r.importance_type === 'mandatory' || (r.is_mandatory === undefined && r.requirement_type === undefined && hint === 'mandatory');
  const rawW = Number(r.weight);
  const w = Number.isFinite(rawW) ? (rawW > 1 && rawW <= 100 ? rawW / 100 : rawW) : NaN;
  const key = NAME_KEYS.find((k) => typeof r[k] === 'string' && (r[k] as string).trim());
  return {
    category: (REQ_CATEGORIES as readonly string[]).includes(r.category as string) ? (r.category as RequirementInput['category']) : 'skills',
    name: key ? (r[key] as string).trim() : '',
    requirement_type: mandatory ? 'mandatory' : 'preferred',
    importance: (IMPORTANCE as readonly string[]).includes(r.importance as string) ? (r.importance as RequirementInput['importance']) : 'medium',
    weight: mandatory ? 0 : Number.isFinite(w) && w > 0 ? Math.min(1, Math.max(0, w)) : 0.1,
    is_mandatory: mandatory
  };
}
export const requestSuggestions = (id: string, description: string) =>
  api<unknown>(`/jobs/${id}/extract-requirements`, { method: 'POST', body: JSON.stringify({ description }) });
export function parseSuggestions(raw: unknown): RequirementInput[] {
  const out: Record<string, unknown>[] = []; collect(raw, undefined, out);
  const seen = new Set<string>();
  return out.map(toSuggestion).filter((s) => s.name && !seen.has(s.name.toLowerCase()) && seen.add(s.name.toLowerCase()));
}
/** Field names of the response (never values), for a helpful message when nothing could be read. */
export const shapeOf = (raw: unknown): string => (raw && typeof raw === 'object' ? Object.keys(raw as object).slice(0, 8).join(', ') || 'empty' : typeof raw);
export const suggestRequirements = async (id: string, description: string) => parseSuggestions(await requestSuggestions(id, description));
export const deleteJob = async (id: string) => {
  const res = await api<unknown>(`/jobs/${id}`, { method: 'DELETE' }); // drafts only
  invalidateJobsCache();
  return res;
};
/** Permanently deletes a job of any status along with all associated applications, resumes, scores, and KPI records. */
export const cleanDeleteJob = async (id: string) => {
  const res = await api<Record<string, unknown>>(`/jobs/${id}?purge=true`, { method: 'DELETE' });
  invalidateJobsCache();
  return res;
};
/** Data Explorer only: permanently deletes all company jobs and dependent records. */
export const deleteAllJobs = async () => {
  const res = await api<Record<string, unknown>>('/jobs', { method: 'DELETE' });
  invalidateJobsCache();
  return res;
};
export const updateRequirement = (id: string, rid: string, b: Partial<RequirementInput>) =>
  api<Requirement>(`/jobs/${id}/requirements/${rid}`, { method: 'PUT', body: JSON.stringify(b) });
export const listAccess = async (id: string) => toList<Record<string, unknown>>(await api<unknown>(`/jobs/${id}/access`), ['items', 'grants', 'accesses']);
export const grantAccess = (id: string, email: string, access_level: 'viewer' | 'editor') =>
  api<unknown>(`/jobs/${id}/access`, { method: 'POST', body: JSON.stringify({ email, access_level }) });
export const revokeAccess = (id: string, userId: string) => api<unknown>(`/jobs/${id}/access/${userId}`, { method: 'DELETE' });
export const updateJob = async (id: string, b: Partial<JobInput>) => {
  const j = await api<Job>(`/jobs/${id}`, { method: 'PUT', body: JSON.stringify(b) });
  invalidateJobsCache();
  return j;
};
