import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { watchlist } from '../services/api';
import { Eye, Clock, CheckCircle2, ExternalLink, ChevronDown, ChevronUp } from 'lucide-react';
import { useState } from 'react';

const statusIcons: Record<string, typeof Clock> = {
  watching: Clock,
  awarded: CheckCircle2,
};

const statusColors: Record<string, string> = {
  watching: 'text-blue-400',
  awarded: 'text-emerald-400',
};

const labelColors: Record<string, string> = {
  'On Track': 'text-emerald-400',
  'Approaching Window': 'text-amber-400',
  'Past Due': 'text-red-400',
};

const labelBgs: Record<string, string> = {
  'On Track': 'bg-emerald-500/10 border-emerald-500/20',
  'Approaching Window': 'bg-amber-500/10 border-amber-500/20',
  'Past Due': 'bg-red-500/10 border-red-500/20',
};

function formatCurrency(value: number | null): string {
  if (!value) return '—';
  if (value >= 1_000_000) return `R${(value / 1_000_000).toFixed(1)}M`;
  return `R${(value / 1_000).toFixed(0)}K`;
}

export default function MatchingPage() {
  const navigate = useNavigate();
  const [showAwarded, setShowAwarded] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['watchlist'],
    queryFn: async () => {
      const res = await watchlist.list();
      return res.data;
    },
    refetchInterval: 30_000,
  });

  const watching = data?.items.filter(i => i.status === 'watching') ?? [];
  const awarded = data?.items.filter(i => i.status === 'awarded') ?? [];

  return (
    <div>
      <div className="flex items-center gap-2 mb-6">
        <Eye className="w-5 h-5 text-primary-400" />
        <h2 className="text-lg font-semibold text-white">Matching Board</h2>
        <span className="text-xs px-2 py-0.5 rounded-full bg-surface-300 text-gray-400">
          {watching.length} watching
        </span>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-64 text-gray-500">Loading...</div>
      ) : watching.length === 0 && awarded.length === 0 ? (
        <div className="glass rounded-xl p-12 text-center">
          <Eye className="w-8 h-8 text-gray-600 mx-auto mb-3" />
          <p className="text-gray-500">No tenders being watched</p>
          <p className="text-sm text-gray-600 mt-1">Browse tenders to start watching qualified opportunities.</p>
        </div>
      ) : (
        <>
          {/* Watching Section */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 mb-6">
            {watching.map((item) => {
              const StatusIcon = statusIcons.watching;
              return (
                <div key={item.id} className="glass rounded-xl p-4 card-hover">
                  <div className="flex items-start justify-between mb-3">
                    <p className="text-sm font-medium text-gray-200 line-clamp-2 flex-1 mr-2">
                      {item.title}
                    </p>
                    <StatusIcon className="w-4 h-4 flex-shrink-0 text-blue-400" />
                  </div>

                  <div className="flex items-center gap-3 text-xs text-gray-500 mb-3">
                    <span className="font-mono font-semibold text-gray-300">{formatCurrency(item.estimated_value)}</span>
                                          {item.category_name && <span className="uppercase">{item.category_name}</span>}
                      {item.province && <span>{item.province}</span>}
                    </div>

                    <p className="text-xs text-gray-600 truncate mb-3">{item.buyer_org}</p>

                  {item.progress_pct != null && (
                    <div className="mb-3">
                      <div className="h-1.5 bg-surface-400 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${
                            item.label === 'Approaching Window' ? 'bg-amber-500' : 'bg-emerald-500'
                          }`}
                          style={{ width: `${Math.min(100, item.progress_pct)}%` }}
                        />
                      </div>
                    </div>
                  )}

                  <div className="flex items-center justify-between">
                    <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full border ${labelBgs[item.label] ?? 'bg-surface-300 border-surface-400'} ${labelColors[item.label] ?? 'text-gray-400'}`}>
                      {item.label}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-600">
                        {item.days_until_window != null
                          ? `${item.days_until_window}d until window`
                          : item.closing_date
                          ? `Closing ${new Date(item.closing_date).toLocaleDateString()}`
                          : ''}
                      </span>
                      <button
                        onClick={() => navigate('/tenders')}
                        className="text-[11px] text-primary-400 hover:text-primary-300 transition-colors"
                      >
                        View in Tenders
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Awarded Section */}
          {awarded.length > 0 && (
            <div className="glass rounded-xl overflow-hidden">
              <button
                onClick={() => setShowAwarded(!showAwarded)}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface-300/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  <span className="text-sm font-medium text-gray-200">Awarded</span>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-surface-300 text-gray-400">
                    {awarded.length}
                  </span>
                </div>
                {showAwarded ? (
                  <ChevronUp className="w-4 h-4 text-gray-500" />
                ) : (
                  <ChevronDown className="w-4 h-4 text-gray-500" />
                )}
              </button>

              {showAwarded && (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 p-4 border-t border-surface-300">
                  {awarded.map((item) => {
                    const StatusIcon = statusIcons.awarded;
                    return (
                      <div key={item.id} className="bg-surface-300 rounded-xl p-4">
                        <div className="flex items-start justify-between mb-3">
                          <p className="text-sm font-medium text-gray-200 line-clamp-2 flex-1 mr-2">
                            {item.title}
                          </p>
                          <StatusIcon className="w-4 h-4 flex-shrink-0 text-emerald-400" />
                        </div>

                        <div className="flex items-center gap-3 text-xs text-gray-500 mb-3">
                          <span className="font-mono font-semibold text-gray-300">{formatCurrency(item.estimated_value)}</span>
                          {item.category_name && <span className="uppercase">{item.category_name}</span>}
                          {item.province && <span>{item.province}</span>}
                        </div>

                        <p className="text-xs text-gray-600 truncate mb-3">{item.buyer_org}</p>

                        {item.progress_pct != null && (
                          <div className="mb-3">
                            <div className="h-1.5 bg-surface-400 rounded-full overflow-hidden">
                              <div
                                className="h-full rounded-full bg-emerald-500"
                                style={{ width: `${Math.min(100, item.progress_pct)}%` }}
                              />
                            </div>
                          </div>
                        )}

                        <div className="flex items-center justify-between">
                          <span className="text-[11px] text-emerald-400 font-medium">
                            Awarded
                          </span>
                          {item.opportunity_id ? (
                            <button
                              onClick={() => navigate(`/pipeline?open=${item.opportunity_id}`)}
                              className="flex items-center gap-1 text-[11px] text-primary-400 hover:text-primary-300 transition-colors"
                            >
                              <ExternalLink className="w-3 h-3" /> Open in Pipeline
                            </button>
                          ) : (
                            <button
                              onClick={() => navigate('/tenders')}
                              className="text-[11px] text-primary-400 hover:text-primary-300 transition-colors"
                            >
                              View in Tenders
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
