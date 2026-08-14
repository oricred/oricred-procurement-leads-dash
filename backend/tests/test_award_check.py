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

    def test_corrupt_year_is_reconstructed_from_publication_year(self):
        r = _resolve_award_date(
            "2099-10-09", None, DISCOVERED, NOW,
            publication_date="2025-12-01",
            tender_closing_date="2025-03-01",
        )
        assert r == _dt(2025, 10, 9)

    def test_corrupt_raw_without_context_uses_prior_discovery_year(self):
        r = _resolve_award_date("2099-10-09", None, DISCOVERED, NOW)
        assert r == _dt(2025, 10, 9)

    def test_null_raw_date_uses_publication_not_source_created(self):
        r = _resolve_award_date(
            None, _dt(2025, 6, 1), DISCOVERED, NOW,
            publication_date="2025-06-15",
        )
        assert r == _dt(2025, 6, 15)

    def test_null_raw_no_source_falls_to_discovered(self):
        r = _resolve_award_date(None, None, DISCOVERED, NOW)
        assert r == DISCOVERED

    def test_null_raw_does_not_use_tender_publication_before_closing(self):
        r = _resolve_award_date(
            None, None, DISCOVERED, NOW,
            tender_published_at="2025-01-01",
            tender_closing_date="2025-03-01",
        )
        assert r == _dt(2025, 3, 1)

    def test_discovered_in_future_uses_now(self):
        r = _resolve_award_date(None, None, _dt(2099, 1, 1), NOW)
        assert r == NOW

    def test_source_created_is_not_used_as_procurement_date(self):
        r = _resolve_award_date(None, _dt(2025, 6, 1), DISCOVERED, NOW)
        assert r == DISCOVERED

    def test_award_after_publication_uses_publication_date(self):
        r = _resolve_award_date(
            "2025-12-09", None, DISCOVERED, NOW,
            publication_date="2025-11-01",
            tender_closing_date="2025-03-01",
        )
        assert r == _dt(2025, 11, 1)

    def test_award_before_tender_close_uses_publication_proxy(self):
        r = _resolve_award_date(
            "2024-01-01", None, DISCOVERED, NOW,
            publication_date="2025-07-01",
            tender_published_at="2025-01-01",
            tender_closing_date="2025-03-01",
        )
        assert r == _dt(2025, 7, 1)
