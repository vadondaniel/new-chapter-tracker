import datetime
import logging
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from scraper_utils import needs_update

DOMAINS = ["ichicomi.com"]

def scrape(url, previous_data, force_update=False):
    if not needs_update(url, previous_data, 10, force_update):
        return previous_data[url]["last_found"], previous_data[url]["timestamp"]

    latest_chapter, timestamp = "No new chapter found", datetime.datetime.now().strftime("%Y/%m/%d")

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/117.0 Safari/537.36"
        ),
        "Referer": "https://ichicomi.com/",
    }

    try:
        page = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(page.text, "html.parser")
        title_tag = soup.select_one("h1.series-header-title")
        if not title_tag:
            logging.warning(f"Series title not found for {url}")
            return latest_chapter, timestamp

        series_title = title_tag.text.strip()
        search_url = f"https://ichicomi.com/search?q={series_title}"
        search_page = requests.get(search_url, headers=HEADERS)
        search_soup = BeautifulSoup(search_page.text, "html.parser")
        latest_chapter_link = search_soup.select_one("a.SearchResultItem_sub_link__BB9Z8")
        if not latest_chapter_link:
            logging.warning(f"No latest chapter link found for {series_title}")
            return latest_chapter, timestamp

        latest_url = urljoin("https://ichicomi.com", latest_chapter_link["href"])
        chapter_page = requests.get(latest_url, headers=HEADERS)
        chapter_soup = BeautifulSoup(chapter_page.text, "html.parser")
        chapter_title_tag = chapter_soup.select_one(".episode-header-title")
        if chapter_title_tag:
            latest_chapter = chapter_title_tag.text.strip()

        date_tag = chapter_soup.select_one(".episode-header-date")
        if date_tag:
            raw_date = date_tag.text.strip()
            match = re.match(r"(\d{4})?(\d{2})?(\d{2})?", raw_date)
            if match:
                timestamp = f"{match.group(1)}/{match.group(2)}/{match.group(3)}"
    except Exception as e:
        logging.error(f"Error scraping {url}: {e}")

    return latest_chapter, timestamp
