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
                    await conn.execute(text(f"ALTER TABLE opportunities ADD COLUMN {name} {definition}"))
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_opportunities_award_id "
                "ON opportunities(award_id) WHERE award_id IS NOT NULL"
            ))
            return

        for name, definition in OPPORTUNITY_COLUMNS.items():
            await conn.execute(text(
                f"ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS {name} {definition}"
            ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_opportunities_award_id "
            "ON opportunities(award_id) WHERE award_id IS NOT NULL"
        ))


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_opportunity_columns()
    logger.info("database_ready", dialect=engine.dialect.name)
