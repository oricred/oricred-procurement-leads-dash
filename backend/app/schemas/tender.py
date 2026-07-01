from datetime import datetime

from pydantic import BaseModel


class TenderItem(BaseModel):
    id: str
    title: str | None = None
    estimated_value: float | None = None
    province: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    buyer_org_id: str | None = None
    buyer_org_name: str | None = None
    closing_date: datetime | None = None
    published_at: datetime | None = None
    tender_type: str | None = None
    discovered_at: datetime | None = None
    status: str
    is_watching: bool
    opportunity_id: str | None = None

    model_config = {"from_attributes": True}


class TendersList(BaseModel):
    items: list[TenderItem]
    total: int
    page: int
    page_size: int
