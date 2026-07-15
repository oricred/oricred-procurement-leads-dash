# Phase 3 — Predictive Procurement Intelligence

> **Status:** Historical spec document. The code is the source of truth. This phase has **not** been implemented — it is deferred until ≥12 months of historical data has accumulated.

**Status:** Approved specification (sequenced after Phase 2 — requires accumulated historical data from Phase 1 & 2 to be effective)

---

## Objective

Leverage the accumulated dataset (12+ months of tenders, awards, company profiles, buyer relationships, and opportunity outcomes) to build predictive models that forecast procurement opportunities, optimize bid targeting, and surface strategic relationship insights.

---

## Prerequisites

This phase cannot begin until:
- [ ] Phase 1 has been running for ≥12 months (sufficient historical award data)
- [ ] Phase 2 municipal coverage is operational
- [ ] Buyer-relationship analytics have ≥6 months of data
- [ ] Opportunity pipeline has ≥100 completed (Funded / Closed) records for model training

---

## 1. Procurement Forecasting

### 1.1 Purpose

Predict *what* tenders are likely to be published in the near future (next 30–90 days), allowing the operations team to prepare in advance.

### 1.2 Approach

Time-series forecasting per `(organization, category)` pair:

- **Input features:**
  - Historical tender publication dates (seasonality, trend)
  - Budget cycle indicators (SA government: April–March fiscal year)
  - Historical award volume as leading indicator (high award volume → fewer new tenders expected in that category)
  - Macro indicators (infrastructure spend announcements, department budget allocations)

- **Model:** Prophet or ARIMA per high-volume `(org, category)` pair. Global deep-learning model (LSTM / Transformer) for low-volume pairs (transfer learning).

- **Output:** List of predicted tenders with:
  - `predicted_publication_date` (with confidence interval)
  - `expected_category`
  - `expected_value_range` (derived from historical)
  - `confidence_score` (0.0–1.0)

### 1.3 Training

- Monthly retraining cycle
- Training window: rolling 36 months (or available data, whichever is shorter)
- Validation: hold-out last 3 months of data

### 1.4 Accuracy Targets

| Metric | Target |
|---|---|
| Publication date within ±14 days | ≥60% |
| Category correct | ≥80% |
| Value range within 40% of actual | ≥50% |

---

## 2. Bid-Targeting Optimization

### 2.1 Purpose

For a given supplier company, rank upcoming and predicted tenders by likelihood of winning (converting to Funded), so the operations team can prioritize which tenders to pursue.

### 2.2 Model

Classification model per organization (or cluster for small orgs):

- **Features:**
  - Company's historical win rate with this buyer (`buyer_relationships`)
  - Company's award history in this category
  - BEE level vs. tender requirements
  - Historical competitors for this `(org, category)` pair
  - Tender value vs. company's historical award values
  - Company's `funding_suitability` score (from Phase 2)

- **Target:** `opportunity_stage = "Funded"` (binary: won / lost)

- **Model:** Gradient-boosted trees (XGBoost / LightGBM) — interpretable, handles mixed feature types well.

### 2.3 Output

For each active and predicted tender, a **Win Probability Score** (0–100%) displayed on the kanban card.

### 2.4 Accuracy Target

AUC-ROC ≥ 0.75 on hold-out test set.

---

## 3. Advanced Relationship Mapping

### 3.1 Purpose

Surface non-obvious connections: shared directors across supplier companies, historical collusion patterns (same bidders across multiple tenders), influence pathways via director networks.

### 3.2 Director Network Graph

Build from `directors` endpoint data:

```python
class DirectorGraph:
    """Nodes: directors + companies. Edges: director_of (person→company)."""
    def shortest_path(self, company_a: str, company_b: str) -> list[Edge]: ...
    def shared_directors(self, company_a: str, company_b: str) -> list[Person]: ...
    def community_detection(self) -> list[set[CompanyId]]: ...
```

- **Source data:** Companies + Directors API endpoints (accumulated over Phase 1 & 2)
- **Graph DB:** Lightweight in-memory graph (NetworkX) with periodic rebuild from DB
- **Visualization:** D3.js / Cytoscape.js force-directed graph in the UI

