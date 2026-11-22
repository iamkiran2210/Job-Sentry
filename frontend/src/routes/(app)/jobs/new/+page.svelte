<script lang="ts">
  import { goto } from '$app/navigation';
  import { createJob, updateJob, addRequirement, requestSuggestions, parseSuggestions, shapeOf } from '$lib/services/jobs';
  import { toast } from '$lib/stores/toast.svelte';
  import { toastError } from '$lib/errors';
  import { weightStatus, normalizeRequirements, fmtPct } from '$lib/weights';
  import JobForm from '$lib/components/JobForm.svelte';
  import RequirementsPanel from '$lib/components/RequirementsPanel.svelte';
  import type { JobInput, RequirementInput } from '$lib/types/job';

  let form = $state<{ getValues: () => JobInput | null }>();
  let description = $state('');
  let items = $state<RequirementInput[]>([]);
  let jobId = $state<string | null>(null); // set once a draft exists (the AI needs a saved job to read)
  const ws = $derived(weightStatus(items));
  const blocked = $derived(ws.ok ? '' : `Preferred requirement weights total ${fmtPct(ws.totalBps)}. They must total 100% before you can create the job.`);

  async function ensureDraft(): Promise<boolean> {
    const v = form?.getValues();
    if (!v) { toast.error('Fill in the job title and description first', 'The AI reads the job text, so a draft is saved first.'); return false; }
    if (jobId) return true;
    try { jobId = (await createJob(v)).id; toast.info('Draft saved', 'The AI needs a saved job to read. Keep editing here.'); return true; }
    catch (e) { toastError(e, 'Could not save the draft'); return false; }
  }
  async function suggest(d: string) {
    const raw = await requestSuggestions(jobId!, d); const s = parseSuggestions(raw);
    if (!s.length) { console.warn('extract-requirements response', raw); toast.info('No readable suggestions', `The AI replied with: ${shapeOf(raw)}. Try a more detailed description.`); }
    return s;
  }
  async function create(v: JobInput) {
    if (!ws.ok) {
      items = normalizeRequirements(items);
    }
    const j = jobId ? await updateJob(jobId, v) : await createJob(v);
    const id = jobId ?? j.id;
    let failed = 0;
    const normalizedItems = normalizeRequirements(items);
    for (const r of normalizedItems) {
      try {
        await addRequirement(id, r);
      } catch {
        failed++;
      }
    }
    if (failed) toast.error(`${failed} requirement${failed === 1 ? '' : 's'} could not be saved`, 'Add them again on the job page.');
    else toast.success('Job created', normalizedItems.length ? `${normalizedItems.length} requirement${normalizedItems.length === 1 ? '' : 's'} saved.` : 'Add requirements next, then publish.');
    await goto(`/jobs/${id}`);
  }
</script>

<nav class="mb-2 text-sm text-muted-foreground"><a href="/jobs">Jobs</a> / Create job</nav>
<h1 class="text-2xl font-semibold">Create job</h1>
<p class="mb-6 text-sm text-muted-foreground">Describe the role and set its requirements on one page. The job is saved as a draft.</p>
<JobForm bind:this={form} bind:description submitLabel="Create job" cancelHref="/jobs" onSubmit={create} {blocked}>
  {#snippet extra()}
    <RequirementsPanel {items} descriptionSeed={description} ensureReady={ensureDraft} onSuggest={suggest}
      onAdd={async (r) => { items = [...items, r]; }}
      onUpdate={async (i, patch) => { items = items.map((x, k) => (k === i ? { ...x, ...patch } : x)); }}
      onRemove={async (i) => { items = items.filter((_, k) => k !== i); }} />
  {/snippet}
</JobForm>
