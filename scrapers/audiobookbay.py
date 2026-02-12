import datetime
import re
from urllib.parse import urljoin

import cloudscraper
from bs4 import BeautifulSoup

DOMAINS = ["audiobookbay.lu"]
SUPPORTS_FREE_TOGGLE = False
SCRAPER_NAME = "AudioBook Bay"
SCRAPER_NOTES = ["Supports search query URLs"]

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def normalize_url(url):
    source = (url or "").strip()
    if not source:
        return None
    if "://" not in source:
        return f"https://{source.lstrip('/')}"
    return source


def parse_posted_date(text, fallback_ts):
    match = re.search(r"Posted:\s*([0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})", text or "")
    if not match:
        return fallback_ts

    date_text = match.group(1)
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.datetime.strptime(date_text, fmt).strftime("%Y/%m/%d")
        except ValueError:
            continue
    return fallback_ts


def scrape(url, free_only=False):
    timestamp = datetime.datetime.now().strftime("%Y/%m/%d")
    source_url = normalize_url(url)
    if not source_url:
        return "Invalid URL", timestamp, False, "Empty URL"

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )
    scraper.headers.update(DEFAULT_HEADERS)

    try:
        response = scraper.get(source_url, timeout=20)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return "Connection error", timestamp, False, str(exc)

    soup = BeautifulSoup(response.content, "html.parser")
    post = soup.select_one("#content .post")
    if not post:
        return "No posts found", timestamp, False, "No .post entry found"

    title_tag = post.select_one(".postTitle h2 a") or post.select_one("h2 a")
    if title_tag:
        title = title_tag.get_text(" ", strip=True)
        href = (title_tag.get("href") or "").strip()
        chapter_url = urljoin(response.url, href) if href else response.url
    else:
        title = "No title found"
        chapter_url = response.url

    post_text = post.get_text(" ", strip=True)
    timestamp = parse_posted_date(post_text, timestamp)

    return title, timestamp, True, None, chapter_url
