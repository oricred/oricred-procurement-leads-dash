import math
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.award import Award
from app.models.tender import Tender
from app.models.timing_model import AwardTimingModel

logger = structlog.get_logger()


class AwardTimingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    async def compute_model():
        async with async_session() as db:
            result = await db.execute(
                select(Award, Tender).join(Tender, Award.tender_id == Tender.id).where(
                    Award.award_date.isnot(None),
                    Tender.closing_date.isnot(None),
                    Award.source == "tenders_api",
                )
            )
            rows = result.all()

            groups: dict[tuple[str | None, str | None], list[float]] = {}
            for award, tender in rows:
                if award.award_date and tender.closing_date:
                    days = (award.award_date - tender.closing_date).total_seconds() / 86400
                    key = (award.buyer_org_id, tender.category_id)
                    groups.setdefault(key, []).append(days)

            now = datetime.now(timezone.utc)
            for (org_id, cat_id), days_list in groups.items():
                n = len(days_list)
                if n == 0:
                    continue
                avg = sum(days_list) / n
                variance = sum((d - avg) ** 2 for d in days_list) / n
                stddev = math.sqrt(variance)
                min_days = int(min(days_list))
                max_days = int(max(days_list))

                existing = await db.execute(
                    select(AwardTimingModel).where(
                        AwardTimingModel.organization_id == org_id,
                        AwardTimingModel.category_id == cat_id,
                    )
                )
                model = existing.scalar_one_or_none()
                if model:
                    model.avg_days_to_award = avg
                    model.stddev_days_to_award = stddev
                    model.sample_count = n
                    model.min_days = min_days
                    model.max_days = max_days
                    model.computed_at = now
                else:
                    model = AwardTimingModel(
                        organization_id=org_id or "",
                        category_id=cat_id or "",
                        avg_days_to_award=avg,
                        stddev_days_to_award=stddev,
                        sample_count=n,
                        min_days=min_days,
                        max_days=max_days,
                        computed_at=now,
                    )
                    db.add(model)

            await db.commit()
            logger.info("timing_model_computed", groups=len(groups))

    async def get_expected_window(self, organization_id: str | None, category_id: str | None, closing_date: datetime | None) -> tuple[datetime | None, datetime | None]:
        if not closing_date:
            return None, None
        if not organization_id or not category_id:
            return await self._fallback_window(closing_date, category_id)

        result = await self.db.execute(
            select(AwardTimingModel).where(
                AwardTimingModel.organization_id == organization_id,
                AwardTimingModel.category_id == category_id,
                AwardTimingModel.sample_count >= 3,
            )
        )
        row = result.scalar_one_or_none()

        if row:
            avg_days = float(row.avg_days_to_award)
            stddev = float(row.stddev_days_to_award)
        else:
            return await self._fallback_window(closing_date, category_id)

        stddev = max(stddev, 15.0)
        start = closing_date + timedelta(days=max(0, int(avg_days - stddev)))
        end = closing_date + timedelta(days=int(avg_days + stddev))
        return start, end

    async def _fallback_window(self, closing_date: datetime, category_id: str | None) -> tuple[datetime, datetime]:
        if category_id:
            async with async_session() as db:
                result = await db.execute(
                    select(AwardTimingModel).where(
                        AwardTimingModel.category_id == category_id,
                        AwardTimingModel.sample_count >= 1,
                    )
                )
                rows = result.scalars().all()
                if rows:
                    avg = sum(float(r.avg_days_to_award) for r in rows if r.avg_days_to_award) / len(rows)
                    std = sum(float(r.stddev_days_to_award) for r in rows if r.stddev_days_to_award) / len(rows) if rows else 30.0
                    start = closing_date + timedelta(days=max(0, int(avg - std)))
                    end = closing_date + timedelta(days=int(avg + std))
                    return start, end

        start = closing_date + timedelta(days=15)
        end = closing_date + timedelta(days=45)
        return start, end
