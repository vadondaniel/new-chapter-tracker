import datetime

import pytest

import scraping


def test_normalize_scrape_result_handles_dict():
    result = {
        "last_found": "Chapter 1",
        "timestamp": "2025/11/17",
        "success": True,
        "error": None,
        "last_found_url": "http://example.com/1"
    }
    chapter, timestamp, success, error, chapter_url = scraping.normalize_scrape_result(
        result)
    assert chapter == "Chapter 1"
    assert timestamp == "2025/11/17"
    assert success is True
    assert error is None
    assert chapter_url == "http://example.com/1"


def test_normalize_scrape_result_handles_tuple_like_inputs():
    chapter, timestamp, success, error, chapter_url = scraping.normalize_scrape_result(
        ("Chapter 2", "2025/11/18", False, "oops", "http://example.com/2")
    )
    assert chapter == "Chapter 2"
    assert timestamp == "2025/11/18"
    assert success is False
    assert error == "oops"
    assert chapter_url == "http://example.com/2"


def test_normalize_scrape_result_handles_strings():
    chapter, timestamp, success, error, chapter_url = scraping.normalize_scrape_result(
        "Chapter x")
    assert "Chapter x" in chapter
    assert isinstance(timestamp, str)
    assert success is True
    assert error is None
    assert chapter_url is None


def test_scrape_website_returns_unsupported_when_no_plugin(monkeypatch):
    monkeypatch.setattr(scraping, "SCRAPERS", {})
    result = scraping.scrape_website({"url": "https://unknown.example"})
    assert result[2] is False
    assert result[3] == "unsupported"


def test_supports_free_toggle_reflects_registry(monkeypatch):
    monkeypatch.setattr(scraping, "SCRAPERS", {
        "example.com": {"scraper": lambda url, free_only=False: None, "supports_free_toggle": True}
    })
    assert scraping.supports_free_toggle("https://example.com") is True
    assert scraping.supports_free_toggle("https://other.com") is False
