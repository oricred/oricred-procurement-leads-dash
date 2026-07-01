import uuid

from sqlalchemy import Boolean, Column, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FilterConfig(Base):
    __tablename__ = "filter_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    value = Column(JSON, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
