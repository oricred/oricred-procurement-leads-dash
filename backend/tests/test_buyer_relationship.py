from app.services.buyer_relationship import _compute_relevance


class TestComputeRelevance:

    def test_no_awards_returns_low(self):
        score = _compute_relevance(0, 0, None)
        assert score == 0.0

    def test_awards_contribute(self):
        score = _compute_relevance(5, 10_000_000, None)
        assert 0 < score <= 100

    def test_value_contributes(self):
        low_val = _compute_relevance(2, 1_000_000, None)
        high_val = _compute_relevance(2, 40_000_000, None)
        assert high_val > low_val

    def test_win_rate_contributes(self):
        no_win = _compute_relevance(5, 10_000_000, 0.0)
        high_win = _compute_relevance(5, 10_000_000, 1.0)
        assert high_win > no_win

    def test_perfect_score(self):
        score = _compute_relevance(10, 50_000_000, 1.0)
        assert score == 100.0

    def test_score_capped_at_100(self):
        score = _compute_relevance(100, 500_000_000, 1.0)
        assert score <= 100.0
