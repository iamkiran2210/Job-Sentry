<script lang="ts">
  import { buildProfile, type Dict } from '$lib/profile';
  import DataView from '$lib/components/DataView.svelte';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { humanize } from '$lib/utils';

  import * as Tabs from '$lib/components/ui/tabs';
  import * as Accordion from '$lib/components/ui/accordion';
  import { Badge } from '$lib/components/ui/badge';
  import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '$lib/components/ui/card';
  import { Input } from '$lib/components/ui/input';
  import { Button } from '$lib/components/ui/button';
  import { Separator } from '$lib/components/ui/separator';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import {
    ExternalLink,
    Mail,
    Phone,
    MapPin,
    Briefcase,
    GraduationCap,
    Award,
    FolderGit2,
    ShieldCheck,
    FileText,
    Info,
    Search
  } from '@lucide/svelte';

  let {
    data,
    resume = null,
    showHeader = true,
    tab = $bindable('overview')
  }: {
    data: Dict;
    resume?: Dict | null;
    showHeader?: boolean;
    tab?: string;
  } = $props();

  const p = $derived(buildProfile(data, { resume }));

  const TABS = [
    { value: 'overview', label: 'Overview' },
    { value: 'experience', label: 'Experience' },
    { value: 'skills', label: 'Skills' },
    { value: 'projects', label: 'Projects' },
    { value: 'education', label: 'Education' },
    { value: 'certifications', label: 'Certifications' },
    { value: 'ai data', label: 'AI Data' }
  ];

  let skillQ = $state('');
  let skillCat = $state('All');

  const initials = $derived(
    (p.name ?? '?')
      .split(/\s+/)
      .map((w) => w[0])
      .slice(0, 2)
      .join('')
      .toUpperCase()
  );

  const cats = $derived(['All', ...new Set(p.skills.map((s) => s.category))]);
  const shownSkills = $derived(
    p.skills.filter(
      (s) =>
        (skillCat === 'All' || s.category === skillCat) &&
        s.name.toLowerCase().includes(skillQ.toLowerCase())
    )
  );

  const grouped = $derived(
    [...new Set(shownSkills.map((s) => s.category))].map((c) => ({
      cat: c,
      items: shownSkills.filter((s) => s.category === c)
    }))
  );

  const evidenceCount = $derived(
    [...p.experience, ...p.education, ...p.projects, ...p.certifications].reduce(
      (n, i) => n + i.evidence.length,
      0
    )
  );

  type Ev = { label: string; evidence: string[]; confidence: number | null };
  const evidenceGroups = $derived(
    ([
      {
        section: 'Experience',
        list: p.experience.map<Ev>((e) => ({
          label: e.title ?? 'Role',
          evidence: e.evidence,
          confidence: e.confidence
        }))
      },
      {
        section: 'Projects',
        list: p.projects.map<Ev>((e) => ({
          label: e.name ?? 'Project',
          evidence: e.evidence,
          confidence: e.confidence
        }))
      },
      {
        section: 'Education',
        list: p.education.map<Ev>((e) => ({
          label: e.degree ?? 'Education',
          evidence: e.evidence,
          confidence: e.confidence
        }))
      },
      {
        section: 'Certifications',
        list: p.certifications.map<Ev>((e) => ({
          label: e.name ?? 'Certification',
          evidence: e.evidence,
          confidence: e.confidence
        }))
      }
    ] as const).filter((g) => g.list.some((i) => i.evidence.length))
  );

  const NP = 'Not provided';
  const mapped = $derived(
    p.skills.length +
      p.experience.length +
      p.education.length +
      p.projects.length +
      p.certifications.length >
      0 || !!p.summary
  );
  const hasOther = $derived(Object.keys(p.other).length > 0);

  const INTERNAL_KEYS = new Set(['confidence', 'evidence', 'id', 'evidence_id', 'source_location']);
  const PRIMARY_KEYS = ['statement', 'title', 'name', 'label', 'role', 'value', 'language', 'award', 'description'];

  type OtherEntry =
    | { kind: 'text'; text: string; isUrl: boolean }
    | { kind: 'tags'; tags: string[] }
    | { kind: 'cards'; cards: { primary: string; meta: { label: string; value: string }[] }[] }
    | { kind: 'pairs'; pairs: { label: string; value: string }[] };

  function fmtScalar(v: unknown, keyHint = ''): string {
    if (v === null || v === undefined) return '';
    if (typeof v === 'boolean') return v ? 'Yes' : 'No';
    if (typeof v === 'number') {
      if (/year/i.test(keyHint)) return `${v} ${v === 1 ? 'year' : 'years'}`;
      return String(v);
    }
    return String(v).replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
  }

  function unwrapValue(v: unknown): unknown {
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      const obj = v as Record<string, unknown>;
      const keys = Object.keys(obj);
      if ('value' in obj && keys.every((k) => k === 'value' || INTERNAL_KEYS.has(k))) {
        return obj.value;
      }
    }
    return v;
  }

  function formatOtherValue(raw: unknown, keyHint = ''): OtherEntry | null {
    const v = unwrapValue(raw);
    if (v === null || v === undefined || v === '') return null;
    if (typeof v !== 'object') {
      const text = fmtScalar(v, keyHint);
      return text ? { kind: 'text', text, isUrl: /^https?:\/\//i.test(text) } : null;
    }
    if (Array.isArray(v)) {
      const cleaned = v.map(unwrapValue).filter((x) => x !== null && x !== undefined && x !== '');
      if (!cleaned.length) return null;
      if (cleaned.every((x) => typeof x !== 'object')) {
        const tags = cleaned.map((x) => fmtScalar(x)).filter(Boolean);
        return tags.length ? { kind: 'tags', tags } : null;
      }
      const cards: { primary: string; meta: { label: string; value: string }[] }[] = [];
      for (const item of cleaned) {
        if (!item || typeof item !== 'object' || Array.isArray(item)) {
          const t = fmtScalar(item);
          if (t) cards.push({ primary: t, meta: [] });
          continue;
        }
        const obj = item as Record<string, unknown>;
        const pKey = PRIMARY_KEYS.find((k) => {
          const u = unwrapValue(obj[k]);
          return u !== null && u !== undefined && String(u).trim() !== '';
        });
        const primary = pKey ? fmtScalar(unwrapValue(obj[pKey]), pKey) : '';
        const meta: { label: string; value: string }[] = [];
        for (const [mk, mv] of Object.entries(obj)) {
          if (mk === pKey || INTERNAL_KEYS.has(mk)) continue;
          const u = unwrapValue(mv);
          if (u === null || u === undefined || u === '') continue;
          if (Array.isArray(u)) {
            const joined = u.map((x) => fmtScalar(unwrapValue(x))).filter(Boolean).join(', ');
            if (joined) meta.push({ label: humanize(mk), value: joined });
          } else if (typeof u !== 'object') {
            const s = fmtScalar(u, mk);
            if (s) meta.push({ label: humanize(mk), value: s });
          }
        }
        if (primary || meta.length) {
          cards.push({
            primary: primary || meta.shift()!.value,
            meta
          });
        }
      }
      return cards.length ? { kind: 'cards', cards } : null;
    }

    const pairs: { label: string; value: string }[] = [];
    for (const [ok, ov] of Object.entries(v as Record<string, unknown>)) {
      if (INTERNAL_KEYS.has(ok)) continue;
      const u = unwrapValue(ov);
      if (u === null || u === undefined || u === '') continue;
      if (Array.isArray(u)) {
        const joined = u.map((x) => fmtScalar(unwrapValue(x))).filter(Boolean).join(', ');
        if (joined) pairs.push({ label: humanize(ok), value: joined });
      } else if (typeof u !== 'object') {
        const s = fmtScalar(u, ok);
        if (s) pairs.push({ label: humanize(ok), value: s });
      }
    }
    return pairs.length ? { kind: 'pairs', pairs } : null;
  }
</script>

{#snippet empty(msg: string)}
  <div class="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
    {msg}
  </div>
{/snippet}

{#snippet link(url: string, label: string)}
  <a
    href={url}
    target="_blank"
    rel="noopener noreferrer"
    class="inline-flex items-center gap-1 font-medium text-primary hover:underline"
    aria-label={`${label} (opens in a new tab)`}
  >
    <span>{label}</span>
    <ExternalLink class="size-3" />
  </a>
{/snippet}

{#snippet expCard(e: (typeof p.experience)[number])}
  <li class="relative pl-7 pb-6 last:pb-0">
    <span class="absolute left-0 top-1.5 size-3 rounded-full border-2 border-primary bg-background" aria-hidden="true"></span>
    <div class="flex flex-wrap items-center gap-2">
      <h3 class="font-semibold text-foreground">{e.title ?? 'Role not provided'}</h3>
      {#if e.current}
        <Badge variant="outline" class="bg-emerald-50 text-emerald-700 border-emerald-200 text-xs">
          Current
        </Badge>
      {/if}
    </div>
    <p class="text-sm font-medium text-primary">{e.company ?? 'Company not provided'}</p>
    <p class="text-xs text-muted-foreground mt-0.5">
      {e.dates ?? 'Dates not provided'}{e.location ? ` · ${e.location}` : ''}
    </p>
    {#if e.bullets.length}
      <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-foreground/90">
        {#each e.bullets as b}
          <li>{b}</li>
        {/each}
      </ul>
    {/if}
  </li>
{/snippet}

{#snippet projCard(pr: (typeof p.projects)[number])}
  <li class="rounded-xl border border-border bg-card p-5 shadow-xs">
    <div class="flex items-start justify-between gap-2">
      <h3 class="font-semibold text-foreground">{pr.name ?? 'Untitled project'}</h3>
      {#if pr.url}
        {@render link(pr.url, 'View Project')}
      {/if}
    </div>
    <p class="mt-2 text-sm text-muted-foreground leading-relaxed">
      {pr.description ?? 'No description provided'}
    </p>
    {#if pr.tech.length}
      <div class="mt-3 flex flex-wrap gap-1.5">
        {#each pr.tech as t}
          <Badge variant="secondary" class="text-xs">
            {t}
          </Badge>
        {/each}
      </div>
    {/if}
  </li>
{/snippet}

{#if showHeader}
  <Card class="mb-6 border-border bg-card shadow-sm" aria-label="Candidate summary">
    <CardContent class="p-6 sm:p-8">
      <div class="flex flex-col sm:flex-row items-start gap-6">
        <!-- Initials only, no photos per Product Rule 6 -->
        <div class="flex size-20 shrink-0 items-center justify-center rounded-2xl bg-sidebar text-2xl font-bold text-white shadow-xs" aria-hidden="true">
          {initials}
        </div>

        <div class="min-w-0 flex-1 space-y-2">
          <div class="flex flex-wrap items-center gap-2.5">
            <h1 class="text-2xl font-bold tracking-tight text-foreground">
              {p.name ?? 'Unnamed candidate'}
            </h1>
            <Badge variant="outline" class="text-xs bg-slate-100 text-slate-700 border-slate-300 font-normal" title="Details come from the resume and are not independently verified">
              Resume-derived
            </Badge>
            {#if p.identity?.status === 'passed'}
              <Badge variant="outline" class="text-xs bg-emerald-50 text-emerald-700 border-emerald-300">
                <ShieldCheck class="mr-1 size-3" /> Identity checks passed
              </Badge>
            {/if}
          </div>

          <p class="text-sm font-medium text-primary">
            {p.headline ?? 'Headline not provided'}
          </p>

          <div class="flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted-foreground pt-1">
            {#if p.email}
              <a href={`mailto:${p.email}`} class="inline-flex items-center gap-1.5 hover:text-foreground">
                <Mail class="size-3.5" />
                <span>{p.email}</span>
              </a>
            {:else}
              <span class="inline-flex items-center gap-1.5"><Mail class="size-3.5" /> Email: {NP}</span>
            {/if}

            <span class="inline-flex items-center gap-1.5">
              <Phone class="size-3.5" />
              <span>{p.phone ?? `Phone: ${NP}`}</span>
            </span>

            <span class="inline-flex items-center gap-1.5">
              <MapPin class="size-3.5" />
              <span>{p.location ?? `Location: ${NP}`}</span>
            </span>

            {#each p.links as l}
              {@render link(l.url, l.label)}
            {/each}
          </div>
        </div>

        <!-- Candidate stat indicators (no global score per Product Rule 2) -->
        <dl class="grid grid-cols-2 sm:grid-cols-4 gap-px overflow-hidden rounded-xl border border-border bg-border text-center w-full lg:w-auto">
          {#each [['Experience', p.yearsExperience ? `${p.yearsExperience} yrs` : NP], ['Skills', String(p.skills.length)], ['Projects', String(p.projects.length)], ['Certifications', String(p.certifications.length)]] as [k, v]}
            <div class="bg-card px-4 py-3 min-w-[85px]">
              <dd class="text-lg font-bold text-foreground">{v}</dd>
              <dt class="text-xs text-muted-foreground mt-0.5">{k}</dt>
            </div>
          {/each}
        </dl>
      </div>
    </CardContent>
  </Card>
{/if}

<!-- Profile Section Tabs -->
<Tabs.Root bind:value={tab} class="w-full flex flex-col space-y-6">
  <div class="w-full overflow-x-auto">
    <Tabs.List class="flex w-max min-w-full justify-start bg-muted p-1 h-auto rounded-lg gap-1">
      {#each TABS as t}
        <Tabs.Trigger
          value={t.value}
          class="px-4 py-2 text-sm font-semibold rounded-md whitespace-nowrap"
        >
          {t.label}
        </Tabs.Trigger>
      {/each}
    </Tabs.List>
  </div>

  <!-- OVERVIEW TAB -->
  <Tabs.Content value="overview">
    {#if !mapped}
      <Alert class="mb-6 border-amber-200 bg-amber-50/70 text-amber-900">
        <Info class="size-4 text-amber-600" />
        <AlertTitle class="font-semibold">Unstructured Resume Format</AlertTitle>
        <AlertDescription>
          This resume's structure could not be neatly partitioned into standard sections. Extracted details are displayed below in clean sections.
        </AlertDescription>
      </Alert>
    {/if}

    <div class="grid items-start gap-6 lg:grid-cols-3">
      <div class="space-y-6 lg:col-span-2">
        <Card class="border-border bg-card shadow-sm">
          <CardHeader>
            <CardTitle class="text-lg">Executive Summary</CardTitle>
          </CardHeader>
          <CardContent>
            {#if p.summary}
              <p class="text-sm leading-relaxed text-foreground/90">{p.summary}</p>
              <p class="mt-3 text-xs text-muted-foreground">
                Extracted from submitted resume. Claims are not independently verified.
              </p>
            {:else}
              <p class="text-sm text-muted-foreground">{NP}</p>
            {/if}
          </CardContent>
        </Card>

        <Card class="border-border bg-card shadow-sm">
          <CardHeader class="flex flex-row items-center justify-between pb-3">
            <CardTitle class="text-lg">Skills ({p.skills.length})</CardTitle>
            {#if p.skills.length > 14}
              <Button variant="link" size="sm" onclick={() => (tab = 'skills')} class="p-0 h-auto text-primary">
                View all skills
              </Button>
            {/if}
          </CardHeader>
          <CardContent>
            {#if p.skills.length}
              <div class="flex flex-wrap gap-2">
                {#each p.skills.slice(0, 14) as s}
                  <Badge variant="secondary" class="text-xs">
                    {s.name}
                  </Badge>
                {/each}
              </div>
            {:else}
              {@render empty('No skills provided')}
            {/if}
          </CardContent>
        </Card>

        <Card class="border-border bg-card shadow-sm">
          <CardHeader class="flex flex-row items-center justify-between pb-3">
            <CardTitle class="text-lg">Experience ({p.experience.length})</CardTitle>
            {#if p.experience.length > 2}
              <Button variant="link" size="sm" onclick={() => (tab = 'experience')} class="p-0 h-auto text-primary">
                View all experience
              </Button>
            {/if}
          </CardHeader>
          <CardContent>
            {#if p.experience.length}
              <ol class="space-y-4 border-l border-border pl-0.5">
                {#each p.experience.slice(0, 2) as e}
                  {@render expCard(e)}
                {/each}
              </ol>
            {:else}
              {@render empty('No experience provided')}
            {/if}
          </CardContent>
        </Card>

        <Card class="border-border bg-card shadow-sm">
          <CardHeader class="flex flex-row items-center justify-between pb-3">
            <CardTitle class="text-lg">Projects ({p.projects.length})</CardTitle>
            {#if p.projects.length > 2}
              <Button variant="link" size="sm" onclick={() => (tab = 'projects')} class="p-0 h-auto text-primary">
                View all projects
              </Button>
            {/if}
          </CardHeader>
          <CardContent>
            {#if p.projects.length}
              <ul class="space-y-3">
                {#each p.projects.slice(0, 2) as pr}
                  {@render projCard(pr)}
                {/each}
              </ul>
            {:else}
              {@render empty('No projects provided')}
            {/if}
          </CardContent>
        </Card>

        {#if hasOther}
          <Card class="border-border bg-card shadow-sm">
            <CardHeader>
              <CardTitle class="text-lg">Additional Extracted Details</CardTitle>
              <CardDescription>Other structured details found in the resume.</CardDescription>
            </CardHeader>
            <CardContent>
              <dl class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                {#each Object.entries(p.other) as [k, v]}
                  {@const formatted = formatOtherValue(v, k)}
                  {#if formatted}
                    <div
                      class={`rounded-lg border border-border p-3.5 bg-muted/10 space-y-2 ${
                        formatted.kind === 'cards' || formatted.kind === 'pairs' || (formatted.kind === 'tags' && formatted.tags.length > 4)
                          ? 'sm:col-span-2'
                          : ''
                      }`}
                    >
                      <dt class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        {humanize(k)}
                      </dt>
                      <dd class="text-foreground">
                        {#if formatted.kind === 'text'}
                          {#if formatted.isUrl}
                            {@render link(formatted.text, formatted.text)}
                          {:else}
                            <p class="font-medium leading-relaxed">{formatted.text}</p>
                          {/if}
                        {:else if formatted.kind === 'tags'}
                          <div class="flex flex-wrap gap-1.5">
                            {#each formatted.tags as tag}
                              <Badge variant="secondary" class="text-xs font-normal">{tag}</Badge>
                            {/each}
                          </div>
                        {:else if formatted.kind === 'cards'}
                          <ul class="space-y-2">
                            {#each formatted.cards as card}
                              <li class="rounded-md border border-border/70 bg-background/80 p-2.5 space-y-1">
                                <p class="font-medium text-foreground leading-snug">{card.primary}</p>
                                {#if card.meta.length > 0}
                                  <div class="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                                    {#each card.meta as m}
                                      <span><strong class="font-medium text-foreground/80">{m.label}:</strong> {m.value}</span>
                                    {/each}
                                  </div>
                                {/if}
                              </li>
                            {/each}
                          </ul>
                        {:else if formatted.kind === 'pairs'}
                          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            {#each formatted.pairs as pair}
                              <div class="text-xs">
                                <span class="text-muted-foreground font-medium">{pair.label}:</span>
                                <span class="ml-1 text-foreground font-medium">{pair.value}</span>
                              </div>
                            {/each}
                          </div>
                        {/if}
                      </dd>
                    </div>
                  {/if}
                {/each}
              </dl>
            </CardContent>
          </Card>
        {/if}
      </div>

      <!-- Right Column: Education, Certifications, Applications -->
      <div class="space-y-6">
        <Card class="border-border bg-card shadow-sm">
          <CardHeader>
            <CardTitle class="text-lg">Education</CardTitle>
          </CardHeader>
          <CardContent>
            {#if p.education.length}
              <ul class="space-y-4 text-sm divide-y divide-border">
                {#each p.education as e, idx}
                  <li class={idx === 0 ? '' : 'pt-3'}>
                    <div class="font-semibold text-foreground">{e.degree ?? 'Degree not provided'}</div>
                    <div class="text-primary text-xs mt-0.5">{e.institution ?? 'Institution not provided'}</div>
                    <div class="text-xs text-muted-foreground mt-0.5">
                      {e.period ?? 'Dates not provided'}{e.grade ? ` · ${e.grade}` : ''}
                    </div>
                  </li>
                {/each}
              </ul>
            {:else}
              <p class="text-sm text-muted-foreground">{NP}</p>
            {/if}
          </CardContent>
        </Card>

        <Card class="border-border bg-card shadow-sm">
          <CardHeader>
            <CardTitle class="text-lg">Certifications ({p.certifications.length})</CardTitle>
          </CardHeader>
          <CardContent>
            {#if p.certifications.length}
              <ul class="space-y-4 text-sm divide-y divide-border">
                {#each p.certifications as c, idx}
                  <li class={idx === 0 ? '' : 'pt-3'}>
                    <div class="font-semibold text-foreground">{c.name ?? 'Untitled'}</div>
                    <div class="text-xs text-muted-foreground mt-0.5">
                      {c.issuer ?? 'Issuer not provided'}{c.date ? ` · ${c.date}` : ''}
                    </div>
                  </li>
                {/each}
              </ul>
            {:else}
              <p class="text-sm text-muted-foreground">{NP}</p>
            {/if}
          </CardContent>
        </Card>

        {#if p.applications.length}
          <Card class="border-border bg-card shadow-sm">
            <CardHeader>
              <CardTitle class="text-lg">Job Applications</CardTitle>
            </CardHeader>
            <CardContent>
              <ul class="space-y-3 text-sm divide-y divide-border">
                {#each p.applications as a, idx}
                  <li class={`flex items-center justify-between gap-2 ${idx === 0 ? '' : 'pt-2.5'}`}>
                    {#if a.jobId && a.applicationId}
                      <a class="font-medium text-primary hover:underline" href={`/jobs/${a.jobId}/applicants/${a.applicationId}`}>
                        {a.jobTitle ?? 'Job'}
                      </a>
                    {:else}
                      <span class="font-medium text-foreground">{a.jobTitle ?? 'Job'}</span>
                    {/if}
                    {#if a.status}
                      <StatusBadge status={a.status} />
                    {/if}
                  </li>
                {/each}
              </ul>
            </CardContent>
          </Card>
        {/if}
      </div>
    </div>
  </Tabs.Content>

  <!-- EXPERIENCE TAB -->
  <Tabs.Content value="experience">
    <Card class="border-border bg-card shadow-sm">
      <CardContent class="p-6">
        {#if p.experience.length}
          <ol class="space-y-6 border-l border-border pl-0.5">
            {#each p.experience as e}
              {@render expCard(e)}
            {/each}
          </ol>
        {:else}
          {@render empty('No experience provided')}
        {/if}
      </CardContent>
    </Card>
  </Tabs.Content>

  <!-- SKILLS TAB -->
  <Tabs.Content value="skills">
    <Card class="border-border bg-card shadow-sm">
      <CardContent class="p-6 space-y-6">
        {#if p.skills.length}
          <div class="flex flex-col sm:flex-row items-start sm:items-center gap-4">
            <div class="relative w-full sm:w-72">
              <Search class="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
              <Input
                type="search"
                bind:value={skillQ}
                placeholder="Search skills…"
                aria-label="Search skills"
                class="pl-9"
              />
            </div>
            <div class="flex flex-wrap gap-1.5" role="group" aria-label="Skill category">
              {#each cats as c}
                <Button
                  variant={skillCat === c ? 'default' : 'outline'}
                  size="sm"
                  onclick={() => (skillCat = c)}
                  class="rounded-full text-xs h-7"
                >
                  {c}
                </Button>
              {/each}
            </div>
          </div>

          {#if grouped.length}
            <div class="space-y-6 pt-2">
              {#each grouped as g}
                <div class="space-y-2">
                  <h3 class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {g.cat} ({g.items.length})
                  </h3>
                  <div class="flex flex-wrap gap-2">
                    {#each g.items as s}
                      <Badge variant="secondary" class="text-xs px-2.5 py-1">
                        {s.name}
                      </Badge>
                    {/each}
                  </div>
                </div>
              {/each}
            </div>
          {:else}
            {@render empty('No skills match your search')}
          {/if}
        {:else}
          {@render empty('No skills provided')}
        {/if}
      </CardContent>
    </Card>
  </Tabs.Content>

  <!-- PROJECTS TAB -->
  <Tabs.Content value="projects">
    {#if p.projects.length}
      <ul class="grid gap-4 md:grid-cols-2">
        {#each p.projects as pr}
          {@render projCard(pr)}
        {/each}
      </ul>
    {:else}
      <Card class="border-border bg-card shadow-sm">
        <CardContent class="p-6">
          {@render empty('No projects provided')}
        </CardContent>
      </Card>
    {/if}
  </Tabs.Content>

  <!-- EDUCATION TAB -->
  <Tabs.Content value="education">
    {#if p.education.length}
      <ul class="grid gap-4 md:grid-cols-2">
        {#each p.education as e}
          <li class="rounded-xl border border-border bg-card p-5 shadow-xs space-y-2">
            <h3 class="font-semibold text-foreground">{e.degree ?? 'Degree not provided'}</h3>
            <p class="text-sm font-medium text-primary">{e.institution ?? 'Institution not provided'}</p>
            <p class="text-xs text-muted-foreground">
              {e.period ?? 'Dates not provided'}{e.location ? ` · ${e.location}` : ''}
            </p>
            {#if e.grade}
              <Badge variant="outline" class="text-xs mt-2 bg-primary/10 text-primary border-primary/20">
                {e.grade}
              </Badge>
            {/if}
          </li>
        {/each}
      </ul>
    {:else}
      <Card class="border-border bg-card shadow-sm">
        <CardContent class="p-6">
          {@render empty('No education provided')}
        </CardContent>
      </Card>
    {/if}
  </Tabs.Content>

  <!-- CERTIFICATIONS TAB -->
  <Tabs.Content value="certifications">
    {#if p.certifications.length}
      <ul class="grid gap-4 md:grid-cols-2">
        {#each p.certifications as c}
          <li class="rounded-xl border border-border bg-card p-5 shadow-xs flex items-start justify-between gap-3">
            <div class="space-y-1">
              <h3 class="font-semibold text-foreground">{c.name ?? 'Untitled'}</h3>
              <p class="text-sm text-muted-foreground">{c.issuer ?? 'Issuer not provided'}</p>
              <p class="text-xs text-muted-foreground">{c.date ?? 'Date not provided'}</p>
            </div>
            {#if c.url}
              {@render link(c.url, 'Credential')}
            {/if}
          </li>
        {/each}
      </ul>
    {:else}
      <Card class="border-border bg-card shadow-sm">
        <CardContent class="p-6">
          {@render empty('No certifications provided')}
        </CardContent>
      </Card>
    {/if}
  </Tabs.Content>

  <!-- AI DATA TAB -->
  <Tabs.Content value="ai data">
    <div class="grid items-start gap-6 lg:grid-cols-2">
      <Card class="border-border bg-card shadow-sm">
        <CardHeader>
          <CardTitle class="text-lg">Extraction Metadata</CardTitle>
          <CardDescription>Pipeline execution parameters and confidence indicators.</CardDescription>
        </CardHeader>
        <CardContent class="space-y-4">
          <dl class="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2.5 text-sm">
            <dt class="text-muted-foreground font-medium">Confidence</dt>
            <dd class="font-semibold text-foreground">
              {p.meta.confidence === null ? NP : `${Math.round(p.meta.confidence <= 1 ? p.meta.confidence * 100 : p.meta.confidence)}%`}
            </dd>

            <dt class="text-muted-foreground font-medium">Method</dt>
            <dd class="text-foreground">{p.meta.method ? p.meta.method.replace(/_/g, ' ') : NP}</dd>

            <dt class="text-muted-foreground font-medium">AI Model</dt>
            <dd class="text-foreground">{p.meta.model ?? NP}</dd>

            <dt class="text-muted-foreground font-medium">Data Origin</dt>
            <dd class="text-foreground">{p.meta.origin ? humanize(p.meta.origin) : NP}</dd>

            {#if p.meta.parseStatus}
              <dt class="text-muted-foreground font-medium">Parse Status</dt>
              <dd class="text-foreground">{humanize(p.meta.parseStatus)}</dd>
            {/if}

            {#if p.meta.promptVersion}
              <dt class="text-muted-foreground font-medium">Prompt Version</dt>
              <dd class="text-foreground font-mono text-xs">{p.meta.promptVersion}</dd>
            {/if}

            {#if p.meta.schemaVersion}
              <dt class="text-muted-foreground font-medium">Schema Version</dt>
              <dd class="text-foreground font-mono text-xs">v{p.meta.schemaVersion}</dd>
            {/if}

            {#if p.meta.ocrUsed !== null}
              <dt class="text-muted-foreground font-medium">OCR Used</dt>
              <dd class="text-foreground">{p.meta.ocrUsed ? 'Yes' : 'No'}</dd>
            {/if}

            <dt class="text-muted-foreground font-medium">Warnings</dt>
            <dd class="text-foreground">
              {#if p.meta.warnings.length}
                <ul class="list-disc pl-4 text-xs space-y-1">
                  {#each p.meta.warnings as w}
                    <li>{w.replace(/_/g, ' ')}</li>
                  {/each}
                </ul>
              {:else}
                None
              {/if}
            </dd>
          </dl>
          <p class="text-xs text-muted-foreground pt-2 border-t border-border">
            Extracted automatically from submitted resumes. Claims are not independently verified.
          </p>
        </CardContent>
      </Card>

      <Card id="verification-review" class="border-border bg-card shadow-sm">
        <CardHeader>
          <CardTitle class="text-lg">Identity Verification Review</CardTitle>
          <CardDescription>Passive consistency and syntax validation results.</CardDescription>
        </CardHeader>
        <CardContent class="space-y-4">
          {#if p.identity}
            <div class="flex items-center gap-2">
              <span class="text-sm text-muted-foreground font-medium">Overall Status:</span>
              <Badge variant={p.identity.status === 'passed' ? 'default' : 'secondary'} class="capitalize text-xs">
                {p.identity.status ? humanize(p.identity.status) : 'Not run'}
              </Badge>
            </div>

            {#if p.identity.checks.length}
              <div class="divide-y divide-border rounded-lg border border-border">
                {#each p.identity.checks as c}
                  {@const projectChecks = Array.isArray(c.details?.projects) ? (c.details.projects as Record<string, unknown>[]) : []}
                  {@const ghRepos = Array.isArray(c.details?.top_repositories) ? (c.details.top_repositories as Record<string, unknown>[]) : []}
                  {@const ghLangs = Array.isArray(c.details?.languages) ? (c.details.languages as Record<string, unknown>[]) : []}
                  {@const isGithubProfile = Boolean(c.details?.username && (ghLangs.length > 0 || ghRepos.length > 0 || c.details?.ai_verdict))}
                  {@const isLinkedinProfile = Boolean(c.details?.provider === 'bright_data' || /linkedin/i.test(c.label))}
                  {@const isPortfolioAi = Boolean(!isGithubProfile && !isLinkedinProfile && projectChecks.length === 0 && c.details?.url && (c.details?.ai_verdict || c.details?.html_title || c.details?.ai_summary))}
                  <div class="p-3 text-sm space-y-2">
                    <div class="flex items-start justify-between gap-3">
                      <div class="min-w-0">
                        <p class="font-medium text-foreground">{c.label.replace(/_/g, ' ')}</p>
                        {#if c.note}
                          <p class="text-xs text-muted-foreground mt-0.5">{c.note.replace(/_/g, ' ')}</p>
                        {/if}
                      </div>
                      <Badge variant={c.status === 'passed' ? 'default' : 'secondary'} class="text-xs capitalize shrink-0">
                        {humanize(c.status)}
                      </Badge>
                    </div>

                    {#if isGithubProfile && c.details}
                      {@const verifiedLangs = Array.isArray(c.details.verified_languages) ? (c.details.verified_languages as string[]) : []}
                      {@const verifiedProjs = Array.isArray(c.details.verified_projects) ? (c.details.verified_projects as string[]) : []}
                      {@const ghDiscrepancies = Array.isArray(c.details.discrepancies) ? (c.details.discrepancies as string[]) : []}
                      <div class="rounded-md bg-muted/30 p-2.5 space-y-2 text-xs border-l-2 border-border">
                        <div class="flex flex-wrap items-center justify-between gap-2">
                          <div class="flex flex-wrap items-center gap-2">
                            {#if typeof c.details.profile_url === 'string'}
                              <a
                                href={c.details.profile_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                class="font-semibold text-primary hover:underline"
                              >
                                @{String(c.details.username)}
                              </a>
                            {:else}
                              <span class="font-semibold text-foreground">@{String(c.details.username)}</span>
                            {/if}
                            <span class="text-muted-foreground">
                              {c.details.original_repos ?? 0} original · {c.details.forked_repos ?? 0} forks · ★ {c.details.total_stars ?? 0}
                            </span>
                          </div>
                          <div class="flex items-center gap-1.5">
                            {#if c.details.ai_verdict}
                              <Badge variant={c.details.ai_verdict === 'consistent' ? 'default' : 'secondary'} class="text-[10px] capitalize">
                                {humanize(String(c.details.ai_verdict))}
                              </Badge>
                            {/if}
                            {#if typeof c.details.ai_alignment_score === 'number'}
                              <span class="font-mono text-[11px] text-muted-foreground">
                                {Math.round(c.details.ai_alignment_score * 100)}%
                              </span>
                            {/if}
                          </div>
                        </div>
                        {#if c.details.ai_summary}
                          <p class="text-foreground"><span class="font-medium">AI assessment:</span> {String(c.details.ai_summary)}</p>
                        {/if}
                        {#if ghLangs.length > 0}
                          <div class="flex flex-wrap items-center gap-1">
                            <span class="text-muted-foreground font-medium mr-1">Languages:</span>
                            {#each ghLangs.slice(0, 8) as lang}
                              <Badge variant="outline" class="text-[10px] font-normal bg-background">
                                {String(lang.name)}{lang.share_pct != null ? ` ${lang.share_pct}%` : ''}
                              </Badge>
                            {/each}
                          </div>
                        {/if}
                        {#if verifiedLangs.length > 0 || verifiedProjs.length > 0}
                          <div class="flex flex-wrap items-center gap-1">
                            <span class="text-muted-foreground font-medium mr-1">Matched claims:</span>
                            {#each verifiedLangs as vl}
                              <Badge variant="secondary" class="text-[10px] font-normal">skill: {vl}</Badge>
                            {/each}
                            {#each verifiedProjs as vp}
                              <Badge variant="secondary" class="text-[10px] font-normal">project: {vp}</Badge>
                            {/each}
                          </div>
                        {/if}
                        {#if ghRepos.length > 0}
                          <div class="space-y-1 pt-0.5">
                            <span class="text-muted-foreground font-medium">Public repositories:</span>
                            <div class="grid gap-1 sm:grid-cols-2">
                              {#each ghRepos.slice(0, 4) as repo}
                                <div class="rounded bg-background/70 px-2 py-1 border border-border/60">
                                  <div class="flex items-center justify-between gap-1">
                                    {#if typeof repo.url === 'string'}
                                      <a href={repo.url} target="_blank" rel="noopener noreferrer" class="font-medium text-primary hover:underline truncate">
                                        {String(repo.name)}
                                      </a>
                                    {:else}
                                      <span class="font-medium truncate">{String(repo.name)}</span>
                                    {/if}
                                    <span class="text-[10px] text-muted-foreground shrink-0">
                                      {repo.language ? String(repo.language) : ''}{repo.stars ? ` · ★${repo.stars}` : ''}
                                    </span>
                                  </div>
                                  {#if repo.description}
                                    <p class="text-[11px] text-muted-foreground line-clamp-1">{String(repo.description)}</p>
                                  {/if}
                                </div>
                              {/each}
                            </div>
                          </div>
                        {/if}
                        {#if ghDiscrepancies.length > 0}
                          <ul class="list-disc pl-4 text-amber-700 dark:text-amber-400 space-y-0.5">
                            {#each ghDiscrepancies as d}
                              <li>{d}</li>
                            {/each}
                          </ul>
                        {/if}
                      </div>
                    {/if}

                    {#if isLinkedinProfile && c.details && (c.details.url || c.details.headline || c.details.ai_summary)}
                      {@const liCompanies = Array.isArray(c.details.matched_companies) ? (c.details.matched_companies as string[]) : []}
                      {@const liRoles = Array.isArray(c.details.matched_roles) ? (c.details.matched_roles as string[]) : []}
                      {@const liEdu = Array.isArray(c.details.matched_education) ? (c.details.matched_education as string[]) : []}
                      {@const liCerts = Array.isArray(c.details.matched_certifications) ? (c.details.matched_certifications as string[]) : []}
                      {@const liProjs = Array.isArray(c.details.matched_projects) ? (c.details.matched_projects as string[]) : []}
                      {@const liSkills = Array.isArray(c.details.matched_skills) ? (c.details.matched_skills as string[]) : []}
                      {@const liDiscrepancies = Array.isArray(c.details.discrepancies) ? (c.details.discrepancies as string[]) : []}
                      <div class="rounded-md bg-muted/30 p-2.5 space-y-2 text-xs border-l-2 border-border">
                        <div class="flex flex-wrap items-center justify-between gap-2">
                          <div class="min-w-0 space-y-0.5">
                            {#if typeof c.details.url === 'string' && /^https?:\/\//i.test(c.details.url)}
                              <a
                                href={c.details.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                class="font-semibold text-primary hover:underline break-all"
                              >
                                {c.details.name ? String(c.details.name) : c.details.url}
                              </a>
                            {/if}
                            {#if c.details.headline || c.details.current_company}
                              <p class="text-muted-foreground">
                                {c.details.headline ? String(c.details.headline) : ''}{c.details.headline && c.details.current_company ? ' · ' : ''}{c.details.current_company ? String(c.details.current_company) : ''}
                              </p>
                            {/if}
                            {#if c.details.location || typeof c.details.connections === 'number' || typeof c.details.followers === 'number' || typeof c.details.experience_count === 'number'}
                              <p class="text-[11px] text-muted-foreground">
                                {[
                                  c.details.location ? String(c.details.location) : null,
                                  typeof c.details.connections === 'number' ? `${c.details.connections} connections` : null,
                                  typeof c.details.followers === 'number' ? `${c.details.followers} followers` : null,
                                  typeof c.details.experience_count === 'number' ? `${c.details.experience_count} roles` : null,
                                  typeof c.details.education_count === 'number' ? `${c.details.education_count} education` : null
                                ].filter(Boolean).join(' · ')}
                              </p>
                            {/if}
                          </div>
                          <div class="flex flex-wrap items-center gap-1.5 shrink-0">
                            {#if c.details.name_match && c.details.name_match !== 'unknown'}
                              <Badge
                                variant={c.details.name_match === 'match' ? 'outline' : 'destructive'}
                                class="text-[10px] capitalize"
                              >
                                Name: {humanize(String(c.details.name_match))}
                              </Badge>
                            {/if}
                            {#if c.details.timeline_alignment && c.details.timeline_alignment !== 'unknown'}
                              <Badge
                                variant={c.details.timeline_alignment === 'aligned' ? 'outline' : 'secondary'}
                                class="text-[10px] capitalize"
                              >
                                Timeline: {humanize(String(c.details.timeline_alignment))}
                              </Badge>
                            {/if}
                            {#if c.details.ai_verdict}
                              <Badge variant={c.details.ai_verdict === 'consistent' ? 'default' : 'secondary'} class="text-[10px] capitalize">
                                {humanize(String(c.details.ai_verdict))}
                              </Badge>
                            {/if}
                            {#if typeof c.details.ai_alignment_score === 'number'}
                              <span class="font-mono text-[11px] text-muted-foreground">
                                {Math.round(c.details.ai_alignment_score * 100)}%
                              </span>
                            {/if}
                          </div>
                        </div>
                        {#if c.details.ai_summary}
                          <p class="text-foreground"><span class="font-medium">AI assessment:</span> {String(c.details.ai_summary)}</p>
                        {/if}
                        {#if c.details.provider_error}
                          <p class="text-amber-700 dark:text-amber-400">
                            <span class="font-medium">Bright Data SDK:</span> {String(c.details.provider_error)}
                          </p>
                        {/if}
                        {#if liCompanies.length > 0 || liRoles.length > 0 || liEdu.length > 0 || liCerts.length > 0 || liProjs.length > 0 || liSkills.length > 0}
                          <div class="flex flex-wrap items-center gap-1">
                            <span class="text-muted-foreground font-medium mr-1">Matched:</span>
                            {#each liCompanies as mc}
                              <Badge variant="secondary" class="text-[10px] font-normal">company: {mc}</Badge>
                            {/each}
                            {#each liRoles as mr}
                              <Badge variant="secondary" class="text-[10px] font-normal">role: {mr}</Badge>
                            {/each}
                            {#each liEdu as me}
                              <Badge variant="outline" class="text-[10px] font-normal bg-background">edu: {me}</Badge>
                            {/each}
                            {#each liCerts as mcert}
                              <Badge variant="outline" class="text-[10px] font-normal bg-background">cert: {mcert}</Badge>
                            {/each}
                            {#each liProjs as mproj}
                              <Badge variant="outline" class="text-[10px] font-normal bg-background">project: {mproj}</Badge>
                            {/each}
                            {#each liSkills.slice(0, 8) as ms}
                              <Badge variant="outline" class="text-[10px] font-normal bg-background">skill: {ms}</Badge>
                            {/each}
                          </div>
                        {/if}
                        {#if liDiscrepancies.length > 0}
                          <ul class="list-disc pl-4 text-amber-700 dark:text-amber-400 space-y-0.5">
                            {#each liDiscrepancies as d}
                              <li>{d}</li>
                            {/each}
                          </ul>
                        {/if}
                      </div>
                    {/if}

                    {#if isPortfolioAi && c.details}
                      {@const pSkills = Array.isArray(c.details.matched_skills) ? (c.details.matched_skills as string[]) : []}
                      {@const pProjs = Array.isArray(c.details.matched_projects) ? (c.details.matched_projects as string[]) : []}
                      {@const pRoles = Array.isArray(c.details.matched_roles) ? (c.details.matched_roles as string[]) : []}
                      {@const pDiscrepancies = Array.isArray(c.details.discrepancies) ? (c.details.discrepancies as string[]) : []}
                      <div class="rounded-md bg-muted/30 p-2.5 space-y-1.5 text-xs border-l-2 border-border">
                        <div class="flex flex-wrap items-center justify-between gap-2">
                          {#if typeof c.details.url === 'string' && /^https?:\/\//i.test(c.details.url)}
                            <a href={c.details.url} target="_blank" rel="noopener noreferrer" class="font-medium text-primary hover:underline break-all">
                              {c.details.url}
                            </a>
                          {/if}
                          <div class="flex items-center gap-1.5 shrink-0">
                            {#if c.details.http_status}
                              <Badge variant="outline" class="text-[10px] font-mono">HTTP {c.details.http_status}</Badge>
                            {/if}
                            {#if c.details.ai_verdict}
                              <Badge variant={c.details.ai_verdict === 'consistent' ? 'default' : 'secondary'} class="text-[10px] capitalize">
                                {humanize(String(c.details.ai_verdict))}
                              </Badge>
                            {/if}
                            {#if typeof c.details.ai_alignment_score === 'number'}
                              <span class="font-mono text-[11px] text-muted-foreground">
                                {Math.round(c.details.ai_alignment_score * 100)}%
                              </span>
                            {/if}
                          </div>
                        </div>
                        {#if c.details.html_title}
                          <p class="text-muted-foreground"><span class="font-medium text-foreground">HTML title:</span> {String(c.details.html_title)}</p>
                        {/if}
                        {#if c.details.html_excerpt}
                          <p class="text-muted-foreground line-clamp-2"><span class="font-medium text-foreground">HTML output:</span> {String(c.details.html_excerpt)}</p>
                        {/if}
                        {#if c.details.ai_summary}
                          <p class="text-foreground"><span class="font-medium">AI check:</span> {String(c.details.ai_summary)}</p>
                        {/if}
                        {#if pSkills.length > 0 || pProjs.length > 0 || pRoles.length > 0}
                          <div class="flex flex-wrap gap-1 pt-0.5">
                            {#each pSkills as s}
                              <Badge variant="outline" class="text-[10px] font-normal bg-background">skill: {s}</Badge>
                            {/each}
                            {#each pProjs as pr}
                              <Badge variant="outline" class="text-[10px] font-normal bg-background">project: {pr}</Badge>
                            {/each}
                            {#each pRoles as r}
                              <Badge variant="outline" class="text-[10px] font-normal bg-background">role: {r}</Badge>
                            {/each}
                          </div>
                        {/if}
                        {#if pDiscrepancies.length > 0}
                          <ul class="list-disc pl-4 text-amber-700 dark:text-amber-400 space-y-0.5">
                            {#each pDiscrepancies as d}
                              <li>{d}</li>
                            {/each}
                          </ul>
                        {/if}
                      </div>
                    {/if}

                    {#if projectChecks.length > 0}
                      <div class="space-y-2 pt-1 pl-2 border-l-2 border-border">
                        {#each projectChecks as proj}
                          {@const matchedClaims = Array.isArray(proj.matched_claims) ? (proj.matched_claims as string[]) : []}
                          {@const discrepancies = Array.isArray(proj.discrepancies) ? (proj.discrepancies as string[]) : []}
                          <div class="rounded-md bg-muted/30 p-2.5 space-y-1.5 text-xs">
                            <div class="flex flex-wrap items-center justify-between gap-2">
                              <div class="min-w-0">
                                <span class="font-semibold text-foreground">{String(proj.project_name ?? 'Project')}</span>
                                {#if typeof proj.url === 'string' && /^https?:\/\//i.test(proj.url)}
                                  <a
                                    href={proj.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    class="ml-1.5 text-primary hover:underline break-all"
                                  >
                                    {proj.url}
                                  </a>
                                {/if}
                              </div>
                              <div class="flex flex-wrap items-center gap-1.5 shrink-0">
                                {#if proj.http_status}
                                  <Badge variant="outline" class="text-[10px] font-mono">HTTP {proj.http_status}</Badge>
                                {/if}
                                {#if proj.ai_verdict}
                                  <Badge
                                    variant={proj.ai_verdict === 'consistent' ? 'default' : 'secondary'}
                                    class="text-[10px] capitalize"
                                  >
                                    {humanize(String(proj.ai_verdict))}
                                  </Badge>
                                {/if}
                                {#if typeof proj.ai_relevance_score === 'number'}
                                  <span class="font-mono text-[11px] text-muted-foreground">
                                    {Math.round(proj.ai_relevance_score * 100)}%
                                  </span>
                                {/if}
                              </div>
                            </div>

                            {#if proj.html_title}
                              <p class="text-muted-foreground">
                                <span class="font-medium text-foreground">HTML title:</span> {String(proj.html_title)}
                              </p>
                            {/if}
                            {#if proj.html_excerpt}
                              <p class="text-muted-foreground line-clamp-2">
                                <span class="font-medium text-foreground">HTML output:</span> {String(proj.html_excerpt)}
                              </p>
                            {/if}
                            {#if proj.ai_summary}
                              <p class="text-foreground">
                                <span class="font-medium">AI check:</span> {String(proj.ai_summary)}
                              </p>
                            {/if}
                            {#if matchedClaims.length > 0}
                              <div class="flex flex-wrap gap-1 pt-0.5">
                                {#each matchedClaims as mc}
                                  <Badge variant="outline" class="text-[10px] font-normal bg-background">{mc}</Badge>
                                {/each}
                              </div>
                            {/if}
                            {#if discrepancies.length > 0}
                              <ul class="list-disc pl-4 text-amber-700 dark:text-amber-400 space-y-0.5">
                                {#each discrepancies as d}
                                  <li>{d}</li>
                                {/each}
                              </ul>
                            {/if}
                          </div>
                        {/each}
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            {/if}
            <p class="text-xs text-muted-foreground">
              These automated checks verify structure and consistency only; they do not independently prove identity.
            </p>
          {:else}
            <p class="text-sm text-muted-foreground">No identity checks have been executed.</p>
          {/if}
        </CardContent>
      </Card>

      <!-- Extracted Evidence Groups using Accordion -->
      <Card class="border-border bg-card shadow-sm lg:col-span-2">
        <CardHeader>
          <CardTitle class="text-lg">Grounding Evidence</CardTitle>
          <CardDescription>Exact source text excerpts from the resume supporting extracted claims.</CardDescription>
        </CardHeader>
        <CardContent>
          {#if evidenceCount}
            <Accordion.Root type="multiple" class="w-full">
              {#each evidenceGroups as g, idx}
                <Accordion.Item value={`item-${idx}`}>
                  <Accordion.Trigger class="text-sm font-semibold hover:no-underline">
                    {g.section} Evidence ({g.list.reduce((acc, i) => acc + i.evidence.length, 0)} excerpts)
                  </Accordion.Trigger>
                  <Accordion.Content class="space-y-3 pt-2">
                    {#each g.list as item}
                      {#if item.evidence.length}
                        <div class="rounded-lg border border-border bg-muted/20 p-3 space-y-1.5">
                          <div class="flex items-center gap-2">
                            <span class="text-sm font-semibold text-foreground">{item.label}</span>
                            {#if item.confidence !== null}
                              <span class="text-xs text-muted-foreground font-mono">
                                (confidence: {Math.round(item.confidence <= 1 ? item.confidence * 100 : item.confidence)}%)
                              </span>
                            {/if}
                          </div>
                          <ul class="space-y-1 border-l-2 border-primary/40 pl-3 text-xs text-muted-foreground font-mono">
                            {#each item.evidence as ev}
                              <li>"{ev}"</li>
                            {/each}
                          </ul>
                        </div>
                      {/if}
                    {/each}
                  </Accordion.Content>
                </Accordion.Item>
              {/each}
            </Accordion.Root>
          {:else}
            <p class="text-sm text-muted-foreground">No evidence text was returned with this profile.</p>
          {/if}
        </CardContent>
      </Card>
    </div>
  </Tabs.Content>
</Tabs.Root>
