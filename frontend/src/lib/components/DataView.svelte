<script lang="ts">
  // Renders backend objects whose shape the OpenAPI schema leaves open. Shows only what was returned in clean formatted layout.
  import Self from './DataView.svelte';
  import { fmtBytes, fmtDate, humanize, isObj } from '$lib/utils';

  let { value }: { value: unknown } = $props();

  const SOURCED_KEYS = new Set(['value', 'confidence', 'evidence']);

  /** Detects Sourced claim wrappers `{ value, confidence?, evidence? }` from resume extraction. */
  function isSourced(v: unknown): v is { value: unknown; confidence?: unknown; evidence?: unknown } {
    if (!isObj(v) || !('value' in v)) return false;
    const keys = Object.keys(v);
    return keys.length > 0 && keys.length <= 3 && keys.every((k) => SOURCED_KEYS.has(k));
  }

  function unwrapVal(v: unknown): unknown {
    return isSourced(v) ? v.value : v;
  }

  const isPrimitive = (v: unknown): boolean => {
    const x = unwrapVal(v);
    return x === null || x === undefined || typeof x !== 'object';
  };

  /** True if value can be rendered inline inside a scalar card or table cell. */
  const isSimpleValue = (v: unknown): boolean => {
    const x = unwrapVal(v);
    if (isPrimitive(x)) return true;
    if (Array.isArray(x)) return x.every(isPrimitive);
    return false;
  };

  function isEmptyVal(v: unknown): boolean {
    const x = unwrapVal(v);
    if (x === null || x === undefined || x === '') return true;
    if (Array.isArray(x)) return x.length === 0;
    if (isObj(x)) return Object.values(x).every(isEmptyVal);
    return false;
  }

  function fmtScalar(v: unknown, key = ''): string {
    const x = unwrapVal(v);
    if (x === null || x === undefined || x === '') return '—';
    if (typeof x === 'boolean') return x ? 'Yes' : 'No';
    if (typeof x === 'number') {
      if (/confidence/i.test(key) && x >= 0 && x <= 1) return `${Math.round(x * 100)}%`;
      if (key === 'size_bytes') return fmtBytes(x);
      return Number.isInteger(x) ? String(x) : String(Number(x.toFixed(2)));
    }
    const s = String(x);
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s)) return fmtDate(s);
    if (
      /^(https?:\/\/|mailto:)/i.test(s) ||
      s.includes('@') ||
      s.includes('/') ||
      /filename|file_name|sha256|id$/i.test(key)
    ) {
      return s;
    }
    return s.replace(/_/g, ' ');
  }

  /** Flattens transparent `data` wrapper inside `profile` so it doesn't create an extra nested box. */
  function normalizedEntries(obj: Record<string, unknown>): [string, unknown][] {
    const out: [string, unknown][] = [];
    for (const [k, v] of Object.entries(obj)) {
      if (k === 'data' && isObj(v) && !isSourced(v)) {
        for (const [dk, dv] of Object.entries(v)) {
          if (!isEmptyVal(dv)) out.push([dk, dv]);
        }
      } else if (!isEmptyVal(v)) {
        out.push([k, v]);
      }
    }
    return out;
  }
</script>

{#if value === null || value === undefined || value === ''}
  <span class="text-muted-foreground">—</span>
{:else if isSourced(value)}
  <span class="text-sm font-medium text-foreground break-words">{fmtScalar(value.value)}</span>
{:else if Array.isArray(value)}
  {#if value.length === 0}
    <span class="text-muted-foreground italic text-xs">None</span>
  {:else if value.every(isPrimitive)}
    {@const strs = value.map((v) => fmtScalar(v)).filter((s) => s !== '—')}
    {#if strs.every((s) => s.length <= 45)}
      <div class="flex flex-wrap gap-1.5">
        {#each strs as s}
          <span class="inline-flex items-center rounded-md border border-border bg-muted/50 px-2 py-0.5 text-xs font-medium text-foreground">
            {s}
          </span>
        {/each}
      </div>
    {:else}
      <ul class="list-disc space-y-1 pl-5 text-sm text-foreground">
        {#each strs as s}
          <li class="break-words">{s}</li>
        {/each}
      </ul>
    {/if}
  {:else if value.every((v) => isObj(v) && Object.values(v).every(isSimpleValue))}
    {@const allCols = [...new Set(value.flatMap((v) => Object.keys(v as object)))]}
    {@const cols = allCols.filter((c) => value.some((r) => !isEmptyVal((r as Record<string, unknown>)[c])))}
    <div class="w-full overflow-x-auto rounded-lg border border-border bg-card">
      <table class="w-full border-collapse text-left text-sm">
        <thead class="border-b border-border bg-muted/40 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          <tr>
            {#each cols as c}
              <th class="py-2.5 px-3 font-semibold text-foreground whitespace-nowrap">{humanize(c)}</th>
            {/each}
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          {#each value as row}
            <tr class="hover:bg-muted/20">
              {#each cols as c}
                {@const cell = (row as Record<string, unknown>)[c]}
                <td class="py-2.5 px-3 align-top text-foreground font-medium">
                  {#if Array.isArray(cell)}
                    <Self value={cell} />
                  {:else}
                    <span class={/description|evidence|summary|statement|notes/i.test(c) ? 'block min-w-[14rem] max-w-md break-words font-normal leading-relaxed' : 'break-words'}>
                      {fmtScalar(cell, c)}
                    </span>
                  {/if}
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <div class="space-y-2.5">
      {#each value as v}
        <div class="rounded-lg border border-border bg-card p-3">
          <Self value={v} />
        </div>
      {/each}
    </div>
  {/if}
{:else if isObj(value)}
  {@const entries = normalizedEntries(value)}
  {@const scalars = entries.filter(([, v]) => isSimpleValue(v))}
  {@const sections = entries.filter(([, v]) => !isSimpleValue(v))}
  {#if entries.length === 0}
    <span class="text-muted-foreground italic text-xs">Not provided</span>
  {:else}
    <div class="space-y-4">
      {#if scalars.length > 0}
        <div class="grid grid-cols-1 gap-2.5 text-sm sm:grid-cols-2 lg:grid-cols-3">
          {#each scalars as [k, v]}
            <div class={`min-w-0 rounded-lg border border-border bg-card p-3 ${/summary|description/i.test(k) ? 'sm:col-span-2 lg:col-span-3' : ''}`}>
              <div class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{humanize(k)}</div>
              <div class="mt-1 font-medium text-foreground min-w-0">
                {#if Array.isArray(v)}
                  <Self value={v} />
                {:else}
                  <span class={/sha256|id$/i.test(k) ? 'break-all font-mono text-xs' : 'break-words'}>
                    {fmtScalar(v, k)}
                  </span>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      {/if}

      {#each sections as [k, v]}
        <div class="w-full rounded-lg border border-border bg-card/60 p-3.5 space-y-2.5">
          <div class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{humanize(k)}</div>
          <div class="min-w-0">
            <Self value={v} />
          </div>
        </div>
      {/each}
    </div>
  {/if}
{:else}
  <span class="text-sm font-medium text-foreground break-words">{fmtScalar(value)}</span>
{/if}
