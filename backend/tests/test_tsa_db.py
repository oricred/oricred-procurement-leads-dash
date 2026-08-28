from app.clients.tsa_db import (
    AWARD_FIELD_MAP,
    TENDER_FIELD_MAP,
    _build_award_where,
    _build_company_where,
    _build_org_where,
    _build_tender_where,
    _map_fields,
)


class TestMapFields:
    def test_all_fields_when_none_given(self):
        result = _map_fields(TENDER_FIELD_MAP, None)
        assert "t.title" in result
        assert "t.estimated_value" in result

    def test_selected_fields_only(self):
        result = _map_fields(TENDER_FIELD_MAP, ["title", "province"])
        assert "t.title AS title" in result
        assert "t.province AS province" in result
        assert "t.estimated_value" not in result

    def test_award_publication_date_is_schema_safe(self):
        result = _map_fields(AWARD_FIELD_MAP, ["publication_date"])
        assert "to_jsonb(a)" in result
        assert "AS publication_date" in result

    def test_unknown_field_skipped(self):
        result = _map_fields(TENDER_FIELD_MAP, ["title", "nonexistent"])
        assert "t.title AS title" in result
        assert "nonexistent" not in result


class TestBuildTenderWhere:
    def test_no_filters(self):
        where, params = _build_tender_where(None)
        assert where == ""
        assert params == {}

    def test_empty_filters(self):
        where, params = _build_tender_where({})
        assert where == ""
        assert params == {}

    def test_tender_ids_filter(self):
        where, params = _build_tender_where({"tender_ids": ["tender-1", "tender-2"]})
        assert "t.tender_id = ANY(:tender_ids)" in where
        assert params["tender_ids"] == ["tender-1", "tender-2"]

    def test_province_filter(self):
        where, params = _build_tender_where({"province": ["Gauteng", "Western Cape"]})
        assert "LOWER(t.province) = ANY(:province)" in where
        assert params["province"] == ["gauteng", "western cape"]

    def test_value_range(self):
        where, params = _build_tender_where({"value_min": 500000, "value_max": 50000000})
        assert "t.estimated_value >= :value_min" in where
        assert "t.estimated_value <= :value_max" in where
        assert params["value_min"] == 500000.0
        assert params["value_max"] == 50000000.0

    def test_since(self):
        where, params = _build_tender_where({"since": "2026-01-01T00:00:00"})
        assert "t.publication_date >= :since" in where
        assert params["since"] == "2026-01-01T00:00:00"

    def test_category_filter(self):
        where, params = _build_tender_where({"category": ["construction", "infrastructure"]})
        assert "LOWER(tc.canonical_name) = ANY(:category)" in where
        assert params["category"] == ["construction", "infrastructure"]

    def test_entity_type_filter(self):
        where, params = _build_tender_where({"entity_type": ["national", "provincial"]})
        assert "LOWER(o.organization_type) = ANY(:entity_type)" in where
        assert params["entity_type"] == ["national", "provincial"]

    def test_status_filter(self):
        where, params = _build_tender_where({"status": ["ACTIVE"]})
        assert "t.status = ANY(:status_list)" in where
        assert params["status_list"] == ["ACTIVE"]

    def test_search_filter(self):
        where, params = _build_tender_where({"search": "solar"})
        assert "LIKE :search" in where
        assert params["search"] == "%solar%"

    def test_exclude_categories(self):
        where, params = _build_tender_where({"_exclude_categories": ["cleaning", "catering"]})
        assert "!= ALL(:_exclude_cats)" in where
        assert params["_exclude_cats"] == ["cleaning", "catering"]

    def test_all_filters_combined(self):
        filters = {
            "province": ["gp"],
            "value_min": 100000,
            "category": ["construction"],
            "status": ["ACTIVE"],
        }
        where, params = _build_tender_where(filters)
        assert where.startswith("WHERE")
        assert "AND" in where


