import datetime

import requests
from dateutil import parser

from scraper_utils import needs_update

DOMAINS = ["kemono.cr"]
SUPPORTS_FREE_TOGGLE = True

def scrape(url, previous_data, force_update=False):
    if not needs_update(url, previous_data, 5, force_update):
        return previous_data[url]["last_found"], previous_data[url]["timestamp"]

    api_url = url.replace("kemono.cr", "kemono.cr/api/v1") + "/posts"
    response = requests.get(
        api_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/css"}
    )
    data = response.json()
    if data and len(data) > 0:
        latest_post = data[0]
        latest_chapter = latest_post["title"]
        timestamp = parser.parse(latest_post["published"]).strftime("%Y/%m/%d")
        return latest_chapter, timestamp
    return "No new post found", datetime.datetime.now().strftime("%Y/%m/%d")
