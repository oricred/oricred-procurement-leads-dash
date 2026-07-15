import re

ACRONYMS = {
    "RFQ", "RFP", "RFB", "SABS", "PRASA", "RAF", "CSIR", "TCTA",
    "POPIA", "GRAP", "VAT", "IT", "HR", "IDC", "PPE", "CCTV",
    "HVAC", "HSRC", "SADC", "SMME", "EME", "QSE", "MSME", "SLA",
    "KPI", "SOL", "PTY", "LTD", "OEM", "PRASA", "CIDB", "SAP",
}

LOWER_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at",
    "to", "for", "of", "by", "with", "from", "as", "per", "via",
}


def normalize_title(title: str) -> str:
    """Convert an all-caps title to proper case while preserving known acronyms.

    Only transforms strings where >70% of alphabetic characters are uppercase.
    """
    alpha = re.sub(r"[^a-zA-Z]", "", title)
    if not alpha:
        return title
    upper_ratio = sum(1 for c in alpha if c.isupper()) / len(alpha)
    if upper_ratio < 0.7:
        return title

    words = title.split()
    result: list[str] = []
    for i, w in enumerate(words):
        prefix = w[: len(w) - len(w.lstrip(r"()[]{}.,;:!?-\"'"))]
        suffix = w[len(w.rstrip(r"()[]{}.,;:!?-\"'")) :]
        core = w[len(prefix) : len(w) - len(suffix)] if len(w) > len(prefix) + len(suffix) else ""

        if not core:
            result.append(w)
            continue

        upper_core = core.upper()
        if upper_core in ACRONYMS:
            result.append(prefix + upper_core + suffix)
        elif i > 0 and upper_core in {x.upper() for x in LOWER_WORDS}:
            result.append(prefix + core.lower() + suffix)
        else:
            result.append(prefix + core.capitalize() + suffix)

    return " ".join(result)


def best_title(data: dict) -> str:
    """Return the best available title from a TSA DB data dict.

    Preference: AI-enriched → original (normalized) → fallback.
    """
    ai = data.get("ai_title_enriched")
    if ai and isinstance(ai, str) and ai.strip():
        return ai.strip()

    raw = data.get("title")
    if raw and isinstance(raw, str) and raw.strip():
        return normalize_title(raw.strip())

    return "Untitled"
