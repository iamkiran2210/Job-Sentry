<script lang="ts">
  import '../app.css';
  import Toaster from '$lib/components/Toaster.svelte';
  import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
  let { children } = $props();
</script>
{@render children()}
<Toaster />
<ConfirmDialog />
