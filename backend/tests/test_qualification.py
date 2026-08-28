"""Filter semantics for the qualification engine."""


from app.models.tender import Tender
from app.services.qualification import (
    ProvinceFilter,
    SectorFilter,
    ValueRangeFilter,
)

INCLUDE_CONSTRUCTION = [{"type": "include", "values": ["construction", "infrastructure"]}]


def _tender(**kwargs) -> Tender:
    return Tender(api_id="t1", title="T", raw_payload={}, discovered_at=None, **kwargs)


class TestMissingDataIsNotDisqualifying:
    """Regression guard for the M10 defect.

    SectorFilter built an empty category list for an uncategorised tender and
    failed the any() include test, so missing data was treated as
    disqualifying — while every sibling filter passed it.
    """

    async def test_sector_filter_passes_a_tender_with_no_category(self):
        result = await SectorFilter().evaluate(_tender(category_id=None), INCLUDE_CONSTRUCTION)
        assert result.passed

    async def test_value_filter_passes_a_tender_with_no_value(self):
        rules = [{"field": "estimated_value", "min": 500000, "max": None}]
        assert (await ValueRangeFilter().evaluate(_tender(estimated_value=None), rules)).passed

    async def test_province_filter_passes_a_tender_with_no_province(self):
        rules = [{"type": "include", "values": ["gp"]}]
        assert (await ProvinceFilter().evaluate(_tender(province=None), rules)).passed

    async def test_the_strict_reading_is_available_per_rule(self):
        rules = [{"type": "include", "values": ["construction"], "on_missing": "fail"}]
        result = await SectorFilter().evaluate(_tender(category_id=None), rules)
        assert not result.passed
        assert result.failed_filter == "sector"


class TestSectorFilterStillFilters:
    async def test_an_included_category_passes(self):
        result = await SectorFilter().evaluate(
            _tender(category_id="construction"), INCLUDE_CONSTRUCTION
        )
        assert result.passed

    async def test_a_category_outside_the_include_list_fails(self):
        result = await SectorFilter().evaluate(
            _tender(category_id="cleaning"), INCLUDE_CONSTRUCTION
        )
        assert not result.passed

    async def test_an_excluded_category_fails(self):
        rules = [{"type": "exclude", "values": ["cleaning"]}]
        result = await SectorFilter().evaluate(_tender(category_id="cleaning"), rules)
        assert not result.passed
