import { api } from './api-client';
import { toList } from './jobs';
import { invalidateSessionCache } from './auth';

export interface CompanyInput { name: string; industry?: string | null; website?: string | null; description?: string | null; location?: string | null }
export const getCompany = () => api<Record<string, unknown>>('/companies/me');
export const createCompany = async (b: CompanyInput) => {
  const res = await api<unknown>('/companies', { method: 'POST', body: JSON.stringify(b) });
  invalidateSessionCache();
  return res;
};
export const updateCompany = async (b: Partial<CompanyInput>) => {
  const res = await api<unknown>('/companies/me', { method: 'PUT', body: JSON.stringify(b) });
  invalidateSessionCache();
  return res;
};
export const listMembers = async () => toList<Record<string, unknown>>(await api<unknown>('/companies/me/members'), ['items', 'members']);
export const addMember = (email: string) => api<unknown>('/companies/me/members', { method: 'POST', body: JSON.stringify({ email }) });
export const removeMember = (id: string) => api<unknown>(`/companies/me/members/${id}`, { method: 'DELETE' });
/** Data Explorer only: removes all non-admin team members while preserving company administrators. */
export const removeAllMembers = () => api<Record<string, unknown>>('/companies/me/members', { method: 'DELETE' });
