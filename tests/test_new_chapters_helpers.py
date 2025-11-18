from datetime import datetime, timedelta

import pytest

import scraping
from new_chapters import (
    annotate_support_flags,
    annotate_timestamp_display,
    get_link_metadata,
    parse_free_only,
    parse_update_frequency,
    resolve_category,
    app,
    db,
)


def test_parse_free_only_handles_booleans_and_strings():
    assert parse_free_only(True, False) is True
    assert parse_free_only(False, True) is False
    assert parse_free_only("Y", False) is True
    assert parse_free_only("no", True) is False
    assert parse_free_only(None, True) is True
    assert parse_free_only("   ", False) is False


def test_parse_update_frequency_respects_units_and_invalid_inputs():
    assert parse_update_frequency("2d", 1) == 2
    assert parse_update_frequency("48h", 1) == 2
    assert parse_update_frequency("30m", 1) == 1  # rounds up to at least 1 day
    assert parse_update_frequency("5", 1) == 5
    assert parse_update_frequency("", 3) == 3
    assert parse_update_frequency("NaN", 4) == 4
    assert parse_update_frequency(None, 1) == 1
    assert parse_update_frequency(2.7, 1) == 2


def test_get_link_metadata_prefers_payload_values():
    payload = {"update_frequency": "3d", "free_only": "yes"}
    existing = {"update_frequency": 5, "free_only": False}
    freq, free_only = get_link_metadata(payload, existing)
    assert freq == 3
    assert free_only is True

    payload = {"update_frequency": None, "free_only": ""}
    existing = {"update_frequency": 5, "free_only": True}
    freq, free_only = get_link_metadata(payload, existing)
    assert freq == 5
    assert free_only is True


def test_annotate_timestamp_display_uses_today_and_yesterday_labels():
    today = datetime.now().strftime("%Y/%m/%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y/%m/%d")
    entries = {
        "today": {"timestamp": today},
        "yesterday": {"timestamp": yesterday},
        "unknown": {"timestamp": "2022/01/01"},
        "invalid": {"timestamp": "bad-date"},
    }

    annotated = annotate_timestamp_display(entries)

    assert annotated["today"]["timestamp_display"] == "Today"
    assert annotated["yesterday"]["timestamp_display"] == "Yesterday"
    assert annotated["unknown"]["timestamp_display"] == "2022/01/01"
    assert annotated["invalid"]["timestamp_display"] == "bad-date"


def test_annotate_support_flags_uses_scraping_support_flags(monkeypatch):
    entries = {
        "https://example.com": {"name": "Example"},
        "https://other.com": {"name": "Other"},
    }
    monkeypatch.setattr(scraping, "supports_free_toggle", lambda url: "other" in url)

    annotated = annotate_support_flags(entries)

    assert annotated["https://example.com"]["supports_free_toggle"] is False
    assert annotated["https://other.com"]["supports_free_toggle"] is True


def test_resolve_category_prefers_known_names_and_path():
    category_names = db.get_category_names()
    assert "main" in category_names
    other_categories = [name for name in category_names if name != "main"]
    if other_categories:
        test_prefix = other_categories[0]
        with app.test_request_context(f"/{test_prefix}/chapter"):
            assert resolve_category() == test_prefix
    with app.test_request_context("/unknown/path"):
        assert resolve_category() == "main"

    # Direct category argument should win over path heuristics.
    first_category = category_names[0]
    assert resolve_category(first_category) == first_category
