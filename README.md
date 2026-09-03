# Mac Remote Controller

Control your Mac, and the Conductor app running on it, from an iPhone or any
browser on your Tailnet.

This project runs a small Python WebSocket server on the Mac. The bundled web
UI lets you browse Conductor projects and chats, read transcripts, start new
Conductor tasks, run shell commands, and keep the Mac awake while you are away.

```text
phone/browser -> Tailscale -> Mac Python server -> Conductor app
                                             \-> local shell commands
                                             \-> optional UI automation
```

## What Works

- Browse Conductor projects and chats from the mobile web UI.
- Read recent messages from a Conductor chat.
- Start a new Conductor task in a selected project.
- Add a GitHub repo from the phone: it's cloned onto the Mac (private repos via
  `gh`), ready to add as a Conductor project. (Conductor has no local add-repo
  API, so the final "New project → choose the folder" is a one-tap manual step.)
- Reply to an existing Conductor chat when `CONDUCTOR_API_TOKEN` is set.
- Run shell commands on the Mac with a persistent working directory per socket.
- Toggle `caffeinate` to keep the Mac awake.
- Optionally drive the Mac UI with `pyautogui` coordinates.

## Conductor Behavior

The Conductor bridge is implemented in `server/conductor.py`.

- Reading projects, chats, and messages does not need a token. The server opens
  Conductor's local SQLite database read-only:
  `~/Library/Application Support/com.conductor.app/conductor.db`.
- Starting a new task does not need a token. The server opens a
  `conductor://prompt=...&path=...` deep link. With autosubmit enabled, it then
  brings Conductor forward and presses Enter.
- Replying to an existing chat requires `CONDUCTOR_API_TOKEN`. When the token is
  set, the server uses the Conductor CLI at:
  `~/Library/Application Support/com.conductor.app/bin/conductor`.
- Without `CONDUCTOR_API_TOKEN`, sending from an existing chat starts a new task
  in that chat's project instead of appending to the old session.

## Quick Start

On the Mac:

```bash
cd server
./start.sh
```

`start.sh`:

- tries to bring up Tailscale,
- creates `server/.venv` if needed,
- installs the core Python dependencies used by the browser flow,
- starts the WebSocket server and static web UI.

It prints URLs and an auth code:

```text
Mac Remote is ready.
Tailscale is ON - reachable from anywhere:
  ->  http://100.x.x.x:8080
AUTH CODE:  922031
```

## Sign in

The primary sign-in is **per-user email codes** with saved session tokens (so you
stay signed in for days). See [`server/AUTH.md`](server/AUTH.md) for the full
flow, protocol, and security notes.

On the phone:

1. Install Tailscale and sign in with the same account as the Mac.
2. Turn Tailscale on.
3. Open `http://100.x.x.x:8080` (or the native iOS app), enter the Mac's address
   and your email, then the 6-digit code emailed to you. You stay signed in for
   days; a saved session reconnects automatically, and **Log out** ends it.
4. Tap Conductor to browse projects, chats, and tasks.

Only allowlisted emails may sign in — set `AUTH_ALLOWED_EMAILS` (it defaults to
`EMAIL_RECEIVER`). Email must be configured (`EMAIL_SENDER`/`EMAIL_PASSWORD`) to
send codes.

**Legacy quick connect:** `start.py` also prints a ready-to-open connect URL with
a shared code embedded in the hash, e.g. `http://100.x.x.x:8080/#922031` (also
copied to the Mac clipboard). It still works as a fallback; disable with
`AUTH_LEGACY_CODE=0`.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `server/start.sh` | Recommended launcher. Sets up the venv, tries Tailscale, then runs `start.py`. |
| `server/start.py` | Starts the WebSocket server plus static web server on `WEB_PORT` (default `8080`). |
| `server/server.py` | WebSocket protocol, shell execution, keep-awake toggle, and Conductor routes. |
| `server/auth.py` | Email-code sign-in + session/refresh tokens, backed by SQLite (`auth.db`). |
| `server/AUTH.md` | Sign-in flow diagram, WebSocket auth protocol, and security notes. |
| `server/conductor.py` | Read-only Conductor DB access plus deep-link/API send helpers. |
| `server/web/index.html` | Mobile browser UI for terminal and Conductor control. |
| `server/client.py` | Minimal CLI client for testing `ws://host:8765`. |
| `server/calibrate.py` | Helper for finding mouse coordinates for optional UI automation. |
| `server/coordinates.example.json` | Example `pyautogui` coordinate map. |
| `server/.env.example` | Environment variable template. |
| `ios/MacRemote/` | SwiftUI files for a full native iOS app (browse chats, read transcripts, reply, start tasks, shell, keep-awake). |

