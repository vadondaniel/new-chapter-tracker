import scraping
import os
import sys
import math
import logging
import sqlite3
import atexit
import threading
import webbrowser
import pystray
from PIL import Image
from functools import wraps
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, session, make_response
from flask_socketio import SocketIO, join_room, leave_room
from apscheduler.schedulers.background import BackgroundScheduler

from scraping import process_link, scrape_all_links, category_room_name
from db_store import ChapterDatabase, DEFAULT_FREE_ONLY, DEFAULT_UPDATE_FREQUENCY

logging.basicConfig(level=logging.INFO)

# --------------------- Data Directory ---------------------
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = Path(DATA_DIR) / "chapters.db"
db = ChapterDatabase(DB_PATH)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("CHAPTER_TRACKER_SECRET_KEY", "dev-secret-key-change-me-123"),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_NAME='chapter_tracker_session'
)
socketio = SocketIO(app)
update_in_progress = False
ASSET_VERSION = os.environ.get("CHAPTER_TRACKER_ASSET_VERSION", "1")
_scheduler = None
_scheduler_lock = threading.Lock()
_scheduler_started = False
client_rooms = {}

# Pass the socketio object to scraping.py
scraping.socketio = socketio


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Bypass auth if request is from localhost
        if request.remote_addr in ("127.0.0.1", "::1"):
            return f(*args, **kwargs)

        settings = db.get_settings()
        if settings.get("password_protected") == "1":
            # Check session or fallback cookie
            if session.get("authenticated") == "1" or request.cookies.get("chapter_auth") == "1":
                return f(*args, **kwargs)

            # Check header (for API requests from JS)
            password = request.headers.get("X-Password")
            correct_password = settings.get("password_hash")
            if not correct_password or password != correct_password:
                return jsonify({"status": "error", "message": "Unauthorized"}), 401

            # Valid password provided in header, upgrade to session and cookie for future requests
            session["authenticated"] = "1"
            session.permanent = True
            
            resp = make_response(f(*args, **kwargs))
            resp.set_cookie("chapter_auth", "1", max_age=30*24*60*60, httponly=True, samesite='Lax')
            return resp
        return f(*args, **kwargs)
    return decorated


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
                    to=category_room_name(category),
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
    last_checked = category_info.get("last_checked") if category_info else None

    return {
        "differences": sort_entries(differences),
        "same_data": sort_entries(same_data),
        "last_full_update": last_checked,
    }
# --------------------- View Logic ---------------------


def index(category=None):
    update_type = resolve_category(category)
    settings = db.get_settings()
    
    is_local = request.remote_addr in ("127.0.0.1", "::1")
    is_protected = settings.get("password_protected") == "1"
    is_authenticated = is_local or session.get("authenticated") == "1" or request.cookies.get("chapter_auth") == "1"

    nav_categories = build_nav_context()

    if is_protected and not is_authenticated:
        # Return shell without data if protected and not authenticated
        # The frontend will fetch data via API after auth
        return render_template(
            "index.html",
            differences={},
            same_data={},
            update_in_progress=scraping.update_in_progress,
            last_full_update=None,
            current_category=update_type,
            current_nav_info=get_current_nav_info([], update_type, 0),
            asset_version=ASSET_VERSION,
            nav_categories=[],
            password_protected=True
        )

    view_data = build_view_data(update_type)
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
        password_protected=False
    )


@app.route("/api/chapters")
def chapter_data():
    category = request.args.get("category")
    update_type = resolve_category(category)
    view_data = build_view_data(update_type)
    nav_categories = build_nav_context()
    differences = view_data.get("differences", {})
    current_nav = get_current_nav_info(
        nav_categories, update_type, len(differences)
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
            "differences": {"count": len(differences), "html": differences_html},
            "same_data": {"count": len(view_data.get("same_data", {})), "html": same_html},
            "last_full_update": view_data.get("last_full_update"),
            "nav": {"categories": nav_categories, "current": current_nav},
        }
    )


