import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { DndContext, DragEndEvent, DragOverlay, DragStartEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { opportunities } from '../services/api';
import { STAGES, STAGE_LABELS, type Opportunity, type Stage } from '../types';
import KanbanColumn from '../components/KanbanColumn';
import OpportunityCard from '../components/OpportunityCard';
import OpportunityModal from '../components/OpportunityModal';
import AwardRadar from '../components/AwardRadar';

export default function PipelinePage() {
  const [searchParams] = useSearchParams();
  const [activeCard, setActiveCard] = useState<Opportunity | null>(null);
  const [selectedOpp, setSelectedOpp] = useState<Opportunity | null>(null);
  const [showRadar, setShowRadar] = useState(true);
  const queryClient = useQueryClient();

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 5 },
    }),
  );

  const { data, isLoading } = useQuery({
    queryKey: ['opportunities'],
    queryFn: async () => {
      const res = await opportunities.list();
      return res.data;
    },
    refetchInterval: 15_000,
  });

  const stageMutation = useMutation({
    mutationFn: ({ id, stage, version }: { id: string; stage: string; version: number }) =>
      opportunities.updateStage(id, stage, version),
    onMutate: async ({ id, stage }) => {
      await queryClient.cancelQueries({ queryKey: ['opportunities'] });
      const previous = queryClient.getQueryData<{ items: Opportunity[]; total: number }>(['opportunities']);
      if (previous) {
        queryClient.setQueryData(['opportunities'], {
          ...previous,
          items: previous.items.map((o) =>
            o.id === id ? { ...o, kanban_stage: stage } : o
          ),
        });
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['opportunities'], context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['opportunities'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
    },
  });

  useEffect(() => {
    const openId = searchParams.get('open');
    if (openId && data?.items) {
      const opp = data.items.find(o => o.id === openId);
      if (opp) setSelectedOpp(opp);
    }
  }, [searchParams, data]);

  const grouped: Record<string, Opportunity[]> = {};
  for (const stage of STAGES) {
    grouped[stage] = [];
  }
  for (const opp of data?.items ?? []) {
    if (grouped[opp.kanban_stage]) {
      grouped[opp.kanban_stage].push(opp);
    }
  }

  const handleDragStart = (event: DragStartEvent) => {
    const opp = data?.items.find((o) => o.id === event.active.id);
    if (opp) setActiveCard(opp);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveCard(null);
    const { active, over } = event;
    if (!over) return;

    const oppId = active.id as string;
    const newStage = over.id as Stage;

    const opp = data?.items.find((o) => o.id === oppId);
    if (!opp || opp.kanban_stage === newStage) return;

    stageMutation.mutate({ id: oppId, stage: newStage, version: opp.version });
  };

  return (
    <div className="flex gap-6 h-full">
      {/* Kanban */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">Opportunity Pipeline</h2>
          <button
            onClick={() => setShowRadar(!showRadar)}
            className="text-xs text-gray-400 hover:text-gray-200 transition-colors"
          >
            {showRadar ? 'Hide Radar' : 'Show Radar'}
          </button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center h-64 text-gray-500">Loading...</div>
        ) : (
          <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
            <div className="flex gap-4 overflow-x-auto pb-4 h-[calc(100vh-10rem)]">
              {STAGES.filter((s) => s !== 'closed').map((stage) => (
                <KanbanColumn
                  key={stage}
                  stage={stage}
                  label={STAGE_LABELS[stage]}
                  count={grouped[stage]?.length ?? 0}
                  items={grouped[stage] ?? []}
                  onCardClick={setSelectedOpp}
                />
              ))}
            </div>

            <DragOverlay dropAnimation={null}>
              {activeCard ? (
                <OpportunityCard opportunity={activeCard} onClick={() => {}} isOverlay />
              ) : null}
            </DragOverlay>
          </DndContext>
        )}
      </div>

      {showRadar && <AwardRadar />}

      {selectedOpp && (
        <OpportunityModal opportunity={selectedOpp} onClose={() => setSelectedOpp(null)} />
      )}
    </div>
  );
}
