from datetime import datetime, timezone

from app.jobs.award_check import _resolve_award_date, _parse_lenient


def _dt(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


NOW = _dt(2026, 7, 16, 10, 0)
DISCOVERED = _dt(2026, 7, 15, 12, 21)


class TestResolveAwardDate:
    # ── Step 1: direct use ──

    def test_valid_date_direct_use(self):
        r = _resolve_award_date("2025-06-17", None, None, None, DISCOVERED, NOW)
        assert r == _dt(2025, 6, 17)

    def test_valid_date_within_tender_bounds(self):
        r = _resolve_award_date(
            "2025-06-20", None, _dt(2025, 6, 1), _dt(2025, 6, 15), DISCOVERED, NOW,
        )
        assert r == _dt(2025, 6, 20)

    def test_valid_date_future_violates_discovered_falls_through(self):
        r = _resolve_award_date("2099-10-09", None, None, None, DISCOVERED, NOW)
        assert r != _dt(2099, 10, 9)

    # ── Step 2: year correction for borderline years (≤ MAX_VALID_YEAR=2027) ──

    def test_year_correction_uses_discovered_year(self):
        discovered = _dt(2026, 5, 1)
        r = _resolve_award_date("2027-01-13", None, None, None, discovered, NOW)
        assert r == _dt(2026, 1, 13)

    def test_year_correction_falls_back_to_discovered_minus_one(self):
        discovered = _dt(2025, 3, 1)
        r = _resolve_award_date("2027-06-15", None, None, None, discovered, NOW)
        # ref_years = [2025, 2024]; 2025-06-15 > discovered 2025-03-01 → skip
        # 2024-06-15 ≤ discovered 2025-03-01 → use
        assert r == _dt(2024, 6, 15)

    def test_year_correction_pub_year_priority(self):
        pub_date = _dt(2025, 6, 1)
        r = _resolve_award_date("2027-03-01", pub_date, None, None, DISCOVERED, NOW)
        # corrected = 2025-03-01 ≤ pub_date 2025-06-01 → OK
        assert r == _dt(2025, 3, 1)

    def test_year_correction_closing_year_fallback(self):
        pub_date = _dt(2025, 6, 1)
        closing = _dt(2024, 12, 1)
        r = _resolve_award_date("2027-03-01", pub_date, None, closing, DISCOVERED, NOW)
        # ref_years = [2025, 2024, 2026]; 2025-03-01 ≤ discovered, ≤ pub_date → OK
        assert r == _dt(2025, 3, 1)

    def test_year_correction_corrected_before_closing_skipped(self):
        closing = _dt(2025, 6, 15)
        r = _resolve_award_date("2027-03-01", None, None, closing, DISCOVERED, NOW)
        # ref_years = [2025, 2026]; corrected = 2025-03-01 < closing 2025-06-15 → OK actually
        # The lower is tender_published_at or tender_closing_date = closing = 2025-06-15
        # corrected 2025-03-01 < 2025-06-15 → violates lower bound → skip
        # Next ref: 2026 → corrected = 2026-03-01 ≤ discovered → 2026-03-01 < 2025-06-15? 
        # 2026-03-01 is not < 2025-06-15, it's greater → OK
        # So it would use 2026-03-01
        assert r == _dt(2026, 3, 1)

    def test_year_correction_corrected_after_pub_falls_to_pub(self):
        pub_date = _dt(2025, 6, 1)
        r = _resolve_award_date("2027-10-09", pub_date, None, None, DISCOVERED, NOW)
        # ref_years = [2025, 2026]; corrected = 2025-10-09 > pub_date 2025-06-01 → violation
        # pub_date 2025-06-01 ≤ discovered → return pub_date
        assert r == pub_date

    # ── Step 3: fully corrupt year (> MAX_VALID_YEAR) → fallback ──

    def test_corrupt_year_fallback_to_discovered(self):
        r = _resolve_award_date("2099-10-09", None, None, None, DISCOVERED, NOW)
        assert r == DISCOVERED

    def test_corrupt_year_fallback_to_publication_date(self):
        pub_date = _dt(2025, 8, 1)
        r = _resolve_award_date("2099-10-09", pub_date, None, None, DISCOVERED, NOW)
        assert r == pub_date

    def test_corrupt_year_fallback_to_tender_published(self):
        pub = _dt(2025, 3, 15)
        closing = _dt(2025, 6, 1)
        r = _resolve_award_date("2099-10-09", None, pub, closing, DISCOVERED, NOW)
        assert r == pub

    def test_corrupt_year_fallback_to_tender_closing(self):
        closing = _dt(2025, 1, 30)
        r = _resolve_award_date("2099-10-09", None, None, closing, DISCOVERED, NOW)
        assert r == closing

    # ── NULL raw_date ──

    def test_null_raw_date_falls_to_discovered(self):
        r = _resolve_award_date(None, None, None, None, DISCOVERED, NOW)
        assert r == DISCOVERED

    def test_null_raw_date_falls_to_closing(self):
        r = _resolve_award_date(None, None, None, _dt(2025, 6, 1), DISCOVERED, NOW)
        assert r == _dt(2025, 6, 1)

    def test_discovered_in_future_uses_now(self):
        future_disc = _dt(2099, 1, 1)
        r = _resolve_award_date(None, None, None, None, future_disc, NOW)
        assert r == NOW


class TestParseLenient:
    def test_parses_high_year(self):
        dt = _parse_lenient("2099-10-09")
        assert dt is not None and dt.year == 2099

    def test_parses_datetime_object(self):
        dt = _parse_lenient(datetime(2099, 10, 9, tzinfo=timezone.utc))
        assert dt.year == 2099

    def test_returns_none_for_none(self):
        assert _parse_lenient(None) is None

    def test_returns_none_for_garbage(self):
        assert _parse_lenient("not-a-date") is None
