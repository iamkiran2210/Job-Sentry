<script lang="ts">
  import { page } from '$app/state';
  import { onDestroy } from 'svelte';
  import { getResume, uploadResume, resumeIdFrom, resumeStatus, retryResume, deleteResume } from '$lib/services/resumes';
  import { getJob } from '$lib/services/jobs';
  import { ApiError } from '$lib/services/api-client';
  import { toast } from '$lib/stores/toast.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { pipelineProgress } from '$lib/stores/pipeline-progress.svelte';
  import { toastError } from '$lib/errors';
  import { runRanking } from '$lib/services/applications';
  import { fmtBytes, humanize } from '$lib/utils';
  import DataView from '$lib/components/DataView.svelte';
  import ResumeDropzone from '$lib/components/ResumeDropzone.svelte';

  import { Progress } from '$lib/components/ui/progress';
  import { Button } from '$lib/components/ui/button';
  import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '$lib/components/ui/card';
  import { Checkbox } from '$lib/components/ui/checkbox';
  import { Label } from '$lib/components/ui/label';
  import { Badge } from '$lib/components/ui/badge';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import {
    UploadCloud,
    FileText,
    CheckCircle2,
    AlertCircle,
    Loader2,
    RefreshCw,
    Trash2,
    Users
  } from '@lucide/svelte';

  const id = page.params.jobId!;
  const OK = [
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'image/jpeg',
    'image/png'
  ];

  type Item = {
    key: string;
    file: File;
    progress: number;
    phase: 'queued' | 'uploading' | 'processing' | 'done' | 'failed';
    resumeId?: string;
    note?: string;
    extracted?: Record<string, unknown> | null;
    open?: boolean;
    deleting?: boolean;
  };

  let jobTitle = $state('');
  let activeTaskId = $state<string | null>(null);
  let items = $state<Item[]>([]);
  let rejected = $state<string[]>([]);
  let autoRank = $state(true);
  let ranked = $state(false);
  let ranking = $state(false);
  const timers = new Set<ReturnType<typeof setInterval>>();
  onDestroy(() => timers.forEach(clearInterval));

  getJob(id)
    .then((j) => (jobTitle = j.title))
    .catch(() => {});

  const resolvedJobName = () => jobTitle || 'Selected job';

  function ensureUploadTask(totalCount: number) {
    if (!activeTaskId) {
      activeTaskId = pipelineProgress.start({
        jobId: id,
        jobName: resolvedJobName(),
        kind: 'upload_and_rank',
        stage: 'uploading',
        detail: `Uploading ${totalCount} resume${totalCount === 1 ? '' : 's'}…`,
        progress: 10,
        totalFiles: totalCount,
        autoRank
      });
    }
    return activeTaskId;
  }

  function syncUploadProgress() {
    if (!activeTaskId || items.length === 0) return;
    const total = items.length;
    const done = items.filter((i) => i.phase === 'done').length;
    const failed = items.filter((i) => i.phase === 'failed').length;
    const uploading = items.filter((i) => i.phase === 'uploading').length;
    const processing = items.filter((i) => i.phase === 'processing').length;
    if (uploading > 0) {
      const avgUpload =
        items.reduce((s, i) => s + (i.phase === 'uploading' ? i.progress : i.phase === 'queued' ? 0 : 100), 0) /
        total;
      pipelineProgress.transition(
        activeTaskId,
        'uploading',
        `Uploading resumes (${total - uploading}/${total} uploaded)…`,
        Math.round(8 + avgUpload * 0.22),
        { doneFiles: done, totalFiles: total }
      );
    } else if (processing > 0) {
      pipelineProgress.transition(
        activeTaskId,
        'analyzing',
        `Analyzing resumes (${done}/${total} analyzed)…`,
        Math.round(32 + (done / total) * 28),
        { doneFiles: done, totalFiles: total }
      );
    } else if (done === 0 && failed === total) {
      pipelineProgress.fail(activeTaskId, `All ${failed} resume upload(s) failed.`);
      activeTaskId = null;
    }
  }

  function add(files: FileList | File[]) {
    rejected = [];
    for (const f of Array.from(files)) {
      if (!OK.includes(f.type)) {
        rejected.push(`${f.name}: only PDF, DOCX, JPG or PNG`);
        continue;
      }
      if (f.size > 10 * 1024 * 1024) {
        rejected.push(`${f.name}: larger than 10 MB`);
        continue;
      }
      items.push({ key: crypto.randomUUID(), file: f, progress: 0, phase: 'queued' });
    }
    if (rejected.length) {
      toast.error(`${rejected.length} file(s) not added`, rejected.join(' · '));
    }
  }

  function poll(it: Item) {
    const t = setInterval(async () => {
      try {
        const s = await resumeStatus(it.resumeId!);
        const st = String(s.parse_status ?? s.status ?? '').toLowerCase();
        const pct = typeof s.progress_pct === 'number' ? ` ${s.progress_pct}%` : '';
        it.note = `${humanize(st || 'processing')}${pct}`;
        if (st === 'completed') {
          it.phase = 'done';
          clearInterval(t);
          syncUploadProgress();
        } else if (st === 'failed') {
          it.phase = 'failed';
          clearInterval(t);
          syncUploadProgress();
        }
      } catch {
        /* keep polling */
      }
    }, 3000);
    timers.add(t);
  }

  async function send(it: Item) {
    const taskId = ensureUploadTask(items.length);
    it.phase = 'uploading';
    it.progress = 0;
    it.note = undefined;
    try {
      const res = await uploadResume(id, it.file, (p) => {
        it.progress = p;
        syncUploadProgress();
      });
      it.resumeId = resumeIdFrom(res) ?? undefined;
      it.phase = 'processing';
      it.note = 'Uploaded — extracting and analyzing resume…';
      toast.info(`${resolvedJobName()} · Uploaded`, `${it.file.name} uploaded. Analyzing resume…`);
      if (it.resumeId) {
        // Hand off to global store so analysis + auto-ranking survive page refresh and navigation!
        pipelineProgress.attachUploadedResume(taskId, it.resumeId, {
          fileName: it.file.name,
          totalFiles: items.length,
          autoRank
        });
        poll(it);
      } else {
        it.note = 'Uploaded. Backend did not return a resume identifier.';
      }
      syncUploadProgress();
    } catch (e) {
      if (e instanceof ApiError && e.isPageUnload) return;
      it.phase = 'failed';
      it.note = e instanceof ApiError ? e.message : 'Upload failed';
      toastError(e, `Could not upload ${it.file.name}`);
      syncUploadProgress();
    }
  }

  const finished = $derived(
    items.length > 0 && items.every((i) => i.phase === 'done' || i.phase === 'failed')
  );
  const anyDone = $derived(items.some((i) => i.phase === 'done'));

  // Sync local `ranked` badge when the global pipeline finishes auto-ranking for this job
  $effect(() => {
    if (pipelineProgress.lastCompleted?.jobId === id && pipelineProgress.lastCompleted.kind === 'upload_and_rank') {
      if (autoRank) ranked = true;
      activeTaskId = null;
    }
  });

  async function rankNow() {
    if (ranking) return;
    ranking = true;
    const taskId = pipelineProgress.start({
      jobId: id,
      jobName: resolvedJobName(),
      kind: 'rank',
      stage: 'verifying',
      detail: 'Verifying profiles and ranking new applicants…',
      progress: 40
    });
    pipelineProgress.simulateRankingPhases(taskId, { includesVerify: true, isRerun: false });
    try {
      const res = await runRanking(id);
      ranked = true;
      const verified = typeof res?.verified_count === 'number' ? res.verified_count : 0;
      if (verified > 0) {
        toast.info(`${resolvedJobName()} · Verified`, `Completed verification checks for ${verified} applicant(s).`);
      }
      pipelineProgress.complete(
        taskId,
        `All processed resumes are now ranked${verified > 0 ? ` (${verified} verified)` : ''}.`,
        { title: `Ranking complete · ${resolvedJobName()}`, verifiedCount: verified, showViewAction: true }
      );
    } catch (e) {
      if (e instanceof ApiError && e.isPageUnload) return;
      const detail = e instanceof ApiError ? e.message : 'Ranking failed';
      pipelineProgress.fail(taskId, detail, `${resolvedJobName()} · Ranking failed`);
    } finally {
      ranking = false;
    }
  }

  async function showExtracted(it: Item) {
    it.open = !it.open;
    if (it.open && !it.extracted && it.resumeId) {
      try {
        it.extracted = await getResume(it.resumeId);
      } catch (e) {
        toastError(e, 'Could not load extracted data');
        it.open = false;
      }
    }
  }

  const startAll = () => items.filter((i) => i.phase === 'queued').forEach(send);

  async function retry(it: Item) {
    if (!it.resumeId) return send(it);
    try {
      await retryResume(it.resumeId);
      it.phase = 'processing';
      poll(it);
    } catch (e) {
      it.note = e instanceof ApiError ? e.message : 'Retry failed';
    }
  }

  async function removeItem(it: Item) {
    if (it.deleting) return;
    if (!it.resumeId) {
      items = items.filter((x) => x.key !== it.key);
      return;
    }
    const ok = await confirmDialog({
      title: 'Delete uploaded resume application?',
      message: `This permanently deletes "${it.file.name}" and its job application from the server.`,
      confirmLabel: 'Delete application',
      danger: true
    });
    if (!ok) return;
    it.deleting = true;
    try {
      await deleteResume(it.resumeId);
      items = items.filter((x) => x.key !== it.key);
      toast.success('Resume application deleted', `"${it.file.name}" was removed.`);
    } catch (e) {
      toastError(e, `Could not delete ${it.file.name}`);
      it.deleting = false;
    }
  }
