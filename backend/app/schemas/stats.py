from pydantic import BaseModel

from app.schemas.dashboard import StageCount


class YearlyCount(BaseModel):
    year: int
    count: int


class YearlyValue(BaseModel):
    year: int
    value: float


class ProvinceCount(BaseModel):
    province: str
    count: int


class SourceCount(BaseModel):
    source: str
    count: int


class StatusCount(BaseModel):
    status: str
    count: int


class BuyerCount(BaseModel):
    buyer_org_id: str
    count: int


class CategoryCount(BaseModel):
    category_id: str
    count: int


class StatsResponse(BaseModel):
    awards_per_year: list[YearlyCount]
    tenders_per_year: list[YearlyCount]
    award_value_per_year: list[YearlyValue]
    total_awards: int
    total_tenders: int
    total_leads: int
    total_watching: int
    past_due_count: int
    total_award_value: float | None
    avg_award_value: float | None
    leads_from_awards: int
    conversion_rate: float
    leads_per_stage: list[StageCount]
    awards_by_province: list[ProvinceCount]
    awards_by_source: list[SourceCount]
    tenders_by_status: list[StatusCount]
    top_buyers: list[BuyerCount]
    top_categories: list[CategoryCount]
