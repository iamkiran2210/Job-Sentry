import { ApiError } from '$lib/services/api-client';
import { toast } from '$lib/stores/toast.svelte';

/** Turns any error into a plain-language title plus a useful detail line. Never exposes ids or request paths. */
export function explain(e: unknown): { title: string; detail?: string } {
  if (!(e instanceof ApiError)) return { title: 'Something went wrong', detail: 'Please try again. If it keeps happening, contact support.' };
  const backend = e.message.trim();
  const fields = Array.isArray(e.errors)
    ? (e.errors as Record<string, unknown>[]).map((x) => [Array.isArray(x.loc) ? (x.loc as unknown[]).slice(1).join('.') : x.field, x.msg ?? x.message].filter(Boolean).join(': ')).filter(Boolean).slice(0, 3).join(' · ')
    : '';
  switch (e.status) {
    case 0: return { title: 'Cannot reach the server', detail: 'Check your connection and that the backend is running.' };
    case 401: return { title: 'Your session has ended', detail: 'Please sign in again.' };
    case 403: return { title: 'You do not have permission', detail: backend || 'Ask a company admin for access.' };
    case 404: return { title: 'Not found', detail: backend || 'It may have been deleted or moved.' };
    case 409: return { title: 'Conflict', detail: backend || 'This was changed elsewhere. Refresh and try again.' };
    case 413: return { title: 'File too large', detail: 'The limit is 10 MB per file.' };
    case 422: return { title: 'Please check your input', detail: fields || backend };
    case 429: return { title: 'Too many requests', detail: 'Wait a moment and try again.' };
    default: return e.status >= 500
      ? { title: 'The server had a problem', detail: backend || 'Please try again shortly.' }
      : { title: backend || 'Request failed' };
  }
}
/** Backend answers with a company-related 400/403/404 when the user has not created or joined a company. */
export const isNoCompany = (e: unknown) => e instanceof ApiError && [400, 403, 404].includes(e.status) && /compan/i.test(e.message);
export function toastError(e: unknown, title?: string) {
  if (isNoCompany(e)) { toast.info('Join or create a company', 'Create a company, or ask an admin to add you, to use this page.'); return; }
  const x = explain(e);
  const same = !x.detail || x.detail.toLowerCase() === x.title.toLowerCase();
  toast.error(title ?? x.title, title ? (same ? x.title : `${x.title}: ${x.detail}`) : x.detail);
}