def update(category=None):
    data = request.get_json()
    if not data or "url" not in data:
        return jsonify({"status": "error", "message": "Missing URL"}), 400
    db.mark_saved(data["url"])
    return jsonify({"status": "success"})


def force_update(category=None):
    update_type = resolve_category(category)
    socketio.start_background_task(run_update_job, update_type, True)
    return jsonify({"status": "started"})


def recheck(category=None):
    data = request.get_json()
    if not data or "url" not in data:
        return jsonify({"status": "error", "message": "Missing URL"}), 400
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
    data = request.get_json() or {}
    url = data.get("url")
    if not url:
        return jsonify({"status": "missing"}), 400
    result = db.get_link_history(url)
    if not result:
        return jsonify({"status": "missing"}), 404
    return jsonify(result)


def history_set_saved(category=None):
    data = request.get_json() or {}
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
    db.set_last_saved(url, entry["last_found"] or "N/A", chapter_url=entry.get("last_found_url"))
    return jsonify({"status": "success"})


def history_delete_entry(category=None):
    data = request.get_json() or {}
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
    data = request.get_json() or {}
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
    data = request.get_json() or {}
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
    data = request.get_json() or {}
    orig_url = data.get("original_url")
    new_url = data.get("url")
    new_name = data.get("name")

    if not orig_url or not new_url or not new_name:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

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
                str(orig_url),
                str(new_url),
                str(new_name),
                freq,
                free_only,
                category=target_category,
            )
            updated = True
            break

    return jsonify({"status": "success"})


def remove_link(category=None):
    data = request.get_json() or {}
    url = data.get("url")
    if not url:
        return jsonify({"status": "error", "message": "Missing URL"}), 400
    db.remove_link(url)
    return jsonify({"status": "success"})


@socketio.on("subscribe_category")
def handle_subscribe_category(payload):
    category = (payload or {}).get("category")
    room = category_room_name(category)
    sid = getattr(request, "sid", None)
    previous = client_rooms.get(sid) if sid else None
    if previous and previous != room:
        leave_room(previous)
    client_rooms[sid] = room
    join_room(room)


@socketio.on("disconnect")
def handle_disconnect():
    sid = getattr(request, "sid", None)
    if sid:
        room = client_rooms.pop(sid, None)
        if room:
            leave_room(room)

# --------------------- Routes ---------------------


@app.route("/")
def main_index():
    return index()


# Main routes (no category prefix)
app.add_url_rule("/update", endpoint="main_update",
                 view_func=require_auth(lambda: update("main")), methods=["POST"])
app.add_url_rule("/force_update", endpoint="main_force_update",
                 view_func=require_auth(lambda: force_update("main")), methods=["POST"])
app.add_url_rule("/recheck", endpoint="main_recheck",
                 view_func=require_auth(lambda: recheck("main")), methods=["POST"])
app.add_url_rule("/add", endpoint="main_add",
                 view_func=require_auth(lambda: add_link("main")), methods=["POST"])
app.add_url_rule("/edit", endpoint="main_edit",
                 view_func=require_auth(lambda: edit_link("main")), methods=["POST"])
app.add_url_rule("/remove", endpoint="main_remove",
                 view_func=require_auth(lambda: remove_link("main")), methods=["POST"])
app.add_url_rule("/favorite", endpoint="main_favorite",
                 view_func=require_auth(lambda: favorite_link("main")), methods=["POST"])
app.add_url_rule("/history", endpoint="main_history",
                 view_func=require_auth(lambda: history("main")), methods=["POST"])
app.add_url_rule("/history/set_saved", endpoint="main_history_set_saved",
                 view_func=require_auth(lambda: history_set_saved("main")), methods=["POST"])
app.add_url_rule("/history/delete", endpoint="main_history_delete",
                 view_func=require_auth(lambda: history_delete_entry("main")), methods=["POST"])

# dynamically add routes for any category slug