### 3.3 Collusion Risk Indicators

| Indicator | Definition | Alert Level |
|---|---|---|
| Bidder overlap | Same set of bidders appears in ≥80% of tenders for a given `(org, category)` | ⚠ Yellow |
| Rotation pattern | Bidders rotate winning (A wins tender 1, B wins tender 2, A wins tender 3) | 🔴 Red |
| Director overlap | Bidding companies share directors | 🔴 Red |
| Price clustering | Bid values clustered within 5% of each other repeatedly | ⚠ Yellow |

### 3.4 Influence Pathways

When a tender has a named contact (Phase 1 contact sufficiency), map the shortest path from the supplier to that contact via:
1. Shared directors
2. Previous awards from the same organization
3. Industry association membership (if data available)

---

## 4. Anomaly Detection

### 4.1 Purpose

Flag unusual procurement patterns that may indicate fraud, inefficiency, or data quality issues.

### 4.2 Detection Rules

| Anomaly | Method |
|---|---|
| Tender with single bidder (no competition) | Threshold check: `known_bidders == 1` |
| Award value significantly above historical average for `(category, org)` | Z-score > 3 on `award_amount` distribution |
| Same supplier winning repeatedly without competitive tender | Roll-count per `(org, supplier)` per 12 months > threshold |
| Unusual timing: award on weekend / public holiday | Calendar check |
| Gap between closing date and award date is an outlier | Z-score > 3 on `award_timing_model` distribution |

### 4.3 Alerting

Anomalies are surfaced in a dedicated **Risk Feed** in the UI — a chronological log of flagged events with severity (red/amber/yellow).

---

## 5. Automated Reporting

### 5.1 Scheduled Reports

| Report | Cadence | Recipient |
|---|---|---|
| Upcoming predicted tenders (next 30 days) | Weekly | Ops team |
| Pipeline health report (stages, velocity, conversion) | Weekly | Management |
| Risk feed digest (anomalies detected) | Bi-weekly | Compliance |
| Buyer relationship health scores | Monthly | Ops team lead |
| Model accuracy report (forecast vs actual) | Monthly | Analytics team |

### 5.2 Format

PDF or embedded dashboard URL via email. Generated via a reporting service that queries the Phase 1/2 database directly.

---

## 6. UI Additions

### 6.1 Prediction Panel

A new side panel on the kanban dashboard:
- **Forecast tab:** list of predicted tenders (next 30/60/90 days) by category
- **Win Probability tab:** current tenders ranked by win probability for the logged-in supplier
- **Relationship Map tab:** interactive director network graph

### 6.2 Risk Feed

A dedicated page/modal showing the chronological anomaly log with:
- Date detected
- Tender / award link
- Anomaly type
- Severity badge
- Dismiss / acknowledge button

### 6.3 Win Probability Badge

On each kanban card, a percentage badge (0–100%) next to the funding-suitability badge.

---

## 7. Deliverables

1. Procurement forecasting model (Prophet/ARIMA/LSTM pipeline)
2. Bid-targeting win-probability model
3. Director network graph engine with visualization
4. Collusion risk indicators
5. Anomaly detection rules engine
6. Risk Feed UI
7. Win-probability badge on kanban cards
8. Automated scheduled reports
9. Model accuracy monitoring dashboard
10. Retraining pipeline (monthly automated)

---

## 8. Acceptance Criteria

- [ ] Forecasting model predicts ≥60% of tender publication dates within ±14 days
- [ ] Win-probability model achieves AUC-ROC ≥ 0.75 on hold-out test set
- [ ] Director network graph correctly identifies shared directors between any two linked companies
- [ ] Collusion risk indicators trigger correctly on known patterns (validated against historical data)
- [ ] Anomaly detection rules flag at least 80% of manually identified anomalous tenders in historical data
- [ ] Risk Feed UI loads and displays all flagged anomalies for the current period
- [ ] Win-probability badge is displayed on every active kanban card
- [ ] Reports are generated and sent on schedule
- [ ] Model retraining pipeline runs monthly without manual intervention
