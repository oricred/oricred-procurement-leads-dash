import structlog
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.config import settings
from app.models.opportunity import Opportunity
from app.models.tender import Tender
from app.models.award import Award
from app.models.company import Company
from app.services.crm import CRMAdapter
from app.services.crm.monday import MondayDotComAdapter

logger = structlog.get_logger()

BOARD_ID = "oricred_opportunities"
GROUP_ID = "main"
COLUMN_MAP = {
    "award_value": "numbers",
    "buyer_org": "text",
    "province": "dropdown",
    "kanban_stage": "status",
    "assigned_to": "people",
    "contact_sufficiency": "status",
    "risk_flag": "status",
}


def _get_adapter() -> CRMAdapter | None:
    api_key = settings.monday_api_key
    if not api_key:
        logger.warning("monday_api_key_not_configured")
        return None
    return MondayDotComAdapter(api_key)


async def push_opportunity_to_crm(opportunity_id: str) -> None:
    adapter = _get_adapter()
    if not adapter:
        return

    async with async_session() as db:
        result = await db.execute(
            select(Opportunity).where(Opportunity.id == opportunity_id)
        )
        opp = result.scalar_one_or_none()
        if not opp:
            return

        company = None
        tender = None
        award = None
        if opp.company_id:
            c_result = await db.execute(select(Company).where(Company.id == opp.company_id))
            company = c_result.scalar_one_or_none()
        if opp.tender_id:
            t_result = await db.execute(select(Tender).where(Tender.id == opp.tender_id))
            tender = t_result.scalar_one_or_none()
        if opp.award_id:
            a_result = await db.execute(select(Award).where(Award.id == opp.award_id))
            award = a_result.scalar_one_or_none()

        item_name = company.name if company else f"Opportunity {opportunity_id[:8]}"

        column_values = {}
        if award and award.amount:
            column_values["numbers"] = str(float(award.amount))
        if tender:
            if tender.buyer_org_id:
                column_values["text"] = tender.buyer_org_id
            if tender.province:
                column_values["dropdown"] = tender.province
        column_values["status"] = opp.kanban_stage.capitalize()
        if opp.assigned_to:
            column_values["people"] = opp.assigned_to
        if opp.contact_sufficiency:
            column_values["status_1"] = opp.contact_sufficiency
        if opp.risk_flag:
            column_values["status_2"] = opp.risk_flag

        item_id_key = f"crm_item_id_{BOARD_ID}"
        existing_id = getattr(opp, item_id_key, None)

        if existing_id:
            for col_id, value in column_values.items():
                await adapter.update_column_value(existing_id, col_id, value)
            logger.info("crm_opportunity_updated", opportunity_id=opportunity_id)
        else:
            item_id = await adapter.create_item(
                board_id=BOARD_ID,
                group_id=GROUP_ID,
                name=item_name,
                column_values=column_values,
            )
            logger.info("crm_opportunity_created", opportunity_id=opportunity_id, crm_item_id=item_id)


async def pull_crm_activity(since: datetime | None = None) -> None:
    adapter = _get_adapter()
    if not adapter:
        return

    if since is None:
        since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    activities = await adapter.get_recent_activity(BOARD_ID, since)
    logger.info("crm_activity_pulled", count=len(activities))

    for activity in activities:
        if activity.event in ("update_column_value", "create_item"):
            logger.debug("crm_activity_event", event=activity.event, data=activity.data)
