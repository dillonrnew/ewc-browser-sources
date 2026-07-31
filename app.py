"""
Local Flask server for the OBS browser sources.

Instead of every browser source hitting the Google Sheets API on its own
schedule (each with the key baked into client-side JS), this app polls the
sheet once in the background every REFRESH_SECONDS and hands the cached
values to each page over a local endpoint. Pages just fetch /api/data/<key>.
"""
import threading
import time

import requests
from flask import Flask, jsonify, abort, request, send_from_directory

SHEET_ID = "1LBKYJNs68HzP5bYJWfuVBs9FflbE68g7UJcvH9Sjf0c"
API_KEY = "AIzaSyDmo1obbuamahEv3wyV4hh9hfOJ8CW9A9s"
REFRESH_SECONDS = 15

LIVE_EVENT_MAP_URL = "https://scoring.mcdonald.gg/LiveEventMap"
LIVE_EVENT_MAP_REFRESH_SECONDS = 5

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

PAGES = [
    "Main Leaderboard",
    "Lower Leaderboard",
    "Lower Stats",
    "Individual Kills",
    "Team Kills",
    "Placement",
    "Top Bar Info",
    "Live Game Information",
    "Controls",
]

# slug -> filename (without .html), e.g. "team-info-table" -> "Team Info Table"
SLUG_TO_PAGE = {p.lower().replace(" ", "-"): p for p in PAGES}

app = Flask(__name__, static_folder=None)

_cache_lock = threading.Lock()
_cache = {key: {"values": []} for key in RANGES}

_live_event_lock = threading.Lock()
_live_event_cache = {
    "event": "",
    "total_teams": 0,
    "squads_alive": 0,
    "map_number": 0,
    "zone": {"number": 0, "state": "", "countdown": "", "final_circle": False},
    "teams": [],
}

def _mock_player(name, kills, downs, revives, damage, health, armor, plates, cash, is_dead):
    return {
        "name": name, "kills": kills, "is_dead": is_dead, "score": kills * 100 + damage * 0.5,
        "downs": downs, "revives": revives, "damage_done": damage,
        "plates": plates, "armor": armor, "health": health, "cash": cash,
        "last_known_poi": "",
    }


def _mock_team(placement, name, players_data):
    players = [_mock_player(*p) for p in players_data]
    return {
        "team_name": name,
        "placement": placement,
        "team_score": round(sum(p["score"] for p in players), 1),
        "team_downs": sum(p["downs"] for p in players),
        "team_revives": sum(p["revives"] for p in players),
        "team_damage_done": sum(p["damage_done"] for p in players),
        "players": players,
    }


