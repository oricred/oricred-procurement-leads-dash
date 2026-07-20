from datetime import datetime

from pydantic import BaseModel


class ContactRead(BaseModel):
    id: str
    company_id: str | None = None
    organization_id: str | None = None
    first_name: str
    last_name: str
    job_title: str | None = None
    email: str | None = None
    phone_direct: str | None = None
    phone_mobile: str | None = None
    linkedin_url: str | None = None
    is_primary: bool = False
    notes: str | None = None
    source: str = "manual"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContactCreate(BaseModel):
    first_name: str
    last_name: str
    job_title: str | None = None
    email: str | None = None
    phone_direct: str | None = None
    phone_mobile: str | None = None
    linkedin_url: str | None = None
    is_primary: bool = False
    notes: str | None = None


class ContactUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    email: str | None = None
    phone_direct: str | None = None
    phone_mobile: str | None = None
    linkedin_url: str | None = None
    is_primary: bool | None = None
    notes: str | None = None
