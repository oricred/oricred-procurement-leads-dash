import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Award(Base):
    __tablename__ = "awards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    api_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    tender_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    raw_payload = Column(JSON, nullable=True)
    supplier_name: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_company_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    award_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    bee_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bee_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buyer_org_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="tenders_api")
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
