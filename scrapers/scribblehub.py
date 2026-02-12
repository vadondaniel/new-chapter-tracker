import datetime
import re
import time
from urllib.parse import urljoin, urlparse

import cloudscraper
import requests
from bs4 import BeautifulSoup

DOMAINS = ["scribblehub.com"]
SUPPORTS_FREE_TOGGLE = False
SCRAPER_NAME = "Scribble Hub"
SCRAPER_NOTES = [""]

TOC_SELECTOR = "ol.toc_ol li.toc_w"
TOC_API_URL = "https://www.scribblehub.com/wp-admin/admin-ajax.php"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.scribblehub.com/",
    "X-Requested-With": "XMLHttpRequest",
}


def build_scraper():
    session = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    session.headers.update(DEFAULT_HEADERS)
    return session


def extract_series_id(url):
    for pattern in (r"/series/(\d+)(?:/|$)", r"/read/(\d+)-"):
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def build_series_url(source_url, series_id):
    parsed = urlparse(source_url)
    scheme = parsed.scheme or "https"
    host = parsed.netloc or "www.scribblehub.com"
    if "scribblehub.com" not in host.lower():
        host = "www.scribblehub.com"
    return f"{scheme}://{host}/series/{series_id}/"


def request_with_retry(scraper, method, url, attempts=2, **kwargs):
    last_error = None
    for attempt in range(attempts):
        try:
            response = scraper.request(method, url, timeout=20, **kwargs)
            if response.status_code in {403, 503} and attempt < attempts - 1:
                time.sleep(1.0)
                continue
            response.raise_for_status()
            return response, None
        except requests.RequestException as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(1.0)
    return None, last_error


def extract_chapter_id(chapter_url):
    match = re.search(r"/chapter/(\d+)(?:/|$)", chapter_url)
    return int(match.group(1)) if match else -1


def parse_timestamp(raw_time, fallback_ts):
    if not raw_time:
        return fallback_ts
    normalized = raw_time.strip()
    lowered = normalized.lower()
    if "ago" in lowered or lowered in {"now", "today"}:
        return fallback_ts

    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(normalized, fmt).strftime("%Y/%m/%d")
        except ValueError:
            continue

    match = re.search(r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})", normalized)
    if match:
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.datetime.strptime(match.group(1), fmt).strftime("%Y/%m/%d")
            except ValueError:
                continue

    return fallback_ts


def pick_latest_chapter(chapter_rows, base_url):
    chapters = []
    for row in chapter_rows:
        title_tag = row.select_one("a.toc_a")
        if not title_tag:
            continue
        chapter_title = title_tag.get_text(strip=True)
        chapter_href = urljoin(base_url, title_tag.get("href", "").strip())
        if not chapter_title or not chapter_href:
            continue

        time_tag = row.select_one("span.fic_date_pub")
        raw_time = ""
        if time_tag:
            raw_time = (time_tag.get("title") or time_tag.get_text(" ", strip=True) or "").strip()

        chapters.append(
            {
                "title": chapter_title,
                "url": chapter_href,
                "raw_time": raw_time,
                "chapter_id": extract_chapter_id(chapter_href),
            }
        )

    if not chapters:
        return None

    with_numeric_id = [item for item in chapters if item["chapter_id"] >= 0]
    if with_numeric_id:
        return max(with_numeric_id, key=lambda item: item["chapter_id"])
    return chapters[0]


def pick_latest_from_links(chapter_links, base_url):
    chapters = []
    for link in chapter_links:
        chapter_title = link.get_text(strip=True)
        chapter_href = urljoin(base_url, link.get("href", "").strip())
        if not chapter_title or not chapter_href:
            continue
        chapters.append(
            {
                "title": chapter_title,
                "url": chapter_href,
                "raw_time": "",
                "chapter_id": extract_chapter_id(chapter_href),
            }
        )

    if not chapters:
        return None

    with_numeric_id = [item for item in chapters if item["chapter_id"] >= 0]
    if with_numeric_id:
        return max(with_numeric_id, key=lambda item: item["chapter_id"])
    return chapters[0]


def fetch_toc_via_api(series_url, series_id, attempts=3):
    data = {
        "action": "wi_getreleases_pagination",
        "mypostid": series_id,
        "pagenum": 1,
    }
    last_error = None
    for attempt in range(attempts):
        scraper = build_scraper()
        scraper.headers["Referer"] = series_url
        try:
            try:
                scraper.get(series_url, timeout=20)
            except requests.RequestException:
                pass
            response = scraper.post(TOC_API_URL, data=data, timeout=20)
            if response.status_code in {403, 503} and attempt < attempts - 1:
                time.sleep(1.5)
                continue
            response.raise_for_status()
            text = response.text.strip()
            if not text or text == "0":
                raise ValueError("Empty TOC response")
            return text, None
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(1.5)
    return None, last_error


def fetch_full_page(series_url, attempts=3):
    scraper = build_scraper()
    response, error = request_with_retry(scraper, "GET", series_url, attempts=attempts)
    if response is None:
        return None, error
    return response.text, None


def parse_latest_from_html(html, fallback_ts):
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select(TOC_SELECTOR)
    if not rows:
        rows = soup.select("ol.toc_ol li")
    chapter = pick_latest_chapter(rows, "https://www.scribblehub.com/")

    if chapter is None:
        # Fallback path when TOC row markup changes.
        fallback_links = soup.select(".latest_release_main a, .toc_ol .toc_a")
        chapter = pick_latest_from_links(
            fallback_links, "https://www.scribblehub.com/"
        )

    if chapter is None:
        return None, "Table of contents not found"

    chapter_text = chapter["title"]
    chapter_url = chapter["url"]
    timestamp = parse_timestamp(chapter["raw_time"], fallback_ts)
    return (chapter_text, timestamp, chapter_url), None


def scrape(url, free_only=False):
    fallback_ts = datetime.datetime.now().strftime("%Y/%m/%d")
    series_id = extract_series_id(url)
    if not series_id:
        return (
            "No chapters found",
            fallback_ts,
            False,
            "Unable to parse series ID from URL",
        )
    series_url = build_series_url(url, series_id)

    html, page_error = fetch_full_page(series_url)
    if html:
        parsed, parse_error = parse_latest_from_html(html, fallback_ts)
        if parsed:
            chapter_text, timestamp, chapter_url = parsed
            return chapter_text, timestamp, True, None, chapter_url
        page_error = parse_error or page_error

    html, api_error = fetch_toc_via_api(series_url, series_id)
    if html:
        parsed, parse_error = parse_latest_from_html(html, fallback_ts)
        if parsed:
            chapter_text, timestamp, chapter_url = parsed
            return chapter_text, timestamp, True, None, chapter_url
        api_error = parse_error or api_error

    message = str(api_error or page_error or "Unable to fetch Scribble Hub TOC")
    return "No chapters found", fallback_ts, False, message
