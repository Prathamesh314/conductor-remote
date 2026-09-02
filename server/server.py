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
import urllib.request
from email.message import EmailMessage
from pathlib import Path

import websockets
from dotenv import load_dotenv

import conductor as cdt

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

load_dotenv()

# --- Configuration (from environment / .env) ---
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", EMAIL_SENDER)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

HOST_IP = os.environ.get("HOST_IP", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8765"))
MAX_AUTH_ATTEMPTS = int(os.environ.get("MAX_AUTH_ATTEMPTS", "5"))
COORDINATES_FILE = os.environ.get("COORDINATES_FILE", "coordinates.json")

# Auth code: use a fixed code from the environment if set (so you can connect
# from far away without seeing the Mac's screen/QR), otherwise generate a fresh
# random one each start.
_ENV_CODE = os.environ.get("AUTH_CODE", "").strip()
AUTH_CODE = _ENV_CODE if _ENV_CODE else f"{random.randint(0, 999999):06d}"

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


def send_discord_code() -> bool:
    """Post the auth code to a Discord channel via webhook. Returns True on send."""
    if not DISCORD_WEBHOOK_URL:
        return False
    try:
        data = json.dumps(
            {"content": f"🔐 Mac Remote auth code: **{AUTH_CODE}**"}
        ).encode()
        req = urllib.request.Request(
            DISCORD_WEBHOOK_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                # Discord/Cloudflare rejects the default urllib UA with 403.
                "User-Agent": "MacRemote/1.0 (+https://github.com)",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        print("Auth code sent to Discord.")
        return True
    except Exception as exc:  # noqa: BLE001 - bad webhook / no network
        print(f"[warn] Discord send failed: {exc}")
        return False


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
    """Send the code everywhere that's configured (Discord + email) and print it."""
    sent_discord = send_discord_code()
    sent_email = send_email_code()
    if not (sent_discord or sent_email):
        print("=" * 52)
        print("  No delivery configured (Discord/email) — read the code below.")
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


async def handle_conductor(message: str) -> str:
    """Handle CDT:* commands, returning a JSON string the web UI parses."""
    rest = message.split("CDT:", 1)[1]
    verb, _, arg = rest.partition(":")
    try:
        if verb == "projects":
            return json.dumps({"cdt": "projects", "items": cdt.list_projects()})
        if verb == "sessions":
            return json.dumps({"cdt": "sessions", "items": cdt.list_sessions()})
        if verb == "messages":
            return json.dumps({
                "cdt": "messages", "session": arg,
                "title": cdt.session_title(arg),
                "items": cdt.get_messages(arg),
            })
        if verb == "send":
            sid, _, text = arg.partition(":")
            if cdt.API_TOKEN:
                # Paid API: continue the existing chat.
                result = await asyncio.to_thread(cdt.send_message, sid, text)
                result.setdefault("mode", "api")
            else:
                # Free: start a new task in that chat's project via deep link.
                result = await asyncio.to_thread(cdt.new_task_for_session, sid, text)
            return json.dumps({"cdt": "sent", "session": sid, **result})
        if verb == "newtask":
            path, _, text = arg.partition(":")
            result = await asyncio.to_thread(cdt.new_task, text, path or None)
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


async def handle_client(websocket) -> None:
    peer = getattr(websocket, "remote_address", "?")
    print(f"New device connected from {peer}. Waiting for auth...")
    session = {"authenticated": False, "cwd": os.path.expanduser("~")}
    attempts = 0

    try:
        async for message in websocket:
            if not session["authenticated"]:
                if message == AUTH_CODE:
                    session["authenticated"] = True
                    await websocket.send("AUTH_SUCCESS")
                    print("Client Authenticated!")
                else:
                    attempts += 1
                    await websocket.send("AUTH_FAILED")
                    print(f"Bad auth attempt {attempts}/{MAX_AUTH_ATTEMPTS}.")
                    if attempts >= MAX_AUTH_ATTEMPTS:
                        await websocket.send("AUTH_LOCKED")
                        await websocket.close()
                        return
                continue

            print(f"Command received: {message}")
            try:
                result = await execute(message, session)
            except Exception as exc:  # noqa: BLE001 - report any failure
                result = f"Error executing command: {exc}"
            await websocket.send(result)

    except websockets.exceptions.ConnectionClosed:
        print("Device disconnected.")


async def main() -> None:
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
