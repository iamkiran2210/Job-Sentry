export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  /** Optional keyword (e.g. "DELETE") the user must type inside the dialog before confirming. */
  confirmText?: string;
}
let current = $state<(ConfirmOptions & { resolve: (ok: boolean) => void }) | null>(null);
export const confirmState = { get current() { return current; } };
export const confirmDialog = (o: ConfirmOptions) => new Promise<boolean>((resolve) => { current = { ...o, resolve }; });
export const settleConfirm = (ok: boolean) => { current?.resolve(ok); current = null; };
