<script lang="ts">
  import { getOverview, getAnalytics } from '$lib/services/analytics';
  import { listJobs } from '$lib/services/jobs';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import AutoViz from '$lib/components/AutoViz.svelte';
  import { toastError } from '$lib/errors';
  import { fmtScore, isObj } from '$lib/utils';
  import { kpiAccent } from '$lib/viz-colors';
  import type { Job } from '$lib/types/job';

  import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '$lib/components/ui/card';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import { Button } from '$lib/components/ui/button';
  import {
    RefreshCw,
    AlertCircle,
    Plus,
    BarChart3,
    Database,
    ArrowRight,
    CheckCircle2,
    Clock,
    XCircle
  } from '@lucide/svelte';

  let phase = $state<'loading' | 'ready' | 'error'>('loading');
  let overview = $state<Record<string, unknown> | null>(null);
  let pipeline = $state<Record<string, unknown> | null>(null);
  let jobs = $state<Job[]>([]);

  async function load() {
    phase = 'loading';
    try {
      const [ov, pipe, jobList] = await Promise.allSettled([
        getOverview(),
        getAnalytics('pipeline'),
        listJobs()
      ]);
      if (ov.status === 'rejected') throw ov.reason;
      overview = isObj(ov.value) ? ov.value : null;
      pipeline = pipe.status === 'fulfilled' && isObj(pipe.value) ? pipe.value : null;
      jobs = jobList.status === 'fulfilled' ? jobList.value : [];
      phase = 'ready';
    } catch (e) {
      phase = 'error';
      toastError(e, 'Could not load dashboard');
    }
  }

  load();

  const kpis = $derived(isObj(overview?.kpis) ? (overview.kpis as Record<string, unknown>) : null);
  const numVal = (obj: Record<string, unknown> | null, key: string): number =>
    obj && typeof obj[key] === 'number' ? (obj[key] as number) : 0;

  const summaryCards = $derived.by(() => {
    if (!kpis) return [];
    const totalApps = numVal(kpis, 'total_applications');
    const openJobs = numVal(kpis, 'open_jobs');
    const analyzed = numVal(kpis, 'analyzed_count');
    const shortlisted = numVal(kpis, 'shortlisted_count');
    const rejected = numVal(kpis, 'rejected_count');
    const avgScore = numVal(kpis, 'average_latest_score');
    const medianScore = numVal(kpis, 'median_latest_score');
    const reviewShare = numVal(kpis, 'share_needing_review');
    const reviewPct = Math.round((reviewShare <= 1 ? reviewShare * 100 : reviewShare) * 10) / 10;

    return [
      {
        label: 'Total Applications',
        value: String(totalApps),
        sub: `${analyzed} analyzed · ${rejected} rejected`
      },
      {
        label: 'Open Jobs',
        value: String(openJobs),
        sub: `${jobs.length} total job${jobs.length === 1 ? '' : 's'} in workspace`
      },
      {
        label: 'Shortlisted',
        value: String(shortlisted),
        sub: totalApps > 0 ? `${Math.round((shortlisted / totalApps) * 100)}% of applicants` : 'No applicants yet'
      },
      {
        label: 'Average Score',
        value: totalApps > 0 ? fmtScore(avgScore) : '—',
        sub: totalApps > 0 ? `Median ${fmtScore(medianScore)} · ${reviewPct}% need review` : 'Awaiting scored resumes'
      }
    ];
  });

  const processing = $derived(
    isObj(pipeline?.processing_outcomes)
      ? (pipeline.processing_outcomes as Record<string, number>)
      : null
  );

  const funnelPayload = $derived(
    pipeline && Array.isArray(pipeline.funnel) ? { pipeline_funnel: pipeline.funnel } : null
  );

  const trendPayload = $derived(
    overview && isObj(overview.trend) ? { application_trend: overview.trend } : null
  );
</script>

