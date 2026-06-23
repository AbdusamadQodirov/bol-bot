"""Storage / audit-log smoke tests."""
import os
import tempfile

import pytest

from bol_bot import config


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DB_PATH", os.path.join(d, "test.db"))
        config.reset_settings_for_tests()
        yield


def test_init_and_log_edit():
    from bol_bot.storage import init_db, log_edit, recent_edits
    init_db()
    log_edit(
        user_id=42, username="alice", file_hash="abc",
        page_index=0, mode="text", field_context="Time In",
        old_value="13:45", new_value="14:00", tz_from="CDT", tz_to="CST",
    )
    rows = recent_edits(42)
    assert len(rows) == 1
    assert rows[0]["new_value"] == "14:00"


def test_rate_limit_below_threshold():
    from bol_bot.storage import init_db, is_rate_limited, record_request
    init_db()
    for _ in range(5):
        record_request(99)
    limited, _ = is_rate_limited(99)
    assert not limited


def test_rate_limit_hits_threshold(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "3")
    config.reset_settings_for_tests()
    from bol_bot.storage import init_db, is_rate_limited, record_request
    init_db()
    for _ in range(3):
        record_request(100)
    limited, reason = is_rate_limited(100)
    assert limited
    assert "daqiqada" in reason or "minute" in reason.lower() or "3" in reason
