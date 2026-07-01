from datetime import datetime

from pydantic import BaseModel


class AwardItem(BaseModel):
    id: str
    supplier_name: str
    buyer_org_id: str | None = None
    buyer_org_name: str | None = None
    tender_title: str | None = None
    amount: float | None = None
    award_date: datetime | None = None
    bee_level: int | None = None
    source: str
    opportunity_id: str | None = None

    model_config = {"from_attributes": True}


class AwardsList(BaseModel):
    items: list[AwardItem]
    total: int
    page: int
    page_size: int