</script>

<div class="w-full space-y-6">
  <div class="space-y-1">
    <h1 class="text-3xl font-bold tracking-tight text-foreground">Upload Resumes</h1>
    <p class="text-sm text-muted-foreground">
      {jobTitle ? `Adding candidates to ${jobTitle} · ` : ''}Upload CVs to extract structured profiles, verify links, and rank applicants automatically.
    </p>
  </div>

  <!-- Clear 4-step workflow guide -->
  <ol class="grid gap-2.5 sm:grid-cols-4 text-xs">
    {#each [
      ['1', 'Upload CVs', 'PDF, DOCX, JPG or PNG up to 10 MB'],
      ['2', 'AI Analysis', 'Extracts skills, experience & education'],
      ['3', 'Verification', 'Checks email MX, authenticity & links'],
      ['4', 'Rank & Notify', 'Scores candidates — persists across refresh']
    ] as [num, title, desc]}
      <li class="flex items-start gap-2.5 rounded-xl border border-border bg-card px-3.5 py-2.5 shadow-2xs">
        <span class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[11px] font-bold text-primary">
          {num}
        </span>
        <div class="min-w-0">
          <div class="font-semibold text-foreground">{title}</div>
          <div class="text-[11px] text-muted-foreground leading-snug">{desc}</div>
        </div>
      </li>
    {/each}
  </ol>

  <ResumeDropzone onFiles={add} class="w-full" />

  {#if rejected.length}
    <Alert variant="destructive">
      <AlertCircle class="size-4" />
      <AlertTitle>Some files could not be queued</AlertTitle>
      <AlertDescription>
        <ul class="list-disc pl-5 text-xs space-y-1 mt-1">
          {#each rejected as r}
            <li>{r}</li>
          {/each}
        </ul>
      </AlertDescription>
    </Alert>
  {/if}

  {#if items.length}
    <Card class="border-border bg-card shadow-sm">
      <CardHeader class="pb-3 flex flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle class="text-lg">Queued Resumes ({items.length})</CardTitle>
          <CardDescription class="text-xs">
            Files are streamed directly with real-time per-file progress tracking.
          </CardDescription>
        </div>
        {#if items.some((i) => i.phase === 'queued')}
          <Button size="sm" onclick={startAll}>
            <UploadCloud class="mr-1.5 size-4" />
            Upload all ({items.filter((i) => i.phase === 'queued').length})
          </Button>
        {/if}
      </CardHeader>

      <CardContent class="space-y-4">
        <div class="divide-y divide-border rounded-lg border border-border">
          {#each items as it (it.key)}
            <div class="p-4 space-y-2">
              <div class="flex flex-wrap sm:flex-nowrap items-center justify-between gap-2 sm:gap-3 text-sm">
                <div class="flex items-center gap-2.5 min-w-0">
                  <FileText class="size-4 text-primary shrink-0" />
                  <span class="font-medium text-foreground truncate">{it.file.name}</span>
                  <span class="text-xs text-muted-foreground font-mono shrink-0">
                    {fmtBytes(it.file.size)}
                  </span>
                </div>

                <div class="flex items-center gap-3 shrink-0">
                  <Badge
                    variant={it.phase === 'done' ? 'default' : it.phase === 'failed' ? 'destructive' : 'secondary'}
                    class="text-xs capitalize"
                  >
                    {#if it.phase === 'uploading'}
                      Uploading {it.progress}%
                    {:else if it.phase === 'processing'}
                      Processing
                    {:else if it.phase === 'done'}
                      Processed
                    {:else if it.phase === 'failed'}
                      Failed
                    {:else}
                      Ready
                    {/if}
                  </Badge>

                  {#if it.phase === 'failed'}
                    <Button variant="ghost" size="sm" onclick={() => retry(it)} class="text-primary text-xs h-7">
                      <RefreshCw class="mr-1 size-3" /> Retry
                    </Button>
                  {/if}

                  {#if it.phase === 'done' && it.resumeId}
                    <Button variant="ghost" size="sm" onclick={() => showExtracted(it)} class="text-xs h-7 text-primary">
                      {it.open ? 'Hide' : 'View'} extracted data
                    </Button>
                  {/if}

                  {#if it.phase === 'queued' || it.phase === 'done' || it.phase === 'failed'}
                    <Button
                      variant="ghost"
                      size="icon"
                      disabled={it.deleting}
                      onclick={() => removeItem(it)}
                      class="size-7 text-muted-foreground hover:text-destructive"
                      title={it.resumeId ? 'Delete resume application' : 'Remove from queue'}
                      aria-label={`Remove ${it.file.name}`}
                    >
                      {#if it.deleting}
                        <Loader2 class="size-3.5 animate-spin" />
                      {:else}
                        <Trash2 class="size-3.5" />
                      {/if}
                    </Button>
                  {/if}
                </div>
              </div>

              {#if it.phase === 'uploading'}
                <Progress value={it.progress} max={100} class="h-1.5" />
              {/if}

              {#if it.open && it.extracted}
                <div class="rounded-lg border border-border bg-muted/20 p-4 mt-3 space-y-3 overflow-hidden">
                  <p class="text-xs text-muted-foreground">Extracted from resume. Not independently verified.</p>
                  <DataView value={it.extracted} />
                </div>
              {/if}

              {#if it.note}
                <p class={`text-xs ${it.phase === 'failed' ? 'text-destructive' : 'text-muted-foreground'}`}>
                  {it.note}
                </p>
              {/if}
            </div>
          {/each}
        </div>

        <!-- Post-upload Ranking Trigger & Auto-rank Toggle (Rule 7) -->
        <div class="rounded-xl border border-border bg-muted/30 p-4 space-y-3">
          <div class="flex items-center gap-2.5">
            <Checkbox id="auto-rank" bind:checked={autoRank} />
            <Label for="auto-rank" class="text-sm font-semibold cursor-pointer">
              Run ranking automatically when processing finishes
            </Label>
          </div>
          <p class="text-xs text-muted-foreground">
            Scores only update when ranking is executed.
            {#if finished && anyDone}
              {ranked ? ' Ranking is fully up to date.' : ranking ? ' Computing ranking now…' : ''}
            {/if}
          </p>

          <div class="flex flex-wrap items-center gap-3 pt-2">
            {#if finished && anyDone && !ranked && !autoRank}
              <Button size="sm" onclick={rankNow} disabled={ranking}>
                {#if ranking}
                  <Loader2 class="mr-1.5 size-4 animate-spin" />
                  Ranking…
                {:else}
                  Run ranking now
                {/if}
              </Button>
            {/if}

            <Button variant="outline" size="sm" href={`/jobs/${id}/applicants`}>
              <Users class="mr-1.5 size-4" /> View applicants
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  {/if}
</div>
