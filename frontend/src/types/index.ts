export interface AwardItem {
  id: string;
  supplier_name: string;
  buyer_org_id: string | null;
  buyer_org_name: string | null;
  tender_title: string | null;
  amount: number | null;
  award_date: string | null;
  bee_level: number | null;
  source: string;
  opportunity_id: string | null;
}

export interface TenderItem {
  id: string;
  title: string | null;
  estimated_value: number | null;
  province: string | null;
  category_id: string | null;
  category_name: string | null;
  buyer_org_id: string | null;
  buyer_org_name: string | null;
  closing_date: string | null;
  published_at: string | null;
  tender_type: string | null;
  discovered_at: string | null;
  status: 'not_watched' | 'watching' | 'awarded' | 'past_due' | 'opportunity';
  is_watching: boolean;
  opportunity_id: string | null;
}

export interface Contact {
  id: string;
  company_id: string | null;
  organization_id: string | null;
  first_name: string;
  last_name: string;
  job_title: string | null;
  email: string;
  phone_direct: string | null;
  phone_mobile: string | null;
  linkedin_url: string | null;
  is_primary: boolean;
  notes: string | null;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface Opportunity {
  id: string;
  tender_id: string | null;
  award_id: string | null;
  company_id: string | null;
  company_name: string | null;
  award_value: number | null;
  buyer_org: string | null;
  province: string | null;
  category: string | null;
  kanban_stage: Stage;
  assigned_to: string | null;
  contact_sufficiency: 'sufficient' | 'role_based' | 'none' | null;
  risk_flag: 'red' | 'amber' | 'green' | null;
  win_probability: number | null;
  funding_suitability: number | null;
  buyer_preference_score: number | null;
  related_bidders: { name: string; inferred: boolean; company_id?: string; resolved?: string; reason?: string }[] | null;
  contacts: Contact[];
  days_since_award: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  version: number;
}

export type Stage =
  | 'new'
  | 'assigned'
  | 'contacted'
  | 'in_discussion'
  | 'application_received'
  | 'funded'
  | 'closed';

export const STAGES: Stage[] = [
  'new',
  'assigned',
  'contacted',
  'in_discussion',
  'application_received',
  'funded',
  'closed',
];

export const STAGE_LABELS: Record<Stage, string> = {
  new: 'New',
  assigned: 'Assigned',
  contacted: 'Contacted',
  in_discussion: 'In Discussion',
  application_received: 'Application Received',
  funded: 'Funded',
  closed: 'Closed',
};

export const STAGE_COLORS: Record<Stage, string> = {
  new: 'border-l-blue-500',
  assigned: 'border-l-yellow-500',
  contacted: 'border-l-orange-500',
  in_discussion: 'border-l-purple-500',
  application_received: 'border-l-pink-500',
  funded: 'border-l-emerald-500',
  closed: 'border-l-gray-500',
};

export interface RadarAward {
  id: string;
  tender_title: string;
  supplier_name: string;
  amount: number | null;
  award_date: string | null;
  buyer_org: string | null;
  passed_filter: boolean;
}

export interface RadarData {
  awards: RadarAward[];
  past_due_count: number;
}

export interface WatchlistItem {
  id: string;
  tender_id: string;
  title: string;
  estimated_value: number | null;
  category: string | null;
  province: string | null;
  buyer_org: string | null;
  status: string;
  expected_window_start: string | null;
  expected_window_end: string | null;
  closing_date: string | null;
  days_until_window: number | null;
  days_overdue: number | null;
  progress_pct: number | null;
  label: string;
  opportunity_id: string | null;
  opportunity_count: number;
}

export interface DashboardStats {
  stages: { stage: string; count: number }[];
  total_opportunities: number;
  total_watching: number;
  past_due_count: number;
}

export interface AuditEntry {
  id: string;
  from_stage: string | null;
  to_stage: string;
  changed_by: string;
  changed_at: string;
}

export interface PastDueEntry {
  id: string;
  tender_id: string;
  tender_title: string;
  estimated_value: number | null;
  province: string | null;
  buyer_org: string | null;
  entered_queue_at: string;
  poll_count_since_due: number;
  resolution: string;
  days_in_queue: number;
}

export interface User {
  id: string;
  email: string;
  name: string;
  role: string;
}
