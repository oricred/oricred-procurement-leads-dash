# Phase 2 — Municipalities & CRM Integration

**Status:** Approved specification (sequenced after Phase 1)

---

## Objective

Extend the platform beyond national and provincial government to include municipal procurement. Add buyer-relationship analytics and CRM integration (Monday.com) to operationalize the opportunity pipeline.

---

## 1. Municipal Procurement Coverage

### 1.1 Data Gap Analysis

Municipal tender data is less centralized than national/provincial. Research required per municipality type:

| Municipality Tier | Count (SA) | Data Availability | Approach |
|---|---|---|---|
| Metropolitan (Category A) | 8 | Good — publish on municipal websites, some on Tenders-SA | Prioritize full API integration + web scraping fallback |
| Local (Category B) | ~205 | Variable — many publish on municipal websites | Targeted integration for top-20 by procurement spend |
| District (Category C) | ~44 | Limited — mostly coordinated via district | Aggregate via district council publications |

### 1.2 Tenders-SA Coverage

Verify which municipalities are already in the Tenders-SA `organizations` dataset. For those that are, integration is a configuration change (add municipality type to the filter config). For those that aren't:

1. **Tenders-SA municipalities:** Add to filter config `entity_type: include: ["municipal"]` — instant coverage.
2. **Non-Tenders-SA municipalities:** Build municipal scraper adapters (reuse Phase 1B adapter pattern) for top-20 municipalities by procurement spend.

### 1.3 Municipal Scraper Adapter

Reuse the `SOEPortalAdapter` interface from Phase 1B:

```python
class MunicipalPortalAdapter(ABC):
    @abstractmethod
    def get_new_tenders(self, since: datetime) -> list[TenderResult]: ...
    @abstractmethod
    def search_awards(self, org: str, date_range: tuple[date, date]) -> list[AwardResult]: ...
```

**Priority municipalities:**
1. City of Johannesburg (largest procurement spend)
2. City of Cape Town
3. eThekwini (Durban)
4. City of Ekurhuleni
5. City of Tshwane
6. Nelson Mandela Bay
7. Buffalo City
8. Mangaung

### 1.4 Data Normalization

Map municipal data into the same schema as Phase 1:

| Field | Tenders-SA | Municipal Scraper |
|---|---|---|
| `tender_id` | API id | Municipal reference / URL hash |
| `title` | `tenders.title` | Extracted from page |
| `estimated_value` | `tenders.estimated_value` | Extracted or null |
| `closing_date` | `tenders.closing_date` | Extracted |
| `province` | `tenders.province` | Derived from municipality |
| `category` | `tenders.category` | Mapped via keyword classification |
| `buyer_org` | `organizations.name` | Municipality name |

---

## 2. Buyer-Relationship Analytics

### 2.1 Purpose

Track the quality and history of the organization's relationship with each buyer (government entity), so the operations team can prioritize opportunities where they have an existing relationship or relevant award history.

### 2.2 Metrics Computed

| Metric | Source | Use |
|---|---|---|
| Award count (12 months) | `awards` table | Relationship strength indicator |
| Total award value (12 months) | `awards.amount` | Relationship scale |
| Average days between award and contact | `opportunities` table + audit log | Responsiveness |
| Win rate (applications ÷ funded) | `opportunities` kanban history | Competitiveness |
| Last interaction date | CRM sync or manual entry | Recency |
| Award categories overlap | `awards.category` vs `companies` historic categories | Relevance score |

### 2.3 Storage

New table: `buyer_relationships`

| Column | Type | Description |
|---|---|---|
| `company_id` | FK → `companies` | Supplier company |
| `organization_id` | FK → `organizations` | Buyer organization |
| `award_count_12m` | int | |
| `total_award_value_12m` | decimal | |
| `avg_response_days` | float | |
| `win_rate` | float | 0.0–1.0 |
| `last_interaction_at` | timestamptz | |
| `relevance_score` | float | Computed composite |
| `updated_at` | timestamptz | |

### 2.4 UI Display

On the kanban card expansion panel, a **Relationship** section:
- Relationship strength bar (weak / medium / strong)
- Award history summary
- "Last contact X days ago" with color coding (green <30, amber 30–90, red >90)
- Quick-link to CRM record

---

## 3. CRM Integration (Monday.com)

### 3.1 Integration Scope

Synchronize opportunity data between Oricred and Monday.com as the primary CRM. Each Oricred opportunity maps to a Monday.com **Item** inside a dedicated **Board** (e.g. "Oricred Opportunities"), with **Column Values** storing structured fields.

### 3.2 Monday.com Data Model

