import datetime
import logging
import re
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

DOMAINS = ["manga.nicovideo.jp"]
SUPPORTS_FREE_TOGGLE = False
SCRAPER_NAME = "Nico Nico Manga"
SCRAPER_NOTES = [""]

COMIC_ID_PATTERN = re.compile(r"/(?:comic|rss/manga)/(\d+)")


def _build_rss_url(url: str):
    parsed = urlparse(url)
    match = COMIC_ID_PATTERN.search(parsed.path)
    if not match:
        return None

    series_id = match.group(1)
    scheme = parsed.scheme or "https"
    host = parsed.netloc or "manga.nicovideo.jp"
    return f"{scheme}://{host}/rss/manga/{series_id}"


def _extract_series_title(soup: BeautifulSoup):
    channel_tag = soup.find("channel")
    if not channel_tag:
        return None

    title_tag = channel_tag.find("title")
    if not title_tag or not title_tag.text:
        return None

    channel_title = title_tag.get_text(strip=True)
    if not channel_title:
        return None

    # Channel titles are commonly "<series> - <site name>".
    return channel_title.rsplit(" - ", 1)[0].strip()


def _strip_series_prefix(item_title: str, series_title: str):
    normalized_title = item_title.strip()
    normalized_series = (series_title or "").strip()
    if not normalized_series:
        return normalized_title

    if not normalized_title.startswith(normalized_series):
        return normalized_title

    # Remove common separators used between series and chapter labels.
    suffix = normalized_title[len(normalized_series):].lstrip(
        " \t\r\n-:|/\\\u3000\uff1a\uff5c\uff0f"
    )
    return suffix or normalized_title


def scrape(url, free_only=False):
    latest_chapter = "No chapters found"
    timestamp = datetime.datetime.now().strftime("%Y/%m/%d")

    rss_url = _build_rss_url(url)
    if not rss_url:
        return (
            latest_chapter,
            timestamp,
            False,
            "Unable to parse comic ID from URL",
            None,
        )

    try:
        response = requests.get(
            rss_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logging.warning("Failed to fetch Nico Nico Manga RSS %s: %s", rss_url, exc)
        return latest_chapter, timestamp, False, f"Failed to fetch RSS feed: {exc}", None

    soup = BeautifulSoup(response.content, "xml")
    latest_item = soup.find("item")
    if not latest_item:
        return latest_chapter, timestamp, False, "No RSS item found", None

    series_title = _extract_series_title(soup)
    title_tag = latest_item.find("title")
    if title_tag and title_tag.text:
        raw_title = title_tag.get_text(strip=True)
        latest_chapter = _strip_series_prefix(raw_title, series_title)

    chapter_url = None
    link_tag = latest_item.find("link")
    if link_tag and link_tag.text:
        chapter_url = link_tag.get_text(strip=True)

    if not chapter_url:
        guid_tag = latest_item.find("guid")
        if guid_tag and guid_tag.text:
            guid_value = guid_tag.get_text(strip=True)
            if guid_value.startswith("https://") or guid_value.startswith("http://"):
                chapter_url = guid_value

    error = None
    pub_date_tag = latest_item.find("pubDate")
    if pub_date_tag and pub_date_tag.text:
        try:
            parsed_date = parsedate_to_datetime(pub_date_tag.get_text(strip=True))
            timestamp = parsed_date.strftime("%Y/%m/%d")
        except (TypeError, ValueError) as exc:
            logging.warning("Unable to parse pubDate for %s: %s", rss_url, exc)
            error = f"Unable to parse pubDate: {exc}"

    return latest_chapter, timestamp, True, error, chapter_url
