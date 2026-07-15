# Oricred Normalized Workflow Specification

**Status:** Canonical reference · **Version:** 1.0 · **Last updated:** 2026-07-03

> **Purpose.** This document normalizes the Oricred *Lead Generation & Transaction
> Funding* process into a single, unambiguous state model. It is the source of
> truth for interface design: every board, column, badge, detail panel, and
> transition control in the application should map back to a stage, transition,
> or attribute defined here. Where the application as it currently stands
> diverges from this model, the gap is documented in
> [§7 Current vs. Target](#7-current-vs-target-gap-analysis) so the interface can
> be brought into alignment.

---

## 1. Scope & orientation

The process is **lead-driven**: an item enters the pipeline as a *lead* and moves
left-to-right through **sales qualification**, **credit assessment**, and **deal
execution & funding**, ending in one of two terminal states — **Funded** (success)
or **Lost / Declined** (exit).

This differs in orientation from the platform's current *award-driven* kanban,
where an item is only created **after** an award is detected. The normalized model
below is the target; §7 explains how to reconcile the two without discarding the
award-tracking machinery that already exists (discovery, watchlist, award radar).

Three vocabulary rules keep the model unambiguous:

| Concept | Definition |
|---|---|
| **Stage** | A durable, persisted position in the pipeline. Exactly one stage is active per item at any time. Stages are the columns of the board. |
| **Gate** | A *decision* between stages (e.g. "Qualified?"). A gate is **not** a persisted stage; it is a transition rule that routes an item to one of several next stages. Gates are rendered as actions/branches, never as columns. |
| **Attribute** | Orthogonal state that can change independently of the stage (e.g. `assigned_to`, `risk_flag`, `credit_decision`). Attributes decorate a card; they do not move it. |

---

## 2. Pipeline phases

Stages are grouped into three phases. Phases are the primary visual grouping for
the board (swimlane bands or column-group headers).

| # | Phase | Owner | Stages |
|---|---|---|---|
| **A** | Lead Generation & Qualification | Sales | New Lead → Client Contacted → *(Qualified? gate)* → Won Opportunity |
| **B** | Credit Assessment | Credit | Credit Preparation → Credit Review → *(Credit Decision gate)* |
| **C** | Deal Execution & Funding | Deal / Legal | Term Sheet Sent → Term Sheet Received → Contracts Sent → Contracts Received → Ready to RFF → Funded |

Terminal states (**Lost / Declined**, **Funded**) belong to no phase; they are
end-of-life and render distinctly (see §5).

---

## 3. Canonical stages

Every stage has a stable machine `id` (snake_case, for the database, API, and DnD
keys), a human `label`, the phase it belongs to, and its entry/exit meaning. The
`id` values are the contract — labels and colours may be re-skinned, ids may not.

| Order | `id` | Label | Phase | Meaning / entry criteria | Exit / done criteria |
|---|---|---|---|---|---|
| 1 | `new_lead` | New Lead | A | Lead received from referral, marketing, or the tender/award pipeline. Not yet worked. | Owner assigned and first outreach attempted. |
| 2 | `client_contacted` | Client Contacted | A | Initial engagement and needs assessment underway. | Enough is known to run the qualification gate. |
| — | *(gate)* | **Qualified?** | A | Assess fit, funding need, and eligibility. | Routes to `won` (yes) or `lost` (no). |
| 3 | `won` | Won Opportunity | A | Client is qualified and proceeds with Oricred. Deal is "won" for the sales team; credit work begins. | Handover to Credit; documents requested. |
| 4 | `credit_preparation` | Credit Preparation | B | Collect documents and prepare the credit paper. | Credit paper complete and submitted to committee. |
| 5 | `credit_review` | Credit Review | B | Credit Committee assessment in progress. | Committee reaches a decision. |
| — | *(gate)* | **Credit Decision** | B | Committee outcome. | Routes to `pre_approved`, `conditions_precedent`, or `lost` (declined). |
| 6 | `pre_approved` | Pre-Approved | B→C | Approved clean, no conditions. | Proceed to issue term sheet. |
| 7 | `conditions_precedent` | Conditions Precedent | B→C | Approved **subject to conditions** that must be cleared before terms/funding. | All conditions satisfied. |
| 8 | `term_sheet_sent` | Term Sheet Sent | C | Commercial terms issued to client. | Client responds. |
| 9 | `term_sheet_received` | Term Sheet Received | C | Client accepts terms (signed term sheet returned). | Move to contracting. |
| 10 | `contracts_sent` | Contracts Sent | C | Legal agreements issued. | Client executes. |
| 11 | `contracts_received` | Contracts Received | C | Executed agreements returned. | Ready for final funding checks. |
| 12 | `ready_to_rff` | Ready to RFF | C | Ready for Request for Funding and final checks. | RFF approved / disbursed. |
| 13 | `funded` | Funded | — (terminal ✔) | Funds disbursed. Successful terminal state. | — |
| ✗ | `lost` | Lost / Declined | — (terminal ✗) | Exited: unqualified lead **or** credit-declined **or** withdrawn. Records a `lost_reason`. | — |

> **Note on `pre_approved` vs `conditions_precedent`.** Both are approval outcomes
> and both feed the term-sheet path — they are modelled as two stages (not one)
> because the interface must make the *presence of outstanding conditions* visible
> and actionable. A `conditions_precedent` item should surface a conditions
> checklist; a `pre_approved` item should not. If the team prefers a single
> `credit_approved` stage, collapse the two and move the clean/conditional
> distinction to a `credit_decision` attribute (§4) — but the default is two
> stages.

---

## 4. Orthogonal attributes

These decorate an item and change independently of the stage. The interface should
render them as badges/fields on the card and in the detail panel — **never** as
columns, and moving a card must not silently reset them.

| Attribute | Values | Applies from | Interface treatment |
|---|---|---|---|
| `assigned_to` | user / null | `new_lead` | Owner avatar on card; assignment control in panel. |
| `credit_decision` | `pre_approved` \| `conditions_precedent` \| `declined` \| null | after `credit_review` | Decision chip; drives which approval stage the item enters. |
| `risk_flag` | `green` \| `amber` \| `red` \| null | any | Coloured dot; sortable/filterable. |
| `contact_sufficiency` | `sufficient` \| `role_based` \| `none` \| null | `client_contacted`+ | Icon indicating quality of the buyer/client contact. |
| `lost_reason` | free text / enum | `lost` only | Required when routing to `lost`; shown on the terminal card. |
| Scores | `win_probability`, `funding_suitability`, `buyer_preference_score` | any | Numeric badges; do not gate transitions. |

---

## 5. State machine — allowed transitions

The board is a **linear pipeline with two gates and two terminals**. Forward moves
follow the order in §3. The rules below are the contract for what the UI must
allow, block, or confirm.

```
new_lead → client_contacted → [Qualified?] ─ yes → won
                                           └ no  → lost ✗

won → credit_preparation → credit_review → [Credit Decision]
                                              ├ pre_approved ──────────┐
                                              ├ conditions_precedent ──┤
                                              └ declined → lost ✗      │
                                                                       ▼
                         (conditions cleared / clean)          term_sheet_sent
                                                                       ▼
                                                              term_sheet_received
                                                                       ▼
                                                                 contracts_sent
                                                                       ▼
                                                               contracts_received
                                                                       ▼
                                                                  ready_to_rff
                                                                       ▼
                                                                    funded ✔
```

**Transition rules the interface must enforce:**

1. **Forward-by-one is the default.** Dragging/advancing normally moves an item to
   the next stage in its path.
2. **Gates require an explicit choice.** Leaving `client_contacted` prompts the
   Qualified? decision; leaving `credit_review` prompts the Credit Decision. The UI
   must not let an item silently skip a gate.
3. **Convergence at term sheet.** Both `pre_approved` and `conditions_precedent`
   lead to `term_sheet_sent`; `conditions_precedent` must have its conditions
   marked cleared before that advance is permitted.
4. **Lost is reachable from any active stage**, not only the qualification gate — a
   deal can fall away or be declined late. Routing to `lost` requires a
   `lost_reason`.
5. **Backward moves are allowed but audited** (e.g. term sheet needs re-issue).
   Terminal stages (`funded`, `lost`) are **not** draggable back into the pipeline;
   reopening is a deliberate, confirmed action, not a drag.
6. **Every transition is audit-logged** (`from_stage`, `to_stage`, actor,
   timestamp) — the mechanism already exists in `opportunity_audit`.

---

## 6. Interface design principles

Derived directly from the model above. These are the acceptance criteria for the
interface work this document exists to guide.

1. **One board, three phase bands.** Render the twelve active stages as columns,
   visually grouped under the Phase A / B / C headers of §2. Phase boundaries are
   the natural handover points (Sales → Credit → Deal) and should read as such.
2. **Gates are actions, not columns.** "Qualified?" and "Credit Decision" never
   appear as columns. They surface as a branch prompt when an item leaves the
   preceding stage (a modal or split drop-target), capturing the outcome attribute.
3. **Terminals are distinct.** `funded` and `lost` render outside the main flow
   (e.g. a collapsed success/exit tray or end caps), styled differently from active
   work so the live pipeline isn't diluted by closed items.
4. **Conditions are first-class.** A `conditions_precedent` card shows a conditions
   checklist and blocks advance to `term_sheet_sent` until all are cleared.
5. **Attributes decorate, stages move.** Owner, risk, credit decision, contact
   sufficiency, and scores are badges — they must not be modelled as columns, and a
   stage move must preserve them.
6. **Labels are re-skinnable, ids are not.** The interface binds to the stage `id`
   values in §3; display labels/colours may be themed without touching logic.
7. **Illegal moves are prevented, legal-but-notable moves are confirmed.**
   Skipping a gate is blocked; backward moves and reopening terminals prompt
   confirmation and are logged.
8. **Every card traces to its origin.** A lead sourced from the tender/award
   pipeline keeps a link back to its tender/award/watchlist record, so the sales
   view and the existing award radar stay connected.

---

## 7. Current vs. target — gap analysis

The application today implements a generic 7-stage kanban:

```
new → assigned → contacted → in_discussion → application_received → funded → closed
```

Defined in `frontend/src/types/index.ts` (`Stage`, `STAGES`, `STAGE_LABELS`,
`STAGE_COLORS`) and persisted as `opportunities.kanban_stage`
(`backend/app/models/opportunity.py`). Mapping to the normalized model:

| Current stage | Normalized target | Action |
|---|---|---|
| `new` | `new_lead` | Rename; semantics shift from "award detected" to "lead received". |
| `assigned` | *(attribute `assigned_to`)* | **Demote to attribute** — assignment is orthogonal, not a stage/column. |
| `contacted` | `client_contacted` | Rename. |
| `in_discussion` | `won` | Re-map to the qualification outcome; add the **Qualified?** gate before it. |
| `application_received` | `credit_preparation` → `contracts_received` | Split — the single stage collapses the entire credit + contracting flow that the target expands. |
| `funded` | `funded` | Keep; now a terminal, not a mid-board column. |
| `closed` | `lost` (and `funded` for success) | Split terminal into success vs. exit; require `lost_reason`. |

**Missing entirely (must be added):** `won` gate, `credit_preparation`,
`credit_review`, the Credit Decision gate, `pre_approved`,
`conditions_precedent`, `term_sheet_sent`, `term_sheet_received`,
`contracts_sent`, `contracts_received`, `ready_to_rff`, and the
`credit_decision` / `lost_reason` attributes.

**Orientation gap:** opportunities are currently created *only* on award
detection (`backend/app/jobs/award_check.py`). To honour the lead-driven model,
a lead must be able to originate before/without an award (referral, marketing,
manual entry), with award-sourced items entering at `new_lead` carrying their
tender/award linkage. The discovery, watchlist, timing, and award-radar features
remain valid as **lead sources** feeding the top of this pipeline — they do not
need to be removed, only connected.

**Reusable as-is:** optimistic-concurrency `version` field, the
`opportunity_audit` trail, contact-sufficiency and scoring attributes, and the
drag-and-drop board shell — all map cleanly onto the normalized model.

---

## 8. Implementation checklist (for the interface work)

- [ ] Replace the `Stage` union / `STAGES` / `STAGE_LABELS` / `STAGE_COLORS` in
      `frontend/src/types/index.ts` with the 12 active stage ids + 2 terminals of §3.
- [ ] Group board columns under the Phase A/B/C bands of §2.
- [ ] Add the **Qualified?** and **Credit Decision** gate prompts as branch UI.
- [ ] Move `assigned` from a column to an owner attribute/badge.
- [ ] Add `credit_decision` and `lost_reason` to the opportunity model, API, and
      detail panel; make `lost_reason` required when routing to `lost`.
- [ ] Render `funded` / `lost` as terminals outside the active flow.
- [ ] Add a conditions checklist to `conditions_precedent`, gating its advance.
- [ ] Enforce the transition rules of §5 (block gate-skips, confirm backward /
      reopen moves), keeping every move audit-logged.
- [ ] Allow lead origination independent of award detection; carry tender/award
      linkage onto award-sourced leads.