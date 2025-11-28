import datetime
import time

import requests
from bs4 import BeautifulSoup

from scraper_utils import convert_to_rss_url

DOMAINS = ["nyaa.si"]
SUPPORTS_FREE_TOGGLE = False
SCRAPER_NAME = "Nyaa"
SCRAPER_NOTES = ["Supports search query URLs"]


def scrape(url, free_only=False):
    timestamp = datetime.datetime.now().strftime("%Y/%m/%d")
    rss_url = convert_to_rss_url(url)
    max_retries = 3
    delay = 2
    for attempt in range(max_retries):
        try:
            response = requests.get(rss_url, timeout=10)
            response.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                return (
                    f"Request failed after {max_retries} retries: {e}",
                    timestamp,
                    False,
                    str(e),
                )

    soup = BeautifulSoup(response.content, "xml")
    latest_item = soup.find("item")
    if latest_item:
        title = latest_item.find("title").get_text(strip=True)
        pub_date = latest_item.find("pubDate").get_text(strip=True)
        timestamp = datetime.datetime.strptime(
            pub_date, "%a, %d %b %Y %H:%M:%S %z"
        ).strftime("%Y/%m/%d")
        return title, timestamp, True, None

    return "No new torrent found", timestamp, False, "No RSS item found"
