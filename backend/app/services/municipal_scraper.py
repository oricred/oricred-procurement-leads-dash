import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger()


@dataclass
class TenderResult:
    reference: str
    title: str
    estimated_value: float | None
    closing_date: datetime | None
    province: str
    category: str | None
    buyer_org: str
    url: str


@dataclass
class AwardResult:
    tender_reference: str
    supplier_name: str
    amount: float | None
    award_date: datetime | None


class MunicipalPortalAdapter(ABC):

    @abstractmethod
    async def get_new_tenders(self, since: datetime) -> list[TenderResult]: ...

    @abstractmethod
    async def search_awards(
        self, org: str, date_range: tuple[datetime, datetime]
    ) -> list[AwardResult]: ...


class CityOfCapeTownAdapter(MunicipalPortalAdapter):
    BASE_URL = "https://web1.capetown.gov.za/web1/tenderportal"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "Oricred/1.0"},
            )
        return self._client

    async def get_new_tenders(self, since: datetime) -> list[TenderResult]:
        client = await self._get_client()
        results: list[TenderResult] = []

        try:
            response = await client.get("/Tender")
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            rows = soup.select("table tbody tr")
            if not rows:
                rows = soup.select("tr")

            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 6:
                    continue

                ref_td = cols[0].get_text(strip=True)
                desc_td = cols[1].get_text(strip=True)
                closing_td = cols[3].get_text(strip=True) if len(cols) > 3 else ""
                posted_td = cols[5].get_text(strip=True) if len(cols) > 5 else ""

                reference = ref_td.split("/")[0] if "/" in ref_td else ref_td

                closing_date = None
                try:
                    raw = closing_td.split(" ")[0] if closing_td else ""
                    if raw:
                        closing_date = datetime.strptime(raw, "%Y-%m-%d")
                except (ValueError, IndexError):
                    pass

                posted_date = None
                try:
                    raw = posted_td.split(" ")[0] if posted_td else ""
                    if raw:
                        posted_date = datetime.strptime(raw, "%Y-%m-%d")
                except (ValueError, IndexError):
                    pass

                if posted_date and posted_date < since:
                    continue

                estimated_value = self._extract_value(desc_td)

                category = self._classify_tender(desc_td)

                link = row.find("a")
                url = ""
                if link and link.get("href"):
                    url = httpx.URL(link["href"]).path if link["href"].startswith("/") else link["href"]

                results.append(TenderResult(
                    reference=reference,
                    title=desc_td[:200] if desc_td else "",
                    estimated_value=estimated_value,
                    closing_date=closing_date,
                    province="wc",
                    category=category,
                    buyer_org="City of Cape Town",
                    url=url,
                ))

            logger.info("capetown_tenders_fetched", count=len(results), since=since.isoformat())

        except Exception as e:
            logger.error("capetown_scraper_failed", error=str(e))

        return results

    async def search_awards(
        self, org: str, date_range: tuple[datetime, datetime]
    ) -> list[AwardResult]:
        return []

    def _extract_value(self, text: str) -> float | None:
        match = re.search(r"R\s*([0-9]+(?:\s[0-9]+)*(?:\.[0-9]+)?)", text)
        if match:
            raw = match.group(1).replace(" ", "")
            try:
                return float(raw)
            except ValueError:
                pass
        return None

    def _classify_tender(self, text: str) -> str | None:
        text_lower = text.lower()
        if any(w in text_lower for w in ["construct", "building", "road", "infrastructure", "civil"]):
            return "construction"
        if any(w in text_lower for w in ["it", "software", "hardware", "system", "digital", "technology", "computer"]):
            return "it-services"
        if any(w in text_lower for w in ["consult", "advisory", "study", "feasibility", "assessment"]):
            return "consulting"
        if any(w in text_lower for w in ["secur", "guard"]):
            return "security-guarding"
        if any(w in text_lower for w in ["clean", "waste"]):
            return "cleaning"
        if any(w in text_lower for w in ["cater", "food"]):
            return "catering"
        return None

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()


class CityOfJoburgAdapter(MunicipalPortalAdapter):
    BASE_URL = "https://coj-prod-fbdjhcbbezcbeeeu.a03.azurefd.net"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "Oricred/1.0"},
            )
        return self._client

    async def get_new_tenders(self, since: datetime) -> list[TenderResult]:
        client = await self._get_client()
        results: list[TenderResult] = []

        try:
            response = await client.get(
                "/joburg-for-business/tenders-and-quotations/request-for-quotations/"
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            rows = soup.select("table tbody tr")
            if not rows:
                rows = soup.select("table tr")

            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 2:
                    continue

                ref = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                # Some tables have ref in col 0
                if not ref or not ref.startswith("COJ"):
                    # Try col 0
                    ref = cols[0].get_text(strip=True) if cols else ""
                # Description might be in a sibling col
                desc = ""
                closing_text = ""
                if len(cols) >= 3:
                    desc = cols[1].get_text(strip=True)
                    closing_text = cols[2].get_text(strip=True)
                else:
                    desc = ref
                    ref = ""

                if "request for quotation" not in desc.lower() and not ref:
                    continue

                if not ref:
                    ref_match = re.search(r"(COJ\d+[-/]\d+)", desc, re.IGNORECASE)
                    ref = ref_match.group(1) if ref_match else ""

                closing_date = None
                try:
                    if closing_text:
                        closing_date = datetime.strptime(closing_text, "%d %B %Y")
                except (ValueError, IndexError):
                    pass

                estimated_value = self._extract_value(desc)

                category = self._classify_tender(cols[1].get_text(strip=True) if len(cols) > 1 else desc)

                results.append(TenderResult(
                    reference=ref or f"joburg-{len(results)}",
                    title=desc[:200] if desc else "",
                    estimated_value=estimated_value,
                    closing_date=closing_date,
                    province="gp",
                    category=category,
                    buyer_org="City of Johannesburg",
                    url=response.url.path,
                ))

            logger.info("joburg_tenders_fetched", count=len(results), since=since.isoformat())

        except Exception as e:
            logger.error("joburg_scraper_failed", error=str(e))

        return results

    async def search_awards(
        self, org: str, date_range: tuple[datetime, datetime]
    ) -> list[AwardResult]:
        return []

    def _extract_value(self, text: str) -> float | None:
        match = re.search(r"R\s*([0-9]+(?:\s[0-9]+)*(?:\.[0-9]+)?)", text)
        if match:
            raw = match.group(1).replace(" ", "")
            try:
                return float(raw)
            except ValueError:
                pass
        return None

    def _classify_tender(self, text: str) -> str | None:
        text_lower = text.lower()
        if any(w in text_lower for w in ["construct", "building", "road", "infrastructure", "civil", "maintenance"]):
            return "construction"
        if any(w in text_lower for w in ["it ", "software", "hardware", "system", "digital", "technology", "computer", "platform"]):
            return "it-services"
        if any(w in text_lower for w in ["consult", "advisory", "study", "feasibility", "assessment", "research"]):
            return "consulting"
        if any(w in text_lower for w in ["secur", "guard"]):
            return "security-guarding"
        if any(w in text_lower for w in ["clean", "waste", "sanitation"]):
            return "cleaning"
        if any(w in text_lower for w in ["cater", "food"]):
            return "catering"
        return None

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
