import { afterEach, describe, expect, it } from 'vitest';
import { pipelineProgress } from '$lib/stores/pipeline-progress.svelte';

describe('pipeline-progress store', () => {
  afterEach(() => {
    pipelineProgress.clearAll();
  });

  it('tracks job-specific pipeline stages from upload through notification and completion', () => {
    const id = pipelineProgress.start({
      jobId: 'job-1',
      jobName: 'Senior ML Engineer',
      kind: 'upload_and_rank',
      stage: 'uploading',
      detail: 'Uploading 2 resumes…',
      includeNotify: true,
      progress: 10
    });

    expect(pipelineProgress.tasks).toHaveLength(1);
    expect(pipelineProgress.tasks[0].jobName).toBe('Senior ML Engineer');
    expect(pipelineProgress.tasks[0].stage).toBe('uploading');

    pipelineProgress.transition(id, 'analyzing', 'Analyzing 2 resumes…', 40);
    expect(pipelineProgress.tasks[0].stage).toBe('analyzing');
    expect(pipelineProgress.tasks[0].progress).toBe(40);

    pipelineProgress.transition(id, 'verifying', 'Verifying candidate links…', 65);
    expect(pipelineProgress.tasks[0].stage).toBe('verifying');

    pipelineProgress.transition(id, 'notifying', 'Sending candidate emails…', 90);
    expect(pipelineProgress.tasks[0].stage).toBe('notifying');

    pipelineProgress.complete(id, 'Ranked & notified 2 applicants.', {
      autoDismissMs: 0,
      showViewAction: false
    });
    expect(pipelineProgress.tasks[0].stage).toBe('completed');
    expect(pipelineProgress.tasks[0].progress).toBe(100);
    expect(pipelineProgress.lastCompleted?.jobId).toBe('job-1');

    pipelineProgress.dismiss(id);
    expect(pipelineProgress.tasks).toHaveLength(0);
  });

  it('persists progress to localStorage and restores across simulated page refresh', () => {
    const id = pipelineProgress.start({
      jobId: 'job-refresh',
      jobName: 'Platform Architect',
      kind: 'rank',
      stage: 'ranking',
      detail: 'Scoring candidates…',
      progress: 70
    });

    const raw = window.localStorage.getItem('js_pipeline_tasks_v1');
    expect(raw).toBeTruthy();
    expect(raw).toContain('Platform Architect');

    // Simulate memory wipe on page reload while keeping localStorage intact
    pipelineProgress.tasks = [];
    (pipelineProgress as unknown as { hydrated: boolean }).hydrated = false;
    pipelineProgress.hydrateAndResume();

    expect(pipelineProgress.tasks).toHaveLength(1);
    expect(pipelineProgress.tasks[0].id).toBe(id);
    expect(pipelineProgress.tasks[0].jobName).toBe('Platform Architect');
    expect(pipelineProgress.tasks[0].stage).toBe('ranking');

    pipelineProgress.clearAll();
    expect(window.localStorage.getItem('js_pipeline_tasks_v1')).toBeNull();
  });

  it('handles failure state cleanly and allows dismissal', () => {
    const id = pipelineProgress.start({
      jobId: 'job-2',
      jobName: 'Backend Lead',
      kind: 'rescore',
      stage: 'analyzing',
      detail: 'Re-scoring all applicants…'
    });
    pipelineProgress.fail(id, 'Provider timeout');
    expect(pipelineProgress.tasks[0].stage).toBe('failed');
    expect(pipelineProgress.tasks[0].detail).toBe('Provider timeout');

    pipelineProgress.dismiss(id);
    expect(pipelineProgress.tasks).toHaveLength(0);
  });
});
