<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { logout } from '$lib/services/auth';
  import NoCompany from '$lib/components/NoCompany.svelte';
  import LogoMark from '$lib/components/LogoMark.svelte';

  import * as Sidebar from '$lib/components/ui/sidebar';
  import * as Breadcrumb from '$lib/components/ui/breadcrumb';
  import * as Avatar from '$lib/components/ui/avatar';
  import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
  import { Separator } from '$lib/components/ui/separator';
  import { Alert, AlertDescription, AlertTitle } from '$lib/components/ui/alert';
  import { Badge } from '$lib/components/ui/badge';

  import {
    LayoutDashboard,
    Briefcase,
    Users,
    ChartColumn,
    Database,
    Building2,
    Settings,
    LogOut,
    ChevronDown,
    AlertTriangle
  } from '@lucide/svelte';
  import { pageTitleStore } from '$lib/stores/page-title.svelte';

  let { data, children } = $props();

  const navItems = [
    { label: 'Overview', href: '/dashboard', icon: LayoutDashboard },
    { label: 'Jobs', href: '/jobs', icon: Briefcase },
    { label: 'Candidates', href: '/candidates', icon: Users },
    { label: 'Analytics', href: '/analytics', icon: ChartColumn },
    { label: 'Data', href: '/data', icon: Database },
    { label: 'Company', href: '/company', icon: Building2 },
    { label: 'Settings', href: '/settings', icon: Settings }
  ];

  const display = $derived(data.user.name || data.user.email);
  const initials = $derived(
    display
      .split(/[\s@.]+/)
      .filter(Boolean)
      .map((s: string) => s[0])
      .slice(0, 2)
      .join('')
      .toUpperCase()
  );

  const gated = $derived(
    ['/dashboard', '/jobs', '/candidates', '/analytics', '/data'].some((p) =>
      page.url.pathname.startsWith(p)
    )
  );

  const isUuid = (s: string) =>
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s);

  // Derive breadcrumbs from pathname, mapping entity IDs to human readable names
  const pathSegments = $derived(
    page.url.pathname
      .split('/')
      .filter(Boolean)
      .map((seg, idx, arr) => {
        let label = pageTitleStore.getTitle(seg);
        if (!label) {
          if (isUuid(seg)) {
            const prev = arr[idx - 1];
            label =
              prev === 'jobs'
                ? 'Job Details'
                : prev === 'candidates'
                  ? 'Candidate Details'
                  : prev === 'applicants'
                    ? 'Applicant Details'
                    : 'Details';
          } else {
            label = seg.charAt(0).toUpperCase() + seg.slice(1).replace(/-/g, ' ');
          }
        }
        return {
          label,
          href: '/' + arr.slice(0, idx + 1).join('/'),
          isLast: idx === arr.length - 1
        };
      })
  );

  async function signOut() {
    await logout();
    await goto('/login', { replaceState: true, invalidateAll: true });
  }
</script>

