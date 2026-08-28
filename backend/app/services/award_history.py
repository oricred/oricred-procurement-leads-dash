"""Per-supplier award aggregates, batchable.

Lead scoring and funding suitability each ran their own aggregate over the
awards table, per company, inside the award ingest loop — two queries per new
lead. Both now read from the same value object, which a caller processing many
companies can fetch in one grouped query.

See docs/specifications/remediation-04-query-performance.md section 2.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.award import Award

RECENT_WINDOW_DAYS = 365


@dataclass(frozen=True)
class AwardHistory:
    """What both scoring paths need to know about a supplier's prior awards."""

    award_count: int = 0
    total_value: Decimal = Decimal("0")
    value_last_12m: Decimal = Decimal("0")

    def including(self, amount: object, *, recent: bool = True) -> "AwardHistory":
        """This history plus one more award.

        The award ingest loop reads history in one grouped query before it
        inserts the batch, but scores each lead after inserting its award. The
        original per-lead query ran after the insert, so it counted the award
        being processed. Adding it back here keeps the batching a pure
        performance change rather than a silent shift in lead priority.
        """
        value = Decimal(str(amount or 0))
        return AwardHistory(
            award_count=self.award_count + 1,
            total_value=self.total_value + value,
            value_last_12m=self.value_last_12m + (value if recent else Decimal("0")),
        )


async def load_award_history(
    company_api_ids: list[str], db: AsyncSession
) -> dict[str, AwardHistory]:
    """One grouped query for every supplier in a batch.

    Keyed by Company.api_id, which is what awards.supplier_company_id holds.
    Suppliers with no awards are absent; callers should treat a miss as the
    empty AwardHistory.
    """
    if not company_api_ids:
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_WINDOW_DAYS)
    rows = await db.execute(
        select(
            Award.supplier_company_id,
            func.count(Award.id),
            func.coalesce(func.sum(Award.amount), 0),
            func.coalesce(
                func.sum(
                    # SQLAlchemy renders this as a CASE, so one pass covers both
                    # the all-time and the 12-month totals.
                    func.coalesce(Award.amount, 0)
                ).filter(Award.award_date >= cutoff),
                0,
            ),
        )
        .where(Award.supplier_company_id.in_(company_api_ids))
        .group_by(Award.supplier_company_id)
    )

    return {
        str(api_id): AwardHistory(
            award_count=int(count or 0),
            total_value=Decimal(str(total or 0)),
            value_last_12m=Decimal(str(recent or 0)),
        )
        for api_id, count, total, recent in rows.all()
        if api_id
    }


async def load_one(company_api_id: str | None, db: AsyncSession) -> AwardHistory:
    """Single-supplier convenience for callers outside a batch."""
    if not company_api_id:
        return AwardHistory()
    return (await load_award_history([company_api_id], db)).get(
        company_api_id, AwardHistory()
    )
