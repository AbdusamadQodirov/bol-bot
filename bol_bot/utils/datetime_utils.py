"""Date/time detection, parsing, and format-preserving regeneration.

Ported from the original BOL bot with the following improvements:
- New patterns: ``Arrival: 1345``, ``Dep 0815`` for compact HHMM
- Stricter ``_IN_KEYWORDS`` (word-boundary, not substring " in")
- Public ``looks_like_time_in_label`` / ``looks_like_time_out_label`` helpers
- Pickup-group keyword set unified here
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class TimeMatch:
    """One date/time occurrence located inside a document text blob."""

    raw_text: str
    start: int
    end: int
    has_date: bool
    has_time: bool
    has_seconds: bool
    has_ampm: bool
    date_style: str
    month_style: Optional[str]
    sep_date: str
    sep_time: str
    upper_ampm: bool
    is_range: bool = False
    range_end_hour: Optional[int] = None
    range_end_minute: Optional[int] = None


_MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]
_MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
                 "Aug", "Sep", "Oct", "Nov", "Dec"]
_MONTH_TO_NUM = {m.lower(): i + 1 for i, m in enumerate(_MONTHS_LONG)}
_MONTH_TO_NUM.update({m.lower(): i + 1 for i, m in enumerate(_MONTHS_SHORT)})


# ---------------------------------------------------------------------------
# Field-label classification helpers
# ---------------------------------------------------------------------------

# A label is "Time Out / departure" if any of these tokens appear.
# Tokens compared after lower-casing; uses word boundaries where ambiguous.
_OUT_REGEXES = [
    re.compile(r"\btime\s*out\b", re.IGNORECASE),
    re.compile(r"\bdeparture\b", re.IGNORECASE),
    re.compile(r"\bdepart\b", re.IGNORECASE),
    re.compile(r"\bdep\b", re.IGNORECASE),
    re.compile(r"\bpickup\b", re.IGNORECASE),
    re.compile(r"\bout\b(?!\s*of)", re.IGNORECASE),  # avoid "out of"
]
_IN_REGEXES = [
    re.compile(r"\btime\s*in\b", re.IGNORECASE),
    re.compile(r"\barrival\b", re.IGNORECASE),
    re.compile(r"\barriv(ed|al)?\b", re.IGNORECASE),
    re.compile(r"\barr\b", re.IGNORECASE),
    re.compile(r"\bcheck[\s-]?in\b", re.IGNORECASE),
    # Bare "in" only at start of a short label, not inside random words
    re.compile(r"^\s*in\s*:", re.IGNORECASE),
]

# Pickup-group: same physical pickup event labelled multiple ways in the form.
_PICKUP_GROUP_REGEXES = [
    re.compile(r"\bship\s*date\b", re.IGNORECASE),
    re.compile(r"\borigin\b", re.IGNORECASE),
    re.compile(r"\bshipper\s*signature\b", re.IGNORECASE),
    re.compile(r"\bsignature\b", re.IGNORECASE),
    re.compile(r"\bpickup\b", re.IGNORECASE),
    re.compile(r"\bpu\s*#\b", re.IGNORECASE),
    re.compile(r"\bpu\s*date\b", re.IGNORECASE),
    re.compile(r"\bp/u\b", re.IGNORECASE),
]


def looks_like_time_in_label(context: str) -> bool:
    return any(r.search(context or "") for r in _IN_REGEXES)


def looks_like_time_out_label(context: str) -> bool:
    return any(r.search(context or "") for r in _OUT_REGEXES)


def looks_like_pickup_group_label(context: str) -> bool:
    return any(r.search(context or "") for r in _PICKUP_GROUP_REGEXES)


# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

_PATTERNS = [
    # 0) MM/DD/YYYY HH:MM-HH:MM (time RANGE)
    (re.compile(
        r'(?P<date>\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})'
        r'(?P<sep>[ ,]+)'
        r'(?P<time>\d{1,2}:\d{2}(:\d{2})?)'
        r'(?P<ampm1>\s*[AaPp]\.?[Mm]\.?)?'
        r'\s*-\s*'
        r'(?P<time_end>\d{1,2}:\d{2}(:\d{2})?)'
        r'(?P<ampm>\s*[AaPp]\.?[Mm]\.?)?'
    ), "mdy_slash_range", None),

    # 1) YYYY-MM-DD HH:MM[:SS] [AM/PM]
    (re.compile(
        r'(?P<date>\d{4}-\d{2}-\d{2})'
        r'(?P<sep>[ T,]+)'
        r'(?P<time>\d{1,2}:\d{2}(:\d{2})?)'
        r'(?P<ampm>\s*[AaPp]\.?[Mm]\.?)?'
    ), "iso", None),

    # 2) DD-Mon-YY HH:MM[:SS]
    (re.compile(
        r'(?P<date>\d{1,2}-(' + '|'.join(_MONTHS_SHORT) + r')-\d{2,4})'
        r'(?P<sep>[ ,]+)'
        r'(?P<time>\d{1,2}:\d{2}(:\d{2})?)'
        r'(?P<ampm>\s*[AaPp]\.?[Mm]\.?)?'
    ), "dmy_dash_month", None),

    # 3) MM/DD/YYYY HH:MM[:SS] [AM/PM]
    (re.compile(
        r'(?P<date>\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})'
        r'(?P<sep>[ ,]+)'
        r'(?P<time>\d{1,2}:\d{2}(:\d{2})?)'
        r'(?P<ampm>\s*[AaPp]\.?[Mm]\.?)?'
    ), "mdy_slash", None),

    # 4) Month DD, YYYY HH:MM[:SS] [AM/PM]
    (re.compile(
        r'(?P<date>(' + '|'.join(_MONTHS_LONG + _MONTHS_SHORT) + r')\.?\s+\d{1,2},?\s+\d{4})'
        r'(?P<sep>[ ,]+)'
        r'(?P<time>\d{1,2}:\d{2}(:\d{2})?)'
        r'(?P<ampm>\s*[AaPp]\.?[Mm]\.?)?'
    ), "month_name", None),

    # 5) Date-only
    (re.compile(
        r'(?P<date>(' + '|'.join(_MONTHS_LONG + _MONTHS_SHORT) + r')\.?\s+\d{1,2},?\s+\d{4})'
    ), "month_name_date_only", None),
    (re.compile(
        r'(?P<date>\d{1,2}-(' + '|'.join(_MONTHS_SHORT) + r')-\d{2,4})'
    ), "dmy_dash_month_date_only", None),
    (re.compile(
        r'(?P<date>\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})(?![ ,]*\d{1,2}:\d{2})'
    ), "mdy_slash_date_only", None),

    # 6) HH:MM[:SS] [AM/PM] only
    (re.compile(
        r'(?<!\d)(?P<time>\d{1,2}:\d{2}(:\d{2})?)(?P<ampm>\s*[AaPp]\.?[Mm]\.?)?(?!\d)'
    ), "time_only", None),

    # 7) Compact HHMM near a time-label keyword (Time/Arrival/Departure/Dep/Arr)
    #    Word boundary on both sides; 24-hour range 0000-2359.
    (re.compile(
        r'(?:\b(?:time|arrival|arr|departure|dep|check[\s-]?in|check[\s-]?out)\b'
        r'\s*(?:[Ii]n|[Oo]ut)?\s*[:\-]?\s*)'
        r'(?P<time>([01]\d|2[0-3])[0-5]\d)(?!\d)',
        re.IGNORECASE,
    ), "time_hhmm_compact", None),
]


def find_datetime_candidates(text: str) -> List[TimeMatch]:
    """Return non-overlapping date/time candidates in priority order."""
    found: List[TimeMatch] = []
    occupied = [False] * len(text)

    for pattern, date_style, _ in _PATTERNS:
        for m in pattern.finditer(text):
            s, e = m.start(), m.end()
            if any(occupied[s:e]):
                continue

            gd = m.groupdict()
            date_text = gd.get("date")
            time_text = gd.get("time")
            ampm_raw = gd.get("ampm")

            has_date = date_text is not None
            has_time = time_text is not None
            has_ampm = bool(ampm_raw and ampm_raw.strip())
            has_seconds = bool(time_text and time_text.count(":") == 2)

            month_style = None
            if date_style in ("month_name", "month_name_date_only") and date_text:
                first_word = re.split(r'\s+', date_text.strip())[0].rstrip('.')
                month_style = "long" if first_word in _MONTHS_LONG else "short"
            elif date_style in ("dmy_dash_month", "dmy_dash_month_date_only"):
                month_style = "short"

            sep_date = "/"
            if has_date and date_style in ("mdy_slash", "mdy_slash_date_only") and date_text:
                sep_date = "-" if "-" in date_text else "/"
            elif date_style == "iso":
                sep_date = "-"
            elif date_style in ("dmy_dash_month", "dmy_dash_month_date_only"):
                sep_date = "-"

            upper_ampm = bool(ampm_raw and ampm_raw.strip()[0].isupper())

            is_range = (date_style == "mdy_slash_range")
            range_end_hour = None
            range_end_minute = None
            if is_range:
                time_end_text = gd.get("time_end")
                if time_end_text:
                    eh, em = time_end_text.split(":")[:2]
                    range_end_hour = int(eh)
                    range_end_minute = int(em)

            if date_style == "time_hhmm_compact":
                t_start, t_end = m.span("time")
                out_raw_text = text[t_start:t_end]
                out_start, out_end = t_start, t_end
            else:
                out_raw_text = m.group(0)
                out_start, out_end = s, e

            found.append(TimeMatch(
                raw_text=out_raw_text,
                start=out_start, end=out_end,
                has_date=has_date,
                has_time=has_time,
                has_seconds=has_seconds,
                has_ampm=has_ampm,
                date_style=date_style,
                month_style=month_style,
                sep_date=sep_date,
                sep_time=":",
                upper_ampm=upper_ampm,
                is_range=is_range,
                range_end_hour=range_end_hour,
                range_end_minute=range_end_minute,
            ))
            for i in range(s, e):
                occupied[i] = True

    found.sort(key=lambda t: t.start)
    return found


# ---------------------------------------------------------------------------
# User-input parsing
# ---------------------------------------------------------------------------

_USER_INPUT_PATTERNS = [
    re.compile(
        r'(?P<month>' + '|'.join(_MONTHS_LONG + _MONTHS_SHORT) + r')\.?\s+'
        r'(?P<day>\d{1,2}),?\s*'
        r'(?P<year>\d{4})?,?\s*'
        r'(?P<hour>\d{1,2}):(?P<minute>\d{2})(:(?P<second>\d{2}))?'
        r'\s*(?P<ampm>[AaPp]\.?[Mm]\.?)?',
        re.IGNORECASE,
    ),
    re.compile(
        r'(?P<month_num>\d{1,2})[/\-](?P<day>\d{1,2})(?:[/\-](?P<year>\d{2,4}))?'
        r'[ ,]+'
        r'(?P<hour>\d{1,2}):(?P<minute>\d{2})(:(?P<second>\d{2}))?'
        r'\s*(?P<ampm>[AaPp]\.?[Mm]\.?)?'
    ),
]


def parse_user_input(text: str, fallback_year: Optional[int] = None) -> Optional[datetime]:
    text = text.strip()
    for pat in _USER_INPUT_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        gd = m.groupdict()

        if gd.get("month"):
            month = _MONTH_TO_NUM.get(gd["month"].lower())
        elif gd.get("month_num"):
            month = int(gd["month_num"])
        else:
            continue
        if not month:
            continue

        day = int(gd["day"])
        year = int(gd["year"]) if gd.get("year") else fallback_year
        if year is None:
            return None
        if year < 100:
            year += 2000

        hour = int(gd["hour"])
        minute = int(gd["minute"])
        second = int(gd["second"]) if gd.get("second") else 0

        ampm = (gd.get("ampm") or "").lower().replace(".", "")
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0

        try:
            return datetime(year, month, day, hour, minute, second)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Format-preserving regeneration
# ---------------------------------------------------------------------------

def format_like_original(dt: datetime, tm: TimeMatch) -> str:
    """Render ``dt`` in the same shape as the originally-matched text."""

    def build_time_str() -> str:
        if tm.date_style == "time_hhmm_compact":
            return f"{dt.hour:02d}{dt.minute:02d}"
        if tm.has_ampm:
            hour12 = dt.hour % 12 or 12
            s = f"{hour12}:{dt.minute:02d}"
            if tm.has_seconds:
                s += f":{dt.second:02d}"
            ampm_str = "PM" if dt.hour >= 12 else "AM"
            if not tm.upper_ampm:
                ampm_str = ampm_str.lower()
            s += f" {ampm_str}"
        else:
            s = f"{dt.hour:02d}:{dt.minute:02d}"
            if tm.has_seconds:
                s += f":{dt.second:02d}"
        return s

    def build_date_str() -> str:
        if tm.date_style in ("mdy_slash", "mdy_slash_date_only"):
            sep = tm.sep_date
            parts = re.split(r'[/\-]', tm.raw_text.split()[0]) if tm.raw_text else []
            year_part = str(dt.year)
            if len(parts) == 3 and len(parts[2]) == 2:
                year_part = str(dt.year)[-2:]
            return f"{dt.month:02d}{sep}{dt.day:02d}{sep}{year_part}"
        elif tm.date_style == "iso":
            return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
        elif tm.date_style in ("dmy_dash_month", "dmy_dash_month_date_only"):
            month_name = _MONTHS_SHORT[dt.month - 1]
            parts = tm.raw_text.split()[0].split("-") if tm.raw_text else []
            year_part = str(dt.year)
            if len(parts) == 3 and len(parts[2]) == 2:
                year_part = str(dt.year)[-2:]
            return f"{dt.day}-{month_name}-{year_part}"
        elif tm.date_style in ("month_name", "month_name_date_only"):
            month_name = (_MONTHS_LONG[dt.month - 1] if tm.month_style == "long"
                          else _MONTHS_SHORT[dt.month - 1])
            has_comma = "," in tm.raw_text
            return (f"{month_name} {dt.day}, {dt.year}" if has_comma
                    else f"{month_name} {dt.day} {dt.year}")
        return dt.strftime("%m/%d/%Y")

    if tm.date_style in ("mdy_slash_date_only", "month_name_date_only",
                          "dmy_dash_month_date_only"):
        return build_date_str()

    if tm.date_style in ("time_only", "time_hhmm_compact") or not tm.has_date:
        return build_time_str()

    if tm.is_range and tm.range_end_hour is not None:
        old_start_match = re.search(r'(\d{1,2}):(\d{2})', tm.raw_text)
        if old_start_match:
            old_start_h = int(old_start_match.group(1))
            old_start_m = int(old_start_match.group(2))
            old_start_minutes = old_start_h * 60 + old_start_m
            old_end_minutes = tm.range_end_hour * 60 + tm.range_end_minute
            duration_minutes = (old_end_minutes - old_start_minutes) % (24 * 60)
        else:
            duration_minutes = 0

        new_start_total = dt.hour * 60 + dt.minute
        new_end_total = (new_start_total + duration_minutes) % (24 * 60)
        new_end_h, new_end_m = divmod(new_end_total, 60)

        return (f"{build_date_str()} "
                f"{dt.hour:02d}:{dt.minute:02d}-{new_end_h:02d}:{new_end_m:02d}")

    return f"{build_date_str()} {build_time_str()}"


def looks_like_amazon(full_text: str) -> bool:
    return bool(re.search(r'\bamazon\b', full_text, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Same-value matching across fields
# ---------------------------------------------------------------------------
# BOL forms routinely print the SAME moment under several labels — e.g. on a
# PS Form 5398-A the Actual Dep., Time Sealed and Date fields all carry
# "06/24 19:39" (the Date one with a year). When the user edits one of them,
# the others must move with it or the document contradicts itself.

_VALUE_TIME_RE = re.compile(
    r'(?<!\d)(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp]\.?[Mm]\.?)?'
)
_VALUE_DATE_RE = re.compile(r'(?<!\d)(\d{1,2})[/\-](\d{1,2})(?:[/\-]\d{2,4})?(?!\d)')


def extract_time_hm(raw: str) -> Optional[tuple]:
    """Pull the first HH:MM out of a raw field value, normalised to 24h."""
    m = _VALUE_TIME_RE.search(raw or "")
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    ampm = (m.group(3) or "").lower().replace(".", "")
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return (hour, minute)


def extract_date_md(raw: str) -> Optional[tuple]:
    """Pull the first plausible MM/DD (year optional) out of a raw value."""
    for m in _VALUE_DATE_RE.finditer(raw or ""):
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return (month, day)
    return None


def matches_datetime_value(chosen_raw: str, other_raw: str) -> bool:
    """True if ``other_raw`` denotes the same moment as ``chosen_raw``.

    Times must be equal; dates must be equal when both values carry one.
    A value missing its date (bare "19:39") still matches a dated twin
    ("06/24 19:39", "06/24/2026 19:39"). A date-only value only matches
    other date-only values — sharing a date with a timed field does NOT
    mean they are the same moment.
    """
    chosen_t, chosen_d = extract_time_hm(chosen_raw), extract_date_md(chosen_raw)
    other_t, other_d = extract_time_hm(other_raw), extract_date_md(other_raw)
    if chosen_t is None and chosen_d is None:
        return False
    if chosen_t is not None:
        if other_t != chosen_t:
            return False
        if chosen_d is not None and other_d is not None and chosen_d != other_d:
            return False
        return True
    return other_t is None and other_d is not None and other_d == chosen_d
