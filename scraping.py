import importlib
import pkgutil
import logging
import datetime

import scrapers
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

from scraper_utils import needs_update

from db_store import DEFAULT_UPDATE_FREQUENCY

logging.basicConfig(level=logging.INFO)

update_in_progress = False
socketio = None  # Set externally


def category_room_name(category=None):
    name = str(category or "main").strip().lower() or "main"
    return f"category:{name}"

# --------------------- Selenium Manager ---------------------


class BrowserManager:
    _instance = None

    def __init__(self):
        options = Options()
        # Headless Chrome mode
        # Use the new headless mode (Chrome 109+)
        options.add_argument('--headless=new')

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
            logging.exception(
                "Failed to import scraper plugin %s: %s", name, exc)
            continue

        if getattr(module, "HIDE_IN_SUPPORTED_LIST", False):
            continue

        scrape_func = getattr(module, "scrape", None)
        domains = getattr(module, "DOMAINS", [])
        if not callable(scrape_func) or not domains:
            logging.warning(
                "Plugin %s missing scrape entry point or domains", name)
            continue

        supports_free_toggle = getattr(
            module, "SUPPORTS_FREE_TOGGLE", False)
        display_name = getattr(
            module, "SCRAPER_NAME", None) or getattr(module, "DISPLAY_NAME", None)
        if not display_name:
            display_name = name.replace("_", " ").replace("-", " ").title()

        raw_notes = getattr(module, "SCRAPER_NOTES", None)
        notes = []
        if isinstance(raw_notes, str):
            normalized = raw_notes.strip()
            if normalized:
                notes.append(normalized)
        elif isinstance(raw_notes, (list, tuple, set)):
            for entry in raw_notes:
                text = str(entry).strip()
                if text:
                    notes.append(text)

        for domain in domains:
            registry[domain] = {
                "scraper": scrape_func,
                "supports_free_toggle": bool(supports_free_toggle),
                "display_name": display_name,
                "notes": notes,
            }

    if not registry:
        logging.warning("No scraper plugins were loaded.")
    return registry


SCRAPERS = load_scraper_plugins()


def get_supported_sites():
    sites = []
    for domain, plugin in SCRAPERS.items():
        sites.append(
            {
                "domain": domain,
                "display_name": plugin.get("display_name") or domain,
                "supports_free_toggle": plugin.get(
                    "supports_free_toggle", False),
                "notes": plugin.get("notes", []),
            }
        )
    return sorted(sites, key=lambda item: item["display_name"].lower())


def _find_scraper_for_url(url: str):
    for domain, plugin in SCRAPERS.items():
        if domain in url:
            return plugin
    return None


def supports_free_toggle(url: str):
    plugin = _find_scraper_for_url(url)
    return bool(plugin and plugin.get("supports_free_toggle"))


def entry_due_for_scrape(link, entry, force_update=False):
    if force_update or not entry or entry.get("last_found") == "No data" or not entry.get("timestamp"):
        return True
    freq = link.get("update_frequency", DEFAULT_UPDATE_FREQUENCY)
    return needs_update(link["url"], {link["url"]: entry}, freq, False)


def process_link(link, entry, force_update=False):
    if not entry_due_for_scrape(link, entry, force_update):
        free_flag = link.get("free_only", entry.get("free_only", True))
        return (
            {
                "name": link.get("name", entry.get("name", "Unknown")),
                "last_found": entry.get("last_found", "No data"),
                "timestamp": entry.get("timestamp", datetime.datetime.now().strftime("%Y/%m/%d")),
                "free_only": free_flag,
            },
            None,
        )

    try:
        result = scrape_website(link)
    except Exception as exc:
        logging.error("Error scraping %s: %s", link["url"], exc)
        return None, {link["url"]: {"error": str(exc)}}
    chapter, timestamp, success, error = normalize_scrape_result(result)
    if success:
        return (
            {
                "name": link.get("name", entry.get("name", "Unknown")),
                "last_found": chapter,
                "timestamp": timestamp,
                "free_only": link.get("free_only", entry.get("free_only", True)),
            },
            None,
        )
    return None, {link["url"]: {"error": error or f"No data returned from {link['url']}", }}


def scrape_website(link):
    url = link["url"]
    for domain, plugin in SCRAPERS.items():
        if domain in url:
            return plugin["scraper"](url, free_only=link.get("free_only", False))
    return (
        "Unsupported website",
        datetime.datetime.now().strftime("%Y/%m/%d"),
        False,
        "unsupported",
    )

# --------------------- Main Scraper ---------------------


def normalize_scrape_result(result):
    if isinstance(result, dict):
        chapter = result.get("last_found", "No chapters found")
        timestamp = result.get(
            "timestamp", datetime.datetime.now().strftime("%Y/%m/%d"))
        success = result.get("success", True)
        error = result.get("error")
    elif isinstance(result, (list, tuple)):
        chapter, timestamp = result[0], result[1]
        success = len(result) < 3 or bool(result[2])
        error = result[3] if len(result) > 3 else None
    else:
        chapter, timestamp, success, error = (
            str(result),
            datetime.datetime.now().strftime("%Y/%m/%d"),
            True,
            None,
        )
    return chapter, timestamp, success, error


def scrape_all_links(links, previous_data, force_update=False, category=None):
    global update_in_progress
    update_in_progress = True
    new_data = {}
    failures = {}
    total_links = len(links)
    processed = 0
    room = category_room_name(category)
    category_name = (category or "main")

    for link in links:
        entry = previous_data.get(link["url"], {})
        data, failure = process_link(link, entry, force_update)
        processed += 1
        if socketio:
            socketio.emit(
                "update_progress",
                {
                    "current": processed,
                    "total": total_links,
                    "category": category_name,
                },
                namespace="/",
                room=room,
            )
        if data:
            new_data[link["url"]] = data
        if failure:
            failures.update(failure)

    if socketio:
        socketio.emit(
            "update_complete",
            {"category": category_name},
            namespace="/",
            room=room,
        )
    update_in_progress = False
    logging.info("Scraping all links completed.")
    return new_data, failures

# --------------------- Pipeline ---------------------


def shutdown_scraper():
    BrowserManager.quit_driver()
