import datetime

import requests
from bs4 import BeautifulSoup

from scraper_utils import needs_update

DOMAINS = ["royalroad.com"]

def scrape(url, previous_data, force_update=False):
    if not needs_update(url, previous_data, 2, force_update):
        return previous_data[url]["last_found"], previous_data[url]["timestamp"]

    url_parts = url.split("/")
    if len(url_parts) > 4:
        api_url = f"https://www.royalroad.com/fiction/syndication/{url_parts[4]}"
    else:
        return "Invalid RoyalRoad URL", datetime.datetime.now().strftime("%Y/%m/%d")

    response = requests.get(api_url).content
    soup = BeautifulSoup(response, "xml")
    channel_title = soup.find("channel").find("title").get_text(strip=True)
    latest_item = soup.find("item")
    if latest_item:
        chapter_title = latest_item.find("title").get_text(strip=True)
        if chapter_title.startswith(channel_title):
            chapter_title = chapter_title[len(channel_title):].strip(" -")
        pub_date = latest_item.find("pubDate").get_text(strip=True)
        timestamp = datetime.datetime.strptime(
            pub_date, "%a, %d %b %Y %H:%M:%S %Z"
        ).strftime("%Y/%m/%d")
        return chapter_title, timestamp

    return "No new chapter found", datetime.datetime.now().strftime("%Y/%m/%d")
