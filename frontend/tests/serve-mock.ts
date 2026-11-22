import { startMock } from './mock-server';
const m = startMock();
m.db.company = { id: 'c1', name: 'ACME' };
m.db.jobs.push({ id: 'job-1', title: 'Rust Developer', description: 'Build fast services', status: 'active', employment_type: 'full_time', work_mode: 'hybrid', department: 'Engineering', location: 'Chennai', openings: 2 });
for (const [i, n] of ['Jane Doe', 'Sam Lee', 'Pat Kim'].entries()) m.db.apps.push({ application_id: `app-${i + 1}`, candidate_id: `cand-${i + 1}`, full_name: n, email: `p${i}@x.com`, created_at: '2026-11-01T00:00:00Z' });
m.db.ranked = true;
m.server.listen(8789, '127.0.0.1', () => console.log('mock on 8789'));
