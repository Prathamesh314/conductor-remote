# Sign-in flow (email code + session tokens)

Before a phone can control the Mac it must **sign in**. Instead of one shared
code, each user signs in with their **email**, receives a one-time code, and is
then issued **session + refresh tokens** so they stay signed in for days.

Everything is stored in a local SQLite DB (`server/auth.db`, git-ignored) — it
never touches Conductor's own database. Codes and tokens are stored **hashed**
(SHA-256); tokens are random URL-safe strings.

## The flow

```
 Phone                              Mac server (auth.py + server.py)         SQLite (auth.db)
   │                                          │                                    │
   │  1. open ws://mac:8765                    │                                    │
   │─────────────────────────────────────────▶│                                    │
   │                                          │                                    │
   │  2. {auth:"request", email}               │  validate allowlist                │
   │─────────────────────────────────────────▶│  make 6-digit code ───────────────▶│ users, codes
   │                                          │  email the code ──► inbox           │
   │  ◀───────────── {auth:"code_sent"}         │                                    │
   │                                          │                                    │
   │  3. {auth:"verify", email, code}          │  check code (hash, expiry, tries)  │
   │─────────────────────────────────────────▶│  mint tokens ─────────────────────▶│ sessions
   │  ◀── {auth:"ok", session_token,           │                                    │
   │        refresh_token, expires_at, …}       │                                    │
   │      store tokens on device               │                                    │
   │                                          │                                    │
   │  ===== authenticated: normal commands (CMD:, CDT:, AWAKE_*) =====              │
   │                                          │                                    │
   │  4. (next launch) {auth:"session", token} │  validate session token            │
   │─────────────────────────────────────────▶│                                    │
   │  ◀───────────── {auth:"ok", …}             │                                    │
   │                                          │                                    │
   │  4b. if expired: {auth:"refresh", token}  │  rotate tokens ───────────────────▶│ sessions
   │─────────────────────────────────────────▶│                                    │
   │  ◀── {auth:"ok", session_token, …}         │                                    │
   │                                          │                                    │
   │  5. {auth:"logout"}                        │  delete session row ──────────────▶│ sessions
   │─────────────────────────────────────────▶│                                    │
   │  ◀───────────── {auth:"logged_out"}  (socket closes)                           │
```

1. **Request** — the phone submits its email. The server checks the allowlist
   (`AUTH_ALLOWED_EMAILS`), saves the user, generates a 6-digit code, stores it
   (hashed, ~10 min expiry), and emails it. → `{auth:"code_sent"}`.
2. **Verify** — the phone submits the code. On a match the server mints a
   **session token** (default 7 days) + **refresh token** (default 30 days),
   stores them, and returns them. → `{auth:"ok", …tokens}`. Now authenticated.
3. **Reconnect** — later the phone reconnects and sends `{auth:"session", token}`
   (no email needed). If the session expired it sends `{auth:"refresh", token}`
   to rotate into a fresh session. Both tokens rotate on refresh.
4. **Logout** — `{auth:"logout"}` deletes the session row; the phone forgets its
   tokens.

## WebSocket auth protocol

All pre-auth messages are JSON strings on the existing `ws://<mac>:8765` socket.

| Client sends | Server replies (JSON) |
| --- | --- |
| `{"auth":"request","email":"…"}` | `{"auth":"code_sent","email":…}` or `{"auth":"error","code":…,"error":…}` |
| `{"auth":"verify","email":"…","code":"123456"}` | `{"auth":"ok","email","session_token","refresh_token","expires_at","refresh_expires_at"}` or `{"auth":"error",…}` |
| `{"auth":"session","token":"…"}` | `{"auth":"ok","email","expires_at"}` or `{"auth":"error","code":"expired"|"invalid"}` |
| `{"auth":"refresh","token":"…"}` | `{"auth":"ok",…rotated tokens}` or `{"auth":"error",…}` |
| `{"auth":"logout"}` (after auth) | `{"auth":"logged_out"}` then the socket closes |

Error `code` values: `bad_email`, `denied`, `rate_limited`, `email_failed`,
`no_code`, `expired`, `too_many_attempts`, `invalid`, `bad_request`.

After `{"auth":"ok"}` the connection is authenticated and the normal command
protocol (`CMD:`, `CDT:*`, `AWAKE_*`) works exactly as before.

**Legacy fallback:** sending a bare numeric code still returns the plain-text
`AUTH_SUCCESS` (so the printed connect URL keeps working). Disable with
`AUTH_LEGACY_CODE=0` to require email sign-in for everyone.

## Who can sign in (security)

Allowing *any* email to sign in would let anyone on your Tailnet control the Mac.
So sign-in is gated by an allowlist:

- `AUTH_ALLOWED_EMAILS` — comma-separated emails allowed to sign in.
- If empty, it falls back to `EMAIL_RECEIVER`.
- If that's empty too, **any** email is allowed — dev only; the server warns.

Other guards: codes expire (`AUTH_CODE_TTL_MIN`), are single-use, and lock after
`AUTH_CODE_MAX_ATTEMPTS` wrong tries; a per-connection attempt limit
(`MAX_AUTH_ATTEMPTS`) still applies; refresh tokens rotate on every use.

## Config

See `.env.example` for `AUTH_ALLOWED_EMAILS`, `AUTH_SESSION_TTL_DAYS`,
`AUTH_REFRESH_TTL_DAYS`, `AUTH_CODE_TTL_MIN`, `AUTH_CODE_MAX_ATTEMPTS`,
`AUTH_DB`, `AUTH_DEBUG_CODE`, and `AUTH_LEGACY_CODE`.

## Local testing without email

Set `AUTH_DEBUG_CODE=1` to print the code to the server console and include it in
the `code_sent` reply (both clients pre-fill it). Never enable this in a real
deployment. You can also drive the store directly:

```bash
python3 auth.py request you@email.com
python3 auth.py verify  you@email.com 123456
python3 auth.py validate <session_token>
python3 auth.py refresh  <refresh_token>
python3 auth.py logout   <token>
```
