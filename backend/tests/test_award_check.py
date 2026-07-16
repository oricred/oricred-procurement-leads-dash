from datetime import datetime, timezone

from app.jobs.award_check import _resolve_award_date


def _dt(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


DISCOVERED = _dt(2026, 7, 15, 12, 21)
NOW = _dt(2026, 7, 16, 10, 0)


class TestResolveAwardDate:
    def test_valid_raw_date_used_directly(self):
        r = _resolve_award_date("2025-06-17", None, DISCOVERED, NOW)
        assert r == _dt(2025, 6, 17)

    def test_corrupt_raw_date_falls_to_source_created(self):
        r = _resolve_award_date("2099-10-09", _dt(2025, 4, 15), DISCOVERED, NOW)
        assert r == _dt(2025, 4, 15)

    def test_corrupt_raw_no_source_created_falls_to_discovered(self):
        r = _resolve_award_date("2099-10-09", None, DISCOVERED, NOW)
        assert r == DISCOVERED

    def test_null_raw_date_falls_to_source_created(self):
        r = _resolve_award_date(None, _dt(2025, 6, 1), DISCOVERED, NOW)
        assert r == _dt(2025, 6, 1)

    def test_null_raw_no_source_falls_to_discovered(self):
        r = _resolve_award_date(None, None, DISCOVERED, NOW)
        assert r == DISCOVERED

    def test_discovered_in_future_uses_now(self):
        r = _resolve_award_date(None, None, _dt(2099, 1, 1), NOW)
        assert r == NOW

    def test_source_created_used_over_discovered(self):
        r = _resolve_award_date("2099-10-09", _dt(2025, 6, 1), DISCOVERED, NOW)
        assert r == _dt(2025, 6, 1)
