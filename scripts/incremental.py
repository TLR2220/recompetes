#!/usr/bin/env python3
"""Grow the Recompetes snapshot without rebuilding it from scratch.

Each run:
  * pulls the next pages of USAspending recipient leaderboards
  * profiles a batch of contractors that do not have a page yet
  * merges the latest SAM.gov notices
  * republishes the site JSON from the cache

The cache lives in data/cache/. Published files in data/ are what the site
builds. A failed source keeps the previous published file.

Environment:
  PROFILE_BATCH   new profiles to fetch this run (default 250, cap 3000 total)
  PROFILE_CAP     maximum pre-rendered profiles (default 3000)
  ALL_PAGES       leaderboard pages to advance for all recipients (default 4)
  SOCIO_PAGES     pages to advance for each socioeconomic list (default 3)
  WORKERS         parallel USAspending requests (default 8)
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import recompetes_data as rd
import update_data as ud

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE = DATA / "cache"

TODAY = date.today()
OBLIGATION_START = "2023-10-01"
OBLIGATION_END = TODAY.isoformat()
AWARD_START = "2019-10-01"
AWARD_END = TODAY.isoformat()
HORIZON_DAYS = 540
RECOMPETE_MIN = 1_000_000
PAST_DAYS = 14
PAGE_SIZE = 100
PROFILE_CAP = int(os.environ.get("PROFILE_CAP", "3000"))
PROFILE_BATCH = int(os.environ.get("PROFILE_BATCH", "250"))
ALL_PAGES = int(os.environ.get("ALL_PAGES", os.environ.get("STREAM_PAGES", "4")))
SOCIO_PAGES = int(os.environ.get("SOCIO_PAGES", os.environ.get("STREAM_PAGES", "3")))
WORKERS = int(os.environ.get("WORKERS", "8"))
ALL_MAX_PAGE = 80
SOCIO_MAX_PAGE = 30
INDEX_CAP = 15000
NOTICE_CAP = 1800
RECOMPETE_CAP = 8000
AWARD_LIMIT = 8

STREAMS = [
    ("all", None, ALL_PAGES, ALL_MAX_PAGE),
    ("small_business", "small_business", SOCIO_PAGES, SOCIO_MAX_PAGE),
    ("8a_program_participant", "8a_program_participant", SOCIO_PAGES, SOCIO_MAX_PAGE),
    ("service_disabled_veteran_owned_business", "service_disabled_veteran_owned_business", SOCIO_PAGES, SOCIO_MAX_PAGE),
    ("women_owned_small_business", "women_owned_small_business", SOCIO_PAGES, SOCIO_MAX_PAGE),
    ("hubzone", "historically_underutilized_business_firm", SOCIO_PAGES, SOCIO_MAX_PAGE),
]

STREAM_TAGS = {
    "small_business": "small",
    "8a_program_participant": "8a",
    "service_disabled_veteran_owned_business": "sdvosb",
    "women_owned_small_business": "wosb",
    "hubzone": "hubzone",
}

TYPE_TAGS = [
    ("8a", ("8a_program_participant", "sba_certified_8a_program_participant", "8a")),
    ("sdvosb", ("service_disabled_veteran_owned", "service_disabled_veteran_owned_business")),
    ("wosb", ("women_owned_small_business", "economically_disadvantaged_women_owned_small_business", "women_owned")),
    ("hubzone", ("hubzone", "hubzone_firm", "historically_underutilized_business_firm", "historically_underutilized_business_zone_hubzone_firm")),
    ("small", ("small_business",)),
]

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands", "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}

SET_ASIDES = [
    ("small", "Small business", "Firms reported as small businesses, and the awards and solicitations around them."),
    ("8a", "8(a)", "SBA 8(a) participants. These pages are for teaming and set-aside capture."),
    ("sdvosb", "SDVOSB", "Service-disabled veteran-owned small businesses."),
    ("wosb", "WOSB", "Women-owned small businesses, including EDWOSB."),
    ("hubzone", "HUBZone", "Historically Underutilized Business Zone firms."),
]

AWARD_FIELDS = [
    "Award ID", "Recipient Name", "Recipient UEI", "Award Amount", "Description",
    "Awarding Agency", "Awarding Sub Agency", "Start Date", "End Date", "Last Date to Order",
    "Contract Award Type", "generated_internal_id", "recipient_id", "Place of Performance State Code",
]


def log(message: str) -> None:
    print(message, flush=True)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def load_cache(name: str, default: dict) -> dict:
    path = CACHE / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log(f"Cache {name} unreadable ({exc}); starting empty")
        return default


def save_cache(name: str, payload: dict) -> None:
    ud.write_json(CACHE / name, payload)


def compact(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(temporary, path)


def tags_from_types(types: list[str], existing: list[str] | None = None) -> list[str]:
    found = set(existing or [])
    keys = set(types or [])
    if "other_than_small_business" in keys:
        found.discard("small")
    for tag, names in TYPE_TAGS:
        if keys & set(names):
            found.add(tag)
    if found & {"8a", "sdvosb", "wosb", "hubzone"} and "other_than_small_business" not in keys:
        found.add("small")
    order = ["8a", "sdvosb", "wosb", "hubzone", "small"]
    return [tag for tag in order if tag in found]


def norm_state(value: Any) -> str:
    text = str(value or "").strip().upper()
    if len(text) == 2 and text.isalpha() and text in STATES:
        return text
    return ""


def seed_from_published(recipients: dict, profiles: dict, notices: dict) -> None:
    published = ud.load_json(DATA / "contractors.json") or {}
    for contractor in published.get("contractors") or []:
        rid = contractor.get("recipient_id") or ""
        if not rid:
            continue
        tags = list(contractor.get("tags") or [])
        if contractor.get("small_business") and "small" not in tags:
            tags.append("small")
        recipients.setdefault(rid, {
            "recipient_id": rid,
            "name": contractor.get("name") or "",
            "uei": contractor.get("uei") or "",
            "amount": contractor.get("total_obligations") or 0,
            "tags": tags_from_types([], tags),
        })
        profiles.setdefault(rid, contractor)
    existing = ud.load_json(DATA / "opportunities.json") or {}
    for notice in existing.get("opportunities") or []:
        if notice.get("id"):
            notices.setdefault(notice["id"], notice)


def fetch_recipient_page(type_name: str | None, page: int) -> list[dict[str, Any]]:
    extra: dict[str, Any] = {}
    if type_name:
        extra["recipient_type_names"] = [type_name]
    filters = ud.obligation_filters(**extra)
    url = f"{ud.USA}/api/v2/search/spending_by_category/recipient/"
    payload = ud.request_json(url, {"filters": filters, "limit": PAGE_SIZE, "page": page}, timeout=60, attempts=2)
    return list(payload.get("results") or [])


def merge_recipient(recipients: dict, row: dict, tag: str | None) -> None:
    name = str(row.get("name") or "").strip()
    rid = str(row.get("recipient_id") or "")
    if not rid or not rd.is_usable_name(name):
        return
    current = recipients.get(rid) or {
        "recipient_id": rid,
        "name": name,
        "uei": str(row.get("uei") or "").upper(),
        "amount": 0,
        "tags": [],
    }
    current["name"] = name
    current["uei"] = str(row.get("uei") or current.get("uei") or "").upper()
    current["amount"] = rd.dollars(row.get("amount"))
    tags = set(current.get("tags") or [])
    if tag:
        tags.add(tag)
    current["tags"] = tags_from_types([], list(tags))
    recipients[rid] = current


def advance_streams(recipients: dict, cursors: dict) -> None:
    for stream, type_name, pages, max_page in STREAMS:
        done = int(cursors.get(stream) or 0)
        # Page 1 is refreshed every run so dollar ranks stay current.
        targets = [1]
        for page in range(done + 1, min(done + pages, max_page) + 1):
            if page not in targets:
                targets.append(page)
        tag = STREAM_TAGS.get(stream)
        log(f"Leaderboard {stream}: pages {targets[0]}–{targets[-1]}")
        advanced = done
        for page in targets:
            try:
                rows = fetch_recipient_page(type_name, page)
            except Exception as exc:  # noqa: BLE001
                log(f"  {stream} page {page} failed: {exc}")
                break
            if not rows:
                log(f"  {stream} page {page} empty")
                break
            for row in rows:
                merge_recipient(recipients, row, tag)
            if page > advanced:
                advanced = page
            log(f"  {stream} page {page}: {len(rows)} rows, index {len(recipients)}")
        cursors[stream] = advanced


def map_award(row: dict[str, Any]) -> dict[str, Any] | None:
    amount = rd.dollars(row.get("Award Amount"))
    if amount < 250_000:
        return None
    end = ""
    for key in ("End Date", "Last Date to Order"):
        day = rd.parse_day(row.get(key))
        if day:
            end = day.isoformat()
            break
    generated = str(row.get("generated_internal_id") or "")
    raw_desc = str(row.get("Description") or "")
    description = rd.strip_html(raw_desc, 220)
    if len(description) < 12 or rd.looks_corrupt(raw_desc) or rd.looks_corrupt(description):
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
        "pop_state": norm_state(row.get("Place of Performance State Code")),
        "usaspending_url": f"https://www.usaspending.gov/award/{generated}" if generated else "",
    }


def fetch_awards(name: str) -> list[dict[str, Any]]:
    payload = ud.request_json(
        f"{ud.USA}/api/v2/search/spending_by_award/",
        {
            "limit": AWARD_LIMIT,
            "page": 1,
            "sort": "Award Amount",
            "order": "desc",
            "filters": {
                "award_type_codes": ["A", "C", "D"],
                "time_period": [{"start_date": AWARD_START, "end_date": AWARD_END, "date_type": "action_date"}],
                "award_amounts": [{"lower_bound": 250_000, "upper_bound": 90_000_000_000}],
                "recipient_search_text": [name],
            },
            "fields": AWARD_FIELDS,
        },
        timeout=50,
        attempts=2,
    )
    return list(payload.get("results") or [])


def build_profile(raw: dict[str, Any]) -> dict[str, Any]:
    name = raw["name"]
    uei = raw.get("uei") or ""
    rid = raw["recipient_id"]
    awards: list[dict[str, Any]] = []
    try:
        selected = rd.select_awards(name, uei, fetch_awards(name))
        seen: set[str] = set()
        for row in selected:
            mapped = map_award(row)
            if not mapped or mapped["generated_id"] in seen:
                continue
            seen.add(mapped["generated_id"])
            awards.append(mapped)
    except Exception as exc:  # noqa: BLE001
        log(f"  awards skipped for {name}: {exc}")
    profile = {}
    try:
        profile = ud.fetch_recipient(rid)
    except Exception as exc:  # noqa: BLE001
        log(f"  profile skipped for {name}: {exc}")
    types = list(profile.get("business_types") or [])
    tags = tags_from_types(types, raw.get("tags") or [])
    location = ud.location_of(profile) if profile else {"line": "", "city": "", "state": "", "zip": "", "country": ""}
    agencies: dict[str, dict[str, Any]] = {}
    for award in awards:
        agency_name = award.get("agency") or ""
        if not agency_name:
            continue
        bucket = agencies.setdefault(agency_name, {"name": agency_name, "slug": award.get("agency_slug") or "", "amount": 0})
        bucket["amount"] += award["amount"]
    pop_states = sorted({award["pop_state"] for award in awards if award.get("pop_state")})
    return {
        "slug": "",
        "name": profile.get("name") or name,
        "uei": (profile.get("uei") or uei or "").upper(),
        "recipient_id": rid,
        "parent_name": profile.get("parent_name") or "",
        "location": location,
        "business_types": rd.business_chips(types),
        "small_business": "small" in tags,
        "tags": tags,
        "pop_states": pop_states,
        "total_obligations": rd.dollars(raw.get("amount")),
        "profiled": True,
        "naics": [],
        "agencies": sorted(agencies.values(), key=lambda item: item["amount"], reverse=True)[:6],
        "awards": sorted(awards, key=lambda item: item["amount"], reverse=True),
        "usaspending_url": f"https://www.usaspending.gov/recipient/{rid}/latest",
        "next_recompete": None,
    }


def profile_batch(recipients: dict, profiles: dict) -> tuple[int, int]:
    have = len(profiles)
    room = max(0, PROFILE_CAP - have)
    batch = min(PROFILE_BATCH, room)
    if batch <= 0:
        log(f"Profile cap {PROFILE_CAP} already met ({have})")
        return 0, 0
    queue = rd.select_cohort(
        [row for row in recipients.values() if row["recipient_id"] not in profiles],
        batch,
        0.45,
    )
    if not queue:
        log("No unprofiled recipients in the index")
        return 0, 0
    log(f"Profiling {len(queue)} contractors with {WORKERS} workers ({have} already on disk)")
    done = 0
    failed = 0
    started = time.time()

    def _one(raw: dict[str, Any]) -> dict[str, Any] | None:
        t0 = time.time()
        profile = build_profile(raw)
        log(f"  {profile['name']} · {len(profile['awards'])} awards · {time.time() - t0:.1f}s")
        return profile

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(_one, raw) for raw in queue]
        for future in as_completed(futures):
            try:
                profile = future.result()
            except Exception as exc:  # noqa: BLE001
                failed += 1
                log(f"  failed: {exc}")
                continue
            if not profile:
                failed += 1
                continue
            profiles[profile["recipient_id"]] = profile
            done += 1
            if done % 40 == 0:
                save_cache("profiles.json", {"by_id": profiles})
                log(f"  checkpoint {done}/{len(queue)} in {time.time() - started:.0f}s")
    save_cache("profiles.json", {"by_id": profiles})
    log(f"Profiled {done} this run, {failed} failures, {len(profiles)} total")
    return done, failed


def assign_slugs(profiles: list[dict[str, Any]]) -> None:
    used: set[str] = set()
    for profile in profiles:
        if profile.get("slug") and profile["slug"] not in used:
            used.add(profile["slug"])
            continue
        profile["slug"] = rd.unique_slug(profile.get("name") or "", profile.get("uei") or profile.get("recipient_id") or "", used)


def attach_next(profile: dict[str, Any]) -> None:
    upcoming = []
    for award in profile.get("awards") or []:
        if rd.in_recompete_window(award.get("end") or "", award.get("amount") or 0, TODAY, HORIZON_DAYS, RECOMPETE_MIN, 0):
            upcoming.append(award)
    upcoming.sort(key=lambda award: award.get("end") or "9999")
    profile["next_recompete"] = (
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


def recompete_row(profile: dict[str, Any], award: dict[str, Any]) -> dict[str, Any]:
    end = rd.parse_day(award.get("end"))
    days = rd.days_between(end, TODAY)
    state = award.get("pop_state") or norm_state((profile.get("location") or {}).get("state"))
    return {
        "award_id": award.get("id") or "",
        "generated_id": award.get("generated_id") or "",
        "slug": profile.get("slug") or "",
        "incumbent": profile.get("name") or "",
        "uei": profile.get("uei") or "",
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
        "set_aside_bucket": (profile.get("tags") or ["open"])[0] if profile.get("tags") else "",
        "tags": profile.get("tags") or [],
        "state": state,
        "extent_competed": award.get("extent_competed") or "",
        "psc": award.get("psc") or "",
        "usaspending_url": award.get("usaspending_url") or "",
    }


def ref_of(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": profile.get("name") or "",
        "slug": profile.get("slug") or "",
        "uei": profile.get("uei") or "",
        "recipient_id": profile.get("recipient_id") or "",
        "amount": profile.get("total_obligations") or 0,
        "usaspending_url": profile.get("usaspending_url") or "",
        "state": norm_state((profile.get("location") or {}).get("state")),
        "tags": profile.get("tags") or [],
    }


def slim_index(profile: dict[str, Any] | None, raw: dict[str, Any]) -> dict[str, Any]:
    location = (profile or {}).get("location") or {}
    agencies = (profile or {}).get("agencies") or []
    return {
        "slug": (profile or {}).get("slug") or "",
        "name": (profile or {}).get("name") or raw.get("name") or "",
        "uei": (profile or {}).get("uei") or raw.get("uei") or "",
        "recipient_id": raw.get("recipient_id") or "",
        "state": norm_state(location.get("state")),
        "amount": (profile or {}).get("total_obligations") or raw.get("amount") or 0,
        "profiled": bool(profile),
        "small_business": "small" in ((profile or {}).get("tags") or raw.get("tags") or []),
        "tags": (profile or {}).get("tags") or raw.get("tags") or [],
        "top_naics": "",
        "top_naics_code": "",
        "top_agency": agencies[0]["name"] if agencies else "",
        "usaspending_url": (profile or {}).get("usaspending_url") or (
            f"https://www.usaspending.gov/recipient/{raw.get('recipient_id')}/latest" if raw.get("recipient_id") else ""
        ),
    }


def publish(profiles_by_id: dict, recipients: dict, notices: dict, failures: int, sam_status: dict) -> dict[str, int]:
    profiles = ud.merge_profiles(list(profiles_by_id.values()))
    if len(profiles) > PROFILE_CAP:
        profiles = sorted(profiles, key=lambda item: item.get("total_obligations") or 0, reverse=True)[:PROFILE_CAP]
    assign_slugs(profiles)
    for profile in profiles:
        attach_next(profile)
        for award in profile.get("awards") or []:
            award.pop("recipient_name", None)
            award.pop("uei", None)

    # Write slugs back so the next run keeps them.
    slug_by_id = {profile["recipient_id"]: profile for profile in profiles if profile.get("recipient_id")}
    for rid, profile in slug_by_id.items():
        profiles_by_id[rid] = profile

    recompetes = []
    seen: set[str] = set()
    for profile in profiles:
        for award in profile.get("awards") or []:
            if not rd.in_recompete_window(award.get("end") or "", award.get("amount") or 0, TODAY, HORIZON_DAYS, RECOMPETE_MIN, PAST_DAYS):
                continue
            key = award.get("generated_id") or f"{profile.get('slug')}-{award.get('id')}"
            if key in seen:
                continue
            seen.add(key)
            recompetes.append(recompete_row(profile, award))
    recompetes.sort(key=lambda item: (item["days"] < 0, item["days"], -item["amount"]))
    recompetes = recompetes[:RECOMPETE_CAP]

    ranked_recipients = sorted(recipients.values(), key=lambda row: row.get("amount") or 0, reverse=True)[:INDEX_CAP]
    profile_ids = {profile["recipient_id"] for profile in profiles}
    index_rows = []
    for raw in ranked_recipients:
        profile = slug_by_id.get(raw["recipient_id"]) if raw["recipient_id"] in profile_ids else None
        # A merged-away duplicate id should not look profiled.
        if profile is None and raw["recipient_id"] in profiles_by_id:
            continue
        index_rows.append(slim_index(profile, raw))

    notice_rows = sorted(notices.values(), key=lambda item: item.get("posted_at") or item.get("posted") or "", reverse=True)[:NOTICE_CAP]

    agencies = refresh_categories("awarding_agency", "agency")
    naics_pages = refresh_categories("naics", "naics")
    fill_leaders(agencies, "agency", profiles)
    fill_leaders(naics_pages, "naics", profiles)
    attach_recompetes(agencies, recompetes, "agency_slug")
    attach_recompetes(naics_pages, [row for row in recompetes if row.get("naics")], "naics")

    states = build_states(profiles, recompetes)
    set_asides = build_set_asides(profiles, recompetes, notice_rows)
    highlights = build_highlights(profiles, recompetes, notice_rows, agencies, states, set_asides)

    compact(DATA / "contractors.json", {"contractors": profiles})
    compact(DATA / "recompetes.json", {"recompetes": recompetes})
    compact(DATA / "index.json", {
        "contractors": index_rows,
        "agencies": [{"slug": item["slug"], "name": item["name"], "amount": item["amount"], "code": item.get("code") or ""} for item in agencies],
        "naics": [{"code": item["code"], "name": item["name"], "amount": item["amount"], "sector": item.get("sector_name") or ""} for item in naics_pages],
    })
    compact(DATA / "opportunities.json", {"opportunities": notice_rows})
    compact(DATA / "agencies.json", {"agencies": agencies})
    compact(DATA / "naics.json", {"naics": naics_pages})
    compact(DATA / "states.json", {"states": states})
    compact(DATA / "setasides.json", {"set_asides": set_asides})
    ud.write_json(DATA / "highlights.json", highlights)

    counts = {
        "profiled": len(profiles),
        "searchable": len(index_rows),
        "recompetes": len([row for row in recompetes if row["days"] >= 0]),
        "recompetes_all": len(recompetes),
        "states": len(states),
        "notices": len(notice_rows),
    }
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "labels": {
            "obligations_window": rd.format_window(OBLIGATION_START, OBLIGATION_END),
            "awards_since": "Oct 1, 2019",
            "recompete_horizon": rd.horizon_label(HORIZON_DAYS),
            "recompete_horizon_days": HORIZON_DAYS,
            "recompete_min": RECOMPETE_MIN,
            "past_days": PAST_DAYS,
        },
        "counts": counts,
        "methodology": {
            "contractors": "Pre-rendered pages are a mix of the largest primes and socioeconomic firms (small business, 8(a), SDVOSB, WOSB, HUBZone). Everyone else in the index is searchable and links to USAspending.",
            "awards": "Up to eight of each profiled contractor's largest definitive contracts, delivery orders, and BPA calls with an action since Oct 1, 2019.",
            "recompetes": "Those awards with at least $1 million obligated and a current end date inside 18 months. Place of performance is the award's reported state, otherwise the contractor's address.",
            "opportunities": "Active SAM.gov notices, merged forward each day and capped so the file stays small.",
        },
        "sources": {
            "usaspending": {
                "ok": True,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
                "kept_previous": False,
                "contractors": counts["profiled"],
                "searchable": counts["searchable"],
                "recompetes": counts["recompetes"],
                "failures": failures,
            },
            "sam": sam_status,
        },
    }
    ud.write_json(DATA / "meta.json", meta)
    save_cache("profiles.json", {"by_id": profiles_by_id})
    return counts


def refresh_categories(category: str, kind: str) -> list[dict[str, Any]]:
    try:
        rows = ud.fetch_category(category, ud.obligation_filters(), 28 if kind == "naics" else 16)
    except Exception as exc:  # noqa: BLE001
        log(f"{category} leaderboard failed, keeping previous if present: {exc}")
        previous = ud.load_json(DATA / ("naics.json" if kind == "naics" else "agencies.json")) or {}
        key = "naics" if kind == "naics" else "agencies"
        return list(previous.get(key) or [])
    published = []
    if kind == "agency":
        for row in rows:
            name = row.get("name") or ""
            if not name:
                continue
            slug = row.get("agency_slug") or rd.slugify(name)
            published.append({
                "slug": slug,
                "name": name,
                "code": row.get("code") or "",
                "amount": rd.dollars(row.get("amount")),
                "contractors": [],
                "recompetes": [],
                "usaspending_url": f"https://www.usaspending.gov/agency/{slug}" if row.get("agency_slug") else "",
            })
        return published
    for row in rows:
        code = rd.naics_code(row.get("code"))
        if not code:
            continue
        sector_code, sector_name = rd.sector_for(code)
        published.append({
            "code": code,
            "name": row.get("name") or f"NAICS {code}",
            "sector_code": sector_code,
            "sector_name": sector_name,
            "amount": rd.dollars(row.get("amount")),
            "contractors": [],
            "recompetes": [],
        })
    return published


def fill_leaders(pages: list[dict], kind: str, profiles: list[dict]) -> None:
    by_name = {rd.normalize_name(profile.get("name") or ""): profile for profile in profiles}

    def link(row: dict) -> dict:
        profile = by_name.get(rd.normalize_name(row.get("name") or ""))
        rid = str(row.get("recipient_id") or "")
        return {
            "name": row.get("name") or "",
            "slug": profile["slug"] if profile else "",
            "uei": str(row.get("uei") or "").upper(),
            "recipient_id": rid,
            "amount": rd.dollars(row.get("amount")),
            "usaspending_url": f"https://www.usaspending.gov/recipient/{rid}/latest" if rid else "",
        }

    def one(page: dict) -> None:
        try:
            if kind == "agency":
                filters = ud.obligation_filters(agencies=[{"type": "awarding", "tier": "toptier", "name": page["name"]}])
            else:
                filters = ud.obligation_filters(naics_codes={"require": [page["code"]]})
            rows = ud.fetch_category("recipient", filters, 8)
            page["contractors"] = [link(row) for row in rows if rd.is_usable_name(row.get("name"))]
        except Exception as exc:  # noqa: BLE001
            log(f"  leaders skipped for {page.get('name') or page.get('code')}: {exc}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(one, pages))


def attach_recompetes(pages: list[dict], recompetes: list[dict], key: str) -> None:
    grouped: dict[str, list[dict]] = {}
    for row in recompetes:
        if row.get("days", 0) < 0:
            continue
        bucket = row.get(key) or ""
        if bucket:
            grouped.setdefault(bucket, []).append(row)
    for page in pages:
        ident = page.get("slug") or page.get("code") or ""
        page["recompetes"] = [
            {
                "description": row["description"],
                "slug": row["slug"],
                "incumbent": row["incumbent"],
                "amount": row["amount"],
                "end": row["end"],
                "days": row["days"],
                "agency": row["agency"],
            }
            for row in (grouped.get(ident) or [])[:12]
        ]


def build_states(profiles: list[dict], recompetes: list[dict]) -> list[dict[str, Any]]:
    by_state: dict[str, dict[str, Any]] = {}

    def bucket(code: str) -> dict[str, Any]:
        return by_state.setdefault(code, {"contractors": {}, "recompetes": [], "obligation": 0})

    for profile in profiles:
        codes = set(profile.get("pop_states") or [])
        hq = norm_state((profile.get("location") or {}).get("state"))
        if hq:
            codes.add(hq)
        for code in codes:
            if code not in STATES:
                continue
            entry = bucket(code)
            entry["contractors"][profile["slug"]] = profile
            if hq == code:
                entry["obligation"] += profile.get("total_obligations") or 0
    for row in recompetes:
        if row.get("days", 0) < 0:
            continue
        code = row.get("state") or ""
        if code in STATES:
            bucket(code)["recompetes"].append(row)
    pages = []
    for code, entry in by_state.items():
        contractors = sorted(entry["contractors"].values(), key=lambda item: item.get("total_obligations") or 0, reverse=True)
        rows = sorted(entry["recompetes"], key=lambda item: (item["days"], -item["amount"]))
        if not contractors and not rows:
            continue
        pages.append({
            "code": code,
            "name": STATES[code],
            "obligation": entry["obligation"],
            "contractor_count": len(contractors),
            "recompete_count": len(rows),
            "contractors": [ref_of(profile) for profile in contractors[:30]],
            "recompetes": [
                {
                    "description": row["description"],
                    "slug": row["slug"],
                    "incumbent": row["incumbent"],
                    "amount": row["amount"],
                    "end": row["end"],
                    "days": row["days"],
                    "agency": row["agency"],
                }
                for row in rows[:24]
            ],
        })
    pages.sort(key=lambda item: item["recompete_count"], reverse=True)
    return pages


def build_set_asides(profiles: list[dict], recompetes: list[dict], notices: list[dict]) -> list[dict[str, Any]]:
    pages = []
    for ident, label, lede in SET_ASIDES:
        firms = [profile for profile in profiles if ident in (profile.get("tags") or [])]
        firms.sort(key=lambda item: item.get("total_obligations") or 0, reverse=True)
        slugs = {profile["slug"] for profile in firms}
        rows = [row for row in recompetes if row.get("days", 0) >= 0 and (ident in (row.get("tags") or []) or row.get("slug") in slugs)]
        rows.sort(key=lambda item: (item["days"], -item["amount"]))
        notes = [note for note in notices if note.get("set_aside_bucket") == ident or (ident == "small" and note.get("set_aside_bucket") in {"small", "8a", "sdvosb", "wosb", "hubzone", "edwosb"})]
        pages.append({
            "id": ident,
            "label": label,
            "lede": lede,
            "contractor_count": len(firms),
            "recompete_count": len(rows),
            "notice_count": len(notes),
            "obligation": sum(profile.get("total_obligations") or 0 for profile in firms),
            "contractors": [ref_of(profile) for profile in firms[:36]],
            "recompetes": [
                {
                    "description": row["description"],
                    "slug": row["slug"],
                    "incumbent": row["incumbent"],
                    "amount": row["amount"],
                    "end": row["end"],
                    "days": row["days"],
                    "agency": row["agency"],
                    "state": row.get("state") or "",
                }
                for row in rows[:24]
            ],
            "notices": [
                {"title": note["title"], "agency": note["agency"], "posted": note.get("posted") or "", "link": note["link"], "type": note.get("type") or ""}
                for note in notes[:12]
            ],
        })
    return pages


def build_highlights(profiles, recompetes, notices, agencies, states, set_asides) -> dict[str, Any]:
    upcoming = [row for row in recompetes if row["days"] >= 0]
    hero = [row for row in upcoming if row["amount"] >= 10_000_000][:3] or upcoming[:3]
    featured = sorted(profiles, key=lambda item: item.get("total_obligations") or 0, reverse=True)
    socio = [profile for profile in profiles if profile.get("tags")]
    mix = []
    for profile in featured[:3] + socio[:3]:
        if profile["slug"] not in {item["slug"] for item in mix}:
            mix.append(profile)
    open_types = {"Solicitation", "Presolicitation", "Sources Sought", "Combined Synopsis/Solicitation", "Special Notice"}
    open_notices = [note for note in notices if note.get("type") in open_types][:5]
    return {
        "hero": hero,
        "radar": upcoming[:8],
        "contractors": [ref_of(profile) for profile in mix[:6]],
        "notices": open_notices,
        "agencies": [{"slug": item["slug"], "name": item["name"], "amount": item["amount"]} for item in agencies[:6]],
        "states": [{"code": item["code"], "name": item["name"], "recompete_count": item["recompete_count"], "contractor_count": item["contractor_count"]} for item in states[:8]],
        "set_asides": [{"id": item["id"], "label": item["label"], "contractor_count": item["contractor_count"], "recompete_count": item["recompete_count"]} for item in set_asides],
    }


def merge_notices(notices: dict) -> dict[str, Any]:
    ud.SAM_KEEP = 900
    ud.SAM_WINDOW_DAYS = 40
    ud.SAM_SCAN_MAX = 15000
    try:
        fresh = ud.fetch_sam()
    except Exception as exc:  # noqa: BLE001
        log(f"SAM.gov failed, keeping {len(notices)} cached notices: {exc}")
        return {
            "ok": False,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
            "kept_previous": True,
            "notices": len(notices),
            "extract_modified": None,
        }
    added = 0
    for notice in fresh.get("opportunities") or []:
        if notice["id"] not in notices:
            added += 1
        notices[notice["id"]] = notice
    # Drop the oldest past the cap.
    if len(notices) > NOTICE_CAP:
        ordered = sorted(notices.values(), key=lambda item: item.get("posted_at") or "", reverse=True)[:NOTICE_CAP]
        notices.clear()
        notices.update({item["id"]: item for item in ordered})
    log(f"SAM.gov merged {added} new notices, {len(notices)} stored")
    return {
        "ok": True,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "error": None,
        "kept_previous": False,
        "notices": len(notices),
        "extract_modified": fresh.get("modified"),
    }


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    recipient_cache = load_cache("recipients.json", {"by_id": {}, "streams": {}})
    profile_cache = load_cache("profiles.json", {"by_id": {}})
    notice_cache = load_cache("notices.json", {"by_id": {}})
    recipients: dict = recipient_cache.get("by_id") or {}
    profiles: dict = profile_cache.get("by_id") or {}
    notices: dict = notice_cache.get("by_id") or {}
    cursors: dict = recipient_cache.get("streams") or {}
    seed_from_published(recipients, profiles, notices)
    log(f"Cache: {len(recipients)} recipients, {len(profiles)} profiles, {len(notices)} notices")

    failures = 0
    sam_status: dict[str, Any] = {
        "ok": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "error": "not run",
        "kept_previous": True,
        "notices": len(notices),
    }
    try:
        advance_streams(recipients, cursors)
        save_cache("recipients.json", {"by_id": recipients, "streams": cursors})
        done, failures = profile_batch(recipients, profiles)
        save_cache("profiles.json", {"by_id": profiles})
        sam_status = merge_notices(notices)
        save_cache("notices.json", {"by_id": notices, "extract_modified": sam_status.get("extract_modified")})
        counts = publish(profiles, recipients, notices, failures, sam_status)
        log("Published " + json.dumps(counts))
    except Exception:
        log("Incremental update failed. Publishing whatever is already cached.")
        log(traceback.format_exc())
        if profiles:
            try:
                counts = publish(profiles, recipients, notices, failures, sam_status)
                log("Published from cache " + json.dumps(counts))
            except Exception:
                log(traceback.format_exc())
                return 1
        elif not (DATA / "contractors.json").exists():
            return 1
    return 0 if (DATA / "contractors.json").exists() and (DATA / "opportunities.json").exists() else 1


if __name__ == "__main__":
    sys.exit(main())
