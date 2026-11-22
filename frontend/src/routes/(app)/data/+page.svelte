<script lang="ts">
  import { page } from '$app/state';
  import { listJobs, cleanDeleteJob, deleteAllJobs } from '$lib/services/jobs';
  import { buildDirectory, cleanDeleteCandidate, deleteAllCandidates, type DirectoryEntry } from '$lib/services/directory';
  import { getOverview, getAnalytics } from '$lib/services/analytics';
  import { listMembers, removeAllMembers } from '$lib/services/company';
  import { toast } from '$lib/stores/toast.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { toastError } from '$lib/errors';
  import { humanize, fmtDate, fmtScore, isObj } from '$lib/utils';
  import { kpiAccent } from '$lib/viz-colors';
  import type { Job } from '$lib/types/job';

  import * as Table from '$lib/components/ui/table';
  import * as Tabs from '$lib/components/ui/tabs';
  import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '$lib/components/ui/card';
  import { Input } from '$lib/components/ui/input';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import {
    Database,
    Search,
    Briefcase,
    Users,
    ChartColumn,
    Building2,
    RefreshCw,
    ExternalLink,
    Trash2,
    Loader2
  } from '@lucide/svelte';

  let currentTab = $state(page.url.searchParams.get('tab') || 'jobs');
  let q = $state('');
  let loading = $state(true);
  let purgingId = $state<string | null>(null);
  let purgingJobId = $state<string | null>(null);
  let deletingAllSection = $state<'jobs' | 'candidates' | 'members' | null>(null);

  let jobs = $state<Job[]>([]);
  let candidates = $state<DirectoryEntry[]>([]);
  let kpis = $state<{ metric: string; value: string }[]>([]);
  let members = $state<Record<string, unknown>[]>([]);

  let pg = $state(1);
  const SIZE = 20;

  async function loadData() {
    loading = true;
    try {
      const [jList, cList, ov, mList] = await Promise.allSettled([
        listJobs(),
        buildDirectory(),
        getOverview(),
        listMembers()
      ]);

      if (jList.status === 'fulfilled') jobs = jList.value;
      if (cList.status === 'fulfilled') candidates = cList.value;
      if (mList.status === 'fulfilled') members = mList.value;

      if (ov.status === 'fulfilled' && isObj(ov.value)) {
        const out: { metric: string; value: string }[] = [];
        const isExcluded = (k: string) => /average_hours?_applied_to_analyzed|hour.*appl/i.test(k);
        const fmtKpi = (key: string, val: number) =>
          /score/i.test(key) ? fmtScore(val) : Number.isInteger(val) ? String(val) : val.toFixed(1);
        for (const [k, v] of Object.entries(ov.value)) {
          if (isExcluded(k)) continue;
          if (typeof v === 'number') {
            out.push({ metric: humanize(k), value: fmtKpi(k, v) });
          } else if (isObj(v)) {
            for (const [k2, v2] of Object.entries(v)) {
              if (isExcluded(k2)) continue;
              if (typeof v2 === 'number') {
                out.push({ metric: `${humanize(k)} · ${humanize(k2)}`, value: fmtKpi(k2, v2) });
              } else if (isObj(v2)) {
                for (const [k3, v3] of Object.entries(v2)) {
                  if (isExcluded(k3)) continue;
                  if (typeof v3 === 'number') {
                    out.push({ metric: `${humanize(k2)} · ${humanize(k3)}`, value: fmtKpi(k3, v3) });
                  }
                }
              }
            }
          }
        }
        kpis = out;
      }
    } catch (e) {
      toastError(e, 'Could not load data explorer');
    } finally {
      loading = false;
    }
  }

  loadData();

  async function handleCleanDeleteJob(job: Job) {
    if (!job.id || purgingJobId) return;
    const ok = await confirmDialog({
      title: `Clean delete "${job.title}"?`,
      message:
        'This permanently deletes this job along with all its requirements, applications, uploaded resumes, scores, verification records, history, and KPI entries. This cannot be undone.',
      confirmLabel: 'Clean delete job',
      danger: true
    });
    if (!ok) return;
    purgingJobId = job.id;
    try {
      const res = await cleanDeleteJob(job.id);
      const an = Number(res?.applications_deleted ?? 0);
      const rn = Number(res?.resumes_deleted ?? 0);
      toast.success(
        'Job clean-deleted',
        `Removed "${job.title}" (${an} application(s), ${rn} resume(s), and KPI metrics).`
      );
      jobs = jobs.filter((j) => j.id !== job.id);
      await loadData();
    } catch (e) {
      toastError(e, 'Could not clean delete job');
    } finally {
      purgingJobId = null;
    }
  }

  async function handleCleanDelete(entry: DirectoryEntry) {
    if (!entry.candidateId || purgingId) return;
    const label = entry.name ?? entry.email ?? 'this candidate';
    const ok = await confirmDialog({
      title: `Clean delete ${label}?`,
      message:
        'This irreversibly erases the candidate and ALL associated data from the platform: all job applications, uploaded resume files, extracted profiles, scores, evidence, verification results, and ranking/status history. Nothing will remain.',
      confirmLabel: 'Clean delete everything',
      danger: true
    });
    if (!ok) return;
    purgingId = entry.candidateId;
    try {
      const res = await cleanDeleteCandidate(entry.candidateId);
      const appsN = Number(res?.applications_cleaned ?? 0);
      const resN = Number(res?.resumes_deleted ?? 0);
      const scoresN = Number(res?.scores_deleted ?? 0);
      toast.success(
        'Candidate clean-deleted',
        `Removed ${label} (${appsN} application(s), ${resN} resume(s), ${scoresN} score(s), and all history).`
      );
      candidates = candidates.filter((c) => c.candidateId !== entry.candidateId);
      await loadData();
    } catch (e) {
      toastError(e, 'Could not clean delete candidate');
    } finally {
      purgingId = null;
    }
  }

  const removableMemberCount = $derived(
    members.filter((m) => String(m.role ?? '').toLowerCase() !== 'admin').length
  );

  async function handleDeleteAllJobs() {
    if (deletingAllSection || jobs.length === 0) return;
    const ok = await confirmDialog({
      title: `Delete all ${jobs.length} job(s)?`,
      message:
        'This permanently deletes ALL jobs in your company along with their requirements, applications, uploaded resumes, scores, verification records, and ranking/status history. This cannot be undone.',
      confirmLabel: 'Delete all jobs',
      confirmText: 'DELETE',
      danger: true
    });
    if (!ok) return;
    deletingAllSection = 'jobs';
    try {
      const res = await deleteAllJobs();
      const jn = Number(res?.jobs_deleted ?? jobs.length);
      const an = Number(res?.applications_deleted ?? 0);
      const rn = Number(res?.resumes_deleted ?? 0);
      toast.success(
        'All jobs deleted',
        `Removed ${jn} job(s), ${an} application(s), and ${rn} resume(s).`
      );
      pg = 1;
      await loadData();
    } catch (e) {
      toastError(e, 'Could not delete all jobs');
    } finally {
      deletingAllSection = null;
    }
  }

  async function handleDeleteAllCandidates() {
    if (deletingAllSection || candidates.length === 0) return;
    const ok = await confirmDialog({
      title: `Clean delete all ${candidates.length} candidate(s)?`,
      message:
        'This irreversibly erases ALL candidates in your company along with every job application, uploaded resume file, extracted profile, score, evidence, verification record, and ranking/status history. This cannot be undone.',
      confirmLabel: 'Delete all candidates',
      confirmText: 'DELETE',
      danger: true
    });
    if (!ok) return;
    deletingAllSection = 'candidates';
    try {
      const res = await deleteAllCandidates();
      const cn = Number(res?.candidates_deleted ?? candidates.length);
      const an = Number(res?.applications_cleaned ?? 0);
      const rn = Number(res?.resumes_deleted ?? 0);
      toast.success(
        'All candidates clean-deleted',
        `Removed ${cn} candidate(s), ${an} application(s), and ${rn} resume(s).`
      );
      pg = 1;
      await loadData();
    } catch (e) {
      toastError(e, 'Could not delete all candidates');
    } finally {
      deletingAllSection = null;
    }
  }

  async function handleDeleteAllMembers() {
    if (deletingAllSection || removableMemberCount === 0) return;
    const ok = await confirmDialog({
      title: `Remove all ${removableMemberCount} team member(s)?`,
      message:
        'This revokes company and job access for all non-administrator team members. Company administrators (including your own admin account) will be preserved.',
      confirmLabel: 'Remove all team members',
      confirmText: 'DELETE',
      danger: true
    });
    if (!ok) return;
    deletingAllSection = 'members';
    try {
      const res = await removeAllMembers();
      const removed = Number(res?.members_removed ?? 0);
      const admins = Number(res?.admins_preserved ?? 0);
      toast.success(
        'Team members removed',
        `Removed ${removed} team member(s). Preserved ${admins} administrator(s).`
      );
      pg = 1;
      await loadData();
    } catch (e) {
      toastError(e, 'Could not remove team members');
    } finally {
      deletingAllSection = null;
    }
  }

  // Search filtering
  const filteredJobs = $derived(
    jobs.filter((j) =>
      `${j.title} ${j.department ?? ''} ${j.location ?? ''} ${j.status}`.toLowerCase().includes(q.toLowerCase())
    )
  );

  const filteredCandidates = $derived(
    candidates.filter((c) =>
      `${c.name ?? ''} ${c.email ?? ''} ${c.jobs.join(' ')}`.toLowerCase().includes(q.toLowerCase())
    )
  );

  const filteredKpis = $derived(
    kpis.filter((k) => k.metric.toLowerCase().includes(q.toLowerCase()))
  );

  const filteredMembers = $derived(
    members.filter((m) =>
      `${String(m.name ?? '')} ${String(m.email ?? '')} ${String(m.role ?? '')}`.toLowerCase().includes(q.toLowerCase())
    )
  );

  const pages = $derived(
    Math.max(
      1,
      Math.ceil(
        (currentTab === 'jobs'
          ? filteredJobs.length
          : currentTab === 'candidates'
            ? filteredCandidates.length
            : currentTab === 'kpis'
              ? filteredKpis.length
              : filteredMembers.length) / SIZE
      )
    )
  );

  const NP = 'Not provided';
