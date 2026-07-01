import { useState, useEffect, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Key, SlidersHorizontal, Bell, Cpu, Users, Clock, AlertTriangle, Play, Trash2, Plus, Filter,
} from 'lucide-react';
import { admin } from '../services/api';
import type { User } from '../types';

const TABS = [
  { id: 'credentials', label: 'Credentials', icon: Key },
  { id: 'filter-config', label: 'Filter Config', icon: Filter },
  { id: 'scrapers', label: 'Scrapers', icon: Cpu },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'scoring', label: 'Scoring', icon: SlidersHorizontal },
  { id: 'jobs', label: 'Jobs', icon: Clock },
  { id: 'users', label: 'Users', icon: Users },
];

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState('credentials');
  return (
    <div className="max-w-5xl mx-auto">
      <h1 className="text-xl font-bold text-white mb-6">Admin</h1>
      <div className="flex gap-1 mb-6 flex-wrap border-b border-surface-300 pb-px">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium rounded-t-lg transition-colors ${
              activeTab === id
                ? 'bg-surface-300 text-primary-400 border border-b-0 border-surface-300'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>
      <div className="bg-surface-200 border border-surface-300 rounded-lg p-6">
        {activeTab === 'credentials' && <CredentialsTab />}
        {activeTab === 'filter-config' && <FilterConfigTab />}
        {activeTab === 'scrapers' && <ScrapersTab />}
        {activeTab === 'notifications' && <NotificationsTab />}
        {activeTab === 'scoring' && <ScoringTab />}
        {activeTab === 'jobs' && <JobsTab />}
        {activeTab === 'users' && <UsersTab />}
      </div>
    </div>
  );
}

// ── Credentials Tab ──

function CredentialsTab() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['admin-credentials'], queryFn: () => admin.getCredentials().then(r => r.data) });
  const [form, setForm] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => { if (data) setForm(data); }, [data]);

  const mutation = useMutation({
    mutationFn: (body: Record<string, string>) => admin.updateCredentials(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-credentials'] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutation.mutate(form);
  };

  if (isLoading) return <p className="text-gray-400">Loading...</p>;

  const secrets = ['api_key', 'password', 'secret'];
  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <h2 className="text-lg font-semibold text-white mb-4">API Credentials & SMTP</h2>
      {Object.entries(form).map(([key, value]) => (
        <div key={key}>
          <label className="block text-sm text-gray-300 mb-1">{key}</label>
          <input
            type={secrets.some(s => key.includes(s)) ? 'password' : 'text'}
            value={value}
            onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
            className="w-full bg-surface-300 border border-surface-400 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-primary-500"
          />
        </div>
      ))}
      <div className="flex items-center gap-3">
        <button type="submit" className="btn-primary px-4 py-2 rounded-lg text-sm" disabled={mutation.isPending}>
          {mutation.isPending ? 'Saving...' : 'Save'}
        </button>
        {saved && <span className="text-emerald-400 text-sm">Saved</span>}
        {mutation.isError && <span className="text-red-400 text-sm">Error saving</span>}
      </div>
    </form>
  );
}

// ── Filter Config Tab ──

const DEFAULT_FILTER_CONFIG = {
  min_award_value: 0,
  max_award_value: 50000000,
  min_days_since_award: 0,
  max_days_since_award: 60,
  provinces: [],
  categories: [],
  buyer_orgs: [],
  exclude_buyer_orgs: [],
  entity_types: ['provincial', 'municipal', 'national'],
  min_funding_suitability: 0,
  exclude_restricted_suppliers: true,
};

