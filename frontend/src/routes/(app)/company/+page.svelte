<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import { registerUserAsAdmin } from '$lib/services/auth';
  import {
    getCompany,
    createCompany,
    updateCompany,
    listMembers,
    addMember,
    removeMember,
    type CompanyInput
  } from '$lib/services/company';
  import { ApiError } from '$lib/services/api-client';
  import { toast } from '$lib/stores/toast.svelte';
  import { toastError } from '$lib/errors';

  import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '$lib/components/ui/card';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import { Label } from '$lib/components/ui/label';
  import { Textarea } from '$lib/components/ui/textarea';
  import { Badge } from '$lib/components/ui/badge';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import { Building2, Users, UserPlus, Trash2, Loader2, AlertCircle } from '@lucide/svelte';

  let { data } = $props();

  let st = $state<'loading' | 'ready' | 'none' | 'error'>('loading');
  let f = $state<CompanyInput>({ name: '', industry: '', website: '', location: '', description: '' });
  let members = $state<Record<string, unknown>[]>([]);
  let email = $state('');
  let nu = $state({ name: '', email: '', password: '' });
  let msg = $state('');
  let busy = $state(false);

  const s = (v: unknown) => (typeof v === 'string' ? v : '');

  async function load() {
    try {
      const c = await getCompany();
      f = {
        name: s(c.name),
        industry: s(c.industry),
        website: s(c.website),
        location: s(c.location),
        description: s(c.description)
      };
      st = 'ready';
      listMembers().then((m) => (members = m)).catch(() => (members = []));
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        st = 'none';
      } else {
        msg = e instanceof ApiError ? e.message : 'Something went wrong.';
        toastError(e, 'Could not load company');
        st = 'error';
      }
    }
  }

  load();

  async function run(fn: () => Promise<unknown>, done: string) {
    if (busy) return;
    busy = true;
    try {
      await fn();
      toast.success(done);
    } catch (e) {
      toastError(e);
    } finally {
      busy = false;
    }
  }

  const save = (e: SubmitEvent) => {
    e.preventDefault();
    return run(async () => {
      await (st === 'none' ? createCompany(f) : updateCompany(f));
      await Promise.all([load(), invalidateAll()]);
    }, st === 'none' ? 'Company created.' : 'Company profile saved.');
  };

  const add = () =>
    run(async () => {
      await addMember(email.trim());
      email = '';
      members = await listMembers();
    }, 'Member added.');

  const remove = (id: string) =>
    run(async () => {
      await removeMember(id);
      members = await listMembers();
    }, 'Member removed.');

  const createUser = () =>
    run(async () => {
      await registerUserAsAdmin(nu.name.trim(), nu.email.trim(), nu.password);
      nu = { name: '', email: '', password: '' };
    }, 'User created. You can now add them to the team by email.');
</script>

