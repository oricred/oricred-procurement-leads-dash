"""Outbound email alerts.

Recipients and per-event toggles come from the Admin -> Notifications config.
They previously did not: both send sites hardcoded ops@oricred.com, so the
config was decorative and changing it had no effect.

Messages generated inside a batch job are queued and flushed over a single SMTP
connection. The previous implementation opened a connection, negotiated TLS and
authenticated once per message, inside the award ingest loop — a backfill
creating 1,000 leads performed 1,000 handshakes and delivered 1,000 separate
emails for one action.

See docs/specifications/remediation-05-integrations-and-delivery.md sections 3-4.
"""

import asyncio
import smtplib
from email.mime.text import MIMEText

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.admin_config import get_config

logger = structlog.get_logger()

# Above this many new leads in one run, send one digest instead of one message
# per lead. A thousand separate "Award Detected" emails is not a notification.
DIGEST_THRESHOLD = 5
DIGEST_MAX_ROWS = 50


class EmailAlertService:
    TEMPLATES: dict[str, str] = {
        "new_opportunity": (
            "New Opportunity: {company_name} — R{amount:,.0f}\n\n"
            "Company: {company_name}\n"
            "Award: R{amount:,.0f}\n"
            "Buyer: {buyer_org}\n"
            "Province: {province}\n"
            "Risk: {risk_flag}\n"
            "Contact: {contact_icon} {contact_label}\n\n"
            "View: {dashboard_url}"
        ),
        "award_detected": (
            "Award Detected: {company_name} — {tender_title}\n\n"
            "Tender: {tender_title}\n"
            "Supplier: {supplier_name}\n"
            "Amount: R{amount:,.0f}\n"
            "Award date: {award_date}\n\n"
            "View: {dashboard_url}"
        ),
        "past_due": (
            "Past-Due: {tender_title} — No award found\n\n"
            "Tender: {tender_title}\n"
            "Buyer: {buyer_org}\n"
            "Category: {category}\n"
            "Window: {window_start} → {window_end}\n"
            "Days overdue: {days_overdue}\n\n"
            "View: {dashboard_url}"
        ),
        "api_failure": (
            "ALERT: API Integration Failure — {endpoint}\n\n"
            "Endpoint: {endpoint}\n"
            "Error: {error}\n"
            "Attempts: {attempts}\n"
            "Time: {failed_at}\n\n"
            "Action: Check API key and endpoint availability."
        ),
    }

    SUBJECTS = {
        "new_opportunity": "[Oricred] New Opportunity",
        "award_detected": "[Oricred] Award Detected",
        "past_due": "[Oricred] Past-Due Alert",
        "api_failure": "[Oricred ALERT] API Integration Failure",
    }

    # Config keys use past_due_alert where the template uses past_due.
    CONFIG_EVENT_NAMES = {"past_due": "past_due_alert"}

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}
        self._enabled = bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)
        self._queue: list[MIMEText] = []
        if not self._enabled:
            logger.warning("smtp_not_configured", host=settings.smtp_host, user=settings.smtp_user)

    @classmethod
    async def from_config(cls, db: AsyncSession) -> "EmailAlertService":
        return cls(await get_config("admin_notifications", db))

    # ── recipients ──

    def recipients_for(self, event_type: str) -> list[str]:
        """Configured recipients, or none when the event is disabled."""
        config_name = self.CONFIG_EVENT_NAMES.get(event_type, event_type)
        event = self._config.get("events", {}).get(config_name, {})
        if not event.get("enabled", True):
            return []
        return [r.strip() for r in self._config.get("recipients", []) if r and r.strip()]

    # ── composition ──

    def _build(self, event_type: str, recipients: list[str], **kwargs) -> MIMEText | None:
        template = self.TEMPLATES.get(event_type)
        if not template:
            logger.warning("unknown_alert_type", event_type=event_type)
            return None
        try:
            body = template.format(**kwargs)
        except (KeyError, IndexError, ValueError) as exc:
            # Formatting used to run outside the guarded block, so a missing key
            # raised straight into the ingest loop and aborted the run.
            logger.warning("alert_template_error", event_type=event_type, error=str(exc))
            body = "\n".join(f"{k}: {v}" for k, v in kwargs.items())

        subject_base = self.SUBJECTS.get(event_type, "Oricred Notification")
        label = kwargs.get("company_name") or kwargs.get("tender_title") or ""
        return self._message(f"{subject_base}: {label}".rstrip(": "), body, recipients)

    def _message(self, subject: str, body: str, recipients: list[str]) -> MIMEText:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = f"{settings.email_from_name} <{settings.email_from}>"
        msg["To"] = ", ".join(recipients)
        return msg

    # ── sending ──

    async def send(self, event_type: str, **kwargs) -> bool:
        """Send one alert immediately."""
        recipients = self.recipients_for(event_type)
        if not recipients:
            logger.info("alert_suppressed", event_type=event_type)
            return False
        message = self._build(event_type, recipients, **kwargs)
        if message is None:
            return False
        if not self._enabled:
            logger.info("email_logged", event_type=event_type, subject=message["Subject"])
            return True
        return await asyncio.to_thread(self._send_many, [message]) == 1

    async def queue(self, event_type: str, **kwargs) -> None:
        """Defer an alert until flush(). Used inside batch jobs."""
        recipients = self.recipients_for(event_type)
        if not recipients:
            return
        message = self._build(event_type, recipients, **kwargs)
        if message is not None:
            self._queue.append(message)

    async def flush(self) -> int:
        """Deliver everything queued over a single SMTP connection.

        Above DIGEST_THRESHOLD messages, collapses them into one digest so a
        backfill does not produce hundreds of separate emails.
        """
        queued, self._queue = self._queue, []
        if not queued:
            return 0

        if len(queued) > DIGEST_THRESHOLD:
            queued = [self._digest(queued)]

        if not self._enabled:
            logger.info("email_logged_batch", count=len(queued))
            return len(queued)
        return await asyncio.to_thread(self._send_many, queued)

    def _digest(self, messages: list[MIMEText]) -> MIMEText:
        shown = messages[:DIGEST_MAX_ROWS]
        lines = [f"{len(messages)} new alerts.", ""]
        lines += [f"— {m['Subject']}" for m in shown]
        if len(messages) > len(shown):
            lines.append(f"...and {len(messages) - len(shown)} more.")
        recipients = [r.strip() for r in (messages[0]["To"] or "").split(",") if r.strip()]
        return self._message(
            f"[Oricred] {len(messages)} new alerts", "\n".join(lines), recipients
        )

    @staticmethod
    def _send_many(messages: list[MIMEText]) -> int:
        sent = 0
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                for message in messages:
                    try:
                        server.send_message(message)
                        sent += 1
                    except smtplib.SMTPException as exc:
                        logger.warning("email_send_failed", error=str(exc))
        except (smtplib.SMTPException, OSError):
            logger.exception("smtp_connection_failed", count=len(messages))
        return sent
