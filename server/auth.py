"""Email-code sign-in with session + refresh tokens, backed by SQLite.

This replaces the single shared auth code with a per-user flow:

  1. The phone submits an email address.
  2. We save the user, generate a 6-digit one-time code, store it (hashed) with a
     short expiry, and email it to that address.
  3. The phone submits the code. On a match we mint a long-lived *session token*
     and a longer-lived *refresh token*, store them, and hand them back.
  4. The phone reconnects later with the session token (no email needed) until it
     expires; then it silently swaps the refresh token for a fresh session.
  5. Logout deletes the stored tokens.

Everything lives in a local SQLite DB (default `server/auth.db`, git-ignored) so
it never touches Conductor's own database. Tokens are random URL-safe strings;
codes and tokens are stored as SHA-256 hashes, never in the clear.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

# --- Configuration (from environment / .env) --------------------------------
_HERE = Path(__file__).parent
AUTH_DB = os.environ.get("AUTH_DB", str(_HERE / "auth.db"))

SESSION_TTL_DAYS = float(os.environ.get("AUTH_SESSION_TTL_DAYS", "7"))
REFRESH_TTL_DAYS = float(os.environ.get("AUTH_REFRESH_TTL_DAYS", "30"))
CODE_TTL_MIN = float(os.environ.get("AUTH_CODE_TTL_MIN", "10"))
CODE_MAX_ATTEMPTS = int(os.environ.get("AUTH_CODE_MAX_ATTEMPTS", "5"))
# Don't email a new code more than once per this many seconds (anti-spam).
CODE_RESEND_COOLDOWN_S = float(os.environ.get("AUTH_CODE_RESEND_COOLDOWN_S", "30"))

# Who may sign in. Comma-separated allowlist; if empty we fall back to
# EMAIL_RECEIVER (the address the old flow mailed), and if that's empty too we
# allow ANY email (dev only — a startup warning is printed by server.py).
_ALLOWED_RAW = os.environ.get("AUTH_ALLOWED_EMAILS", "").strip()
_EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "").strip()

# Print the code to the server console / return it to the client for local
# testing when email isn't set up. NEVER enable in a real deployment.
DEBUG_CODE = os.environ.get("AUTH_DEBUG_CODE", "0").strip().lower() not in ("0", "false", "no", "")

# SMTP (shared with server.py's email config).
_SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
_SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
_EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "").strip()
_EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_lock = threading.Lock()  # serialize writes; sqlite + threads want care


# --- Helpers ----------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or ""))


def allowed_emails() -> list[str]:
    if _ALLOWED_RAW:
        return [normalize_email(e) for e in _ALLOWED_RAW.split(",") if e.strip()]
    if _EMAIL_RECEIVER:
        return [normalize_email(_EMAIL_RECEIVER)]
    return []  # empty => allow any (dev)


def is_email_allowed(email: str) -> bool:
    allow = allowed_emails()
    return not allow or normalize_email(email) in allow


def email_configured() -> bool:
    return bool(_EMAIL_SENDER and _EMAIL_PASSWORD)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(AUTH_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def _db():
    """A connection that commits on clean exit and always closes (no leaks)."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create the auth tables if they don't exist. Safe to call on every start."""
    with _lock, _db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                email          TEXT PRIMARY KEY,
                created_at     TEXT NOT NULL,
                last_login_at  TEXT
            );
            CREATE TABLE IF NOT EXISTS codes (
                email        TEXT PRIMARY KEY,          -- one active code per email
                code_hash    TEXT NOT NULL,
                expires_at   TEXT NOT NULL,
                attempts     INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                session_hash        TEXT PRIMARY KEY,
                refresh_hash        TEXT NOT NULL UNIQUE,
                email               TEXT NOT NULL,
                created_at          TEXT NOT NULL,
                session_expires_at  TEXT NOT NULL,
                refresh_expires_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_email ON sessions(email);
            """
        )


# --- Sign-in: request a code ------------------------------------------------
def request_code(email: str) -> dict:
    """Generate + email a fresh 6-digit code for `email`.

    Returns {"ok": True, "email": ...} on success (and, if DEBUG_CODE, "code").
    On failure returns {"ok": False, "error": msg, "code": reason} where reason
    is one of: bad_email, denied, rate_limited, email_failed.
    """
    email = normalize_email(email)
    if not is_valid_email(email):
        return {"ok": False, "code": "bad_email", "error": "Enter a valid email address."}
    if not is_email_allowed(email):
        return {"ok": False, "code": "denied", "error": "This email isn't allowed to sign in."}

    code = f"{secrets.randbelow(1_000_000):06d}"
    now = _now()
    with _lock, _db() as c:
        row = c.execute("SELECT created_at FROM codes WHERE email=?", (email,)).fetchone()
        if row:
            try:
                last = datetime.fromisoformat(row["created_at"])
                if (now - last).total_seconds() < CODE_RESEND_COOLDOWN_S:
                    return {"ok": False, "code": "rate_limited",
                            "error": "A code was just sent — wait a moment before retrying."}
            except ValueError:
                pass
        c.execute(
            "INSERT INTO users(email, created_at) VALUES(?, ?) "
            "ON CONFLICT(email) DO NOTHING",
            (email, _iso(now)),
        )
        c.execute(
            "INSERT INTO codes(email, code_hash, expires_at, attempts, created_at) "
            "VALUES(?, ?, ?, 0, ?) "
            "ON CONFLICT(email) DO UPDATE SET "
            "  code_hash=excluded.code_hash, expires_at=excluded.expires_at, "
            "  attempts=0, created_at=excluded.created_at",
            (email, _hash(code), _iso(now + timedelta(minutes=CODE_TTL_MIN)), _iso(now)),
        )

    sent = _email_code(email, code)
    if not sent and not DEBUG_CODE:
        return {"ok": False, "code": "email_failed",
                "error": "Couldn't send the code email — check the server's email settings."}
    result = {"ok": True, "email": email}
    if DEBUG_CODE:
        result["code"] = code  # local testing only
        print(f"[auth][DEBUG] code for {email}: {code}")
    return result


# --- Sign-in: verify the code ----------------------------------------------
def verify_code(email: str, code: str) -> dict:
    """Check a submitted code and, on success, mint session + refresh tokens.

    Returns {"ok": True, "email", "session_token", "refresh_token",
             "expires_at", "refresh_expires_at"} or
            {"ok": False, "error": msg, "code": reason}
    reason ∈ {no_code, expired, too_many_attempts, invalid}.
    """
    email = normalize_email(email)
    code = (code or "").strip()
    now = _now()
    with _lock, _db() as c:
        row = c.execute("SELECT code_hash, expires_at, attempts FROM codes WHERE email=?",
                        (email,)).fetchone()
        if not row:
            return {"ok": False, "code": "no_code", "error": "Request a code first."}
        if _now() > _parse(row["expires_at"], now):
            c.execute("DELETE FROM codes WHERE email=?", (email,))
            return {"ok": False, "code": "expired", "error": "That code expired — request a new one."}
        if row["attempts"] >= CODE_MAX_ATTEMPTS:
            c.execute("DELETE FROM codes WHERE email=?", (email,))
            return {"ok": False, "code": "too_many_attempts",
                    "error": "Too many wrong tries — request a new code."}
        if not secrets.compare_digest(row["code_hash"], _hash(code)):
            c.execute("UPDATE codes SET attempts=attempts+1 WHERE email=?", (email,))
            return {"ok": False, "code": "invalid", "error": "Wrong code — try again."}

        # Success: consume the code and issue tokens.
        c.execute("DELETE FROM codes WHERE email=?", (email,))
        c.execute("UPDATE users SET last_login_at=? WHERE email=?", (_iso(now), email))
        tokens = _issue_session(c, email, now)
    return {"ok": True, "email": email, **tokens}


# --- Reconnect with a saved session token -----------------------------------
def validate_session(session_token: str) -> dict:
    """True-ish result if the session token is valid and unexpired.

    Returns {"ok": True, "email", "expires_at"} or
            {"ok": False, "code": "expired"|"invalid", "error": msg}.
    """
    if not session_token:
        return {"ok": False, "code": "invalid", "error": "No session token."}
    now = _now()
    with _lock, _db() as c:
        row = c.execute(
            "SELECT email, session_expires_at FROM sessions WHERE session_hash=?",
            (_hash(session_token),),
        ).fetchone()
        if not row:
            return {"ok": False, "code": "invalid", "error": "Session not recognized."}
        if now > _parse(row["session_expires_at"], now):
            return {"ok": False, "code": "expired", "error": "Session expired — refresh or sign in again."}
    return {"ok": True, "email": row["email"], "expires_at": row["session_expires_at"]}


def refresh_session(refresh_token: str) -> dict:
    """Swap a valid refresh token for a fresh session (and refresh) token.

    Rotates both tokens. Returns the same shape as verify_code on success, else
    {"ok": False, "code": "expired"|"invalid", "error": msg}.
    """
    if not refresh_token:
        return {"ok": False, "code": "invalid", "error": "No refresh token."}
    now = _now()
    with _lock, _db() as c:
        row = c.execute(
            "SELECT email, refresh_expires_at FROM sessions WHERE refresh_hash=?",
            (_hash(refresh_token),),
        ).fetchone()
        if not row:
            return {"ok": False, "code": "invalid", "error": "Refresh token not recognized."}
        if now > _parse(row["refresh_expires_at"], now):
            c.execute("DELETE FROM sessions WHERE refresh_hash=?", (_hash(refresh_token),))
            return {"ok": False, "code": "expired", "error": "Session fully expired — sign in again."}
        c.execute("DELETE FROM sessions WHERE refresh_hash=?", (_hash(refresh_token),))
        tokens = _issue_session(c, row["email"], now)
    return {"ok": True, "email": row["email"], **tokens}


def logout(session_token: str = "", refresh_token: str = "") -> dict:
    """Delete the session row(s) matching either token. Always returns ok."""
    with _lock, _db() as c:
        if session_token:
            c.execute("DELETE FROM sessions WHERE session_hash=?", (_hash(session_token),))
        if refresh_token:
            c.execute("DELETE FROM sessions WHERE refresh_hash=?", (_hash(refresh_token),))
    return {"ok": True}


# --- internals --------------------------------------------------------------
def _issue_session(c: sqlite3.Connection, email: str, now: datetime) -> dict:
    """Create + store a new session/refresh pair. Returns the plaintext tokens."""
    session_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(32)
    s_exp = now + timedelta(days=SESSION_TTL_DAYS)
    r_exp = now + timedelta(days=REFRESH_TTL_DAYS)
    c.execute(
        "INSERT INTO sessions(session_hash, refresh_hash, email, created_at, "
        "session_expires_at, refresh_expires_at) VALUES(?, ?, ?, ?, ?, ?)",
        (_hash(session_token), _hash(refresh_token), email, _iso(now), _iso(s_exp), _iso(r_exp)),
    )
    return {
        "session_token": session_token,
        "refresh_token": refresh_token,
        "expires_at": _iso(s_exp),
        "refresh_expires_at": _iso(r_exp),
    }


def _parse(iso: str, default: datetime) -> datetime:
    try:
        return datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return default


def _email_code(to_email: str, code: str) -> bool:
    """Email the 6-digit code. Returns True on success, False if not configured
    or the send failed."""
    if not email_configured():
        print("[auth] email not configured (EMAIL_SENDER/EMAIL_PASSWORD) — cannot send code.")
        return False
    try:
        msg = EmailMessage()
        msg.set_content(
            f"Your Mac Remote sign-in code is: {code}\n\n"
            f"It expires in {int(CODE_TTL_MIN)} minutes. If you didn't request it, ignore this email."
        )
        msg["Subject"] = f"Mac Remote code: {code}"
        msg["From"] = _EMAIL_SENDER
        msg["To"] = to_email
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT, context=context) as smtp:
            smtp.login(_EMAIL_SENDER, _EMAIL_PASSWORD)
            smtp.send_message(msg)
        print(f"[auth] code emailed to {to_email}.")
        return True
    except Exception as exc:  # noqa: BLE001 - bad creds / no network
        print(f"[auth] code email failed: {exc}")
        return False


def print_startup_notes() -> None:
    """Warn about insecure / non-functional sign-in configs at startup."""
    if not email_configured():
        print("[auth] WARNING: EMAIL_SENDER/EMAIL_PASSWORD not set — email sign-in "
              "can't send codes. Set them, or use the legacy connect URL.")
    if not allowed_emails():
        print("[auth] WARNING: no AUTH_ALLOWED_EMAILS (and no EMAIL_RECEIVER) — "
              "ANY email can sign in and control this Mac. Set AUTH_ALLOWED_EMAILS.")
    else:
        print(f"[auth] sign-in allowed for: {', '.join(allowed_emails())}")


def purge_expired() -> None:
    """Best-effort cleanup of expired codes/sessions (called opportunistically)."""
    now = _iso(_now())
    try:
        with _lock, _db() as c:
            c.execute("DELETE FROM codes WHERE expires_at < ?", (now,))
            c.execute("DELETE FROM sessions WHERE refresh_expires_at < ?", (now,))
    except Exception:  # noqa: BLE001
        pass


# --- tiny self-test CLI -----------------------------------------------------
if __name__ == "__main__":
    import sys
    init_db()
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
    elif argv[0] == "request" and len(argv) > 1:
        print(request_code(argv[1]))
    elif argv[0] == "verify" and len(argv) > 2:
        print(verify_code(argv[1], argv[2]))
    elif argv[0] == "validate" and len(argv) > 1:
        print(validate_session(argv[1]))
    elif argv[0] == "refresh" and len(argv) > 1:
        print(refresh_session(argv[1]))
    elif argv[0] == "logout" and len(argv) > 1:
        print(logout(session_token=argv[1], refresh_token=argv[1]))
    else:
        print("usage: auth.py [request <email> | verify <email> <code> | "
              "validate <token> | refresh <token> | logout <token>]")
