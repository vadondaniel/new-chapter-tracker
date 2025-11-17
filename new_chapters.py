import os
import math
import logging
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from apscheduler.schedulers.background import BackgroundScheduler

from scraping import process_link, scrape_all_links
from db_store import ChapterDatabase, DEFAULT_FREE_ONLY, DEFAULT_UPDATE_FREQUENCY

logging.basicConfig(level=logging.INFO)

# --------------------- Data Directory ---------------------
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = Path(DATA_DIR) / "chapters.db"
db = ChapterDatabase(DB_PATH)

CATEGORY_NAMES = db.get_category_names()
CATEGORY_PREFIXES = [name for name in CATEGORY_NAMES if name != "main"]

app = Flask(__name__)
socketio = SocketIO(app)
update_in_progress = False

# Pass the socketio object to scraping.py
import scraping
scraping.socketio = socketio


def annotate_support_flags(entries):
    return {
        url: {
            **data,
            "supports_free_toggle": scraping.supports_free_toggle(url),
        }
        for url, data in entries.items()
    }


def annotate_timestamp_display(entries):
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    def display_label(ts):
        if not ts:
            return ts or "Unknown"
        try:
            ts_date = datetime.strptime(ts[:10], "%Y/%m/%d").date()
        except (ValueError, TypeError):
            return ts
        if ts_date == today:
            return "Today"
        if ts_date == yesterday:
            return "Yesterday"
        return ts

    return {
        url: {
            **data,
            "timestamp_display": display_label(data.get("timestamp")),
        }
        for url, data in entries.items()
    }

# --------------------- Helpers ---------------------
def resolve_category(category=None):
    if category in CATEGORY_NAMES:
        return category
    path = request.path or ""
    for candidate in CATEGORY_PREFIXES:
        if path.startswith(f"/{candidate}"):
            return candidate
    return "main"


def parse_free_only(value, default):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    value_str = str(value).strip().lower()
    if not value_str:
        return default
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

    if not math.isfinite(num):
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
def run_update_job(category="main", force_update=False):
    with app.app_context():
        logging.info(f"Starting scheduled update for {category} (force={force_update})...")
        try:
            links = db.get_links(category)
            current_data = db.get_scraped_data(category)
            new_data, failures = scrape_all_links(
                links, current_data, force_update=force_update, category=category
            )
            db.merge_scraped(new_data)
            db.record_failures(failures)
            logging.info(f"Scheduled update for {category} completed.")
        finally:
            db.set_category_last_checked(category, datetime.now().isoformat())

def schedule_updates():
    scheduler = BackgroundScheduler(job_defaults={"max_instances": 1})
    now = datetime.now()
    for category in db.get_categories():
        name = category["name"]
        interval = category.get("update_interval_hours") or 1
        try:
            interval_hours = max(1, int(interval))
        except (TypeError, ValueError):
            interval_hours = 1

        last_checked_str = category.get("last_checked")
        last_checked = None
        if last_checked_str:
            try:
                last_checked = datetime.fromisoformat(last_checked_str)
            except ValueError:
                last_checked = None

        next_run_time = now
        if last_checked:
            candidate = last_checked + timedelta(hours=interval_hours)
            if candidate > now:
                next_run_time = candidate

        scheduler.add_job(
            lambda c=name: run_update_job(c),
            "interval",
            hours=interval_hours,
            next_run_time=next_run_time,
        )
        logging.info(
            "Scheduled '%s' to run next at %s (interval=%dh)",
            name,
            next_run_time.isoformat(),
            interval_hours,
        )
    scheduler.start()
    
def build_view_data(update_type):
    previous_data = annotate_support_flags(db.get_scraped_data(update_type))
    previous_data = annotate_timestamp_display(previous_data)

    differences = {url: data for url, data in previous_data.items() if data["last_found"] != data["last_saved"]}
    same_data = {url: data for url, data in previous_data.items() if data["last_found"] == data["last_saved"]}

    def sort_entries(entries):
        return dict(
            sorted(
                entries.items(),
                key=lambda item: (
                    1 if item[1].get("favorite") else 0,
                    item[1].get("timestamp") or "",
                ),
                reverse=True,
            )
        )

    category_info = db.get_category(update_type)
    last_checked = category_info["last_checked"] if category_info else None

    return {
        "differences": sort_entries(differences),
        "same_data": sort_entries(same_data),
        "last_full_update": last_checked,
    }
# --------------------- View Logic ---------------------
def index(category=None):
    update_type = resolve_category(category)
    view_data = build_view_data(update_type)

    logging.info(f"Last full update ({update_type}): {view_data['last_full_update']}")
    return render_template(
        "index.html",
        differences=view_data["differences"],
        same_data=view_data["same_data"],
        update_in_progress=update_in_progress,
        last_full_update=view_data["last_full_update"],
        current_category=update_type,
    )


