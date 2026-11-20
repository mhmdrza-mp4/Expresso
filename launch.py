#!/usr/bin/env python3
"""
Expresso launcher - one process, fastest possible start.

  * VPN connected    -> disconnect and exit (Expresso is never imported)
  * VPN disconnected -> open ExpressVPN if needed, wait for its CLI, run Expresso,
                        and close the window CLOSE_AFTER seconds after the VPN is connected

Usage (shortcut target):  py "C:\\path\\to\\launch.py"
Extra arguments are passed to Expresso (e.g. --demo).
"""

import os
import subprocess
import sys
import threading
import time

T_START = time.time() * 1000  # ms, used by --trace

from config import (
    APP_CANDIDATES,
    CLOSE_AFTER,
    CTL_CANDIDATES,
    DISCONNECT_HOLD,
    DISCONNECT_VISUAL,
    FALLBACK_AFTER,
    POLL,
    READY_TIMEOUT,
)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PASSTHROUGH_FLAGS = ("--demo", "--reset-history", "-h", "--help")

# Draw a lightweight logo the moment Python starts, while the heavy imports load.
# Only in Windows Terminal (it understands ANSI without any setup). Set to False to disable.
SPLASH = True

TRACE = "--trace" in sys.argv  # prints where the start-up time goes
if TRACE:
    sys.argv.remove("--trace")
MARKS = []  # (label, ms)
FIRST_FRAME = threading.Event()
SPLASH_LINES = 0  # how many lines the splash occupies (0 = not drawn)


def mark(label):
    MARKS.append((label, time.time() * 1000))


def trace_report():
    if not TRACE:
        return
    try:
        t0 = float(os.environ["EXPRESSO_T0"])
    except (KeyError, ValueError):
        t0 = T_START
    print("\n--- trace (ms since command start) ---")
    prev = t0
    for label, ms in MARKS:
        print(f"{label:<20} {ms - t0:7.0f}   (+{ms - prev:.0f})")
        prev = ms
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Instant splash: plain ANSI, no imports, drawn before anything heavy is loaded.
# ---------------------------------------------------------------------------
_LOGO_BIG = [
    "███████╗██╗  ██╗██████╗ ██████╗ ███████╗███████╗███████╗ ██████╗ ",
    "██╔════╝╚██╗██╔╝██╔══██╗██╔══██╗██╔════╝██╔════╝██╔════╝██╔═══██╗",
    "█████╗   ╚███╔╝ ██████╔╝██████╔╝█████╗  ███████╗███████╗██║   ██║",
    "██╔══╝   ██╔██╗ ██╔═══╝ ██╔══██╗██╔══╝  ╚════██║╚════██║██║   ██║",
    "███████╗██╔╝ ██╗██║     ██║  ██║███████╗███████║███████║╚██████╔╝",
    "╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝ ╚═════╝ ",
]
_LOGO_SMALL = [
    "╔═╗═╗ ╦╔═╗╦═╗╔═╗╔═╗╔═╗╔═╗",
    "║╣ ╔╩╦╝╠═╝╠╦╝║╣ ╚═╗╚═╗║ ║",
    "╚═╝╩ ╚═╩  ╩╚═╚═╝╚═╝╚═╝╚═╝",
]
_STOPS = [(245, 222, 179), (251, 191, 36), (217, 119, 6), (146, 84, 40), (217, 119, 6), (251, 191, 36)]
_INK = (24, 20, 18)
_GREY = (96, 88, 80)


def _gradient(pos):
    pos -= int(pos)
    x = pos * len(_STOPS)
    i = int(x)
    a, b, k = _STOPS[i % len(_STOPS)], _STOPS[(i + 1) % len(_STOPS)], x - i
    return tuple(a[n] + (b[n] - a[n]) * k for n in range(3))


