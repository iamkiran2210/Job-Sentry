<script lang="ts">
  import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '$lib/components/ui/card';
  import { Button } from '$lib/components/ui/button';
  import Building2Icon from '@lucide/svelte/icons/building-2';

  let { email }: { email?: string } = $props();
</script>

<div class="mx-auto mt-10 max-w-xl">
  <Card class="border-border bg-card p-6 text-center shadow-sm">
    <div class="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
      <Building2Icon class="size-6" />
    </div>
    <CardHeader class="p-0">
      <CardTitle class="text-xl font-semibold">Join or create a company</CardTitle>
      <CardDescription class="mt-2 text-sm text-muted-foreground">
        Jobs, applicants and analytics are organised by company. Create your own company, or ask a company admin to add
        {#if email}<strong>{email}</strong>{:else}your email{/if} as a member.
      </CardDescription>
    </CardHeader>
    <CardContent class="mt-6 p-0">
      <Button href="/company" class="font-medium">
        Create a company
      </Button>
    </CardContent>
  </Card>
</div>
