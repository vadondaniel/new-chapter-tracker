import scraping
import os
import math
import logging
import sqlite3
import atexit
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for
from flask_socketio import SocketIO, join_room, leave_room
from apscheduler.schedulers.background import BackgroundScheduler
from threading import Lock

from scraping import process_link, scrape_all_links, category_room_name
from db_store import ChapterDatabase, DEFAULT_FREE_ONLY, DEFAULT_UPDATE_FREQUENCY

logging.basicConfig(level=logging.INFO)

# --------------------- Data Directory ---------------------
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = Path(DATA_DIR) / "chapters.db"
db = ChapterDatabase(DB_PATH)

app = Flask(__name__)
socketio = SocketIO(app)
update_in_progress = False
ASSET_VERSION = os.environ.get("CHAPTER_TRACKER_ASSET_VERSION", "1")
_scheduler = None
_scheduler_lock = Lock()
_scheduler_started = False
client_rooms = {}

# Pass the socketio object to scraping.py
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
    names = set(db.get_category_names())
    if category in names:
        return category
    path = request.path or ""
    for candidate in names:
        if candidate != "main" and path.startswith(f"/{candidate}"):
            return candidate
    return "main"


def build_nav_context():
    categories = db.get_categories()
    counts = db.get_category_unsaved_counts()
    for category in categories:
        category["unsaved_count"] = counts.get(category["name"], 0)
    return categories


def get_current_nav_info(nav_categories, current_category, fallback_count):
    for nav in nav_categories:
        if nav["name"] == current_category:
            return nav
    category_info = db.get_category(current_category)
    display_name = None
    include_in_nav = False
    if category_info:
        display_name = category_info.get("display_name")
        include_in_nav = bool(category_info.get("include_in_nav"))
    if not display_name:
        display_name = current_category.replace("_", " ").title()
    return {
        "name": current_category,
        "display_name": display_name,
        "include_in_nav": include_in_nav,
        "unsaved_count": fallback_count,
    }


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
    existing_freq = existing.get(
        "update_frequency") if existing else DEFAULT_UPDATE_FREQUENCY
    freq = parse_update_frequency(
        payload.get("update_frequency"), existing_freq)

    existing_free_flag = existing.get(
        "free_only") if existing else DEFAULT_FREE_ONLY
    free_only = parse_free_only(payload.get("free_only"), existing_free_flag)
    return freq, free_only

# --------------------- Background Jobs ---------------------


def run_update_job(category="main", force_update=False):
    with app.app_context():
        logging.info(
            f"Starting scheduled update for {category} (force={force_update})...")
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
            if socketio:
                socketio.emit(
                    "update_complete",
                    {"category": category},
                    namespace="/",
                    room=category_room_name(category),
                )


def schedule_updates(force=False):
    global _scheduler, _scheduler_started
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = BackgroundScheduler(job_defaults={"max_instances": 1})
        elif force and _scheduler_started:
            _scheduler.remove_all_jobs()
        elif _scheduler_started:
            # Scheduler already configured and running; nothing to do.
            return _scheduler

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

            _scheduler.add_job(
                run_update_job,
                "interval",
                hours=interval_hours,
                next_run_time=next_run_time,
                id=f"update_{name}",
                replace_existing=True,
                kwargs={"category": name},
            )
            logging.info(
                "Scheduled '%s' to run next at %s (interval=%dh)",
                name,
                next_run_time.isoformat(),
                interval_hours,
            )

        if not _scheduler_started:
            _scheduler.start()
            _scheduler_started = True
        return _scheduler


@atexit.register
def _shutdown_scheduler():
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler and _scheduler_started:
            _scheduler.shutdown(wait=False)
            _scheduler_started = False


def build_view_data(update_type):
    previous_data = annotate_support_flags(db.get_scraped_data(update_type))
    previous_data = annotate_timestamp_display(previous_data)

    differences = {url: data for url, data in previous_data.items(
    ) if data["last_found"] != data["last_saved"]}
    same_data = {url: data for url, data in previous_data.items(
    ) if data["last_found"] == data["last_saved"]}

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

    nav_categories = build_nav_context()
    current_nav = get_current_nav_info(
        nav_categories, update_type, len(view_data["differences"])
    )

    logging.info(
        f"Last full update ({update_type}): {view_data['last_full_update']}")
    return render_template(
        "index.html",
        differences=view_data["differences"],
        same_data=view_data["same_data"],
        update_in_progress=scraping.update_in_progress,
        last_full_update=view_data["last_full_update"],
        current_category=update_type,
        current_nav_info=current_nav,
        asset_version=ASSET_VERSION,
        nav_categories=nav_categories,
    )


