import axios from 'axios';
import type { Opportunity, Stage, RadarData, WatchlistItem, DashboardStats, User, AuditEntry, PastDueEntry, Contact, AwardItem, TenderItem, HistoricalContact } from '../types';

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
  assignees: () => api.get<Array<{ id: string; name: string; email: string }>>('/auth/assignees'),
};

export const opportunities = {
  list: (stage?: Stage) =>
    api.get<{ items: Opportunity[]; total: number }>('/opportunities', {
      params: stage ? { stage } : {},
    }),
  get: (id: string) =>
    api.get<Opportunity>(`/opportunities/${id}`),
  transition: (id: string, body: { action: string; version: number; changed_by?: string; lost_reason?: string; credit_decision?: string; confirm?: boolean; conditions_checklist?: Array<Record<string, unknown>> }) =>
    api.post<Opportunity>(`/opportunities/${id}/transition`, body),  assign: (id: string, assignee: string) =>
    api.patch(`/opportunities/${id}/assign`, null, { params: { assignee } }),
  update: (id: string, body: { notes?: string; risk_flag?: string; assigned_to?: string }) =>
    api.patch<Opportunity>(`/opportunities/${id}`, body),
  findContact: (id: string) =>
    api.post<{ opportunity: Opportunity; contacts_added: number }>(`/opportunities/${id}/find-contact`),
  markContacted: (id: string, body: { version: number; contact_id?: string; note?: string; changed_by?: string }) =>
    api.post<Opportunity>(`/opportunities/${id}/mark-contacted`, body),
  getAudit: (id: string) =>
    api.get<AuditEntry[]>(`/opportunities/${id}/audit`),
};


export const leads = {
  list: (params?: Record<string, unknown>) =>
    api.get<{ items: Opportunity[]; total: number }>('/leads', { params }),
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
  getFailedApiCalls: (resolved?: boolean) =>
    api.get<{ items: Array<{ id: string; endpoint: string; method?: string; error: string; attempts: number; failed_at: string; resolved: boolean }> }>(
      '/admin/failed-api-calls',
      { params: resolved !== undefined ? { resolved } : {} },
    ),
  retryFailedApiCall: (callId: string) =>
    api.post<{ status: string; message: string }>(`/admin/failed-api-calls/${callId}/retry`),
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

export const pastDueQueue = {
  list: () => api.get<{ items: PastDueEntry[] }>('/past-due'),
};

export const funding = {
  compute: (opportunityId: string) =>
    api.post<{ funding_suitability: number }>(`/opportunities/${opportunityId}/compute-funding`),
  computePreference: (opportunityId: string) =>
    api.post<{ buyer_preference_score: number }>(`/opportunities/${opportunityId}/compute-preference`),
};

export const contacts = {
  listByCompany: (companyId: string) =>
    api.get<Contact[]>(`/companies/${companyId}/contacts`),
  createForCompany: (companyId: string, body: {
    first_name: string; last_name: string; email: string;
    job_title?: string; phone_direct?: string; phone_mobile?: string;
    linkedin_url?: string; is_primary?: boolean; notes?: string;
  }) => api.post<Contact>(`/companies/${companyId}/contacts`, body),
  listByOrganization: (orgId: string) =>
    api.get<Contact[]>(`/organizations/${orgId}/contacts`),
  createForOrganization: (orgId: string, body: {
    first_name: string; last_name: string; email: string;
    job_title?: string; phone_direct?: string; phone_mobile?: string;
    linkedin_url?: string; is_primary?: boolean; notes?: string;
  }) => api.post<Contact>(`/organizations/${orgId}/contacts`, body),
  listByOpportunity: (opportunityId: string) =>
    api.get<Contact[]>(`/opportunities/${opportunityId}/contacts`),
  update: (contactId: string, body: Partial<{
    first_name: string; last_name: string; email: string;
    job_title: string; phone_direct: string; phone_mobile: string;
    linkedin_url: string; is_primary: boolean; notes: string;
  }>) => api.patch<Contact>(`/contacts/${contactId}`, body),
  delete: (contactId: string) => api.delete(`/contacts/${contactId}`),
};

export const historicalContactsApi = {
  list: (params?: Record<string, unknown>) =>
    api.get<{ items: HistoricalContact[]; total: number }>('/historical-contacts', { params }),
};

export const awardsApi = {
  list: (params: Record<string, unknown>) =>
    api.get<{ items: AwardItem[]; total: number; page: number; page_size: number }>('/awards', { params }),
  createLead: (awardId: string) => api.post<Opportunity>(`/awards/${awardId}/lead`),
  exportUrl: (params: Record<string, string>) => `/api/awards/export?${new URLSearchParams(params).toString()}`,
};

export const tendersApi = {
  list: (params: Record<string, unknown>) =>
    api.get<{ items: TenderItem[]; total: number; page: number; page_size: number }>('/tenders', { params }),
  toggleWatch: (tenderId: string) =>
    api.post<{ is_watching: boolean }>('/watchlist/toggle', { tender_id: tenderId }),
  provinces: () =>
    api.get<string[]>('/tenders/provinces'),
};

export const organizationsApi = {
  list: () =>
    api.get<{ id: string; name: string }[]>('/organizations'),
};

export const categoriesApi = {
  list: () =>
    api.get<{ id: string; name: string }[]>('/categories'),
};

export const crmActivity = {
  get: (opportunityId: string) =>
    api.get<{ activities: Array<{ event: string; data: Record<string, unknown>; created_at: string }> }>(
      `/opportunities/${opportunityId}/crm-activity`
    ),
};
