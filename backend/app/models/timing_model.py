import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AwardTimingModel(Base):
    __tablename__ = "award_timing_model"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(String(32), nullable=False)
    category_id: Mapped[str] = mapped_column(String(256), nullable=False)
    avg_days_to_award: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    stddev_days_to_award: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    min_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("organization_id", "category_id", name="uq_atm_org_category"),
    )
