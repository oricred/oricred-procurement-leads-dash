import axios from 'axios';
import type { Opportunity, Stage, RadarData, WatchlistItem, DashboardStats } from '../types';

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
};
