from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class RadarAward(BaseModel):
    id: str
    tender_title: str
    supplier_name: str
    amount: Decimal | None = None
    award_date: datetime | None = None
    buyer_org: str | None = None
    passed_filter: bool

    model_config = {"from_attributes": True}


class RadarData(BaseModel):
    awards: list[RadarAward]
    past_due_count: int
