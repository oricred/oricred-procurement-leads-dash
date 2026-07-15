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


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _run_migrations()


_migration_sql = """
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS buyer_preference_score NUMERIC(5,2);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS related_bidders JSON;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS crm_item_id VARCHAR(64);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS lead_priority_score NUMERIC(5,2);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS lead_priority_reasons JSON;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS next_action VARCHAR(64);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS last_contact_lookup_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS contacted_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS credit_decision VARCHAR(32);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS lost_reason TEXT;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS conditions_checklist JSON;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS needs_enrichment BOOLEAN NOT NULL DEFAULT FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS uq_opportunities_award_id ON opportunities(award_id) WHERE award_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS contacts (
    id VARCHAR(36) PRIMARY KEY,
    company_id VARCHAR(36),
    organization_id VARCHAR(32),
    first_name VARCHAR(128) NOT NULL,
    last_name VARCHAR(128) NOT NULL,
    job_title VARCHAR(256),
    email VARCHAR(256) NOT NULL,
    phone_direct VARCHAR(32),
    phone_mobile VARCHAR(32),
    linkedin_url VARCHAR(512),
    is_primary BOOLEAN NOT NULL DEFAULT 0,
    notes TEXT,
    source VARCHAR(32) NOT NULL DEFAULT 'manual',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, email),
    UNIQUE(organization_id, email)
);
CREATE TABLE IF NOT EXISTS historical_contacts (
    id VARCHAR(36) PRIMARY KEY,
    company_id VARCHAR(36) NOT NULL UNIQUE,
    first_award_date TIMESTAMP WITH TIME ZONE,
    last_award_date TIMESTAMP WITH TIME ZONE,
    total_award_count INTEGER NOT NULL DEFAULT 0,
    total_award_value NUMERIC(15,2),
    last_award_id VARCHAR(64),
    award_ids JSON NOT NULL DEFAULT '[]',
    source VARCHAR(32) NOT NULL DEFAULT 'tenders_api',
    last_synced_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE historical_contacts ADD COLUMN IF NOT EXISTS award_ids JSON NOT NULL DEFAULT '[]';
CREATE INDEX IF NOT EXISTS idx_historical_contacts_company_id ON historical_contacts(company_id);
CREATE INDEX IF NOT EXISTS idx_historical_contacts_last_award_date ON historical_contacts(last_award_date);"""


async def _run_migrations():
    try:
        async with engine.begin() as conn:
            for stmt in _migration_sql.strip().split(";"):
                s = stmt.strip()
                if s:
                    await conn.execute(text(s + ";"))
            logger.info("migrations_complete")
    except Exception as e:
        logger.warning("migrations_skipped", error=str(e))




