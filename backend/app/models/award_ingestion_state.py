from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AwardIngestionState(Base):
    """Durable per-source cursor for incremental award ingestion."""

    __tablename__ = "award_ingestion_state"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    latest_award_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
