import { api, tokens, ApiError } from './api-client';
import { invalidateDirectoryCache } from './directory';
import { invalidateJobsCache } from './jobs';
import { pageTitleStore } from '$lib/stores/page-title.svelte';
import { pipelineProgress } from '$lib/stores/pipeline-progress.svelte';

export interface User {
  id: string;
  name?: string;
  email: string;
  role: 'admin' | 'recruiter';
  is_active: boolean;
  company_id?: string | null;
}

interface TokenPair { access_token: string; refresh_token: string }

/**
 * The OpenAPI schema leaves login response untyped, so find the token pair defensively:
 * snake_case or camelCase, at the top level or nested one level (e.g. data.tokens).
 */
function extractTokens(payload: unknown): TokenPair {
  const pick = (o: unknown): TokenPair | null => {
    if (!o || typeof o !== 'object') return null;
    const r = o as Record<string, unknown>;
    const access = r.access_token ?? r.accessToken ?? r.access ?? r.token;
    const refresh = r.refresh_token ?? r.refreshToken ?? r.refresh;
    return typeof access === 'string' && typeof refresh === 'string' ? { access_token: access, refresh_token: refresh } : null;
  };
  const direct = pick(payload);
  if (direct) return direct;
  if (payload && typeof payload === 'object')
    for (const v of Object.values(payload)) { const nested = pick(v); if (nested) return nested; }
  const keys = payload && typeof payload === 'object' ? Object.keys(payload).join(', ') : typeof payload;
  throw new ApiError(0, `Login succeeded but no tokens were found in the response (keys: ${keys}). Update extractTokens in services/auth.ts.`);
}

const REFRESH_CACHE_TTL = 60_000;
let sessionCache: { user: User; hasCompany: boolean; ts: number } | null = null;
export function invalidateSessionCache() {
  sessionCache = null;
  invalidateJobsCache();
  invalidateDirectoryCache();
  pageTitleStore.clear();
}
export function getSessionCache() {
  return sessionCache && Date.now() - sessionCache.ts < REFRESH_CACHE_TTL ? sessionCache : null;
}
export function setSessionCache(user: User, hasCompany: boolean) {
  sessionCache = { user, hasCompany, ts: Date.now() };
}

function disableGoogleAutoSelect() {
  try {
    const g = (window as unknown as { google?: { accounts?: { id?: { disableAutoSelect?: () => void } } } }).google;
    g?.accounts?.id?.disableAutoSelect?.();
  } catch {
    /* ignore if GIS not loaded */
  }
}

export async function login(email: string, password: string): Promise<User> {
  invalidateSessionCache();
  const res = await api<unknown>('/auth/login', { method: 'POST', auth: false, body: JSON.stringify({ email, password }) });
  const t = extractTokens(res);
  tokens.set(t.access_token, t.refresh_token);
  return await verifySession();
}

/** Confirms the new token works, so a failure is attributed to the right step. */
async function verifySession(): Promise<User> {
  try { return await getMe(); }
  catch (e) { tokens.clear(); throw new ApiError(401, `Signed in, but the token was rejected by /auth/me. ${e instanceof Error ? e.message : ''}`); }
}

export const getMe = () => api<User>('/auth/me');

export async function logout(): Promise<void> {
  invalidateSessionCache();
  pipelineProgress.clearAll();
  disableGoogleAutoSelect();
  const refresh_token = tokens.refresh();
  try {
    if (refresh_token) await api('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token }) });
  } finally {
    tokens.clear();
    try { sessionStorage.clear(); } catch { /* ignore */ }
  }
}

export async function deleteAccount(): Promise<Record<string, unknown>> {
  const res = await api<Record<string, unknown>>('/users/me', { method: 'DELETE' });
  invalidateSessionCache();
  pipelineProgress.clearAll();
  disableGoogleAutoSelect();
  tokens.clear();
  try { sessionStorage.clear(); } catch { /* ignore */ }
  return res;
}

export const register = (name: string, email: string, password: string) =>
  api<unknown>('/auth/register', { method: 'POST', auth: false, body: JSON.stringify({ name, email, password }) });

/**
 * Google. `/auth/google` is for existing users; `/auth/sign/google` registers new recruiters (per the API reference).
 * The login button tries the first and falls back to the second when the account is not recognised.
 */
async function googleAuth(path: '/auth/google' | '/auth/sign/google', id_token: string): Promise<User> {
  invalidateSessionCache();
  const res = await api<unknown>(path, { method: 'POST', auth: false, body: JSON.stringify({ id_token }) });
  const t = extractTokens(res);
  tokens.set(t.access_token, t.refresh_token);
  return await verifySession();
}
export async function loginWithGoogle(id_token: string): Promise<User> {
  try { return await googleAuth('/auth/google', id_token); }
  catch (e) { if (e instanceof ApiError && [401, 403, 404, 409, 422].includes(e.status)) return await googleAuth('/auth/sign/google', id_token); else throw e; }
}
export const signUpWithGoogle = (id_token: string): Promise<User> => googleAuth('/auth/sign/google', id_token);

/** Admin-only: create another user. Backend enforces the role. */
export const registerUserAsAdmin = (name: string, email: string, password: string) =>
  api<unknown>('/auth/admin/register', { method: 'POST', body: JSON.stringify({ name, email, password }) });

export const getAccess = () => api<Record<string, unknown>>('/users/me/access');

export const adminCheck = () => api<{ is_admin?: boolean; role?: string; verified_at?: string }>('/users/admin/check');
export const getProfile = () => api<Partial<User>>('/users/me');
