from app.services.competitor_intel import CompetitorIntelService, Competitor


class TestCompetitorDataclass:
    def test_defaults(self):
        c = Competitor(name="ACME Corp", inferred=False)
        assert c.name == "ACME Corp"
        assert c.inferred is False
        assert c.company_id is None
        assert c.resolved is False
        assert c.reason == ""

    def test_all_fields(self):
        c = Competitor(name="Biz", inferred=True, company_id="123", resolved=True, reason="top bidder")
        assert c.name == "Biz"
        assert c.inferred is True
        assert c.company_id == "123"
        assert c.resolved is True
        assert c.reason == "top bidder"
