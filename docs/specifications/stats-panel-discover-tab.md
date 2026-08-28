# Statistics Panel — Discover Tab

> **Status:** Specification for implementation
> **Depends on:** Phase 2b (Discover page with tabbed layout) — uses existing awards, tenders, and opportunity data models

---

## Objective

Add a "Statistics" tab to the Discover page that visualizes aggregate data about awards, tenders, and leads. Currently the platform has no dedicated view for understanding historical trends or high-level metrics — users must page through lists to gauge volume. This panel fills that gap with yearly bar charts and summary stat cards.

---

## 1. Backend — Statistics API

### 1.1 New Endpoint

**`GET /api/stats`** — Returns aggregate statistics across awards, tenders, and opportunities.

```python
# backend/app/api/stats.py

class YearlyCount(BaseModel):
    year: int
    count: int

class StatsResponse(BaseModel):
    # Yearly distributions (for bar charts)
    awards_per_year: list[YearlyCount]           # All years with awards
    tenders_per_year: list[YearlyCount]          # All years with tenders

    # Summary cards
    total_awards: int                             # COUNT of all awards
    total_tenders: int                            # COUNT of all tenders
    total_leads: int                              # COUNT of all opportunities
    total_watching: int                           # COUNT of watchlist items (status='watching')
    past_due_count: int                           # COUNT of past-due queue

    # Value stats
    total_award_value: float | None               # SUM(awards.amount)
    avg_award_value: float | None                 # AVG(awards.amount)
    award_value_per_year: list[YearlyValue]       # SUM(amount) per year

    # Pipeline / conversion
    leads_from_awards: int                        # COUNT of opportunities with award_id NOT NULL
    conversion_rate: float                        # leads_from_awards / total_awards (percentage)
    leads_per_stage: list[StageCount]             # Existing from /dashboard/stats

    # Distribution
    awards_by_province: list[ProvinceCount]       # COUNT per province (via Tender join)
    awards_by_source: list[SourceCount]           # COUNT per source
    tenders_by_status: list[StatusCount]          # COUNT per derived status

    # Top items
    top_buyers: list[BuyerCount]                  # Top 10 buyer orgs by award count
    top_categories: list[CategoryCount]           # Top 10 categories by tender count
```

### 1.2 SQL Queries

All queries executed against the **oricred application database** (read-only), using SQLAlchemy async ORM.

#### Awards Per Year
```sql
SELECT EXTRACT(YEAR FROM award_date) AS year, COUNT(*) AS count
FROM awards
WHERE award_date IS NOT NULL
GROUP BY year
ORDER BY year DESC
```

Uses `func.extract('YEAR', Award.award_date)` — handles `TIMESTAMPTZ` via SQLAlchemy's `Extract` construct. Returns up to 30 rows (unlikely to exceed 30 years of data).

#### Tenders Per Year
```sql
SELECT EXTRACT(YEAR FROM published_at) AS year, COUNT(*) AS count
FROM tenders
WHERE published_at IS NOT NULL
GROUP BY year
ORDER BY year DESC
```

#### Award Value Per Year
```sql
SELECT EXTRACT(YEAR FROM award_date) AS year, SUM(amount) AS value
FROM awards
WHERE award_date IS NOT NULL AND amount IS NOT NULL
GROUP BY year
ORDER BY year DESC
```

#### Awards by Province
```sql
SELECT t.province, COUNT(*) AS count
FROM awards a
JOIN tenders t ON a.tender_id = t.id
WHERE t.province IS NOT NULL
GROUP BY t.province
ORDER BY count DESC
```

#### Awards by Source
```sql
SELECT source, COUNT(*) AS count
FROM awards
GROUP BY source
ORDER BY count DESC
```

#### Top Buyers
```sql
SELECT t.buyer_org_id, COUNT(*) AS count
FROM awards a
JOIN tenders t ON a.tender_id = t.id
WHERE t.buyer_org_id IS NOT NULL
GROUP BY t.buyer_org_id
ORDER BY count DESC
LIMIT 10
```

