<script lang="ts">
  import { Card, CardContent } from '$lib/components/ui/card';
  import { Button } from '$lib/components/ui/button';
  import { UploadCloud } from '@lucide/svelte';

  let {
    onFiles,
    class: className
  }: {
    onFiles: (files: FileList | File[]) => void;
    class?: string;
  } = $props();

  let drag = $state(false);
  let fileInput = $state<HTMLInputElement>();
</script>

<div
  role="group"
  aria-label="Drop files here"
  ondragover={(e) => {
    e.preventDefault();
    drag = true;
  }}
  ondragleave={() => (drag = false)}
  ondrop={(e) => {
    e.preventDefault();
    drag = false;
    if (e.dataTransfer?.files) onFiles(e.dataTransfer.files);
  }}
  class={`w-full transition-colors rounded-2xl border-2 border-dashed p-12 text-center ${
    drag ? 'border-primary bg-primary/5' : 'border-border bg-card'
  } ${className ?? ''}`}
>
  <div class="mx-auto flex size-14 items-center justify-center rounded-full bg-primary/10 text-primary mb-4">
    <UploadCloud class="size-7" />
  </div>

  <h3 class="text-base font-semibold text-foreground">Drag and drop resumes here</h3>
  <p class="mt-1 text-xs text-muted-foreground max-w-sm mx-auto">
    Supported file formats: PDF, DOCX, JPG or PNG (up to 10 MB per file).
  </p>

  <div class="mt-5">
    <input
      bind:this={fileInput}
      type="file"
      multiple
      class="sr-only"
      accept=".pdf,.docx,.jpg,.jpeg,.png"
      onchange={(e) => {
        if (e.currentTarget.files) onFiles(e.currentTarget.files);
        e.currentTarget.value = '';
      }}
    />
    <Button
      type="button"
      onclick={() => fileInput?.click()}
      class="font-medium"
    >
      Browse files
    </Button>
  </div>
</div>
