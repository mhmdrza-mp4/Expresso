"""
Expresso notifications - sound, on-screen popup and taskbar flash when the VPN gets connected.

Everything here is fire-and-forget: it never blocks the UI and never raises.
Imported lazily (only at the moment of connection), so start-up speed is unchanged.

The popup is a tiny separate process (`python notify.py --popup <server>`), so it
survives the launcher closing the window and does not depend on Windows
notification settings (Focus Assist, per-app permissions).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ---------------------------------------------------------------------------
# Sound: a pleasant Windows system sound instead of a raw beep.
# ---------------------------------------------------------------------------
_SOUND_CANDIDATES = (
    "Windows Notify System Generic.wav",
    "Speech On.wav",
    "Windows Ding.wav",
    "tada.wav",
)


def _find_sound(custom):
    if custom and os.path.isfile(custom):
        return custom
    media = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Media")
    for name in _SOUND_CANDIDATES:
        path = os.path.join(media, name)
        if os.path.isfile(path):
            return path
    return None


def _play_sound(custom):
    try:
        import winsound

        path = _find_sound(custom)
        if path:
            winsound.PlaySound(path, winsound.SND_FILENAME)
        else:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Taskbar flash: the console button blinks until you bring the window forward.
# Works with classic cmd (conhost), where GetConsoleWindow() is the real window.
# ---------------------------------------------------------------------------
def _flash_taskbar():
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("hwnd", wintypes.HWND),
                ("dwFlags", wintypes.DWORD),
                ("uCount", wintypes.UINT),
                ("dwTimeout", wintypes.DWORD),
            ]

        FLASHW_TRAY, FLASHW_TIMERNOFG = 0x2, 0xC
        info = FLASHWINFO(
            ctypes.sizeof(FLASHWINFO), hwnd, FLASHW_TRAY | FLASHW_TIMERNOFG, 0, 0
        )
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Popup: animated, rounded card in the bottom-right corner of the work area.
# Slides in, shows a pulsing check, a live countdown bar, then slides out.
# Hover freezes the countdown; a click dismisses it. Never steals keyboard focus.
# ---------------------------------------------------------------------------
def _pretty_location(loc):
    """'germany-frankfurt-1' -> 'Germany · Frankfurt 1'."""
    parts = [p for p in (loc or "").replace("_", "-").split("-") if p]
    if not parts:
        return "Secure tunnel established"
    head = parts[0].upper() if len(parts[0]) <= 3 else parts[0].title()
    rest = " ".join(p.title() for p in parts[1:])
    return f"{head} \u00b7 {rest}" if rest else head


def _popup_main(location, hold_secs=1.6, ui=0.58):
    import math
    import time
    import tkinter as tk

    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp on scaled displays
        except Exception:  # noqa: BLE001
            ctypes.windll.user32.SetProcessDPIAware()
        scale = ctypes.windll.user32.GetDpiForSystem() / 96.0
    except Exception:  # noqa: BLE001
        ctypes = None
        scale = 1.0

    def S(v):
        return int(round(v * scale * ui))

    W, H = 452, 128  # design size (px at 100 % scaling)
    KEY = "#010203"  # colour made transparent -> rounded outer corners

    G_L, G_R = (14, 88, 64), (7, 40, 34)  # card gradient, left -> right
    BORDER_A, BORDER_B = (30, 165, 108), (92, 245, 168)
    SH_RIM, SH_BODY, SH_GLINT = (130, 248, 182), (34, 190, 100), (150, 245, 190)
    GREEN = (74, 222, 128)
    TEXT, SUB, MUTED = (255, 255, 255), (206, 228, 218), (150, 190, 172)

    def lerp(a, b, k):
        k = max(0.0, min(1.0, k))
        return tuple(a[n] + (b[n] - a[n]) * k for n in range(3))

    def hexc(c):
        return "#%02x%02x%02x" % tuple(int(max(0, min(255, v))) for v in c)

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.0)
    root.configure(bg=KEY)
    try:
        root.attributes("-transparentcolor", KEY)
    except tk.TclError:
        pass

    # Place inside the work area (respects the taskbar wherever it is docked).
    right, bottom = root.winfo_screenwidth(), root.winfo_screenheight() - S(48)
    if ctypes is not None:
        try:
            from ctypes import wintypes

            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0):
                right, bottom = rect.right, rect.bottom
        except Exception:  # noqa: BLE001
            pass
    margin = S(14)
    fx, fy = right - S(W) - margin, bottom - S(H) - margin
    travel = S(80)
    root.geometry(f"{S(W)}x{S(H)}+{fx + travel}+{fy}")

    cv = tk.Canvas(root, width=S(W), height=S(H), bg=KEY, highlightthickness=0, bd=0)
    cv.pack()
    root.update_idletasks()

    if ctypes is not None:  # no focus stealing, no taskbar / Alt-Tab entry
        try:
            u32 = ctypes.windll.user32
            u32.GetParent.restype = ctypes.c_void_p
            hwnd = u32.GetParent(root.winfo_id()) or root.winfo_id()
            style = u32.GetWindowLongW(hwnd, -20)
            u32.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x00000080)
        except Exception:  # noqa: BLE001
            pass

    # ---- geometry --------------------------------------------------------
    cx, cy = S(70), S(64)  # shield centre
    X1, Y1, X2, Y2 = S(28), S(22), S(W - 8), S(106)  # card
    R = S(38)
    SH_W, SH_H = S(36), S(52)  # shield half width / half height

    def rounded_points(x1, y1, x2, y2, r, n=14):
        pts = []
        for ccx, ccy, a0 in ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0),
                             (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)):
            for k in range(n + 1):
                a = math.radians(a0 + 90 * k / n)
                pts += [ccx + r * math.cos(a), ccy + r * math.sin(a)]
        return pts + pts[:2]

    border_pts = rounded_points(X1, Y1, X2, Y2, R)

    # ---- static layer: card gradient, text, location pin ------------------
    step = max(1, S(2))
    x = X1
    while x < X2:
        xc = x + step / 2
        if xc < X1 + R:
            d = X1 + R - xc
            inset = R - math.sqrt(max(0.0, R * R - d * d))
        elif xc > X2 - R:
            d = xc - (X2 - R)
            inset = R - math.sqrt(max(0.0, R * R - d * d))
        else:
            inset = 0
        k = (xc - X1) / (X2 - X1)
        col = lerp(G_L, G_R, k ** 0.75)
        col = lerp(col, (24, 128, 90), max(0.0, 1 - abs(xc - cx) / S(130)) * 0.30)
        cv.create_rectangle(x, Y1 + inset, x + step + 1, Y2 - inset,
                            fill=hexc(col), outline="", tags="static")
        x += step

    tx = cx + SH_W + S(24)
    cv.create_text(tx, S(52), text="VPN connected", anchor="w",
                   font=("Segoe UI Semibold", -max(14, S(28))), fill=hexc(TEXT), tags="static")
    px, py = tx + S(8), S(81)
    cv.create_oval(px - S(7), py - S(10), px + S(7), py + S(4), fill=hexc(GREEN), outline="", tags="static")
    cv.create_polygon(px - S(6), py - S(3), px + S(6), py - S(3), px, py + S(10),
                      fill=hexc(GREEN), outline="", tags="static")
    cv.create_oval(px - S(3), py - S(6), px + S(3), py, fill=hexc(G_R), outline="", tags="static")
    cv.create_text(px + S(18), py, text=_pretty_location(location), anchor="w",
                   font=("Segoe UI", -max(10, S(16))), fill=hexc(SUB), tags="static")

    # ---- dynamic layer helpers -------------------------------------------
    def _build_shield():
        right = [(0.0, -1.0), (0.3, -0.94), (0.62, -0.85), (0.95, -0.72), (0.95, -0.15)]
        p0, p1, p2 = (0.95, -0.15), (0.92, 0.55), (0.0, 1.0)
        for k in range(1, 13):
            u = k / 12
            right.append(((1 - u) ** 2 * p0[0] + 2 * u * (1 - u) * p1[0] + u * u * p2[0],
                          (1 - u) ** 2 * p0[1] + 2 * u * (1 - u) * p1[1] + u * u * p2[1]))
        left = [(-x, y) for (x, y) in reversed(right[1:-1])]
        return right + left

    SHIELD = _build_shield()

    def shield_poly(sc):
        return [v for nx, ny in SHIELD for v in (cx + nx * SH_W * sc, cy + ny * SH_H * sc)]

    def ring_arc(a0, a1, n=28):
        a, b, phi = S(56), S(19), math.radians(-14)
        pts = []
        for k in range(n + 1):
            th = a0 + (a1 - a0) * k / n
            ex, ey = a * math.cos(th), b * math.sin(th)
            pts += [cx + ex * math.cos(phi) - ey * math.sin(phi),
                    cy + ex * math.sin(phi) + ey * math.cos(phi)]
        return pts

    def ring_point(th):
        a, b, phi = S(56), S(19), math.radians(-14)
        ex, ey = a * math.cos(th), b * math.sin(th)
        return (cx + ex * math.cos(phi) - ey * math.sin(phi),
                cy + ex * math.sin(phi) + ey * math.cos(phi))

    def sparkle(x, y, r, col):
        q = 0.3 * r
        pts = [x, y - r, x + q, y - q, x + r, y, x + q, y + q,
               x, y + r, x - q, y + q, x - r, y, x - q, y - q]
        cv.create_polygon(pts, fill=hexc(col), outline="", tags="dyn")

    def back_ease(p):
        c1 = 1.70158
        c3 = c1 + 1
        return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2

    IN, OUT = 0.18, 0.14
    t0 = time.perf_counter()
    st = {"phase": "in", "ts": t0, "held": 0.0, "last": t0, "hover": False}

    def draw(t):
        cv.delete("dyn")
        breathe = 0.5 + 0.5 * math.sin(t * 2.2)
        cv.create_line(*border_pts, fill=hexc(lerp(BORDER_A, BORDER_B, breathe)),
                       width=max(1, S(1.6)), joinstyle="round", tags="dyn")

        # Orbit ring: back half behind the shield, front half in front.
        ring_back = lerp(BORDER_A, G_R, 0.45)
        ring_front = lerp(BORDER_A, BORDER_B, 0.35 + 0.65 * breathe)
        lw = max(1, S(2))
        cv.create_line(*ring_arc(math.pi, 2 * math.pi), fill=hexc(ring_back), width=lw, tags="dyn")
        th = t * 4.2
        front = math.sin(th) > 0
        if not front:
            sx, sy = ring_point(th)
            r = S(3.5)
            cv.create_oval(sx - r, sy - r, sx + r, sy + r, fill=hexc(lerp(BORDER_B, G_R, 0.4)), outline="", tags="dyn")

        # Shield with pop-in, rim, body, glint and a self-drawing check mark.
        p = min(1.0, t / 0.22)
        sc = (0.45 + 0.55 * back_ease(p)) * (1 + 0.018 * math.sin(t * 3))
        cv.create_polygon(*shield_poly(sc), joinstyle="round",
                          fill=hexc(SH_RIM), outline=hexc(lerp(SH_RIM, (255, 255, 255), 0.4)),
                          width=max(1, S(1.5)), tags="dyn")
        cv.create_polygon(*shield_poly(sc * 0.84),
                          fill=hexc(SH_BODY), outline="", tags="dyn")
        glint = [(-0.68, -0.42), (-0.62, -0.62), (-0.36, -0.76)]
        cv.create_line(*[v for nx, ny in glint
                         for v in (cx + nx * SH_W * sc * 0.84, cy + ny * SH_H * sc * 0.84)],
                       fill=hexc(SH_GLINT), width=max(2, S(2.5)), capstyle="round",
                       joinstyle="round", smooth=True, tags="dyn")
        cp = max(0.0, min(1.0, (t - 0.08) / 0.20))
        a, b, c = (-0.38, 0.02), (-0.1, 0.3), (0.42, -0.26)
        l1, l2 = math.dist(a, b), math.dist(b, c)
        drawn = cp * (l1 + l2)
        pts = [a]
        if drawn <= l1:
            k = drawn / l1
            pts.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k))
        else:
            k = (drawn - l1) / l2
            pts += [b, (b[0] + (c[0] - b[0]) * k, b[1] + (c[1] - b[1]) * k)]
        if cp > 0:
            cv.create_line(*[v for nx, ny in pts for v in (cx + nx * SH_W * sc * 1.05, cy + ny * SH_W * sc * 1.05)],
                           fill="white", width=max(3, S(6)), capstyle="round", joinstyle="round", tags="dyn")

        cv.create_line(*ring_arc(0, math.pi), fill=hexc(ring_front), width=lw, tags="dyn")
        if front:
            sx, sy = ring_point(th)
            r = S(4)
            cv.create_oval(sx - r, sy - r, sx + r, sy + r, fill="white", outline="", tags="dyn")

        # Twinkling sparkles.
        for (sx, sy, base, ph) in ((cx + S(38), S(16), S(9), 0.0), (cx - S(46), cy + S(40), S(6.5), 2.0),
                                   (cx + S(46), cy + S(30), S(4.5), 4.1)):
            lvl = 0.55 + 0.45 * math.sin(t * 3 + ph)
            sparkle(sx, sy, base * lvl, lerp(BORDER_A, (225, 255, 238), lvl))

        # Close "X" (brightens on hover).
        xc, yc, d = X2 - S(34), S(46), S(6)
        col = TEXT if st["hover"] else MUTED
        for (ax, ay, bx, by) in ((-d, -d, d, d), (-d, d, d, -d)):
            cv.create_line(xc + ax, yc + ay, xc + bx, yc + by, fill=hexc(col),
                           width=max(2, S(2)), capstyle="round", tags="dyn")

    def frame():
        now = time.perf_counter()
        dt, st["last"] = now - st["last"], now
        t = now - t0
        if st["phase"] == "in":
            p = min(1.0, (now - st["ts"]) / IN)
            e = 1 - (1 - p) ** 3
            root.attributes("-alpha", min(0.98, e * 1.2))
            root.geometry(f"+{int(fx + travel * (1 - e))}+{fy}")
            if p >= 1.0:
                st["phase"] = "hold"
        elif st["phase"] == "hold":
            if not st["hover"]:
                st["held"] += dt
            if st["held"] >= hold_secs:
                st["phase"], st["ts"] = "out", now
        else:
            p = min(1.0, (now - st["ts"]) / OUT)
            e = p * p
            root.attributes("-alpha", max(0.0, 0.98 * (1 - e)))
            root.geometry(f"+{int(fx + travel * e)}+{fy}")
            if p >= 1.0:
                root.destroy()
                return
        draw(t)
        root.after(15, frame)

    cv.bind("<Button-1>", lambda _e: root.destroy())
    cv.bind("<Enter>", lambda _e: st.update(hover=True))
    cv.bind("<Leave>", lambda _e: st.update(hover=False))
    frame()
    root.mainloop()


def _spawn_popup(location, secs, ui):
    exe = sys.executable
    if os.path.basename(exe).lower() == "python.exe":
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(w):
            exe = w
    try:
        subprocess.Popen(
            [exe, os.path.abspath(__file__), "--popup", location or "", str(secs), str(ui)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW,
        )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Windows toast (optional, off by default: Focus Assist / app permissions can hide it).
# ---------------------------------------------------------------------------
_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
_TOAST_SCRIPT = (
    r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$t = [Security.SecurityElement]::Escape($env:EXPRESSO_TOAST_TITLE)
$b = [Security.SecurityElement]::Escape($env:EXPRESSO_TOAST_BODY)
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual><audio silent='true'/></toast>")
$n = [Windows.UI.Notifications.ToastNotification]::new($x)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('"""
    + _APP_ID
    + r"""').Show($n)
"""
)