MOCK_LIVE_EVENT_MAP = {
    "event": "DUMMY_Championship_Test",
    "total_teams": 16,
    "squads_alive": 8,
    "map_number": 2,
    "zone": {"number": 4, "state": "closing", "countdown": "1:32", "final_circle": False},
    "match_timer": "18:42",
    "respawn_disabled": True,
    "respawn_remaining": "0:00",
    "fire_sale_active": False,
    "fire_sale_remaining": 0,
    "teams": [
        # -- Alive teams (8) --
        _mock_team(0, "Team Falcons", [
            ("Newbz", 4, 1, 2, 620, 100, 75, 2, 3400, False),
            ("Dongy", 2, 0, 1, 340, 80, 50, 1, 1200, False),
            ("Hisoka", 6, 2, 0, 890, 60, 100, 3, 5600, False),
        ]),
        _mock_team(0, "G2 Esports", [
            ("Cythe", 5, 0, 3, 700, 100, 100, 3, 4100, False),
            ("Bigman", 3, 1, 0, 390, 100, 75, 2, 2200, False),
            ("anziety", 2, 0, 1, 210, 100, 50, 1, 900, False),
        ]),
        _mock_team(0, "Gentle Mates", [
            ("M8 HalloW", 7, 0, 2, 950, 90, 100, 3, 6200, False),
            ("M8 Gromalok", 4, 1, 1, 500, 100, 100, 2, 3100, False),
            ("M8 Enkeo", 3, 0, 0, 340, 75, 50, 1, 1500, False),
        ]),
        _mock_team(0, "Fnatic", [
            ("Vxlcoom", 3, 1, 1, 480, 100, 75, 2, 2900, False),
            ("xRessolve", 2, 0, 0, 260, 90, 50, 1, 1400, False),
            ("XtraJ", 1, 1, 1, 190, 70, 25, 1, 800, False),
        ]),
        _mock_team(0, "Gamax Esport", [
            ("Sleepy", 5, 1, 0, 610, 100, 100, 3, 3800, False),
            ("iR7aL", 2, 0, 2, 300, 100, 75, 2, 1700, False),
            ("CAPA", 1, 0, 0, 120, 60, 25, 0, 500, False),
        ]),
        _mock_team(0, "NEW ICONS", [
            ("Tabeykz", 2, 1, 1, 340, 80, 50, 1, 1600, False),
            ("Vitin", 4, 0, 0, 520, 100, 100, 2, 2800, False),
            ("Padrinnn", 1, 1, 0, 150, 60, 25, 0, 700, False),
        ]),
        _mock_team(0, "GodLike Esports", [
            ("Trikempathy", 6, 0, 1, 780, 100, 100, 3, 4700, False),
            ("Natedogg", 3, 1, 1, 410, 90, 75, 2, 2300, False),
            ("Intechs", 2, 0, 0, 230, 80, 50, 1, 1100, False),
        ]),
        _mock_team(0, "AG.AL", [
            ("ScummN", 1, 0, 0, 90, 50, 25, 0, 400, False),
            ("Fifakill", 0, 0, 0, 0, 40, 0, 0, 0, False),
            ("Knight", 2, 1, 0, 210, 60, 25, 1, 900, False),
        ]),
        # -- Eliminated teams (8), placement = final finish position --
        _mock_team(9, "Leviatán", [
            ("DeusAmir", 1, 2, 0, 150, 0, 0, 0, 0, True),
            ("Criminal God", 3, 1, 1, 410, 0, 0, 0, 0, True),
            ("zDark", 0, 1, 0, 0, 0, 0, 0, 0, True),
        ]),
        _mock_team(10, "Team Orchid", [
            ("Sariel", 2, 1, 0, 280, 0, 0, 0, 0, True),
            ("Master5K", 1, 1, 0, 120, 0, 0, 0, 0, True),
            ("Swiizn", 0, 2, 0, 60, 0, 0, 0, 0, True),
        ]),
        _mock_team(11, "JD Gaming", [
            ("Melvn", 0, 1, 0, 40, 0, 0, 0, 0, True),
            ("Slappy", 1, 1, 0, 90, 0, 0, 0, 0, True),
            ("FLS", 0, 1, 0, 0, 0, 0, 0, 0, True),
        ]),
        _mock_team(12, "Team Nemesis", [
            ("Levi", 1, 3, 0, 220, 0, 0, 0, 0, True),
            ("Lymax", 0, 1, 0, 40, 0, 0, 0, 0, True),
            ("Bray", 2, 2, 1, 310, 0, 0, 0, 0, True),
        ]),
        _mock_team(13, "Ninjas in Pyjamas eStar", [
            ("iVisionSR", 3, 2, 0, 410, 0, 0, 0, 0, True),
            ("KINGAJ", 2, 1, 0, 260, 0, 0, 0, 0, True),
            ("ShowStoppxr", 1, 0, 1, 130, 0, 0, 0, 0, True),
        ]),
        _mock_team(14, "KaadGooyVdaty", [
            ("Kaadxzu", 1, 1, 0, 130, 0, 0, 0, 0, True),
            ("Gooy", 0, 2, 0, 50, 0, 0, 0, 0, True),
            ("VdatY", 2, 1, 0, 240, 0, 0, 0, 0, True),
        ]),
        _mock_team(15, "The Vicious Esports", [
            ("Predkt", 0, 1, 0, 30, 0, 0, 0, 0, True),
            ("xSuldz", 1, 2, 0, 160, 0, 0, 0, 0, True),
            ("ADRENALINE", 0, 1, 0, 20, 0, 0, 0, 0, True),
        ]),
        _mock_team(16, "ForFun Esports", [
            ("JujuSaiyan", 0, 1, 0, 10, 0, 0, 0, 0, True),
            ("Flxnked", 0, 1, 0, 0, 0, 0, 0, 0, True),
            ("BubbleCT", 1, 1, 0, 90, 0, 0, 0, 0, True),
        ]),
    ],
    "timestamp": 0,
}