function FilterConfigTab() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['admin-filter-config'], queryFn: () => admin.getFilterConfig().then(r => r.data) });
  const [config, setConfig] = useState(DEFAULT_FILTER_CONFIG);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data?.value) setConfig({ ...DEFAULT_FILTER_CONFIG, ...data.value });
  }, [data]);

  const mutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => admin.updateFilterConfig(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-filter-config'] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutation.mutate(config);
  };

  if (isLoading) return <p className="text-gray-400">Loading...</p>;

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <h2 className="text-lg font-semibold text-white mb-4">Qualification Filters</h2>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm text-gray-300 mb-1">Min Award Value</label>
          <input type="number" value={config.min_award_value} onChange={e => setConfig(c => ({ ...c, min_award_value: +e.target.value }))} className="w-full bg-surface-300 border border-surface-400 rounded-lg px-3 py-2 text-sm text-white" />
        </div>
        <div>
          <label className="block text-sm text-gray-300 mb-1">Max Award Value</label>
          <input type="number" value={config.max_award_value} onChange={e => setConfig(c => ({ ...c, max_award_value: +e.target.value }))} className="w-full bg-surface-300 border border-surface-400 rounded-lg px-3 py-2 text-sm text-white" />
        </div>
        <div>
          <label className="block text-sm text-gray-300 mb-1">Min Days Since Award</label>
          <input type="number" value={config.min_days_since_award} onChange={e => setConfig(c => ({ ...c, min_days_since_award: +e.target.value }))} className="w-full bg-surface-300 border border-surface-400 rounded-lg px-3 py-2 text-sm text-white" />
        </div>
        <div>
          <label className="block text-sm text-gray-300 mb-1">Max Days Since Award</label>
          <input type="number" value={config.max_days_since_award} onChange={e => setConfig(c => ({ ...c, max_days_since_award: +e.target.value }))} className="w-full bg-surface-300 border border-surface-400 rounded-lg px-3 py-2 text-sm text-white" />
        </div>
      </div>
      <div>
        <label className="block text-sm text-gray-300 mb-1">Entity Types (comma-separated)</label>
        <input type="text" value={config.entity_types?.join(', ') || ''} onChange={e => setConfig(c => ({ ...c, entity_types: e.target.value.split(',').map(s => s.trim()).filter(Boolean) }))} className="w-full bg-surface-300 border border-surface-400 rounded-lg px-3 py-2 text-sm text-white" />
      </div>
      <div>
        <label className="flex items-center gap-2 text-sm text-gray-300">
          <input type="checkbox" checked={!!config.exclude_restricted_suppliers} onChange={e => setConfig(c => ({ ...c, exclude_restricted_suppliers: e.target.checked }))} className="rounded" />
          Exclude restricted suppliers
        </label>
      </div>
      <div>
        <label className="block text-sm text-gray-300 mb-1">Min Funding Suitability</label>
        <input type="number" min="0" max="1" step="0.05" value={config.min_funding_suitability} onChange={e => setConfig(c => ({ ...c, min_funding_suitability: +e.target.value }))} className="w-full bg-surface-300 border border-surface-400 rounded-lg px-3 py-2 text-sm text-white" />
      </div>
      <div className="flex items-center gap-3">
        <button type="submit" className="btn-primary px-4 py-2 rounded-lg text-sm" disabled={mutation.isPending}>
          {mutation.isPending ? 'Saving...' : 'Save'}
        </button>
        {saved && <span className="text-emerald-400 text-sm">Saved</span>}
        {mutation.isError && <span className="text-red-400 text-sm">Error saving</span>}
      </div>
    </form>
  );
}

// ── Scrapers Tab ──

function ScrapersTab() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['admin-scrapers'], queryFn: () => admin.getScrapers().then(r => r.data) });
  const [form, setForm] = useState<Record<string, unknown>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => { if (data) setForm(data); }, [data]);

  const mutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => admin.updateScrapers(body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['admin-scrapers'] }); setSaved(true); setTimeout(() => setSaved(false), 2000); },
  });

  const handleSubmit = (e: React.FormEvent) => { e.preventDefault(); mutation.mutate(form); };

  if (isLoading) return <p className="text-gray-400">Loading...</p>;

  const metros = form.metros as Record<string, { enabled: boolean; base_url: string; province: string; name: string }> | undefined;
  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <h2 className="text-lg font-semibold text-white mb-4">Municipal Scrapers</h2>
      {metros && Object.entries(metros).map(([key, metro]) => (
        <div key={key} className="p-4 bg-surface-300 rounded-lg space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium text-white">{metro.name}</label>
            <input
              type="checkbox"
              checked={metro.enabled}
              onChange={e => setForm(f => ({ ...f, metros: { ...metros, [key]: { ...metro, enabled: e.target.checked } } }))}
              className="rounded"
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs text-gray-400">Base URL</label>
              <input type="text" value={metro.base_url} onChange={e => setForm(f => ({ ...f, metros: { ...metros, [key]: { ...metro, base_url: e.target.value } } }))} className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white" />
            </div>
            <div>
              <label className="block text-xs text-gray-400">Province</label>
              <input type="text" value={metro.province} onChange={e => setForm(f => ({ ...f, metros: { ...metros, [key]: { ...metro, province: e.target.value } } }))} className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white" />
            </div>
          </div>
        </div>
      ))}
      <div className="flex items-center gap-3">
        <button type="submit" className="btn-primary px-4 py-2 rounded-lg text-sm" disabled={mutation.isPending}>
          {mutation.isPending ? 'Saving...' : 'Save'}
        </button>
        {saved && <span className="text-emerald-400 text-sm">Saved</span>}
        {mutation.isError && <span className="text-red-400 text-sm">Error saving</span>}
      </div>
    </form>
  );
}

