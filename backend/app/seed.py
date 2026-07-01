import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.user import User
from app.models.filter_config import FilterConfig
from app.models.category import Category
from app.models.organization import Organization
from app.models.company import Company
from app.models.tender import Tender
from app.models.award import Award
from app.models.watchlist import WatchlistItem
from app.models.opportunity import Opportunity, OpportunityAudit
from app.models.past_due import PastDueQueue
from app.models.failed_api_call import FailedApiCall
from app.services.auth import AuthService
from app.services.qualification import QualificationService
from datetime import datetime, timedelta, timezone

logger = structlog.get_logger()


async def seed_defaults():
    async with async_session() as db:
        result = await db.execute(User.__table__.select().limit(1))
        if result.first():
            logger.info("seed_skipped", reason="users_exist")
            return

        logger.info("seeding_defaults")

        # === Admin configs ===
        await _seed_admin_configs(db)

        # === Users ===
        admin = User(
            email="admin@oricred.com", name="Admin User",
            hashed_password=AuthService.hash_password("admin123"), role="admin",
        )
        operator = User(
            email="ops@oricred.com", name="Ops User",
            hashed_password=AuthService.hash_password("ops123"), role="operator",
        )
        db.add_all([admin, operator])

        # === Categories ===
        categories = [
            Category(id="construction", name="Construction"),
            Category(id="infrastructure", name="Infrastructure"),
            Category(id="it-services", name="IT Services"),
            Category(id="consulting", name="Consulting"),
            Category(id="security-guarding", name="Security Guarding"),
            Category(id="cleaning", name="Cleaning"),
            Category(id="catering", name="Catering"),
            Category(id="facilities-management", name="Facilities Management"),
        ]
        db.add_all(categories)

        # === Organizations ===
        orgs = [
            Organization(id="org-sanral", name="South African National Roads Agency (SANRAL)", organization_type="national"),
            Organization(id="org-treasury", name="National Treasury", organization_type="national"),
            Organization(id="org-gpw", name="Gauteng Provincial Government", organization_type="provincial"),
            Organization(id="org-transnet", name="Transnet SOC Ltd", organization_type="soe"),
            Organization(id="org-eskom", name="Eskom Holdings SOC Ltd", organization_type="soe"),
            Organization(id="org-joburg", name="City of Johannesburg Metropolitan Municipality", organization_type="municipal"),
            Organization(id="org-cpt", name="City of Cape Town Metropolitan Municipality", organization_type="municipal"),
        ]
        db.add_all(orgs)

        # === Companies ===
        companies = [
            Company(api_id="co-acme", name="Acme Construction (Pty) Ltd", bee_level=1, cipc_forensic_risk_score=12.5, cipc_compliance_status="compliant", restricted_supplier=False),
            Company(api_id="co-basil", name="Basil Read Holdings Ltd", bee_level=2, cipc_forensic_risk_score=45.0, cipc_compliance_status="compliant", restricted_supplier=False),
            Company(api_id="co-murray", name="Murray & Roberts Ltd", bee_level=2, cipc_forensic_risk_score=28.0, cipc_compliance_status="compliant", restricted_supplier=False),
            Company(api_id="co-wbho", name="WBHO Construction Ltd", bee_level=1, cipc_forensic_risk_score=8.0, cipc_compliance_status="compliant", restricted_supplier=False),
            Company(api_id="co-raubex", name="Raubex Group Ltd", bee_level=3, cipc_forensic_risk_score=32.0, cipc_compliance_status="compliant", restricted_supplier=False),
            Company(api_id="co-afr", name="AfriSam South Africa (Pty) Ltd", bee_level=2, cipc_forensic_risk_score=18.0, cipc_compliance_status="compliant", restricted_supplier=False),
            Company(api_id="co-concor", name="Concor Infrastructure (Pty) Ltd", bee_level=2, cipc_forensic_risk_score=22.0, cipc_compliance_status="compliant", restricted_supplier=False),
            Company(api_id="co-stef", name="Stefanutti Stocks Holdings Ltd", bee_level=3, cipc_forensic_risk_score=35.0, cipc_compliance_status="compliant", restricted_supplier=False),
            Company(api_id="co-bit", name="Bitco IT Solutions (Pty) Ltd", bee_level=1, cipc_forensic_risk_score=5.0, cipc_compliance_status="compliant", restricted_supplier=False),
            Company(api_id="co-secure", name="SecureGuard National (Pty) Ltd", bee_level=2, cipc_forensic_risk_score=15.0, cipc_compliance_status="compliant", restricted_supplier=False),
        ]
        for co in companies:
            db.add(co)
        await db.flush()

        now = datetime.now(timezone.utc)

        co_ix = {c.api_id: c.id for c in companies}
        org_ix = {o.id: o for o in orgs}

        # === Tenders ===
        tenders = [
            Tender(
                api_id="tdr-001", raw_payload={}, title="Upgrade of N2 Highway Section 12",
                estimated_value=45_000_000, province="wc", category_id="construction",
                closing_date=now - timedelta(days=45), buyer_org_id="org-sanral",
                published_at=now - timedelta(days=80), discovered_at=now - timedelta(days=79),
            ),
            Tender(
                api_id="tdr-002", raw_payload={}, title="IT Infrastructure Refresh: Department of Transport",
                estimated_value=2_800_000, province="gp", category_id="it-services",
                closing_date=now - timedelta(days=30), buyer_org_id="org-gpw",
                published_at=now - timedelta(days=60), discovered_at=now - timedelta(days=59),
            ),
            Tender(
                api_id="tdr-003", raw_payload={}, title="Gauteng Provincial Roads Maintenance 2025/26",
                estimated_value=12_000_000, province="gp", category_id="construction",
                closing_date=now - timedelta(days=20), buyer_org_id="org-gpw",
                published_at=now - timedelta(days=50), discovered_at=now - timedelta(days=49),
            ),
            Tender(
                api_id="tdr-004", raw_payload={}, title="Transnet Port Terminal Expansion Feasibility Study",
                estimated_value=5_500_000, province="kzn", category_id="consulting",
                closing_date=now - timedelta(days=60), buyer_org_id="org-transnet",
                published_at=now - timedelta(days=90), discovered_at=now - timedelta(days=89),
            ),
            Tender(
                api_id="tdr-005", raw_payload={}, title="Small cleaning services contract",
                estimated_value=180_000, province="gp", category_id="cleaning",
                closing_date=now + timedelta(days=10), buyer_org_id="org-treasury",
                published_at=now - timedelta(days=5), discovered_at=now - timedelta(days=5),
            ),
            Tender(
                api_id="tdr-006", raw_payload={}, title="Eskom Medupi Ash Disposal Facility Upgrade",
                estimated_value=28_000_000, province="lp", category_id="infrastructure",
                closing_date=now - timedelta(days=15), buyer_org_id="org-eskom",
                published_at=now - timedelta(days=45), discovered_at=now - timedelta(days=44),
            ),
            Tender(
                api_id="tdr-007", raw_payload={}, title="Joburg CBD Precinct Security Services",
                estimated_value=8_500_000, province="gp", category_id="security-guarding",
                closing_date=now + timedelta(days=25), buyer_org_id="org-joburg",
                published_at=now - timedelta(days=3), discovered_at=now - timedelta(days=2),
            ),
            Tender(
                api_id="tdr-008", raw_payload={}, title="Cape Town Library Facilities Management",
                estimated_value=3_200_000, province="wc", category_id="facilities-management",
                closing_date=now - timedelta(days=8), buyer_org_id="org-cpt",
                published_at=now - timedelta(days=40), discovered_at=now - timedelta(days=39),
            ),
            Tender(
                api_id="tdr-009", raw_payload={}, title="Transnet Rail Signalling System Overhaul",
                estimated_value=15_000_000, province="gp", category_id="infrastructure",
                closing_date=now - timedelta(days=5), buyer_org_id="org-transnet",
                published_at=now - timedelta(days=35), discovered_at=now - timedelta(days=34),
            ),
            Tender(
                api_id="tdr-010", raw_payload={}, title="SANRAL N3 Toll Route Resurfacing",
                estimated_value=32_000_000, province="ec", category_id="construction",
                closing_date=now - timedelta(days=2), buyer_org_id="org-sanral",
                published_at=now - timedelta(days=60), discovered_at=now - timedelta(days=59),
            ),
        ]
        for t in tenders:
            db.add(t)
        await db.flush()
        tdr_ix = {t.api_id: t for t in tenders}

        # === Awards (for closed tenders) ===
        awards = [
            Award(
                api_id="awd-001", tender_id=tdr_ix["tdr-001"].id, raw_payload={},
                supplier_name="Acme Construction (Pty) Ltd", supplier_company_id=co_ix["co-acme"],
                amount=42_500_000, award_date=now - timedelta(days=10),
                bee_level=1, bee_points=85, buyer_org_id="org-sanral",
                source="tenders_api", discovered_at=now - timedelta(days=10),
            ),
            Award(
                api_id="awd-002", tender_id=tdr_ix["tdr-002"].id, raw_payload={},
                supplier_name="WBHO Construction Ltd", supplier_company_id=co_ix["co-wbho"],
                amount=2_650_000, award_date=now - timedelta(days=5),
                bee_level=1, bee_points=90, buyer_org_id="org-gpw",
                source="tenders_api", discovered_at=now - timedelta(days=5),
            ),
            Award(
                api_id="awd-003", tender_id=tdr_ix["tdr-004"].id, raw_payload={},
                supplier_name="Murray & Roberts Ltd", supplier_company_id=co_ix["co-murray"],
                amount=5_200_000, award_date=now - timedelta(days=2),
                bee_level=2, bee_points=78, buyer_org_id="org-transnet",
                source="tenders_api", discovered_at=now - timedelta(days=2),
            ),
            Award(
                api_id="awd-004", tender_id=tdr_ix["tdr-006"].id, raw_payload={},
                supplier_name="Basil Read Holdings Ltd", supplier_company_id=co_ix["co-basil"],
                amount=26_800_000, award_date=now - timedelta(days=3),
                bee_level=2, bee_points=72, buyer_org_id="org-eskom",
                source="tenders_api", discovered_at=now - timedelta(days=3),
            ),
            Award(
                api_id="awd-005", tender_id=tdr_ix["tdr-009"].id, raw_payload={},
                supplier_name="Concor Infrastructure (Pty) Ltd", supplier_company_id=co_ix["co-concor"],
                amount=14_200_000, award_date=now - timedelta(days=1),
                bee_level=2, bee_points=80, buyer_org_id="org-transnet",
                source="tenders_api", discovered_at=now - timedelta(days=1),
            ),
            Award(
                api_id="awd-006", tender_id=tdr_ix["tdr-010"].id, raw_payload={},
                supplier_name="Raubex Group Ltd", supplier_company_id=co_ix["co-raubex"],
                amount=31_500_000, award_date=now,
                bee_level=3, bee_points=76, buyer_org_id="org-sanral",
                source="tenders_api", discovered_at=now,
            ),
        ]
        for a in awards:
            db.add(a)
        await db.flush()

        # === Watchlist ===
        watchlist = [
            WatchlistItem(
                tender_id=tdr_ix["tdr-003"].id, status="watching",
                expected_window_start=now - timedelta(days=5),
                expected_window_end=now + timedelta(days=25),
                started_watching_at=now - timedelta(days=49),
            ),
            WatchlistItem(
                tender_id=tdr_ix["tdr-005"].id, status="watching",
                expected_window_start=now + timedelta(days=15),
                expected_window_end=now + timedelta(days=45),
                started_watching_at=now - timedelta(days=5),
            ),
            WatchlistItem(
                tender_id=tdr_ix["tdr-007"].id, status="watching",
                expected_window_start=now + timedelta(days=30),
                expected_window_end=now + timedelta(days=60),
                started_watching_at=now - timedelta(days=2),
            ),
            WatchlistItem(
                tender_id=tdr_ix["tdr-008"].id, status="awarded",
                expected_window_start=now - timedelta(days=15),
                expected_window_end=now - timedelta(days=5),
                started_watching_at=now - timedelta(days=39),
                awarded_at=now - timedelta(days=8),
            ),
        ]
        db.add_all(watchlist)

        # === Past Due Queue ===
        past_due = [
            PastDueQueue(
                tender_id=tdr_ix["tdr-003"].id,
                entered_queue_at=now - timedelta(days=1),
                poll_count_since_due=3, resolution="pending",
            ),
            PastDueQueue(
                tender_id=tdr_ix["tdr-008"].id,
                entered_queue_at=now - timedelta(days=3),
                poll_count_since_due=8, resolution="pending",
            ),
        ]
        db.add_all(past_due)

        # === Opportunities ===
        opportunities = [
            Opportunity(
                tender_id=tdr_ix["tdr-001"].id, award_id=awards[0].id, company_id=co_ix["co-acme"],
                kanban_stage="contacted", assigned_to="ops@oricred.com",
                contact_sufficiency="sufficient", risk_flag="green",
                funding_suitability=82.5, buyer_preference_score=90.0, win_probability=75.0,
                notes="Contact made via email. CEO is interested in financing options for N2 project.",
                related_bidders=[
                    {"name": "Basil Read Holdings Ltd", "inferred": False, "company_id": co_ix["co-basil"], "resolved": "Basil Read Holdings Ltd", "reason": "confirmed bidder on same tender"},
                    {"name": "WBHO Construction Ltd", "inferred": False, "company_id": co_ix["co-wbho"], "resolved": "WBHO Construction Ltd", "reason": "confirmed bidder on same tender"},
                ],
            ),
            Opportunity(
                tender_id=tdr_ix["tdr-002"].id, award_id=awards[1].id, company_id=co_ix["co-wbho"],
                kanban_stage="new", assigned_to=None,
                contact_sufficiency="role_based", risk_flag="green",
                funding_suitability=68.0, buyer_preference_score=75.0, win_probability=50.0,
            ),
            Opportunity(
                tender_id=tdr_ix["tdr-004"].id, award_id=awards[2].id, company_id=co_ix["co-murray"],
                kanban_stage="assigned", assigned_to="ops@oricred.com",
                contact_sufficiency="sufficient", risk_flag="amber",
                funding_suitability=55.0, buyer_preference_score=40.0, win_probability=60.0,
                notes="Large consulting firm — may have internal financing. Follow up needed.",
                related_bidders=[
                    {"name": "Concor Infrastructure (Pty) Ltd", "inferred": False, "company_id": co_ix["co-concor"], "resolved": "Concor Infrastructure (Pty) Ltd", "reason": "confirmed bidder on same tender"},
                    {"name": "Stefanutti Stocks Holdings Ltd", "inferred": True, "company_id": co_ix["co-stef"], "resolved": "Stefanutti Stocks Holdings Ltd", "reason": "similar company in same category for this buyer"},
                ],
            ),
            Opportunity(
                tender_id=tdr_ix["tdr-006"].id, award_id=awards[3].id, company_id=co_ix["co-basil"],
                kanban_stage="in_discussion", assigned_to="ops@oricred.com",
                contact_sufficiency="sufficient", risk_flag="green",
                funding_suitability=45.0, buyer_preference_score=60.0, win_probability=80.0,
                notes="Basil Read needs R26.8M for Eskom project. Negotiating terms — 12-month facility with prime + 3%.",
            ),
            Opportunity(
                tender_id=tdr_ix["tdr-009"].id, award_id=awards[4].id, company_id=co_ix["co-concor"],
                kanban_stage="application_received", assigned_to="admin@oricred.com",
                contact_sufficiency="sufficient", risk_flag="green",
                funding_suitability=74.0, buyer_preference_score=85.0, win_probability=90.0,
                notes="Application submitted. Credit check complete — approved in principle. Awaiting signed mandate.",
            ),
            Opportunity(
                tender_id=tdr_ix["tdr-010"].id, award_id=awards[5].id, company_id=co_ix["co-raubex"],
                kanban_stage="new", assigned_to=None,
                contact_sufficiency="none", risk_flag="red",
                funding_suitability=32.0, buyer_preference_score=50.0, win_probability=25.0,
                notes="BEE Level 3 supplier with moderate forensic risk score. Need to verify compliance status.",
            ),
        ]
        db.add_all(opportunities)
        await db.flush()

        # === Audit entries ===
        audits = [
            OpportunityAudit(opportunity_id=opportunities[0].id, from_stage="new", to_stage="contacted", changed_by="ops@oricred.com", changed_at=now - timedelta(days=8)),
            OpportunityAudit(opportunity_id=opportunities[2].id, from_stage="new", to_stage="assigned", changed_by="admin@oricred.com", changed_at=now - timedelta(days=1)),
            OpportunityAudit(opportunity_id=opportunities[3].id, from_stage="new", to_stage="assigned", changed_by="ops@oricred.com", changed_at=now - timedelta(days=2)),
            OpportunityAudit(opportunity_id=opportunities[3].id, from_stage="assigned", to_stage="in_discussion", changed_by="ops@oricred.com", changed_at=now - timedelta(hours=12)),
            OpportunityAudit(opportunity_id=opportunities[4].id, from_stage="new", to_stage="assigned", changed_by="admin@oricred.com", changed_at=now - timedelta(days=1)),
            OpportunityAudit(opportunity_id=opportunities[4].id, from_stage="assigned", to_stage="application_received", changed_by="admin@oricred.com", changed_at=now - timedelta(hours=6)),
        ]
        db.add_all(audits)

        # === Failed API calls ===
        failed = [
            FailedApiCall(endpoint="/tenders/tdr-999", params={"id": "tdr-999"}, error="404 Not Found: tender not found", attempts=3, failed_at=now - timedelta(hours=2), resolved=False),
            FailedApiCall(endpoint="/companies/top", params={"category": "mining"}, error="500 Internal Server Error", attempts=3, failed_at=now - timedelta(hours=6), resolved=True),
        ]
        db.add_all(failed)

        await db.commit()
        logger.info("seed_complete",
            users=2, tenders=len(tenders), awards=len(awards),
            watchlist=len(watchlist), past_due=len(past_due),
            opportunities=len(opportunities), audits=len(audits),
            failed_api_calls=len(failed))


