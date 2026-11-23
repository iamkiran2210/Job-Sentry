<script lang="ts">
  import { page } from '$app/state';
  import { compare, setStatus } from '$lib/services/applications';
  import { getJob } from '$lib/services/jobs';
  import { ApiError } from '$lib/services/api-client';
  import { toast } from '$lib/stores/toast.svelte';
  import { toastError } from '$lib/errors';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import ScoreRing from '$lib/components/ScoreRing.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import { ELIGIBILITY_LABEL, type AppStatus, type Eligibility } from '$lib/types/application';
  import { fmtScore, fmtRatio, humanize, shortId, pctNum, isObj } from '$lib/utils';
  import { CATEGORICAL_PALETTE, colorForRatio } from '$lib/viz-colors';

  import * as Table from '$lib/components/ui/table';
  import * as Tabs from '$lib/components/ui/tabs';
  import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '$lib/components/ui/card';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import {
    AlertTriangle,
    ArrowLeft,
    CheckCircle2,
    XCircle,
    HelpCircle,
    ShieldCheck,
    ExternalLink,
    Sparkles,
    BarChart3,
    ListChecks,
    Trophy,
    UserCheck,
    UserX,
    Loader2
  } from '@lucide/svelte';

  interface ComparedApp {
    id: string;
    display_name: string | null;
    status: string;
    total_score: string | number | null;
    lower_bound: string | number | null;
    upper_bound: string | number | null;
    data_completeness: string | number | null;
    eligibility: Eligibility | null;
    rank: number | null;
    verification_status: string | null;
  }

  interface CategoryCell {
    application_id: string;
    match: number | string | null;
    status: string;
    weighted_contribution: string | number | null;
  }

  interface SkillCoverageRow {
    requirement_id: string;
    name: string;
    mandatory: boolean;
    weight: string | number;
    applications: {
      application_id: string;
      result: 'exact' | 'alias' | 'semantic' | 'unknown' | 'none' | string;
      credit: string | number | null;
    }[];
  }

  interface MandatoryCoverageApp {
    application_id: string;
    counts: { met?: number; not_met?: number; unknown?: number };
    requirements: {
      requirement_id?: string;
      name?: string;
      requirement_name?: string;
      status?: string;
      reason?: string;
    }[];
  }

  interface DiffItem {
    type: string;
    description: string;
    application_ids?: string[];
    values?: { application_id: string; match: number | string | null }[];
  }

  const id = page.params.jobId!;
  const ids = (page.url.searchParams.get('ids') ?? '').split(',').filter(Boolean);

  let jobTitle = $state('');
  let data = $state<Record<string, unknown> | null>(null);
  let err = $state('');
  let activeTab = $state<'categories' | 'skills' | 'mandatory'>('categories');
  let updatingId = $state<string | null>(null);

  getJob(id)
    .then((j) => (jobTitle = j.title))
    .catch(() => {});

  async function load() {
    err = '';
    if (ids.length < 2 || ids.length > 4) {
      err = 'Select 2 to 4 applicants on the Applicant Ranking page to compare them side by side.';
      return;
    }
    try {
      data = await compare(id, ids);
    } catch (e) {
      err = e instanceof ApiError ? e.message : 'Comparison failed.';
      toastError(e, 'Comparison failed');
    }
  }

  load();

  const apps = $derived<ComparedApp[]>(
    Array.isArray(data?.applications) ? (data.applications as ComparedApp[]) : []
  );

  const colorOf = (idx: number) => CATEGORICAL_PALETTE[idx % CATEGORICAL_PALETTE.length];

  const nameById = $derived.by(() => {
    const m: Record<string, string> = {};
    for (const a of apps) {
      m[a.id] = a.display_name?.trim() || `Applicant ${shortId(a.id)}`;
    }
    return m;
  });

  const bestScore = $derived.by(() => {
    const vals = apps.map((a) => pctNum(a.total_score)).filter((v): v is number => v !== null);
    return vals.length ? Math.max(...vals) : null;
  });

  const categories = $derived.by(() => {
    const raw = isObj(data?.categories) ? (data.categories as Record<string, CategoryCell[]>) : {};
    return Object.entries(raw).map(([cat, rows]) => {
      const byApp: Record<string, CategoryCell> = {};
      for (const r of rows) byApp[r.application_id] = r;
      const numericMatches = rows
        .map((r) => pctNum(r.match))
        .filter((v): v is number => v !== null);
      const topMatch = numericMatches.length ? Math.max(...numericMatches) : null;
      return { name: cat, byApp, topMatch };
    });
  });

  const skillRows = $derived<SkillCoverageRow[]>(
    Array.isArray(data?.skill_coverage) ? (data.skill_coverage as SkillCoverageRow[]) : []
  );

  const mandatoryByApp = $derived.by(() => {
    const raw = Array.isArray(data?.mandatory_coverage)
      ? (data.mandatory_coverage as MandatoryCoverageApp[])
      : [];
    const map: Record<string, MandatoryCoverageApp> = {};
    for (const item of raw) map[item.application_id] = item;
    return map;
  });

  const mandatoryMatrix = $derived.by(() => {
    const raw = Array.isArray(data?.mandatory_coverage)
      ? (data.mandatory_coverage as MandatoryCoverageApp[])
      : [];
    const reqMap = new Map<string, { label: string; byApp: Record<string, string> }>();
    for (const entry of raw) {
      for (const req of entry.requirements ?? []) {
        const key = String(req.requirement_id ?? req.name ?? req.requirement_name ?? '');
        if (!key) continue;
        const label = String(req.name ?? req.requirement_name ?? shortId(key));
        const cur = reqMap.get(key) ?? { label, byApp: {} };
        cur.byApp[entry.application_id] = String(req.status ?? 'unknown');
        reqMap.set(key, cur);
      }
    }
    return [...reqMap.values()];
  });

  /** Plain-English summary of key differences between the selected candidates. */
  const humanInsights = $derived.by(() => {
    const out: { title: string; detail: string; tone: 'indigo' | 'emerald' | 'amber' }[] = [];

    // 1. Overall score leader
    const scored = apps
      .map((a) => ({ app: a, pct: pctNum(a.total_score) }))
      .filter((x): x is { app: ComparedApp; pct: number } => x.pct !== null)
      .sort((a, b) => b.pct - a.pct);
    if (scored.length >= 2) {
      const top = scored[0];
      const runner = scored[1];
      const gap = Math.round((top.pct - runner.pct) * 10) / 10;
      if (gap >= 1) {
        out.push({
          title: 'Overall match lead',
          detail: `${nameById[top.app.id]} leads with ${top.pct.toFixed(1)}% (+${gap.toFixed(1)} pts ahead of ${nameById[runner.app.id]} at ${runner.pct.toFixed(1)}%).`,
          tone: 'indigo'
        });
      } else {
        out.push({
          title: 'Close overall scores',
          detail: `${nameById[top.app.id]} (${top.pct.toFixed(1)}%) and ${nameById[runner.app.id]} (${runner.pct.toFixed(1)}%) are nearly tied overall.`,
          tone: 'indigo'
        });
      }
    }

    // 2. Biggest category spreads
    for (const cat of categories) {
      const vals = apps
        .map((a) => ({ name: nameById[a.id], pct: pctNum(cat.byApp[a.id]?.match) }))
        .filter((x): x is { name: string; pct: number } => x.pct !== null)
        .sort((a, b) => b.pct - a.pct);
      if (vals.length >= 2 && vals[0].pct - vals[vals.length - 1].pct >= 10) {
        const diff = Math.round((vals[0].pct - vals[vals.length - 1].pct) * 10) / 10;
        out.push({
          title: `${humanize(cat.name)} gap`,
          detail: `${vals[0].name} scores ${vals[0].pct.toFixed(1)}% vs ${vals[vals.length - 1].name} at ${vals[vals.length - 1].pct.toFixed(1)}% (+${diff.toFixed(1)} pts).`,
          tone: 'emerald'
        });
      }
    }

    // 3. Skill coverage differences
    const differingSkills = skillRows.filter((row) => {
      const results = new Set(row.applications.map((a) => a.result));
      return results.size > 1;
    });
    if (differingSkills.length > 0) {
      const preview = differingSkills.slice(0, 4).map((s) => s.name).join(', ');
      out.push({
        title: `${differingSkills.length} differing skill${differingSkills.length === 1 ? '' : 's'}`,
        detail: `Evidence differs on ${preview}${differingSkills.length > 4 ? ` and ${differingSkills.length - 4} more` : ''}.`,
        tone: 'amber'
      });
    }

    // 4. Verification differences
    const verSet = new Set(apps.map((a) => a.verification_status ?? 'not_verified'));
    if (verSet.size > 1) {
      const parts = apps.map((a) => `${nameById[a.id]}: ${humanize(a.verification_status ?? 'not_verified')}`);
      out.push({
        title: 'Verification status differs',
        detail: parts.join(' · '),
        tone: 'amber'
      });
    }

    // Fallback to raw backend descriptions if nothing above triggered
    if (out.length === 0 && Array.isArray(data?.differences)) {
      for (const d of (data.differences as DiffItem[]).slice(0, 4)) {
        if (d.description) {
          out.push({ title: humanize(d.type), detail: d.description, tone: 'indigo' });
        }
      }
    }

    return out.slice(0, 6);
  });

  async function quickDecide(app: ComparedApp, target: AppStatus) {
    if (updatingId) return;
    const label = nameById[app.id];
    if (target === 'rejected') {
      const ok = await confirmDialog({
        title: `Reject ${label}?`,
        message: 'This records a manual rejection decision in the candidate status history.',
        confirmLabel: 'Confirm rejection',
        danger: true
      });
      if (!ok) return;
    }
    updatingId = app.id;
    try {
      await setStatus(
        app.id,
        target,
        target === 'rejected'
          ? 'Rejected after side-by-side applicant comparison'
          : 'Shortlisted after side-by-side applicant comparison'
      );
      toast.success(`${label} marked ${humanize(target)}`);
      await load();
    } catch (e) {
      toastError(e, 'Could not update applicant status');
    } finally {
      updatingId = null;
    }
  }

  function skillPill(result: string): { label: string; cls: string } {
    switch (result) {
      case 'exact':
        return { label: 'Exact match', cls: 'border-emerald-200 bg-emerald-50 text-emerald-700' };
      case 'alias':
        return { label: 'Alias match', cls: 'border-teal-200 bg-teal-50 text-teal-700' };
      case 'semantic':
        return { label: 'Related skill', cls: 'border-sky-200 bg-sky-50 text-sky-700' };
      case 'unknown':
        return { label: 'Not stated', cls: 'border-amber-200 bg-amber-50 text-amber-700' };
      default:
        return { label: 'Not matched', cls: 'border-rose-200 bg-rose-50 text-rose-700' };
    }
  }
