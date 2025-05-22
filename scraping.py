import requests
import json
from bs4 import BeautifulSoup
import os
import datetime
from dateutil import parser
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask_socketio import SocketIO, emit

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logging.basicConfig(level=logging.INFO)

LINKS_FILE = "links.json"
MANGA_LINKS_FILE = "manga_links.json"
DATA_FILE = "scraped_data.json"
MANGA_DATA_FILE = "manga_scraped_data.json"
update_in_progress = False

# socketio will be set by new_chapters.py
socketio = None

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

def wait_for_chromedriver():
    while True:
        try:
            options = webdriver.ChromeOptions()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
            driver.quit()
            logging.info("ChromeDriver is available.")
            break
        except Exception as e:
            logging.error(f"ChromeDriver not available: {e}")
            time.sleep(5)  # Wait for 5 seconds before retrying

def scrape_website(url, previous_data, force_update=False):
    try:
        start_time = time.time()
        latest_chapter = "No new chapter found"
        timestamp = datetime.datetime.now().strftime("%Y/%m/%d")
        
        if "ichijin-plus.com" in url:
            if force_update or url not in previous_data or (datetime.datetime.now() - datetime.datetime.strptime(previous_data[url]["timestamp"], "%Y/%m/%d")).days > 10:
                response = requests.get(url).content
                soup = BeautifulSoup(response, "html.parser")
                
                # Try to extract from embedded JSON if normal method fails
                script = soup.find("script", id="__NEXT_DATA__")
                if script:
                    try:
                        data = json.loads(script.string)
                        latest_episode = data["props"]["pageProps"]["fallbackData"]["comicResponse"]["latest_episode"]
                        chapter_text = latest_episode.get("title", "No title found")
                        published_at = latest_episode.get("published_at")
                        if published_at:
                            # published_at: "2025-04-27T11:00:00.000+09:00"
                            timestamp = datetime.datetime.strptime(published_at[:10], "%Y-%m-%d").strftime("%Y/%m/%d")
                        latest_chapter = chapter_text
                    except Exception as e:
                        logging.error(f"Error parsing __NEXT_DATA__ JSON: {e}")
        elif "royalroad.com" in url:
            if force_update or url not in previous_data or (datetime.datetime.now() - datetime.datetime.strptime(previous_data[url]["timestamp"], "%Y/%m/%d")).days > 2:
                url_parts = url.split('/')
                if len(url_parts) > 4:
                    api_url = f"https://www.royalroad.com/fiction/syndication/{url_parts[4]}"
                response = requests.get(api_url).content
                soup = BeautifulSoup(response, "xml")
                
                # Extract the channel title
                channel_title = soup.find("channel").find("title").get_text(strip=True)
                
                latest_chapter = soup.find("item")
                if latest_chapter:
                    chapter_title = latest_chapter.find("title").get_text(strip=True) if latest_chapter.find("title") else "No title found"
                    # Remove the channel title from the item title
                    if chapter_title.startswith(channel_title):
                        chapter_title = chapter_title[len(channel_title):].strip(" -")
                    pub_date = latest_chapter.find("pubDate").get_text(strip=True) if latest_chapter.find("pubDate") else "No date found"
                    timestamp = datetime.datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z").strftime("%Y/%m/%d")
                    latest_chapter = f"{chapter_title}"
                else:
                    latest_chapter = "No new chapter found"
                    timestamp = datetime.datetime.now().strftime("%Y/%m/%d")
        elif "web-ace.jp" in url:
            if force_update or url not in previous_data or (datetime.datetime.now() - datetime.datetime.strptime(previous_data[url]["timestamp"], "%Y.%m.%d")).days > 10:
                response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
                soup = BeautifulSoup(response.text, "html.parser")
                latest_chapter_div = soup.find("div", class_="media-body")
                if latest_chapter_div:
                    updated_date = latest_chapter_div.find("span", class_="updated-date").get_text(strip=True)
                    chapter_text = latest_chapter_div.find("p", class_="text-bold").get_text(strip=True)
                    updated_date_parts = updated_date.split('.')
                    updated_date_padded = '.'.join(part.zfill(2) for part in updated_date_parts)
                    timestamp = datetime.datetime.strptime(updated_date_padded, "%Y.%m.%d").strftime("%Y/%m/%d") if updated_date else datetime.datetime.now().strftime("%Y/%m/%d")
                    latest_chapter = f"{chapter_text}"
        elif "kemono.su" in url:
            if force_update or url not in previous_data or (datetime.datetime.now() - datetime.datetime.strptime(previous_data[url]["timestamp"], "%Y/%m/%d")).days > 5:
                api_url = url.replace("kemono.su", "kemono.su/api/v1")
                response = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0"})
                data = response.json()
                if data and len(data) > 0:
                    latest_post = data[0]
                    latest_chapter = latest_post["title"]
                    timestamp = parser.parse(latest_post["published"]).strftime("%Y/%m/%d")
        elif "jnovels.com" in url: # doesnt seem to work :/ need to debug later
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(response.text, "html.parser")
            post_container = soup.find("div", class_="post-container post-loaded fade-in")
            if post_container:
                post_header = post_container.find("header", class_="post-header")
                post_meta = post_container.find("div", class_="post-meta")
                if post_header and post_meta:
                    chapter_text = post_header.find("h1", class_="post-title entry-title").get_text(strip=True)
                    updated_date = post_meta.find("time", class_="updated").get("datetime").strip()
                    timestamp = datetime.datetime.strptime(updated_date, "%Y-%m-%d").strftime("%Y/%m/%d")
                    latest_chapter = f"{chapter_text}"
        else:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(response.text, "html.parser")
            latest_chapter = "Unsupported website"
            timestamp = datetime.datetime.now().strftime("%Y/%m/%d")
        
        end_time = time.time()
        elapsed = end_time - start_time
        link_name = previous_data[url]['name'] if url in previous_data and 'name' in previous_data[url] else 'New Link'
        logging.info(
            f"Scraping done in {elapsed:.2f} seconds for URL: {url} ({link_name})"
        )
        return latest_chapter, timestamp
    except Exception as e:
        logging.error(f"Error scraping {url}: {e}")
        return f"Error: {e}", datetime.datetime.now().strftime("%Y/%m/%d")

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
                new_data[link["url"]] = {"name": link["name"], "last_found": scraped_text, "timestamp": timestamp}
                # logging.info(f"Scraped {link['url']}: {new_data[link['url']]}")
                socketio.emit('update_progress', {'current': i, 'total': total_links})
            except Exception as e:
                logging.error(f"Error scraping {link['url']}: {e}")
    socketio.emit('update_complete')
    update_in_progress = False
    logging.info("Scraping all links completed.")
    return new_data