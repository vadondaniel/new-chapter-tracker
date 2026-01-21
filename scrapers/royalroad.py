import datetime

import requests
from bs4 import BeautifulSoup

DOMAINS = ["royalroad.com"]
SUPPORTS_FREE_TOGGLE = False
SCRAPER_NAME = "Royal Road"


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
    channel = soup.find("channel")
    if not channel:
        return "No channel found", timestamp, False, "No channel found"
    
    channel_title_tag = channel.find("title")
    channel_title = channel_title_tag.get_text(strip=True) if channel_title_tag else ""
    
    latest_item = soup.find("item")
    if latest_item:
        title_tag = latest_item.find("title")
        chapter_title = title_tag.get_text(strip=True) if title_tag else "Unknown Chapter"
        
        if channel_title and chapter_title.startswith(channel_title):
            chapter_title = chapter_title[len(channel_title):].strip(" -")
            
        pub_date_tag = latest_item.find("pubDate")
        if pub_date_tag:
            pub_date = pub_date_tag.get_text(strip=True)
            try:
                timestamp = datetime.datetime.strptime(
                    pub_date, "%a, %d %b %Y %H:%M:%S %Z"
                ).strftime("%Y/%m/%d")
            except ValueError:
                pass
        
        link_tag = latest_item.find("link")
        chapter_url = link_tag.get_text(strip=True) if link_tag else None
        
        success = True
        return {
            "last_found": chapter_title,
            "timestamp": timestamp,
            "success": success,
            "error": None,
            "last_found_url": chapter_url,
        }

    return "No chapters found", timestamp, False, "No chapters found"
