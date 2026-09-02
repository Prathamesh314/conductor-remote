#!/usr/bin/env bash
#
# One command to start everything on the MacBook:
#   1. brings up Tailscale (so your iPhone can reach this Mac anywhere)
#   2. installs Python deps into a local venv (first run only)
#   3. launches the control server + web terminal, prints a connect URL + auth code
#
# Usage:   ./start.sh
#
set -euo pipefail
cd "$(dirname "$0")"   # the server/ directory

echo "==> Mac Remote starting..."

# --- 1. Tailscale ---------------------------------------------------------
TS_BIN=""
for c in tailscale /Applications/Tailscale.app/Contents/MacOS/Tailscale; do
  if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then TS_BIN="$c"; break; fi
done

if [ -n "$TS_BIN" ]; then
  echo "==> Bringing up Tailscale..."
  # Non-fatal: if already up / needs interactive login, we continue anyway.
  "$TS_BIN" up 2>/dev/null || true
  TS_IP="$("$TS_BIN" ip -4 2>/dev/null | head -n1 || true)"
  if [ -n "$TS_IP" ]; then
    echo "==> Tailscale IP: $TS_IP"
  else
    echo "!! Tailscale not logged in yet. Open the Tailscale app, sign in, then re-run."
  fi
else
  echo "!! Tailscale not found."
  echo "   Install it: https://tailscale.com/download/mac  (then sign in and re-run)"
  echo "   Continuing anyway — the server will still work on your local Wi-Fi."
fi

# --- 2. Python deps (local venv) -----------------------------------------
if [ ! -d ".venv" ]; then
  echo "==> Creating Python virtualenv (first run)..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing dependencies..."
# Xcode's bundled pip is too old to fetch some prebuilt wheels and tries to
# compile them (which fails). Upgrade pip first so wheels are used.
pip install -q --upgrade pip setuptools wheel
# Minimal set needed for the remote terminal. pyautogui (for UI clicking) is
# optional; install it with: pip install --prefer-binary pyautogui
pip install -q --prefer-binary websockets python-dotenv

# --- 3. Launch -----------------------------------------------------------
echo "==> Launching server + web terminal..."
echo
exec python3 -u start.py
