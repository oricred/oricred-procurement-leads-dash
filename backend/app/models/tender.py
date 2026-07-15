import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Numeric, String, Text, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Tender(Base):
    __tablename__ = "tenders"

    __table_args__ = (
        Index("idx_tenders_title", "title"),
        Index("idx_tenders_buyer_org_id", "buyer_org_id"),
        Index("idx_tenders_province", "province"),
        Index("idx_tenders_category_id", "category_id"),
        Index("idx_tenders_estimated_value", "estimated_value"),
        Index("idx_tenders_closing_date", "closing_date"),
        Index("idx_tenders_tender_type", "tender_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    api_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    raw_payload = Column(JSON, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_value: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    province: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    closing_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    buyer_org_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tender_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
