import datetime

import cloudscraper
from bs4 import BeautifulSoup

from scraper_utils import parse_timestamp

DOMAINS = ["novelupdates.com"]
SUPPORTS_FREE_TOGGLE = False
SCRAPER_NAME = "Novel Updates"

def scrape(url, free_only=False):
    # use cloudscraper to bypass Cloudflare
    scraper = cloudscraper.create_scraper()
    try:
        response = scraper.get(url, timeout=15)
    except Exception:
        return (
            "Connection error",
            datetime.datetime.now().strftime("%Y/%m/%d"),
            False,
            None,
        )

    soup = BeautifulSoup(response.content, "html.parser")
    row = soup.select_one("#myTable tbody tr")

    if not row:
        return (
            "No chapters found",
            datetime.datetime.now().strftime("%Y/%m/%d"),
            False,
            None,
        )

    title_tag = row.select_one("td:nth-of-type(3) span")
    time_tag = row.select_one("td:nth-of-type(1)")

    chapter_text = title_tag.text.strip() if title_tag else "No title found"
    time_value = time_tag.text.strip() if time_tag and time_tag.text else ""
    date_portion = time_value.split()[0] if time_value else ""
    try:
        timestamp = parse_timestamp(date_portion, "%m/%d/%y")
    except (ValueError, IndexError):
        timestamp = datetime.datetime.now().strftime("%Y/%m/%d")

    return chapter_text, timestamp, True, None
