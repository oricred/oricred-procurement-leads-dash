import axios from 'axios';
import type { Opportunity, Stage, RadarData, WatchlistItem, DashboardStats, User, AuditEntry, PastDueEntry, Contact, AwardItem, TenderItem, HistoricalContact, StatsData } from '../types';

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
  // FastAPI reads a repeated query param as a list; axios would otherwise emit
  // `stage[]=…`, which it cannot parse.
  paramsSerializer: { indexes: null },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/**
 * Caches written by service-worker versions predating the H8 fix. Those held
 * every /api/ response, lead and contact records included. A returning user
 * still has one on disk until it is explicitly removed, so this runs at boot
 * rather than waiting for their next sign-out.
 */
const LEGACY_PII_CACHES = ['api-cache'];

export async function purgeLegacyCaches(): Promise<void> {
  if (!('caches' in window)) return;
  try {
    await Promise.all(LEGACY_PII_CACHES.map((name) => caches.delete(name)));
  } catch {
    // Best effort; nothing the user can act on.
  }
}

/**
 * Delete every service-worker cache holding API responses.
 *
 * Must run on both ways a session ends — the Sign out button and an expired
 * token — because Cache Storage is keyed by origin, not by user, and survives
 * logout on a shared machine.
 *
 * Best effort: Cache Storage is unavailable over plain HTTP and in some private
 * browsing modes, and a failure here must never block signing out.
 */
export async function clearApiCaches(): Promise<void> {
  if (!('caches' in window)) return;
  try {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k.startsWith('api-')).map((k) => caches.delete(k)));
  } catch {
    // Nothing actionable; the user is signing out either way.
  }
}

/**
 * Requests where a 401 is the answer to the question asked, not a dead session.
 *
 * Signing in with the wrong password *is* a 401. Treating it as an expired
 * session reloaded the page out from under the login form: the error rendered,
 * then clearApiCaches() settled a tick later and navigated, wiping the message
 * and the typed address before either could be read. The reported symptom was
 * "it says invalid, then the login page reloads" — and the reload is what made
 * the real cause impossible to see.
 */
const AUTHENTICATING_PATHS = ['/auth/login'];

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status !== 401) {
      return Promise.reject(error);
    }
    const url: string = error.config?.url ?? '';
    localStorage.removeItem('token');
    if (!AUTHENTICATING_PATHS.some((path) => url.includes(path))) {
      void clearApiCaches().finally(() => {
        // Already on the login page: navigating there again only discards
        // whatever the form is holding.
        if (window.location.pathname !== '/login') {
          window.location.href = '/login';
        }
      });
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
  list: (params?: Record<string, unknown>) =>
    api.get<{ items: Opportunity[]; total: number }>('/opportunities', {
      params,
    }),
  get: (id: string) =>
    api.get<Opportunity>(`/opportunities/${id}`),
  transition: (id: string, body: { action: string; version: number; changed_by?: string; lost_reason?: string; credit_decision?: string; confirm?: boolean; conditions_checklist?: Array<Record<string, unknown>> }) =>
    api.post<Opportunity>(`/opportunities/${id}/transition`, body),  assign: (id: string, assignee: string) =>
    api.patch(`/opportunities/${id}/assign`, null, { params: { assignee } }),
  update: (id: string, body: { notes?: string; risk_flag?: string; assigned_to?: string }) =>
    api.patch<Opportunity>(`/opportunities/${id}`, body),
  findContact: (id: string) =>
    api.post<{ opportunity: Opportunity; contacts_added: number; lookup_errors: number }>(`/opportunities/${id}/find-contact`),
  markContacted: (id: string, body: { version: number; contact_id?: string; note?: string; changed_by?: string }) =>
    api.post<Opportunity>(`/opportunities/${id}/mark-contacted`, body),
  getAudit: (id: string) =>
    api.get<AuditEntry[]>(`/opportunities/${id}/audit`),
};


export const leads = {
  list: (params?: Record<string, unknown>) =>
    api.get<{ items: Opportunity[]; total: number; page: number; page_size: number }>(
      '/leads',
      { params },
    ),
  export: (params?: Record<string, unknown>) =>
    api.get<Blob>('/leads/export', { params, responseType: 'blob' }),
  previewContactImport: (file: File) => {
    const data = new FormData();
    data.append('file', file);
    return api.post<LeadContactImportResult>('/leads/contact-import/preview', data, {
      headers: { 'Content-Type': undefined },
    });
  },
  applyContactImport: (file: File) => {
    const data = new FormData();
    data.append('file', file);
    return api.post<LeadContactImportResult>('/leads/contact-import/apply', data, {
      headers: { 'Content-Type': undefined },
    });
  },
};

export interface LeadContactImportResult {
  total_rows: number; creates: number; updates: number; skips: number; applied?: number;
  rows: Array<{ row: number; lead_id: string | null; company: string | null; action: 'create' | 'update' | 'skip'; message: string }>;
}

export const radar = {
  get: () => api.get<RadarData>('/radar'),
};

export const watchlist = {
  list: () => api.get<{ items: WatchlistItem[]; total: number }>('/watchlist'),
};
export const dashboard = {
  stats: () => api.get<DashboardStats>('/dashboard/stats'),
};

/**
 * Placeholder returned by GET /admin/credentials for any secret that is set.
 * Sending it back unchanged on PUT means "keep the stored value"; sending an
 * empty string clears the credential. Must match SECRET_SENTINEL in
 * backend/app/services/admin_config.py.
 */
export const SECRET_SENTINEL = '•'.repeat(12);

/**
 * Only what the Admin page actually calls.
 *
 * Client functions for the Filters, Sources, Notifications and Scoring tabs
 * were removed here when those tabs were dropped in a515055 — the endpoints
 * still exist, so add them back alongside a UI that uses them rather than
 * keeping callers-of-nothing around.
 */
export const admin = {
  getCredentials: () => api.get('/admin/credentials'),
  updateCredentials: (body: Record<string, string>) => api.put('/admin/credentials', body),
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

export const statsApi = {
  get: () => api.get<StatsData>('/stats'),
};

export const crmActivity = {
  get: (opportunityId: string) =>
    api.get<{ activities: Array<{ event: string; data: Record<string, unknown>; created_at: string }> }>(
      `/opportunities/${opportunityId}/crm-activity`
    ),
};
