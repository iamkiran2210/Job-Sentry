// Build-time public env (baked into the bundle). Works for `vite dev` and for static production builds.
import * as pub from '$env/static/public';
const env = pub as unknown as Record<string, string | undefined>;

/** The one place the backend URL is defined. Set PUBLIC_API_BASE_URL in .env (rebuild after changing). Empty string uses same-origin relative paths (/api/v1) via Nginx/Vite proxy. */
const rawBase = (env.PUBLIC_API_BASE_URL ?? 'http://localhost:8000').replace(/\/+$/, '');
const isLocalTarget = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(rawBase);
const isRemoteHost =
  typeof window !== 'undefined' &&
  window.location.hostname !== 'localhost' &&
  window.location.hostname !== '127.0.0.1';

export const API_BASE_URL = isLocalTarget && isRemoteHost ? '' : rawBase;
export const API_PREFIX = '/api/v1';

/** Same OAuth Web Client ID the backend verifies against (GOOGLE_CLIENT_ID). Public by design. */
export const GOOGLE_CLIENT_ID = env.PUBLIC_GOOGLE_CLIENT_ID ?? '';

/**
 * Scale of scores returned by the backend: 100 means 0-100 (default), 1 means 0-1.
 * Used to display scores correctly and to convert min/max score filters.
 */
export const SCORE_SCALE: 1 | 100 = Number(env.PUBLIC_SCORE_SCALE || '100') === 1 ? 1 : 100;
