"""Read the latest auth code from your Discord channel and validate it.

Webhooks are SEND-only, so reading messages needs a Discord **bot token**.
One-time setup:
  1. https://discord.com/developers/applications  -> New Application
  2. Left menu -> Bot -> Reset/Copy Token. Enable "MESSAGE CONTENT INTENT".
  3. Left menu -> OAuth2 -> URL Generator -> scopes: `bot`,
     permissions: "Read Message History" -> open the URL, add the bot to your
     server (the same server the webhook posts to).
  4. Put the token in .env:   DISCORD_BOT_TOKEN=xxxxx

The channel is auto-detected from DISCORD_WEBHOOK_URL, so you don't need to
find the channel id yourself.

Usage:
    python3 discord_reader.py            # poll until a valid code appears
    python3 discord_reader.py --once     # check once and exit
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request

from dotenv import load_dotenv

load_dotenv()

API = "https://discord.com/api/v10"
UA = "MacRemote/1.0 (+https://github.com)"

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
# Length of the auth code to look for (matches server.py's 6-digit codes).
CODE_LENGTH = int(os.environ.get("CODE_LENGTH", "6"))
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "3"))


def _get(url: str, headers: dict) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def channel_id_from_webhook() -> str:
    """Derive the channel id from the webhook URL (no bot token needed)."""
    if not WEBHOOK_URL:
        raise SystemExit("DISCORD_WEBHOOK_URL is not set in .env")
    data = _get(WEBHOOK_URL, {})
    cid = data.get("channel_id")
    if not cid:
        raise SystemExit("Could not read channel_id from the webhook.")
    return cid


def extract_code(text: str, length: int = CODE_LENGTH) -> str | None:
    """Return the first run of exactly `length` digits in `text`, else None.

    This validates BOTH the length and that every character is a digit.
    """
    for token in re.findall(r"\d+", text or ""):
        if len(token) == length and token.isdigit():
            return token
    return None


def latest_code(channel_id: str) -> str | None:
    """Fetch recent messages (newest first) and return the first valid code."""
    if not BOT_TOKEN:
        raise SystemExit(
            "DISCORD_BOT_TOKEN is not set. Webhooks can't read messages — "
            "add a bot token to .env (see the header of this file)."
        )
    url = f"{API}/channels/{channel_id}/messages?limit=10"
    messages = _get(url, {"Authorization": f"Bot {BOT_TOKEN}"})
    for msg in messages:  # already newest-first from Discord
        code = extract_code(msg.get("content", ""))
        if code:
            return code
    return None


def main() -> None:
    once = "--once" in sys.argv
    channel_id = channel_id_from_webhook()
    print(f"Watching channel {channel_id} for a {CODE_LENGTH}-digit code...")

    # Keep searching until a valid code is found (or exit after one try).
    while True:
        try:
            code = latest_code(channel_id)
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 - transient network/API error
            print(f"[warn] read failed: {exc}")
            code = None

        if code:
            print(code)
            return
        if once:
            print("No valid code found yet.")
            return
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
