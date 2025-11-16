import datetime

import requests
from bs4 import BeautifulSoup

from scraper_utils import needs_update

DOMAINS = ["web-ace.jp"]

def scrape(url, previous_data, force_update=False):
    if not needs_update(url, previous_data, 10, force_update):
        return previous_data[url]["last_found"], previous_data[url]["timestamp"]

    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(response.text, "html.parser")
    latest_chapter_div = soup.find("div", class_="media-body")
    if latest_chapter_div:
        updated_date = latest_chapter_div.find("span", class_="updated-date").get_text(strip=True)
        chapter_text = latest_chapter_div.find("p", class_="text-bold").get_text(strip=True)
        updated_date_parts = updated_date.split(".")
        updated_date_padded = ".".join(part.zfill(2) for part in updated_date_parts)
        timestamp = (
            datetime.datetime.strptime(updated_date_padded, "%Y.%m.%d").strftime("%Y/%m/%d")
            if updated_date
            else datetime.datetime.now().strftime("%Y/%m/%d")
        )
        return chapter_text, timestamp
    return "No new chapter found", datetime.datetime.now().strftime("%Y/%m/%d")
