<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import {
    getAnalysis,
    getStatusHistory,
    runRanking,
    setStatus,
    verifyApplication,
    notifyCandidate,
    deleteApplication
  } from '$lib/services/applications';
  import { ApiError } from '$lib/services/api-client';
  import { toast } from '$lib/stores/toast.svelte';
  import { toastError } from '$lib/errors';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import CandidateProfile from '$lib/components/profile/CandidateProfile.svelte';
  import ScoreRing from '$lib/components/ScoreRing.svelte';
  import BarList from '$lib/components/BarList.svelte';
  import {
    ELIGIBILITY_LABEL,
    DEFAULT_DECISION_AGENTS,
    DECISION_OUTCOME_LABEL,
    type Analysis,
    type AppStatus,
    type DecisionAgentId,
    type DecisionOutcome
  } from '$lib/types/application';
  import { fmtScore, fmtRatio, humanize, pctNum, nameOf, fmtDate } from '$lib/utils';
  import { colorForLabel } from '$lib/viz-colors';

  import * as Table from '$lib/components/ui/table';
  import * as Select from '$lib/components/ui/select';
  import * as Tabs from '$lib/components/ui/tabs';
  import * as Collapsible from '$lib/components/ui/collapsible';
  import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
  import { Checkbox } from '$lib/components/ui/checkbox';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Label } from '$lib/components/ui/label';
  import { Badge } from '$lib/components/ui/badge';
  import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '$lib/components/ui/card';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import {
    ShieldCheck,
    CheckCircle2,
    AlertTriangle,
    Loader2,
    UserCheck,
    Play,
    Trash2,
    Mail,
    SlidersHorizontal,
    ChevronDown,
    ChevronUp,
    MoreHorizontal,
    ArrowLeft,
    UserRound,
    Bot,
    BarChart3,
    FileText
  } from '@lucide/svelte';

  const { jobId, applicationId } = page.params as { jobId: string; applicationId: string };
  let a = $state<Analysis | null>(null);
  let history = $state<Record<string, unknown>[] | null>(null);
  let st = $state<'loading' | 'ready' | 'error'>('loading');
  let msg = $state('');
  let busy = $state(false);
  let busyOp = $state<'verify' | 'rank' | 'status' | 'notify' | 'delete' | null>(null);

  let showRankOpts = $state(false);
  let forceVerifyOnRank = $state(false);
  let autoApplyOnRank = $state(false);
  let minAcceptThreshold = $state('65');

  let sectionTab = $state<'evaluation' | 'breakdown' | 'profile'>('evaluation');
  let profileTab = $state('overview');
  let selectedAgent = $state<DecisionAgentId>('balanced');
  let next = $state<AppStatus>('shortlisted');
  let reason = $state('');

  const statusHistory = $derived((history ?? a?.application.status_history) as Record<string, unknown>[] | undefined);
  const activeDecision = $derived(
    a?.agent_decisions?.[selectedAgent] ?? a?.decision ?? null
  );

  const decisionBadgeClass = (d?: DecisionOutcome | string | null): string => {
    switch (d) {
      case 'strong_advance':
        return 'bg-emerald-100 text-emerald-800 border-emerald-200';
      case 'advance':
        return 'bg-sky-100 text-sky-800 border-sky-200';
      case 'review':
        return 'bg-amber-100 text-amber-800 border-amber-200';
      case 'hold':
        return 'bg-slate-100 text-slate-700 border-slate-200';
      case 'pass':
        return 'bg-rose-100 text-rose-800 border-rose-200';
      default:
        return 'bg-muted text-muted-foreground border-border';
    }
  };

  function jumpToVerification() {
    sectionTab = 'profile';
    profileTab = 'ai data';
    setTimeout(() => {
      document.getElementById('verification-review')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 80);
  }

  type FormattedAiPoint = { text: string; evidenceCount: number };
  type FormattedAiSummary = {
    overview: string | null;
    strengths: FormattedAiPoint[];
    gaps: FormattedAiPoint[];
    extras: { label: string; text: string }[];
  };

  function cleanText(raw: string): string {
    return raw
      .replace(/\(?\b(?:evidence[_\s-]?ids?|ev-[a-z0-9-]+)\b[:\s]*[a-z0-9,-]*\)?/gi, '')
      .replace(/_/g, ' ')
      .replace(/\s+/g, ' ')
      .replace(/\s+([.,;:])/g, '$1')
      .trim();
  }

  function toAiPoints(val: unknown): FormattedAiPoint[] {
    if (!Array.isArray(val)) return [];
    const out: FormattedAiPoint[] = [];
    for (const item of val) {
      if (typeof item === 'string' && item.trim()) {
        out.push({ text: cleanText(item), evidenceCount: 0 });
      } else if (item && typeof item === 'object') {
        const obj = item as Record<string, unknown>;
        const txt =
          typeof obj.text === 'string'
            ? obj.text
            : typeof obj.description === 'string'
              ? obj.description
              : typeof obj.summary === 'string'
                ? obj.summary
                : '';
        const ev = Array.isArray(obj.evidence_ids) ? obj.evidence_ids.length : 0;
        if (txt.trim()) out.push({ text: cleanText(txt), evidenceCount: ev });
      }
    }
    return out;
  }

  const formattedAiSummary = $derived.by((): FormattedAiSummary | null => {
    const raw: unknown = a?.explanation?.ai_summary;
    if (!raw) return null;
    let obj: Record<string, unknown> | null = null;
    if (typeof raw === 'string') {
      const trimmed = raw.trim();
      if (!trimmed) return null;
      if (trimmed.startsWith('{')) {
        try {
          const parsed = JSON.parse(trimmed);
          if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            obj = parsed as Record<string, unknown>;
          }
        } catch {
          /* plain prose string */
        }
      }
      if (!obj) {
        return { overview: cleanText(trimmed), strengths: [], gaps: [], extras: [] };
      }
    } else if (typeof raw === 'object' && !Array.isArray(raw)) {
      obj = raw as Record<string, unknown>;
    }
    if (!obj) return null;

    const overview =
      typeof obj.summary === 'string' && obj.summary.trim() ? cleanText(obj.summary) : null;
    const strengths = toAiPoints(obj.strengths);
    const gaps = toAiPoints(obj.gaps);
    const extras: { label: string; text: string }[] = [];
    for (const [k, v] of Object.entries(obj)) {
      if (k === 'summary' || k === 'strengths' || k === 'gaps' || v == null) continue;
      if (typeof v === 'string' && v.trim()) {
        extras.push({ label: humanize(k), text: cleanText(v) });
      } else if (Array.isArray(v)) {
        const joined = v
          .map((x) =>
            typeof x === 'string'
              ? cleanText(x)
              : x && typeof x === 'object' && typeof (x as Record<string, unknown>).text === 'string'
                ? cleanText(String((x as Record<string, unknown>).text))
                : ''
          )
          .filter(Boolean)
          .join(' · ');
        if (joined) extras.push({ label: humanize(k), text: joined });
      }
    }
    if (!overview && !strengths.length && !gaps.length && !extras.length) return null;
    return { overview, strengths, gaps, extras };
  });

  async function load() {
    try {
      a = await getAnalysis(applicationId);
      st = 'ready';
      getStatusHistory(applicationId)
        .then((h) => (history = h))
        .catch(() => (history = null));
    } catch (e) {
      msg = e instanceof ApiError ? e.message : 'Failed to load analysis.';
      st = 'error';
      toastError(e, 'Could not load analysis');
    }
  }

  load();

  async function run(op: 'verify' | 'rank' | 'status', fn: () => Promise<unknown>) {
    if (busy) return;
    busy = true;
    busyOp = op;
    msg = '';
    try {
      await fn();
      await load();
    } catch (e) {
      toastError(e);
    } finally {
      busy = false;
      busyOp = null;
    }
  }

  const USER_DECISION_STATUSES: AppStatus[] = ['shortlisted', 'rejected', 'withdrawn', 'analyzed'];

  const changeStatus = async () => {
    if (next === 'rejected' && !reason.trim()) {
      toast.error('Reason required', 'Please provide decision notes before rejecting an application.');
      return;
    }
    if (
      next === 'rejected' &&
      !(await confirmDialog({
        title: 'Reject this application?',
        message:
          'This is your manual decision, not an automated system rejection. This action will be permanently recorded in the candidate status history.',
        confirmLabel: 'Confirm rejection',
        danger: true
      }))
    ) {
      return;
    }
    return run('status', async () => {
      await setStatus(applicationId, next, reason);
      reason = '';
      toast.success(`Application status updated to ${humanize(next)}`);
    });
  };

  const runVerify = () =>
    run('verify', async () => {
      await verifyApplication(applicationId);
      toast.success(
        'Verification checks completed',
        'Includes email domain MX, content authenticity, LinkedIn, GitHub, portfolio, and project link checks.'
      );
    });

  async function sendNotification() {
    if (busy) return;
    busy = true;
    busyOp = 'notify';
    try {
      const res = await notifyCandidate(applicationId, {
        outcome: a?.application.status === 'rejected' ? 'rejected' : 'shortlisted',
        feedback: activeDecision?.summary,
        include_score: true
      });
      if (res.delivered) {
        toast.success('Candidate email sent', `${res.subject} — ${res.reason}`);
      } else if (res.channel === 'sendpulse_failed' || res.channel === 'smtp_failed' || res.channel === 'skipped') {
        toast.error('Candidate email not sent', res.reason);
      } else {
        toast.info('Notification recorded (Audit Outbox)', `${res.subject} — ${res.reason}`);
      }
    } catch (e) {
      toastError(e, 'Could not notify candidate');
    } finally {
      busy = false;
      busyOp = null;
    }
  }

  const runIndividualRank = () =>
    run('rank', async () => {
      const parsedThreshold = minAcceptThreshold.trim() !== '' ? Number(minAcceptThreshold) : undefined;
      const res = await runRanking(jobId, {
        applicationIds: [applicationId],
        force: true,
        forceVerify: forceVerifyOnRank,
        decisionAgent: selectedAgent,
        minAcceptThreshold:
          parsedThreshold !== undefined && Number.isFinite(parsedThreshold)
            ? parsedThreshold
            : undefined,
        autoApplyDecisions: autoApplyOnRank
      });
      const verified = typeof res?.verified_count === 'number' && res.verified_count > 0;
      const autoApplied = typeof res?.auto_applied_count === 'number' ? res.auto_applied_count : 0;
      const notifSent = typeof res?.notifications_sent === 'number' ? res.notifications_sent : 0;
      const notifFailed = typeof res?.notifications_failed === 'number' ? res.notifications_failed : 0;
      const notifResults = Array.isArray(res?.notification_results)
        ? (res.notification_results as { channel?: string; reason?: string }[])
        : [];
      if (notifFailed > 0) {
        const errReason =
          notifResults.find((n) => n.channel === 'sendpulse_failed' || n.channel === 'smtp_failed')?.reason ??
          'Check SendPulse settings in backend/.env.';
        toast.error('Applicant ranked, but email failed', errReason);
        return;
      }
      const parts: string[] = [
        verified
          ? 'Score, relative rank, and verification checks refreshed.'
          : 'Score and relative rank refreshed for this applicant.'
      ];
      if (autoApplyOnRank) {
        if (autoApplied > 0) parts.push('Status auto-updated.');
        if (notifSent > 0) parts.push('Candidate notified via SendPulse.');
        else if (notifResults.some((n) => n.channel === 'audit_outbox'))
          parts.push('Notification logged to Audit Outbox.');
      }
      toast.success('Applicant ranked', parts.join(' '));
    });

  async function removeApplication() {
    if (busy) return;
    const label = nameOf(a?.candidate) ?? nameOf(a?.candidate?.profile) ?? 'this applicant';
    const ok = await confirmDialog({
      title: 'Delete resume application?',
      message: `This permanently deletes the application and uploaded resume for ${label} from this job. Audit history entries (if already ranked) are preserved without candidate data.`,
      confirmLabel: 'Delete application',
      danger: true
    });
    if (!ok) return;
    busy = true;
    busyOp = 'delete';
    try {
      await deleteApplication(applicationId);
      toast.success('Application deleted', `${label} has been removed from this job.`);
      goto(`/jobs/${jobId}/applicants`);
    } catch (e) {
      toastError(e, 'Could not delete application');
    } finally {
      busy = false;
      busyOp = null;
    }
  }

  const catLabel: Record<string, string> = {
    known: 'Assessed',
    unknown: 'Missing information',
    not_applicable: 'Not applicable'
  };

  function parseExplanationItem(raw: string): { heading: string; body: string } {
    const clean = raw.replace(/_/g, ' ').trim();
    const idx = clean.indexOf(':');
    if (idx === -1) return { heading: '', body: clean };
    const heading = humanize(clean.slice(0, idx).trim());
    let body = clean.slice(idx + 1).trim();
    body = body
      .replace(/^match\s+(?:None|unknown)\s*\(([^)]+)\);\s*/i, (_, st) => `Not scored (${humanize(st)}) · `)
      .replace(/^match\s+([0-9.]+)\s*\(([^)]+)\);\s*/i, (_, val, st) => {
        const label = catLabel[st.replace(/\s+/g, '_').toLowerCase()] ?? humanize(st);
        return `Match ${fmtScore(Number(val))} (${label}) · `;
      })
      .replace(/;\s*/g, ' · ');
    return { heading, body };
  }

  const NP = 'Not provided';
