<script lang="ts">
  import { page } from '$app/state';
  import { onDestroy } from 'svelte';
  import {
    pipelineProgress,
    KIND_LABEL,
    type PipelineJobTask,
    type PipelineStage
  } from '$lib/stores/pipeline-progress.svelte';
  import { Badge } from '$lib/components/ui/badge';
  import { Button } from '$lib/components/ui/button';
  import {
    CheckCircle2,
    AlertCircle,
    Loader2,
    X,
    ArrowRight,
    Briefcase
  } from '@lucide/svelte';

  let now = $state(Date.now());
  const clock = setInterval(() => {
    if (pipelineProgress.tasks.some((t) => t.stage !== 'completed' && t.stage !== 'failed')) {
      now = Date.now();
    }
  }, 1000);
  onDestroy(() => clearInterval(clock));

  const STAGE_ORDER: Record<PipelineStage, number> = {
    uploading: 0,
    analyzing: 1,
    verifying: 2,
    ranking: 3,
    notifying: 4,
    completed: 5,
    failed: -1
  };

  function stepsFor(t: PipelineJobTask): { key: PipelineStage; label: string }[] {
    if (t.kind === 'notify') {
      return [{ key: 'notifying', label: 'Notifying' }];
    }
    if (t.kind === 'verify') {
      return [{ key: 'verifying', label: 'Verifying' }];
    }
    const base: { key: PipelineStage; label: string }[] =
      t.kind === 'upload_and_rank'
        ? [
            { key: 'uploading', label: 'Uploaded' },
            { key: 'analyzing', label: 'Analyzed' },
            { key: 'verifying', label: 'Verified' },
            { key: 'ranking', label: 'Ranked' }
          ]
        : [
            { key: 'analyzing', label: 'Analyzed' },
            { key: 'verifying', label: 'Verified' },
            { key: 'ranking', label: 'Ranked' }
          ];
    if (t.includeNotify) {
      base.push({ key: 'notifying', label: 'Notified' });
    }
    return base;
  }

  function stepState(task: PipelineJobTask, stepKey: PipelineStage): 'done' | 'active' | 'pending' {
    if (task.stage === 'completed') return 'done';
    if (task.stage === 'failed') return 'pending';
    const cur = STAGE_ORDER[task.stage];
    const target = STAGE_ORDER[stepKey];
    if (target < cur) return 'done';
    if (target === cur) return 'active';
    return 'pending';
  }

  function elapsedLabel(task: PipelineJobTask): string {
    const end = task.finishedAt ?? now;
    const sec = Math.max(0, Math.floor((end - task.startedAt) / 1000));
    if (sec < 60) return `${sec}s`;
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}m ${s}s`;
  }
</script>

{#if pipelineProgress.tasks.length > 0}
  <div
    class="sticky top-14 z-10 border-b border-border bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/85 shadow-xs"
    role="status"
    aria-live="polite"
  >
    {#each pipelineProgress.tasks as task (task.id)}
      {@const steps = stepsFor(task)}
      {@const isDone = task.stage === 'completed'}
      {@const isErr = task.stage === 'failed'}
      {@const onRankingPage = page.url.pathname === `/jobs/${task.jobId}/applicants`}
      <div class="relative px-4 sm:px-6 py-2.5">
        <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <!-- Left: Status Icon + Specific Job Name + Run Badge -->
          <div class="flex items-center gap-2.5 min-w-0">
            {#if isDone}
              <CheckCircle2 class="size-4 text-emerald-600 shrink-0" />
            {:else if isErr}
              <AlertCircle class="size-4 text-destructive shrink-0" />
            {:else}
              <Loader2 class="size-4 text-indigo-600 animate-spin shrink-0" />
            {/if}

            <a
              href={`/jobs/${task.jobId}/applicants`}
              class="inline-flex items-center gap-1.5 font-semibold text-sm text-foreground hover:text-primary transition-colors min-w-0"
              title={`Open Applicant Ranking for ${task.jobName}`}
            >
              <Briefcase class="size-3.5 text-primary shrink-0" />
              <span class="truncate max-w-[170px] sm:max-w-[240px]">{task.jobName}</span>
            </a>

            <Badge
              variant="outline"
              class={`text-[11px] font-medium shrink-0 ${
                isDone
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                  : isErr
                    ? 'border-rose-200 bg-rose-50 text-rose-700'
                    : 'border-indigo-200 bg-indigo-50 text-indigo-700'
              }`}
            >
              {isDone ? 'Completed' : isErr ? 'Attention needed' : KIND_LABEL[task.kind]}
            </Badge>

            {#if task.subject}
              <span class="hidden md:inline text-xs text-muted-foreground truncate max-w-[150px]">
                · {task.subject}
              </span>
            {/if}
          </div>

          <!-- Center: Adaptive Inline Process Stepper -->
          <ol class="hidden lg:flex items-center gap-1.5 text-xs" aria-label="Pipeline stages">
            {#each steps as s, idx}
              {@const state = stepState(task, s.key)}
              <li class="inline-flex items-center gap-1.5">
                <span
                  class={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium transition-colors ${
                    state === 'done'
                      ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                      : state === 'active'
                        ? 'bg-indigo-50 text-indigo-700 border border-indigo-200'
                        : 'text-muted-foreground'
                  }`}
                >
                  {#if state === 'done'}
                    <CheckCircle2 class="size-3" />
                  {:else if state === 'active'}
                    <span class="h-1.5 w-1.5 rounded-full bg-indigo-600 animate-pulse"></span>
                  {/if}
                  {s.label}
                </span>
                {#if idx < steps.length - 1}
                  <span class="text-border">›</span>
                {/if}
              </li>
            {/each}
          </ol>

          <!-- Right: Plain-English Status Detail + Elapsed + % + View / Dismiss -->
          <div class="flex items-center gap-2.5 ml-auto">
            <span class="text-xs text-muted-foreground truncate max-w-[200px] sm:max-w-[280px]" title={task.detail}>
              {task.detail}
            </span>
            <span class="hidden sm:inline text-[11px] font-mono text-muted-foreground tabular-nums shrink-0">
              {elapsedLabel(task)}
            </span>
            {#if !isErr}
              <span
                class={`text-xs font-mono font-semibold tabular-nums shrink-0 ${
                  isDone ? 'text-emerald-600' : 'text-indigo-600'
                }`}
              >
                {Math.round(task.progress)}%
              </span>
            {/if}
            {#if !onRankingPage}
              <Button
                variant="outline"
                size="sm"
                href={`/jobs/${task.jobId}/applicants`}
                class="h-6 px-2 text-[11px] shrink-0"
              >
                Ranking <ArrowRight class="ml-1 size-3" />
              </Button>
            {/if}
            <button
              type="button"
              onclick={() => pipelineProgress.dismiss(task.id)}
              class="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors cursor-pointer"
              aria-label={`Dismiss progress for ${task.jobName}`}
            >
              <X class="size-3.5" />
            </button>
          </div>
        </div>

        <!-- Smooth Hairline Progress Bar -->
        <div class="absolute inset-x-0 bottom-0 h-[3px] bg-muted/60 overflow-hidden">
          <div
            class="h-full transition-all duration-500 ease-out"
            style={`width: ${isErr ? 100 : Math.min(100, Math.max(4, task.progress))}%; background: ${
              isErr
                ? '#F43F5E'
                : isDone
                  ? '#10B981'
                  : 'linear-gradient(90deg, #4F46E5, #06B6D4)'
            }`}
          ></div>
        </div>
      </div>
    {/each}
  </div>
{/if}
