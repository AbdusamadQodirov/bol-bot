"""Tests for date/time detection, parsing, and format-preserving regen."""
from datetime import datetime

import pytest

from bol_bot.utils.datetime_utils import (
    find_datetime_candidates,
    format_like_original,
    looks_like_pickup_group_label,
    looks_like_time_in_label,
    looks_like_time_out_label,
    parse_user_input,
)


class TestFindCandidates:
    def test_mdy_slash_with_time(self):
        text = "Ship Date: 07/13/2026 14:30"
        result = find_datetime_candidates(text)
        assert len(result) == 1
        assert result[0].raw_text == "07/13/2026 14:30"
        assert result[0].date_style == "mdy_slash"

    def test_mdy_slash_with_ampm(self):
        text = "Time: 7/13/2026 1:34:45 PM"
        result = find_datetime_candidates(text)
        assert len(result) == 1
        assert result[0].has_ampm
        assert result[0].has_seconds

    def test_iso(self):
        text = "Created: 2026-07-13 14:30:00"
        result = find_datetime_candidates(text)
        assert len(result) == 1
        assert result[0].date_style == "iso"

    def test_dmy_dash_month(self):
        text = "Pickup 20-Jun-26 23:15"
        result = find_datetime_candidates(text)
        assert len(result) == 1
        assert result[0].date_style == "dmy_dash_month"

    def test_month_name(self):
        text = "Date: July 13, 2026 4:45 PM"
        result = find_datetime_candidates(text)
        assert len(result) == 1
        assert result[0].date_style == "month_name"
        assert result[0].month_style == "long"

    def test_time_range(self):
        text = "Ship: 6/19/2026 06:00-10:00 CST"
        result = find_datetime_candidates(text)
        assert len(result) == 1
        assert result[0].is_range
        assert result[0].range_end_hour == 10
        assert result[0].range_end_minute == 0

    def test_compact_hhmm_with_time_in_label(self):
        text = "Time In: 1345"
        result = find_datetime_candidates(text)
        assert len(result) == 1
        assert result[0].raw_text == "1345"
        assert result[0].date_style == "time_hhmm_compact"

    def test_compact_hhmm_with_arrival_label(self):
        text = "Arrival: 1345"
        result = find_datetime_candidates(text)
        assert len(result) == 1
        assert result[0].raw_text == "1345"

    def test_compact_hhmm_with_departure_label(self):
        text = "Departure 0815"
        result = find_datetime_candidates(text)
        assert len(result) == 1
        assert result[0].raw_text == "0815"

    def test_compact_hhmm_invalid_hour(self):
        # 2500 is not a valid time and there's no label nearby — should not match
        text = "Reference 2500"
        result = find_datetime_candidates(text)
        assert len(result) == 0

    def test_date_only(self):
        text = "Date: 07/13/2026"
        result = find_datetime_candidates(text)
        assert len(result) == 1
        assert result[0].date_style == "mdy_slash_date_only"
        assert not result[0].has_time

    def test_multiple_candidates(self):
        text = "Time In: 1345 Time Out: 1530"
        result = find_datetime_candidates(text)
        assert len(result) == 2

    def test_no_overlap(self):
        # The range pattern should win over plain mdy_slash for this string.
        text = "6/19/2026 06:00-10:00"
        result = find_datetime_candidates(text)
        assert len(result) == 1
        assert result[0].is_range


class TestParseUserInput:
    def test_month_name_with_year(self):
        dt = parse_user_input("July 13, 2026 1:34:45 PM")
        assert dt == datetime(2026, 7, 13, 13, 34, 45)

    def test_month_name_no_year_with_fallback(self):
        dt = parse_user_input("July 13 13:45", fallback_year=2025)
        assert dt == datetime(2025, 7, 13, 13, 45)

    def test_mdy_slash(self):
        dt = parse_user_input("07/13/2026 13:45")
        assert dt == datetime(2026, 7, 13, 13, 45)

    def test_2_digit_year(self):
        dt = parse_user_input("07/13/26 13:45")
        assert dt == datetime(2026, 7, 13, 13, 45)

    def test_pm_conversion(self):
        dt = parse_user_input("07/13/2026 1:45 PM")
        assert dt.hour == 13

    def test_am_midnight(self):
        dt = parse_user_input("07/13/2026 12:00 AM")
        assert dt.hour == 0

    def test_invalid_returns_none(self):
        assert parse_user_input("not a date") is None

    def test_invalid_day(self):
        assert parse_user_input("02/30/2026 12:00") is None


class TestFormatLikeOriginal:
    def _match(self, text):
        cands = find_datetime_candidates(text)
        assert cands, f"no match for {text!r}"
        return cands[0]

    def test_preserves_24h(self):
        tm = self._match("Ship Date: 07/13/2026 14:30")
        out = format_like_original(datetime(2026, 8, 20, 9, 5), tm)
        assert out == "08/20/2026 09:05"

    def test_preserves_ampm_and_seconds(self):
        tm = self._match("Time: 07/13/2026 1:34:45 PM")
        out = format_like_original(datetime(2026, 7, 13, 13, 5, 7), tm)
        assert out == "07/13/2026 1:05:07 PM"

    def test_preserves_iso(self):
        tm = self._match("2026-07-13 14:30:00")
        out = format_like_original(datetime(2026, 8, 1, 9, 5, 0), tm)
        assert out == "2026-08-01 09:05:00"

    def test_preserves_2_digit_year(self):
        tm = self._match("20-Jun-26 23:15")
        out = format_like_original(datetime(2026, 7, 4, 8, 30), tm)
        assert out == "4-Jul-26 08:30"

    def test_preserves_range_duration(self):
        # 4-hour window — should stay 4 hours after editing the start
        tm = self._match("6/19/2026 06:00-10:00 CST")
        out = format_like_original(datetime(2026, 6, 19, 14, 30), tm)
        # 14:30 + 4h = 18:30
        assert "14:30-18:30" in out

    def test_compact_hhmm_round_trip(self):
        tm = self._match("Time In: 1345")
        out = format_like_original(datetime(2026, 1, 1, 9, 5), tm)
        assert out == "0905"


class TestLabelClassifiers:
    @pytest.mark.parametrize("label", [
        "Time Out", "TIME OUT", "Departure", "Pickup time", "DEPART:",
    ])
    def test_out_labels(self, label):
        assert looks_like_time_out_label(label)

    @pytest.mark.parametrize("label", [
        "Time In", "Arrival", "Arr:", "Check In", "Check-in",
    ])
    def test_in_labels(self, label):
        assert looks_like_time_in_label(label)

    def test_in_label_does_not_match_substring_origin(self):
        # The original v1 bug: " in" matched "origin", "destination" etc.
        assert not looks_like_time_in_label("Origin")
        assert not looks_like_time_in_label("Destination Info")
        assert not looks_like_time_in_label("Shipping Info")

    @pytest.mark.parametrize("label", [
        "Ship Date", "Origin", "Shipper Signature", "Pickup #", "PU Date",
    ])
    def test_pickup_group_labels(self, label):
        assert looks_like_pickup_group_label(label)
