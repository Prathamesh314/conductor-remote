# Mac Remote Controller

**Control your Mac — and the [Conductor](https://conductor.build) app running on it — straight from your iPhone (or any phone/browser), from anywhere.**

You leave your MacBook at home with Conductor running its coding agents. From
your phone on cellular you open a web page, type a code once, and you can:

- **Browse every Conductor project and chat**, see which agents are working vs.
  idle, and read the live transcript of any session.
- **Send a new command/prompt into any Conductor chat** — i.e. drive your
  Conductor agents remotely while you're away from the desk.
- **Run any shell command** on the Mac (`ls`, `cd`, `git …`) with a real,
  persistent working directory.
- **Keep the Mac awake** so agents keep running while the lid's closed.

```
 iPhone / any browser  ──ws──►  Mac (Python server)  ──►  Conductor app (read DB + CLI)
         │                              │              └─►  shell commands
         │                              └─►  pyautogui UI clicks (optional)
         └──────────── Tailscale VPN (encrypted, works anywhere) ───────────┘
```

---

## 🎯 What it's for

The **main purpose is to operate the Conductor app from your phone** — to give
commands to your Conductor coding agents directly from your phone without being
at your Mac. Everything else (the remote shell, keep-awake, optional UI
automation) is supporting plumbing around that goal.

How the Conductor bridge works (see `server/conductor.py`):

- **Reading** projects / chats / messages needs **no token** — it reads
  Conductor's local SQLite database (`~/Library/Application Support/com.conductor.app/conductor.db`) read-only.
- **Sending** a message into a chat uses the **Conductor CLI**, which needs a
  `CONDUCTOR_API_TOKEN`.

---

## ⚡ Quick start (the simple version)

**On the MacBook — one command:**

```bash
cd server
./start.sh
```

This brings up Tailscale, installs what it needs (into a local `.venv`), and
starts everything. It prints a box like:

```
  Tailscale is ON — reachable from anywhere:
    ->  http://100.x.x.x:8080
  AUTH CODE:  922031
```

(If you ran `brew install qrencode` first, it also prints a scannable QR code
that logs you in automatically.)

**On the iPhone — one step to connect:**

1. Install the **Tailscale app**, sign in with the **same account** as the Mac,
   and toggle it **on**.
2. Open **Safari** and go to the `http://100.x.x.x:8080` URL the Mac printed
   (or point the **Camera** at the QR code and tap the banner — it auto-fills
   the code).
3. The server address is pre-filled — type the **auth code** and tap
   **Connect**.
4. Tap **🎛 Conductor** in the header to browse your projects/chats and send
   commands. Or use the terminal directly: `ls -la`, `cd Desktop`, `pwd`.

That's it. Everything below is detail / optional extras.

---

## Layout

| Path | What it is |
|------|------------|
| `server/start.py` | **One-command launcher** — WebSocket server + phone-friendly web terminal, prints URL/QR/code |
| `server/start.sh` | Wrapper that also brings up Tailscale and sets up the venv |
| `server/server.py` | WebSocket server: auth + shell commands + Conductor bridge + optional pyautogui UI control |
| `server/conductor.py` | Bridge to the Conductor app (reads its SQLite DB, sends via the Conductor CLI) |
| `server/web/index.html` | The **web terminal + Conductor browser** you open in any phone/desktop browser |
| `server/client.py` | Minimal CLI test client (no phone/browser needed) |
| `server/calibrate.py` | Prints live mouse coordinates so you can map buttons (for optional UI automation) |
| `server/coordinates.example.json` | Template for the button-coordinate map |
| `server/.env.example` | Template for config (Conductor token, code delivery, ports) |
| `ios/MacRemote/` | Optional native SwiftUI iOS app (drop into an Xcode iOS App project) |

---

## Setup (Mac)

### 1. Network

Install [Tailscale](https://tailscale.com/download/mac) on **both** the Mac and
your phone, signed into the **same account**. Tailscale is what makes the Mac
reachable from anywhere (cellular included) over an encrypted tunnel — no port
forwarding, no exposing anything to the public internet.

> Same-Wi-Fi also works as a fallback; `start.py` prints a `http://192.168.x.x`
> LAN URL when Tailscale isn't logged in.

### 2. Install the server

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then edit .env (see below)
```

### 3. Configure `.env`

The two things that matter most for the Conductor use-case:

- **`CONDUCTOR_API_TOKEN`** — required to *send* commands into chats (browsing
  works without it). Get it from the Conductor app / your account, or run
  `conductor auth login`.
- **`AUTH_CODE`** — optionally set a fixed 6-digit code you'll remember, so you
  can connect from far away without seeing the Mac's screen. If left unset a
  fresh random code is generated on every start.

Optional — deliver the auth code to a channel you can read on the go (only
needed if you *don't* set a fixed `AUTH_CODE`):

- **Discord (easiest):** paste a channel webhook URL into `DISCORD_WEBHOOK_URL`.
- **Email:** set `EMAIL_SENDER` / `EMAIL_PASSWORD` / `EMAIL_RECEIVER` (Gmail
  needs an App Password).

### 4. (Optional) UI automation permission

Only if you want the `NEW_CHAT` / `TYPE:` pyautogui clicking features:

- Grant **System Settings → Privacy & Security → Accessibility** to the app that
  runs Python (Terminal / iTerm / VS Code / Cursor).
- Run `python3 calibrate.py`, hover over each button, and put the X/Y into a
  `coordinates.json` (copy from `coordinates.example.json`).

The shell + Conductor features work fine without this; pyautogui is optional and
degrades gracefully if it isn't installed.

---

## Start it

```bash
cd server
./start.sh            # recommended: also brings up Tailscale + venv
# or:
python3 start.py      # server + web terminal only (venv already active)
# or:
python3 server.py     # just the WebSocket server, no bundled web terminal
```

`start.py` prints your connect URL, a QR code, and the auth code.

---

## Connect from your phone (or any device)

1. Turn on **Tailscale** on the phone (same account as the Mac).
2. Open the `http://100.x.x.x:8080` URL that `start.py` printed — in Safari,
   Chrome, any browser. Or scan the printed QR with the Camera app (it logs you
   in for you).
3. Enter the **auth code** → **Connect**.
4. Use it:
   - **🎛 Conductor** (header) → browse projects/chats, open a chat to read the
     transcript, type into the box and **Send** to give that agent a command.
   - **Terminal** → `ls`, `cd`, `git status`, anything; `cd` persists between
     commands. Quick-tap buttons for `ls -la` / `pwd` / `clear`, and ▲/▼ recall
     history.
   - **☕ Awake toggle** (top-right) → keeps the Mac awake via `caffeinate` so
     commands keep landing while you're away.

Works on iPhone, Android, iPad, or another computer — anything with a browser on
your Tailnet. No app install required.

> If the phone won't connect it's almost always (a) Tailscale off / wrong IP,
> (b) the server isn't running or a firewall blocks the port, or (c) you opened
> the page over `https` while the socket is `ws://` — use the exact `http://…:8080`
> URL that `start.py` prints.

---

## Optional: native iOS app

The web terminal already works great on the phone, so the native app is only if
you want a home-screen icon.

1. In Xcode, create a new **iOS App** project (SwiftUI, named `MacRemote`).
2. Replace the generated `MacRemoteApp.swift` / `ContentView.swift` with the
   files in `ios/MacRemote/`.
3. Run on your iPhone, enter the Mac's Tailscale IP + code, and connect.

> Because it connects over plain `ws://`, add an **App Transport Security**
> exception (`NSAllowsLocalNetworking` or an ATS exception for the Tailscale
> host). The Tailscale tunnel itself is encrypted end-to-end.

---

## Protocol reference

**Conductor (client → server), returns JSON the web UI parses:**

| Message | Result |
|---------|--------|
| `CDT:projects` | list of repos/projects |
| `CDT:sessions` | all chats with project, status, unread |
| `CDT:messages:<sessionId>` | recent transcript of a chat |
| `CDT:send:<sessionId>:<text>` | queue `<text>` into that chat (needs token) |

**General commands:**

| Message | Action on Mac |
|---------|---------------|
| `CMD:<shell>` | Run `<shell>` in the session's cwd; return output. `cd` persists |
| `PWD` | Return the current working directory |
| `AWAKE_ON` / `AWAKE_OFF` | Start/stop `caffeinate` (keep Mac + display awake) |
| `AWAKE_STATUS` | Report whether keep-awake is on |
| `NEW_CHAT` | Click the `new_chat` coordinate (pyautogui) |
| `NEXT_CHAT` / `PREV_CHAT` | Click `next_chat` / `prev_chat` (if defined) |
| `TYPE:<text>` | Click `input_box`, type `<text>`, press Enter |

---

## Notes & hardening

- **Auth:** a 6-digit code (fixed or regenerated each start) that locks a client
  after `MAX_AUTH_ATTEMPTS` wrong tries.
- **Fail-safe:** slam the mouse into any screen corner to instantly abort UI
  automation (`pyautogui.FAILSAFE`).
- **Read-only DB access:** Conductor's database is opened read-only — browsing
  never disturbs the live app.
- Secrets (`.env`) and your real `coordinates.json` are git-ignored.
- This is meant for controlling **your own** Mac over **your own** Tailnet.
  Don't expose port `8765` / `8080` to the public internet.
