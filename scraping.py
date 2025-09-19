import os
import json
import logging
import re
import datetime
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from dateutil import parser
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(level=logging.INFO)

update_in_progress = False
socketio = None  # Set externally

# --------------------- JSON Helpers ---------------------
def load_json(file_path, default):
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(default, f)
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, type(default)) else default

def save_json(data, file_path):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        
def load_links(file_path):
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump([], f)
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, list):
            return data
    return []

def save_links(links, file_path):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(links, f, indent=4)

def save_data(data, file_path):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_previous_data(file_path):
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({}, f)
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)
    return {}

# --------------------- Selenium Manager ---------------------
class BrowserManager:
    _instance = None

    def __init__(self):
        options = Options()
        # Headless Chrome mode
        options.add_argument('--headless=new')  # Use the new headless mode (Chrome 109+)

        # System and performance flags
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--mute-audio')
        options.add_argument('--metrics-recording-only')

        # Disable unnecessary features
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-infobars')
        options.add_argument('--disable-notifications')
        options.add_argument('--disable-cloud-import')
        options.add_argument('--disable-sync')
        options.add_argument('--disable-client-side-phishing-detection')
        options.add_argument('--disable-background-networking')
        options.add_argument('--disable-background-timer-throttling')
        options.add_argument('--disable-backgrounding-occluded-windows')
        options.add_argument('--disable-component-update')
        options.add_argument('--disable-default-apps')

        # Privacy and identity
        options.add_argument('--no-first-run')
        options.add_argument('--no-default-browser-check')
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--guest')
        
        # Suppress logs
        options.add_argument("--log-level=3")
        self.driver = webdriver.Chrome(
            service=ChromeService(ChromeDriverManager().install()),
            options=options
        )

    @classmethod
    def get_driver(cls):
        if cls._instance is None:
            cls._instance = BrowserManager()
        return cls._instance.driver

    @classmethod
    def quit_driver(cls):
        if cls._instance:
            cls._instance.driver.quit()
            cls._instance = None

# --------------------- Scraper Utilities ---------------------
def needs_update(url, previous_data, max_days, force_update):
    if force_update or url not in previous_data:
        return True
    last_ts = previous_data[url]["timestamp"]
    last_date = datetime.datetime.strptime(last_ts, "%Y/%m/%d")
    return (datetime.datetime.now() - last_date).days > max_days

def parse_timestamp(date_str, fmt="%Y-%m-%d"):
    return datetime.datetime.strptime(date_str[:10], fmt).strftime("%Y/%m/%d")

# --------------------- Individual Scrapers ---------------------
def scrape_ichicomi(url, previous_data, force_update=False):
    # Same update check logic
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
        # Step 1: Fetch the series/first-episode page to get the title
        page = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(page.text, "html.parser")
        title_tag = soup.select_one("h1.series-header-title")
        if not title_tag:
            logging.warning(f"Series title not found for {url}")
            return latest_chapter, timestamp

        series_title = title_tag.text.strip()

        # Step 2: Fetch the search results page
        search_url = f"https://ichicomi.com/search?q={series_title}"
        search_page = requests.get(search_url, headers=HEADERS)
        search_soup = BeautifulSoup(search_page.text, "html.parser")

        # Step 3: Find the latest chapter link from search results
        latest_chapter_link = search_soup.select_one("a.SearchResultItem_sub_link__BB9Z8")
        if not latest_chapter_link:
            logging.warning(f"No latest chapter link found for {series_title}")
            return latest_chapter, timestamp

        latest_url = urljoin("https://ichicomi.com", latest_chapter_link["href"])

        # Step 4: Fetch latest chapter page
        chapter_page = requests.get(latest_url, headers=HEADERS)
        chapter_soup = BeautifulSoup(chapter_page.text, "html.parser")

        # Step 5: Extract chapter title
        chapter_title_tag = chapter_soup.select_one(".episode-header-title")
        if chapter_title_tag:
            latest_chapter = chapter_title_tag.text.strip()

        # Step 6: Extract chapter date
        date_tag = chapter_soup.select_one(".episode-header-date")
        if date_tag:
            raw_date = date_tag.text.strip()
            match = re.match(r"(\d{4})年(\d{2})月(\d{2})日", raw_date)
            if match:
                timestamp = f"{match.group(1)}/{match.group(2)}/{match.group(3)}"

    except Exception as e:
        logging.error(f"Error scraping {url}: {e}")

    return latest_chapter, timestamp

def scrape_royalroad(url, previous_data, force_update=False):
    if not needs_update(url, previous_data, 2, force_update):
        return previous_data[url]["last_found"], previous_data[url]["timestamp"]

    url_parts = url.split('/')
    if len(url_parts) > 4:
        api_url = f"https://www.royalroad.com/fiction/syndication/{url_parts[4]}"
    else:
        return "Invalid RoyalRoad URL", datetime.datetime.now().strftime("%Y/%m/%d")

    response = requests.get(api_url).content
    soup = BeautifulSoup(response, "xml")
    channel_title = soup.find("channel").find("title").get_text(strip=True)
    latest_item = soup.find("item")
    if latest_item:
        chapter_title = latest_item.find("title").get_text(strip=True)
        if chapter_title.startswith(channel_title):
            chapter_title = chapter_title[len(channel_title):].strip(" -")
        pub_date = latest_item.find("pubDate").get_text(strip=True)
        timestamp = datetime.datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z").strftime("%Y/%m/%d")
        return chapter_title, timestamp
    return "No new chapter found", datetime.datetime.now().strftime("%Y/%m/%d")

