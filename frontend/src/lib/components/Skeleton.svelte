<script lang="ts">
  import { Skeleton } from '$lib/components/ui/skeleton';

  let { rows = 5, cols = 1, height = 'h-10', class: className }: { rows?: number; cols?: number; height?: string; class?: string } = $props();
</script>

<div class={`grid gap-3 ${className ?? ''}`} style={`grid-template-columns:repeat(${cols},minmax(0,1fr))`} role="status" aria-label="Loading">
  {#each Array(rows * cols) as _}
    <Skeleton class={`w-full ${height}`} />
  {/each}
</div>