<div class="max-w-6xl space-y-6">
  <div>
    <h1 class="text-3xl font-bold tracking-tight text-foreground">Company</h1>
    <p class="mt-1 text-sm text-muted-foreground">
      {st === 'none'
        ? 'Create your company to start posting jobs and managing applicants.'
        : 'Manage your company profile and team workspace. Some administrative actions require admin role.'}
    </p>
  </div>

  {#if st === 'loading'}
    <div class="space-y-4">
      <Skeleton class="h-64 w-full rounded-xl" />
      <Skeleton class="h-48 w-full rounded-xl" />
    </div>
  {:else if st === 'error'}
    <Alert variant="destructive">
      <AlertCircle class="size-4" />
      <AlertTitle>Error loading company</AlertTitle>
      <AlertDescription>{msg}</AlertDescription>
    </Alert>
  {:else}
    <div class="grid lg:grid-cols-2 gap-6 items-start">
      <!-- Left Column: Company Details -->
      <div>
        <Card class="border-border bg-card shadow-sm">
          <form onsubmit={save}>
            <CardHeader>
              <div class="flex items-center gap-2">
                <Building2 class="size-5 text-primary" />
                <CardTitle class="text-xl">
                  {st === 'none' ? 'Create Company Profile' : 'Company Details'}
                </CardTitle>
              </div>
              <CardDescription>
                Basic organization details used across your job postings.
              </CardDescription>
            </CardHeader>

            <CardContent class="space-y-5">
              <div class="space-y-2">
                <Label for="name">Company Name *</Label>
                <Input id="name" required placeholder="Acme Technologies" bind:value={f.name} />
              </div>

              <div class="grid gap-4 sm:grid-cols-2">
                <div class="space-y-2">
                  <Label for="industry">Industry</Label>
                  <Input id="industry" placeholder="Software Engineering" bind:value={f.industry} />
                </div>

                <div class="space-y-2">
                  <Label for="location">Location</Label>
                  <Input id="location" placeholder="San Francisco, CA (or Remote)" bind:value={f.location} />
                </div>

                <div class="space-y-2 sm:col-span-2">
                  <Label for="website">Website</Label>
                  <Input id="website" type="url" placeholder="https://acme.example.com" bind:value={f.website} />
                </div>

                <div class="space-y-2 sm:col-span-2">
                  <Label for="description">Company Description</Label>
                  <Textarea
                    id="description"
                    rows={4}
                    placeholder="Tell candidates about your company mission and culture..."
                    bind:value={f.description}
                  />
                </div>
              </div>
            </CardContent>

            <CardFooter class="border-t border-border/50 bg-muted/20 px-6 py-4 flex justify-end">
              <Button type="submit" disabled={busy || !f.name.trim()}>
                {#if busy}
                  <Loader2 class="mr-2 size-4 animate-spin" />
                  Saving…
                {:else}
                  {st === 'none' ? 'Create company' : 'Save changes'}
                {/if}
              </Button>
            </CardFooter>
          </form>
        </Card>
      </div>

      <!-- Right Column: Team Members & Create User -->
      <div class="space-y-6">
        {#if st === 'ready'}
          <!-- Team Members Section -->
          <Card class="border-border bg-card shadow-sm">
            <CardHeader>
              <div class="flex items-center gap-2">
                <Users class="size-5 text-primary" />
                <CardTitle class="text-xl">Team Members</CardTitle>
              </div>
              <CardDescription>
                Recruiters and admins who have access to this company's jobs and applicants.
              </CardDescription>
            </CardHeader>

            <CardContent class="space-y-6">
              {#if members.length === 0}
                <p class="text-sm text-muted-foreground py-2">
                  No members to display. (The member list is visible to admins).
                </p>
              {:else}
                <div class="divide-y divide-border rounded-lg border border-border">
                  {#each members as m}
                    <div class="flex items-center justify-between p-4">
                      <div class="flex items-center gap-3">
                        <div class="size-8 rounded-full bg-primary/10 text-primary flex items-center justify-center font-semibold text-xs">
                          {(s(m.name) || s(m.email)).slice(0, 2).toUpperCase()}
                        </div>
                        <div>
                          <p class="text-sm font-medium text-foreground">
                            {s(m.name) || s(m.email)}
                          </p>
                          <p class="text-xs text-muted-foreground">{s(m.email)}</p>
                        </div>
                      </div>
                      <div class="flex items-center gap-3">
                        <Badge variant="secondary" class="capitalize text-xs">
                          {s(m.role) || 'recruiter'}
                        </Badge>
                        {#if s(m.id) || s(m.user_id)}
                          <Button
                            variant="ghost"
                            size="icon"
                            disabled={busy}
                            onclick={() => remove(s(m.id) || s(m.user_id))}
                            class="text-destructive hover:bg-destructive/10"
                            title="Remove member"
                          >
                            <Trash2 class="size-4" />
                          </Button>
                        {/if}
                      </div>
                    </div>
                  {/each}
                </div>
              {/if}

              <!-- Add Member Input -->
              <div class="flex flex-col sm:flex-row gap-3 pt-2">
                <div class="flex-1 space-y-1">
                  <Input
                    type="email"
                    placeholder="colleague@company.com"
                    bind:value={email}
                  />
                </div>
                <Button
                  variant="outline"
                  disabled={busy || !email.trim()}
                  onclick={add}
                  class="shrink-0"
                >
                  <UserPlus class="mr-2 size-4" />
                  Add member
                </Button>
              </div>
            </CardContent>
          </Card>

          <!-- Admin: Create User -->
          {#if data.user.role === 'admin'}
            <Card class="border-border bg-card shadow-sm">
              <CardHeader>
                <CardTitle class="text-lg">Create User (System Admin)</CardTitle>
                <CardDescription>
                  Register a new user account directly on the platform, then invite them by email above.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div class="grid gap-3 sm:grid-cols-3">
                  <Input placeholder="Full name" bind:value={nu.name} />
                  <Input type="email" placeholder="Email" bind:value={nu.email} />
                  <Input type="password" placeholder="Temporary password" bind:value={nu.password} />
                </div>
              </CardContent>
              <CardFooter class="border-t border-border/50 bg-muted/20 px-6 py-3 flex justify-end">
                <Button
                  variant="secondary"
                  disabled={busy || !nu.name || !nu.email || !nu.password}
                  onclick={createUser}
                >
                  Create user
                </Button>
              </CardFooter>
            </Card>
          {/if}
        {:else}
          <Card class="border-dashed border-border bg-card/50">
            <CardContent class="p-8 text-center text-sm text-muted-foreground">
              Once your company profile is created, you can invite team members and manage recruiter permissions here.
            </CardContent>
          </Card>
        {/if}
      </div>
    </div>
  {/if}
</div>
