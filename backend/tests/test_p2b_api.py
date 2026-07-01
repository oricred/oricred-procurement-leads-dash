from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.awards import router as awards_router
from app.api.tenders import router as tenders_router
from app.api.organizations import router as orgs_router
from app.api.categories import router as categories_router
from app.api.watchlist import router as watchlist_router
from app.database import get_db
from app.schemas.award import AwardItem, AwardsList
from app.schemas.tender import TenderItem, TendersList
from app.schemas.watchlist import (
    WatchlistItemRead,
    WatchlistList,
    WatchToggleRequest,
    WatchToggleResponse,
)


# ---------------------------------------------------------------------------
# Schema unit tests
# ---------------------------------------------------------------------------

class TestAwardSchemas:
    def test_award_item_full(self):
        item = AwardItem(
            id="a1", supplier_name="Acme Corp", source="tenders_api",
            buyer_org_id="org-cpt", amount=1_500_000.0, bee_level=2,
        )
        assert item.id == "a1"
        assert item.supplier_name == "Acme Corp"
        assert item.amount == 1_500_000.0
        assert item.bee_level == 2
        assert item.opportunity_id is None

    def test_award_item_from_orm(self):
        data = {"id": "a2", "supplier_name": "BuildIt", "source": "manual", "amount": 50000}
        item = AwardItem.model_validate(data)
        assert item.supplier_name == "BuildIt"
        assert item.amount == 50000.0

    def test_award_item_nullable_fields(self):
        item = AwardItem(id="a3", supplier_name="Z", source="api")
        assert item.buyer_org_id is None
        assert item.tender_title is None
        assert item.amount is None
        assert item.award_date is None
        assert item.bee_level is None
        assert item.opportunity_id is None

    def test_awards_list_pagination(self):
        items = [AwardItem(id="a1", supplier_name="X", source="api")]
        lst = AwardsList(items=items, total=100, page=2, page_size=10)
        assert lst.total == 100
        assert lst.page == 2
        assert lst.page_size == 10

    def test_awards_list_empty(self):
        lst = AwardsList(items=[], total=0, page=1, page_size=50)
        assert len(lst.items) == 0
        assert lst.total == 0


class TestTenderSchemas:
    def test_tender_item_full(self):
        dt = datetime(2026, 7, 15, tzinfo=timezone.utc)
        item = TenderItem(
            id="t1", title="Road Works", status="watching", is_watching=True,
            province="gp", estimated_value=5_000_000.0, closing_date=dt,
            category_name="Infrastructure",
        )
        assert item.title == "Road Works"
        assert item.status == "watching"
        assert item.is_watching is True
        assert item.province == "gp"
        assert item.category_name == "Infrastructure"
        assert item.closing_date == dt

    def test_tender_item_defaults(self):
        item = TenderItem(id="t2", title="T2", status="not_watched", is_watching=False)
        assert item.estimated_value is None
        assert item.closing_date is None
        assert item.opportunity_id is None

    def test_tenders_list(self):
        items = [TenderItem(id="t1", title="T1", status="open", is_watching=False)]
        lst = TendersList(items=items, total=1, page=1, page_size=50)
        assert lst.total == 1
        assert lst.items[0].id == "t1"


class TestWatchlistSchemas:
    def test_item_with_opportunity(self):
        item = WatchlistItemRead(
            id="w1", tender_id="t1", title="Test", status="watching",
            opportunity_id="o1", opportunity_count=3,
        )
        assert item.opportunity_id == "o1"
        assert item.opportunity_count == 3

    def test_item_defaults(self):
        item = WatchlistItemRead(id="w2", tender_id="t2", title="Test2", status="watching")
        assert item.opportunity_id is None
        assert item.opportunity_count == 0
        assert item.label == "On Track"

    def test_item_decimal_value(self):
        item = WatchlistItemRead(id="w3", tender_id="t3", title="T3", status="watching",
                                 estimated_value=1234.56)
        assert item.estimated_value == Decimal("1234.56")

    def test_watchlist_list(self):
        items = [WatchlistItemRead(id="w4", tender_id="t4", title="T4", status="watching")]
        lst = WatchlistList(items=items, total=1)
        assert lst.total == 1
        assert len(lst.items) == 1

    def test_toggle_request(self):
        req = WatchToggleRequest(tender_id="abc-123")
        assert req.tender_id == "abc-123"

    def test_toggle_response_true(self):
        resp = WatchToggleResponse(is_watching=True)
        assert resp.is_watching is True
        assert resp.model_dump() == {"is_watching": True}

    def test_toggle_response_false(self):
        resp = WatchToggleResponse(is_watching=False)
        assert resp.is_watching is False


