"""US state/city to time zone mapping + DST-aware conversion.

Ported from original timezone_utils.py with minor cleanup.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

TZ_ABBR_TO_IANA = {
    "EDT": "America/New_York",
    "EST": "America/New_York",
    "CDT": "America/Chicago",
    "CST": "America/Chicago",
    "MDT": "America/Denver",
    "MST": "America/Denver",
    "PDT": "America/Los_Angeles",
    "PST": "America/Los_Angeles",
}

_STATE_TO_IANA = {
    "AL": "America/Chicago", "AK": "America/Anchorage", "AZ": "America/Phoenix",
    "AR": "America/Chicago", "CA": "America/Los_Angeles", "CO": "America/Denver",
    "CT": "America/New_York", "DE": "America/New_York", "FL": "America/New_York",
    "GA": "America/New_York", "HI": "Pacific/Honolulu", "ID": "America/Boise",
    "IL": "America/Chicago", "IN": "America/Indiana/Indianapolis", "IA": "America/Chicago",
    "KS": "America/Chicago", "KY": "America/New_York", "LA": "America/Chicago",
    "ME": "America/New_York", "MD": "America/New_York", "MA": "America/New_York",
    "MI": "America/Detroit", "MN": "America/Chicago", "MS": "America/Chicago",
    "MO": "America/Chicago", "MT": "America/Denver", "NE": "America/Chicago",
    "NV": "America/Los_Angeles", "NH": "America/New_York", "NJ": "America/New_York",
    "NM": "America/Denver", "NY": "America/New_York", "NC": "America/New_York",
    "ND": "America/North_Dakota/Center", "OH": "America/New_York", "OK": "America/Chicago",
    "OR": "America/Los_Angeles", "PA": "America/New_York", "RI": "America/New_York",
    "SC": "America/New_York", "SD": "America/Chicago", "TN": "America/Chicago",
    "TX": "America/Chicago", "UT": "America/Denver", "VT": "America/New_York",
    "VA": "America/New_York", "WA": "America/Los_Angeles", "WV": "America/New_York",
    "WI": "America/Chicago", "WY": "America/Denver", "DC": "America/New_York",
}

_STATE_NAME_TO_CODE = {
    "minnesota": "MN", "texas": "TX", "tennessee": "TN", "california": "CA",
    "pennsylvania": "PA", "new york": "NY", "florida": "FL", "illinois": "IL",
    "north carolina": "NC", "saint paul": "MN", "dallas": "TX", "knoxville": "TN",
    "los angeles": "CA", "san francisco": "CA", "chicago": "IL", "houston": "TX",
    "phoenix": "AZ", "philadelphia": "PA", "san antonio": "TX", "san diego": "CA",
    "atlanta": "GA", "miami": "FL", "boston": "MA", "seattle": "WA", "denver": "CO",
    "memphis": "TN", "nashville": "TN", "milwaukee": "WI", "detroit": "MI",
}

_ORIGIN_LABELS = (
    "origin", "ship from", "shipper", "pickup", "pu#", "pu #",
    "shipper information", "from:",
)
_DESTINATION_LABELS = (
    "destination", "ship to", "consignee", "deliver to", "dropoff", "drop off",
)


def _extract_origin_section(text: str) -> str:
    lower = text.lower()
    origin_start = None
    for label in _ORIGIN_LABELS:
        idx = lower.find(label)
        if idx != -1 and (origin_start is None or idx < origin_start):
            origin_start = idx
    if origin_start is None:
        return text

    search_from = origin_start + 1
    dest_start = None
    for label in _DESTINATION_LABELS:
        idx = lower.find(label, search_from)
        if idx != -1 and (dest_start is None or idx < dest_start):
            dest_start = idx
    if dest_start is not None:
        return text[origin_start:dest_start]
    return text[origin_start:origin_start + 300]


def guess_state_code_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    section = _extract_origin_section(text)

    # Most reliable: "STATE ZIP"
    m = re.search(r'\b([A-Z]{2})\s+\d{5}(-\d{4})?\b', section)
    if m and m.group(1) in _STATE_TO_IANA:
        return m.group(1)

    # "(MN)" or ", MN"
    candidates = re.findall(r'\(([A-Z]{2})\)|,\s*([A-Z]{2})\b', section)
    for tup in candidates:
        code = tup[0] or tup[1]
        if code in _STATE_TO_IANA:
            return code

    lower_text = section.lower()
    for name, code in _STATE_NAME_TO_CODE.items():
        if name in lower_text:
            return code
    return None


def state_code_to_iana(code: str) -> Optional[str]:
    return _STATE_TO_IANA.get(code.upper())


def convert_between_timezones(dt: datetime, from_tz_abbr: str, to_iana: str) -> datetime:
    from_iana = TZ_ABBR_TO_IANA.get(from_tz_abbr.upper())
    if from_iana is None:
        raise ValueError(f"Unknown company time zone: {from_tz_abbr}")
    aware_dt = dt.replace(tzinfo=ZoneInfo(from_iana))
    converted = aware_dt.astimezone(ZoneInfo(to_iana))
    return converted.replace(tzinfo=None)


def iana_to_abbr(iana: str, reference_dt: Optional[datetime] = None) -> str:
    ref = reference_dt or datetime.now()
    aware = ref.replace(tzinfo=ZoneInfo(iana))
    return aware.strftime("%Z")
