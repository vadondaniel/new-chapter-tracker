import datetime

import requests
from dateutil import parser

DOMAINS = ["kemono.cr"]
SUPPORTS_FREE_TOGGLE = False

def scrape(url, free_only=False):
    timestamp = datetime.datetime.now().strftime("%Y/%m/%d")
    api_url = url.replace("kemono.cr", "kemono.cr/api/v1") + "/posts"
    response = requests.get(
        api_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/css"}
    )
    data = response.json()
    if data and len(data) > 0:
        latest_post = data[0]
        latest_chapter = latest_post["title"]
        timestamp = parser.parse(latest_post["published"]).strftime("%Y/%m/%d")
        return latest_chapter, timestamp, True, None
    return (
        "No new post found",
        timestamp,
        False,
        "No posts in feed",
    )
