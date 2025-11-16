import datetime
import logging
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from scraper_utils import needs_update

DOMAINS = ["ichicomi.com"]

FREE_ONLY_DEFAULT = True

def scrape(url, previous_data, force_update=False):
    if not needs_update(url, previous_data, 10, force_update):
        return previous_data[url]["last_found"], previous_data[url]["timestamp"]

    latest_chapter = "No new chapter found"
    timestamp = datetime.datetime.now().strftime("%Y/%m/%d")

    entry = previous_data.get(url, {})
    free_only = entry.get("free_only", FREE_ONLY_DEFAULT)

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
        rss_link = soup.find("link", rel="alternate", type="application/rss+xml")
        if not rss_link or not rss_link.get("href"):
            logging.warning("RSS feed link missing for %s, cannot check for new chapters", url)
            return latest_chapter, timestamp

        rss_url = urljoin("https://ichicomi.com", rss_link["href"])
        rss_page = requests.get(rss_url, headers=HEADERS, timeout=10)
        rss_soup = BeautifulSoup(rss_page.content, "xml")
        items = rss_soup.find_all("item")

        selected_item = None
        if free_only:
            for item in items:
                if item.find("giga:freeTermStartDate"):
                    selected_item = item
                    break
        else:
            selected_item = items[0] if items else None

        if not selected_item:
            logging.info("No free chapter item found yet for %s", url)
            return latest_chapter, timestamp

        item_title = selected_item.find("title")
        if item_title and item_title.text:
            latest_chapter = item_title.text.strip()

        date_text = None
        free_term_tag = selected_item.find("giga:freeTermStartDate")
        if free_term_tag and free_term_tag.text:
            date_text = free_term_tag.text.strip()
        else:
            pub_date_tag = selected_item.find("pubDate")
            date_text = pub_date_tag.text.strip() if pub_date_tag and pub_date_tag.text else None

        if date_text:
            try:
                parsed_date = parsedate_to_datetime(date_text)
            except (TypeError, ValueError) as date_err:
                logging.warning(
                    "Could not parse date from RSS for %s: %s", url, date_err
                )
            else:
                timestamp = parsed_date.strftime("%Y/%m/%d")
    except requests.RequestException as rss_error:
        logging.warning("Failed to fetch RSS feed for %s: %s", url, rss_error)
    except Exception as e:
        logging.error(f"Error scraping {url}: {e}")

    return latest_chapter, timestamp
