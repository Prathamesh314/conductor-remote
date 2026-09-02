"""Bridge to the Conductor desktop app.

Reads projects / chats / messages directly from Conductor's local SQLite DB
(read-only, no token needed), and sends new messages via the Conductor CLI
(which talks to the Conductor API and needs CONDUCTOR_API_TOKEN).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from urllib.parse import quote

_SUPPORT = os.path.expanduser("~/Library/Application Support/com.conductor.app")
DB_PATH = os.environ.get("CONDUCTOR_DB", os.path.join(_SUPPORT, "conductor.db"))
CLI_PATH = os.environ.get("CONDUCTOR_CLI", os.path.join(_SUPPORT, "bin", "conductor"))
API_TOKEN = os.environ.get("CONDUCTOR_API_TOKEN", "").strip()


def available() -> bool:
    return os.path.exists(DB_PATH)


def _connect() -> sqlite3.Connection:
    # Read-only so we never disturb the live app.
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def list_projects() -> list[dict]:
    with _connect() as c:
        rows = c.execute(
            "SELECT id, name, default_branch, root_path FROM repos "
            "WHERE COALESCE(hidden,0)=0 ORDER BY display_order, name"
        ).fetchall()
    return [dict(r) for r in rows]


def repo_path_for_session(session_id: str) -> str | None:
    with _connect() as c:
        row = c.execute(
            """
            SELECT r.root_path
            FROM sessions s
            LEFT JOIN workspaces w ON s.workspace_id = w.id
            LEFT JOIN repos r ON w.repository_id = r.id
            WHERE s.id = ?
            """,
            (session_id,),
        ).fetchone()
    return row["root_path"] if row and row["root_path"] else None


def list_sessions() -> list[dict]:
    """All chats, newest first, with their workspace + project names."""
    with _connect() as c:
        rows = c.execute(
            """
            SELECT s.id, s.title, s.status,
                   COALESCE(s.unread_count,0) AS unread,
                   s.updated_at, s.model,
                   w.workspace_name, w.branch,
                   r.name AS project, r.id AS project_id
            FROM sessions s
            LEFT JOIN workspaces w ON s.workspace_id = w.id
            LEFT JOIN repos r ON w.repository_id = r.id
            WHERE COALESCE(s.is_hidden,0)=0
            ORDER BY s.updated_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def _extract_text(raw: str) -> str:
    """Turn a stored message (plain text or Claude-Code JSON) into readable text."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not raw.startswith("{"):
        return raw  # plain text the user typed
    try:
        obj = json.loads(raw)
    except Exception:  # noqa: BLE001 - not JSON after all
        return raw
    msg = obj.get("message", obj) if isinstance(obj, dict) else obj
    content = msg.get("content") if isinstance(msg, dict) else None
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        t = block.get("type")
        if t == "text":
            parts.append(block.get("text", ""))
        elif t == "tool_use":
            parts.append(f"› {block.get('name', 'tool')}")
        # tool_result / thinking are omitted to keep the transcript readable
    return "\n".join(p for p in parts if p).strip()


def get_messages(session_id: str, limit: int = 40) -> list[dict]:
    with _connect() as c:
        rows = c.execute(
            """
            SELECT role, content, sent_at, created_at
            FROM session_messages
            WHERE session_id=? AND content IS NOT NULL AND content!=''
            ORDER BY created_at DESC LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    out: list[dict] = []
    for r in reversed(rows):  # back to chronological order
        text = _extract_text(r["content"])
        if text:
            out.append(
                {"role": r["role"], "text": text[:4000],
                 "at": r["sent_at"] or r["created_at"]}
            )
    return out


def session_title(session_id: str) -> str:
    with _connect() as c:
        row = c.execute(
            "SELECT title FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
    return (row["title"] if row else None) or "Chat"


def deeplink_url(prompt: str, repo_path: str | None = None) -> str:
    """Build a conductor:// deep link that creates a new task with `prompt`."""
    url = "conductor://prompt=" + quote(prompt, safe="")
    if repo_path:
        url += "&path=" + quote(repo_path, safe="")
    return url


def new_task(prompt: str, repo_path: str | None = None) -> dict:
    """Create a new Conductor task/workspace with a prompt (FREE, no token).

    Uses the official conductor:// deep link, opened via `open`.
    """
    url = deeplink_url(prompt, repo_path)
    try:
        subprocess.run(["open", url], check=True, timeout=10)
        where = repo_path or "the first available repo"
        return {"ok": True, "mode": "deeplink",
                "note": f"Started a NEW Conductor task in {where}."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "mode": "deeplink", "error": str(exc)}


def new_task_for_session(session_id: str, prompt: str) -> dict:
    """Free send: start a new task in the same project as the given chat."""
    return new_task(prompt, repo_path_for_session(session_id))


def send_message(session_id: str, text: str) -> dict:
    """Queue a user message into a session via the Conductor CLI."""
    if not API_TOKEN:
        return {
            "ok": False,
            "error": "CONDUCTOR_API_TOKEN not set. Add a Conductor API token to "
                     ".env to send messages (reading works without it).",
        }
    try:
        env = {**os.environ, "CONDUCTOR_API_TOKEN": API_TOKEN}
        res = subprocess.run(
            [CLI_PATH, "--json", "messages", "create",
             "--session", session_id, "--message", text],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if res.returncode == 0:
            return {"ok": True, "out": res.stdout.strip()[:400]}
        return {"ok": False, "error": (res.stderr or res.stdout).strip()[:400]}
    except Exception as exc:  # noqa: BLE001 - CLI missing / network
        return {"ok": False, "error": str(exc)}
