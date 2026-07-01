from dataclasses import dataclass

from app.models.organization import Organization


@dataclass
class ContactSufficiencyResult:
    label: str
    icon: str
    reason: str


class ContactSufficiencyService:
    @staticmethod
    def classify(org: Organization | None) -> ContactSufficiencyResult:
        if not org:
            return ContactSufficiencyResult(label="none", icon="✗", reason="No contact on file")

        has_email = bool(org.contact_email)
        has_phone = bool(org.contact_phone)

        if not has_email and not has_phone:
            return ContactSufficiencyResult(
                label="none", icon="✗", reason="No contact on file",
            )

        if org.contact_email_is_role_based:
            return ContactSufficiencyResult(
                label="role_based", icon="⚠", reason="Role-based email only (e.g. info@, admin@)",
            )

        confidence = float(org.confidence_score or 0.0)
        if confidence >= 0.7:
            return ContactSufficiencyResult(
                label="sufficient", icon="✓", reason=f"Named official — confidence {confidence:.0%}",
            )
        elif confidence >= 0.4:
            return ContactSufficiencyResult(
                label="role_based", icon="⚠", reason=f"Named contact, low confidence ({confidence:.0%})",
            )
        else:
            return ContactSufficiencyResult(
                label="role_based", icon="⚠", reason=f"Named contact, insufficient confidence ({confidence:.0%})",
            )
