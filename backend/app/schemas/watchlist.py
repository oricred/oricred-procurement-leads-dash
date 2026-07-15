from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class WatchlistItemRead(BaseModel):
    id: str
    tender_id: str
    title: str
    estimated_value: Decimal | None = None
    category: str | None = None
    category_name: str | None = None
    province: str | None = None
    buyer_org: str | None = None
    status: str
    expected_window_start: datetime | None = None
    expected_window_end: datetime | None = None
    closing_date: datetime | None = None
    days_until_window: int | None = None
    days_overdue: int | None = None
    progress_pct: int | None = None
    label: str = "On Track"
    opportunity_id: str | None = None
    opportunity_count: int = 0

    model_config = {"from_attributes": True}


class WatchlistList(BaseModel):
    items: list[WatchlistItemRead]
    total: int


class WatchToggleRequest(BaseModel):
    tender_id: str


class WatchToggleResponse(BaseModel):
    is_watching: bool
