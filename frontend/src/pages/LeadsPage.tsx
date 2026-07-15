import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Mail, Phone, Search, UserRound, RefreshCcw, ArrowRightCircle } from 'lucide-react';
import { leads } from '../services/api';
import type { Opportunity } from '../types';
import OpportunityModal from '../components/OpportunityModal';
import HelpLink from '../components/HelpLink';

function formatCurrency(value: number | null): string {
  if (!value) return '—';
  if (value >= 1_000_000) return `R${(value / 1_000_000).toFixed(1)}M`;
  return `R${(value / 1_000).toFixed(0)}K`;
}

function formatDate(value: string | null): string {
  if (!value) return '—';
  return new Date(value).toLocaleDateString('en-ZA', { day: 'numeric', month: 'short', year: 'numeric' });
}

function priorityTone(score: number | null): string {
  if (score == null) return 'text-gray-500 bg-surface-300';
  if (score >= 75) return 'text-emerald-300 bg-emerald-500/10';
  if (score >= 50) return 'text-amber-300 bg-amber-500/10';
  return 'text-gray-300 bg-surface-300';
}

export default function LeadsPage() {
  const [selectedOpp, setSelectedOpp] = useState<Opportunity | null>(null);
  const [query, setQuery] = useState('');
  const [contactability, setContactability] = useState('');

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['leads', contactability],
    queryFn: async () => {
      const res = await leads.list({
        stage: 'new_lead',
        contactability: contactability || undefined,
      });
      return res.data;
    },
    refetchInterval: 30_000,
  });

  const items = useMemo(() => {
    const all = data?.items ?? [];
    const needle = query.trim().toLowerCase();
    if (!needle) return all;
    return all.filter((opp) =>
      [opp.company_name, opp.buyer_org, opp.source_tender_title, opp.province, opp.category, opp.category_name]
        .some((value) => (value ?? '').toLowerCase().includes(needle)),
    );
  }, [data?.items, query]);

  return (
    <div className="h-full flex flex-col min-w-0">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-white">Lead Inbox</h2>
          <p className="text-xs text-gray-500">Awarded companies ready for funding outreach</p><HelpLink section="lead-inbox" />
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2 top-2.5 w-3.5 h-3.5 text-gray-500" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search leads"
              className="w-56 bg-surface-200 border border-surface-300 rounded pl-7 pr-2 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-primary-500"
            />
          </div>
          <select
            value={contactability}
            onChange={(e) => setContactability(e.target.value)}
            className="bg-surface-200 border border-surface-300 rounded px-2 py-2 text-sm text-gray-200 focus:outline-none focus:border-primary-500"
          >
            <option value="">All contacts</option>
            <option value="contactable">Contactable</option>
            <option value="needs_contact">Needs contact</option>
          </select>
        </div>
      </div>

      <div className="overflow-auto border border-surface-300 rounded-lg bg-surface-200/50">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface-200 border-b border-surface-300 text-xs uppercase text-gray-500">
            <tr>
              <th className="text-left px-4 py-3 font-medium">Company</th>
              <th className="text-left px-4 py-3 font-medium">Contact</th>
              <th className="text-left px-4 py-3 font-medium">Award</th>
              <th className="text-left px-4 py-3 font-medium">Fit</th>
              <th className="text-left px-4 py-3 font-medium">Next</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-300">
            {isLoading ? (
              <tr><td colSpan={5} className="px-4 py-10 text-center text-gray-500">Loading leads...</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-10 text-center text-gray-500">No new leads match the current filters.</td></tr>
            ) : items.map((opp) => {
              const contact = opp.primary_contact;
              return (
                <tr
                  key={opp.id}
                  onClick={() => setSelectedOpp(opp)}
                  className="hover:bg-surface-300/60 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3 align-top">
                    <div className="font-medium text-gray-100 truncate max-w-[260px]">{opp.company_name ?? 'Unknown Company'}</div>
                    <div className="text-xs text-gray-500 truncate max-w-[260px]">{opp.province ?? '—'} · {opp.category_name ?? opp.category ?? '—'}</div>
                  </td>
                  <td className="px-4 py-3 align-top">
                    {contact ? (
                      <div className="space-y-1">
                        <div className="flex items-center gap-1.5 text-gray-200">
                          <UserRound className="w-3.5 h-3.5 text-primary-400" />
                          <span>{contact.first_name} {contact.last_name}</span>
                        </div>
                        <div className="flex flex-wrap gap-2 text-xs text-gray-500">
                          {contact.email && <span className="inline-flex items-center gap-1"><Mail className="w-3 h-3" />{contact.email}</span>}
                          {(contact.phone_direct || contact.phone_mobile) && <span className="inline-flex items-center gap-1"><Phone className="w-3 h-3" />{contact.phone_direct || contact.phone_mobile}</span>}
                        </div>
                      </div>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-amber-300 text-xs"><RefreshCcw className="w-3.5 h-3.5" />Find contact</span>
                    )}
                  </td>
                  <td className="px-4 py-3 align-top">
                    <div className="font-mono text-gray-100">{formatCurrency(opp.source_award_value ?? opp.award_value)}</div>
                    <div className="text-xs text-gray-500">{formatDate(opp.source_award_date)} · {opp.buyer_org ?? 'Unknown buyer'}</div>
                    <div className="text-xs text-gray-600 truncate max-w-[280px]">{opp.source_tender_title ?? 'No tender title'}</div>
                  </td>
                  <td className="px-4 py-3 align-top">
                    <span className={`inline-flex px-2 py-1 rounded text-xs font-mono font-semibold ${priorityTone(opp.lead_priority_score)}`}>
                      {opp.lead_priority_score != null ? `${opp.lead_priority_score}%` : '—'}
                    </span>
                    <div className="text-xs text-gray-500 mt-1 truncate max-w-[220px]">{opp.lead_priority_reasons?.[0] ?? 'Awaiting score'}</div>
                  </td>
                  <td className="px-4 py-3 align-top">
                    <div className="inline-flex items-center gap-1.5 text-primary-300 text-xs font-medium">
                      <ArrowRightCircle className="w-3.5 h-3.5" />
                      {opp.next_action ?? 'Review lead'}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {isFetching && !isLoading && <div className="mt-2 text-xs text-gray-600">Refreshing...</div>}
      {selectedOpp && <OpportunityModal opportunity={selectedOpp} onClose={() => setSelectedOpp(null)} />}
    </div>
  );
}
