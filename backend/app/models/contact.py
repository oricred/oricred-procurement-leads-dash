import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    organization_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_name: Mapped[str] = mapped_column(String(128), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    phone_direct: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone_mobile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Partial unique indexes, not plain unique constraints. A contact known only
    # by phone stores email as NULL, and any number of those must be able to
    # coexist for one company — a full constraint on (company_id, email) let
    # only one such row exist and silently rejected every enriched director
    # after the first. See remediation-01 section 3.
    __table_args__ = (
        Index(
            "uq_contact_company_email",
            "company_id",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
            sqlite_where=text("email IS NOT NULL"),
        ),
        Index(
            "uq_contact_org_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
            sqlite_where=text("email IS NOT NULL"),
        ),
    )
