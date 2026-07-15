from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.contact import ContactRead


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
    lead_priority_score: Decimal | None = None
    lead_priority_reasons: list[str] = []
    next_action: str | None = None
    last_contact_lookup_at: datetime | None = None
    contacted_at: datetime | None = None
    credit_decision: str | None = None
    lost_reason: str | None = None
    conditions_checklist: list[dict] = []
    needs_enrichment: bool = False
    primary_contact: ContactRead | None = None
    source_tender_title: str | None = None
    source_award_date: datetime | None = None
    source_award_value: Decimal | None = None
    days_since_award: int | None = None
    related_bidders: list[dict] | None = None
    contacts: list[ContactRead] = []
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    version: int

    model_config = {"from_attributes": True}


class OpportunityCreate(BaseModel):
    pass


class OpportunityUpdate(BaseModel):
    notes: str | None = None
    risk_flag: str | None = None
    assigned_to: str | None = None


class AuditEntry(BaseModel):
    id: str
    from_stage: str | None = None
    to_stage: str
    changed_by: str
    changed_at: datetime

    model_config = {"from_attributes": True}


class OpportunityStageUpdate(BaseModel):
    stage: str
    assigned_to: str | None = None
    version: int


class OpportunityTransition(BaseModel):
    action: str
    version: int
    changed_by: str | None = None
    lost_reason: str | None = None
    credit_decision: str | None = None
    confirm: bool = False
    conditions_checklist: list[dict] | None = None


class OpportunityContactedUpdate(BaseModel):
    version: int
    contact_id: str | None = None
    note: str | None = None
    changed_by: str | None = None


class OpportunityList(BaseModel):
    items: list[OpportunityRead]
    total: int

