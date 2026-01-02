import datetime

import requests
import re
from bs4 import BeautifulSoup

from scraper_utils import parse_timestamp

DOMAINS = ["rawkuma.net"]
SUPPORTS_FREE_TOGGLE = False
SCRAPER_NAME = "Rawkuma"
SCRAPER_NOTES = [""]


def scrape(url, free_only=False):
    try:
        # Extract manga_id from URL by fetching main page
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return "Failed to fetch main page", datetime.datetime.now().strftime("%Y/%m/%d"), False, None

        soup = BeautifulSoup(resp.content, "html.parser")
        container = soup.select_one("div#chapter-list")
        if not container:
            return "No chapter list found", datetime.datetime.now().strftime("%Y/%m/%d"), False, None

        # Extract manga_id from hx-get attribute using regex
        hx_get = str(container.get("hx-get", ""))
        match = re.search(r"manga_id=(\d+)", hx_get)
        if not match:
            return "No manga_id found", datetime.datetime.now().strftime("%Y/%m/%d"), False, None
        manga_id = match.group(1)

        # Call AJAX endpoint to get chapters
        ajax_url = "https://rawkuma.net/wp-admin/admin-ajax.php"
        params = {"action": "chapter_list", "manga_id": manga_id, "page": "1"}
        ajax_resp = requests.get(ajax_url, params=params, headers={"User-Agent": "Mozilla/5.0"})

        if ajax_resp.status_code != 200:
            return "Failed to fetch chapter list", datetime.datetime.now().strftime("%Y/%m/%d"), False, None

        ajax_soup = BeautifulSoup(ajax_resp.content, "html.parser")
        chapters = ajax_soup.select("div[data-chapter-number]")
        if not chapters:
            return "No chapters found", datetime.datetime.now().strftime("%Y/%m/%d"), False, None

        # Take latest chapter
        latest = chapters[0]

        # Title
        title_tag = latest.select_one("span")
        chapter_title = title_tag.text.strip() if title_tag else "No title found"

        # Timestamp
        time_tag = latest.select_one("time")
        time_value = time_tag.get("datetime") if time_tag else None
        timestamp = parse_timestamp(time_value) if time_value else datetime.datetime.now().strftime("%Y/%m/%d")

        return chapter_title, timestamp, True, None

    except Exception as e:
        return "Error fetching chapters", datetime.datetime.now().strftime("%Y/%m/%d"), False, str(e)
