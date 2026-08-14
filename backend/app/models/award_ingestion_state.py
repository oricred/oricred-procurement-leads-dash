from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AwardIngestionState(Base):
    """Durable per-source cursor for incremental award ingestion.

    ``latest_award_at`` is retained as the deployed database column name, but
    stores the latest source-created timestamp for Tenders-SA ingestion.
    """

    __tablename__ = "award_ingestion_state"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    latest_award_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    legacy_after_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    legacy_recovery_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
