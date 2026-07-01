from app.clients.tsa_db import (
    _map_fields,
    _build_tender_where,
    _build_award_where,
    _build_company_where,
    _build_org_where,
    TENDER_FIELD_MAP,
    AWARD_FIELD_MAP,
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
