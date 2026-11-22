import { api } from './api-client';
import { invalidateDirectoryCache } from './directory';
import { toList } from './jobs';
import { SCORE_SCALE } from '$lib/config';
import { nameOf } from '$lib/utils';
import { pageTitleStore } from '$lib/stores/page-title.svelte';
import type { RankedItem, RankingPage, Analysis, AppStatus } from '$lib/types/application';

export interface RankingQuery {
  page: number;
  page_size: number;
  status?: string;
  eligibility?: string;
  verification_status?: string;
  decision_agent?: string;
  decision?: string;
  run_id?: string;
  minPercent?: number;
  maxPercent?: number;
}
export function getRanking(jobId: string, q: RankingQuery) {
  const p = new URLSearchParams({ page: String(q.page), page_size: String(q.page_size) });
  if (q.status) p.set('status', q.status);
  if (q.eligibility) p.set('eligibility', q.eligibility);
  if (q.verification_status) p.set('verification_status', q.verification_status);
  if (q.decision_agent) p.set('decision_agent', q.decision_agent);
  if (q.decision) p.set('decision', q.decision);
  // Inputs are percents (0-100); convert to the backend scale.
  if (q.minPercent !== undefined) p.set('min_score', String((q.minPercent * SCORE_SCALE) / 100));
  if (q.maxPercent !== undefined) p.set('max_score', String((q.maxPercent * SCORE_SCALE) / 100));
  if (q.run_id) p.set('run_id', q.run_id); // keeps paging inside one immutable ranking run
  return api<unknown>(`/jobs/${jobId}/ranking?${p}`).then(normaliseRanking);
}
/** Runs the backend's deterministic ranking. It never changes application statuses. */
export interface RunOptions {
  force?: boolean;
  forceVerify?: boolean;
  eligibility?: string;
  decisionAgent?: string;
  minAcceptThreshold?: number;
  autoApplyDecisions?: boolean;
  minPercent?: number;
  maxPercent?: number;
  limit?: number;
  applicationIds?: string[];
}
export const runRanking = (jobId: string, o: RunOptions = {}) => {
  const body: Record<string, unknown> = { offset: 0, limit: o.limit ?? 50, force_rescore: !!o.force };
  if (o.forceVerify) body.force_verify = true;
  if (o.eligibility) body.eligibility = o.eligibility;
  if (o.decisionAgent) body.decision_agent = o.decisionAgent;
  if (o.minAcceptThreshold !== undefined) body.min_accept_threshold = o.minAcceptThreshold;
  if (o.autoApplyDecisions) body.auto_apply_decisions = true;
  if (o.minPercent !== undefined) body.min_score = (o.minPercent * SCORE_SCALE) / 100;
  if (o.maxPercent !== undefined) body.max_score = (o.maxPercent * SCORE_SCALE) / 100;
  if (o.applicationIds && o.applicationIds.length > 0) body.application_ids = o.applicationIds;
  return api<Record<string, unknown>>(`/jobs/${jobId}/rank`, { method: 'POST', body: JSON.stringify(body) });
};
/** Loads every applicant, following page/page_size until a short page (capped to stay safe). */
export async function listApplicants(jobId: string, status?: string): Promise<Record<string, unknown>[]> {
  const SIZE = 100, all: Record<string, unknown>[] = [];
  for (let page = 1; page <= 20; page++) {
    const p = new URLSearchParams({ page: String(page), page_size: String(SIZE) });
    if (status) p.set('status', status);
    const rows = toList<Record<string, unknown>>(await api<unknown>(`/jobs/${jobId}/applicants?${p}`), ['items', 'applicants', 'applications']);
    all.push(...rows);
    if (rows.length < SIZE) break;
    if (page > 1 && rows[0] && all.slice(0, -rows.length).some((r) => JSON.stringify(r) === JSON.stringify(rows[0]))) break; // backend ignored paging
  }
  return all;
}
export const getStatusHistory = async (appId: string, page = 1) => toList<Record<string, unknown>>(await api<unknown>(`/applications/${appId}/status-history?page=${page}&page_size=20`), ['items', 'history']);
export const getApplication = (appId: string) => api<Record<string, unknown>>(`/applications/${appId}`);
export const getAnalysis = async (appId: string) => {
  const res = await api<Analysis>(`/applications/${appId}/analysis`);
  const candidateName = nameOf(res?.candidate) ?? nameOf(res?.candidate?.profile);
  if (candidateName) pageTitleStore.setTitle(appId, candidateName);
  if (res?.application?.job_id && res?.application?.job_title) {
    pageTitleStore.setTitle(res.application.job_id, res.application.job_title);
  }
  return res;
};
export const verifyApplication = (appId: string) => api<unknown>(`/applications/${appId}/verify`, { method: 'POST' });
export const notifyCandidate = (
  appId: string,
  payload: { outcome?: 'shortlisted' | 'rejected'; feedback?: string; include_score?: boolean } = {}
) =>
  api<{
    application_id: string;
    delivered: boolean;
    channel: string;
    reason: string;
    recipient?: string | null;
    subject: string;
    preview: string;
    sent_at: string;
  }>(`/applications/${appId}/notify`, { method: 'POST', body: JSON.stringify(payload) });