## Setup

### 1. Network

Install Tailscale on the Mac and phone, using the same Tailscale account. This
lets the phone reach the Mac over a private encrypted network without port
forwarding.

Same-Wi-Fi can also work. If Tailscale is unavailable, `start.py` prints a LAN
URL such as `http://192.168.x.x:8080`.

### 2. Environment

Create a local `.env` when you need persistent settings:

```bash
cd server
cp .env.example .env
```

Important variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `HOST_IP` | `0.0.0.0` | WebSocket listen address. |
| `PORT` | `8765` | WebSocket port used by the web UI and CLI client. |
| `WEB_PORT` | `8080` | Static web UI port used by `start.py`. |
| `AUTH_CODE` | random 6 digits | Optional fixed auth code. If unset, a new code is generated on startup. |
| `MAX_AUTH_ATTEMPTS` | `5` | Failed auth attempts before the socket is closed. |
| `CONDUCTOR_API_TOKEN` | empty | Required only to reply to an existing Conductor chat. |
| `CONDUCTOR_AUTOSUBMIT` | `1` | Press Enter after opening a new-task deep link. |
| `CONDUCTOR_SUBMIT_DELAY` | `4` | Seconds to wait before autosubmit. |
| `CONDUCTOR_SUBMIT_KEY` | `enter` | Use `enter` or `cmd-enter` for autosubmit. |
| `EMAIL_SENDER` / `EMAIL_PASSWORD` / `EMAIL_RECEIVER` | empty | Optional email delivery settings. |
| `COORDINATES_FILE` | `coordinates.json` | Coordinate map for optional UI automation. |

`CONDUCTOR_API_TOKEN` must be present in `.env` or the environment of the Python
server process. Running a CLI login by itself is not enough for this server
unless it also provides that environment variable.

### 3. Dependencies

The recommended browser flow needs:

```bash
pip install websockets python-dotenv
```

`./start.sh` installs those into `server/.venv` automatically.

For optional coordinate-based UI automation, also install:

```bash
pip install --prefer-binary pyautogui
```

`server/requirements.txt` includes both the core and optional Python packages if
you prefer installing everything manually:

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

Recommended:

```bash
cd server
./start.sh
```

Manual alternatives:

```bash
cd server
python3 start.py    # WebSocket server plus browser UI
python3 server.py   # WebSocket server only
```

Do not expose ports `8765` or `8080` to the public internet. Use Tailscale or a
trusted private network.

## Browser UI

After connecting:

- Tap Conductor to open the mobile Conductor browser.
- Projects shows every visible Conductor repo.
- Project chats shows chat status, unread counts, branch/workspace info, and
  recent update time.
- New task opens a bottom sheet where you choose a project and prompt.
- Opening a chat shows recent transcript messages.
- The chat input replies to the existing chat when an API token is configured;
  otherwise it starts a new task in that project.
- Terminal runs local shell commands. `cd` persists for that WebSocket session.
- Awake toggles `caffeinate` on the Mac.

## Optional UI Automation

The `NEW_CHAT`, `NEXT_CHAT`, `PREV_CHAT`, and `TYPE:<text>` commands use
`pyautogui` and screen coordinates.

To enable them:

1. Install `pyautogui`.
2. Grant Accessibility permission in macOS to the app running Python, such as
   Terminal, iTerm, VS Code, or Cursor.
3. Run:

   ```bash
   cd server
   python3 calibrate.py
   ```

4. Copy `server/coordinates.example.json` to `server/coordinates.json` and fill
   in the real coordinates.

