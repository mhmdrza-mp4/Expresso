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
JITTER = 0.06  # small randomness so the order isn't fully fixed
BENCH_AFTER = 2  # consecutive failures before a server is benched
BENCH_BASE_MIN = 10  # first cool-down (minutes), doubles each extra failure
BENCH_MAX_MIN = 360  # cool-down ceiling (minutes)

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
