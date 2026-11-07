#!/usr/bin/env python3
"""
Expresso

Tests ExpressVPN locations one by one, verifies that real internet traffic
works through the tunnel, and stays connected to the first server that passes.

  * Optional traffic check (VERIFY_TRAFFIC): after the tunnel is up, several
    HTTPS endpoints are probed and the public IP must change.
  * Server history (SQLite): every attempt is remembered. Good servers are
    tried first, unknown ones get a fair chance, and servers that keep failing
    are put on hold for a while ("resting"), with a growing cool-down.
  * Animated terminal UI (built on `rich`).

Usage:
    python expresso.py                 run for real
    python expresso.py --demo          preview the UI with a fake VPN backend
    python expresso.py --reset-history forget everything learned so far
"""

from __future__ import annotations

import math
import os
import random
import subprocess
import sys
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from rich import box
from rich.align import Align
from rich.color import Color
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text

from config import (
    APP_NAME,
    BENCH_AFTER,
    BENCH_BASE_MIN,
    BENCH_MAX_MIN,
    CONNECT_TIMEOUT,
    CONNECT_WAIT,
    DECAY,
    EARLY_FAIL_SECS,
    FPS,
    HEALTH_MIN_PASS,
    HEALTH_TIMEOUT,
    HEALTH_URLS,
    HEALTH_WAIT,
    HISTORY_DAYS,
    HISTORY_FILE,
    HISTORY_KEEP,
    IP_SERVICES,
    JITTER,
    MANUAL_LOCATIONS,
    PRIOR_RATE,
    PRIOR_WEIGHT,
    ROUND_PAUSE,
    USER_AGENT,
    VERIFY_TRAFFIC,
    WIN_CANDIDATES,
)

# ============================================================
#                    COLOR / DRAWING HELPERS
# ============================================================

C_CYAN = (34, 211, 238)
C_BLUE = (96, 165, 250)
C_VIOLET = (167, 139, 250)
C_PINK = (244, 114, 182)
C_GREEN = (74, 222, 128)
C_TEAL = (45, 212, 191)
C_RED = (248, 113, 113)
C_AMBER = (251, 191, 36)
C_TEXT = (229, 231, 235)
C_MUTED = (107, 114, 128)
C_DIM = (55, 65, 81)
C_TRACK = (31, 41, 55)
WHITE = (255, 255, 255)

LOGO_STOPS = [
    (245, 222, 179),
    (251, 191, 36),
    (217, 119, 6),
    (146, 84, 40),
    (217, 119, 6),
    (251, 191, 36),
]
OK_STOPS = [C_GREEN, C_TEAL, C_CYAN, C_TEAL]

SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def lerp(a, b, k):
    k = max(0.0, min(1.0, k))
    return tuple(a[i] + (b[i] - a[i]) * k for i in range(3))


def hx(c):
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, v))) for v in c)


def fg(c, bold=False, dim=False):
    return Style(color=Color.from_rgb(*(int(v) for v in c)), bold=bold, dim=dim)


def palette(stops, pos):
    n = len(stops)
    p = (pos % 1.0) * n
    i = int(p)
    return lerp(stops[i % n], stops[(i + 1) % n], p - i)


def pulse(t, speed=2.0):
    return 0.5 + 0.5 * math.sin(t * speed)


LOGO = [
    "███████╗██╗  ██╗██████╗ ██████╗ ███████╗███████╗███████╗ ██████╗ ",
    "██╔════╝╚██╗██╔╝██╔══██╗██╔══██╗██╔════╝██╔════╝██╔════╝██╔═══██╗",
    "█████╗   ╚███╔╝ ██████╔╝██████╔╝█████╗  ███████╗███████╗██║   ██║",
    "██╔══╝   ██╔██╗ ██╔═══╝ ██╔══██╗██╔══╝  ╚════██║╚════██║██║   ██║",
    "███████╗██╔╝ ██╗██║     ██║  ██║███████╗███████║███████║╚██████╔╝",
    "╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝ ╚═════╝ ",
]

ART_CONNECTED = [
    " ██████╗ ██████╗ ███╗   ██╗███╗   ██╗███████╗ ██████╗████████╗███████╗██████╗ ",
    "██╔════╝██╔═══██╗████╗  ██║████╗  ██║██╔════╝██╔════╝╚══██╔══╝██╔════╝██╔══██╗",
    "██║     ██║   ██║██╔██╗ ██║██╔██╗ ██║█████╗  ██║        ██║   █████╗  ██║  ██║",
    "██║     ██║   ██║██║╚██╗██║██║╚██╗██║██╔══╝  ██║        ██║   ██╔══╝  ██║  ██║",
    "╚██████╗╚██████╔╝██║ ╚████║██║ ╚████║███████╗╚██████╗   ██║   ███████╗██████╔╝",
    " ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═══╝╚══════╝ ╚═════╝   ╚═╝   ╚══════╝╚═════╝ ",
]

ART_ONLINE = [
    " ██████╗ ███╗   ██╗██╗     ██╗███╗   ██╗███████╗",
    "██╔═══██╗████╗  ██║██║     ██║████╗  ██║██╔════╝",
    "██║   ██║██╔██╗ ██║██║     ██║██╔██╗ ██║█████╗  ",
    "██║   ██║██║╚██╗██║██║     ██║██║╚██╗██║██╔══╝  ",
    "╚██████╔╝██║ ╚████║███████╗██║██║ ╚████║███████╗",
    " ╚═════╝ ╚═╝  ╚═══╝╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝",
]


def gradient_text(lines, t, stops=LOGO_STOPS, shadow=False, sweep=True, speed=0.18):
    """Multi-line text with a flowing colour gradient and a light sweep."""
    width = max(len(line) for line in lines)
    sweep_pos = (t * 30) % (width + 44) - 22
    out = Text(no_wrap=True)
    for li, line in enumerate(lines):
        for x, ch in enumerate(line.ljust(width)):
            if ch == " ":
                out.append(" ")
                continue
            col = palette(stops, x / width - t * speed + li * 0.02)
            if sweep:
                boost = max(0.0, 1 - abs(x - li * 1.5 - sweep_pos) / 7)
                col = lerp(col, WHITE, boost * 0.55)
            bold = True
            if shadow and ch != "█":
                col = lerp(col, (0, 0, 0), 0.55)
                bold = False
            out.append(ch, fg(col, bold=bold))
        if li < len(lines) - 1:
            out.append("\n")
    return out


