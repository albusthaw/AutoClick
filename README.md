# ⚡ AutoClicker

A small Windows app that keeps another application alive by clicking a spot **inside a window of your choice** at a fixed interval — silently, in the background, without ever touching your mouse.

Built for remote setups: run it on a VM and connect from a phone, iPad or PC at any resolution — the click keeps landing on the right spot.

## 📥 Download

**➡ [Download the latest `AutoClicker.exe` from Releases](https://github.com/albusthaw/AutoClick/releases/latest)**
(direct link: [`AutoClicker.exe`](https://github.com/albusthaw/AutoClick/releases/latest/download/AutoClicker.exe))

No installation — it's a single portable exe. Windows SmartScreen may warn on first launch because the exe is unsigned: choose **More info → Run anyway**.

Every push to the default branch automatically builds the exe and publishes it to [Releases](https://github.com/albusthaw/AutoClick/releases). Development builds for other branches are available as artifacts on the [Actions](https://github.com/albusthaw/AutoClick/actions) tab.

## ✨ Features

- 🪟 **Window-targeted** — pick the target window from a list; clicks are delivered to *that window only*
- 🫥 **True background clicking** — clicks are sent as window messages (`PostMessage`), so the mouse cursor never moves and you can keep working in other apps while it runs
- 📐 **Resolution-independent** — the click point is stored as a *percentage of the window*, recalculated at every click, so it adapts when the screen resolution or window size changes (RDP from phone/iPad/PC)
- 🎯 **Graphical point picking** — a translucent overlay appears over the target window; click the exact spot, watch the animated crosshair confirm it, and see it marked on a live mini-preview
- ⏱ **Flexible frequency** — every *N* seconds, minutes or hours
- 🎛 **Always-on-top control bar** while running — pause/resume, restart, stop, live countdown and click counter; draggable, and it pulls itself back on-screen after resolution changes
- 🔁 **Self-healing** — if the target window closes and reopens, it re-attaches by title automatically
- 💾 Settings (window, point, frequency, mode) are remembered between runs
- 🌙 Modern dark UI

## 🚀 How to use

1. Run `AutoClicker.exe`.
2. **Step 1 — Target window**: pick the app's window from the dropdown (press `↻` to refresh the list).
3. **Step 2 — Click point**: press **🎯 Pick point**. The target window comes to the front with a translucent blue overlay — click the exact spot you want auto-clicked. An animated crosshair flashes where you picked, and the point appears on the mini-preview. Use **👁 Show** to flash the marker again, and **🖱 Test click** to verify the click actually works.
4. **Step 3 — Frequency**: e.g. every `30 seconds`, `5 minutes` or `1 hours`.
5. Press **▶ Start clicking**. The window collapses into a slim always-on-top bar:
   - **⏸ Pause / ▶ Resume** — temporarily stop clicking
   - **↻ Restart** — reset the timer and click counter
   - **⏹ Stop** — return to the setup screen
   - a pulsing status dot with a live "next click" countdown and total clicks

## 🧠 How it works

**Resolution independence.** The click point is saved as a fraction of the target window's *client area* (e.g. "37% across, 62% down"), never as a pixel. Each click re-reads the window's current size and position, so the same relative spot gets clicked at any resolution, window size, or DPI — exactly what you need when a VM's resolution changes between phone, iPad and desktop RDP sessions.

**Background clicking.** In the default *Background* mode, clicks are posted directly to the target window (down to the exact child control under the point) as `WM_LBUTTONDOWN`/`WM_LBUTTONUP` messages. The physical cursor never moves, the target window doesn't need to be in front, and your own mouse/keyboard activity is untouched.

**Fallback mode.** A few apps ignore synthetic window messages (games with raw input, some elevated apps). For those, switch to *Real cursor* mode: it performs a physical click at the point and instantly restores your cursor to where it was. This mode briefly moves the mouse and clicks whatever is on top at that spot, so prefer Background mode when it works — verify with **Test click**.

### Limitations

| Situation | Behaviour |
|---|---|
| Target window closed | Bar shows "window not found"; re-attaches automatically when a window with the same title reappears |
| Target app runs as administrator | Windows blocks messages from normal apps (bar shows "blocked") — run AutoClicker as administrator too |
| Games using raw input / DirectInput | Background mode may be ignored — use *Real cursor* mode |
| Window minimized | Background clicks use the last known window size; some apps ignore clicks while minimized — keep the window restored (it can be behind other windows) |
| Locked / signed-out session | Windows delivers no input to a locked desktop — keep the VM session signed in |

## 🛠 Build it yourself

```bat
build.bat
```

Produces `dist\AutoClicker.exe`. Requires Python 3.9+ on Windows; the app itself is pure standard library (tkinter + ctypes), and only PyInstaller is needed for packaging. You can also run it directly with `python autoclicker.py`.

## 📦 Releases & versioning

- Every push to the default branch builds `AutoClicker.exe` and publishes it under a `v<version>` tag in [Releases](https://github.com/albusthaw/AutoClick/releases) (version comes from `APP_VERSION` in `autoclicker.py`).
- This README is updated with each release — changelog below.

## 📝 Changelog

### v2.0.0
- **Window-targeted clicking**: choose a target window; clicks go inside that window only
- **Background mode**: clicks are sent as window messages — the mouse cursor never moves, and your activity outside the window is not disturbed
- **Graphical click point picking**: translucent overlay over the target window + animated crosshair marker + live mini-preview of the window with the point marked
- **Visual overhaul**: modern dark theme, step cards, hover effects, pulsing status bar, dark title bar
- Auto re-attach when the target window closes and reopens
- Click method, window and point are remembered between runs
- Releases now ship `AutoClicker.exe` automatically

### v1.0.0
- Initial release: screen-percentage click location, configurable frequency (seconds/minutes/hours), always-on-top pause/restart/stop bar, exe build via GitHub Actions
