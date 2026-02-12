import datetime
import re
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup

DOMAINS = ["alert.shop-bell.com"]
SUPPORTS_FREE_TOGGLE = False
SCRAPER_NAME = "Shop Bell Alert"
SCRAPER_NOTES = ["Supports both detail and RSS URLs"]


def extract_series_id(url):
    for pattern in (r"/ranobe/detail/(\d+)(?:/|$)", r"/rss/ranobe/(\d+)\.rss(?:\?|$)"):
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def to_rss_url(url):
    series_id = extract_series_id(url)
    if not series_id:
        return None
    return f"https://alert.shop-bell.com/rss/ranobe/{series_id}.rss"


def strip_series_prefix(item_title, series_title):
    if not item_title:
        return "No title found"
    if series_title and item_title.startswith(series_title):
        item_title = item_title[len(series_title) :].lstrip(" -:")
        if item_title.startswith("\u306e"):
            item_title = item_title[1:].lstrip(" -:")
        if item_title.startswith("\uff1a"):
            item_title = item_title[1:].lstrip(" -:")
    return item_title or "No title found"


def unwrap_rss_link(link):
    if not link:
        return None
    parsed = urlparse(link)
    if parsed.path.lower().endswith("rsslink.html") and parsed.query:
        target = unquote(parsed.query).strip()
        if target.startswith(("https://", "http://")):
            return target
    return link


def scrape(url, free_only=False):
    timestamp = datetime.datetime.now().strftime("%Y/%m/%d")
    rss_url = to_rss_url(url)
    if not rss_url:
        return "Invalid Shop Bell URL", timestamp, False, "Unable to parse series ID"

    try:
        response = requests.get(rss_url, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        return "Connection error", timestamp, False, str(exc)

    soup = BeautifulSoup(response.content, "xml")
    latest_item = soup.find("item")
    if not latest_item:
        return "No chapters found", timestamp, False, "No RSS item found"

    channel = soup.find("channel")
    series_title_tag = channel.find("title", recursive=False) if channel else None
    series_title = (
        series_title_tag.get_text(strip=True) if series_title_tag else ""
    )

    title_tag = latest_item.find("title")
    raw_title = title_tag.get_text(strip=True) if title_tag else "No title found"
    chapter_text = strip_series_prefix(raw_title, series_title)

    link_tag = latest_item.find("link")
    raw_link = link_tag.get_text(strip=True) if link_tag else None
    chapter_url = unwrap_rss_link(raw_link)

    pub_date_tag = latest_item.find("pubDate")
    if pub_date_tag:
        pub_date = pub_date_tag.get_text(strip=True)
        try:
            timestamp = datetime.datetime.strptime(
                pub_date, "%a, %d %b %Y %H:%M:%S %z"
            ).strftime("%Y/%m/%d")
        except ValueError:
            pass

    return chapter_text, timestamp, True, None, chapter_url
