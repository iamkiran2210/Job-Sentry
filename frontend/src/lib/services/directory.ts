import { listJobs } from './jobs';
import { listApplicants, applicantView } from './applications';
import { pageTitleStore } from '$lib/stores/page-title.svelte';
import { nameOf } from '$lib/utils';

export interface DirectoryEntry { key: string; candidateId: string | null; name: string | null; email: string | null; applications: number; jobs: string[]; lastApplied: string | null }

const DIR_TTL = 25_000;
let dirCache: { data: DirectoryEntry[]; ts: number } | null = null;
let dirInflight: Promise<DirectoryEntry[]> | null = null;

export function invalidateDirectoryCache() {
  dirCache = null;
  dirInflight = null;
}

/**
 * The backend has no "list candidates" endpoint, so the directory is assembled from each job's applicants.
 * Deduplicated by candidate id (or email). Contains no score by design.
 */
export async function buildDirectory(force = false): Promise<DirectoryEntry[]> {
  if (!force && dirCache && Date.now() - dirCache.ts < DIR_TTL) return dirCache.data;
  if (!force && dirInflight) return dirInflight;
  const p = (async () => {
    try {
      const jobs = await listJobs();
      const results = await Promise.allSettled(jobs.map((j) => listApplicants(j.id).then((l) => ({ j, l }))));
      const map = new Map<string, DirectoryEntry>();
      for (const r of results) {
        if (r.status !== 'fulfilled') continue;
        for (const a of r.value.l) {
          const v = applicantView(a);
          const key = v.candidateId ?? v.email ?? v.applicationId;
          if (!key) continue;
          const e = map.get(key) ?? { key, candidateId: v.candidateId, name: v.name, email: v.email, applications: 0, jobs: [], lastApplied: null };
          e.applications++;
          if (v.candidateId && v.name) pageTitleStore.setTitle(v.candidateId, v.name);
          if (!e.jobs.includes(r.value.j.title)) e.jobs.push(r.value.j.title);
          if (v.createdAt && (!e.lastApplied || v.createdAt > e.lastApplied)) e.lastApplied = v.createdAt;
          map.set(key, e);
        }
      }
      const out = [...map.values()].sort((a, b) => (b.lastApplied ?? '').localeCompare(a.lastApplied ?? ''));
      dirCache = { data: out, ts: Date.now() };
      return out;
    } finally {
      dirInflight = null;
    }
  })();
  dirInflight = p;
  return p;
}

import { api } from './api-client';

export interface CandidateUpdatePayload {
  full_name?: string | null;
  email?: string | null;
  phone?: string | null;
  location?: string | null;
  summary?: string | null;
  linkedin_url?: string | null;
  github_url?: string | null;
  portfolio_url?: string | null;
  skills?: string[] | null;
}

export const getCandidate = async (id: string) => {
  const c = await api<Record<string, unknown>>(`/candidates/${id}`);
  const name = nameOf(c);
  if (name) pageTitleStore.setTitle(id, name);
  return c;
};

export const updateCandidate = async (id: string, payload: CandidateUpdatePayload) => {
  const c = await api<Record<string, unknown>>(`/candidates/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  });
  invalidateDirectoryCache();
  const name = nameOf(c);
  if (name) pageTitleStore.setTitle(id, name);
  return c;
};

export const deleteCandidate = async (id: string) => {
  const res = await api<Record<string, unknown>>(`/candidates/${id}`, { method: 'DELETE' });
  invalidateDirectoryCache();
  return res;
};

/** Data Explorer only: permanently purges candidate, applications, resumes, scores, verifications & history. */
export const cleanDeleteCandidate = async (id: string) => {
  const res = await api<Record<string, unknown>>(`/candidates/${id}?purge=true`, { method: 'DELETE' });
  invalidateDirectoryCache();
  return res;
};

/** Data Explorer only: permanently purges ALL candidates, applications, resumes, scores, verifications & history. */
export const deleteAllCandidates = async () => {
  const res = await api<Record<string, unknown>>('/candidates', { method: 'DELETE' });
  invalidateDirectoryCache();
  return res;
};
