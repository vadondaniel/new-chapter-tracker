import datetime
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

DOMAINS = ["z-lib.fm,z-lib.gd,articles.sk,1lib.sk,z-library.sk,z-lib.gs"]
SUPPORTS_FREE_TOGGLE = False
SCRAPER_NAME = "Z-Library"
SCRAPER_NOTES = ["Supports search URLs and forces order=date sorting"]


def normalize_search_url(url):
    raw_url = (url or "").strip()
    if not raw_url:
        return None
    if "://" not in raw_url:
        raw_url = f"https://{raw_url.lstrip('/')}"

    parsed = urlparse(raw_url)
    path = parsed.path or ""
    if not path.startswith("/s/"):
        return None

    search_term = unquote(path[len("/s/"):]).strip()
    if not search_term:
        return None

    encoded_term = quote(search_term, safe="")
    canonical_path = f"/s/{encoded_term}"
    return urlunparse(("https", "z-lib.fm", canonical_path, "", "order=date", ""))


def scrape(url, free_only=False):
    timestamp = datetime.datetime.now().strftime("%Y/%m/%d")
    search_url = normalize_search_url(url)
    if not search_url:
        return (
            "Invalid Z-Library URL",
            timestamp,
            False,
            "Expected a /s/<search term> URL",
        )

    try:
        response = requests.get(search_url, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        return "Connection error", timestamp, False, str(exc)

    soup = BeautifulSoup(response.content, "html.parser")
    results_box = soup.select_one("#searchResultBox")
    if not results_box:
        return "No results found", timestamp, False, "searchResultBox not found"

    cards = results_box.select("z-bookcard")
    if not cards:
        return "No results found", timestamp, False, "No z-bookcard entries found"

    latest = cards[0]
    title_tag = latest.select_one('[slot="title"]')
    title = title_tag.get_text(" ", strip=True) if title_tag else "No title found"

    href = (latest.get("href") or "").strip()
    chapter_url = urljoin("https://z-lib.fm", href) if href else search_url

    return title, timestamp, True, None, chapter_url
