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

from config import (
    APP_CANDIDATES,
    CLOSE_AFTER,
    CTL_CANDIDATES,
    FALLBACK_AFTER,
    POLL,
    READY_TIMEOUT,
)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PASSTHROUGH_FLAGS = ("--demo", "--reset-history", "-h", "--help")


def fail(message):
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
    print("Starting ExpressVPN...")
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
    since = None
    while True:
        time.sleep(POLL)
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
    expresso.main()


def main():
    if any(arg in PASSTHROUGH_FLAGS for arg in sys.argv[1:]):
        run_expresso()
        return

    ctl = find_ctl()
    if not ctl:
        fail("expressvpnctl not found.")

    # Start the CLI check and the heavy imports at the same time.
    check = spawn_state_check(ctl)
    threading.Thread(target=preload, daemon=True).start()
    state = parse_state(check)

    if state and state.lower() == "connected":
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
        sys.stdout.flush()
        os._exit(0)  # do not wait for the background import

    if not state:
        state = start_and_wait(ctl)

    if state.lower() == "disconnected":
        os.environ["EXPRESSO_ASSUME_CLEAN"] = (
            "1"  # skip Expresso's own initial disconnect
        )

    threading.Thread(target=watch, args=(ctl,), daemon=True).start()
    run_expresso()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