#### Top Categories
```sql
SELECT t.category_id, COUNT(*) AS count
FROM tenders t
WHERE t.category_id IS NOT NULL
GROUP BY t.category_id
ORDER BY count DESC
LIMIT 10
```

#### Summary counts
Simple `SELECT COUNT(*)` on `awards`, `tenders`, `opportunities`, `watchlist_items` (WHERE status='watching'), `past_due_queue`.

#### Conversion rate
```python
leads_from_awards = await db.scalar(
    select(func.count()).where(Opportunity.award_id.isnot(None))
)
total_awards = await db.scalar(select(func.count()).select_from(Award))
conversion_rate = (leads_from_awards / total_awards * 100) if total_awards > 0 else 0
```

### 1.3 Pydantic Schemas

```python
# backend/app/schemas/stats.py

from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel


class YearlyCount(BaseModel):
    year: int
    count: int


class YearlyValue(BaseModel):
    year: int
    value: float


class StageCount(BaseModel):
    stage: str
    count: int


class ProvinceCount(BaseModel):
    province: str
    count: int


class SourceCount(BaseModel):
    source: str
    count: int


class StatusCount(BaseModel):
    status: str
    count: int


class BuyerCount(BaseModel):
    buyer_org_id: str
    count: int


class CategoryCount(BaseModel):
    category_id: str
    count: int


class StatsResponse(BaseModel):
    awards_per_year: list[YearlyCount]
    tenders_per_year: list[YearlyCount]
    award_value_per_year: list[YearlyValue]
    total_awards: int
    total_tenders: int
    total_leads: int
    total_watching: int
    past_due_count: int
    total_award_value: float | None
    avg_award_value: float | None
    leads_from_awards: int
    conversion_rate: float
    leads_per_stage: list[StageCount]
    awards_by_province: list[ProvinceCount]
    awards_by_source: list[SourceCount]
    tenders_by_status: list[StatusCount]
    top_buyers: list[BuyerCount]
    top_categories: list[CategoryCount]
```

### 1.4 API Router Registration

Add to `backend/app/api/__init__.py`:
```python
from app.api.stats import router as stats_router
# ...
router.include_router(stats_router, prefix="/stats", tags=["stats"], dependencies=authenticated)
```

---

## 2. Frontend — Statistics Tab

### 2.1 New Tab in Discover Page

Add `'stats'` to the tabs array in `DiscoverPage.tsx`:

```tsx
const tabs = [
  ['awards', 'Awards'],
  ['tenders', 'Tenders'],
  ['watching', 'Watching'],
  ['stats', 'Statistics'],   // ← new tab
  ['past-due', 'Past Due'],
  ['history', 'Supplier History'],
] as const;
```

Routing logic conditional:
```tsx
const content = tab === 'tenders' ? <TendersPage />
  : tab === 'watching' ? <MatchingPage />
  : tab === 'stats' ? <StatsPage />   // ← new
  : tab === 'past-due' ? <PastDuePage />
  : tab === 'history' ? <HistoricalContactsPage />
  : <AwardsPage />;
```

### 2.2 Charting Library Decision

Add **recharts** (2.x) as a dependency — lightweight React charting library with bar chart, line chart, and pie chart support. No heavy dependencies.

```bash
cd frontend && npm install recharts
```

Alternatively, if avoiding external dependencies, use pure CSS bar charts (div height proportional to value). The spec recommends recharts for production quality, with CSS bars as a lighter alternative.

### 2.3 StatsPage Component

```tsx
// frontend/src/pages/StatsPage.tsx

import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend as RechartsLegend
} from 'recharts';
import { BarChart3, TrendingUp, Target, Activity } from 'lucide-react';
import { statsApi } from '../services/api';
import type { StatsData } from '../types';
```

#### Layout (top to bottom):

