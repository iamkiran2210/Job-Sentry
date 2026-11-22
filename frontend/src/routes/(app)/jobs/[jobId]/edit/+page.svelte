<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { getJob, updateJob } from '$lib/services/jobs';
  import { toast } from '$lib/stores/toast.svelte';
  import { toastError } from '$lib/errors';
  import JobForm from '$lib/components/JobForm.svelte';
  import type { Job } from '$lib/types/job';
  const id = page.params.jobId!;
  let job = $state<Job | null>(null); let err = $state('');
  getJob(id).then((j) => (job = j)).catch((e) => { err = e.message; toastError(e, 'Could not load job'); });
</script>
<nav class="mb-2 text-sm text-muted-foreground"><a href="/jobs">Jobs</a> / <a href={`/jobs/${id}`}>{job?.title ?? '…'}</a> / Edit</nav>
<h1 class="mb-6 text-2xl font-semibold">Edit job</h1>
{#if err}<p role="alert" class="text-danger">{err}</p>
{:else if !job}<p role="status" class="text-muted-foreground">Loading…</p>
{:else}<JobForm initial={job} submitLabel="Save changes" cancelHref={`/jobs/${id}`} onSubmit={async (b) => { await updateJob(id, b); toast.success('Job updated'); await goto(`/jobs/${id}`); }} />{/if}
