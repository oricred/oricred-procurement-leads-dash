from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.contact import ContactRead


class HistoricalContactRead(BaseModel):
    id: str
    company_id: str
    company_name: str
    registration_number: str | None = None
    bee_level: int | None = None
    first_award_date: datetime | None = None
    last_award_date: datetime | None = None
    total_award_count: int
    total_award_value: float | None = None
    last_award_id: str | None = None
    contact_sufficiency: str
    primary_contact: ContactRead | None = None
    contacts: list[ContactRead] = Field(default_factory=list)
    source: str
    last_synced_at: datetime


class HistoricalContactList(BaseModel):
    items: list[HistoricalContactRead]
    total: int



