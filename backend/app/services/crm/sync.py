import structlog
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.opportunity import Opportunity
from app.models.tender import Tender
from app.models.award import Award
from app.models.company import Company
from app.models.contact import Contact
from app.services.crm import CRMAdapter
from app.services.crm.monday import MondayDotComAdapter
from app.services.admin_config import get_config
from app.workflow import WORKFLOW_STAGE_LABELS, normalize_stage

logger = structlog.get_logger()


async def _get_adapter(db: AsyncSession) -> CRMAdapter | None:
    creds = await get_config("admin_credentials", db)
    api_key = creds.get("monday_api_key", "")
    if not api_key:
        logger.warning("monday_api_key_not_configured")
        return None
    return MondayDotComAdapter(api_key)


async def _get_board_config(db: AsyncSession) -> tuple[str, str]:
    creds = await get_config("admin_credentials", db)
    board_id = creds.get("monday_board_id", "oricred_opportunities")
    group_id = creds.get("monday_group_id", "main")
    return board_id, group_id


async def push_opportunity_to_crm(opportunity_id: str) -> None:
    async with async_session() as db:
        adapter = await _get_adapter(db)
        if not adapter:
            return

        board_id, group_id = await _get_board_config(db)

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
        stage = normalize_stage(opp.kanban_stage) or opp.kanban_stage
        column_values["status"] = WORKFLOW_STAGE_LABELS.get(stage, stage.replace("_", " ").title())
        if opp.assigned_to:
            column_values["people"] = opp.assigned_to
        if opp.contact_sufficiency:
            column_values["status_1"] = opp.contact_sufficiency
        if opp.risk_flag:
            column_values["status_2"] = opp.risk_flag

        # Push primary contact info
        if opp.company_id:
            c_result = await db.execute(
                select(Contact).where(Contact.company_id == opp.company_id, Contact.is_primary == True).limit(1)
            )
            primary = c_result.scalar_one_or_none()
            if primary:
                contact_parts = [f"{primary.first_name} {primary.last_name}"]
                if primary.email:
                    contact_parts.append(primary.email)
                if primary.phone_direct:
                    contact_parts.append(primary.phone_direct)
                if primary.phone_mobile:
                    contact_parts.append(primary.phone_mobile)
                column_values["text7"] = " | ".join(contact_parts)

        if opp.crm_item_id:
            for col_id, value in column_values.items():
                await adapter.update_column_value(opp.crm_item_id, col_id, value)
            logger.info("crm_opportunity_updated", opportunity_id=opportunity_id)
        else:
            item_id = await adapter.create_item(
                board_id=board_id,
                group_id=group_id,
                name=item_name,
                column_values=column_values,
            )
            opp.crm_item_id = item_id
            await db.commit()
            logger.info("crm_opportunity_created", opportunity_id=opportunity_id, crm_item_id=item_id)


async def pull_crm_activity(since: datetime | None = None) -> None:
    async with async_session() as db:
        adapter = await _get_adapter(db)
        if not adapter:
            return

        board_id, _ = await _get_board_config(db)

        if since is None:
            since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        activities = await adapter.get_recent_activity(board_id, since)
        logger.info("crm_activity_pulled", count=len(activities))

        for activity in activities:
            if activity.event in ("update_column_value", "create_item"):
                logger.debug("crm_activity_event", event=activity.event, data=activity.data)

