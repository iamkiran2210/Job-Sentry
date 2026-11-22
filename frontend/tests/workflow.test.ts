import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { AddressInfo } from 'node:net';
import { startMock } from './mock-server';

const mock = startMock();
let S: Record<string, any> = {};
beforeAll(async () => {
  await new Promise<void>((r) => mock.server.listen(0, '127.0.0.1', r));
  process.env.MOCK_API = `http://127.0.0.1:${(mock.server.address() as AddressInfo).port}`;
  const [client, auth, jobs, resumes, apps, company, analytics, dir] = await Promise.all([
    import('$lib/services/api-client'), import('$lib/services/auth'), import('$lib/services/jobs'), import('$lib/services/resumes'),
    import('$lib/services/applications'), import('$lib/services/company'), import('$lib/services/analytics'), import('$lib/services/directory')
  ]);
  S = { client, auth, jobs, resumes, apps, company, analytics, dir };
});
afterAll(() => mock.server.close());

let jobId = '', appId = '';
describe('recruiter workflow against documented API shapes', () => {
  it('rejects wrong password with a clear error, then logs in', async () => {
    await expect(S.auth.login('a@x.com', 'bad')).rejects.toThrow(/Invalid credentials/);
    await S.auth.login('a@x.com', 'good');
    expect(S.client.tokens.hasSession()).toBe(true);
  });
  it('registers a user', async () => { expect((await S.auth.register('Alex', 'n@x.com', 'pw')).role).toBe('recruiter'); });
  it('loads user, profile and access; no company yet', async () => {
    expect((await S.auth.getMe()).email).toBe('a@x.com');
    expect((await S.auth.getProfile()).name).toBe('Alex');
    expect((await S.auth.getAccess()).company_access).toBeNull();
    await expect(S.company.getCompany()).rejects.toMatchObject({ status: 404 });
  });
  it('creates company, adds/lists members', async () => {
    await S.company.createCompany({ name: 'ACME' });
    expect((await S.company.getCompany()).name).toBe('ACME');
    expect((await S.company.listMembers()).length).toBe(1);
    expect((await S.auth.getAccess()).company_access).not.toBeNull();
  });
  it('shows field-level validation errors for a bad job', async () => {
    const { explain } = await import('$lib/errors');
    const e = await S.jobs.createJob({ title: '' }).catch((x: unknown) => x);
    expect(explain(e).title).toBe('Please check your input');
    expect(explain(e).detail).toContain('title');
  });
  it('creates a draft job, adds/edits requirements, AI suggestions are not auto-saved', async () => {
    const j = await S.jobs.createJob({ title: 'Rust Dev', description: 'd', employment_type: 'full_time', work_mode: 'onsite', openings: 2 });
    jobId = j.id; expect(j.status).toBe('draft');
    const r = await S.jobs.addRequirement(jobId, { category: 'skills', name: 'Rust', requirement_type: 'mandatory', importance: 'high', weight: 0, is_mandatory: true });
    await S.jobs.updateRequirement(jobId, r.id, { importance: 'low' });
    const sugg = await S.jobs.suggestRequirements(jobId, 'text');
    expect(sugg[0]).toMatchObject({ name: 'Systems Architecture', requirement_type: 'mandatory', is_mandatory: true, weight: 0, category: 'skills' });
    expect((await S.jobs.listRequirements(jobId)).length).toBe(1); // suggestion NOT saved until approved
  });
  it('publishes (partial response) and re-fetches full job; server-side status filter works', async () => {
    await S.jobs.jobAction(jobId, 'publish');
    expect((await S.jobs.getJob(jobId)).title).toBe('Rust Dev');
    expect((await S.jobs.listJobs('active')).length).toBe(1);
    expect((await S.jobs.listJobs('paused')).length).toBe(0);
  });
  it('uploads with progress, polls to completed, reads extracted data', async () => {
    const f = new File([new Uint8Array(2048)], 'cv.pdf', { type: 'application/pdf' });
    const seen: number[] = [];
    const res = await S.resumes.uploadResume(jobId, f, (p: number) => seen.push(p));
    const rid = S.resumes.resumeIdFrom(res);
    expect(rid).toMatch(/^res-/);
    expect((await S.resumes.resumeStatus(rid)).status).toBe('processing');
    const s2 = await S.resumes.resumeStatus(rid);
    expect(s2.status).toBe('completed'); expect(s2.progress_pct).toBe(100);
    expect((await S.resumes.getResume(rid)).parsed_skills).toContain('Rust');
    await S.resumes.uploadResume(jobId, new File([new Uint8Array(10)], 'b.pdf', { type: 'application/pdf' }), () => {});
  });
  it('ranking is empty before running, and scored after (doc array shape normalised)', async () => {
    const before = await S.apps.getRanking(jobId, { page: 1, page_size: 25 });
    expect(before.items.length).toBe(0);
    const applicants = await S.apps.listApplicants(jobId);
    expect(applicants.length).toBe(2); // so the UI can say "2 of 2 not scored"
    await S.apps.runRanking(jobId);
    const after = await S.apps.getRanking(jobId, { page: 1, page_size: 25, minPercent: 50 });
    expect(after.items.map((i: any) => i.rank)).toEqual([1, 2]);
    expect(after.items[0].candidate_name).toBe('Jane Doe');
    expect(mock.db.calls.some((c) => c.includes('min_score=50'))).toBe(true); // scale 100
    appId = after.items[0].application_id;
    expect((await S.apps.getRankingHistory(jobId)).items?.length ?? 1).toBeGreaterThan(0);
  });
  it('analysis, verification, status change with request id, history, compare', async () => {
    const a = await S.apps.getAnalysis(appId); expect(a.eligibility).toBe('eligible');
    expect((await S.apps.verifyApplication(appId)).overall_status).toBe('passed');
    const r: any = await S.apps.setStatus(appId, 'shortlisted', 'good');
    expect(r.status).toBe('shortlisted'); expect(r._reqId).toMatch(/^[0-9a-f-]{36}$/);
    expect((await S.apps.getStatusHistory(appId))[0].to_status).toBe('shortlisted');
    const c = await S.apps.compare(jobId, ['app-1', 'app-2']); expect((c.comparison as unknown[]).length).toBe(2);
  });
  it('candidate directory aggregates applicants without any score', async () => {
    const d = await S.dir.buildDirectory();
    expect(d.length).toBe(2); expect(d[0]).not.toHaveProperty('score'); expect(d.map((x: any) => x.name).sort()).toEqual(['Jane Doe', 'Sam Lee']);
  });
  it('all analytics tabs return and are recognised by the chart detector', async () => {
    for (const t of ['overview', 'jobs', 'candidates', 'skills', 'pipeline']) expect(await S.analytics.getAnalytics(t, { page: 1, sort: 'applications:desc', limit: 10 })).toBeTruthy();
    expect(mock.db.calls.some((c) => c.includes('/analytics/jobs?') && c.includes('sort=applications%3Adesc'))).toBe(true);
  });
  it('analytics jobs finds a sort format the backend accepts and keeps the requested order', async () => {
    const rows: any[] = await S.analytics.getAnalytics('jobs', { sort: 'applications:desc' });
    expect(rows.map((r) => r.applications)).toEqual([120, 64, 31]);
    const asc: any[] = await S.analytics.getAnalytics('jobs', { sort: 'avg_score:asc' });
    expect(asc.map((r) => r.avg_score)).toEqual([66.5, 71.2, 74.9]);
    expect(mock.db.calls.some((c) => c.includes('sort=-applications'))).toBe(true);
    const bad: any[] = await S.analytics.getAnalytics('jobs', { sort: 'applications_count:desc' }); // unknown field: falls back to no sort
    expect(Array.isArray(bad)).toBe(true);
  });
  it('AI suggestions parse every plausible response shape', async () => {
    const j = await import('$lib/services/jobs');
    expect(j.parseSuggestions({ suggestions: [{ name: 'A', is_mandatory: true }] })[0]).toMatchObject({ name: 'A', is_mandatory: true, weight: 0 });
    expect(j.parseSuggestions({ requirements: [{ requirement: 'B', weight: 0.3 }] })[0]).toMatchObject({ name: 'B', requirement_type: 'preferred', weight: 0.3 });
    expect(j.parseSuggestions(['C', 'D']).map((x: any) => x.name)).toEqual(['C', 'D']);
    const v = j.parseSuggestions({ extracted: { mandatory: ['Rust'], preferred: [{ skill: 'Docker' }] } });
    expect(v.map((x: any) => [x.name, x.requirement_type])).toEqual([['Rust', 'mandatory'], ['Docker', 'preferred']]);
    expect(j.parseSuggestions({ nothing: 1 })).toEqual([]);
    const raw = await j.requestSuggestions(jobId, 'VARIANT text');
    expect(j.parseSuggestions(raw).length).toBe(3);
  });
  it('ranking history (bare array) and run options are sent as documented', async () => {
    expect((await S.apps.getRankingHistory(jobId)).length).toBe(1);
    await S.apps.runRanking(jobId, { force: true, eligibility: 'eligible', minPercent: 60, limit: 20 });
    expect(mock.db.lastRank).toMatchObject({ force_rescore: true, eligibility: 'eligible', min_score: 60, limit: 20, offset: 0 });
  });
  it('refreshes an expired access token transparently and retries', async () => {
    mock.expireAccess();
    const jobs = await S.jobs.listJobs();
    expect(jobs.length).toBe(1);
    expect(mock.db.calls.some((c) => c === 'POST /auth/refresh')).toBe(true);
  });
  it('google: existing-user route fails, sign-up route succeeds (fallback)', async () => {
    S.client.tokens.clear();
    await S.auth.loginWithGoogle('fake-id-token');
    expect(mock.db.calls.filter((c) => c.endsWith('/auth/google') || c.endsWith('/auth/sign/google'))).toEqual(['POST /auth/google', 'POST /auth/sign/google']);
  });
  it('weights: basis points, even split and the must-total-100% rule', async () => {
    const { weightStatus, evenBps, toBps, fmtPct } = await import('$lib/weights');
    expect(evenBps(3)).toEqual([3334, 3333, 3333]); expect(evenBps(3).reduce((a: number, b: number) => a + b)).toBe(10000);
    expect(toBps(0.1) + toBps(0.2)).toBe(3000); expect(fmtPct(3333)).toBe('33.33%'); expect(fmtPct(5000)).toBe('50%');
    expect(weightStatus([{ is_mandatory: true, weight: 0 }]).ok).toBe(true); // nothing preferred: no weights needed
    expect(weightStatus([{ is_mandatory: false, weight: 0.6 }, { is_mandatory: false, weight: 0.3 }]).ok).toBe(false);
    expect(weightStatus([{ is_mandatory: false, weight: 0.6 }, { is_mandatory: false, weight: 0.4 }, { is_mandatory: true, weight: 0 }]).ok).toBe(true);
    expect(weightStatus([{ is_mandatory: false, weight: 0.1 }, { is_mandatory: false, weight: 0.2 }, { is_mandatory: false, weight: 0.7 }]).ok).toBe(true); // float drift handled
  });
  it('health endpoints', async () => { expect(await S.client.health('/health')).toBe(true); expect(await S.client.health('/ready')).toBe(true); });
  it('error messages never contain ids or request paths', async () => {
    const e = await S.jobs.getJob('does-not-exist').catch((x: unknown) => x);
    expect(e).toBeInstanceOf(S.client.ApiError); expect((e as any).status).toBe(404);
    expect(String((e as Error).message)).not.toMatch(/→|\/api\/|id=/);
    const { explain } = await import('$lib/errors');
    expect(JSON.stringify(explain(e))).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}|→|id=/);
  });
  it('network failure is explained in plain language', async () => {
    const { explain } = await import('$lib/errors');
    expect(explain(new S.client.ApiError(0, 'x')).title).toBe('Cannot reach the server');
    expect(explain(new S.client.ApiError(413, 'x')).title).toBe('File too large');
  });
});