@app.route("/api/categories", methods=["GET", "POST"])
@require_auth
def categories_api():
    if request.method == "GET":
        return jsonify(build_nav_context())

    data = request.get_json() or {}
    name = data.get("name")
    if not name:
        return jsonify({"status": "error", "error": "Category name is required"}), 400
    display_name = data.get("display_name")
    include_in_nav = parse_free_only(data.get("include_in_nav", True), True)
    update_interval = data.get(
        "update_interval_hours") or data.get("update_interval")
    try:
        created = db.create_category(
            name=str(name),
            display_name=display_name,
            include_in_nav=include_in_nav,
            update_interval_hours=int(update_interval) if update_interval is not None else 1,
        )
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "error": "Category already exists"}), 400
    except ValueError as exc:
        return jsonify({"status": "error", "error": str(exc)}), 400
    return jsonify({"status": "success", "category": created})


@app.route("/api/categories/<category_name>", methods=["PUT", "DELETE"])
@require_auth
def categories_detail(category_name):
    if request.method == "DELETE":
        try:
            deleted = db.delete_category(category_name)
        except ValueError as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400
        if not deleted:
            return jsonify({"status": "missing"}), 404
        return jsonify({"status": "success"})

    data = request.get_json() or {}
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
@require_auth
def categories_reorder():
    data = request.get_json() or {}
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


@app.route("/api/settings", methods=["GET", "POST"])
def settings_api():
    if request.method == "POST":
        # Protect saving settings if a password is set (unless local)
        if request.remote_addr not in ("127.0.0.1", "::1"):
            settings = db.get_settings()
            if settings.get("password_protected") == "1":
                password = request.headers.get("X-Password")
                correct_password = settings.get("password_hash")
                if not correct_password or password != correct_password:
                    return jsonify({"status": "error", "message": "Unauthorized"}), 401

    if request.method == "GET":
        settings = db.get_settings()
        # Don't send the actual hash, just whether a password is set
        has_password = bool(settings.get("password_hash"))
        
        # Check if auth is required for THIS specific request
        is_local = request.remote_addr in ("127.0.0.1", "::1")
        auth_required = (settings.get("password_protected") == "1") and not is_local
        
        return jsonify({
            "password_protected": settings.get("password_protected") == "1",
            "auth_required": auth_required,
            "has_password": has_password,
            "share_local": settings.get("share_local") == "1",
            "port": settings.get("port", "555")
        })

    data = request.get_json() or {}
    if "password_protected" in data:
        db.update_setting("password_protected", "1" if data["password_protected"] else "0")
    if "share_local" in data:
        db.update_setting("share_local", "1" if data["share_local"] else "0")
    if "port" in data:
        db.update_setting("port", str(data["port"]))
    if "password" in data and data["password"]:
        # In a real app we'd use a proper hash, but for local hosting a simple string or basic hash is often requested
        # I'll use a simple way to store it for now as per "local host" context
        db.update_setting("password_hash", str(data["password"]))

    return jsonify({"status": "success"})


@app.route("/api/auth", methods=["POST"])
def auth_api():
    data = request.get_json() or {}
    password = data.get("password")
    settings = db.get_settings()
    correct_password = settings.get("password_hash")

    if not correct_password or password == correct_password:
        session["authenticated"] = "1"
        session.permanent = True
        resp = make_response(jsonify({"status": "success"}))
        resp.set_cookie("chapter_auth", "1", max_age=30*24*60*60, httponly=True, samesite='Lax')
        return resp
    return jsonify({"status": "error", "message": "Invalid password"}), 401


@app.route("/<category>")
def category_index(category):
    return index(category)


@app.route("/<category>/update", methods=["POST"])
@require_auth
def category_update_route(category):
    return update(category)


@app.route("/<category>/force_update", methods=["POST"])
@require_auth
def category_force_update_route(category):
    return force_update(category)


@app.route("/<category>/recheck", methods=["POST"])
@require_auth
def category_recheck_route(category):
    return recheck(category)


