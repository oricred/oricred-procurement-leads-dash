import { useState, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Award, ExternalLink } from 'lucide-react';
import { awardsApi, organizationsApi } from '../services/api';
import type { AwardItem } from '../types';
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

export default function AwardsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const [k, v] of searchParams.entries()) {
      if (k !== 'page') initial[k] = v;
    }
    return initial;
  });

  useEffect(() => {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(filters)) {
      if (v) params.set(k, v);
    }
    if (page > 1) params.set('page', String(page));
    setSearchParams(params, { replace: true });
  }, [filters, page, setSearchParams]);

  const queryParams = { ...filters, page, page_size: 50 };
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['awards', queryParams],
    queryFn: async () => {
      const res = await awardsApi.list(queryParams);
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

  const filterFields: FilterField[] = [
    { key: 'supplier', label: 'Supplier', type: 'text', placeholder: 'Search supplier' },
    {
      key: 'buyer_org_id', label: 'Buyer', type: 'select',
      options: orgs?.map(o => ({ label: o.name, value: o.id })) ?? [],
    },
    { key: 'date_from', label: 'Date from', type: 'date' },
    { key: 'date_to', label: 'Date to', type: 'date' },
    { key: 'value_min', label: 'Value min', type: 'number', placeholder: 'Min' },
    { key: 'value_max', label: 'Value max', type: 'number', placeholder: 'Max' },
    {
      key: 'source', label: 'Source', type: 'select',
      options: [
        { label: 'Tenders-SA', value: 'tenders_api' },
        { label: 'Municipal', value: 'municipal' },
      ],
    },
    { key: 'has_opportunity', label: 'Has opportunity', type: 'toggle' },
  ];

  const columns: ColumnDef[] = [
    {
      key: 'supplier_name', label: 'Supplier',
      render: (val: unknown, row: Record<string, unknown>) => (
        <button
          onClick={() => { setFilters(prev => ({ ...prev, supplier: val as string })); setPage(1); }}
          className="text-sm font-medium text-gray-200 hover:text-primary-400 transition-colors text-left"
        >
          {val as string ?? '—'}
        </button>
      ),
      width: '20%',
    },
    {
      key: 'buyer_org_name', label: 'Buyer',
      render: (val: unknown, row: Record<string, unknown>) => {
        const buyerId = row.buyer_org_id as string | null;
        return (
          <button
            onClick={() => { setFilters(prev => ({ ...prev, buyer_org_id: buyerId ?? '' })); setPage(1); }}
            className="text-xs text-gray-400 hover:text-primary-400 transition-colors text-left"
          >
            {(val as string) ?? '—'}
          </button>
        );
      },
      width: '18%',
    },
    {
      key: 'tender_title', label: 'Tender',
      render: (val: unknown) => (
        <span className="text-xs text-gray-400 block truncate max-w-[200px]" title={val as string ?? ''}>
          {val as string ?? '—'}
        </span>
      ),
      width: '25%',
    },
    {
      key: 'amount', label: 'Value',
      render: (val: unknown) => (
        <span className="text-sm font-mono text-gray-200 font-medium">{formatCurrency(val as number | null)}</span>
      ),
      className: 'text-right',
      width: '12%',
    },
    {
      key: 'award_date', label: 'Date',
      render: (val: unknown) => (
        <span className="text-xs text-gray-400">{formatDate(val as string | null)}</span>
      ),
      width: '12%',
    },
    {
      key: 'opportunity_id', label: 'Link',
      render: (val: unknown) => val ? (
        <button
          onClick={() => navigate(`/pipeline?open=${val as string}`)}
          className="text-primary-400 hover:text-primary-300 transition-colors"
          title="Open in Pipeline"
        >
          <ExternalLink className="w-3.5 h-3.5" />
        </button>
      ) : (
        <span className="text-gray-600">—</span>
      ),
      className: 'text-center',
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
        <Award className="w-5 h-5 text-primary-400" />
        <h2 className="text-lg font-semibold text-white">Awards</h2>
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
          <p className="text-sm text-red-400 mb-2">Failed to load awards.</p>
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
          emptyMessage="No awards match your filters."
        />
      )}
    </div>
  );
}
