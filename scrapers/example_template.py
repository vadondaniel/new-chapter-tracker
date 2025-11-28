"""
Example scraper plugin that documents the expected inputs/outputs and
offers tips for implementing scraping logic (HTML, RSS, and optional
Selenium fallback).

The scraper registry loads this module if the request URL matches one
of the strings in `DOMAINS`. Each module must export:

  * `DOMAINS`: iterable of substrings used to detect which URLs the plugin
    should handle.
  * `scrape(url, free_only=False)`: callable that returns the latest
    chapter info (see explanation below).
  * Optional `SUPPORTS_FREE_TOGGLE`: `True` if the plugin honors the
    `free_only` flag; otherwise omit it or set to `False`.

The scraping function receives:

  * `url` (str) — the full address of the chapter/listing to check.
  * `free_only` (bool) — whether the user wants to restrict results to
    freely accessible content. The plugin may ignore this flag if the
    source does not distinguish.

It must return either:
  1. A dict with keys `last_found`, `timestamp`, and optional `success`/`error`.
  2. A tuple/list like `(last_found, timestamp[, success[, error]])`.

Recommended formats:

  ```python
  {
      "last_found": "Chapter 20",
      "timestamp": "2025/11/17",
      "success": True
  }
  ```

  or

  ```python
  ("Chapter 20", "2025/11/17", True)
  ```

The scraper_utils module will normalize either shape for you.

Tips for scraping:
  * Start by using a browser’s inspector to locate the elements containing
    the latest chapter and release date. Prefer stable CSS selectors or IDs.
  * Guard against missing data: wrap lookups in try/except and surface
    meaningful messages via the returned `error` payload when scraping
    fails (non-200 status, site layout changes, etc.).
  * Prefer RSS/JSON feeds when available; they are easier to parse, load
    faster, and usually include timestamped updates. Use `feedparser` or
    `xml.etree.ElementTree` to traverse RSS feeds.
  * Normalize timestamps to the `YYYY/MM/DD` pattern expected by the app
    (see `scraper_utils.parse_timestamp`).

Optional Selenium fallback:
  * If the page requires JavaScript rendering, you can instantiate
    `BrowserManager.get_driver()` (from `scraping.py`) and let it fetch the
    fully rendered DOM. Remember to call `BrowserManager.quit_driver()` once
    you are done, or rely on the existing shutdown logic.
  * Drawbacks: Selenium is heavier, slower, and harder to run in
    headless environments; it also complicates deployments because you need
    a compatible browser/driver combo. Always try HTTP requests first and
    only revert to Selenium if the site absolutely requires it.
"""

from typing import Dict, Tuple, Union
from datetime import datetime

DOMAINS = ["example.com"]
SUPPORTS_FREE_TOGGLE = True
SCRAPER_NAME = "Example Scraper"
SCRAPER_NOTES = ["Some notes"]
HIDE_IN_SUPPORTED_LIST = True


def parse_series_page(html: str) -> Tuple[str, str]:
    """Placeholder helper; replace with your HTML parsing logic."""
    # Example: use BeautifulSoup() to find the chapter/title selectors here.
    latest_chapter = "Chapter 100 (mocked)"
    release_date = datetime.now().strftime("%Y/%m/%d")
    return latest_chapter, release_date


def scrape(url: str, free_only: bool = False) -> Union[Dict, Tuple]:
    """
    Core entry point. Return tuple/dict explained above.

    The `free_only` flag should be enforced if the source distinguishes
    between free and paid chapters. You can cut the request short or
    filter the results accordingly.
    """
    # 1. Try to fetch via HTTP/requests.
    # 2. If you detect a paywall or missing data, you may fallback to
    #    BrowserManager.get_driver() for rendering the page (see docstring).
    # 3. Always return the latest chapter & timestamp info.

    # Mocked response for documentation purposes:
    last_found, timestamp = parse_series_page("<html>...</html>")
    return (last_found, timestamp, True, None)
