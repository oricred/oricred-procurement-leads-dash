import { useState, useEffect, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Key, Users, Clock, Play, Trash2, Plus, RefreshCw } from 'lucide-react';
import { admin } from '../services/api';
import type { User } from '../types';

const TABS = [
  { id: 'credentials', label: 'Credentials', icon: Key },
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


