import { goto } from '$app/navigation';
import { toast } from './toast.svelte';
import { resumeStatus } from '$lib/services/resumes';
import { getRankingHistory, runRanking } from '$lib/services/applications';

export type PipelineStage =
  | 'uploading'
  | 'analyzing'
  | 'verifying'
  | 'ranking'
  | 'notifying'
  | 'completed'
  | 'failed';

export type PipelineKind =
  | 'upload_and_rank'
  | 'rank'
  | 'rescore'
  | 'selected'
  | 'individual'
  | 'verify'
  | 'notify';

export interface PipelineJobTask {
  id: string;
  jobId: string;
  jobName: string;
  kind: PipelineKind;
  stage: PipelineStage;
  progress: number;
  detail: string;
  subject?: string;
  includeNotify?: boolean;
  autoRank?: boolean;
  resumeIds?: string[];
  completedResumeIds?: string[];
  failedResumeIds?: string[];
  totalFiles?: number;
  doneFiles?: number;
  verifiedCount?: number;
  runCountBefore?: number;
  startedAt: number;
  updatedAt: number;
  finishedAt?: number;
}

const STORAGE_KEY = 'js_pipeline_tasks_v1';
const ACTIVE_TTL_MS = 15 * 60 * 1000;
const FINISHED_TTL_MS = 90 * 1000;

const STAGE_LABEL: Record<PipelineStage, string> = {
  uploading: 'Uploading',
  analyzing: 'Analyzing',
  verifying: 'Verifying',
  ranking: 'Ranking',
  notifying: 'Notifying',
  completed: 'Completed',
  failed: 'Failed'
};

export const KIND_LABEL: Record<PipelineKind, string> = {
  upload_and_rank: 'Upload & Rank',
  rank: 'Ranking',
  rescore: 'Re-run all',
  selected: 'Selected re-run',
  individual: 'Individual rank',
  verify: 'Verification',
  notify: 'Notification'
};

function canUseStorage(): boolean {
  try {
    return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
  } catch {
    return false;
  }
}

class PipelineProgressStore {
  tasks = $state<PipelineJobTask[]>([]);
  /** Reactive counter bumped whenever a job finishes so open pages (e.g. Ranking) auto-refresh. */
  lastCompleted = $state<{ jobId: string; kind: PipelineKind; at: number } | null>(null);

  private timers = new Map<string, ReturnType<typeof setInterval>>();
  private dismissTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private hydrated = false;

