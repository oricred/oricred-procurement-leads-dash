import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tender_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    award_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    company_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    kanban_stage: Mapped[str] = mapped_column(String(32), nullable=False, default="new", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contact_sufficiency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    risk_flag: Mapped[str | None] = mapped_column(String(16), nullable=True)
    win_probability: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    funding_suitability: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    buyer_preference_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    related_bidders = Column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    crm_item_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class OpportunityAudit(Base):
    __tablename__ = "opportunity_audit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    opportunity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    from_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
