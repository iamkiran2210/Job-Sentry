<script lang="ts">
  // Charts are drawn with lightweight native SVG from data the backend returned. Shapes are detected because
  // many analytics bodies are open objects in OpenAPI. Unrecognised shapes are not charted (see raw data).
  import { isObj, num, humanize, shortId } from '$lib/utils';
  import { colorForLabel, kpiAccent, LINE_STROKE, LINE_ACCENT } from '$lib/viz-colors';
  let { value, stats = true, rootTitle = 'Summary' }: { value: unknown; stats?: boolean; rootTitle?: string } = $props();

  type Item = { label: string; value: number };
  type Kind = 'bar' | 'column' | 'donut' | 'line' | 'funnel';
  type Chart = { title: string; kind: Kind; items: Item[]; suffix?: string };
  const LABEL = ['name', 'label', 'skill', 'status', 'stage', 'bucket', 'date', 'period', 'interval', 'category', 'title', 'key', 'code'];
  const VALUE = ['count', 'value', 'total', 'applicants', 'number', 'coverage', 'percentage', 'percent', 'candidates', 'score'];
  const DONUT = /status|verification|outcome|share|eligib/i;
  const TIMEY = /trend|series|timeline|over_time|history/i;
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-/i;
  const pretty = (s: string) => (UUID.test(s) ? shortId(s) : s.replace(/_/g, ' '));
  const uid = Math.random().toString(36).slice(2, 8);

  const isExcludedStat = (k: string) =>
    /average_hours?_applied_to_analyzed|hour.*appl|average_hours|^page$|^page_size$|^total_pages$|^offset$|^limit$/i.test(k);
  const isTimingKey = (k: string) => /seconds|duration|latency|ms$/i.test(k);
  const isPercentKey = (k: string) => /score|share|rate|coverage|percent|pct/i.test(k);
  const isRatioKey = (k: string) => /share|rate|coverage/i.test(k);

  const fmtNum = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));
  function fmtStat(key: string, v: number): string {
    if (isTimingKey(key)) return `${v.toFixed(1)}s`;
    if (isRatioKey(key)) return `${(v <= 1 ? v * 100 : v).toFixed(1)}%`;
    if (/score|percent|pct/i.test(key)) return `${v.toFixed(1)}%`;
    return fmtNum(v);
  }
  const fmtVal = (v: number, suffix = '') => `${fmtNum(v)}${suffix}`;

  function kindFor(path: string, items: Item[], rows: boolean): Kind {
    const dates = items.length > 1 && items.every((i) => !Number.isNaN(Date.parse(i.label)) && /^\d{4}-\d{2}/.test(i.label));
    if (dates || (TIMEY.test(path) && rows && items.length > 1 && items.every((i) => !Number.isNaN(Date.parse(i.label))))) return 'line';
    if (/funnel/i.test(path)) return 'funnel';
    if (/distribution|bucket/i.test(path)) return 'column';
    if (DONUT.test(path) && items.length <= 7) return 'donut';
    return 'bar';
  }
  /** One chart per numeric column (up to 4), so rows like {title, applications, analyzed, avg_score} are all visible. */
  function fromRows(rows: Record<string, unknown>[]): { metric: string | null; suffix: string; items: Item[] }[] {
    if (!rows.length) return [];
    const keys = Object.keys(rows[0]);
    const lk = LABEL.find((k) => keys.includes(k) && typeof rows[0][k] === 'string') ?? keys.find((k) => typeof rows[0][k] === 'string');
    if (!lk) return [];
    const nums = keys.filter((k) => k !== lk && typeof rows[0][k] === 'number');
    const preferred = VALUE.find((k) => nums.includes(k));
    const metrics = nums.length > 1 ? nums.slice(0, 4) : preferred ? [preferred] : nums.slice(0, 1);
    return metrics.map((m) => {
      const ratio = isRatioKey(m);
      const pct = isPercentKey(m);
      return {
        metric: nums.length > 1 ? humanize(m) : null,
        suffix: pct ? '%' : '',
        items: rows.map((r) => {
          const raw = num(r[m]) ?? 0;
          const val = ratio && raw <= 1 ? Math.round(raw * 1000) / 10 : raw;
          return { label: pretty(String(r[lk])), value: val };
        })
      };
    });
  }
  function scan(v: unknown, path: string[], out: Chart[], depth = 0) {
    if (depth > 3) return;
    const key = path.join('_');
    const title = path.map(humanize).join(' · ') || rootTitle;
    if (Array.isArray(v)) {
      if (v.length && v.every((r) => isObj(r) && Object.values(r).every((x) => x === null || typeof x !== 'object'))) {
        for (const { metric, suffix, items } of fromRows(v as Record<string, unknown>[])) {
          out.push({ title: metric ? `${title} · ${metric}` : title, kind: kindFor(key, items, true), items, suffix });
        }
      }
      return;
    }
    if (!isObj(v)) return;
    const entries = Object.entries(v);
    const flatNums = entries.length >= 1 && entries.every(([, x]) => typeof x === 'number');
    if (path.length && flatNums && /funnel|distribution|status|verification|stage|outcome|bucket|coverage|share/i.test(key)) {
      // Exclude timing metrics (e.g. average_processing_seconds) from count-based outcome donuts
      const filteredEntries = entries.filter(([k]) => !isTimingKey(k));
      if (filteredEntries.length) {
        const items = filteredEntries.map(([k, x]) => ({ label: humanize(k), value: x as number }));
        out.push({ title, kind: kindFor(key, items, false), items });
      }
    } else {
      for (const [k, x] of entries) scan(x, [...path, k], out, depth + 1);
    }
  }
  const charts = $derived.by(() => { const o: Chart[] = []; scan(value, [], o); return o; });
  const cards = $derived.by(() => {
    const out: [string, string][] = [];
    if (!stats || !isObj(value)) return out;
    for (const [k, v] of Object.entries(value)) {
      if (isExcludedStat(k)) continue;
      if (typeof v === 'number') out.push([humanize(k), fmtStat(k, v)]);
      else if (isObj(v) && /kpi|summary|total|stat|metric|conversion/i.test(k)) {
        for (const [k2, v2] of Object.entries(v)) {
          if (isExcludedStat(k2)) continue;
          if (typeof v2 === 'number') out.push([humanize(k2), fmtStat(k2, v2)]);
        }
      } else if (isObj(v) && /outcome/i.test(k)) {
        // Surface timing fields (e.g. average_processing_seconds) from outcome objects as clean KPI cards
        for (const [k2, v2] of Object.entries(v)) {
          if (isTimingKey(k2) && typeof v2 === 'number') out.push([humanize(k2), fmtStat(k2, v2)]);
        }
      }
    }
    return out;
  });
  function isWideChart(list: Chart[], idx: number): boolean {
    if (list[idx].kind === 'line') return true;
    let runStart = idx;
    while (runStart > 0 && list[runStart - 1].kind !== 'line') runStart--;
    let runEnd = idx;
    while (runEnd + 1 < list.length && list[runEnd + 1].kind !== 'line') runEnd++;
    const runLen = runEnd - runStart + 1;
    return runLen % 2 === 1 && idx === runEnd;
  }
  const height = (c: Chart) =>
    c.kind === 'funnel'
      ? Math.max(200, c.items.length * 42 + 16)
      : c.kind === 'bar'
        ? Math.max(120, c.items.length * 36 + 16)
        : c.kind === 'donut'
          ? 200
          : 220;

  function funnelSteps(items: Item[]) {
    const n = items.length;
    const maxVal = Math.max(1, ...items.map((i) => i.value));
    const widths: number[] = [];
    for (let k = 0; k < n; k++) {
      const ratio = items[k].value / maxVal;
      const taper = 1 - (k / Math.max(1, n)) * 0.55;
      const raw = Math.max(0.22, ratio * 0.65 + taper * 0.35);
      widths.push(k === 0 ? raw : Math.min(widths[k - 1] * 0.92, raw));
    }
    return items.map((item, k) => {
      const topW = widths[k] * 280;
      const botW = (k + 1 < n ? widths[k + 1] : Math.max(0.16, widths[k] * 0.78)) * 280;
      const y1 = k * 42 + 3;
      const y2 = (k + 1) * 42 - 3;
      const midY = (y1 + y2) / 2;
      const cx = 300;
      const pct = Math.round((item.value / maxVal) * 100);
      return {
        ...item,
        pct,
        midY,
        color: colorForLabel(item.label, k),
        points: `${cx - topW / 2},${y1} ${cx + topW / 2},${y1} ${cx + botW / 2},${y2} ${cx - botW / 2},${y2}`
      };
    });
  }

  function donutArcs(items: Item[]) {
    const r = 46;
    const circ = 2 * Math.PI * r;
    const total = items.reduce((a, i) => a + i.value, 0);
    let offset = 0;
    const arcs = items.map((item, k) => {
      const len = total > 0 ? (item.value / total) * circ : 0;
      const arc = { len, off: offset, color: colorForLabel(item.label, k), label: item.label, value: item.value };
      offset += len;
      return arc;
    });
    return { r, circ, total, arcs };
  }

  function linePoints(items: Item[]) {
    const W = 640, H = 210, PL = 42, PR = 20, PT = 18, PB = 30;
    const maxVal = Math.max(1, ...items.map((i) => i.value));
    const spanW = W - PL - PR;
    const spanH = H - PT - PB;
    const pts = items.map((i, k) => ({
      x: PL + (items.length > 1 ? (k / (items.length - 1)) * spanW : spanW / 2),
      y: PT + spanH - (i.value / maxVal) * spanH,
      label: i.label,
      value: i.value
    }));
    const poly = pts.map((p) => `${p.x},${p.y}`).join(' ');
    const area = pts.length ? `${pts[0].x},${PT + spanH} ${poly} ${pts[pts.length - 1].x},${PT + spanH}` : '';
    const midY = PT + spanH / 2;
    return { W, H, PL, PR, PT, PB, maxVal, midY, pts, poly, area };
  }
