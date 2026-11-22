<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import {
    getJob,
    jobAction,
    listRequirements,
    addRequirement,
    updateRequirement,
    deleteRequirement,
    deleteJob,
    cleanDeleteJob,
    requestSuggestions,
    parseSuggestions,
    shapeOf
  } from '$lib/services/jobs';
  import { toast } from '$lib/stores/toast.svelte';
  import { toastError } from '$lib/errors';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { weightStatus, fmtPct } from '$lib/weights';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import JobAccess from '$lib/components/JobAccess.svelte';
  import RequirementsPanel from '$lib/components/RequirementsPanel.svelte';
  import { humanize } from '$lib/utils';
  import type { Job, Requirement } from '$lib/types/job';

  import { Button } from '$lib/components/ui/button';
  import { Card, CardHeader, CardTitle, CardContent } from '$lib/components/ui/card';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import {
    Users,
    UploadCloud,
    Pencil,
    Trash2,
    AlertTriangle,
    Building2,
    MapPin,
    Clock,
    Briefcase
  } from '@lucide/svelte';

  const id = page.params.jobId!;
  let job = $state<Job | null>(null);
  let reqs = $state<Requirement[]>([]);
  let st = $state<'loading' | 'ready' | 'error'>('loading');
  let busy = $state(false);

  async function load() {
    try {
      [job, reqs] = await Promise.all([getJob(id), listRequirements(id)]);
      st = 'ready';
    } catch (e) {
      st = 'error';
      toastError(e, 'Could not load job');
    }
  }

  load();

  async function run(fn: () => Promise<unknown>) {
    if (busy) return;
    busy = true;
    try {
      await fn();
    } catch (e) {
      toastError(e);
    } finally {
      busy = false;
    }
  }

  const DONE = {
    publish: 'Job is now live',
    pause: 'Job paused',
    close: 'Job closed',
    archive: 'Job archived'
  };

  const act = (a: 'publish' | 'pause' | 'close' | 'archive') =>
    run(async () => {
      await jobAction(id, a);
      job = await getJob(id);
      toast.success(DONE[a]);
    });

  const removeJob = async () => {
    const isDraft = job?.status === 'draft';
    if (
      await confirmDialog({
        title: isDraft ? 'Delete this draft?' : `Delete "${job?.title ?? 'this job'}"?`,
        message: isDraft
          ? 'The draft job and all its requirements, applications, and KPI metrics will be permanently deleted.'
          : 'This permanently deletes the job along with all its applications, resumes, scores, verification records, and KPI metrics. This cannot be undone.',
        confirmLabel: isDraft ? 'Delete draft' : 'Delete job',
        danger: true
      })
    ) {
      run(async () => {
        if (isDraft) {
          await deleteJob(id);
          toast.success('Draft deleted');
        } else {
          await cleanDeleteJob(id);
          toast.success('Job deleted', 'Job and all associated KPI data removed.');
        }
        await goto('/jobs');
      });
    }
  };

  const ws = $derived(weightStatus(reqs));
  const ACTIONS_BY_STATUS: Record<string, ('publish' | 'pause' | 'close' | 'archive')[]> = {
    draft: ['publish'],
    active: ['pause', 'close'],
    paused: ['publish', 'close'],
    closed: ['archive']
  };
  const actions = $derived(job?.status ? ACTIONS_BY_STATUS[job.status] ?? [] : []);

  async function suggest(d: string) {
    const raw = await requestSuggestions(id, d);
    const s = parseSuggestions(raw);
    if (!s.length) {
      console.warn('extract-requirements response', raw);
      toast.info('No readable suggestions', `The AI replied with: ${shapeOf(raw)}. Try a more detailed description.`);
    }
    return s;
  }

  async function withEditableJob<T>(fn: () => Promise<T>): Promise<T> {
    if (job?.status === 'active') {
      await jobAction(id, 'pause');
      job = await getJob(id);
    }
    return fn();
  }

  const NP = 'Not provided';
</script>

