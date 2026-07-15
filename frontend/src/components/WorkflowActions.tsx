import { useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, ArrowRight, CheckCircle2, RotateCcw, XCircle } from 'lucide-react';
import { opportunities } from '../services/api';
import type { Opportunity } from '../types';

type Dialog = 'loss' | 'credit' | 'conditions' | 'back' | 'reopen' | null;

export default function WorkflowActions({ opportunity }: { opportunity: Opportunity }) {
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [lostReason, setLostReason] = useState('');
  const [conditionText, setConditionText] = useState('');
  const [conditions, setConditions] = useState<Array<Record<string, unknown>>>(opportunity.conditions_checklist ?? []);

  const isTerminal = ['funded', 'lost_lead'].includes(opportunity.kanban_stage);
  const canGoBack = !isTerminal && opportunity.kanban_stage !== 'new_lead';
  const transition = useMutation({
    mutationFn: (body: { action: string; version: number; lost_reason?: string; credit_decision?: string; confirm?: boolean; conditions_checklist?: Array<Record<string, unknown>> }) =>
      opportunities.transition(opportunity.id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['opportunity', opportunity.id] });
      queryClient.invalidateQueries({ queryKey: ['opportunities'] });
      queryClient.invalidateQueries({ queryKey: ['leads'] });
      queryClient.invalidateQueries({ queryKey: ['opportunity-audit', opportunity.id] });
      setDialog(null);
      setLostReason('');
    },
  });

  const errorMessage = useMemo(() => {
    const error = transition.error as { response?: { data?: { detail?: string } }; message?: string } | null;
    return error?.response?.data?.detail ?? error?.message ?? null;
  }, [transition.error]);

  const markContacted = useMutation({
    mutationFn: () => opportunities.markContacted(opportunity.id, { version: opportunity.version }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['opportunity', opportunity.id] });
      queryClient.invalidateQueries({ queryKey: ['opportunities'] });
      queryClient.invalidateQueries({ queryKey: ['leads'] });
      queryClient.invalidateQueries({ queryKey: ['opportunity-audit', opportunity.id] });
    },
  });

  function advance() {
    if (opportunity.kanban_stage === 'credit_review') return setDialog('credit');
    if (opportunity.kanban_stage === 'conditions_precedent') {
      setConditions(opportunity.conditions_checklist ?? []);
      return setDialog('conditions');
    }
    transition.mutate({ action: 'advance', version: opportunity.version });
  }

  const pending = transition.isPending || markContacted.isPending;

  return <div className="flex flex-wrap items-center justify-end gap-2">
    {isTerminal ? (
      <button onClick={() => setDialog('reopen')} disabled={pending} className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded bg-primary-600 text-white hover:bg-primary-500 disabled:opacity-50">
        <RotateCcw className="w-3.5 h-3.5" />Reopen
      </button>
    ) : (
      <>
        {opportunity.kanban_stage === 'new_lead' ? (
          <button onClick={() => markContacted.mutate()} disabled={pending} className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded bg-primary-600 text-white hover:bg-primary-500 disabled:opacity-50">
            <CheckCircle2 className="w-3.5 h-3.5" />Mark contacted
          </button>
        ) : (
          <button onClick={advance} disabled={pending} className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-50">
            <ArrowRight className="w-3.5 h-3.5" />Advance
          </button>
        )}
        {canGoBack && <button onClick={() => setDialog('back')} disabled={pending} className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded text-gray-300 hover:bg-surface-300 disabled:opacity-50"><ArrowLeft className="w-3.5 h-3.5" />Back</button>}
        <button onClick={() => setDialog('loss')} disabled={pending} className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded text-red-300 hover:bg-red-500/10 disabled:opacity-50"><XCircle className="w-3.5 h-3.5" />Decline</button>
      </>
    )}
    {(errorMessage || markContacted.isError) && <p className="basis-full text-right text-xs text-red-400">{errorMessage ?? 'Unable to mark the lead contacted.'}</p>}
    {dialog && <ActionDialog dialog={dialog} lostReason={lostReason} setLostReason={setLostReason} conditions={conditions} setConditions={setConditions} conditionText={conditionText} setConditionText={setConditionText} pending={transition.isPending} onClose={() => setDialog(null)} onConfirm={() => {
      if (dialog === 'loss') transition.mutate({ action: 'decline', version: opportunity.version, lost_reason: lostReason });
      if (dialog === 'credit') transition.mutate({ action: 'advance', version: opportunity.version, credit_decision: 'approved' });
      if (dialog === 'conditions') transition.mutate({ action: 'advance', version: opportunity.version, conditions_checklist: conditions });
      if (dialog === 'back') transition.mutate({ action: 'back', version: opportunity.version, confirm: true });
      if (dialog === 'reopen') transition.mutate({ action: 'reopen', version: opportunity.version, confirm: true });
    }} />}
  </div>;
}

