<script lang="ts">
  import { listJobs } from '$lib/services/jobs';
  import { ApiError } from '$lib/services/api-client';
  import { toastError } from '$lib/errors';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { fmtDate, humanize } from '$lib/utils';
  import type { Job } from '$lib/types/job';

  import * as Table from '$lib/components/ui/table';
  import * as Select from '$lib/components/ui/select';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Card, CardContent } from '$lib/components/ui/card';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import { Plus, Search, AlertCircle, RefreshCw } from '@lucide/svelte';

  let jobs = $state<Job[]>([]);
  let st = $state<'loading' | 'ready' | 'error'>('loading');
  let err = $state('');
  let q = $state('');
  let status = $state('all');

  async function load() {
    st = 'loading';
    try {
      jobs = await listJobs(status === 'all' ? undefined : status);
      st = 'ready';
    } catch (e) {
      err = e instanceof ApiError ? e.message : 'Failed to load jobs.';
      st = 'error';
      toastError(e, 'Could not load jobs');
    }
  }

  load();

  const shown = $derived(
    jobs.filter((j) =>
      `${j.title} ${j.department ?? ''} ${j.location ?? ''}`.toLowerCase().includes(q.toLowerCase())
    )
  );

  const NP = 'Not provided';
</script>

<div class="space-y-6">
  <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
    <div>
      <h1 class="text-3xl font-bold tracking-tight text-foreground">Jobs</h1>
      <p class="mt-1 text-sm text-muted-foreground">Manage active openings, requirements and hiring stages</p>
    </div>
    <Button href="/jobs/new" class="font-medium shrink-0">
      <Plus class="mr-1.5 size-4" /> Create job
    </Button>
  </div>

  <div class="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
    <div class="relative w-full sm:w-72">
      <Search class="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
      <Input
        type="search"
        aria-label="Search jobs"
        placeholder="Search jobs by title, department…"
        bind:value={q}
        class="pl-9"
      />
    </div>

    <div class="w-full sm:w-48">
      <Select.Root
        type="single"
        bind:value={status}
        onValueChange={() => load()}
      >
        <Select.Trigger aria-label="Filter by status" class="w-full">
          {status === 'all' ? 'All statuses' : humanize(status)}
        </Select.Trigger>
        <Select.Content>
          <Select.Item value="all">All statuses</Select.Item>
          {#each ['draft', 'active', 'paused', 'closed', 'archived'] as s}
            <Select.Item value={s}>{humanize(s)}</Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
    </div>
  </div>

  {#if st === 'loading'}
    <Skeleton rows={6} />
  {:else if st === 'error'}
    <Alert variant="destructive">
      <AlertCircle class="size-4" />
      <AlertTitle>Error loading jobs</AlertTitle>
      <AlertDescription class="flex items-center justify-between gap-4 mt-2">
        <span>{err}</span>
        <Button variant="outline" size="sm" onclick={load} class="shrink-0">
          <RefreshCw class="mr-1.5 size-3.5" /> Retry
        </Button>
      </AlertDescription>
    </Alert>
  {:else if shown.length === 0}
    <Card class="border-border bg-card">
      <CardContent class="p-12 text-center text-sm text-muted-foreground">
        {jobs.length ? 'No jobs match your filters.' : 'No jobs created yet. Post your first opening to get started.'}
      </CardContent>
    </Card>
  {:else}
    <Card class="border-0 bg-card overflow-hidden shadow-sm">
      <Table.Root>
        <Table.Header>
          <Table.Row>
            <Table.Head class="text-left font-semibold text-foreground">Title</Table.Head>
            <Table.Head class="text-left font-semibold text-foreground">Department</Table.Head>
            <Table.Head class="text-left font-semibold text-foreground">Location</Table.Head>
            <Table.Head class="text-center font-semibold text-foreground">Status</Table.Head>
            <Table.Head class="text-right font-semibold text-foreground">Created</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each shown as j (j.id)}
            <Table.Row class="hover:bg-muted/30 transition-colors">
              <Table.Cell class="text-left font-medium">
                <a class="text-primary hover:underline font-semibold" href={`/jobs/${j.id}`}>
                  {j.title}
                </a>
              </Table.Cell>
              <Table.Cell class="text-left text-muted-foreground">
                {j.department ?? NP}
              </Table.Cell>
              <Table.Cell class="text-left text-muted-foreground">
                {j.location ? `${j.location} · ${humanize(j.work_mode)}` : `${NP} · ${humanize(j.work_mode)}`}
              </Table.Cell>
              <Table.Cell class="text-center">
                <StatusBadge status={j.status} />
              </Table.Cell>
              <Table.Cell class="text-right text-muted-foreground text-sm tabular-nums">
                {fmtDate(j.created_at)}
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    </Card>
  {/if}
</div>
