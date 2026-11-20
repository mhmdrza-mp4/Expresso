"""
Expresso Configuration

Fine-tune scanner, health-check, ranking, and launcher behavior here.
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

# --- health check (optional) ------------------------------------------------
# Off by default: a server counts as "connected" as soon as the VPN reports it.
# Turn it on to also require real internet traffic through the tunnel; servers
# that connect but fail this check are then skipped.
VERIFY_TRAFFIC = False
HEALTH_URLS = [
    "https://www.gstatic.com/generate_204",
    "https://cp.cloudflare.com/generate_204",
    "https://www.msftconnecttest.com/connecttest.txt",
]
HEALTH_MIN_PASS = 2  # how many of the URLs must answer
HEALTH_TIMEOUT = 2.5  # seconds per probe
HEALTH_WAIT = 5.0  # total seconds we keep retrying the check
IP_SERVICES = [
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
]

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

# --- quality: prefer fast servers -------------------------------------------
# After a server connects, Expresso measures latency and download speed through
# the tunnel. Servers that are clearly weak are rejected on the spot and the next
# one is tried. Every measurement is stored, so strong servers climb the ranking.
QUALITY_CHECK = True  # False = old behaviour (any server that connects is accepted)
QUALITY_LATENCY_URL = "https://www.gstatic.com/generate_204"
QUALITY_DOWNLOAD_URL = "https://speed.cloudflare.com/__down?bytes={bytes}"
QUALITY_DOWNLOAD_BYTES = 600_000  # small test file; a bigger one is more accurate but slower
QUALITY_TIMEOUT = 3.0  # seconds: cap for each measurement (a weak server costs at most ~this)
QUALITY_MAX_LATENCY_MS = 300  # slower than this -> rejected (round trip through the tunnel)
QUALITY_MIN_MBPS = 2.0  # slower than this -> rejected (short test, so keep it low)
QUALITY_MAX_REJECTS = 6  # after this many rejections the check switches off for this run
#                          (safety net: your own internet may just be slow)
QUALITY_WEIGHT = 0.6  # share of the ranking score that comes from speed (rest = reliability)
QUALITY_PRIOR = 0.5  # assumed speed score for servers that were never measured

# --- how the next server is picked ------------------------------------------
# Weighted random order: a better score means a much higher chance to be tried
# early, but nothing is fixed. 0 = pure random, 3 = leans to the best, 6+ = almost
# always the best. Weak/unknown servers still get an occasional turn.
PICK_SHARPNESS = 5.0
FAST_PATH_CHANCE = 0.5  # chance to retry the last good server first (skips listing servers)

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

USER_AGENT = "Expresso"


def __getattr__(name):
    # Lazy attribute: importing pathlib costs time, and the launcher does not need it.
    if name == "HISTORY_FILE":
        from pathlib import Path

        return Path.home() / ".expresso" / "history.db"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
