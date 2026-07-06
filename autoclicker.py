#!/usr/bin/env python3
"""AutoClicker - resolution-independent auto clicker for Windows.

Keeps an application alive by clicking a chosen spot at a fixed interval.
The click target is stored as a percentage of the screen rather than in
pixels, so the same spot keeps getting clicked when the screen resolution
changes (e.g. when the VM is accessed over RDP from a phone, iPad or PC).
"""

import ctypes
import json
import os
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

IS_WINDOWS = sys.platform == "win32"

APP_NAME = "AutoClicker"
CAPTURE_COUNTDOWN_SECONDS = 5
MIN_INTERVAL_SECONDS = 0.2
TICK_MS = 200

UNIT_SECONDS = {"seconds": 1, "minutes": 60, "hours": 3600}

# ---------------------------------------------------------------------------
# Win32 input plumbing (SendInput with normalized absolute coordinates).
# Coordinates passed with MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK are
# normalized to a 0..65535 grid over the whole virtual desktop, so a stored
# fraction of the screen maps to the same relative spot at any resolution.
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


def set_dpi_aware():
    """Opt in to per-monitor DPI awareness so cursor coordinates are real pixels."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_virtual_screen():
    """Return (x, y, width, height) of the virtual desktop in pixels."""
    u = ctypes.windll.user32
    return (
        u.GetSystemMetrics(SM_XVIRTUALSCREEN),
        u.GetSystemMetrics(SM_YVIRTUALSCREEN),
        max(u.GetSystemMetrics(SM_CXVIRTUALSCREEN), 1),
        max(u.GetSystemMetrics(SM_CYVIRTUALSCREEN), 1),
    )


def get_cursor_pos():
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def cursor_to_fraction():
    """Current cursor position as a fraction (0..1) of the virtual desktop."""
    x, y = get_cursor_pos()
    vx, vy, vw, vh = get_virtual_screen()
    fx = (x - vx) / max(vw - 1, 1)
    fy = (y - vy) / max(vh - 1, 1)
    return min(max(fx, 0.0), 1.0), min(max(fy, 0.0), 1.0)


def fraction_to_pixels(fx, fy):
    """Where a stored fraction lands in pixels at the current resolution."""
    vx, vy, vw, vh = get_virtual_screen()
    return vx + round(fx * (vw - 1)), vy + round(fy * (vh - 1))


def _send_mouse(flags, nx=0, ny=0):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(nx, ny, 0, flags, 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def click_at_fraction(fx, fy, restore_cursor=True):
    """Left-click at a screen fraction; resolution is resolved at click time."""
    old = get_cursor_pos() if restore_cursor else None
    nx = round(fx * 65535)
    ny = round(fy * 65535)
    move = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    _send_mouse(move, nx, ny)
    time.sleep(0.01)
    _send_mouse(move | MOUSEEVENTF_LEFTDOWN, nx, ny)
    time.sleep(0.01)
    _send_mouse(move | MOUSEEVENTF_LEFTUP, nx, ny)
    if old is not None:
        time.sleep(0.03)
        ctypes.windll.user32.SetCursorPos(old[0], old[1])


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
# GUI
# ---------------------------------------------------------------------------

BAR_BG = "#1f2430"
BAR_FG = "#e8eaf0"
ACCENT = "#4f8cff"
GREEN = "#2ecc71"
YELLOW = "#f1c40f"
RED = "#e74c3c"


def format_duration(seconds):
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


class AutoClickerApp:
    def __init__(self, root):
        self.root = root
        self.fraction = None          # (fx, fy) click target as screen fraction
        self.interval = None          # seconds between clicks
        self.click_count = 0
        self.paused = False
        self.next_click_at = None     # time.monotonic() deadline
        self.remaining_when_paused = None
        self.bar = None
        self._tick_job = None
        self._capture_job = None
        self._drag_offset = None

        self._build_setup_window()
        self._restore_saved_config()

    # ---------------- Setup window ----------------

    def _build_setup_window(self):
        self.root.title(APP_NAME)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

        outer = ttk.Frame(self.root, padding=16)
        outer.grid(sticky="nsew")

        ttk.Label(outer, text="Auto Clicker", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=2, pady=(0, 2), sticky="w")
        ttk.Label(
            outer,
            text="Clicks a chosen spot on a timer to keep an app alive.\n"
                 "The spot is remembered as a % of the screen, so it still\n"
                 "works when the resolution changes (RDP from phone/iPad/PC).",
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=2, pady=(0, 12), sticky="w")

        # --- Step 1: location ---
        loc = ttk.LabelFrame(outer, text=" 1. Click location ", padding=12)
        loc.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        loc.columnconfigure(0, weight=1)

        self.location_label = ttk.Label(loc, text="Not set yet", font=("Segoe UI", 10, "bold"))
        self.location_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self.capture_button = ttk.Button(
            loc, text=f"Set location ({CAPTURE_COUNTDOWN_SECONDS}s countdown)",
            command=self._start_capture)
        self.capture_button.grid(row=1, column=0, sticky="ew", padx=(0, 6))

        self.test_button = ttk.Button(loc, text="Test click", command=self._test_click)
        self.test_button.grid(row=1, column=1, sticky="ew")

        ttk.Label(
            loc,
            text="Press the button, then move the mouse to the target\n"
                 "and hold it there until the countdown ends.",
            foreground="#555555",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # --- Step 2: frequency ---
        freq = ttk.LabelFrame(outer, text=" 2. Click frequency ", padding=12)
        freq.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        ttk.Label(freq, text="Click every").grid(row=0, column=0, padx=(0, 6))
        self.value_var = tk.StringVar(value="30")
        self.value_entry = ttk.Entry(freq, textvariable=self.value_var, width=8, justify="center")
        self.value_entry.grid(row=0, column=1, padx=(0, 6))

        self.unit_var = tk.StringVar(value="seconds")
        self.unit_combo = ttk.Combobox(
            freq, textvariable=self.unit_var, state="readonly",
            values=list(UNIT_SECONDS.keys()), width=10)
        self.unit_combo.grid(row=0, column=2)

        # --- Step 3: start ---
        self.start_button = tk.Button(
            outer, text="▶  Start clicking", font=("Segoe UI", 12, "bold"),
            bg=GREEN, fg="white", activebackground="#27ae60", activeforeground="white",
            relief="flat", pady=8, cursor="hand2", command=self._start_clicking)
        self.start_button.grid(row=4, column=0, columnspan=2, sticky="ew")

        self.hint_label = ttk.Label(outer, text="", foreground="#555555")
        self.hint_label.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _restore_saved_config(self):
        cfg = load_config()
        if "fx" in cfg and "fy" in cfg:
            self.fraction = (float(cfg["fx"]), float(cfg["fy"]))
            self._update_location_label()
        if "value" in cfg:
            self.value_var.set(str(cfg["value"]))
        if cfg.get("unit") in UNIT_SECONDS:
            self.unit_var.set(cfg["unit"])

    def _update_location_label(self):
        if self.fraction is None:
            self.location_label.config(text="Not set yet")
            return
        fx, fy = self.fraction
        px, py = fraction_to_pixels(fx, fy)
        self.location_label.config(
            text=f"{fx * 100:.1f}% across, {fy * 100:.1f}% down"
                 f"   (pixel {px}, {py} at current resolution)")

    # ---------------- Location capture ----------------

    def _start_capture(self):
        if self._capture_job is not None:
            return
        self.capture_button.state(["disabled"])
        self._capture_countdown(CAPTURE_COUNTDOWN_SECONDS)

    def _capture_countdown(self, seconds_left):
        if seconds_left > 0:
            self.capture_button.config(
                text=f"Move mouse to target… capturing in {seconds_left}")
            self._capture_job = self.root.after(
                1000, self._capture_countdown, seconds_left - 1)
            return
        self._capture_job = None
        self.fraction = cursor_to_fraction()
        save_config(self._current_config())
        self.capture_button.config(
            text=f"Set location ({CAPTURE_COUNTDOWN_SECONDS}s countdown)")
        self.capture_button.state(["!disabled"])
        self._update_location_label()
        self.hint_label.config(text="Location captured. Use Test click to verify it.")

    def _test_click(self):
        if self.fraction is None:
            messagebox.showwarning(APP_NAME, "Set the click location first.")
            return
        click_at_fraction(*self.fraction)
        self.hint_label.config(text="Test click sent.")

    # ---------------- Start / validation ----------------

    def _current_config(self):
        cfg = {"value": self.value_var.get(), "unit": self.unit_var.get()}
        if self.fraction is not None:
            cfg["fx"], cfg["fy"] = self.fraction
        return cfg

    def _read_interval(self):
        try:
            value = float(self.value_var.get())
        except ValueError:
            return None
        if value <= 0:
            return None
        return value * UNIT_SECONDS[self.unit_var.get()]

    def _start_clicking(self):
        if self.fraction is None:
            messagebox.showwarning(APP_NAME, "Set the click location first (step 1).")
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
        bar.configure(bg=BAR_BG)

        frame = tk.Frame(bar, bg=BAR_BG, padx=10, pady=5)
        frame.pack()

        grip = tk.Label(frame, text="⋮⋮", bg=BAR_BG, fg="#5a6275",
                        font=("Segoe UI", 10))
        grip.pack(side="left", padx=(0, 8))

        self.status_label = tk.Label(frame, text="", bg=BAR_BG, fg=BAR_FG,
                                     font=("Segoe UI", 10, "bold"), width=32, anchor="w")
        self.status_label.pack(side="left", padx=(0, 10))

        def bar_button(text, color, command):
            return tk.Button(
                frame, text=text, command=command, bg=color, fg="white",
                activebackground=color, activeforeground="white",
                relief="flat", font=("Segoe UI", 9, "bold"),
                padx=10, pady=2, cursor="hand2", borderwidth=0)

        self.pause_button = bar_button("⏸ Pause", YELLOW, self._toggle_pause)
        self.pause_button.config(fg="black", activeforeground="black")
        self.pause_button.pack(side="left", padx=3)

        self.restart_button = bar_button("↻ Restart", ACCENT, self._restart)
        self.restart_button.pack(side="left", padx=3)

        self.stop_button = bar_button("⏹ Stop", RED, self._stop)
        self.stop_button.pack(side="left", padx=3)

        for widget in (frame, grip, self.status_label):
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
            click_at_fraction(*self.fraction)
            self.click_count += 1
            # schedule from "now" so a slow tick can't cause a burst of clicks
            self.next_click_at = time.monotonic() + self.interval
        self._update_status()
        self._keep_bar_on_screen()
        self._schedule_tick()

    def _update_status(self):
        if self.paused:
            text = (f"⏸ Paused — {format_duration(self.remaining_when_paused)} left"
                    f"  •  {self.click_count} clicks")
            self.status_label.config(text=text, fg=YELLOW)
        else:
            remaining = self.next_click_at - time.monotonic()
            text = (f"● Next click in {format_duration(remaining)}"
                    f"  •  {self.click_count} clicks")
            self.status_label.config(text=text, fg=BAR_FG)

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
        self._update_location_label()
        self.hint_label.config(
            text=f"Stopped after {self.click_count} clicks.")

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