```
┌─────────────────────────────────────────────────────┐
│  [Summary Cards Row — 4 across]                      │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                │
│  │Total │ │Total │ │Total │ │Total │                │
│  │Awards│ │Tenders│ │Leads │ │Watch │                │
│  │ 1,234│ │ 5,678│ │   456│ │    89│                │
│  └──────┘ └──────┘ └──────┘ └──────┘                │
│                                                       │
│  ┌──────────────────────┐ ┌──────────────────────┐    │
│  │ Awards per Year      │ │ Tenders per Year      │    │
│  │ [Bar Chart]          │ │ [Bar Chart]           │    │
│  │                      │ │                       │    │
│  └──────────────────────┘ └──────────────────────┘    │
│                                                       │
│  ┌──────────────────────┐ ┌──────────────────────┐    │
│  │ Award Value per Year │ │ Pipeline Stage       │    │
│  │ [Bar Chart]          │ │ [Pie Chart]          │    │
│  │                      │ │                       │    │
│  └──────────────────────┘ └──────────────────────┘    │
│                                                       │
│  ┌──────────────────────┐ ┌──────────────────────┐    │
│  │ Top Buyers           │ │ Awards by Province   │    │
│  │ [Horizontal Bar]     │ │ [Bar Chart]          │    │
│  │                      │ │                       │    │
│  └──────────────────────┘ └──────────────────────┘    │
│                                                       │
│  ┌──────────────────────┐ ┌──────────────────────┐    │
│  │ Top Categories       │ │ Awards by Source     │    │
│  │ [Horizontal Bar]     │ │ [Pie Chart]          │    │
│  │                      │ │                       │    │
│  └──────────────────────┘ └──────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

### 2.4 Summary Stat Cards (Row 1)

Four cards using the existing glass-panel style from the codebase:

| Card | Value | Icon | Source |
|------|-------|------|--------|
| Total Awards | `data.total_awards` | `Award` | awards table COUNT |
| Total Tenders | `data.total_tenders` | `FileText` | tenders table COUNT |
| Total Leads | `data.total_leads` | `Target` | opportunities table COUNT |
| Watching | `data.total_watching` | `Eye` | watchlist items COUNT |

Additional metrics row (2nd row of smaller cards, if space allows):

| Card | Value |
|------|-------|
| Past Due | `data.past_due_count` |
| Conversion Rate | `data.conversion_rate`% |
| Avg Award Value | format as ZAR currency |
| Total Award Value | format as ZAR currency |

### 2.5 Chart Specifications

#### Awards per Year (Bar Chart)
- **Type:** Vertical bar chart
- **X-axis:** Year (integer)
- **Y-axis:** Count (integer)
- **Color:** Primary blue (`#3b82f6`) with gradient
- **Tooltip:** "2025: 142 awards"
- **Empty state:** "No award data available"

#### Tenders per Year (Bar Chart)
- **Type:** Vertical bar chart
- **X-axis:** Year (integer)
- **Y-axis:** Count (integer)
- **Color:** Emerald green (`#10b981`)
- **Tooltip:** "2025: 523 tenders"

#### Award Value per Year (Bar Chart)
- **Type:** Vertical bar chart
- **X-axis:** Year (integer)
- **Y-axis:** Total value (ZAR, compact notation e.g. R2.5B)
- **Color:** Amber (`#f59e0b`)
- **Tooltip:** "2025: R1.2B total"

#### Pipeline Stage (Pie Chart)
- **Type:** Donut/pie chart
- **Data:** `leads_per_stage` with non-zero counts only
- **Colors:** Use existing `STAGE_COLORS` mapping from `types/index.ts`
- **Label:** Stage name + count
- **Tooltip:** "qualified_lead: 32"

#### Top Buyers (Horizontal Bar Chart)
- **Type:** Horizontal bar chart
- **Y-axis:** Buyer org ID (truncated to fit)
- **X-axis:** Count
- **Color:** Violet (`#8b5cf6`)
- **Limit:** Top 10

#### Awards by Province (Vertical Bar Chart)
- **Type:** Vertical bar chart
- **X-axis:** Province (abbreviated if needed)
- **Y-axis:** Count
- **Color:** Cyan (`#06b6d4`)

#### Top Categories (Horizontal Bar Chart)
- **Type:** Horizontal bar chart
- **Y-axis:** Category ID (truncated)
- **X-axis:** Count
- **Color:** Pink (`#ec4899`)
- **Limit:** Top 10

