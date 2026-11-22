import { redirect } from '@sveltejs/kit';
import { tokens } from '$lib/services/api-client';
import { getMe, getProfile, getAccess, getSessionCache, setSessionCache, invalidateSessionCache, type User } from '$lib/services/auth';

// UX guard only. The backend is the real authority on permissions and tenant isolation.
export const load = async () => {
  if (!tokens.hasSession()) {
    invalidateSessionCache();
    redirect(307, '/login');
  }
  const cached = getSessionCache();
  if (cached) return { user: cached.user, hasCompany: cached.hasCompany };
  try {
    const [me, profile, access] = await Promise.all([getMe(), getProfile().catch(() => ({})), getAccess().catch(() => null)]);
    const user: User = { ...me, ...profile };
    // Only claim "no company" when we positively know it; unknown stays quiet.
    const hasCompany = access ? !!access.company_access : user.company_id !== null;
    setSessionCache(user, hasCompany);
    return { user, hasCompany };
  } catch {
    invalidateSessionCache();
    tokens.clear();
    redirect(307, '/login');
  }
};