| Oricred Field | Monday.com Mapping |
|---|---|
| Opportunity (item) | **Item** on the "Oricred Opportunities" board |
| Company name | Item name |
| Award value | `numbers` column |
| Buyer organization | `text` or `dropdown` column |
| Province | `dropdown` column |
| BEE level | `dropdown` or `numbers` column |
| Stage (kanban) | `status` column (mirrors Oricred pipeline) |
| Assignee | `people` column |
| Contact-sufficiency | `status` column (✓ / ⚠ / ✗) |
| Risk flag | `status` column (red/amber/green) |
| Tender reference | `text` column |
| Notes / activity | `long_text` or `activity_log` |

### 3.3 Sync Direction

| Direction | Trigger | Fields |
|---|---|---|
| Oricred → Monday.com | New opportunity created | All mapped fields |
| Oricred → Monday.com | Stage change on kanban | `status` column value |
| Oricred → Monday.com | Any field update on card | Changed column values only |
| Monday.com → Oricred | Note/activity added to item | Via webhook or polling — activity text, timestamp |
| Monday.com → Oricred | Assignment change in `people` column | New assignee |

### 3.4 Monday.com API Integration

**API:** Monday.com GraphQL API (`https://api.monday.com/v2`).

**Authentication:** Bearer token via `Authorization` header. Token stored in environment variable `MONDAY_API_KEY`.

**Key GraphQL operations:**

```graphql
# Create item
mutation {
  create_item (board_id: <id>, group_id: "<group>", item_name: "<company>",
    column_values: "{\"numbers\": \"150000\", \"status\": \"New\"}"
  ) { id }
}

# Update column value
mutation {
  change_simple_column_value (board_id: <id>, item_id: <id>,
    column_id: "status", value: "Contacted"
  ) { id }
}

# Query recent activity
query {
  boards (ids: <id>) {
    activity_logs (limit: 50, from: "<timestamp>") {
      event, data, created_at
    }
  }
}
```

### 3.5 CRM Abstraction Layer

```python
class CRMAdapter(ABC):
    @abstractmethod
    def create_item(self, board_id: str, group_id: str, name: str,
                    column_values: dict) -> CRMId: ...
    @abstractmethod
    def update_column_value(self, item_id: CRMId, column_id: str,
                            value: Any) -> None: ...
    @abstractmethod
    def get_recent_activity(self, board_id: str,
                            since: datetime) -> list[Activity]: ...
    @abstractmethod
    def search_items(self, board_id: str,
                     term: str) -> list[CRMItem]: ...
```

**Initial implementation:** `MondayDotComAdapter` using the GraphQL API. Additional adapters (Salesforce, HubSpot) are pluggable via the same interface if needed later.

### 3.6 Sync Cadence

- Oricred → Monday.com: real-time (GraphQL mutation on kanban mutation)
- Monday.com → Oricred: hourly poll of board activity logs (or Monday.com webhook if available)

### 3.7 Conflict Resolution

Oricred is the source of truth for stage, assignment, and all structured fields. Monday.com is the source of truth for notes/activity added manually by users inside Monday.com. No bidirectional write on the same field.

---

## 4. Funding-Suitability Scoring

### 4.1 Principle

Most of the data needed to assess funding suitability is already available from Phase 1's `companies` and `awards` tables. This is incremental scoring, not new data infrastructure.

### 4.2 Score Components

| Component | Weight | Source |
|---|---|---|
| BEE level | 25% | `companies.bee_level` |
| Historical award value (12m) | 20% | `awards.amount` aggregate |
| CIPC forensic risk score | 20% | `companies.cipc_forensic_risk_score` (inverted) |
| Sector alignment with funder | 15% | Configurable per funder |
| Company age / track record | 10% | `companies.registration_date` |
| Restricted-supplier status | 10% | Binary exclusion if active |

### 4.3 Storage

Computed on demand or refreshed daily. Stored as a `funding_suitability` field on the `opportunities` record.

### 4.4 UI Display

Funding-suitability badge on kanban card:
- **High** (≥75) — green
- **Medium** (50–74) — amber
- **Low** (<50) — red

---

## 5. Deliverables

1. Municipal coverage analysis and priority list
2. Tenders-SA municipal filter config update
3. Municipal scraper adapters (top 8 metros)
4. Buyer-relationship analytics engine
5. Buyer-relationship UI in kanban card expansion
6. CRM abstraction layer with Monday.com GraphQL adapter
7. Bidirectional sync (Oricred → Monday.com real-time, Monday.com → Oricred polling)
8. Funding-suitability scoring module
9. Funding-suitability badge on kanban cards

---

## 6. Acceptance Criteria

- [ ] Municipal tenders from Tenders-SA-covered municipalities appear when filter includes `entity_type: ["municipal"]`
- [ ] At least 2 of the top 8 municipal scraper adapters are extracting data correctly
- [ ] Buyer-relationship metrics are computed and displayed on kanban card expansion
- [ ] New Oricred opportunities are created in Monday.com within 30 seconds
- [ ] Monday.com activity (<24h old) appears in Oricred card expansion
- [ ] Funding-suitability scores are computed and displayed for all qualified opportunities
- [ ] No duplicate opportunities created across sync
