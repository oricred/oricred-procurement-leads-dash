import { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, X } from 'lucide-react';
import { DndContext, DragOverlay, PointerSensor, useSensor, useSensors, useDroppable, pointerWithin, closestCorners, type DragStartEvent, type DragEndEvent, type CollisionDetection } from '@dnd-kit/core';
import { opportunities } from '../services/api';
import { STAGE_ORDER, WORKFLOW_NEXT, type Opportunity, type Stage } from '../types';
import OpportunityCard from '../components/OpportunityCard';
import OpportunityModal from '../components/OpportunityModal';
import HelpLink from '../components/HelpLink';

const phases: Record<string, Stage[]> = {
  'New Leads': ['new_lead'],
  Contacting: ['client_contacted'],
  Sales: ['qualified_lead', 'won_opportunity'],
  Credit: ['credit_preparation', 'credit_review', 'pre_approved', 'conditions_precedent'],
  'Deal Execution': ['term_sheet_sent', 'term_sheet_received', 'contracts_sent', 'contracts_received', 'ready_to_rff'],
};

const terminalPhases: Record<string, Stage[]> = {
  Funded: ['funded'],
  Lost: ['lost_lead'],
};

function PhaseDroppable({ phase, stages, items, onCardClick, onDecline }: {
  phase: string; stages: readonly Stage[]; items: Opportunity[]; onCardClick: (opp: Opportunity) => void; onDecline: (opp: Opportunity) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: phase });
  return (
    <section
      ref={setNodeRef}
      data-phase={phase}
      className={`rounded-xl border min-h-72 flex flex-col transition-colors ${
        isOver ? 'border-primary-500 bg-primary-500/5' : 'border-surface-300 bg-surface-200/50'
      }`}
    >
      <header className="flex items-center justify-between border-b border-surface-300 px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-200">{phase}</h3>
        <span className="text-xs text-gray-500">{items.length}</span>
      </header>
      <div className="flex-1 space-y-3 p-3">
        {items.map((opp) => (
          <div key={opp.id} className="group relative">
            <OpportunityCard opportunity={opp} onClick={() => onCardClick(opp)} />
            <button
              onClick={(e) => { e.stopPropagation(); onDecline(opp); }}
              className="absolute right-2 top-2 z-10 flex h-5 w-5 items-center justify-center rounded bg-red-500/80 text-white opacity-0 transition-opacity hover:bg-red-500 group-hover:opacity-100"
              title="Decline this opportunity"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
        {items.length === 0 && (
          <p className="py-8 text-center text-xs text-gray-600">No deals</p>
        )}
      </div>
    </section>
  );
}

function DecliningDialog({ opp, onConfirm, onCancel, pending }: {
  opp: Opportunity; onConfirm: (reason: string) => void; onCancel: () => void; pending: boolean;
}) {
  const [reason, setReason] = useState('');
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label="Decline opportunity">
      <div className="w-full max-w-md rounded-xl border border-surface-300 bg-surface-200 p-5 shadow-xl">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-white">Decline {opp.company_name ?? 'opportunity'}</h3>
          <button onClick={onCancel} disabled={pending} className="text-gray-500 hover:text-white"><X className="h-5 w-5" /></button>
        </div>
        <p className="mt-2 text-sm text-gray-400">This will move the opportunity to the Lost column. Record why.</p>
        <textarea
          autoFocus
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          className="mt-3 w-full rounded bg-surface-300 p-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-primary-500"
          placeholder="Reason for decline"
        />
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} disabled={pending} className="rounded px-3 py-1.5 text-xs text-gray-400 hover:text-white">Cancel</button>
          <button
            onClick={() => onConfirm(reason)}
            disabled={pending || !reason.trim()}
            className="rounded bg-red-600 px-3 py-1.5 text-xs text-white hover:bg-red-500 disabled:opacity-50"
          >
            {pending ? 'Moving…' : 'Confirm Decline'}
          </button>
        </div>
      </div>
    </div>
  );
}

const collisionDetection: CollisionDetection = useCallback((args) => {
  const pointerCollisions = pointerWithin(args);
  if (pointerCollisions.length > 0) return pointerCollisions;
  return closestCorners(args);
}, []);

