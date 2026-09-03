"""Free UI-automation bridge to Conductor (no API token).

Drives the Conductor app by screen automation:
  1. OCR the screen (macOS Vision, via ocr.swift) to find a chat's title
  2. Click that chat in the sidebar
  3. Type a message into the composer and press send

This is a best-effort "hack" — Conductor's UI is a WKWebView invisible to the
accessibility API, so we navigate by reading the screen. It needs:
  * Accessibility permission  (to move the mouse / type)
  * Screen Recording permission (to screenshot for OCR)
both granted to whatever app runs this (Terminal / iTerm / the server).

Self-test on the Mac (see what it detects, without sending anything):
    python3 conductor_ui.py where                      # hover to read x,y of an icon
    python3 conductor_ui.py ocr                        # dump everything OCR sees
    python3 conductor_ui.py find "istanbul"            # show the sidebar match
    python3 conductor_ui.py ensure                      # launch full screen if closed
    python3 conductor_ui.py model "opus-4-8"            # pick a model in the composer
    python3 conductor_ui.py filter "vagent-backend-py" "istanbul" "your message"
    python3 conductor_ui.py send "istanbul" "your message" "vagent-backend-py"

Filter navigation (default): clicks the filter ICON, picks the project so all its
chats show, clicks the chat, sends, then clears the filter — it NEVER clicks a
project header (that would collapse an already-open project). The filter icon has
no text, so set its position once:

    python3 conductor_ui.py where     # hover over the funnel icon, read x,y
    # then in .env:
    CONDUCTOR_FILTER_ICON_XY=0.1362,0.2352   # the funnel/filter icon

Without CONDUCTOR_FILTER_ICON_XY it falls back to plain scrolling (also without
clicking any project header).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).parent
_OCR_SWIFT = _HERE / "ocr.swift"
_OCR_BIN = _HERE / ".ocr_bin"

# Only look for chat rows in the left part of the screen (the sidebar).
SIDEBAR_MAX_X = float(os.environ.get("CONDUCTOR_SIDEBAR_MAX_X", "0.40"))
# X position (fraction of width) to place the cursor over when scrolling.
SIDEBAR_SCROLL_X = float(os.environ.get("CONDUCTOR_SIDEBAR_X", "0.12"))
# Max scroll steps when hunting for an off-screen chat.
MAX_SCROLLS = int(os.environ.get("CONDUCTOR_MAX_SCROLLS", "12"))
# Navigation strategy: "filter" (click the filter icon → pick project → the
# chats show → click chat → clear filter) or "scroll" (just scroll the sidebar).
# Filter needs the icon coordinate below; it degrades to scroll if unset.
NAV_MODE = os.environ.get("CONDUCTOR_NAV_MODE", "filter").strip().lower()
# The filter (funnel) icon is an icon, not text, so OCR can't find it — give its
# position as "x,y" fractions of the screen (use: conductor_ui.py where).
FILTER_ICON_XY = os.environ.get("CONDUCTOR_FILTER_ICON_XY", "").strip()
# The filter panel has a "Repo" row (default value "All repos") — clicking it
# opens the project list. These labels are OCR text and rarely need changing.
REPO_ALL_LABEL = os.environ.get("CONDUCTOR_REPO_ALL_LABEL", "All repos")
# Optional composer click point "x,y" normalized (0..1) if auto-focus fails.
COMPOSER_XY = os.environ.get("CONDUCTOR_COMPOSER_XY", "").strip()
# The composer's model/agent selector is an icon OCR can't find, so give its
# position as "x,y" fractions (use: conductor_ui.py where) to enable picking a
# model on a new task. Without it, model selection is skipped (task uses the
# workspace's default model).
MODEL_PICKER_XY = os.environ.get("CONDUCTOR_MODEL_PICKER_XY", "").strip()
SUBMIT_KEY = os.environ.get("CONDUCTOR_SUBMIT_KEY", "enter").strip().lower()
# When Conductor is closed and we have to launch it, put it into macOS full
# screen so the sidebar has a stable, maximized layout for OCR. Only applies to a
# cold launch — if Conductor is already open we leave its windows as the user
# had them. Set to 0 to just launch it normally.
LAUNCH_FULLSCREEN = os.environ.get("CONDUCTOR_LAUNCH_FULLSCREEN", "1").strip().lower() not in ("0", "false", "no")
# Seconds to wait for Conductor's window to appear after a cold launch.
LAUNCH_TIMEOUT = float(os.environ.get("CONDUCTOR_LAUNCH_TIMEOUT", "12"))


def _lazy_pyautogui():
    import pyautogui  # imported lazily so the module loads without a display
    pyautogui.FAILSAFE = False
    return pyautogui


def activate_conductor() -> None:
    subprocess.run(["osascript", "-e", 'tell application "Conductor" to activate'],
                   check=False, timeout=10)


def conductor_running() -> bool:
    """True if the Conductor app currently has a running process."""
    try:
        r = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to (name of processes) contains "Conductor"'],
            capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "true"
    except Exception:  # noqa: BLE001
        return False


def _conductor_window_count() -> int:
    try:
        r = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to tell process "Conductor" to count windows'],
            capture_output=True, text=True, timeout=10)
        return int((r.stdout or "0").strip() or 0)
    except Exception:  # noqa: BLE001
        return 0


def _wait_for_window(timeout: float) -> bool:
    """Block until Conductor has at least one window on screen, or `timeout`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _conductor_window_count() > 0:
            return True
        time.sleep(0.4)
    return False