@app.route("/api/chapters")
def chapter_data():
    category = request.args.get("category")
    update_type = resolve_category(category)
    view_data = build_view_data(update_type)
    nav_categories = build_nav_context()
    current_nav = get_current_nav_info(
        nav_categories, update_type, len(view_data["differences"])
    )

    differences_html = (
        render_template(
            "partials/chapter_table.html",
            rows=view_data["differences"],
            show_found_column=True,
            show_save_button=True,
            current_category=update_type,
        )
        if view_data["differences"]
        else '<div class="status-box status-success"><i class="fas fa-check-circle"></i><span>All chapters are up to date!</span></div>'
    )
    same_html = (
        render_template(
            "partials/chapter_table.html",
            rows=view_data["same_data"],
            current_category=update_type,
        )
        if view_data["same_data"]
        else '<div class="status-box status-info"><i class="fas fa-info-circle"></i><span>No entries being tracked yet.</span></div>'
    )

    return jsonify(
        {
            "differences": {"count": len(view_data["differences"]), "html": differences_html},
            "same_data": {"count": len(view_data["same_data"]), "html": same_html},
            "last_full_update": view_data["last_full_update"],
            "nav": {"categories": nav_categories, "current": current_nav},
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


def history_set_saved(category=None):
    data = request.json
    url = data.get("url")
    entry_id = data.get("entry_id")
    if not url or entry_id is None:
        return jsonify({"status": "missing"}), 400
    try:
        entry_id = int(entry_id)
    except (TypeError, ValueError):
        return jsonify({"status": "invalid_entry"}), 400
    entry = db.get_history_entry(url, entry_id)
    if not entry:
        return jsonify({"status": "missing"}), 404
    db.set_last_saved(url, entry["last_found"] or "N/A")
    return jsonify({"status": "success"})


def history_delete_entry(category=None):
    data = request.json
    url = data.get("url")
    entry_id = data.get("entry_id")
    if not url or entry_id is None:
        return jsonify({"status": "missing"}), 400
    try:
        entry_id = int(entry_id)
    except (TypeError, ValueError):
        return jsonify({"status": "invalid_entry"}), 400
    try:
        deleted = db.delete_history_entry(url, entry_id)
    except ValueError as exc:
        return jsonify({"status": "action_invalid", "error": str(exc)}), 400
    if not deleted:
        return jsonify({"status": "missing"}), 404
    return jsonify({"status": "success"})


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
    requested_category = data.get("target_category")
    valid_categories = set(db.get_category_names())
    requested_category = requested_category if requested_category in valid_categories else None

    update_type = resolve_category(category)
    links = db.get_links(update_type)

    def normalize(u): return u.replace("http://", "").replace("https://", "")
    updated = False
    for link in links:
        if normalize(link.get("url", "")) == normalize(orig_url or ""):
            freq, free_only = get_link_metadata(data, link)
            target_category = (
                requested_category if requested_category and requested_category != update_type else None
            )
            db.update_link(
                orig_url,
                new_url,
                new_name,
                freq,
                free_only,
                category=target_category,
            )
            updated = True
            break

    return jsonify({"status": "success"})


def remove_link(category=None):
    data = request.json
    db.remove_link(data["url"])
    return jsonify({"status": "success"})


@socketio.on("subscribe_category")
def handle_subscribe_category(payload):
    category = (payload or {}).get("category")
    room = category_room_name(category)
    sid = request.sid
    previous = client_rooms.get(sid)
    if previous and previous != room:
        leave_room(previous)
    client_rooms[sid] = room
    join_room(room)


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    room = client_rooms.pop(sid, None)
    if room:
        leave_room(room)

# --------------------- Routes ---------------------


@app.route("/")
def main_index():
    return index()


# Main routes (no category prefix)
app.add_url_rule("/update", endpoint="main_update",
                 view_func=lambda: update("main"), methods=["POST"])
app.add_url_rule("/force_update", endpoint="main_force_update",
                 view_func=lambda: force_update("main"), methods=["POST"])
app.add_url_rule("/recheck", endpoint="main_recheck",
                 view_func=lambda: recheck("main"), methods=["POST"])
app.add_url_rule("/add", endpoint="main_add",
                 view_func=lambda: add_link("main"), methods=["POST"])
app.add_url_rule("/edit", endpoint="main_edit",
                 view_func=lambda: edit_link("main"), methods=["POST"])
app.add_url_rule("/remove", endpoint="main_remove",
                 view_func=lambda: remove_link("main"), methods=["POST"])
app.add_url_rule("/favorite", endpoint="main_favorite",
                 view_func=lambda: favorite_link("main"), methods=["POST"])
app.add_url_rule("/history", endpoint="main_history",
                 view_func=lambda: history("main"), methods=["POST"])
app.add_url_rule("/history/set_saved", endpoint="main_history_set_saved",
                 view_func=lambda: history_set_saved("main"), methods=["POST"])
app.add_url_rule("/history/delete", endpoint="main_history_delete",
                 view_func=lambda: history_delete_entry("main"), methods=["POST"])

# dynamically add routes for any category slug


@app.route("/api/categories", methods=["GET", "POST"])
def categories_api():
    if request.method == "GET":
        return jsonify(build_nav_context())

    data = request.json or {}
    name = data.get("name")
    display_name = data.get("display_name")
    include_in_nav = parse_free_only(data.get("include_in_nav", True), True)
    update_interval = data.get(
        "update_interval_hours") or data.get("update_interval")
    try:
        created = db.create_category(
            name=name,
            display_name=display_name,
            include_in_nav=include_in_nav,
            update_interval_hours=update_interval,
        )
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "error": "Category already exists"}), 400
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400
    return jsonify({"status": "success", "category": created})