def scrape_web_ace(url, previous_data, force_update=False):
    if not needs_update(url, previous_data, 10, force_update):
        return previous_data[url]["last_found"], previous_data[url]["timestamp"]

    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(response.text, "html.parser")
    latest_chapter_div = soup.find("div", class_="media-body")
    if latest_chapter_div:
        updated_date = latest_chapter_div.find("span", class_="updated-date").get_text(strip=True)
        chapter_text = latest_chapter_div.find("p", class_="text-bold").get_text(strip=True)
        # Ensure date parts are zero-padded
        updated_date_parts = updated_date.split('.')
        updated_date_padded = '.'.join(part.zfill(2) for part in updated_date_parts)
        timestamp = datetime.datetime.strptime(updated_date_padded, "%Y.%m.%d").strftime("%Y/%m/%d") if updated_date else datetime.datetime.now().strftime("%Y/%m/%d")
        return chapter_text, timestamp
    return "No new chapter found", datetime.datetime.now().strftime("%Y/%m/%d")

def scrape_kemono_cr(url, previous_data, force_update=False):
    if not needs_update(url, previous_data, 5, force_update):
        return previous_data[url]["last_found"], previous_data[url]["timestamp"]

    api_url = url.replace("kemono.cr", "kemono.cr/api/v1") + "/posts"
    response = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/css"})
    data = response.json()
    if data and len(data) > 0:
        latest_post = data[0]
        latest_chapter = latest_post["title"]
        timestamp = parser.parse(latest_post["published"]).strftime("%Y/%m/%d")
        return latest_chapter, timestamp
    return "No new post found", datetime.datetime.now().strftime("%Y/%m/%d")

def scrape_jnovels(url, previous_data, force_update=False):
    if not needs_update(url, previous_data, 10, force_update):
        return previous_data[url]["last_found"], previous_data[url]["timestamp"]

    response = requests.get(url)
    
    soup = BeautifulSoup(response.content, "html.parser")
    posts = soup.select("div.post-container")
    
    if not posts:
        return "No new chapter found", datetime.datetime.now().strftime("%Y/%m/%d")

    latest_post = posts[0]
    title_tag = latest_post.select_one("h1.post-title a")
    time_tag = latest_post.select_one("time.updated")

    chapter_text = title_tag.text.strip() if title_tag else "No title found"
    timestamp = parse_timestamp(time_tag["datetime"]) if time_tag else datetime.datetime.now().strftime("%Y/%m/%d")
    
    return chapter_text, timestamp

def convert_to_rss_url(url: str) -> str:
    """Convert a Nyaa.si search URL to its RSS feed equivalent."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    # Ensure RSS page param
    query["page"] = ["rss"]

    rss_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        urlencode(query, doseq=True),
        parsed.fragment
    ))
    return rss_url

def scrape_nyaa(url, previous_data, force_update=False):
    if not needs_update(url, previous_data, 2, force_update):
        return previous_data[url]["last_found"], previous_data[url]["timestamp"]

    rss_url = convert_to_rss_url(url)

    # retry logic
    max_retries = 3
    delay = 2
    for attempt in range(max_retries):
        try:
            response = requests.get(rss_url, timeout=10)
            response.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                datetime.time.sleep(delay)
            else:
                return f"Request failed after {max_retries} retries: {e}", datetime.datetime.now().strftime("%Y/%m/%d")

    soup = BeautifulSoup(response.content, "xml")
    latest_item = soup.find("item")
    if latest_item:
        title = latest_item.find("title").get_text(strip=True)
        pub_date = latest_item.find("pubDate").get_text(strip=True)
        timestamp = datetime.datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z").strftime("%Y/%m/%d")
        return title, timestamp

    return "No new torrent found", datetime.datetime.now().strftime("%Y/%m/%d")

def scrape_generic(url, previous_data, force_update=False):
    return "Unsupported website", datetime.datetime.now().strftime("%Y/%m/%d")

# --------------------- Scraper Dispatcher ---------------------
SCRAPERS = {
    "ichicomi.com": scrape_ichicomi,
    "royalroad.com": scrape_royalroad,
    "web-ace.jp": scrape_web_ace,
    "kemono.cr": scrape_kemono_cr,
    "jnovels.com": scrape_jnovels,
    "nyaa.si": scrape_nyaa,
}

def scrape_website(url, previous_data, force_update=False):
    for domain, scraper in SCRAPERS.items():
        if domain in url:
            return scraper(url, previous_data, force_update)
    return scrape_generic(url, previous_data, force_update)

# --------------------- Main Scraper ---------------------
def scrape_all_links(links, previous_data, force_update=False):
    global update_in_progress
    update_in_progress = True
    new_data = {}
    total_links = len(links)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(scrape_website, link["url"], previous_data, force_update): link for link in links}
        for i, future in enumerate(as_completed(futures), 1):
            link = futures[future]
            try:
                scraped_text, timestamp = future.result()
                new_data[link["url"]] = {
                    "name": link["name"],
                    "last_found": scraped_text,
                    "timestamp": timestamp
                }
                if socketio:
                    socketio.emit('update_progress', {'current': i, 'total': total_links})
            except Exception as e:
                logging.error(f"Error scraping {link['url']}: {e}")

    if socketio:
        socketio.emit('update_complete')
    update_in_progress = False
    logging.info("Scraping all links completed.")
    return new_data

# --------------------- Pipeline ---------------------
def scrape_pipeline(links_file, data_file, force_update=False):
    links = load_json(links_file, default=[])
    previous_data = load_json(data_file, default={})
    new_data = scrape_all_links(links, previous_data, force_update)
    save_json(new_data, data_file)
    return new_data

# --------------------- Clean Shutdown ---------------------
def shutdown_scraper():
    BrowserManager.quit_driver()
