from abc import ABC, abstractmethod
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.award import Award
from app.models.company import Company
from app.models.filter_config import FilterConfig
from app.models.tender import Tender

logger = structlog.get_logger()


class FilterResult:
    def __init__(self, passed: bool, failed_filter: str = "", reason: str = ""):
        self.passed = passed
        self.failed_filter = failed_filter
        self.reason = reason


class FilterHandler(ABC):
    @abstractmethod
    async def evaluate(self, tender: Tender, rules: list[dict], db: AsyncSession | None = None) -> FilterResult:
        ...


class ValueRangeFilter(FilterHandler):
    async def evaluate(self, tender: Tender, rules: list[dict], db: AsyncSession | None = None) -> FilterResult:
        value: Decimal | None = tender.estimated_value
        if value is None:
            return FilterResult(passed=True)
        for rule in rules:
            min_val = rule.get("min")
            max_val = rule.get("max")
            if min_val is not None and value < Decimal(str(min_val)):
                return FilterResult(passed=False, failed_filter="value_range", reason=f"Below minimum {min_val}")
            if max_val is not None and value > Decimal(str(max_val)):
                return FilterResult(passed=False, failed_filter="value_range", reason=f"Above maximum {max_val}")
        return FilterResult(passed=True)


class SectorFilter(FilterHandler):
    async def evaluate(self, tender: Tender, rules: list[dict], db: AsyncSession | None = None) -> FilterResult:
        cats = [tender.category_id] if tender.category_id else []
        for rule in rules:
            if rule.get("type") == "include":
                if not any(c in rule.get("values", []) for c in cats):
                    return FilterResult(passed=False, failed_filter="sector", reason="Category not in include list")
            elif rule.get("type") == "exclude":
                if any(c in rule.get("values", []) for c in cats):
                    return FilterResult(passed=False, failed_filter="sector", reason="Category in exclude list")
        return FilterResult(passed=True)


class ProvinceFilter(FilterHandler):
    async def evaluate(self, tender: Tender, rules: list[dict], db: AsyncSession | None = None) -> FilterResult:
        if not tender.province:
            return FilterResult(passed=True)
        for rule in rules:
            if rule.get("type") == "include":
                if tender.province.lower() not in [v.lower() for v in rule.get("values", [])]:
                    return FilterResult(passed=False, failed_filter="province", reason="Province not in include list")
        return FilterResult(passed=True)


class EntityTypeFilter(FilterHandler):
    async def evaluate(self, tender: Tender, rules: list[dict], db: AsyncSession | None = None) -> FilterResult:
        if not tender.buyer_org_id:
            return FilterResult(passed=True)
        org_type = None
        if db is not None:
            from app.models.organization import Organization
            result = await db.execute(select(Organization).where(Organization.id == tender.buyer_org_id))
            org = result.scalar_one_or_none()
            if org:
                org_type = org.organization_type
        if not org_type:
            return FilterResult(passed=True)
        for rule in rules:
            if rule.get("type") == "include":
                allowed = rule.get("values", [])
                if org_type not in allowed:
                    return FilterResult(passed=False, failed_filter="entity_type", reason=f"Org type '{org_type}' not in {allowed}")
        return FilterResult(passed=True)


class BEEFilter(FilterHandler):
    async def evaluate(self, tender: Tender, rules: list[dict], db: AsyncSession | None = None) -> FilterResult:
        return FilterResult(passed=True)


class RiskExclusionFilter(FilterHandler):
    async def evaluate(self, tender: Tender, rules: list[dict], db: AsyncSession | None = None) -> FilterResult:
        return FilterResult(passed=True)


class PreferenceFilter(FilterHandler):
    async def evaluate(self, tender: Tender, rules: list[dict], db: AsyncSession | None = None) -> FilterResult:
        if not db:
            return FilterResult(passed=True)
        min_score = None
        for rule in rules:
            min_score = rule.get("min_score")
        if min_score is None or min_score <= 0:
            return FilterResult(passed=True)
        from app.services.buyer_preference import evaluate_tender_preference
        score = await evaluate_tender_preference(tender.province, tender.buyer_org_id, db)
        if score < min_score:
            return FilterResult(passed=False, failed_filter="preference", reason=f"Preference score {score} below minimum {min_score}")
        return FilterResult(passed=True)


