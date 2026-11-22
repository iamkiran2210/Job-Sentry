<script lang="ts">
  import { listAccess, grantAccess, revokeAccess } from '$lib/services/jobs';
  import { ApiError } from '$lib/services/api-client';
  import { toast } from '$lib/stores/toast.svelte';
  import { toastError } from '$lib/errors';
  import { humanize } from '$lib/utils';

  import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '$lib/components/ui/card';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Badge } from '$lib/components/ui/badge';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import { Shield, UserPlus, Trash2, AlertCircle, Loader2 } from '@lucide/svelte';

  let { jobId }: { jobId: string } = $props();
  let rows = $state<Record<string, unknown>[]>([]);
  let denied = $state(false);
  let email = $state('');
  let level = $state<'viewer' | 'editor'>('viewer');
  let msg = $state('');
  let busy = $state(false);

  const s = (v: unknown) => (typeof v === 'string' ? v : '');

  async function load() {
    try {
      rows = await listAccess(jobId);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 403 || e.status === 404)) {
        denied = true;
      } else {
        msg = 'Could not load access list.';
      }
    }
  }

  load();

  async function run(fn: () => Promise<unknown>) {
    if (busy) return;
    busy = true;
    msg = '';
    try {
      await fn();
      await load();
      toast.success('Access updated');
    } catch (e) {
      toastError(e);
    } finally {
      busy = false;
    }
  }

  const selectClass =
    'h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring';
</script>

<Card class="border-border bg-card shadow-sm">
  <CardHeader class="pb-3">
    <div class="flex items-center gap-2">
      <Shield class="size-5 text-primary" />
      <CardTitle class="text-lg">Job Access & Permissions</CardTitle>
    </div>
    <CardDescription class="text-xs text-muted-foreground mt-1">
      Manage recruiter access to this specific job. Admin users can grant viewer or editor privileges.
    </CardDescription>
  </CardHeader>

  <CardContent class="space-y-4">
    {#if denied}
      <p class="text-sm text-muted-foreground">
        Only company administrators can manage direct access permissions for this job.
      </p>
    {:else}
      {#if msg}
        <Alert variant="destructive">
          <AlertCircle class="size-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{msg}</AlertDescription>
        </Alert>
      {/if}

      {#if rows.length === 0}
        <p class="text-sm text-muted-foreground py-1">
          No explicit grants. All company members currently have access.
        </p>
      {:else}
        <div class="divide-y divide-border rounded-lg border border-border">
          {#each rows as r}
            <div class="flex items-center justify-between p-3 text-sm">
              <div class="flex items-center gap-2">
                <span class="font-medium text-foreground">
                  {s(r.email) || s(r.name) || s(r.user_id)}
                </span>
                <Badge variant="outline" class="capitalize text-xs text-muted-foreground border-border">
                  {humanize(s(r.access_level) || 'viewer')}
                </Badge>
              </div>

              {#if s(r.user_id) || s(r.id)}
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onclick={() => run(() => revokeAccess(jobId, s(r.user_id) || s(r.id)))}
                  class="text-destructive hover:bg-destructive/10 h-8 px-2"
                >
                  <Trash2 class="size-3.5 mr-1" /> Revoke
                </Button>
              {/if}
            </div>
          {/each}
        </div>
      {/if}

      <!-- Grant access input row -->
      <div class="flex flex-wrap items-center gap-2 pt-2">
        <Input
          type="email"
          aria-label="Registered user's email"
          placeholder="colleague@company.com"
          bind:value={email}
          class="min-w-56 flex-1 h-9"
        />
        <select
          aria-label="Access level"
          bind:value={level}
          class={selectClass}
        >
          <option value="viewer">Viewer</option>
          <option value="editor">Editor</option>
        </select>
        <Button
          disabled={busy || !email.trim()}
          onclick={() =>
            run(async () => {
              await grantAccess(jobId, email.trim(), level);
              email = '';
            })}
          class="h-9 font-medium shrink-0"
        >
          {#if busy}
            <Loader2 class="size-4 mr-1.5 animate-spin" />
            Saving…
          {:else}
            <UserPlus class="size-4 mr-1.5" />
            Grant access
          {/if}
        </Button>
      </div>
    {/if}
  </CardContent>
</Card>
