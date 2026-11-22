<script lang="ts">
  import { LINE_STROKE, LINE_ACCENT } from '$lib/viz-colors';
  let { items }: { items: { label: string; value: number }[] } = $props();
  const W = 600, H = 200, P = 32;
  const uid = Math.random().toString(36).slice(2, 8);
  const max = $derived(Math.max(1, ...items.map((i) => i.value)));
  const pts = $derived(items.map((i, k) => ({ x: P + (items.length > 1 ? (k / (items.length - 1)) * (W - 2 * P) : (W - 2 * P) / 2), y: H - P - (i.value / max) * (H - 2 * P), ...i })));
  const line = $derived(pts.map((p) => `${p.x},${p.y}`).join(' '));
</script>
<svg viewBox={`0 0 ${W} ${H}`} class="w-full" role="img" aria-label={`Trend from ${items[0]?.label} to ${items[items.length - 1]?.label}, peak ${max}`}>
  <defs>
    <linearGradient id={`lc-stroke-${uid}`} x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color={LINE_STROKE} />
      <stop offset="100%" stop-color={LINE_ACCENT} />
    </linearGradient>
    <linearGradient id={`lc-area-${uid}`} x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color={LINE_STROKE} stop-opacity="0.26" />
      <stop offset="100%" stop-color={LINE_ACCENT} stop-opacity="0.02" />
    </linearGradient>
  </defs>
  <line x1={P} y1={P} x2={W - P} y2={P} stroke="currentColor" class="text-border/60" stroke-dasharray="3 3" />
  <line x1={P} y1={H - P} x2={W - P} y2={H - P} stroke="currentColor" class="text-border" />
  <line x1={P} y1={P} x2={P} y2={H - P} stroke="currentColor" class="text-border" />
  {#if pts.length}
    <polygon points={`${pts[0].x},${H - P} ${line} ${pts[pts.length - 1].x},${H - P}`} fill={`url(#lc-area-${uid})`} />
    <polyline points={line} fill="none" stroke={`url(#lc-stroke-${uid})`} stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
  {/if}
  {#each pts as p}<circle cx={p.x} cy={p.y} r="3.75" fill="#ffffff" stroke={LINE_STROKE} stroke-width="2.2"><title>{p.label}: {p.value}</title></circle>{/each}
  <text x={P} y={H - 8} font-size="10" font-weight="600" fill="currentColor" class="text-muted-foreground">{items[0]?.label}</text>
  <text x={W - P} y={H - 8} font-size="10" font-weight="600" fill="currentColor" class="text-muted-foreground" text-anchor="end">{items[items.length - 1]?.label}</text>
  <text x={P - 5} y={P + 4} font-size="10" font-weight="600" fill="currentColor" class="text-muted-foreground" text-anchor="end">{max}</text>
</svg>
