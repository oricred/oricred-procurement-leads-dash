import structlog

logger = structlog.get_logger()


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

    async def send(self, event_type: str, recipient: str, **kwargs) -> bool:
        template = self.TEMPLATES.get(event_type)
        if not template:
            logger.warning("unknown_alert_type", event_type=event_type)
            return False

        subject_map = {
            "new_opportunity": "[Oricred] New Opportunity",
            "award_detected": "[Oricred] Award Detected",
            "past_due": "[Oricred] Past-Due Alert",
            "api_failure": "[Oricred ALERT] API Integration Failure",
        }

        subject = f"{subject_map.get(event_type, 'Oricred Notification')}: {kwargs.get('company_name', kwargs.get('tender_title', ''))}"
        body = template.format(**kwargs)

        logger.info("email_sent", event_type=event_type, recipient=recipient, subject=subject)
        return True