# ---------------------------------------------------------------------------
# API route integration tests (mocked DB)
# ---------------------------------------------------------------------------

def _mock_row(**kwargs):
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


@pytest.fixture
def client_and_mock():
    app = FastAPI()
    app.include_router(awards_router, prefix="/api")
    app.include_router(tenders_router, prefix="/api")
    app.include_router(orgs_router, prefix="/api")
    app.include_router(categories_router, prefix="/api")
    app.include_router(watchlist_router, prefix="/api/watchlist")

    mock_session = AsyncMock()
    # Use MagicMock for execute results so .all(), .scalar_one_or_none() are sync
    mock_session.execute.return_value = MagicMock()

    async def override_get_db():
        yield mock_session

    def override_current_user():
        return {"sub": "admin@oricred.com", "role": "admin"}

    app.dependency_overrides[get_db] = override_get_db
    from app.api.auth import get_current_user
    app.dependency_overrides[get_current_user] = override_current_user

    client = TestClient(app)
    return client, mock_session


class TestOrganizationsEndpoint:
    def test_list_organizations(self, client_and_mock):
        client, mock_db = client_and_mock
        mock_db.execute.return_value.all.return_value = [
            _mock_row(id="org-cpt", name="City of Cape Town"),
        ]

        resp = client.get("/api/organizations")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "org-cpt"
        assert data[0]["name"] == "City of Cape Town"

    def test_empty(self, client_and_mock):
        client, mock_db = client_and_mock
        mock_db.execute.return_value.all.return_value = []
        resp = client.get("/api/organizations")
        assert resp.status_code == 200
        assert resp.json() == []


class TestCategoriesEndpoint:
    def test_list_categories(self, client_and_mock):
        client, mock_db = client_and_mock
        mock_db.execute.return_value.all.return_value = [
            _mock_row(id="cat-1", name="Security"),
        ]

        resp = client.get("/api/categories")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "cat-1"

    def test_empty(self, client_and_mock):
        client, mock_db = client_and_mock
        mock_db.execute.return_value.all.return_value = []
        resp = client.get("/api/categories")
        assert resp.status_code == 200


class TestTendersProvincesEndpoint:
    def test_list_provinces(self, client_and_mock):
        client, mock_db = client_and_mock
        mock_db.execute.return_value.all.return_value = [("gp",), ("wc",)]

        resp = client.get("/api/tenders/provinces")

        assert resp.status_code == 200
        assert resp.json() == ["gp", "wc"]

    def test_empty(self, client_and_mock):
        client, mock_db = client_and_mock
        mock_db.execute.return_value.all.return_value = []
        resp = client.get("/api/tenders/provinces")
        assert resp.status_code == 200


