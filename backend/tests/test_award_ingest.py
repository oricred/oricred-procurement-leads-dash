"""End-to-end coverage for the award ingest loop.

This job creates every lead in the platform and had no test that ran it. The
H2 defect — competitor intelligence silently empty for every lead since it
shipped — lived here and was invisible precisely because nothing exercised the
loop from raw award to created opportunity.
"""

import pytest
from sqlalchemy import select

from app.models.opportunity import Opportunity
from app.models.tender import Tender

# The two identifiers that the H2 defect conflated.
TENDER_ROW_UUID = "8f14e45f-ceea-467a-9d1a-1f3f9a0b1c2d"  # TSA t.id, and a.tender_id
TENDER_REFERENCE = "RFQ-2026-0042"                        # TSA t.tender_id


@pytest.fixture
async def ingest_env(monkeypatch):
    """Point every module the job touches at one in-memory database."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    import app.database as database
    import app.jobs.award_check as award_check
    import app.services.contact_enrichment as enrichment
    import app.services.lead_service as lead_service

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(database.Base.metadata.create_all)

    for module in (award_check, enrichment, lead_service):
        monkeypatch.setattr(module, "async_session", session_factory)

    # Keep the job off the network: no CRM push, no contact lookups.
    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(award_check, "push_opportunity_to_crm", noop)
    monkeypatch.setattr(award_check, "retry_new_lead_contact_lookups", noop)

    async def no_lookup(opportunity_id, db, tsa_db=None):
        return await db.get(Opportunity, opportunity_id), enrichment.EnrichmentResult()

    monkeypatch.setattr(award_check, "retry_contact_lookup_for_opportunity", no_lookup)

    yield session_factory
    await engine.dispose()


def _award(award_id="award-1", supplier="Sizwe Construction", award_date="2026-06-01"):
    return {
        "id": award_id,
        "tender_id": TENDER_ROW_UUID,
        "supplier_name": supplier,
        "amount": 2_500_000,
        "award_date": award_date,
        "created_at": "2026-06-02T08:00:00+00:00",
        "bee_level": 2,
        "bee_points": 90,
        "supplier_canonical_id": "tsa-company-1",
    }


def _tender_metadata():
    return {
        "id": TENDER_ROW_UUID,
        # The business reference. This is what becomes Tender.api_id, and what
        # the bidder lookup used to be keyed on by mistake.
        "tender_id": TENDER_REFERENCE,
        "title": "UPGRADE OF NATIONAL ROAD N2",
        "description": "Road works",
        "estimated_value": 3_000_000,
        "province": "wc",
        "category_id": "construction",
        "closing_date": "2026-05-01T00:00:00+00:00",
        "source_organization_id": "org-1",
        "source_organization": "SANRAL",
        "type": "open",
        "publication_date": "2026-04-01T00:00:00+00:00",
    }


def _stub(tsa_stub, *, bidders=None, awards=None, metadata=None):
    tsa_stub.queue("tender_awards", awards if awards is not None else [_award()])
    tsa_stub.queue("tenders", [metadata if metadata is not None else _tender_metadata()])
    tsa_stub.queue("companies", [{"id": "tsa-company-1", "name": "Sizwe Construction"}])
    tsa_stub.queue("source_organizations", [{"id": "org-1", "name": "SANRAL"}])
    tsa_stub.queue("tender_bidders", bidders or [])
    return tsa_stub


class TestAwardIngestCreatesLeads:
    async def test_an_award_becomes_an_opportunity(self, ingest_env, tsa_stub, monkeypatch):
        import app.jobs.award_check as award_check

        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub))
        await award_check.check_awards_for_watching()

        async with ingest_env() as db:
            opps = (await db.execute(select(Opportunity))).scalars().all()
        assert len(opps) == 1
        assert opps[0].kanban_stage == "new_lead"

    async def test_reingesting_the_same_award_creates_no_duplicate(
        self, ingest_env, tsa_stub, monkeypatch
    ):
        import app.jobs.award_check as award_check

        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub))
        await award_check.check_awards_for_watching()
        await award_check.check_awards_for_watching()

        async with ingest_env() as db:
            assert len((await db.execute(select(Opportunity))).scalars().all()) == 1

    async def test_tender_api_id_is_the_business_reference(self, ingest_env, tsa_stub, monkeypatch):
        import app.jobs.award_check as award_check

        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub))
        await award_check.check_awards_for_watching()

        async with ingest_env() as db:
            tender = (await db.execute(select(Tender))).scalars().one()
        assert tender.api_id == TENDER_REFERENCE


class TestRelatedBidders:
    """The H2 regression.

    Bidders are indexed by the TSA row UUID (b.tender_id == t.id). The lookup
    used tender.api_id, which holds the business reference. The two key spaces
    never intersect, so related_bidders was None for every lead.
    """

    async def test_bidders_are_attached_to_the_new_opportunity(
        self, ingest_env, tsa_stub, monkeypatch
    ):
        import app.jobs.award_check as award_check

        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub, bidders=[
            {"id": "b1", "tender_id": TENDER_ROW_UUID, "name": "Rival One"},
            {"id": "b2", "tender_id": TENDER_ROW_UUID, "name": "Rival Two"},
        ]))
        await award_check.check_awards_for_watching()

        async with ingest_env() as db:
            opp = (await db.execute(select(Opportunity))).scalars().one()
        assert opp.related_bidders is not None, "bidder map key never matched the lookup key"
        assert {b["name"] for b in opp.related_bidders} == {"Rival One", "Rival Two"}
        assert all(b["inferred"] is False for b in opp.related_bidders)

    async def test_the_winning_supplier_is_excluded(self, ingest_env, tsa_stub, monkeypatch):
        import app.jobs.award_check as award_check

        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub, bidders=[
            {"id": "b1", "tender_id": TENDER_ROW_UUID, "name": "Rival One"},
            {"id": "b2", "tender_id": TENDER_ROW_UUID, "name": "SIZWE CONSTRUCTION"},
        ]))
        await award_check.check_awards_for_watching()

        async with ingest_env() as db:
            opp = (await db.execute(select(Opportunity))).scalars().one()
        assert {b["name"] for b in opp.related_bidders} == {"Rival One"}

    async def test_no_bidders_leaves_the_field_null(self, ingest_env, tsa_stub, monkeypatch):
        import app.jobs.award_check as award_check

        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub, bidders=[]))
        await award_check.check_awards_for_watching()

        async with ingest_env() as db:
            opp = (await db.execute(select(Opportunity))).scalars().one()
        assert opp.related_bidders is None


class TestIngestCursor:
    """The H1 regression, against the persisted cursor.

    The original defect: the watermark was taken from the *resolved* award date,
    whose last-resort branch is "now", so one unparseable date pushed the cursor
    to today and every award published later with an older award_date was
    permanently skipped.

    The cursor now reads the source row's created_at — a monotonic ingestion
    timestamp rather than a procurement event — so a bad award_date cannot
    reach it at all. Every run also re-reads a full lookback window.
    """

    @staticmethod
    async def _cursor(session_factory):
        from app.models.award_ingestion_state import AwardIngestionState

        async with session_factory() as db:
            state = await db.get(AwardIngestionState, "tenders_sa")
        return state.latest_award_at if state else None

    async def test_a_corrupt_award_date_cannot_move_the_cursor(
        self, ingest_env, tsa_stub, monkeypatch
    ):
        import app.jobs.award_check as award_check

        awards = [
            {**_award("a1", "Alpha Co", "2026-06-01"), "created_at": "2026-06-02T08:00:00+00:00"},
            # Unusable award_date and no created_at: the resolver must synthesise
            # a date near now, and that must not become the watermark.
            {**_award("a2", "Beta Co", "2099-10-09"), "created_at": None},
        ]
        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub, awards=awards))
        await award_check.check_awards_for_watching()

        cursor = await self._cursor(ingest_env)
        assert cursor is not None
        assert cursor.date().isoformat() == "2026-06-02", (
            f"cursor moved to {cursor} on a synthesised date; the next run would "
            "skip every award published later with an older date"
        )

    async def test_the_cursor_tracks_the_newest_source_timestamp(
        self, ingest_env, tsa_stub, monkeypatch
    ):
        import app.jobs.award_check as award_check

        awards = [
            {**_award("a1", "Alpha Co"), "created_at": "2026-06-02T08:00:00+00:00"},
            {**_award("a2", "Beta Co"), "created_at": "2026-08-20T08:00:00+00:00"},
            {**_award("a3", "Gamma Co"), "created_at": "2026-07-04T08:00:00+00:00"},
        ]
        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub, awards=awards))
        await award_check.check_awards_for_watching()

        cursor = await self._cursor(ingest_env)
        assert cursor.date().isoformat() == "2026-08-20"

    async def test_the_award_date_never_reaches_the_cursor(
        self, ingest_env, tsa_stub, monkeypatch
    ):
        """A far-future award_date with an ordinary created_at must leave the
        watermark on the created_at."""
        import app.jobs.award_check as award_check

        awards = [
            {**_award("a1", "Alpha Co", "2099-01-01"), "created_at": "2026-06-02T08:00:00+00:00"},
        ]
        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub, awards=awards))
        await award_check.check_awards_for_watching()

        cursor = await self._cursor(ingest_env)
        assert cursor.date().isoformat() == "2026-06-02"

    async def test_a_second_run_re_reads_a_lookback_window(
        self, ingest_env, tsa_stub, monkeypatch
    ):
        """The overlap is what stops a late-published award falling through the
        boundary between two runs."""
        import app.jobs.award_check as award_check

        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub))
        await award_check.check_awards_for_watching()
        cursor_after_first = await self._cursor(ingest_env)

        stub2 = _stub(tsa_stub)
        monkeypatch.setattr(award_check, "TSADatabase", lambda: stub2)
        await award_check.check_awards_for_watching()

        # The award query filters on the source row's created_at, so the bind
        # parameter is created_since rather than since.
        since_values = [
            params["created_since"] for _sql, params in stub2.calls if "created_since" in params
        ]
        assert since_values, "no created_since filter was sent on the second run"
        watermark = cursor_after_first.replace(tzinfo=None)
        assert min(since_values) < watermark, (
            "the second run started at the watermark with no overlap, so a "
            "late-published older award would fall through the boundary"
        )