<div class="space-y-5">
  <!-- Clean Header + Quick Actions -->
  <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
    <div class="space-y-1">
      <h1 class="text-3xl font-bold tracking-tight text-foreground">Dashboard</h1>
      <p class="text-sm text-muted-foreground">
        Recruitment overview, pipeline health, and recent jobs
      </p>
    </div>

    <div class="flex flex-wrap items-center gap-2 shrink-0">
      <Button size="sm" href="/jobs/new">
        <Plus class="mr-1.5 size-3.5" /> New job
      </Button>
      <Button variant="outline" size="sm" href="/analytics">
        <BarChart3 class="mr-1.5 size-3.5" /> Analytics
      </Button>
      <Button variant="outline" size="sm" href="/data?tab=kpis">
        <Database class="mr-1.5 size-3.5" /> Data Explorer
      </Button>
      <Button variant="ghost" size="icon" class="size-8" onclick={load} disabled={phase === 'loading'} aria-label="Refresh dashboard">
        <RefreshCw class="size-4 {phase === 'loading' ? 'animate-spin' : ''}" />
      </Button>
    </div>
  </div>

  {#if phase === 'loading'}
    <Skeleton rows={2} cols={4} height="h-28" />
  {:else if phase === 'error'}
    <Alert variant="destructive">
      <AlertCircle class="size-4" />
      <AlertTitle>Cannot load dashboard data</AlertTitle>
      <AlertDescription class="flex items-center justify-between gap-4 mt-2">
        <span>Could not reach the analytics service.</span>
        <Button variant="outline" size="sm" onclick={load}>
          <RefreshCw class="mr-1.5 size-3.5" /> Try again
        </Button>
      </AlertDescription>
    </Alert>
  {:else}
    <!-- 4-Card Executive KPI Strip -->
    {#if summaryCards.length}
      <div class="grid w-full gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {#each summaryCards as c, idx}
          {@const accent = kpiAccent(c.label, idx)}
          <Card
            class="border-border bg-card shadow-sm overflow-hidden transition-shadow hover:shadow-md"
            style={`border-top: 3px solid ${accent.hex}`}
          >
            <CardContent class="p-5 flex flex-col justify-between h-full">
              <div>
                <div class="flex items-center justify-between gap-2">
                  <div class="text-3xl font-bold tracking-tight tabular-nums" style={`color: ${accent.hex}`}>
                    {c.value}
                  </div>
                  <span
                    class="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={`background: ${accent.dot}; box-shadow: 0 0 0 4px ${accent.hex}1F`}
                    aria-hidden="true"
                  ></span>
                </div>
                <div class="mt-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {c.label}
                </div>
              </div>
              <p class="mt-2.5 pt-2 border-t border-border/60 text-xs text-muted-foreground truncate">
                {c.sub}
              </p>
            </CardContent>
          </Card>
        {/each}
      </div>
    {/if}

    <!-- Compact Resume Processing Health Strip -->
    {#if processing}
      <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3 text-xs shadow-xs">
        <span class="font-semibold uppercase tracking-wider text-muted-foreground text-[11px]">
          Resume Processing
        </span>
        <div class="flex flex-wrap items-center gap-x-6 gap-y-1.5">
          <span class="inline-flex items-center gap-1.5">
            <CheckCircle2 class="size-3.5 text-emerald-500" />
            <span class="text-muted-foreground">Succeeded:</span>
            <strong class="font-bold text-foreground tabular-nums">{processing.succeeded ?? 0}</strong>
          </span>
          <span class="inline-flex items-center gap-1.5">
            <Clock class="size-3.5 text-amber-500" />
            <span class="text-muted-foreground">In progress:</span>
            <strong class="font-bold text-foreground tabular-nums">{processing.in_progress ?? 0}</strong>
          </span>
          <span class="inline-flex items-center gap-1.5">
            <XCircle class="size-3.5 text-rose-500" />
            <span class="text-muted-foreground">Failed:</span>
            <strong class="font-bold text-foreground tabular-nums">{processing.failed ?? 0}</strong>
          </span>
          {#if (processing.average_processing_seconds ?? 0) > 0}
            <span class="text-muted-foreground">
              Avg time: <strong class="font-semibold text-foreground tabular-nums">{Number(processing.average_processing_seconds).toFixed(1)}s</strong>
            </span>
          {/if}
        </div>
      </div>
    {/if}

    <!-- Main 2-Column Row: Pipeline Funnel + Recent Jobs Snapshot -->
    <div class="grid gap-5 lg:grid-cols-12 items-stretch">
      <div class="lg:col-span-7 min-w-0">
        {#if funnelPayload}
          <AutoViz value={funnelPayload} stats={false} rootTitle="Pipeline Funnel" />
        {/if}
      </div>

      <Card class="lg:col-span-5 border-border bg-card shadow-sm flex flex-col justify-between">
        <div>
          <CardHeader class="pb-3 border-b border-border/60 flex flex-row items-center justify-between gap-2">
            <div>
              <CardTitle class="text-sm font-semibold">Recent Jobs</CardTitle>
              <CardDescription class="text-xs">Jump straight to applicant ranking</CardDescription>
            </div>
            <Button variant="ghost" size="sm" href="/jobs" class="h-7 px-2 text-xs text-muted-foreground">
              View all <ArrowRight class="ml-1 size-3" />
            </Button>
          </CardHeader>
          <CardContent class="p-0">
            {#if jobs.length === 0}
              <div class="p-8 text-center space-y-3">
                <p class="text-sm text-muted-foreground">No jobs posted yet.</p>
                <Button size="sm" href="/jobs/new">
                  <Plus class="mr-1.5 size-3.5" /> Create your first job
                </Button>
              </div>
            {:else}
              <ul class="divide-y divide-border">
                {#each jobs.slice(0, 5) as j (j.id)}
                  <li class="flex items-center justify-between gap-3 px-5 py-3 hover:bg-muted/30 transition-colors">
                    <div class="min-w-0">
                      <a href={`/jobs/${j.id}/applicants`} class="text-sm font-semibold text-foreground hover:text-primary truncate block">
                        {j.title}
                      </a>
                      <span class="text-xs text-muted-foreground truncate block">
                        {j.department ?? 'General'}{j.location ? ` · ${j.location}` : ''}
                      </span>
                    </div>
                    <div class="flex items-center gap-2 shrink-0">
                      <StatusBadge status={j.status} />
                      <Button variant="ghost" size="sm" href={`/jobs/${j.id}/applicants`} class="h-7 px-2 text-xs">
                        Rank <ArrowRight class="ml-1 size-3" />
                      </Button>
                    </div>
                  </li>
                {/each}
              </ul>
            {/if}
          </CardContent>
        </div>
      </Card>
    </div>

    <!-- Application Trend Line Chart -->
    {#if trendPayload}
      <AutoViz value={trendPayload} stats={false} rootTitle="Application Trend" />
    {/if}
  {/if}
</div>
