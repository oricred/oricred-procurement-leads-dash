from datetime import datetime, timezone

from app.jobs.award_check import _resolve_award_date


def _dt(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


DISCOVERED = _dt(2026, 7, 15, 12, 21)
NOW = _dt(2026, 7, 16, 10, 0)


class TestResolveAwardDate:
    """The date itself. This contract is unchanged: never None."""

    def test_valid_raw_date_used_directly(self):
        assert _resolve_award_date("2025-06-17", None, DISCOVERED, NOW).value == _dt(2025, 6, 17)

    def test_corrupt_raw_date_falls_to_source_created(self):
        r = _resolve_award_date("2099-10-09", _dt(2025, 4, 15), DISCOVERED, NOW)
        assert r.value == _dt(2025, 4, 15)

    def test_corrupt_raw_no_source_created_falls_to_discovered(self):
        assert _resolve_award_date("2099-10-09", None, DISCOVERED, NOW).value == DISCOVERED

    def test_null_raw_date_falls_to_source_created(self):
        assert _resolve_award_date(None, _dt(2025, 6, 1), DISCOVERED, NOW).value == _dt(2025, 6, 1)

    def test_null_raw_no_source_falls_to_discovered(self):
        assert _resolve_award_date(None, None, DISCOVERED, NOW).value == DISCOVERED

    def test_discovered_in_future_uses_now(self):
        assert _resolve_award_date(None, None, _dt(2099, 1, 1), NOW).value == NOW

    def test_source_created_used_over_discovered(self):
        r = _resolve_award_date("2099-10-09", _dt(2025, 6, 1), DISCOVERED, NOW)
        assert r.value == _dt(2025, 6, 1)

    def test_never_returns_none(self):
        """The core business rule: a missing award date makes the record useless."""
        for raw in (None, "", "not-a-date", "2099-10-09", {"unexpected": "type"}):
            assert _resolve_award_date(raw, None, DISCOVERED, NOW).value is not None


class TestAwardDateProvenance:
    """Whether the date may advance the ingestion cursor.

    A synthesised date equals roughly 'now'. Feeding it into the cursor moves
    the watermark to today, and every award published afterwards with an older
    award_date is then permanently skipped — the H1 defect.
    """

    def test_a_parsed_source_date_is_source_backed(self):
        assert _resolve_award_date("2025-06-17", None, DISCOVERED, NOW).from_source is True

    def test_source_created_at_is_source_backed(self):
        r = _resolve_award_date("2099-10-09", _dt(2025, 4, 15), DISCOVERED, NOW)
        assert r.from_source is True

    def test_discovery_fallback_is_not_source_backed(self):
        assert _resolve_award_date("2099-10-09", None, DISCOVERED, NOW).from_source is False

    def test_null_everything_is_not_source_backed(self):
        assert _resolve_award_date(None, None, DISCOVERED, NOW).from_source is False

    def test_now_fallback_is_not_source_backed(self):
        assert _resolve_award_date(None, None, _dt(2099, 1, 1), NOW).from_source is False

    def test_a_synthesised_date_is_near_now(self):
        """Precisely why it must not become the cursor."""
        r = _resolve_award_date("2099-10-09", None, DISCOVERED, NOW)
        assert r.from_source is False
        assert r.value >= DISCOVERED


class TestCursorAdvancement:
    """The watermark computation, as check_awards_for_watching performs it."""

    @staticmethod
    def _cursor(resolved):
        source_backed = [r.value for r in resolved if r.from_source]
        if not source_backed:
            return None
        return min(max(source_backed), NOW)

    def test_one_corrupt_row_does_not_drag_the_cursor_to_today(self):
        """The H1 regression, stated directly."""
        resolved = [
            _resolve_award_date("2025-06-01", None, DISCOVERED, NOW),
            _resolve_award_date("2025-06-10", None, DISCOVERED, NOW),
            _resolve_award_date("2099-10-09", None, DISCOVERED, NOW),  # corrupt
        ]
        assert self._cursor(resolved) == _dt(2025, 6, 10)

    def test_cursor_is_the_newest_source_backed_date(self):
        resolved = [
            _resolve_award_date("2025-06-01", None, DISCOVERED, NOW),
            _resolve_award_date("2025-08-20", None, DISCOVERED, NOW),
            _resolve_award_date("2025-07-04", None, DISCOVERED, NOW),
        ]
        assert self._cursor(resolved) == _dt(2025, 8, 20)

    def test_a_batch_of_only_corrupt_rows_does_not_advance(self):
        resolved = [_resolve_award_date("2099-01-01", None, DISCOVERED, NOW) for _ in range(3)]
        assert self._cursor(resolved) is None

    def test_cursor_never_exceeds_now(self):
        resolved = [_resolve_award_date(NOW.isoformat(), None, _dt(2099, 1, 1), NOW)]
        assert self._cursor(resolved) <= NOW