// ── Notifications Tab ──

function NotificationsTab() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['admin-notifications'], queryFn: () => admin.getNotifications().then(r => r.data) });
  const [form, setForm] = useState<Record<string, unknown>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => { if (data) setForm(data); }, [data]);

  const mutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => admin.updateNotifications(body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['admin-notifications'] }); setSaved(true); setTimeout(() => setSaved(false), 2000); },
  });

  const handleSubmit = (e: React.FormEvent) => { e.preventDefault(); mutation.mutate(form); };

  if (isLoading) return <p className="text-gray-400">Loading...</p>;

  const events = form.events as Record<string, { enabled: boolean; subject: string }> | undefined;
  const recipients = (form.recipients as string[]) || [];
  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <h2 className="text-lg font-semibold text-white mb-4">Email Notifications</h2>
      <div>
        <label className="block text-sm text-gray-300 mb-1">Recipients (one per line)</label>
        <textarea
          value={recipients.join('\n')}
          onChange={e => setForm(f => ({ ...f, recipients: e.target.value.split('\n').map(s => s.trim()).filter(Boolean) }))}
          rows={3}
          className="w-full bg-surface-300 border border-surface-400 rounded-lg px-3 py-2 text-sm text-white"
        />
      </div>
      {events && Object.entries(events).map(([key, ev]) => (
        <div key={key} className="p-4 bg-surface-300 rounded-lg space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-white">{key}</span>
            <input type="checkbox" checked={ev.enabled} onChange={e => setForm(f => ({ ...f, events: { ...events, [key]: { ...ev, enabled: e.target.checked } } }))} className="rounded" />
          </div>
          <div>
            <label className="block text-xs text-gray-400">Subject</label>
            <input type="text" value={ev.subject} onChange={e => setForm(f => ({ ...f, events: { ...events, [key]: { ...ev, subject: e.target.value } } }))} className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white" />
          </div>
        </div>
      ))}
      <div className="flex items-center gap-3">
        <button type="submit" className="btn-primary px-4 py-2 rounded-lg text-sm" disabled={mutation.isPending}>
          {mutation.isPending ? 'Saving...' : 'Save'}
        </button>
        {saved && <span className="text-emerald-400 text-sm">Saved</span>}
        {mutation.isError && <span className="text-red-400 text-sm">Error saving</span>}
      </div>
    </form>
  );
}

// ── Scoring Tab ──