class TestBuildAwardWhere:
    def test_source_created_cursor_only_selects_cursor_bearing_rows(self):
        where, params, join = _build_award_where({"created_since": "2026-01-01"})
        assert "a.created_at >= :created_since" in where
        assert "created_at IS NULL" not in where
        assert params["created_since"] == "2026-01-01"

    def test_legacy_awards_use_a_durable_id_keyset(self):
        where, params, join = _build_award_where({
            "created_is_null": True,
            "legacy_after_id": "award-100",
        })
        assert "a.created_at IS NULL" in where
        assert "CAST(a.id AS TEXT) > :legacy_after_id" in where
        assert params["legacy_after_id"] == "award-100"

    def test_tender_ids_filter(self):
        where, params, join = _build_award_where({"tender_ids": ["id1", "id2"]})
        assert "a.tender_id = ANY(:tender_ids)" in where
        assert params["tender_ids"] == ["id1", "id2"]

    def test_supplier_filter(self):
        where, params, join = _build_award_where({"supplier": "ACME"})
        assert "LOWER(a.supplier_name) LIKE :supplier" in where
        assert params["supplier"] == "%acme%"

    def test_buyer_org_id_adds_join(self):
        where, params, join = _build_award_where({"buyer_org_id": "org123"})
        assert "JOIN tenders t" in join
        assert "t.source_organization_id = :buyer_org_id" in where
        assert params["buyer_org_id"] == "org123"


class TestBuildCompanyWhere:
    def test_names_filter(self):
        where, params = _build_company_where({"names": ["ACME Corp", "Globex"]})
        assert "LOWER(c.name) = ANY(:names)" in where
        assert params["names"] == ["acme corp", "globex"]

    def test_bee_level_range(self):
        where, params = _build_company_where({"bee_level_min": 1, "bee_level_max": 4})
        assert "c.bbbee_level >= :bee_min" in where
        assert "c.bbbee_level <= :bee_max" in where


class TestBuildOrgWhere:
    def test_ids_filter(self):
        where, params = _build_org_where({"ids": ["org1", "org2"]})
        assert "o.id = ANY(:ids)" in where
        assert params["ids"] == ["org1", "org2"]

    def test_org_type_filter(self):
        where, params = _build_org_where({"type": ["GOVERNMENT", "MUNICIPALITY"]})
        assert "LOWER(o.organization_type) = ANY(:org_types)" in where


class TestContactQueryExecution:
    """Regression guard for the C1 defect.

    query_directors, query_key_personnel and query_source_directors each
    referenced an undefined `offset` name and raised NameError on every call.
    Every caller wrapped them in `except Exception`, so the crash surfaced to
    operators as "no contacts found". These tests execute the methods rather
    than only inspecting the SQL they would build.
    """

    async def test_query_directors_executes(self, tsa_stub):
        rows = await tsa_stub.query_directors(company_ids=["company-1"])
        assert rows == []
        assert "FROM directors" in tsa_stub.last_sql
        assert tsa_stub.last_params["company_ids"] == ["company-1"]

    async def test_query_key_personnel_executes(self, tsa_stub):
        rows = await tsa_stub.query_key_personnel(company_ids=["company-1"])
        assert rows == []
        assert "FROM key_personnel" in tsa_stub.last_sql
        assert tsa_stub.last_params["company_ids"] == ["company-1"]

    async def test_query_source_directors_executes(self, tsa_stub):
        rows = await tsa_stub.query_source_directors(organization_ids=["org-1"])
        assert rows == []
        assert "FROM source_directors" in tsa_stub.last_sql
        assert tsa_stub.last_params["organization_ids"] == ["org-1"]

    async def test_contact_queries_do_not_paginate(self, tsa_stub):
        """These three deliberately take no offset. Binding one without a
        matching OFFSET clause is what produced the NameError."""
        for method, kwargs in (
            ("query_directors", {"company_ids": ["c"]}),
            ("query_key_personnel", {"company_ids": ["c"]}),
            ("query_source_directors", {"organization_ids": ["o"]}),
        ):
            await getattr(tsa_stub, method)(**kwargs)
            sql, params = tsa_stub.calls[-1]
            assert "LIMIT :limit" in sql
            assert "OFFSET" not in sql
            assert "offset" not in params

    async def test_query_directors_returns_rows(self, tsa_stub):
        tsa_stub.queue("directors", [
            {"id": "d1", "company_id": "c1", "full_name": "Thabo Mokoena",
             "email": "thabo@example.co.za", "phone": "0821234567", "equity_percentage": 40},
        ])
        rows = await tsa_stub.query_directors(company_ids=["c1"])
        assert [r["full_name"] for r in rows] == ["Thabo Mokoena"]


class TestPaginatedQueriesStillBindOffset:
    """The four methods that do paginate must keep binding :offset — the C1 fix
    is a deletion, and deleting too much breaks these silently."""

    async def test_paginated_queries_bind_offset(self, tsa_stub):
        for method in ("query_tenders", "query_awards", "query_companies", "query_organizations"):
            await getattr(tsa_stub, method)(limit=10, offset=20)
            sql, params = tsa_stub.calls[-1]
            assert "LIMIT :limit OFFSET :offset" in sql
            assert params["offset"] == 20
            assert params["limit"] == 10
