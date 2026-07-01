from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.tsa_db import TSADatabase
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
    def __init__(self, db: AsyncSession, tsa_db: TSADatabase | None = None):
        self.db = db
        self.tsa_db = tsa_db or TSADatabase()

    async def get_speculative_competitors(self, organization_id: str | None, category_id: str | None) -> list[Competitor]:
        if not organization_id or not category_id:
            return []
        try:
            # Query TSA DB for top suppliers awarded by this org in this category
            awards = await self.tsa_db.query_awards(
                filters={"buyer_org_id": organization_id},
                fields=["supplier_name"],
            )
            seen: set[str] = set()
            competitors = []
            for aw in awards:
                name = aw.get("supplier_name")
                if name and name not in seen:
                    seen.add(name)
                    company = await self._resolve_company(name)
                    competitors.append(
                        Competitor(
                            name=name,
                            inferred=True,
                            company_id=str(company.id) if company else None,
                            resolved=company is not None,
                            reason="Awarded supplier for this buyer org",
                        )
                    )
                    if len(competitors) >= 10:
                        break
            return competitors
        except Exception as e:
            logger.warning("speculative_competitors_failed", error=str(e))
            return []

    async def get_confirmed_competitors(self, tender_api_id: str) -> list[Competitor]:
        try:
            bidders = await self.tsa_db.query_bidders(tender_ids=[tender_api_id])
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

        # Try lookup by name in TSA DB companies table
        try:
            companies = await self.tsa_db.query_companies(
                filters={"names": [name]},
                fields=["id", "name"],
            )
            if companies:
                co_data = companies[0]
                company = Company(
                    api_id=co_data.get("id", name),
                    name=co_data.get("name", name),
                    raw_payload=co_data,
                )
                await self.db.merge(company)
                await self.db.flush()
                return company
        except Exception as e:
            logger.warning("company_lookup_failed", name=name, error=str(e))

        return None
