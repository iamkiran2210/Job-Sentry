<script lang="ts">
  import { colorForLabel, colorForRatio } from '$lib/viz-colors';
  let { items, max, suffix = '' }: { items: { label: string; value: number | null; note?: string }[]; max?: number; suffix?: string } = $props();
  const top = $derived(max ?? Math.max(1, ...items.map((i) => i.value ?? 0)));
  const isScoreScale = $derived(suffix === '%' || max === 100);
</script>
<ul class="space-y-2.5">
  {#each items as i, k}
    {@const ratio = i.value === null ? 0 : Math.min(1, Math.max(0, i.value / top))}
    {@const clr = i.value === null ? '#94A3B8' : isScoreScale ? colorForRatio(ratio) : colorForLabel(i.label, k)}
    <li class="grid grid-cols-[minmax(6rem,9rem)_1fr_4rem] items-center gap-3 text-sm">
      <span class="truncate font-medium text-foreground" title={i.label}>{i.label}</span>
      <span class="h-2.5 overflow-hidden rounded-full bg-muted/70">
        <span
          class="block h-full rounded-full transition-all duration-300"
          style={`width:${ratio * 100}%; background: linear-gradient(90deg, ${clr}, ${clr}CC)`}
        ></span>
      </span>
      <span class="text-right font-semibold tabular-nums" style={`color:${clr}`}>
        {i.value === null ? 'n/a' : `${Number.isInteger(i.value) ? i.value : i.value.toFixed(1)}${suffix}`}
      </span>
      {#if i.note}<span class="col-span-3 -mt-1 text-xs text-muted-foreground">{i.note}</span>{/if}
    </li>
  {/each}
</ul>