function ScoringTab() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['admin-scoring'], queryFn: () => admin.getScoring().then(r => r.data) });
  const [form, setForm] = useState<Record<string, unknown>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => { if (data) setForm(data); }, [data]);

  const mutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => admin.updateScoring(body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['admin-scoring'] }); setSaved(true); setTimeout(() => setSaved(false), 2000); },
  });

  const handleSubmit = (e: React.FormEvent) => { e.preventDefault(); mutation.mutate(form); };

  if (isLoading) return <p className="text-gray-400">Loading...</p>;

  const fundingWeights = form.funding_suitability as Record<string, number> | undefined;
  const buyerWeight = form.buyer_relationship as Record<string, number> | undefined;
  const buyerPref = form.buyer_preference as Record<string, unknown> | undefined;
  const provinceWeights = buyerPref?.province_weights as Record<string, number> | undefined;
  const preferredBuyers = (buyerPref?.preferred_buyers as string[]) || [];
  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <h2 className="text-lg font-semibold text-white mb-4">Scoring Weights</h2>
      {fundingWeights && (
        <div>
          <h3 className="text-sm font-medium text-gray-300 mb-3">Funding Suitability</h3>
          <div className="space-y-3">
            {Object.entries(fundingWeights).map(([key, val]) => (
              <div key={key}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-gray-300">{key}</span>
                  <span className="text-gray-400">{(val as number * 100).toFixed(0)}%</span>
                </div>
                <input
                  type="range" min="0" max="1" step="0.01" value={val as number}
                  onChange={e => setForm(f => ({ ...f, funding_suitability: { ...fundingWeights, [key]: +e.target.value } }))}
                  className="w-full"
                />
              </div>
            ))}
          </div>
        </div>
      )}
      {buyerWeight && (
        <div>
          <h3 className="text-sm font-medium text-gray-300 mb-3">Buyer Relationship</h3>
          <div className="space-y-3">
            {Object.entries(buyerWeight).map(([key, val]) => (
              <div key={key}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-gray-300">{key}</span>
                  <span className="text-gray-400">{val}%</span>
                </div>
                <input
                  type="range" min="0" max="100" step="1" value={val as number}
                  onChange={e => setForm(f => ({ ...f, buyer_relationship: { ...buyerWeight, [key]: +e.target.value } }))}
                  className="w-full"
                />
              </div>
            ))}
          </div>
        </div>
      )}
      {buyerPref && (
        <div className="border-t border-surface-300 pt-6">
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            Buyer Preference
            <label className="ml-3 text-xs text-gray-500">
              <input type="checkbox" checked={!!buyerPref.enabled} onChange={e => setForm(f => ({ ...f, buyer_preference: { ...buyerPref, enabled: e.target.checked } }))} className="mr-1.5 rounded" />
              Enabled
            </label>
          </h3>
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              {provinceWeights && Object.entries(provinceWeights).map(([prov, weight]) => (
                <div key={prov}>
                  <label className="block text-xs text-gray-400 mb-1 uppercase">{prov}</label>
                  <input
                    type="number" min="0" max="100" value={weight}
                    onChange={e => setForm(f => ({ ...f, buyer_preference: { ...buyerPref, province_weights: { ...provinceWeights, [prov]: +e.target.value } } }))}
                    className="w-full bg-surface-300 border border-surface-400 rounded px-2 py-1.5 text-sm text-white"
                  />
                </div>
              ))}
              <div>
                <label className="block text-xs text-gray-400 mb-1 uppercase">Default</label>
                <input
                  type="number" min="0" max="100" value={buyerPref.default_province_weight as number}
                  onChange={e => setForm(f => ({ ...f, buyer_preference: { ...buyerPref, default_province_weight: +e.target.value } }))}
                  className="w-full bg-surface-300 border border-surface-400 rounded px-2 py-1.5 text-sm text-white"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">SOE Bonus</label>
              <input
                type="number" min="0" max="100" value={buyerPref.soe_bonus as number}
                onChange={e => setForm(f => ({ ...f, buyer_preference: { ...buyerPref, soe_bonus: +e.target.value } }))}
                className="w-32 bg-surface-300 border border-surface-400 rounded px-2 py-1.5 text-sm text-white"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Preferred Buyers (one per line — name or org ID)</label>
              <textarea
                value={preferredBuyers.join('\n')}
                onChange={e => setForm(f => ({ ...f, buyer_preference: { ...buyerPref, preferred_buyers: e.target.value.split('\n').map(s => s.trim()).filter(Boolean) } }))}
                rows={3}
                className="w-full bg-surface-300 border border-surface-400 rounded-lg px-3 py-2 text-sm text-white"
                placeholder="Eskom&#10;Transnet&#10;SABC"
              />
            </div>
          </div>
        </div>
      )}
      <div className="flex items-center gap-3">
        <button type="submit" className="btn-primary px-4 py-2 rounded-lg text-sm" disabled={mutation.isPending}>
          {mutation.isPending ? 'Saving...' : 'Save'}
        </button>
        {saved && <span className="text-emerald-400 text-sm">Saved</span>}
        {mutation.isError && <span className="text-red-400 text-sm">Error saving</span>}
      </div>
    </form>
  );
}

// ── Jobs Tab ──