def _paint_logo(art, fade=0.0):
    width = len(art[0])
    out = []
    for y, row in enumerate(art):
        parts, prev = ["  "], None
        for x, ch in enumerate(row):
            if ch == " ":
                parts.append(" ")
                continue
            c = _gradient((x + y * 1.6) / (width + 10))
            if ch != "█":  # shadow strokes a shade darker
                c = tuple(c[n] + (_INK[n] - c[n]) * 0.55 for n in range(3))
            if fade:
                c = tuple(c[n] + (_GREY[n] - c[n]) * fade for n in range(3))
            c = tuple(int(v) for v in c)
            if c != prev:
                parts.append("\x1b[38;2;%d;%d;%dm" % c)
                prev = c
            parts.append(ch)
        out.append("".join(parts) + "\x1b[0m")
    return out


def _status_line(text):
    return "  \x1b[38;2;128;120;112m" + text + "\x1b[0m"


def draw_splash():
    """Paint the logo and a status line at once. Returns False when it is not supported."""
    global SPLASH_LINES
    if not SPLASH or not sys.stdout.isatty():
        return False
    if os.name == "nt" and not os.environ.get("WT_SESSION"):
        return False  # classic console: no ANSI until rich enables it later
    try:
        cols, rows = os.get_terminal_size()
    except OSError:
        return False
    if cols >= 70 and rows >= 14:
        art = _LOGO_BIG
    elif cols >= 30 and rows >= 8:
        art = _LOGO_SMALL
    else:
        return False
    lines = _paint_logo(art) + ["", _status_line("checking ExpressVPN ...")]
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()
    SPLASH_LINES = len(lines)
    return True


def set_status(text):
    """Replace the splash status line (or just print when there is no splash)."""
    if SPLASH_LINES:
        sys.stdout.write("\x1b[1A\x1b[2K" + _status_line(text) + "\n")
        sys.stdout.flush()
    else:
        print(text)


def clear_splash():
    global SPLASH_LINES
    if SPLASH_LINES:
        sys.stdout.write("\x1b[%dA\x1b[J" % SPLASH_LINES)
        sys.stdout.flush()
        SPLASH_LINES = 0


def _mix(a, b, k):
    k = max(0.0, min(1.0, k))
    return tuple(int(a[n] + (b[n] - a[n]) * k) for n in range(3))


def _fg(c, text, bold=False):
    return "\x1b[%s38;2;%d;%d;%dm%s\x1b[0m" % (("1;" if bold else "",) + tuple(int(v) for v in c) + (text,))


def _enable_vt():
    """Make an old Windows console understand ANSI colours. True when it is ready."""
    if os.name != "nt" or os.environ.get("WT_SESSION"):
        return True
    try:
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:  # noqa: BLE001
        return False