#### Awards by Source (Pie Chart)
- **Type:** Pie chart
- **Data:** `awards_by_source`
- **Colors:** Distinct per source (tenders_api, SOE, municipal, etc.)

### 2.6 Loading & Empty States

- **Loading:** Skeleton shimmer cards for stat cards, empty chart placeholders with pulsing animation
- **Empty:** "No data yet — awards and tenders populate as they are discovered."
- **Error:** "Statistics could not load. [Retry]" — consistent with AwardsPage error pattern

### 2.7 API Service Function

```typescript
// Add to frontend/src/services/api.ts

export const statsApi = {
  get: () => api.get<StatsData>('/stats'),
};
```

### 2.8 TypeScript Types

```typescript
// Add to frontend/src/types/index.ts

export interface YearlyCount {
  year: number;
  count: number;
}

export interface YearlyValue {
  year: number;
  value: number;
}

export interface ProvinceCount {
  province: string;
  count: number;
}

export interface SourceCount {
  source: string;
  count: number;
}

export interface BuyerCount {
  buyer_org_id: string;
  count: number;
}

export interface CategoryCount {
  category_id: string;
  count: number;
}

export interface StatsData {
  awards_per_year: YearlyCount[];
  tenders_per_year: YearlyCount[];
  award_value_per_year: YearlyValue[];
  total_awards: number;
  total_tenders: number;
  total_leads: number;
  total_watching: number;
  past_due_count: number;
  total_award_value: number | null;
  avg_award_value: number | null;
  leads_from_awards: number;
  conversion_rate: number;
  leads_per_stage: StageCount[];
  awards_by_province: ProvinceCount[];
  awards_by_source: SourceCount[];
  tenders_by_status: StatusCount[];
  top_buyers: BuyerCount[];
  top_categories: CategoryCount[];
}

export interface StageCount {
  stage: string;
  count: number;
}

export interface StatusCount {
  status: string;
  count: number;
}
```

---

## 3. Implementation Order

1. **Backend: Create schemas** — `backend/app/schemas/stats.py`
2. **Backend: Create API route** — `backend/app/api/stats.py` with all aggregation queries
3. **Backend: Register route** — Add to `backend/app/api/__init__.py`
4. **Frontend: Install recharts** — `npm install recharts`
5. **Frontend: Add types** — `StatsData` and related interfaces to `types/index.ts`
6. **Frontend: Add API function** — `statsApi.get()` to `services/api.ts`
7. **Frontend: Create StatsPage** — `pages/StatsPage.tsx` with charts
8. **Frontend: Wire tab** — Add `'stats'` entry to DiscoverPage tabs
9. **Verify** — `cd backend && .venv/bin/pytest` passes; frontend compiles with `npm run build`

---

## 4. Acceptance Criteria

- [ ] `GET /api/stats` returns all fields in `StatsResponse` with correct counts
- [ ] Yearly bar charts display correctly for awards and tenders (max 30 bars)
- [ ] Empty state renders when no data exists (fresh database)
- [ ] Loading state shows skeleton placeholders
- [ ] Summary cards show correct counts
- [ ] Pie charts render pipeline stage distribution and source distribution
- [ ] Horizontal bar charts render top buyers and categories
- [ ] All charts are responsive (fit within their container)
- [ ] Backend tests pass without modification
- [ ] Frontend builds without TypeScript errors
- [ ] Statistics tab is the 4th tab in the Discover page (between "Watching" and "Past Due")
- [ ] Tab title "Statistics" with icon `BarChart3` (lucide-react)

---

## 5. Deferred Scope

- **Date range filter on charts** — all stats are "all time" for v1
- **Drill-down** — clicking a bar to see filtered list is future work
- **Export** — CSV/PDF export of statistics is future work
- **Time series line charts** — monthly/weekly trends deferred
- **Forecasting** — predictive stats (Phase 3 territory)
- **Comparison periods** — YoY/MoM growth indicators deferred
