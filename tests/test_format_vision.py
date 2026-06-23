"""Tests for vision-text format reconstruction."""
from datetime import datetime

from bol_bot.bot.format_vision import (
    format_like_vision_text, quick_parse_full_datetime, quick_parse_time_text,
)


class TestFormatLikeVisionText:
    def test_compact_hhmm(self):
        out = format_like_vision_text("1455", datetime(2026, 1, 1, 9, 5))
        assert out == "0905"

    def test_colon_24h(self):
        out = format_like_vision_text("16:45", datetime(2026, 1, 1, 9, 5))
        assert out == "09:05"

    def test_colon_with_seconds_24h(self):
        out = format_like_vision_text("16:45:30", datetime(2026, 1, 1, 9, 5, 7))
        assert out == "09:05:07"

    def test_ampm_format(self):
        out = format_like_vision_text("4:45 PM", datetime(2026, 1, 1, 9, 5))
        assert out == "9:05 AM"

    def test_ampm_pm(self):
        out = format_like_vision_text("4:45 PM", datetime(2026, 1, 1, 13, 5))
        assert out == "1:05 PM"

    def test_date_only_4digit_year(self):
        out = format_like_vision_text("6/19/2026", datetime(2027, 7, 4, 10, 0))
        assert out == "07/04/2027"

    def test_date_only_2digit_year(self):
        out = format_like_vision_text("06/18/26", datetime(2027, 7, 4, 10, 0))
        assert out == "07/04/27"

    def test_date_plus_time(self):
        out = format_like_vision_text("6/19/2026 06:00", datetime(2026, 6, 19, 14, 30))
        assert out == "06/19/2026 14:30"

    def test_date_plus_range_keeps_duration(self):
        out = format_like_vision_text(
            "6/19/2026 06:00-10:00", datetime(2026, 6, 19, 14, 30),
        )
        # duration was 4 hours
        assert "14:30-18:30" in out

    def test_dash_month_format(self):
        out = format_like_vision_text("20-Jun-26", datetime(2027, 7, 4, 10, 0))
        assert out == "4-Jul-27"


class TestQuickParseTime:
    def test_ampm(self):
        out = quick_parse_time_text("4:45 PM")
        assert out.hour == 16 and out.minute == 45

    def test_24h(self):
        out = quick_parse_time_text("16:45")
        assert out.hour == 16 and out.minute == 45

    def test_compact(self):
        out = quick_parse_time_text("1345")
        assert out.hour == 13 and out.minute == 45

    def test_invalid(self):
        assert quick_parse_time_text("not a time") is None


class TestQuickParseFull:
    def test_with_full_date(self):
        out = quick_parse_full_datetime("06/18/2026 14:30", 2026)
        assert out == datetime(2026, 6, 18, 14, 30)

    def test_date_only(self):
        out = quick_parse_full_datetime("06/18/2026", 2026)
        assert out == datetime(2026, 6, 18)

    def test_time_only(self):
        out = quick_parse_full_datetime("14:30", 2026)
        assert out is not None
        assert out.hour == 14 and out.minute == 30

    def test_range_uses_start(self):
        out = quick_parse_full_datetime("06/18/2026 06:00-10:00", 2026)
        assert out.hour == 6 and out.minute == 0
