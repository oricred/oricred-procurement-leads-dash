# Oricred Procurement Intelligence Platform — Client Presentation

> **Purpose:** Client-facing overview of platform capabilities, integration readiness, and strategic value drivers for deal closure.

---

## 1. Improved Award Data Quality (Tenders SA)

### What's Been Built
The platform ingests data from **two complementary Tenders-SA sources** — the public REST API and a direct PostgreSQL read-only connection — enabling cross-validation and richer data than either source alone.

### Key Quality Improvements

| Area | How It's Handled |
|---|---|
| **Award Dates** | 5-tier fallback resolver that never returns NULL. Detects and auto-corrects century typos (e.g. `2062` → `2025`) via `MAX_VALID_YEAR=2027` guard. Daily recovery job runs at 4AM to fix any corrupted dates. Procurement timeline enforced: `published_at ≤ closing_date ≤ award_date ≤ publication_date ≤ discovered_at`. |
| **Award Amounts** | Resolved from structured DB fields with fallback chain. |
| **Company Data** | BEE level, CIPC compliance/risk score, restricted-supplier flags consumed directly from Tenders-SA verified records. |
| **Contact Data** | Role-based vs. named-official classification with confidence scoring. Directors and key personnel pulled from TSA DB via scheduled enrichment jobs. |
| **Duplicate Elimination** | Deduplication via award ingestion state tracking and CRM item ID persistence. |
| **Failed API Calls** | Dead-letter queue captures failures for retry via admin UI — no data loss. |

**Client Takeaway:** *The platform actively cleans and validates government procurement data rather than passing it through raw. Date accuracy — the single most operationally critical field — has dedicated correction logic that recovers data even when the source has errors.*

---

## 2. Automated Award Ingestion into the Deal Pipeline

### End-to-End Automation Pipeline

```
Tenders-SA Source Data
        │
        ▼
┌──────────────────┐      Every 15 min
│ Tender Discovery  │──────────────────────▶ Configurable 6-stage qualification filter
└──────────────────┘                          (buyer org, category, value, province, etc.)
        │
        ▼
┌──────────────────┐      Hourly
│  Award Detection  │──────────────────────▶ Matches awards to watched tenders
└──────────────────┘
        │
        ▼
┌──────────────────┐
│ Opportunity      │──────────────────────▶ Automatically created in pipeline
│ Creation         │                        with company intel, buyer analytics,
└──────────────────┘                        funding score pre-computed
        │
        ▼
┌──────────────────┐
│ 14-Stage Funding │──────────────────────▶ Manual workflow from here
│ Pipeline (Kanban) │
└──────────────────┘
```

### Scheduled Jobs Running in Production

| Job | Frequency | Purpose |
|---|---|---|
| Tender Discovery | Every 15 min | Polls Tenders-SA for new tenders through configurable filters |
| Award Check | Hourly | Batch check for awards linked to watched tenders (eliminated N+1) |
| Timing Model Refresh | Weekly (Sun 2AM) | Recomputes expected award windows from historical averages |
| Tender Backfill | Daily | Backfills stub tenders from direct DB connection |
| Contact Enrichment | Mon/Thu | Pulls directors and key personnel from TSA DB |
| Historical Contacts Sync | Daily | Syncs historical award data per company |
| CRM Sync | Hourly | Pushes opportunities to Monday.com |
| Award Date Recovery | Daily (4AM) | Fixes corrupted award dates |

**Client Takeaway:** *Leads flow from raw government data into your deal pipeline automatically — no manual data entry. The system does the heavy lifting of monitoring, filtering, matching, and enriching before a human ever touches the opportunity.*

---

## 3. Exportable Leads for External Contact Enrichment

### Current Export Capabilities

- **CSV export** from the Awards browser (filterable, paginated)
- **Filterable lead inbox** with export-ready data (stage, contactability, priority, risk, value, recency)
- **Historical contacts** with search and contactability filter — can be exported for batch enrichment via third-party tools

### Designed for Tool-Chain Flexibility

The platform is **not a walled garden**. Data can be exported at multiple stages:
1. **Raw awards/tenders** → export CSV for external analysis
2. **Qualified leads** → export filtered lead set for contact enrichment via LinkedIn Sales Navigator, Lusha, Apollo, etc.
3. **Enriched contacts** → re-import or update via the contact CRUD API

