<script lang="ts">
  import { goto } from '$app/navigation';
  import { logout, getAccess, adminCheck, deleteAccount } from '$lib/services/auth';
  import StatusBadge from '$lib/components/StatusBadge.svelte';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import { toast } from '$lib/stores/toast.svelte';
  import { toastError } from '$lib/errors';
  import { humanize, isObj } from '$lib/utils';
  import { Button } from '$lib/components/ui/button';
  import { AlertTriangle, Loader2, LogOut, Trash2 } from '@lucide/svelte';

  let { data } = $props();

  let access = $state<Record<string, unknown> | null>(null);
  let platformAdmin = $state<boolean | null>(null);
  let deleting = $state(false);
  let signingOut = $state(false);

  getAccess()
    .then((a) => (access = a))
    .catch(() => {});
  adminCheck()
    .then((r) => (platformAdmin = r?.is_admin === true || r?.role === 'admin'))
    .catch(() => (platformAdmin = false));

  const s = (v: unknown) => (typeof v === 'string' ? v : '');
  const company = $derived(access && isObj(access.company_access) ? access.company_access : null);
  const jobAccess = $derived(
    access && Array.isArray(access.job_accesses)
      ? (access.job_accesses as Record<string, unknown>[])
      : []
  );
  const display = $derived(data.user.name || data.user.email);
  const initials = $derived(
    display
      .split(/[\s@.]+/)
      .filter(Boolean)
      .map((p: string) => p[0])
      .slice(0, 2)
      .join('')
      .toUpperCase()
  );

  async function handleSignOut() {
    if (signingOut || deleting) return;
    signingOut = true;
    try {
      await logout();
      await goto('/login', { replaceState: true, invalidateAll: true });
    } finally {
      signingOut = false;
    }
  }

  async function handleDeleteAccount() {
    if (deleting || signingOut) return;
    const companyName = company ? s(company.company_name) || s(company.name) : '';
    const ok = await confirmDialog({
      title: 'Delete your account permanently?',
      message: companyName
        ? `This irreversibly deletes your account (${data.user.email}), all active sessions, and access grants. If you are the sole remaining member of "${companyName}", the entire company workspace — including all jobs, candidates, uploaded resumes, scores, verification records, and KPIs — will also be permanently erased.`
        : `This irreversibly deletes your account (${data.user.email}), all active sessions, and access grants. Nothing will remain.`,
      confirmLabel: 'Delete my account',
      confirmText: 'DELETE',
      danger: true
    });
    if (!ok) return;

    deleting = true;
    try {
      const res = await deleteAccount();
      const wipedCompany = res?.company_deleted === true;
      toast.success(
        'Account deleted',
        wipedCompany
          ? 'Your account and entire company workspace have been permanently erased.'
          : 'Your account and all session data have been permanently erased.'
      );
      await goto('/login', { replaceState: true, invalidateAll: true });
    } catch (e) {
      toastError(e, 'Could not delete account');
    } finally {
      deleting = false;
    }
  }
</script>

