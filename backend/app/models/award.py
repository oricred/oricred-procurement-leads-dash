import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, Numeric, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Award(Base):
    __tablename__ = "awards"

    __table_args__ = (
        Index("idx_awards_supplier_name", "supplier_name"),
        Index("idx_awards_buyer_org_id", "buyer_org_id"),
        Index("idx_awards_amount", "amount"),
        Index("idx_awards_source", "source"),
        Index("idx_awards_bee_level", "bee_level"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    api_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    tender_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    raw_payload = Column(JSON, nullable=True)
    supplier_name: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_company_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    award_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    publication_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bee_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bee_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buyer_org_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="tenders_api")
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
