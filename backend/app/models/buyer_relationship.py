import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BuyerRelationship(Base):
    __tablename__ = "buyer_relationships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    award_count_12m: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_award_value_12m: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    avg_response_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("company_id", "organization_id", name="uq_buyer_rel_company_org"),
    )
