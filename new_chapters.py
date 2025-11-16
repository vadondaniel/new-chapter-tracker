import os
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from apscheduler.schedulers.background import BackgroundScheduler

from scraping import scrape_website, scrape_all_links
from config import CATEGORIES
from data_store import (
    CategoryStorage,
    DEFAULT_FREE_ONLY,
    DEFAULT_UPDATE_FREQUENCY,
)

logging.basicConfig(level=logging.INFO)

# --------------------- File Paths ---------------------
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

FILE_PATHS = {
    "main": {
        "links": os.path.join(DATA_DIR, "links.json"),
        "data": os.path.join(DATA_DIR, "scraped_data.json"),
    }
}

# auto-generate paths from categories
for category in CATEGORIES:
    FILE_PATHS[category] = {
        "links": os.path.join(DATA_DIR, f"{category}_links.json"),
        "data": os.path.join(DATA_DIR, f"{category}_scraped_data.json"),
    }

app = Flask(__name__)
socketio = SocketIO(app)
update_in_progress = False
last_full_update = {key: None for key in FILE_PATHS}

# Pass the socketio object to scraping.py
import scraping
scraping.socketio = socketio

# --------------------- Helpers ---------------------
def resolve_category(category=None):
    if category:
        return category
    path = request.path or ""
    for candidate in CATEGORIES:
        if path.startswith(f"/{candidate}"):
            return candidate
    return "main"


def get_category_storage(category=None):
    resolved = resolve_category(category)
    paths = FILE_PATHS[resolved]
    return CategoryStorage(paths["links"], paths["data"]), resolved


def parse_free_only(value, default):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    value_str = str(value).strip().lower()
    return value_str in {"1", "true", "yes", "y"}


def parse_update_frequency(value, default):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return max(1, int(value))
    text = str(value).strip().lower()
    if not text:
        return default

    multiplier = 1.0
    if text.endswith("d"):
        text = text[:-1]
    elif text.endswith("h"):
        multiplier = 1 / 24
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1 / (24 * 60)
        text = text[:-1]

    try:
        num = float(text)
    except ValueError:
        return default

    freq = num * multiplier
    return max(1, int(freq) if freq.is_integer() else int(freq) + 1)


def get_link_metadata(payload, existing=None):
    existing_freq = existing.get("update_frequency") if existing else DEFAULT_UPDATE_FREQUENCY
    freq = parse_update_frequency(payload.get("update_frequency"), existing_freq)

    existing_free_flag = existing.get("free_only") if existing else DEFAULT_FREE_ONLY
    free_only = parse_free_only(payload.get("free_only"), existing_free_flag)
    return freq, free_only

# --------------------- Background Jobs ---------------------
def force_update_job(category="main"):
    global last_full_update
    with app.app_context():
        logging.info(f"Starting scheduled force update for {category}...")
        store = CategoryStorage(FILE_PATHS[category]["links"], FILE_PATHS[category]["data"])
        links = store.read_links()
        new_data = scrape_all_links(links, store.read_data(), force_update=True)
        store.merge_scraped(new_data)
        last_full_update[category] = datetime.now().isoformat()
        logging.info(f"Scheduled force update for {category} completed.")

def schedule_updates():
    scheduler = BackgroundScheduler(job_defaults={'max_instances': 1})
    scheduler.add_job(
        lambda: force_update_job("main"),
        'interval', hours=1
    )
    for category in CATEGORIES:
        scheduler.add_job(
            lambda c=category: force_update_job(c),
            'interval', hours=5
        )
    scheduler.start()
    
# --------------------- View Logic ---------------------
def index(category=None):
    store, update_type = get_category_storage(category)
    previous_data = store.read_data()

    differences = {url: data for url, data in previous_data.items() if data["last_found"] != data["last_saved"]}
    same_data = {url: data for url, data in previous_data.items() if data["last_found"] == data["last_saved"]}

    differences = dict(sorted(differences.items(), key=lambda x: x[1]["timestamp"], reverse=True))
    same_data = dict(sorted(same_data.items(), key=lambda x: x[1]["timestamp"], reverse=True))

    logging.info(f"Last full update ({update_type}): {last_full_update[update_type]}")
    return render_template(
        "index.html",
        differences=differences,
        same_data=same_data,
        update_in_progress=update_in_progress,
        last_full_update=last_full_update[update_type]
    )

def update(category=None):
    data = request.json
    store, _ = get_category_storage(category)
    previous_data = store.read_data()
    if data["url"] in previous_data:
        previous_data[data["url"]]["last_saved"] = previous_data[data["url"]]["last_found"]
        store.save_data()
    return jsonify({"status": "success"})

def force_update(category=None):
    _, update_type = get_category_storage(category)
    socketio.start_background_task(force_update_job, update_type)
    return jsonify({"status": "started"})

def recheck(category=None):
    data = request.json
    store, _ = get_category_storage(category)
    previous_data = store.read_data()
    if data["url"] in previous_data:
        latest_chapter, timestamp = scrape_website(data["url"], previous_data, force_update=True)
        previous_data[data["url"]]["last_found"] = latest_chapter
        previous_data[data["url"]]["timestamp"] = timestamp
        store.save_data()
    return jsonify({"status": "success"})

