#!/usr/bin/env python3
"""AutoClicker - window-targeted, resolution-independent auto clicker for Windows.

Keeps an application alive by clicking a chosen spot inside a chosen window
at a fixed interval.

* The click target is stored as a percentage of the target window's client
  area, so the same relative spot keeps getting clicked when the screen
  resolution or window size changes (e.g. when the VM is accessed over RDP
  from a phone, iPad or PC).
* Clicks are delivered straight to the target window with window messages
  (PostMessage), so the real mouse cursor never moves and you can keep
  working in other apps while it clicks in the background.
"""

import ctypes
import json
import os
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

APP_NAME = "AutoClicker"
APP_VERSION = "2.1.0"

IS_WINDOWS = sys.platform == "win32"

CAPTURE_SETTLE_MS = 450         # let the target window come to front before overlay
MIN_INTERVAL_SECONDS = 0.2
TICK_MS = 200

UNIT_SECONDS = {"seconds": 1, "minutes": 60, "hours": 3600}

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

COL_BG = "#12141d"
COL_CARD = "#1b1f2d"
COL_CARD_HI = "#232839"
COL_BORDER = "#2b3147"
COL_TEXT = "#eceef6"
COL_SUB = "#8b92ab"
COL_ACCENT = "#5b8cff"
COL_ACCENT_HOVER = "#7aa2ff"
COL_GREEN = "#22c55e"
COL_GREEN_HOVER = "#3ddb75"
COL_AMBER = "#f5b942"
COL_AMBER_HOVER = "#ffd06b"
COL_RED = "#ef5350"
COL_RED_HOVER = "#ff6f6c"
COL_BAR_BG = "#161927"

FONT = "Segoe UI"

# ---------------------------------------------------------------------------
# Win32 plumbing
# ---------------------------------------------------------------------------

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
GA_ROOT = 2
SW_RESTORE = 9
DWMWA_CLOAKED = 14
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19

EXCLUDED_CLASSES = {"Progman", "Shell_TrayWnd", "Windows.UI.Core.CoreWindow",
                    "WorkerW", "Shell_SecondaryTrayWnd"}

# Windows whose content is a remote session: they ignore posted window
# messages (input is captured as real events and forwarded), so they need
# Real-cursor mode.
REMOTE_CLIENT_PATTERNS = ("horizon", "omnissa", "vmware", "citrix",
                          "remote desktop", "remotedesktop", "mstsc", "rdp",
                          "anydesk", "teamviewer", "parsec", "rustdesk")
REMOTE_CLIENT_CLASSES = ("tscshellcontainerclass", "vmwareclient")

DWM_TNP_RECTDESTINATION = 0x0001
DWM_TNP_OPACITY = 0x0004
DWM_TNP_VISIBLE = 0x0008
DWM_TNP_SOURCECLIENTAREAONLY = 0x0010

if ctypes.sizeof(ctypes.c_void_p) == 8:
    ULONG_PTR = ctypes.c_ulonglong
else:
    ULONG_PTR = ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class DWM_THUMBNAIL_PROPERTIES(ctypes.Structure):
    _fields_ = [("dwFlags", ctypes.c_uint),
                ("rcDestination", RECT),
                ("rcSource", RECT),
                ("opacity", ctypes.c_ubyte),
                ("fVisible", ctypes.c_int),
                ("fSourceClientAreaOnly", ctypes.c_int)]


if IS_WINDOWS:
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.RealChildWindowFromPoint.argtypes = [ctypes.c_void_p, POINT]
    user32.RealChildWindowFromPoint.restype = ctypes.c_void_p
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                    ctypes.c_size_t, ctypes.c_ssize_t]
    user32.MapWindowPoints.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.POINTER(POINT), ctypes.c_uint]
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.WindowFromPoint.argtypes = [POINT]
    user32.WindowFromPoint.restype = ctypes.c_void_p
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    dwmapi = ctypes.windll.dwmapi
    dwmapi.DwmRegisterThumbnail.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                            ctypes.POINTER(ctypes.c_void_p)]
    dwmapi.DwmUnregisterThumbnail.argtypes = [ctypes.c_void_p]
    dwmapi.DwmUpdateThumbnailProperties.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(DWM_THUMBNAIL_PROPERTIES)]
    dwmapi.DwmQueryThumbnailSourceSize.argtypes = [ctypes.c_void_p,
                                                   ctypes.POINTER(SIZE)]


def set_dpi_aware():
    """Opt in to DPI awareness so all coordinates are real pixels."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def enable_dark_title_bar(window):
    """Ask DWM for a dark title bar (Windows 10 1809+); harmless elsewhere."""
    try:
        window.update_idletasks()
        hwnd = user32.GetAncestor(window.winfo_id(), GA_ROOT)
        value = ctypes.c_int(1)
        for attr in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def get_virtual_screen():
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        max(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), 1),
        max(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN), 1),
    )


def get_cursor_pos():
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def get_window_title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _get_class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _is_cloaked(hwnd):
    try:
        val = ctypes.c_int(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val))
        return bool(val.value)
    except Exception:
        return False


def list_windows(exclude_hwnds):
    """Visible, titled, top-level windows the user can target."""
    results = []

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        if hwnd in exclude_hwnds or _is_cloaked(hwnd):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        if _get_class_name(hwnd) in EXCLUDED_CLASSES:
            return True
        title = get_window_title(hwnd)
        if title.strip():
            results.append((hwnd, title))
        return True

    user32.EnumWindows(WNDENUMPROC(lambda h, l: callback(h, l)), 0)
    return results


def get_client_geometry(hwnd):
    """Screen position and size of a window's client area, or None."""
    rect = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    w, h = rect.right, rect.bottom
    if w <= 0 or h <= 0:
        return None
    origin = POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    return origin.x, origin.y, w, h


