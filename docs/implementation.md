# Oricred Procurement Intelligence Platform — Implementation Plan

> **Status:** Historical design document. The actual implementation may differ — the code is the source of truth.
>
> This document describes the original Phase 1 design intent. Post-Phase-1 additions (Phase 2, Phase 2b) are documented in their respective spec files and the actual code. See AGENTS.md for the current implementation status.

**Scope of this build:** Tenders-SA API integration end-to-end. SOE internal-portal checks and OCPO Gazette PDF parsing are an explicit later phase (§6) — not because they're less important, but because they're triggered by data this build produces, so they're sequenced after it rather than alongside it.

---

## 1. Data Foundation: What We Build vs. What the API Already Gives Us

This matters for estimating effort, not just architecture. A meaningful share of what looked like "Oricred enrichment work" in the original brief is already computed by Tenders-SA and just needs to be consumed correctly.

| Need | Source | Build effort |
|---|---|---|
| Supplier award history, BEE level, CIPC compliance/risk score, restricted-supplier flag | `companies` object | None — consume directly |
| Organization contact details (email, phone, website) with role-based/confidence flags | `organizations` object | None — consume directly |
| Risk screening | `/forensic/restricted-suppliers/check`, `/match` | None — call directly per award |
| Bidder names per tender | `/tenders/{id}/bidders` | None — names only, no bid value/outcome (accepted limitation, see §4) |
| Named-official contact sufficiency | `organizations.contact_email_is_role_based` + `confidence_score` | Build: a simple sufficiency classifier (✓ named official / ⚠ role-based only / ✗ none) — see §1.1 |
| Award-timing prediction (when will this tender actually be awarded) | Not provided by API | **Build required** — this is the core custom logic, §2 |

### 1.1 Contact Sufficiency Rule (final)
A contact record is **sufficient** if it is tied to a named official at the company — director-level is preferred but not required. Practically:
- `contact_email_is_role_based = 0` + `confidence_score` above threshold → ✓ sufficient
- `contact_email_is_role_based = 1` (generic inbox only) → ⚠ usable as fallback, flagged for manual upgrade
- No contact on file → ✗, queued for the known-supplier short-circuit (§4) before any manual lookup

---

## 2. Award-Timing Model (Core Build)

This is the single piece of custom logic the whole pipeline depends on — without it, "track from publication" has no trigger for when to check for an award.

**Build steps:**
1. Compute historical baseline per (organization, category): `award_date − tender.closing_date`, using `/v2/awards`, `/v2/awards/analytics/category`.
2. Store `avg_days_to_award` / `stddev_days_to_award` per pair; refresh via weekly batch job.
3. Per tracked tender: `expected_award_window = closing_date + avg_days_to_award ± stddev`.
4. Cold-start fallback: insufficient org-specific history → use category-level global average until enough data accumulates.

**Operational trigger this produces:**
- Inside window → normal daily poll of `/awards/by-tender/{id}`.
- Past window, no award found → escalate poll frequency **and** push the tender into the "Past-Due, No Award" queue — this queue is what determines whether/when Phase 1B (SOE/Gazette) work is worth activating (§6).

---

## 3. Core Workflow

```
Tender Published (Tenders-SA: /tenders/new)
        │
        ▼
Apply Qualification Filters (§5) ──reject──> discarded, not surfaced
        │ pass
        ▼
Tracked ("Matching" pane, §7.3)
        │
        ▼
Award-Timing Model (§2) sets expected window
        │
   past window, no award? ──yes──> Past-Due Queue (§2, §6 trigger)
        │ no / award found
        ▼
Award Detected → pull /companies/{name}, /organizations/{id}
        │
        ▼
Forensic screen: /forensic/restricted-suppliers/check
        │
        ▼
Contact sufficiency check (§1.1)
        │
        ▼
Opportunity Card → Kanban pipeline (§7.1)
        │
        ▼
New → Assigned → Contacted → In Discussion → Application Received → Funded/Closed
```

> **Note:** The actual workflow has been expanded to 14 stages (`new_lead` → `funded`). See `backend/app/workflow.py` and `docs/workflow.md` for the current state machine.

---

## 4. Competitor Intelligence (Build Spec)

**Pre-close (speculative):** likely-bidder list derived from historical award frequency for the organization+category pair, via `/companies/top` and `/awards/analytics/category`. Labeled in UI as inferred, not confirmed.

**At close (confirmed):** `/tenders/{id}/bidders` returns actual bidder names, replacing the speculative list.

