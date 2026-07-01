from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


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
    def get_new_tenders(self, since: datetime) -> list[TenderResult]: ...

    @abstractmethod
    def search_awards(
        self, org: str, date_range: tuple[datetime, datetime]
    ) -> list[AwardResult]: ...


class CityOfJoburgAdapter(MunicipalPortalAdapter):
    BASE_URL = "https://www.joburg.org.za/tenders"

    async def get_new_tenders(self, since: datetime) -> list[TenderResult]:
        return []

    async def search_awards(
        self, org: str, date_range: tuple[datetime, datetime]
    ) -> list[AwardResult]:
        return []


class CityOfCapeTownAdapter(MunicipalPortalAdapter):
    BASE_URL = "https://www.capetown.gov.za/tenders"

    async def get_new_tenders(self, since: datetime) -> list[TenderResult]:
        return []

    async def search_awards(
        self, org: str, date_range: tuple[datetime, datetime]
    ) -> list[AwardResult]:
        return []