  private persist() {
    if (!canUseStorage()) return;
    try {
      if (this.tasks.length === 0) {
        window.localStorage.removeItem(STORAGE_KEY);
      } else {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(this.tasks));
      }
    } catch {
      /* ignore quota/private mode errors */
    }
  }

  private clearTimers(id: string) {
    const t = this.timers.get(id);
    if (t) {
      clearInterval(t);
      this.timers.delete(id);
    }
    const d = this.dismissTimers.get(id);
    if (d) {
      clearTimeout(d);
      this.dismissTimers.delete(id);
    }
  }

  /**
   * Restores active/recent pipeline tasks from localStorage after a full page refresh
   * and seamlessly resumes polling backend resume/ranking status.
   */
  hydrateAndResume() {
    if (this.hydrated || !canUseStorage()) return;
    this.hydrated = true;

    let saved: PipelineJobTask[] = [];
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) saved = parsed as PipelineJobTask[];
    } catch {
      return;
    }

    const now = Date.now();
    const valid = saved.filter((t) => {
      if (!t?.id || !t?.jobId) return false;
      const age = now - (t.finishedAt ?? t.updatedAt ?? t.startedAt ?? 0);
      if (t.stage === 'completed' || t.stage === 'failed') return age < FINISHED_TTL_MS;
      return age < ACTIVE_TTL_MS;
    });

    this.tasks = valid;
    this.persist();

    for (const task of valid) {
      if (task.stage === 'completed' || task.stage === 'failed') {
        const remaining = Math.max(2500, 8000 - (now - (task.finishedAt ?? now)));
        const dt = setTimeout(() => this.dismiss(task.id), remaining);
        this.dismissTimers.set(task.id, dt);
        continue;
      }

      // Case 1: Resumes were already uploaded and Celery is analyzing them -> resume global polling!
      if (task.resumeIds && task.resumeIds.length > 0 && (task.stage === 'uploading' || task.stage === 'analyzing')) {
        task.stage = 'analyzing';
        task.detail = 'Resumed tracking resume analysis after refresh…';
        this.persist();
        this.startResumePolling(task.id);
        continue;
      }

      // Case 2: Page refreshed during active file upload before any resumeId returned
      if (task.stage === 'uploading' && (!task.resumeIds || task.resumeIds.length === 0)) {
        this.fail(
          task.id,
          'Upload was interrupted by page refresh before finishing. Please re-upload any unfinished files.',
          `${task.jobName} · Upload interrupted`
        );
        continue;
      }

      // Case 3: Page refreshed while ranking/verification/notification was running on backend -> reconcile!
      if (task.stage === 'verifying' || task.stage === 'ranking' || task.stage === 'notifying') {
        task.detail = 'Reconnecting to in-progress run after refresh…';
        this.persist();
        this.reconcileInFlightRanking(task.id);
      }
    }
  }

  /** Starts (or replaces) a live pipeline task for a specific job. */
  start(opts: {
    jobId: string;
    jobName: string;
    kind: PipelineKind;
    stage: PipelineStage;
    detail: string;
    progress?: number;
    subject?: string;
    includeNotify?: boolean;
    autoRank?: boolean;
    totalFiles?: number;
    runCountBefore?: number;
    notify?: boolean;
  }): string {
    for (const existing of this.tasks) {
      if (existing.jobId === opts.jobId) {
        this.clearTimers(existing.id);
      }
    }

    const now = Date.now();
    const id = `${opts.jobId}-${now}-${Math.random().toString(36).slice(2, 6)}`;
    const task: PipelineJobTask = {
      id,
      jobId: opts.jobId,
      jobName: opts.jobName.trim() || 'Job',
      kind: opts.kind,
      stage: opts.stage,
      progress: opts.progress ?? 12,
      detail: opts.detail,
      subject: opts.subject,
      includeNotify: opts.includeNotify,
      autoRank: opts.autoRank,
      resumeIds: [],
      completedResumeIds: [],
      failedResumeIds: [],
      totalFiles: opts.totalFiles,
      doneFiles: 0,
      runCountBefore: opts.runCountBefore,
      startedAt: now,
      updatedAt: now
    };
    this.tasks = [task, ...this.tasks.filter((x) => x.jobId !== opts.jobId)];
    this.persist();

    if (opts.notify) {
      toast.info(`${task.jobName} · ${STAGE_LABEL[task.stage]}`, task.detail, { duration: 3000 });
    }
    return id;
  }

  /** Attaches an uploaded resume ID to an active task and ensures background polling survives refresh/navigation. */
  attachUploadedResume(
    id: string,
    resumeId: string,
    opts: { fileName?: string; totalFiles?: number; autoRank?: boolean } = {}
  ) {
    const task = this.tasks.find((t) => t.id === id);
    if (!task) return;
    const list = task.resumeIds ?? [];
    if (!list.includes(resumeId)) {
      task.resumeIds = [...list, resumeId];
    }
    if (typeof opts.totalFiles === 'number') task.totalFiles = opts.totalFiles;
    if (typeof opts.autoRank === 'boolean') task.autoRank = opts.autoRank;
    task.updatedAt = Date.now();
    this.persist();

    if (!this.timers.has(id)) {
      this.startResumePolling(id);
    }
  }

  /** Polls Celery resume parsing status globally (survives navigation AND page refresh!). */
  private startResumePolling(id: string) {
    this.clearTimers(id);
    const pollTick = async () => {
      const task = this.tasks.find((t) => t.id === id);
      if (!task || task.stage === 'completed' || task.stage === 'failed') {
        this.clearTimers(id);
        return;
      }
      const allIds = task.resumeIds ?? [];
      if (allIds.length === 0) return;

      const doneSet = new Set(task.completedResumeIds ?? []);
      const failSet = new Set(task.failedResumeIds ?? []);
      const pending = allIds.filter((rid) => !doneSet.has(rid) && !failSet.has(rid));

      let newlyCompleted = 0;
      let newlyFailed = 0;

      for (const rid of pending) {
        try {
          const s = await resumeStatus(rid);
          const st = String(s.parse_status ?? s.status ?? '').toLowerCase();
          if (st === 'completed') {
            doneSet.add(rid);
            newlyCompleted += 1;
          } else if (st === 'failed') {
            failSet.add(rid);
            newlyFailed += 1;
          }
        } catch {
          /* transient network/poll error; retry next tick */
        }
      }

      task.completedResumeIds = [...doneSet];
      task.failedResumeIds = [...failSet];
      const total = Math.max(task.totalFiles ?? allIds.length, allIds.length);
      task.doneFiles = doneSet.size;
      task.updatedAt = Date.now();

      if (newlyCompleted > 0) {
        toast.info(
          `${task.jobName} · Analyzed`,
          `${doneSet.size} of ${total} resume${total === 1 ? '' : 's'} analyzed and ready.`
        );
      }
      if (newlyFailed > 0) {
        toast.error(
          `${task.jobName} · Analysis failed`,
          `${newlyFailed} resume${newlyFailed === 1 ? '' : 's'} could not be parsed.`
        );
      }

      const allSettled = doneSet.size + failSet.size >= total && allIds.length >= total;
      if (!allSettled) {
        if (task.stage !== 'uploading') {
          task.stage = 'analyzing';
          task.detail = `Analyzing resumes (${doneSet.size}/${total} analyzed)…`;
          task.progress = Math.max(task.progress, Math.round(32 + (doneSet.size / Math.max(1, total)) * 28));
        }
        this.persist();
        return;
      }

      // All uploaded resumes have finished parsing!
      this.clearTimers(id);
      if (doneSet.size === 0) {
        this.fail(id, `All ${failSet.size} resume(s) failed to parse.`, `${task.jobName} · Analysis failed`);
        return;
      }

      if (task.autoRank) {
        // Automatically run verification + ranking right from the global store!
        this.transition(id, 'verifying', 'Verifying candidate links & scoring applicants…', 66, {
          notify: true
        });
        this.simulateRankingPhases(id, { includesVerify: true, isRerun: false });
        try {
          const res = await runRanking(task.jobId);
          const verified = typeof res?.verified_count === 'number' ? res.verified_count : 0;
          if (verified > 0) {
            toast.info(
              `${task.jobName} · Verified`,
              `Completed verification checks for ${verified} applicant${verified === 1 ? '' : 's'}.`
            );
          }
          this.complete(
            id,
            `All ${doneSet.size} analyzed resume${doneSet.size === 1 ? '' : 's'} ranked${verified > 0 ? ` (${verified} verified)` : ''}.`,
            { title: `Ranking complete · ${task.jobName}`, verifiedCount: verified }
          );
        } catch (err) {
          const msg = err instanceof Error ? err.message : 'Auto-ranking failed';
          this.fail(id, msg, `${task.jobName} · Ranking failed`);
        }
      } else {
        this.complete(
          id,
          `${doneSet.size} resume${doneSet.size === 1 ? '' : 's'} analyzed${failSet.size ? ` (${failSet.size} failed)` : ''}. Ready for ranking.`,
          { title: `Analyzed · ${task.jobName}` }
        );
      }
    };

    const timer = setInterval(pollTick, 2500);
    this.timers.set(id, timer);
    void pollTick();
  }

  /** Reconciles an in-flight ranking/verification task after a full browser reload. */
  private reconcileInFlightRanking(id: string) {
    this.clearTimers(id);
    let checks = 0;
    const tick = async () => {
      const task = this.tasks.find((t) => t.id === id);
      if (!task || task.stage === 'completed' || task.stage === 'failed') {
        this.clearTimers(id);
        return;
      }
      checks += 1;
      try {
        const hist = await getRankingHistory(task.jobId);
        const latest = hist[0];
        const latestTs = latest?.created_at ?? latest?.executed_at;
        const latestMs = latestTs ? Date.parse(latestTs) : 0;
        const countIncreased =
          typeof task.runCountBefore === 'number' && hist.length > task.runCountBefore;
        const newerTimestamp = latestMs > 0 && latestMs >= task.startedAt - 2000;

        if (countIncreased || newerTimestamp) {
          this.complete(id, 'Ranking finished and scores are up to date.', {
            title: `Ranking complete · ${task.jobName}`
          });
          return;
        }
      } catch {
        /* ignore transient errors */
      }

      task.progress = Math.min(94, task.progress + 3);
      task.updatedAt = Date.now();
      this.persist();

      if (checks >= 15) {
        this.complete(id, 'Latest ranking data is ready to view.', {
          title: `Updated · ${task.jobName}`
        });
      }
    };

    const timer = setInterval(tick, 3000);
    this.timers.set(id, timer);
    void tick();
  }

  /**
   * Smoothly advances an in-flight synchronous ranking/verification request through visible stages
   * so users always see clear live progress while the backend runs.
   */
  simulateRankingPhases(
    id: string,
    opts: { includesVerify?: boolean; includeNotify?: boolean; isRerun?: boolean; subject?: string } = {}
  ) {
    this.clearTimers(id);
    let step = 0;
    const timer = setInterval(() => {
      const task = this.tasks.find((t) => t.id === id);
      if (!task || task.stage === 'completed' || task.stage === 'failed') {
        this.clearTimers(id);
        return;
      }
      step += 1;
      const target = opts.subject ? `for ${opts.subject}` : 'for applicants';
      if (step === 1 && opts.includesVerify) {
        this.transition(id, 'verifying', `Verifying email MX, authenticity & links ${target}…`, 46, {
          notify: true
        });
      } else if (step === 2 || (step === 1 && !opts.includesVerify)) {
        this.transition(
          id,
          'ranking',
          opts.isRerun
            ? `Re-scoring requirements & updating ranks ${target}…`
            : `Scoring requirements & computing AI decisions ${target}…`,
          72,
          { notify: false }
        );
      } else if (step === 4 && opts.includeNotify) {
        this.transition(id, 'notifying', `Applying decisions & sending notifications ${target}…`, 88, {
          notify: true
        });
      } else {
        task.progress = Math.min(94, task.progress + 3);
        task.updatedAt = Date.now();
        this.persist();
      }
    }, 1800);
    this.timers.set(id, timer);
  }

  /** Moves a task to a new stage and optionally pops a concise stage-transition notification. */
  transition(
    id: string,
    stage: PipelineStage,
    detail: string,
    progress?: number,
    opts?: {
      notify?: boolean;
      notifyTitle?: string;
      doneFiles?: number;
      totalFiles?: number;
      verifiedCount?: number;
    }
  ) {
    const task = this.tasks.find((t) => t.id === id);
    if (!task) return;
    task.stage = stage;
    task.detail = detail;
    task.updatedAt = Date.now();
    if (typeof progress === 'number') {
      task.progress = Math.max(task.progress, Math.min(99, progress));
    }
    if (typeof opts?.doneFiles === 'number') task.doneFiles = opts.doneFiles;
    if (typeof opts?.totalFiles === 'number') task.totalFiles = opts.totalFiles;
    if (typeof opts?.verifiedCount === 'number') task.verifiedCount = opts.verifiedCount;
    this.persist();

    if (opts?.notify) {
      const heading = opts.notifyTitle ?? `${task.jobName} · ${STAGE_LABEL[stage]}`;
      toast.info(heading, detail, { duration: 3200 });
    }
  }

  /** Marks a task completed, pops a completion notification with optional View Ranking shortcut, and auto-clears. */
  complete(
    id: string,
    detail: string,
    opts?: {
      title?: string;
      verifiedCount?: number;
      showViewAction?: boolean;
      autoDismissMs?: number;
    }
  ) {
    this.clearTimers(id);
    const task = this.tasks.find((t) => t.id === id);
    if (!task) return;
    const now = Date.now();
    task.stage = 'completed';
    task.progress = 100;
    task.detail = detail;
    task.updatedAt = now;
    task.finishedAt = now;
    if (typeof opts?.verifiedCount === 'number') task.verifiedCount = opts.verifiedCount;
    this.persist();

    this.lastCompleted = { jobId: task.jobId, kind: task.kind, at: now };

    const popupTitle = opts?.title ?? `Completed · ${task.jobName}`;
    const showAction =
      opts?.showViewAction ??
      (typeof window !== 'undefined' && !window.location.pathname.includes(`/jobs/${task.jobId}/applicants`));

    toast.success(popupTitle, detail, {
      duration: 5500,
      action: showAction
        ? {
            label: 'View ranking',
            onClick: () => {
              goto(`/jobs/${task.jobId}/applicants`);
            }
          }
        : undefined
    });

    const ms = opts?.autoDismissMs ?? 10000;
    if (ms > 0) {
      const dt = setTimeout(() => this.dismiss(id), ms);
      this.dismissTimers.set(id, dt);
    }
  }

  /** Marks a task failed and surfaces a clear error popup. */
  fail(id: string, detail: string, title?: string) {
    this.clearTimers(id);
    const task = this.tasks.find((t) => t.id === id);
    if (!task) return;
    const now = Date.now();
    task.stage = 'failed';
    task.detail = detail;
    task.updatedAt = now;
    task.finishedAt = now;
    this.persist();

    toast.error(title ?? `${task.jobName} · Process failed`, detail);

    const dt = setTimeout(() => this.dismiss(id), 12000);
    this.dismissTimers.set(id, dt);
  }

  dismiss(id: string) {
    this.clearTimers(id);
    this.tasks = this.tasks.filter((t) => t.id !== id);
    this.persist();
  }

  clearAll() {
    for (const t of this.tasks) this.clearTimers(t.id);
    this.tasks = [];
    this.hydrated = false;
    this.persist();
  }
}

export const pipelineProgress = new PipelineProgressStore();