@app.route("/<category>/add", methods=["POST"])
@require_auth
def category_add_route(category):
    return add_link(category)


@app.route("/<category>/edit", methods=["POST"])
@require_auth
def category_edit_route(category):
    return edit_link(category)


@app.route("/<category>/remove", methods=["POST"])
@require_auth
def category_remove_route(category):
    return remove_link(category)


@app.route("/<category>/favorite", methods=["POST"])
@require_auth
def category_favorite_route(category):
    return favorite_link(category)


@app.route("/<category>/history", methods=["POST"])
@require_auth
def category_history_route(category):
    return history(category)


@app.route("/<category>/history/set_saved", methods=["POST"])
@require_auth
def category_history_set_route(category):
    return history_set_saved(category)


@app.route("/<category>/history/delete", methods=["POST"])
@require_auth
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


# Use before_request as a reliable way to ensure scheduler starts on first request
# since before_first_request is deprecated/removed in Flask 2.3+
@app.before_request
def before_request_hooks():
    _start_scheduler_hook()
    
    # Sync session from fallback cookie if needed
    if session.get("authenticated") != "1" and request.cookies.get("chapter_auth") == "1":
        session["authenticated"] = "1"
        session.permanent = True


@app.after_request
def set_cache_headers(response):
    # Disable caching for the main page and API to ensure auth state is always fresh
    # This prevents the browser from showing a cached "skeleton" page
    if request.endpoint in ("main_index", "category_index", "chapter_data"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# --------------------- Startup Logic ---------------------

def set_run_on_startup(enabled=True):
    if sys.platform != 'win32':
        return False
    
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "ChapterTracker"
    
    if getattr(sys, 'frozen', False):
        cmd = f'"{sys.executable}"'
    else:
        # Use pythonw.exe if available to run without console window on startup
        python_exe = sys.executable.replace("python.exe", "pythonw.exe")
        cmd = f'"{python_exe}" "{os.path.abspath(__file__)}"'
    
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, app_name)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        logging.error(f"Failed to update startup registry: {e}")
        return False

def is_run_on_startup():
    if sys.platform != 'win32':
        return False
        
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "ChapterTracker"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, app_name)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        logging.error(f"Failed to read startup registry: {e}")
        return False

# --------------------- Tray Icon ---------------------

def setup_tray(host, port):
    def on_open(icon, item):
        # Use localhost if host is 0.0.0.0
        display_host = "127.0.0.1" if host == "0.0.0.0" else host
        webbrowser.open(f"http://{display_host}:{port}")

    def on_exit(icon, item):
        icon.stop()
        os._exit(0)

    def toggle_startup(icon, item):
        new_state = not is_run_on_startup()
        if set_run_on_startup(new_state):
            db.update_setting("start_on_startup", "1" if new_state else "0")

    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "favicon.ico")
    try:
        image = Image.open(icon_path)
    except Exception as e:
        logging.error(f"Failed to load tray icon: {e}")
        # Fallback to a simple colored square if favicon is missing
        image = Image.new('RGB', (64, 64), color=(60, 120, 216))

    menu = pystray.Menu(
        pystray.MenuItem("Open App", on_open, default=True),
        pystray.MenuItem("Start on Startup", toggle_startup, checked=lambda item: is_run_on_startup()),
        pystray.MenuItem("Exit", on_exit)
    )

    icon = pystray.Icon("chapter_tracker", image, "Chapter Tracker", menu)
    icon.run()


# --------------------- Startup ---------------------
if __name__ == "__main__":
    schedule_updates()
    # Load settings for startup
    try:
        settings = db.get_settings()
        host = "0.0.0.0" if settings.get("share_local") == "1" else "127.0.0.1"
        port = int(settings.get("port", 555))
    except Exception:
        host = "127.0.0.1"
        port = 555

    # Start tray icon in a background thread
    threading.Thread(target=setup_tray, args=(host, port), daemon=True).start()

    app.run(host=host, debug=False, port=port)
