import importlib
import pkgutil
import os
import json
import logging
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import scrapers
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

# --------------------- Scraper Plugins ---------------------
def load_scraper_plugins():
    registry = {}
    package = scrapers
    for finder, name, ispkg in pkgutil.iter_modules(package.__path__):
        if name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{package.__name__}.{name}")
        except Exception as exc:
            logging.exception("Failed to import scraper plugin %s: %s", name, exc)
            continue

        scrape_func = getattr(module, "scrape", None)
        domains = getattr(module, "DOMAINS", [])
        if not callable(scrape_func) or not domains:
            logging.warning("Plugin %s missing scrape entry point or domains", name)
            continue

        for domain in domains:
            registry[domain] = scrape_func

    if not registry:
        logging.warning("No scraper plugins were loaded.")
    return registry

SCRAPERS = load_scraper_plugins()

def scrape_website(url, previous_data, force_update=False):
    for domain, scraper in SCRAPERS.items():
        if domain in url:
            return scraper(url, previous_data, force_update)
    return "Unsupported website", datetime.datetime.now().strftime("%Y/%m/%d")

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
                entry = previous_data.get(link["url"], {})
                new_data[link["url"]] = {
                    "name": link["name"],
                    "last_found": scraped_text,
                    "timestamp": timestamp,
                    "free_only": entry.get("free_only", True)
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