def add_link(category=None):
    data = request.json
    store, _ = get_category_storage(category)
    links = store.read_links()
    freq, free_only = get_link_metadata(data)
    new_entry = {
        "name": data["name"],
        "url": data["url"],
        "update_frequency": freq,
        "free_only": free_only,
    }
    if not any(link["url"] == new_entry["url"] for link in links):
        links.append(new_entry)
        store.save_links()
    previous_data = store.read_data()
    latest_chapter, timestamp = scrape_website(new_entry["url"], previous_data, force_update=True)
    previous_data[new_entry["url"]] = {
        "name": new_entry["name"],
        "last_saved": "N/A",
        "last_found": latest_chapter,
        "timestamp": timestamp
    }
    store.save_data()
    return jsonify({"status": "success"})

def edit_link(category=None):
    data = request.json
    orig_url = data.get("original_url")
    new_url = data.get("url")
    new_name = data.get("name")

    store, _ = get_category_storage(category)
    links = store.read_links()

    def normalize(u): return u.replace("http://", "").replace("https://", "")

    updated = False
    for link in links:
        if normalize(link.get("url", "")) == normalize(orig_url or ""):
            freq, free_only = get_link_metadata(data, link)
            link["url"] = new_url
            link["name"] = new_name
            link["update_frequency"] = freq
            link["free_only"] = free_only
            updated = True
            break
    if updated:
        store.save_links()

    previous_data = store.read_data()
    data_modified = False
    for key in list(previous_data.keys()):
        if normalize(key) == normalize(orig_url or ""):
            entry = previous_data.pop(key)
            entry["name"] = new_name
            previous_data[new_url] = entry
            data_modified = True
            break
    if data_modified:
        store.save_data()

    return jsonify({"status": "success"})

def remove_link(category=None):
    data = request.json
    store, _ = get_category_storage(category)
    links = store.read_links()
    def normalize_url(url): return url.replace("http://", "").replace("https://", "")
    input_url = normalize_url(data["url"])
    links = [link for link in links if normalize_url(link["url"]) != input_url]
    store.save_links()
    previous_data = store.read_data()
    keys_to_remove = [url for url in previous_data if normalize_url(url) == input_url]
    for url in keys_to_remove:
        del previous_data[url]
    if keys_to_remove:
        store.save_data()
    return jsonify({"status": "success"})

# --------------------- Routes ---------------------
@app.route("/")
def main_index():
    return index()

# Main routes (no category prefix)
app.add_url_rule("/update", endpoint="main_update", view_func=lambda: update("main"), methods=["POST"])
app.add_url_rule("/force_update", endpoint="main_force_update", view_func=lambda: force_update("main"), methods=["POST"])
app.add_url_rule("/recheck", endpoint="main_recheck", view_func=lambda: recheck("main"), methods=["POST"])
app.add_url_rule("/add", endpoint="main_add", view_func=lambda: add_link("main"), methods=["POST"])
app.add_url_rule("/edit", endpoint="main_edit", view_func=lambda: edit_link("main"), methods=["POST"])
app.add_url_rule("/remove", endpoint="main_remove", view_func=lambda: remove_link("main"), methods=["POST"])

# dynamically add routes for each category
for category in CATEGORIES:
    app.add_url_rule(
        f"/{category}",
        endpoint=f"{category}_index",   # unique endpoint name
        view_func=lambda cat=category: index(cat)
    )
    app.add_url_rule(
        f"/{category}/update",
        endpoint=f"{category}_update",
        view_func=lambda cat=category: update(cat),
        methods=["POST"]
    )
    app.add_url_rule(
        f"/{category}/force_update",
        endpoint=f"{category}_force_update",
        view_func=lambda cat=category: force_update(cat),
        methods=["POST"]
    )
    app.add_url_rule(
        f"/{category}/recheck",
        endpoint=f"{category}_recheck",
        view_func=lambda cat=category: recheck(cat),
        methods=["POST"]
    )
    app.add_url_rule(
        f"/{category}/add",
        endpoint=f"{category}_add",
        view_func=lambda cat=category: add_link(cat),
        methods=["POST"]
    )
    app.add_url_rule(
        f"/{category}/edit",
        endpoint=f"{category}_edit",
        view_func=lambda cat=category: edit_link(cat),
        methods=["POST"]
    )
    app.add_url_rule(
        f"/{category}/remove",
        endpoint=f"{category}_remove",
        view_func=lambda cat=category: remove_link(cat),
        methods=["POST"]
    )
    
@app.route("/api/categories")
def get_categories():
    return jsonify(CATEGORIES)

# --------------------- Startup ---------------------
if __name__ == "__main__":
    schedule_updates()
    # Option A: Run synchronously at startup (wait before serving requests)
    # for category, paths in FILE_PATHS.items():
    #     force_update_job(paths["links"], paths["data"], category)

    # Option B: Kick off background tasks at startup (server starts immediately)
    for category, paths in FILE_PATHS.items():
        socketio.start_background_task(force_update_job, paths["links"], paths["data"], category)

    app.run(host="0.0.0.0", debug=False, port=555)