class QualificationService:
    _config_cache: dict | None = None
    _config_cache_time: float = 0

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_config(self) -> dict:
        import time
        now = time.time()
        cls = type(self)
        if cls._config_cache is not None and now - cls._config_cache_time < 60:
            return cls._config_cache
        result = await self.db.execute(select(FilterConfig).where(FilterConfig.key == "qualification"))
        row = result.scalar_one_or_none()
        if row is None:
            config = self.default_config()
        elif not row.enabled:
            config = {}
        else:
            config = row.value
        cls._config_cache = config
        cls._config_cache_time = now
        return config

    async def evaluate(self, tender: Tender) -> FilterResult:
        config = await self.get_config()
        if not config:
            return FilterResult(passed=True)

        handlers: dict[str, FilterHandler] = {
            "value_range": ValueRangeFilter(),
            "sector": SectorFilter(),
            "province": ProvinceFilter(),
            "entity_type": EntityTypeFilter(),
            "bee_level": BEEFilter(),
            "risk_exclusion": RiskExclusionFilter(),
            "preference": PreferenceFilter(),
        }

        for filter_name, filter_def in config.items():
            if not filter_def.get("enabled", True):
                continue
            handler = handlers.get(filter_name)
            if not handler:
                continue
            result = await handler.evaluate(tender, filter_def.get("rules", []), self.db)
            if not result.passed:
                logger.info("filter_rejected", filter=filter_name, reason=result.reason, tender_id=tender.api_id)
                return result

        return FilterResult(passed=True)

    async def evaluate_award_lead(
        self,
        tender: Tender,
        award: Award,
        company: Company,
    ) -> FilterResult:
        """Apply the configured business filters to an automatic award lead.

        Award value replaces the pre-award tender estimate. Supplier-only B-BBEE
        and risk rules are evaluated here because those facts do not exist during
        tender discovery.
        """
        config = await self.get_config()
        if not config:
            return FilterResult(passed=True)

        tender_handlers: dict[str, FilterHandler] = {
            "sector": SectorFilter(),
            "province": ProvinceFilter(),
            "entity_type": EntityTypeFilter(),
            "preference": PreferenceFilter(),
        }
        for filter_name, filter_def in config.items():
            if not filter_def.get("enabled", True):
                continue
            rules = filter_def.get("rules", [])

            if filter_name == "value_range":
                if award.amount is None:
                    return FilterResult(False, filter_name, "Award value is missing")
                value = Decimal(str(award.amount))
                for rule in rules:
                    minimum = rule.get("min")
                    maximum = rule.get("max")
                    if minimum is not None and value < Decimal(str(minimum)):
                        return FilterResult(False, filter_name, f"Below minimum {minimum}")
                    if maximum is not None and value > Decimal(str(maximum)):
                        return FilterResult(False, filter_name, f"Above maximum {maximum}")
                continue

            if filter_name == "bee_level":
                level = company.bee_level if company.bee_level is not None else award.bee_level
                for rule in rules:
                    minimum = rule.get("min_level")
                    maximum = rule.get("max_level")
                    min_points = rule.get("min_points")
                    if level is not None and minimum is not None and level < int(minimum):
                        return FilterResult(False, filter_name, f"B-BBEE level {level} below {minimum}")
                    if level is not None and maximum is not None and level > int(maximum):
                        return FilterResult(False, filter_name, f"B-BBEE level {level} above {maximum}")
                    if award.bee_points is not None and min_points is not None and award.bee_points < int(min_points):
                        return FilterResult(False, filter_name, f"B-BBEE points below {min_points}")
                continue

            if filter_name == "risk_exclusion":
                for rule in rules:
                    if rule.get("exclude_if_restricted") and company.restricted_supplier:
                        return FilterResult(False, filter_name, "Supplier is restricted")
                    maximum = rule.get("max_forensic_score")
                    if (
                        maximum is not None
                        and company.cipc_forensic_risk_score is not None
                        and Decimal(str(company.cipc_forensic_risk_score)) > Decimal(str(maximum))
                    ):
                        return FilterResult(False, filter_name, f"Forensic risk exceeds {maximum}")
                continue

            handler = tender_handlers.get(filter_name)
            if handler:
                result = await handler.evaluate(tender, rules, self.db)
                if not result.passed:
                    return result

        return FilterResult(passed=True)

    @staticmethod
    def default_config() -> dict:
        return {
            "value_range": {
                "enabled": True,
                "rules": [{"field": "estimated_value", "min": 500000.00, "max": None}],
            },
            "sector": {
                "enabled": True,
                "rules": [
                    {"type": "include", "values": ["construction", "infrastructure", "it-services", "consulting"], "field": "category_id"},
                    {"type": "exclude", "values": ["cleaning", "catering", "security-guarding"], "field": "category_id"},
                ],
            },
            "province": {
                "enabled": True,
                "rules": [{"type": "include", "values": ["gp", "wc", "kzn", "ec"]}],
            },
            "entity_type": {
                "enabled": True,
                "rules": [{"type": "include", "values": ["national", "provincial", "soe", "municipal"]}],
            },
            "bee_level": {
                "enabled": True,
                "rules": [{"min_level": 1, "max_level": 4, "min_points": 75}],
            },
            "risk_exclusion": {
                "enabled": True,
                "rules": [{"exclude_if_restricted": True, "max_forensic_score": 70.0}],
            },
            "preference": {
                "enabled": True,
                "rules": [{"min_score": 0}],
            },
        }
