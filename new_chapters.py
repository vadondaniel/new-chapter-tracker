from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import logging
from scraping import load_links, save_links, save_data, load_previous_data, wait_for_chromedriver, scrape_website, scrape_all_links, LINKS_FILE, MANGA_LINKS_FILE, DATA_FILE, MANGA_DATA_FILE

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
socketio = SocketIO(app)
update_in_progress = False
last_full_update = {"main": None, "manga": None}

# Pass the socketio object to scraping.py
import scraping
scraping.socketio = socketio

def force_update_job(file_path_links, file_path_data, update_type="main"):
    global last_full_update
    with app.app_context():
        logging.info("Starting scheduled force update...")
        links = load_links(file_path=file_path_links)
        previous_data = load_previous_data(file_path=file_path_data)
        new_data = scrape_all_links(links, previous_data, force_update=True)
        
        # Update previous_data with new_data
        for url, data in new_data.items():
            if url in previous_data:
                previous_data[url]["last_found"] = data["last_found"]
                previous_data[url]["timestamp"] = data["timestamp"]
            else:
                previous_data[url] = data
        
        save_data(previous_data, file_path=file_path_data)
        last_full_update[update_type] = datetime.now().isoformat()
        logging.info("Scheduled force update completed.")

def schedule_updates():
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: force_update_job(LINKS_FILE, DATA_FILE, "main"), 'interval', hours=1)
    scheduler.add_job(lambda: force_update_job(MANGA_LINKS_FILE, MANGA_DATA_FILE, "manga"), 'interval', hours=5)
    scheduler.start()

@app.route('/')
@app.route('/manga')
def index():
    file_path = MANGA_DATA_FILE if request.path.startswith('/manga') else DATA_FILE
    previous_data = load_previous_data(file_path=file_path)
    
    # Separate entries where last_found and last_saved do not match
    differences = {url: data for url, data in previous_data.items() if data["last_found"] != data["last_saved"]}
    same_data = {url: data for url, data in previous_data.items() if data["last_found"] == data["last_saved"]}
    
    # Sort the dictionaries by timestamp in descending order
    differences = dict(sorted(differences.items(), key=lambda item: item[1]["timestamp"], reverse=True))
    same_data = dict(sorted(same_data.items(), key=lambda item: item[1]["timestamp"], reverse=True))
    
    update_type = "manga" if request.path.startswith('/manga') else "main"
    logging.info(last_full_update[update_type])
    return render_template("index.html", differences=differences, same_data=same_data, update_in_progress=update_in_progress, last_full_update=last_full_update[update_type])

@app.route('/update', methods=["POST"])
@app.route('/manga/update', methods=["POST"])
def update():
    data = request.json
    file_path = MANGA_DATA_FILE if request.path.startswith('/manga') else DATA_FILE
    previous_data = load_previous_data(file_path=file_path)
    
    if data["url"] in previous_data:
        previous_data[data["url"]]["last_saved"] = previous_data[data["url"]]["last_found"]
        save_data(previous_data, file_path=file_path)
    
    return jsonify({"status": "success"})

@app.route('/force_update', methods=["POST"])
@app.route('/manga/force_update', methods=["POST"])
def force_update():
    file_path_links = MANGA_LINKS_FILE if request.path.startswith('/manga') else LINKS_FILE
    file_path_data = MANGA_DATA_FILE if request.path.startswith('/manga') else DATA_FILE
    links = load_links(file_path=file_path_links)
    previous_data = load_previous_data(file_path=file_path_data)
    new_data = scrape_all_links(links, previous_data, force_update=True)
    
    # Update previous_data with new_data
    for url, data in new_data.items():
        if url in previous_data:
            previous_data[url]["last_found"] = data["last_found"]
            previous_data[url]["timestamp"] = data["timestamp"]
        else:
            previous_data[url] = data
    
    save_data(previous_data, file_path=file_path_data)
    
    # Update last_full_update
    update_type = "manga" if request.path.startswith('/manga') else "main"
    last_full_update[update_type] = datetime.now().isoformat()
    logging.info(f"Force update completed for {update_type}. Last full update: {last_full_update[update_type]}")
    
    return jsonify({"status": "success"})

@app.route('/recheck', methods=["POST"])
@app.route('/manga/recheck', methods=["POST"])
def recheck():
    data = request.json
    file_path = MANGA_DATA_FILE if request.path.startswith('/manga') else DATA_FILE
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
    file_path_links = MANGA_LINKS_FILE if request.path.startswith('/manga') else LINKS_FILE
    file_path_data = MANGA_DATA_FILE if request.path.startswith('/manga') else DATA_FILE
    links = load_links(file_path=file_path_links)
    
    new_entry = {"name": data["name"], "url": data["url"]}
    if not any(link["url"] == new_entry["url"] for link in links):
        links.append(new_entry)
        save_links(links, file_path=file_path_links)
    
    # Initialize the new entry in the appropriate data file
    previous_data = load_previous_data(file_path=file_path_data)
    latest_chapter, timestamp = scrape_website(new_entry["url"], previous_data, force_update=True)
    previous_data[new_entry["url"]] = {"name": new_entry["name"], "last_saved": "N/A", "last_found": latest_chapter, "timestamp": timestamp}
    save_data(previous_data, file_path=file_path_data)
    
    return jsonify({"status": "success"})

if __name__ == "__main__":
    schedule_updates()
    # wait_for_chromedriver()
    force_update_job(LINKS_FILE, DATA_FILE, "main")  # Force a full update when the app starts
    force_update_job(MANGA_LINKS_FILE, MANGA_DATA_FILE, "manga")
    app.run(debug=False, port=555)