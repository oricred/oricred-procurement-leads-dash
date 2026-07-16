import logging
from datetime import date, datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Maximum valid year for award dates. Dates beyond this are assumed to be data
# entry errors (e.g. 2099 instead of 2025) and are silently dropped to prevent
# ingestion-cursor corruption and incorrect time-based queries.
MAX_VALID_YEAR = 2027


def parse_datetime(value: Any, context: str = "") -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            dt = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning("parse_datetime_failed value=%s context=%s", value, context)
            return None
    else:
        logger.warning("parse_datetime_unexpected_type type=%s context=%s", type(value).__name__, context)
        return None
    if dt.year > MAX_VALID_YEAR:
        logger.warning("parse_datetime_year_too_high year=%s max_year=%s context=%s", dt.year, MAX_VALID_YEAR, context)
        return None
    return dt
