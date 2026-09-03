"""One-command launcher: WebSocket control server + web terminal.

    python3 start.py

Starts:
  - the WebSocket command server on PORT (default 8765)
  - a static web server for the phone-friendly terminal on WEB_PORT (default 8080)

Then prints a ready-to-open connection URL (with the auth code embedded). Open
that URL on your phone (over Tailscale) or Mac and you have a live terminal.
"""

from __future__ import annotations

import asyncio
import functools
import os
import shutil
import socket
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Where the Tailscale CLI lives (PATH, or bundled inside the Mac app).
TAILSCALE_BINS = [
    "tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
]

import websockets

import server as srv  # reuse handle_client, config, AUTH_CODE, email

WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
WEB_DIR = Path(__file__).parent / "web"


def tailscale_bin() -> str | None:
    for b in TAILSCALE_BINS:
        if shutil.which(b) or (os.path.isabs(b) and os.access(b, os.X_OK)):
            return b
    return None


def tailscale_ip() -> str | None:
    """Tailscale IP, but only if Tailscale is actually logged in/connected.

    Returns None when logged out, so we don't advertise an unreachable URL.
    """
    ts = tailscale_bin()
    if not ts:
        return None
    try:
        res = subprocess.run(
            [ts, "status"], capture_output=True, text=True, timeout=5
        )
        # "Logged out." / "stopped" are printed to stderr, so check both.
        status = (res.stdout + res.stderr).lower()
        if "logged out" in status or "stopped" in status or res.returncode != 0:
            return None
        ip = subprocess.run(
            [ts, "ip", "-4"], capture_output=True, text=True, timeout=5
        ).stdout.strip().splitlines()
        return ip[0] if ip else None
    except Exception:  # noqa: BLE001 - tailscale not up
        return None


def lan_ip() -> str:
    """This Mac's IP on the local network (same-Wi-Fi fallback)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "localhost"


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the Mac clipboard via pbcopy. With Universal Clipboard on,
    it becomes pasteable on the iPhone moments later."""
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True, timeout=3)
        return True
    except Exception:  # noqa: BLE001 - pbcopy missing / not on macOS
        return False


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silence per-request logging
        pass

    def send_head(self):
        # Ignore the browser's cache validators so we ALWAYS return a fresh
        # 200 with the current HTML (otherwise Safari reuses a stale page and
        # the auto-fill code never runs).
        for h in ("If-Modified-Since", "If-None-Match"):
            if h in self.headers:
                del self.headers[h]
        return super().send_head()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        super().end_headers()

    def handle(self) -> None:
        # Browsers routinely drop connections early (prefetch, tab switch).
        # Swallow the resulting reset/broken-pipe so it isn't logged as a
        # traceback — it's harmless.
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass


class _QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:
        pass  # don't dump tracebacks for dropped client connections


def start_web_server() -> None:
    handler = functools.partial(_QuietHandler, directory=str(WEB_DIR))
    httpd = _QuietServer(("0.0.0.0", WEB_PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()


async def main() -> None:
    srv.auth.init_db()
    srv.auth.print_startup_notes()
    srv.deliver_code()
    start_web_server()

    ts_ip = tailscale_ip()
    lan = lan_ip()
    # Prefer Tailscale (works anywhere) when connected; the connect URL points
    # at the address that is most likely to actually be reachable.
    primary = ts_ip or lan
    url = f"http://{primary}:{WEB_PORT}"

    line = "=" * 54
    print("\n" + line)
    print("  Mac Remote is ready.")
    print(line)

    if ts_ip:
        print("  Tailscale is ON — reachable from anywhere:")
        print(f"    ->  http://{ts_ip}:{WEB_PORT}")
        print(f"  (same Wi-Fi fallback:  http://{lan}:{WEB_PORT})")
    else:
        print("  !! Tailscale is LOGGED OUT — sign in via the menu-bar app to")
        print("     connect over cellular / away from home.")
        print("  For now, if your iPhone is on the SAME Wi-Fi, open:")
        print(f"    ->  http://{lan}:{WEB_PORT}")
    print(f"  (on this Mac:          http://localhost:{WEB_PORT})")
    print(f"\n  AUTH CODE:  {srv.AUTH_CODE}")

    # This connect URL embeds the code in the hash, so opening it fills the code
    # in and auto-connects — just open it (or type it) on the phone, no scanning.
    connect_url = f"{url}/#{srv.AUTH_CODE}"
    print("\n  Open this URL on your phone to connect (auto-logs in):")
    print(f"    ->  {connect_url}")
    copy_to_clipboard(connect_url)  # also copied to the Mac clipboard
    if srv.pyautogui is None:
        print("\n  [note] pyautogui not loaded — shell commands work, UI")
        print("         clicking (NEW_CHAT/TYPE) is disabled until you")
        print("         `pip install pyautogui` + grant Accessibility.")
    print(line + "\n")

    async with websockets.serve(srv.handle_client, srv.HOST_IP, srv.PORT):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
