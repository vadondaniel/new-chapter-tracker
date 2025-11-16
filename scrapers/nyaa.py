import datetime

import requests
from bs4 import BeautifulSoup

from scraper_utils import needs_update, convert_to_rss_url

DOMAINS = ["nyaa.si"]

def scrape(url, previous_data, force_update=False):
    if not needs_update(url, previous_data, 2, force_update):
        return previous_data[url]["last_found"], previous_data[url]["timestamp"]

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
                datetime.time.sleep(delay)
            else:
                return f"Request failed after {max_retries} retries: {e}", datetime.datetime.now().strftime("%Y/%m/%d")

    soup = BeautifulSoup(response.content, "xml")
    latest_item = soup.find("item")
    if latest_item:
        title = latest_item.find("title").get_text(strip=True)
        pub_date = latest_item.find("pubDate").get_text(strip=True)
        timestamp = datetime.datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z").strftime("%Y/%m/%d")
        return title, timestamp

    return "No new torrent found", datetime.datetime.now().strftime("%Y/%m/%d")
