"""One-time backfill: re-key categories table so Category.id = canonical_name."""
import asyncio
import structlog

from app.database import async_session
from app.models.category import Category
from sqlalchemy import select, delete

logger = structlog.get_logger()


async def backfill_categories():
    async with async_session() as db:
        result = await db.execute(select(Category))
        cats = result.scalars().all()
        old_ids = []
        inserted = 0
        for cat in cats:
            payload = cat.raw_payload or {}
            new_id = payload.get("canonical_name") or cat.name
            new_name = payload.get("name") or cat.name
            if new_id and new_id != cat.id:
                existing = await db.get(Category, new_id)
                if not existing:
                    db.add(Category(
                        id=new_id,
                        name=new_name,
                        parent_id=cat.parent_id,
                        raw_payload=cat.raw_payload,
                    ))
                    inserted += 1
                old_ids.append(cat.id)
            elif new_name != cat.name:
                cat.name = new_name
        if old_ids:
            await db.execute(delete(Category).where(Category.id.in_(old_ids)))
        await db.commit()
        logger.info("categories_backfilled", total=len(cats), inserted=inserted, removed=len(old_ids))


if __name__ == "__main__":
    asyncio.run(backfill_categories())
