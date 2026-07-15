import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { opportunities } from '../services/api';
import { STAGE_LABELS, type Opportunity } from '../types';
import OpportunityModal from '../components/OpportunityModal';

const phases = {
  Sales: ['new_lead', 'client_contacted', 'qualified_lead', 'won_opportunity'],
  Credit: ['credit_preparation', 'credit_review', 'pre_approved', 'conditions_precedent'],
  'Deal Execution': ['term_sheet_sent', 'term_sheet_received', 'contracts_sent', 'contracts_received', 'ready_to_rff'],
} as const;
const terminal = { Funded: ['funded'], 'Lost / Declined': ['lost_lead'] } as const;
const money = (v: number | null) => v == null ? '—' : new Intl.NumberFormat('en-ZA', { style: 'currency', currency: 'ZAR', notation: 'compact' }).format(v);
function Card({ opp, open }: { opp: Opportunity; open: () => void }) { return <button onClick={open} className="w-full text-left bg-surface-300 hover:bg-surface-400 border border-surface-400 rounded-lg p-3 transition-colors"><div className="flex justify-between gap-2"><span className="font-medium text-gray-100 truncate">{opp.company_name ?? 'Unresolved supplier'}</span><span className="font-mono text-xs text-gray-300">{money(opp.award_value)}</span></div><div className="mt-2 flex items-center justify-between gap-2"><span className="text-[10px] px-1.5 py-0.5 rounded bg-primary-500/10 text-primary-300">{STAGE_LABELS[opp.kanban_stage].toUpperCase()}</span><span className={opp.contact_sufficiency === 'sufficient' ? 'text-emerald-400 text-xs' : 'text-amber-400 text-xs'}>{opp.contact_sufficiency === 'sufficient' ? 'Contact ready' : 'Needs contact'}</span></div>{opp.needs_enrichment && <p className="mt-2 text-xs text-amber-300">Identity enrichment needed</p>}</button>; }
export default function PipelinePage() {
  const [params] = useSearchParams(); const [selected, setSelected] = useState<Opportunity | null>(null); const [openTray, setOpenTray] = useState<string | null>(null);
  const { data, isLoading } = useQuery({ queryKey: ['opportunities'], queryFn: async () => (await opportunities.list()).data, refetchInterval: 15000 });
  useEffect(() => { const id = params.get('open'); if (id && data) setSelected(data.items.find(x => x.id === id) ?? null); }, [params, data]);
  const byPhase = (stages: readonly string[]) => (data?.items ?? []).filter(o => stages.includes(o.kanban_stage));
  return <div className="h-full flex flex-col"><div className="mb-4"><h2 className="text-lg font-semibold text-white">Deal Pipeline</h2><p className="text-xs text-gray-500">Move a deal deliberately from its detail panel; exact state stays visible on every card.</p></div>{isLoading ? <div className="text-gray-500">Loading pipeline…</div> : <><div className="grid grid-cols-1 lg:grid-cols-3 gap-4">{Object.entries(phases).map(([phase, states]) => { const items = byPhase(states); return <section key={phase} className="rounded-xl border border-surface-300 bg-surface-200/50 min-h-72"><header className="p-3 border-b border-surface-300 flex justify-between"><h3 className="font-semibold text-gray-200">{phase}</h3><span className="text-xs text-gray-500">{items.length}</span></header><div className="p-3 space-y-3">{items.map(o => <Card key={o.id} opp={o} open={() => setSelected(o)} />)}{items.length === 0 && <p className="text-center text-xs text-gray-600 py-8">No active deals</p>}</div></section>; })}</div><div className="mt-5 space-y-2">{Object.entries(terminal).map(([name, states]) => { const items = byPhase(states); const expanded = openTray === name; return <section key={name} className="border border-surface-300 rounded-lg"><button onClick={() => setOpenTray(expanded ? null : name)} className="w-full px-4 py-3 flex items-center gap-2 text-left text-sm text-gray-300">{expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}{name}<span className="text-gray-600">{items.length}</span></button>{expanded && <div className="grid grid-cols-1 md:grid-cols-3 gap-3 p-3 pt-0">{items.map(o => <Card key={o.id} opp={o} open={() => setSelected(o)} />)}</div>}</section>; })}</div></>}{selected && <OpportunityModal opportunity={selected} onClose={() => setSelected(null)} />}</div>;
}