def _show_toast(location):
    from config import APP_NAME

    env = dict(os.environ)
    env["EXPRESSO_TOAST_TITLE"] = f"{APP_NAME}: VPN connected"
    env["EXPRESSO_TOAST_BODY"] = f"Server: {location}" if location else "Secure tunnel established"
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _TOAST_SCRIPT],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW,
        )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
def notify_connected(location=None):
    """Call once, at the moment the VPN is confirmed connected."""
    if os.name != "nt":
        return
    from config import (
        NOTIFY_FLASH,
        NOTIFY_POPUP,
        NOTIFY_POPUP_SCALE,
        NOTIFY_POPUP_SECS,
        NOTIFY_SOUND,
        NOTIFY_SOUND_FILE,
        NOTIFY_TOAST,
    )

    if NOTIFY_POPUP:
        _spawn_popup(location, NOTIFY_POPUP_SECS, NOTIFY_POPUP_SCALE)
    if NOTIFY_FLASH:
        _flash_taskbar()
    if NOTIFY_TOAST:
        threading.Thread(target=_show_toast, args=(location,), daemon=True).start()
    if NOTIFY_SOUND:
        threading.Thread(target=_play_sound, args=(NOTIFY_SOUND_FILE,), daemon=True).start()


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--popup":
        try:
            secs = float(sys.argv[3]) if len(sys.argv) > 3 else 1.6
            ui = float(sys.argv[4]) if len(sys.argv) > 4 else 0.58
        except ValueError:
            secs, ui = 1.6, 0.58
        _popup_main(sys.argv[2] if len(sys.argv) > 2 else "", secs, ui)