def smooth_bar(ratio, width, t, c1, c2, shimmer=True):
    """Progress bar with 1/8 cell precision, gradient fill and a shimmer."""
    width = max(width, 4)
    ratio = max(0.0, min(1.0, ratio))
    exact = ratio * width
    full = int(exact)
    frac = exact - full
    parts = " ▏▎▍▌▋▊▉"
    track = Color.from_rgb(*C_TRACK)
    out = Text(no_wrap=True)
    pos = (t * 18) % (width + 12) - 6
    for i in range(width):
        col = lerp(c1, c2, i / max(1, width - 1))
        if i < full:
            if shimmer:
                col = lerp(col, WHITE, max(0.0, 1 - abs(i - pos) / 4) * 0.5)
            out.append("█", fg(col))
        elif i == full and frac > 0:
            out.append(
                parts[int(frac * 8)],
                Style(color=Color.from_rgb(*(int(v) for v in col)), bgcolor=track),
            )
        else:
            out.append(" ", Style(bgcolor=track))
    return out


# ============================================================
#                    DATA MODELS
# ============================================================


@dataclass
class HealthResult:
    ok: bool
    latency: float | None = None  # median ms of the successful probes
    passed: int = 0
    total: int = 0
    ip: str | None = None
    ip_changed: bool | None = None
    reason: str = ""


@dataclass
class ServerStat:
    location: str
    attempts: int
    rate: float
    avg_latency: float | None
    streak: int
    last_ts: float
    score: float
    benched: bool
    recent: list  # newest first, list[bool]


STAGES_ALL = [
    ("RESET", "Clearing previous tunnel"),
    ("CONNECT", "Opening encrypted tunnel"),
    ("HANDSHAKE", "Waiting for the handshake"),
    ("VERIFY", "Testing real internet traffic"),
]
STAGES = STAGES_ALL if VERIFY_TRAFFIC else STAGES_ALL[:3]
N_STAGES = len(STAGES)


