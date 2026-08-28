"""Regression guard for the M7 defect.

list_historical_contacts applied its LIMIT first and then filtered
contactability in Python, so asking for 100 contactable companies could return
four with no indication the list had been truncated before filtering. It also
issued one contact query per row, up to 500 deep.

The filter moved into SQL, which introduces a new risk: the EXISTS predicate and
classify_company_contacts must agree, or the filter and the badge rendered
beside it contradict each other. TestFilterAgreesWithBadge pins that.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.api.historical_contacts import _has_reachable_contact
from app.models.company import Company
from app.models.contact import Contact
from app.models.historical_contact import HistoricalContact
from app.services.lead_scoring import classify_company_contacts

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
async def hc_db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    import app.database as database

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(database.Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


async def _company(session_factory, company_id: str, contacts: list[dict]):
    async with session_factory() as db:
        db.add(Company(id=company_id, api_id=f"api-{company_id}", name=f"Co {company_id}"))
        db.add(HistoricalContact(company_id=company_id, source="tenders_api", award_ids=[]))
        for i, fields in enumerate(contacts):
            db.add(Contact(
                company_id=company_id,
                first_name=f"First{i}",
                last_name=f"Last{i}",
                **fields,
            ))
        await db.commit()


# Every combination of the three reachable fields, plus no contact at all.
CONTACT_SHAPES = [
    pytest.param([], id="no-contacts"),
    pytest.param([{}], id="name-only"),
    pytest.param([{"email": "a@example.com"}], id="email"),
    pytest.param([{"phone_direct": "0821111111"}], id="phone-direct"),
    pytest.param([{"phone_mobile": "0822222222"}], id="phone-mobile"),
    pytest.param([{"email": "a@example.com", "phone_direct": "0821111111"}], id="email+direct"),
    pytest.param([{}, {"email": "b@example.com"}], id="one-of-two-reachable"),
]


class TestFilterAgreesWithBadge:
    @pytest.mark.parametrize("contacts", CONTACT_SHAPES)
    async def test_sql_predicate_matches_the_python_classifier(self, hc_db, contacts):
        await _company(hc_db, "c1", contacts)

        async with hc_db() as db:
            matched = await db.scalar(
                select(func.count()).select_from(Company).where(_has_reachable_contact())
            )
            rows = (
                await db.execute(select(Contact).where(Contact.company_id == "c1"))
            ).scalars().all()

        badge = classify_company_contacts(rows)
        assert bool(matched) == (badge == "sufficient"), (
            f"SQL says reachable={bool(matched)} but the badge says {badge!r}"
        )


class TestFilterIsAppliedBeforeTheLimit:
    async def test_a_full_page_of_contactable_companies_is_returned(self, hc_db):
        """The M7 regression: 20 unreachable companies sort ahead of 5 reachable
        ones. Filtering after the limit would return nothing."""
        for i in range(20):
            await _company(hc_db, f"unreachable-{i}", [{}])
        for i in range(5):
            await _company(hc_db, f"reachable-{i}", [{"email": f"r{i}@example.com"}])

        async with hc_db() as db:
            reachable = (
                await db.execute(
                    select(Company).where(_has_reachable_contact()).limit(10)
                )
            ).scalars().all()

        assert len(reachable) == 5

    async def test_needs_contact_is_the_complement(self, hc_db):
        await _company(hc_db, "reachable", [{"email": "a@example.com"}])
        await _company(hc_db, "unreachable", [{}])
        await _company(hc_db, "no-contacts", [])

        async with hc_db() as db:
            needs = (
                await db.execute(select(Company.id).where(~_has_reachable_contact()))
            ).scalars().all()

        assert set(needs) == {"unreachable", "no-contacts"}


class TestContactsAreBatchLoaded:
    async def test_one_query_loads_every_page_row(self, hc_db):
        """Was one query per row, up to the 500-row limit."""
        for i in range(10):
            await _company(hc_db, f"c{i}", [{"email": f"c{i}@example.com"}])

        async with hc_db() as db:
            company_ids = (await db.execute(select(Company.id))).scalars().all()
            statements = []
            original = db.execute

            async def counting(statement, *args, **kwargs):
                statements.append(statement)
                return await original(statement, *args, **kwargs)

            db.execute = counting
            contacts = (
                await db.execute(select(Contact).where(Contact.company_id.in_(company_ids)))
            ).scalars().all()

        assert len(contacts) == 10
        assert len(statements) == 1
