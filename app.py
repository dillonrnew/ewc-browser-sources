"""
Local Flask server for the OBS browser sources.

Instead of every browser source hitting the Google Sheets API on its own
schedule (each with the key baked into client-side JS), this app polls the
sheet once in the background every REFRESH_SECONDS and hands the cached
values to each page over a local endpoint. Pages just fetch /api/data/<key>.
"""
import os
import threading
import time

import requests
from flask import Flask, jsonify, abort, send_from_directory

SHEET_ID = "1LBKYJNs68HzP5bYJWfuVBs9FflbE68g7UJcvH9Sjf0c"
API_KEY = os.environ.get("GOOGLE_API_KEY", "")
REFRESH_SECONDS = 15

# key -> sheet range. Keys are what the HTML pages request via /api/data/<key>.
RANGES = {
    "main_leaderboard":  "MAIN LEADERBOARD TRANSPOSE!A1:F17",
    "lower_leaderboard": "BOTTOM LEADERBOARD!A1:F17",
    "lower_stats":       "BOTTOM STATS TRANSPOSE!A1:D11",
    "individual_kills":  "PLAYER KILLS TRANSPOSE!A1:C6",
    "team_kills":        "TEAM KILL TRANSPOSE!A1:F6",
    "placement":         "AVG PLACE TRANSPOSE!A1:F6",
    "top_bar_info":      "SETTINGS!B15:B17",
}

app = Flask(__name__, static_folder=None)

_cache_lock = threading.Lock()
_cache = {key: {"values": []} for key in RANGES}


def _fetch_all():
    """One batchGet call for every range, instead of one request per page."""
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values:batchGet"
    params = [("key", API_KEY)] + [("ranges", r) for r in RANGES.values()]
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        value_ranges = data.get("valueRanges", [])
        with _cache_lock:
            for key, vr in zip(RANGES.keys(), value_ranges):
                _cache[key] = {"values": vr.get("values", [])}
    except Exception as e:
        print(f"[sheet fetch error] {e}")


def _poll_loop():
    while True:
        _fetch_all()
        time.sleep(REFRESH_SECONDS)


@app.route("/api/data/<key>")
def api_data(key):
    if key not in RANGES:
        abort(404)
    with _cache_lock:
        return jsonify(_cache[key])


@app.route("/Static/<path:filename>")
def static_files(filename):
    return send_from_directory("Static", filename)


@app.route("/<path:filename>.html")
def html_page(filename):
    return send_from_directory(".", filename + ".html")


@app.route("/")
def index():
    pages = sorted(f.replace(".html", "") for f in RANGES_TO_FILES)
    links = "".join(f'<li><a href="/{p}.html">{p}</a></li>' for p in pages)
    return f"<h1>Browser Sources</h1><ul>{links}</ul>"


RANGES_TO_FILES = [
    "Main Leaderboard",
    "Lower Leaderboard",
    "Lower Stats",
    "Individual Kills",
    "Team Kills",
    "Placement",
    "Top Bar Info",
]


if __name__ == "__main__":
    threading.Thread(target=_poll_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
