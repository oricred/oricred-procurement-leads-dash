import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = structlog.get_logger()
engine = create_async_engine(settings.database_url, echo=settings.debug)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


AWARD_COLUMNS: dict[str, str] = {
    "publication_date": "TIMESTAMPTZ",
    "source_created_at": "TIMESTAMPTZ",
}

OPPORTUNITY_COLUMNS = {
    "buyer_preference_score": "NUMERIC(5,2)",
    "related_bidders": "JSON",
    "crm_item_id": "VARCHAR(64)",
    "lead_priority_score": "NUMERIC(5,2)",
    "lead_priority_reasons": "JSON",
    "next_action": "VARCHAR(64)",
    "last_contact_lookup_at": "TIMESTAMP",
    "contacted_at": "TIMESTAMP",
    "credit_decision": "VARCHAR(32)",
    "lost_reason": "TEXT",
    "conditions_checklist": "JSON",
    "needs_enrichment": "BOOLEAN NOT NULL DEFAULT FALSE",
}


async def _ensure_opportunity_columns() -> None:
    async with engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            columns = {
                row[1]
                for row in (await conn.execute(text("PRAGMA table_info(opportunities)"))).fetchall()
            }
            for name, definition in OPPORTUNITY_COLUMNS.items():
                if name not in columns:
                    await conn.execute(
                        text(f"ALTER TABLE opportunities ADD COLUMN {name} {definition}")
                    )
            await conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_opportunities_award_id "
                    "ON opportunities(award_id) WHERE award_id IS NOT NULL"
                )
            )
            return

        for name, definition in OPPORTUNITY_COLUMNS.items():
            await conn.execute(
                text(f"ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS {name} {definition}")
            )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_opportunities_award_id "
                "ON opportunities(award_id) WHERE award_id IS NOT NULL"
            )
        )


async def _ensure_award_columns() -> None:
    async with engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            existing = {
                row[1] for row in (await conn.execute(text("PRAGMA table_info(awards)"))).fetchall()
            }
            for name, definition in AWARD_COLUMNS.items():
                if name not in existing:
                    await conn.execute(text(f"ALTER TABLE awards ADD COLUMN {name} {definition}"))
            return
        for name, definition in AWARD_COLUMNS.items():
            await conn.execute(
                text(f"ALTER TABLE awards ADD COLUMN IF NOT EXISTS {name} {definition}")
            )


async def _ensure_contact_email_nullable() -> None:
    """Allow externally enriched contacts to be recorded when only a phone is known."""
    async with engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            columns = (await conn.execute(text("PRAGMA table_info(contacts)"))).fetchall()
            email_column = next((column for column in columns if column[1] == "email"), None)
            if not email_column or not email_column[3]:
                return
            await conn.execute(text("ALTER TABLE contacts RENAME TO contacts_legacy"))
            await conn.execute(
                text(
                    "CREATE TABLE contacts ("
                    "id VARCHAR(36) NOT NULL PRIMARY KEY, "
                    "company_id VARCHAR(36), organization_id VARCHAR(32), "
                    "first_name VARCHAR(128) NOT NULL, last_name VARCHAR(128) NOT NULL, "
                    "job_title VARCHAR(256), email VARCHAR(256), phone_direct VARCHAR(32), "
                    "phone_mobile VARCHAR(32), linkedin_url VARCHAR(512), "
                    "is_primary BOOLEAN NOT NULL, notes TEXT, source VARCHAR(32) NOT NULL, "
                    "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, "
                    "CONSTRAINT uq_contact_company_email UNIQUE (company_id, email), "
                    "CONSTRAINT uq_contact_org_email UNIQUE (organization_id, email))"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO contacts SELECT id, company_id, organization_id, first_name, "
                    "last_name, job_title, NULLIF(email, ''), phone_direct, phone_mobile, "
                    "linkedin_url, is_primary, notes, source, created_at, updated_at "
                    "FROM contacts_legacy"
                )
            )
            await conn.execute(text("DROP TABLE contacts_legacy"))
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_contacts_company_id ON contacts (company_id)")
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_contacts_organization_id "
                    "ON contacts (organization_id)"
                )
            )
            return

        await conn.execute(text("UPDATE contacts SET email = NULL WHERE email = ''"))
        await conn.execute(text("ALTER TABLE contacts ALTER COLUMN email DROP NOT NULL"))


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_opportunity_columns()
    await _ensure_award_columns()
    await _ensure_contact_email_nullable()
    logger.info("database_ready", dialect=engine.dialect.name)
