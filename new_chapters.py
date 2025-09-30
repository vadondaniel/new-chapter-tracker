import os
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from apscheduler.schedulers.background import BackgroundScheduler

from scraping import (
    load_links, save_links, save_data, load_previous_data,
    scrape_website, scrape_all_links
)
from config import CATEGORIES

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
def get_file_paths():
    """Return file paths based on current route."""
    path = request.path
    for category in CATEGORIES:
        if path.startswith(f"/{category}"):
            return FILE_PATHS[category]["links"], FILE_PATHS[category]["data"], category
    return FILE_PATHS["main"]["links"], FILE_PATHS["main"]["data"], "main"

# --------------------- Background Jobs ---------------------
def force_update_job(file_path_links, file_path_data, update_type="main"):
    global last_full_update
    with app.app_context():
        logging.info(f"Starting scheduled force update for {update_type}...")
        links = load_links(file_path=file_path_links)
        previous_data = load_previous_data(file_path=file_path_data)
        new_data = scrape_all_links(links, previous_data, force_update=True)

        # Merge new_data into previous_data
        for url, data in new_data.items():
            previous_data[url] = {
                "name": data.get("name", previous_data.get(url, {}).get("name", "Unknown")),
                "last_found": data["last_found"],
                "last_saved": previous_data.get(url, {}).get("last_saved", "N/A"),
                "timestamp": data["timestamp"]
            }

        save_data(previous_data, file_path=file_path_data)
        last_full_update[update_type] = datetime.now().isoformat()
        logging.info(f"Scheduled force update for {update_type} completed.")

def schedule_updates():
    scheduler = BackgroundScheduler(job_defaults={'max_instances': 1})
    scheduler.add_job(
        lambda: force_update_job(FILE_PATHS["main"]["links"], FILE_PATHS["main"]["data"], "main"),
        'interval', hours=1
    )
    for category in CATEGORIES:
        scheduler.add_job(
            lambda c=category: force_update_job(FILE_PATHS[c]["links"], FILE_PATHS[c]["data"], c),
            'interval', hours=5
        )
    scheduler.start()
    
# --------------------- View Logic ---------------------
def index(category=None):
    _, file_path, update_type = get_file_paths()
    previous_data = load_previous_data(file_path=file_path)

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
    _, file_path, _ = get_file_paths()
    previous_data = load_previous_data(file_path=file_path)
    if data["url"] in previous_data:
        previous_data[data["url"]]["last_saved"] = previous_data[data["url"]]["last_found"]
        save_data(previous_data, file_path=file_path)
    return jsonify({"status": "success"})

def force_update(category=None):
    file_path_links, file_path_data, update_type = get_file_paths()
    socketio.start_background_task(force_update_job, file_path_links, file_path_data, update_type)
    return jsonify({"status": "started"})

def recheck(category=None):
    data = request.json
    _, file_path, _ = get_file_paths()
    previous_data = load_previous_data(file_path=file_path)
    if data["url"] in previous_data:
        latest_chapter, timestamp = scrape_website(data["url"], previous_data, force_update=True)
        previous_data[data["url"]]["last_found"] = latest_chapter
        previous_data[data["url"]]["timestamp"] = timestamp
        save_data(previous_data, file_path=file_path)
    return jsonify({"status": "success"})

def add_link(category=None):
    data = request.json
    file_path_links, file_path_data, _ = get_file_paths()
    links = load_links(file_path=file_path_links)
    new_entry = {"name": data["name"], "url": data["url"]}
    if not any(link["url"] == new_entry["url"] for link in links):
        links.append(new_entry)
        save_links(links, file_path=file_path_links)
    previous_data = load_previous_data(file_path=file_path_data)
    latest_chapter, timestamp = scrape_website(new_entry["url"], previous_data, force_update=True)
    previous_data[new_entry["url"]] = {
        "name": new_entry["name"],
        "last_saved": "N/A",
        "last_found": latest_chapter,
        "timestamp": timestamp
    }
    save_data(previous_data, file_path=file_path_data)
    return jsonify({"status": "success"})

def edit_link(category=None):
    data = request.json
    orig_url = data.get("original_url")
    new_url = data.get("url")
    new_name = data.get("name")

    file_path_links, file_path_data, _ = get_file_paths()
    links = load_links(file_path=file_path_links)

    def normalize(u): return u.replace("http://", "").replace("https://", "")

    # update links list (first match)
    updated = False
    for link in links:
        if normalize(link.get("url", "")) == normalize(orig_url or ""):
            link["url"] = new_url
            link["name"] = new_name
            updated = True
            break
    if updated:
        save_links(links, file_path=file_path_links)

    # update previous_data: move key if url changed, update name
    previous_data = load_previous_data(file_path=file_path_data)
    for key in list(previous_data.keys()):
        if normalize(key) == normalize(orig_url or ""):
            entry = previous_data.pop(key)
            entry["name"] = new_name
            previous_data[new_url] = entry
            save_data(previous_data, file_path=file_path_data)
            break

    return jsonify({"status": "success"})

def remove_link(category=None):
    data = request.json
    file_path_links, file_path_data, _ = get_file_paths()
    links = load_links(file_path=file_path_links)
    def normalize_url(url): return url.replace("http://", "").replace("https://", "")
    input_url = normalize_url(data["url"])
    links = [link for link in links if normalize_url(link["url"]) != input_url]
    save_links(links, file_path=file_path_links)
    previous_data = load_previous_data(file_path=file_path_data)
    keys_to_remove = [url for url in previous_data if normalize_url(url) == input_url]
    for url in keys_to_remove:
        del previous_data[url]
    if keys_to_remove:
        save_data(previous_data, file_path=file_path_data)
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
