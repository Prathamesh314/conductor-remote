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
import time
from urllib.parse import quote

_SUPPORT = os.path.expanduser("~/Library/Application Support/com.conductor.app")
DB_PATH = os.environ.get("CONDUCTOR_DB", os.path.join(_SUPPORT, "conductor.db"))
CLI_PATH = os.environ.get("CONDUCTOR_CLI", os.path.join(_SUPPORT, "bin", "conductor"))
API_TOKEN = os.environ.get("CONDUCTOR_API_TOKEN", "").strip()

# After a deep link pre-fills the prompt, press the send key so the agent
# actually starts (true remote fire-and-forget). Needs Accessibility permission.
AUTO_SUBMIT = os.environ.get("CONDUCTOR_AUTOSUBMIT", "1").strip().lower() not in ("0", "false", "no")
SUBMIT_DELAY = float(os.environ.get("CONDUCTOR_SUBMIT_DELAY", "4"))
# "enter" (default) or "cmd-enter" if your Conductor sends on ⌘-Enter.
SUBMIT_KEY = os.environ.get("CONDUCTOR_SUBMIT_KEY", "enter").strip().lower()


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


WORKSPACES_ROOT = os.path.expanduser("~/conductor/workspaces")


def build_tree() -> list[dict]:
    """Full project -> workspaces -> disk path tree (DB + disk verification)."""
    projects = list_projects()
    with _connect() as c:
        ws = c.execute(
            "SELECT id, repository_id, directory_name, branch, workspace_path "
            "FROM workspaces"
        ).fetchall()
    by_repo: dict[str, list] = {}
    for w in ws:
        by_repo.setdefault(w["repository_id"], []).append(dict(w))

    tree = []
    for p in projects:
        wss = []
        for w in by_repo.get(p["id"], []):
            path = w["workspace_path"]
            if not path and w["directory_name"]:
                path = os.path.join(WORKSPACES_ROOT, p["name"], w["directory_name"])
            wss.append({**w, "path": path,
                        "exists": bool(path and os.path.isdir(path))})
        tree.append({**p, "workspaces": wss})
    return tree


def session_nav_info(session_id: str) -> dict:
    """Everything needed to navigate the Conductor UI to a chat: the project it
    lives in, the workspace's on-screen names, and the chat title."""
    with _connect() as c:
        row = c.execute(
            """
            SELECT s.title, w.directory_name, w.branch, w.workspace_path,
                   r.name AS project
            FROM sessions s
            LEFT JOIN workspaces w ON s.workspace_id = w.id
            LEFT JOIN repos r ON w.repository_id = r.id
            WHERE s.id = ?
            """,
            (session_id,),
        ).fetchone()
    if not row:
        return {}
    branch = row["branch"]
    raw_terms = [row["directory_name"], branch]
    if branch and "/" in branch:
        raw_terms.append(branch.rsplit("/", 1)[-1])
    ws_terms: list[str] = []
    seen: set[str] = set()
    for v in raw_terms:
        if v and v.lower() not in seen:
            seen.add(v.lower())
            ws_terms.append(v)
    return {
        "project": row["project"],
        "workspace_terms": ws_terms,
        "session_terms": [row["title"]] if row["title"] else [],
        "workspace_path": row["workspace_path"],
    }


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


def session_search_terms(session_id: str) -> list[str]:
    """Candidate strings to look for on screen when locating this chat.

    Conductor's sidebar shows the workspace's directory/branch name (e.g.
    "istanbul"), not the chat title — so we return both, plus the branch's
    last path segment, deduped in priority order.
    """
    with _connect() as c:
        row = c.execute(
            """
            SELECT s.title, w.directory_name, w.workspace_name,
                   w.branch, w.DEPRECATED_city_name AS city
            FROM sessions s
            LEFT JOIN workspaces w ON s.workspace_id = w.id
            WHERE s.id = ?
            """,
            (session_id,),
        ).fetchone()

    terms: list[str] = []
    if row:
        branch = row["branch"]
        for v in (row["directory_name"], row["workspace_name"], row["city"],
                  branch, row["title"]):
            if v:
                terms.append(v)
        if branch and "/" in branch:
            terms.append(branch.rsplit("/", 1)[-1])

    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        key = t.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(t)
    return out


def deeplink_url(prompt: str, repo_path: str | None = None) -> str:
    """Build a conductor:// deep link that creates a new task with `prompt`."""
    url = "conductor://prompt=" + quote(prompt, safe="")
    if repo_path:
        url += "&path=" + quote(repo_path, safe="")
    return url


def _submit_keystroke() -> None:
    """Bring Conductor to the front and press the send key."""
    key = ("keystroke return using command down"
           if SUBMIT_KEY in ("cmd-enter", "cmd", "command", "cmd-return")
           else "keystroke return")
    script = (
        'tell application "Conductor" to activate\n'
        'delay 0.5\n'
        f'tell application "System Events" to {key}'
    )
    subprocess.run(["osascript", "-e", script], check=True, timeout=15,
                   capture_output=True, text=True)


def new_task(prompt: str, repo_path: str | None = None) -> dict:
    """Create a new Conductor task/workspace with a prompt (FREE, no token).

    Uses the official conductor:// deep link, opened via `open`. The deep link
    only *pre-fills* the prompt, so (if AUTO_SUBMIT) we then press the send key
    to actually start the agent.
    """
    url = deeplink_url(prompt, repo_path)
    try:
        subprocess.run(["open", url], check=True, timeout=10)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "mode": "deeplink", "error": f"open failed: {exc}"}

    where = repo_path or "the first available repo"
    note = f"Started a new Conductor task in {where}."

    if not AUTO_SUBMIT:
        return {"ok": True, "mode": "deeplink",
                "note": note + " Prompt pre-filled — press Enter in Conductor to send."}

    time.sleep(SUBMIT_DELAY)
    try:
        _submit_keystroke()
        return {"ok": True, "mode": "deeplink", "note": note + " Prompt sent ✓"}
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or "").strip()
        if "not allowed to send keystrokes" in err or "1002" in err:
            hint = ("Prompt is pre-filled but NOT sent — grant Accessibility "
                    "permission to the app running this server, then it will "
                    "auto-send. (Or press Enter in Conductor.)")
        else:
            hint = f"Prompt pre-filled; auto-send failed ({err[:80]}). Press Enter in Conductor."
        return {"ok": True, "mode": "deeplink", "submitted": False, "note": note + " " + hint}
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "mode": "deeplink", "submitted": False,
                "note": note + f" Auto-send failed: {exc}. Press Enter in Conductor."}


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
