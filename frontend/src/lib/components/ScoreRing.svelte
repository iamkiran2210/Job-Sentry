<script lang="ts">
  import { pctNum } from '$lib/utils';

  let {
    value,
    label = 'Score',
    size = 132
  }: {
    value: number | string | null | undefined;
    label?: string;
    size?: number;
  } = $props();

  const r = 50;
  const c = 2 * Math.PI * r;

  // Normalized 0-100 percentage for the ring arc
  const pct = $derived(pctNum(value, true));

  const tone = $derived(
    pct === null
      ? 'var(--muted-foreground)'
      : pct >= 70
        ? '#16A36A'
        : pct >= 50
          ? '#E9A23B'
          : '#DC5353'
  );
</script>

<!-- Score Ring: Pending score is clearly formatted as "Pending", never 0 or dash. -->
<div class="flex flex-col items-center">
  <svg
    width={size}
    height={size}
    viewBox="0 0 120 120"
    role="img"
    aria-label={pct === null ? `${label}: Pending` : `${label}: ${pct.toFixed(1)}%`}
    class="overflow-visible"
  >
    <!-- Background track -->
    <circle
      cx="60"
      cy="60"
      {r}
      fill="none"
      stroke="currentColor"
      class="text-slate-200"
      stroke-width="10"
    />

    <!-- Foreground Arc -->
    {#if pct !== null}
      <circle
        cx="60"
        cy="60"
        {r}
        fill="none"
        stroke={tone}
        stroke-width="10"
        stroke-linecap="round"
        stroke-dasharray={`${(Math.min(100, Math.max(0, pct)) / 100) * c} ${c}`}
        transform="rotate(-90 60 60)"
        class="transition-all duration-500 ease-out"
      />
    {/if}

    <!-- Center Label: bold sans-serif text -->
    <text
      x="60"
      y="66"
      text-anchor="middle"
      class="fill-foreground font-bold tracking-tight"
      font-size={pct === null ? '15' : '22'}
    >
      {pct === null ? 'Pending' : `${pct.toFixed(0)}%`}
    </text>
  </svg>
  <span class="mt-2 text-xs font-semibold tracking-wide uppercase text-muted-foreground">{label}</span>
</div>