function ActionDialog({ dialog, lostReason, setLostReason, conditions, setConditions, conditionText, setConditionText, pending, onClose, onConfirm }: {
  dialog: Exclude<Dialog, null>; lostReason: string; setLostReason: (value: string) => void; conditions: Array<Record<string, unknown>>; setConditions: (value: Array<Record<string, unknown>>) => void; conditionText: string; setConditionText: (value: string) => void; pending: boolean; onClose: () => void; onConfirm: () => void;
}) {
  const title = dialog === 'loss' ? 'Decline lead' : dialog === 'credit' ? 'Confirm credit approval' : dialog === 'conditions' ? 'Clear conditions precedent' : dialog === 'back' ? 'Move card back' : 'Reopen opportunity';
  const canConfirm = dialog !== 'loss' || lostReason.trim().length > 0;
  const addCondition = () => {
    const text = conditionText.trim();
    if (!text) return;
    setConditions([...conditions, { description: text, cleared: false }]);
    setConditionText('');
  };

  return <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label={title}>
    <div className="w-full max-w-md rounded-xl border border-surface-300 bg-surface-200 p-5 shadow-xl">
      <h3 className="text-base font-semibold text-white">{title}</h3>
      {dialog === 'loss' && <><p className="mt-2 text-sm text-gray-400">Record why this opportunity is leaving the active pipeline.</p><textarea autoFocus value={lostReason} onChange={event => setLostReason(event.target.value)} rows={3} className="mt-3 w-full rounded bg-surface-300 p-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-primary-500" placeholder="Reason for loss or decline" /></>}
      {dialog === 'credit' && <p className="mt-2 text-sm text-gray-400">This will mark the credit decision approved and move the opportunity to Pre-Approved.</p>}
      {dialog === 'back' && <p className="mt-2 text-sm text-gray-400">This confirmed backward move will be recorded in the audit history.</p>}
      {dialog === 'reopen' && <p className="mt-2 text-sm text-gray-400">This will reopen the terminal opportunity as a new lead and record the decision.</p>}
      {dialog === 'conditions' && <div className="mt-3 space-y-2"><p className="text-sm text-gray-400">Every condition must be cleared before issuing the term sheet.</p><div className="flex gap-2"><input value={conditionText} onChange={event => setConditionText(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); addCondition(); } }} className="min-w-0 flex-1 rounded bg-surface-300 px-2 py-1.5 text-sm text-white" placeholder="Add a condition" /><button onClick={addCondition} className="rounded bg-surface-300 px-2 text-xs text-primary-300">Add</button></div>{conditions.length === 0 ? <p className="text-xs text-amber-300">Add and clear every condition before advancing.</p> : <div className="max-h-40 space-y-1 overflow-auto">{conditions.map((condition, index) => <label key={index} className="flex items-center gap-2 rounded bg-surface-300 px-2 py-1.5 text-sm text-gray-200"><input type="checkbox" checked={Boolean(condition.cleared)} onChange={event => setConditions(conditions.map((item, itemIndex) => itemIndex === index ? { ...item, cleared: event.target.checked } : item))} /><span className="flex-1">{String(condition.description ?? 'Condition')}</span><button onClick={() => setConditions(conditions.filter((_, itemIndex) => itemIndex !== index))} className="text-xs text-red-300">Remove</button></label>)}</div>}</div>}
      <div className="mt-5 flex justify-end gap-2"><button onClick={onClose} disabled={pending} className="rounded px-3 py-1.5 text-xs text-gray-400 hover:text-white">Cancel</button><button onClick={onConfirm} disabled={pending || !canConfirm || (dialog === 'conditions' && (!conditions.length || !conditions.every(item => Boolean(item.cleared))))} className="rounded bg-primary-600 px-3 py-1.5 text-xs text-white hover:bg-primary-500 disabled:opacity-50">{pending ? 'Saving…' : 'Confirm'}</button></div>
    </div>
  </div>;
}
