import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from 'recharts';
import {
  Award, FileText, Target, Eye, Clock, TrendingUp, DollarSign, Activity,
} from 'lucide-react';
import { statsApi } from '../services/api';
import type { StatsData } from '../types';

const money = (v: number | null | undefined) =>
  v == null ? '—' : new Intl.NumberFormat('en-ZA', { style: 'currency', currency: 'ZAR', notation: 'compact' }).format(v);

const tooltipStyle = {
  contentStyle: { background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#f1f5f9', fontSize: '12px' } as const,
  itemStyle: { color: '#f1f5f9' } as const,
  labelStyle: { color: '#94a3b8' } as const,
};

const noopFormatter = undefined;

const CHART_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316', '#14b8a6'];

function StatCard({ label, value, icon: Icon, sub }: { label: string; value: string | number; icon: React.ElementType; sub?: string }) {
  return (
    <div className="glass p-4 flex items-center gap-3">
      <div className="w-10 h-10 rounded-lg bg-primary-400/10 flex items-center justify-center shrink-0">
        <Icon className="w-5 h-5 text-primary-400" />
      </div>
      <div className="min-w-0">
        <div className="text-lg font-semibold text-white">{value}</div>
        <div className="text-xs text-gray-400 truncate">{label}</div>
        {sub && <div className="text-xs text-gray-500">{sub}</div>}
      </div>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="glass p-4 flex items-center gap-3 animate-pulse">
      <div className="w-10 h-10 rounded-lg bg-surface-300/50" />
      <div className="space-y-2 flex-1">
        <div className="h-5 w-20 bg-surface-300/50 rounded" />
        <div className="h-3 w-32 bg-surface-300/50 rounded" />
      </div>
    </div>
  );
}

function ChartCard({ title, icon: Icon, children }: { title: string; icon: React.ElementType; children: React.ReactNode }) {
  return (
    <div className="glass p-4">
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-4 h-4 text-primary-400" />
        <h3 className="text-sm font-medium text-gray-200">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function EmptyChart({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-48 text-gray-500 text-sm">
      {message}
    </div>
  );
}

export default function StatsPage() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['stats'],
    queryFn: async () => (await statsApi.get()).data,
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="glass p-4 animate-pulse">
              <div className="h-4 w-32 bg-surface-300/50 rounded mb-3" />
              <div className="h-48 bg-surface-300/50 rounded" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="glass p-8 text-center text-red-400">
        Statistics could not load. <button onClick={() => refetch()} className="underline">Retry</button>
      </div>
    );
  }

  if (!data) return null;

  const sortedAwards = [...data.awards_per_year].reverse();
  const sortedTenders = [...data.tenders_per_year].reverse();
  const sortedAwardValue = [...data.award_value_per_year].reverse();
  const topBuyers = [...data.top_buyers].reverse();
  const topCats = [...data.top_categories].reverse();
  const stagesWithCounts = data.leads_per_stage.filter(s => s.count > 0);

  return (
    <div className="space-y-4">
      {/* Summary cards row 1 */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Total Awards" value={data.total_awards} icon={Award} />
        <StatCard label="Total Tenders" value={data.total_tenders} icon={FileText} />
        <StatCard label="Total Leads" value={data.total_leads} icon={Target} />
        <StatCard label="Watching" value={data.total_watching} icon={Eye} sub={`${data.past_due_count} past due`} />
      </div>

      {/* Summary cards row 2 */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Conversion Rate" value={`${data.conversion_rate.toFixed(1)}%`} icon={TrendingUp} sub={`${data.leads_from_awards} from awards`} />
        <StatCard label="Avg Award Value" value={money(data.avg_award_value)} icon={DollarSign} />
        <StatCard label="Total Award Value" value={money(data.total_award_value)} icon={Activity} />
        <StatCard label="Awarded Tenders" value={data.tenders_by_status.find(s => s.status === 'awarded')?.count ?? 0} icon={Clock} sub={`of ${data.total_tenders} total`} />
      </div>

      {/* Charts grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Awards per year */}
        <ChartCard title="Awards per Year" icon={Award}>
          {sortedAwards.length === 0 ? <EmptyChart message="No award data yet" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={sortedAwards}>
                <XAxis dataKey="year" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip {...tooltipStyle} />
                <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        {/* Tenders per year */}
        <ChartCard title="Tenders per Year" icon={FileText}>
          {sortedTenders.length === 0 ? <EmptyChart message="No tender data yet" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={sortedTenders}>
                <XAxis dataKey="year" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip {...tooltipStyle} />
                <Bar dataKey="count" fill="#10b981" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        {/* Award value per year */}
        <ChartCard title="Award Value per Year" icon={DollarSign}>
          {sortedAwardValue.length === 0 ? <EmptyChart message="No award value data yet" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={sortedAwardValue}>
                <XAxis dataKey="year" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v: number) => money(v)} />
                <Tooltip {...tooltipStyle} />
                <Bar dataKey="value" fill="#f59e0b" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        {/* Pipeline stage donut */}
        <ChartCard title="Pipeline Stage Distribution" icon={Target}>
          {stagesWithCounts.length === 0 ? <EmptyChart message="No pipeline data yet" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={stagesWithCounts}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  dataKey="count"
                  nameKey="stage"
                  paddingAngle={2}
                >
                  {stagesWithCounts.map((entry, index) => (
                    <Cell key={entry.stage} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip {...tooltipStyle} />
              </PieChart>
            </ResponsiveContainer>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1">
            {stagesWithCounts.map((s, i) => (
              <span key={s.stage} className="text-xs text-gray-400 flex items-center gap-1">
                <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }} />
                {s.stage.replace(/_/g, ' ')}: {s.count}
              </span>
            ))}
          </div>
        </ChartCard>

        {/* Top buyers */}
        <ChartCard title="Top Buyers by Award Count" icon={Activity}>
          {topBuyers.length === 0 ? <EmptyChart message="No buyer data yet" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={topBuyers} layout="vertical">
                <XAxis type="number" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="buyer_org_id" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} width={120} tickFormatter={(v: string) => v.length > 18 ? v.slice(0, 17) + '…' : v} />
                <Tooltip {...tooltipStyle} />
                <Bar dataKey="count" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        {/* Awards by province */}
        <ChartCard title="Awards by Province" icon={Activity}>
          {data.awards_by_province.length === 0 ? <EmptyChart message="No province data yet" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data.awards_by_province}>
                <XAxis dataKey="province" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v: string) => v.length > 10 ? v.slice(0, 9) + '…' : v} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip {...tooltipStyle} />
                <Bar dataKey="count" fill="#06b6d4" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        {/* Top categories */}
        <ChartCard title="Top Categories by Tender Count" icon={FileText}>
          {topCats.length === 0 ? <EmptyChart message="No category data yet" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={topCats} layout="vertical">
                <XAxis type="number" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="category_id" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} width={120} tickFormatter={(v: string) => v.length > 18 ? v.slice(0, 17) + '…' : v} />
                <Tooltip {...tooltipStyle} />
                <Bar dataKey="count" fill="#ec4899" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        {/* Awards by source */}
        <ChartCard title="Awards by Source" icon={Award}>
          {data.awards_by_source.length === 0 ? <EmptyChart message="No source data yet" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={data.awards_by_source}
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  dataKey="count"
                  nameKey="source"
                  paddingAngle={2}
                  labelLine={false}
                >
                  {data.awards_by_source.map((entry, index) => (
                    <Cell key={entry.source} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip {...tooltipStyle} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

      </div>
    </div>
  );
}
