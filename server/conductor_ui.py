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
    python3 conductor_ui.py ocr                 # dump everything OCR sees
    python3 conductor_ui.py find "Chat Title"   # show the match + where it'd click
    python3 conductor_ui.py click "Chat Title"  # actually click that chat
    python3 conductor_ui.py send "Chat Title" "your message here"
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
# Optional composer click point "x,y" normalized (0..1) if auto-focus fails.
COMPOSER_XY = os.environ.get("CONDUCTOR_COMPOSER_XY", "").strip()
SUBMIT_KEY = os.environ.get("CONDUCTOR_SUBMIT_KEY", "enter").strip().lower()


def _lazy_pyautogui():
    import pyautogui  # imported lazily so the module loads without a display
    pyautogui.FAILSAFE = False
    return pyautogui


def activate_conductor() -> None:
    subprocess.run(["osascript", "-e", 'tell application "Conductor" to activate'],
                   check=False, timeout=10)


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


def open_chat_and_send(candidates, text: str) -> dict:
    """Activate Conductor, click the chat by any of its names, type + send.

    `candidates` is the chat title and/or its workspace/directory/branch names
    (e.g. "istanbul") — whatever Conductor shows in the sidebar.
    """
    if isinstance(candidates, str):
        candidates = [candidates]
    label = candidates[0] if candidates else "?"
    try:
        activate_conductor()
        time.sleep(0.7)
        items = screen_ocr()
        target = find_target(candidates, items)
        if not target:
            tried = ", ".join(repr(c) for c in candidates)
            return {"ok": False, "error": f"Couldn't find the chat on screen "
                    f"(looked for {tried}). Open Conductor so it's visible in the sidebar."}
        click_norm(target["x"], target["y"])
        time.sleep(0.7)
        type_and_send(text)
        return {"ok": True, "mode": "uiauto",
                "note": f"Typed into '{target.get('text', label)}' and pressed send."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# ---------------- self-test CLI ----------------
def _main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        return
    cmd = argv[0]
    if cmd == "ocr":
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
    elif cmd == "send" and len(argv) > 2:
        print(open_chat_and_send(argv[1], argv[2]))
    else:
        print(__doc__)


if __name__ == "__main__":
    _main(sys.argv[1:])