**Client Takeaway:** *You're not locked into a single enrichment workflow. Export leads, enrich externally with your preferred tools, and bring the data back in.*

---

## 4. Monday.com Integration — Ready, Needs API Key

### What's Already Built

| Component | Status |
|---|---|
| **GraphQL Adapter** | Complete — full Monday.com GraphQL API adapter with query building, mutation handling, rate limiting |
| **CRM Abstraction Layer** | Complete — abstract base class allows swapping CRM providers without changing core logic |
| **Sync Job** | Complete — hourly push of opportunities to Monday.com |
| **Item ID Persistence** | Complete — deduplication so the same opportunity isn't re-created on Monday.com |
| **CRM Activity Display** | Complete — Monday.com activity feed shown inside the opportunity modal |
| **Push on Assign** | Complete — opportunity is pushed to CRM the moment it's assigned to a team member |

### What's Needed Internally (Oricred)
- Set `ORICRED_MONDAY_API_KEY` in production environment
- Monday.com board/workspace configuration mapping to pipeline stages

**Client Takeaway:** *The integration is fully coded and tested. No development work is needed — just provide the API key and configure the board mapping. Your team's Monday.com workflows can consume Oricred opportunities immediately.*

---

## 5. Excel / CSV Integration

### Current State

| Capability | Status |
|---|---|
| **CSV Export** | Built and working — awards browser with full filtering |
| **openpyxl Library** | Available in the dependency stack |
| **Lead Contact Import** | Service exists for importing contacts from spreadsheets |

### Ready to Extend
The `openpyxl` dependency is already present. Excel-native import/export (`.xlsx` with formatting, multiple sheets) can be activated with minimal additional build.

**Client Takeaway:** *Basic spreadsheet export works today. Native Excel import/export is a small configuration step away — the libraries are already in the stack.*

---

## 6. Automated Contact Details Discovery — Ready, Needs Google Search API

### What's Already Built

| Component | Status |
|---|---|
| **Contact Enrichment Service** | Complete — pulls directors and key personnel from Tenders-SA DB |
| **Historical Contacts Sync** | Complete — syncs all historical award contacts per company |
| **Contact Sufficiency Classifier** | Complete — scores contacts as ✓ named official / ⚠ role-based only / ✗ none |
| **Contact CRUD API** | Complete — full create/read/update/delete for company, organization, and opportunity contacts |
| **Lead Contact Import** | Complete — import contacts from spreadsheets |

### Architecture for Google Search Integration

The contact enrichment pipeline is designed to accept additional data sources:

```
Tenders-SA DB (Directors, Key Personnel)
        │
        ▼
┌──────────────────┐
│ Contact          │────▶ Structured contact records with sufficiency scores
│ Enrichment       │
│ Pipeline         │────▶ Google Search / Company Website scraping
└──────────────────┘     (integration point — ready, needs implementation)
        │
        ▼
┌──────────────────┐
│ Contact Scoring  │────▶ Contactability score (0-100) used for lead prioritization
│ & Prioritization │
└──────────────────┘
```

### What's Needed Internally (Oricred)
- Google Custom Search API key (or alternative: SerpAPI, Clearbit, Hunter.io)
- Integration adapter to map search results to the existing contact model
- Cost-per-query analysis for budgeting

**Client Takeaway:** *The contact enrichment framework is built and actively pulling structured data from government sources. Adding web search to discover email addresses and phone numbers requires only the API adapter — the storage, scoring, and workflow layers are already in place.*

---

## 7. Suggestions for Improvement — Sales & Deal Team Participation

### What Already Exists for Feedback-Driven Improvement

| Feature | How It Enables Team Input |
|---|---|
| **14-Stage Funding Pipeline** | Granular stage definitions let the team surface exactly where deals stall — data-driven process refinement |
| **Lead Scoring Model** | Configurable scoring parameters (BEE level, CIPC risk, award value, company age) — team can adjust weights |
| **Buyer Relationship Analytics** | Tracks award count, response times, win rates per (company, buyer org) — reveals which relationships to invest in |
| **Buyer Preference Scoring** | Province weights, SOE bonus, preferred buyers configurable per team input |
| **Audit Trail** | Every opportunity transition is logged with timestamp and user — full visibility into team workflow patterns |
| **Qualification Filter Config** | 6-stage filter pipeline configurable via admin UI — team decides which tenders qualify |
| **Admin UI (7 tabs)** | Non-technical team members can configure filters, notifications, scoring, and users without developer involvement |