function JobsTab() {
  const queryClient = useQueryClient();
  const { data: config, isLoading } = useQuery({ queryKey: ['admin-jobs'], queryFn: () => admin.getJobs().then(r => r.data) });
  const { data: history } = useQuery({ queryKey: ['admin-job-history'], queryFn: () => admin.getJobHistory(20).then(r => r.data) });
  const [form, setForm] = useState<Record<string, unknown>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => { if (config) setForm(config); }, [config]);

  const saveMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => admin.updateJobs(body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['admin-jobs'] }); setSaved(true); setTimeout(() => setSaved(false), 2000); },
  });

  const triggerMutation = useMutation({
    mutationFn: (jobName: string) => admin.triggerJob(jobName),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-job-history'] }),
  });

  const jobs = form as Record<string, { enabled: boolean; cron: string; description: string }>;
  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-white mb-4">Scheduled Jobs</h2>
      {isLoading ? <p className="text-gray-400">Loading...</p> : (
        <form onSubmit={e => { e.preventDefault(); saveMutation.mutate(form); }} className="space-y-4">
          {Object.entries(jobs).map(([key, job]) => (
            <div key={key} className="p-4 bg-surface-300 rounded-lg flex items-center justify-between">
              <div className="flex-1 space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-white">{key}</span>
                  <span className="text-xs text-gray-400">{job.description}</span>
                </div>
                <div className="flex items-center gap-3">
                  <input
                    type="text" value={job.cron}
                    onChange={e => setForm(f => ({ ...f, [key]: { ...job, cron: e.target.value } }))}
                    className="w-40 bg-surface-200 border border-surface-400 rounded px-2 py-1 text-xs text-white font-mono"
                  />
                  <label className="flex items-center gap-1.5 text-xs text-gray-300">
                    <input type="checkbox" checked={job.enabled} onChange={e => setForm(f => ({ ...f, [key]: { ...job, enabled: e.target.checked } }))} className="rounded" />
                    Enabled
                  </label>
                  <button
                    type="button" onClick={() => triggerMutation.mutate(key)}
                    disabled={triggerMutation.isPending}
                    className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-primary-400 transition-colors"
                  >
                    <Play className="w-3 h-3" /> Run Now
                  </button>
                </div>
              </div>
            </div>
          ))}
          <div className="flex items-center gap-3">
            <button type="submit" className="btn-primary px-4 py-2 rounded-lg text-sm" disabled={saveMutation.isPending}>
              {saveMutation.isPending ? 'Saving...' : 'Save'}
            </button>
            {saved && <span className="text-emerald-400 text-sm">Saved</span>}
            {saveMutation.isError && <span className="text-red-400 text-sm">Error saving</span>}
          </div>
        </form>
      )}
      {history && (
        <div>
          <h3 className="text-sm font-medium text-gray-300 mb-3">Recent Runs</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-400 border-b border-surface-300">
                  <th className="pb-2 pr-4">Job</th>
                  <th className="pb-2 pr-4">Started</th>
                  <th className="pb-2 pr-4">Status</th>
                  <th className="pb-2 pr-4">Items</th>
                  <th className="pb-2">Error</th>
                </tr>
              </thead>
              <tbody>
                {history.items?.map((item: { id: string; job_name: string; started_at: string; status: string; items_processed: number | null; error: string | null }) => (
                  <tr key={item.id} className="border-b border-surface-300 text-gray-300">
                    <td className="py-2 pr-4">{item.job_name}</td>
                    <td className="py-2 pr-4 text-xs">{item.started_at ? new Date(item.started_at).toLocaleString() : '-'}</td>
                    <td className="py-2 pr-4">
                      <span className={`text-xs px-1.5 py-0.5 rounded ${item.status === 'success' ? 'bg-emerald-500/20 text-emerald-400' : item.status === 'running' ? 'bg-blue-500/20 text-blue-400' : 'bg-red-500/20 text-red-400'}`}>
                        {item.status}
                      </span>
                    </td>
                    <td className="py-2 pr-4">{item.items_processed ?? '-'}</td>
                    <td className="py-2 text-xs text-red-400 max-w-[200px] truncate">{item.error || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Users Tab ──

function UsersTab() {
  const queryClient = useQueryClient();
  const { data: users, isLoading } = useQuery({ queryKey: ['admin-users'], queryFn: () => admin.listUsers().then(r => r.data) });
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const createMutation = useMutation({
    mutationFn: (body: { email: string; password: string; name: string; role: string }) => admin.createUser(body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['admin-users'] }); setShowCreate(false); },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, string> }) => admin.updateUser(id, body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['admin-users'] }); setEditingId(null); setSaved(true); setTimeout(() => setSaved(false), 2000); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => admin.deleteUser(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-users'] }),
  });

  if (isLoading) return <p className="text-gray-400">Loading...</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Users</h2>
        <button onClick={() => setShowCreate(true)} className="flex items-center gap-1.5 text-sm text-primary-400 hover:text-primary-300">
          <Plus className="w-4 h-4" /> Add User
        </button>
      </div>

      {showCreate && (
        <UserForm
          onSave={(data) => createMutation.mutate(data)}
          onCancel={() => setShowCreate(false)}
          isPending={createMutation.isPending}
          error={createMutation.error ? 'Failed to create user' : null}
        />
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-400 border-b border-surface-300">
              <th className="pb-2 pr-4">Name</th>
              <th className="pb-2 pr-4">Email</th>
              <th className="pb-2 pr-4">Role</th>
              <th className="pb-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users?.map((user: User) => (
              <tr key={user.id} className="border-b border-surface-300 text-gray-300">
                {editingId === user.id ? (
                  <>
                    <td className="py-2 pr-4" colSpan={4}>
                      <InlineEditUser
                        user={user}
                        onSave={(body) => updateMutation.mutate({ id: user.id, body })}
                        onCancel={() => setEditingId(null)}
                      />
                    </td>
                  </>
                ) : (
                  <>
                    <td className="py-2 pr-4">{user.name}</td>
                    <td className="py-2 pr-4 text-xs">{user.email}</td>
                    <td className="py-2 pr-4">
                      <span className={`text-xs px-1.5 py-0.5 rounded ${user.role === 'admin' ? 'bg-purple-500/20 text-purple-400' : 'bg-blue-500/20 text-blue-400'}`}>
                        {user.role}
                      </span>
                    </td>
                    <td className="py-2 flex gap-2">
                      <button onClick={() => setEditingId(user.id)} className="text-xs text-primary-400 hover:text-primary-300">Edit</button>
                      <button onClick={() => { if (confirm('Delete user?')) deleteMutation.mutate(user.id); }} className="text-xs text-red-400 hover:text-red-300"><Trash2 className="w-3 h-3" /></button>
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {saved && <p className="text-emerald-400 text-sm">User updated</p>}
    </div>
  );
}

function UserForm({ onSave, onCancel, isPending, error, initial }: {
  onSave: (data: { email: string; password: string; name: string; role: string }) => void;
  onCancel: () => void;
  isPending: boolean;
  error: string | null;
  initial?: { email: string; name: string; role: string };
}) {
  const [email, setEmail] = useState(initial?.email || '');
  const [name, setName] = useState(initial?.name || '');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState(initial?.role || 'operator');
  return (
    <div className="p-4 bg-surface-300 rounded-lg space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-gray-400 mb-1">Name</label>
          <input type="text" value={name} onChange={e => setName(e.target.value)} className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white" />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Email</label>
          <input type="email" value={email} onChange={e => setEmail(e.target.value)} className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white" />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Password {initial ? '(leave blank to keep)' : ''}</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white" />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Role</label>
          <select value={role} onChange={e => setRole(e.target.value)} className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white">
            <option value="operator">Operator</option>
            <option value="admin">Admin</option>
            <option value="viewer">Viewer</option>
          </select>
        </div>
      </div>
      {error && <p className="text-red-400 text-xs">{error}</p>}
      <div className="flex gap-2">
        <button onClick={() => onSave({ email, name, password, role })} disabled={isPending} className="btn-primary px-3 py-1.5 rounded text-xs">
          {isPending ? 'Saving...' : 'Save'}
        </button>
        <button onClick={onCancel} className="text-xs text-gray-400 hover:text-gray-200">Cancel</button>
      </div>
    </div>
  );
}

function InlineEditUser({ user, onSave, onCancel }: {
  user: User;
  onSave: (body: Record<string, string>) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState({ name: user.name, email: user.email, role: user.role });
  return (
    <div className="flex items-center gap-2">
      <input type="text" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} className="w-32 bg-surface-200 border border-surface-400 rounded px-2 py-1 text-xs text-white" />
      <input type="text" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} className="w-40 bg-surface-200 border border-surface-400 rounded px-2 py-1 text-xs text-white" />
      <select value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))} className="bg-surface-200 border border-surface-400 rounded px-2 py-1 text-xs text-white">
        <option value="operator">Operator</option>
        <option value="admin">Admin</option>
        <option value="viewer">Viewer</option>
      </select>
      <button onClick={() => onSave(form)} className="text-xs text-emerald-400">Save</button>
      <button onClick={onCancel} className="text-xs text-gray-400">Cancel</button>
    </div>
  );
}
