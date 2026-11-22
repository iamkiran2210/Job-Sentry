import { api, upload } from './api-client';
import { findStr } from '$lib/utils';
import { invalidateDirectoryCache } from './directory';

export const uploadResume = async (jobId: string, file: File, onProgress: (p: number) => void) => {
  const res = await upload<unknown>(`/jobs/${jobId}/resumes`, file, onProgress);
  invalidateDirectoryCache();
  return res;
};
/** Response shape is untyped; find the resume id wherever it is. */
export const resumeIdFrom = (res: unknown) => findStr(res, ['resume_id', 'id']);
export const resumeStatus = (id: string) => api<Record<string, unknown>>(`/resumes/${id}/status`);
export const getResume = (id: string) => api<Record<string, unknown>>(`/resumes/${id}`);
export const retryResume = (id: string) => api<unknown>(`/resumes/${id}/retry`, { method: 'POST' });
export const deleteResume = async (id: string) => {
  const res = await api<Record<string, unknown>>(`/resumes/${id}`, { method: 'DELETE' });
  invalidateDirectoryCache();
  return res;
};
