import os
import json
import logging
import time
import datetime
from dateutil import parser
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

from flask_socketio import SocketIO

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(level=logging.INFO)

# --------------------- File Paths ---------------------
LINKS_FILE = "links.json"
MANGA_LINKS_FILE = "manga_links.json"
DATA_FILE = "scraped_data.json"
MANGA_DATA_FILE = "manga_scraped_data.json"

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
        
def load_links(file_path=LINKS_FILE):
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump([], f)
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, list):
            return data
    return []

def save_links(links, file_path=LINKS_FILE):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(links, f, indent=4)

def save_data(data, file_path=DATA_FILE):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_previous_data(file_path=DATA_FILE):
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
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
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
def scrape_ichijin(url, previous_data, force_update=False):
    if not needs_update(url, previous_data, 10, force_update):
        return previous_data[url]["last_found"], previous_data[url]["timestamp"]

    response = requests.get(url).content
    soup = BeautifulSoup(response, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    latest_chapter, timestamp = "No new chapter found", datetime.datetime.now().strftime("%Y/%m/%d")
    
    if script:
        try:
            data = json.loads(script.string)
            latest_episode = data["props"]["pageProps"]["fallbackData"]["comicResponse"]["latest_episode"]
            chapter_text = latest_episode.get("title", "No title found")
            published_at = latest_episode.get("published_at")
            if published_at:
                timestamp = parse_timestamp(published_at)
            latest_chapter = chapter_text
        except Exception as e:
            logging.error(f"Error parsing __NEXT_DATA__ JSON: {e}")
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

    driver = BrowserManager.get_driver()
    driver.get(url)

    try:
        wait = WebDriverWait(driver, 10)
        post_container = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.post-container.post-loaded.fade-in"))
        )
        post_header = post_container.find_element(By.CSS_SELECTOR, "header.post-header")
        post_meta = post_container.find_element(By.CSS_SELECTOR, "div.post-meta")
        chapter_text = post_header.find_element(By.CSS_SELECTOR, "h1.post-title.entry-title").text.strip()
        updated_date = post_meta.find_element(By.CSS_SELECTOR, "time.updated").get_attribute("datetime").strip()
        timestamp = parse_timestamp(updated_date)
        return chapter_text, timestamp
    except Exception as e:
        logging.error(f"Error scraping jnovels.com {url}: {e}")
        return "Error scraping jnovels.com", datetime.datetime.now().strftime("%Y/%m/%d")

def scrape_generic(url, previous_data, force_update=False):
    return "Unsupported website", datetime.datetime.now().strftime("%Y/%m/%d")

# --------------------- Scraper Dispatcher ---------------------
SCRAPERS = {
    "ichijin-plus.com": scrape_ichijin,
    "royalroad.com": scrape_royalroad,
    "web-ace.jp": scrape_web_ace,
    "kemono.cr": scrape_kemono_cr,
    "jnovels.com": scrape_jnovels,
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
