from datetime import datetime, timedelta

from scraper_utils import convert_to_rss_url, needs_update, parse_timestamp


def test_needs_update_variants():
    assert needs_update("https://example.com", {}, 7, False)
    now_ts = datetime.now().strftime("%Y/%m/%d")
    assert needs_update("https://example.com", {"https://example.com": {"timestamp": now_ts}}, 7, True)

    old_ts = (datetime.now() - timedelta(days=5)).strftime("%Y/%m/%d")
    assert needs_update("https://example.com", {"https://example.com": {"timestamp": old_ts}}, 2, False)

    recent_ts = (datetime.now() - timedelta(hours=1)).strftime("%Y/%m/%d")
    assert not needs_update("https://example.com", {"https://example.com": {"timestamp": recent_ts}}, 1, False)


def test_parse_timestamp_rounds_to_slash_format():
    assert parse_timestamp("2025-11-17T12:00:00") == "2025/11/17"
    assert parse_timestamp("2023-01-01") == "2023/01/01"


def test_convert_to_rss_url_appends_page_parameter():
    url = "https://example.com/path?foo=bar"
    rss_url = convert_to_rss_url(url)
    assert "page=rss" in rss_url
    assert rss_url.startswith("https://example.com/path")
