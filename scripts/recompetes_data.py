"""Pure transforms for the Recompetes data pipeline.

Network I/O lives in update_data.py. This module is safe to unit test.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from typing import Any

GENERIC_BUSINESS_TYPES = {
    "category_business",
    "category_organization",
    "corporate_entity_not_tax_exempt",
    "corporate_entity_tax_exempt",
    "manufacturer_of_goods",
    "special_designations",
    "us_owned_business",
    "us_owned",
    "contractor",
    "service_provider",
    "vendor",
    "partnership_or_limited_liability_partnership",
    "limited_liability_corporation",
    "subchapter_s_corporation",
    "for_profit_organization",
}

BUSINESS_LABELS = {
    "small_business": "Small business",
    "other_than_small_business": "Other than small",
    "women_owned": "Women-owned",
    "women_owned_small_business": "WOSB",
    "economically_disadvantaged_women_owned_small_business": "EDWOSB",
    "joint_venture_women_owned_small_business": "WOSB joint venture",
    "veteran_owned": "Veteran-owned",
    "service_disabled_veteran_owned": "SDVOSB",
    "minority_owned": "Minority-owned",
    "black_american_owned": "Black American-owned",
    "hispanic_american_owned": "Hispanic American-owned",
    "asian_pacific_american_owned": "Asian Pacific American-owned",
    "subcontinent_asian_indian_american": "Subcontinent Asian American-owned",
    "native_american_owned": "Native American-owned",
    "other_minority_owned": "Other minority-owned",
    "8a": "8(a)",
    "8a_program_participant": "8(a)",
    "sba_certified_8a_program_participant": "8(a)",
    "hubzone": "HUBZone",
    "hubzone_firm": "HUBZone",
    "nonprofit": "Nonprofit",
    "educational_institution": "Educational institution",
    "historically_black_college": "HBCU",
    "local_government": "Local government",
    "state_government": "State government",
    "federal_government": "Federal government",
    "tribal_government": "Tribal government",
    "foreign_owned": "Foreign-owned",
    "sole_proprietorship": "Sole proprietorship",
    "alaskan_native_corporation": "Alaska Native Corporation",
    "indian_tribe": "Indian tribe",
    "native_hawaiian_organization": "Native Hawaiian Organization",
}

ACRONYMS = {
    "DOD", "VA", "NASA", "DHS", "GSA", "DOE", "HHS", "USDA", "FAA", "FDA", "CDC",
    "NIH", "EPA", "DOT", "DOI", "DOC", "DOJ", "ED", "HUD", "OPM", "SBA", "USAID",
    "IDIQ", "BPA", "GWAC", "FFP", "CPFF", "CPAF", "T&M", "O&M", "IT", "AI", "C4ISR",
    "FMS", "LRIP", "US", "USA", "USAF", "USN", "USMC", "USSF", "SOCOM", "NATO",
    "FY", "RFP", "RFQ", "RFI", "NAICS", "PSC", "UEI", "SAM", "SDVOSB", "WOSB",
    "EDWOSB", "HUBZONE", "JV", "LLC", "LP", "LLP", "INC", "CO", "LTD", "PLC",
    "PAC", "AMRAAM", "JSF", "FMS", "OASIS", "SEWP", "CIO", "SP", "IPO", "NGO",
    "GPS", "OCX", "VCS", "VXX", "EMD", "FRP", "USACE", "VBA", "NTESS", "SNL",
    "R&D", "OEM", "COTS", "GOTS", "CONUS", "OCONUS", "FOB", "CLIN", "SLIN",
}

SMALL_WORDS = {"A", "AN", "AND", "THE", "FOR", "OF", "TO", "IN", "ON", "BY", "OR", "AT", "WITH", "FROM"}

NAME_STOP = {
    "INC", "LLC", "CORP", "CO", "LTD", "THE", "OF", "AND", "COMPANY", "CORPORATION",
    "INCORPORATED", "LP", "LLP", "PLC", "NA", "GROUP", "HOLDINGS", "HOLDING",
    "LIMITED", "INCORP", "PC", "PLLC",
}

SECTORS = {
    "11": "Agriculture, Forestry, Fishing and Hunting",
    "21": "Mining, Quarrying, and Oil and Gas Extraction",
    "22": "Utilities",
    "23": "Construction",
    "31": "Manufacturing",
    "32": "Manufacturing",
    "33": "Manufacturing",
    "42": "Wholesale Trade",
    "44": "Retail Trade",
    "45": "Retail Trade",
    "48": "Transportation and Warehousing",
    "49": "Transportation and Warehousing",
    "51": "Information",
    "52": "Finance and Insurance",
    "53": "Real Estate and Rental and Leasing",
    "54": "Professional, Scientific, and Technical Services",
    "55": "Management of Companies and Enterprises",
    "56": "Administrative and Support and Waste Management",
    "61": "Educational Services",
    "62": "Health Care and Social Assistance",
    "71": "Arts, Entertainment, and Recreation",
    "72": "Accommodation and Food Services",
    "81": "Other Services",
    "92": "Public Administration",
}

BAD_NAME = re.compile(
    r"REDACTED|MULTIPLE RECIPIENTS|MISCELLANEOUS|UNIDENTIFIED|INDIVIDUAL RECIPIENT|TO BE DETERMINED|NULL RECIPIENT",
    re.I,
)
TAG_RE = re.compile(r"<[^>]+>")
IGF_RE = re.compile(r"\bigf::[a-z0-9,]+:{2}igf\b", re.I)
SLUG_RE = re.compile(r"[^a-z0-9]+")
WS_RE = re.compile(r"\s+")


def dollars(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def is_usable_name(name: str | None) -> bool:
    if not name:
        return False
    cleaned = name.strip()
    if len(cleaned) < 2:
        return False
    if BAD_NAME.search(cleaned):
        return False
    return True


def normalize_name(name: str) -> str:
    text = (name or "").upper()
    text = text.replace("&", " AND ")
    text = text.replace(".", " ")
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = text.replace(" CORPORATION ", " CORP ")
    text = text.replace(" INCORPORATED ", " INC ")
    text = text.replace(" COMPANY ", " CO ")
    text = text.replace(" LIMITED ", " LTD ")
    text = WS_RE.sub(" ", text).strip()
    return text


def name_tokens(name: str) -> list[str]:
    return [token for token in normalize_name(name).split() if token not in NAME_STOP and len(token) > 1]


def names_match(query: str, candidate: str) -> bool:
    left = normalize_name(query)
    right = normalize_name(candidate)
    if not left or not right:
        return False
    if left == right or right.startswith(left) or left.startswith(right):
        return True
    return False


def names_related(query: str, candidate: str) -> bool:
    if names_match(query, candidate):
        return True
    qt = name_tokens(query)
    ct = name_tokens(candidate)
    if not qt or not ct:
        return False
    width = 2 if len(qt) >= 2 and len(ct) >= 2 else 1
    return qt[:width] == ct[:width]


def slugify(name: str, extra: str = "") -> str:
    base = SLUG_RE.sub("-", (name or "").lower().replace("&", " and ")).strip("-")
    base = re.sub(r"-{2,}", "-", base)[:56].strip("-")
    suffix = SLUG_RE.sub("", (extra or "").lower())[:6]
    if base and suffix:
        return f"{base}-{suffix}"
    return base or suffix or "listing"


def unique_slug(name: str, extra: str, used: set[str]) -> str:
    slug = slugify(name, extra)
    if slug not in used:
        used.add(slug)
        return slug
    stem = slug
    n = 2
    while f"{stem}-{n}" in used:
        n += 1
    slug = f"{stem}-{n}"
    used.add(slug)
    return slug


def humanize(value: str | None) -> str:
    text = WS_RE.sub(" ", html.unescape(value or "").replace("\xa0", " ")).strip()
    if not text:
        return ""
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return text
    upper_ratio = sum(1 for char in letters if char.isupper()) / len(letters)
    if upper_ratio < 0.62:
        return text
    words = text.split(" ")
    out: list[str] = []
    for index, token in enumerate(words):
        core = re.sub(r"[^A-Za-z0-9]", "", token).upper()
        if not core:
            out.append(token)
            continue
        if core in ACRONYMS or (any(ch.isdigit() for ch in core) and len(core) <= 6):
            out.append(token.upper() if token.isalpha() or "-" in token or any(ch.isdigit() for ch in token) else token)
            continue
        if core in SMALL_WORDS and index not in (0, len(words) - 1):
            out.append(token.lower())
            continue
        pieces = []
        for piece in token.split("-"):
            if not piece:
                pieces.append(piece)
                continue
            pieces.append(piece[:1].upper() + piece[1:].lower())
        out.append("-".join(pieces))
    return " ".join(out)


def looks_corrupt(text: str) -> bool:
    if text.count("!") >= 3 or text.count("|") >= 2:
        return True
    if len(text) > 90 and text.count(" ") < max(3, len(text) // 28):
        return True
    return False


def polish_description(text: str) -> str:
    """Turn all-caps title case into a sentence, then restore contracting acronyms."""
    cleaned = IGF_RE.sub(" ", text or "")
    cleaned = WS_RE.sub(" ", cleaned).strip(" -–—")
    if not cleaned or looks_corrupt(cleaned):
        return ""
    words = cleaned.split(" ")
    titled = sum(1 for word in words if word[:1].isupper() and (len(word) < 2 or word[1:2].islower()))
    if len(words) >= 6 and titled >= len(words) * 0.34:
        rebuilt: list[str] = []
        for index, word in enumerate(words):
            core = re.sub(r"[^A-Za-z0-9]", "", word)
            if core.isupper() and 2 <= len(core) <= 6:
                rebuilt.append(word)
            elif index == 0:
                rebuilt.append(word[:1].upper() + word[1:].lower())
            else:
                rebuilt.append(word.lower())
        cleaned = " ".join(rebuilt)
    cleaned = re.sub(r"\bthe to\b", "the task order", cleaned, flags=re.I)
    fixes = {
        "gps": "GPS", "ocx": "OCX", "usace": "USACE", "vcs": "VCS", "vxx": "VXX",
        "emd": "EMD", "frp": "FRP", "lrip": "LRIP", "fms": "FMS", "dod": "DoD",
        "usaf": "USAF", "usn": "USN", "nasa": "NASA", "non-dod": "non-DoD", "f-35a": "F-35A",
        "f-35b": "F-35B", "f-35c": "F-35C",
    }
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        return fixes.get(token.lower(), token)
    return re.sub(r"\b[A-Za-z0-9][A-Za-z0-9-]{0,6}\b", replace, cleaned)


def strip_html(value: str | None, limit: int = 420) -> str:
    text = TAG_RE.sub(" ", value or "")
    text = html.unescape(text)
    text = IGF_RE.sub(" ", text)
    text = humanize(text)
    text = polish_description(text)
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1].rsplit(" ", 1)[0]
    return f"{clipped}…"


def fallback_description(kind: str, agency: str, naics_name: str = "", award_id: str = "") -> str:
    base = naics_name or kind or "Federal contract"
    if award_id and not naics_name:
        base = f"{base} {award_id}".strip()
    if agency:
        return f"{base} for {agency}"
    return base or "Federal contract award"


def business_chips(types: list[str] | None) -> list[str]:
    chips: list[str] = []
    for raw in types or []:
        key = str(raw).strip()
        if not key or key in GENERIC_BUSINESS_TYPES:
            continue
        label = BUSINESS_LABELS.get(key) or humanize(key.replace("_", " "))
        if label and label not in chips:
            chips.append(label)
    return chips[:6]


def is_small_business(types: list[str] | None) -> bool:
    keys = set(types or [])
    if "other_than_small_business" in keys:
        return False
    return "small_business" in keys


def sector_for(code: str | None) -> tuple[str, str]:
    digits = re.sub(r"\D", "", code or "")
    if len(digits) < 2:
        return "", ""
    prefix = digits[:2]
    return prefix, SECTORS.get(prefix, "Other")


def naics_code(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) >= 6:
        return digits[:6]
    return digits


def parse_day(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if len(text) < 10:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def days_between(end: date | None, today: date) -> int | None:
    if end is None:
        return None
    return (end - today).days


def award_end(row: dict[str, Any]) -> str:
    for key in ("End Date", "end", "Last Date to Order"):
        day = parse_day(row.get(key) if key != "end" else row.get("end"))
        if day:
            return day.isoformat()
    return ""


def select_awards(contractor_name: str, contractor_uei: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    uei = (contractor_uei or "").upper()
    exact_uei = []
    matched = []
    related = []
    for row in rows:
        row_uei = str(row.get("Recipient UEI") or row.get("uei") or "").upper()
        row_name = str(row.get("Recipient Name") or row.get("recipient") or "")
        if uei and row_uei and row_uei == uei:
            exact_uei.append(row)
        elif names_match(contractor_name, row_name):
            matched.append(row)
        elif names_related(contractor_name, row_name):
            related.append(row)
    if len(exact_uei) >= 5:
        return exact_uei
    if len(exact_uei) + len(matched) >= 3:
        return exact_uei + matched
    if exact_uei or matched or related:
        return exact_uei + matched + related
    return []


def setaside_bucket(label: str | None, code: str | None = "") -> str:
    blob = f"{code or ''} {label or ''}".upper()
    if not blob.strip() or "NO SET" in blob or blob.strip() in {"NONE", "NONE NO SET ASIDE USED."}:
        return "open"
    if "SDVOSB" in blob or "SERVICE-DISABLED" in blob or "SERVICE DISABLED" in blob:
        return "sdvosb"
    if "8(A)" in blob or "8A" in blob:
        return "8a"
    if "EDWOSB" in blob:
        return "edwosb"
    if "WOSB" in blob or "WOMEN" in blob:
        return "wosb"
    if "HUBZONE" in blob or re.search(r"\bHZ", blob):
        return "hubzone"
    if "SMALL" in blob or "SBA" in blob:
        return "small"
    return "other"


def clean_setaside(label: str | None) -> str:
    text = humanize(label or "")
    if not text or "no set" in text.lower():
        return "No set-aside"
    return text


def choose_payload(new: Any, old: Any, min_items: int) -> tuple[Any, str]:
    """Keep the previous snapshot when a fetch fails or comes back too thin."""
    if new is None:
        if old is None:
            return None, "missing"
        return old, "kept-previous"
    count = _count_items(new)
    if count < min_items:
        if old is not None and _count_items(old) >= count:
            return old, "kept-previous-short"
    return new, "updated"


def _count_items(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("contractors", "opportunities", "recompetes", "agencies", "naics", "index"):
            if isinstance(payload.get(key), list):
                return len(payload[key])
    return 0


def in_recompete_window(end_iso: str, amount: int, today: date, horizon_days: int, min_amount: int, past_days: int = 14) -> bool:
    end = parse_day(end_iso)
    if end is None or amount < min_amount:
        return False
    delta = (end - today).days
    return -past_days <= delta <= horizon_days


def format_window(start_iso: str, end_iso: str) -> str:
    start = parse_day(start_iso)
    end = parse_day(end_iso)
    if not start or not end:
        return f"{start_iso} – {end_iso}"

    def fmt(day: date) -> str:
        return f"{day.strftime('%b')} {day.day}, {day.year}"

    return f"{fmt(start)} – {fmt(end)}"


def horizon_label(days: int) -> str:
    if days % 30 == 0 and days >= 30:
        months = days // 30
        return f"{months} month" if months == 1 else f"{months} months"
    return f"{days} days"


def add_days(day: date, count: int) -> str:
    return (day + timedelta(days=count)).isoformat()


SOCIO_TAGS = {"small", "8a", "sdvosb", "wosb", "hubzone"}


def select_cohort(rows: list[dict], cap: int, socio_share: float = 0.45) -> list[dict]:
    """Pick profile pages: a share of socioeconomic firms, then the largest remaining."""
    ranked = sorted(rows, key=lambda row: int(row.get("amount") or 0), reverse=True)
    quota = int(cap * socio_share)
    chosen: list[dict] = []
    seen: set[str] = set()
    socio_n = 0

    def add(row: dict) -> bool:
        rid = str(row.get("recipient_id") or "")
        if not rid or rid in seen:
            return False
        seen.add(rid)
        chosen.append(row)
        return True

    for row in ranked:
        if socio_n >= quota:
            break
        if set(row.get("tags") or []) & SOCIO_TAGS and add(row):
            socio_n += 1
    for row in ranked:
        if len(chosen) >= cap:
            break
        add(row)
    return chosen[:cap]
