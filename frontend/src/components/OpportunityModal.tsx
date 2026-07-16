import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { X, Building2, Award, Users, FileText, TrendingUp, BarChart3, Activity, History, Edit2, Phone, Mail, Linkedin, Star, Plus, Trash2, CheckCircle2 } from 'lucide-react';
import { auth, opportunities, buyerRelationships, crmActivity, contacts as contactsApi } from '../services/api';
import type { Opportunity, Contact } from '../types';
import WorkflowActions from './WorkflowActions';

interface Props {
  opportunity: Opportunity;
  onClose: () => void;
}

export default function OpportunityModal({ opportunity: initialOpportunity, onClose }: Props) {
  const { data: latestOpportunity } = useQuery({
    queryKey: ['opportunity', initialOpportunity.id],
    queryFn: async () => (await opportunities.get(initialOpportunity.id)).data,
    initialData: initialOpportunity,
  });
  const opp = latestOpportunity ?? initialOpportunity;
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const { data: rel } = useQuery({
    queryKey: ['buyer-relationship', opp.id],
    queryFn: async () => {
      const res = await buyerRelationships.get(opp.id);
      return res.data;
    },
    enabled: true,
  });

  const { data: crmData } = useQuery({
    queryKey: ['crm-activity', opp.id],
    queryFn: async () => {
      const res = await crmActivity.get(opp.id);
      return res.data;
    },
    enabled: true,
    refetchInterval: 30_000,
  });

  const sufficiencyIcons: Record<string, string> = { sufficient: '✓', role_based: '⚠', none: '✗' };
  const sufficiencyColors: Record<string, string> = {
    sufficient: 'text-emerald-400',
    role_based: 'text-amber-400',
    none: 'text-red-400',
  };

  const queryClient = useQueryClient();
  const { data: assignees = [] } = useQuery({
    queryKey: ['assignees'],
    queryFn: async () => (await auth.assignees()).data,
  });
  const [editingNotes, setEditingNotes] = useState(false);
  const [notesDraft, setNotesDraft] = useState(opp.notes ?? '');
  const [showAddContact, setShowAddContact] = useState(false);
  const [newContact, setNewContact] = useState({
    first_name: '', last_name: '', email: '', phone_direct: '', phone_mobile: '',
    job_title: '', linkedin_url: '', is_primary: false, notes: '',
  });

  const addContactMutation = useMutation({
    mutationFn: async (body: typeof newContact) => {
      if (opp.company_id) {
        await contactsApi.createForCompany(opp.company_id, body);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['opportunity', opp.id] });
      setShowAddContact(false);
      setNewContact({ first_name: '', last_name: '', email: '', phone_direct: '', phone_mobile: '', job_title: '', linkedin_url: '', is_primary: false, notes: '' });
    },
  });

  const deleteContactMutation = useMutation({
    mutationFn: (contactId: string) => contactsApi.delete(contactId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['opportunity', opp.id] });
    },
  });

  function handleAddContact() {
    addContactMutation.mutate(newContact);
  }

  function handleDeleteContact(contactId: string) {
    if (confirm('Remove this contact?')) {
      deleteContactMutation.mutate(contactId);
    }
  }

  const { data: auditData } = useQuery({
    queryKey: ['opportunity-audit', opp.id],
    queryFn: async () => {
      const res = await opportunities.getAudit(opp.id);
      return res.data;
    },
  });


  const [findContactFeedback, setFindContactFeedback] = useState<string | null>(null);
  const [showManualGuidance, setShowManualGuidance] = useState(false);

  const findContactMutation = useMutation({
    mutationFn: () => opportunities.findContact(opp.id),
    onSuccess: (res) => {
      const added = res.data.contacts_added;
      if (added > 0) {
        setFindContactFeedback(`Found ${added} contact${added !== 1 ? 's' : ''}`);
        setShowManualGuidance(false);
      } else {
        setFindContactFeedback('No contacts found in Tenders-SA');
        setShowManualGuidance(true);
      }
      queryClient.invalidateQueries({ queryKey: ['leads'] });
      queryClient.invalidateQueries({ queryKey: ['opportunities', opp.id] });
      setTimeout(() => setFindContactFeedback(null), 6000);
    },
    onError: () => {
      setFindContactFeedback('Contact lookup failed');
      setTimeout(() => setFindContactFeedback(null), 6000);
    },
  });

  const updateMutation = useMutation({
    mutationFn: (body: { notes?: string; risk_flag?: string; assigned_to?: string }) => opportunities.update(opp.id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['opportunity', opp.id] });
      setEditingNotes(false);
    },
  });

  function relationshipStrength(score: number | null | undefined): { label: string; color: string } {
    if (score == null) return { label: 'N/A', color: 'text-gray-500' };
    if (score >= 70) return { label: 'Strong', color: 'text-emerald-400' };
    if (score >= 40) return { label: 'Medium', color: 'text-amber-400' };
    return { label: 'Weak', color: 'text-red-400' };
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-2xl max-h-[85vh] overflow-y-auto bg-surface-200 border border-surface-300 rounded-2xl p-6 m-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div>
            <h2 className="text-lg font-bold text-white">{opp.company_name ?? 'Opportunity'}</h2>
            <div className="flex items-center gap-3 mt-1 text-sm text-gray-400">
              <span className={`font-mono font-bold ${sufficiencyColors[opp.contact_sufficiency ?? 'none']}`}>
                {sufficiencyIcons[opp.contact_sufficiency ?? 'none']} {opp.contact_sufficiency}
              </span>
              {opp.risk_flag && (
                <span className={`px-2 py-0.5 rounded-full text-xs ${
                  opp.risk_flag === 'red' ? 'badge-red' : opp.risk_flag === 'amber' ? 'badge-amber' : 'badge-green'
                }`}>
                  {opp.risk_flag}
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <WorkflowActions opportunity={opp} onFindContact={() => findContactMutation.mutate()} findContactPending={findContactMutation.isPending} />
            {findContactFeedback && (
              <span className={`text-xs font-medium ${
                findContactFeedback.includes('No') || findContactFeedback.includes('failed')
                  ? 'text-amber-400' : 'text-emerald-400'
              }`}>
                {findContactFeedback}
              </span>
            )}
            <button onClick={onClose} className="p-1 hover:bg-surface-300 rounded-lg transition-colors">
              <X className="w-5 h-5 text-gray-400" />
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Award Detail */}
          <div className="glass rounded-xl p-4 md:col-span-2">
            <div className="flex items-center gap-2 mb-3">
              <Award className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Award Detail</h3>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-sm">
              <div>
                <span className="block text-gray-500 text-xs mb-1">Value</span>
                <span className="text-white font-mono font-semibold">
                  {(opp.source_award_value ?? opp.award_value) ? `R${(((opp.source_award_value ?? opp.award_value) as number) / 1_000).toFixed(0)}K` : '—'}
                </span>
              </div>
              <div>
                <span className="block text-gray-500 text-xs mb-1">Award date</span>
                <span className="text-gray-200">{opp.source_award_date ? new Date(opp.source_award_date).toLocaleDateString() : '—'}</span>
              </div>
              <div>
                <span className="block text-gray-500 text-xs mb-1">Buyer</span>
                <span className="text-gray-200">{opp.buyer_org ?? '—'}</span>
              </div>
              <div>
                <span className="block text-gray-500 text-xs mb-1">Days since award</span>
                <span className="text-gray-200">{opp.days_since_award ?? '—'}d</span>
              </div>
            </div>
            <div className="mt-3 pt-3 border-t border-surface-300 text-sm">
              <span className="block text-gray-500 text-xs mb-1">Tender</span>
              <span className="text-gray-200">{opp.source_tender_title ?? '—'}</span>
            </div>
          </div>

          {/* Company Intel */}
          <div className="glass rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <Building2 className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Company Intelligence</h3>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Company</span>
                <span className="text-gray-200">{opp.company_name ?? '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Province</span>
                <span className="text-gray-200">{opp.province ?? '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Category</span>
                <span className="text-gray-200">{opp.category_name ?? opp.category ?? '—'}</span>
              </div>
            </div>
          </div>

          {/* Contact */}
          <div className="glass rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <Users className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Contact</h3>
              {opp.contacts.length > 0 && (
                <span className="text-xs text-gray-500 ml-auto">{opp.contacts.length} contact{opp.contacts.length > 1 ? 's' : ''}</span>
              )}
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Sufficiency</span>
                <span className={`font-mono ${sufficiencyColors[opp.contact_sufficiency ?? 'none']}`}>
                  {sufficiencyIcons[opp.contact_sufficiency ?? 'none']} {opp.contact_sufficiency}
                </span>
              </div>
              <label className="flex items-center justify-between gap-3">
                <span className="text-gray-500">Assigned</span>
                <select value={opp.assigned_to ?? ''} onChange={event => updateMutation.mutate({ assigned_to: event.target.value })} className="max-w-[160px] rounded bg-surface-300 px-2 py-1 text-xs text-gray-200">
                  <option value="">Unassigned</option>{assignees.map(user => <option key={user.id} value={user.id}>{user.name}</option>)}
                </select>
              </label>
              <label className="flex items-center justify-between gap-3">
                <span className="text-gray-500">Risk</span>
                <select value={opp.risk_flag ?? ''} onChange={event => updateMutation.mutate({ risk_flag: event.target.value })} className="rounded bg-surface-300 px-2 py-1 text-xs text-gray-200">
                  <option value="">No flag</option><option value="green">Green</option><option value="amber">Amber</option><option value="red">Red</option>
                </select>
              </label>
              {(() => {
                const primary = opp.contacts.find(c => c.is_primary);
                if (!primary) return null;
                return (
                  <>
                    <div className="border-t border-surface-300 my-2" />
                    <div className="text-xs space-y-1">
                      <div className="flex items-center gap-1 text-emerald-400 font-medium">
                        <Star className="w-3 h-3" /> {primary.first_name} {primary.last_name}
                        {primary.job_title && <span className="text-gray-500 font-normal">— {primary.job_title}</span>}
                      </div>
                      {primary.email && (
                        <div className="flex items-center gap-1.5 text-gray-400">
                          <Mail className="w-3 h-3" /> {primary.email}
                        </div>
                      )}
                      {(primary.phone_direct || primary.phone_mobile) && (
                        <div className="flex items-center gap-1.5 text-gray-400">
                          <Phone className="w-3 h-3" /> {primary.phone_direct || primary.phone_mobile}
                        </div>
                      )}
                    </div>
                  </>
                );
              })()}
            </div>
          </div>

          {/* Buyer Relationship */}
          <div className="glass rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <BarChart3 className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Relationship</h3>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Strength</span>
                <span className={`font-mono font-bold ${relationshipStrength(rel?.relevance_score).color}`}>
                  {relationshipStrength(rel?.relevance_score).label}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Awards (12m)</span>
                <span className="text-gray-200">{rel?.award_count_12m ?? '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Total value (12m)</span>
                <span className="text-gray-200 font-mono">
                  {rel?.total_award_value_12m != null ? `R${(rel.total_award_value_12m / 1_000_000).toFixed(1)}M` : '—'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Avg response</span>
                <span className="text-gray-200">
                  {rel?.avg_response_days != null ? `${rel.avg_response_days.toFixed(1)}d` : '—'}
                </span>
              </div>
              {rel?.win_rate != null && (
                <div className="flex justify-between">
                  <span className="text-gray-500">Win rate</span>
                  <span className="text-gray-200">{(rel.win_rate * 100).toFixed(0)}%</span>
                </div>
              )}
            </div>
          </div>

          {/* Scores */}
          <div className="glass rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <TrendingUp className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Scoring</h3>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Funding suitability</span>
                <span className={`font-mono font-bold ${
                  opp.funding_suitability != null
                    ? opp.funding_suitability >= 75 ? 'text-emerald-400'
                    : opp.funding_suitability >= 50 ? 'text-amber-400'
                    : 'text-red-400'
                    : 'text-gray-200'
                }`}>
                  {opp.funding_suitability != null ? `${opp.funding_suitability}%` : '—'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Win probability</span>
                <span className="text-gray-200 font-mono">
                  {opp.win_probability != null ? `${opp.win_probability}%` : '—'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Buyer preference</span>
                <span className={`font-mono font-bold ${
                  opp.buyer_preference_score != null
                    ? opp.buyer_preference_score >= 75 ? 'text-emerald-400'
                    : opp.buyer_preference_score >= 50 ? 'text-amber-400'
                    : 'text-red-400'
                    : 'text-gray-200'
                }`}>
                  {opp.buyer_preference_score != null ? `${opp.buyer_preference_score}%` : '—'}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Related Bidders */}
        {opp.related_bidders && opp.related_bidders.length > 0 && (
          <div className="glass rounded-xl p-4 mt-4">
            <div className="flex items-center gap-2 mb-3">
              <Users className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Related Bidders</h3>
            </div>
            <p className="text-xs text-gray-500 mb-3">Other companies that bid on this tender — potential financing leads</p>
            <div className="space-y-2 text-sm max-h-40 overflow-y-auto">
              {opp.related_bidders.map((c, i) => (
                <div key={i} className="flex items-start gap-2 text-xs border-b border-surface-300 pb-2 last:border-0">
                  <span className="text-gray-200 font-medium">{c.name}</span>
                  {c.resolved && <span className="text-gray-500">({c.resolved})</span>}
                  {c.inferred ? (
                    <span className="text-amber-400 text-[10px]">similar company</span>
                  ) : (
                    <span className="text-emerald-400 text-[10px]">confirmed bidder</span>
                  )}
                  {c.reason && <span className="text-gray-500">— {c.reason}</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Audit History */}
        {auditData && auditData.length > 0 && (
          <div className="glass rounded-xl p-4 mt-4">
            <div className="flex items-center gap-2 mb-3">
              <History className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Audit History</h3>
            </div>
            <div className="space-y-1 text-xs max-h-32 overflow-y-auto">
              {auditData.map((a) => (
                <div key={a.id} className="flex gap-2 text-gray-400">
                  <span className="text-gray-600 font-mono shrink-0">
                    {new Date(a.changed_at).toLocaleDateString()}
                  </span>
                  <span>
                    {a.from_stage ? `${a.from_stage} → ` : ''}{a.to_stage}
                  </span>
                  <span className="text-gray-600">by {a.changed_by}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* CRM Activity */}
        {crmData?.activities != null && (
          <div className="glass rounded-xl p-4 mt-4">
            <div className="flex items-center gap-2 mb-3">
              <Activity className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Monday.com Activity</h3>
            </div>
            {crmData.activities.length === 0 ? (
              <p className="text-xs text-gray-500">No recent activity</p>
            ) : (
              <div className="space-y-2 text-sm max-h-40 overflow-y-auto">
                {crmData.activities.map((act, i) => (
                  <div key={i} className="border-b border-surface-300 pb-2 last:border-0">
                    <div className="flex items-start gap-2 text-xs">
                      <span className="text-gray-500 font-mono shrink-0">
                        {new Date(act.created_at).toLocaleDateString()}
                      </span>
                      <span className="text-gray-300 capitalize">{act.event.replace(/_/g, ' ')}</span>
                    </div>
                    {act.data && (() => {
                      const d = act.data as Record<string, string>;
                      return (
                        <div className="mt-1 ml-0 text-xs text-gray-500 space-y-0.5">
                          {d.item_name && <div><span className="text-gray-600">Item:</span> {d.item_name}</div>}
                          {d.column_name && <div><span className="text-gray-600">Column:</span> {d.column_name}</div>}
                          {d.old_value != null && (
                            <div className="flex gap-2">
                              <span className="text-gray-600">Changed:</span>
                              <span className="line-through text-red-400/70">{d.old_value}</span>
                              <span className="text-emerald-400">&rarr; {d.new_value ?? '(empty)'}</span>
                            </div>
                          )}
                        </div>
                      );
                    })()}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Contacts */}
        <div className="glass rounded-xl p-4 mt-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Users className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Contacts</h3>
            </div>
            <button
              onClick={() => setShowAddContact(true)}
              className="p-1 hover:bg-surface-300 rounded transition-colors text-gray-400 hover:text-gray-200"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          </div>

          {showAddContact && (
            <div className="mb-3 p-3 bg-surface-300 rounded-lg space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <input className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-primary-500" placeholder="First name" value={newContact.first_name} onChange={e => setNewContact(prev => ({ ...prev, first_name: e.target.value }))} />
                <input className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-primary-500" placeholder="Last name" value={newContact.last_name} onChange={e => setNewContact(prev => ({ ...prev, last_name: e.target.value }))} />
              </div>
              <input className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-primary-500" placeholder="Email" type="email" value={newContact.email} onChange={e => setNewContact(prev => ({ ...prev, email: e.target.value }))} />
              <div className="grid grid-cols-2 gap-2">
                <input className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-primary-500" placeholder="Phone (direct)" value={newContact.phone_direct} onChange={e => setNewContact(prev => ({ ...prev, phone_direct: e.target.value }))} />
                <input className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-primary-500" placeholder="Phone (mobile)" value={newContact.phone_mobile} onChange={e => setNewContact(prev => ({ ...prev, phone_mobile: e.target.value }))} />
              </div>
              <input className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-primary-500" placeholder="Job title" value={newContact.job_title} onChange={e => setNewContact(prev => ({ ...prev, job_title: e.target.value }))} />
              <input className="w-full bg-surface-200 border border-surface-400 rounded px-2 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-primary-500" placeholder="LinkedIn URL" value={newContact.linkedin_url} onChange={e => setNewContact(prev => ({ ...prev, linkedin_url: e.target.value }))} />
              <div className="flex items-center gap-2">
                <input type="checkbox" id="new-primary" checked={newContact.is_primary} onChange={e => setNewContact(prev => ({ ...prev, is_primary: e.target.checked }))} />
                <label htmlFor="new-primary" className="text-xs text-gray-400">Primary contact</label>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleAddContact}
                  disabled={!newContact.first_name || !newContact.last_name || !newContact.email}
                  className="px-3 py-1 text-xs bg-primary-600 hover:bg-primary-500 text-white rounded-lg transition-colors disabled:opacity-50"
                >
                  Add
                </button>
                <button
                  onClick={() => setShowAddContact(false)}
                  className="px-3 py-1 text-xs bg-surface-300 hover:bg-surface-200 text-gray-300 rounded-lg transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {showManualGuidance && (
            <div className="mb-3 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-xs text-amber-300 space-y-1.5">
              <p className="font-medium">No contacts found automatically.</p>
              <p>Try searching for this company on Google, LinkedIn, or their website to find contact details, then use the <strong>Add Contact</strong> form below to record them.</p>
              <button
                onClick={() => setShowManualGuidance(false)}
                className="text-gray-400 hover:text-gray-200 underline"
              >
                Dismiss
              </button>
            </div>
          )}

          {opp.contacts.length === 0 ? (
            <p className="text-sm text-gray-500 italic">No contacts</p>
          ) : (
            <div className="space-y-2 max-h-60 overflow-y-auto">
              {opp.contacts.map((c) => (
                <div key={c.id} className="border-b border-surface-300 pb-2 last:border-0">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-medium text-gray-200">
                          {c.first_name} {c.last_name}
                        </span>
                        {c.is_primary && <Star className="w-3 h-3 text-emerald-400 fill-emerald-400" />}
                        {c.job_title && <span className="text-xs text-gray-500">— {c.job_title}</span>}
                      </div>
                      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-0.5 text-xs text-gray-400">
                        {c.email && (
                          <a href={`mailto:${c.email}`} className="flex items-center gap-1 hover:text-primary-400 transition-colors">
                            <Mail className="w-3 h-3" /> {c.email}
                          </a>
                        )}
                        {c.phone_direct && (
                          <a href={`tel:${c.phone_direct}`} className="flex items-center gap-1 hover:text-primary-400 transition-colors">
                            <Phone className="w-3 h-3" /> {c.phone_direct}
                          </a>
                        )}
                        {c.phone_mobile && (
                          <a href={`tel:${c.phone_mobile}`} className="flex items-center gap-1 hover:text-primary-400 transition-colors">
                            <Phone className="w-3 h-3" /> {c.phone_mobile}
                          </a>
                        )}
                        {c.linkedin_url && (
                          <a href={c.linkedin_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 hover:text-primary-400 transition-colors">
                            <Linkedin className="w-3 h-3" /> LinkedIn
                          </a>
                        )}
                      </div>
                      {c.notes && <p className="text-xs text-gray-600 mt-0.5">{c.notes}</p>}
                    </div>
                    <button
                      onClick={() => handleDeleteContact(c.id)}
                      className="p-1 hover:bg-surface-300 rounded transition-colors text-gray-600 hover:text-red-400 shrink-0 ml-2"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Notes */}
        <div className="glass rounded-xl p-4 mt-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Notes</h3>
            </div>
            <button
              onClick={() => {
                if (editingNotes) {
                  updateMutation.mutate({ notes: notesDraft });
                } else {
                  setNotesDraft(opp.notes ?? '');
                  setEditingNotes(true);
                }
              }}
              className="p-1 hover:bg-surface-300 rounded transition-colors text-gray-400 hover:text-gray-200"
            >
              <Edit2 className="w-3.5 h-3.5" />
            </button>
          </div>
          {editingNotes ? (
            <div className="space-y-2">
              <textarea
                className="w-full bg-surface-300 border border-surface-300 rounded-lg p-2 text-sm text-gray-200 resize-none focus:outline-none focus:border-primary-500"
                rows={3}
                value={notesDraft}
                onChange={(e) => setNotesDraft(e.target.value)}
              />
              <div className="flex gap-2">
                <button
                  onClick={() => {
                    updateMutation.mutate({ notes: notesDraft });
                    setEditingNotes(false);
                  }}
                  className="px-3 py-1 text-xs bg-primary-600 hover:bg-primary-500 text-white rounded-lg transition-colors"
                >
                  Save
                </button>
                <button
                  onClick={() => setEditingNotes(false)}
                  className="px-3 py-1 text-xs bg-surface-300 hover:bg-surface-200 text-gray-300 rounded-lg transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-300 whitespace-pre-wrap min-h-[1em]">
              {opp.notes || <span className="text-gray-500 italic">No notes</span>}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

