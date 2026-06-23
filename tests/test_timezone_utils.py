"""Tests for timezone detection and conversion."""
from datetime import datetime

import pytest

from bol_bot.utils.timezone_utils import (
    TZ_ABBR_TO_IANA, convert_between_timezones, guess_state_code_from_text,
    state_code_to_iana,
)


class TestStateDetection:
    def test_state_zip_pattern(self):
        assert guess_state_code_from_text("Springdale AR 72764") == "AR"

    def test_state_in_parens(self):
        text = "ORIGIN: SAINT PAUL (MN) P&DC"
        assert guess_state_code_from_text(text) == "MN"

    def test_state_with_comma(self):
        text = "Origin: Knoxville, TN"
        assert guess_state_code_from_text(text) == "TN"

    def test_origin_section_isolation(self):
        # The destination's state must NOT be returned
        text = """
        Origin: Dallas, TX 75201
        Destination: Miami, FL 33101
        """
        assert guess_state_code_from_text(text) == "TX"

    def test_city_name_fallback(self):
        text = "Pickup at Memphis warehouse"
        assert guess_state_code_from_text(text) == "TN"

    def test_no_state_returns_none(self):
        assert guess_state_code_from_text("just a random string") is None

    def test_empty_string(self):
        assert guess_state_code_from_text("") is None
        assert guess_state_code_from_text(None) is None


class TestStateToIana:
    @pytest.mark.parametrize("code,expected", [
        ("CA", "America/Los_Angeles"),
        ("NY", "America/New_York"),
        ("TX", "America/Chicago"),
        ("AZ", "America/Phoenix"),
    ])
    def test_known_codes(self, code, expected):
        assert state_code_to_iana(code) == expected

    def test_unknown_code(self):
        assert state_code_to_iana("ZZ") is None


class TestTimezoneConversion:
    def test_central_to_eastern(self):
        # 09:00 CDT -> 10:00 EDT (1 hour ahead)
        dt = datetime(2026, 7, 15, 9, 0)
        out = convert_between_timezones(dt, "CDT", "America/New_York")
        assert out == datetime(2026, 7, 15, 10, 0)

    def test_eastern_to_pacific(self):
        # 14:00 EDT -> 11:00 PDT
        dt = datetime(2026, 7, 15, 14, 0)
        out = convert_between_timezones(dt, "EDT", "America/Los_Angeles")
        assert out == datetime(2026, 7, 15, 11, 0)

    def test_invalid_abbr_raises(self):
        with pytest.raises(ValueError):
            convert_between_timezones(datetime(2026, 1, 1), "ZZZ", "America/New_York")

    def test_all_four_abbrs_supported(self):
        for abbr in ("EDT", "CDT", "MDT", "PDT"):
            assert abbr in TZ_ABBR_TO_IANA