export const setStatus = (appId: string, status: AppStatus, reason?: string) =>
  api<unknown>(`/applications/${appId}/status`, { method: 'PATCH', headers: { 'X-Request-ID': crypto.randomUUID() }, body: JSON.stringify({ status, reason: reason || null }) });
export const deleteApplication = async (appId: string) => {
  const res = await api<Record<string, unknown>>(`/applications/${appId}`, { method: 'DELETE' });
  invalidateDirectoryCache();
  return res;
};
export const compare = (jobId: string, ids: string[]) => api<Record<string, unknown>>(`/jobs/${jobId}/compare`, { method: 'POST', body: JSON.stringify({ application_ids: ids }) });
export type { RankedItem };

/** Best-effort display fields from the untyped applicants list. */
export function applicantView(a: Record<string, unknown>) {
  const c = (a.candidate ?? {}) as Record<string, unknown>;
  const s = (v: unknown) => (typeof v === 'string' ? v : null);
  const applicationId = s(a.application_id) ?? s(a.id) ?? '';
  const name = nameOf(a);
  if (applicationId && name) pageTitleStore.setTitle(applicationId, name);
  return {
    applicationId,
    candidateId: s(a.candidate_id) ?? s(c.id),
    name,
    email: s(a.email) ?? s(c.email),
    createdAt: s(a.created_at) ?? s(a.application_created_at)
  };
}
export interface RankingRun { run_id: string; created_at?: string; executed_at?: string; count?: number; scoring_version?: string }
/** The reference returns a bare array; accept wrapped shapes too. */
export const getRankingHistory = async (jobId: string) => toList<RankingRun>(await api<unknown>(`/jobs/${jobId}/ranking/history?limit=20`), ['items', 'runs', 'history']);

/** The reference shows a bare array; the OpenAPI schema shows a paginated object. Accept both. */
function normaliseRanking(raw: unknown): RankingPage {
  const page = (Array.isArray(raw) ? { items: raw } : raw ?? {}) as Partial<RankingPage>;
  const items = ((page.items ?? []) as unknown as Record<string, unknown>[]).map((r, i) => {
    const candidate_name = nameOf(r) ?? undefined;
    const application_id = String(r.application_id ?? r.id ?? '');
    if (application_id && candidate_name) pageTitleStore.setTitle(application_id, candidate_name);
    return {
      ...r, candidate_name, application_id, rank: Number(r.rank ?? i + 1)
    };
  }) as unknown as RankedItem[];
  return {
    run_id: page.run_id ?? null,
    total_count: page.total_count ?? items.length,
    offset: page.offset ?? 0,
    limit: page.limit ?? items.length,
    items,
    scoring_version: page.scoring_version,
    algorithm_version: page.algorithm_version,
    decision_agent: page.decision_agent,
    available_decision_agents: page.available_decision_agents
  };
}