{#if st === 'loading'}
  <Skeleton rows={4} height="h-20" />
{:else if st === 'error'}
  <Alert variant="destructive">
    <AlertTriangle class="size-4" />
    <AlertTitle>Error loading job</AlertTitle>
    <AlertDescription>
      We could not load this job posting. <a class="underline font-medium" href="/jobs">Return to jobs list</a>.
    </AlertDescription>
  </Alert>
{:else if job}
  <div class="space-y-6">
    <!-- Header Section -->
    <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
      <div class="space-y-1.5">
        <div class="flex flex-wrap items-center gap-3">
          <h1 class="text-3xl font-bold tracking-tight text-foreground">{job.title}</h1>
          <StatusBadge status={job.status} />
        </div>
        <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
          <span class="inline-flex items-center gap-1.5">
            <Building2 class="size-3.5" /> {job.department ?? NP}
          </span>
          <span class="inline-flex items-center gap-1.5">
            <MapPin class="size-3.5" /> {job.location ?? NP}
          </span>
          <span class="inline-flex items-center gap-1.5">
            <Briefcase class="size-3.5" /> {humanize(job.work_mode)}
          </span>
          <span class="inline-flex items-center gap-1.5">
            <Clock class="size-3.5" /> {humanize(job.employment_type)}
          </span>
        </div>
      </div>

      <!-- Action buttons -->
      <div class="flex flex-wrap items-center gap-2">
        <Button href={`/jobs/${id}/applicants`} class="font-medium">
          <Users class="mr-1.5 size-4" /> Applicants
        </Button>
        <Button variant="outline" href={`/jobs/${id}/upload`}>
          <UploadCloud class="mr-1.5 size-4" /> Upload resumes
        </Button>
        <Button variant="outline" href={`/jobs/${id}/edit`}>
          <Pencil class="mr-1.5 size-4" /> Edit
        </Button>

        <Button
          variant="outline"
          disabled={busy}
          onclick={removeJob}
          class="text-destructive hover:bg-destructive/10 border-destructive/30"
        >
          <Trash2 class="mr-1.5 size-4" /> {job.status === 'draft' ? 'Delete draft' : 'Delete job'}
        </Button>

        {#each actions as a}
          <Button
            variant={a === 'publish' ? 'default' : 'secondary'}
            disabled={busy || (a === 'publish' && !ws.ok)}
            title={a === 'publish' && !ws.ok ? 'Preferred weights must total 100% before publishing' : undefined}
            onclick={() => act(a)}
            class="capitalize"
          >
            {a}
          </Button>
        {/each}
      </div>
    </div>

    <!-- Weight validation banner -->
    {#if !ws.ok}
      <Alert class="border-amber-200 bg-amber-50/70 text-amber-900">
        <AlertTriangle class="size-4 text-amber-600" />
        <AlertTitle class="font-semibold text-amber-900">Invalid Requirement Weights</AlertTitle>
        <AlertDescription class="text-amber-800">
          Preferred requirement weights currently total <strong>{fmtPct(ws.totalBps)}</strong>. They must total exactly 100% before this job can be published.
        </AlertDescription>
      </Alert>
    {/if}

    <!-- Description Card -->
    <Card class="border-border bg-card shadow-sm">
      <CardHeader>
        <CardTitle class="text-lg">Job Description</CardTitle>
      </CardHeader>
      <CardContent>
        <p class="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">{job.description}</p>
      </CardContent>
    </Card>

    <!-- Requirements Panel -->
    <RequirementsPanel
      items={reqs}
      descriptionSeed={job.description}
      onSuggest={suggest}
      onAdd={async (r) => {
        await withEditableJob(async () => {
          reqs = [...reqs, await addRequirement(id, r)];
        });
      }}
      onUpdate={async (i, patch) => {
        await withEditableJob(async () => {
          const u = await updateRequirement(id, reqs[i].id, patch);
          reqs = reqs.map((x, k) => (k === i ? { ...x, ...patch, ...u } : x));
        });
      }}
      onRemove={async (i) => {
        await withEditableJob(async () => {
          await deleteRequirement(id, reqs[i].id);
          reqs = reqs.filter((_, k) => k !== i);
        });
      }}
    />

    <!-- Access control (admin) -->
    <JobAccess jobId={id} />
  </div>
{/if}