_GLYPHS = {
    "D": ["██████╗ ", "██╔══██╗", "██║  ██║", "██║  ██║", "██████╔╝", "╚═════╝ "],
    "I": ["██╗", "██║", "██║", "██║", "██║", "╚═╝"],
    "S": ["███████╗", "██╔════╝", "███████╗", "╚════██║", "███████║", "╚══════╝"],
    "C": [" ██████╗", "██╔════╝", "██║     ", "██║     ", "╚██████╗", " ╚═════╝"],
    "O": [" ██████╗ ", "██╔═══██╗", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "N": ["███╗   ██╗", "████╗  ██║", "██╔██╗ ██║", "██║╚██╗██║", "██║ ╚████║", "╚═╝  ╚═══╝"],
    "E": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"],
    "T": ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "],
}  # fmt: skip


def _word_art(word):
    rows = [""] * 6
    for ch in word:
        glyph = _GLYPHS[ch]
        width = max(len(r) for r in glyph)
        rows = [rows[i] + glyph[i].ljust(width) for i in range(6)]
    return rows


def _hash01(a, b):
    n = (a * 73856093) ^ (b * 19349663)
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return (n & 0xFFFF) / 65535.0


_ROSE, _FUCHSIA = (244, 114, 182), (217, 70, 239)
_LAV, _LAV_DIM = (130, 124, 150), (62, 56, 84)


def _paint_art(row, y, fade, t):
    """One line of the big word: Expresso amber gradient that cools down to lavender-grey."""
    width = len(row)
    parts, prev = [], None
    for x, ch in enumerate(row):
        if ch == " ":
            parts.append(" ")
            continue
        c = _gradient((x + y * 1.6) / (width + 10) + t * 0.12)
        if ch != "█":
            c = tuple(c[n] + (_INK[n] - c[n]) * 0.55 for n in range(3))
        c = _mix(c, _LAV_DIM if ch != "█" else _LAV, fade)
        if c != prev:
            parts.append("\x1b[38;2;%d;%d;%dm" % c)
            prev = c
        parts.append(ch)
    return "".join(parts) + "\x1b[0m"


def _disconnect_frame(rows, cols, p, finished, tick, t):
    inner = cols - 4
    body = rows - 2
    fade = min(1.0, p * 1.25) if not finished else 1.0
    spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    # ---- content block: (visible text, styled text) per line
    lines = []
    if cols >= 106 and rows >= 20:
        for y, row in enumerate(_word_art("DISCONNECTED")):
            lines.append((row, _paint_art(row, y, fade, t)))
    else:
        txt = "D I S C O N N E C T E D"
        lines.append((txt, _fg(_mix((251, 191, 36), _LAV, fade), txt, True)))
    lines.append(("", ""))

    length = max(12, min(46, inner - 24))
    gap = int(length * p)
    left = (length - gap) // 2
    right = length - gap - left
    mid = _mix((74, 222, 128), _LAV, p * 1.6)
    end_col = (74, 222, 128) if p < 1 else _LAV
    gap_chars = [" "] * gap
    if 0 < gap < length and not finished:
        gap_chars[0] = "╌" if tick % 2 else " "
        if gap >= 2:
            gap_chars[-1] = "╌" if (tick // 2) % 2 else " "
    tunnel = (
        _fg(_LAV, "YOU ") + _fg(end_col, "●", True) + _fg(mid, "━" * left)
        + _fg((251, 191, 36), "".join(gap_chars)) + _fg(mid, "━" * right)
        + _fg(end_col, "◉", True) + _fg(_LAV, " NET")
    )  # fmt: skip
    lines.append((" " * (length + 10), tunnel))
    lines.append(("", ""))
    if finished:
        a, b = "✔ DISCONNECTED", "  -  you are back on your normal connection"
        if len(a + b) > inner:
            b = ""
        lines.append((a + b, _fg(_ROSE, a, True) + _fg(_LAV, b)))
        hint = "run the launcher again to connect"
        hint = hint[:inner]
        lines.append(("", ""))
        lines.append((hint, _fg(_LAV_DIM, hint)))
    else:
        s = spin[tick % len(spin)] + " closing the tunnel ..."
        lines.append((s, _fg(_LAV, s)))

    top_pad = max(0, (body - len(lines)) // 2)
    content = {top_pad + i: line for i, line in enumerate(lines)}

    # ---- falling embers on the rows the content does not use
    stars = {}
    for k in range(40):
        x = int(_hash01(k, 1) * inner)
        y0 = _hash01(k, 2) * body
        speed = 1.2 + _hash01(k, 3) * 3.0
        y = int((y0 + t * speed) % body)
        if y in content:
            continue
        warm = _mix((251, 191, 36), _LAV_DIM, 0.35 + 0.65 * fade)
        glyph = "•" if speed > 3 else "·"
        stars.setdefault(y, {})[x] = (glyph, _mix(warm, _LAV_DIM, 0.4 if speed < 2 else 0.0))

    border = _mix(_ROSE, _FUCHSIA, 0.5 + 0.5 * __import__("math").sin(t * 2)) if not finished else _LAV_DIM
    title = " DISCONNECTED " if finished else " DISCONNECTING "
    lt = (cols - 2 - len(title)) // 2
    out = [
        _fg(border, "╔" + "═" * lt) + _fg(_LAV if finished else _ROSE, title, True)
        + _fg(border, "═" * (cols - 2 - lt - len(title)) + "╗")
    ]  # fmt: skip
    side = _fg(border, "║")
    for r in range(body):
        if r in content:
            plain, styled = content[r]
            lpad = max(0, (inner - len(plain)) // 2)
            rpad = max(0, inner - lpad - len(plain))
            out.append(side + " " + " " * lpad + styled + " " * rpad + " " + side)
        else:
            cells, row_stars = [], stars.get(r, {})
            run = 0
            for x in range(inner):
                if x in row_stars:
                    if run:
                        cells.append(" " * run)
                        run = 0
                    cells.append(_fg(row_stars[x][1], row_stars[x][0]))
                else:
                    run += 1
            if run:
                cells.append(" " * run)
            out.append(side + " " + "".join(cells) + " " + side)
    out.append(_fg(border, "╚" + "═" * (cols - 2) + "╝"))
    return out


def disconnect_visual(ctl):
    """Full-screen animation while `disconnect` runs. False = not supported here."""
    if not DISCONNECT_VISUAL or not sys.stdout.isatty():
        return False
    if not _enable_vt():
        return False
    try:
        cols, rows = os.get_terminal_size()
    except OSError:
        return False
    if cols < 30 or rows < 10:
        return False

    out = sys.stdout
    proc = subprocess.Popen(
        [ctl, "disconnect"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=NO_WINDOW,
    )
    out.write("\x1b[?1049h\x1b[?25l")  # alternate screen, hide cursor
    began = time.monotonic()
    held_at = None
    tick = 0
    try:
        while True:
            elapsed = time.monotonic() - began
            done = proc.poll() is not None or elapsed > 15
            p = min(1.0, elapsed / 1.2)
            if not done:
                p = min(p, 0.9)
            finished = done and p >= 1.0
            try:
                cols, rows = os.get_terminal_size()
            except OSError:
                pass
            frame = _disconnect_frame(rows - 1, max(cols, 30), p, finished, tick, elapsed)
            buf = []
            for i, line in enumerate(frame):
                buf.append("\x1b[%d;1H%s\x1b[K" % (i + 1, line))
            buf.append("\x1b[%d;1H\x1b[J" % (len(frame) + 1))
            out.write("".join(buf))
            out.flush()
            tick += 1
            if finished:
                held_at = held_at or time.monotonic()
                if time.monotonic() - held_at >= DISCONNECT_HOLD:
                    break
            time.sleep(0.05)
    finally:
        out.write("\x1b[?1049l\x1b[?25h")
        out.flush()
    return True


def fail(message):
    clear_splash()
    print(message)
    try:
        input("Enter to exit")
    except EOFError:
        pass
    sys.exit(1)


def find_ctl():
    for path in CTL_CANDIDATES:
        if os.path.isfile(path):
            return path
    import shutil

    return shutil.which("expressvpnctl")


def parse_state(proc):
    """Result of a finished `get connectionstate` process, or None."""
    try:
        out, _ = proc.communicate(timeout=8)
    except (subprocess.TimeoutExpired, OSError):
        proc.kill()
        return None
    out = (out or "").strip()
    return out if proc.returncode == 0 and out else None


def spawn_state_check(ctl):
    return subprocess.Popen(
        [ctl, "get", "connectionstate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW,
    )


def get_state(ctl):
    try:
        return parse_state(spawn_state_check(ctl))
    except OSError:
        return None


def start_via_start_menu():
    script = (
        "$a = Get-StartApps | Where-Object { $_.Name -like '*ExpressVPN*' } | Select-Object -First 1; "
        "if ($a) { Start-Process ('shell:AppsFolder\\' + $a.AppID) } else { exit 2 }"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        creationflags=NO_WINDOW,
    )
    if result.returncode != 0:
        fail("ExpressVPN app not found.")


def start_app(app_path):
    os.startfile(app_path)  # detached from this console (Windows only)


def start_and_wait(ctl):
    """Open ExpressVPN and wait until its CLI answers. Returns the first state seen."""
    set_status("starting ExpressVPN ...")
    used_fallback = False
    app = next((p for p in APP_CANDIDATES if os.path.isfile(p)), None)
    try:
        if app:
            start_app(app)
        else:
            start_via_start_menu()
            used_fallback = True
    except OSError:
        start_via_start_menu()
        used_fallback = True

    started = time.monotonic()
    while True:
        state = get_state(ctl)
        if state:
            return state
        elapsed = time.monotonic() - started
        if elapsed > READY_TIMEOUT:
            fail(f"ExpressVPN not ready after {READY_TIMEOUT} s.")
        if not used_fallback and elapsed > FALLBACK_AFTER:
            start_via_start_menu()
            used_fallback = True
        time.sleep(POLL)


def preload():
    """Import Expresso (and rich) in the background while the CLI check runs."""
    try:
        import expresso  # noqa: F401
    except Exception:  # noqa: BLE001 - the real import in main() reports the error
        pass


def quit_now():
    """Leave immediately. The VPN stays connected; the console window closes with the process."""
    try:
        sys.stdout.write("\x1b[?1049l\x1b[?25h")  # leave alt screen, show cursor
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass
    os._exit(0)


def watch(ctl):
    """Close this window CLOSE_AFTER seconds after the VPN is continuously connected."""
    FIRST_FRAME.wait(timeout=3)  # no extra CLI processes while the first frame is being built
    since = None
    while True:
        time.sleep(POLL)
        # A server can be connected while Expresso is still testing it (quality check). The
        # countdown only starts once Expresso has accepted it, otherwise the window could close
        # before the check finishes - and before the notification.
        accepted = getattr(sys.modules.get("expresso"), "ACCEPTED", None)
        if accepted is not None and not accepted.is_set():
            since = None
            continue
        state = get_state(ctl)
        if state and state.lower() == "connected":
            if since is None:
                since = time.monotonic()
            if time.monotonic() - since >= CLOSE_AFTER:
                quit_now()
        else:
            since = None


def run_expresso():
    try:
        import expresso
    except ImportError as exc:
        fail(f"{exc}\nInstall the requirements first:  pip install rich")
    mark("expresso_imported")

    original_render = expresso.render

    def render_hook(state, console):
        if not FIRST_FRAME.is_set():
            mark("first_frame")
            FIRST_FRAME.set()
        return original_render(state, console)

    expresso.render = render_hook
    clear_splash()
    expresso.main()


def main():
    if any(arg in PASSTHROUGH_FLAGS for arg in sys.argv[1:]):
        run_expresso()
        return

    mark("launcher_started")
    draw_splash()
    mark("splash_drawn")

    # The heavy imports are the longest task: start them first, then ask the CLI in parallel.
    threading.Thread(target=preload, daemon=True).start()

    ctl = find_ctl()
    if not ctl:
        fail("expressvpnctl not found.")
    os.environ["EXPRESSO_CTL"] = ctl  # lets expresso.py skip its own CLI search

    check = spawn_state_check(ctl)
    state = parse_state(check)
    mark("cli_answered")

    if state and state.lower() == "connected":
        clear_splash()
        try:
            shown = disconnect_visual(ctl)
        except Exception as exc:  # noqa: BLE001 - the visual is optional, the disconnect is not
            print(f"(disconnect animation failed: {exc!r})")
            shown = False
        if not shown:
            print("Disconnecting...")
            try:
                subprocess.run(
                    [ctl, "disconnect"],
                    capture_output=True,
                    timeout=15,
                    creationflags=NO_WINDOW,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass
        trace_report()
        sys.stdout.flush()
        os._exit(0)  # do not wait for the background import

    if not state:
        state = start_and_wait(ctl)

    if state.lower() == "disconnected":
        os.environ["EXPRESSO_ASSUME_CLEAN"] = (
            "1"  # skip Expresso's own initial disconnect
        )

    if not TRACE:  # in trace mode the window stays open until Ctrl+C
        threading.Thread(target=watch, args=(ctl,), daemon=True).start()
    run_expresso()
    if TRACE:
        trace_report()
        try:
            input("Enter to exit")
        except EOFError:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
