import { useDraggable } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import type { Opportunity } from '../types';
import { clsx } from 'clsx';

interface Props {
  opportunity: Opportunity;
  onClick: () => void;
  isOverlay?: boolean;
}

const sufficiencyIcons: Record<string, string> = {
  sufficient: '✓',
  role_based: '⚠',
  none: '✗',
};

const sufficiencyColors: Record<string, string> = {
  sufficient: 'text-emerald-400',
  role_based: 'text-amber-400',
  none: 'text-red-400',
};

const riskColors: Record<string, string> = {
  green: 'bg-emerald-500',
  amber: 'bg-amber-500',
  red: 'bg-red-500',
};

const fundingColors: Record<string, string> = {
  high: 'text-emerald-400',
  medium: 'text-amber-400',
  low: 'text-red-400',
};

function fundingLabel(score: number | null): { label: string; color: string } | null {
  if (score == null) return null;
  if (score >= 75) return { label: 'High', color: fundingColors.high };
  if (score >= 50) return { label: 'Med', color: fundingColors.medium };
  return { label: 'Low', color: fundingColors.low };
}

function formatCurrency(value: number | null): string {
  if (!value) return '—';
  if (value >= 1_000_000) return `R${(value / 1_000_000).toFixed(1)}M`;
  return `R${(value / 1_000).toFixed(0)}K`;
}

function CardContent({ opportunity: opp }: { opportunity: Opportunity }) {
  return (
    <>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <span className={clsx('text-xs font-mono font-bold', sufficiencyColors[opp.contact_sufficiency ?? 'none'])}>
            {sufficiencyIcons[opp.contact_sufficiency ?? 'none']}
          </span>
          <span className={clsx('w-2 h-2 rounded-full', riskColors[opp.risk_flag ?? 'green'])} />
        </div>
        <span className="text-sm font-semibold text-white font-mono">
          {formatCurrency(opp.award_value)}
        </span>
        {(() => {
          const badge = fundingLabel(opp.funding_suitability);
          return badge ? (
            <span className={`text-[10px] px-1.5 py-0.5 rounded bg-surface-400 font-mono font-bold ${badge.color}`}>
              {badge.label}
            </span>
          ) : null;
        })()}
        {opp.buyer_preference_score != null && opp.buyer_preference_score >= 70 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400 font-mono font-bold">
            P{opp.buyer_preference_score >= 90 ? '★' : ''}
          </span>
        )}
        {opp.category && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-400 text-gray-400 uppercase">
            {opp.category.slice(0, 4)}
          </span>
        )}
      </div>

      <p className="text-sm font-medium text-gray-200 truncate mb-0.5">
        {opp.company_name ?? 'Unknown Company'}
      </p>

      <p className="text-xs text-gray-500 truncate mb-2">
        {opp.buyer_org ?? ''}
      </p>

      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>{opp.province ?? ''}</span>
        {opp.days_since_award !== null && (
          <span>{opp.days_since_award}d</span>
        )}
      </div>

      {opp.assigned_to && (
        <div className="mt-1.5 pt-1.5 border-t border-surface-400 text-xs text-gray-500">
          {opp.assigned_to}
        </div>
      )}
    </>
  );
}

export default function OpportunityCard({ opportunity: opp, onClick, isOverlay }: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: opp.id,
    data: { opportunity: opp },
  });

  const style = transform ? { transform: CSS.Translate.toString(transform) } : undefined;

  if (isOverlay) {
    return (
      <div className="bg-surface-300 rounded-lg border border-surface-400 p-3 shadow-xl w-72">
        <CardContent opportunity={opp} />
      </div>
    );
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      onClick={onClick}
      className={clsx(
        'bg-surface-300 rounded-lg border border-surface-400 p-3 cursor-grab active:cursor-grabbing card-hover',
        isDragging && 'opacity-50 ring-2 ring-primary-500/30',
      )}
    >
      <CardContent opportunity={opp} />
    </div>
  );
}
