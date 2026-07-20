from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HistoricalIngestionState(Base):
    """Durable tracker for phased historical data backfill jobs."""

    __tablename__ = "historical_ingestion_state"

    job_name: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="idle")
    current_lower_bound: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_upper_bound: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target_lower_bound: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