@app.route("/api/chapters")
def chapter_data():
    category = request.args.get("category")
    update_type = resolve_category(category)
    view_data = build_view_data(update_type)

    differences_html = (
        render_template(
            "partials/chapter_table.html",
            rows=view_data["differences"],
            show_found_column=True,
            show_save_button=True,
        )
        if view_data["differences"]
        else '<div class="status-box status-success"><i class="fas fa-check-circle"></i><span>All chapters are up to date!</span></div>'
    )
    same_html = (
        render_template(
            "partials/chapter_table.html",
            rows=view_data["same_data"],
        )
        if view_data["same_data"]
        else '<div class="status-box status-info"><i class="fas fa-info-circle"></i><span>No entries being tracked yet.</span></div>'
    )

    return jsonify(
        {
            "differences": {"count": len(view_data["differences"]), "html": differences_html},
            "same_data": {"count": len(view_data["same_data"]), "html": same_html},
            "last_full_update": view_data["last_full_update"],
        }
    )

def update(category=None):
    data = request.json
    db.mark_saved(data["url"])
    return jsonify({"status": "success"})

def force_update(category=None):
    update_type = resolve_category(category)
    socketio.start_background_task(run_update_job, update_type, True)
    return jsonify({"status": "started"})

def recheck(category=None):
    data = request.json
    update_type = resolve_category(category)
    previous_data = db.get_scraped_data(update_type)
    entry = previous_data.get(data["url"])
    if not entry:
        return jsonify({"status": "missing"})

    link = {
        "url": data["url"],
        "free_only": entry.get("free_only", False),
        "name": entry.get("name", "Unknown"),
        "update_frequency": entry.get("update_frequency", DEFAULT_UPDATE_FREQUENCY),
    }
    data_entry, failure = process_link(link, entry, force_update=True)
    if data_entry:
        db.merge_scraped({link["url"]: data_entry})
    if failure:
        db.record_failures(failure)
    return jsonify({"status": "success"})

def history(category=None):
    data = request.json
    url = data.get("url")
    if not url:
        return jsonify({"status": "missing"}), 400
    result = db.get_link_history(url)
    if not result:
        return jsonify({"status": "missing"}), 404
    return jsonify(result)

def favorite_link(category=None):
    data = request.json
    target_url = data.get("url")
    favorite_flag = data.get("favorite")
    if target_url is None or favorite_flag is None:
        return jsonify({"status": "missing"}), 400
    if isinstance(favorite_flag, str):
        favorite_flag = favorite_flag.strip().lower() in {"true", "1", "yes"}
    else:
        favorite_flag = bool(favorite_flag)
    db.update_link_metadata(target_url, favorite=favorite_flag)
    return jsonify({"status": "success"})

def add_link(category=None):
    data = request.json
    freq, free_only = get_link_metadata(data)
    new_entry = {
        "name": data["name"],
        "url": data["url"],
        "update_frequency": freq,
        "free_only": free_only,
    }
    update_type = resolve_category(category)
    db.add_link(
        new_entry["name"],
        new_entry["url"],
        update_type,
        new_entry["update_frequency"],
        new_entry["free_only"],
    )
    link = {
        "url": new_entry["url"],
        "free_only": new_entry["free_only"],
        "name": new_entry["name"],
        "update_frequency": new_entry["update_frequency"],
    }
    data_entry, failure = process_link(link, {})
    if data_entry:
        db.merge_scraped({link["url"]: data_entry})
    if failure:
        db.record_failures(failure)
    return jsonify({"status": "success"})

def edit_link(category=None):
    data = request.json
    orig_url = data.get("original_url")
    new_url = data.get("url")
    new_name = data.get("name")

    update_type = resolve_category(category)
    links = db.get_links(update_type)

    def normalize(u): return u.replace("http://", "").replace("https://", "")
    updated = False
    for link in links:
        if normalize(link.get("url", "")) == normalize(orig_url or ""):
            freq, free_only = get_link_metadata(data, link)
            db.update_link(
                orig_url,
                new_url,
                new_name,
                freq,
                free_only,
            )
            updated = True
            break

    return jsonify({"status": "success"})

def remove_link(category=None):
    data = request.json
    db.remove_link(data["url"])
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
app.add_url_rule("/favorite", endpoint="main_favorite", view_func=lambda: favorite_link("main"), methods=["POST"])
app.add_url_rule("/history", endpoint="main_history", view_func=lambda: history("main"), methods=["POST"])

# dynamically add routes for each category
for category in CATEGORY_PREFIXES:
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
    app.add_url_rule(
        f"/{category}/favorite",
        endpoint=f"{category}_favorite",
        view_func=lambda cat=category: favorite_link(cat),
        methods=["POST"]
    )
    app.add_url_rule(
        f"/{category}/history",
        endpoint=f"{category}_history",
        view_func=lambda cat=category: history(cat),
        methods=["POST"]
    )
    
@app.route("/api/categories")
def get_categories():
    return jsonify(db.get_categories())

# --------------------- Startup ---------------------
if __name__ == "__main__":
    schedule_updates()
    app.run(host="0.0.0.0", debug=False, port=555)
