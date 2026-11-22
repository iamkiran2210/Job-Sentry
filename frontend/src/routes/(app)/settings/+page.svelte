<script lang="ts">
  import { goto } from '$app/navigation';
  import { logout, getAccess, adminCheck } from '$lib/services/auth';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { humanize, isObj } from '$lib/utils';
  let { data } = $props();

  let access = $state<Record<string, unknown> | null>(null);
  let platformAdmin = $state<boolean | null>(null);
  getAccess().then((a) => (access = a)).catch(() => {});
  adminCheck().then((r) => (platformAdmin = r.is_admin === true)).catch(() => (platformAdmin = false));

  const s = (v: unknown) => (typeof v === 'string' ? v : '');
  const company = $derived(access && isObj(access.company_access) ? access.company_access : null);
  const jobAccess = $derived(access && Array.isArray(access.job_accesses) ? (access.job_accesses as Record<string, unknown>[]) : []);
  const display = $derived(data.user.name || data.user.email);
  const initials = $derived(display.split(/[\s@.]+/).filter(Boolean).map((p: string) => p[0]).slice(0, 2).join('').toUpperCase());
</script>

<h1 class="text-3xl font-bold tracking-tight text-foreground">Settings</h1>
<p class="text-sm text-muted-foreground">Your account and company access</p>

<div class="grid max-w-4xl gap-6 mt-6">
  <section class="rounded-xl border border-border bg-card p-6 shadow-sm" aria-labelledby="acct">
    <div class="flex flex-wrap items-center gap-4">
      <span class="flex h-14 w-14 items-center justify-center rounded-full bg-navy text-lg font-semibold text-white" aria-hidden="true">{initials}</span>
      <div class="min-w-0 flex-1"><h2 id="acct" class="truncate text-lg font-semibold text-foreground">{display}</h2><p class="truncate text-sm text-muted-foreground">{data.user.email}</p></div>
      <button onclick={async () => { await logout(); await goto('/login'); }} class="rounded-md border border-border px-4 py-2 text-sm hover:bg-muted font-medium transition-colors">Sign out</button>
    </div>
    <dl class="mt-5 grid gap-4 border-t border-border pt-5 text-sm sm:grid-cols-3">
      <div><dt class="text-muted-foreground">Account role</dt><dd class="mt-1 font-medium text-foreground">{humanize(data.user.role)}</dd></div>
      <div><dt class="text-muted-foreground">Company role</dt><dd class="mt-1 font-medium text-foreground">{company ? humanize(s(company.role) || 'member') : 'No company yet'}</dd></div>
      <div><dt class="text-muted-foreground">Platform administrator</dt><dd class="mt-1 font-medium text-foreground">{platformAdmin === null ? 'Checking…' : platformAdmin ? 'Yes' : 'No'}</dd></div>
    </dl>
  </section>

  <section class="rounded-xl border border-border bg-card p-6 shadow-sm" aria-labelledby="acc">
    <h2 id="acc" class="text-lg font-semibold text-foreground">Company access</h2>
    {#if company}
      <p class="mt-1 text-sm text-muted-foreground">You belong to <strong class="text-foreground">{s(company.company_name) || s(company.name) || 'your company'}</strong> as {humanize(s(company.role) || 'member')}.</p>
    {:else}
      <p class="mt-1 text-sm text-muted-foreground">You have not joined a company yet. <a href="/company" class="text-primary font-medium underline">Create one</a> or ask an admin to add you.</p>
    {/if}
    {#if jobAccess.length}
      <div class="mt-4 overflow-x-auto"><table class="w-full text-left text-sm">
        <thead class="text-muted-foreground"><tr><th class="py-2 px-3 text-left font-semibold text-foreground">Job</th><th class="py-2 px-3 text-center font-semibold text-foreground">Status</th><th class="py-2 px-3 text-center font-semibold text-foreground">Access</th><th class="py-2 px-3 text-right font-semibold text-foreground">Granted via</th></tr></thead>
        <tbody>{#each jobAccess as j}<tr><td class="py-2.5 px-3 text-left font-medium text-foreground">{s(j.job_title) || s(j.title) || 'Untitled job'}</td><td class="py-2.5 px-3 text-center">{#if s(j.status)}<StatusBadge status={s(j.status)} />{:else}—{/if}</td><td class="py-2.5 px-3 text-center text-foreground">{humanize(s(j.access_level) || 'viewer')}</td><td class="py-2.5 px-3 text-right text-muted-foreground">{humanize(s(j.access_source) || 'direct')}</td></tr>{/each}</tbody>
      </table></div>
    {/if}
  </section>
</div>
