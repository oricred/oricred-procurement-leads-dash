import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQueries, useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
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

function PhaseDroppable({ phase, items, total, onCardClick, onDecline }: {
  phase: string; stages: readonly Stage[]; items: Opportunity[]; total: number; onCardClick: (opp: Opportunity) => void; onDecline: (opp: Opportunity) => void;
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
        <span className="text-xs text-gray-500">{total}</span>
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

function collisionDetection(args: Parameters<CollisionDetection>[0]): ReturnType<CollisionDetection> {
  const pointerCollisions = pointerWithin(args);
  if (pointerCollisions.length > 0) return pointerCollisions;
  return closestCorners(args);
}

export default function PipelinePage() {
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const [selected, setSelected] = useState<Opportunity | null>(null);
  const [openTray, setOpenTray] = useState<string | null>(null);
  const [activeDrag, setActiveDrag] = useState<Opportunity | null>(null);
  const [declining, setDeclining] = useState<Opportunity | null>(null);
  const [dndError, setDndError] = useState<string | null>(null);

  const PHASE_LIMIT = 200;

  // One query per column. A single global page ordered by priority score pushed
  // late-stage deals (which often have no score) off the board entirely.
  const allPhases = Object.entries({ ...phases, ...terminalPhases });
  const phaseQueries = useQueries({
    queries: allPhases.map(([phase, stages]) => ({
      queryKey: ['opportunities', phase],
      queryFn: async () => (await opportunities.list({ stage: stages, limit: PHASE_LIMIT, offset: 0 })).data,
      // Seven columns polling at once, so pause while the tab is hidden and
      // refetch on focus instead. Award ingest runs every 30 minutes; 15s was
      // never a product requirement.
      refetchInterval: () => (document.visibilityState === 'visible' ? 60_000 : false),
      refetchOnWindowFocus: true,
    })),
  });
  const itemsByPhase = Object.fromEntries(
    allPhases.map(([phase], index) => [phase, phaseQueries[index]?.data?.items ?? []]),
  ) as Record<string, Opportunity[]>;
  const totalsByPhase = Object.fromEntries(
    allPhases.map(([phase], index) => [phase, phaseQueries[index]?.data?.total ?? 0]),
  ) as Record<string, number>;
  const isLoading = phaseQueries.some((q) => q.isLoading);

  // A deep-linked card may not be in any loaded page, so fetch it directly
  // rather than silently opening nothing.
  const openId = searchParams.get('open');
  const loadedOpen = openId
    ? Object.values(itemsByPhase).flat().find((x) => x.id === openId)
    : undefined;
  const { data: deepLinked } = useQuery({
    queryKey: ['opportunity', openId],
    queryFn: async () => (await opportunities.get(openId as string)).data,
    enabled: Boolean(openId) && !loadedOpen,
  });


  useEffect(() => {
    if (!openId) return;
    const found = loadedOpen ?? deepLinked;
    if (found) setSelected(found);
  }, [openId, loadedOpen, deepLinked]);

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
      // Each column is its own cache, so an optimistic move has to lift the card
      // out of one and drop it into another.
      const previous = allPhases.map(([phase]) => [phase, queryClient.getQueryData(['opportunities', phase])] as const);

      const moving = Object.values(itemsByPhase).flat().find((o) => o.id === id);
      let newStage: Stage | null = null;
      if (moving) {
        if (action === 'advance' || action === 'markContacted') {
          newStage = WORKFLOW_NEXT[moving.kanban_stage] ?? null;
        } else if (action === 'back') {
          const prev = Object.entries(WORKFLOW_NEXT).find(([, v]) => v === moving.kanban_stage);
          if (prev) newStage = prev[0] as Stage;
        } else if (action === 'decline') {
          newStage = 'lost_lead';
        }
      }

      if (moving && newStage) {
        const destination = allPhases.find(([, stages]) => stages.includes(newStage as Stage))?.[0];
        const moved = { ...moving, kanban_stage: newStage };
        for (const [phase] of allPhases) {
          queryClient.setQueryData(['opportunities', phase], (old: { items: Opportunity[]; total: number } | undefined) => {
            if (!old) return old;
            const without = old.items.filter((o) => o.id !== id);
            const items = phase === destination ? [moved, ...without] : without;
            return { ...old, items, total: old.total - (old.items.length - items.length) };
          });
        }
      }

      return { previous };
    },
    onError: (err, _vars, context) => {
      for (const [phase, snapshot] of context?.previous ?? []) {
        queryClient.setQueryData(['opportunities', phase], snapshot);
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

  const reportDropRefusal = (message: string) => {
    setDndError(message);
    setTimeout(() => setDndError(null), 5000);
  };

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
    if (!targetStages) {
      return reportDropRefusal('Drop a card onto one of the pipeline phases.');
    }

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
    } else {
      reportDropRefusal('Cards move one phase at a time — advance or backtrack step by step.');
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
                items={itemsByPhase[phase] ?? []}
                total={totalsByPhase[phase] ?? 0}
                onCardClick={setSelected}
                onDecline={(opp) => setDeclining(opp)}
              />
            ))}
          </div>

          {/* Terminal tray */}
          <div className="mt-5 space-y-2">
            {Object.entries(terminalPhases).map(([name]) => {
              const items = itemsByPhase[name] ?? [];
              const expanded = openTray === name;
              return (
                <section key={name} className="rounded-lg border border-surface-300">
                  <button
                    onClick={() => setOpenTray(expanded ? null : name)}
                    className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm text-gray-300"
                  >
                    {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    {name}
                    <span className="text-gray-600">{totalsByPhase[name] ?? 0}</span>
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
