import { useDroppable } from '@dnd-kit/core';
import type { Opportunity, Stage } from '../types';
import OpportunityCard from './OpportunityCard';

interface Props {
  stage: Stage;
  label: string;
  count: number;
  items: Opportunity[];
  onCardClick: (opp: Opportunity) => void;
}

export default function KanbanColumn({ stage, label, count, items, onCardClick }: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: stage });

  return (
    <div
      ref={setNodeRef}
      className={`flex-shrink-0 w-72 flex flex-col rounded-xl border transition-colors ${
        isOver ? 'border-primary-500/50 bg-primary-500/5' : 'border-surface-300 bg-surface-200/50'
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-300">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-gray-200">{label}</h3>
          <span className="text-xs px-2 py-0.5 rounded-full bg-surface-300 text-gray-400">{count}</span>
        </div>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 min-h-[200px]">
        {items.map((opp) => (
          <OpportunityCard key={opp.id} opportunity={opp} onClick={() => onCardClick(opp)} />
        ))}

        {items.length === 0 && (
          <div className="flex items-center justify-center h-20 text-xs text-gray-600 border border-dashed border-surface-300 rounded-lg">
            Drop cards here
          </div>
        )}
      </div>
    </div>
  );
}
