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
"""


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
