import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tender_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="watching", index=True)
    expected_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    started_watching_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    awarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    past_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
