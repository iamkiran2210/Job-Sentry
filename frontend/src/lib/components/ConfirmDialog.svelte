<script lang="ts">
  import * as AlertDialog from '$lib/components/ui/alert-dialog';
  import { Input } from '$lib/components/ui/input';
  import { Label } from '$lib/components/ui/label';
  import { confirmState, settleConfirm } from '$lib/stores/confirm.svelte';

  let open = $derived(confirmState.current !== null);
  let typed = $state('');

  $effect(() => {
    if (!confirmState.current) {
      typed = '';
    }
  });

  const requiredText = $derived(confirmState.current?.confirmText?.trim() ?? '');
  const canConfirm = $derived(
    !requiredText || typed.trim().toUpperCase() === requiredText.toUpperCase()
  );

  function close(ok: boolean) {
    if (ok && !canConfirm) return;
    typed = '';
    settleConfirm(ok);
  }
</script>

<AlertDialog.Root {open} onOpenChange={(v) => { if (!v) close(false); }}>
  {#if confirmState.current}
    <AlertDialog.Content>
      <AlertDialog.Header>
        <AlertDialog.Title>{confirmState.current.title}</AlertDialog.Title>
        <AlertDialog.Description>{confirmState.current.message}</AlertDialog.Description>
      </AlertDialog.Header>
      {#if requiredText}
        <div class="mt-3 space-y-1.5">
          <Label for="confirm-dialog-input" class="text-xs font-medium text-foreground">
            Type <span class="font-mono font-bold text-destructive">{requiredText}</span> to confirm
          </Label>
          <Input
            id="confirm-dialog-input"
            bind:value={typed}
            placeholder={requiredText}
            autocomplete="off"
            onkeydown={(e) => {
              if (e.key === 'Enter' && canConfirm) {
                e.preventDefault();
                close(true);
              }
            }}
          />
        </div>
      {/if}
      <AlertDialog.Footer class="mt-4 gap-2">
        <AlertDialog.Cancel
          onclick={() => close(false)}
          class="border border-[#101D35]/20 text-[#101D35] hover:bg-[#F6F8FC]"
        >
          Cancel
        </AlertDialog.Cancel>
        <AlertDialog.Action
          disabled={!canConfirm}
          onclick={() => close(true)}
          class={confirmState.current.danger
            ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90 font-medium shadow-sm disabled:opacity-50 disabled:pointer-events-none'
            : 'bg-[#101D35] text-white hover:bg-[#101D35]/90 font-medium shadow-sm disabled:opacity-50 disabled:pointer-events-none'}
        >
          {confirmState.current.confirmLabel ?? 'Confirm'}
        </AlertDialog.Action>
      </AlertDialog.Footer>
    </AlertDialog.Content>
  {/if}
</AlertDialog.Root>