VIEW_MODES = ("full", "team", "alive")

_view_mode_lock = threading.Lock()
_view_mode = "full"

_hide_dead_gear_lock = threading.Lock()
_hide_dead_gear = False


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


def _fetch_live_event_map():
    try:
        res = requests.get(LIVE_EVENT_MAP_URL, timeout=10)
        res.raise_for_status()
        data = res.json()
        with _live_event_lock:
            _live_event_cache.clear()
            _live_event_cache.update(data)
    except Exception as e:
        print(f"[live event map fetch error] {e}")


def _poll_loop():
    while True:
        _fetch_all()
        time.sleep(REFRESH_SECONDS)


def _live_event_map_poll_loop():
    while True:
        _fetch_live_event_map()
        time.sleep(LIVE_EVENT_MAP_REFRESH_SECONDS)


@app.route("/api/data/<key>")
def api_data(key):
    if key not in RANGES:
        abort(404)
    with _cache_lock:
        return jsonify(_cache[key])


@app.route("/api/live-event-map")
def api_live_event_map():
    with _live_event_lock:
        return jsonify(_live_event_cache)


@app.route("/api/live-event-map-mock")
def api_live_event_map_mock():
    """Dummy dataset for previewing the table before pointing at the real endpoint."""
    return jsonify(MOCK_LIVE_EVENT_MAP)


@app.route("/api/view-mode", methods=["GET", "POST"])
def api_view_mode():
    global _view_mode
    if request.method == "POST":
        mode = (request.get_json(silent=True) or {}).get("mode")
        if mode not in VIEW_MODES:
            abort(400)
        with _view_mode_lock:
            _view_mode = mode
    with _view_mode_lock:
        return jsonify({"mode": _view_mode})


@app.route("/api/hide-dead-gear", methods=["GET", "POST"])
def api_hide_dead_gear():
    """Whether Health/Armor/Plates/Cash should render blank for teams that
    are fully eliminated, instead of whatever stale value the endpoint last
    reported for them."""
    global _hide_dead_gear
    if request.method == "POST":
        value = (request.get_json(silent=True) or {}).get("hide")
        if not isinstance(value, bool):
            abort(400)
        with _hide_dead_gear_lock:
            _hide_dead_gear = value
    with _hide_dead_gear_lock:
        return jsonify({"hide": _hide_dead_gear})


@app.route("/Static/<path:filename>")
def static_files(filename):
    return send_from_directory("Static", filename)


@app.route("/<slug>")
def clean_page(slug):
    page = SLUG_TO_PAGE.get(slug.lower())
    if not page:
        abort(404)
    return send_from_directory(".", page + ".html")


@app.route("/")
def index():
    links = "".join(f'<li><a href="/{slug}">{page}</a></li>' for slug, page in sorted(SLUG_TO_PAGE.items()))
    return f"<h1>Browser Sources</h1><ul>{links}</ul>"


@app.after_request
def _no_cache(response):
    # Pages poll their own data via JS, but browsers were caching the HTML/JS
    # files themselves — so code edits on the server didn't show up until a
    # hard refresh. Force revalidation on every request instead.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


if __name__ == "__main__":
    threading.Thread(target=_poll_loop, daemon=True).start()
    threading.Thread(target=_live_event_map_poll_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
