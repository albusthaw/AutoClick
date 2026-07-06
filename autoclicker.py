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
APP_VERSION = "2.0.0"

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
        self._tick_job = None
        self._drag_offset = None
        self._pulse_on = False

        self._build_styles()
        self._build_setup_window()
        self._refresh_windows()
        self._restore_saved_config()
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
                           "Clicks are sent straight to this window in the background —\n"
                           "your mouse stays free for everything else.")
        self.window_combo = ttk.Combobox(body1, state="readonly",
                                         style="Dark.TCombobox", font=(FONT, 10))
        self.window_combo.pack(side="left", fill="x", expand=True)
        self.window_combo.bind("<<ComboboxSelected>>", self._on_window_selected)
        refresh = pill_button(body1, "↻", COL_CARD_HI, COL_BORDER,
                              self._refresh_windows, fg=COL_TEXT, padx=12, pady=4)
        refresh.pack(side="left", padx=(8, 0))

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
                             ("cursor", "🖱 Real cursor (moves the mouse)")):
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

    def _refresh_windows(self):
        self.windows = list_windows(self._own_hwnds())
        self.window_combo["values"] = [truncate(t, 70) for _, t in self.windows]
        # keep / re-find current target after refresh
        for i, (hwnd, title) in enumerate(self.windows):
            if hwnd == self.target_hwnd or (
                    self.target_hwnd is None and title == self.target_title):
                self.window_combo.current(i)
                self.target_hwnd, self.target_title = hwnd, title
                break
        else:
            self.window_combo.set("")
            self.target_hwnd = None
        self._draw_preview()

    def _on_window_selected(self, _event=None):
        i = self.window_combo.current()
        if 0 <= i < len(self.windows):
            self.target_hwnd, self.target_title = self.windows[i]
            self.cached_client_size = None
            geom = get_client_geometry(self.target_hwnd)
            if geom:
                self.cached_client_size = (geom[2], geom[3])
            save_config(self._current_config())
            self._draw_preview()
            self._hint("Window selected. Now pick the click point.")

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
            c.create_text(CW // 2, CH // 2, text="Select a window above",
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
            geom = self._target_geometry()
            if geom is None:
                return "lost"
            sx, sy, w, h = geom
            fx, fy = self.fraction
            cursor_click_at(sx + round(fx * (w - 1)), sy + round(fy * (h - 1)))
            return "ok"
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
            self._refresh_windows()   # auto-reselect if that window is open

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
    AutoClickerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
