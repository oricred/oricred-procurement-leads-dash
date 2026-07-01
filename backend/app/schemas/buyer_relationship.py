from datetime import datetime
from pydantic import BaseModel


class BuyerRelationshipRead(BaseModel):
    id: str
    company_id: str
    organization_id: str
    award_count_12m: int
    total_award_value_12m: float | None = None
    avg_response_days: float | None = None
    win_rate: float | None = None
    last_interaction_at: datetime | None = None
    relevance_score: float | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class BuyerRelationshipStrength(BaseModel):
    label: str
    score: float
    color: str
