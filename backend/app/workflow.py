WORKFLOW_STAGES = [
    "new_lead",
    "client_contacted",
    "qualified_lead",
    "lost_lead",
    "won_opportunity",
    "credit_preparation",
    "credit_review",
    "pre_approved",
    "conditions_precedent",
    "term_sheet_sent",
    "term_sheet_received",
    "contracts_sent",
    "contracts_received",
    "ready_to_rff",
    "funded",
]

WORKFLOW_STAGE_LABELS = {
    "new_lead": "New Lead",
    "client_contacted": "Client Contacted",
    "qualified_lead": "Qualified Lead",
    "lost_lead": "Lost Lead",
    "won_opportunity": "Won Opportunity",
    "credit_preparation": "Credit Preparation",
    "credit_review": "Credit Review",
    "pre_approved": "Pre-Approved",
    "conditions_precedent": "Conditions Precedent",
    "term_sheet_sent": "Term Sheet Sent",
    "term_sheet_received": "Term Sheet Received",
    "contracts_sent": "Contracts Sent",
    "contracts_received": "Contracts Received",
    "ready_to_rff": "Ready to RFF",
    "funded": "Funded",
}

LEGACY_STAGE_MAP = {
    "new": "new_lead",
    "assigned": "new_lead",
    "contacted": "client_contacted",
    "in_discussion": "qualified_lead",
    "application_received": "credit_preparation",
    "closed": "lost_lead",
}


# The former combined state is retained as a database compatibility alias.
LEGACY_STAGE_MAP["conditions_precedent_preapproved"] = "pre_approved"

WORKFLOW_NEXT = {
    "new_lead": "client_contacted", "client_contacted": "qualified_lead",
    "qualified_lead": "won_opportunity", "won_opportunity": "credit_preparation",
    "credit_preparation": "credit_review", "credit_review": "pre_approved",
    "pre_approved": "conditions_precedent", "conditions_precedent": "term_sheet_sent",
    "term_sheet_sent": "term_sheet_received", "term_sheet_received": "contracts_sent",
    "contracts_sent": "contracts_received", "contracts_received": "ready_to_rff",
    "ready_to_rff": "funded",
}

def normalize_stage(stage: str | None) -> str | None:
    if stage is None:
        return None
    return LEGACY_STAGE_MAP.get(stage, stage)


def is_workflow_stage(stage: str | None) -> bool:
    return normalize_stage(stage) in WORKFLOW_STAGES

