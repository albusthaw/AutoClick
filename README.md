# AutoClicker

A small Windows app that clicks a chosen spot on the screen at a fixed interval — useful for keeping an application alive that would otherwise close or time out.

## Why it works when the screen resolution changes

The click location is stored as a **percentage of the screen** (e.g. "37% across, 62% down"), not as a fixed pixel. Every click converts that percentage to the *current* resolution using Windows' normalized input coordinates. So if you access your VM over RDP from a phone, iPad, or PC — each with a different resolution — the click still lands on the same relative spot.

> Note: the target app should scale with the screen the same way (e.g. a maximized window or fixed-position dialog). If the app is a floating window that stays the same pixel size, keep it maximized or anchored to a corner for best results.

## Usage

1. Run `AutoClicker.exe`.
2. **Set the click location**: press *Set location*, then move your mouse to the spot you want clicked and hold it there for the 5-second countdown. Use *Test click* to verify.
3. **Set the frequency**: e.g. every `30 seconds`, `5 minutes`, or `1 hours`.
4. Press **Start clicking**. The window collapses into a slim always-on-top bar with:
   - **⏸ Pause / ▶ Resume** — temporarily stop clicking
   - **↻ Restart** — reset the timer and click counter
   - **⏹ Stop** — go back to the setup screen
   - a live status showing the next click countdown and total clicks

The bar is draggable (grab the `⋮⋮` handle or the status text). Your location and frequency are remembered between runs (`%APPDATA%\AutoClicker\autoclicker.json`).

## Getting the exe

**Option A — download from GitHub Actions (no tools needed):**
Every push builds the exe automatically. Go to the repo's **Actions** tab → open the latest **Build Windows EXE** run → download the **AutoClicker-windows-exe** artifact and unzip it.

**Option B — build it yourself on Windows:**
```bat
build.bat
```
The exe appears at `dist\AutoClicker.exe`. (Requires Python 3.9+.)

**Option C — run without compiling:**
```bat
python autoclicker.py
```
No third-party packages needed — it's pure standard library.

## Notes

- Windows only (it uses the Win32 `SendInput` API).
- The VM session must stay logged in and unlocked for clicks to register. If you disconnect RDP, keep the session alive (don't sign out).
- Windows SmartScreen may warn about an unsigned exe the first time — choose "More info → Run anyway".
- The mouse cursor briefly jumps to the target for each click and is then restored to where it was.
