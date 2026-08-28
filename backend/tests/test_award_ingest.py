"""End-to-end coverage for the award ingest loop.

This job creates every lead in the platform and had no test that ran it. The
H2 defect — competitor intelligence silently empty for every lead since it
shipped — lived here and was invisible precisely because nothing exercised the
loop from raw award to created opportunity.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.opportunity import Opportunity
from app.models.tender import Tender

# The two identifiers that the H2 defect conflated.
TENDER_ROW_UUID = "8f14e45f-ceea-467a-9d1a-1f3f9a0b1c2d"  # TSA t.id, and a.tender_id
TENDER_REFERENCE = "RFQ-2026-0042"                        # TSA t.tender_id

NOW_UTC = datetime(2026, 6, 1, tzinfo=timezone.utc)


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
    """The H1 regression, against the persisted cursor rather than a model of it.

    The unit tests in test_award_check.py cover _resolve_award_date's provenance
    flag. These assert what check_awards_for_watching actually writes to
    award_ingestion_state, which is the value that decides what the next run
    asks Tenders-SA for.
    """

    @staticmethod
    async def _cursor(session_factory):
        from app.models.award_ingestion_state import AwardIngestionState

        async with session_factory() as db:
            state = await db.get(AwardIngestionState, "tenders_sa")
        return state.latest_award_at if state else None

    async def test_one_corrupt_date_does_not_drag_the_cursor_to_today(
        self, ingest_env, tsa_stub, monkeypatch
    ):
        import app.jobs.award_check as award_check

        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub, awards=[
            _award("a1", "Alpha Co", "2026-06-01"),
            _award("a2", "Beta Co", "2026-06-10"),
            # Nothing usable: a corrupt year AND no created_at, so the resolver
            # must synthesise a date from discovered_at, which is ~now. This is
            # the row that used to drag the cursor forward.
            {**_award("a3", "Gamma Co", "2099-10-09"), "created_at": None},
        ]))
        await award_check.check_awards_for_watching()

        cursor = await self._cursor(ingest_env)
        assert cursor is not None
        assert cursor.date().isoformat() == "2026-06-10", (
            f"cursor was dragged to {cursor} by a synthesised date; the next run "
            "would skip every award published later with an older award_date"
        )

    async def test_cursor_tracks_the_newest_source_backed_date(
        self, ingest_env, tsa_stub, monkeypatch
    ):
        import app.jobs.award_check as award_check

        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub, awards=[
            _award("a1", "Alpha Co", "2026-06-01"),
            _award("a2", "Beta Co", "2026-08-20"),
            _award("a3", "Gamma Co", "2026-07-04"),
        ]))
        await award_check.check_awards_for_watching()

        cursor = await self._cursor(ingest_env)
        assert cursor.date().isoformat() == "2026-08-20"

    async def test_a_batch_of_only_corrupt_dates_leaves_the_cursor_unset(
        self, ingest_env, tsa_stub, monkeypatch
    ):
        """Better to re-read the lookback window than to skip forward blindly."""
        import app.jobs.award_check as award_check

        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub, awards=[
            {**_award("a1", "Alpha Co", "2099-01-01"), "created_at": None},
        ]))
        await award_check.check_awards_for_watching()

        assert await self._cursor(ingest_env) is None


class TestCorruptedDateScan:
    """Regression guard for the M3 defect.

    find_corrupted_award_dates selected every healthy award with a payload,
    materialised all of them, and filtered in Python by re-parsing the raw JSON
    year — a full table scan running nightly and growing forever.
    """

    @staticmethod
    async def _seed(session_factory, rows):
        from app.models.award import Award

        async with session_factory() as db:
            for i, (date_source, award_date) in enumerate(rows):
                db.add(Award(
                    id=f"a{i}", api_id=f"api-{i}", tender_id="t1", supplier_name="S",
                    discovered_at=NOW_UTC, award_date=award_date, date_source=date_source,
                    raw_payload={"award_date": "2026-06-01"},
                ))
            await db.commit()

    async def test_healthy_awards_are_not_scanned(self, ingest_env):
        from app.jobs.award_check import find_corrupted_award_dates

        await self._seed(ingest_env, [("source", NOW_UTC)] * 5)
        async with ingest_env() as db:
            assert await find_corrupted_award_dates(db) == []

    async def test_synthesised_awards_are_scanned(self, ingest_env):
        from app.jobs.award_check import find_corrupted_award_dates

        await self._seed(ingest_env, [("source", NOW_UTC), ("synthesised", NOW_UTC)])
        async with ingest_env() as db:
            found = await find_corrupted_award_dates(db)
        assert [a.date_source for a in found] == ["synthesised"]

    async def test_unmarked_awards_are_scanned(self, ingest_env):
        """Rows written before the column existed, until the CLI backfill runs."""
        from app.jobs.award_check import find_corrupted_award_dates

        await self._seed(ingest_env, [(None, NOW_UTC)])
        async with ingest_env() as db:
            assert len(await find_corrupted_award_dates(db)) == 1

    async def test_the_scan_is_bounded(self, ingest_env, monkeypatch):
        import app.jobs.award_check as award_check

        monkeypatch.setattr(award_check, "REPAIR_BATCH_SIZE", 3)
        await self._seed(ingest_env, [("synthesised", NOW_UTC)] * 10)
        async with ingest_env() as db:
            assert len(await award_check.find_corrupted_award_dates(db)) == 3

    async def test_ingest_records_provenance(self, ingest_env, tsa_stub, monkeypatch):
        """A repaired award drops out of the scan permanently."""
        from sqlalchemy import select as _select

        import app.jobs.award_check as award_check
        from app.models.award import Award

        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub))
        await award_check.check_awards_for_watching()

        async with ingest_env() as db:
            award = (await db.execute(_select(Award))).scalars().one()
        assert award.date_source == "source"


class TestBatching:
    """Regression guard for the M2 defect.

    The loop issued a company lookup, an award lookup, a watchlist lookup, an
    opportunity lookup and up to two tender lookups per award, plus one query to
    the external Tenders-SA database per award for the buyer organisation —
    roughly 30,000 local queries and 5,000 remote ones for a 5,000-award page.
    """

    @staticmethod
    def _awards(count: int) -> list[dict]:
        return [
            _award(f"award-{i}", f"Supplier {i}", "2026-06-01")
            for i in range(count)
        ]

    async def test_query_count_barely_grows_with_batch_size(
        self, ingest_env, tsa_stub, monkeypatch
    ):
        import app.jobs.award_check as award_check

        counts = {}
        for size in (2, 40):
            # A fresh database per size, so the second run is not a no-op.
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
            from sqlalchemy.pool import StaticPool

            import app.database as database

            engine = create_async_engine(
                "sqlite+aiosqlite://",
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
            )
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with engine.begin() as conn:
                await conn.run_sync(database.Base.metadata.create_all)

            issued = 0
            original = factory

            def counting_factory(*, _f=original):
                session = _f()
                inner = session.execute

                async def counting(statement, *args, **kwargs):
                    nonlocal issued
                    issued += 1
                    return await inner(statement, *args, **kwargs)

                session.execute = counting
                return session

            monkeypatch.setattr(award_check, "async_session", counting_factory)
            stub = _stub(tsa_stub, awards=self._awards(size))
            monkeypatch.setattr(award_check, "TSADatabase", lambda: stub)

            await award_check.check_awards_for_watching()
            counts[size] = issued
            await engine.dispose()

        # Every upsert and context lookup is now batched, so the only queries
        # that still scale with the batch are two per-company aggregates: the
        # 12-month award total for funding suitability, and the prior-award
        # count for lead priority. Both are genuine per-company reads over the
        # awards table; batching them needs a GROUP BY and is tracked as
        # follow-up work in remediation-04.
        #
        # Was roughly 7 local queries per award plus one remote call each.
        marginal = (counts[40] - counts[2]) / (40 - 2)
        assert marginal <= 3, (
            f"{marginal:.1f} queries per additional award (expected <= 3): {counts}"
        )

    async def test_the_buyer_organisation_is_fetched_once_per_run(
        self, ingest_env, tsa_stub, monkeypatch
    ):
        import app.jobs.award_check as award_check

        stub = _stub(tsa_stub, awards=self._awards(10))
        monkeypatch.setattr(award_check, "TSADatabase", lambda: stub)
        await award_check.check_awards_for_watching()

        org_queries = [sql for sql, _ in stub.calls if "FROM source_organizations" in sql]
        assert len(org_queries) == 1, (
            f"queried the external database {len(org_queries)} times for organisations"
        )

    async def test_two_awards_for_one_new_tender_create_one_tender(
        self, ingest_env, tsa_stub, monkeypatch
    ):
        """The cache must write new rows back, or a preload would let a second
        award in the same batch insert a duplicate."""
        from sqlalchemy import select as _select

        import app.jobs.award_check as award_check
        from app.models.company import Company

        monkeypatch.setattr(award_check, "TSADatabase", lambda: _stub(tsa_stub, awards=[
            _award("a1", "Sizwe Construction", "2026-06-01"),
            _award("a2", "Sizwe Construction", "2026-06-02"),
        ]))
        await award_check.check_awards_for_watching()

        async with ingest_env() as db:
            tenders = (await db.execute(_select(Tender))).scalars().all()
            companies = (await db.execute(_select(Company))).scalars().all()
            opps = (await db.execute(_select(Opportunity))).scalars().all()

        assert len(tenders) == 1, "the same tender was inserted twice"
        assert len(companies) == 1, "the same supplier was inserted twice"
        assert len(opps) == 2, "each award should still produce its own lead"
