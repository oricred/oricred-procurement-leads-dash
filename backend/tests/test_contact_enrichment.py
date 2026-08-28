"""Behavioural coverage for the contact enrichment path.

This is the code where every critical finding in the 2026-08 review lived, and
which had no test at all. Each class below pins one of the three rules stated in
the module docstring of app/services/contact_enrichment.py.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.models.company import Company
from app.models.contact import Contact
from app.services.contact_enrichment import (
    RECOVERABLE,
    EnrichmentResult,
    _index_by_normalised_name,
    _resolve_unique,
    enrich_company_contacts_by_id,
)


@pytest.fixture
async def db_session(monkeypatch):
    """An in-memory SQLite session with the current schema.

    StaticPool keeps every checkout on the same connection, which is what makes
    ``:memory:`` usable — a fresh connection would see an empty database.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    import app.database as database
    import app.services.contact_enrichment as enrichment

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(database.Base.metadata.create_all)

    monkeypatch.setattr(enrichment, "async_session", session_factory)
    yield session_factory
    await engine.dispose()


async def _make_company(session_factory, name="Sizwe Construction", api_id="tsa-company-1"):
    async with session_factory() as db:
        company = Company(api_id=api_id, name=name)
        db.add(company)
        await db.commit()
        await db.refresh(company)
        return company


class TestPhoneOnlyContacts:
    """Rule 2: 'no email' is NULL, and any number of those may coexist."""

    async def test_two_phone_only_directors_both_persist(self, db_session, tsa_stub):
        company = await _make_company(db_session)
        tsa_stub.queue("directors", [
            {"full_name": "Thabo Mokoena", "email": None, "phone": "0821111111"},
            {"full_name": "Naledi Dlamini", "email": None, "phone": "0822222222"},
        ])

        result = await enrich_company_contacts_by_id(company.id, tsa_stub)

        assert result.added == 2, "the second phone-only contact was rejected"
        assert result.errors == 0
        async with db_session() as db:
            rows = (await db.execute(select(Contact))).scalars().all()
        assert {c.last_name for c in rows} == {"Mokoena", "Dlamini"}
        assert all(c.email is None for c in rows), "email must be NULL, never ''"

    async def test_rerunning_enrichment_adds_no_duplicates(self, db_session, tsa_stub):
        company = await _make_company(db_session)
        tsa_stub.queue("directors", [
            {"full_name": "Thabo Mokoena", "email": None, "phone": "0821111111"},
        ])

        first = await enrich_company_contacts_by_id(company.id, tsa_stub)
        second = await enrich_company_contacts_by_id(company.id, tsa_stub)

        assert first.added == 1
        assert second.added == 0
        async with db_session() as db:
            assert len((await db.execute(select(Contact))).scalars().all()) == 1

    async def test_a_contact_with_neither_email_nor_phone_is_skipped(self, db_session, tsa_stub):
        company = await _make_company(db_session)
        tsa_stub.queue("directors", [{"full_name": "No Contact Details"}])
        result = await enrich_company_contacts_by_id(company.id, tsa_stub)
        assert result.added == 0

    async def test_phone_backfills_an_existing_contact(self, db_session, tsa_stub):
        company = await _make_company(db_session)
        async with db_session() as db:
            db.add(Contact(company_id=company.id, first_name="Thabo", last_name="Mokoena"))
            await db.commit()

        tsa_stub.queue("directors", [
            {"full_name": "Thabo Mokoena", "email": None, "phone": "0821111111"},
        ])
        result = await enrich_company_contacts_by_id(company.id, tsa_stub)

        assert result.added == 0
        async with db_session() as db:
            contact = (await db.execute(select(Contact))).scalars().one()
        assert contact.phone_direct == "0821111111"
        assert contact.job_title == "Director"


class TestErrorsAreNotSilentlyEmpty:
    """Rule 1: a failure must be distinguishable from an empty result."""

    async def test_a_recoverable_failure_is_counted_not_swallowed(self, db_session, tsa_stub):
        company = await _make_company(db_session)

        async def boom(**_kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        tsa_stub.query_directors = boom
        tsa_stub.query_key_personnel = boom

        result = await enrich_company_contacts_by_id(company.id, tsa_stub)

        assert result.added == 0
        assert result.errors == 2, "an outage must not look like 'no contacts on file'"

    async def test_an_empty_source_reports_zero_errors(self, db_session, tsa_stub):
        company = await _make_company(db_session)
        result = await enrich_company_contacts_by_id(company.id, tsa_stub)
        assert result.added == 0
        assert result.errors == 0

    async def test_a_programming_error_propagates(self, db_session, tsa_stub):
        """The C1 class of defect must reach the job runner, not a warning log."""
        company = await _make_company(db_session)

        async def bug(**_kwargs):
            raise NameError("name 'offset' is not defined")

        tsa_stub.query_directors = bug

        with pytest.raises(NameError):
            await enrich_company_contacts_by_id(company.id, tsa_stub)

    def test_recoverable_does_not_include_bare_exception(self):
        assert Exception not in RECOVERABLE
        assert NameError not in RECOVERABLE
        assert AttributeError not in RECOVERABLE


class TestResultArithmetic:
    def test_results_add(self):
        total = EnrichmentResult(2, 1, 3) + EnrichmentResult(4, 0, 5)
        assert (total.added, total.errors, total.companies_attempted) == (6, 1, 8)

    def test_error_rate_with_nothing_attempted_is_zero(self):
        assert EnrichmentResult().error_rate == 0.0

    def test_error_rate(self):
        assert EnrichmentResult(errors=1, companies_attempted=4).error_rate == 0.25


class TestUnambiguousMatching:
    """Rule 3: an uncertain match is worse than no match."""

    def test_exact_normalised_match_resolves(self):
        index = _index_by_normalised_name([
            {"id": "tsa-1", "name": "ABC TRADING PTY LTD"},
        ])
        assert _resolve_unique(index, "ABC Trading (Pty) Ltd", "company") == "tsa-1"

    def test_substring_no_longer_matches(self):
        """'ABC Trading' must not silently resolve to 'ABC Trading Holdings'."""
        index = _index_by_normalised_name([
            {"id": "tsa-1", "name": "ABC Trading Holdings"},
        ])
        assert _resolve_unique(index, "ABC Trading", "company") is None

    def test_ambiguous_names_resolve_to_nothing(self):
        index = _index_by_normalised_name([
            {"id": "tsa-1", "name": "ABC Trading (Pty) Ltd"},
            {"id": "tsa-2", "name": "ABC Trading CC"},
        ])
        assert _resolve_unique(index, "ABC Trading", "company") is None

    def test_no_candidate_resolves_to_nothing(self):
        assert _resolve_unique({}, "Nobody Ltd", "company") is None

    async def test_an_ambiguous_company_gets_no_contacts(self, db_session, tsa_stub):
        """The M8 regression: never attach one company's directors to another."""
        company = await _make_company(db_session, name="ABC Trading", api_id="historical:abc")
        tsa_stub.queue("companies", [
            {"id": "tsa-1", "name": "ABC Trading (Pty) Ltd"},
            {"id": "tsa-2", "name": "ABC Trading CC"},
        ])
        tsa_stub.queue("directors", [
            {"full_name": "Wrong Person", "email": "wrong@example.com", "phone": None},
        ])

        result = await enrich_company_contacts_by_id(company.id, tsa_stub)

        assert result.added == 0
        async with db_session() as db:
            assert (await db.execute(select(Contact))).scalars().all() == []
