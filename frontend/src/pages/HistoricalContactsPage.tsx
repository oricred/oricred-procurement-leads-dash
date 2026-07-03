import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Archive, Mail, Phone, RefreshCcw, Search, UserRound } from 'lucide-react';
import { historicalContactsApi } from '../services/api';
import type { HistoricalContact } from '../types';

function formatCurrency(value: number | null): string {
  if (!value) return '-';
  if (value >= 1_000_000) return `R${(value / 1_000_000).toFixed(1)}M`;
  return `R${(value / 1_000).toFixed(0)}K`;
}

function formatDate(value: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleDateString('en-ZA', { day: 'numeric', month: 'short', year: 'numeric' });
}

function contactTone(status: HistoricalContact['contact_sufficiency']): string {
  if (status === 'sufficient') return 'text-emerald-300 bg-emerald-500/10';
  if (status === 'role_based') return 'text-amber-300 bg-amber-500/10';
  return 'text-gray-400 bg-surface-300';
}

export default function HistoricalContactsPage() {
  const [query, setQuery] = useState('');
  const [contactability, setContactability] = useState('');

  const { data, isLoading, isFetching, isError, refetch } = useQuery({
    queryKey: ['historical-contacts', query, contactability],
    queryFn: async () => {
      const res = await historicalContactsApi.list({
        search: query || undefined,
        contactability: contactability || undefined,
        limit: 250,
      });
      return res.data;
    },
    refetchInterval: 60_000,
  });

  const items = useMemo(() => data?.items ?? [], [data?.items]);

  return (
    <div className="h-full flex flex-col min-w-0">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between mb-4">
        <div className="flex items-center gap-2">
          <Archive className="w-5 h-5 text-primary-400" />
          <div>
            <h2 className="text-lg font-semibold text-white">Historical Contacts</h2>
            <p className="text-xs text-gray-500">Older awarded companies kept as a contact base</p>
          </div>
          {data && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-surface-300 text-gray-400">
              {data.total.toLocaleString()} companies
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2 top-2.5 w-3.5 h-3.5 text-gray-500" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search companies"
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

      {isError ? (
        <div className="glass rounded-xl p-8 text-center">
          <p className="text-sm text-red-400 mb-2">Failed to load historical contacts.</p>
          <button onClick={() => refetch()} className="text-xs text-primary-400 hover:text-primary-300 transition-colors">
            Retry
          </button>
        </div>
      ) : (
        <div className="overflow-auto border border-surface-300 rounded-lg bg-surface-200/50">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface-200 border-b border-surface-300 text-xs uppercase text-gray-500">
              <tr>
                <th className="text-left px-4 py-3 font-medium">Company</th>
                <th className="text-left px-4 py-3 font-medium">Contact</th>
                <th className="text-left px-4 py-3 font-medium">Award History</th>
                <th className="text-left px-4 py-3 font-medium">Fit Signals</th>
                <th className="text-left px-4 py-3 font-medium">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-300">
              {isLoading ? (
                <tr><td colSpan={5} className="px-4 py-10 text-center text-gray-500">Loading historical contacts...</td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-10 text-center text-gray-500">No historical contacts match the current filters.</td></tr>
              ) : items.map((item) => {
                const contact = item.primary_contact;
                return (
                  <tr key={item.id} className="hover:bg-surface-300/60 transition-colors">
                    <td className="px-4 py-3 align-top">
                      <div className="font-medium text-gray-100 truncate max-w-[280px]">{item.company_name}</div>
                      <div className="text-xs text-gray-500 truncate max-w-[280px]">
                        {item.registration_number ?? 'No registration'}
                      </div>
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
                        <span className="inline-flex items-center gap-1.5 text-amber-300 text-xs"><RefreshCcw className="w-3.5 h-3.5" />Awaiting contact</span>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top">
                      <div className="font-mono text-gray-100">{formatCurrency(item.total_award_value)}</div>
                      <div className="text-xs text-gray-500">
                        {item.total_award_count} awards - last {formatDate(item.last_award_date)}
                      </div>
                      <div className="text-xs text-gray-600">first {formatDate(item.first_award_date)}</div>
                    </td>
                    <td className="px-4 py-3 align-top">
                      <span className={`inline-flex px-2 py-1 rounded text-xs font-medium ${contactTone(item.contact_sufficiency)}`}>
                        {item.contact_sufficiency.replace('_', ' ')}
                      </span>
                      <div className="text-xs text-gray-500 mt-1">B-BBEE {item.bee_level ?? '-'}</div>
                    </td>
                    <td className="px-4 py-3 align-top text-xs text-gray-500">
                      {formatDate(item.last_synced_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {isFetching && !isLoading && <div className="mt-2 text-xs text-gray-600">Refreshing...</div>}
    </div>
  );
}