class State:
    """Shared between the scanner thread (writer) and the UI (reader)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.phase = "init"  # init / scanning / pause / connected / error / stopped
        self.message = "Starting up"
        self.error: str | None = None
        self.started = time.monotonic()
        self.done_at: float | None = None

        self.location: str | None = None
        self.active_stage = -1
        self.stage_state = ["wait"] * N_STAGES
        self.stage_time: list[float | None] = [None] * N_STAGES
        self.stage_detail: list[str | None] = [None] * N_STAGES
        self.stage_started = 0.0
        self.flash: tuple[float, str] | None = None
        self.fail_reason: str | None = None

        self.round_no = 0
        self.completed = 0
        self.total = 0
        self.tested = 0
        self.failed = 0
        self.benched = 0
        self.known = 0
        self.pause_left = 0
        self.pause_total = 1

        self.log: deque = deque(maxlen=80)
        self.board: list[ServerStat] = []
        self.real_ip: str | None = None
        self.result: dict | None = None
        self.tunnel_clean = (
            False  # True once a disconnect has completed and nothing connected since
        )

    # -- attempt bookkeeping ---------------------------------------------
    def begin_attempt(self, location):
        self.location = location
        self.active_stage = -1
        self.stage_state = ["wait"] * N_STAGES
        self.stage_time = [None] * N_STAGES
        self.stage_detail = [None] * N_STAGES
        self.fail_reason = None
        self.message = "Preparing probe"

    def stage_begin(self, i):
        self.active_stage = i
        self.stage_state[i] = "active"
        self.stage_started = time.monotonic()
        self.message = STAGES[i][1]

    def stage_end(self, i, ok, detail=None):
        self.stage_time[i] = time.monotonic() - self.stage_started
        self.stage_state[i] = "ok" if ok else "fail"
        self.stage_detail[i] = detail
        if not ok:
            self.flash = (time.monotonic(), "fail")
        elif i == len(STAGES) - 1:
            self.flash = (time.monotonic(), "ok")

    def add_log(self, entry):
        with self.lock:
            self.log.append(entry)

    def log_snapshot(self):
        with self.lock:
            return list(self.log)


# ============================================================
#                    HISTORY & RANKING
# ============================================================


sqlite3 = None  # imported by History on first use (keeps start-up fast)


class History:
    """Small SQLite store with every connection attempt ever made."""

    def __init__(self, path: Path):
        global sqlite3
        import sqlite3  # noqa: F811 - lazy: the UI must not wait for it

        self.path = path
        self.lock = threading.Lock()
        self.usable = True
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._db() as c:
                c.execute(
                    "CREATE TABLE IF NOT EXISTS attempts ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, "
                    "location TEXT NOT NULL, ok INTEGER NOT NULL, "
                    "connect_time REAL, latency_ms REAL, ip TEXT, reason TEXT)"
                )
                c.execute(
                    "CREATE INDEX IF NOT EXISTS idx_attempts_loc "
                    "ON attempts(location, ts)"
                )
                cutoff = time.time() - HISTORY_DAYS * 2 * 86400
                if c.execute(
                    "SELECT 1 FROM attempts WHERE ts < ? LIMIT 1", (cutoff,)
                ).fetchone():
                    c.execute("DELETE FROM attempts WHERE ts < ?", (cutoff,))
        except (sqlite3.Error, OSError):
            self.usable = False

    @contextmanager
    def _db(self):
        with self.lock:
            conn = sqlite3.connect(self.path, timeout=5)
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def record(self, location, ok, connect_time, latency_ms, ip, reason):
        if not self.usable:
            return
        try:
            with self._db() as c:
                c.execute(
                    "INSERT INTO attempts "
                    "(ts, location, ok, connect_time, latency_ms, ip, reason) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        time.time(),
                        location,
                        int(ok),
                        connect_time,
                        latency_ms,
                        ip,
                        reason,
                    ),
                )
        except sqlite3.Error:
            pass

    def reset(self):
        if not self.usable:
            return
        with self._db() as c:
            c.execute("DELETE FROM attempts")

    def last_success(self):
        """Most recent server that connected and has not failed since."""
        if not self.usable:
            return None
        try:
            with self._db() as c:
                row = c.execute(
                    "SELECT location, ts FROM attempts WHERE ok = 1 AND ts > ? "
                    "ORDER BY ts DESC LIMIT 1",
                    (time.time() - HISTORY_DAYS * 86400,),
                ).fetchone()
                if not row:
                    return None
                failed_since = c.execute(
                    "SELECT 1 FROM attempts WHERE location = ? AND ok = 0 AND ts > ? LIMIT 1",
                    (row[0], row[1]),
                ).fetchone()
                return None if failed_since else row[0]
        except sqlite3.Error:
            return None

    def load(self) -> dict[str, ServerStat]:
        if not self.usable:
            return {}
        try:
            with self._db() as c:
                rows = c.execute(
                    "SELECT location, ok, latency_ms, ts FROM attempts "
                    "WHERE ts > ? ORDER BY ts DESC",
                    (time.time() - HISTORY_DAYS * 86400,),
                ).fetchall()
        except sqlite3.Error:
            return {}

        per: dict[str, list] = defaultdict(list)
        for loc, ok, lat, ts in rows:
            if len(per[loc]) < HISTORY_KEEP:
                per[loc].append((bool(ok), lat, ts))

        now = time.time()
        out: dict[str, ServerStat] = {}
        for loc, items in per.items():
            weights = [DECAY**i for i in range(len(items))]
            wsum = sum(weights)
            wok = sum(w for w, it in zip(weights, items) if it[0])
            rate = (wok + PRIOR_RATE * PRIOR_WEIGHT) / (wsum + PRIOR_WEIGHT)
            lats = [it[1] for it in items if it[0] and it[1]]
            avg_lat = sum(lats) / len(lats) if lats else None
            streak = 0
            for it in items:
                if it[0]:
                    break
                streak += 1
            last_ts = items[0][2]
            benched = False
            if streak >= BENCH_AFTER:
                cooldown = min(
                    BENCH_BASE_MIN * 2 ** (streak - BENCH_AFTER), BENCH_MAX_MIN
                )
                benched = (now - last_ts) < cooldown * 60
            lat_score = 1 / (1 + avg_lat / 400) if avg_lat else 0.45
            out[loc] = ServerStat(
                location=loc,
                attempts=len(items),
                rate=rate,
                avg_latency=avg_lat,
                streak=streak,
                last_ts=last_ts,
                score=0.75 * rate + 0.25 * lat_score,
                benched=benched,
                recent=[it[0] for it in items[:8]],
            )
        return out


def order_locations(locations, stats):
    """Best-known first, unknown ones mixed in fairly, benched ones last."""
    unknown_score = 0.75 * PRIOR_RATE + 0.25 * 0.45
    active, benched = [], []
    for loc in locations:
        st = stats.get(loc)
        score = (st.score if st else unknown_score) + random.uniform(0, JITTER)
        (benched if st and st.benched else active).append((score, loc))
    active.sort(reverse=True)
    benched.sort(reverse=True)
    return [loc for _, loc in active] + [loc for _, loc in benched], len(benched)


def leaderboard(stats, limit=12):
    ranked = sorted(stats.values(), key=lambda s: (s.benched, -s.score))
    return ranked[:limit]


# ============================================================
#                    BACKENDS
# ============================================================


def find_cli():
    hint = os.environ.get("EXPRESSO_CTL")  # set by launch.py
    if hint:
        return hint, ("ctl" if "expressvpnctl" in hint.lower() else "legacy")
    import shutil  # lazy

    if shutil.which("expressvpnctl"):
        return "expressvpnctl", "ctl"
    if shutil.which("expressvpn"):
        return "expressvpn", "legacy"
    for path in WIN_CANDIDATES:
        if Path(path).is_file():
            flavor = "ctl" if "expressvpnctl" in path.lower() else "legacy"
            return path, flavor
    raise FileNotFoundError(
        "ExpressVPN CLI was not found. Check your ExpressVPN installation."
    )


def run_cli(cli, args, timeout=30):
    result = subprocess.run(
        [cli, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
    )
    output = (result.stdout + "\n" + result.stderr).strip()
    return output, result.returncode


def probe(url, timeout):
    """Return the response time in ms, or None when the probe failed."""
    import urllib.request  # lazy: only needed for the optional traffic check

    started = time.monotonic()
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(256)
            if resp.status in (200, 204):
                return (time.monotonic() - started) * 1000
    except Exception:
        pass
    return None


class ExpressBackend:
    handshake_wait = CONNECT_WAIT

    def __init__(self):
        self.cli, self.flavor = find_cli()

    def locations(self):
        if MANUAL_LOCATIONS:
            return list(dict.fromkeys(MANUAL_LOCATIONS))
        if self.flavor == "ctl":
            output, code = run_cli(self.cli, ["get", "regions"])
        else:
            output, code = run_cli(self.cli, ["list", "all"])
        if code != 0:
            raise RuntimeError(output or "Could not retrieve server locations.")

        found = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            if self.flavor == "legacy":
                if line.startswith(("ALIAS", "-")):
                    continue
                found.append(line.split()[0])
            else:
                if line.lower() in ("region", "regions", "available regions"):
                    continue
                found.append(line)
        return list(dict.fromkeys(found))

    def connect(self, location):
        output, code = run_cli(self.cli, ["connect", location], timeout=CONNECT_TIMEOUT)
        if code != 0:
            first = (output.splitlines() or [""])[0].strip()
            return False, (
                ("CLI error: " + first[:44]) if first else "CLI connection error"
            )
        return True, ""

    def disconnect(self):
        try:
            run_cli(self.cli, ["disconnect"], timeout=15)
            return True
        except (subprocess.TimeoutExpired, OSError):
            return False

    def poll(self):
        """One CLI call -> 'connected', 'disconnected', another state, or None."""
        if self.flavor == "ctl":
            try:
                out, code = run_cli(self.cli, ["get", "connectionstate"], timeout=8)
            except (subprocess.TimeoutExpired, OSError):
                return None
            return out.strip().lower() if code == 0 else None
        return "connected" if self.is_connected() else None

    def is_connected(self):
        try:
            if self.flavor == "ctl":
                out, code = run_cli(self.cli, ["get", "connectionstate"], timeout=8)
                return code == 0 and out.strip().lower() == "connected"
            out, code = run_cli(self.cli, ["status"], timeout=8)
            status = out.lower()
            return code == 0 and (
                "connected to" in status or status.strip().startswith("connected")
            )
        except (subprocess.TimeoutExpired, OSError):
            return False

    def public_ip(self, timeout=2.5):
        import ipaddress  # lazy: only needed for the optional traffic check
        import urllib.request

        for url in IP_SERVICES:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    text = resp.read(64).decode(errors="ignore").strip()
                ipaddress.ip_address(text)
                return text
            except Exception:
                continue
        return None

    def health(self, real_ip, stop):
        """Probe several endpoints in parallel until enough of them answer."""
        import statistics  # lazy: only needed for the optional traffic check
        from concurrent.futures import ThreadPoolExecutor

        total = len(HEALTH_URLS)
        deadline = time.monotonic() + HEALTH_WAIT
        good: list[float] = []
        with ThreadPoolExecutor(total) as pool:
            while True:
                results = list(
                    pool.map(lambda u: probe(u, HEALTH_TIMEOUT), HEALTH_URLS)
                )
                good = [r for r in results if r is not None]
                if len(good) >= HEALTH_MIN_PASS:
                    break
                if stop.is_set() or time.monotonic() >= deadline:
                    return HealthResult(
                        False,
                        None,
                        len(good),
                        total,
                        reason=f"No real traffic ({len(good)}/{total} probes)",
                    )
                stop.wait(0.6)

        ip = self.public_ip()
        changed = None if (ip is None or real_ip is None) else ip != real_ip
        if changed is False:
            return HealthResult(
                False,
                None,
                len(good),
                total,
                ip,
                False,
                reason="IP unchanged - tunnel not routing",
            )
        return HealthResult(
            True, statistics.median(good), len(good), total, ip, changed
        )


class DemoBackend:
    """Fake VPN so the UI can be previewed without ExpressVPN installed."""

    handshake_wait = 2.2

    # The demo is scripted: the first servers fail in these ways, then the next
    # one connects. Handy for recording a GIF. Edit the list to change the story.
    FAIL_PLAN = ["handshake", "cli", "handshake"]

    NAMES = [
        "USA - New York",
        "USA - Los Angeles",
        "USA - Miami",
        "USA - Chicago",
        "UK - London",
        "UK - Docklands",
        "Germany - Frankfurt",
        "Germany - Nuremberg",
        "Netherlands - Amsterdam",
        "France - Paris",
        "Switzerland",
        "Sweden",
        "Spain - Madrid",
        "Italy - Milan",
        "Canada - Toronto",
        "Japan - Tokyo",
        "Singapore - CBD",
        "Hong Kong",
        "Turkey",
        "UAE - Dubai",
        "Australia - Sydney",
        "Poland",
        "Romania",
        "Brazil - Sao Paulo",
    ]

    def __init__(self):
        rnd = random.Random(11)
        self.quality = {n: rnd.random() ** 1.5 * 0.9 + 0.04 for n in self.NAMES}
        self.plan = "ok"
        self.connected_at = 0.0
        self.attempts = 0

    def locations(self):
        time.sleep(0.6)
        return list(self.NAMES)

    def connect(self, location):
        time.sleep(random.uniform(0.8, 1.5))
        self.attempts += 1
        if self.attempts <= len(self.FAIL_PLAN):
            self.plan = self.FAIL_PLAN[self.attempts - 1]
        else:
            self.plan = "ok"
        if self.plan == "cli":
            return False, "CLI error: server unavailable"
        self.connected_at = time.monotonic() + random.uniform(0.4, 1.0)
        return True, ""

    def disconnect(self):
        time.sleep(0.25)

    def is_connected(self):
        if self.plan == "handshake":
            return False
        return time.monotonic() >= self.connected_at

    def poll(self):
        return "connected" if self.is_connected() else "connecting"

    def public_ip(self, timeout=2.5):
        time.sleep(0.4)
        return ".".join(str(random.randint(11, 220)) for _ in range(4))

    def health(self, real_ip, stop):
        time.sleep(random.uniform(0.9, 1.7))
        if self.plan == "health":
            return HealthResult(
                False,
                None,
                random.choice([0, 1]),
                3,
                reason="No real traffic (0/3 probes)",
            )
        return HealthResult(True, random.uniform(55, 320), 3, 3, self.public_ip(), True)


# ============================================================
#                    SCANNER ENGINE (worker thread)
# ============================================================


class Fail(Exception):
    pass


class Stopped(Exception):
    pass


def attempt(state, backend, location, stop):
    """Run the stages for one server. Returns (ok, seconds, health, reason)."""
    started = time.monotonic()
    health = None
    stage = 0
    try:
        state.stage_begin(0)
        if not state.tunnel_clean:
            state.tunnel_clean = backend.disconnect() is not False
        state.stage_end(0, True)
        if stop.is_set():
            raise Stopped

        stage = 1
        state.stage_begin(1)
        state.tunnel_clean = False
        ok, message = backend.connect(location)
        if not ok:
            raise Fail(message)
        state.stage_end(1, True)

        stage = 2
        state.stage_begin(2)
        deadline = time.monotonic() + backend.handshake_wait
        dead_since = None
        while True:
            conn_state = backend.poll()
            if conn_state == "connected":
                break
            if stop.is_set():
                raise Stopped
            now = time.monotonic()
            if now > deadline:
                raise Fail("Handshake timeout")
            if conn_state == "disconnected":
                dead_since = dead_since or now
                if now - dead_since >= EARLY_FAIL_SECS:
                    raise Fail("Server refused")
            else:
                dead_since = None
            stop.wait(0.08)  # each poll is a CLI call anyway; a short gap only shaves detection latency
        state.stage_end(2, True)
        if not VERIFY_TRAFFIC:
            return True, time.monotonic() - started, None, "Connected"

        stage = 3
        state.stage_begin(3)
        health = backend.health(state.real_ip, stop)
        if stop.is_set():
            raise Stopped
        if not health.ok:
            raise Fail(health.reason)
        state.stage_end(
            3, True, f"{health.passed}/{health.total} · {health.latency:.0f}ms"
        )
        return True, time.monotonic() - started, health, "Connected"

    except Stopped:
        raise
    except Fail as exc:
        reason = str(exc)
    except subprocess.TimeoutExpired:
        reason = "Command timeout"
    except Exception as exc:  # noqa: BLE001
        reason = str(exc)[:60] or exc.__class__.__name__

    state.stage_end(stage, False)
    state.fail_reason = reason
    state.message = reason
    state.tunnel_clean = backend.disconnect() is not False
    return False, time.monotonic() - started, health, reason


def run_scanner(state, backend_factory, history, stop):
    try:
        state.message = "Locating ExpressVPN CLI"
        backend = backend_factory()

        # Fast path: try the last server that worked before listing all locations.
        preferred = None if MANUAL_LOCATIONS else history.last_success()
        locations = None
        skip = None
        if preferred is None:
            state.message = "Discovering server locations"
            locations = backend.locations()
            if not locations:
                raise RuntimeError("No server locations found. Check MANUAL_LOCATIONS.")

        state.message = "Clearing any old tunnel"
        if os.environ.get("EXPRESSO_ASSUME_CLEAN") == "1":
            state.tunnel_clean = True  # the launcher already saw "Disconnected"
        else:
            state.tunnel_clean = backend.disconnect() is not False
        if VERIFY_TRAFFIC:
            state.message = "Detecting your real IP address"
            state.real_ip = backend.public_ip()

        state.phase = "scanning"
        while not stop.is_set():
            state.round_no += 1
            stats = history.load()
            if locations is None:
                ordered, benched = [preferred], 0
            else:
                ordered, benched = order_locations(locations, stats)
                if skip:
                    ordered = [loc for loc in ordered if loc != skip]
            state.total = len(ordered)
            state.completed = 0
            state.benched = benched
            state.known = len(stats)
            state.board = leaderboard(stats)

            for loc in ordered:
                if stop.is_set():
                    raise Stopped
                state.begin_attempt(loc)
                ok, seconds, health, reason = attempt(state, backend, loc, stop)

                latency = health.latency if health else None
                ip = health.ip if health else None
                history.record(loc, ok, seconds, latency, ip, reason)

                state.tested += 1
                state.completed += 1
                if not ok:
                    state.failed += 1
                state.add_log(
                    {
                        "n": state.tested,
                        "location": loc,
                        "ok": ok,
                        "seconds": seconds,
                        "latency": latency,
                        "ip": ip,
                        "reason": reason,
                        "ts": time.monotonic(),
                    }
                )
                state.board = leaderboard(history.load())

                if ok:
                    state.result = {
                        "location": loc,
                        "ip": ip,
                        "seconds": seconds,
                        "latency": latency,
                        "passed": health.passed if health else None,
                        "total": health.total if health else None,
                        "ip_changed": health.ip_changed if health else None,
                    }
                    state.done_at = time.monotonic()
                    state.phase = "connected"
                    return

            if locations is None:
                # Last known good server failed: discover everything and scan normally.
                skip = preferred
                state.message = "Discovering server locations"
                locations = backend.locations()
                if not locations:
                    raise RuntimeError(
                        "No server locations found. Check MANUAL_LOCATIONS."
                    )
                state.round_no -= 1
                continue

            # every server failed -> short break, then next round
            state.phase = "pause"
            state.location = None
            state.pause_total = ROUND_PAUSE
            for remaining in range(ROUND_PAUSE, 0, -1):
                if stop.is_set():
                    raise Stopped
                state.pause_left = remaining
                stop.wait(1)
            state.phase = "scanning"

    except Stopped:
        pass
    except Exception as exc:  # noqa: BLE001
        state.error = str(exc) or exc.__class__.__name__
        state.phase = "error"


# ============================================================
#                    TERMINAL VISUALS
# ============================================================


def border_color(state, t):
    if state.phase == "pause":
        return hx(lerp(C_AMBER, (146, 64, 14), pulse(t, 1.5)))
    if state.phase == "init":
        return hx(lerp(C_BLUE, C_VIOLET, pulse(t)))
    if state.flash and time.monotonic() - state.flash[0] < 0.6:
        return hx(C_GREEN if state.flash[1] == "ok" else C_RED)
    return hx(lerp(C_CYAN, C_VIOLET, pulse(t, 1.2)))


def panel(content, title, border, subtitle=None, **kw):
    return Panel(
        content,
        title=Text(f" {title} ", style=fg(C_TEXT, bold=True)),
        subtitle=Text(f" {subtitle} ", style=fg(C_MUTED)) if subtitle else None,
        border_style=border,
        box=box.ROUNDED,
        **kw,
    )


def fmt_clock(seconds):
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


# ---------- header ----------


def render_header(state, t, compact, border):
    taglines = {
        "init": "warming up the machine",
        "scanning": "pulling the best server",
        "pause": "all shots failed - cooling down",
        "connected": "your shot is ready",
    }
    tag = taglines.get(state.phase, "")
    if compact:
        title = gradient_text(["E X P R E S S O"], t)
        return Panel(
            Align.center(title), box=box.ROUNDED, border_style=border, padding=(0, 1)
        )

    sub = Text(no_wrap=True)
    sub.append("S E R V E R   S C A N N E R", fg(C_TEXT, bold=True))
    sub.append("   ·   ", fg(C_DIM))
    sub.append(tag, fg(C_CYAN))
    return Panel(
        Group(
            Align.center(gradient_text(LOGO, t, shadow=True)),
            Align.center(sub),
        ),
        box=box.ROUNDED,
        border_style=border,
        padding=(0, 1),
    )


# ---------- active probe ----------


def render_tunnel(state, t, length):
    """YOU ●───◆──◆───● SERVER  with packets flying through the tunnel."""
    stage = state.active_stage
    now = time.monotonic()
    flashing = state.flash and now - state.flash[0] < 0.9
    base = C_DIM
    packet = C_CYAN
    mode = "idle"

    if flashing and state.flash[1] == "fail":
        base, packet, mode = (130, 50, 50), C_RED, "fail"
    elif flashing and state.flash[1] == "ok":
        base, packet, mode = C_GREEN, C_GREEN, "ok"
    elif stage == 1:
        packet, mode = C_CYAN, "fwd"
    elif stage == 2:
        packet, mode = C_VIOLET, "fwd"
    elif stage == 3:
        packet, mode = C_AMBER, "bounce"

    chars = ["─"] * length
    styles = [fg(base)] * length
    if mode == "ok":
        chars = ["━"] * length
    elif mode == "fail":
        chars = ["╌"] * length

    if mode in ("fwd", "bounce"):
        speed = 14 if stage == 2 else 11
        count = max(2, length // 14)
        for k in range(count):
            raw = (t * speed + k * length / count) % (
                length * (2 if mode == "bounce" else 1)
            )
            pos = int(raw)
            if mode == "bounce" and pos >= length:
                pos = 2 * length - 1 - pos
                trail = 1
            else:
                trail = -1
            for d, (ch, k2) in enumerate((("◆", 1.0), ("•", 0.65), ("·", 0.35))):
                p = pos + trail * d
                if 0 <= p < length:
                    chars[p] = ch
                    styles[p] = fg(lerp(base, packet, k2), bold=(d == 0))

    right_col = {"ok": C_GREEN, "fail": C_RED}.get(
        mode, C_CYAN if stage >= 1 else C_MUTED
    )
    out = Text(no_wrap=True)
    out.append("YOU ", fg(C_MUTED))
    out.append("●", fg(C_CYAN, bold=True))
    for ch, st in zip(chars, styles):
        out.append(ch, st)
    out.append("◉", fg(right_col, bold=True))
    out.append(" NET", fg(C_MUTED))
    return out


SHORT_NAMES = ["RESET", "CONNECT", "SHAKE", "VERIFY"][:N_STAGES]


def stage_cell(state, i, t, short=False):
    s = state.stage_state[i]
    name = SHORT_NAMES[i] if short else STAGES[i][0]
    spin = SPIN[int(t * 12) % len(SPIN)]
    if s == "wait":
        icon, col, sub = "○", C_DIM, "—"
    elif s == "active":
        icon, col = spin, C_CYAN
        sub = f"{time.monotonic() - state.stage_started:.1f}s"
    elif s == "ok":
        icon, col = "✔", C_GREEN
        sub = state.stage_detail[i] or f"{state.stage_time[i]:.2f}s"
    else:
        icon, col = "✘", C_RED
        sub = f"{state.stage_time[i]:.2f}s"
    cell = Text(justify="center", no_wrap=True)
    cell.append(f"{icon} {name}", fg(col, bold=True))
    cell.append("\n")
    cell.append(sub, fg(C_MUTED))
    return cell


def render_stages(state, t, short=False):
    grid = Table.grid(expand=True)
    for i in range(2 * N_STAGES - 1):
        if i % 2 == 0:
            grid.add_column(justify="center", ratio=1, no_wrap=True)
        else:
            grid.add_column(justify="center", width=2 if short else 4, no_wrap=True)
    cells = []
    for i in range(N_STAGES):
        cells.append(stage_cell(state, i, t, short))
        if i < N_STAGES - 1:
            done = state.stage_state[i] == "ok"
            link = "╼" if short else "─╼"
            cells.append(
                Text(
                    link if done else ("╌" if short else "╌╌"),
                    style=fg(C_GREEN if done else C_DIM),
                    justify="center",
                )
            )
    grid.add_row(*cells)
    return grid


def render_target(state, t, w, compact, border):
    inner = int(w * 0.6) - 8
    tunnel_len = max(16, inner - 14)

    head = Text(no_wrap=True)
    if state.location:
        head.append("◆ PROBING  ", fg(C_CYAN, bold=True))
        head.append(
            f"candidate {min(state.completed + 1, state.total)}/{state.total}",
            fg(C_MUTED),
        )
    else:
        head.append("◆ STANDBY", fg(C_MUTED, bold=True))

    name = Text(no_wrap=True, overflow="ellipsis")
    name.append(
        state.location or "waiting for the next round…",
        fg(C_TEXT if state.location else C_MUTED, bold=True),
    )

    dots = "." * (int(t * 2.5) % 4)
    if (
        state.stage_state[state.active_stage if state.active_stage >= 0 else 0]
        == "fail"
        and state.fail_reason
    ):
        status = Text(no_wrap=True, overflow="ellipsis")
        status.append("✘ ", fg(C_RED, bold=True))
        status.append(state.fail_reason, fg(C_RED))
    else:
        status = Text(no_wrap=True, overflow="ellipsis")
        status.append(f"{state.message}{dots}", fg(C_MUTED))

    gap = Text("")
    body = [head, name]
    if not compact:
        body.append(gap)
    body.append(render_tunnel(state, t, tunnel_len))
    if not compact:
        body.append(gap)
    body.append(render_stages(state, t, short=w < 100))
    if not compact:
        body.append(gap)
    body.append(status)
    return panel(Group(*body), "ACTIVE PROBE", border, padding=(0, 2))


# ---------- stats ----------


def metric(value, label, color):
    cell = Text(justify="center", no_wrap=True)
    cell.append(str(value), fg(color, bold=True))
    cell.append("\n")
    cell.append(label, fg(C_MUTED))
    return cell


def wave(t, width, energy):
    """Flowing equaliser-style wave: calm while paused, lively while scanning."""
    blocks = "▁▂▃▄▅▆▇█"
    out = Text(no_wrap=True)
    for x in range(width):
        amp = (0.55 + 0.45 * math.sin(x * 0.07 + t * 1.3)) * energy
        v = 0.5 + 0.5 * math.sin(x * 0.28 - t * 5) * amp
        out.append(
            blocks[min(7, int(max(0.0, min(1.0, v)) * 8))],
            fg(palette(LOGO_STOPS, x / max(1, width) - t * 0.1)),
        )
    return out


def render_stats(state, t, border, w=120, compact=False):
    elapsed = time.monotonic() - state.started
    grid = Table.grid(expand=True, padding=(0, 1))
    for _ in range(3):
        grid.add_column(justify="center", ratio=1)
    grid.add_row(
        metric(state.tested, "TESTED", C_CYAN),
        metric(state.failed, "FAILED", C_RED),
        metric(state.round_no, "ROUND", C_AMBER),
    )
    grid.add_row(Text(""), Text(""), Text(""))
    grid.add_row(
        metric(fmt_clock(elapsed), "RUNTIME", C_VIOLET),
        metric(state.known, "KNOWN", C_BLUE),
        metric(state.benched, "RESTING", C_PINK),
    )
    content = grid
    if not compact:
        energy = 0.2 if state.phase in ("pause", "init") else 1.0
        content = Group(grid, Text(""), wave(t, max(10, int(w * 0.4) - 6), energy))
    return panel(
        content, "STATISTICS", border, subtitle="learned from history", padding=(0, 1)
    )


# ---------- progress ----------


def render_progress(state, t, w):
    width = max(10, w - 14)
    if state.phase == "pause":
        ratio = state.pause_left / max(1, state.pause_total)
        label = f"NEXT ROUND IN {state.pause_left}s"
        c1, c2, border = C_AMBER, C_PINK, hx(C_AMBER)
    else:
        ratio = state.completed / state.total if state.total else 0
        label = f"ROUND {max(state.round_no, 1)}  ·  {state.completed}/{state.total} SERVERS"
        c1, c2, border = C_CYAN, C_VIOLET, hx(C_BLUE)
    head = Text(no_wrap=True)
    head.append(label, fg(C_TEXT, bold=True))
    bar = smooth_bar(ratio, width, t, c1, c2)
    bar.append(f" {ratio:>4.0%}", fg(C_TEXT, bold=True))
    return panel(Group(head, bar), "PROGRESS", border, padding=(0, 1))


# ---------- log + leaderboard ----------


def render_log(state, rows, border):
    table = Table(
        box=box.SIMPLE_HEAD,
        expand=True,
        show_edge=False,
        pad_edge=False,
        header_style=fg(C_CYAN, bold=True),
        padding=(0, 1),
    )
    table.add_column("#", width=4, justify="right", no_wrap=True)
    table.add_column("SERVER", ratio=3, no_wrap=True, overflow="ellipsis")
    table.add_column("RESULT", width=8, no_wrap=True)
    table.add_column("TIME", width=6, justify="right", no_wrap=True)
    table.add_column("PING", width=7, justify="right", no_wrap=True)
    table.add_column("DETAIL", ratio=3, no_wrap=True, overflow="ellipsis")

    entries = list(reversed(state.log_snapshot()))[:rows]
    now = time.monotonic()
    if not entries:
        table.add_row(
            "-",
            Text("waiting for the first result…", style=fg(C_MUTED)),
            "",
            "",
            "",
            "",
        )
    for idx, e in enumerate(entries):
        fresh = now - e["ts"] < 1.2
        dim = idx >= 4
        base = fg(C_TEXT, bold=fresh, dim=dim)
        if e["ok"]:
            res = Text("✔ LIVE", fg(C_GREEN, bold=True))
            detail = Text(e["ip"] or "ip unavailable", fg(C_GREEN, dim=dim))
        else:
            res = Text("✘ FAIL", fg(C_RED, bold=fresh, dim=dim))
            detail = Text(e["reason"], fg(C_MUTED, dim=dim))
        ping = f"{e['latency']:.0f}ms" if e["latency"] else "-"
        table.add_row(
            Text(str(e["n"]), fg(C_MUTED, dim=dim)),
            Text(e["location"], base),
            res,
            Text(f"{e['seconds']:.1f}s", fg(C_MUTED, dim=dim)),
            Text(ping, fg(C_MUTED, dim=dim)),
            detail,
        )
    return panel(table, "LIVE LOG", border, subtitle="newest first", padding=(0, 1))


def render_board(state, rows, border):
    table = Table(
        box=box.SIMPLE_HEAD,
        expand=True,
        show_edge=False,
        pad_edge=False,
        header_style=fg(C_VIOLET, bold=True),
        padding=(0, 1),
    )
    table.add_column("#", width=2, justify="right", no_wrap=True)
    table.add_column("SERVER", ratio=3, no_wrap=True, overflow="ellipsis")
    table.add_column("HIT", width=4, justify="right", no_wrap=True)
    table.add_column("PING", width=6, justify="right", no_wrap=True)
    table.add_column("TREND", width=6, no_wrap=True)

    board = state.board[:rows]
    if not board:
        table.add_row(
            "",
            Text("no history yet - it learns as it runs", style=fg(C_MUTED)),
            "",
            "",
            "",
        )
    for i, st in enumerate(board, 1):
        col = (
            C_MUTED
            if st.benched
            else (C_GREEN if st.rate >= 0.7 else C_AMBER if st.rate >= 0.4 else C_RED)
        )
        trend = Text(no_wrap=True)
        for ok in reversed(st.recent[:6]):
            trend.append("▮", fg(C_GREEN if ok else C_RED, dim=st.benched))
        name = Text(st.location, fg(C_MUTED if st.benched else C_TEXT, dim=st.benched))
        if st.benched:
            name.append(" zz", fg(C_PINK))
        table.add_row(
            Text(str(i), fg(C_MUTED)),
            name,
            Text(f"{st.rate:.0%}", fg(col, bold=True)),
            Text(f"{st.avg_latency:.0f}ms" if st.avg_latency else "-", fg(C_MUTED)),
            trend,
        )
    return panel(
        table,
        "SERVER RANKING",
        border,
        subtitle="zz = resting after failures",
        padding=(0, 1),
    )


def render_footer(state, w=120):
    foot = Text(justify="center", no_wrap=True, overflow="ellipsis")
    foot.append("CTRL+C", fg(C_TEXT, bold=True))
    foot.append(" stop   ·   ", fg(C_MUTED))
    foot.append(APP_NAME, fg(C_MUTED))
    if w >= 100:
        foot.append("   ·   ", fg(C_MUTED))
        foot.append("history saved after every attempt", fg(C_MUTED))
    return foot


def render_dashboard(state, console, t):
    w, h = console.size
    compact = h < 34 or w < 72
    header_h = 3 if compact else 9
    top_h = 10 if compact else 12
    prog_h = 4
    bottom_h = max(6, h - header_h - top_h - prog_h - 1)
    rows = max(1, bottom_h - 4)
    border = border_color(state, t)

    layout = Layout()
    layout.split_column(
        Layout(render_header(state, t, compact, border), name="header", size=header_h),
        Layout(name="top", size=top_h),
        Layout(render_progress(state, t, w), name="progress", size=prog_h),
        Layout(name="bottom", size=bottom_h),
        Layout(render_footer(state, w), name="footer", size=1),
    )
    layout["top"].split_row(
        Layout(render_target(state, t, w, compact, border), ratio=3),
        Layout(render_stats(state, t, border, w, compact), ratio=2),
    )
    if w >= 100:
        layout["bottom"].split_row(
            Layout(render_log(state, rows, hx(C_BLUE)), ratio=3),
            Layout(render_board(state, rows, hx(C_VIOLET)), ratio=2),
        )
    else:
        layout["bottom"].update(render_log(state, rows, hx(C_BLUE)))
    return layout


# ---------- success screen ----------


def hash01(x, y, k):
    """Cheap deterministic pseudo-random number in [0, 1] for a grid cell."""
    n = (x * 73856093) ^ (y * 19349663) ^ (k * 83492791)
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return (n & 0xFFFF) / 65535.0


def starfield(width, rows, t, y0=0, density=0.04):
    """A block of softly twinkling stars (static when t is constant)."""
    if rows <= 0 or width <= 0:
        return Text("")
    out = Text(no_wrap=True)
    for y in range(rows):
        run = 0
        for x in range(width):
            if hash01(x, y + y0, 1) < density:
                phase = hash01(x, y + y0, 2) * 6.283
                level = 0.5 + 0.5 * math.sin(t * 3 + phase)
                glyph = "·" if level < 0.33 else "✧" if level < 0.66 else "✦"
                col = lerp(C_DIM, palette(OK_STOPS, hash01(x, y + y0, 3)), level)
                if run:
                    out.append(" " * run)
                    run = 0
                out.append(glyph, fg(col, bold=level > 0.66))
            else:
                run += 1
        if run:
            out.append(" " * run)
        if y < rows - 1:
            out.append("\n")
    return out


def render_success(state, console, t, final=False):
    w, h = console.size
    r = state.result or {}
    art = ART_CONNECTED if w >= 86 else ART_ONLINE
    art_text = gradient_text(art, t, stops=OK_STOPS, shadow=True, speed=0.3)

    items = [("SERVER", r.get("location", "-"))]
    if r.get("passed") is not None:
        changed = r.get("ip_changed")
        items += [
            ("PUBLIC IP", r.get("ip") or "unavailable"),
            (
                "IP CHANGED",
                (
                    Text("yes - traffic is tunnelled", fg(C_GREEN, bold=True))
                    if changed
                    else Text("could not compare", fg(C_MUTED))
                ),
            ),
            ("LATENCY", f"{r['latency']:.0f} ms" if r.get("latency") else "-"),
            ("HEALTH CHECK", f"{r.get('passed', 0)}/{r.get('total', 0)} probes passed"),
        ]
    items += [
        ("CONNECT TIME", f"{r.get('seconds', 0):.2f} s"),
        ("SERVERS TRIED", f"{state.tested}  ({state.failed} failed)"),
        (
            "TOTAL RUNTIME",
            fmt_clock((state.done_at or time.monotonic()) - state.started),
        ),
    ]
    rows = Table.grid(padding=(0, 3))
    rows.add_column(justify="right", style=fg(C_MUTED), no_wrap=True)
    rows.add_column(style=fg(C_TEXT, bold=True), no_wrap=True)
    for label, value in items:
        rows.add_row(label, value)

    live_dot = Text(justify="center")
    live_dot.append(
        "● ", fg(lerp(C_GREEN, WHITE, pulse(t, 5)) if not final else C_GREEN, bold=True)
    )
    live_dot.append("SECURE TUNNEL ESTABLISHED", fg(C_GREEN, bold=True))

    note_text = (
        "The VPN stays connected. Press Ctrl+C to close this window. "
        "This server will be tried first next time."
    )
    note = Text(note_text, style=fg(C_MUTED), justify="center")

    # The card fills the whole terminal (a bit shorter when printed at the end,
    # so the summary line and your shell prompt still fit below it).
    total_h = max(10, h - 3) if final else h
    inner_w = max(20, w - 6)
    note_lines = -(-len(note_text) // inner_w)
    content_h = len(art) + 1 + 1 + 1 + len(items) + 1 + note_lines
    free = (total_h - 2) - content_h
    top = max(0, free // 2)
    bottom = max(0, free - top)

    pieces = []
    if top:
        pieces.append(starfield(inner_w, top, t, y0=0))
    pieces += [
        Align.center(art_text),
        Text(""),
        live_dot,
        Text(""),
        Align.center(rows),
        Text(""),
        note,
    ]
    if bottom:
        pieces.append(starfield(inner_w, bottom, t, y0=top + 50))

    border = hx(C_GREEN if final else lerp(C_GREEN, C_CYAN, pulse(t, 2)))
    return Panel(
        Group(*pieces),
        title=Text(" CONNECTION SUCCESSFUL ", style=fg(C_GREEN, bold=True)),
        border_style=border,
        box=box.DOUBLE,
        padding=(0, 2),
        height=total_h,
    )


def render(state, console):
    t = time.monotonic() - state.started
    if state.phase == "connected":
        return render_success(state, console, t)
    return render_dashboard(state, console, t)


# ============================================================
#                    MAIN
# ============================================================


def parse_args():
    argv = sys.argv[1:]
    if all(a in ("--demo", "--reset-history") for a in argv):
        # Fast path: no argparse import for the flags we know.
        from types import SimpleNamespace

        return SimpleNamespace(demo="--demo" in argv, reset_history="--reset-history" in argv)
    import argparse  # lazy: only for --help, abbreviations, errors

    ap = argparse.ArgumentParser(
        description="Expresso - find and hold a working ExpressVPN server"
    )
    ap.add_argument(
        "--demo", action="store_true", help="preview the UI with a fake VPN"
    )
    ap.add_argument(
        "--reset-history", action="store_true", help="forget learned server history"
    )
    return ap.parse_args()


def main():
    args = parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    console = Console()
    try:
        console.set_window_title(APP_NAME)
    except Exception:  # noqa: BLE001
        pass

    history_path = (
        HISTORY_FILE.with_name("history_demo.db") if args.demo else HISTORY_FILE
    )
    if args.reset_history:
        History(history_path).reset()
        console.print("[bold green]✔ Server history cleared.[/]")
        return

    state = State()
    stop = threading.Event()
    factory = DemoBackend if args.demo else ExpressBackend

    def scan():
        # The history is opened here, not before the UI starts, so the first frame never waits for the disk.
        try:
            history = History(history_path)
            if args.demo:
                # Same story on every demo run: fresh history, fixed server order.
                history.reset()
                random.seed(7)
        except Exception as exc:  # noqa: BLE001
            state.error = str(exc) or exc.__class__.__name__
            state.phase = "error"
            return
        run_scanner(state, factory, history, stop)

    worker = threading.Thread(target=scan, daemon=True)

    interrupted = False
    try:
        with Live(
            get_renderable=lambda: render(state, console),
            console=console,
            refresh_per_second=FPS,
            screen=True,
            transient=True,
        ):
            worker.start()
            while worker.is_alive():
                time.sleep(0.05)
            if state.phase == "connected":
                # Connected: keep the animated success screen open until Ctrl+C.
                while True:
                    time.sleep(0.25)
    except KeyboardInterrupt:
        # Ctrl+C after connecting only closes this window - the VPN stays connected.
        if state.phase != "connected":
            interrupted = True
            stop.set()
            worker.join(timeout=6)

    # ---- after the live screen is gone: leave a clean final printout ----
    if state.phase == "connected" and not interrupted:
        console.print(render_success(state, console, 0.0, final=True))
    elif state.phase == "error":
        console.print(
            panel(
                Text(state.error or "Unknown error", style=fg(C_RED)),
                "APPLICATION ERROR",
                hx(C_RED),
                padding=(1, 2),
            )
        )
    else:
        console.print(
            Panel(
                Text(
                    "Scanner stopped by user.",
                    style=fg(C_AMBER, bold=True),
                    justify="center",
                ),
                box=box.ROUNDED,
                border_style=hx(C_AMBER),
            )
        )
        # Not connected through us -> make sure we leave no half-open tunnel.
        try:
            backend = factory()
            backend.disconnect()
        except Exception:  # noqa: BLE001
            pass

    summary = Text(justify="center")
    summary.append(
        f"TESTED {state.tested}   ·   FAILED {state.failed}   ·   "
        f"RUNTIME {fmt_clock(time.monotonic() - state.started)}",
        fg(C_MUTED),
    )
    console.print(summary)


if __name__ == "__main__":
    main()