def _enter_fullscreen() -> bool:
    """Put Conductor's front window into macOS full screen.

    Tries the accessibility attribute (AXFullScreen) first; if the app doesn't
    expose it, falls back to the standard ⌃⌘F "Enter Full Screen" shortcut.
    """
    ax = (
        'tell application "System Events" to tell process "Conductor"\n'
        '  if (count of windows) is 0 then return "nowin"\n'
        '  try\n'
        '    if value of attribute "AXFullScreen" of window 1 is true then return "already"\n'
        '    set value of attribute "AXFullScreen" of window 1 to true\n'
        '    return "ok"\n'
        '  on error errm\n'
        '    return "err:" & errm\n'
        '  end try\n'
        'end tell'
    )
    try:
        r = subprocess.run(["osascript", "-e", ax], capture_output=True, text=True, timeout=10)
        if (r.stdout or "").strip() in ("ok", "already"):
            return True
    except Exception:  # noqa: BLE001
        pass
    # Fallback: the standard "Enter Full Screen" shortcut (needs Conductor front).
    try:
        subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to keystroke "f" using {control down, command down}'],
            check=False, timeout=10)
        return True
    except Exception:  # noqa: BLE001
        return False


def ensure_conductor(fullscreen: bool | None = None) -> None:
    """Make sure Conductor is open and frontmost before we automate it.

    If Conductor was closed, launch it, wait for its window to appear, and (by
    default) enter full screen so the sidebar layout is stable for OCR. If it was
    already running we just bring it forward and leave its windows untouched.
    """
    if fullscreen is None:
        fullscreen = LAUNCH_FULLSCREEN
    was_running = conductor_running()
    activate_conductor()          # `activate` also launches the app if it was closed
    if not was_running:
        _wait_for_window(LAUNCH_TIMEOUT)
        time.sleep(0.6)           # let the freshly opened UI settle
        if fullscreen:
            _enter_fullscreen()
            time.sleep(1.0)       # wait out the full-screen animation
    else:
        time.sleep(0.7)           # brief settle after bringing it forward


def _ensure_ocr_binary() -> list[str]:
    """Compile ocr.swift once for speed; fall back to interpreting it."""
    try:
        src_m = _OCR_SWIFT.stat().st_mtime
        if not _OCR_BIN.exists() or _OCR_BIN.stat().st_mtime < src_m:
            subprocess.run(["swiftc", str(_OCR_SWIFT), "-o", str(_OCR_BIN)],
                           check=True, timeout=120, capture_output=True)
        return [str(_OCR_BIN)]
    except Exception:  # noqa: BLE001 - swiftc missing/slow → interpret
        return ["swift", str(_OCR_SWIFT)]


def screen_ocr() -> list[dict]:
    """Screenshot the screen and OCR it.

    Capture uses the `screencapture` CLI (needs Screen Recording permission);
    OCR uses the Vision helper. Returns [{text, x, y, w, h}] normalized,
    top-origin.
    """
    shot = "/tmp/conductor_shot.png"
    cap = subprocess.run(["screencapture", "-x", shot], capture_output=True, text=True, timeout=15)
    if cap.returncode != 0 or not os.path.exists(shot):
        raise RuntimeError("screenshot failed — grant Screen Recording permission "
                           "to the app running this server.")
    cmd = _ensure_ocr_binary() + [shot]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or "OCR failed").strip())
    return json.loads(res.stdout or "[]")


