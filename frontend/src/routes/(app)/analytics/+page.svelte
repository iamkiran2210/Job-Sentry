<script lang="ts">
  import { getAnalytics, TABS, type Tab } from '$lib/services/analytics';
  import { listJobs } from '$lib/services/jobs';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import AutoViz from '$lib/components/AutoViz.svelte';
  import { toastError } from '$lib/errors';
  import { humanize, isObj, fmtScore } from '$lib/utils';
  import { colorForLabel, colorForRatio, kpiAccent } from '$lib/viz-colors';
  import type { Job } from '$lib/types/job';

  import * as Tabs from '$lib/components/ui/tabs';
  import * as Select from '$lib/components/ui/select';
  import * as Table from '$lib/components/ui/table';
  import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '$lib/components/ui/card';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Badge } from '$lib/components/ui/badge';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import {
    RefreshCw,
    AlertCircle,
    Database,
    LayoutGrid,
    Briefcase,
    Users,
    Sparkles,
    GitBranch,
    X,
    ExternalLink
  } from '@lucide/svelte';

  const SORTS = [
    ['applications', 'Applications'],
    ['analyzed', 'Analyzed'],
    ['shortlisted', 'Shortlisted'],
    ['avg_score', 'Average score'],
    ['created_at', 'Date created']
  ] as const;

  function localIsoDate(d: Date): string {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  function isoDaysAgo(days: number): string {
    const d = new Date();
    d.setDate(d.getDate() - days);
    return localIsoDate(d);
  }

  const todayIso = localIsoDate(new Date());

  let tab = $state<Tab>('overview');
  let preset = $state<'7d' | '30d' | '90d' | 'custom'>('30d');
  let from = $state(isoDaysAgo(29));
  let to = $state(todayIso);
  let jobId = $state('all');
  let interval = $state<'day' | 'week' | 'month'>('day');
  let sortField = $state('applications');
  let sortDir = $state<'asc' | 'desc'>('desc');
  let pg = $state(1);
  let limit = $state('10');
  let jobs = $state<Job[]>([]);
  let data = $state<unknown>(null);
  let st = $state<'loading' | 'ready' | 'error'>('loading');
  let loadSeq = 0;

  listJobs()
    .then((j) => (jobs = j))
    .catch(() => {});

  function applyPreset(p: '7d' | '30d' | '90d') {
    preset = p;
    const now = localIsoDate(new Date());
    to = now;
    if (p === '7d') {
      from = isoDaysAgo(6);
      interval = 'day';
    } else if (p === '30d') {
      from = isoDaysAgo(29);
      interval = 'day';
    } else {
      from = isoDaysAgo(89);
      interval = 'week';
    }
    pg = 1;
    load();
  }

  function onDateChange(which: 'from' | 'to', value: string) {
    if (which === 'from') from = value;
    else to = value;
    preset = 'custom';
    // Prevent invalid inverted ranges (start > end) before hitting the API
    if (from && to && from > to) {
      if (which === 'from') to = from;
      else from = to;
    }
    pg = 1;
    load();
  }

  const hasCustomFilters = $derived(
    preset !== '30d' || jobId !== 'all' || (tab === 'overview' && interval !== 'day')
  );

  function resetFilters() {
    jobId = 'all';
    applyPreset('30d');
  }

  async function load() {
    const seq = ++loadSeq;
    st = 'loading';
    try {
      const result = await getAnalytics(tab, {
        from: from || undefined,
        to: to || undefined,
        jobId: jobId === 'all' ? undefined : jobId,
        interval,
        page: pg,
        sort: `${sortField}:${sortDir}`,
        limit: Number(limit) || 10
      });
      if (seq !== loadSeq) return;
      data = result;
      st = 'ready';
    } catch (e) {
      if (seq !== loadSeq) return;
      st = 'error';
      toastError(e, 'Could not load analytics');
    }
  }

  load();

  const pick = (t: Tab) => {
    tab = t;
    pg = 1;
    load();
  };

  // Typed helpers for purpose-built Jobs & Skills views
  interface JobMetricRow {
    id: string;
    title: string;
    applications: number;
    applied: number;
    processing: number;
    analyzed: number;
    shortlisted: number;
    rejected: number;
    withdrawn: number;
    avg_score: number | null;
    eligible: number;
    needs_review: number;
    potentially_ineligible: number;
  }

  const jobsPayload = $derived.by(() => {
    if (tab !== 'jobs' || !isObj(data)) return null;
    const rawItems = Array.isArray(data.items) ? (data.items as JobMetricRow[]) : [];
    const total = typeof data.total === 'number' ? data.total : rawItems.length;
    const totalPages = typeof data.total_pages === 'number' ? Math.max(1, data.total_pages) : 1;
    const totalApps = rawItems.reduce((s, r) => s + (Number(r.applications) || 0), 0);
    const totalShortlisted = rawItems.reduce((s, r) => s + (Number(r.shortlisted) || 0), 0);
    const scored = rawItems.map((r) => r.avg_score).filter((v): v is number => typeof v === 'number');
    const avgScore = scored.length ? scored.reduce((a, b) => a + b, 0) / scored.length : null;
    return { items: rawItems, total, totalPages, totalApps, totalShortlisted, avgScore };
  });

  interface CandidateSkillRow {
    skill: string;
    candidate_count: number;
    share: number;
  }
  interface RequiredSkillRow {
    requirement_id: string;
    skill: string;
    mandatory: boolean;
    weight: number;
    coverage_rate: number;
  }

  const skillsPayload = $derived.by(() => {
    if (tab !== 'skills' || !isObj(data)) return null;
    const candidateSkills = Array.isArray(data.top_candidate_skills)
      ? (data.top_candidate_skills as CandidateSkillRow[])
      : [];
    const requiredSkills = Array.isArray(data.top_required_skills)
      ? (data.top_required_skills as RequiredSkillRow[])
      : [];
    return { candidateSkills, requiredSkills };
  });

  const overviewPayload = $derived.by(() => {
    if (tab !== 'overview' || !isObj(data) || !isObj(data.kpis)) return null;
    const k = data.kpis as Record<string, unknown>;
    const numV = (key: string) => (typeof k[key] === 'number' ? (k[key] as number) : 0);
    const totalApps = numV('total_applications');
    const openJobs = numV('open_jobs');
    const analyzed = numV('analyzed_count');
    const shortlisted = numV('shortlisted_count');
    const rejected = numV('rejected_count');
    const avgScore = numV('average_latest_score');
    const medianScore = numV('median_latest_score');
    const reviewShare = numV('share_needing_review');
    const reviewPct = Math.round((reviewShare <= 1 ? reviewShare * 100 : reviewShare) * 10) / 10;

    return {
      cards: [
        {
          label: 'Total Applications',
          value: String(totalApps),
          sub: `${analyzed} analyzed · ${rejected} rejected`
        },
        {
          label: 'Open Jobs',
          value: String(openJobs),
          sub: jobId === 'all' ? 'Active openings in company' : 'Selected job filter'
        },
        {
          label: 'Shortlisted',
          value: String(shortlisted),
          sub: totalApps > 0 ? `${Math.round((shortlisted / totalApps) * 100)}% shortlist rate` : 'No applicants in range'
        },
        {
          label: 'Average Score',
          value: totalApps > 0 ? fmtScore(avgScore) : '—',
          sub: totalApps > 0 ? `Median ${fmtScore(medianScore)} · ${reviewPct}% need review` : 'No scored applicants'
        }
      ],
      charts: {
        ...(isObj(k.applications_per_status) ? { applications_per_status: k.applications_per_status } : {}),
        ...(isObj(data.trend) ? { application_trend: data.trend } : {})
      }
    };
  });
</script>

<div class="space-y-5">
  <!-- Clean Header + Action Toolbar -->
  <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
    <div class="space-y-1">
      <h1 class="text-3xl font-bold tracking-tight text-foreground">Analytics</h1>
      <p class="text-sm text-muted-foreground">
        Recruitment KPIs, pipeline velocity, and skill coverage
      </p>
    </div>

    <div class="flex flex-wrap items-center gap-2 shrink-0">
      <Button variant="outline" size="sm" onclick={load} disabled={st === 'loading'}>
        <RefreshCw class="mr-1.5 size-3.5 {st === 'loading' ? 'animate-spin' : ''}" />
        Refresh
      </Button>
      <Button variant="outline" size="sm" href="/data?tab=kpis">
        <Database class="mr-1.5 size-3.5" />
        Data Explorer
      </Button>
    </div>
  </div>

  <!-- Unified Tabs & Streamlined Filter Bar -->
  <Card class="border-border bg-card shadow-xs">
    <CardContent class="p-4 space-y-3.5">
      <Tabs.Root value={tab} onValueChange={(v) => pick(v as Tab)}>
        <Tabs.List class="grid grid-cols-2 sm:grid-cols-5 w-full h-auto">
          {#each TABS as t}
            <Tabs.Trigger value={t} class="capitalize gap-1.5 py-2 text-xs sm:text-sm">
              {#if t === 'overview'}
                <LayoutGrid class="size-3.5 hidden sm:inline" />
              {:else if t === 'jobs'}
                <Briefcase class="size-3.5 hidden sm:inline" />
              {:else if t === 'candidates'}
                <Users class="size-3.5 hidden sm:inline" />
              {:else if t === 'skills'}
                <Sparkles class="size-3.5 hidden sm:inline" />
              {:else}
                <GitBranch class="size-3.5 hidden sm:inline" />
              {/if}
              <span>{humanize(t)}</span>
            </Tabs.Trigger>
          {/each}
        </Tabs.List>
      </Tabs.Root>

      <!-- Single Aligned Filter Row -->
      <div class="flex flex-wrap items-center justify-between gap-2.5 pt-2 border-t border-border/60">
        <!-- Date Range Presets + Inputs -->
        <div class="flex flex-wrap items-center gap-2">
          <div class="inline-flex items-center rounded-lg border border-border bg-muted/30 p-0.5">
            {#each (['7d', '30d', '90d'] as const) as p}
              <button
                type="button"
                onclick={() => applyPreset(p)}
                class={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer ${
                  preset === p ? 'bg-background text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {p}
              </button>
            {/each}
          </div>

          <div class="flex items-center gap-1.5">
            <Input
              id="from-date"
              aria-label="From date"
              type="date"
              max={to || todayIso}
              value={from}
              onchange={(e) => onDateChange('from', (e.currentTarget as HTMLInputElement).value)}
              class="h-8 w-[136px] text-xs"
            />
            <span class="text-xs text-muted-foreground">–</span>
            <Input
              id="to-date"
              aria-label="To date"
              type="date"
              min={from || undefined}
              max={todayIso}
              value={to}
              onchange={(e) => onDateChange('to', (e.currentTarget as HTMLInputElement).value)}
              class="h-8 w-[136px] text-xs"
            />
          </div>
        </div>

        <!-- Contextual Controls -->
        <div class="flex flex-wrap items-center gap-2">
          {#if tab !== 'jobs'}
            <div class="w-44">
              <Select.Root type="single" bind:value={jobId} onValueChange={() => load()}>
                <Select.Trigger aria-label="Filter by job" class="h-8 text-xs w-full">
                  {jobId === 'all' ? 'All jobs' : (jobs.find((j) => j.id === jobId)?.title ?? 'Selected job')}
                </Select.Trigger>
                <Select.Content>
                  <Select.Item value="all">All jobs</Select.Item>
                  {#each jobs as j}
                    <Select.Item value={j.id}>{j.title}</Select.Item>
                  {/each}
                </Select.Content>
              </Select.Root>
            </div>
          {/if}

          {#if tab === 'overview'}
            <div class="w-32">
              <Select.Root type="single" bind:value={interval} onValueChange={() => load()}>
                <Select.Trigger aria-label="Group interval" class="h-8 text-xs w-full capitalize">
                  By {humanize(interval)}
                </Select.Trigger>
                <Select.Content>
                  {#each ['day', 'week', 'month'] as i}
                    <Select.Item value={i}>By {humanize(i)}</Select.Item>
                  {/each}
                </Select.Content>
              </Select.Root>
            </div>
          {/if}

          {#if tab === 'jobs'}
            <div class="w-40">
              <Select.Root
                type="single"
                bind:value={sortField}
                onValueChange={() => {
                  pg = 1;
                  load();
                }}
              >
                <Select.Trigger aria-label="Sort jobs by" class="h-8 text-xs w-full">
                  Sort: {SORTS.find(([v]) => v === sortField)?.[1] ?? sortField}
                </Select.Trigger>
                <Select.Content>
                  {#each SORTS as [v, l]}
                    <Select.Item value={v}>{l}</Select.Item>
                  {/each}
                </Select.Content>
              </Select.Root>
            </div>

            <div class="w-32">
              <Select.Root
                type="single"
                bind:value={sortDir}
                onValueChange={() => {
                  pg = 1;
                  load();
                }}
              >
                <Select.Trigger aria-label="Sort order" class="h-8 text-xs w-full">
                  {sortDir === 'desc' ? 'High → Low' : 'Low → High'}
                </Select.Trigger>
                <Select.Content>
                  <Select.Item value="desc">High → Low</Select.Item>
                  <Select.Item value="asc">Low → High</Select.Item>
                </Select.Content>
              </Select.Root>
            </div>
          {/if}

          {#if tab === 'skills'}
            <div class="w-28">
              <Select.Root type="single" bind:value={limit} onValueChange={() => load()}>
                <Select.Trigger aria-label="Top skills limit" class="h-8 text-xs w-full">
                  Top {limit}
                </Select.Trigger>
                <Select.Content>
                  {#each ['5', '10', '20', '50'] as n}
                    <Select.Item value={n}>Top {n}</Select.Item>
                  {/each}
                </Select.Content>
              </Select.Root>
            </div>
          {/if}

          {#if hasCustomFilters}
            <Button variant="ghost" size="sm" class="h-8 px-2 text-xs text-muted-foreground" onclick={resetFilters}>
              <X class="mr-1 size-3.5" /> Reset
            </Button>
          {/if}
        </div>
      </div>
    </CardContent>
  </Card>

  <!-- Main Content Area -->
  {#if st === 'loading'}
    <Skeleton rows={2} cols={2} height="h-64" />
  {:else if st === 'error'}
    <Alert variant="destructive">
      <AlertCircle class="size-4" />
      <AlertTitle>Cannot load analytics</AlertTitle>
      <AlertDescription class="flex items-center justify-between gap-4 mt-2">
        <span>Could not retrieve reporting data for this view.</span>
        <Button variant="outline" size="sm" onclick={load}>
          <RefreshCw class="mr-1.5 size-3.5" /> Try again
        </Button>
      </AlertDescription>
    </Alert>
  {:else if tab === 'overview' && overviewPayload}
    <!-- Purpose-built Overview Analytics View -->
    {@const ov = overviewPayload}
    <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {#each ov.cards as c, idx}
        {@const acc = kpiAccent(c.label, idx)}
        <Card class="border-border bg-card shadow-sm overflow-hidden transition-shadow hover:shadow-md" style={`border-top: 3px solid ${acc.hex}`}>
          <CardContent class="p-4 flex flex-col justify-between h-full">
            <div>
              <div class="flex items-center justify-between gap-2">
                <div class="text-2xl font-bold tabular-nums" style={`color: ${acc.hex}`}>{c.value}</div>
                <span
                  class="h-2.5 w-2.5 rounded-full shrink-0"
                  style={`background: ${acc.dot}; box-shadow: 0 0 0 4px ${acc.hex}1F`}
                  aria-hidden="true"
                ></span>
              </div>
              <div class="mt-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{c.label}</div>
            </div>
            <p class="mt-2 pt-2 border-t border-border/60 text-xs text-muted-foreground truncate">{c.sub}</p>
          </CardContent>
        </Card>
      {/each}
    </div>
    <AutoViz value={ov.charts} stats={false} rootTitle="Overview" />
  {:else if tab === 'jobs' && jobsPayload}
    <!-- Purpose-built Jobs Analytics View -->
    {@const jp = jobsPayload}
    <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {#each [
        ['Total Jobs', String(jp.total)],
        ['Total Applications', String(jp.totalApps)],
        ['Shortlisted', String(jp.totalShortlisted)],
        ['Average Score', jp.avgScore !== null ? `${jp.avgScore.toFixed(1)}%` : '—']
      ] as [label, val], idx}
        {@const acc = kpiAccent(label, idx)}
        <Card class="border-border bg-card shadow-sm overflow-hidden" style={`border-top: 3px solid ${acc.hex}`}>
          <CardContent class="p-4 flex flex-col justify-between">
            <div class="flex items-center justify-between gap-2">
              <div class="text-2xl font-bold tabular-nums" style={`color: ${acc.hex}`}>{val}</div>
              <span
                class="h-2.5 w-2.5 rounded-full shrink-0"
                style={`background: ${acc.dot}; box-shadow: 0 0 0 4px ${acc.hex}1F`}
                aria-hidden="true"
              ></span>
            </div>
            <div class="mt-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</div>
          </CardContent>
        </Card>
      {/each}
    </div>

    {#if jp.items.length === 0}
      <Card class="border-border bg-card shadow-sm">
        <CardContent class="p-12 text-center text-sm text-muted-foreground">
          No jobs found for the selected date range.
        </CardContent>
      </Card>
    {:else}
      <!-- Job Performance Comparison Table -->
      <Card class="border-border bg-card shadow-sm overflow-hidden">
        <CardHeader class="pb-3">
          <CardTitle class="text-base font-semibold">Job Performance Breakdown</CardTitle>
          <CardDescription class="text-xs">
            Applicant volume, stage conversion, average score, and mandatory eligibility per role.
          </CardDescription>
        </CardHeader>
        <div class="overflow-x-auto">
          <Table.Root>
            <Table.Header>
              <Table.Row class="bg-muted/30">
                <Table.Head class="text-left font-semibold text-foreground">Job Title</Table.Head>
                <Table.Head class="text-center font-semibold text-foreground">Applications</Table.Head>
                <Table.Head class="text-center font-semibold text-foreground">Analyzed</Table.Head>
                <Table.Head class="text-center font-semibold text-foreground">Shortlisted</Table.Head>
                <Table.Head class="text-center font-semibold text-foreground">Rejected</Table.Head>
                <Table.Head class="text-left font-semibold text-foreground">Avg Score</Table.Head>
                <Table.Head class="text-center font-semibold text-foreground">Mandatory Fit</Table.Head>
                <Table.Head class="text-right font-semibold text-foreground">Open</Table.Head>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {#each jp.items as r (r.id)}
                {@const scoreClr = r.avg_score !== null ? colorForRatio(r.avg_score / 100) : '#94A3B8'}
                <Table.Row class="hover:bg-muted/30 transition-colors">
                  <Table.Cell class="font-semibold text-foreground">
                    <a href={`/jobs/${r.id}/applicants`} class="text-primary hover:underline">
                      {r.title}
                    </a>
                  </Table.Cell>
                  <Table.Cell class="text-center font-semibold tabular-nums">{r.applications}</Table.Cell>
                  <Table.Cell class="text-center tabular-nums text-indigo-600 font-medium">{r.analyzed}</Table.Cell>
                  <Table.Cell class="text-center tabular-nums text-emerald-600 font-semibold">{r.shortlisted}</Table.Cell>
                  <Table.Cell class="text-center tabular-nums text-rose-600 font-medium">{r.rejected}</Table.Cell>
                  <Table.Cell>
                    {#if r.avg_score !== null}
                      <div class="flex items-center gap-2 min-w-[110px]">
                        <div class="h-2 w-14 rounded-full bg-muted overflow-hidden">
                          <div class="h-full rounded-full" style={`width:${Math.min(100, Math.max(0, r.avg_score))}%; background:${scoreClr}`}></div>
                        </div>
                        <span class="text-xs font-semibold tabular-nums" style={`color:${scoreClr}`}>
                          {fmtScore(r.avg_score)}
                        </span>
                      </div>
                    {:else}
                      <span class="text-xs text-muted-foreground">—</span>
                    {/if}
                  </Table.Cell>
                  <Table.Cell class="text-center">
                    <div class="inline-flex items-center gap-1.5 text-[11px] tabular-nums">
                      <Badge variant="outline" class="border-emerald-200 bg-emerald-50 text-emerald-700 font-medium">
                        {r.eligible} pass
                      </Badge>
                      {#if r.needs_review > 0}
                        <Badge variant="outline" class="border-amber-200 bg-amber-50 text-amber-700 font-medium">
                          {r.needs_review} rev
                        </Badge>
                      {/if}
                      {#if r.potentially_ineligible > 0}
                        <Badge variant="outline" class="border-rose-200 bg-rose-50 text-rose-700 font-medium">
                          {r.potentially_ineligible} gap
                        </Badge>
                      {/if}
                    </div>
                  </Table.Cell>
                  <Table.Cell class="text-right">
                    <Button variant="ghost" size="sm" href={`/jobs/${r.id}/applicants`} class="h-7 px-2 text-xs">
                      Ranking <ExternalLink class="ml-1 size-3" />
                    </Button>
                  </Table.Cell>
                </Table.Row>
              {/each}
            </Table.Body>
          </Table.Root>
        </div>

        <div class="flex items-center justify-between border-t border-border px-4 py-3 text-xs text-muted-foreground">
          <span>Showing {jp.items.length} of {jp.total} job{jp.total === 1 ? '' : 's'}</span>
          <div class="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={pg <= 1}
              onclick={() => {
                pg--;
                load();
              }}
              class="h-7 px-2.5 text-xs"
            >
              Previous
            </Button>
            <span class="font-medium text-foreground">Page {pg} of {jp.totalPages}</span>
            <Button
              variant="outline"
              size="sm"
              disabled={pg >= jp.totalPages}
              onclick={() => {
                pg++;
                load();
              }}
              class="h-7 px-2.5 text-xs"
            >
              Next
            </Button>
          </div>
        </div>
      </Card>

      <!-- Side-by-side Job Visual Comparisons -->
      <AutoViz
        value={{
          applications_by_job: jp.items.map((r) => ({ name: r.title, count: r.applications })),
          average_score_by_job: jp.items.map((r) => ({ name: r.title, score: r.avg_score ?? 0 }))
        }}
        stats={false}
        rootTitle="Jobs"
      />
    {/if}
  {:else if tab === 'skills' && skillsPayload}
    <!-- Purpose-built Skills Analytics View -->
    {@const sp = skillsPayload}
    <div class="grid gap-5 lg:grid-cols-2 items-start">
      <Card class="border-border bg-card shadow-sm">
        <CardHeader class="pb-3 border-b border-border/60">
          <CardTitle class="text-base font-semibold">Top Candidate Skills</CardTitle>
          <CardDescription class="text-xs">
            Most common skills extracted across active candidate resumes.
          </CardDescription>
        </CardHeader>
        <CardContent class="pt-4">
          {#if sp.candidateSkills.length === 0}
            <p class="py-8 text-center text-sm text-muted-foreground">No candidate skills recorded in this range.</p>
          {:else}
            {@const maxCnt = Math.max(1, ...sp.candidateSkills.map((s) => s.candidate_count))}
            <ul class="space-y-3">
              {#each sp.candidateSkills as s, idx}
                {@const clr = colorForLabel(s.skill, idx)}
                {@const sharePct = Math.round((s.share <= 1 ? s.share * 100 : s.share) * 10) / 10}
                <li class="space-y-1">
                  <div class="flex items-center justify-between gap-2 text-sm">
                    <span class="flex items-center gap-2 min-w-0">
                      <span class="h-2.5 w-2.5 shrink-0 rounded-full" style={`background:${clr}`}></span>
                      <span class="font-medium text-foreground capitalize truncate">{s.skill}</span>
                    </span>
                    <span class="text-xs tabular-nums shrink-0">
                      <strong class="font-bold text-foreground">{s.candidate_count}</strong>
                      <span class="text-muted-foreground ml-1">({sharePct}%)</span>
                    </span>
                  </div>
                  <div class="h-2 w-full rounded-full bg-muted/70 overflow-hidden">
                    <div
                      class="h-full rounded-full transition-all duration-300"
                      style={`width:${Math.min(100, (s.candidate_count / maxCnt) * 100)}%; background: linear-gradient(90deg, ${clr}, ${clr}CC)`}
                    ></div>
                  </div>
                </li>
              {/each}
            </ul>
          {/if}
        </CardContent>
      </Card>

      <Card class="border-border bg-card shadow-sm">
        <CardHeader class="pb-3 border-b border-border/60">
          <CardTitle class="text-base font-semibold">Required Skill Coverage</CardTitle>
          <CardDescription class="text-xs">
            Share of applicants matching each job skill requirement.
          </CardDescription>
        </CardHeader>
        <CardContent class="pt-4">
          {#if sp.requiredSkills.length === 0}
            <p class="py-8 text-center text-sm text-muted-foreground">No skill requirements configured for jobs in this range.</p>
          {:else}
            <ul class="space-y-3">
              {#each sp.requiredSkills as r}
                {@const covRatio = r.coverage_rate <= 1 ? r.coverage_rate : r.coverage_rate / 100}
                {@const covPct = Math.round(covRatio * 1000) / 10}
                {@const clr = colorForRatio(covRatio)}
                <li class="space-y-1">
                  <div class="flex items-center justify-between gap-2 text-sm">
                    <div class="flex items-center gap-2 min-w-0">
                      <span class="font-medium text-foreground truncate">{r.skill}</span>
                      <Badge
                        variant="outline"
                        class={`text-[10px] px-1.5 py-0 ${
                          r.mandatory
                            ? 'border-rose-200 bg-rose-50 text-rose-700'
                            : 'border-sky-200 bg-sky-50 text-sky-700'
                        }`}
                      >
                        {r.mandatory ? 'Mandatory' : `Weight ${Math.round((r.weight <= 1 ? r.weight * 100 : r.weight))}%`}
                      </Badge>
                    </div>
                    <span class="text-xs font-bold tabular-nums shrink-0" style={`color:${clr}`}>
                      {covPct}%
                    </span>
                  </div>
                  <div class="h-2 w-full rounded-full bg-muted/70 overflow-hidden">
                    <div
                      class="h-full rounded-full transition-all duration-300"
                      style={`width:${Math.min(100, covPct)}%; background: linear-gradient(90deg, ${clr}, ${clr}CC)`}
                    ></div>
                  </div>
                </li>
              {/each}
            </ul>
          {/if}
        </CardContent>
      </Card>
    </div>
  {:else}
    <!-- Overview, Candidates, Pipeline (using upgraded AutoViz) -->
    <AutoViz value={data} rootTitle={humanize(tab)} />
  {/if}
</div>
