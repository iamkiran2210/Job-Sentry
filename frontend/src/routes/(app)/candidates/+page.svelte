<script lang="ts">
  import { buildDirectory, deleteCandidate, type DirectoryEntry } from '$lib/services/directory';
  import { toast } from '$lib/stores/toast.svelte';
  import { toastError } from '$lib/errors';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import { fmtDate } from '$lib/utils';

  import * as Table from '$lib/components/ui/table';
  import { Input } from '$lib/components/ui/input';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { Card, CardContent } from '$lib/components/ui/card';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import { Search, AlertCircle, Trash2, Loader2 } from '@lucide/svelte';

  let all = $state<DirectoryEntry[]>([]);
  let st = $state<'loading' | 'ready' | 'error'>('loading');
  let q = $state('');
  let pg = $state(1);
  let deletingId = $state<string | null>(null);
  const SIZE = 25;

  async function removeCandidate(entry: DirectoryEntry) {
    if (!entry.candidateId || deletingId) return;
    const ok = await confirmDialog({
      title: `Delete ${entry.name ?? 'this candidate'}?`,
      message:
        'This permanently deletes the candidate profile and uploaded resumes. Past immutable ranking audit logs are preserved without personal data.',
      confirmLabel: 'Delete candidate',
      danger: true
    });
    if (!ok) return;
    deletingId = entry.candidateId;
    try {
      await deleteCandidate(entry.candidateId);
      all = all.filter((x) => x.candidateId !== entry.candidateId);
      toast.success('Candidate deleted', `${entry.name ?? 'Candidate'} has been removed.`);
    } catch (e) {
      toastError(e, 'Could not delete candidate');
    } finally {
      deletingId = null;
    }
  }

  buildDirectory()
    .then((d) => {
      all = d;
      st = 'ready';
    })
    .catch((e) => {
      st = 'error';
      toastError(e, 'Could not load candidates');
    });

  const filtered = $derived(
    all.filter((e) => `${e.name ?? ''} ${e.email ?? ''}`.toLowerCase().includes(q.toLowerCase()))
  );
  const pages = $derived(Math.max(1, Math.ceil(filtered.length / SIZE)));
  const rows = $derived(filtered.slice((pg - 1) * SIZE, pg * SIZE));

  const NP = 'Not provided';
</script>

<div class="space-y-6">
  <div class="space-y-1">
    <h1 class="text-3xl font-bold tracking-tight text-foreground">Candidate Directory</h1>
    <p class="text-sm text-muted-foreground">
      Unified pool of all applicants. Scores, ranks, and statuses are strictly job-specific.
    </p>
  </div>

  <div class="relative w-full sm:w-72">
    <Search class="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
    <Input
      type="search"
      aria-label="Search candidates"
      placeholder="Search candidate name or email…"
      bind:value={q}
      oninput={() => (pg = 1)}
      class="pl-9"
    />
  </div>

  {#if st === 'loading'}
    <Skeleton rows={6} />
  {:else if st === 'error'}
    <Alert variant="destructive">
      <AlertCircle class="size-4" />
      <AlertTitle>Error loading candidate directory</AlertTitle>
      <AlertDescription>Could not retrieve candidate directory data.</AlertDescription>
    </Alert>
  {:else if rows.length === 0}
    <Card class="border-border bg-card">
      <CardContent class="p-12 text-center text-sm text-muted-foreground">
        {all.length ? 'No candidates match your search.' : 'No candidates in directory yet. Upload resumes to a job to build your talent pool.'}
      </CardContent>
    </Card>
  {:else}
    <Card class="border-0 bg-card shadow-sm w-full min-w-0 overflow-hidden">
      <div class="overflow-x-auto w-full">
        <Table.Root class="w-full">
          <Table.Header>
            <Table.Row>
              <Table.Head class="w-48 text-left font-semibold text-foreground">Name</Table.Head>
              <Table.Head class="w-56 text-left font-semibold text-foreground">Email</Table.Head>
              <Table.Head class="w-28 text-center font-semibold text-foreground">Applications</Table.Head>
              <Table.Head class="min-w-64 text-left font-semibold text-foreground">Jobs Applied</Table.Head>
              <Table.Head class="w-36 text-right font-semibold text-foreground">Last Applied</Table.Head>
              <Table.Head class="w-24 text-right font-semibold text-foreground">Actions</Table.Head>
            </Table.Row>
          </Table.Header>

          <Table.Body>
            {#each rows as e (e.key)}
              <Table.Row class="hover:bg-muted/30 transition-colors">
                <Table.Cell class="w-48 text-left whitespace-normal font-medium align-middle">
                  {#if e.candidateId}
                    <a class="font-semibold text-primary hover:underline" href={`/candidates/${e.candidateId}`}>
                      {e.name ?? 'Unnamed candidate'}
                    </a>
                  {:else}
                    <span class="font-semibold text-foreground">{e.name ?? 'Unnamed candidate'}</span>
                  {/if}
                </Table.Cell>
                <Table.Cell class="w-56 text-left whitespace-normal break-all text-muted-foreground text-sm align-middle">
                  {e.email ?? NP}
                </Table.Cell>
                <Table.Cell class="w-28 text-center tabular-nums font-semibold text-foreground align-middle">
                  {e.applications}
                </Table.Cell>
                <Table.Cell class="min-w-64 text-left whitespace-normal align-middle">
                  {#if e.jobs.length}
                    <div class="flex flex-wrap items-center gap-1.5 py-0.5">
                      {#each e.jobs as j}
                        <Badge variant="secondary" class="text-xs font-normal bg-slate-100 text-slate-800 border-slate-200">
                          {j}
                        </Badge>
                      {/each}
                    </div>
                  {:else}
                    <span class="text-muted-foreground text-xs">{NP}</span>
                  {/if}
                </Table.Cell>
                <Table.Cell class="w-36 text-right whitespace-nowrap text-muted-foreground text-sm align-middle">
                  {fmtDate(e.lastApplied ?? undefined)}
                </Table.Cell>
                <Table.Cell class="w-24 text-right align-middle">
                  {#if e.candidateId}
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={deletingId === e.candidateId}
                      onclick={() => removeCandidate(e)}
                      class="h-7 px-2 text-xs text-destructive hover:text-destructive hover:bg-destructive/10"
                      aria-label={`Delete ${e.name ?? 'candidate'}`}
                    >
                      {#if deletingId === e.candidateId}
                        <Loader2 class="size-3.5 animate-spin" />
                      {:else}
                        <Trash2 class="size-3.5" />
                      {/if}
                    </Button>
                  {/if}
                </Table.Cell>
              </Table.Row>
            {/each}
          </Table.Body>
        </Table.Root>
      </div>

      <!-- Pagination -->
      <div class="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-xs text-muted-foreground">
        <span>Showing {rows.length} of {filtered.length} candidates</span>
        <div class="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={pg <= 1}
            onclick={() => pg--}
            class="h-7 px-2.5 text-xs"
          >
            Previous
          </Button>
          <span class="px-2 font-medium text-foreground">
            Page {pg} of {pages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={pg >= pages}
            onclick={() => pg++}
            class="h-7 px-2.5 text-xs"
          >
            Next
          </Button>
        </div>
      </div>
    </Card>
  {/if}
</div>
