<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import {
    getRankingHistory,
    getRanking,
    runRanking,
    listApplicants,
    applicantView,
    deleteApplication
  } from '$lib/services/applications';
  import { getJob } from '$lib/services/jobs';
  import { ApiError } from '$lib/services/api-client';
  import { toast } from '$lib/stores/toast.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { pipelineProgress } from '$lib/stores/pipeline-progress.svelte';
  import { toastError } from '$lib/errors';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import Donut from '$lib/components/Donut.svelte';
  import {
    APP_STATUSES,
    ELIGIBILITY_LABEL,
    DEFAULT_DECISION_AGENTS,
    DECISION_OUTCOME_LABEL,
    type DecisionAgentId,
    type DecisionAgentMeta,
    type DecisionOutcome,
    type RankedItem,
    type RankingPage
  } from '$lib/types/application';
  import { fmtScore, fmtRatio, fmtDateTime, humanize, shortId, pctNum, num } from '$lib/utils';
  import { colorForRatio } from '$lib/viz-colors';
  import {
    buildExportRows,
    makeExportFilename,
    toCsv,
    toXlsx,
    triggerFileDownload
  } from '$lib/export-ranking';

  import * as Table from '$lib/components/ui/table';
  import * as Select from '$lib/components/ui/select';
  import * as Collapsible from '$lib/components/ui/collapsible';
  import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
  import { Checkbox } from '$lib/components/ui/checkbox';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Label } from '$lib/components/ui/label';
  import { Badge } from '$lib/components/ui/badge';
  import { Card, CardHeader, CardTitle, CardContent } from '$lib/components/ui/card';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import {
    Play,
    SlidersHorizontal,
    GitCompare,
    Search,
    AlertTriangle,
    Loader2,
    RefreshCw,
    ChevronDown,
    ChevronUp,
    Trash2,
    Bot,
    Download,
    FileSpreadsheet,
    FileText,
    Filter,
    X,
    PieChart,
    UploadCloud
  } from '@lucide/svelte';

  const id = page.params.jobId!;
  const SIZE = 25;
  let jobTitle = $state('');
  let data = $state<RankingPage | null>(null);
  let names = $state<Record<string, string>>({});
  let emails = $state<Record<string, string>>({});
  let st = $state<'loading' | 'ready' | 'error'>('loading');
  let msg = $state('');
  let busy = $state(false);
  let busyAction = $state<'rank' | 'force' | 'selected' | 'individual' | null>(null);
  let busyAppId = $state<string | null>(null);
  let deletingAppId = $state<string | null>(null);
  let exporting = $state<'csv' | 'xlsx' | null>(null);

  let pg = $state(1);
  let status = $state('all');
  let elig = $state('all');
  let q = $state('');
  let picked = $state<string[]>([]);
  let applicantCount = $state<number | null>(null);
  let runSel = $state('latest');
  let ver = $state('all');
  let decisionAgent = $state<DecisionAgentId>('balanced');
  let decisionFilter = $state<'all' | DecisionOutcome>('all');
  let minS = $state('');
  let maxS = $state('');
  let history = $state<{ run_id: string; created_at?: string; executed_at?: string; count?: number }[]>([]);

  let showRun = $state(false);
  let showMoreFilters = $state(false);
  let showCharts = $state(false);

  let force = $state(false);
  let forceVerify = $state(false);
  let autoApplyDecisions = $state(false);
  let minAcceptThreshold = $state('65');
  let runElig = $state('all');
  let runMin = $state('');
  let runMax = $state('');
  let runLimit = $state(50);

  getJob(id)
    .then((j) => (jobTitle = j.title))
    .catch(() => {});

  const loadHistory = () =>
    getRankingHistory(id)
      .then((h) => (history = h))
      .catch(() => {});

  loadHistory();

  function activeRankingFilters() {
    return {
      status: status === 'all' ? undefined : status,
      eligibility: elig === 'all' ? undefined : elig,
      verification_status: ver === 'all' ? undefined : ver,
      decision_agent: decisionAgent,
      decision: decisionFilter === 'all' ? undefined : decisionFilter,
      run_id: runSel === 'latest' ? undefined : runSel,
      minPercent: num(minS) ?? undefined,
      maxPercent: num(maxS) ?? undefined
    };
  }

  async function load() {
    st = 'loading';
    try {
      data = await getRanking(id, {
        page: pg,
        page_size: SIZE,
        ...activeRankingFilters()
      });
      st = 'ready';
      listApplicants(id)
        .then((l) => {
          applicantCount = l.length;
          for (const a of l) {
            const v = applicantView(a);
            if (v.applicationId) {
              if (v.name || v.email) names[v.applicationId] = v.name ?? v.email ?? '';
              if (v.email) emails[v.applicationId] = v.email;
            }
          }
        })
        .catch(() => {});
    } catch (e) {
      msg = e instanceof ApiError ? e.message : 'Failed to load ranking.';
      st = 'error';
      toastError(e, 'Could not load ranking');
    }
  }

  load();

  // Auto-refresh ranking table when a background upload+rank or post-refresh task completes for this job
  let lastHandledCompletionAt = 0;
  $effect(() => {
    const done = pipelineProgress.lastCompleted;
    if (done && done.jobId === id && done.at > lastHandledCompletionAt && !busy) {
      lastHandledCompletionAt = done.at;
      load();
      loadHistory();
    }
  });

  async function executeRank(
    opts: { force?: boolean; applicationIds?: string[]; useFilters?: boolean },
    action: 'rank' | 'force' | 'selected' | 'individual',
    singleId: string | null = null
  ) {
    if (busy) return;
    busy = true;
    busyAction = action;
    busyAppId = singleId;
    msg = '';
    const resolvedJob = jobTitle || 'Applicant Ranking';
    const singleLabel = singleId ? names[singleId] || `Application ${shortId(singleId)}` : undefined;
    const taskKind =
      action === 'force'
        ? 'rescore'
        : action === 'selected'
          ? 'selected'
          : action === 'individual'
            ? 'individual'
            : 'rank';
    const taskId = pipelineProgress.start({
      jobId: id,
      jobName: resolvedJob,
      kind: taskKind,
      stage: 'analyzing',
      subject: singleLabel,
      includeNotify: autoApplyDecisions,
      runCountBefore: history.length,
      detail:
        action === 'individual' && singleLabel
          ? `Analyzing & scoring ${singleLabel}…`
          : action === 'selected'
            ? `Re-scoring ${opts.applicationIds?.length ?? 0} selected applicants…`
            : opts.force
              ? 'Re-analyzing & re-scoring all applicants…'
              : 'Analyzing processed resumes & preparing scores…',
      progress: 18,
      notify: true
    });
    pipelineProgress.simulateRankingPhases(taskId, {
      includesVerify: forceVerify || !opts.force,
      includeNotify: autoApplyDecisions,
      isRerun: !!opts.force,
      subject: singleLabel
    });

    try {
      const res = await runRanking(id, {
        force: opts.force ?? false,
        forceVerify,
        decisionAgent,
        minAcceptThreshold: num(minAcceptThreshold) ?? undefined,
        autoApplyDecisions,
        applicationIds: opts.applicationIds,
        eligibility: opts.useFilters && runElig !== 'all' ? runElig : undefined,
        minPercent: opts.useFilters ? (num(runMin) ?? undefined) : undefined,
        maxPercent: opts.useFilters ? (num(runMax) ?? undefined) : undefined,
        limit: opts.useFilters ? runLimit : Math.max(runLimit, applicantCount ?? 50)
      });
      showRun = false;
      pg = 1;
      runSel = 'latest';
      await load();
      loadHistory();
      const verifiedCount = typeof res?.verified_count === 'number' ? res.verified_count : 0;
      const autoApplied = typeof res?.auto_applied_count === 'number' ? res.auto_applied_count : 0;
      const notifSent = typeof res?.notifications_sent === 'number' ? res.notifications_sent : 0;
      const notifFailed = typeof res?.notifications_failed === 'number' ? res.notifications_failed : 0;
      const notifResults = Array.isArray(res?.notification_results)
        ? (res.notification_results as { channel?: string; reason?: string }[])
        : [];
      if (verifiedCount > 0) {
        toast.info(
          `${resolvedJob} · Verified`,
          `Completed verification checks for ${verifiedCount} applicant${verifiedCount === 1 ? '' : 's'}.`
        );
      }
      const verSuffix = verifiedCount > 0 ? ` Verified ${verifiedCount} applicant(s).` : '';
      const autoSuffix = autoApplyDecisions
        ? autoApplied > 0 || notifSent > 0 || notifFailed > 0
          ? ` Auto-applied ${autoApplied} status update(s)` +
            (notifSent > 0
              ? ` and emailed ${notifSent} via SendPulse.`
              : notifFailed > 0
                ? ` (${notifFailed} email(s) failed — check SendPulse config).`
                : ' (notifications logged to Audit Outbox).')
          : ' Auto-apply checked all applicants (no status changes or new notifications needed).'
        : '';
      if (notifFailed > 0) {
        const firstErr =
          notifResults.find((n) => n.channel === 'sendpulse_failed' || n.channel === 'smtp_failed')?.reason ??
          'Check SendPulse settings in backend/.env.';
        pipelineProgress.fail(
          taskId,
          `Auto-applied ${autoApplied} decision(s), but ${notifFailed} email(s) failed: ${firstErr}`,
          `${resolvedJob} · Email notification issue`
        );
      } else if (opts.applicationIds?.length === 1) {
        const label = singleLabel || `Application ${shortId(opts.applicationIds[0])}`;
        pipelineProgress.complete(
          taskId,
          `Re-scored ${label} and updated relative ranks.${verSuffix}${autoSuffix}`,
          { title: `Ranking complete · ${resolvedJob}`, verifiedCount, showViewAction: false }
        );
      } else if (opts.applicationIds && opts.applicationIds.length > 1) {
        pipelineProgress.complete(
          taskId,
          `Re-scored ${opts.applicationIds.length} selected applicants and updated relative ranks.${verSuffix}${autoSuffix}`,
          { title: `Ranking complete · ${resolvedJob}`, verifiedCount, showViewAction: false }
        );
      } else if (opts.force) {
        pipelineProgress.complete(
          taskId,
          `Recalculated scores for every applicant.${verSuffix}${autoSuffix}`,
          { title: `Re-run complete · ${resolvedJob}`, verifiedCount, showViewAction: false }
        );
      } else {
        pipelineProgress.complete(
          taskId,
          `Scores now reflect all processed resumes.${verSuffix}${autoSuffix}`,
          { title: `Ranking complete · ${resolvedJob}`, verifiedCount, showViewAction: false }
        );
      }
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : 'Ranking failed';
      pipelineProgress.fail(taskId, detail, `${resolvedJob} · Ranking failed`);
    } finally {
      busy = false;
      busyAction = null;
      busyAppId = null;
    }
  }

  const rank = () => executeRank({ force: false, useFilters: false }, 'rank');
  const forceRescoreAll = () => executeRank({ force: true, useFilters: false }, 'force');
  const rankWithOptions = () => executeRank({ force, useFilters: true }, force ? 'force' : 'rank');
  const rankSelected = () =>
    picked.length > 0 && executeRank({ force: true, applicationIds: [...picked] }, 'selected');
  const rankIndividual = (appId: string) =>
    appId && executeRank({ force: true, applicationIds: [appId] }, 'individual', appId);

  async function removeApplication(appId: string, label: string) {
    if (busy || deletingAppId) return;
    const ok = await confirmDialog({
      title: 'Delete resume application?',
      message: `This permanently deletes the application and uploaded resume for ${label} from this job. Audit history entries (if already ranked) are preserved without candidate data.`,
      confirmLabel: 'Delete application',
      danger: true
    });
    if (!ok) return;
    deletingAppId = appId;
    try {
      await deleteApplication(appId);
      picked = picked.filter((x) => x !== appId);
      toast.success('Application deleted', `${label} has been removed from this job.`);
      await load();
      loadHistory();
    } catch (e) {
      toastError(e, 'Could not delete application');
    } finally {
      deletingAppId = null;
    }
  }

  async function handleExport(format: 'csv' | 'xlsx') {
    if (exporting || !data) return;
    exporting = format;
    try {
      const filters = activeRankingFilters();
      let allItems: RankedItem[] = [];
      const pageSize = 100;
      const total = data.total_count;
      if (total <= data.items.length && pg === 1) {
        allItems = [...data.items];
      } else {
        const totalPages = Math.min(20, Math.max(1, Math.ceil(total / pageSize)));
        for (let p = 1; p <= totalPages; p++) {
          const res = await getRanking(id, { page: p, page_size: pageSize, ...filters });
          allItems.push(...res.items);
          if (res.items.length < pageSize) break;
        }
      }

      if (q.trim()) {
        const term = q.trim().toLowerCase();
        allItems = allItems.filter((i) => {
          const hay = `${names[i.application_id] ?? ''} ${i.candidate_name ?? ''} ${emails[i.application_id] ?? ''} ${i.application_id}`.toLowerCase();
          return hay.includes(term);
        });
      }

      if (allItems.length === 0) {
        toast.info('Nothing to export', 'No ranked applicants match the current filters.');
        return;
      }

      const rows = buildExportRows(allItems, {
        names,
        emails,
        agentName: activeAgentMeta.name
      });
      const filename = makeExportFilename(jobTitle || `job-${shortId(id)}`, format);
      if (format === 'csv') {
        const blob = new Blob([toCsv(rows)], { type: 'text/csv;charset=utf-8;' });
        triggerFileDownload(blob, filename);
      } else {
        const bytes = toXlsx(rows, jobTitle || 'Applicant Ranking');
        const blob = new Blob([bytes as BlobPart], {
          type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        });
        triggerFileDownload(blob, filename);
      }
      toast.success(
        `Exported ${rows.length} applicant${rows.length === 1 ? '' : 's'}`,
        `Downloaded ${filename}`
      );
    } catch (e) {
      toastError(e, 'Could not export ranking');
    } finally {
      exporting = null;
    }
  }

  const toggle = (a: string) => {
    picked = picked.includes(a) ? picked.filter((x) => x !== a) : [...picked, a];
  };

  const pages = $derived(data ? Math.max(1, Math.ceil(data.total_count / SIZE)) : 1);
  const shown = $derived(
    (data?.items ?? []).filter((i) => {
      if (!q.trim()) return true;
      const term = q.trim().toLowerCase();
      const hay = `${names[i.application_id] ?? ''} ${i.candidate_name ?? ''} ${emails[i.application_id] ?? ''} ${i.application_id}`.toLowerCase();
      return hay.includes(term);
    })
  );

  const allShownSelected = $derived(
    shown.length > 0 && shown.every((i) => picked.includes(i.application_id))
  );

  function toggleAllShown() {
    if (allShownSelected) {
      const shownIds = new Set(shown.map((i) => i.application_id));
      picked = picked.filter((x) => !shownIds.has(x));
    } else {
      const nextSet = new Set(picked);
      for (const i of shown) nextSet.add(i.application_id);
      picked = [...nextSet];
    }
  }

  const advancedFilterCount = $derived(
    (elig !== 'all' ? 1 : 0) +
      (ver !== 'all' ? 1 : 0) +
      (decisionFilter !== 'all' ? 1 : 0) +
      (runSel !== 'latest' ? 1 : 0) +
      (minS.trim() !== '' || maxS.trim() !== '' ? 1 : 0)
  );

  const hasAnyFilter = $derived(
    q.trim() !== '' || status !== 'all' || advancedFilterCount > 0
  );

  function clearFilters() {
    q = '';
    status = 'all';
    elig = 'all';
    ver = 'all';
    decisionFilter = 'all';
    runSel = 'latest';
    minS = '';
    maxS = '';
    pg = 1;
    load();
  }

  const agentsList = $derived<DecisionAgentMeta[]>(
    data?.available_decision_agents?.length ? data.available_decision_agents : DEFAULT_DECISION_AGENTS
  );
  const activeAgentMeta = $derived(
    agentsList.find((a) => a.id === decisionAgent) ?? DEFAULT_DECISION_AGENTS[0]
  );

  const avgPageScore = $derived.by(() => {
    const nums = (data?.items ?? [])
      .map((i) => pctNum(i.score))
      .filter((n): n is number => n !== null);
    if (!nums.length) return null;
    return nums.reduce((a, b) => a + b, 0) / nums.length;
  });

  const eligibleCount = $derived(
    (data?.items ?? []).filter((i) => i.eligibility === 'eligible').length
  );

  const advanceCount = $derived(
    (data?.items ?? []).filter(
      (i) => i.decision?.decision === 'strong_advance' || i.decision?.decision === 'advance'
    ).length
  );

  const decisionBadgeClass = (d?: string | null): string => {
    switch (d) {
      case 'strong_advance':
        return 'bg-emerald-100 text-emerald-800 border-emerald-200 hover:bg-emerald-100';
      case 'advance':
        return 'bg-sky-100 text-sky-800 border-sky-200 hover:bg-sky-100';
      case 'review':
        return 'bg-amber-100 text-amber-800 border-amber-200 hover:bg-amber-100';
      case 'hold':
        return 'bg-slate-100 text-slate-700 border-slate-200 hover:bg-slate-100';
      case 'pass':
        return 'bg-rose-100 text-rose-800 border-rose-200 hover:bg-rose-100';
      default:
        return 'bg-muted text-muted-foreground border-border';
    }
  };

  const decisionOutcomes = $derived(
    (Object.entries(DECISION_OUTCOME_LABEL) as [DecisionOutcome, string][])
      .map(([k, label]) => ({
        label,
        value: (data?.items ?? []).filter((i) => i.decision?.decision === k).length
      }))
      .filter((o) => o.value > 0)
  );

  const outcomes = $derived(
    Object.entries(ELIGIBILITY_LABEL)
      .map(([k, label]) => ({
        label,
        value: (data?.items ?? []).filter((i) => i.eligibility === k).length
      }))
      .filter((o) => o.value > 0)
  );

  const formatRunLabel = (h: { run_id: string; created_at?: string; executed_at?: string; count?: number }) => {
    const ts = fmtDateTime(h.created_at ?? h.executed_at);
    const base = ts !== '—' ? ts : `Run ${shortId(h.run_id)}`;
    return h.count ? `${base} (${h.count})` : base;
  };

  const selectedRunLabel = $derived.by(() => {
    if (runSel === 'latest') {
      const latest = history[0];
      const ts = latest ? fmtDateTime(latest.created_at ?? latest.executed_at) : '—';
      return ts !== '—' ? `Latest · ${ts}` : 'Latest run';
    }
    const found = history.find((h) => h.run_id === runSel);
    return found ? formatRunLabel(found) : `Run ${shortId(runSel)}`;
  });

  const NP = 'Not provided';
