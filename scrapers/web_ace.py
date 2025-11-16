import datetime
import logging
import re
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

DOMAINS = ["web-ace.jp"]
SUPPORTS_FREE_TOGGLE = False

RSS_TEMPLATE = "https://web-ace.jp/youngaceup/feed/rss/{series_id}/"

def _extract_series_id(url: str) -> Optional[str]:
    path = urlparse(url).path
    match = re.search(r"/contents/(\d+)", path)
    return match.group(1) if match else None

def scrape(url, free_only=False):
    latest_chapter = "No chapters found"
    timestamp = datetime.datetime.now().strftime("%Y/%m/%d")
    success = False
    error = None

    series_id = _extract_series_id(url)
    if not series_id:
        logging.warning("Unable to parse series ID from %s", url)
        return latest_chapter, timestamp, False, "Unable to parse series ID"

    rss_url = RSS_TEMPLATE.format(series_id=series_id)

    try:
        response = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "xml")
        latest_item = soup.find("item")
        if not latest_item:
            return latest_chapter, timestamp, False, "No RSS items"

        title_tag = latest_item.find("title")
        if title_tag and title_tag.text:
            raw_title = title_tag.text.strip()
            bracket_match = re.match(r"^\[([^\]]+)\]", raw_title)
            latest_chapter = bracket_match.group(1) if bracket_match else raw_title

        pub_date_tag = latest_item.find("pubDate")
        if pub_date_tag and pub_date_tag.text:
            try:
                parsed_date = parsedate_to_datetime(pub_date_tag.text.strip())
            except (TypeError, ValueError) as err:
                logging.warning("Unable to parse pubDate for %s: %s", url, err)
                error = f"Unable to parse pubDate: {err}"
            else:
                timestamp = parsed_date.strftime("%Y/%m/%d")
        success = True
        return latest_chapter, timestamp, success, error
    except requests.RequestException as exc:
        logging.warning("Failed to fetch RSS feed %s: %s", rss_url, exc)

    return latest_chapter, timestamp, success, error
