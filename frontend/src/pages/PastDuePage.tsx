import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Clock, AlertTriangle, Building2, MapPin, DollarSign } from 'lucide-react';
import { pastDueQueue } from '../services/api';

export default function PastDuePage() {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ['past-due'],
    queryFn: async () => {
      const res = await pastDueQueue.list();
      return res.data.items;
    },
    refetchInterval: 30_000,
  });

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <div className="flex items-center gap-3 mb-6">
        <Clock className="w-6 h-6 text-amber-400" />
        <h1 className="text-xl font-bold text-white">Past-Due Queue</h1>
        {data && (
          <span className="bg-amber-500/20 text-amber-400 text-xs px-2 py-0.5 rounded-full">
            {data.length} items
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="text-gray-500 text-sm">Loading...</div>
      ) : !data || data.length === 0 ? (
        <div className="glass rounded-xl p-8 text-center">
          <AlertTriangle className="w-8 h-8 text-gray-600 mx-auto mb-2" />
          <p className="text-sm text-gray-500">No past-due items</p>
        </div>
      ) : (
        <div className="space-y-3">
          {data.map((item) => (
            <div key={item.id} className="glass rounded-xl p-4">
              <div className="flex items-start justify-between mb-2">
                <h3 className="text-sm font-semibold text-gray-200">{item.tender_title}</h3>
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  item.resolution === 'pending'
                    ? 'bg-amber-500/20 text-amber-400'
                    : item.resolution === 'resolved'
                    ? 'bg-emerald-500/20 text-emerald-400'
                    : 'bg-red-500/20 text-red-400'
                }`}>
                  {item.resolution}
                </span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs text-gray-400">
                {item.estimated_value != null && (
                  <div className="flex items-center gap-1">
                    <DollarSign className="w-3 h-3" />
                    <span>R{(item.estimated_value / 1_000_000).toFixed(1)}M</span>
                  </div>
                )}
                {item.province && (
                  <div className="flex items-center gap-1">
                    <MapPin className="w-3 h-3" />
                    <span>{item.province}</span>
                  </div>
                )}
                {item.buyer_org && (
                  <div className="flex items-center gap-1">
                    <Building2 className="w-3 h-3" />
                    <span>{item.buyer_org}</span>
                  </div>
                )}
                <div className="flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  <span>{item.days_in_queue}d in queue</span>
                </div>
              </div>
              <div className="mt-3 flex justify-end">
                <button onClick={() => navigate(item.opportunity_id ? `/pipeline?open=${item.opportunity_id}` : `/discover?tab=tenders&status=past_due`)} className="text-xs text-primary-400 hover:text-primary-300">
                  {item.opportunity_id ? 'Open lead' : 'View tender queue'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
