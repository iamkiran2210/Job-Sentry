import { toast as sonnerToast } from 'svelte-sonner';

/**
 * Recruiter-facing toast notifications powered by svelte-sonner.
 * Stable id is derived from kind + title + detail to dedupe identical errors.
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
  success: (title: string, detail?: string) =>
    sonnerToast.success(title, {
      description: detail,
      id: stableId('success', title, detail),
      duration: 3500
    }),
  info: (title: string, detail?: string) =>
    sonnerToast.info(title, {
      description: detail,
      id: stableId('info', title, detail),
      duration: 4000
    })
};
