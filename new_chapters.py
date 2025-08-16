from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import logging
from scraping import (
    load_links, save_links, save_data, load_previous_data,
    scrape_website, scrape_all_links,
    LINKS_FILE, MANGA_LINKS_FILE, DATA_FILE, MANGA_DATA_FILE
)

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
socketio = SocketIO(app)
update_in_progress = False
last_full_update = {"main": None, "manga": None}

# Pass the socketio object to scraping2.py
import scraping
scraping.socketio = socketio

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
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: force_update_job(LINKS_FILE, DATA_FILE, "main"), 'interval', hours=1)
    scheduler.add_job(lambda: force_update_job(MANGA_LINKS_FILE, MANGA_DATA_FILE, "manga"), 'interval', hours=5)
    scheduler.start()

@app.route('/')
@app.route('/manga')
def index():
    is_manga = request.path.startswith('/manga')
    file_path = MANGA_DATA_FILE if is_manga else DATA_FILE
    previous_data = load_previous_data(file_path=file_path)

    differences = {url: data for url, data in previous_data.items() if data["last_found"] != data["last_saved"]}
    same_data = {url: data for url, data in previous_data.items() if data["last_found"] == data["last_saved"]}

    # Sort by timestamp descending
    differences = dict(sorted(differences.items(), key=lambda x: x[1]["timestamp"], reverse=True))
    same_data = dict(sorted(same_data.items(), key=lambda x: x[1]["timestamp"], reverse=True))

    update_type = "manga" if is_manga else "main"
    logging.info(f"Last full update ({update_type}): {last_full_update[update_type]}")
    return render_template(
        "index.html",
        differences=differences,
        same_data=same_data,
        update_in_progress=update_in_progress,
        last_full_update=last_full_update[update_type]
    )

def get_file_paths():
    is_manga = request.path.startswith('/manga')
    return (
        MANGA_LINKS_FILE if is_manga else LINKS_FILE,
        MANGA_DATA_FILE if is_manga else DATA_FILE
    )

@app.route('/update', methods=["POST"])
@app.route('/manga/update', methods=["POST"])
def update():
    data = request.json
    _, file_path = get_file_paths()
    previous_data = load_previous_data(file_path=file_path)

    if data["url"] in previous_data:
        previous_data[data["url"]]["last_saved"] = previous_data[data["url"]]["last_found"]
        save_data(previous_data, file_path=file_path)

    return jsonify({"status": "success"})

@app.route('/force_update', methods=["POST"])
@app.route('/manga/force_update', methods=["POST"])
def force_update():
    file_path_links, file_path_data = get_file_paths()
    force_update_job(file_path_links, file_path_data, update_type="manga" if request.path.startswith('/manga') else "main")
    return jsonify({"status": "success"})

@app.route('/recheck', methods=["POST"])
@app.route('/manga/recheck', methods=["POST"])
def recheck():
    data = request.json
    _, file_path = get_file_paths()
    previous_data = load_previous_data(file_path=file_path)

    if data["url"] in previous_data:
        latest_chapter, timestamp = scrape_website(data["url"], previous_data, force_update=True)
        previous_data[data["url"]]["last_found"] = latest_chapter
        previous_data[data["url"]]["timestamp"] = timestamp
        save_data(previous_data, file_path=file_path)

    return jsonify({"status": "success"})

@app.route('/add', methods=["POST"])
@app.route('/manga/add', methods=["POST"])
def add_link():
    data = request.json
    file_path_links, file_path_data = get_file_paths()
    links = load_links(file_path=file_path_links)

    new_entry = {"name": data["name"], "url": data["url"]}
    if not any(link["url"] == new_entry["url"] for link in links):
        links.append(new_entry)
        save_links(links, file_path=file_path_links)

    previous_data = load_previous_data(file_path=file_path_data)
    latest_chapter, timestamp = scrape_website(new_entry["url"], previous_data, force_update=True)
    previous_data[new_entry["url"]] = {"name": new_entry["name"], "last_saved": "N/A", "last_found": latest_chapter, "timestamp": timestamp}
    save_data(previous_data, file_path=file_path_data)

    return jsonify({"status": "success"})

@app.route('/remove', methods=["POST"])
@app.route('/manga/remove', methods=["POST"])
def remove_link():
    data = request.json
    file_path_links, file_path_data = get_file_paths()
    links = load_links(file_path=file_path_links)

    def normalize_url(url):
        return url.replace("http://", "").replace("https://", "")

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

if __name__ == "__main__":
    schedule_updates()
    # Force initial full updates
    force_update_job(LINKS_FILE, DATA_FILE, "main")
    force_update_job(MANGA_LINKS_FILE, MANGA_DATA_FILE, "manga")
    app.run(debug=False, port=555)