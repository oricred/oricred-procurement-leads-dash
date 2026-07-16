from datetime import datetime, timezone

from app.jobs.award_check import _resolve_award_date, _parse_lenient


def _dt(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


DISCOVERED = _dt(2026, 7, 15, 12, 21)
NOW = _dt(2026, 7, 16, 10, 0)


def _resolve(raw_date, pub=None, tpub=None, close=None, src=None, disc=None, now=None):
    if disc is None:
        disc = DISCOVERED
    if now is None:
        now = NOW
    return _resolve_award_date(raw_date, pub, tpub, close, src, disc, now)


class TestResolveAwardDate:
    def test_valid_date_direct_use(self):
        assert _resolve("2025-06-17") == _dt(2025, 6, 17)

    def test_valid_date_within_tender_bounds(self):
        assert _resolve(
            "2025-06-20", tpub=_dt(2025, 6, 1), close=_dt(2025, 6, 15),
        ) == _dt(2025, 6, 20)

    def test_valid_date_future_violates_discovered_falls_through(self):
        assert _resolve("2099-10-09") != _dt(2099, 10, 9)

    def test_year_correction_uses_discovered_year(self):
        assert _resolve("2027-01-13", disc=_dt(2026, 5, 1)) == _dt(2026, 1, 13)

    def test_year_correction_falls_back_to_discovered_minus_one(self):
        assert _resolve("2027-06-15", disc=_dt(2025, 3, 1)) == _dt(2024, 6, 15)

    def test_year_correction_pub_year_priority(self):
        assert _resolve("2027-03-01", pub=_dt(2025, 6, 1)) == _dt(2025, 3, 1)

    def test_year_correction_closing_year_fallback(self):
        assert _resolve(
            "2027-03-01", pub=_dt(2025, 6, 1), close=_dt(2024, 12, 1),
        ) == _dt(2025, 3, 1)

    def test_year_correction_corrected_before_closing_skipped(self):
        assert _resolve("2027-03-01", close=_dt(2025, 6, 15)) == _dt(2026, 3, 1)

    def test_year_correction_corrected_after_pub_falls_to_pub(self):
        pub = _dt(2025, 6, 1)
        assert _resolve("2027-10-09", pub=pub) == pub

    def test_corrupt_year_fallback_to_discovered(self):
        assert _resolve("2099-10-09") == DISCOVERED

    def test_corrupt_year_fallback_to_publication_date(self):
        assert _resolve("2099-10-09", pub=_dt(2025, 8, 1)) == _dt(2025, 8, 1)

    def test_corrupt_year_fallback_to_tender_published(self):
        assert _resolve(
            "2099-10-09", tpub=_dt(2025, 3, 15), close=_dt(2025, 6, 1),
        ) == _dt(2025, 3, 15)

    def test_corrupt_year_fallback_to_tender_closing(self):
        assert _resolve("2099-10-09", close=_dt(2025, 1, 30)) == _dt(2025, 1, 30)

    def test_corrupt_year_fallback_to_source_created_at(self):
        assert _resolve(
            "2099-10-09", src=_dt(2025, 4, 15),
        ) == _dt(2025, 4, 15)

    def test_source_created_at_before_discovered_in_fallback(self):
        assert _resolve(
            "2099-10-09", src=_dt(2025, 6, 1),
        ) == _dt(2025, 6, 1)

    def test_source_created_at_not_used_as_ref_year(self):
        assert _resolve(
            "2027-03-15", src=_dt(2025, 6, 1),
        ) == _dt(2026, 3, 15)  # uses discovered.year (2026), not src.year (2025)

    def test_null_raw_date_falls_to_discovered(self):
        assert _resolve(None) == DISCOVERED

    def test_null_raw_date_falls_to_closing(self):
        assert _resolve(None, close=_dt(2025, 6, 1)) == _dt(2025, 6, 1)

    def test_null_raw_date_falls_to_source_created_at(self):
        assert _resolve(None, src=_dt(2025, 3, 1)) == _dt(2025, 3, 1)

    def test_discovered_in_future_uses_now(self):
        assert _resolve(None, disc=_dt(2099, 1, 1)) == NOW


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
