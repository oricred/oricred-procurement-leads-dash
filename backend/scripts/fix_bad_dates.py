"""Fix bad award dates (year > 2027) and poisoned ingestion state.

Run:  cd backend && .venv/bin/python scripts/fix_bad_dates.py
"""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select, text

from app.database import async_session, engine
from app.models.award import Award
from app.models.award_ingestion_state import AwardIngestionState
from app.models.historical_contact import HistoricalContact


async def fix_bad_dates():
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        # ── Fix Awards with future dates ──
        result = await db.execute(select(Award).where(Award.award_date > now))
        bad_awards = result.scalars().all()
        for a in bad_awards:
            print(f"Nullifying award_date {a.award_date} for award {a.id} ({a.supplier_name})")
            a.award_date = None
        await db.commit()
        print(f"Fixed {len(bad_awards)} awards with future dates")

        # ── Fix HistoricalContact with future dates ──
        for col in ("first_award_date", "last_award_date"):
            result = await db.execute(
                select(HistoricalContact).where(
                    getattr(HistoricalContact, col) > now
                )
            )
            bad_hc = result.scalars().all()
            for hc in bad_hc:
                print(f"Nullifying {col}={getattr(hc, col)} for historical_contact {hc.id}")
                setattr(hc, col, None)
        await db.commit()
        print(f"Fixed {len(bad_hc)} historical contacts with future {col}")

        # ── Fix poisoned ingestion state ──
        state = await db.get(AwardIngestionState, "tenders_sa")
        if state and state.latest_award_at and state.latest_award_at > now:
            new_since = now.replace(tzinfo=None)
            print(f"Resetting latest_award_at from {state.latest_award_at} to {new_since}")
            state.latest_award_at = new_since
            await db.commit()
        else:
            print("Ingestion state OK")

        # ── Verify fix ──
        remaining = await db.execute(
            select(Award).where(Award.award_date > now)
        )
        still_bad = remaining.scalars().all()
        print(f"Remaining bad awards: {len(still_bad)}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(fix_bad_dates())
