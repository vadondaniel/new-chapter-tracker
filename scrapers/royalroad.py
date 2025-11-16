import datetime

import requests
from bs4 import BeautifulSoup

DOMAINS = ["royalroad.com"]
SUPPORTS_FREE_TOGGLE = False

def scrape(url, free_only=False):
    success = False
    error = None
    timestamp = datetime.datetime.now().strftime("%Y/%m/%d")
    url_parts = url.split("/")
    if len(url_parts) > 4:
        api_url = f"https://www.royalroad.com/fiction/syndication/{url_parts[4]}"
    else:
        error = "Invalid RoyalRoad URL"
        return "Invalid RoyalRoad URL", timestamp, False, error

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
        success = True
        return chapter_title, timestamp, success, None

    return "No chapters found", timestamp, False, "No chapters found"
