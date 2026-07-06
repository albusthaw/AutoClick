# ⚡ AutoClicker

A small Windows app that keeps another application alive by clicking a spot **inside a window of your choice** at a fixed interval — silently, in the background, without ever touching your mouse.

Built for remote setups: run it on a VM and connect from a phone, iPad or PC at any resolution — the click keeps landing on the right spot. Works with remote-desktop client windows too (RDP, **Omnissa Horizon**, Citrix), including nested sessions (a Horizon window inside an RDP session).

## 📥 Download

**➡ [Download the latest release](https://github.com/albusthaw/AutoClick/releases/latest)**

| File | What it is |
|---|---|
| [`AutoClicker.exe`](https://github.com/albusthaw/AutoClick/releases/latest/download/AutoClicker.exe) | Single portable exe — just run it |
| `AutoClicker-v*-portable.zip` | Same app as a folder — extract and run `AutoClicker\AutoClicker.exe`. Use this if your browser or antivirus blocks the bare exe |

### ⚠ "Windows protected your PC" / antivirus warnings

This is an unsigned open-source tool (code-signing certificates cost hundreds of dollars a year), so Windows treats it as an unknown publisher. The exe embeds proper version/publisher metadata and an icon to help reputation, but you may still see a warning the first time:

- **SmartScreen prompt** → click *More info* → *Run anyway*
- **Browser flags the download** → keep it (Chrome/Edge: Downloads → ⋯ → *Keep*), or download the **portable .zip** instead — archives are flagged far less often
- **File won't run after download** → right-click → *Properties* → check *Unblock* → OK
- **Defender quarantines it** → Windows Security → *Protection history* → *Allow on device*, or add an exclusion for the folder

You can always audit the code (it's one Python file) and build the exe yourself with `build.bat`.

**If Defender names a specific threat** (typically `Wacatac`/`Wacapew` with an `!ml` suffix — meaning "machine-learning guess", not an actual signature match): that's a false positive you can help clear for everyone. Submit the file at [Microsoft's false-positive portal](https://www.microsoft.com/en-us/wdsi/filesubmission) (choose *Software developer* → *Incorrectly detected*). Microsoft usually re-classifies within 1–3 days, which whitelists that exact file globally.

**What the app does and doesn't do** (auditable in `autoclicker.py`): it simulates mouse clicks (`SendInput`/`PostMessage`), lists window titles for the picker, and stores its settings in `%APPDATA%\AutoClicker`. It contains **no** networking, no keyboard capture or hooks, no process injection, no registry access, and no autostart — the flag comes from "simulates input + unsigned + Python-packed exe" pattern-matching, not from any actual behavior.

## ✨ Features

- 🔎 **Smart Find (visual anchoring)** — instead of clicking blindly at a saved coordinate, AutoClicker remembers what the target *looks like* and finds it in the window before clicking, searching across sizes so it **keeps working after you resize the Horizon/Citrix window**. If it can't find the target confidently, it **skips rather than misclicking**
- 🪟 **Graphical window picker** — choose the target from a grid of **live window previews** (like the Windows taskbar previews), not a text list
- 🎯 **Multiple click areas** — pick up to 5 points in one go; they're clicked one per interval, **in the order you picked them (looping)** or **randomly**
- 🕊 **Idle-aware clicking** — in real-cursor mode the app waits until *you* haven't touched the mouse/keyboard for a few seconds before clicking, so it never interrupts your work (a due click is never held more than 90 s, so keep-alive still keeps alive)
- 🫥 **True background clicking** — clicks are sent as window messages, so the mouse cursor never moves and you can keep working in other apps while it runs
- 🖱 **Real-cursor mode for remote-desktop windows** — RDP / Omnissa Horizon / Citrix windows only forward *real* input; this mode clicks physically, then instantly restores your cursor and gives focus back to the window you were using. Remote-client windows are detected automatically and the right mode is pre-selected
- 📐 **Resolution-independent** — the click point is stored as a *percentage of the window*, recalculated at every click, so it adapts when the screen resolution or window size changes (RDP from phone/iPad/PC)
- 🎯 **Graphical point picking** — a translucent overlay appears over the target window; click the exact spot, watch the animated crosshair confirm it, and see it marked on a live mini-preview
- ⏱ **Flexible frequency** — every *N* seconds, minutes or hours
- 🎛 **Always-on-top control bar** while running — pause/resume, restart, stop, live countdown and click counter; draggable, and it pulls itself back on-screen after resolution changes
- 🔁 **Self-healing** — if the target window closes and reopens, it re-attaches by title automatically
- 💾 Settings (window, point, frequency, mode) are remembered between runs
- 🌙 Modern dark UI

## 🚀 How to use

1. Run `AutoClicker.exe`.
2. **Step 1 — Target window**: press **🪟 Choose…** and click the window in the live-preview grid.
3. **Step 2 — Click points**: press **🎯 Pick points**. The target window comes to the front with a translucent blue overlay — click up to **5 spots** in the order you want them clicked (right-click or Enter when done, Esc to cancel). The points appear numbered on the mini-preview. Choose **In order (loop)** or **Random** for how they advance — each interval clicks *one* point, then moves to the next.
   - **🔎 Smart Find** (recommended for Horizon/Citrix, on by default): when you pick each point, AutoClicker also snapshots a small picture around it. At click time it locates that picture in the window — so clicks stay accurate even after you resize the remote window. Pick points on something *visually distinctive* (a button, an icon, text) rather than a blank area, or Smart Find can't anchor to it and that point falls back to percentage-based clicking.
4. **Test it**: press **🖱 Test click**. With Smart Find on, it reports the match confidence per point ("Found & clicked 92% ✓" or "Could NOT find — would skip"). In plain background mode it instead asks whether the click registered — if not (typical for remote-desktop windows), it switches to Real cursor mode automatically.
5. **Step 3 — Frequency**: e.g. every `30 seconds`, `5 minutes` or `1 hours`.
6. Press **▶ Start clicking**. The window collapses into a slim always-on-top bar:
   - **⏸ Pause / ▶ Resume** — temporarily stop clicking
   - **↻ Restart** — reset the timer and click counter
   - **⏹ Stop** — return to the setup screen
   - a pulsing status dot with a live "next click" countdown and total clicks

## 🧠 How it works

**Smart Find (visual anchoring) — the fix for resize misclicks.** Percentage-based clicking assumes the window's content scales linearly with the window. Remote-desktop clients break that assumption: when you resize a Horizon/Citrix window, the remote image inside it gets **letterboxed, scaled non-linearly, or panned**, so "50% across the client area" stops pointing at the same remote pixel — and you get clicks landing in the wrong place. Smart Find solves this by *recognizing the target visually*:

1. When you pick a point, a small grayscale patch around it is captured and saved (in `%APPDATA%\AutoClicker`, base64 in the config).
2. Before each click, AutoClicker screenshots the window's client area and runs **multi-scale normalized cross-correlation** to locate that patch — trying a range of sizes (0.5×–1.6×) so the target is found even after the window (and thus the rendered content) is resized.
3. It clicks the *found* location. If the best match confidence is below ~78%, it **does not click at all** — a skipped keep-alive is always better than a click in the wrong place. The control bar shows "target not found — skipped" so you know.

Matching runs on a background thread (so the control bar stays responsive) and only every interval, so the cost is negligible. It needs a *visually distinctive* target; a blank area has nothing to anchor to and automatically falls back to percentage mode.

**Resolution independence (percentage mode).** When Smart Find is off (or the target isn't distinctive), the click point is saved as a fraction of the target window's *client area* (e.g. "37% across, 62% down"), never as a pixel. Each click re-reads the window's current size and position, so the same relative spot gets clicked at any resolution, window size, or DPI. This works well for **normal application windows** and for remote windows in a simple stretch/fit display mode; it's the case that drifts when a remote client letterboxes or pans — which is exactly what Smart Find is for.

**Background mode.** Clicks are posted directly to the target window (down to the exact child control under the point) as `WM_LBUTTONDOWN`/`WM_LBUTTONUP` messages. The physical cursor never moves, the target window doesn't need to be in front, and your own mouse/keyboard activity is untouched. Works for most normal applications.

**Real cursor mode — for remote-desktop windows.** Clients like RDP (`mstsc`), Omnissa/VMware Horizon and Citrix don't act on posted messages: they capture *real* input events and forward them into the remote session. For these windows AutoClicker performs a genuine click, engineered to interfere as little as possible:

1. If something covers the click point, the target window is raised first (otherwise it isn't touched).
2. The click is sent with hardware-level input at the exact spot — this is what gets forwarded into the remote session (even nested ones, e.g. Horizon inside RDP).
3. Your cursor is restored to where it was within ~50 ms.
4. If a different window had focus before, focus is handed back to it.

AutoClicker detects remote-client windows by name/class and pre-selects this mode for them; the **Test click** confirmation flow catches any app it doesn't know about.

### Can clicks into a remote-desktop window ever be truly silent?

Short answer: **not from outside the session** — and any tool claiming otherwise is fighting Windows physics. Every injection path was reviewed for this app:

| Approach | Result |
|---|---|
| Posted window messages (`PostMessage`/`SendMessage`) | Ignored — remote clients read **raw input**, not messages (this is AutoClicker's Background mode; great for normal apps) |
| UI Automation (`InvokePattern`) | The remote session is a video stream — there are no UI elements to invoke |
| Journal playback hooks | Disabled by Windows since Vista for security |
| Synthetic touch/pen injection (`InjectSyntheticPointerInput`) | Still real input: activates the window and steals focus — same interference, less compatibility |
| Real cursor click (`SendInput`) | **The only thing remote clients forward** — so AutoClicker makes it as gentle as possible |

What AutoClicker does to make real-cursor clicks barely noticeable: **idle-aware timing** (waits until you're not using mouse/keyboard), raise-only-if-covered with **z-order restore**, **cursor restore** in ~50 ms, and **focus give-back** to the window you were using.

💡 **The one truly silent setup**: run AutoClicker *inside* the remote session (copy the exe into the Horizon/RDP desktop and target the actual application window there). Inside the session the target is a real app — Background mode works, nothing on your outer desktop is touched, and it keeps clicking even while you're disconnected (as long as the session stays signed in).

### Limitations

| Situation | Behaviour |
|---|---|
| Target window closed | Bar shows "window not found"; re-attaches automatically when a window with the same title reappears |
| Target app runs as administrator | Windows blocks messages from normal apps (bar shows "blocked") — run AutoClicker as administrator too |
| Remote-desktop / games with raw input | Background mode is ignored — use *Real cursor* mode (auto-detected for known clients) |
| Real-cursor mode while you're typing/clicking | The cursor teleports to the target for ~50 ms per click, then returns; focus is restored. Brief, but not invisible |
| Smart Find target is a blank/uniform area | Nothing to recognize — that point automatically falls back to percentage-based clicking (pick a button/icon/text instead) |
| Control bar sits over the click point | In real-cursor mode the click could hit the bar — drag the bar away from the target area |
| Remote window fully hidden/minimized at click time | Screenshot can't see the target → Smart Find skips that click (no misclick) until it's visible again |
| Window minimized | Background clicks use the last known window size; some apps ignore clicks while minimized — keep the window restored (it can be behind other windows) |
| Locked / signed-out session | Windows delivers no input to a locked desktop — keep the VM session signed in |

## 🛠 Build it yourself

```bat
build.bat
```

Produces `dist\AutoClicker.exe`. Requires Python 3.9+ on Windows. The app uses tkinter + ctypes (standard library) plus **numpy** for Smart Find's image matching; `build.bat` installs numpy and PyInstaller for you. The icon and Windows version resource are generated by `build_assets.py` (pure stdlib). You can also run the app directly with `python autoclicker.py` (with numpy installed; without it, everything works except Smart Find).

## 📦 Releases & versioning

- Every push to the default branch builds the exe + portable zip and publishes them under a `v<version>` tag in [Releases](https://github.com/albusthaw/AutoClick/releases) (version comes from `APP_VERSION` in `autoclicker.py`).
- This README is updated with each release — changelog below.

## 📝 Changelog

### v2.3.0
- **Smart Find (visual anchoring)** — the fix for misclicks after resizing a Horizon/Citrix window. AutoClicker now captures a picture of each target when you pick it and locates it visually before clicking (multi-scale normalized cross-correlation on a background thread), so clicks track the target across window resizing/scaling. Below ~78% confidence it skips instead of misclicking; featureless targets fall back to percentage mode automatically. Per-point confidence is shown in Test click and the control bar. Adds a numpy dependency (bundled in the exe)
- Click delivery refactored to support located coordinates in both Background and Real-cursor modes; templates and the Smart Find setting persist between runs

### v2.2.0
- **Multiple click areas**: pick up to 5 points in one overlay session (numbered markers); one point is clicked per interval, advancing **in order with a loop** or **randomly** — works in both Background and Real-cursor modes
- **Idle-aware clicking (🕊)**: real-cursor clicks wait until you haven't touched mouse/keyboard for ~3 s (capped at 90 s so keep-alive isn't starved); the control bar shows "waiting until you're idle"; the app's own injected clicks don't count as activity
- **Less intrusive real-cursor clicks**: focus is now *always* returned to the window you were using, and when the target had to be raised, its z-order position is restored afterwards
- Documented the full review of silent-click approaches and the run-inside-the-session setup for truly invisible clicking

### v2.1.1
- Antivirus-review release: removed the `AttachThreadInput` focus-restore workaround — the one API pattern in the app strongly associated with malware. Focus restore now uses plain `SetForegroundWindow` only (may occasionally be refused by Windows; clicking is unaffected)
- Documented the app's full API surface and the Microsoft false-positive submission process in the README

### v2.1.0
- **Remote-desktop support**: Real-cursor mode reworked for RDP / Omnissa Horizon / Citrix windows (incl. nested sessions like Horizon inside RDP) — raises the window only when covered, clicks with hardware input, restores cursor and gives focus back to what you were doing
- **Auto-detection** of remote-client windows — the right click mode is pre-selected
- **Test click verification**: after a background-mode test, the app asks whether the click registered and switches modes automatically if not
- **Graphical window picker**: choose the target from a grid of live window previews instead of a text dropdown
- App icon + embedded Windows version/publisher metadata (improves SmartScreen/antivirus reputation), and a **portable .zip** release variant for downloads that browsers block
- README: added unblock/quarantine guidance

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
