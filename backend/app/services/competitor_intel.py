from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.companies import CompaniesClient
from app.clients.forensic import ForensicClient
from app.clients.tenders import TendersClient
from app.models.company import Company

logger = structlog.get_logger()


@dataclass
class Competitor:
    name: str
    inferred: bool
    company_id: str | None = None
    resolved: bool = False
    reason: str = ""


class CompetitorIntelService:
    def __init__(self, db: AsyncSession, tenders: TendersClient, companies: CompaniesClient, forensic: ForensicClient):
        self.db = db
        self.tenders = tenders
        self.companies = companies
        self.forensic = forensic

    async def get_speculative_competitors(self, organization_id: str | None, category_id: str | None) -> list[Competitor]:
        if not organization_id or not category_id:
            return []
        try:
            data = await self.companies.get_top_companies(organization_id, category_id, limit=10)
            return [
                Competitor(
                    name=item.get("name", "Unknown"),
                    inferred=True,
                    reason=f"Top bidder for this category from this org",
                )
                for item in data
            ]
        except Exception as e:
            logger.warning("speculative_competitors_failed", error=str(e))
            return []

    async def get_confirmed_competitors(self, tender_api_id: str) -> list[Competitor]:
        try:
            bidders = await self.tenders.get_bidders(tender_api_id)
        except Exception as e:
            logger.warning("bidders_fetch_failed", error=str(e))
            return []

        competitors = []
        for bidder in bidders:
            name = bidder.get("name", "Unknown")
            company = await self._resolve_company(name)
            competitors.append(
                Competitor(
                    name=name,
                    inferred=False,
                    company_id=str(company.id) if company else None,
                    resolved=company is not None,
                )
            )
        return competitors

    async def _resolve_company(self, name: str) -> Company | None:
        result = await self.db.execute(select(Company).where(Company.name == name))
        company = result.scalar_one_or_none()
        if company:
            return company

        try:
            match = await self.forensic.match_company(name)
            if match and match.get("confidence", 0) >= 0.8:
                company_id = match.get("company_id")
                if company_id:
                    result = await self.db.execute(select(Company).where(Company.api_id == company_id))
                    return result.scalar_one_or_none()
        except Exception as e:
            logger.warning("company_match_failed", name=name, error=str(e))

        return None