@app.route("/api/categories/<category_name>", methods=["PUT", "DELETE"])
def categories_detail(category_name):
    if request.method == "DELETE":
        try:
            deleted = db.delete_category(category_name)
        except ValueError as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400
        if not deleted:
            return jsonify({"status": "missing"}), 404
        return jsonify({"status": "success"})

    data = request.json or {}
    updated = db.update_category_entry(
        name=category_name,
        new_name=data.get("name"),
        display_name=data.get("display_name"),
        include_in_nav=parse_free_only(data.get("include_in_nav"), None),
        update_interval_hours=data.get("update_interval_hours"),
    )
    if not updated:
        return jsonify({"status": "missing"}), 404
    return jsonify({"status": "success", "category": updated})


@app.route("/api/categories/reorder", methods=["POST"])
def categories_reorder():
    data = request.json or {}
    order = data.get("order") or []
    if not isinstance(order, list) or not order:
        return jsonify({"status": "error", "error": "Invalid order payload"}), 400
    categories = db.reorder_categories(order)
    return jsonify({"status": "success", "categories": categories})


@app.route("/api/supported_sites", methods=["GET"])
def supported_sites():
    try:
        sites = scraping.get_supported_sites()
    except Exception as exc:
        logging.error("Failed to load supported sites: %s", exc)
        return jsonify({"status": "error"}), 500
    return jsonify(sites)


@app.route("/<category>")
def category_index(category):
    return index(category)


@app.route("/<category>/update", methods=["POST"])
def category_update_route(category):
    return update(category)


@app.route("/<category>/force_update", methods=["POST"])
def category_force_update_route(category):
    return force_update(category)


@app.route("/<category>/recheck", methods=["POST"])
def category_recheck_route(category):
    return recheck(category)


@app.route("/<category>/add", methods=["POST"])
def category_add_route(category):
    return add_link(category)


@app.route("/<category>/edit", methods=["POST"])
def category_edit_route(category):
    return edit_link(category)


@app.route("/<category>/remove", methods=["POST"])
def category_remove_route(category):
    return remove_link(category)


@app.route("/<category>/favorite", methods=["POST"])
def category_favorite_route(category):
    return favorite_link(category)


@app.route("/<category>/history", methods=["POST"])
def category_history_route(category):
    return history(category)


@app.route("/<category>/history/set_saved", methods=["POST"])
def category_history_set_route(category):
    return history_set_saved(category)


@app.route("/<category>/history/delete", methods=["POST"])
def category_history_delete_route(category):
    return history_delete_entry(category)


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )


@app.errorhandler(404)
def handle_404(_error):
    return redirect(url_for("main_index"))


def _start_scheduler_hook():
    schedule_updates()


if hasattr(app, "before_serving"):
    app.before_serving(_start_scheduler_hook)
elif hasattr(app, "before_first_request"):
    app.before_first_request(_start_scheduler_hook)
else:
    # Fallback for very old Flask versions; harmless because schedule_updates is idempotent.
    app.before_request(_start_scheduler_hook)


# --------------------- Startup ---------------------
if __name__ == "__main__":
    schedule_updates()
    app.run(host="0.0.0.0", debug=False, port=555)