def _norm(s: str) -> str:
    # Case-insensitive AND separator-insensitive: "Astana", "astana",
    # "porto-novo", "Porto Novo", "porto_novo" all collapse to one form.
    return "".join(ch for ch in s.lower() if ch.isalnum())


def find_target(candidates, items: list[dict]) -> dict | None:
    """Best sidebar OCR match for any of the candidate names.

    `candidates` may be a single string or a list (chat title, workspace/
    directory name like "istanbul", branch, etc.). We try them all and keep the
    single best-scoring on-screen match.
    """
    if isinstance(candidates, str):
        candidates = [candidates]
    best, best_score = None, 0.0
    for title in candidates:
        want = _norm(title)
        if not want:
            continue
        for it in items:
            if it["x"] > SIDEBAR_MAX_X:
                continue
            got = _norm(it.get("text", ""))
            if not got:
                continue
            if got == want:
                score = 1.0
            elif want.startswith(got) or got.startswith(want):
                score = 0.85 * min(len(got), len(want)) / max(len(got), len(want))
            elif want in got or got in want:
                score = 0.7 * min(len(got), len(want)) / max(len(got), len(want))
            else:
                continue
            score += (1.0 - it["y"]) * 0.05          # gently prefer higher rows
            if score > best_score:
                best, best_score = it, score
    return best


def click_norm(nx: float, ny: float) -> None:
    pg = _lazy_pyautogui()
    w, h = pg.size()
    pg.click(int(nx * w), int(ny * h))


def find_text(candidates, items: list[dict], max_x: float = 1.0) -> dict | None:
    """Like find_target but searches the whole screen (any x) — for controls
    such as the Filter icon or a project name in a filter popover."""
    if isinstance(candidates, str):
        candidates = [candidates]
    best, best_score = None, 0.0
    for title in candidates:
        want = _norm(title)
        if not want:
            continue
        for it in items:
            if it["x"] > max_x:
                continue
            got = _norm(it.get("text", ""))
            if not got:
                continue
            if got == want:
                score = 1.0
            elif want in got or got in want:
                score = 0.75 * min(len(got), len(want)) / max(len(got), len(want))
            else:
                continue
            if score > best_score:
                best, best_score = it, score
    return best


def _tap(candidates, max_x: float = 1.0) -> dict | None:
    """OCR the screen and click the best match for `candidates`, if found."""
    it = find_text(candidates, screen_ocr(), max_x)
    if it:
        click_norm(it["x"], it["y"])
        time.sleep(0.5)
    return it


def _scroll(amount: int) -> None:
    """Scroll the sidebar (positive = up, negative = down)."""
    pg = _lazy_pyautogui()
    w, h = pg.size()
    pg.moveTo(int(SIDEBAR_SCROLL_X * w), int(h * 0.5))
    pg.scroll(amount)


def scroll_find(candidates, click: bool = False) -> dict | None:
    """Scroll the sidebar from top to bottom, OCR at each step, and return (or
    click) the first matching row — so a chat need not already be on screen."""
    for _ in range(MAX_SCROLLS):          # jump to the top first
        _scroll(800)
    time.sleep(0.25)
    seen: set = set()
    for _ in range(MAX_SCROLLS * 2 + 1):
        items = screen_ocr()
        target = find_target(candidates, items)
        if target:
            if click:
                click_norm(target["x"], target["y"])
                time.sleep(0.6)
            return target
        # Stop if the visible sidebar text stops changing (reached the bottom).
        sig = tuple(_norm(it["text"]) for it in items if it["x"] < SIDEBAR_MAX_X)
        if sig and sig in seen:
            break
        seen.add(sig)
        _scroll(-400)
        time.sleep(0.3)
    return None


def type_and_send(text: str) -> None:
    pg = _lazy_pyautogui()
    if COMPOSER_XY:
        try:
            cx, cy = (float(v) for v in COMPOSER_XY.split(","))
            w, h = pg.size()
            pg.click(int(cx * w), int(cy * h))
            time.sleep(0.2)
        except Exception:  # noqa: BLE001
            pass
    pg.write(text, interval=0.01)
    time.sleep(0.15)
    if SUBMIT_KEY in ("cmd-enter", "cmd", "command"):
        pg.hotkey("command", "enter")
    else:
        pg.press("enter")