</script>

<div class="space-y-5">
  <!-- Header & Primary Actions -->
  <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
    <div class="space-y-1">
      <h1 class="text-3xl font-bold tracking-tight text-foreground">Applicant Ranking</h1>
      <p class="text-sm text-muted-foreground">
        Explainable AI scoring{jobTitle ? ` for ${jobTitle}` : ''} · Humans make all final hiring decisions.
      </p>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <Button disabled={busy} onclick={rank} class="font-medium">
        {#if busy && busyAction === 'rank'}
          <Loader2 class="mr-1.5 size-4 animate-spin" />
          Ranking…
        {:else}
          <Play class="mr-1.5 size-4 fill-current" />
          Run ranking
        {/if}
      </Button>

      <Button
        variant="secondary"
        disabled={busy}
        onclick={forceRescoreAll}
        class="font-medium"
        title="Recalculate scores for every applicant"
      >
        {#if busy && busyAction === 'force'}
          <Loader2 class="mr-1.5 size-4 animate-spin" />
          Re-scoring…
        {:else}
          <RefreshCw class="mr-1.5 size-4" />
          Re-score all
        {/if}
      </Button>

      <Button
        variant={autoApplyDecisions ? 'default' : 'outline'}
        onclick={() => (showRun = !showRun)}
        aria-expanded={showRun}
      >
        <SlidersHorizontal class="mr-1.5 size-4" />
        Run options{autoApplyDecisions ? ` (Auto ≥ ${minAcceptThreshold || 65}%)` : ''}
        {#if showRun}
          <ChevronUp class="ml-1 size-3.5" />
        {:else}
          <ChevronDown class="ml-1 size-3.5" />
        {/if}
      </Button>

      <DropdownMenu.Root>
        <DropdownMenu.Trigger>
          {#snippet child({ props })}
            <Button
              {...props}
              variant="outline"
              disabled={exporting !== null || !data || data.total_count === 0}
            >
              {#if exporting}
                <Loader2 class="mr-1.5 size-4 animate-spin" />
                Exporting…
              {:else}
                <Download class="mr-1.5 size-4" />
                Export
                <ChevronDown class="ml-1 size-3.5" />
              {/if}
            </Button>
          {/snippet}
        </DropdownMenu.Trigger>
        <DropdownMenu.Content align="end" class="w-48">
          <DropdownMenu.Item onclick={() => handleExport('csv')}>
            <FileText class="mr-2 size-4 text-muted-foreground" />
            <span>Download CSV (.csv)</span>
          </DropdownMenu.Item>
          <DropdownMenu.Item onclick={() => handleExport('xlsx')}>
            <FileSpreadsheet class="mr-2 size-4 text-emerald-600" />
            <span>Download Excel (.xlsx)</span>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Root>
    </div>
  </div>

  <!-- Run Options Collapsible -->
  <Collapsible.Root bind:open={showRun}>
    <Collapsible.Content>
      <Card class="border-border bg-card shadow-sm">
        <CardHeader class="pb-3">
          <CardTitle class="text-base font-semibold">Ranking Run Options</CardTitle>
          <p class="text-xs text-muted-foreground">
            Configure rescoring, profile re-verification, acceptance threshold, and optional auto-apply notifications. For single-applicant options, open that applicant's page.
          </p>
        </CardHeader>
        <CardContent class="space-y-4">
          <div class="grid gap-4 md:grid-cols-2">
            <!-- Scoring & Verification -->
            <div class="space-y-3 rounded-lg border border-border/70 bg-muted/20 p-3.5">
              <div class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Scoring &amp; Verification
              </div>
              <div class="flex items-start gap-2.5">
                <Checkbox id="force-rescore" bind:checked={force} />
                <div class="space-y-0.5">
                  <Label for="force-rescore" class="text-sm font-medium cursor-pointer">
                    Force re-score everyone
                  </Label>
                  <p class="text-xs text-muted-foreground">
                    Recalculate scores for all applicants, including already evaluated ones.
                  </p>
                </div>
              </div>
              <div class="flex items-start gap-2.5">
                <Checkbox id="force-verify" bind:checked={forceVerify} />
                <div class="space-y-0.5">
                  <Label for="force-verify" class="text-sm font-medium cursor-pointer">
                    Re-verify profiles while re-ranking
                  </Label>
                  <p class="text-xs text-muted-foreground">
                    Re-run email MX, LinkedIn, GitHub, portfolio, and project link checks.
                  </p>
                </div>
              </div>
              <div class="grid grid-cols-2 gap-3 pt-1">
                <div class="space-y-1">
                  <Label class="text-xs">Mandatory outcome</Label>
                  <Select.Root type="single" bind:value={runElig}>
                    <Select.Trigger class="h-8 text-xs w-full">
                      {runElig === 'all' ? 'Include all' : ((ELIGIBILITY_LABEL as Record<string, string>)[runElig] ?? runElig)}
                    </Select.Trigger>
                    <Select.Content>
                      <Select.Item value="all">Include all</Select.Item>
                      {#each Object.entries(ELIGIBILITY_LABEL) as [k, v]}
                        <Select.Item value={k}>{v}</Select.Item>
                      {/each}
                    </Select.Content>
                  </Select.Root>
                </div>
                <div class="space-y-1">
                  <Label for="run-limit" class="text-xs">Applicants limit</Label>
                  <Input id="run-limit" type="number" min="1" max="500" bind:value={runLimit} class="h-8 text-xs" />
                </div>
              </div>
            </div>

            <!-- Threshold & Auto-Apply -->
            <div class="space-y-3 rounded-lg border border-border/70 bg-muted/20 p-3.5">
              <div class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Threshold &amp; Auto-Apply
              </div>
              <div class="grid grid-cols-3 gap-2.5">
                <div class="space-y-1">
                  <Label for="run-threshold" class="text-xs">Accept min (%)</Label>
                  <Input id="run-threshold" type="number" min="0" max="100" placeholder="65" bind:value={minAcceptThreshold} class="h-8 text-xs" />
                </div>
                <div class="space-y-1">
                  <Label for="run-min" class="text-xs">Score min (%)</Label>
                  <Input id="run-min" type="number" min="0" max="100" placeholder="0" bind:value={runMin} class="h-8 text-xs" />
                </div>
                <div class="space-y-1">
                  <Label for="run-max" class="text-xs">Score max (%)</Label>
                  <Input id="run-max" type="number" min="0" max="100" placeholder="100" bind:value={runMax} class="h-8 text-xs" />
                </div>
              </div>
              <div class="flex items-start gap-2.5 pt-1">
                <Checkbox id="auto-apply-decisions" bind:checked={autoApplyDecisions} />
                <div class="space-y-0.5">
                  <Label for="auto-apply-decisions" class="text-sm font-medium cursor-pointer">
                    Auto-apply decisions (Shortlist / Reject + notify)
                  </Label>
                  <p class="text-xs text-muted-foreground">
                    Automatically updates status based on the Decision Agent &amp; accept threshold, logs audit history, and sends candidate notifications.
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div class="flex items-center gap-2 pt-2 border-t border-border">
            <Button size="sm" disabled={busy} onclick={rankWithOptions}>
              Run with these options
            </Button>
            <Button size="sm" variant="ghost" onclick={() => (showRun = false)}>
              Close
            </Button>
          </div>
        </CardContent>
      </Card>
    </Collapsible.Content>
  </Collapsible.Root>

  <!-- Simplified Filter Bar -->
  <Card class="border-border bg-card shadow-xs">
    <CardContent class="p-3.5 space-y-3">
      <!-- Primary Row -->
      <div class="flex flex-wrap items-center gap-2.5">
        <div class="relative flex-1 min-w-[200px]">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            type="search"
            aria-label="Search applicants"
            placeholder="Search by name or email…"
            bind:value={q}
            class="pl-9 h-9"
          />
        </div>

        <div class="w-full sm:w-40">
          <Select.Root
            type="single"
            bind:value={status}
            onValueChange={() => {
              pg = 1;
              load();
            }}
          >
            <Select.Trigger aria-label="Status filter" class="w-full h-9 text-xs">
              {status === 'all' ? 'All statuses' : humanize(status)}
            </Select.Trigger>
            <Select.Content>
              <Select.Item value="all">All statuses</Select.Item>
              {#each APP_STATUSES as s}
                <Select.Item value={s}>{humanize(s)}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        </div>

        <div class="w-full sm:w-52">
          <Select.Root
            type="single"
            bind:value={decisionAgent}
            onValueChange={() => {
              pg = 1;
              load();
            }}
          >
            <Select.Trigger aria-label="Decision agent" class="w-full h-9 text-xs">
              <span class="inline-flex items-center gap-1.5 truncate">
                <Bot class="size-3.5 text-primary shrink-0" />
                <span class="truncate">{activeAgentMeta.name}</span>
              </span>
            </Select.Trigger>
            <Select.Content>
              {#each agentsList as ag}
                <Select.Item value={ag.id}>
                  <div class="flex flex-col">
                    <span class="font-medium">{ag.name}</span>
                    <span class="text-[11px] text-muted-foreground">{ag.tagline}</span>
                  </div>
                </Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        </div>

        <Button
          variant={showMoreFilters || advancedFilterCount > 0 ? 'secondary' : 'outline'}
          size="sm"
          class="h-9 text-xs shrink-0"
          onclick={() => (showMoreFilters = !showMoreFilters)}
          aria-expanded={showMoreFilters}
        >
          <Filter class="mr-1.5 size-3.5" />
          More filters{advancedFilterCount > 0 ? ` (${advancedFilterCount})` : ''}
          {#if showMoreFilters}
            <ChevronUp class="ml-1 size-3.5" />
          {:else}
            <ChevronDown class="ml-1 size-3.5" />
          {/if}
        </Button>

        {#if hasAnyFilter}
          <Button variant="ghost" size="sm" class="h-9 text-xs text-muted-foreground" onclick={clearFilters}>
            <X class="mr-1 size-3.5" /> Clear
          </Button>
        {/if}
      </div>

      <!-- Advanced Filters Row (Collapsible) -->
      {#if showMoreFilters}
        <div class="grid gap-3 pt-3 border-t border-border/70 sm:grid-cols-2 lg:grid-cols-5">
          <div class="space-y-1">
            <Label class="text-[11px] font-medium text-muted-foreground">AI Decision</Label>
            <Select.Root
              type="single"
              bind:value={decisionFilter}
              onValueChange={() => {
                pg = 1;
                load();
              }}
            >
              <Select.Trigger aria-label="Decision outcome filter" class="w-full h-8 text-xs">
                {decisionFilter === 'all'
                  ? 'All AI decisions'
                  : (DECISION_OUTCOME_LABEL[decisionFilter] ?? decisionFilter)}
              </Select.Trigger>
              <Select.Content>
                <Select.Item value="all">All AI decisions</Select.Item>
                {#each Object.entries(DECISION_OUTCOME_LABEL) as [k, label]}
                  <Select.Item value={k}>{label}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
          </div>

          <div class="space-y-1">
            <Label class="text-[11px] font-medium text-muted-foreground">Mandatory Requirements</Label>
            <Select.Root
              type="single"
              bind:value={elig}
              onValueChange={() => {
                pg = 1;
                load();
              }}
            >
              <Select.Trigger aria-label="Mandatory filter" class="w-full h-8 text-xs">
                {elig === 'all' ? 'All outcomes' : ((ELIGIBILITY_LABEL as Record<string, string>)[elig] ?? elig)}
              </Select.Trigger>
              <Select.Content>
                <Select.Item value="all">All outcomes</Select.Item>
                {#each Object.entries(ELIGIBILITY_LABEL) as [k, v]}
                  <Select.Item value={k}>{v}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
          </div>

          <div class="space-y-1">
            <Label class="text-[11px] font-medium text-muted-foreground">Verification</Label>
            <Select.Root
              type="single"
              bind:value={ver}
              onValueChange={() => {
                pg = 1;
                load();
              }}
            >
              <Select.Trigger aria-label="Verification filter" class="w-full h-8 text-xs">
                {ver === 'all' ? 'All verification' : humanize(ver)}
              </Select.Trigger>
              <Select.Content>
                <Select.Item value="all">All verification</Select.Item>
                {#each ['passed', 'needs_review', 'not_verified', 'failed'] as v}
                  <Select.Item value={v}>{humanize(v)}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
          </div>

          <div class="space-y-1">
            <Label class="text-[11px] font-medium text-muted-foreground">Score Range (%)</Label>
            <div class="flex items-center gap-1.5">
              <Input
                type="number"
                min="0"
                max="100"
                placeholder="Min"
                bind:value={minS}
                onchange={() => {
                  pg = 1;
                  load();
                }}
                class="h-8 text-xs"
              />
              <span class="text-xs text-muted-foreground">–</span>
              <Input
                type="number"
                min="0"
                max="100"
                placeholder="Max"
                bind:value={maxS}
                onchange={() => {
                  pg = 1;
                  load();
                }}
                class="h-8 text-xs"
              />
            </div>
          </div>

          {#if history.length > 0}
            <div class="space-y-1">
              <Label class="text-[11px] font-medium text-muted-foreground">Ranking Run</Label>
              <Select.Root
                type="single"
                bind:value={runSel}
                onValueChange={() => {
                  pg = 1;
                  load();
                }}
              >
                <Select.Trigger aria-label="Ranking history run" class="w-full h-8 text-xs">
                  {selectedRunLabel}
                </Select.Trigger>
                <Select.Content>
                  <Select.Item value="latest">
                    {history[0] && fmtDateTime(history[0].created_at ?? history[0].executed_at) !== '—'
                      ? `Latest · ${fmtDateTime(history[0].created_at ?? history[0].executed_at)}`
                      : 'Latest run'}
                  </Select.Item>
                  {#each history as h}
                    <Select.Item value={h.run_id}>
                      {formatRunLabel(h)}
                    </Select.Item>
                  {/each}
                </Select.Content>
              </Select.Root>
            </div>
          {/if}
        </div>
      {/if}
    </CardContent>
  </Card>

  <!-- Unscored warning banner -->
  {#if st === 'ready' && applicantCount !== null && data && applicantCount > data.total_count}
    <Alert class="border-amber-200 bg-amber-50/70 text-amber-900">
      <AlertTriangle class="size-4 text-amber-600" />
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 w-full">
        <div>
          <AlertTitle class="font-semibold text-amber-900">Unscored Applicants Detected</AlertTitle>
          <AlertDescription class="text-amber-800 text-xs mt-0.5">
            <strong>{applicantCount - data.total_count} of {applicantCount} applicants</strong> do not have scores for this run.
          </AlertDescription>
        </div>
        <Button
          size="sm"
          disabled={busy}
          onclick={rank}
          class="shrink-0 bg-amber-600 hover:bg-amber-700 text-white font-medium"
        >
          {busy ? 'Ranking…' : 'Run ranking now'}
        </Button>
      </div>
    </Alert>
  {/if}

  {#if msg}
    <Alert variant="destructive">
      <AlertTriangle class="size-4" />
      <AlertDescription>{msg}</AlertDescription>
    </Alert>
  {/if}

  {#if st === 'loading'}
    <Skeleton rows={8} />
  {:else if st === 'ready' && data}
    {#if data.items.length === 0}
      <Card class="border-border bg-card">
        <CardContent class="p-12 text-center space-y-3">
          <p class="text-sm text-muted-foreground">
            {hasAnyFilter
              ? 'No ranked applicants match your current filters.'
              : 'No ranked applicants yet. Upload resumes and click "Run ranking" to evaluate candidates.'}
          </p>
          <div class="flex items-center justify-center gap-2">
            {#if hasAnyFilter}
              <Button variant="outline" size="sm" onclick={clearFilters}>Clear filters</Button>
            {:else}
              <Button variant="outline" size="sm" href={`/jobs/${id}/upload`}>
                <UploadCloud class="mr-1.5 size-4" /> Upload resumes
              </Button>
            {/if}
          </div>
        </CardContent>
      </Card>
    {:else}
      <!-- Compact Summary Strip + Charts Toggle -->
      <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3 shadow-xs">
        <div class="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
          <div class="flex items-center gap-2">
            <span class="h-2 w-2 rounded-full bg-indigo-500"></span>
            <span class="text-muted-foreground">Ranked:</span>
            <strong class="text-sm font-bold text-foreground tabular-nums">{data.total_count}</strong>
          </div>
          {#if avgPageScore !== null}
            <div class="flex items-center gap-2">
              <span class="h-2 w-2 rounded-full bg-teal-500"></span>
              <span class="text-muted-foreground">Avg score:</span>
              <strong class="text-sm font-bold text-foreground tabular-nums">{avgPageScore.toFixed(1)}%</strong>
            </div>
          {/if}
          <div class="flex items-center gap-2">
            <span class="h-2 w-2 rounded-full bg-emerald-500"></span>
            <span class="text-muted-foreground">Meets mandatory:</span>
            <strong class="text-sm font-bold text-foreground tabular-nums">{eligibleCount}</strong>
          </div>
          <div class="flex items-center gap-2">
            <span class="h-2 w-2 rounded-full bg-sky-500"></span>
            <span class="text-muted-foreground">Advance ({activeAgentMeta.short_name}):</span>
            <strong class="text-sm font-bold text-foreground tabular-nums">{advanceCount}</strong>
          </div>
        </div>

        {#if outcomes.length || decisionOutcomes.length}
          <Button
            variant="ghost"
            size="sm"
            class="h-7 px-2.5 text-xs text-muted-foreground hover:text-foreground"
            onclick={() => (showCharts = !showCharts)}
            aria-expanded={showCharts}
          >
            <PieChart class="mr-1.5 size-3.5 text-primary" />
            {showCharts ? 'Hide charts' : 'Show charts'}
          </Button>
        {/if}
      </div>

      <!-- Optional Charts (collapsed by default so table is immediately visible) -->
      {#if showCharts && (outcomes.length || decisionOutcomes.length)}
        <div class="grid gap-4 md:grid-cols-2">
          {#if outcomes.length}
            <Card class="border-border bg-card shadow-sm">
              <CardHeader class="pb-2">
                <CardTitle class="text-sm font-semibold">Mandatory Requirements Distribution</CardTitle>
              </CardHeader>
              <CardContent>
                <Donut items={outcomes} />
              </CardContent>
            </Card>
          {/if}
          {#if decisionOutcomes.length}
            <Card class="border-border bg-card shadow-sm">
              <CardHeader class="pb-2">
                <CardTitle class="text-sm font-semibold flex items-center gap-1.5">
                  <Bot class="size-4 text-primary" />
                  <span>{activeAgentMeta.name} — Decisions</span>
                </CardTitle>
                <p class="text-xs text-muted-foreground">{activeAgentMeta.tagline}</p>
              </CardHeader>
              <CardContent>
                <Donut items={decisionOutcomes} />
              </CardContent>
            </Card>
          {/if}
        </div>
      {/if}

      <!-- Contextual Selection Bar (appears only when applicants are selected) -->
      {#if picked.length > 0}
        <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/30 bg-primary/5 px-4 py-2.5">
          <span class="text-xs font-semibold text-foreground">
            {picked.length} applicant{picked.length === 1 ? '' : 's'} selected
          </span>
          <div class="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="default" disabled={busy} onclick={rankSelected} class="h-7 text-xs">
              {#if busy && busyAction === 'selected'}
                <Loader2 class="mr-1.5 size-3.5 animate-spin" />
                Ranking selected…
              {:else}
                <Play class="mr-1.5 size-3" />
                Rank selected ({picked.length})
              {/if}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={picked.length < 2 || picked.length > 4}
              onclick={() => goto(`/jobs/${id}/compare?ids=${picked.slice(0, 4).join(',')}`)}
              class="h-7 text-xs"
              title="Select 2 to 4 applicants to compare side by side"
            >
              <GitCompare class="mr-1.5 size-3.5" />
              Compare ({Math.min(picked.length, 4)}/4)
            </Button>
            <Button size="sm" variant="ghost" onclick={() => (picked = [])} class="h-7 text-xs">
              Clear
            </Button>
          </div>
        </div>
      {/if}

      <!-- Main Ranking Table -->
      <Card class="border-border bg-card overflow-hidden shadow-sm">
        <div class="overflow-x-auto">
          <Table.Root>
            <Table.Header>
              <Table.Row class="bg-muted/30">
                <Table.Head class="w-11 text-center">
                  <div class="flex items-center justify-center">
                    <Checkbox
                      aria-label="Select all applicants on this page"
                      checked={allShownSelected}
                      onCheckedChange={toggleAllShown}
                    />
                  </div>
                </Table.Head>
                <Table.Head class="w-12 text-center font-semibold text-foreground">#</Table.Head>
                <Table.Head class="text-left font-semibold text-foreground">Applicant</Table.Head>
                <Table.Head class="text-left font-semibold text-foreground">Score</Table.Head>
                <Table.Head class="text-left font-semibold text-foreground">
                  <span class="inline-flex items-center gap-1">
                    <Bot class="size-3.5 text-primary" />
                    <span>AI Decision ({activeAgentMeta.short_name})</span>
                  </span>
                </Table.Head>
                <Table.Head class="text-center font-semibold text-foreground">Skills</Table.Head>
                <Table.Head class="text-center font-semibold text-foreground">Mandatory</Table.Head>
                <Table.Head class="text-center font-semibold text-foreground">Completeness</Table.Head>
                <Table.Head class="text-center font-semibold text-foreground">Status</Table.Head>
                <Table.Head class="text-right font-semibold text-foreground">Actions</Table.Head>
              </Table.Row>
            </Table.Header>

            <Table.Body>
              {#each shown as it (it.application_id)}
                {@const scorePct = pctNum(it.score)}
                {@const barClr = scorePct !== null ? colorForRatio(scorePct / 100) : '#94A3B8'}
                {@const displayName =
                  names[it.application_id] || it.candidate_name || `Application ${shortId(it.application_id)}`}
                <Table.Row class="hover:bg-muted/30 transition-colors">
                  <Table.Cell class="w-11 text-center">
                    <div class="flex items-center justify-center">
                      <Checkbox
                        aria-label={`Select ${displayName} for comparison or ranking`}
                        checked={picked.includes(it.application_id)}
                        onCheckedChange={() => toggle(it.application_id)}
                      />
                    </div>
                  </Table.Cell>
                  <Table.Cell class="w-12 text-center font-mono text-sm font-semibold text-muted-foreground">
                    {it.rank}
                  </Table.Cell>
                  <Table.Cell class="text-left">
                    <div class="min-w-0">
                      <a
                        class="font-semibold text-primary hover:underline block truncate max-w-[200px]"
                        href={`/jobs/${id}/applicants/${it.application_id}`}
                        title={displayName}
                      >
                        {displayName}
                      </a>
                      {#if emails[it.application_id]}
                        <span class="text-[11px] text-muted-foreground block truncate max-w-[200px]">
                          {emails[it.application_id]}
                        </span>
                      {/if}
                    </div>
                  </Table.Cell>
                  <Table.Cell class="text-left">
                    <div class="flex items-center gap-2.5">
                      <div class="h-2 w-16 overflow-hidden rounded-full bg-muted">
                        <div
                          class="h-full rounded-full transition-all duration-300"
                          style={`width: ${scorePct ?? 0}%; background: ${barClr}`}
                        ></div>
                      </div>
                      <span class="tabular-nums font-semibold text-sm" style={`color: ${barClr}`}>
                        {fmtScore(it.score)}
                      </span>
                    </div>
                  </Table.Cell>
                  <Table.Cell class="text-left max-w-[260px]">
                    {#if it.decision}
                      <div class="space-y-1">
                        <div class="flex flex-wrap items-center gap-1.5">
                          <Badge
                            variant="outline"
                            class={`text-[11px] font-semibold ${decisionBadgeClass(it.decision.decision)}`}
                          >
                            {DECISION_OUTCOME_LABEL[it.decision.decision] ?? humanize(it.decision.decision)}
                          </Badge>
                          <span class="text-[11px] font-mono text-muted-foreground tabular-nums">
                            {Math.round((it.decision.confidence ?? 0) * 100)}%
                          </span>
                        </div>
                        {#if it.decision.summary}
                          <p class="text-xs text-muted-foreground leading-snug line-clamp-2" title={it.decision.summary}>
                            {it.decision.summary}
                          </p>
                        {/if}
                      </div>
                    {:else}
                      <span class="text-xs text-muted-foreground">Pending</span>
                    {/if}
                  </Table.Cell>
                  <Table.Cell class="text-center tabular-nums text-sm font-medium">
                    {fmtScore(it.skills_score)}
                  </Table.Cell>
                  <Table.Cell class="text-center">
                    {#if it.eligibility}
                      <Badge
                        variant="outline"
                        class={`text-xs font-medium ${
                          it.eligibility === 'eligible'
                            ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                            : it.eligibility === 'needs_review'
                              ? 'border-amber-200 bg-amber-50 text-amber-700'
                              : 'border-rose-200 bg-rose-50 text-rose-700'
                        }`}
                      >
                        {it.eligibility === 'eligible'
                          ? 'Meets'
                          : it.eligibility === 'needs_review'
                            ? 'Review'
                            : 'Gap'}
                      </Badge>
                    {:else}
                      <span class="text-xs text-muted-foreground">Pending</span>
                    {/if}
                  </Table.Cell>
                  <Table.Cell class="text-center text-sm text-muted-foreground tabular-nums">
                    {fmtRatio(it.data_completeness)}
                  </Table.Cell>
                  <Table.Cell class="text-center">
                    {#if it.status}
                      <StatusBadge status={it.status} />
                    {:else}
                      <span class="text-xs text-muted-foreground">{NP}</span>
                    {/if}
                  </Table.Cell>
                  <Table.Cell class="text-right">
                    <div class="inline-flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy || deletingAppId === it.application_id}
                        onclick={() => rankIndividual(it.application_id)}
                        class="h-7 px-2 text-xs"
                        title="Re-score this applicant only"
                      >
                        {#if busy && busyAppId === it.application_id}
                          <Loader2 class="mr-1 size-3.5 animate-spin" />
                          Scoring…
                        {:else}
                          <RefreshCw class="mr-1 size-3.5" />
                          Re-score
                        {/if}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={busy || deletingAppId !== null}
                        onclick={() => removeApplication(it.application_id, displayName)}
                        class="size-7 text-muted-foreground hover:text-destructive"
                        title="Delete resume application"
                        aria-label={`Delete application for ${displayName}`}
                      >
                        {#if deletingAppId === it.application_id}
                          <Loader2 class="size-3.5 animate-spin" />
                        {:else}
                          <Trash2 class="size-3.5" />
                        {/if}
                      </Button>
                    </div>
                  </Table.Cell>
                </Table.Row>
              {/each}
            </Table.Body>
          </Table.Root>
        </div>

        <!-- Pagination Controls Bar -->
        <div class="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-3 text-xs text-muted-foreground">
          <span>
            Showing {shown.length} of {data.total_count} applicant{data.total_count === 1 ? '' : 's'} · algorithm {data.scoring_version ?? 'standard'}
          </span>
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
            <span class="px-2 font-medium text-foreground">
              Page {pg} of {pages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={pg >= pages}
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
    {/if}
  {:else}
    <Button variant="outline" onclick={load}>
      <RefreshCw class="mr-1.5 size-3.5" /> Retry
    </Button>
  {/if}
</div>