async def _seed_admin_configs(db: AsyncSession):
    configs = [
        FilterConfig(
            key="qualification", value=QualificationService.default_config(),
            enabled=True, updated_by="system",
        ),
        FilterConfig(
            key="admin_credentials",
            value={
                "monday_api_key": "mock-monday-key",
                "monday_board_id": "1234567",
                "monday_group_id": "group123",
                "tsa_api_key": "mock-tsa-key",
            },
            enabled=True, updated_by="system",
        ),
        FilterConfig(
            key="admin_sources",
            value={
                "municipal": {"enabled": True, "metros": ["joburg", "cape_town"]},
                "ocpo": {"enabled": True, "base_url": "https://ocpo.example.com/api", "api_key": "mock-ocpo-key"},
                "etenders": {"enabled": True, "base_url": "https://etenders.example.com/api", "api_key": "mock-etenders-key"},
                "tsa_ocp": {"enabled": True, "base_url": "https://tsa-ocp.example.com/api", "api_key": "mock-tsa-ocp-key"},
            },
            enabled=True, updated_by="system",
        ),
        FilterConfig(
            key="admin_scoring",
            value={
                "province_weights": {"gp": 1.0, "wc": 0.9, "kzn": 0.8, "ec": 0.7, "lp": 0.6, "mp": 0.6, "nw": 0.6, "fs": 0.6, "nc": 0.5},
                "soe_bonus": 10,
                "preferred_buyers": ["org-sanral", "org-transnet"],
            },
            enabled=True, updated_by="system",
        ),
        FilterConfig(
            key="admin_notifications",
            value={"email_alerts": True, "alert_email": "ops@oricred.com"},
            enabled=True, updated_by="system",
        ),
    ]
    db.add_all(configs)