def _press_escape() -> None:
    """Dismiss an open menu/popover so we never leave the UI in a bad state."""
    try:
        _lazy_pyautogui().press("esc")
    except Exception:  # noqa: BLE001
        pass


def select_model(model: str, agent: str | None = None) -> dict:
    """Open the composer's model picker and choose `model` (best-effort).

    The new-task composer shows a model/agent selector; the deep link can't set
    a model, so we click it open and pick the requested model by its on-screen
    name. Needs CONDUCTOR_MODEL_PICKER_XY (the selector's position) since the
    control is an icon OCR can't locate on its own. Model-name matching is
    separator-insensitive, so "opus-4-8" matches an "Opus 4.8" menu row.

    Returns {"ok": True} on success, else {"ok": False, "error": "..."}.
    """
    if not model:
        return {"ok": False, "error": "no model given"}
    if not MODEL_PICKER_XY:
        return {"ok": False, "error": "model picker position not configured "
                "(set CONDUCTOR_MODEL_PICKER_XY)"}
    if not _click_xy_env(MODEL_PICKER_XY):        # open the model menu
        return {"ok": False, "error": "couldn't open the model picker"}
    time.sleep(0.5)
    # The menu lists model names as text — find + click ours anywhere on screen.
    it = find_text([model], screen_ocr())
    if not it:
        _press_escape()                           # leave the menu closed
        return {"ok": False, "error": f"'{model}' not found in the model picker"}
    click_norm(it["x"], it["y"])
    time.sleep(0.4)
    return {"ok": True, "model": it.get("text", model)}


def _click_xy_env(value: str) -> bool:
    """Click a normalized "x,y" screen point from config. Returns False if unset."""
    if not value:
        return False
    try:
        nx, ny = (float(v) for v in value.split(","))
        click_norm(nx, ny)
        time.sleep(0.4)
        return True
    except Exception:  # noqa: BLE001
        return False


def _clear_filter(project: str | None) -> None:
    """Reset the Repo filter back to 'All repos'."""
    try:
        if not _click_xy_env(FILTER_ICON_XY):   # open the filter panel
            return
        time.sleep(0.4)
        # The Repo dropdown now shows the project name; open it and pick All repos.
        if project:
            _tap([project])
            time.sleep(0.4)
        _tap([REPO_ALL_LABEL])
        time.sleep(0.3)
        _click_xy_env(FILTER_ICON_XY)           # close the panel
    except Exception:  # noqa: BLE001
        pass


def _open_chat_via_filter(project: str, chat_terms: list[str], text: str) -> dict:
    """filter icon → Repo dropdown → pick project → chats show → click chat →
    type + send → reset the filter. Never clicks a project header."""
    if not _click_xy_env(FILTER_ICON_XY):
        return {"ok": False, "error": "filter icon position not configured "
                "(set CONDUCTOR_FILTER_ICON_XY)"}
    time.sleep(0.5)
    # Open the Repo dropdown (shows "All repos" by default).
    if not _tap([REPO_ALL_LABEL]):
        _click_xy_env(FILTER_ICON_XY)           # close panel
        return {"ok": False, "error": f"Repo dropdown ('{REPO_ALL_LABEL}') not found"}
    time.sleep(0.5)
    # Pick the project from the repo list.
    if not _tap([project]):
        _click_xy_env(FILTER_ICON_XY)
        return {"ok": False, "error": f"project '{project}' not in the repo list"}
    time.sleep(0.5)
    _click_xy_env(FILTER_ICON_XY)               # close the panel so chats show
    time.sleep(0.5)
    # Now only this project's chats are listed — find + click the chat.
    target = scroll_find(chat_terms, click=True)
    if not target:
        _clear_filter(project)
        return {"ok": False, "error": "chat not found after filtering to project"}
    time.sleep(0.4)
    type_and_send(text)
    time.sleep(0.3)
    _clear_filter(project)
    return {"ok": True, "mode": "uiauto-filter",
            "note": f"Filtered to {project}, replied in '{target.get('text', chat_terms[0])}'."}


