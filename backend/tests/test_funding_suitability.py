import pytest
from app.services.funding_suitability import compute_score


class TestComputeScore:

    def test_restricted_supplier_returns_zero(self):
        score = compute_score(1, 10.0, True, None, None)
        assert score == 0.0

    def test_high_bee_level_gives_high_score(self):
        score = compute_score(1, 10.0, False, None, None)
        assert score > 0

    def test_low_bee_level_gives_lower_score(self):
        high = compute_score(1, 10.0, False, None, None)
        low = compute_score(4, 10.0, False, None, None)
        assert high > low

    def test_high_forensic_risk_lowers_score(self):
        low_risk = compute_score(2, 10.0, False, None, None)
        high_risk = compute_score(2, 90.0, False, None, None)
        assert low_risk > high_risk

    def test_large_award_value_contributes(self):
        with_value = compute_score(2, 10.0, False, None, None)
        with_award = compute_score(2, 10.0, False, 25_000_000, None)
        assert with_award > with_value

    def test_company_age_contributes(self):
        young = compute_score(2, 10.0, False, None, 365)
        old = compute_score(2, 10.0, False, None, 3650)
        assert old > young

    def test_full_score_range(self):
        score = compute_score(1, 0.0, False, 50_000_000, 3650)
        assert 80 <= score <= 100

    def test_minimal_score(self):
        score = compute_score(4, 100.0, False, 0, None)
        assert 0 <= score <= 30