<div class="space-y-6 max-w-4xl">
  <div class="space-y-1">
    <h1 class="text-3xl font-bold tracking-tight text-foreground">Settings</h1>
    <p class="text-sm text-muted-foreground">Your account, workspace access, and security controls</p>
  </div>

  <!-- Account Profile Card -->
  <section class="rounded-xl border border-border bg-card p-6 shadow-sm" aria-labelledby="acct">
    <div class="flex flex-wrap items-center gap-4">
      <span
        class="flex h-14 w-14 items-center justify-center rounded-full bg-navy text-lg font-semibold text-white shrink-0"
        aria-hidden="true"
      >
        {initials}
      </span>
      <div class="min-w-0 flex-1">
        <h2 id="acct" class="truncate text-lg font-semibold text-foreground">{display}</h2>
        <p class="truncate text-sm text-muted-foreground">{data.user.email}</p>
      </div>
      <Button variant="outline" size="sm" onclick={handleSignOut} disabled={signingOut || deleting}>
        {#if signingOut}
          <Loader2 class="mr-1.5 size-4 animate-spin" />
          Signing out…
        {:else}
          <LogOut class="mr-1.5 size-4" />
          Sign out
        {/if}
      </Button>
    </div>

    <dl class="mt-5 grid gap-4 border-t border-border pt-5 text-sm sm:grid-cols-3">
      <div>
        <dt class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Account role</dt>
        <dd class="mt-1 font-medium text-foreground">{humanize(data.user.role)}</dd>
      </div>
      <div>
        <dt class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Company role</dt>
        <dd class="mt-1 font-medium text-foreground">
          {company ? humanize(s(company.role) || 'member') : 'No company yet'}
        </dd>
      </div>
      <div>
        <dt class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Administrator</dt>
        <dd class="mt-1 font-medium text-foreground">
          {platformAdmin === null ? 'Checking…' : platformAdmin ? 'Yes' : 'No'}
        </dd>
      </div>
    </dl>
  </section>

  <!-- Company Access Card -->
  <section class="rounded-xl border border-border bg-card p-6 shadow-sm" aria-labelledby="acc">
    <h2 id="acc" class="text-lg font-semibold text-foreground">Company access</h2>
    {#if company}
      <p class="mt-1 text-sm text-muted-foreground">
        You belong to <strong class="text-foreground">{s(company.company_name) || s(company.name) || 'your company'}</strong>
        as {humanize(s(company.role) || 'member')}.
      </p>
    {:else}
      <p class="mt-1 text-sm text-muted-foreground">
        You have not joined a company yet.
        <a href="/company" class="text-primary font-medium underline">Create one</a> or ask an admin to add you.
      </p>
    {/if}

    {#if jobAccess.length}
      <div class="mt-4 overflow-x-auto rounded-lg border border-border/70">
        <table class="w-full text-left text-sm">
          <thead class="bg-muted/30 text-muted-foreground">
            <tr>
              <th class="py-2.5 px-3 text-left font-semibold text-foreground">Job</th>
              <th class="py-2.5 px-3 text-center font-semibold text-foreground">Status</th>
              <th class="py-2.5 px-3 text-center font-semibold text-foreground">Access</th>
              <th class="py-2.5 px-3 text-right font-semibold text-foreground">Granted via</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            {#each jobAccess as j}
              <tr class="hover:bg-muted/20">
                <td class="py-2.5 px-3 text-left font-medium text-foreground">
                  {s(j.job_title) || s(j.title) || 'Untitled job'}
                </td>
                <td class="py-2.5 px-3 text-center">
                  {#if s(j.status)}
                    <StatusBadge status={s(j.status)} />
                  {:else}
                    —
                  {/if}
                </td>
                <td class="py-2.5 px-3 text-center text-foreground">
                  {humanize(s(j.access_level) || 'viewer')}
                </td>
                <td class="py-2.5 px-3 text-right text-muted-foreground">
                  {humanize(s(j.access_source) || 'direct')}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>

  <!-- Danger Zone: Delete Account -->
  <section
    class="rounded-xl border border-destructive/30 bg-destructive/5 p-6 shadow-sm"
    aria-labelledby="danger-zone"
  >
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <div class="space-y-1">
        <div class="flex items-center gap-2 text-destructive">
          <AlertTriangle class="size-4 shrink-0" />
          <h2 id="danger-zone" class="text-base font-semibold">Delete account</h2>
        </div>
        <p class="text-xs sm:text-sm text-muted-foreground">
          Permanently erase your account, active sessions, and access grants. If you are the sole member of your company, all company jobs, candidates, resumes, rankings, and KPIs will also be completely removed.
        </p>
      </div>

      <Button
        variant="destructive"
        size="sm"
        disabled={deleting || signingOut}
        onclick={handleDeleteAccount}
        class="shrink-0"
      >
        {#if deleting}
          <Loader2 class="mr-1.5 size-4 animate-spin" />
          Deleting account…
        {:else}
          <Trash2 class="mr-1.5 size-4" />
          Delete account
        {/if}
      </Button>
    </div>
  </section>
</div>
