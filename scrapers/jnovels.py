import datetime

import requests
from bs4 import BeautifulSoup

from scraper_utils import parse_timestamp

DOMAINS = ["jnovels.com"]
SUPPORTS_FREE_TOGGLE = False

def scrape(url, free_only=False):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, "html.parser")
    posts = soup.select("div.post-container")

    if not posts:
        return (
            "No chapters found",
            datetime.datetime.now().strftime("%Y/%m/%d"),
            False,
            None,
        )

    latest_post = posts[0]
    title_tag = latest_post.select_one("h1.post-title a")
    time_tag = latest_post.select_one("time.updated")

    chapter_text = title_tag.text.strip() if title_tag else "No title found"
    timestamp = (
        parse_timestamp(time_tag["datetime"]) if time_tag else datetime.datetime.now().strftime("%Y/%m/%d")
    )

    return chapter_text, timestamp, True, None
