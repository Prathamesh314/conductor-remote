#!/usr/bin/env bash
#
# Control the Mac Remote server (WebSocket on PORT 8765 + web UI on WEB_PORT 8080).
# Runs start.sh in the background and tracks it with a PID file + log file.
#
#   ./serverctl.sh start      # launch in the background
#   ./serverctl.sh stop       # stop it
#   ./serverctl.sh restart    # stop then start
#   ./serverctl.sh status     # is it running? which ports?
#   ./serverctl.sh logs       # follow the log (Ctrl-C to stop watching)
#
# Tip: add a shortcut to your ~/.zshrc so you can run it from anywhere —
#   macremote() { (cd "/full/path/to/repo/server" && ./serverctl.sh "$@"); }
# then: `macremote start`, `macremote stop`, `macremote restart`.
#
set -uo pipefail
cd "$(dirname "$0")"   # the server/ directory, wherever this repo lives

PID_FILE=".server.pid"
LOG_FILE="server.log"
WS_PORT="${PORT:-8765}"
WEB_PORT="${WEB_PORT:-8080}"

_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }

# Echo the tracked PID if it's still alive, else return non-zero.
running_pid() {
  local p
  [ -f "$PID_FILE" ] || return 1
  p="$(cat "$PID_FILE" 2>/dev/null || true)"
  if _alive "$p"; then echo "$p"; return 0; fi
  return 1
}

# PIDs holding either server port (catches stale / detached listeners).
port_pids() { { lsof -ti "tcp:$WS_PORT" 2>/dev/null; lsof -ti "tcp:$WEB_PORT" 2>/dev/null; } | sort -u; }

start() {
  local p
  if p="$(running_pid)"; then echo "Already running (PID $p)."; return 0; fi
  if [ -n "$(port_pids)" ]; then
    echo "Ports $WS_PORT/$WEB_PORT are already in use. Run '$0 stop' first."; return 1
  fi
  echo "Starting Mac Remote server (logs: server/$LOG_FILE)…"
  nohup ./start.sh >"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  sleep 2
  if p="$(running_pid)"; then
    echo "Started (PID $p)."
    grep -E "AUTH CODE|http://|ready" "$LOG_FILE" 2>/dev/null | tail -n 4 || true
  else
    echo "Failed to start — last log lines:"; tail -n 15 "$LOG_FILE" 2>/dev/null; return 1
  fi
}

stop() {
  local p pp i any=0
  if p="$(running_pid)"; then
    echo "Stopping (PID $p)…"; kill "$p" 2>/dev/null || true
    for i in $(seq 1 20); do _alive "$p" || break; sleep 0.25; done
    _alive "$p" && kill -9 "$p" 2>/dev/null || true
    any=1
  fi
  # Free the ports in case the tracked PID was stale or a listener lingered.
  pp="$(port_pids)"
  if [ -n "$pp" ]; then
    echo "Freeing ports $WS_PORT/$WEB_PORT…"
    echo "$pp" | xargs kill 2>/dev/null || true
    sleep 0.5
    pp="$(port_pids)"; [ -n "$pp" ] && echo "$pp" | xargs kill -9 2>/dev/null || true
    any=1
  fi
  rm -f "$PID_FILE"
  [ "$any" = 1 ] && echo "Stopped." || echo "Not running."
}

restart() { stop; sleep 1; start; }

status() {
  local p pp
  if p="$(running_pid)"; then echo "● running (PID $p)"; else echo "○ not running"; fi
  pp="$(port_pids)"
  if [ -n "$pp" ]; then echo "  ports $WS_PORT/$WEB_PORT held by PID(s): $(echo $pp)"; else echo "  ports $WS_PORT/$WEB_PORT free"; fi
}

logs() { tail -n "${1:-40}" -f "$LOG_FILE"; }

case "${1:-}" in
  start)   start ;;
  stop)    stop ;;
  restart) restart ;;
  status)  status ;;
  logs)    shift; logs "${1:-40}" ;;
  *) echo "Usage: $0 {start|stop|restart|status|logs}"; exit 2 ;;
esac
