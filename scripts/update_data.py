#!/usr/bin/env python3
"""Build the Recompetes snapshot from public USAspending and SAM.gov data.

No API keys. If a source fails or comes back too thin, the previous file for
that source is left in place so the site never publishes an empty directory.

Usage (from the repo root):
    python3 scripts/update_data.py
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import recompetes_data as rd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

USA = "https://api.usaspending.gov"
SAM_URLS = [
    "https://sam.gov/api/prod/fileextractservices/v1/api/download/Contract%20Opportunities/datagov/ContractOpportunitiesFullCSV.csv?privacy=Public",
    "https://s3.amazonaws.com/falextracts/Contract%20Opportunities/datagov/ContractOpportunitiesFullCSV.csv",
]
UA = "RecompetesDirectory/1.0 (+https://recompetes.com; public-data snapshot)"

# Cohort and thresholds. Tuned so a daily run finishes on a free CI runner
# while the radar still covers the largest prime awards.
RECIPIENT_INDEX = 100
PROFILE_LIMIT = 40
AGENCY_LIMIT = 16
NAICS_LIMIT = 28
TOP_ON_PAGE = 8
CONTRACT_LIMIT = 22
IDV_LIMIT = 6
DETAIL_ENRICH = 40
SAM_KEEP = 400
SAM_SCAN_MAX = 6000
SAM_WINDOW_DAYS = 21
WORKERS = 4
RECOMPETE_HORIZON_DAYS = 540
RECOMPETE_MIN = 5_000_000
PAST_DAYS = 14

CONTRACT_TYPES = ["A", "C", "D"]
IDV_TYPES = ["IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B", "IDV_B_C", "IDV_C", "IDV_D", "IDV_E"]
AWARD_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
    "Award Amount",
    "Description",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Start Date",
    "End Date",
    "Last Date to Order",
    "Contract Award Type",
    "generated_internal_id",
    "recipient_id",
]

TODAY = date.today()
OBLIGATION_START = "2023-10-01"
OBLIGATION_END = TODAY.isoformat()
AWARD_START = "2018-10-01"
AWARD_END = TODAY.isoformat()


def log(message: str) -> None:
    print(message, flush=True)


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log(f"Could not read {path.name}: {exc}")
        return None


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def request_json(url: str, payload: dict | None = None, timeout: int = 75, attempts: int = 3) -> Any:
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    last_error: Exception | None = None
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:400]
            last_error = RuntimeError(f"HTTP {exc.code} {url} {body}")
            if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
                time.sleep(1.4 * (attempt + 1))
                continue
            raise last_error from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise
    raise last_error or RuntimeError(f"Request failed: {url}")


def obligation_filters(**extra: Any) -> dict[str, Any]:
    filters: dict[str, Any] = {
        "time_period": [{"start_date": OBLIGATION_START, "end_date": OBLIGATION_END}],
        "award_type_codes": ["A", "B", "C", "D"],
    }
    filters.update(extra)
    return filters


def fetch_category(category: str, filters: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    url = f"{USA}/api/v2/search/spending_by_category/{category}/"
    payload = request_json(url, {"filters": filters, "limit": limit, "page": 1})
    return list(payload.get("results") or [])


def fetch_awards(name: str, award_types: list[str], limit: int) -> list[dict[str, Any]]:
    payload = request_json(
        f"{USA}/api/v2/search/spending_by_award/",
        {
            "limit": limit,
            "page": 1,
            "sort": "Award Amount",
            "order": "desc",
            "filters": {
                "award_type_codes": award_types,
                "time_period": [
                    {"start_date": AWARD_START, "end_date": AWARD_END, "date_type": "action_date"}
                ],
                "award_amounts": [{"lower_bound": 1_000_000, "upper_bound": 90_000_000_000}],
                "recipient_search_text": [name],
            },
            "fields": AWARD_FIELDS,
        },
        timeout=90,
    )
    return list(payload.get("results") or [])


def fetch_recipient(recipient_id: str) -> dict[str, Any]:
    if not recipient_id:
        return {}
    try:
        return request_json(f"{USA}/api/v2/recipient/{recipient_id}/", timeout=40)
    except Exception as exc:  # noqa: BLE001 — profile fields are optional
        log(f"  recipient profile skipped for {recipient_id}: {exc}")
        return {}


def fetch_award_detail(generated_id: str) -> dict[str, Any]:
    url = f"{USA}/api/v2/awards/{urllib.request.quote(generated_id, safe='')}/"
    return request_json(url, timeout=40)


def location_of(profile: dict[str, Any]) -> dict[str, str]:
    loc = profile.get("location") or {}
    if not isinstance(loc, dict):
        return {"city": "", "state": "", "zip": "", "country": "", "line": ""}
    return {
        "line": str(loc.get("address_line1") or ""),
        "city": rd.humanize(str(loc.get("city_name") or "")),
        "state": str(loc.get("state_code") or ""),
        "zip": str(loc.get("zip") or ""),
        "country": rd.humanize(str(loc.get("country_name") or "")),
    }


def map_award(row: dict[str, Any]) -> dict[str, Any] | None:
    amount = rd.dollars(row.get("Award Amount"))
    if amount < 1_000_000:
        return None
    end = ""
    for key in ("End Date", "Last Date to Order"):
        day = rd.parse_day(row.get(key))
        if day:
            end = day.isoformat()
            break
    generated = str(row.get("generated_internal_id") or "")
    description = rd.strip_html(row.get("Description"), 320)
    if len(description) < 12 or rd.looks_corrupt(description):
        description = rd.fallback_description(
            rd.humanize(row.get("Contract Award Type") or ""),
            row.get("Awarding Sub Agency") or row.get("Awarding Agency") or "",
            award_id=str(row.get("Award ID") or ""),
        )
    return {
        "id": str(row.get("Award ID") or ""),
        "generated_id": generated,
        "description": description or "Federal contract award",
        "amount": amount,
        "agency": row.get("Awarding Agency") or "",
        "agency_slug": row.get("agency_slug") or "",
        "subagency": row.get("Awarding Sub Agency") or "",
        "naics": "",
        "naics_name": "",
        "psc": "",
        "psc_name": "",
        "start": (rd.parse_day(row.get("Start Date")).isoformat() if rd.parse_day(row.get("Start Date")) else ""),
        "end": end,
        "potential_end": "",
        "type": rd.humanize(row.get("Contract Award Type") or ""),
        "set_aside": "",
        "extent_competed": "",
        "recipient_name": row.get("Recipient Name") or "",
        "uei": str(row.get("Recipient UEI") or "").upper(),
        "usaspending_url": f"https://www.usaspending.gov/award/{generated}" if generated else "",
    }


def summarize_groups(awards: list[dict[str, Any]], key: str, slug_key: str | None = None) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for award in awards:
        name = award.get(key) or ""
        if not name:
            continue
        bucket = totals.setdefault(
            name,
            {"name": name, "slug": award.get(slug_key) or "" if slug_key else "", "amount": 0},
        )
        bucket["amount"] += award["amount"]
    ranked = sorted(totals.values(), key=lambda item: item["amount"], reverse=True)
    return ranked[:8]


def build_contractor(raw: dict[str, Any], used_slugs: set[str]) -> dict[str, Any] | None:
    name = str(raw.get("name") or "").strip()
    if not rd.is_usable_name(name):
        return None
    uei = str(raw.get("uei") or "").upper()
    recipient_id = str(raw.get("recipient_id") or "")
    contracts = fetch_awards(name, CONTRACT_TYPES, CONTRACT_LIMIT)
    time.sleep(0.15)
    idvs = fetch_awards(name, IDV_TYPES, IDV_LIMIT)
    time.sleep(0.1)
    selected = rd.select_awards(name, uei, contracts + idvs)
    awards = []
    seen = set()
    for row in selected:
        mapped = map_award(row)
        if not mapped or mapped["generated_id"] in seen:
            continue
        seen.add(mapped["generated_id"])
        awards.append(mapped)
    awards.sort(key=lambda item: item["amount"], reverse=True)

    profile = fetch_recipient(recipient_id)
    time.sleep(0.05)
    naics_rows: list[dict[str, Any]] = []
    try:
        naics_rows = fetch_category(
            "naics",
            obligation_filters(recipient_search_text=[name]),
            6,
        )
    except Exception as exc:  # noqa: BLE001 — awards still make a useful profile
        log(f"  NAICS mix skipped for {name}: {exc}")
    naics = []
    for row in naics_rows:
        code = rd.naics_code(row.get("code"))
        if not code:
            continue
        naics.append({"code": code, "name": row.get("name") or code, "amount": rd.dollars(row.get("amount"))})
    agencies = summarize_groups(awards, "agency", "agency_slug")

    types = list(profile.get("business_types") or [])
    location = location_of(profile)
    slug = rd.unique_slug(name, uei or recipient_id, used_slugs)
    return {
        "slug": slug,
        "name": profile.get("name") or name,
        "uei": profile.get("uei") or uei,
        "recipient_id": recipient_id,
        "parent_name": profile.get("parent_name") or "",
        "location": location,
        "business_types": rd.business_chips(types),
        "small_business": rd.is_small_business(types),
        "total_obligations": rd.dollars(raw.get("amount")),
        "profiled": True,
        "naics": naics,
        "agencies": agencies,
        "awards": awards,
        "usaspending_url": f"https://www.usaspending.gov/recipient/{recipient_id}/latest" if recipient_id else "",
    }


def slim_contractor(contractor: dict[str, Any], profiled: bool) -> dict[str, Any]:
    naics = contractor.get("naics") or []
    agencies = contractor.get("agencies") or []
    location = contractor.get("location") or {}
    return {
        "slug": contractor.get("slug") or "",
        "name": contractor.get("name") or "",
        "uei": contractor.get("uei") or "",
        "recipient_id": contractor.get("recipient_id") or "",
        "state": location.get("state") or "",
        "amount": contractor.get("total_obligations") or contractor.get("amount") or 0,
        "profiled": profiled,
        "small_business": bool(contractor.get("small_business")),
        "top_naics": naics[0]["name"] if naics else "",
        "top_naics_code": naics[0]["code"] if naics else "",
        "top_agency": agencies[0]["name"] if agencies else "",
        "usaspending_url": contractor.get("usaspending_url") or "",
    }


def index_only(raw: dict[str, Any], used_slugs: set[str]) -> dict[str, Any] | None:
    name = str(raw.get("name") or "").strip()
    if not rd.is_usable_name(name):
        return None
    recipient_id = str(raw.get("recipient_id") or "")
    uei = str(raw.get("uei") or "").upper()
    return {
        "slug": rd.unique_slug(name, uei or recipient_id, used_slugs),
        "name": name,
        "uei": uei,
        "recipient_id": recipient_id,
        "state": "",
        "amount": rd.dollars(raw.get("amount")),
        "profiled": False,
        "small_business": False,
        "top_naics": "",
        "top_naics_code": "",
        "top_agency": "",
        "usaspending_url": f"https://www.usaspending.gov/recipient/{recipient_id}/latest" if recipient_id else "",
    }


def link_known(name: str, by_name: dict[str, dict[str, Any]]) -> str:
    key = rd.normalize_name(name)
    found = by_name.get(key)
    return found["slug"] if found else ""


def contractor_ref(raw: dict[str, Any], by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    name = str(raw.get("name") or "")
    recipient_id = str(raw.get("recipient_id") or "")
    return {
        "name": name,
        "slug": link_known(name, by_name),
        "uei": str(raw.get("uei") or "").upper(),
        "recipient_id": recipient_id,
        "amount": rd.dollars(raw.get("amount")),
        "usaspending_url": f"https://www.usaspending.gov/recipient/{recipient_id}/latest" if recipient_id else "",
    }


def enrich_award(award: dict[str, Any], detail: dict[str, Any]) -> None:
    contract = detail.get("latest_transaction_contract_data") or {}
    hierarchy = (detail.get("naics_hierarchy") or {}).get("base_code") or {}
    code = rd.naics_code(contract.get("naics") or hierarchy.get("code"))
    if code:
        award["naics"] = code
    name = contract.get("naics_description") or hierarchy.get("description") or ""
    if name:
        award["naics_name"] = rd.humanize(str(name))
    potential = rd.parse_day((detail.get("period_of_performance") or {}).get("potential_end_date"))
    if potential:
        award["potential_end"] = potential.isoformat()
    if contract.get("type_set_aside_description"):
        award["set_aside"] = rd.clean_setaside(str(contract.get("type_set_aside_description")))
    if contract.get("extent_competed_description"):
        award["extent_competed"] = rd.humanize(str(contract.get("extent_competed_description")))
    if contract.get("product_or_service_code"):
        award["psc"] = str(contract.get("product_or_service_code"))
        award["psc_name"] = rd.humanize(str(contract.get("product_or_service_description") or ""))


def recompete_from(contractor: dict[str, Any], award: dict[str, Any]) -> dict[str, Any]:
    end = rd.parse_day(award.get("end"))
    days = rd.days_between(end, TODAY)
    return {
        "award_id": award.get("id") or "",
        "generated_id": award.get("generated_id") or "",
        "slug": contractor["slug"],
        "incumbent": contractor["name"],
        "uei": contractor.get("uei") or "",
        "description": award.get("description") or "",
        "amount": award.get("amount") or 0,
        "agency": award.get("agency") or "",
        "agency_slug": award.get("agency_slug") or "",
        "subagency": award.get("subagency") or "",
        "naics": award.get("naics") or "",
        "naics_name": award.get("naics_name") or "",
        "start": award.get("start") or "",
        "end": award.get("end") or "",
        "potential_end": award.get("potential_end") or "",
        "days": days if days is not None else 0,
        "type": award.get("type") or "",
        "set_aside": award.get("set_aside") or "",
        "extent_competed": award.get("extent_competed") or "",
        "psc": award.get("psc") or "",
        "usaspending_url": award.get("usaspending_url") or "",
    }


def map_notice(row: dict[str, str]) -> dict[str, Any] | None:
    notice_id = (row.get("NoticeId") or "").strip()
    title = rd.strip_html(row.get("Title"), 240)
    if not notice_id or not title:
        return None
    active = (row.get("Active") or "Yes").strip().lower()
    if active not in {"yes", "y", "true", "1"}:
        return None
    posted = rd.parse_day(row.get("PostedDate"))
    deadline = rd.parse_day(row.get("ResponseDeadLine"))
    setaside = rd.clean_setaside(row.get("SetASide"))
    naics = rd.naics_code(row.get("NaicsCode"))
    notice_type = (row.get("Type") or row.get("BaseType") or "Notice").strip()
    link = (row.get("Link") or "").strip() or f"https://sam.gov/opp/{notice_id}/view"
    return {
        "id": notice_id,
        "title": title,
        "solicitation": (row.get("Sol#") or "").strip(),
        "agency": rd.humanize(row.get("Department/Ind.Agency") or ""),
        "office": rd.humanize(row.get("Office") or ""),
        "type": notice_type,
        "posted": posted.isoformat() if posted else "",
        "posted_at": (row.get("PostedDate") or "")[:19],
        "deadline": deadline.isoformat() if deadline else "",
        "deadline_at": (row.get("ResponseDeadLine") or "")[:25],
        "set_aside": setaside,
        "set_aside_bucket": rd.setaside_bucket(row.get("SetASide"), row.get("SetASideCode")),
        "naics": naics,
        "state": (row.get("PopState") or row.get("State") or "").strip(),
        "city": rd.humanize(row.get("PopCity") or row.get("City") or ""),
        "contact_name": (row.get("PrimaryContactFullname") or "").strip(),
        "contact_email": (row.get("PrimaryContactEmail") or "").strip(),
        "link": link,
        "description": rd.strip_html(row.get("Description"), 420),
    }


def fetch_sam() -> dict[str, Any]:
    last_error: Exception | None = None
    for url in SAM_URLS:
        try:
            log(f"SAM.gov extract: {url.split('?')[0]}")
            return _stream_sam(url)
        except Exception as exc:  # noqa: BLE001 — try the fallback URL
            last_error = exc
            log(f"SAM source failed, trying fallback: {exc}")
    raise last_error or RuntimeError("SAM.gov extract unavailable")


def _stream_sam(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/csv,*/*"})
    response = urllib.request.urlopen(req, timeout=180)
    modified = response.headers.get("Last-Modified")
    notices: list[dict[str, Any]] = []
    seen: set[str] = set()
    newest: date | None = None
    scanned = 0
    try:
        wrapper = io.TextIOWrapper(response, encoding="cp1252", errors="replace", newline="")
        reader = csv.DictReader(wrapper)
        csv.field_size_limit(10_000_000)
        for row in reader:
            scanned += 1
            if scanned > SAM_SCAN_MAX or len(notices) >= SAM_KEEP:
                break
            posted = rd.parse_day(row.get("PostedDate"))
            if posted and (newest is None or posted > newest):
                newest = posted
            if (
                newest
                and posted
                and len(notices) >= 40
                and (newest - posted).days > SAM_WINDOW_DAYS
            ):
                break
            item = map_notice(row)
            if not item or item["id"] in seen:
                continue
            if item["posted"] and newest and (newest - rd.parse_day(item["posted"])).days > SAM_WINDOW_DAYS:  # type: ignore[operator]
                continue
            seen.add(item["id"])
            notices.append(item)
    finally:
        try:
            response.close()
        except Exception:
            pass
    notices.sort(key=lambda item: item.get("posted_at") or item.get("posted") or "", reverse=True)
    log(f"SAM.gov kept {len(notices)} notices after scanning {scanned} rows (extract {modified})")
    return {"modified": modified, "opportunities": notices[:SAM_KEEP]}


def merge_profiles(profiled: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One page per legal name. Awards from sibling UEIs are kept."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for contractor in profiled:
        grouped.setdefault(rd.normalize_name(contractor["name"]), []).append(contractor)
    merged: list[dict[str, Any]] = []
    for group in grouped.values():
        group.sort(key=lambda item: (len(item["awards"]), item["total_obligations"]), reverse=True)
        keep = group[0]
        seen = {award.get("generated_id") for award in keep["awards"]}
        naics = {row["code"]: row for row in keep.get("naics") or []}
        agencies = {row["name"]: row for row in keep.get("agencies") or []}
        for other in group[1:]:
            keep["total_obligations"] = max(keep["total_obligations"], other["total_obligations"])
            for award in other["awards"]:
                if award.get("generated_id") not in seen:
                    keep["awards"].append(award)
                    seen.add(award.get("generated_id"))
            for row in other.get("naics") or []:
                current = naics.get(row["code"])
                if current is None or row["amount"] > current["amount"]:
                    naics[row["code"]] = row
            for row in other.get("agencies") or []:
                current = agencies.get(row["name"])
                if current is None or row["amount"] > current["amount"]:
                    agencies[row["name"]] = row
        keep["awards"].sort(key=lambda award: award["amount"], reverse=True)
        keep["naics"] = sorted(naics.values(), key=lambda row: row["amount"], reverse=True)[:6]
        keep["agencies"] = sorted(agencies.values(), key=lambda row: row["amount"], reverse=True)[:8]
        merged.append(keep)
    merged.sort(key=lambda item: item["total_obligations"], reverse=True)
    return merged


def build_usaspending() -> dict[str, Any]:
    log("Fetching contractor, agency, and NAICS leaderboards…")
    recipients = [
        row
        for row in fetch_category("recipient", obligation_filters(), RECIPIENT_INDEX)
        if rd.is_usable_name(row.get("name"))
    ]
    agency_rows = fetch_category("awarding_agency", obligation_filters(), AGENCY_LIMIT)
    naics_rows = fetch_category("naics", obligation_filters(), NAICS_LIMIT)
    log(f"Leaderboards: {len(recipients)} recipients, {len(agency_rows)} agencies, {len(naics_rows)} NAICS")

    used_slugs: set[str] = set()
    profiled: list[dict[str, Any]] = []
    failures = 0
    targets = recipients[:PROFILE_LIMIT]

    # Slugs are assigned on the main thread before workers start.
    preassigned = []
    for raw in targets:
        slug = rd.unique_slug(str(raw.get("name")), str(raw.get("uei") or raw.get("recipient_id") or ""), used_slugs)
        preassigned.append((raw, slug))

    def _one_assigned(item: tuple[dict[str, Any], str]) -> dict[str, Any] | None:
        raw, slug = item
        local: set[str] = set()
        started = time.time()
        contractor = build_contractor(raw, local)
        if contractor:
            contractor["slug"] = slug
            log(f"  profiled {contractor['name']} ({len(contractor['awards'])} awards, {time.time() - started:.1f}s)")
        return contractor

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(_one_assigned, item) for item in preassigned]
        for future in as_completed(futures):
            try:
                contractor = future.result()
            except Exception as exc:  # noqa: BLE001
                failures += 1
                log(f"  contractor failed: {exc}")
                continue
            if contractor:
                profiled.append(contractor)
            else:
                failures += 1

    profiled = merge_profiles(profiled)
    by_name = {rd.normalize_name(item["name"]): item for item in profiled}
    by_recipient = {item["recipient_id"]: item for item in profiled if item.get("recipient_id")}

    def page_contractors(category_filter: dict[str, Any]) -> list[dict[str, Any]]:
        rows = fetch_category("recipient", category_filter, TOP_ON_PAGE)
        return [contractor_ref(row, by_name) for row in rows if rd.is_usable_name(row.get("name"))]

    agencies = []
    log("Fetching top contractors for agency and NAICS pages…")
    agency_jobs = []
    for row in agency_rows:
        name = row.get("name") or ""
        if not name:
            continue
        agencies.append(
            {
                "slug": row.get("agency_slug") or rd.slugify(name),
                "name": name,
                "code": row.get("code") or "",
                "amount": rd.dollars(row.get("amount")),
                "contractors": [],
                "usaspending_url": f"https://www.usaspending.gov/agency/{row.get('agency_slug')}" if row.get("agency_slug") else "",
            }
        )
        agency_jobs.append(agencies[-1])

    naics_pages = []
    for row in naics_rows:
        code = rd.naics_code(row.get("code"))
        if not code:
            continue
        sector_code, sector_name = rd.sector_for(code)
        naics_pages.append(
            {
                "code": code,
                "name": row.get("name") or f"NAICS {code}",
                "sector_code": sector_code,
                "sector_name": sector_name,
                "amount": rd.dollars(row.get("amount")),
                "contractors": [],
            }
        )

    def fill_agency(agency: dict[str, Any]) -> None:
        agency["contractors"] = page_contractors(
            obligation_filters(agencies=[{"type": "awarding", "tier": "toptier", "name": agency["name"]}])
        )

    def fill_naics(entry: dict[str, Any]) -> None:
        entry["contractors"] = page_contractors(
            obligation_filters(naics_codes={"require": [entry["code"]]})
        )

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(fill_agency, agency) for agency in agency_jobs]
        futures += [pool.submit(fill_naics, entry) for entry in naics_pages]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001
                log(f"  category contractors failed: {exc}")

    recompetes: list[dict[str, Any]] = []
    seen_awards: set[str] = set()
    for contractor in profiled:
        for award in contractor["awards"]:
            if not rd.in_recompete_window(
                award.get("end") or "",
                award.get("amount") or 0,
                TODAY,
                RECOMPETE_HORIZON_DAYS,
                RECOMPETE_MIN,
                PAST_DAYS,
            ):
                continue
            key = award.get("generated_id") or f"{contractor['slug']}-{award.get('id')}"
            if key in seen_awards:
                continue
            seen_awards.add(key)
            recompetes.append(recompete_from(contractor, award))

    recompetes.sort(key=lambda item: (item["days"] < 0, item["days"], -item["amount"]))
    enrich_targets = sorted(recompetes, key=lambda item: item["amount"], reverse=True)[:DETAIL_ENRICH]
    log(f"Enriching {len(enrich_targets)} recompetes with NAICS and set-aside…")

    def _enrich(item: dict[str, Any]) -> None:
        if not item.get("generated_id"):
            return
        detail = fetch_award_detail(item["generated_id"])
        # Mutate the shared award on the contractor plus the radar record.
        contractor = by_recipient.get(next((c["recipient_id"] for c in profiled if c["slug"] == item["slug"]), ""))
        award = None
        if contractor:
            award = next((row for row in contractor["awards"] if row.get("generated_id") == item["generated_id"]), None)
        if award:
            enrich_award(award, detail)
            item["naics"] = award.get("naics") or ""
            item["naics_name"] = award.get("naics_name") or ""
            item["potential_end"] = award.get("potential_end") or ""
            item["set_aside"] = award.get("set_aside") or ""
            item["extent_competed"] = award.get("extent_competed") or ""
            item["psc"] = award.get("psc") or ""
        else:
            scratch = {"generated_id": item["generated_id"]}
            enrich_award(scratch, detail)
            item.update({k: scratch.get(k, item.get(k)) for k in ("naics", "naics_name", "potential_end", "set_aside", "extent_competed", "psc")})

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(_enrich, item) for item in enrich_targets]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001
                log(f"  detail skipped: {exc}")

    for contractor in profiled:
        upcoming = [
            award
            for award in contractor["awards"]
            if rd.in_recompete_window(
                award.get("end") or "",
                award.get("amount") or 0,
                TODAY,
                RECOMPETE_HORIZON_DAYS,
                RECOMPETE_MIN,
                0,
            )
        ]
        upcoming.sort(key=lambda award: award.get("end") or "9999")
        contractor["next_recompete"] = (
            {
                "end": upcoming[0]["end"],
                "amount": upcoming[0]["amount"],
                "description": upcoming[0]["description"],
                "agency": upcoming[0]["agency"],
                "days": rd.days_between(rd.parse_day(upcoming[0]["end"]), TODAY),
            }
            if upcoming
            else None
        )
        # Drop helper fields that the site does not need.
        for award in contractor["awards"]:
            award.pop("recipient_name", None)
            award.pop("uei", None)

    index: list[dict[str, Any]] = []
    seen_ids = {item["recipient_id"] for item in profiled if item.get("recipient_id")}
    for contractor in profiled:
        index.append(slim_contractor(contractor, True))
    for raw in recipients:
        recipient_id = str(raw.get("recipient_id") or "")
        if recipient_id in seen_ids:
            continue
        slim = index_only(raw, used_slugs)
        if slim:
            index.append(slim)
            seen_ids.add(recipient_id)

    # Contractors discovered on agency/NAICS pages join search even without a profile.
    for collection in (agencies, naics_pages):
        for page in collection:
            for ref in page["contractors"]:
                recipient_id = ref.get("recipient_id") or ""
                if not recipient_id or recipient_id in seen_ids or not rd.is_usable_name(ref.get("name")):
                    continue
                slim = index_only(ref, used_slugs)
                if slim:
                    index.append(slim)
                    seen_ids.add(recipient_id)

    log(
        f"USAspending snapshot: {len(profiled)} profiles, {len(index)} searchable names, "
        f"{len(recompetes)} recompetes, {failures} contractor failures"
    )
    return {
        "contractors": {"contractors": profiled},
        "agencies": {"agencies": agencies},
        "naics": {"naics": naics_pages},
        "recompetes": {"recompetes": recompetes},
        "index": {
            "contractors": index,
            "agencies": [
                {"slug": item["slug"], "name": item["name"], "amount": item["amount"], "code": item.get("code") or ""}
                for item in agencies
            ],
            "naics": [
                {"code": item["code"], "name": item["name"], "amount": item["amount"], "sector": item["sector_name"]}
                for item in naics_pages
            ],
        },
        "counts": {
            "profiled": len(profiled),
            "index": len(index),
            "recompetes": len(recompetes),
            "failures": failures,
        },
    }


def source_status(ok: bool, error: str | None, kept: bool, **extra: Any) -> dict[str, Any]:
    return {
        "ok": ok,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "error": error,
        "kept_previous": kept,
        **extra,
    }


def publish_usaspending(snapshot: dict[str, Any]) -> None:
    write_json(DATA / "contractors.json", snapshot["contractors"])
    write_json(DATA / "agencies.json", snapshot["agencies"])
    write_json(DATA / "naics.json", snapshot["naics"])
    write_json(DATA / "recompetes.json", snapshot["recompetes"])
    write_json(DATA / "index.json", snapshot["index"])


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    previous = {
        "contractors": load_json(DATA / "contractors.json"),
        "agencies": load_json(DATA / "agencies.json"),
        "naics": load_json(DATA / "naics.json"),
        "recompetes": load_json(DATA / "recompetes.json"),
        "index": load_json(DATA / "index.json"),
        "opportunities": load_json(DATA / "opportunities.json"),
        "meta": load_json(DATA / "meta.json") or {},
    }
    usaspending_status: dict[str, Any]
    sam_status: dict[str, Any]

    try:
        snapshot = build_usaspending()
        min_profiles = max(8, PROFILE_LIMIT // 3)
        if snapshot["counts"]["profiled"] < min_profiles and previous["contractors"]:
            raise RuntimeError(
                f"Only {snapshot['counts']['profiled']} contractor profiles built; keeping the previous snapshot"
            )
        publish_usaspending(snapshot)
        usaspending_status = source_status(
            True,
            None,
            False,
            contractors=snapshot["counts"]["profiled"],
            searchable=snapshot["counts"]["index"],
            recompetes=snapshot["counts"]["recompetes"],
            failures=snapshot["counts"]["failures"],
        )
    except Exception as exc:  # noqa: BLE001
        log("USAspending update failed; previous files will be kept if they exist.")
        log(traceback.format_exc())
        kept = previous["contractors"] is not None
        if not kept:
            usaspending_status = source_status(False, str(exc), False, contractors=0, recompetes=0)
        else:
            prior = (previous["meta"].get("sources") or {}).get("usaspending") or {}
            usaspending_status = source_status(
                False,
                str(exc),
                True,
                contractors=prior.get("contractors", 0),
                recompetes=prior.get("recompetes", 0),
                searchable=prior.get("searchable", 0),
            )

    try:
        sam = fetch_sam()
        payload = {"opportunities": sam["opportunities"], "extract_modified": sam.get("modified")}
        chosen, reason = rd.choose_payload(payload, previous["opportunities"], min_items=25)
        if reason == "updated":
            write_json(DATA / "opportunities.json", payload)
            sam_status = source_status(
                True,
                None,
                False,
                notices=len(sam["opportunities"]),
                extract_modified=sam.get("modified"),
            )
        elif chosen is None:
            sam_status = source_status(False, "SAM.gov returned no notices and no previous file exists", False, notices=0)
        else:
            prior = (previous["meta"].get("sources") or {}).get("sam") or {}
            sam_status = source_status(
                False,
                f"SAM.gov result was too thin ({reason})",
                True,
                notices=prior.get("notices", 0),
                extract_modified=prior.get("extract_modified"),
            )
    except Exception as exc:  # noqa: BLE001
        log("SAM.gov update failed; previous opportunities will be kept if they exist.")
        log(traceback.format_exc())
        prior = (previous["meta"].get("sources") or {}).get("sam") or {}
        kept = previous["opportunities"] is not None
        sam_status = source_status(
            False,
            str(exc),
            kept,
            notices=prior.get("notices", 0) if kept else 0,
            extract_modified=prior.get("extract_modified") if kept else None,
        )

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "labels": {
            "obligations_window": rd.format_window(OBLIGATION_START, OBLIGATION_END),
            "awards_since": rd.format_window(AWARD_START, AWARD_END).split(" – ")[0],
            "recompete_horizon": rd.horizon_label(RECOMPETE_HORIZON_DAYS),
            "recompete_horizon_days": RECOMPETE_HORIZON_DAYS,
            "recompete_min": RECOMPETE_MIN,
            "past_days": PAST_DAYS,
        },
        "methodology": {
            "contractors": "Largest prime recipients by contract obligations since the window start.",
            "awards": "Largest definitive contracts, delivery orders, BPA calls, and IDVs with an action since the awards-since date.",
            "recompetes": "Those awards whose current end date, or last date to order, falls inside the horizon and clears the minimum obligated amount.",
            "opportunities": "Newest active notices in the public SAM.gov Contract Opportunities extract.",
        },
        "sources": {"usaspending": usaspending_status, "sam": sam_status},
    }
    write_json(DATA / "meta.json", meta)
    log(json.dumps(meta["sources"], indent=2))

    have_contractors = (DATA / "contractors.json").exists()
    have_opps = (DATA / "opportunities.json").exists()
    if not have_contractors or not have_opps:
        log("Snapshot is incomplete and there was no previous file to keep.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
