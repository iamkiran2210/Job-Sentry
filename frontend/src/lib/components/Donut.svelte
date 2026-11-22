<script lang="ts">
  import { colorForLabel } from '$lib/viz-colors';
  let { items }: { items: { label: string; value: number }[] } = $props();
  const r = 48, c = 2 * Math.PI * r;
  const total = $derived(items.reduce((a, i) => a + i.value, 0));
  const arcs = $derived(items.reduce<{ len: number; off: number; color: string }[]>((acc, i, k) => {
    const len = total ? (i.value / total) * c : 0;
    const off = acc.length ? acc[acc.length - 1].off + acc[acc.length - 1].len : 0;
    return [...acc, { len, off, color: colorForLabel(i.label, k) }];
  }, []));
</script>
<div class="flex flex-wrap items-center gap-6">
  <svg width="136" height="136" viewBox="0 0 120 120" role="img" aria-label={`Distribution of ${total} items`}>
    <circle cx="60" cy="60" {r} fill="none" stroke="currentColor" class="text-muted/60" stroke-width="16" />
    <g transform="rotate(-90 60 60)">
      {#each arcs as a}
        {#if a.len > 0}
          <circle cx="60" cy="60" {r} fill="none" stroke={a.color} stroke-width="16" stroke-dasharray={`${a.len} ${c - a.len}`} stroke-dashoffset={-a.off} />
        {/if}
      {/each}
    </g>
    <text x="60" y="61" text-anchor="middle" font-size="19" font-weight="700" fill="currentColor" class="text-foreground">{total}</text>
    <text x="60" y="74" text-anchor="middle" font-size="8.5" font-weight="600" fill="currentColor" class="text-muted-foreground">TOTAL</text>
  </svg>
  <ul class="space-y-1.5 text-sm">
    {#each items as i, k}
      {@const clr = colorForLabel(i.label, k)}
      <li class="flex items-center gap-2">
        <span class="h-3 w-3 shrink-0 rounded-full" style={`background:${clr}`} aria-hidden="true"></span>
        <span class="text-foreground">{i.label}:</span>
        <strong class="tabular-nums text-foreground">{i.value}</strong>
        <span class="text-muted-foreground tabular-nums">({total ? Math.round((i.value / total) * 100) : 0}%)</span>
      </li>
    {/each}
  </ul>
</div>
