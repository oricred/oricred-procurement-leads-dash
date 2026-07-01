from pydantic import BaseModel


class StageCount(BaseModel):
    stage: str
    count: int


class DashboardStats(BaseModel):
    stages: list[StageCount]
    total_opportunities: int
    total_watching: int
    past_due_count: int
