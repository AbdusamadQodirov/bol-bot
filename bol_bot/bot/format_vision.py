"""Format-preserving regenerator for VISION-mode candidates.

(Text/OCR candidates use ``format_like_original`` from datetime_utils,
which has full TimeMatch info. Vision candidates only have raw_text,
so we infer the shape from that string here.)
"""
from __future__ import annotations

import re
from datetime import datetime

_MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
                 "Aug", "Sep", "Oct", "Nov", "Dec"]


def format_like_vision_text(old_raw: str, new_dt: datetime) -> str:
    old_raw = old_raw.strip()

    date_m = re.search(r'(\d{1,2})([/\-])(\d{1,2})[/\-](\d{2,4})', old_raw)
    date_mon_m = None
    date_md_m = None
    if not date_m:
        date_mon_m = re.search(
            r'(\d{1,2})-(' + '|'.join(_MONTHS_SHORT) + r')-(\d{2,4})',
            old_raw, re.IGNORECASE,
        )
        if not date_mon_m:
            # Year-less MM/DD ("06/24 19:39") — the usual shape on route
            # tickets like PS Form 5398-A. The ':' guards keep the dash of
            # a time range ("06:00-10:00") from parsing as a date.
            date_md_m = re.search(
                r'(?<![\d:])(\d{1,2})([/\-])(\d{1,2})(?![\d:])', old_raw
            )
    range_m = re.search(r'(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})', old_raw)

    def date_part() -> str:
        if date_mon_m:
            year_len = len(date_mon_m.group(3))
            year_str = str(new_dt.year) if year_len == 4 else str(new_dt.year)[-2:]
            return f"{new_dt.day}-{_MONTHS_SHORT[new_dt.month - 1]}-{year_str}"
        if date_md_m:
            sep = date_md_m.group(2)
            return f"{new_dt.month:02d}{sep}{new_dt.day:02d}"
        if not date_m:
            return ""
        sep = date_m.group(2)
        year_len = len(date_m.group(4))
        year_str = str(new_dt.year) if year_len == 4 else str(new_dt.year)[-2:]
        return f"{new_dt.month:02d}{sep}{new_dt.day:02d}{sep}{year_str}"

    date_present = bool(date_m or date_mon_m or date_md_m)

    if range_m:
        sh, sm, eh, em = (int(g) for g in range_m.groups())
        duration = ((eh * 60 + em) - (sh * 60 + sm)) % (24 * 60)
        new_start = new_dt.hour * 60 + new_dt.minute
        new_end_h, new_end_m = divmod((new_start + duration) % (24 * 60), 60)
        time_part = (f"{new_dt.hour:02d}:{new_dt.minute:02d}-"
                     f"{new_end_h:02d}:{new_end_m:02d}")
        d = date_part()
        return f"{d} {time_part}".strip()

    if not date_present and re.fullmatch(r'\d{4}', old_raw):
        return f"{new_dt.hour:02d}{new_dt.minute:02d}"

    if re.search(r'\d{1,2}:\d{2}(:\d{2})?\s*[AaPp][Mm]', old_raw):
        hour12 = new_dt.hour % 12 or 12
        ampm = "PM" if new_dt.hour >= 12 else "AM"
        has_sec = bool(re.search(r'\d{1,2}:\d{2}:\d{2}\s*[AaPp][Mm]', old_raw))
        time_part = f"{hour12}:{new_dt.minute:02d}"
        if has_sec:
            time_part += f":{new_dt.second:02d}"
        time_part += f" {ampm}"
        d = date_part()
        return f"{d} {time_part}".strip()

    if date_present and not re.search(r'\d{1,2}:\d{2}', old_raw):
        return date_part()

    if date_present and re.search(r'\d{1,2}:\d{2}', old_raw):
        has_sec = bool(re.search(r'\d{1,2}:\d{2}:\d{2}', old_raw))
        t = f"{new_dt.hour:02d}:{new_dt.minute:02d}"
        if has_sec:
            t += f":{new_dt.second:02d}"
        return f"{date_part()} {t}".strip()

    if re.fullmatch(r'\d{1,2}:\d{2}(:\d{2})?', old_raw):
        if old_raw.count(":") == 2:
            return f"{new_dt.hour:02d}:{new_dt.minute:02d}:{new_dt.second:02d}"
        return f"{new_dt.hour:02d}:{new_dt.minute:02d}"

    return f"{new_dt.hour:02d}:{new_dt.minute:02d}"


def quick_parse_time_text(raw: str):
    """Parse a bare time string into datetime (today's date) for delta math."""
    raw = raw.strip()
    today = datetime.now().date()

    m = re.fullmatch(r'(\d{1,2}):(\d{2})(:(\d{2}))?\s*([AaPp][Mm])', raw)
    if m:
        hour = int(m.group(1)); minute = int(m.group(2)); second = int(m.group(4) or 0)
        ampm = m.group(5).lower()
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        return datetime(today.year, today.month, today.day, hour, minute, second)

    m = re.fullmatch(r'([01]\d|2[0-3])([0-5]\d)', raw)
    if m:
        return datetime(today.year, today.month, today.day, int(m.group(1)), int(m.group(2)))

    m = re.fullmatch(r'(\d{1,2}):(\d{2})(:(\d{2}))?', raw)
    if m:
        return datetime(today.year, today.month, today.day,
                         int(m.group(1)), int(m.group(2)), int(m.group(4) or 0))
    return None


def quick_parse_full_datetime(raw: str, fallback_year: int):
    """Parse a possibly date+time string for old-value delta math."""
    from bol_bot.utils.datetime_utils import parse_user_input

    raw = raw.strip()
    raw = re.split(r'\s*-\s*\d{1,2}:\d{2}', raw)[0]
    dt = parse_user_input(raw, fallback_year=fallback_year)
    if dt:
        return dt
    m = re.search(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})', raw)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day)
        except ValueError:
            return None
    return quick_parse_time_text(raw)