export default function PipelinePage() {
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const [selected, setSelected] = useState<Opportunity | null>(null);
  const [openTray, setOpenTray] = useState<string | null>(null);
  const [activeDrag, setActiveDrag] = useState<Opportunity | null>(null);
  const [declining, setDeclining] = useState<Opportunity | null>(null);
  const [dndError, setDndError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['opportunities'],
    queryFn: async () => (await opportunities.list()).data,
    refetchInterval: 15_000,
  });

  useEffect(() => {
    const id = searchParams.get('open');
    if (id && data) setSelected(data.items.find((x) => x.id === id) ?? null);
  }, [searchParams, data]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['opportunities'] });
    queryClient.invalidateQueries({ queryKey: ['leads'] });
  };

  const dndTransition = useMutation({
    mutationFn: ({ id, action, version, lost_reason }: { id: string; action: 'advance' | 'back' | 'decline' | 'markContacted'; version: number; lost_reason?: string }) => {
      if (action === 'markContacted') {
        return opportunities.markContacted(id, { version });
      }
      if (action === 'decline') {
        return opportunities.transition(id, { action, version, lost_reason });
      }
      return opportunities.transition(id, { action, version, confirm: action === 'back' });
    },
    onMutate: async ({ id, action }) => {
      await queryClient.cancelQueries({ queryKey: ['opportunities'] });
      const previous = queryClient.getQueryData(['opportunities']);

      queryClient.setQueryData(['opportunities'], (old: { items: Opportunity[]; total: number } | undefined) => {
        if (!old) return old;
        return {
          ...old,
          items: old.items.map((o) => {
            if (o.id !== id) return o;
            let newStage: Stage | null = null;
            if (action === 'advance' || action === 'markContacted') {
              newStage = WORKFLOW_NEXT[o.kanban_stage] ?? null;
            } else if (action === 'back') {
              const prev = Object.entries(WORKFLOW_NEXT).find(([, v]) => v === o.kanban_stage);
              if (prev) newStage = prev[0] as Stage;
            } else if (action === 'decline') {
              newStage = 'lost_lead';
            }
            return newStage ? { ...o, kanban_stage: newStage } : o;
          }),
        };
      });

      return { previous };
    },
    onError: (err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['opportunities'], context.previous);
      }
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string }).response?.data?.detail
        ?? (err as { message?: string }).message
        ?? 'Transition failed';
      setDndError(msg);
      setTimeout(() => setDndError(null), 5000);
    },
    onSettled: () => {
      invalidate();
      setDeclining(null);
    },
  });

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  );

  const byPhase = useCallback((stages: readonly Stage[]) =>
    (data?.items ?? []).filter((o) => stages.includes(o.kanban_stage)),
  [data]);

  const handleDragStart = (event: DragStartEvent) => {
    const opp = (event.active.data.current as { opportunity?: Opportunity } | undefined)?.opportunity;
    if (!opp || opp.kanban_stage === 'funded' || opp.kanban_stage === 'lost_lead') return;
    setActiveDrag(opp);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveDrag(null);
    const opp = (event.active.data.current as { opportunity?: Opportunity } | undefined)?.opportunity;
    if (!opp) return;

    let targetPhase: string;
    if (event.over) {
      targetPhase = String(event.over.id);
    } else {
      const x = (event.activatorEvent as MouseEvent).clientX;
      const y = (event.activatorEvent as MouseEvent).clientY;
      targetPhase = document.elementsFromPoint(x, y)
        .find((el) => el.getAttribute('data-phase'))
        ?.getAttribute('data-phase') ?? '';
    }

    const targetStages = phases[targetPhase];
    if (!targetStages) return;

    const targetStage = targetStages[0];
    if (!targetStage || targetStage === opp.kanban_stage) return;

    const currentIdx = STAGE_ORDER.indexOf(opp.kanban_stage);
    const targetIdx = STAGE_ORDER.indexOf(targetStage);

    if (targetIdx === currentIdx + 1) {
      if (opp.kanban_stage === 'new_lead') {
        dndTransition.mutate({ id: opp.id, action: 'markContacted', version: opp.version });
      } else {
        dndTransition.mutate({ id: opp.id, action: 'advance', version: opp.version });
      }
    } else if (targetIdx === currentIdx - 1) {
      dndTransition.mutate({ id: opp.id, action: 'back', version: opp.version });
    }
  };

  const confirmDecline = (reason: string) => {
    if (!declining) return;
    const opp = declining;
    setDeclining(null);
    dndTransition.mutate({ id: opp.id, action: 'decline', version: opp.version, lost_reason: reason });
  };

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-white">Deal Pipeline</h2>
        <p className="text-xs text-gray-500">Drag cards between phases to advance or backtrack. Click a card for full detail and workflow actions.</p>
        <HelpLink section="deal-pipeline" />
      </div>

      {isLoading ? (
        <div className="text-sm text-gray-500">Loading pipeline…</div>
      ) : (
        <>
          {dndError && (
            <div className="mb-3 rounded bg-red-500/10 px-3 py-2 text-sm text-red-300">{dndError}</div>
          )}
          <DndContext sensors={sensors} collisionDetection={collisionDetection} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 xl:grid-cols-5">
            {Object.entries(phases).map(([phase, stages]) => (
              <PhaseDroppable
                key={phase}
                phase={phase}
                stages={stages}
                items={byPhase(stages)}
                onCardClick={setSelected}
                onDecline={(opp) => setDeclining(opp)}
              />
            ))}
          </div>

          {/* Terminal tray */}
          <div className="mt-5 space-y-2">
            {Object.entries(terminalPhases).map(([name, stages]) => {
              const items = byPhase(stages);
              const expanded = openTray === name;
              return (
                <section key={name} className="rounded-lg border border-surface-300">
                  <button
                    onClick={() => setOpenTray(expanded ? null : name)}
                    className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm text-gray-300"
                  >
                    {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    {name}
                    <span className="text-gray-600">{items.length}</span>
                  </button>
                  {expanded && (
                    <div className="grid grid-cols-1 gap-3 p-3 pt-0 md:grid-cols-3 xl:grid-cols-5">
                      {items.map((opp) => (
                        <OpportunityCard key={opp.id} opportunity={opp} onClick={() => setSelected(opp)} />
                      ))}
                      {items.length === 0 && (
                        <p className="col-span-full py-4 text-center text-xs text-gray-600">None</p>
                      )}
                    </div>
                  )}
                </section>
              );
            })}
          </div>

          {/* Drag overlay */}
          <DragOverlay>
            {activeDrag && <OpportunityCard opportunity={activeDrag} onClick={() => {}} isOverlay />}
          </DragOverlay>
        </DndContext>
          </>      )}

      {selected && <OpportunityModal opportunity={selected} onClose={() => setSelected(null)} />}

      {declining && (
        <DecliningDialog
          opp={declining}
          onCancel={() => setDeclining(null)}
          onConfirm={confirmDecline}
          pending={dndTransition.isPending}
        />
      )}
    </div>
  );
}