def bring_to_front(hwnd):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)


def force_foreground(hwnd):
    """SetForegroundWindow with the AttachThreadInput fallback for when
    Windows refuses to let a background process steal focus."""
    if user32.GetForegroundWindow() == hwnd:
        return
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if user32.SetForegroundWindow(hwnd):
        return
    fg = user32.GetForegroundWindow()
    cur = ctypes.windll.kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    if fg_thread and fg_thread != cur:
        user32.AttachThreadInput(fg_thread, cur, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(fg_thread, cur, False)


def looks_like_remote_client(hwnd, title):
    """Remote-desktop client windows need Real-cursor mode."""
    haystack = (title + " " + _get_class_name(hwnd)).lower()
    return (any(p in haystack for p in REMOTE_CLIENT_PATTERNS)
            or any(c in haystack for c in REMOTE_CLIENT_CLASSES))


def cursor_click_window(hwnd, fx, fy):
    """Real-input click at a window fraction, as unobtrusive as possible.

    Remote-desktop clients (RDP, Omnissa Horizon, Citrix...) only forward
    real input, so this sends a genuine click. The window is raised only if
    something else covers the click point, the cursor is restored right
    after, and the window you were working in gets focus back.
    """
    geom = get_client_geometry(hwnd)
    if geom is None:
        return False
    sx, sy, w, h = geom
    px = sx + round(fx * max(w - 1, 1))
    py = sy + round(fy * max(h - 1, 1))

    root_target = user32.GetAncestor(hwnd, GA_ROOT)
    hit = user32.WindowFromPoint(POINT(px, py))
    covered = not hit or user32.GetAncestor(hit, GA_ROOT) != root_target

    prev = user32.GetForegroundWindow()
    if covered:
        force_foreground(hwnd)
        time.sleep(0.15)
        geom = get_client_geometry(hwnd)
        if geom is None:
            return False
        sx, sy, w, h = geom
        px = sx + round(fx * max(w - 1, 1))
        py = sy + round(fy * max(h - 1, 1))

    cursor_click_at(px, py)

    if covered and prev and prev != root_target and user32.IsWindow(prev):
        time.sleep(0.08)
        force_foreground(prev)
    return True


def post_click(hwnd, fx, fy, client_size):
    """Deliver a click at a client-area fraction using window messages only.

    The message is posted to the deepest child window under the point (that is
    who actually handles clicks in real apps), with coordinates mapped into
    that child's client space. The physical cursor is never touched.
    """
    w, h = client_size
    cx = round(fx * max(w - 1, 1))
    cy = round(fy * max(h - 1, 1))

    target = hwnd
    for _ in range(16):
        child = user32.RealChildWindowFromPoint(target, POINT(cx, cy))
        if not child or child == target:
            break
        pt = POINT(cx, cy)
        user32.MapWindowPoints(target, child, ctypes.byref(pt), 1)
        target, cx, cy = child, pt.x, pt.y

    lparam = ((cy & 0xFFFF) << 16) | (cx & 0xFFFF)
    user32.PostMessageW(target, WM_MOUSEMOVE, 0, lparam)
    ok_down = user32.PostMessageW(target, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    time.sleep(0.02)
    ok_up = user32.PostMessageW(target, WM_LBUTTONUP, 0, lparam)
    return bool(ok_down and ok_up)


def _send_mouse(flags, nx=0, ny=0):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(nx, ny, 0, flags, 0, 0)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def cursor_click_at(sx, sy):
    """Fallback mode: a real cursor click at a screen pixel, cursor restored."""
    old = get_cursor_pos()
    vx, vy, vw, vh = get_virtual_screen()
    nx = round((sx - vx) * 65535 / max(vw - 1, 1))
    ny = round((sy - vy) * 65535 / max(vh - 1, 1))
    move = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    _send_mouse(move, nx, ny)
    time.sleep(0.01)
    _send_mouse(move | MOUSEEVENTF_LEFTDOWN, nx, ny)
    time.sleep(0.01)
    _send_mouse(move | MOUSEEVENTF_LEFTUP, nx, ny)
    time.sleep(0.03)
    user32.SetCursorPos(old[0], old[1])


def resource_path(rel):
    """Path to a bundled resource, both in dev and in the PyInstaller exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------

def config_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, APP_NAME)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = os.path.expanduser("~")
    return os.path.join(folder, "autoclicker.json")


def load_config():
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data):
    try:
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Small UI helpers
# ---------------------------------------------------------------------------

def format_duration(seconds):
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def add_hover(widget, normal, hover):
    widget.bind("<Enter>", lambda e: widget.config(bg=hover))
    widget.bind("<Leave>", lambda e: widget.config(bg=normal))


def pill_button(parent, text, bg, hover, command, fg="white", font_size=10, padx=14, pady=6):
    btn = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                    activebackground=hover, activeforeground=fg,
                    relief="flat", borderwidth=0, cursor="hand2",
                    font=(FONT, font_size, "bold"), padx=padx, pady=pady)
    add_hover(btn, bg, hover)
    return btn


def truncate(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + "…"


# ---------------------------------------------------------------------------
# Graphical window picker (live previews via the DWM thumbnail API — the
# same mechanism as the Windows taskbar previews)
# ---------------------------------------------------------------------------

class WindowPicker:
    COLS, ROWS = 3, 2
    TILE_W, TILE_H = 272, 196
    THUMB_W, THUMB_H = 256, 140
    GAP, MARGIN, HEADER, FOOTER = 12, 14, 48, 56

    def __init__(self, parent, exclude_hwnds, on_select):
        self.on_select = on_select
        self.windows = []
        self.page = 0
        self.thumbs = []
        self.hover = None

        self.W = self.MARGIN * 2 + self.COLS * self.TILE_W + (self.COLS - 1) * self.GAP
        self.H = (self.HEADER + self.FOOTER + self.MARGIN
                  + self.ROWS * self.TILE_H + (self.ROWS - 1) * self.GAP)

        top = tk.Toplevel(parent)
        self.top = top
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=COL_ACCENT)
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        top.geometry(f"{self.W}x{self.H}+{max((sw - self.W) // 2, 0)}"
                     f"+{max((sh - self.H) // 3, 0)}")

        self.canvas = tk.Canvas(top, width=self.W - 2, height=self.H - 2,
                                bg=COL_BG, highlightthickness=0)
        self.canvas.pack(padx=1, pady=1)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Button-1>", self._on_click)
        top.bind("<Escape>", lambda e: self._close())
        top.protocol("WM_DELETE_WINDOW", self._close)

        self.prev_btn = pill_button(self.canvas, "‹", COL_CARD_HI, COL_BORDER,
                                    lambda: self._flip(-1), fg=COL_TEXT, padx=14)
        self.next_btn = pill_button(self.canvas, "›", COL_CARD_HI, COL_BORDER,
                                    lambda: self._flip(1), fg=COL_TEXT, padx=14)
        self.refresh_btn = pill_button(self.canvas, "↻ Refresh", COL_CARD_HI,
                                       COL_BORDER, self.refresh, fg=COL_TEXT)
        self.cancel_btn = pill_button(self.canvas, "✕ Cancel", COL_RED,
                                      COL_RED_HOVER, self._close)

        top.update_idletasks()
        self.dest_hwnd = user32.GetAncestor(top.winfo_id(), GA_ROOT)
        self.exclude = set(exclude_hwnds) | {self.dest_hwnd}

        top.grab_set()
        top.focus_force()
        self.refresh()

    # ---- data ----

    def refresh(self):
        self.windows = list_windows(self.exclude)
        self.page = 0
        self._render()

    def _pages(self):
        per = self.COLS * self.ROWS
        return max((len(self.windows) + per - 1) // per, 1)

    def _flip(self, step):
        new = min(max(self.page + step, 0), self._pages() - 1)
        if new != self.page:
            self.page = new
            self._render()

    # ---- rendering ----

    def _tile_rect(self, i):
        col, row = i % self.COLS, i // self.COLS
        x = self.MARGIN + col * (self.TILE_W + self.GAP)
        y = self.HEADER + row * (self.TILE_H + self.GAP)
        return x, y

    def _render(self):
        self._unregister_all()
        c = self.canvas
        c.delete("all")
        self.hover = None

        c.create_text(self.MARGIN, 16, anchor="w", fill=COL_TEXT,
                      text="Choose the window to keep alive",
                      font=(FONT, 13, "bold"))
        c.create_text(self.MARGIN, 34, anchor="w", fill=COL_SUB,
                      text="Live previews — click one to select it  •  Esc to cancel",
                      font=(FONT, 9))

        per = self.COLS * self.ROWS
        page_windows = self.windows[self.page * per:(self.page + 1) * per]

        if not page_windows:
            c.create_text(self.W // 2, self.H // 2, fill=COL_SUB,
                          text="No windows found — press Refresh",
                          font=(FONT, 11))
        for i, (hwnd, title) in enumerate(page_windows):
            x, y = self._tile_rect(i)
            c.create_rectangle(x, y, x + self.TILE_W, y + self.TILE_H,
                               fill=COL_CARD, outline=COL_BORDER,
                               tags=f"tile{i}")
            c.create_text(x + self.TILE_W // 2, y + self.THUMB_H + 8 + 22,
                          text=truncate(title, 38), fill=COL_TEXT,
                          font=(FONT, 9, "bold"), width=self.TILE_W - 16)
            if not self._register_thumb(hwnd, x + 8, y + 8):
                c.create_text(x + self.TILE_W // 2, y + 8 + self.THUMB_H // 2,
                              text="🪟", fill=COL_SUB, font=(FONT, 28))

        fy = self.H - self.FOOTER + 12
        c.create_window(self.MARGIN, fy, anchor="nw", window=self.refresh_btn)
        c.create_window(self.W // 2 - 40, fy, anchor="ne", window=self.prev_btn)
        c.create_text(self.W // 2, fy + 15, fill=COL_SUB,
                      text=f"{self.page + 1} / {self._pages()}", font=(FONT, 10))
        c.create_window(self.W // 2 + 40, fy, anchor="nw", window=self.next_btn)
        c.create_window(self.W - self.MARGIN, fy, anchor="ne", window=self.cancel_btn)

    def _register_thumb(self, hwnd, dx, dy):
        try:
            thumb = ctypes.c_void_p()
            if dwmapi.DwmRegisterThumbnail(self.dest_hwnd, hwnd,
                                           ctypes.byref(thumb)) != 0 or not thumb.value:
                return False
            src = SIZE()
            dwmapi.DwmQueryThumbnailSourceSize(thumb, ctypes.byref(src))
            sw, sh = max(src.cx, 1), max(src.cy, 1)
            scale = min(self.THUMB_W / sw, self.THUMB_H / sh, 1.0)
            tw, th = max(int(sw * scale), 1), max(int(sh * scale), 1)
            ox = dx + (self.THUMB_W - tw) // 2 + 1   # +1: canvas offset in window
            oy = dy + (self.THUMB_H - th) // 2 + 1
            props = DWM_THUMBNAIL_PROPERTIES()
            props.dwFlags = (DWM_TNP_RECTDESTINATION | DWM_TNP_VISIBLE
                             | DWM_TNP_OPACITY | DWM_TNP_SOURCECLIENTAREAONLY)
            props.rcDestination = RECT(ox, oy, ox + tw, oy + th)
            props.opacity = 255
            props.fVisible = 1
            props.fSourceClientAreaOnly = 1
            dwmapi.DwmUpdateThumbnailProperties(thumb, ctypes.byref(props))
            self.thumbs.append(thumb)
            return True
        except Exception:
            return False

    def _unregister_all(self):
        for thumb in self.thumbs:
            try:
                dwmapi.DwmUnregisterThumbnail(thumb)
            except Exception:
                pass
        self.thumbs = []

    # ---- interaction ----

    def _tile_at(self, x, y):
        per = self.COLS * self.ROWS
        count = len(self.windows[self.page * per:(self.page + 1) * per])
        for i in range(count):
            tx, ty = self._tile_rect(i)
            if tx <= x <= tx + self.TILE_W and ty <= y <= ty + self.TILE_H:
                return i
        return None

    def _on_motion(self, event):
        i = self._tile_at(event.x, event.y)
        if i == self.hover:
            return
        self.hover = i
        self.canvas.delete("hoverbox")
        if i is not None:
            x, y = self._tile_rect(i)
            self.canvas.create_rectangle(x - 2, y - 2, x + self.TILE_W + 2,
                                         y + self.TILE_H + 2,
                                         outline=COL_ACCENT, width=2,
                                         tags="hoverbox")

    def _on_click(self, event):
        i = self._tile_at(event.x, event.y)
        if i is None:
            return
        per = self.COLS * self.ROWS
        idx = self.page * per + i
        if idx < len(self.windows):
            hwnd, title = self.windows[idx]
            self._close()
            self.on_select(hwnd, title)

    def _close(self):
        self._unregister_all()
        try:
            self.top.grab_release()
        except Exception:
            pass
        self.top.destroy()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class AutoClickerApp:
    def __init__(self, root):
        self.root = root

        self.windows = []             # [(hwnd, title)] from last refresh
        self.target_hwnd = None
        self.target_title = None
        self.fraction = None          # (fx, fy) inside the target client area
        self.interval = None
        self.click_count = 0
        self.paused = False
        self.next_click_at = None
        self.remaining_when_paused = None
        self.last_click_state = "ok"  # ok | blocked | lost
        self.cached_client_size = None

        self.bar = None
        self.overlay = None
        self.picker = None
        self._tick_job = None
        self._drag_offset = None
        self._pulse_on = False

        self._build_styles()
        self._build_setup_window()
        self._restore_saved_config()
        self._update_window_readout()
        self._draw_preview()

    # ---------------- Styling ----------------

    def _build_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Dark.TCombobox",
            fieldbackground=COL_CARD_HI, background=COL_CARD_HI,
            foreground=COL_TEXT, arrowcolor=COL_SUB,
            bordercolor=COL_BORDER, lightcolor=COL_CARD_HI,
            darkcolor=COL_CARD_HI, insertcolor=COL_TEXT,
            selectbackground=COL_ACCENT, selectforeground="white", padding=6)
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", COL_CARD_HI)],
                  foreground=[("readonly", COL_TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", COL_CARD_HI)
        self.root.option_add("*TCombobox*Listbox.foreground", COL_TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", COL_ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")
        self.root.option_add("*TCombobox*Listbox.font", (FONT, 10))

    def _card(self, parent, step, title, subtitle=None):
        outer = tk.Frame(parent, bg=COL_CARD, highlightbackground=COL_BORDER,
                         highlightthickness=1)
        outer.pack(fill="x", pady=(0, 10))
        inner = tk.Frame(outer, bg=COL_CARD, padx=14, pady=12)
        inner.pack(fill="x")

        head = tk.Frame(inner, bg=COL_CARD)
        head.pack(fill="x")
        badge = tk.Label(head, text=f" {step} ", bg=COL_ACCENT, fg="white",
                         font=(FONT, 9, "bold"))
        badge.pack(side="left")
        tk.Label(head, text=" " + title, bg=COL_CARD, fg=COL_TEXT,
                 font=(FONT, 11, "bold")).pack(side="left")
        if subtitle:
            tk.Label(inner, text=subtitle, bg=COL_CARD, fg=COL_SUB,
                     font=(FONT, 9), justify="left", anchor="w").pack(
                fill="x", pady=(4, 0))
        body = tk.Frame(inner, bg=COL_CARD)
        body.pack(fill="x", pady=(10, 0))
        return body

    # ---------------- Setup window ----------------

    def _build_setup_window(self):
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.configure(bg=COL_BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        enable_dark_title_bar(self.root)

        outer = tk.Frame(self.root, bg=COL_BG, padx=18, pady=16)
        outer.pack(fill="both", expand=True)

        # Header
        head = tk.Frame(outer, bg=COL_BG)
        head.pack(fill="x", pady=(0, 14))
        tk.Label(head, text="⚡", bg=COL_BG, fg=COL_ACCENT,
                 font=(FONT, 20)).pack(side="left", padx=(0, 8))
        titles = tk.Frame(head, bg=COL_BG)
        titles.pack(side="left")
        row = tk.Frame(titles, bg=COL_BG)
        row.pack(anchor="w")
        tk.Label(row, text=APP_NAME, bg=COL_BG, fg=COL_TEXT,
                 font=(FONT, 16, "bold")).pack(side="left")
        tk.Label(row, text=f"  v{APP_VERSION}", bg=COL_BG, fg=COL_SUB,
                 font=(FONT, 9)).pack(side="left", pady=(6, 0))
        tk.Label(titles, text="Background keep-alive clicks inside a window of your choice",
                 bg=COL_BG, fg=COL_SUB, font=(FONT, 9)).pack(anchor="w")

        # Step 1: target window
        body1 = self._card(outer, 1, "Target window",
                           "Pick the window from live previews. Clicks go to this\n"
                           "window only — your mouse stays free for everything else.")
        self.window_label = tk.Label(body1, text="No window selected",
                                     bg=COL_CARD, fg=COL_SUB, anchor="w",
                                     justify="left", wraplength=230,
                                     font=(FONT, 10, "bold"))
        self.window_label.pack(side="left", fill="x", expand=True)
        pill_button(body1, "🪟  Choose…", COL_ACCENT, COL_ACCENT_HOVER,
                    self._choose_window).pack(side="left", padx=(8, 0))

        # Step 2: click point
        body2 = self._card(outer, 2, "Click point",
                           "Pick the spot graphically — it is stored as a % of the window,\n"
                           "so it adapts to any screen size or resolution.")
        self.preview = tk.Canvas(body2, width=272, height=140, bg=COL_CARD,
                                 highlightthickness=0)
        self.preview.pack()
        btns2 = tk.Frame(body2, bg=COL_CARD)
        btns2.pack(fill="x", pady=(10, 0))
        pill_button(btns2, "🎯  Pick point", COL_ACCENT, COL_ACCENT_HOVER,
                    self._pick_point).pack(side="left", expand=True, fill="x", padx=(0, 4))
        pill_button(btns2, "👁  Show", COL_CARD_HI, COL_BORDER,
                    self._show_point, fg=COL_TEXT).pack(side="left", expand=True,
                                                        fill="x", padx=4)
        pill_button(btns2, "🖱  Test click", COL_CARD_HI, COL_BORDER,
                    self._test_click, fg=COL_TEXT).pack(side="left", expand=True,
                                                        fill="x", padx=(4, 0))

        # Step 3: frequency
        body3 = self._card(outer, 3, "Frequency")
        tk.Label(body3, text="Click every", bg=COL_CARD, fg=COL_TEXT,
                 font=(FONT, 10)).pack(side="left", padx=(0, 8))
        self.value_var = tk.StringVar(value="30")
        entry = tk.Entry(body3, textvariable=self.value_var, width=7,
                         justify="center", bg=COL_CARD_HI, fg=COL_TEXT,
                         insertbackground=COL_TEXT, relief="flat",
                         highlightthickness=1, highlightbackground=COL_BORDER,
                         highlightcolor=COL_ACCENT, font=(FONT, 11))
        entry.pack(side="left", ipady=4, padx=(0, 8))
        self.unit_var = tk.StringVar(value="seconds")
        unit = ttk.Combobox(body3, textvariable=self.unit_var, state="readonly",
                            values=list(UNIT_SECONDS.keys()), width=9,
                            style="Dark.TCombobox", font=(FONT, 10))
        unit.pack(side="left")

        # Click method
        method_row = tk.Frame(outer, bg=COL_BG)
        method_row.pack(fill="x", pady=(2, 10))
        self.method_var = tk.StringVar(value="background")
        for value, label in (("background", "🫥 Background (invisible, mouse stays free)"),
                             ("cursor", "🖱 Real cursor (for RDP / Horizon / Citrix windows)")):
            tk.Radiobutton(method_row, text=label, value=value,
                           variable=self.method_var, bg=COL_BG, fg=COL_SUB,
                           selectcolor=COL_CARD_HI, activebackground=COL_BG,
                           activeforeground=COL_TEXT, font=(FONT, 9),
                           highlightthickness=0, cursor="hand2").pack(anchor="w")

        # Start
        self.start_button = pill_button(outer, "▶   Start clicking",
                                        COL_GREEN, COL_GREEN_HOVER,
                                        self._start_clicking, font_size=13, pady=10)
        self.start_button.pack(fill="x")

        self.hint_label = tk.Label(outer, text="Settings are saved automatically.",
                                   bg=COL_BG, fg=COL_SUB, font=(FONT, 9),
                                   anchor="w", justify="left")
        self.hint_label.pack(fill="x", pady=(10, 0))

    def _hint(self, text):
        self.hint_label.config(text=text)

    # ---------------- Window targeting ----------------

    def _own_hwnds(self):
        hwnds = set()
        for w in (self.root, self.bar, self.overlay):
            if w is not None:
                try:
                    hwnds.add(user32.GetAncestor(w.winfo_id(), GA_ROOT))
                except Exception:
                    pass
        return hwnds

    def _choose_window(self):
        if self.picker is not None and self.picker.top.winfo_exists():
            return
        self.picker = WindowPicker(self.root, self._own_hwnds(), self._set_target)

    def _set_target(self, hwnd, title):
        self.picker = None
        self.target_hwnd, self.target_title = hwnd, title
        self.cached_client_size = None
        geom = get_client_geometry(hwnd)
        if geom:
            self.cached_client_size = (geom[2], geom[3])
        if looks_like_remote_client(hwnd, title) and self.method_var.get() == "background":
            self.method_var.set("cursor")
            self._hint("Remote-desktop window detected — switched to Real cursor "
                       "mode (remote sessions ignore background clicks).")
        else:
            self._hint("Window selected. Now pick the click point.")
        save_config(self._current_config())
        self._update_window_readout()
        self._draw_preview()

    def _update_window_readout(self):
        if self.target_title:
            alive = self.target_hwnd is not None and user32.IsWindow(self.target_hwnd)
            self.window_label.config(
                text=("✔ " if alive else "⚠ (closed) ") + truncate(self.target_title, 60),
                fg=COL_TEXT if alive else COL_AMBER)
        else:
            self.window_label.config(text="No window selected", fg=COL_SUB)

    def _target_geometry(self):
        """Client geometry of the target, refreshing the size cache."""
        if self.target_hwnd is None or not user32.IsWindow(self.target_hwnd):
            return None
        geom = get_client_geometry(self.target_hwnd)
        if geom:
            self.cached_client_size = (geom[2], geom[3])
        return geom

    def _reattach_window(self):
        """If the target window was closed and reopened, find it by title."""
        if not self.target_title:
            return False
        for hwnd, title in list_windows(self._own_hwnds()):
            if title == self.target_title or self.target_title in title:
                self.target_hwnd = hwnd
                return True
        return False

    # ---------------- Preview drawing ----------------

    def _draw_preview(self):
        c = self.preview
        c.delete("all")
        CW, CH = 272, 140

        if self.target_hwnd is None and self.target_title is None:
            c.create_text(CW // 2, CH // 2, text="Choose a window above",
                          fill=COL_SUB, font=(FONT, 10))
            return

        w, h = self.cached_client_size or (16, 9)
        aspect = w / max(h, 1)
        rw = CW - 24
        rh = rw / aspect
        if rh > CH - 24:
            rh = CH - 24
            rw = rh * aspect
        x0 = (CW - rw) / 2
        y0 = (CH - rh) / 2
        x1, y1 = x0 + rw, y0 + rh

        # window body + fake title bar
        c.create_rectangle(x0, y0, x1, y1, fill=COL_CARD_HI, outline=COL_BORDER)
        c.create_rectangle(x0, y0, x1, y0 + 10, fill=COL_BORDER, outline=COL_BORDER)
        for i in range(3):
            c.create_oval(x0 + 5 + i * 9, y0 + 3, x0 + 11 + i * 9, y0 + 9,
                          fill=COL_SUB, outline="")

        if self.fraction is None:
            c.create_text((x0 + x1) / 2, (y0 + y1 + 10) / 2,
                          text="No point picked yet", fill=COL_SUB, font=(FONT, 9))
            return

        fx, fy = self.fraction
        px = x0 + fx * rw
        py = y0 + 10 + fy * (rh - 10)
        c.create_line(px, y0 + 10, px, y1, fill=COL_ACCENT, dash=(2, 3))
        c.create_line(x0, py, x1, py, fill=COL_ACCENT, dash=(2, 3))
        c.create_oval(px - 5, py - 5, px + 5, py + 5,
                      outline=COL_ACCENT, width=2)
        c.create_oval(px - 1.5, py - 1.5, px + 1.5, py + 1.5,
                      fill=COL_ACCENT, outline="")
        label_y = py - 14 if py - 14 > y0 + 16 else py + 14
        c.create_text(min(max(px, x0 + 46), x1 - 46), label_y,
                      text=f"{fx * 100:.1f}% , {fy * 100:.1f}%",
                      fill=COL_TEXT, font=(FONT, 8, "bold"))

    # ---------------- Graphical point picking ----------------

    def _pick_point(self):
        if self.target_hwnd is None or not user32.IsWindow(self.target_hwnd):
            messagebox.showwarning(APP_NAME, "Select the target window first (step 1).")
            return
        self.root.withdraw()
        bring_to_front(self.target_hwnd)
        self.root.after(CAPTURE_SETTLE_MS, self._open_overlay)

    def _open_overlay(self):
        geom = self._target_geometry()
        if geom is None:
            self.root.deiconify()
            messagebox.showwarning(
                APP_NAME, "Could not read the window area (is it minimized?).")
            return
        sx, sy, w, h = geom

        overlay = tk.Toplevel(self.root)
        self.overlay = overlay
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.30)
        overlay.geometry(f"{w}x{h}+{sx}+{sy}")
        overlay.configure(bg=COL_ACCENT)

        canvas = tk.Canvas(overlay, width=w, height=h, bg=COL_ACCENT,
                           highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        canvas.create_text(
            w // 2, max(24, h // 12),
            text="Click the exact spot to auto-click   •   Esc to cancel",
            fill="white", font=(FONT, 12, "bold"), tags="hint")

        def on_motion(e):
            canvas.delete("cross")
            canvas.create_line(e.x, 0, e.x, h, fill="white", width=1, tags="cross")
            canvas.create_line(0, e.y, w, e.y, fill="white", width=1, tags="cross")
            canvas.create_text(
                min(max(e.x, 60), w - 60), min(e.y + 22, h - 12),
                text=f"{e.x / max(w - 1, 1) * 100:.1f}% , {e.y / max(h - 1, 1) * 100:.1f}%",
                fill="white", font=(FONT, 9, "bold"), tags="cross")

        def on_click(e):
            fx = min(max(e.x / max(w - 1, 1), 0.0), 1.0)
            fy = min(max(e.y / max(h - 1, 1), 0.0), 1.0)
            self.fraction = (fx, fy)
            self._close_overlay()
            save_config(self._current_config())
            self._flash_marker(sx + round(fx * (w - 1)), sy + round(fy * (h - 1)))
            self._finish_pick()

        def on_cancel(_e=None):
            self._close_overlay()
            self._finish_pick(cancelled=True)

        canvas.bind("<Motion>", on_motion)
        canvas.bind("<Button-1>", on_click)
        overlay.bind("<Escape>", on_cancel)
        overlay.focus_force()

    def _close_overlay(self):
        if self.overlay is not None:
            self.overlay.destroy()
            self.overlay = None

    def _finish_pick(self, cancelled=False):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self._draw_preview()
        self._hint("Cancelled." if cancelled
                   else "Point saved. Use Test click to verify it.")

    def _flash_marker(self, sx, sy, rings=9):
        """Animated crosshair rings at a screen point, click-through by look."""
        size = 150
        half = size // 2
        marker = tk.Toplevel(self.root)
        marker.overrideredirect(True)
        marker.attributes("-topmost", True)
        try:
            marker.attributes("-transparentcolor", "#010101")
        except tk.TclError:
            marker.attributes("-alpha", 0.6)
        marker.geometry(f"{size}x{size}+{sx - half}+{sy - half}")
        canvas = tk.Canvas(marker, width=size, height=size, bg="#010101",
                           highlightthickness=0)
        canvas.pack()

        def frame(i=0):
            if i >= rings:
                marker.destroy()
                return
            canvas.delete("all")
            r = 8 + i * 7
            canvas.create_oval(half - r, half - r, half + r, half + r,
                               outline=COL_ACCENT, width=3)
            canvas.create_oval(half - 4, half - 4, half + 4, half + 4,
                               fill=COL_ACCENT, outline="")
            canvas.create_line(half - r - 8, half, half + r + 8, half,
                               fill=COL_ACCENT, width=1)
            canvas.create_line(half, half - r - 8, half, half + r + 8,
                               fill=COL_ACCENT, width=1)
            marker.after(90, frame, i + 1)

        frame()

    def _show_point(self):
        if self.fraction is None:
            messagebox.showwarning(APP_NAME, "Pick a click point first.")
            return
        if self.target_hwnd is None or not user32.IsWindow(self.target_hwnd):
            messagebox.showwarning(APP_NAME, "The target window is gone — reselect it.")
            return
        bring_to_front(self.target_hwnd)

        def flash():
            geom = self._target_geometry()
            if geom:
                sx, sy, w, h = geom
                fx, fy = self.fraction
                self._flash_marker(sx + round(fx * (w - 1)), sy + round(fy * (h - 1)))

        self.root.after(CAPTURE_SETTLE_MS, flash)

    # ---------------- Clicking ----------------

    def _perform_click(self):
        """Returns 'ok', 'blocked' or 'lost'."""
        if self.target_hwnd is None or not user32.IsWindow(self.target_hwnd):
            if not self._reattach_window():
                return "lost"
        if self.method_var.get() == "cursor":
            geom = self._target_geometry()   # refresh the size cache
            if geom is None:
                return "lost"
            ok = cursor_click_window(self.target_hwnd, *self.fraction)
            return "ok" if ok else "lost"
        # background mode: prefer live size, fall back to cache when minimized
        geom = self._target_geometry()
        size = (geom[2], geom[3]) if geom else self.cached_client_size
        if size is None:
            return "lost"
        ok = post_click(self.target_hwnd, self.fraction[0], self.fraction[1], size)
        return "ok" if ok else "blocked"

    def _test_click(self):
        if self.fraction is None:
            messagebox.showwarning(APP_NAME, "Pick a click point first (step 2).")
            return
        if self.target_hwnd is None:
            messagebox.showwarning(APP_NAME, "Select the target window first (step 1).")
            return
        state = self._perform_click()
        self._hint({"ok": "Test click sent ✓",
                    "blocked": "Click was blocked — the target may need AutoClicker "
                               "to run as administrator.",
                    "lost": "Target window not found — reselect it in step 1."}[state])
        if state == "ok" and self.method_var.get() == "background":
            self.root.after(700, self._confirm_background_test)

    def _confirm_background_test(self):
        registered = messagebox.askyesno(
            APP_NAME,
            "Did the target app actually register the test click?\n\n"
            "Remote-desktop windows (RDP, Omnissa Horizon, Citrix...) ignore "
            "background clicks — they only forward real input.\n\n"
            "Choose No to switch to Real cursor mode and try again.")
        if registered:
            self._hint("Great — background mode works for this window.")
        else:
            self.method_var.set("cursor")
            save_config(self._current_config())
            self._hint("Switched to Real cursor mode — press Test click again.")

    # ---------------- Start / validation ----------------

    def _current_config(self):
        cfg = {"value": self.value_var.get(), "unit": self.unit_var.get(),
               "method": self.method_var.get()}
        if self.target_title:
            cfg["window_title"] = self.target_title
        if self.fraction is not None:
            cfg["fx"], cfg["fy"] = self.fraction
        return cfg

    def _restore_saved_config(self):
        cfg = load_config()
        if "fx" in cfg and "fy" in cfg:
            self.fraction = (float(cfg["fx"]), float(cfg["fy"]))
        if "value" in cfg:
            self.value_var.set(str(cfg["value"]))
        if cfg.get("unit") in UNIT_SECONDS:
            self.unit_var.set(cfg["unit"])
        if cfg.get("method") in ("background", "cursor"):
            self.method_var.set(cfg["method"])
        title = cfg.get("window_title")
        if title and self.target_hwnd is None:
            self.target_title = title
            if self._reattach_window():   # auto-reselect if that window is open
                geom = get_client_geometry(self.target_hwnd)
                if geom:
                    self.cached_client_size = (geom[2], geom[3])

    def _read_interval(self):
        try:
            value = float(self.value_var.get())
        except ValueError:
            return None
        if value <= 0:
            return None
        return value * UNIT_SECONDS[self.unit_var.get()]

    def _start_clicking(self):
        if self.target_hwnd is None or not user32.IsWindow(self.target_hwnd):
            messagebox.showwarning(APP_NAME, "Select the target window first (step 1).")
            return
        if self.fraction is None:
            messagebox.showwarning(APP_NAME, "Pick the click point first (step 2).")
            return
        interval = self._read_interval()
        if interval is None or interval < MIN_INTERVAL_SECONDS:
            messagebox.showwarning(
                APP_NAME,
                f"Enter a valid frequency (at least {MIN_INTERVAL_SECONDS} seconds).")
            return
        self.interval = interval
        save_config(self._current_config())

        self.click_count = 0
        self.paused = False
        self.remaining_when_paused = None
        self.last_click_state = "ok"
        self.next_click_at = time.monotonic() + self.interval

        self.root.withdraw()
        self._build_bar()
        self._schedule_tick()

    # ---------------- Control bar ----------------

    def _build_bar(self):
        bar = tk.Toplevel(self.root)
        self.bar = bar
        bar.overrideredirect(True)
        bar.attributes("-topmost", True)
        bar.configure(bg=COL_ACCENT)  # 1px accent frame

        frame = tk.Frame(bar, bg=COL_BAR_BG, padx=12, pady=6)
        frame.pack(padx=1, pady=1)

        self.pulse = tk.Canvas(frame, width=12, height=12, bg=COL_BAR_BG,
                               highlightthickness=0)
        self.pulse.pack(side="left", padx=(0, 8))
        self.pulse_dot = self.pulse.create_oval(2, 2, 10, 10, fill=COL_GREEN, outline="")

        self.bar_target = tk.Label(frame, text=truncate(self.target_title or "", 24),
                                   bg=COL_BAR_BG, fg=COL_SUB, font=(FONT, 9))
        self.bar_target.pack(side="left", padx=(0, 10))

        self.status_label = tk.Label(frame, text="", bg=COL_BAR_BG, fg=COL_TEXT,
                                     font=(FONT, 10, "bold"), width=30, anchor="w")
        self.status_label.pack(side="left", padx=(0, 10))

        self.pause_button = pill_button(frame, "⏸ Pause", COL_AMBER, COL_AMBER_HOVER,
                                        self._toggle_pause, fg="#241a00",
                                        font_size=9, padx=10, pady=3)
        self.pause_button.pack(side="left", padx=3)
        pill_button(frame, "↻ Restart", COL_ACCENT, COL_ACCENT_HOVER,
                    self._restart, font_size=9, padx=10, pady=3).pack(side="left", padx=3)
        pill_button(frame, "⏹ Stop", COL_RED, COL_RED_HOVER,
                    self._stop, font_size=9, padx=10, pady=3).pack(side="left", padx=3)

        for widget in (frame, self.pulse, self.bar_target, self.status_label):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

        bar.update_idletasks()
        width = bar.winfo_reqwidth()
        x = max((bar.winfo_screenwidth() - width) // 2, 0)
        bar.geometry(f"+{x}+0")

    def _drag_start(self, event):
        self._drag_offset = (event.x_root - self.bar.winfo_x(),
                             event.y_root - self.bar.winfo_y())

    def _drag_move(self, event):
        if self._drag_offset is None:
            return
        ox, oy = self._drag_offset
        self.bar.geometry(f"+{event.x_root - ox}+{event.y_root - oy}")

    def _keep_bar_on_screen(self):
        """Pull the bar back into view if a resolution change left it off-screen."""
        if self.bar is None:
            return
        sw = self.bar.winfo_screenwidth()
        sh = self.bar.winfo_screenheight()
        w = self.bar.winfo_width()
        h = self.bar.winfo_height()
        x = self.bar.winfo_x()
        y = self.bar.winfo_y()
        nx = min(max(x, 0), max(sw - w, 0))
        ny = min(max(y, 0), max(sh - h, 0))
        if (nx, ny) != (x, y):
            self.bar.geometry(f"+{nx}+{ny}")

    # ---------------- Clicking loop ----------------

    def _schedule_tick(self):
        self._tick_job = self.root.after(TICK_MS, self._tick)

    def _tick(self):
        self._tick_job = None
        if self.bar is None:
            return
        now = time.monotonic()
        if not self.paused and now >= self.next_click_at:
            self.last_click_state = self._perform_click()
            if self.last_click_state == "ok":
                self.click_count += 1
            # schedule from "now" so a slow tick can't cause a burst of clicks
            self.next_click_at = time.monotonic() + self.interval
        self._update_status()
        self._keep_bar_on_screen()
        self._schedule_tick()

    def _update_status(self):
        self._pulse_on = not self._pulse_on
        if self.paused:
            dot = COL_AMBER
            text = (f"Paused — {format_duration(self.remaining_when_paused)} left"
                    f"  •  {self.click_count} clicks")
            fg = COL_AMBER
        elif self.last_click_state == "lost":
            dot = COL_RED
            text = "Window not found — waiting for it…"
            fg = COL_RED
        elif self.last_click_state == "blocked":
            dot = COL_RED
            text = "Clicks blocked — try running as admin"
            fg = COL_RED
        else:
            dot = COL_GREEN if self._pulse_on else "#14532d"
            remaining = self.next_click_at - time.monotonic()
            text = (f"Next in {format_duration(remaining)}"
                    f"  •  {self.click_count} clicks")
            fg = COL_TEXT
        self.pulse.itemconfig(self.pulse_dot, fill=dot)
        self.status_label.config(text=text, fg=fg)

    def _toggle_pause(self):
        if self.paused:
            self.paused = False
            self.next_click_at = time.monotonic() + self.remaining_when_paused
            self.remaining_when_paused = None
            self.pause_button.config(text="⏸ Pause")
        else:
            self.paused = True
            self.remaining_when_paused = max(self.next_click_at - time.monotonic(), 0)
            self.pause_button.config(text="▶ Resume")
        self._update_status()

    def _restart(self):
        self.click_count = 0
        self.paused = False
        self.remaining_when_paused = None
        self.last_click_state = "ok"
        self.next_click_at = time.monotonic() + self.interval
        self.pause_button.config(text="⏸ Pause")
        self._update_status()

    def _stop(self):
        if self._tick_job is not None:
            self.root.after_cancel(self._tick_job)
            self._tick_job = None
        if self.bar is not None:
            self.bar.destroy()
            self.bar = None
        self.root.deiconify()
        self.root.lift()
        self._update_window_readout()
        self._draw_preview()
        self._hint(f"Stopped after {self.click_count} clicks.")

    def _quit(self):
        if self._tick_job is not None:
            self.root.after_cancel(self._tick_job)
        self.root.destroy()


def main():
    if IS_WINDOWS:
        set_dpi_aware()
    root = tk.Tk()
    if not IS_WINDOWS:
        root.withdraw()
        messagebox.showerror(APP_NAME, "This application only runs on Windows.")
        root.destroy()
        return
    try:
        icon = tk.PhotoImage(file=resource_path(os.path.join("assets", "icon.png")))
        root.iconphoto(True, icon)
        root._icon_image = icon   # keep a reference so tk doesn't drop it
    except Exception:
        pass
    AutoClickerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