</script>

<div class="space-y-6">
  <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
    <div class="space-y-1">
      <div class="flex items-center gap-2">
        <Database class="size-6 text-primary" />
        <h1 class="text-3xl font-bold tracking-tight text-foreground">Data Explorer</h1>
      </div>
      <p class="text-sm text-muted-foreground">
        Clean, structured tabular view of all platform data formatted for review and export.
      </p>
    </div>

    <Button variant="outline" size="sm" onclick={loadData} disabled={loading}>
      <RefreshCw class="mr-1.5 size-3.5 {loading ? 'animate-spin' : ''}" /> Refresh
    </Button>
  </div>

  <Tabs.Root bind:value={currentTab} class="space-y-5">
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
      <Tabs.List class="grid grid-cols-2 sm:grid-cols-4 w-full sm:w-auto h-auto">
        <Tabs.Trigger value="jobs" onclick={() => { pg = 1; q = ''; }}>
          Jobs ({jobs.length})
        </Tabs.Trigger>
        <Tabs.Trigger value="candidates" onclick={() => { pg = 1; q = ''; }}>
          Candidates ({candidates.length})
        </Tabs.Trigger>
        <Tabs.Trigger value="kpis" onclick={() => { pg = 1; q = ''; }}>
          KPIs ({kpis.length})
        </Tabs.Trigger>
        <Tabs.Trigger value="members" onclick={() => { pg = 1; q = ''; }}>
          Team ({members.length})
        </Tabs.Trigger>
      </Tabs.List>

      <div class="relative w-full sm:w-64">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input
          type="search"
          placeholder="Filter data..."
          bind:value={q}
          oninput={() => (pg = 1)}
          class="pl-9 h-9"
        />
      </div>
    </div>

    {#if loading}
      <Skeleton rows={6} height="h-16" />
    {:else}
      <!-- JOBS TAB -->
      <Tabs.Content value="jobs" class="space-y-3">
        <div class="flex items-center justify-between gap-2">
          <p class="text-xs text-muted-foreground">
            Showing {filteredJobs.length} of {jobs.length} job(s)
          </p>
          <Button
            variant="destructive"
            size="sm"
            disabled={jobs.length === 0 || deletingAllSection !== null}
            onclick={handleDeleteAllJobs}
            class="h-8 text-xs"
          >
            {#if deletingAllSection === 'jobs'}
              <Loader2 class="mr-1.5 size-3.5 animate-spin" />
              Deleting all jobs…
            {:else}
              <Trash2 class="mr-1.5 size-3.5" />
              Delete all jobs ({jobs.length})
            {/if}
          </Button>
        </div>
        <Card class="border-0 bg-card shadow-sm overflow-hidden">
          <div class="overflow-x-auto">
            <Table.Root>
              <Table.Header>
                <Table.Row>
                  <Table.Head class="text-left font-semibold text-foreground">Job Title</Table.Head>
                  <Table.Head class="text-left font-semibold text-foreground">Department</Table.Head>
                  <Table.Head class="text-left font-semibold text-foreground">Location</Table.Head>
                  <Table.Head class="text-center font-semibold text-foreground">Mode</Table.Head>
                  <Table.Head class="text-center font-semibold text-foreground">Status</Table.Head>
                  <Table.Head class="text-right font-semibold text-foreground">Action</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#if filteredJobs.length === 0}
                  <Table.Row>
                    <Table.Cell colspan={6} class="text-center py-8 text-muted-foreground">
                      No jobs match the current filter.
                    </Table.Cell>
                  </Table.Row>
                {:else}
                  {#each filteredJobs.slice((pg - 1) * SIZE, pg * SIZE) as j (j.id)}
                    <Table.Row class="hover:bg-muted/20">
                      <Table.Cell class="text-left font-medium text-foreground">{j.title}</Table.Cell>
                      <Table.Cell class="text-left text-muted-foreground">{j.department ?? NP}</Table.Cell>
                      <Table.Cell class="text-left text-muted-foreground">{j.location ?? NP}</Table.Cell>
                      <Table.Cell class="text-center capitalize text-muted-foreground">{humanize(j.work_mode)}</Table.Cell>
                      <Table.Cell class="text-center"><StatusBadge status={j.status} /></Table.Cell>
                      <Table.Cell class="text-right">
                        <div class="inline-flex items-center justify-end gap-1.5">
                          <Button variant="ghost" size="sm" href={`/jobs/${j.id}`} class="h-7 px-2">
                            View <ExternalLink class="ml-1 size-3" />
                          </Button>
                          <Button
                            variant="destructive"
                            size="sm"
                            disabled={purgingJobId !== null || deletingAllSection !== null}
                            onclick={() => handleCleanDeleteJob(j)}
                            class="h-7 px-2.5 text-xs"
                            title="Permanently delete this job, its applications, resumes, scores, and KPI metrics"
                          >
                            {#if purgingJobId === j.id}
                              <Loader2 class="mr-1 size-3.5 animate-spin" />
                              Purging…
                            {:else}
                              <Trash2 class="mr-1 size-3.5" />
                              Clean delete
                            {/if}
                          </Button>
                        </div>
                      </Table.Cell>
                    </Table.Row>
                  {/each}
                {/if}
              </Table.Body>
            </Table.Root>
          </div>
        </Card>
      </Tabs.Content>

      <!-- CANDIDATES TAB -->
      <Tabs.Content value="candidates" class="space-y-3">
        <div class="flex items-center justify-between gap-2">
          <p class="text-xs text-muted-foreground">
            Showing {filteredCandidates.length} of {candidates.length} candidate(s)
          </p>
          <Button
            variant="destructive"
            size="sm"
            disabled={candidates.length === 0 || deletingAllSection !== null || purgingId !== null}
            onclick={handleDeleteAllCandidates}
            class="h-8 text-xs"
          >
            {#if deletingAllSection === 'candidates'}
              <Loader2 class="mr-1.5 size-3.5 animate-spin" />
              Deleting all candidates…
            {:else}
              <Trash2 class="mr-1.5 size-3.5" />
              Delete all candidates ({candidates.length})
            {/if}
          </Button>
        </div>
        <Card class="border-0 bg-card shadow-sm overflow-hidden">
          <div class="overflow-x-auto">
            <Table.Root>
              <Table.Header>
                <Table.Row>
                  <Table.Head class="font-semibold text-foreground">Candidate Name</Table.Head>
                  <Table.Head class="font-semibold text-foreground">Email</Table.Head>
                  <Table.Head class="text-center font-semibold text-foreground">Applications</Table.Head>
                  <Table.Head class="font-semibold text-foreground">Jobs Applied</Table.Head>
                  <Table.Head class="text-right font-semibold text-foreground">Last Applied</Table.Head>
                  <Table.Head class="text-right font-semibold text-foreground">Actions</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#if filteredCandidates.length === 0}
                  <Table.Row>
                    <Table.Cell colspan={6} class="text-center py-8 text-muted-foreground">
                      No candidates match the current filter.
                    </Table.Cell>
                  </Table.Row>
                {:else}
                  {#each filteredCandidates.slice((pg - 1) * SIZE, pg * SIZE) as c (c.key)}
                    <Table.Row class="hover:bg-muted/20">
                      <Table.Cell class="font-medium text-foreground">
                        {#if c.candidateId}
                          <a href={`/candidates/${c.candidateId}`} class="text-primary hover:underline font-semibold">
                            {c.name ?? 'Unnamed candidate'}
                          </a>
                        {:else}
                          {c.name ?? 'Unnamed candidate'}
                        {/if}
                      </Table.Cell>
                      <Table.Cell class="text-muted-foreground text-sm">{c.email ?? NP}</Table.Cell>
                      <Table.Cell class="text-center font-semibold tabular-nums text-foreground">{c.applications}</Table.Cell>
                      <Table.Cell class="whitespace-normal">
                        <div class="flex flex-wrap gap-1">
                          {#each c.jobs as j}
                            <Badge variant="secondary" class="text-xs bg-slate-100 text-slate-800 border-slate-200">
                              {j}
                            </Badge>
                          {/each}
                        </div>
                      </Table.Cell>
                      <Table.Cell class="text-right text-xs text-muted-foreground">{fmtDate(c.lastApplied ?? undefined)}</Table.Cell>
                      <Table.Cell class="text-right">
                        {#if c.candidateId}
                          <Button
                            variant="destructive"
                            size="sm"
                            disabled={purgingId !== null}
                            onclick={() => handleCleanDelete(c)}
                            class="h-7 px-2.5 text-xs"
                            title="Permanently erase candidate, resumes, applications, scores, and all history"
                          >
                            {#if purgingId === c.candidateId}
                              <Loader2 class="mr-1 size-3.5 animate-spin" />
                              Purging…
                            {:else}
                              <Trash2 class="mr-1 size-3.5" />
                              Clean delete
                            {/if}
                          </Button>
                        {/if}
                      </Table.Cell>
                    </Table.Row>
                  {/each}
                {/if}
              </Table.Body>
            </Table.Root>
          </div>
        </Card>
      </Tabs.Content>

      <!-- KPIS TAB -->
      <Tabs.Content value="kpis" class="w-full space-y-5">
        {#if filteredKpis.length > 0}
          <div class="grid w-full gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {#each filteredKpis.slice((pg - 1) * SIZE, pg * SIZE) as k, idx}
              {@const accent = kpiAccent(k.metric, idx)}
              <Card
                class="border-border bg-card shadow-sm overflow-hidden transition-shadow hover:shadow-md"
                style={`border-top: 3px solid ${accent.hex}`}
              >
                <CardContent class="p-5 flex items-center justify-between gap-4">
                  <div class="flex items-center gap-2.5 min-w-0">
                    <span
                      class="h-2.5 w-2.5 shrink-0 rounded-full"
                      style={`background: ${accent.dot}; box-shadow: 0 0 0 4px ${accent.hex}1F`}
                      aria-hidden="true"
                    ></span>
                    <span class="text-sm font-semibold text-foreground truncate">{k.metric}</span>
                  </div>
                  <span class="text-2xl font-bold tabular-nums shrink-0" style={`color: ${accent.hex}`}>{k.value}</span>
                </CardContent>
              </Card>
            {/each}
          </div>
        {/if}
        <Card class="w-full border-0 bg-card shadow-sm overflow-hidden">
          <div class="overflow-x-auto w-full">
            <Table.Root class="w-full">
              <Table.Header>
                <Table.Row>
                  <Table.Head class="text-left font-semibold text-foreground">Metric / KPI</Table.Head>
                  <Table.Head class="text-right font-semibold text-foreground">Formatted Value</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#if filteredKpis.length === 0}
                  <Table.Row>
                    <Table.Cell colspan={2} class="text-center py-8 text-muted-foreground">
                      No metrics match the current filter.
                    </Table.Cell>
                  </Table.Row>
                {:else}
                  {#each filteredKpis.slice((pg - 1) * SIZE, pg * SIZE) as k}
                    <Table.Row class="hover:bg-muted/20">
                      <Table.Cell class="text-left font-medium text-foreground">{k.metric}</Table.Cell>
                      <Table.Cell class="text-right font-semibold text-foreground tabular-nums">{k.value}</Table.Cell>
                    </Table.Row>
                  {/each}
                {/if}
              </Table.Body>
            </Table.Root>
          </div>
        </Card>
      </Tabs.Content>

      <!-- TEAM MEMBERS TAB -->
      <Tabs.Content value="members" class="space-y-3">
        <div class="flex items-center justify-between gap-2">
          <p class="text-xs text-muted-foreground">
            Showing {filteredMembers.length} of {members.length} team member(s) ({removableMemberCount} removable)
          </p>
          <Button
            variant="destructive"
            size="sm"
            disabled={removableMemberCount === 0 || deletingAllSection !== null}
            onclick={handleDeleteAllMembers}
            class="h-8 text-xs"
            title={removableMemberCount === 0 ? 'Company administrators cannot be removed' : 'Remove all non-admin team members'}
          >
            {#if deletingAllSection === 'members'}
              <Loader2 class="mr-1.5 size-3.5 animate-spin" />
              Removing team…
            {:else}
              <Trash2 class="mr-1.5 size-3.5" />
              Delete all team ({removableMemberCount})
            {/if}
          </Button>
        </div>
        <Card class="border-0 bg-card shadow-sm overflow-hidden">
          <div class="overflow-x-auto">
            <Table.Root>
              <Table.Header>
                <Table.Row>
                  <Table.Head class="text-left font-semibold text-foreground">Member</Table.Head>
                  <Table.Head class="text-left font-semibold text-foreground">Email</Table.Head>
                  <Table.Head class="text-center font-semibold text-foreground">Role</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#if filteredMembers.length === 0}
                  <Table.Row>
                    <Table.Cell colspan={3} class="text-center py-8 text-muted-foreground">
                      No members match the current filter.
                    </Table.Cell>
                  </Table.Row>
                {:else}
                  {#each filteredMembers.slice((pg - 1) * SIZE, pg * SIZE) as m}
                    <Table.Row class="hover:bg-muted/20">
                      <Table.Cell class="text-left font-medium text-foreground">
                        {String(m.name || m.email || 'Unnamed')}
                      </Table.Cell>
                      <Table.Cell class="text-left text-muted-foreground text-sm">{String(m.email ?? NP)}</Table.Cell>
                      <Table.Cell class="text-center">
                        <Badge variant="secondary" class="capitalize text-xs">
                          {String(m.role || 'recruiter')}
                        </Badge>
                      </Table.Cell>
                    </Table.Row>
                  {/each}
                {/if}
              </Table.Body>
            </Table.Root>
          </div>
        </Card>
      </Tabs.Content>

      <!-- Pagination -->
      <div class="flex items-center justify-between px-2 text-xs text-muted-foreground">
        <span>Page {pg} of {pages}</span>
        <div class="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={pg <= 1}
            onclick={() => pg--}
            class="h-7 px-2.5 text-xs"
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={pg >= pages}
            onclick={() => pg++}
            class="h-7 px-2.5 text-xs"
          >
            Next
          </Button>
        </div>
      </div>
    {/if}
  </Tabs.Root>
</div>
