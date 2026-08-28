from datetime import datetime, timezone

from app.models.award import Award
from app.models.company import Company
from app.models.tender import Tender
from app.services.qualification import QualificationService


def _entities(amount=1_000_000, restricted=False):
    now = datetime(2026, 8, 14, tzinfo=timezone.utc)
    tender = Tender(api_id="T-1", raw_payload={}, title="Tender", discovered_at=now)
    award = Award(tender_id="local-tender", supplier_name="Supplier", amount=amount, discovered_at=now)
    company = Company(api_id="C-1", name="Supplier", restricted_supplier=restricted)
    return tender, award, company


async def test_automatic_lead_uses_award_value(monkeypatch):
    service = QualificationService(None)

    async def config():
        return {"value_range": {"enabled": True, "rules": [{"min": 500_000, "max": 20_000_000}]}}

    monkeypatch.setattr(service, "get_config", config)
    tender, award, company = _entities(amount=100_000)
    result = await service.evaluate_award_lead(tender, award, company)
    assert not result.passed
    assert result.failed_filter == "value_range"


async def test_restricted_supplier_does_not_become_automatic_lead(monkeypatch):
    service = QualificationService(None)

    async def config():
        return {"risk_exclusion": {"enabled": True, "rules": [{"exclude_if_restricted": True}]}}

    monkeypatch.setattr(service, "get_config", config)
    tender, award, company = _entities(restricted=True)
    result = await service.evaluate_award_lead(tender, award, company)
    assert not result.passed
    assert result.failed_filter == "risk_exclusion"
