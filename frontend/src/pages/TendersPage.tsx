import { useState, useEffect, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { FileText, ExternalLink, Eye, EyeOff } from 'lucide-react';
import { tendersApi, organizationsApi, categoriesApi } from '../services/api';
import type { TenderItem } from '../types';
import FilterBar from '../components/FilterBar';
import DataTable from '../components/DataTable';
import type { FilterField } from '../components/FilterBar';
import type { ColumnDef } from '../components/DataTable';

function formatCurrency(value: number | null | undefined): string {
  if (!value) return '—';
  if (value >= 1_000_000) return `R${(value / 1_000_000).toFixed(1)}M`;
  return `R${(value / 1_000).toFixed(0)}K`;
}

function formatDate(d: string | null | undefined): string {
  if (!d) return '—';
  return new Date(d).toLocaleDateString('en-ZA', { day: 'numeric', month: 'short', year: 'numeric' });
}

const statusBadges: Record<string, { label: string; color: string; bg: string }> = {
  watching: { label: 'Watching', color: 'text-blue-400', bg: 'bg-blue-500/10' },
  awarded: { label: 'Awarded', color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  past_due: { label: 'Past Due', color: 'text-red-400', bg: 'bg-red-500/10' },
  opportunity: { label: 'Opportunity', color: 'text-purple-400', bg: 'bg-purple-500/10' },
  not_watched: { label: 'Not Watched', color: 'text-gray-500', bg: 'bg-surface-400' },
};

export default function TendersPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<Record<string, string>>({});

  const queryParams = { ...filters, page, page_size: 50 };
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['tenders', queryParams],
    queryFn: async () => {
      const res = await tendersApi.list(queryParams);
      return res.data;
    },
  });

  const { data: orgs } = useQuery({
    queryKey: ['organizations'],
    queryFn: async () => {
      const res = await organizationsApi.list();
      return res.data;
    },
    staleTime: 300_000,
  });

  const { data: cats } = useQuery({
    queryKey: ['categories'],
    queryFn: async () => {
      const res = await categoriesApi.list();
      return res.data;
    },
    staleTime: 300_000,
  });

  const { data: provinces } = useQuery({
    queryKey: ['tender-provinces'],
    queryFn: async () => {
      const res = await tendersApi.provinces();
      return res.data;
    },
    staleTime: 300_000,
  });

  const toggleWatchMutation = useMutation({
    mutationFn: (tenderId: string) => tendersApi.toggleWatch(tenderId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tenders'] });
      queryClient.invalidateQueries({ queryKey: ['watchlist'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
  });

  const filterFields: FilterField[] = [
    { key: 'search', label: 'Search', type: 'text', placeholder: 'Search title...' },
    {
      key: 'buyer_org_id', label: 'Buyer', type: 'select',
      options: orgs?.map(o => ({ label: o.name, value: o.id })) ?? [],
    },
    {
      key: 'province', label: 'Province', type: 'select',
      options: provinces?.map(p => ({ label: p, value: p })) ?? [],
    },
    {
      key: 'category_id', label: 'Category', type: 'select',
      options: cats?.map(c => ({ label: c.name, value: c.id })) ?? [],
    },
    { key: 'value_min', label: 'Value min', type: 'number', placeholder: 'Min' },
    { key: 'value_max', label: 'Value max', type: 'number', placeholder: 'Max' },
    { key: 'closing_from', label: 'Closing from', type: 'date' },
    { key: 'closing_to', label: 'Closing to', type: 'date' },
    {
      key: 'status', label: 'Status', type: 'select',
      options: [
        { label: 'Watching', value: 'watching' },
        { label: 'Awarded', value: 'awarded' },
        { label: 'Past Due', value: 'past_due' },
        { label: 'Opportunity', value: 'opportunity' },
        { label: 'Not Watched', value: 'not_watched' },
      ],
    },
    { key: 'has_opportunity', label: 'Has opportunity', type: 'toggle' },
  ];

  const columns: ColumnDef[] = [
    {
      key: 'title', label: 'Title',
      render: (val: unknown) => (
        <span className="text-sm text-gray-200 block truncate max-w-[300px]" title={val as string ?? ''}>
          {val as string ?? '—'}
        </span>
      ),
    },
    {
      key: 'buyer_org_name', label: 'Buyer',
      render: (val: unknown) => (
        <span className="text-xs text-gray-400">{(val as string) ?? '—'}</span>
      ),
      width: '14%',
    },
    {
      key: 'category_name', label: 'Category',
      render: (val: unknown) => (
        <span className="text-xs text-gray-500 uppercase">{(val as string) ?? '—'}</span>
      ),
      width: '10%',
    },
    {
      key: 'province', label: 'Province',
      render: (val: unknown) => (
        <span className="text-xs text-gray-500">{(val as string) ?? '—'}</span>
      ),
      width: '8%',
    },
    {
      key: 'estimated_value', label: 'Value',
      render: (val: unknown) => (
        <span className="text-sm font-mono text-gray-200 font-medium">{formatCurrency(val as number | null)}</span>
      ),
      className: 'text-right',
      width: '10%',
    },
    {
      key: 'closing_date', label: 'Closing',
      render: (val: unknown) => (
        <span className="text-xs text-gray-400">{formatDate(val as string | null)}</span>
      ),
      width: '10%',
    },
    {
      key: 'status', label: 'Status',
      render: (val: unknown, row: Record<string, unknown>) => {
        const s = (val as string) ?? 'not_watched';
        const badge = statusBadges[s] ?? statusBadges.not_watched;
        return (
          <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${badge.bg} ${badge.color}`}>
            {badge.label}
          </span>
        );
      },
      width: '10%',
    },
    {
      key: 'id', label: '',
      render: (_val: unknown, row: Record<string, unknown>) => {
        const item = row as unknown as TenderItem;
        return (
          <div className="flex items-center gap-1">
            {item.opportunity_id ? (
              <button
                onClick={() => navigate(`/pipeline?open=${item.opportunity_id}`)}
                className="p-1 hover:bg-surface-300 rounded transition-colors text-primary-400"
                title="Open in Pipeline"
              >
                <ExternalLink className="w-3.5 h-3.5" />
              </button>
            ) : item.is_watching ? (
              <button
                onClick={() => navigate('/matching')}
                className="p-1 hover:bg-surface-300 rounded transition-colors text-gray-500 hover:text-amber-400"
                title="View in Matching"
              >
                <Eye className="w-3.5 h-3.5" />
              </button>
            ) : null}
            <button
              onClick={() => toggleWatchMutation.mutate(item.id)}
              className={`p-1 rounded transition-colors ${
                item.is_watching
                  ? 'text-blue-400 hover:text-gray-400'
                  : 'text-gray-600 hover:text-blue-400'
              }`}
              title={item.is_watching ? 'Unwatch' : 'Watch'}
            >
              {item.is_watching ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
            </button>
          </div>
        );
      },
      className: 'text-right',
      width: '8%',
    },
  ];

  const handleFilterChange = useCallback((key: string, value: string) => {
    setFilters(prev => ({ ...prev, [key]: value }));
    setPage(1);
  }, []);

  const handleClear = useCallback(() => {
    setFilters({});
    setPage(1);
  }, []);

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <FileText className="w-5 h-5 text-primary-400" />
        <h2 className="text-lg font-semibold text-white">Tenders</h2>
        {data && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-surface-300 text-gray-400">
            {data.total.toLocaleString()} total
          </span>
        )}
      </div>

      <div className="mb-4">
        <FilterBar fields={filterFields} values={filters} onChange={handleFilterChange} onClear={handleClear} />
      </div>

      {isError ? (
        <div className="glass rounded-xl p-8 text-center">
          <p className="text-sm text-red-400 mb-2">Failed to load tenders.</p>
          <button
            onClick={() => refetch()}
            className="text-xs text-primary-400 hover:text-primary-300 transition-colors"
          >
            Retry
          </button>
        </div>
      ) : (
        <DataTable
          columns={columns}
          data={(data?.items ?? []) as unknown as Record<string, unknown>[]}
          page={page}
          pageSize={50}
          total={data?.total ?? 0}
          onPageChange={setPage}
          isLoading={isLoading}
          emptyMessage="No tenders match your filters."
        />
      )}
    </div>
  );
}
