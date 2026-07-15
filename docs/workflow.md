# Oricred Lead Workflow

**Status:** Current application contract · **Version:** 2.0 · **Updated:** 2026-07-15

Oricred turns awarded procurement suppliers into funding leads. Awards remain the only lead source in this release; a lead carries its tender and award evidence throughout the workflow.

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

- **New Lead:** award created or selected for outreach.
- **Client Contacted:** first outreach has been recorded.
- **Qualified Lead:** commercial need and eligibility have been reviewed.
- **Won Opportunity:** sales handover to credit is complete.
- **Credit Preparation / Review:** collect evidence and make the credit assessment.
- **Pre-Approved:** credit approval is confirmed.
- **Conditions Precedent:** every stated condition must be cleared before the term sheet can be issued.
- **Term Sheet / Contracts / Ready to RFF:** execute the approved deal through funding.
- **Funded / Lost Lead:** terminal outcomes.

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

1. Discover a relevant award and create/open its lead.
2. Resolve supplier identity and find a useful contact.
3. Mark the first contact, record notes, set owner and risk, then progress the card deliberately.
4. Keep source evidence, contacts, conditions, and credit decisions current in the opportunity detail panel.
5. Use Discover’s Watching and Past Due views to manage tender signals before and after award detection.

## Access

Every authenticated user can work leads, contacts, ownership, and risk. Only administrators can change credentials, sources, schedules, users, and manual job triggers.