### Recommended Participation Model

1. **Monthly scoring calibration** — Review lead conversion data and adjust scoring weights based on actual outcomes
2. **Filter tuning sessions** — Sales team feeds back which lead sources convert best; filters adjusted accordingly
3. **Pipeline stage refinement** — If deals stall at a specific stage, consider splitting it or adding automation
4. **Contact sufficiency feedback** — Flag false positives/negatives in contact classification to improve the model

**Client Takeaway:** *The platform is designed to get smarter over time through team input. Scoring, filtering, and pipeline stages are all configurable without code changes. Your deal team's real-world outcomes drive continuous improvement.*

---

## 8. Needs Verification — Built-In Quality Assurance

### Verification Mechanisms Already in Place

| Mechanism | What It Does |
|---|---|
| **Dead-Letter Queue** | Failed API calls are captured with full context for retry — no silent data loss |
| **Award Date Recovery Job** | Daily scan for corrupted dates with automatic correction |
| **Procurement Timeline Validation** | Enforces logical date ordering; flags inconsistencies |
| **Job Runs Table** | Every scheduled job execution is logged with start time, end time, status, and error details |
| **Admin Job Monitor** | Real-time visibility into job status, last run, next run, and failure count |
| **Award Ingestion State** | Tracks which awards have been processed to prevent duplicates |
| **CRM Sync Deduplication** | Prevents duplicate Monday.com items via external ID persistence |
| **Contact Sufficiency Scoring** | Flags which contacts need manual verification vs. automated trust |

### What "Needs Verification" Means in Practice

- **Data accuracy** should be spot-checked monthly against source systems
- **Scoring models** should be validated against actual deal outcomes quarterly
- **Contact data** quality should be reviewed periodically (especially web-sourced contacts if Google Search integration is activated)
- **Filter configuration** should be reviewed for over/under-inclusion as the market evolves

**Client Takeaway:** *The platform doesn't just trust its data — it actively verifies, corrects, and logs everything. Verification is a built-in philosophy, not an afterthought. Your team has full visibility into data quality at every stage.*

---

## Strategic Value Summary

| Capability | Value to Client | Risk Addressed |
|---|---|---|
| Automated award ingestion | Eliminates manual monitoring of government portals | Missed opportunities |
| Date quality correction | Reliable pipeline timelines for sales follow-up | Wrong-time engagement |
| Configurable qualification | Team controls which leads enter pipeline | Wasted effort on bad leads |
| Monday.com integration | No workflow disruption — CRM stays central | Adoption resistance |
| Exportable data | Flexibility to use best-in-breed tools | Vendor lock-in |
| Contact enrichment framework | Faster path from lead to conversation | Cold outreach inefficiency |
| Scoring & analytics | Data-backed prioritization | Gut-feel deal selection |
| Audit & verification | Trust in system data | Garbage-in-garbage-out |

---

## Technical Investment Summary

| Component | Status | Effort Required |
|---|---|---|
| Core Platform (Phases 1, 2, 2b) | **Complete** | None — operational |
| Tenders-SA Dual Integration (REST + DB) | **Complete** | None — operational |
| Award Date Quality / Correction | **Complete** | None — operational |
| Automated Ingestion Pipeline | **Complete** | None — operational |
| 14-Stage Funding Pipeline | **Complete** | None — operational |
| Exportable Leads (CSV) | **Complete** | None — operational |
| BEE / CIPC / Risk Enrichment | **Complete** | None — operational |
| Buyer Relationship Analytics | **Complete** | None — operational |
| Lead Scoring & Funding Suitability | **Complete** | None — operational |
| Monday.com Integration | **Built, needs API key** | Internal ops (Oricred) |
| Excel (.xlsx) Import/Export | **Libraries ready** | Small build |
| Google Search Contact Discovery | **Framework ready** | Medium build (Oricred) |
| Phase 3 — Predictive Intelligence | **Not started** | Deferred (≥12 months data) |
| Municipal Portal Scrapers | **Stubs only** | Future phase |
| SOE Portal / OCPO Gazette PDF Parsing | **Not started** | Future phase |