class TestAwardsEndpoint:
    def test_list_awards(self, client_and_mock):
        client, mock_db = client_and_mock

        result = MagicMock()
        result.__iter__.return_value = [
            _mock_row(
                id="aw-1", supplier_name="Raubex", buyer_org_id="org-sanral",
                buyer_org_name="SANRAL", tender_title="N3 Resurfacing",
                amount=31_500_000.0,
                award_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
                bee_level=2, source="tenders_api", opportunity_id=None,
            ),
        ]
        mock_db.execute.return_value = result
        mock_db.scalar.return_value = 1

        resp = client.get("/api/awards?page_size=10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["supplier_name"] == "Raubex"
        assert data["items"][0]["amount"] == 31_500_000.0

    def test_empty(self, client_and_mock):
        client, mock_db = client_and_mock
        result = MagicMock()
        result.__iter__.return_value = []
        mock_db.execute.return_value = result
        mock_db.scalar.return_value = 0

        resp = client.get("/api/awards")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_filter_by_buyer(self, client_and_mock):
        client, mock_db = client_and_mock
        result = MagicMock()
        result.__iter__.return_value = []
        mock_db.execute.return_value = result
        mock_db.scalar.return_value = 0

        resp = client.get("/api/awards?buyer_org_id=org-sanral")
        assert resp.status_code == 200

    def test_filter_by_value_range(self, client_and_mock):
        client, mock_db = client_and_mock
        result = MagicMock()
        result.__iter__.return_value = []
        mock_db.execute.return_value = result
        mock_db.scalar.return_value = 0

        resp = client.get("/api/awards?value_min=100000&value_max=5000000")
        assert resp.status_code == 200

    def test_filter_by_has_opportunity(self, client_and_mock):
        client, mock_db = client_and_mock
        result = MagicMock()
        result.__iter__.return_value = []
        mock_db.execute.return_value = result
        mock_db.scalar.return_value = 0

        resp = client.get("/api/awards?has_opportunity=true")
        assert resp.status_code == 200


class TestTendersEndpoint:
    def test_list_tenders(self, client_and_mock):
        client, mock_db = client_and_mock

        result = MagicMock()
        result.__iter__.return_value = [
            _mock_row(
                id="tn-1", title="CBD Security", estimated_value=8_500_000.0,
                province="gp", category_id="sec-1", category_name="Security Guarding",
                buyer_org_id="org-joburg", buyer_org_name="City of Joburg",
                closing_date=datetime(2026, 7, 26, tzinfo=timezone.utc),
                published_at=None, tender_type=None, discovered_at=None,
            ),
        ]
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result
        mock_db.scalar.return_value = 1

        resp = client.get("/api/tenders?page_size=10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "CBD Security"
        assert data["items"][0]["status"] == "not_watched"

    def test_filter_by_status(self, client_and_mock):
        client, mock_db = client_and_mock
        result = MagicMock()
        result.__iter__.return_value = []
        mock_db.execute.return_value = result
        mock_db.scalar.return_value = 0

        resp = client.get("/api/tenders?status=watching")
        assert resp.status_code == 200

    def test_filter_by_province(self, client_and_mock):
        client, mock_db = client_and_mock
        result = MagicMock()
        result.__iter__.return_value = []
        mock_db.execute.return_value = result
        mock_db.scalar.return_value = 0

        resp = client.get("/api/tenders?province=gp")
        assert resp.status_code == 200

    def test_filter_by_category(self, client_and_mock):
        client, mock_db = client_and_mock
        result = MagicMock()
        result.__iter__.return_value = []
        mock_db.execute.return_value = result
        mock_db.scalar.return_value = 0

        resp = client.get("/api/tenders?category_id=sec-1")
        assert resp.status_code == 200

    def test_search(self, client_and_mock):
        client, mock_db = client_and_mock
        result = MagicMock()
        result.__iter__.return_value = []
        mock_db.execute.return_value = result
        mock_db.scalar.return_value = 0

        resp = client.get("/api/tenders?search=security")
        assert resp.status_code == 200


class TestWatchlistEndpoint:
    def test_get_watchlist(self, client_and_mock):
        client, mock_db = client_and_mock

        mock_wl = MagicMock()
        mock_wl.id = "wl-1"
        mock_wl.tender_id = "tn-1"
        mock_wl.status = "watching"
        mock_wl.expected_window_start = datetime(2026, 6, 16, tzinfo=timezone.utc)
        mock_wl.expected_window_end = datetime(2026, 6, 26, tzinfo=timezone.utc)
        mock_wl.started_watching_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        mock_wl.created_at = datetime(2026, 6, 1, tzinfo=timezone.utc)

        mock_tender = MagicMock()
        mock_tender.id = "tn-1"
        mock_tender.title = "Library FM"
        mock_tender.estimated_value = 3_200_000.00
        mock_tender.category_id = "facilities-management"
        mock_tender.province = "wc"
        mock_tender.buyer_org_id = "org-cpt"
        mock_tender.closing_date = datetime(2026, 6, 23, tzinfo=timezone.utc)

        mock_db.execute.return_value.all.return_value = [
            (mock_wl, mock_tender, None, 0),
        ]

        resp = client.get("/api/watchlist")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Library FM"
        assert data["items"][0]["status"] == "watching"
        assert data["items"][0]["opportunity_id"] is None
        assert data["items"][0]["opportunity_count"] == 0

    def test_watchlist_with_opportunity(self, client_and_mock):
        client, mock_db = client_and_mock

        mock_wl = MagicMock()
        mock_wl.id = "wl-2"
        mock_wl.tender_id = "tn-2"
        mock_wl.status = "awarded"
        mock_wl.expected_window_start = None
        mock_wl.expected_window_end = None
        mock_wl.started_watching_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        mock_wl.created_at = datetime(2026, 6, 1, tzinfo=timezone.utc)

        mock_tender = MagicMock()
        mock_tender.id = "tn-2"
        mock_tender.title = "Road Repairs"
        mock_tender.estimated_value = 5_000_000.00
        mock_tender.category_id = "roads"
        mock_tender.province = "gp"
        mock_tender.buyer_org_id = "org-sanral"
        mock_tender.closing_date = datetime(2026, 5, 1, tzinfo=timezone.utc)

        mock_db.execute.return_value.all.return_value = [
            (mock_wl, mock_tender, "opp-1", 2),
        ]

        resp = client.get("/api/watchlist")

        assert resp.status_code == 200
        data = resp.json()
        item = data["items"][0]
        assert item["opportunity_id"] == "opp-1"
        assert item["opportunity_count"] == 2

    def test_empty(self, client_and_mock):
        client, mock_db = client_and_mock
        mock_db.execute.return_value.all.return_value = []

        resp = client.get("/api/watchlist")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_toggle_watch(self, client_and_mock):
        client, mock_db = client_and_mock

        mock_tender = MagicMock()
        mock_tender.id = "tn-new"
        mock_tender.buyer_org_id = "org-cpt"
        mock_tender.category_id = "facilities-management"
        mock_tender.closing_date = datetime(2026, 7, 15, tzinfo=timezone.utc)
        mock_tender.title = "New Tender"

        call_count = 0

        def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.scalar_one_or_none.return_value = mock_tender if call_count == 1 else None
            return result

        mock_db.execute = AsyncMock(side_effect=execute_side_effect)

        with (
            patch("app.api.watchlist.AwardTimingService.get_expected_window", new_callable=AsyncMock) as mock_timing,
        ):
            mock_timing.return_value = (
                datetime(2026, 7, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 30, tzinfo=timezone.utc),
            )
            resp = client.post("/api/watchlist/toggle", json={"tender_id": "tn-new"})

        assert resp.status_code == 200
        assert resp.json()["is_watching"] is True

    def test_toggle_unwatch(self, client_and_mock):
        client, mock_db = client_and_mock

        mock_tender = MagicMock()
        mock_tender.id = "tn-existing"

        mock_wl = MagicMock()
        mock_wl.tender_id = "tn-existing"

        call_count = 0

        def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = mock_tender
            else:
                result.scalar_one_or_none.return_value = mock_wl
            return result

        mock_db.execute = AsyncMock(side_effect=execute_side_effect)

        resp = client.post("/api/watchlist/toggle", json={"tender_id": "tn-existing"})

        assert resp.status_code == 200
        assert resp.json()["is_watching"] is False

    def test_toggle_missing_tender_returns_404(self, client_and_mock):
        client, mock_db = client_and_mock
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        resp = client.post("/api/watchlist/toggle", json={"tender_id": "nonexistent"})

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


class TestAwardEdgeCases:
    def test_award_float_coercion(self):
        item = AwardItem(id="a1", supplier_name="X", source="api", amount=50000)
        assert isinstance(item.amount, float)
        assert item.amount == 50000.0

    def test_awards_list_serialization(self):
        items = [AwardItem(id="a1", supplier_name="X", source="api")]
        lst = AwardsList(items=items, total=1, page=1, page_size=50)
        dumped = lst.model_dump()
        assert dumped["total"] == 1
        assert dumped["items"][0]["supplier_name"] == "X"