</script>

{#if cards.length}
  <div class="mb-5 grid w-full gap-4 sm:grid-cols-2 lg:grid-cols-4">
    {#each cards as [label, val], idx}
      {@const accent = kpiAccent(label, idx)}
      <div
        class="relative overflow-hidden rounded-xl border border-border bg-card p-4 shadow-sm transition-shadow hover:shadow-md flex flex-col justify-between"
        style={`border-top: 3px solid ${accent.hex}`}
      >
        <div class="flex items-center justify-between gap-2">
          <div class="text-2xl font-bold tabular-nums tracking-tight" style={`color: ${accent.hex}`}>{val}</div>
          <span
            class="h-2.5 w-2.5 shrink-0 rounded-full"
            style={`background: ${accent.dot}; box-shadow: 0 0 0 4px ${accent.hex}1F`}
            aria-hidden="true"
          ></span>
        </div>
        <div class="mt-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground leading-snug">{label}</div>
      </div>
    {/each}
  </div>
{/if}
{#if charts.length}
  <div class="grid w-full items-stretch gap-5 lg:grid-cols-2">
    {#each charts as c, idx}
      {@const wide = isWideChart(charts, idx)}
      <section class={`flex flex-col justify-between w-full rounded-xl border border-border bg-card p-5 shadow-sm ${wide ? 'lg:col-span-2' : ''}`}>
        <div>
          <h3 class="mb-4 pb-2.5 border-b border-border/60 text-sm font-semibold text-foreground">{c.title}</h3>
          {#if c.kind === 'donut'}
            {@const d = donutArcs(c.items)}
            <div class={wide ? 'grid items-center gap-6 md:grid-cols-[190px_1fr]' : 'space-y-4'}>
              <div class="flex justify-center">
                <svg width="164" height="164" viewBox="0 0 120 120" role="img" aria-label={`${c.title} chart`}>
                  <circle cx="60" cy="60" r={d.r} fill="none" stroke="currentColor" class="text-muted/60" stroke-width="16" />
                  <g transform="rotate(-90 60 60)">
                    {#each d.arcs as a}
                      {#if a.len > 0}
                        <circle cx="60" cy="60" r={d.r} fill="none" stroke={a.color} stroke-width="16" stroke-dasharray={`${a.len} ${d.circ - a.len}`} stroke-dashoffset={-a.off}>
                          <title>{a.label}: {fmtVal(a.value, c.suffix)}</title>
                        </circle>
                      {/if}
                    {/each}
                  </g>
                  <text x="60" y="61" text-anchor="middle" font-size="18" font-weight="700" fill="currentColor" class="text-foreground">{fmtVal(d.total)}</text>
                  <text x="60" y="74" text-anchor="middle" font-size="8.5" font-weight="600" fill="currentColor" class="text-muted-foreground uppercase">TOTAL</text>
                </svg>
              </div>
              <ul class={`grid gap-2 text-xs sm:text-sm ${wide ? 'sm:grid-cols-2 lg:grid-cols-3' : 'sm:grid-cols-2'}`}>
                {#each c.items as i, k}
                  {@const clr = colorForLabel(i.label, k)}
                  <li
                    class="flex items-center justify-between gap-2 rounded-lg border border-border/60 bg-muted/30 px-3 py-2"
                    style={`border-left: 3px solid ${clr}`}
                  >
                    <div class="flex items-center gap-2 min-w-0">
                      <span class="h-2.5 w-2.5 shrink-0 rounded-full" style={`background:${clr}`} aria-hidden="true"></span>
                      <span class="font-medium text-foreground truncate">{i.label}</span>
                    </div>
                    <div class="text-right tabular-nums shrink-0">
                      <span class="font-bold text-foreground">{fmtVal(i.value, c.suffix)}</span>
                      <span class="ml-1 text-[11px] text-muted-foreground">({d.total ? ((i.value / d.total) * 100).toFixed(0) : '0'}%)</span>
                    </div>
                  </li>
                {/each}
              </ul>
            </div>
          {:else if c.kind === 'funnel'}
            {@const steps = funnelSteps(c.items)}
            <div style={`height:${height(c)}px`}>
              <svg viewBox={`0 0 540 ${Math.max(1, c.items.length * 42)}`} class="h-full w-full" role="img" aria-label={`${c.title} funnel chart`}>
                {#each steps as s}
                  <polygon points={s.points} fill={s.color} opacity="0.92">
                    <title>{s.label}: {fmtVal(s.value, c.suffix)} ({s.pct}%)</title>
                  </polygon>
                  <text x="145" y={s.midY} text-anchor="end" dominant-baseline="middle" font-size="12" font-weight="600" fill="currentColor" class="text-foreground">{s.label}</text>
                  <text x="300" y={s.midY} text-anchor="middle" dominant-baseline="middle" font-size="12" font-weight="700" fill="#ffffff">{fmtVal(s.value, c.suffix)}</text>
                  <text x="452" y={s.midY} text-anchor="start" dominant-baseline="middle" font-size="11" font-weight="600" fill="currentColor" class="text-muted-foreground">{s.pct}%</text>
                {/each}
              </svg>
            </div>
          {:else if c.kind === 'bar'}
            {@const maxB = Math.max(1, ...c.items.map((i) => i.value))}
            <ul class="space-y-2.5 py-1">
              {#each c.items as i, k}
                {@const clr = colorForLabel(i.label, k)}
                <li class="grid grid-cols-[minmax(5rem,8rem)_1fr_4rem] sm:grid-cols-[minmax(6rem,11rem)_1fr_4rem] items-center gap-3 text-sm">
                  <span class="flex items-center gap-2 min-w-0">
                    <span class="h-2.5 w-2.5 shrink-0 rounded-full" style={`background:${clr}`} aria-hidden="true"></span>
                    <span class="truncate font-medium text-foreground" title={i.label}>{i.label}</span>
                  </span>
                  <span class="h-2.5 overflow-hidden rounded-full bg-muted/70">
                    <span
                      class="block h-full rounded-full transition-all duration-300"
                      style={`width:${Math.min(100, Math.max(0, (i.value / maxB) * 100))}%; background: linear-gradient(90deg, ${clr}, ${clr}CC)`}
                    ></span>
                  </span>
                  <span class="text-right font-semibold tabular-nums" style={`color:${clr}`}>{fmtVal(i.value, c.suffix)}</span>
                </li>
              {/each}
            </ul>
          {:else if c.kind === 'column'}
            {@const maxC = Math.max(1, ...c.items.map((i) => i.value))}
            <div class="grid grid-flow-col auto-cols-fr items-end gap-2 pt-3 pb-1" style="height: 205px">
              {#each c.items as i, k}
                {@const clr = colorForLabel(i.label, k)}
                <div class="flex h-full flex-col items-center justify-end gap-1.5 min-w-0">
                  <span class="text-xs font-semibold tabular-nums text-foreground">{fmtVal(i.value, c.suffix)}</span>
                  <div
                    class="w-full max-w-12 rounded-t-md shadow-xs transition-all duration-300"
                    style={`height:${Math.max(5, Math.round((i.value / maxC) * 140))}px; background: linear-gradient(180deg, ${clr}, ${clr}B3)`}
                    title={`${i.label}: ${fmtVal(i.value, c.suffix)}`}
                  ></div>
                  <span class="w-full truncate text-center text-[11px] font-medium text-muted-foreground" title={i.label}>{i.label}</span>
                </div>
              {/each}
            </div>
          {:else}
            {@const lp = linePoints(c.items)}
            <div style="height: 215px">
              <svg viewBox={`0 0 ${lp.W} ${lp.H}`} class="h-full w-full" role="img" aria-label={`${c.title} line chart`}>
                <defs>
                  <linearGradient id={`line-grad-${uid}-${idx}`} x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stop-color={LINE_STROKE} />
                    <stop offset="100%" stop-color={LINE_ACCENT} />
                  </linearGradient>
                  <linearGradient id={`area-grad-${uid}-${idx}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stop-color={LINE_STROKE} stop-opacity="0.28" />
                    <stop offset="100%" stop-color={LINE_ACCENT} stop-opacity="0.02" />
                  </linearGradient>
                </defs>
                <line x1={lp.PL} y1={lp.PT} x2={lp.W - lp.PR} y2={lp.PT} stroke="currentColor" class="text-border/60" stroke-dasharray="3 3" />
                <line x1={lp.PL} y1={lp.midY} x2={lp.W - lp.PR} y2={lp.midY} stroke="currentColor" class="text-border/60" stroke-dasharray="3 3" />
                <line x1={lp.PL} y1={lp.H - lp.PB} x2={lp.W - lp.PR} y2={lp.H - lp.PB} stroke="currentColor" class="text-border" />
                <line x1={lp.PL} y1={lp.PT} x2={lp.PL} y2={lp.H - lp.PB} stroke="currentColor" class="text-border" />
                {#if lp.area}
                  <polygon points={lp.area} fill={`url(#area-grad-${uid}-${idx})`} />
                {/if}
                {#if lp.poly}
                  <polyline points={lp.poly} fill="none" stroke={`url(#line-grad-${uid}-${idx})`} stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round" />
                {/if}
                {#each lp.pts as p}
                  <circle cx={p.x} cy={p.y} r="4" fill="#ffffff" stroke={LINE_STROKE} stroke-width="2.25">
                    <title>{p.label}: {fmtVal(p.value, c.suffix)}</title>
                  </circle>
                {/each}
                {#if lp.pts.length}
                  <text x={lp.PL} y={lp.H - 8} font-size="11" font-weight="600" fill="currentColor" class="text-muted-foreground">{lp.pts[0].label}</text>
                  {#if lp.pts.length > 1}
                    <text x={lp.W - lp.PR} y={lp.H - 8} font-size="11" font-weight="600" fill="currentColor" class="text-muted-foreground" text-anchor="end">{lp.pts[lp.pts.length - 1].label}</text>
                  {/if}
                  <text x={lp.PL - 6} y={lp.PT + 5} font-size="11" font-weight="600" fill="currentColor" class="text-muted-foreground" text-anchor="end">{fmtVal(lp.maxVal, c.suffix)}</text>
                  <text x={lp.PL - 6} y={lp.H - lp.PB} font-size="11" font-weight="600" fill="currentColor" class="text-muted-foreground" text-anchor="end">0</text>
                {/if}
              </svg>
            </div>
          {/if}
        </div>
        {#if c.kind !== 'donut'}
          <!-- Text alternative so the chart never carries meaning by shape or color alone. -->
          <details class="mt-3 pt-2 border-t border-border/50 text-xs text-muted-foreground"><summary class="cursor-pointer select-none hover:text-foreground">View values</summary>
            <ul class="mt-1.5 columns-2 gap-4 text-muted-foreground">{#each c.items as i}<li>{i.label}: <strong class="text-foreground">{fmtVal(i.value, c.suffix)}</strong></li>{/each}</ul></details>
        {/if}
      </section>
    {/each}
  </div>
{/if}
