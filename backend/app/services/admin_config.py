from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.filter_config import FilterConfig


DEFAULT_CREDENTIALS = {
    "tsa_api_key": "",
    "tsa_base_url": "https://api.tenders-sa.org",
    "monday_api_key": "",
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "email_from": "noreply@oricred.com",
}

DEFAULT_SCRAPERS = {
    "enabled": ["joburg", "capetown"],
    "metros": {
        "joburg": {"enabled": True, "base_url": "https://coj-prod-fbdjhcbbezcbeeeu.a03.azurefd.net", "province": "gp", "name": "City of Johannesburg"},
        "capetown": {"enabled": True, "base_url": "https://web1.capetown.gov.za/web1/tenderportal", "province": "wc", "name": "City of Cape Town"},
        "ethekwini": {"enabled": False, "base_url": "", "province": "kzn", "name": "eThekwini (Durban)"},
        "ekurhuleni": {"enabled": False, "base_url": "", "province": "gp", "name": "City of Ekurhuleni"},
        "tshwane": {"enabled": False, "base_url": "", "province": "gp", "name": "City of Tshwane"},
        "nelsonmandelabay": {"enabled": False, "base_url": "", "province": "ec", "name": "Nelson Mandela Bay"},
    },
}

DEFAULT_NOTIFICATIONS = {
    "recipients": ["ops@oricred.com"],
    "events": {
        "award_detected": {"enabled": True, "subject": "[Oricred] Award Detected: {company_name}"},
        "past_due_alert": {"enabled": True, "subject": "[Oricred] Past-Due: {tender_title}"},
        "api_failure": {"enabled": True, "subject": "[Oricred ALERT] API Failure"},
    },
}

DEFAULT_SCORING = {
    "funding_suitability": {
        "bee_level_weight": 0.25,
        "award_value_weight": 0.20,
        "forensic_risk_weight": 0.20,
        "sector_alignment_weight": 0.15,
        "track_record_weight": 0.10,
        "restricted_supplier_exclusion": True,
    },
    "buyer_relationship": {
        "count_weight": 40,
        "value_weight": 30,
        "win_rate_weight": 30,
    },
}

DEFAULT_JOBS = {
    "discover_tenders": {"enabled": True, "cron": "*/15 * * * *", "description": "Poll Tenders-SA for new tenders"},
    "check_awards": {"enabled": True, "cron": "0 * * * *", "description": "Check awards for watching tenders"},
    "refresh_timing_model": {"enabled": True, "cron": "0 2 * * 0", "description": "Recompute award-timing model"},
    "sync_crm": {"enabled": True, "cron": "30 * * * *", "description": "Sync CRM activity from Monday.com"},
}

CONFIG_DEFAULTS: dict[str, tuple[dict, str]] = {
    "admin_credentials": (DEFAULT_CREDENTIALS, "API credentials and SMTP settings"),
    "admin_scrapers": (DEFAULT_SCRAPERS, "Municipal scraper configuration"),
    "admin_notifications": (DEFAULT_NOTIFICATIONS, "Email notification settings"),
    "admin_scoring": (DEFAULT_SCORING, "Scoring weights and parameters"),
    "admin_jobs": (DEFAULT_JOBS, "Scheduled job configuration"),
}

CONFIG_KEYS = list(CONFIG_DEFAULTS.keys())


async def get_config(key: str, db: AsyncSession) -> dict:
    result = await db.execute(select(FilterConfig).where(FilterConfig.key == key))
    row = result.scalar_one_or_none()
    if row:
        return row.value
    defaults, _ = CONFIG_DEFAULTS.get(key, ({}, ""))
    return dict(defaults)


async def save_config(key: str, value: dict, updated_by: str, db: AsyncSession) -> dict:
    result = await db.execute(select(FilterConfig).where(FilterConfig.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
        row.updated_at = datetime.now(timezone.utc).isoformat()
        row.updated_by = updated_by
    else:
        description = CONFIG_DEFAULTS.get(key, ({}, ""))[1]
        row = FilterConfig(
            key=key,
            value=value,
            description=description,
            enabled=True,
            updated_at=datetime.now(timezone.utc).isoformat(),
            updated_by=updated_by,
        )
        db.add(row)
    await db.commit()
    return {"status": "ok", "key": key}


async def get_all_configs(db: AsyncSession) -> dict:
    result = await db.execute(
        select(FilterConfig).where(FilterConfig.key.in_(CONFIG_KEYS))
    )
    rows = result.scalars().all()
    configs = {row.key: row.value for row in rows}
    for key in CONFIG_KEYS:
        if key not in configs:
            defaults, _ = CONFIG_DEFAULTS.get(key, ({}, ""))
            configs[key] = dict(defaults)
    return configs