</script>

{#if st === 'loading'}
  <Skeleton rows={4} height="h-28" />
{:else if st === 'error'}
  <Alert variant="destructive">
    <AlertTriangle class="size-4" />
    <AlertTitle>Error loading candidate analysis</AlertTitle>
    <AlertDescription>{msg}</AlertDescription>
  </Alert>
{:else if a}
  {@const candidateName = nameOf(a.candidate) ?? nameOf(a.candidate.profile) ?? 'Unnamed candidate'}
  {@const eligColor = colorForLabel(a.eligibility ?? 'pending', 0)}
  <div class="space-y-5">
    <!-- Top Bar: Back Link & Hero Header -->
    <Card class="border-border bg-card shadow-sm">
      <CardContent class="p-5 space-y-4">
        <div class="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
          <div class="space-y-2 min-w-0">
            <a
              href={`/jobs/${jobId}/applicants`}
              class="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft class="size-3.5" /> Back to Applicant Ranking
            </a>

            <div class="flex flex-wrap items-center gap-2.5">
              <h1 class="text-2xl sm:text-3xl font-bold tracking-tight text-foreground truncate">
                {candidateName}
              </h1>
              <StatusBadge status={a.application.status} />
              {#if a.verification_detail?.overall_status}
                <button
                  type="button"
                  onclick={jumpToVerification}
                  class="inline-flex items-center gap-1 rounded-full border border-border bg-muted/40 px-2.5 py-0.5 text-xs font-medium text-foreground hover:bg-muted transition-colors cursor-pointer"
                  title="Jump to detailed verification output"
                >
                  <ShieldCheck class="size-3.5 text-primary" />
                  <span>{humanize(a.verification_detail.overall_status)}</span>
                </button>
              {/if}
              {#if a.verification_detail?.fraud_risk}
                {@const fr = a.verification_detail.fraud_risk}
                <button
                  type="button"
                  onclick={jumpToVerification}
                  class={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold cursor-pointer ${
                    fr.level === 'high'
                      ? 'border-rose-200 bg-rose-50 text-rose-800'
                      : fr.level === 'medium'
                        ? 'border-amber-200 bg-amber-50 text-amber-800'
                        : 'border-emerald-200 bg-emerald-50 text-emerald-800'
                  }`}
                  title="Composite fraud & authenticity risk score (0–100)"
                >
                  <span>Risk: {humanize(fr.level)} ({fr.score}/100)</span>
                </button>
              {/if}
            </div>

            <p class="text-sm text-muted-foreground">
              Applying for <strong class="text-foreground">{a.application.job_title}</strong>
              · {a.candidate.email ?? NP}
              {#if a.candidate.phone}
                · {a.candidate.phone}
              {/if}
            </p>
          </div>

          <!-- Clean Grouped Action Toolbar -->
          <div class="flex flex-wrap items-center gap-2 shrink-0">
            <Button size="sm" disabled={busy} onclick={runIndividualRank}>
              {#if busy && busyOp === 'rank'}
                <Loader2 class="mr-1.5 size-3.5 animate-spin" />
                Ranking…
              {:else}
                <Play class="mr-1.5 size-3.5 fill-current" />
                Rank applicant
              {/if}
            </Button>

            <Button
              variant={autoApplyOnRank ? 'secondary' : 'outline'}
              size="sm"
              onclick={() => (showRankOpts = !showRankOpts)}
              aria-expanded={showRankOpts}
            >
              <SlidersHorizontal class="mr-1.5 size-3.5" />
              Options{autoApplyOnRank ? ` (≥ ${minAcceptThreshold || 65}%)` : ''}
              {#if showRankOpts}
                <ChevronUp class="ml-1 size-3.5" />
              {:else}
                <ChevronDown class="ml-1 size-3.5" />
              {/if}
            </Button>

            <Button variant="outline" size="sm" disabled={busy} onclick={runVerify}>
              {#if busy && busyOp === 'verify'}
                <Loader2 class="mr-1.5 size-3.5 animate-spin" />
                Verifying…
              {:else}
                <ShieldCheck class="mr-1.5 size-3.5 text-primary" />
                Verify
              {/if}
            </Button>

            <Button variant="outline" size="sm" disabled={busy} onclick={sendNotification}>
              {#if busy && busyOp === 'notify'}
                <Loader2 class="mr-1.5 size-3.5 animate-spin" />
                Sending…
              {:else}
                <Mail class="mr-1.5 size-3.5 text-primary" />
                Notify
              {/if}
            </Button>

            <DropdownMenu.Root>
              <DropdownMenu.Trigger>
                {#snippet child({ props })}
                  <Button {...props} variant="ghost" size="icon" class="size-8" aria-label="More applicant actions">
                    <MoreHorizontal class="size-4" />
                  </Button>
                {/snippet}
              </DropdownMenu.Trigger>
              <DropdownMenu.Content align="end" class="w-48">
                {#if a.candidate?.id}
                  <DropdownMenu.Item onclick={() => goto(`/candidates/${a!.candidate.id}`)}>
                    <UserRound class="mr-2 size-4 text-muted-foreground" />
                    <span>Manage candidate</span>
                  </DropdownMenu.Item>
                {/if}
                <DropdownMenu.Item
                  onclick={removeApplication}
                  disabled={busy}
                  class="text-destructive focus:text-destructive"
                >
                  <Trash2 class="mr-2 size-4" />
                  <span>Delete application</span>
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Root>
          </div>
        </div>

        <!-- Collapsible Individual Ranking Options -->
        <Collapsible.Root bind:open={showRankOpts}>
          <Collapsible.Content>
            <div class="pt-3 mt-1 border-t border-border/70 flex flex-wrap items-center justify-between gap-4">
              <div class="flex flex-wrap items-center gap-4 text-xs">
                <div class="flex items-center gap-2">
                  <Label for="ind-threshold" class="text-xs font-medium text-muted-foreground whitespace-nowrap">
                    Min accept threshold (%)
                  </Label>
                  <Input
                    id="ind-threshold"
                    type="number"
                    min="0"
                    max="100"
                    bind:value={minAcceptThreshold}
                    class="h-7 w-20 text-xs"
                  />
                </div>
                <label class="flex items-center gap-1.5 text-foreground cursor-pointer select-none">
                  <Checkbox id="individual-auto-apply" bind:checked={autoApplyOnRank} />
                  <span>Auto-apply decision &amp; notify</span>
                </label>
                <label class="flex items-center gap-1.5 text-foreground cursor-pointer select-none">
                  <Checkbox id="individual-force-verify" bind:checked={forceVerifyOnRank} />
                  <span>Re-verify profile</span>
                </label>
              </div>
              <span class="text-[11px] text-muted-foreground">
                Uses active agent ({DEFAULT_DECISION_AGENTS.find((x) => x.id === selectedAgent)?.short_name ?? 'Balanced'}) against peers.
              </span>
            </div>
          </Collapsible.Content>
        </Collapsible.Root>
      </CardContent>
    </Card>

    {#if msg}
      <Alert variant="destructive">
        <AlertTriangle class="size-4" />
        <AlertDescription>{msg}</AlertDescription>
      </Alert>
    {/if}

    <!-- Evenly Aligned KPI Overview Strip -->
    <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Card class="border-border bg-card shadow-sm overflow-hidden" style="border-top: 3px solid #4F46E5">
        <CardContent class="p-4 flex items-center justify-between gap-3 h-full">
          <div class="space-y-1 min-w-0">
            <div class="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Job Match Score
            </div>
            <div class="text-xs text-muted-foreground">
              Range:
              <span class="font-mono font-semibold text-foreground">
                {fmtScore(a.score_lower_bound)} – {fmtScore(a.score_upper_bound)}
              </span>
            </div>
          </div>
          <ScoreRing
            value={a.score_percent != null ? pctNum(a.score_percent, true) : pctNum(a.score ?? a.overall_score)}
            label="Match"
          />
        </CardContent>
      </Card>

      <Card class="border-border bg-card shadow-sm overflow-hidden" style={`border-top: 3px solid ${eligColor}`}>
        <CardContent class="p-4 flex flex-col justify-between h-full space-y-1.5">
          <div class="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Mandatory Requirements
          </div>
          <div class="text-lg font-bold leading-snug" style={`color: ${eligColor}`}>
            {a.eligibility ? (ELIGIBILITY_LABEL[a.eligibility] ?? humanize(a.eligibility)) : 'Pending'}
          </div>
          <p class="text-xs text-muted-foreground">
            {#if a.mandatory_coverage_pct != null}
              Coverage: <strong class="text-foreground">{Number(a.mandatory_coverage_pct).toFixed(0)}%</strong>
            {:else}
              Evaluated before preferred weights
            {/if}
          </p>
        </CardContent>
      </Card>

      <Card class="border-border bg-card shadow-sm overflow-hidden" style="border-top: 3px solid #0EA5E9">
        <CardContent class="p-4 flex flex-col justify-between h-full space-y-1.5">
          <div class="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            AI Recommendation
          </div>
          {#if activeDecision}
            <div class="flex flex-wrap items-center gap-2">
              <Badge variant="outline" class={`text-xs font-semibold ${decisionBadgeClass(activeDecision.decision)}`}>
                {DECISION_OUTCOME_LABEL[activeDecision.decision] ?? humanize(activeDecision.decision)}
              </Badge>
              <span class="text-xs font-mono font-semibold text-foreground tabular-nums">
                {Math.round((activeDecision.confidence ?? 0) * 100)}%
              </span>
            </div>
            <p class="text-xs text-muted-foreground truncate" title={activeDecision.agent_name}>
              {activeDecision.agent_name}
            </p>
          {:else}
            <div class="text-lg font-bold text-muted-foreground">Pending</div>
            <p class="text-xs text-muted-foreground">Run ranking to generate advisory decision</p>
          {/if}
        </CardContent>
      </Card>

      <Card class="border-border bg-card shadow-sm overflow-hidden" style="border-top: 3px solid #14B8A6">
        <CardContent class="p-4 flex flex-col justify-between h-full space-y-1.5">
          <div class="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Data Completeness
          </div>
          <div class="text-2xl font-bold text-teal-600 tabular-nums">
            {fmtRatio(a.data_completeness)}
          </div>
          <p class="text-[11px] text-muted-foreground font-mono truncate">
            {(a.scoring_version ?? 'standard').replace(/_/g, ' ')} · {(a.algorithm_version ?? 'v1').replace(/_/g, ' ')}
          </p>
        </CardContent>
      </Card>
    </div>

    <!-- Main 2-Column Workspace: Left Tabbed Deep-Dive + Right Sticky Recruiter Decision Rail -->
    <div class="grid gap-6 lg:grid-cols-12 items-start">
      <!-- Left Main Column (8 cols) -->
      <div class="lg:col-span-8 space-y-5 min-w-0">
        <Tabs.Root bind:value={sectionTab} class="space-y-4">
          <Tabs.List class="grid w-full grid-cols-3 h-auto">
            <Tabs.Trigger value="evaluation" class="text-xs sm:text-sm py-2">
              <Bot class="mr-1.5 size-3.5 hidden sm:inline" />
              Evaluation &amp; AI Summary
            </Tabs.Trigger>
            <Tabs.Trigger value="breakdown" class="text-xs sm:text-sm py-2">
              <BarChart3 class="mr-1.5 size-3.5 hidden sm:inline" />
              Score Breakdown
            </Tabs.Trigger>
            <Tabs.Trigger value="profile" class="text-xs sm:text-sm py-2">
              <FileText class="mr-1.5 size-3.5 hidden sm:inline" />
              Profile &amp; Verification
            </Tabs.Trigger>
          </Tabs.List>

          <!-- TAB 1: EVALUATION & AI SUMMARY -->
          <Tabs.Content value="evaluation" class="space-y-5">
            {#if a.review_signals.length}
              <Alert class="border-amber-200 bg-amber-50/70 text-amber-900">
                <AlertTriangle class="size-4 text-amber-600" />
                <AlertTitle class="font-semibold text-amber-900">Items Requiring Review</AlertTitle>
                <AlertDescription class="text-amber-800 text-xs mt-1">
                  <ul class="list-disc pl-4 space-y-0.5">
                    {#each a.review_signals as s}
                      <li>{s.replace(/_/g, ' ')}</li>
                    {/each}
                  </ul>
                </AlertDescription>
              </Alert>
            {/if}

            <!-- Advisory Decision Agent Panel -->
            {#if activeDecision}
              <Card class="border-border bg-card shadow-sm">
                <CardHeader class="pb-3">
                  <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <div>
                      <CardTitle class="text-base font-semibold">AI Decision Agent Panel</CardTitle>
                      <CardDescription class="text-xs">
                        Switch perspectives across specialized advisory agents.
                      </CardDescription>
                    </div>
                    <div class="flex flex-wrap gap-1.5" role="group" aria-label="Choose decision agent">
                      {#each DEFAULT_DECISION_AGENTS as ag}
                        <Button
                          size="sm"
                          variant={selectedAgent === ag.id ? 'default' : 'outline'}
                          onclick={() => (selectedAgent = ag.id)}
                          class="h-7 px-2.5 text-xs"
                        >
                          {ag.short_name}
                        </Button>
                      {/each}
                    </div>
                  </div>
                </CardHeader>
                <CardContent class="space-y-4">
                  <div class="flex flex-wrap items-center gap-2.5">
                    <Badge variant="outline" class={`text-xs font-semibold px-2.5 py-0.5 ${decisionBadgeClass(activeDecision.decision)}`}>
                      {DECISION_OUTCOME_LABEL[activeDecision.decision] ?? humanize(activeDecision.decision)}
                    </Badge>
                    <span class="text-xs font-mono text-muted-foreground">
                      Confidence: {Math.round((activeDecision.confidence ?? 0) * 100)}%
                    </span>
                    <span class="text-xs text-muted-foreground">· {activeDecision.agent_name}</span>
                  </div>

                  <p class="text-sm text-foreground leading-relaxed">{activeDecision.summary}</p>

                  {#if activeDecision.next_step}
                    <div class="rounded-lg bg-muted/40 px-3.5 py-2.5 text-xs text-foreground">
                      <strong class="font-semibold">Recommended next step:</strong> {activeDecision.next_step}
                    </div>
                  {/if}

                  {#if (activeDecision.key_factors?.length ?? 0) > 0 || (activeDecision.risk_flags?.length ?? 0) > 0}
                    <div class="grid gap-3 md:grid-cols-2">
                      {#if activeDecision.key_factors?.length}
                        <div class="rounded-lg border border-emerald-200/70 bg-emerald-50/40 p-3.5 space-y-1.5">
                          <div class="text-[11px] font-semibold uppercase tracking-wider text-emerald-800">Key Drivers</div>
                          <ul class="list-disc pl-4 text-xs text-foreground space-y-1">
                            {#each activeDecision.key_factors as f}
                              <li>{f}</li>
                            {/each}
                          </ul>
                        </div>
                      {/if}
                      {#if activeDecision.risk_flags?.length}
                        <div class="rounded-lg border border-amber-200/70 bg-amber-50/40 p-3.5 space-y-1.5">
                          <div class="text-[11px] font-semibold uppercase tracking-wider text-amber-800">Risks &amp; Watchouts</div>
                          <ul class="list-disc pl-4 text-xs text-foreground space-y-1">
                            {#each activeDecision.risk_flags as r}
                              <li>{r}</li>
                            {/each}
                          </ul>
                        </div>
                      {/if}
                    </div>
                  {/if}
                </CardContent>
              </Card>
            {/if}

            <!-- AI Score Summary & Deterministic Logic -->
            <Card class="border-border bg-card shadow-sm">
              <CardHeader class="pb-3">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <CardTitle class="text-base font-semibold">Score Explanation &amp; Logic</CardTitle>
                    <CardDescription class="text-xs">
                      Plain-English summary and deterministic scoring trace.
                    </CardDescription>
                  </div>
                  {#if formattedAiSummary}
                    <Badge variant="secondary" class="text-[11px] capitalize font-medium">
                      {humanize(a.explanation.ai_status)}
                    </Badge>
                  {/if}
                </div>
              </CardHeader>
              <CardContent class="space-y-4">
                {#if formattedAiSummary}
                  <div class="rounded-xl border border-border bg-muted/20 p-4 space-y-4">
                    {#if formattedAiSummary.overview}
                      <p class="text-sm leading-relaxed text-foreground">
                        {formattedAiSummary.overview}
                      </p>
                    {/if}

                    {#if formattedAiSummary.strengths.length > 0 || formattedAiSummary.gaps.length > 0}
                      <div class="grid gap-3 md:grid-cols-2">
                        {#if formattedAiSummary.strengths.length > 0}
                          <div class="rounded-lg border border-emerald-200/80 bg-emerald-50/40 p-3.5 space-y-2">
                            <div class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-emerald-800">
                              <CheckCircle2 class="size-3.5 text-emerald-600" />
                              <span>Key Strengths</span>
                            </div>
                            <ul class="space-y-1.5 text-xs sm:text-sm text-foreground">
                              {#each formattedAiSummary.strengths as s}
                                <li class="leading-relaxed">
                                  <span>{s.text}</span>
                                  {#if s.evidenceCount > 0}
                                    <span class="ml-1.5 inline-flex items-center rounded bg-emerald-100/80 px-1.5 py-0.5 text-[10px] font-medium text-emerald-800 align-middle">
                                      {s.evidenceCount} {s.evidenceCount === 1 ? 'ref' : 'refs'}
                                    </span>
                                  {/if}
                                </li>
                              {/each}
                            </ul>
                          </div>
                        {/if}

                        {#if formattedAiSummary.gaps.length > 0}
                          <div class="rounded-lg border border-amber-200/80 bg-amber-50/40 p-3.5 space-y-2">
                            <div class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-amber-800">
                              <AlertTriangle class="size-3.5 text-amber-600" />
                              <span>Gaps &amp; Missing Info</span>
                            </div>
                            <ul class="space-y-1.5 text-xs sm:text-sm text-foreground">
                              {#each formattedAiSummary.gaps as g}
                                <li class="leading-relaxed">
                                  <span>{g.text}</span>
                                  {#if g.evidenceCount > 0}
                                    <span class="ml-1.5 inline-flex items-center rounded bg-amber-100/80 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 align-middle">
                                      {g.evidenceCount} {g.evidenceCount === 1 ? 'ref' : 'refs'}
                                    </span>
                                  {/if}
                                </li>
                              {/each}
                            </ul>
                          </div>
                        {/if}
                      </div>
                    {/if}

                    {#if formattedAiSummary.extras.length > 0}
                      <div class="space-y-1.5 pt-2 border-t border-border/60 text-xs sm:text-sm">
                        {#each formattedAiSummary.extras as ex}
                          <p class="leading-relaxed text-foreground">
                            <strong class="font-semibold">{ex.label}:</strong> {ex.text}
                          </p>
                        {/each}
                      </div>
                    {/if}
                  </div>
                {/if}

                <div class="space-y-2">
                  <h4 class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Deterministic Trace
                  </h4>
                  <ul class="space-y-2 text-xs sm:text-sm text-foreground">
                    {#each a.explanation.deterministic_summary as s}
                      {@const item = parseExplanationItem(s)}
                      <li class="flex flex-col sm:flex-row sm:items-baseline gap-1 sm:gap-2 rounded-lg bg-muted/30 px-3.5 py-2">
                        {#if item.heading}
                          <strong class="font-semibold text-foreground shrink-0">{item.heading}:</strong>
                          <span class="text-foreground/90">{item.body}</span>
                        {:else}
                          <span class="text-foreground/90">{item.body}</span>
                        {/if}
                      </li>
                    {/each}
                  </ul>
                </div>

                <p class="text-[11px] text-muted-foreground pt-2 border-t border-border">
                  {a.explanation.disclaimer.replace(/_/g, ' ')}
                </p>
              </CardContent>
            </Card>
          </Tabs.Content>

          <!-- TAB 2: SCORE BREAKDOWN -->
          <Tabs.Content value="breakdown" class="space-y-5">
            <Card class="border-border bg-card shadow-sm">
              <CardHeader>
                <CardTitle class="text-base font-semibold">Requirement Breakdown by Category</CardTitle>
                <CardDescription class="text-xs">
                  Comparison across job requirement categories. Missing information indicates unstated resume details, not lack of capability.
                </CardDescription>
              </CardHeader>
              <CardContent class="space-y-6">
                <BarList
                  max={100}
                  suffix="%"
                  items={Object.entries(a.categories).map(([k, c]) => ({
                    label: humanize(k),
                    value: c.status === 'known' ? pctNum(c.match) : null,
                    note: c.status === 'known' ? `Weight ${fmtRatio(c.weight)}` : 'Missing information (not scored)'
                  }))}
                />

                <div class="overflow-x-auto rounded-lg border border-border/70">
                  <Table.Root>
                    <Table.Header>
                      <Table.Row class="bg-muted/30">
                        <Table.Head class="text-left font-semibold text-foreground">Category</Table.Head>
                        <Table.Head class="text-center font-semibold text-foreground">Assessment</Table.Head>
                        <Table.Head class="text-right font-semibold text-foreground">Match</Table.Head>
                        <Table.Head class="text-right font-semibold text-foreground">Weight</Table.Head>
                        <Table.Head class="text-right font-semibold text-foreground">Contribution</Table.Head>
                      </Table.Row>
                    </Table.Header>
                    <Table.Body>
                      {#each Object.entries(a.categories) as [k, c]}
                        <Table.Row>
                          <Table.Cell class="text-left font-semibold text-foreground">{humanize(k)}</Table.Cell>
                          <Table.Cell class="text-center">
                            <Badge variant={c.status === 'known' ? 'default' : 'secondary'} class="text-xs">
                              {catLabel[c.status] ?? humanize(c.status)}
                            </Badge>
                          </Table.Cell>
                          <Table.Cell class="text-right tabular-nums font-mono text-sm">
                            {c.status === 'known' ? fmtScore(c.match) : NP}
                          </Table.Cell>
                          <Table.Cell class="text-right tabular-nums font-mono text-sm">
                            {fmtRatio(c.weight)}
                          </Table.Cell>
                          <Table.Cell class="text-right tabular-nums font-mono text-sm">
                            {c.status === 'known' ? fmtRatio(c.weighted_contribution) : NP}
                          </Table.Cell>
                        </Table.Row>
                        {#if c.notes?.length}
                          <Table.Row class="bg-muted/15">
                            <Table.Cell></Table.Cell>
                            <Table.Cell colspan={4} class="text-left text-xs text-muted-foreground py-2">
                              {c.notes.map((n) => n.replace(/_/g, ' ')).join(' · ')}
                            </Table.Cell>
                          </Table.Row>
                        {/if}
                      {/each}
                    </Table.Body>
                  </Table.Root>
                </div>
              </CardContent>
            </Card>
          </Tabs.Content>

          <!-- TAB 3: CANDIDATE PROFILE & VERIFICATION -->
          <Tabs.Content value="profile" class="space-y-4">
            <CandidateProfile
              data={{ ...(a.candidate as unknown as Record<string, unknown>), verification_detail: a.verification_detail }}
              resume={a.resume as unknown as Record<string, unknown> | null}
              showHeader={false}
              bind:tab={profileTab}
            />
          </Tabs.Content>
        </Tabs.Root>
      </div>

      <!-- Right Sticky Recruiter Rail (4 cols) -->
      <div class="lg:col-span-4 space-y-5 lg:sticky lg:top-6">
        <!-- Recruiter Decision Card -->
        <Card class="border-border bg-card shadow-sm">
          <CardHeader class="pb-3">
            <div class="flex items-center gap-2">
              <UserCheck class="size-4 text-primary" />
              <CardTitle class="text-base font-semibold">Recruiter Decision</CardTitle>
            </div>
            <CardDescription class="text-xs">
              Update hiring stage manually and record rationale in the audit trail.
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-3.5">
            <div class="space-y-1.5">
              <Label class="text-xs">Stage / Decision</Label>
              <Select.Root type="single" bind:value={next}>
                <Select.Trigger class="w-full h-9 text-sm">
                  {humanize(next)}
                </Select.Trigger>
                <Select.Content>
                  {#each USER_DECISION_STATUSES as s}
                    <Select.Item value={s}>{humanize(s)}</Select.Item>
                  {/each}
                </Select.Content>
              </Select.Root>
            </div>

            <div class="space-y-1.5">
              <Label for="decision-reason" class="text-xs">
                Decision notes {next === 'rejected' ? '(required) *' : '(optional)'}
              </Label>
              <Input
                id="decision-reason"
                placeholder="e.g. Strong systems background; advance to technical screen."
                bind:value={reason}
                class="h-9 text-sm"
              />
            </div>

            <Button
              disabled={busy}
              onclick={changeStatus}
              variant={next === 'rejected' ? 'destructive' : 'default'}
              class="w-full font-medium"
            >
              {#if busy && busyOp === 'status'}
                <Loader2 class="mr-1.5 size-4 animate-spin" />
                Updating…
              {:else}
                Update status to {humanize(next)}
              {/if}
            </Button>
          </CardContent>
        </Card>

        <!-- Audit History Card -->
        <Card class="border-border bg-card shadow-sm">
          <CardHeader class="pb-3">
            <CardTitle class="text-sm font-semibold">Audit History</CardTitle>
          </CardHeader>
          <CardContent>
            {#if Array.isArray(statusHistory) && statusHistory.length > 0}
              <div class="divide-y divide-border -mx-1">
                {#each statusHistory as h}
                  {@const targetStatus = h.to_status ?? h.status}
                  <div class="py-2.5 px-1 space-y-1">
                    <div class="flex items-center justify-between gap-2">
                      <div class="flex flex-wrap items-center gap-1.5">
                        {#if h.from_status && h.to_status}
                          <Badge variant="outline" class="capitalize font-normal text-[11px] text-muted-foreground">
                            {humanize(String(h.from_status))}
                          </Badge>
                          <span class="text-[11px] text-muted-foreground">→</span>
                        {/if}
                        {#if targetStatus}
                          <Badge variant="outline" class="capitalize font-semibold text-[11px]">
                            {humanize(String(targetStatus))}
                          </Badge>
                        {/if}
                      </div>
                      <span class="text-[11px] text-muted-foreground shrink-0">
                        {fmtDate(String(h.created_at ?? h.timestamp ?? h.updated_at ?? ''))}
                      </span>
                    </div>
                    <p class="text-xs text-muted-foreground leading-snug">
                      {h.reason ? String(h.reason) : 'Manual status transition'}
                    </p>
                  </div>
                {/each}
              </div>
            {:else}
              <p class="text-xs text-muted-foreground">No status transitions recorded yet.</p>
            {/if}
          </CardContent>
        </Card>
      </div>
    </div>
  </div>
{/if}