<Sidebar.Provider>
  <div class="flex min-h-screen w-full bg-background">
    <!-- Collapsible App Shell Sidebar -->
    <Sidebar.Root class="border-sidebar-border bg-sidebar text-sidebar-foreground">
      <Sidebar.Header class="h-16 flex items-center justify-center px-4 border-b border-sidebar-border/60">
        <a href="/dashboard" class="flex items-center px-1 py-1 w-full">
          <LogoMark variant="white" class="h-11 w-auto max-w-full" />
        </a>
      </Sidebar.Header>

      <Sidebar.Content class="bg-sidebar px-2 py-3">
        <Sidebar.Group class="bg-sidebar">
          <Sidebar.Menu>
            {#each navItems as item}
              {@const active = page.url.pathname.startsWith(item.href)}
              <Sidebar.MenuItem>
                <Sidebar.MenuButton
                  isActive={active}
                  tooltipContent={item.label}
                  class={active
                    ? 'bg-primary! text-primary-foreground! font-medium shadow-xs hover:bg-primary/90!'
                    : 'bg-transparent text-sidebar-foreground hover:bg-sidebar-accent hover:text-white font-normal transition-colors'}
                >
                  {#snippet child({ props })}
                    <a href={item.href} {...props}>
                      <item.icon class="size-4 shrink-0" />
                      <span>{item.label}</span>
                    </a>
                  {/snippet}
                </Sidebar.MenuButton>
              </Sidebar.MenuItem>
            {/each}
          </Sidebar.Menu>
        </Sidebar.Group>
      </Sidebar.Content>

      <Sidebar.Rail />
    </Sidebar.Root>

    <!-- Main Inset Content Area -->
    <Sidebar.Inset class="flex flex-1 flex-col min-w-0">
      <header class="sticky top-0 z-10 flex h-14 items-center justify-between gap-2 border-b border-border bg-card px-3 sm:px-6">
        <div class="flex items-center gap-2 sm:gap-3 min-w-0 flex-1">
          <Sidebar.Trigger class="text-foreground hover:bg-muted shrink-0" />
          <Separator orientation="vertical" class="h-4 bg-border shrink-0" />
          <div class="min-w-0 flex-1 overflow-x-auto no-scrollbar">
            <Breadcrumb.Root class="min-w-0">
              <Breadcrumb.List class="flex-nowrap whitespace-nowrap">
                <Breadcrumb.Item class="hidden sm:inline-flex">
                  <Breadcrumb.Link href="/dashboard">Home</Breadcrumb.Link>
                </Breadcrumb.Item>
                {#each pathSegments as segment, i}
                  <Breadcrumb.Separator class={i === 0 ? 'hidden sm:inline-flex' : ''} />
                  <Breadcrumb.Item class="min-w-0">
                    {#if segment.isLast}
                      <Breadcrumb.Page class="truncate max-w-[160px] sm:max-w-none">{segment.label}</Breadcrumb.Page>
                    {:else}
                      <Breadcrumb.Link href={segment.href} class="truncate max-w-[110px] sm:max-w-none">{segment.label}</Breadcrumb.Link>
                    {/if}
                  </Breadcrumb.Item>
                {/each}
              </Breadcrumb.List>
            </Breadcrumb.Root>
          </div>
        </div>

        <div class="flex items-center gap-2 sm:gap-3 shrink-0">
          {#if data.user.role}
            <Badge variant="outline" class="hidden sm:inline-flex capitalize font-normal text-xs text-muted-foreground">
              {data.user.role}
            </Badge>
          {/if}

          <!-- Account Dropdown Menu -->
          <DropdownMenu.Root>
            <DropdownMenu.Trigger class="flex items-center gap-2 rounded-full p-1 text-sm outline-none hover:bg-muted transition-colors focus-visible:ring-2 focus-visible:ring-ring">
              <Avatar.Root class="size-8 border border-border bg-primary/10 text-primary">
                <Avatar.Fallback class="bg-primary/10 text-primary font-semibold text-xs">
                  {initials}
                </Avatar.Fallback>
              </Avatar.Root>
              <span class="hidden text-sm font-medium text-foreground md:inline-block max-w-[140px] truncate">
                {display}
              </span>
              <ChevronDown class="size-3.5 text-muted-foreground" />
            </DropdownMenu.Trigger>

            <DropdownMenu.Content align="end" class="w-56">
              <DropdownMenu.Label class="font-normal">
                <div class="flex flex-col space-y-1">
                  <p class="text-sm font-medium leading-none">{display}</p>
                  <p class="text-xs leading-none text-muted-foreground truncate">{data.user.email}</p>
                </div>
              </DropdownMenu.Label>
              <DropdownMenu.Separator />
              <DropdownMenu.Item onclick={() => goto('/company')}>
                <Building2 class="mr-2 size-4" />
                <span>Company Profile</span>
              </DropdownMenu.Item>
              <DropdownMenu.Item onclick={() => goto('/settings')}>
                <Settings class="mr-2 size-4" />
                <span>Settings</span>
              </DropdownMenu.Item>
              <DropdownMenu.Separator />
              <DropdownMenu.Item onclick={signOut} class="text-destructive focus:text-destructive">
                <LogOut class="mr-2 size-4" />
                <span>Sign out</span>
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        </div>
      </header>

      <main class="flex-1 p-4 sm:p-6 md:p-8 min-w-0">
        {#if !data.hasCompany && !gated && !page.url.pathname.startsWith('/company')}
          <Alert class="mb-6 border-amber-200 bg-amber-50/70 text-amber-900">
            <AlertTriangle class="size-4 text-amber-600" />
            <AlertTitle class="font-semibold text-amber-900">No company profile set up</AlertTitle>
            <AlertDescription class="text-amber-800">
              You have not set up a company yet. <a class="font-semibold underline hover:text-amber-950" href="/company">Create your company</a> to start posting jobs and reviewing applicants.
            </AlertDescription>
          </Alert>
        {/if}

        {#if !data.hasCompany && gated}
          <NoCompany email={data.user.email} />
        {:else}
          {@render children()}
        {/if}
      </main>
    </Sidebar.Inset>
  </div>
</Sidebar.Provider>
