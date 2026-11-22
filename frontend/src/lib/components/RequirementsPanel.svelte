<script lang="ts">
  // One requirements editor for both "create job" (local list) and the job page (API-backed list).
  import { REQ_CATEGORIES, IMPORTANCE, type RequirementInput } from '$lib/types/job';
  import { toast } from '$lib/stores/toast.svelte';
  import { toastError } from '$lib/errors';
  import { humanize } from '$lib/utils';
  import { toBps, weightStatus, evenBps, normalizeBps, normalizeRequirements, fmtPct } from '$lib/weights';

  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Textarea } from '$lib/components/ui/textarea';
  import { Badge } from '$lib/components/ui/badge';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '$lib/components/ui/card';
  import { Sparkles, Plus, Check, X, Pencil, Trash2, Loader2, AlertCircle } from '@lucide/svelte';

  type Req = RequirementInput & { id?: string };
  let { items, descriptionSeed, ensureReady, onAdd, onUpdate, onRemove, onSuggest }: {
    items: Req[]; descriptionSeed: string; ensureReady?: () => Promise<boolean>;
    onAdd: (r: RequirementInput) => Promise<void>; onUpdate: (index: number, patch: Partial<RequirementInput>) => Promise<void>;
    onRemove: (index: number) => Promise<void>; onSuggest: (description: string) => Promise<RequirementInput[]>;
  } = $props();

  const blank = (): RequirementInput => ({ category: 'skills', name: '', requirement_type: 'mandatory', importance: 'medium', weight: 0, is_mandatory: true });
  let nd = $state(blank());
  let ed = $state<RequirementInput>(blank());
  let editing = $state<number | null>(null);
  let aiOpen = $state(false);
  let aiText = $state('');
  let generating = $state(false);
  let suggestions = $state<RequirementInput[]>([]);
  let working = $state(false);
  let wDraft = $state<Record<number, number>>({});

  const setType = (r: RequirementInput, mandatory: boolean) => {
    r.is_mandatory = mandatory;
    r.requirement_type = mandatory ? 'mandatory' : 'preferred';
    if (mandatory) {
      r.weight = 0;
    } else {
      if (!r.weight || r.weight === 0) {
        const currentSumBps = items.filter((x) => !x.is_mandatory).reduce((acc, x) => acc + toBps(x.weight), 0);
        const remBps = Math.max(0, 10000 - currentSumBps);
        r.weight = remBps > 0 ? remBps / 10000 : 0.1;
      }
    }
  };

  async function guard(fn: () => Promise<void>) {
    if (working) return;
    working = true;
    try {
      await fn();
    } catch (e) {
      toastError(e);
    } finally {
      working = false;
    }
  }

  // Weights: saved values live in `items`; edits are held as a draft until applied.
  const prefIdx = $derived(items.map((r, i) => (r.is_mandatory ? -1 : i)).filter((i) => i >= 0));
  const val = (i: number) => wDraft[i] ?? toBps(items[i].weight);
  const draftTotal = $derived(prefIdx.reduce((a, i) => a + val(i), 0));
  const dirty = $derived(prefIdx.some((i) => val(i) !== toBps(items[i].weight)));
  const saved = $derived(weightStatus(items));

  $effect(() => {
    const idx = items.map((r, i) => (r.is_mandatory ? -1 : i)).filter((i) => i >= 0);
    if (idx.length && idx.reduce((a, i) => a + toBps(items[i].weight), 0) === 0) {
      const e = evenBps(idx.length);
      wDraft = Object.fromEntries(idx.map((i, k) => [i, e[k]]));
    } else {
      wDraft = {};
    }
  });

  const even = () => guard(async () => {
    const e = evenBps(prefIdx.length);
    for (let k = 0; k < prefIdx.length; k++) {
      const idx = prefIdx[k];
      if (e[k] !== toBps(items[idx].weight)) {
        await onUpdate(idx, { weight: e[k] / 10000 });
      }
    }
    wDraft = {};
    toast.success('Weights split evenly (100%)');
  });

  const normalizeDraft = () => guard(async () => {
    const scaled = normalizeBps(prefIdx.map((i) => val(i) / 10000));
    for (let k = 0; k < prefIdx.length; k++) {
      const idx = prefIdx[k];
      if (scaled[k] !== toBps(items[idx].weight)) {
        await onUpdate(idx, { weight: scaled[k] / 10000 });
      }
    }
    wDraft = {};
    toast.success('Weights normalized to 100%');
  });

  const setPct = (i: number, v: string) => {
    wDraft = { ...wDraft, [i]: Math.min(10000, Math.max(0, Math.round((parseFloat(v) || 0) * 100))) };
  };

  async function rebalanceSavedPreferred() {
    const currentPref = items.map((r, i) => (r.is_mandatory ? -1 : i)).filter((i) => i >= 0);
    if (!currentPref.length) return;
    const total = currentPref.reduce((a, i) => a + toBps(items[i].weight), 0);
    if (total === 10000) return;
    const scaled = normalizeBps(currentPref.map((i) => items[i].weight));
    for (let k = 0; k < currentPref.length; k++) {
      const idx = currentPref[k];
      if (scaled[k] !== toBps(items[idx].weight)) {
        await onUpdate(idx, { weight: scaled[k] / 10000 });
      }
    }
    wDraft = {};
  }

  const apply = () => guard(async () => {
    if (draftTotal !== 10000) throw new Error('weights');
    for (const i of prefIdx) {
      if (val(i) !== toBps(items[i].weight)) await onUpdate(i, { weight: val(i) / 10000 });
    }
    wDraft = {};
    toast.success('Weights saved');
  });

  const clean = (r: RequirementInput): RequirementInput => ({
    ...r,
    name: r.name.trim(),
    weight: r.is_mandatory ? 0 : r.weight ?? 0
  });

  const add = () => {
    if (!nd.name.trim()) {
      toast.error('Requirement name is required');
      return;
    }
    return guard(async () => {
      await onAdd(clean(nd));
      await rebalanceSavedPreferred();
      nd = blank();
      toast.success('Requirement added');
    });
  };

  const approve = (s: RequirementInput) => guard(async () => {
    if (!s.name.trim()) {
      toast.error('Requirement name is required');
      return;
    }
    await onAdd(clean(s));
    const remaining = suggestions.filter((x) => x !== s);
    suggestions = normalizeRequirements(remaining);
    await rebalanceSavedPreferred();
    toast.success('Requirement added');
  });

  const addAll = () => guard(async () => {
    let n = 0;
    const normalizedList = normalizeRequirements([...suggestions]);
    for (const s of normalizedList) {
      if (!s.name.trim()) continue;
      await onAdd(clean(s));
      n++;
    }
    suggestions = [];
    await rebalanceSavedPreferred();
    toast.success(`${n} requirement${n === 1 ? '' : 's'} added`);
  });

  const startEdit = (i: number) => {
    editing = i;
    const r = items[i];
    ed = {
      category: r.category,
      name: r.name,
      requirement_type: r.requirement_type,
      importance: r.importance,
      weight: r.weight ?? 0,
      is_mandatory: r.is_mandatory
    };
  };

  const saveEdit = () => guard(async () => {
    if (!ed.name.trim()) {
      toast.error('Requirement name is required');
      return;
    }
    const idx = editing!;
    const typeChanged = items[idx].is_mandatory !== ed.is_mandatory;
    await onUpdate(idx, {
      category: ed.category,
      name: ed.name.trim(),
      requirement_type: ed.requirement_type,
      importance: ed.importance,
      is_mandatory: ed.is_mandatory,
      weight: ed.is_mandatory ? 0 : (ed.weight ?? 0)
    });
    editing = null;
    if (typeChanged) await rebalanceSavedPreferred();
    toast.success('Requirement updated');
  });

  const remove = (i: number) => guard(async () => {
    const wasPreferred = !items[i]?.is_mandatory;
    await onRemove(i);
    if (wasPreferred) await rebalanceSavedPreferred();
    toast.success('Requirement removed');
  });

  const toggleAi = () => {
    aiOpen = !aiOpen;
    if (aiOpen && !aiText.trim()) aiText = descriptionSeed;
  };

  async function suggest() {
    if (!aiText.trim()) {
      toast.error('Add a description first', 'Write or paste the job text the AI should read.');
      return;
    }
    if (generating) return;
    if (ensureReady && !(await ensureReady())) return;
    generating = true;
    try {
      const rawSuggestions = await onSuggest(aiText.trim());
      suggestions = normalizeRequirements(rawSuggestions);
      if (suggestions.length) {
        toast.success(
          `${suggestions.length} suggestion${suggestions.length === 1 ? '' : 's'} ready`,
          'Edit them if needed, then add the ones you want.'
        );
      }
    } catch (e) {
      toastError(e, 'Could not generate suggestions');
    } finally {
      generating = false;
    }
  }

  const selectClass = 'h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring';
