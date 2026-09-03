"""Mac remote-control WebSocket server.

Flow:
  1. On startup, generate a fresh 6-digit auth code and email it to you.
  2. A client (web terminal, CLI, or the iOS app) connects over Tailscale and
     sends the code.
  3. Once authenticated the client can:
       - run shell commands:  CMD:ls -la        -> returns combined output
       - drive the Mac's UI:   NEW_CHAT / TYPE:<text> / NEXT_CHAT / PREV_CHAT
     Each connection keeps its own working directory, so `cd foo` then `ls`
     behaves like a real shell session.

Config comes from a `.env` file (see .env.example). Button coordinates come
from a JSON file (see coordinates.example.json).
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import shlex
import smtplib
import ssl
import subprocess
import time
from email.message import EmailMessage
from pathlib import Path

import websockets
from dotenv import load_dotenv

# Load .env BEFORE importing local modules: auth/conductor/conductor_ui read
# configuration (SMTP creds, the email allowlist, Conductor paths, calibration
# coordinates) from the environment at import time.
load_dotenv()

import auth
import conductor as cdt
import conductor_ui as cui

# pyautogui is only needed for the UI-clicking commands and requires a GUI
# session + Accessibility permission. Make it optional so the shell/terminal
# features work even in a headless or unprivileged environment.
try:
    import pyautogui

    pyautogui.PAUSE = 0.1
    pyautogui.FAILSAFE = True
    _PYAUTOGUI_ERR = None
except Exception as exc:  # noqa: BLE001 - any import/display failure disables UI
    pyautogui = None
    _PYAUTOGUI_ERR = exc


class _NeverRaised(Exception):
    """Placeholder so `except FailSafe` is valid when pyautogui is absent."""


_FailSafe = pyautogui.FailSafeException if pyautogui else _NeverRaised

# --- Configuration (from environment / .env) ---
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", EMAIL_SENDER)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))

HOST_IP = os.environ.get("HOST_IP", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8765"))
MAX_AUTH_ATTEMPTS = int(os.environ.get("MAX_AUTH_ATTEMPTS", "5"))
COORDINATES_FILE = os.environ.get("COORDINATES_FILE", "coordinates.json")

# Legacy shared auth code: a single fixed/random code, delivered via the connect
# URL. Kept as a fallback so the printed connect URL still works; the primary
# path is now per-user email sign-in (see auth.py). Disable with
# AUTH_LEGACY_CODE=0 to require email sign-in for everyone.
_ENV_CODE = os.environ.get("AUTH_CODE", "").strip()
AUTH_CODE = _ENV_CODE if _ENV_CODE else f"{random.randint(0, 999999):06d}"
LEGACY_CODE_ENABLED = os.environ.get("AUTH_LEGACY_CODE", "1").strip().lower() not in ("0", "false", "no")

# Sentinel used to smuggle the post-command working directory back out of the
# subshell so `cd` persists across commands.
_CWD_MARK = "__CWD__:"


def load_coordinates() -> dict[str, tuple[int, int]]:
    path = Path(__file__).parent / COORDINATES_FILE
    if not path.exists():
        print(f"[warn] {path} not found. Run calibrate.py and create it.")
        print("       Falling back to example coordinates (probably wrong).")
        path = Path(__file__).parent / "coordinates.example.json"
    with open(path) as f:
        raw = json.load(f)
    return {key: (int(x), int(y)) for key, (x, y) in raw.items()}


COORDS = load_coordinates()


def send_email_code() -> bool:
    """Email the auth code. Returns True on send, False if not configured."""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        return False
    try:
        msg = EmailMessage()
        msg.set_content(f"Your Mac remote control code is: {AUTH_CODE}")
        msg["Subject"] = "Remote Control Auth Code"
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
            smtp.send_message(msg)
        print(f"Auth code emailed to {EMAIL_RECEIVER}.")
        return True
    except Exception as exc:  # noqa: BLE001 - bad creds / no network
        print(f"[warn] Email send failed: {exc}")
        return False


def deliver_code() -> None:
    """Email the code if configured, and always print it on the Mac terminal."""
    sent_email = send_email_code()
    if not sent_email:
        print("=" * 52)
        print("  No delivery configured (email) — read the code below.")
    print("=" * 52)
    print(f"  AUTH CODE: {AUTH_CODE}")
    print("=" * 52)


_UI_VERBS = ("NEW_CHAT", "NEXT_CHAT", "PREV_CHAT", "TYPE:")


def run_ui_command(message: str) -> str | None:
    """Handle pyautogui UI commands. Returns None if not a UI command."""
    if pyautogui is None:
        if message.startswith(_UI_VERBS):
            return f"UI control unavailable (pyautogui not loaded: {_PYAUTOGUI_ERR})"
        return None
    if message == "NEW_CHAT":
        pyautogui.click(*COORDS["new_chat"])
        return "Executed: New Chat"
    if message == "NEXT_CHAT" and "next_chat" in COORDS:
        pyautogui.click(*COORDS["next_chat"])
        return "Executed: Next Chat"
    if message == "PREV_CHAT" and "prev_chat" in COORDS:
        pyautogui.click(*COORDS["prev_chat"])
        return "Executed: Previous Chat"
    if message.startswith("TYPE:"):
        text = message.split("TYPE:", 1)[1]
        pyautogui.click(*COORDS["input_box"])
        pyautogui.write(text, interval=0.01)
        pyautogui.press("enter")
        return "Executed: Typed and Sent"
    return None


async def run_shell_command(command: str, session: dict) -> str:
    """Run a shell command in the session's working directory.

    The resulting directory is captured so `cd` persists to the next command.
    """
    cwd = session["cwd"]
    wrapped = (
        f"cd {shlex.quote(cwd)} && {command}\n"
        f'__rc=$?; printf "\\n{_CWD_MARK}%s" "$(pwd)"; exit $__rc'
    )
    proc = await asyncio.create_subprocess_shell(
        wrapped,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        executable="/bin/bash",
    )
    out, _ = await proc.communicate()
    text = out.decode(errors="replace")

    # Peel off the trailing working-directory marker and update the session.
    if _CWD_MARK in text:
        text, _, tail = text.rpartition(_CWD_MARK)
        new_cwd = tail.strip()
        if new_cwd:
            session["cwd"] = new_cwd
        text = text.rstrip("\n")

    if not text.strip():
        text = f"(no output, exit {proc.returncode})"
    return text


# Holds the running `caffeinate` process while "keep awake" is enabled.
_caffeinate_proc: subprocess.Popen | None = None


def set_caffeinate(on: bool) -> str:
    """Start/stop `caffeinate` to keep the Mac (and display) from sleeping."""
    global _caffeinate_proc
    if on:
        if _caffeinate_proc and _caffeinate_proc.poll() is None:
            return "AWAKE_ON"  # already running
        try:
            # -d display, -i idle, -m disk, -s system, -u user-active
            _caffeinate_proc = subprocess.Popen(["caffeinate", "-dimsu"])
            return "AWAKE_ON"
        except Exception as exc:  # noqa: BLE001 - caffeinate missing
            return f"Could not keep awake: {exc}"
    else:
        if _caffeinate_proc and _caffeinate_proc.poll() is None:
            _caffeinate_proc.terminate()
        _caffeinate_proc = None
        return "AWAKE_OFF"


# Remembers the last time each (session, text) was sent, so a duplicate
# request (double tap, phone key + Enter, an impatient re-send) doesn't drive
# the Conductor UI — or hit the API — a second time. UI automation is slow and
# synchronous, which is exactly when accidental duplicates arrive.
_recent_sends: dict[tuple[str, str], float] = {}
_DUP_WINDOW_S = float(os.environ.get("CDT_DUP_WINDOW_S", "15"))


def _is_duplicate_send(sid: str, text: str) -> bool:
    """True if this exact (session, text) was just sent within the dedup window."""
    now = time.monotonic()
    # Drop stale entries so the map can't grow without bound.
    for k, t in list(_recent_sends.items()):
        if now - t > 60:
            _recent_sends.pop(k, None)
    key = (sid, text)
    last = _recent_sends.get(key)
    _recent_sends[key] = now
    return last is not None and (now - last) < _DUP_WINDOW_S


# Last branch we saw per session id, so we can tell the client which chats were
# renamed between two `CDT:sessions` fetches. Keyed on the STABLE session id.
_last_branch: dict[str, str] = {}


def _branch_changes(items: list[dict]) -> list[dict]:
    """Sessions whose branch changed since the previous `CDT:sessions` fetch.

    Returns [{"session", "workspace_id", "branch", "previous"}]. The first fetch
    just seeds the snapshot (returns []), so a fresh connection isn't told that
    every chat "changed".
    """
    seeded = bool(_last_branch)
    changes: list[dict] = []
    for s in items:
        sid = s.get("id")
        if not sid:
            continue
        branch = s.get("branch")
        prev = _last_branch.get(sid)
        _last_branch[sid] = branch
        if seeded and prev is not None and prev != branch:
            changes.append({"session": sid, "workspace_id": s.get("workspace_id"),
                            "branch": branch, "previous": prev})
    return changes


async def handle_conductor(message: str) -> str:
    """Handle CDT:* commands, returning a JSON string the web UI parses."""
    rest = message.split("CDT:", 1)[1]
    verb, _, arg = rest.partition(":")
    try:
        if verb == "models":
            return json.dumps({"cdt": "models", **cdt.list_models()})
        if verb == "projects":
            return json.dumps({"cdt": "projects", "items": cdt.list_projects()})
        if verb == "sessions":
            items = cdt.list_sessions()
            # Tell the client which chats had their branch renamed since the last
            # fetch (Conductor renames branches over time). The client keys chats
            # on the stable id/workspace_id and just refreshes the branch label.
            return json.dumps({"cdt": "sessions", "items": items,
                               "changed": _branch_changes(items)})
        if verb == "messages":
            # Carry the chat's CURRENT identity so a client that already has this
            # chat open updates its branch/name in place after a rename, instead
            # of losing track of it. id/workspace_id are stable; the rest is
            # display only.
            ident = cdt.session_identity(arg)
            return json.dumps({
                "cdt": "messages", "session": arg,
                "workspace_id": ident.get("workspace_id"),
                "title": ident.get("title") or cdt.session_title(arg),
                "branch": ident.get("branch"),
                "workspace_name": ident.get("workspace_name"),
                "directory_name": ident.get("directory_name"),
                "items": cdt.get_messages(arg),
                "has_token": bool(cdt.API_TOKEN),
            })
        if verb == "send":
            sid, _, text = arg.partition(":")
            if _is_duplicate_send(sid, text):
                # Same message just went out — swallow the duplicate so the
                # agent isn't asked twice. The client keeps polling and will
                # show the reply from the first send.
                print(f"[dedup] ignored duplicate send to {sid}")
                return json.dumps({"cdt": "sent", "session": sid, "ok": True,
                                   "mode": "duplicate", "note": "Already sent."})
            if cdt.API_TOKEN:
                # Paid API: continue the existing chat.
                result = await asyncio.to_thread(cdt.send_message, sid, text)
                result.setdefault("mode", "api")
            else:
                # Free: reply into the SAME chat by driving the Conductor UI.
                # nav_info gives the project + workspace/branch names so the
                # automation can scroll/filter to the chat.
                nav = cdt.session_nav_info(sid) or {
                    "workspace_terms": [cdt.session_title(sid)]}
                result = await asyncio.to_thread(cui.open_chat_and_send, nav, text)
                if not result.get("ok"):
                    # Chat not found / UI automation failed → fall back to the
                    # OLD deep-link solution: create a NEW task in the SAME
                    # project (repo path comes from this chat's session).
                    fb = await asyncio.to_thread(cdt.new_task_for_session, sid, text)
                    if fb.get("ok"):
                        fb["fallback"] = True
                        fb["note"] = ("Couldn't open the existing chat, so started "
                                      "a new task in the same project instead.")
                        result = fb
                    elif fb.get("repo_missing"):
                        # Git repo absent on disk → surface that, do NOT create.
                        result = fb
            return json.dumps({"cdt": "sent", "session": sid, **result})
        if verb == "newtask":
            # New clients send a JSON payload (so a model/agent/effort can ride
            # along); older clients send the plain "path:prompt" form.
            arg_s = arg.strip()
            if arg_s.startswith("{"):
                try:
                    payload = json.loads(arg_s)
                except Exception:  # noqa: BLE001
                    return json.dumps({"cdt": "error", "error": "bad newtask payload"})
                path = payload.get("path") or None
                text = payload.get("prompt") or ""
                agent = payload.get("agent") or None
                model = payload.get("model") or None
                effort = payload.get("effort") or None
            else:
                path, _, text = arg.partition(":")
                path, agent, model, effort = (path or None), None, None, None
            result = await asyncio.to_thread(cdt.new_task, text, path, agent, model, effort)
            return json.dumps({"cdt": "sent", **result})
    except Exception as exc:  # noqa: BLE001 - surface any DB/CLI error to the UI
        return json.dumps({"cdt": "error", "error": str(exc)})
    return json.dumps({"cdt": "error", "error": f"unknown conductor verb: {verb}"})


async def execute(message: str, session: dict) -> str:
    if message.startswith("CDT:"):
        return await handle_conductor(message)
    if message.startswith("CMD:"):
        command = message.split("CMD:", 1)[1]
        return await run_shell_command(command, session)
    if message == "PWD":
        return session["cwd"]
    if message == "AWAKE_ON":
        return set_caffeinate(True)
    if message == "AWAKE_OFF":
        return set_caffeinate(False)
    if message == "AWAKE_STATUS":
        running = _caffeinate_proc is not None and _caffeinate_proc.poll() is None
        return "AWAKE_ON" if running else "AWAKE_OFF"

    try:
        ui_result = run_ui_command(message)
    except _FailSafe:
        return "Aborted: fail-safe triggered (mouse in corner)."
    if ui_result is not None:
        return ui_result

    return f"Unknown command: {message}"


def _auth_json(message: str) -> dict | None:
    """Parse a message as an {"auth": ...} control object, else None."""
    if not message or not message.lstrip().startswith("{"):
        return None
    try:
        obj = json.loads(message)
    except Exception:  # noqa: BLE001
        return None
    return obj if isinstance(obj, dict) and obj.get("auth") else None


async def _handle_auth(message: str, session: dict) -> tuple[str, bool, bool]:
    """Process a pre-auth message.

    Returns (reply, authenticated, hard_fail). `hard_fail` means it counts
    toward the per-connection lockout (wrong code / bad legacy code), as opposed
    to soft outcomes like "code sent" or an expired token the client can refresh.
    """
    obj = _auth_json(message)
    if obj is not None:
        verb = obj.get("auth")
        if verb == "request":
            res = await asyncio.to_thread(auth.request_code, obj.get("email", ""))
            if res.get("ok"):
                reply = {"auth": "code_sent", "email": res.get("email")}
                if "code" in res:                       # AUTH_DEBUG_CODE only
                    reply["debug_code"] = res["code"]
                return json.dumps(reply), False, False
            return json.dumps({"auth": "error", "code": res.get("code", "error"),
                               "error": res.get("error", "Couldn't send code.")}), False, False
        if verb == "verify":
            res = await asyncio.to_thread(auth.verify_code, obj.get("email", ""), obj.get("code", ""))
            if res.get("ok"):
                session.update(authenticated=True, email=res["email"],
                               session_token=res["session_token"], refresh_token=res["refresh_token"])
                return json.dumps({"auth": "ok", **{k: res[k] for k in (
                    "email", "session_token", "refresh_token", "expires_at", "refresh_expires_at")}}), True, False
            return json.dumps({"auth": "error", "code": res.get("code", "invalid"),
                               "error": res.get("error", "Wrong code.")}), False, True
        if verb in ("session", "refresh"):
            fn = auth.validate_session if verb == "session" else auth.refresh_session
            res = await asyncio.to_thread(fn, obj.get("token", ""))
            if res.get("ok"):
                session["authenticated"] = True
                session["email"] = res["email"]
                if verb == "session":
                    session["session_token"] = obj.get("token", "")
                    return json.dumps({"auth": "ok", "email": res["email"],
                                       "expires_at": res.get("expires_at")}), True, False
                session.update(session_token=res["session_token"], refresh_token=res["refresh_token"])
                return json.dumps({"auth": "ok", **{k: res[k] for k in (
                    "email", "session_token", "refresh_token", "expires_at", "refresh_expires_at")}}), True, False
            # A stale token is not a brute-force attempt — let the client re-auth.
            return json.dumps({"auth": "error", "code": res.get("code", "invalid"),
                               "error": res.get("error", "Invalid token.")}), False, False
        return json.dumps({"auth": "error", "code": "bad_request",
                           "error": f"Unknown auth verb: {verb}"}), False, False

    # Legacy shared-code fallback (the printed connect URL still works).
    if LEGACY_CODE_ENABLED and message == AUTH_CODE:
        session.update(authenticated=True, email="legacy")
        return "AUTH_SUCCESS", True, False
    return "AUTH_FAILED", False, True


async def handle_client(websocket) -> None:
    peer = getattr(websocket, "remote_address", "?")
    print(f"New device connected from {peer}. Waiting for auth...")
    session = {"authenticated": False, "cwd": os.path.expanduser("~")}
    attempts = 0

    try:
        async for message in websocket:
            if not session["authenticated"]:
                reply, authed, hard_fail = await _handle_auth(message, session)
                await websocket.send(reply)
                if authed:
                    print(f"Client authenticated ({session.get('email')}).")
                elif hard_fail:
                    attempts += 1
                    print(f"Bad auth attempt {attempts}/{MAX_AUTH_ATTEMPTS}.")
                    if attempts >= MAX_AUTH_ATTEMPTS:
                        await websocket.send("AUTH_LOCKED")
                        await websocket.close()
                        return
                continue

            # Authenticated: a logout control message ends the session.
            obj = _auth_json(message)
            if obj is not None and obj.get("auth") == "logout":
                await asyncio.to_thread(auth.logout, session.get("session_token", ""),
                                        session.get("refresh_token", ""))
                await websocket.send(json.dumps({"auth": "logged_out"}))
                await websocket.close()
                print(f"Client logged out ({session.get('email')}).")
                return

            print(f"Command received: {message}")
            try:
                result = await execute(message, session)
            except Exception as exc:  # noqa: BLE001 - report any failure
                result = f"Error executing command: {exc}"
            await websocket.send(result)

    except websockets.exceptions.ConnectionClosed:
        print("Device disconnected.")


async def main() -> None:
    auth.init_db()
    auth.print_startup_notes()
    deliver_code()
    async with websockets.serve(handle_client, HOST_IP, PORT):
        print(f"WebSocket server running on ws://{HOST_IP}:{PORT}")
        print(f"Connect a client to ws://<your-tailscale-ip>:{PORT}")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
