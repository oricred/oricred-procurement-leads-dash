import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HistoricalContact(Base):
    __tablename__ = "historical_contacts"

    __table_args__ = (
        UniqueConstraint("company_id", name="uq_historical_contact_company"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    first_award_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_award_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    total_award_count: Mapped[int] = mapped_column(default=0, nullable=False)
    total_award_value: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    last_award_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    award_ids = Column(JSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="tenders_api")
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
