<script lang="ts">
  import { page } from '$app/state';
  import { compare } from '$lib/services/applications';
  import { ApiError } from '$lib/services/api-client';
  import { toastError } from '$lib/errors';
  import DataView from '$lib/components/DataView.svelte';
  import AutoViz from '$lib/components/AutoViz.svelte';
  import { isObj } from '$lib/utils';

  import { Card, CardHeader, CardTitle, CardContent } from '$lib/components/ui/card';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import { Button } from '$lib/components/ui/button';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import { GitCompare, AlertTriangle, ArrowLeft } from '@lucide/svelte';

  const id = page.params.jobId!;
  const ids = (page.url.searchParams.get('ids') ?? '').split(',').filter(Boolean);
  let data = $state<Record<string, unknown> | null>(null);
  let err = $state('');

  if (ids.length < 2 || ids.length > 4) {
    err = 'Choose 2 to 4 applicants from the ranking page to run side-by-side comparison.';
  } else {
    compare(id, ids)
      .then((d) => (data = d))
      .catch((e) => {
        err = e instanceof ApiError ? e.message : 'Comparison failed.';
        toastError(e, 'Comparison failed');
      });
  }

  const parts: [string, string][] = [
    ['applications', 'Applicants Overview'],
    ['categories', 'Category Match Scores'],
    ['mandatory_coverage', 'Mandatory Criteria Alignment'],
    ['skill_coverage', 'Extracted Skills Coverage'],
    ['differences', 'Key Variance Analysis']
  ];
</script>

<div class="space-y-6">
  <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
    <div class="space-y-1">
      <h1 class="text-3xl font-bold tracking-tight text-foreground">Compare Applicants</h1>
      <p class="text-sm text-muted-foreground">
        Side-by-side evaluation across role requirements. Higher scores reflect closer keyword/experience alignment, not overall human worth.
      </p>
    </div>

    <Button variant="outline" href={`/jobs/${id}/applicants`}>
      <ArrowLeft class="mr-1.5 size-4" /> Back to ranking
    </Button>
  </div>

  {#if err}
    <Alert variant="destructive">
      <AlertTriangle class="size-4" />
      <AlertTitle>Cannot compare applicants</AlertTitle>
      <AlertDescription class="mt-1 flex items-center justify-between">
        <span>{err}</span>
        <Button variant="outline" size="sm" href={`/jobs/${id}/applicants`}>Back to ranking</Button>
      </AlertDescription>
    </Alert>
  {:else if !data}
    <Skeleton rows={6} height="h-24" />
  {:else}
    <div class="space-y-6">
      <AutoViz value={{ comparison: data.comparison }} stats={false} />
      <AutoViz value={data.skill_coverage} stats={false} />

      {#each parts as [k, title]}
        {#if data[k]}
          <Card class="border-border bg-card shadow-sm">
            <CardHeader class="pb-3">
              <CardTitle class="text-lg">{title}</CardTitle>
            </CardHeader>
            <CardContent>
              <DataView value={data[k]} />
            </CardContent>
          </Card>
        {/if}
      {/each}

      {#if Array.isArray(data.disclaimers) && data.disclaimers.length}
        <div class="rounded-lg border border-border bg-muted/20 p-4 space-y-1 text-xs text-muted-foreground">
          {#each data.disclaimers as d}
            <p>{isObj(d) ? JSON.stringify(d) : d}</p>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>
