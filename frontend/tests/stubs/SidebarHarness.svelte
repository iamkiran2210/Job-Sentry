<script lang="ts">
  import * as Sidebar from '$lib/components/ui/sidebar';
</script>

<Sidebar.Provider>
  <Sidebar.Root>
    <Sidebar.Header>
      <a href="/dashboard" data-testid="logo-link">Logo</a>
    </Sidebar.Header>
    <Sidebar.Content>
      <Sidebar.Group>
        <Sidebar.Menu>
          <Sidebar.MenuItem>
            <Sidebar.MenuButton tooltipContent="Overview" isActive={true}>
              {#snippet child({ props })}
                <a href="/dashboard" data-testid="nav-dashboard" {...props}>Overview</a>
              {/snippet}
            </Sidebar.MenuButton>
          </Sidebar.MenuItem>
          <Sidebar.MenuItem>
            <Sidebar.MenuButton tooltipContent="Jobs">
              {#snippet child({ props })}
                <a href="/jobs" data-testid="nav-jobs" {...props}>Jobs</a>
              {/snippet}
            </Sidebar.MenuButton>
          </Sidebar.MenuItem>
        </Sidebar.Menu>
      </Sidebar.Group>
    </Sidebar.Content>
    <Sidebar.Rail />
  </Sidebar.Root>
  <Sidebar.Inset>
    <Sidebar.Trigger data-testid="sidebar-trigger" />
  </Sidebar.Inset>
</Sidebar.Provider>