**Known-supplier short-circuit (build this — it's the main lever on contact-sufficiency coverage):** for every bidder name returned, check `/companies/{name}` first. Most bidders are repeat players already in the Tenders-SA dataset, so this resolves company history, risk score, and org contact details immediately at zero enrichment cost. Only names with no existing record get queued for manual lookup — this is the residual gap, not the default path.

**Accepted limitation:** bidder data has no bid value or win/loss outcome attached. The system will show *who* bid, not *who lost and by how much*. No build planned against this gap; flagged here so it isn't mistaken for an oversight later.

---

## 5. Qualification Filter — Implementation Spec

Final filter logic, implemented as a config object (not hardcoded), so thresholds can be tuned without a redeploy:

| Filter | Field(s) | 
|---|---|
| Value range (min/max) | `tenders.estimated_value`, `awards.amount` |
| Sector include/exclude | category fields, `/categories`, `organizations.industry_codes` |
| Province | `tenders.province` |
| Entity type (national/provincial/municipal/SOE) | `organizations.organization_type` |
| BEE level | `awards.bee_level`, `awards.bee_points` |
| Risk exclusion | `restricted-suppliers.is_active`, `companies.cipc_forensic_risk_score` |

**Volume handling:** no capacity throttle. Every opportunity that passes this filter is surfaced — the filter itself is the sole control on volume. If volume needs adjusting, the fix is tightening filter thresholds in config, not adding a separate gating layer downstream.

---

## 6. Phase 1B Trigger: SOE Portals & OCPO Gazette

Not built in this phase, but explicitly designed for: the Past-Due Queue from §2 is the activation signal.

- **Activation rule:** Phase 1B work starts once the Past-Due Queue shows a sustained, material rate (operational team to monitor — see §8) — this is the live evidence of exactly the Transnet-style pattern (internal portal award precedes OCPO publication) the original brief anticipated.
- **Research task, not engineering, first:** map per-SOE where each Tier-1 entity (Transnet, Eskom, SANRAL, Prasa, etc.) publishes and the typical internal→OCPO lag.
- **OCPO Gazette ZIP/PDF pipeline:** isolated Python microservice (unzip → parse → entity extraction), architecturally separate from the live dashboard so its batch nature and parsing fragility can't affect pipeline uptime.

---

## 7. Kanban Dashboard — Build Spec

### 7.1 Primary Board — Opportunity Pipeline
`New → Assigned → Contacted → In Discussion → Application Received → Funded` (+ collapsed `Closed` swimlane)

Card fields: company, award value, buyer org, province, BEE level, risk flag (red/amber/green), days since award, contact-sufficiency indicator (✓/⚠/✗ per §1.1).

Card expansion: award detail, company intelligence panel, org contact panel, competitor list (§4).

### 7.2 Live Award Radar (persistent side panel, not a column)
- Rolling 7-day **pre-filter** award feed — raw signal, so filter tuning can be sanity-checked against what it's excluding.
- Past-Due Queue counter (§2/§6 trigger).

### 7.3 Matching (pre-award)
Tracked tenders between publication and award, with expected-award countdown from §2's model.

---

## 8. Build Sequence & Deliverables

### Phase 1 — Core Platform (Completed)
- Tenders-SA API integration: tenders, awards, organizations, companies, forensic endpoints
- Award-Timing Model: baseline computation + weekly refresh job
- Qualification filter engine, config-driven
- Kanban dashboard: pipeline + radar + matching
- Contact-sufficiency classifier
- Known-supplier short-circuit for bidder resolution
- Email alerting

### Phase 1B — SOE/Gazette Gap-Fill (Not started)
- Activated by Past-Due Queue volume — sequenced, not parallel
- SOE-portal targeted checks (per-organization, research-then-build)
- OCPO Gazette microservice

### Phase 2 — Municipalities & CRM (Completed)
- Funding-suitability scoring
- Buyer-relationship analytics, CRM integration
- Municipal coverage (filter config + scraper stubs)
- CRM sync with Monday.com

### Phase 2b — UI Navigation, Awards & Tenders Browsers (Completed)
- Navigation restructure: single-page Discover with tabs
- Awards browser: filterable/paginated + CSV export + create-lead
- Tenders browser: filterable/paginated + watch toggle + status badges
- Historical contacts browser
- Watchlist toggle endpoint
- Reference endpoints (organizations, categories, provinces)
- Reusable FilterBar + DataTable components

### Phase 3 — Predictive Intelligence (Not started)
- Deferred until ≥12 months of historical data accumulated

---

## 9. Post-Launch Monitoring (replaces open questions — there's no further discovery, just metrics to watch)

- **Past-Due Queue rate** — directly determines Phase 1B timing (§6).
- **Contact-sufficiency rate** (✓ vs ⚠ vs ✗ across live opportunity cards) — if ✗ stays high after the known-supplier short-circuit is live, that's the signal to scope a dedicated cold-enrichment step, not a hypothetical now.
- **Filter pass-through volume** — direct lever per §5; tune filter config rather than add new gating logic if volume runs too high or too low.
