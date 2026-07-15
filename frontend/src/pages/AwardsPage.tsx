import { useCallback, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Award, Download, ExternalLink, History, Plus } from 'lucide-react';
import { awardsApi, organizationsApi } from '../services/api';
import type { AwardItem } from '../types';
import FilterBar, { type FilterField } from '../components/FilterBar';
import DataTable, { type ColumnDef } from '../components/DataTable';
import HelpLink from '../components/HelpLink';

const money = (v: number | null) => v == null ? '—' : new Intl.NumberFormat('en-ZA', { style: 'currency', currency: 'ZAR', notation: 'compact' }).format(v);
const date = (v: string | null) => v ? new Date(v).toLocaleDateString('en-ZA') : '—';

export default function AwardsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(Number(params.get('page') || 1));
  const [filters, setFilters] = useState<Record<string, string>>(() => Object.fromEntries([...params].filter(([key]) => !['tab', 'page', 'sort', 'direction'].includes(key))));
  const [sort, setSort] = useState(params.get('sort') || 'award_date');
  const [direction, setDirection] = useState(params.get('direction') || 'desc');
  const [hidden, setHidden] = useState<string[]>([]);
  useEffect(() => {
    const nextFilters = Object.fromEntries([...params].filter(([key]) => !['tab', 'page', 'sort', 'direction'].includes(key)));
    setFilters(current => JSON.stringify(current) === JSON.stringify(nextFilters) ? current : nextFilters);
    setPage(Number(params.get('page') || 1));
    setSort(params.get('sort') || 'award_date');
    setDirection(params.get('direction') || 'desc');
  }, [params]);

  useEffect(() => {
    const next = new URLSearchParams(filters);
    if (page > 1) next.set('page', String(page));
    next.set('sort', sort); next.set('direction', direction);
    setParams(next, { replace: true });
  }, [filters, page, sort, direction, setParams]);
  const queryParams = { ...filters, page, page_size: 50, sort, direction };
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ['awards', queryParams], queryFn: async () => (await awardsApi.list(queryParams)).data });
  const { data: orgs } = useQuery({ queryKey: ['organizations'], queryFn: async () => (await organizationsApi.list()).data, staleTime: 300000 });
  const create = useMutation({
    mutationFn: (id: string) => awardsApi.createLead(id),
    onSuccess: ({ data: lead }) => { queryClient.invalidateQueries({ queryKey: ['awards'] }); queryClient.invalidateQueries({ queryKey: ['leads'] }); navigate(`/pipeline?open=${lead.id}&created=1`); },
  });
  const fields: FilterField[] = [
    { key: 'supplier', label: 'Supplier', type: 'text', placeholder: 'Search supplier' },
    { key: 'buyer_org_id', label: 'Buyer', type: 'select', options: orgs?.map(o => ({ label: o.name, value: o.id })) ?? [] },
    { key: 'date_from', label: 'From', type: 'date' }, { key: 'date_to', label: 'To', type: 'date' },
    { key: 'value_min', label: 'Min value', type: 'number' }, { key: 'source', label: 'Source', type: 'select', options: [{ label: 'Tenders-SA', value: 'tenders_api' }, { label: 'Municipal', value: 'municipal' }] },
    { key: 'has_opportunity', label: 'Lead created', type: 'toggle' },
  ];
  const columns: ColumnDef[] = useMemo<ColumnDef[]>(() => [
    { key: 'supplier_name', label: 'Supplier', render: (v: unknown) => <span className="font-medium text-gray-100">{String(v)}</span> },
    { key: 'buyer_org_name', label: 'Buyer' }, { key: 'tender_title', label: 'Tender', render: (v: unknown) => <span className="text-xs text-gray-400 block truncate max-w-56">{String(v ?? '—')}</span> },
    { key: 'amount', label: 'Value', render: (v: unknown) => <span className="font-mono">{money(v as number | null)}</span> },
    { key: 'award_date', label: 'Awarded', render: (v: unknown) => date(v as string | null) }, { key: 'bee_level', label: 'B-BBEE', render: (v: unknown) => v == null ? '—' : `Level ${v}` },
    { key: 'source', label: 'Source' }, { key: 'lead_state', label: 'Lead', render: (v: unknown, row: Record<string, unknown>) => <span className={(row as unknown as AwardItem).contact_readiness === 'sufficient' ? 'text-emerald-400' : 'text-amber-300'}>{String(v).replace(/_/g, ' ')}</span> },
    { key: 'id', label: 'Actions', render: (_v: unknown, row: Record<string, unknown>) => { const a = row as unknown as AwardItem; return <div className="flex gap-2"><button onClick={() => a.opportunity_id ? navigate(`/pipeline?open=${a.opportunity_id}`) : create.mutate(a.id)} className="text-primary-400 hover:text-primary-300" title={a.opportunity_id ? 'Open lead' : 'Create lead'}>{a.opportunity_id ? <ExternalLink className="w-4 h-4" /> : <Plus className="w-4 h-4" />}</button><button onClick={() => navigate("/discover?tab=history")} className="text-gray-400 hover:text-gray-200" title="View supplier history"><History className="w-4 h-4" /></button></div> } },
  ].filter(c => !hidden.includes(c.key)), [create, hidden, navigate]);
  const toggleSort = () => { setDirection(d => sort === 'award_date' && d === 'desc' ? 'asc' : 'desc'); setSort('award_date'); };
  const exportCsv = () => window.open(awardsApi.exportUrl({ ...filters, sort, direction }), '_blank', 'noopener,noreferrer');
  return <div>
    <div className="flex flex-wrap items-center gap-3 mb-4"><Award className="w-5 h-5 text-primary-400" /><div><h2 className="text-lg font-semibold text-white">Award intelligence</h2><p className="text-xs text-gray-500">Create outreach-ready leads from awarded suppliers.</p></div><span className="text-xs text-gray-500">{data?.total ?? 0} results</span><div className="ml-auto"><HelpLink section="discover" /></div><button onClick={toggleSort} className="text-xs text-gray-400 hover:text-white">Sort award date {direction === 'desc' ? '↓' : '↑'}</button><button onClick={exportCsv} className="inline-flex gap-1 text-xs text-primary-400"><Download className="w-4 h-4" />CSV</button></div>
    <FilterBar fields={fields} values={filters} onChange={(k, v) => { setFilters(f => ({ ...f, [k]: v })); setPage(1); }} onClear={() => { setFilters({}); setPage(1); }} />
    <details className="my-3 text-xs text-gray-500"><summary className="cursor-pointer">Columns</summary><div className="flex flex-wrap gap-3 mt-2">{['buyer_org_name','tender_title','bee_level','source','lead_state'].map(key => <label key={key}><input type="checkbox" checked={!hidden.includes(key)} onChange={() => setHidden(h => h.includes(key) ? h.filter(x => x !== key) : [...h, key])} /> {key.replace(/_/g, ' ')}</label>)}</div></details>
    {isError ? <div className="glass p-8 text-center text-red-400">Awards could not load. <button onClick={() => refetch()}>Retry</button></div> : <DataTable columns={columns} data={(data?.items ?? []) as unknown as Record<string, unknown>[]} page={page} pageSize={50} total={data?.total ?? 0} onPageChange={setPage} isLoading={isLoading} emptyMessage="No awards match these filters." />}
  </div>;
}
