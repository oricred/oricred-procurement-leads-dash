import axios from 'axios';
import type { Opportunity, Stage, RadarData, WatchlistItem, DashboardStats, User } from '../types';

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  },
);

export const auth = {
  login: (email: string, password: string) =>
    api.post<{ access_token: string }>('/auth/login', { email, password }),
  me: () => api.get<{ id: string; email: string; name: string; role: string }>('/auth/me'),
};

export const opportunities = {
  list: (stage?: Stage) =>
    api.get<{ items: Opportunity[]; total: number }>('/opportunities', {
      params: stage ? { stage } : {},
    }),
  get: (id: string) =>
    api.get<Opportunity>(`/opportunities/${id}`),
  updateStage: (id: string, stage: string, version: number, assignedTo?: string) =>
    api.patch<Opportunity>(`/opportunities/${id}/stage`, {
      stage,
      version,
      assigned_to: assignedTo,
    }),
  assign: (id: string, assignee: string) =>
    api.patch(`/opportunities/${id}/assign`, null, { params: { assignee } }),
};

export const radar = {
  get: () => api.get<RadarData>('/radar'),
};

export const watchlist = {
  list: () => api.get<{ items: WatchlistItem[]; total: number }>('/watchlist'),
};

export const dashboard = {
  stats: () => api.get<DashboardStats>('/dashboard/stats'),
};

export const admin = {
  getFilterConfig: () => api.get('/admin/filter-config'),
  updateFilterConfig: (config: Record<string, unknown>) =>
    api.put('/admin/filter-config', config),
  getSettings: () => api.get('/admin/settings'),
  getCredentials: () => api.get('/admin/credentials'),
  updateCredentials: (body: Record<string, string>) => api.put('/admin/credentials', body),
  getScrapers: () => api.get('/admin/sources'),
  updateScrapers: (body: Record<string, unknown>) => api.put('/admin/sources', body),
  getNotifications: () => api.get('/admin/notifications'),
  updateNotifications: (body: Record<string, unknown>) => api.put('/admin/notifications', body),
  getScoring: () => api.get('/admin/scoring'),
  updateScoring: (body: Record<string, unknown>) => api.put('/admin/scoring', body),
  getJobs: () => api.get('/admin/jobs'),
  updateJobs: (body: Record<string, unknown>) => api.put('/admin/jobs', body),
  getJobHistory: (limit = 50) => api.get('/admin/jobs/history', { params: { limit } }),
  triggerJob: (jobName: string) => api.post(`/admin/jobs/${jobName}/trigger`),
  listUsers: () => api.get<User[]>('/admin/users'),
  createUser: (body: { email: string; password: string; name: string; role: string }) =>
    api.post<User>('/admin/users', body),
  updateUser: (userId: string, body: Record<string, string>) =>
    api.put<User>(`/admin/users/${userId}`, body),
  deleteUser: (userId: string) => api.delete(`/admin/users/${userId}`),
};

export const buyerRelationships = {
  get: (opportunityId: string) =>
    api.get<{
      id: string;
      company_id: string;
      organization_id: string;
      award_count_12m: number;
      total_award_value_12m: number | null;
      avg_response_days: number | null;
      win_rate: number | null;
      relevance_score: number | null;
      updated_at: string;
    } | null>(`/opportunities/${opportunityId}/relationship`),
};

export const funding = {
  compute: (opportunityId: string) =>
    api.post<{ funding_suitability: number }>(`/opportunities/${opportunityId}/compute-funding`),
  computePreference: (opportunityId: string) =>
    api.post<{ buyer_preference_score: number }>(`/opportunities/${opportunityId}/compute-preference`),
};

export const crmActivity = {
  get: (opportunityId: string) =>
    api.get<{ activities: Array<{ event: string; data: Record<string, unknown>; created_at: string }> }>(
      `/opportunities/${opportunityId}/crm-activity`
    ),
};
