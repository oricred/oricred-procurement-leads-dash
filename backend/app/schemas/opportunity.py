from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class OpportunityRead(BaseModel):
    id: str
    tender_id: str | None = None
    award_id: str | None = None
    company_id: str | None = None
    company_name: str | None = None
    award_value: Decimal | None = None
    buyer_org: str | None = None
    province: str | None = None
    category: str | None = None
    kanban_stage: str
    assigned_to: str | None = None
    contact_sufficiency: str | None = None
    risk_flag: str | None = None
    win_probability: Decimal | None = None
    funding_suitability: Decimal | None = None
    buyer_preference_score: Decimal | None = None
    days_since_award: int | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    version: int

    model_config = {"from_attributes": True}


class OpportunityCreate(BaseModel):
    pass


class OpportunityUpdate(BaseModel):
    notes: str | None = None


class OpportunityStageUpdate(BaseModel):
    stage: str
    assigned_to: str | None = None
    version: int


class OpportunityList(BaseModel):
    items: list[OpportunityRead]
    total: int
