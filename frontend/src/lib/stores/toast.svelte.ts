import { toast as sonnerToast } from 'svelte-sonner';

export interface ToastAction {
  label: string;
  onClick: () => void;
}

/**
 * Recruiter-facing toast notifications powered by svelte-sonner.
 * Stable id is derived from kind + title + detail to dedupe identical alerts.
 */
function stableId(kind: string, title: string, detail?: string): string {
  return `${kind}:${title}:${detail ?? ''}`;
}

export const toast = {
  error: (title: string, detail?: string) =>
    sonnerToast.error(title, {
      description: detail,
      id: stableId('error', title, detail),
      duration: 8000
    }),
  success: (title: string, detail?: string, opts?: { duration?: number; action?: ToastAction }) =>
    sonnerToast.success(title, {
      description: detail,
      id: stableId('success', title, detail),
      duration: opts?.duration ?? 4500,
      action: opts?.action
    }),
  info: (title: string, detail?: string, opts?: { duration?: number; action?: ToastAction }) =>
    sonnerToast.info(title, {
      description: detail,
      id: stableId('info', title, detail),
      duration: opts?.duration ?? 3500,
      action: opts?.action
    })
};