</script>

<div class="space-y-6">
  <!-- Clean Header -->
  <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
    <div class="space-y-1">
      <a
        href={`/jobs/${id}/applicants`}
        class="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft class="size-3.5" /> Back to Applicant Ranking
      </a>
      <h1 class="text-3xl font-bold tracking-tight text-foreground">Compare Applicants</h1>
      <p class="text-sm text-muted-foreground">
        Side-by-side evidence comparison{jobTitle ? ` for ${jobTitle}` : ''} · Final hiring decisions stay with you.
      </p>
    </div>

    <Button variant="outline" size="sm" href={`/jobs/${id}/applicants`} class="shrink-0">
      <ArrowLeft class="mr-1.5 size-3.5" /> Change selection
    </Button>
  </div>

  {#if err}
    <Alert variant="destructive">
      <AlertTriangle class="size-4" />
      <AlertTitle>Cannot compare applicants</AlertTitle>
      <AlertDescription class="mt-2 flex flex-wrap items-center justify-between gap-3">
        <span>{err}</span>
        <Button variant="outline" size="sm" href={`/jobs/${id}/applicants`}>Back to ranking</Button>
      </AlertDescription>
    </Alert>
  {:else if !data}
    <Skeleton rows={4} cols={2} height="h-36" />
  {:else}
    <!-- 1. Side-by-Side Candidate Overview Cards -->
    <div class={`grid gap-4 ${apps.length === 2 ? 'md:grid-cols-2' : apps.length === 3 ? 'md:grid-cols-3' : 'md:grid-cols-2 xl:grid-cols-4'}`}>
      {#each apps as app, idx (app.id)}
        {@const clr = colorOf(idx)}
        {@const pct = pctNum(app.total_score)}
        {@const isLeader = bestScore !== null && pct !== null && pct === bestScore}
        {@const mand = mandatoryByApp[app.id]?.counts}
        <Card
          class="border-border bg-card shadow-sm overflow-hidden flex flex-col justify-between"
          style={`border-top: 3px solid ${clr}`}
        >
          <CardContent class="p-5 space-y-4">
            <!-- Name + Rank + Leader pill -->
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0 space-y-1">
                <div class="flex items-center gap-2">
                  <span class="h-2.5 w-2.5 rounded-full shrink-0" style={`background:${clr}`} aria-hidden="true"></span>
                  <a
                    href={`/jobs/${id}/applicants/${app.id}`}
                    class="text-base font-bold text-foreground hover:text-primary hover:underline truncate"
                    title={nameById[app.id]}
                  >
                    {nameById[app.id]}
                  </a>
                </div>
                <div class="flex flex-wrap items-center gap-1.5">
                  {#if app.rank != null}
                    <Badge variant="secondary" class="text-[11px] font-mono">Rank #{app.rank}</Badge>
                  {/if}
                  <StatusBadge status={app.status} />
                  {#if isLeader}
                    <Badge variant="outline" class="border-emerald-200 bg-emerald-50 text-emerald-700 text-[11px] font-semibold">
                      <Trophy class="mr-1 size-3" /> Top score
                    </Badge>
                  {/if}
                </div>
              </div>

              <ScoreRing value={pct} label="Match" />
            </div>

            <!-- Key Structured Metrics -->
            <dl class="grid grid-cols-2 gap-2.5 rounded-lg bg-muted/30 p-3 text-xs">
              <div>
                <dt class="text-muted-foreground">Confidence</dt>
                <dd class="mt-0.5 font-mono font-semibold text-foreground">
                  {fmtScore(app.lower_bound)} – {fmtScore(app.upper_bound)}
                </dd>
              </div>
              <div>
                <dt class="text-muted-foreground">Completeness</dt>
                <dd class="mt-0.5 font-semibold text-foreground tabular-nums">
                  {fmtRatio(app.data_completeness)}
                </dd>
              </div>
              <div>
                <dt class="text-muted-foreground">Mandatory</dt>
                <dd class="mt-0.5 font-semibold text-foreground">
                  {#if mand && ((mand.met ?? 0) + (mand.not_met ?? 0) + (mand.unknown ?? 0)) > 0}
                    {mand.met ?? 0}/{(mand.met ?? 0) + (mand.not_met ?? 0) + (mand.unknown ?? 0)} met
                  {:else}
                    {app.eligibility === 'eligible' ? 'Meets' : app.eligibility === 'needs_review' ? 'Review' : 'Check'}
                  {/if}
                </dd>
              </div>
              <div>
                <dt class="text-muted-foreground">Verification</dt>
                <dd class="mt-0.5 inline-flex items-center gap-1 font-semibold text-foreground">
                  <ShieldCheck class="size-3 text-primary" />
                  {humanize(app.verification_status ?? 'not_verified')}
                </dd>
              </div>
            </dl>

            <!-- Direct Recruiter Actions -->
            <div class="flex flex-wrap items-center gap-2 pt-1 border-t border-border/60">
              <Button
                size="sm"
                variant={app.status === 'shortlisted' ? 'secondary' : 'default'}
                disabled={updatingId !== null || app.status === 'shortlisted'}
                onclick={() => quickDecide(app, 'shortlisted')}
                class="h-7 px-2.5 text-xs flex-1"
              >
                {#if updatingId === app.id}
                  <Loader2 class="mr-1 size-3 animate-spin" />
                {:else}
                  <UserCheck class="mr-1 size-3.5" />
                {/if}
                {app.status === 'shortlisted' ? 'Shortlisted' : 'Shortlist'}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={updatingId !== null || app.status === 'rejected'}
                onclick={() => quickDecide(app, 'rejected')}
                class="h-7 px-2.5 text-xs text-destructive border-destructive/30 hover:bg-destructive/10"
              >
                <UserX class="mr-1 size-3.5" />
                {app.status === 'rejected' ? 'Rejected' : 'Reject'}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                href={`/jobs/${id}/applicants/${app.id}`}
                class="h-7 px-2 text-xs"
                title="Open full applicant analysis"
              >
                Details <ExternalLink class="ml-1 size-3" />
              </Button>
            </div>
          </CardContent>
        </Card>
      {/each}
    </div>

    <!-- 2. Plain-English Key Takeaways -->
    <Card class="border-border bg-card shadow-sm">
      <CardHeader class="pb-3 border-b border-border/60">
        <div class="flex items-center gap-2">
          <Sparkles class="size-4 text-primary" />
          <CardTitle class="text-base font-semibold">Key Differences at a Glance</CardTitle>
        </div>
        <CardDescription class="text-xs">
          Plain-English summary of where these applicants stand apart.
        </CardDescription>
      </CardHeader>
      <CardContent class="pt-4">
        {#if humanInsights.length === 0}
          <p class="text-sm text-muted-foreground">
            Selected candidates are closely aligned across all evaluated criteria.
          </p>
        {:else}
          <div class="grid gap-3 md:grid-cols-2">
            {#each humanInsights as insight}
              <div
                class={`rounded-lg border p-3.5 space-y-1 ${
                  insight.tone === 'emerald'
                    ? 'border-emerald-200/70 bg-emerald-50/40'
                    : insight.tone === 'amber'
                      ? 'border-amber-200/70 bg-amber-50/40'
                      : 'border-indigo-200/70 bg-indigo-50/40'
                }`}
              >
                <div class="text-xs font-semibold text-foreground">{insight.title}</div>
                <p class="text-xs text-muted-foreground leading-relaxed">{insight.detail}</p>
              </div>
            {/each}
          </div>
        {/if}
      </CardContent>
    </Card>

    <!-- 3. Clean Tabbed Comparison Matrices (No raw UUIDs or JSON dumps) -->
    <Tabs.Root bind:value={activeTab} class="space-y-4">
      <Tabs.List class="grid w-full sm:w-auto grid-cols-3 h-auto">
        <Tabs.Trigger value="categories" class="text-xs sm:text-sm py-2 px-4">
          <BarChart3 class="mr-1.5 size-3.5 hidden sm:inline" />
          Category Scores ({categories.length})
        </Tabs.Trigger>
        <Tabs.Trigger value="skills" class="text-xs sm:text-sm py-2 px-4">
          <Sparkles class="mr-1.5 size-3.5 hidden sm:inline" />
          Skills Matrix ({skillRows.length})
        </Tabs.Trigger>
        <Tabs.Trigger value="mandatory" class="text-xs sm:text-sm py-2 px-4">
          <ListChecks class="mr-1.5 size-3.5 hidden sm:inline" />
          Mandatory Checks ({mandatoryMatrix.length})
        </Tabs.Trigger>
      </Tabs.List>

      <!-- TAB A: CATEGORY SCORES MATRIX -->
      <Tabs.Content value="categories">
        <Card class="border-border bg-card shadow-sm overflow-hidden">
          <div class="overflow-x-auto">
            <Table.Root>
              <Table.Header>
                <Table.Row class="bg-muted/30">
                  <Table.Head class="text-left font-semibold text-foreground min-w-[160px]">Category</Table.Head>
                  {#each apps as app, idx (app.id)}
                    <Table.Head class="text-left font-semibold text-foreground min-w-[170px]">
                      <span class="inline-flex items-center gap-2">
                        <span class="h-2.5 w-2.5 rounded-full shrink-0" style={`background:${colorOf(idx)}`}></span>
                        <span class="truncate max-w-[150px]">{nameById[app.id]}</span>
                      </span>
                    </Table.Head>
                  {/each}
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#if categories.length === 0}
                  <Table.Row>
                    <Table.Cell colspan={apps.length + 1} class="py-8 text-center text-sm text-muted-foreground">
                      No category score breakdown available.
                    </Table.Cell>
                  </Table.Row>
                {:else}
                  {#each categories as cat}
                    <Table.Row class="hover:bg-muted/20">
                      <Table.Cell class="font-semibold text-foreground">{humanize(cat.name)}</Table.Cell>
                      {#each apps as app (app.id)}
                        {@const cell = cat.byApp[app.id]}
                        {@const cellPct = cell?.status === 'known' ? pctNum(cell.match) : null}
                        {@const barClr = cellPct !== null ? colorForRatio(cellPct / 100) : '#94A3B8'}
                        {@const isTop = cat.topMatch !== null && cellPct !== null && cellPct === cat.topMatch && apps.length > 1}
                        <Table.Cell>
                          {#if cellPct !== null}
                            <div class="space-y-1">
                              <div class="flex items-center justify-between gap-2 text-xs">
                                <span class="font-bold tabular-nums" style={`color:${barClr}`}>
                                  {cellPct.toFixed(1)}%
                                </span>
                                {#if isTop}
                                  <span class="rounded bg-emerald-50 border border-emerald-200 px-1.5 py-0 text-[10px] font-semibold text-emerald-700">
                                    Best
                                  </span>
                                {/if}
                              </div>
                              <div class="h-2 w-full rounded-full bg-muted overflow-hidden">
                                <div
                                  class="h-full rounded-full"
                                  style={`width:${Math.min(100, Math.max(0, cellPct))}%; background:${barClr}`}
                                ></div>
                              </div>
                            </div>
                          {:else}
                            <span class="text-xs text-muted-foreground">Not stated</span>
                          {/if}
                        </Table.Cell>
                      {/each}
                    </Table.Row>
                  {/each}
                {/if}
              </Table.Body>
            </Table.Root>
          </div>
        </Card>
      </Tabs.Content>

      <!-- TAB B: SKILLS MATRIX -->
      <Tabs.Content value="skills">
        <Card class="border-border bg-card shadow-sm overflow-hidden">
          <div class="overflow-x-auto">
            <Table.Root>
              <Table.Header>
                <Table.Row class="bg-muted/30">
                  <Table.Head class="text-left font-semibold text-foreground min-w-[200px]">Required Skill</Table.Head>
                  {#each apps as app, idx (app.id)}
                    <Table.Head class="text-center font-semibold text-foreground min-w-[150px]">
                      <span class="inline-flex items-center justify-center gap-2">
                        <span class="h-2.5 w-2.5 rounded-full shrink-0" style={`background:${colorOf(idx)}`}></span>
                        <span class="truncate max-w-[130px]">{nameById[app.id]}</span>
                      </span>
                    </Table.Head>
                  {/each}
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#if skillRows.length === 0}
                  <Table.Row>
                    <Table.Cell colspan={apps.length + 1} class="py-8 text-center text-sm text-muted-foreground">
                      No skill requirements configured for this job.
                    </Table.Cell>
                  </Table.Row>
                {:else}
                  {#each skillRows as row (row.requirement_id)}
                    {@const byApp = Object.fromEntries(row.applications.map((a) => [a.application_id, a]))}
                    <Table.Row class="hover:bg-muted/20">
                      <Table.Cell>
                        <div class="flex items-center gap-2">
                          <span class="font-medium text-foreground">{row.name}</span>
                          <Badge
                            variant="outline"
                            class={`text-[10px] px-1.5 py-0 ${
                              row.mandatory
                                ? 'border-rose-200 bg-rose-50 text-rose-700'
                                : 'border-sky-200 bg-sky-50 text-sky-700'
                            }`}
                          >
                            {row.mandatory ? 'Mandatory' : `${Math.round(Number(row.weight) <= 1 ? Number(row.weight) * 100 : Number(row.weight))}%`}
                          </Badge>
                        </div>
                      </Table.Cell>
                      {#each apps as app (app.id)}
                        {@const cell = byApp[app.id]}
                        {@const pill = skillPill(cell?.result ?? 'none')}
                        <Table.Cell class="text-center">
                          <Badge variant="outline" class={`text-[11px] font-medium ${pill.cls}`}>
                            {pill.label}
                          </Badge>
                        </Table.Cell>
                      {/each}
                    </Table.Row>
                  {/each}
                {/if}
              </Table.Body>
            </Table.Root>
          </div>
        </Card>
      </Tabs.Content>

      <!-- TAB C: MANDATORY CRITERIA MATRIX -->
      <Tabs.Content value="mandatory">
        <Card class="border-border bg-card shadow-sm overflow-hidden">
          <div class="overflow-x-auto">
            <Table.Root>
              <Table.Header>
                <Table.Row class="bg-muted/30">
                  <Table.Head class="text-left font-semibold text-foreground min-w-[200px]">Mandatory Requirement</Table.Head>
                  {#each apps as app, idx (app.id)}
                    <Table.Head class="text-center font-semibold text-foreground min-w-[150px]">
                      <span class="inline-flex items-center justify-center gap-2">
                        <span class="h-2.5 w-2.5 rounded-full shrink-0" style={`background:${colorOf(idx)}`}></span>
                        <span class="truncate max-w-[130px]">{nameById[app.id]}</span>
                      </span>
                    </Table.Head>
                  {/each}
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {#if mandatoryMatrix.length === 0}
                  <Table.Row>
                    <Table.Cell colspan={apps.length + 1} class="py-8 text-center text-sm text-muted-foreground">
                      No mandatory requirements configured for this job.
                    </Table.Cell>
                  </Table.Row>
                {:else}
                  {#each mandatoryMatrix as row}
                    <Table.Row class="hover:bg-muted/20">
                      <Table.Cell class="font-medium text-foreground">{row.label}</Table.Cell>
                      {#each apps as app (app.id)}
                        {@const status = row.byApp[app.id] ?? 'unknown'}
                        <Table.Cell class="text-center">
                          {#if status === 'met'}
                            <span class="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700">
                              <CheckCircle2 class="size-3.5" /> Met
                            </span>
                          {:else if status === 'not_met'}
                            <span class="inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50 px-2.5 py-0.5 text-xs font-medium text-rose-700">
                              <XCircle class="size-3.5" /> Not met
                            </span>
                          {:else}
                            <span class="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-700">
                              <HelpCircle class="size-3.5" /> Needs review
                            </span>
                          {/if}
                        </Table.Cell>
                      {/each}
                    </Table.Row>
                  {/each}
                {/if}
              </Table.Body>
            </Table.Root>
          </div>
        </Card>
      </Tabs.Content>
    </Tabs.Root>

    <!-- Subtle Disclaimer Footer -->
    {#if Array.isArray(data.disclaimers) && data.disclaimers.length}
      <p class="text-xs text-muted-foreground px-1">
        {data.disclaimers.filter((d) => typeof d === 'string').join(' · ')}
      </p>
    {/if}
  {/if}
</div>
