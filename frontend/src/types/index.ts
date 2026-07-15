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
  supplier_company_id: string | null;
  supplier_resolved: boolean;
  lead_state: string;
  contact_readiness: string | null;
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

export interface HistoricalContact {
  id: string;
  company_id: string;
  company_name: string;
  registration_number: string | null;
  bee_level: number | null;
  first_award_date: string | null;
  last_award_date: string | null;
  total_award_count: number;
  total_award_value: number | null;
  last_award_id: string | null;
  contact_sufficiency: 'sufficient' | 'role_based' | 'none';
  primary_contact: Contact | null;
  contacts: Contact[];
  source: string;
  last_synced_at: string;
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
  lead_priority_score: number | null;
  lead_priority_reasons: string[];
  next_action: string | null;
  last_contact_lookup_at: string | null;
  contacted_at: string | null;
  credit_decision: string | null;
  lost_reason: string | null;
  conditions_checklist: Record<string, unknown>[];
  needs_enrichment: boolean;
  primary_contact: Contact | null;
  source_tender_title: string | null;
  source_award_date: string | null;
  source_award_value: number | null;
  related_bidders: { name: string; inferred: boolean; company_id?: string; resolved?: string; reason?: string }[] | null;
  contacts: Contact[];
  days_since_award: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  version: number;
}

export type Stage =
  | 'new_lead'
  | 'client_contacted'
  | 'qualified_lead'
  | 'lost_lead'
  | 'won_opportunity'
  | 'credit_preparation'
  | 'credit_review'
  | 'pre_approved'
  | 'conditions_precedent'
  | 'term_sheet_sent'
  | 'term_sheet_received'
  | 'contracts_sent'
  | 'contracts_received'
  | 'ready_to_rff'
  | 'funded';

export const STAGES: Stage[] = [
  'new_lead',
  'client_contacted',
  'qualified_lead',
  'lost_lead',
  'won_opportunity',
  'credit_preparation',
  'credit_review',
  'pre_approved',
  'conditions_precedent',
  'term_sheet_sent',
  'term_sheet_received',
  'contracts_sent',
  'contracts_received',
  'ready_to_rff',
  'funded',
];

export const STAGE_LABELS: Record<Stage, string> = {
  new_lead: 'New Lead',
  client_contacted: 'Client Contacted',
  qualified_lead: 'Qualified Lead',
  lost_lead: 'Lost Lead',
  won_opportunity: 'Won Opportunity',
  credit_preparation: 'Credit Prep',
  credit_review: 'Credit Review',
  pre_approved: 'Pre-Approved',
  conditions_precedent: 'Conditions Precedent',
  term_sheet_sent: 'Term Sheet Sent',
  term_sheet_received: 'Term Sheet Received',
  contracts_sent: 'Contracts Sent',
  contracts_received: 'Contracts Received',
  ready_to_rff: 'Ready to RFF',
  funded: 'Funded',
};

export const STAGE_COLORS: Record<Stage, string> = {
  new_lead: 'border-l-sky-500',
  client_contacted: 'border-l-blue-500',
  qualified_lead: 'border-l-violet-500',
  lost_lead: 'border-l-gray-500',
  won_opportunity: 'border-l-emerald-500',
  credit_preparation: 'border-l-amber-500',
  credit_review: 'border-l-orange-500',
  pre_approved: 'border-l-yellow-500',
  conditions_precedent: 'border-l-amber-500',
  term_sheet_sent: 'border-l-cyan-500',
  term_sheet_received: 'border-l-teal-500',
  contracts_sent: 'border-l-indigo-500',
  contracts_received: 'border-l-purple-500',
  ready_to_rff: 'border-l-pink-500',
  funded: 'border-l-emerald-500',
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



