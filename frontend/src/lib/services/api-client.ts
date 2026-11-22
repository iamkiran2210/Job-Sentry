import { API_BASE_URL, API_PREFIX } from '$lib/config';
import { goto } from '$app/navigation';
import { toast } from '$lib/stores/toast.svelte';

/** Backend envelope: { success, message, data, errors } (see backend README). */
export interface ApiEnvelope<T> {
  success: boolean;
  message: string;
  data: T | null;
  errors?: unknown;
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public errors?: unknown) {
    super(message);
  }
}

const REFRESH_KEY = 'js_refresh_token';
let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;

export const tokens = {
  hasSession: () => !!accessToken || !!sessionStorage.getItem(REFRESH_KEY),
  set(access: string, refresh: string) {
    accessToken = access;
    sessionStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    accessToken = null;
    sessionStorage.removeItem(REFRESH_KEY);
  },
  refresh: () => sessionStorage.getItem(REFRESH_KEY)
};

async function raw(path: string, init: RequestInit & { auth?: boolean } = {}) {
  const headers = new Headers(init.headers);
  if (typeof init.body === 'string' && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (init.auth !== false && accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
  return fetch(`${API_BASE_URL}${API_PREFIX}${path}`, { ...init, headers });
}

async function tryRefresh(): Promise<boolean> {
  const rt = tokens.refresh();
  if (!rt) return false;
  refreshing ??= (async () => {
    try {
      const res = await raw('/auth/refresh', { method: 'POST', auth: false, body: JSON.stringify({ refresh_token: rt }) });
      if (!res.ok) return false;
      const body = (await res.json()) as ApiEnvelope<{ access_token: string; refresh_token: string }>;
      if (!body.data) return false;
      tokens.set(body.data.access_token, body.data.refresh_token);
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

export async function api<T>(path: string, init: RequestInit & { auth?: boolean } = {}): Promise<T> {
  let res: Response;
  try {
    res = await raw(path, init);
    if (res.status === 401 && init.auth !== false && (await tryRefresh())) res = await raw(path, init);
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Check your connection and PUBLIC_API_BASE_URL.');
  }
  const body = (await res.json().catch(() => null)) as ApiEnvelope<T> | null;
  if (!res.ok || body?.success === false) {
    if (res.status === 401 && init.auth !== false) {
      tokens.clear();
      if (typeof location !== 'undefined' && !location.pathname.startsWith('/login')) { toast.info('Your session has ended', 'Please sign in again.'); goto('/login'); }
    }
    throw new ApiError(res.status, body?.message ?? 'Request failed', body?.errors);
  }
  return (body?.data ?? (body as unknown)) as T;
}

/** Upload one file with real progress (fetch cannot report upload progress). Field name is `files` per OpenAPI. */
export function upload<T>(path: string, file: File, onProgress: (pct: number) => void): Promise<T> {
  const send = () =>
    new Promise<{ status: number; body: ApiEnvelope<T> | null }>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API_BASE_URL}${API_PREFIX}${path}`);
      if (accessToken) xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
      xhr.onerror = () => reject(new ApiError(0, 'Cannot reach the server.'));
      xhr.onload = () => { let body = null; try { body = JSON.parse(xhr.responseText); } catch { /* non-JSON */ } resolve({ status: xhr.status, body }); };
      const fd = new FormData();
      fd.append('files', file);
      xhr.send(fd);
    });
  return (async () => {
    let r = await send();
    if (r.status === 401 && (await tryRefresh())) r = await send();
    if (r.status < 200 || r.status >= 300 || r.body?.success === false)
      throw new ApiError(r.status, r.body?.message ?? 'Upload failed', r.body?.errors);
    return (r.body?.data ?? r.body) as T;
  })();
}

/** Root-level health endpoints live outside /api/v1. */
export async function health(path: '/health' | '/ready'): Promise<boolean> {
  try { return (await fetch(`${API_BASE_URL}${path}`)).ok; } catch { return false; }
}