def _open_chat_via_scroll(chat_terms: list[str], text: str) -> dict:
    """Scroll the sidebar to the chat and click it — WITHOUT clicking any
    project header (clicking a project toggles it collapsed)."""
    target = scroll_find(chat_terms, click=True)
    if not target:
        tried = ", ".join(repr(c) for c in chat_terms)
        return {"ok": False, "error": "Couldn't find the chat in Conductor's "
                f"sidebar (looked for {tried}). Make sure its project is expanded, "
                "or set CONDUCTOR_FILTER_ICON_XY to use the filter."}
    type_and_send(text)
    return {"ok": True, "mode": "uiauto",
            "note": f"Opened '{target.get('text', chat_terms[0])}' and sent."}


def open_chat_and_send(nav, text: str) -> dict:
    """Activate Conductor, navigate to the chat, type + send.

    `nav` may be a dict from conductor.session_nav_info()
    ({project, workspace_terms, session_terms}), or a str/list of names.
    """
    if isinstance(nav, str):
        nav = {"workspace_terms": [nav]}
    elif isinstance(nav, list):
        nav = {"workspace_terms": nav}

    project = nav.get("project")
    chat_terms = (nav.get("workspace_terms") or []) + (nav.get("session_terms") or [])
    if not chat_terms:
        return {"ok": False, "error": "No chat name to search for."}

    try:
        ensure_conductor()   # launch (full screen) if it was closed, else focus
        # Use the filter flow only if we know the project AND have the icon coord.
        if NAV_MODE == "filter" and project and FILTER_ICON_XY:
            result = _open_chat_via_filter(project, chat_terms, text)
            if result["ok"]:
                return result
            # fall through to scrolling
        return _open_chat_via_scroll(chat_terms, text)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# ---------------- self-test CLI ----------------
def _main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        return
    cmd = argv[0]
    if cmd == "where":
        # Hover over a target (filter icon, the ✕) to read its x,y fraction.
        pg = _lazy_pyautogui()
        w, h = pg.size()
        print("Hover over the target; Ctrl-C to stop.")
        print("Put the printed x,y into CONDUCTOR_FILTER_ICON_XY.")
        try:
            while True:
                x, y = pg.position()
                print(f"  {x / w:.4f},{y / h:.4f}   (px {x},{y})   ", end="\r", flush=True)
                time.sleep(0.1)
        except KeyboardInterrupt:
            print()
    elif cmd == "ensure":
        # Launch Conductor full screen if it's closed, else just bring it forward.
        was = conductor_running()
        ensure_conductor()
        print(f"Conductor was {'running' if was else 'closed'} → "
              f"now {'focused' if was else 'launched full screen'}.")
    elif cmd == "ocr":
        for it in screen_ocr():
            print(f'{it["x"]:.3f},{it["y"]:.3f}  {it["text"]!r}')
    elif cmd == "find" and len(argv) > 1:
        items = screen_ocr()
        t = find_target(argv[1], items)
        print("match:", t if t else "NONE FOUND")
    elif cmd == "click" and len(argv) > 1:
        activate_conductor(); time.sleep(0.7)
        t = find_target(argv[1], screen_ocr())
        if not t: print("not found"); return
        print("clicking", t["text"]); click_norm(t["x"], t["y"])
    elif cmd == "tap" and len(argv) > 1:
        # test clicking a control anywhere on screen (e.g. the Filter icon)
        activate_conductor(); time.sleep(0.7)
        t = _tap([argv[1]])
        print("tapped", t["text"] if t else "NONE FOUND")
    elif cmd == "model" and len(argv) > 1:
        # test picking a model in the composer: model <model-id> [agent]
        activate_conductor(); time.sleep(0.7)
        print(select_model(argv[1], argv[2] if len(argv) > 2 else None))
    elif cmd == "filter" and len(argv) > 3:
        # test the full filter flow: filter <project> <chat> <message>
        activate_conductor(); time.sleep(0.7)
        print(_open_chat_via_filter(argv[1], [argv[2]], argv[3]))
    elif cmd == "send" and len(argv) > 2:
        # send <chat-or-nav> <message>; add a 3rd arg to set project for filter
        nav = {"project": argv[3], "workspace_terms": [argv[1]]} if len(argv) > 3 else argv[1]
        print(open_chat_and_send(nav, argv[2]))
    else:
        print(__doc__)


if __name__ == "__main__":
    _main(sys.argv[1:])
