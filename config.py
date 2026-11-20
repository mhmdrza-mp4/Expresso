"""
Expresso Configuration

Fine-tune scanner, ranking, country priority, and launcher behavior here.
"""

from __future__ import annotations

APP_NAME = "Expresso"

# --- connection -------------------------------------------------------------
CONNECT_TIMEOUT = 20  # max seconds for the CLI "connect" command
CONNECT_WAIT = 8.5  # max seconds to wait for the "connected" state
EARLY_FAIL_SECS = (
    1.5  # "disconnected" this long right after connect -> give up on the server
)
ROUND_PAUSE = 30  # pause between full rounds when every server failed
MANUAL_LOCATIONS: list[str] = []  # e.g. ["germany-frankfurt-1", "uk-london"]

# --- history / ranking ------------------------------------------------------
# HISTORY_FILE (~/.expresso/history.db) is created lazily, see __getattr__ at the bottom.
HISTORY_DAYS = 30  # attempts older than this are ignored
HISTORY_KEEP = 20  # last N attempts per server are considered
DECAY = 0.85  # newer attempts weigh more
PRIOR_RATE = 0.60  # optimistic guess for servers we know nothing about
PRIOR_WEIGHT = 2.0  # how strongly that guess counts
BENCH_AFTER = 2  # consecutive failures before a server is benched
BENCH_BASE_MIN = 10  # first cool-down (minutes), doubles each extra failure
BENCH_MAX_MIN = 360  # cool-down ceiling (minutes)

# --- country priority --------------------------------------------------------
# Countries are tried in this order (best first). The order is a judgement call based on
# how large and well connected ExpressVPN's server clusters are, and how stable their
# links tend to be; ExpressVPN does not publish a per-country ranking. Edit freely.
# Names are matched against the start of the location name, so "usa" also covers
# "usa-new-york", "usa-miami", ... and "germany" covers "germany-frankfurt-1".
# Countries that are not in the list are tried after all of these.
COUNTRY_PRIORITY = [
    "usa",
    "uk",
    "germany",
    "netherlands",
    "canada",
    "france",
    "sweden",
    "switzerland",
    "spain",
    "italy",
    "belgium",
    "denmark",
    "norway",
    "finland",
    "austria",
    "ireland",
    "poland",
    "czech-republic",
    "luxembourg",
    "romania",
    "singapore",
    "japan",
    "hong-kong",
    "australia",
    "south-korea",
    "taiwan",
    "turkey",
    "uae",
    "portugal",
    "hungary",
    "bulgaria",
    "greece",
]
# Other spellings of the same country (all lower-case, words joined by "-").
COUNTRY_ALIASES = {
    "us": "usa",
    "united-states": "usa",
    "united-states-of-america": "usa",
    "america": "usa",
    "united-kingdom": "uk",
    "great-britain": "uk",
    "england": "uk",
    "the-netherlands": "netherlands",
    "holland": "netherlands",
    "czechia": "czech-republic",
    "czech": "czech-republic",
    "united-arab-emirates": "uae",
    "korea": "south-korea",
    "hongkong": "hong-kong",
    "turkiye": "turkey",
}

# --- how the next server is picked ------------------------------------------
# Order of play:
#   1. servers that connected before (and are not resting), country by country in
#      COUNTRY_PRIORITY order; inside a country, the most reliable ones lean to the front
#   2. servers with no successful connection yet, country by country in the same order,
#      randomly inside each country
#   3. servers that are resting after repeated failures (same rules)
# Inside a country the order is a weighted random shuffle: 0 = pure random,
# 3 = leans to the best, 6+ = almost always the best.
PICK_SHARPNESS = 5.0
FAST_PATH_CHANCE = 0.5  # chance to retry the last good server first (skips listing servers);
#                         only used when that server is in the best country you have history with

# --- notification on connect (notify.py) ------------------------------------
NOTIFY_SOUND = True  # play a Windows system sound when the VPN gets connected
NOTIFY_SOUND_FILE = ""  # optional path to your own .wav ("" = pick a Windows sound)
NOTIFY_POPUP = True  # animated card in the bottom-right corner of the screen
NOTIFY_POPUP_SECS = 1.6  # how long the card stays (hover pauses it, click closes it)
NOTIFY_POPUP_SCALE = 0.58  # card size: 1.0 = large, 0.8 = compact, 0.58 = small
NOTIFY_FLASH = True  # blink the taskbar button until the window is brought forward
NOTIFY_TOAST = False  # Windows toast (can be hidden by Focus Assist / app permissions)

# --- UI ---------------------------------------------------------------------
FPS = 20

# --- launcher (launch.py) ---------------------------------------------------
DISCONNECT_VISUAL = True  # animated screen when the launcher disconnects a running VPN
DISCONNECT_HOLD = 1.2  # seconds the "disconnected" screen stays before the window closes
CLOSE_AFTER = 5  # seconds to keep the window open after the VPN is connected
READY_TIMEOUT = 60  # seconds to wait for ExpressVPN to become ready
FALLBACK_AFTER = (
    15  # seconds before trying the Start-menu launch if the direct launch did not help
)
POLL = 0.25  # seconds between CLI polls

# --- executables & network --------------------------------------------------
WIN_CANDIDATES = [
    r"C:\Program Files\ExpressVPN\expressvpnctl.exe",
    r"C:\Program Files (x86)\ExpressVPN\expressvpnctl.exe",
    r"C:\Program Files\ExpressVPN\services\ExpressVPN.CLI.exe",
    r"C:\Program Files (x86)\ExpressVPN\services\ExpressVPN.CLI.exe",
]
CTL_CANDIDATES = [
    r"C:\Program Files\ExpressVPN\expressvpnctl.exe",
    r"C:\Program Files (x86)\ExpressVPN\expressvpnctl.exe",
]
APP_CANDIDATES = [
    r"C:\Program Files\ExpressVPN\expressvpn-client.exe",
    r"C:\Program Files (x86)\ExpressVPN\expressvpn-client.exe",
]

def __getattr__(name):
    # Lazy attribute: importing pathlib costs time, and the launcher does not need it.
    if name == "HISTORY_FILE":
        from pathlib import Path

        return Path.home() / ".expresso" / "history.db"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
