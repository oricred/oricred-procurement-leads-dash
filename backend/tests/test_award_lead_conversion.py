"""The awards -> lead inbox -> deal pipeline journey.

Covers the manual conversion endpoint, the inbox query that has to surface the
resulting lead, and the promotion that moves it onto the pipeline board.
"""

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.auth import get_current_user
from app.api.awards import router as awards_router
from app.api.leads import router as leads_router
from app.api.opportunities import router as opportunities_router
from app.database import Base, get_db
from app.models.award import Award
from app.models.company import Company
from app.models.opportunity import Opportunity, OpportunityAudit
from app.models.organization import Organization
from app.models.tender import Tender

NOW = datetime(2026, 8, 17, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def journey():
    """A client wired to a real in-memory database, plus its session factory."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        # Applied at runtime by _ensure_opportunity_columns, not by create_all.
        await connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_opportunities_award_id "
            "ON opportunities(award_id) WHERE award_id IS NOT NULL"
        ))

    sessions = async_sessionmaker(engine, expire_on_commit=False)

    app = FastAPI()
    app.include_router(awards_router, prefix="/api")
    app.include_router(leads_router, prefix="/api")
    app.include_router(opportunities_router, prefix="/api/opportunities")

    async def override_get_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "ops@oricred.com", "name": "Ops User", "role": "admin",
    }

    with TestClient(app) as client:
        yield client, sessions

    await engine.dispose()


async def _seed_award(sessions, *, with_tender=True, with_company=True, supplier="Bopape Civils"):
    async with sessions() as db:
        tender_id = "T-1"
        if with_tender:
            db.add(Organization(id="org-cpt", name="City of Cape Town", organization_type="municipal"))
            db.add(Tender(
                id=tender_id, api_id="T-1", title="Bulk water pipeline", raw_payload={},
                buyer_org_id="org-cpt", province="wc", discovered_at=NOW,
            ))
        company_api_id = None
        if with_company:
            company_api_id = "co-1"
            db.add(Company(id="c-1", api_id=company_api_id, name=supplier, bee_level=2))
        db.add(Award(
            id="aw-1", api_id="A-1", tender_id=tender_id, supplier_name=supplier,
            supplier_company_id=company_api_id, amount=2_500_000, award_date=NOW,
            source="tenders_api", discovered_at=NOW,
        ))
        await db.commit()
    return "aw-1"


# ---------------------------------------------------------------------------
# Award -> Lead
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_converting_an_award_creates_a_new_lead_and_audits_the_actor(journey):
    client, sessions = journey
    await _seed_award(sessions)

    response = client.post("/api/awards/aw-1/lead")

    assert response.status_code == 201
    body = response.json()
    assert body["kanban_stage"] == "new_lead"
    assert body["award_id"] == "aw-1"
    assert body["company_name"] == "Bopape Civils"

    async with sessions() as db:
        opp = (await db.execute(select(Opportunity))).scalar_one()
        assert opp.lead_origin == "manual"
        assert opp.needs_enrichment is False
        assert opp.next_action == "Find contact"

        audit = (await db.execute(select(OpportunityAudit))).scalar_one()
        assert audit.from_stage is None
        assert audit.to_stage == "new_lead"
        assert audit.changed_by == "Ops User"


@pytest.mark.asyncio
async def test_converting_the_same_award_twice_returns_the_existing_lead(journey):
    client, sessions = journey
    await _seed_award(sessions)

    first = client.post("/api/awards/aw-1/lead")
    second = client.post("/api/awards/aw-1/lead")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]

    async with sessions() as db:
        assert len((await db.execute(select(Opportunity))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_converting_an_unknown_award_is_not_found(journey):
    client, _ = journey

    assert client.post("/api/awards/missing/lead").status_code == 404


@pytest.mark.asyncio
async def test_unresolvable_supplier_creates_a_provisional_company_for_enrichment(journey):
    client, sessions = journey
    await _seed_award(sessions, with_company=False)

    response = client.post("/api/awards/aw-1/lead")

    assert response.status_code == 201
    assert response.json()["needs_enrichment"] is True

    async with sessions() as db:
        opp = (await db.execute(select(Opportunity))).scalar_one()
        assert opp.next_action == "Resolve supplier identity"
        company = await db.get(Company, opp.company_id)
        assert company.api_id == "provisional:aw-1"
        assert company.name == "Bopape Civils"


@pytest.mark.asyncio
async def test_award_list_reports_the_lead_state_once_per_award(journey):
    client, sessions = journey
    await _seed_award(sessions)
    client.post("/api/awards/aw-1/lead")

    body = client.get("/api/awards").json()

    # A tender may carry several watchlist rows; the award must not fan out.
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["lead_state"] == "new_lead"


# ---------------------------------------------------------------------------
# Lead Inbox
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_converted_award_appears_in_the_lead_inbox(journey):
    client, sessions = journey
    await _seed_award(sessions)
    created = client.post("/api/awards/aw-1/lead").json()

    body = client.get("/api/leads", params={"stage": "new_lead"}).json()

    assert body["total"] == 1
    assert body["items"][0]["id"] == created["id"]


@pytest.mark.asyncio
async def test_lead_is_still_listed_when_its_tender_row_is_missing(journey):
    client, sessions = journey
    # No FK constraints exist, so an award can outlive its tender. An inner join
    # would drop the lead from the inbox while the stats endpoints still count it.
    await _seed_award(sessions, with_tender=False)
    client.post("/api/awards/aw-1/lead")

    body = client.get("/api/leads", params={"stage": "new_lead"}).json()

    assert body["total"] == 1
    assert body["items"][0]["company_name"] == "Bopape Civils"


@pytest.mark.asyncio
async def test_inbox_rejects_an_unknown_stage_instead_of_returning_nothing(journey):
    client, _ = journey

    assert client.get("/api/leads", params={"stage": "not_a_stage"}).status_code == 400
    assert client.get("/api/leads", params={"sort": "sideways"}).status_code == 400


@pytest.mark.asyncio
async def test_newest_sort_surfaces_an_unscored_lead_above_a_scored_one(journey):
    client, sessions = journey
    await _seed_award(sessions)
    async with sessions() as db:
        db.add(Award(
            id="aw-2", api_id="A-2", tender_id="T-1", supplier_name="Older Supplier",
            amount=9_000_000, award_date=NOW, source="tenders_api", discovered_at=NOW,
        ))
        db.add(Opportunity(
            id="op-old", award_id="aw-2", tender_id="T-1", company_id="c-1",
            kanban_stage="new_lead", lead_priority_score=95,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ))
        await db.commit()

    fresh = client.post("/api/awards/aw-1/lead").json()

    by_priority = client.get("/api/leads", params={"stage": "new_lead"}).json()
    assert by_priority["items"][0]["id"] == "op-old"

    by_newest = client.get("/api/leads", params={"stage": "new_lead", "sort": "newest"}).json()
    assert by_newest["items"][0]["id"] == fresh["id"]


# ---------------------------------------------------------------------------
# Lead -> Deal Pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_promoting_a_lead_moves_it_onto_the_pipeline(journey):
    client, sessions = journey
    await _seed_award(sessions)
    lead = client.post("/api/awards/aw-1/lead").json()

    response = client.post(
        f"/api/opportunities/{lead['id']}/mark-contacted", json={"version": lead["version"]},
    )

    assert response.status_code == 200
    assert response.json()["kanban_stage"] == "client_contacted"

    # It leaves the inbox and lands in the Contacting column.
    assert client.get("/api/leads", params={"stage": "new_lead"}).json()["total"] == 0
    board = client.get("/api/opportunities", params={"stage": "client_contacted"}).json()
    assert [item["id"] for item in board["items"]] == [lead["id"]]

    async with sessions() as db:
        opp = await db.get(Opportunity, lead["id"])
        assert opp.contacted_at is not None
        assert opp.next_action == "Qualify lead"


@pytest.mark.asyncio
async def test_a_lead_stored_under_a_legacy_stage_can_still_be_promoted(journey):
    client, sessions = journey
    await _seed_award(sessions)
    lead = client.post("/api/awards/aw-1/lead").json()
    async with sessions() as db:
        opp = await db.get(Opportunity, lead["id"])
        opp.kanban_stage = "new"  # LEGACY_STAGE_MAP -> new_lead
        await db.commit()

    # The inbox shows it as a new lead, so it has to be promotable as one.
    assert client.get("/api/leads", params={"stage": "new_lead"}).json()["total"] == 1

    response = client.post(
        f"/api/opportunities/{lead['id']}/mark-contacted", json={"version": lead["version"]},
    )

    assert response.status_code == 200
    assert response.json()["kanban_stage"] == "client_contacted"


@pytest.mark.asyncio
async def test_promoting_with_a_stale_version_conflicts(journey):
    client, sessions = journey
    await _seed_award(sessions)
    lead = client.post("/api/awards/aw-1/lead").json()

    response = client.post(
        f"/api/opportunities/{lead['id']}/mark-contacted", json={"version": lead["version"] + 5},
    )

    assert response.status_code == 409
    assert "version conflict" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_an_already_promoted_lead_cannot_be_promoted_again(journey):
    client, sessions = journey
    await _seed_award(sessions)
    lead = client.post("/api/awards/aw-1/lead").json()
    promoted = client.post(
        f"/api/opportunities/{lead['id']}/mark-contacted", json={"version": lead["version"]},
    ).json()

    response = client.post(
        f"/api/opportunities/{lead['id']}/mark-contacted", json={"version": promoted["version"]},
    )

    assert response.status_code == 409
    assert "new lead" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_pipeline_can_load_one_phase_column_at_a_time(journey):
    client, sessions = journey
    await _seed_award(sessions)
    async with sessions() as db:
        for index, stage in enumerate(("new_lead", "qualified_lead", "won_opportunity", "funded")):
            db.add(Opportunity(
                id=f"op-{index}", award_id=None, tender_id="T-1", company_id="c-1",
                kanban_stage=stage,
            ))
        await db.commit()

    sales = client.get(
        "/api/opportunities", params=[("stage", "qualified_lead"), ("stage", "won_opportunity")],
    ).json()

    assert sales["total"] == 2
    assert {item["kanban_stage"] for item in sales["items"]} == {"qualified_lead", "won_opportunity"}

    assert client.get("/api/opportunities", params={"stage": "funded"}).json()["total"] == 1
    assert client.get("/api/opportunities", params={"stage": "nope"}).status_code == 400