The browser terminal and Conductor database/deep-link features work without
`pyautogui`.

## Optional Native iOS App

A full native SwiftUI client lives under `ios/MacRemote/`. It has a dark,
minimalist design and covers the main workflow:

- Connect + authenticate with the Mac's Tailscale IP and the emailed code.
- Browse Conductor chats (workspace-centric, newest first) with search.
- Read a chat's transcript in message bubbles; it polls for new replies.
- Reply into a chat, or start a new task from any project.
- Run shell commands with a persistent working directory.
- Toggle keep-awake (`caffeinate`) and see connection/API-token status.

To use it:

1. Create a new SwiftUI iOS app in Xcode named `MacRemote`.
2. Delete the generated `ContentView.swift`/app file and add every file from
   `ios/MacRemote/` to the target.
3. Configure App Transport Security for local `ws://` connections, for example
   with `NSAllowsLocalNetworking` or a host-specific exception.
4. Run on the phone and connect to the Mac's Tailscale IP on port `8765`.

## Protocol

The first message on every WebSocket connection must be the auth code. After
`AUTH_SUCCESS`, these messages are supported.

### Conductor

| Message | Result |
| --- | --- |
| `CDT:projects` | Return visible Conductor projects/repos. |
| `CDT:sessions` | Return visible chats with project, status, unread count, branch, workspace, and update time. |
| `CDT:messages:<sessionId>` | Return recent readable transcript messages for a chat. |
| `CDT:send:<sessionId>:<text>` | Reply to the chat when `CONDUCTOR_API_TOKEN` is set; otherwise start a new task in that chat's project. |
| `CDT:newtask:<repoPath>:<text>` | Start a new Conductor task using a deep link. `repoPath` may be empty. |

### General

| Message | Action |
| --- | --- |
| `CMD:<shell>` | Run a shell command in the session cwd and return combined output. |
| `PWD` | Return the session cwd. |
| `AWAKE_ON` / `AWAKE_OFF` | Start or stop `caffeinate -dimsu`. |
| `AWAKE_STATUS` | Return `AWAKE_ON` or `AWAKE_OFF`. |
| `NEW_CHAT` | Click the configured `new_chat` coordinate. |
| `NEXT_CHAT` / `PREV_CHAT` | Click configured chat navigation coordinates. |
| `TYPE:<text>` | Click the configured input coordinate, type text, and press Enter. |

## Testing

CLI smoke test:

```bash
cd server
python3 server.py
```

In another terminal:

```bash
cd server
python3 client.py localhost 8765
```

For the browser UI, use:

```bash
cd server
python3 start.py
```

Then open `http://localhost:8080` on the Mac or the printed Tailscale/LAN URL
from another device.

## Troubleshooting

- Phone cannot connect: confirm Tailscale is on, use the exact printed
  `http://...:8080` URL, and make sure the Python process is still running.
- Auth fails: use the latest printed or delivered code. If `AUTH_CODE` is unset,
  it changes every server start.
- Projects/chats do not load: make sure Conductor is installed for this user and
  its database exists at the expected path, or set `CONDUCTOR_DB`.
- Existing-chat replies fail: set `CONDUCTOR_API_TOKEN` in the server
  environment and confirm the Conductor CLI path, or set `CONDUCTOR_CLI`.
- New-task autosubmit does not press Enter: grant Accessibility permission to
  the app running Python, increase `CONDUCTOR_SUBMIT_DELAY`, or set
  `CONDUCTOR_AUTOSUBMIT=0` and submit manually in Conductor.
- UI-click commands fail: install `pyautogui`, grant Accessibility permission,
  and create `server/coordinates.json`.
- Browser uses stale code or UI: `start.py` sends no-cache headers, but a hard
  refresh or reopening the tab may still help on mobile Safari.

## Security Notes

- The server uses a shared auth code and closes the socket after too many failed
  attempts.
- Tailscale limits reachability to devices on your Tailnet.
- The Conductor database is opened read-only.
- `.env` and `server/coordinates.json` are gitignored.
- This is intended for controlling your own Mac on a trusted private network.
