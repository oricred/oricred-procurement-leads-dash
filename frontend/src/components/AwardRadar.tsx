import { useQuery } from '@tanstack/react-query';
import { radar } from '../services/api';
import { Activity, AlertTriangle, TrendingUp } from 'lucide-react';

export default function AwardRadar() {
  const { data, isLoading } = useQuery({
    queryKey: ['radar'],
    queryFn: async () => {
      const res = await radar.get();
      return res.data;
    },
    refetchInterval: 30_000,
  });

  return (
    <aside className="w-80 flex-shrink-0 flex flex-col gap-4">
      {/* Past-Due Counter */}
      <div className="glass rounded-xl p-4">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            Past-Due Queue
          </div>
          <span className={`text-lg font-bold font-mono ${(data?.past_due_count ?? 0) > 0 ? 'text-amber-400' : 'text-gray-500'}`}>
            {data?.past_due_count ?? 0}
          </span>
        </div>
        <p className="text-[10px] text-gray-600">Awards past expected window</p>
      </div>

      {/* Award Feed */}
      <div className="glass rounded-xl flex-1 flex flex-col overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-surface-300">
          <Activity className="w-4 h-4 text-primary-400" />
          <h3 className="text-sm font-semibold text-gray-200">7-Day Award Feed</h3>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {isLoading ? (
            <div className="text-xs text-gray-600 text-center py-8">Loading...</div>
          ) : data?.awards.length === 0 ? (
            <div className="text-xs text-gray-600 text-center py-8">No awards in last 7 days</div>
          ) : (
            data?.awards.map((award) => (
              <div key={award.id} className="bg-surface-300 rounded-lg p-3 border border-surface-400">
                <p className="text-xs font-medium text-gray-200 truncate">{award.tender_title}</p>
                <p className="text-xs text-gray-500 truncate">{award.supplier_name}</p>
                <div className="flex items-center justify-between mt-1.5 text-[11px]">
                  <span className="text-gray-400 font-mono">
                    {award.amount ? `R${(award.amount / 1_000).toFixed(0)}K` : '—'}
                  </span>
                  <span className="text-gray-600">
                    {award.award_date ? new Date(award.award_date).toLocaleDateString() : ''}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </aside>
  );
}