</script>

{#snippet fields(r: RequirementInput)}
  <Input
    aria-label="Requirement name"
    placeholder="e.g. Distributed Systems, Go, Kubernetes"
    class="min-w-48 flex-1"
    bind:value={r.name}
  />
  <select aria-label="Category" class={selectClass} bind:value={r.category}>
    {#each REQ_CATEGORIES as c}
      <option value={c}>{humanize(c)}</option>
    {/each}
  </select>
  <select
    aria-label="Type"
    class={selectClass}
    value={r.requirement_type}
    onchange={(e) => setType(r, e.currentTarget.value === 'mandatory')}
  >
    <option value="mandatory">Mandatory</option>
    <option value="preferred">Preferred</option>
  </select>
  <select aria-label="Importance" class={selectClass} bind:value={r.importance}>
    {#each IMPORTANCE as c}
      <option value={c}>{humanize(c)}</option>
    {/each}
  </select>
  <div class="flex items-center gap-1.5">
    <span class="text-xs font-medium text-muted-foreground whitespace-nowrap">Weight:</span>
    <Input
      type="number"
      min="0"
      max="100"
      step="any"
      placeholder="0%"
      aria-label="Requirement weight percentage"
      class="w-20 text-right h-9"
      value={r.is_mandatory ? 0 : Math.round((r.weight ?? 0) * 10000) / 100}
      oninput={(e) => {
        const val = parseFloat(e.currentTarget.value) || 0;
        if (val > 0) {
          r.is_mandatory = false;
          r.requirement_type = 'preferred';
          r.weight = Math.min(1, Math.max(0, val / 100));
        } else {
          r.weight = 0;
        }
      }}
    />
    <span class="text-xs font-semibold text-muted-foreground">%</span>
  </div>
{/snippet}

<Card class="border-border bg-card shadow-sm" aria-labelledby="req-h">
  <CardHeader class="pb-3">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <CardTitle id="req-h" class="text-lg">Role Requirements</CardTitle>
        <CardDescription class="text-xs mt-1">
          Mandatory requirements are must-haves and carry no weight. Preferred requirements share exactly 100% of the weight to publish.
        </CardDescription>
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onclick={toggleAi}
        aria-expanded={aiOpen}
        class="border-primary/30 text-primary hover:bg-primary/5"
      >
        <Sparkles class="mr-1.5 size-3.5" />
        Extract with AI
      </Button>
    </div>
  </CardHeader>

  <CardContent class="space-y-5">
    {#if aiOpen}
      <div class="rounded-xl border border-primary/20 bg-primary/5 p-4 space-y-3">
        <div class="space-y-1">
          <label for="ai-desc" class="text-sm font-semibold text-foreground">Job description text</label>
          <p class="text-xs text-muted-foreground">
            The AI suggests structured requirements from this text. Edit any suggestion before adding. Suggestions are never auto-saved.
          </p>
        </div>
        <Textarea
          id="ai-desc"
          rows={4}
          bind:value={aiText}
          placeholder="Paste or write the role description, responsibilities and key requirements…"
          class="bg-background"
        />
        <div class="flex items-center gap-3 pt-1">
          <Button
            type="button"
            size="sm"
            disabled={generating || !aiText.trim()}
            onclick={suggest}
          >
            {#if generating}
              <Loader2 class="mr-1.5 size-3.5 animate-spin" />
              Analyzing…
            {:else}
              <Sparkles class="mr-1.5 size-3.5" />
              Generate requirements
            {/if}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onclick={() => (aiText = descriptionSeed)}
            class="text-xs text-muted-foreground"
          >
            Use job description
          </Button>
        </div>
      </div>
    {/if}

    {#if suggestions.length}
      <div class="rounded-xl border border-amber-300 bg-amber-50/50 p-4 space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h3 class="text-sm font-semibold text-amber-900">
            AI suggestions ({suggestions.length}) — review, edit and approve
          </h3>
          <div class="flex gap-2">
            <Button
              type="button"
              size="sm"
              disabled={working}
              onclick={addAll}
              class="h-7 text-xs bg-amber-600 hover:bg-amber-700 text-white"
            >
              Add all
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onclick={() => (suggestions = [])}
              class="h-7 text-xs text-amber-800"
            >
              Dismiss all
            </Button>
          </div>
        </div>

        <div class="space-y-2">
          {#each suggestions as s}
            <div class="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200/80 bg-background p-2.5">
              {@render fields(s)}
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={working}
                onclick={() => approve(s)}
                class="h-9 px-3 border-emerald-300 text-emerald-700 hover:bg-emerald-50"
              >
                <Plus class="mr-1 size-3.5" /> Add
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onclick={() => (suggestions = normalizeRequirements(suggestions.filter((x) => x !== s)))}
                class="h-9 px-2 text-muted-foreground"
              >
                <X class="size-4" />
              </Button>
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Current Requirements List -->
    {#if items.length === 0}
      <div class="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        No requirements added yet. Add one manually below or extract them with AI.
      </div>
    {:else}
      <div class="divide-y divide-border rounded-lg border border-border">
        {#each items as r, i}
          {#if editing === i}
            <div class="space-y-2 p-3 bg-muted/20 rounded-lg">
              <div class="flex flex-wrap items-center gap-2">
                {@render fields(ed)}
                <Button type="button" size="sm" disabled={working} onclick={saveEdit}>
                  <Check class="mr-1 size-3.5" /> Save
                </Button>
                <Button type="button" variant="ghost" size="sm" onclick={() => (editing = null)}>
                  Cancel
                </Button>
              </div>
              {#if !ed.is_mandatory}
                {@const editTotal = items.map((x, idx) => idx === i ? ed : x).filter(x => !x.is_mandatory).reduce((acc, x) => acc + toBps(x.weight), 0)}
                <div class="flex items-center gap-2 text-xs">
                  <span class="text-muted-foreground">Total preferred weights after this edit:</span>
                  {#if editTotal === 10000}
                    <Badge variant="outline" class="bg-emerald-50 text-emerald-700 border-emerald-300 font-semibold">
                      ✓ Exactly 100%
                    </Badge>
                  {:else if editTotal < 10000}
                    <Badge variant="outline" class="bg-amber-50 text-amber-700 border-amber-300 font-semibold">
                      Total: {fmtPct(editTotal)} · {fmtPct(10000 - editTotal)} remaining to reach 100%
                    </Badge>
                  {:else}
                    <Badge variant="outline" class="bg-rose-50 text-rose-700 border-rose-300 font-semibold">
                      Total: {fmtPct(editTotal)} · {fmtPct(editTotal - 10000)} over 100%
                    </Badge>
                  {/if}
                </div>
              {/if}
            </div>
          {:else}
            <div class="flex items-center justify-between gap-3 p-3 text-sm hover:bg-muted/10 transition-colors">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-medium text-foreground">{r.name}</span>
                <span class="text-xs text-muted-foreground">· {humanize(r.category)} · {humanize(r.importance)}</span>
                {#if r.is_mandatory}
                  <Badge variant="outline" class="text-xs bg-slate-100 text-slate-800 border-slate-300">
                    Mandatory
                  </Badge>
                {:else}
                  <Badge variant="secondary" class="text-xs bg-primary/10 text-primary border-primary/20">
                    Preferred · {fmtPct(toBps(r.weight))}
                  </Badge>
                {/if}
              </div>
              <div class="flex items-center gap-1 shrink-0">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={working}
                  onclick={() => startEdit(i)}
                  aria-label={`Edit ${r.name}`}
                  class="size-8"
                >
                  <Pencil class="size-3.5 text-muted-foreground" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={working}
                  onclick={() => remove(i)}
                  aria-label={`Remove ${r.name}`}
                  class="size-8 text-destructive hover:bg-destructive/10"
                >
                  <Trash2 class="size-3.5" />
                </Button>
              </div>
            </div>
          {/if}
        {/each}
      </div>
    {/if}

    <!-- Add New Requirement Manual Form -->
    <div class="space-y-2 pt-2">
      <div class="flex flex-wrap items-center gap-2">
        {@render fields(nd)}
        <Button type="button" disabled={working} onclick={add} class="shrink-0 font-medium">
          <Plus class="mr-1 size-4" /> Add
        </Button>
      </div>

      {#if !nd.is_mandatory}
        {@const addTotal = items.filter(x => !x.is_mandatory).reduce((acc, x) => acc + toBps(x.weight), 0) + toBps(nd.weight)}
        <div class="flex items-center gap-2 text-xs">
          <span class="text-muted-foreground">Total preferred weights with this requirement:</span>
          {#if addTotal === 10000}
            <Badge variant="outline" class="bg-emerald-50 text-emerald-700 border-emerald-300 font-semibold">
              ✓ Exactly 100% (Ready to publish)
            </Badge>
          {:else if addTotal < 10000}
            <Badge variant="outline" class="bg-amber-50 text-amber-700 border-amber-300 font-semibold">
              Total: {fmtPct(addTotal)} · {fmtPct(10000 - addTotal)} remaining to reach 100%
            </Badge>
          {:else}
            <Badge variant="outline" class="bg-rose-50 text-rose-700 border-rose-300 font-semibold">
              Total: {fmtPct(addTotal)} · {fmtPct(addTotal - 10000)} over 100%
            </Badge>
          {/if}
        </div>
      {/if}
    </div>

    <!-- Preferred Requirement Weights Editor -->
    {#if prefIdx.length}
      <div class="mt-4 rounded-xl border border-border bg-muted/30 p-4 space-y-4" role="group" aria-label="Preferred requirement weights">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 class="text-sm font-semibold text-foreground">Preferred Weights Distribution</h3>
            <p class="text-xs text-muted-foreground">Preferred weights must total exactly 100% to publish the job.</p>
          </div>
          <div class="flex items-center gap-3">
            {#if draftTotal !== 10000}
              <Button type="button" variant="link" size="sm" disabled={working} onclick={normalizeDraft} class="text-xs text-primary p-0 h-auto">
                Normalize to 100%
              </Button>
            {/if}
            <Button type="button" variant="link" size="sm" disabled={working} onclick={even} class="text-xs text-primary p-0 h-auto">
              Split evenly
            </Button>
          </div>
        </div>

        <div class="space-y-2">
          {#each prefIdx as i}
            <div class="grid grid-cols-[1fr_8rem] items-center gap-3 text-sm">
              <label for={`w-${i}`} class="truncate font-medium text-foreground">{items[i].name}</label>
              <div class="flex items-center gap-1.5 justify-end">
                <Input
                  id={`w-${i}`}
                  type="number"
                  min="0"
                  max="100"
                  step="any"
                  value={val(i) / 100}
                  oninput={(e) => setPct(i, e.currentTarget.value)}
                  class="w-20 text-right h-8"
                />
                <span class="text-xs text-muted-foreground font-semibold">%</span>
              </div>
            </div>
          {/each}
        </div>

        <div class="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3 text-sm">
          <span class={draftTotal === 10000 ? 'font-semibold text-emerald-600' : 'font-semibold text-destructive'}>
            Total: {fmtPct(draftTotal)}
            {#if draftTotal === 10000}
              ✓ Valid
            {:else if draftTotal > 10000}
              · {fmtPct(draftTotal - 10000)} over (must equal 100%)
            {:else}
              · {fmtPct(10000 - draftTotal)} remaining (must equal 100%)
            {/if}
          </span>
          <Button
            type="button"
            size="sm"
            disabled={working || !dirty || draftTotal !== 10000}
            onclick={apply}
          >
            Save weights
          </Button>
        </div>

        {#if !dirty && !saved.ok}
          <Alert variant="destructive" class="py-2">
            <AlertCircle class="size-4" />
            <AlertDescription class="text-xs">
              Saved weights total {fmtPct(saved.totalBps)}. They must total exactly 100% before publishing.
            </AlertDescription>
          </Alert>
        {/if}
      </div>
    {/if}
  </CardContent>
</Card>
