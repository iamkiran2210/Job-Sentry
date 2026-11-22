<script lang="ts">
  import type { Snippet } from 'svelte';
  import { untrack } from 'svelte';
  import {
    EMPLOYMENT_TYPES,
    WORK_MODES,
    type EmploymentType,
    type WorkMode,
    type JobInput
  } from '$lib/types/job';
  import { humanize } from '$lib/utils';
  import { toastError } from '$lib/errors';

  import { Input } from '$lib/components/ui/input';
  import { Label } from '$lib/components/ui/label';
  import { Textarea } from '$lib/components/ui/textarea';
  import { Button } from '$lib/components/ui/button';
  import * as Select from '$lib/components/ui/select';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import { Card, CardContent } from '$lib/components/ui/card';
  import { AlertCircle, Loader2 } from '@lucide/svelte';

  let {
    initial,
    submitLabel,
    cancelHref,
    onSubmit,
    description = $bindable(''),
    extra,
    blocked = ''
  }: {
    initial?: Partial<JobInput>;
    submitLabel: string;
    cancelHref: string;
    onSubmit: (b: JobInput) => Promise<void>;
    description?: string;
    extra?: Snippet;
    blocked?: string;
  } = $props();

  const i = untrack(() => initial);
  let title = $state(i?.title ?? '');
  description = untrack(() => description) || (i?.description ?? '');
  let department = $state(i?.department ?? '');
  let location = $state(i?.location ?? '');
  let openings = $state(i?.openings ?? 1);
  let employment_type = $state<EmploymentType>(i?.employment_type ?? 'full_time');
  let work_mode = $state<WorkMode>(i?.work_mode ?? 'hybrid');
  let pending = $state(false);
  let touched = $state(false);

  const titleErr = $derived(touched && !title.trim() ? 'Title is required' : '');
  const descErr = $derived(touched && !description.trim() ? 'Description is required' : '');

  /** Validates and returns the form values, or null when required fields are missing. */
  export function getValues(): JobInput | null {
    touched = true;
    if (!title.trim() || !description.trim()) return null;
    return {
      title: title.trim(),
      description,
      department: department || null,
      location: location || null,
      employment_type,
      work_mode,
      openings
    };
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    const v = getValues();
    if (pending || !v || blocked) return;
    pending = true;
    try {
      await onSubmit(v);
    } catch (err) {
      toastError(err, 'Could not save job');
    } finally {
      pending = false;
    }
  }
</script>

<Card class="border-border bg-card shadow-sm max-w-4xl">
  <CardContent class="p-6 sm:p-8">
    <form onsubmit={submit} novalidate class="space-y-6">
      <div class="space-y-2">
        <Label for="title">Job Title *</Label>
        <Input
          id="title"
          placeholder="e.g. Senior Backend Engineer"
          bind:value={title}
          aria-invalid={!!titleErr}
        />
        {#if titleErr}
          <p class="text-xs text-destructive">{titleErr}</p>
        {/if}
      </div>

      <div class="grid gap-5 sm:grid-cols-2">
        <div class="space-y-2">
          <Label for="department">Department</Label>
          <Input id="department" placeholder="e.g. Platform Infrastructure" bind:value={department} />
        </div>

        <div class="space-y-2">
          <Label for="location">Location</Label>
          <Input id="location" placeholder="e.g. San Francisco, CA" bind:value={location} />
        </div>

        <div class="space-y-2">
          <Label for="employment_type">Employment Type</Label>
          <Select.Root type="single" bind:value={employment_type}>
            <Select.Trigger id="employment_type" class="w-full">
              {humanize(employment_type)}
            </Select.Trigger>
            <Select.Content>
              {#each EMPLOYMENT_TYPES as v}
                <Select.Item value={v}>{humanize(v)}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        </div>

        <div class="space-y-2">
          <Label for="work_mode">Work Mode</Label>
          <Select.Root type="single" bind:value={work_mode}>
            <Select.Trigger id="work_mode" class="w-full">
              {humanize(work_mode)}
            </Select.Trigger>
            <Select.Content>
              {#each WORK_MODES as v}
                <Select.Item value={v}>{humanize(v)}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        </div>

        <div class="space-y-2 sm:col-span-2">
          <Label for="openings">Number of Openings</Label>
          <Input id="openings" type="number" min="1" bind:value={openings} class="max-w-xs" />
        </div>
      </div>

      <div class="space-y-2">
        <Label for="description">Job Description *</Label>
        <Textarea
          id="description"
          rows={6}
          placeholder="Detailed role responsibilities, tech stack, and background requirements..."
          bind:value={description}
          aria-invalid={!!descErr}
        />
        {#if descErr}
          <p class="text-xs text-destructive">{descErr}</p>
        {/if}
      </div>

      {@render extra?.()}

      {#if blocked}
        <Alert variant="destructive">
          <AlertCircle class="size-4" />
          <AlertTitle>Publishing Blocked</AlertTitle>
          <AlertDescription>{blocked}</AlertDescription>
        </Alert>
      {/if}

      <div class="flex items-center justify-end gap-3 pt-4 border-t border-border/60">
        <Button variant="outline" href={cancelHref}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending || !!blocked}>
          {#if pending}
            <Loader2 class="mr-2 size-4 animate-spin" />
            Saving…
          {:else}
            {submitLabel}
          {/if}
        </Button>
      </div>
    </form>
  </CardContent>
</Card>
