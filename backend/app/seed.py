import structlog
from sqlalchemy import select

from app.database import async_session
from app.models.user import User
from app.models.filter_config import FilterConfig
from app.models.category import Category
from app.models.organization import Organization
from app.models.company import Company
from app.models.tender import Tender
from app.models.award import Award
from app.models.watchlist import WatchlistItem
from app.models.opportunity import Opportunity
from app.models.past_due import PastDueQueue
from app.services.auth import AuthService
from app.services.qualification import QualificationService
from datetime import datetime, timedelta, timezone

logger = structlog.get_logger()


async def seed_defaults():
    async with async_session() as db:
        result = await db.execute(select(User).limit(1))
        if result.scalar_one_or_none():
            logger.info("seed_skipped", reason="users_exist")
            return

        logger.info("seeding_defaults")

        # Admin user
        admin = User(
            email="admin@oricred.com",
            name="Admin User",
            hashed_password=AuthService.hash_password("admin123"),
            role="admin",
        )
        db.add(admin)
        logger.info("seed_admin_created", email="admin@oricred.com", password="admin123")

        # Operator user
        operator = User(
            email="ops@oricred.com",
            name="Ops User",
            hashed_password=AuthService.hash_password("ops123"),
            role="operator",
        )
        db.add(operator)

        # Filter config
        config = FilterConfig(
            key="qualification",
            value=QualificationService.default_config(),
            enabled=True,
            updated_by="system",
        )
        db.add(config)

        # Categories
        categories = [
            Category(id="construction", name="Construction"),
            Category(id="infrastructure", name="Infrastructure"),
            Category(id="it-services", name="IT Services"),
            Category(id="consulting", name="Consulting"),
            Category(id="security-guarding", name="Security Guarding"),
            Category(id="cleaning", name="Cleaning"),
            Category(id="catering", name="Catering"),
        ]
        for cat in categories:
            db.add(cat)

        # Organizations
        orgs = [
            Organization(id="org-samtrek", name="South African National Roads Agency (SANRAL)", organization_type="national"),
            Organization(id="org-treasury", name="National Treasury", organization_type="national"),
            Organization(id="org-gpw", name="Gauteng Provincial Government", organization_type="provincial"),
            Organization(id="org-transnet", name="Transnet SOC Ltd", organization_type="soe"),
        ]
        for org in orgs:
            db.add(org)

        # Companies
        companies = [
            Company(api_id="co-acme", name="Acme Construction (Pty) Ltd", bee_level=1, cipc_forensic_risk_score=12.5, restricted_supplier=False),
            Company(api_id="co-basil", name="Basil Read Holdings Ltd", bee_level=2, cipc_forensic_risk_score=45.0, restricted_supplier=False),
            Company(api_id="co-murray", name="Murray & Roberts Ltd", bee_level=2, cipc_forensic_risk_score=28.0, restricted_supplier=False),
            Company(api_id="co-wbho", name="WBHO Construction Ltd", bee_level=1, cipc_forensic_risk_score=8.0, restricted_supplier=False),
            Company(api_id="co-raubex", name="Raubex Group Ltd", bee_level=3, cipc_forensic_risk_score=32.0, restricted_supplier=False),
            Company(api_id="co-restricted", name="Blacklisted Enterprises CC", bee_level=4, cipc_forensic_risk_score=88.0, restricted_supplier=True),
        ]
        for co in companies:
            db.add(co)

        await db.flush()

        now = datetime.now(timezone.utc)

        # Tenders
        tenders = [
            Tender(
                api_id="tdr-001", raw_payload={}, title="Upgrade of N2 Highway Section 12",
                estimated_value=45000000, province="wc", category_id="construction",
                closing_date=now - timedelta(days=45), buyer_org_id="org-samtrek",
                published_at=now - timedelta(days=80), discovered_at=now - timedelta(days=79),
            ),
            Tender(
                api_id="tdr-002", raw_payload={}, title="IT Infrastructure Refresh: Department of Transport",
                estimated_value=2800000, province="gp", category_id="it-services",
                closing_date=now - timedelta(days=30), buyer_org_id="org-gpw",
                published_at=now - timedelta(days=60), discovered_at=now - timedelta(days=59),
            ),
            Tender(
                api_id="tdr-003", raw_payload={}, title="Gauteng Provincial Roads Maintenance",
                estimated_value=12000000, province="gp", category_id="construction",
                closing_date=now - timedelta(days=20), buyer_org_id="org-gpw",
                published_at=now - timedelta(days=50), discovered_at=now - timedelta(days=49),
            ),
            Tender(
                api_id="tdr-004", raw_payload={}, title="Transnet Port Terminal Expansion Feasibility Study",
                estimated_value=5500000, province="kzn", category_id="consulting",
                closing_date=now - timedelta(days=60), buyer_org_id="org-transnet",
                published_at=now - timedelta(days=90), discovered_at=now - timedelta(days=89),
            ),
            Tender(
                api_id="tdr-005", raw_payload={}, title="Small cleaning services contract",
                estimated_value=180000, province="gp", category_id="cleaning",
                closing_date=now + timedelta(days=10), buyer_org_id="org-treasury",
                published_at=now - timedelta(days=5), discovered_at=now - timedelta(days=5),
            ),
        ]
        for t in tenders:
            db.add(t)
        await db.flush()

        # Awards (for tenders 1, 2, 4)
        awards = [
            Award(
                api_id="awd-001", tender_id=tenders[0].id, raw_payload={},
                supplier_name="Acme Construction (Pty) Ltd", supplier_company_id="co-acme",
                amount=42500000, award_date=now - timedelta(days=10),
                bee_level=1, bee_points=85, buyer_org_id="org-samtrek",
                source="tenders_api", discovered_at=now - timedelta(days=10),
            ),
            Award(
                api_id="awd-002", tender_id=tenders[1].id, raw_payload={},
                supplier_name="WBHO Construction Ltd", supplier_company_id="co-wbho",
                amount=2650000, award_date=now - timedelta(days=5),
                bee_level=1, bee_points=90, buyer_org_id="org-gpw",
                source="tenders_api", discovered_at=now - timedelta(days=5),
            ),
            Award(
                api_id="awd-003", tender_id=tenders[3].id, raw_payload={},
                supplier_name="Murray & Roberts Ltd", supplier_company_id="co-murray",
                amount=5200000, award_date=now - timedelta(days=2),
                bee_level=2, bee_points=78, buyer_org_id="org-transnet",
                source="tenders_api", discovered_at=now - timedelta(days=2),
            ),
        ]
        for a in awards:
            db.add(a)
        await db.flush()

        # Watchlist items
        watchlist = [
            WatchlistItem(tender_id=tenders[2].id, status="watching",
                          expected_window_start=now - timedelta(days=5),
                          expected_window_end=now + timedelta(days=25),
                          started_watching_at=now - timedelta(days=49)),
            WatchlistItem(tender_id=tenders[4].id, status="watching",
                          expected_window_start=now + timedelta(days=15),
                          expected_window_end=now + timedelta(days=45),
                          started_watching_at=now - timedelta(days=5)),
        ]
        for w in watchlist:
            db.add(w)

        # Past due
        past_due = PastDueQueue(
            tender_id=tenders[2].id,
            entered_queue_at=now - timedelta(days=1),
            poll_count_since_due=3,
            resolution="pending",
        )
        db.add(past_due)

        # Opportunities
        opportunities = [
            Opportunity(
                tender_id=tenders[0].id, award_id=awards[0].id, company_id=companies[0].id,
                kanban_stage="contacted", assigned_to="ops@oricred.com",
                contact_sufficiency="sufficient", risk_flag="green",
            ),
            Opportunity(
                tender_id=tenders[1].id, award_id=awards[1].id, company_id=companies[3].id,
                kanban_stage="new", assigned_to=None,
                contact_sufficiency="role_based", risk_flag="green",
            ),
            Opportunity(
                tender_id=tenders[3].id, award_id=awards[2].id, company_id=companies[2].id,
                kanban_stage="assigned", assigned_to="ops@oricred.com",
                contact_sufficiency="sufficient", risk_flag="amber",
            ),
        ]
        for opp in opportunities:
            db.add(opp)

        await db.commit()
        logger.info("seed_complete", users=2, tenders=5, awards=3, opportunities=3)
