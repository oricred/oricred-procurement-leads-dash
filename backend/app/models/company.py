import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    api_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    registration_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bee_level: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    cipc_forensic_risk_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    cipc_compliance_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    restricted_supplier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    raw_payload = Column(JSON, nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
