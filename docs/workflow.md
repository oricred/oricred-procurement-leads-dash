# Oricred Lead Workflow

> **Status:** This document is kept in sync with the code. If anything conflicts, the code in `backend/app/workflow.py` is the source of truth.

**Status:** Current application contract · **Version:** 2.1 · **Updated:** 2026-08-17

Oricred turns awarded procurement suppliers into funding leads. Awards remain the only lead source in this release; a lead carries its tender and award evidence throughout the workflow.

There is no separate lead or deal record. `awards` is one table, and a single `opportunities` row is *simultaneously* the lead and the deal, moving through one `kanban_stage`. So converting an award creates a row, while promoting a lead into the pipeline only changes that row's stage.

## Surfaces

| Surface | Route | Shows |
| --- | --- | --- |
| Awards | `/discover?tab=awards` | Every ingested award, with a `lead_state` of `not_created` until one exists |
| Lead Inbox | `/leads` | Award-linked opportunities at `new_lead` |
| Deal Pipeline | `/pipeline` | All stages, grouped into phase columns, loaded one column at a time |

The pipeline's "New Leads" column deliberately overlaps the Lead Inbox — the inbox is the working view of that stage, the board is the overview.

## Stages

```
new_lead
  → client_contacted
  → qualified_lead
  → won_opportunity
  → credit_preparation
  → credit_review
  → pre_approved
  → conditions_precedent
  → term_sheet_sent
  → term_sheet_received
  → contracts_sent
  → contracts_received
  → ready_to_rff
  → funded
```

`lost_lead` is a terminal state reachable from every active stage.

- **New Lead:** award automatically qualified, or manually selected for outreach.
- **Client Contacted:** first outreach has been recorded.
- **Qualified Lead:** commercial need and eligibility have been reviewed.
- **Won Opportunity:** sales handover to credit is complete.
- **Credit Preparation / Review:** collect evidence and make the credit assessment.
- **Pre-Approved:** credit approval is confirmed.
- **Conditions Precedent:** every stated condition must be cleared before the term sheet can be issued.
- **Term Sheet / Contracts / Ready to RFF:** execute the approved deal through funding.
- **Funded / Lost Lead:** terminal outcomes.

## How a lead is created

Two paths, both producing a `new_lead`:

**Automatic.** `check_awards_for_watching` (and `backfill_historical_awards` for history) runs every ingested award through `QualificationService.evaluate_award_lead`. Only awards that pass become leads. A rejected award is logged as `automatic_lead_rejected` and nothing else — no database state records the rejection, so it is indistinguishable from an award not yet processed. Rejection is not permanent: the `requalify_award_leads` job (disabled by default) re-checks existing automatic leads and closes untouched ones that no longer qualify, or flags worked ones for review.

**Manual.** `POST /api/awards/{award_id}/lead` converts any award, and **deliberately bypasses qualification** — its purpose is to pull in an award the filters rejected. Such a lead is stamped `lead_origin="manual"` and is permanently exempt from requalification. It responds `201` when it creates a lead and `200` when the award already had one, so one award never yields two leads (enforced by the partial unique index `uq_opportunities_award_id`). The conversion writes an `OpportunityAudit` row attributing it to the authenticated user.

When the supplier cannot be resolved to a known company, a placeholder company (`api_id = provisional:{award_id}`) is created, the lead is marked `needs_enrichment`, and its next action becomes *Resolve supplier identity*.

## Promoting a lead into the pipeline

A lead leaves the inbox through **Send to pipeline** on its inbox row, or **Mark contacted → pipeline** in the opportunity detail panel. Both call `POST /opportunities/{id}/mark-contacted`, which records `contacted_at`, writes an audit entry, and moves the lead to Client Contacted. `advance` is rejected from `new_lead` — mark-contacted is the only route out.

## Transition rules

- A new lead moves to Client Contacted only through **Mark contacted**; this creates the audit event and records the contact timestamp.
- Other active stages use **Advance** to move one stage forward.
- Advancing from Credit Review requires a confirmed credit approval.
- Advancing from Conditions Precedent requires a non-empty checklist with every item marked cleared.
- **Decline** is available from any active stage and requires a loss reason.
- **Back** is available from active non-new stages and requires confirmation.
- **Reopen** is available only for Funded and Lost Lead; it returns the card to New Lead after confirmation.
- Every stage change uses optimistic version checking and writes an audit entry using the authenticated user.

## Working a lead

1. Discover a relevant award and convert it; the lead appears in the Lead Inbox. Sort the inbox by *Newest first* to find a lead that has not been scored yet.
2. Resolve supplier identity and find a useful contact.
3. Send the lead to the pipeline once first contact is made, record notes, set owner and risk, then progress the card deliberately.
4. Keep source evidence, contacts, conditions, and credit decisions current in the opportunity detail panel.
5. Use Discover’s Watching and Past Due views to manage tender signals before and after award detection.

## Access

Every authenticated user can work leads, contacts, ownership, and risk. Only administrators can change credentials, sources, schedules, users, and manual job triggers.
