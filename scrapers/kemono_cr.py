import datetime

import requests
from dateutil import parser

DOMAINS = ["kemono.cr"]
SUPPORTS_FREE_TOGGLE = False
SCRAPER_NAME = "Kemono"


def scrape(url, free_only=False):
    timestamp = datetime.datetime.now().strftime("%Y/%m/%d")
    api_url = url.replace("kemono.cr", "kemono.cr/api/v1") + "/posts"
    try:
        response = requests.get(
            api_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/css"},
            timeout=15
        )
        data = response.json()
    except (requests.RequestException, ValueError):
        return "Connection error", timestamp, False, "Failed to fetch or parse API"
    if data and len(data) > 0:
        latest_post = data[0]
        latest_chapter = latest_post["title"]
        timestamp = parser.parse(latest_post["published"]).strftime("%Y/%m/%d")
        service, user_id, post_id = latest_post.get("service"), latest_post.get("user"), latest_post.get("id")
        post_url = f"https://kemono.cr/{service}/user/{user_id}/post/{post_id}"
        return latest_chapter, timestamp, True, None, post_url
    return (
        "No new post found",
        timestamp,
        False,
        "No posts in feed",
    )
