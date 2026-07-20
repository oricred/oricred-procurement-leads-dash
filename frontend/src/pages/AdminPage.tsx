import { useState, useEffect, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Key, SlidersHorizontal, Bell, Database, Users, Clock, AlertTriangle, Play, Trash2, Plus, Filter, RefreshCw,
} from 'lucide-react';
import { admin } from '../services/api';
import type { User } from '../types';

const TABS = [
  { id: 'credentials', label: 'Credentials', icon: Key },
  { id: 'filter-config', label: 'Filter Config', icon: Filter },
  { id: 'sources', label: 'Sources', icon: Database },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'scoring', label: 'Scoring', icon: SlidersHorizontal },
  { id: 'jobs', label: 'Jobs', icon: Clock },
  { id: 'users', label: 'Users', icon: Users },
  { id: 'failed-api-calls', label: 'Dead Letter', icon: AlertTriangle },
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
        {activeTab === 'sources' && <SourcesTab />}
        {activeTab === 'notifications' && <NotificationsTab />}
        {activeTab === 'scoring' && <ScoringTab />}
        {activeTab === 'jobs' && <JobsTab />}
        {activeTab === 'users' && <UsersTab />}
        {activeTab === 'failed-api-calls' && <FailedApiCallsTab />}
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
  const mondayFields = ['monday_api_key', 'monday_board_id', 'monday_group_id'];
  const tsaFields = ['tsa_api_key', 'tsa_base_url'];
  const smtpFields = ['smtp_host', 'smtp_port', 'smtp_user', 'smtp_password', 'email_from'];

  function fieldGroup(label: string, keys: string[]) {
    return (
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide">{label}</h3>
        {keys.map(key => form[key] !== undefined && (
          <div key={key}>
            <label className="block text-sm text-gray-300 mb-1">{key}</label>
            <input
              type={secrets.some(s => key.includes(s)) ? 'password' : 'text'}
              value={form[key] as string}
              onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
              className="w-full bg-surface-300 border border-surface-400 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-primary-500"
            />
          </div>
        ))}
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {fieldGroup('Tenders-SA API', tsaFields)}
      <div className="border-t border-surface-300 pt-4">
        {fieldGroup('Monday.com CRM', mondayFields)}
      </div>
      <div className="border-t border-surface-300 pt-4">
        {fieldGroup('SMTP / Email', smtpFields)}
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

// ── Filter Config Tab ──

const ALL_PROVINCES = [
  { value: 'gp', label: 'GP (Gauteng)' },
  { value: 'wc', label: 'WC (Western Cape)' },
  { value: 'kzn', label: 'KZN (KwaZulu-Natal)' },
  { value: 'ec', label: 'EC (Eastern Cape)' },
  { value: 'mp', label: 'MP (Mpumalanga)' },
  { value: 'lp', label: 'LP (Limpopo)' },
  { value: 'nw', label: 'NW (North West)' },
  { value: 'fs', label: 'FS (Free State)' },
  { value: 'nc', label: 'NC (Northern Cape)' },
];

const ALL_ENTITY_TYPES = [
  { value: 'national', label: 'National' },
  { value: 'provincial', label: 'Provincial' },
  { value: 'soe', label: 'SOE' },
  { value: 'municipal', label: 'Municipal' },
];

const ALL_CATEGORIES = [
  { value: 'construction', label: 'Construction' },
  { value: 'infrastructure', label: 'Infrastructure' },
  { value: 'it-services', label: 'IT Services' },
  { value: 'consulting', label: 'Consulting' },
  { value: 'security-guarding', label: 'Security Guarding' },
  { value: 'cleaning', label: 'Cleaning' },
  { value: 'catering', label: 'Catering' },
  { value: 'facilities-management', label: 'Facilities Management' },
];

function ChipSelector({ label, available, selected, onChange }: {
  label: string;
  available: { value: string; label: string }[];
  selected: string[];
  onChange: (values: string[]) => void;
}) {
  const [showAdd, setShowAdd] = useState(false);
  const [custom, setCustom] = useState('');

  function toggle(val: string) {
    if (selected.includes(val)) {
      onChange(selected.filter(v => v !== val));
    } else {
      onChange([...selected, val]);
    }
  }

  function addCustom() {
    const v = custom.trim().toLowerCase();
    if (v && !selected.includes(v)) {
      onChange([...selected, v]);
    }
    setCustom('');
    setShowAdd(false);
  }

  return (
    <div>
      <label className="block text-xs text-gray-400 mb-1.5">{label}</label>
      <div className="flex flex-wrap gap-1.5 mb-1.5">
        {available.map(a => {
          const on = selected.includes(a.value);
          return (
            <button
              key={a.value}
              type="button"
              onClick={() => toggle(a.value)}
              className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                on
                  ? 'bg-primary-500/20 border-primary-500/40 text-primary-300'
                  : 'bg-surface-300 border-surface-400 text-gray-400 hover:text-gray-300'
              }`}
            >
              {a.label}
            </button>
          );
        })}
        {selected.filter(v => !available.find(a => a.value === v)).map(v => (
          <button
            key={v}
            type="button"
            onClick={() => toggle(v)}
            className="text-xs px-2.5 py-1 rounded-full border bg-amber-500/20 border-amber-500/40 text-amber-300"
          >
            {v} <span className="ml-1">&times;</span>
          </button>
        ))}
      </div>
      {showAdd ? (
        <div className="flex gap-1.5">
          <input
            type="text"
            value={custom}
            onChange={e => setCustom(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addCustom())}
            placeholder="Type and press Enter"
            className="flex-1 bg-surface-300 border border-surface-400 rounded px-2 py-1 text-xs text-white placeholder-gray-500"
            autoFocus
          />
          <button type="button" onClick={addCustom} className="text-xs text-primary-400 hover:text-primary-300">Add</button>
          <button type="button" onClick={() => setShowAdd(false)} className="text-xs text-gray-500">Cancel</button>
        </div>
      ) : (
        <button type="button" onClick={() => setShowAdd(true)} className="text-xs text-gray-500 hover:text-gray-300">
          + Add custom
        </button>
      )}
    </div>
  );
}

function FilterCard({ title, enabled, onToggle, children }: {
  title: string;
  enabled: boolean;
  onToggle: (v: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <div className="p-4 bg-surface-300 rounded-lg space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-white">{title}</h3>
        <label className="relative inline-flex items-center cursor-pointer">
          <input type="checkbox" checked={enabled} onChange={e => onToggle(e.target.checked)} className="sr-only peer" />
          <div className="w-9 h-5 bg-surface-400 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-primary-600" />
        </label>
      </div>
      {enabled && children}
    </div>
  );
}

function FilterConfigTab() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['admin-filter-config'], queryFn: () => admin.getFilterConfig().then(r => r.data) });
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data?.value) setConfig(data.value);
  }, [data]);

  const mutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => admin.updateFilterConfig(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-filter-config'] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  function getSection(section: string): Record<string, unknown> {
    return (config[section] as Record<string, unknown>) || {};
  }

  function getRule(section: string): Record<string, unknown> {
    const rules = getSection(section).rules as Record<string, unknown>[] | undefined;
    return rules?.[0] || {};
  }

  function updateSection(section: string, patch: Record<string, unknown>) {
    setConfig(c => ({ ...c, [section]: { ...(c[section] as object || {}), ...patch } }));
  }

  function updateRule(section: string, patch: Record<string, unknown>) {
    const sectionObj = getSection(section);
    const rules = (sectionObj.rules as Record<string, unknown>[]) || [{}];
    const newRules = [{ ...rules[0], ...patch }];
    setConfig(c => ({ ...c, [section]: { ...sectionObj, rules: newRules } }));
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutation.mutate(config);
  };

  if (isLoading) return <p className="text-gray-400">Loading...</p>;

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <h2 className="text-lg font-semibold text-white mb-4">Qualification Filters</h2>
      <p className="text-xs text-gray-500 -mt-3 mb-2">Toggle each filter on/off. Tenders that fail any enabled filter are excluded from opportunities.</p>

      {/* Value Range */}
      <FilterCard title="Value Range" enabled={!!getSection('value_range').enabled} onToggle={v => updateSection('value_range', { enabled: v })}>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-gray-400 mb-1">Min estimated value (R)</label>
            <input type="number" value={getRule('value_range').min as number ?? ''} onChange={e => updateRule('value_range', { min: e.target.value ? +e.target.value : null })} className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white" placeholder="500000" />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Max estimated value (R)</label>
            <input type="number" value={getRule('value_range').max as number ?? ''} onChange={e => updateRule('value_range', { max: e.target.value ? +e.target.value : null })} className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white" placeholder="No max" />
          </div>
        </div>
      </FilterCard>

      {/* Sector */}
      <FilterCard title="Sector / Category" enabled={!!getSection('sector').enabled} onToggle={v => updateSection('sector', { enabled: v })}>
        {(() => {
          const rules = (getSection('sector').rules as Record<string, unknown>[]) || [];
          const includeRule = rules.find(r => r.type === 'include');
          const excludeRule = rules.find(r => r.type === 'exclude');
          return (
            <div className="space-y-3">
              <ChipSelector
                label="Include categories"
                available={ALL_CATEGORIES}
                selected={(includeRule?.values as string[]) || []}
                onChange={vals => {
                  const newRules = rules.filter(r => r.type !== 'include');
                  if (vals.length) newRules.push({ type: 'include', values: vals, field: 'category_id' });
                  updateSection('sector', { rules: newRules });
                }}
              />
              <ChipSelector
                label="Exclude categories"
                available={ALL_CATEGORIES}
                selected={(excludeRule?.values as string[]) || []}
                onChange={vals => {
                  const newRules = rules.filter(r => r.type !== 'exclude');
                  if (vals.length) newRules.push({ type: 'exclude', values: vals, field: 'category_id' });
                  updateSection('sector', { rules: newRules });
                }}
              />
            </div>
          );
        })()}
      </FilterCard>

      {/* Province */}
      <FilterCard title="Province" enabled={!!getSection('province').enabled} onToggle={v => updateSection('province', { enabled: v })}>
        {(() => {
          const rule = getRule('province');
          const vals = (rule.values as string[]) || [];
          return (
            <ChipSelector
              label="Allowed provinces"
              available={ALL_PROVINCES}
              selected={vals}
              onChange={vals => updateRule('province', { type: 'include', values: vals })}
            />
          );
        })()}
      </FilterCard>

      {/* Entity Type */}
      <FilterCard title="Entity Type" enabled={!!getSection('entity_type').enabled} onToggle={v => updateSection('entity_type', { enabled: v })}>
        {(() => {
          const rule = getRule('entity_type');
          const vals = (rule.values as string[]) || [];
          return (
            <ChipSelector
              label="Allowed buyer entity types"
              available={ALL_ENTITY_TYPES}
              selected={vals}
              onChange={vals => updateRule('entity_type', { type: 'include', values: vals })}
            />
          );
        })()}
      </FilterCard>

      {/* BEE Level */}
      <FilterCard title="BEE Level" enabled={!!getSection('bee_level').enabled} onToggle={v => updateSection('bee_level', { enabled: v })}>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs text-gray-400 mb-1">Min level (1 = best)</label>
            <input type="number" min="1" max="4" value={getRule('bee_level').min_level as number ?? ''} onChange={e => updateRule('bee_level', { min_level: e.target.value ? +e.target.value : null })} className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white" />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Max level</label>
            <input type="number" min="1" max="4" value={getRule('bee_level').max_level as number ?? ''} onChange={e => updateRule('bee_level', { max_level: e.target.value ? +e.target.value : null })} className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white" />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Min BEE points</label>
            <input type="number" min="0" max="100" value={getRule('bee_level').min_points as number ?? ''} onChange={e => updateRule('bee_level', { min_points: e.target.value ? +e.target.value : null })} className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white" />
          </div>
        </div>
      </FilterCard>

      {/* Risk Exclusion */}
      <FilterCard title="Risk Exclusion" enabled={!!getSection('risk_exclusion').enabled} onToggle={v => updateSection('risk_exclusion', { enabled: v })}>
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm text-gray-300">
            <input
              type="checkbox"
              checked={!!getRule('risk_exclusion').exclude_if_restricted}
              onChange={e => updateRule('risk_exclusion', { exclude_if_restricted: e.target.checked })}
              className="rounded"
            />
            Exclude restricted suppliers
          </label>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Max forensic risk score (0–100)</label>
            <input
              type="number" min="0" max="100" value={getRule('risk_exclusion').max_forensic_score as number ?? ''}
              onChange={e => updateRule('risk_exclusion', { max_forensic_score: e.target.value ? +e.target.value : null })}
              className="w-32 bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white"
            />
          </div>
        </div>
      </FilterCard>

      {/* Preference */}
      <FilterCard title="Buyer Preference" enabled={!!getSection('preference').enabled} onToggle={v => updateSection('preference', { enabled: v })}>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Min preference score (0–100)</label>
          <input
            type="number" min="0" max="100" value={getRule('preference').min_score as number ?? ''}
            onChange={e => updateRule('preference', { min_score: e.target.value ? +e.target.value : null })}
            className="w-32 bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white"
          />
        </div>
      </FilterCard>

      <div className="flex items-center gap-3 pt-2">
        <button type="submit" className="btn-primary px-4 py-2 rounded-lg text-sm" disabled={mutation.isPending}>
          {mutation.isPending ? 'Saving...' : 'Save Filters'}
        </button>
        {saved && <span className="text-emerald-400 text-sm">Saved</span>}
        {mutation.isError && <span className="text-red-400 text-sm">Error saving</span>}
      </div>
    </form>
  );
}

// ── Sources Tab ──

function SourcesTab() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['admin-sources'], queryFn: () => admin.getSources().then(r => r.data) });
  const [form, setForm] = useState<Record<string, unknown>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => { if (data) setForm(data); }, [data]);

  const mutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => admin.updateSources(body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['admin-sources'] }); setSaved(true); setTimeout(() => setSaved(false), 2000); },
  });

  const handleSubmit = (e: React.FormEvent) => { e.preventDefault(); mutation.mutate(form); };

  if (isLoading) return <p className="text-gray-400">Loading...</p>;

  const metros = form.metros as Record<string, { enabled: boolean; base_url: string; province: string; name: string }> | undefined;
  const apiSources = form.api_sources as Record<string, { enabled: boolean; base_url: string; api_key: string; name: string }> | undefined;
  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <h2 className="text-lg font-semibold text-white mb-4">Data Sources</h2>

      <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide">Municipal Portals</h3>
      <p className="text-xs text-gray-500">Only sources with a maintained ingestion adapter can be enabled.</p>
      {metros && Object.entries(metros).filter(([key]) => ['joburg', 'capetown'].includes(key)).map(([key, metro]) => (
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

      <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide mt-6">API Sources</h3>
      <p className="text-xs text-gray-500">Tenders-SA is ingested through the configured direct database connection. Additional API adapters are not exposed until implemented.</p>
      {apiSources && Object.entries(apiSources).filter(() => false).map(([key, src]) => (
        <div key={key} className="p-4 bg-surface-300 rounded-lg space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium text-white">{src.name}</label>
            <input
              type="checkbox"
              checked={src.enabled}
              onChange={e => setForm(f => ({ ...f, api_sources: { ...apiSources, [key]: { ...src, enabled: e.target.checked } } }))}
              className="rounded"
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs text-gray-400">Base URL</label>
              <input type="text" value={src.base_url} onChange={e => setForm(f => ({ ...f, api_sources: { ...apiSources, [key]: { ...src, base_url: e.target.value } } }))} className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white" />
            </div>
            <div>
              <label className="block text-xs text-gray-400">API Key</label>
              <input type="password" value={src.api_key} onChange={e => setForm(f => ({ ...f, api_sources: { ...apiSources, [key]: { ...src, api_key: e.target.value } } }))} className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white" />
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
              <div className="mt-3">
                <label className="block text-xs text-gray-400 mb-1">Min Preference Score (tenders below this are filtered out)</label>
                <input
                  type="number" min="0" max="100" value={buyerPref.min_preference_score as number}
                  onChange={e => setForm(f => ({ ...f, buyer_preference: { ...buyerPref, min_preference_score: +e.target.value } }))}
                  className="w-32 bg-surface-300 border border-surface-400 rounded px-2 py-1.5 text-sm text-white"
                />
              </div>
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-job-history'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
  });

  const jobs = form as Record<string, { enabled: boolean; cron: string; description: string }>;
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">Scheduled Jobs</h2>
          <p className="text-xs text-gray-500 mt-1">Manually run critical ingestion jobs or adjust their schedules.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => triggerMutation.mutate('check_awards')}
            disabled={triggerMutation.isPending}
            className="btn-primary px-3 py-2 rounded-lg text-sm inline-flex items-center gap-2"
          >
            <Play className="w-4 h-4" />
            {triggerMutation.isPending ? 'Running...' : 'Ingest Awards Now'}
          </button>
          <button
            type="button"
            onClick={() => triggerMutation.mutate('historical_contacts')}
            disabled={triggerMutation.isPending}
            className="px-3 py-2 rounded-lg text-sm inline-flex items-center gap-2 bg-surface-300 text-gray-300 hover:text-white hover:bg-surface-400 transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Historical Contacts
          </button>
        </div>
      </div>
      <div className="p-3 rounded-lg bg-surface-300/70 border border-surface-400 text-xs text-gray-400">
        <span className="text-gray-200 font-medium">Ingest Awards Now</span> re-ingests every Tenders-SA award from the last 30 days across all buyers. Watched tenders are matched after ingestion; new awarded suppliers receive leads and contact enrichment.
      </div>
      {triggerMutation.isError && <p className="text-red-400 text-sm">Job trigger failed.</p>}
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

function FailedApiCallsTab() {
  const queryClient = useQueryClient();
  const [showResolved, setShowResolved] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ['admin-failed-api-calls', showResolved],
    queryFn: () => admin.getFailedApiCalls(showResolved ? undefined : false).then(r => r.data),
    refetchInterval: 15000,
  });

  const retryMutation = useMutation({
    mutationFn: (callId: string) => admin.retryFailedApiCall(callId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-failed-api-calls'] }),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Failed API Calls</h2>
        <label className="flex items-center gap-1.5 text-xs text-gray-400">
          <input type="checkbox" checked={showResolved} onChange={e => setShowResolved(e.target.checked)} className="rounded" />
          Show resolved
        </label>
      </div>
      {isLoading ? <p className="text-gray-400">Loading...</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-400 border-b border-surface-300">
                <th className="pb-2 pr-3">Endpoint</th>
                <th className="pb-2 pr-3">Method</th>
                <th className="pb-2 pr-3">Error</th>
                <th className="pb-2 pr-3">Attempts</th>
                <th className="pb-2 pr-3">Failed At</th>
                <th className="pb-2 pr-3">Status</th>
                <th className="pb-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data?.items?.map((item: { id: string; endpoint: string; method?: string; error: string; attempts: number; failed_at: string; resolved: boolean }) => (
                <tr key={item.id} className="border-b border-surface-300 text-gray-300">
                  <td className="py-2 pr-3 text-xs max-w-[200px] truncate font-mono">{item.endpoint}</td>
                  <td className="py-2 pr-3 text-xs">{item.method || 'GET'}</td>
                  <td className="py-2 pr-3 text-xs text-red-400 max-w-[250px] truncate">{item.error}</td>
                  <td className="py-2 pr-3">{item.attempts}</td>
                  <td className="py-2 pr-3 text-xs">{new Date(item.failed_at).toLocaleString()}</td>
                  <td className="py-2 pr-3">
                    <span className={`text-xs px-1.5 py-0.5 rounded ${item.resolved ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}>
                      {item.resolved ? 'Resolved' : 'Failed'}
                    </span>
                  </td>
                  <td className="py-2">
                    {!item.resolved && (
                      <button
                        onClick={() => retryMutation.mutate(item.id)}
                        disabled={retryMutation.isPending}
                        className="flex items-center gap-1 text-xs text-primary-400 hover:text-primary-300"
                      >
                        <RefreshCw className="w-3 h-3" /> Retry
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {(!data?.items || data.items.length === 0) && (
                <tr><td colSpan={7} className="py-4 text-center text-gray-500">No failed API calls</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {retryMutation.isError && (
        <p className="text-red-400 text-sm">Retry failed: {(retryMutation.error as Error).message}</p>
      )}
    </div>
  );
}
