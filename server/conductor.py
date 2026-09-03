"""Bridge to the Conductor desktop app.

Reads projects / chats / messages directly from Conductor's local SQLite DB
(read-only, no token needed), and sends new messages via the Conductor CLI
(which talks to the Conductor API and needs CONDUCTOR_API_TOKEN).
"""

from __future__ import annotations

import json
import os
import re
import shutil
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

# Where "Add repo" clones new GitHub projects on the Mac. Conductor then adds the
# folder as a project. Defaults next to your other projects' parent if we can
# guess it, else ~/ConductorProjects.
PROJECTS_DIR = os.path.expanduser(
    os.environ.get("CONDUCTOR_PROJECTS_DIR", "~/ConductorProjects"))
# Seconds to allow a clone before giving up (big repos over slow links).
CLONE_TIMEOUT = float(os.environ.get("CONDUCTOR_CLONE_TIMEOUT", "600"))


def available() -> bool:
    return os.path.exists(DB_PATH)


# --- Add a GitHub repo as a local project -----------------------------------
def _parse_repo_url(raw: str) -> tuple[str | None, str | None, str | None]:
    """Normalize a user-supplied repo reference.

    Accepts `owner/repo`, `https://github.com/owner/repo[.git]`, or
    `git@host:owner/repo[.git]`. Returns (clone_target, repo_name, owner_repo)
    where owner_repo is "owner/repo" for GitHub (so we can use `gh`), else None.
    Returns (None, None, None) if it doesn't look like a git repo reference.
    """
    raw = (raw or "").strip()
    if not raw:
        return None, None, None
    # owner/repo shorthand (GitHub)
    if re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", raw):
        owner_repo = raw[:-4] if raw.endswith(".git") else raw
        return f"https://github.com/{owner_repo}.git", owner_repo.split("/")[-1], owner_repo
    # git@host:owner/repo(.git)
    m = re.fullmatch(r"git@([\w.-]+):(.+?)(?:\.git)?/?", raw)
    if m:
        path = m.group(2)
        owner_repo = path if m.group(1) == "github.com" else None
        return raw, path.split("/")[-1], owner_repo
    # http(s)://host/owner/repo(.git)
    m = re.fullmatch(r"https?://([\w.-]+)/(.+?)(?:\.git)?/?", raw)
    if m:
        path = m.group(2)
        owner_repo = path if m.group(1).endswith("github.com") else None
        return raw, path.split("/")[-1], owner_repo
    return None, None, None


def add_repo(raw_url: str) -> dict:
    """Clone a GitHub repo onto the Mac so it can be added as a Conductor project.

    Private repos work when the `gh` CLI is logged in (preferred) or git has
    stored credentials. Returns {"ok", "path", "name", "note"} on success, or
    {"ok": False, "error": ...}. Conductor has no local "add repo" API, so after
    cloning we bring Conductor to the front for the one-tap "add project" step.
    """
    target, name, owner_repo = _parse_repo_url(raw_url)
    if not target:
        return {"ok": False, "error": "That doesn't look like a GitHub URL or owner/repo."}
    name = re.sub(r"[^A-Za-z0-9._-]", "", name or "").lstrip(".") or "repo"
    if name in (".", ".."):
        name = "repo"

    dest = os.path.join(PROJECTS_DIR, name)
    if os.path.exists(dest):
        if os.path.isdir(os.path.join(dest, ".git")):
            _bring_conductor_forward()
            return {"ok": True, "path": dest, "name": name, "already": True,
                    "note": f"'{name}' is already cloned at {dest}. Add it in "
                            "Conductor: New project → choose this folder."}
        return {"ok": False, "error": f"{dest} already exists and isn't a git repo."}

    try:
        os.makedirs(PROJECTS_DIR, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "error": f"Can't create {PROJECTS_DIR}: {exc}"}

    # Prefer `gh repo clone` (uses your GitHub login → private repos just work).
    if owner_repo and shutil.which("gh"):
        cmd = ["gh", "repo", "clone", owner_repo, dest]
    else:
        cmd = ["git", "clone", target, dest]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=CLONE_TIMEOUT, env=os.environ)
    except subprocess.TimeoutExpired:
        _rmtree_quiet(dest)
        return {"ok": False, "error": f"Clone timed out after {int(CLONE_TIMEOUT)}s."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Clone failed to start: {exc}"}

    if res.returncode != 0:
        _rmtree_quiet(dest)   # don't leave a half-clone behind
        err = (res.stderr or res.stdout or "").strip().splitlines()
        msg = err[-1] if err else "unknown error"
        if "already exists" in msg:
            msg = "destination already exists."
        elif "Repository not found" in msg or "not found" in msg.lower():
            msg = "repository not found (private? check `gh auth login` on the Mac)."
        elif "Authentication" in msg or "could not read Username" in msg:
            msg = "authentication needed — run `gh auth login` on the Mac."
        return {"ok": False, "error": f"Clone failed: {msg}"}

    _bring_conductor_forward()
    return {"ok": True, "path": dest, "name": name,
            "note": f"Cloned {name} to {dest}. Add it in Conductor: "
                    "New project → choose this folder."}


def _rmtree_quiet(path: str) -> None:
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
    except OSError:
        pass


def _bring_conductor_forward() -> None:
    """Best-effort: make sure Conductor is open so the user can add the project."""
    try:
        import conductor_ui as _cui
        _cui.ensure_conductor()
    except Exception:  # noqa: BLE001
        pass


def list_models() -> dict:
    """Available agents and their model ids / effort levels / defaults.

    Reads `conductor models --json` (works without a token). Returns a normalized
    shape the phone can render a picker from:

        {"agents": [{"agent": "claude", "models": [...], "efforts": [...],
                     "default_model": "sonnet", "default_effort": "high",
                     "fast_mode_models": [...]}],
         "cloud": <bool>}   # whether picking a model actually creates a cloud task

    On any failure returns {"agents": [], "error": "..."}.
    """
    if not os.path.exists(CLI_PATH):
        return {"agents": [], "error": "Conductor CLI not found — is Conductor installed?"}
    try:
        res = subprocess.run([CLI_PATH, "--json", "models"],
                             capture_output=True, text=True, timeout=20)
        if res.returncode != 0:
            return {"agents": [], "error": (res.stderr or res.stdout).strip()[:300]}
        raw = json.loads(res.stdout or "{}")
    except Exception as exc:  # noqa: BLE001 - CLI missing / bad JSON
        return {"agents": [], "error": str(exc)}

    agents = []
    for a in raw.get("agents", []):
        agents.append({
            "agent": a.get("agent"),
            "models": a.get("models", []),
            "efforts": a.get("efforts", []),
            "default_model": a.get("defaultModel"),
            "default_effort": a.get("defaultEffort"),
            "fast_mode_models": a.get("fastModeModels", []),
        })
    return {"agents": agents}


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


def workspace_id_for_session(session_id: str) -> str | None:
    """The stable workspace id for a session — used to open the EXACT chat via a
    conductor://workspace/<id> deep link (deterministic, no sidebar OCR)."""
    with _connect() as c:
        row = c.execute(
            "SELECT workspace_id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return row["workspace_id"] if row and row["workspace_id"] else None


def list_sessions() -> list[dict]:
    """Chats, newest first, mirroring what the Conductor app shows.

    Conductor's sidebar is workspace-centric: it shows exactly one chat per
    workspace (labelled by the workspace, not the session title), even for a
    brand-new workspace whose only session is still an empty "Untitled" draft.
    A single workspace can accumulate several sessions over time, but the app
    still shows it as one chat. So to match the counts the Mac shows we:

      * skip hidden / remote-archived sessions;
      * skip sessions in an archived workspace;
      * collapse each workspace to a single row, keeping its most recently
        updated session as the representative chat.

    (Sessions with no workspace — none exist today — are treated as their own
    single-row "workspace" via COALESCE, so they are never merged together.)
    """
    with _connect() as c:
        rows = c.execute(
            """
            SELECT id, workspace_id, title, status, unread, updated_at, model,
                   workspace_name, directory_name, branch, project, project_id
            FROM (
                SELECT s.id, s.workspace_id, s.title, s.status,
                       COALESCE(s.unread_count,0) AS unread,
                       s.updated_at, s.model,
                       w.workspace_name, w.directory_name, w.branch,
                       r.name AS project, r.id AS project_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY COALESCE(s.workspace_id, s.id)
                           ORDER BY s.updated_at DESC, s.created_at DESC
                       ) AS rn
                FROM sessions s
                LEFT JOIN workspaces w ON s.workspace_id = w.id
                LEFT JOIN repos r ON w.repository_id = r.id
                WHERE COALESCE(s.is_hidden,0)=0
                  AND s.remote_archived_at IS NULL
                  AND COALESCE(w.state, '') != 'archived'
            )
            WHERE rn = 1
            ORDER BY updated_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def newest_session_for_repo(repo_path: str | None, within_seconds: int = 180) -> str | None:
    """Id of the most recently created session in a repo (created recently).

    Used right after starting a new task so the phone can jump straight into
    the freshly created chat instead of staying on the old one.
    """
    if not repo_path:
        return None
    with _connect() as c:
        row = c.execute(
            """
            SELECT s.id
            FROM sessions s
            LEFT JOIN workspaces w ON s.workspace_id = w.id
            LEFT JOIN repos r ON w.repository_id = r.id
            WHERE r.root_path = ?
              AND julianday(s.created_at) >= julianday('now', ?)
            ORDER BY s.created_at DESC
            LIMIT 1
            """,
            (repo_path, f"-{int(within_seconds)} seconds"),
        ).fetchone()
    return row["id"] if row else None


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
        # tool_use / tool_result / thinking are omitted: the phone transcript
        # shows only the agent's actual replies, not Bash/Edit/Read tool calls.
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


def session_identity(session_id: str) -> dict:
    """The chat's *current* labels keyed to its stable id, so the client can
    refresh a chat it already has open when Conductor renames the branch.

    `id` and `workspace_id` never change; `branch`, `workspace_name`, `title`
    and `directory_name` may. The client should key on `id`/`workspace_id` and
    only use the rest for display — never as an identifier.
    """
    with _connect() as c:
        row = c.execute(
            """
            SELECT s.id, s.workspace_id, s.title,
                   w.branch, w.workspace_name, w.directory_name
            FROM sessions s
            LEFT JOIN workspaces w ON s.workspace_id = w.id
            WHERE s.id = ?
            """,
            (session_id,),
        ).fetchone()
    if not row:
        return {"id": session_id}
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "title": row["title"],
        "branch": row["branch"],
        "workspace_name": row["workspace_name"],
        "directory_name": row["directory_name"],
    }


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
                   w.user_set_workspace_name, w.user_set_branch_name,
                   w.placeholder_branch_name, w.branch,
                   w.DEPRECATED_city_name AS city
            FROM sessions s
            LEFT JOIN workspaces w ON s.workspace_id = w.id
            WHERE s.id = ?
            """,
            (session_id,),
        ).fetchone()

    terms: list[str] = []
    if row:
        branch = row["branch"]
        # directory_name is the STABLE city label Conductor shows and doesn't
        # rename, so it leads. The others cover whatever the sidebar currently
        # displays after a rename (user-set names, the live branch, its tail).
        for v in (row["directory_name"], row["workspace_name"],
                  row["user_set_workspace_name"], row["user_set_branch_name"],
                  row["placeholder_branch_name"], row["city"],
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


def new_task(prompt: str, repo_path: str | None = None,
             agent: str | None = None, model: str | None = None,
             effort: str | None = None) -> dict:
    """Create a new Conductor task/workspace with a prompt (FREE, no token).

    Uses the official conductor:// deep link, opened via `open`. The deep link
    only *pre-fills* the prompt (it can't carry a model), so — if a `model` was
    picked — we set it in the composer via UI automation before pressing send.
    (if AUTO_SUBMIT) we then press the send key to actually start the agent.
    """
    try:
        import conductor_ui as _cui
    except Exception:  # noqa: BLE001
        _cui = None

    # If Conductor is closed, launch it (full screen) first so the deep link
    # lands in a ready app instead of racing its cold start.
    try:
        if _cui and not _cui.conductor_running():
            _cui.ensure_conductor()
    except Exception:  # noqa: BLE001 - never block task creation on this
        pass

    url = deeplink_url(prompt, repo_path)
    try:
        subprocess.run(["open", url], check=True, timeout=10)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "mode": "deeplink", "error": f"open failed: {exc}"}

    where = repo_path or "the first available repo"
    note = f"Started a new Conductor task in {where}."

    def _settle_and_apply_model(settle: float) -> str:
        """Wait for the composer, then (if a model was picked) select it in the
        Conductor UI. Returns a short note describing the outcome."""
        time.sleep(settle)                 # also the pre-submit settle wait
        if not model:
            return ""
        if not _cui:
            return f" (Wanted {model}; UI automation unavailable.)"
        try:
            sel = _cui.select_model(model, agent)
        except Exception as exc:  # noqa: BLE001
            return f" (Couldn't set model {model}: {exc}.)"
        return (f" Model: {model}." if sel.get("ok")
                else f" (Wanted {model}: {sel.get('error', 'not found')}.)")

    if not AUTO_SUBMIT:
        # Give Conductor a moment to create the workspace, then hand back the
        # new session id so the phone can jump straight into it.
        model_note = _settle_and_apply_model(min(SUBMIT_DELAY, 3))
        return {"ok": True, "mode": "deeplink",
                "note": note + model_note + " Prompt pre-filled — press Enter in Conductor to send.",
                "new_session": newest_session_for_repo(repo_path)}

    model_note = _settle_and_apply_model(SUBMIT_DELAY)
    try:
        _submit_keystroke()
        return {"ok": True, "mode": "deeplink", "note": note + model_note + " Prompt sent ✓",
                "new_session": newest_session_for_repo(repo_path)}
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or "").strip()
        if "not allowed to send keystrokes" in err or "1002" in err:
            hint = ("Prompt is pre-filled but NOT sent — grant Accessibility "
                    "permission to the app running this server, then it will "
                    "auto-send. (Or press Enter in Conductor.)")
        else:
            hint = f"Prompt pre-filled; auto-send failed ({err[:80]}). Press Enter in Conductor."
        return {"ok": True, "mode": "deeplink", "submitted": False,
                "note": note + model_note + " " + hint}
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "mode": "deeplink", "submitted": False,
                "note": note + model_note + f" Auto-send failed: {exc}. Press Enter in Conductor."}


def new_task_for_session(session_id: str, prompt: str) -> dict:
    """Free send: start a new task in the same project as the given chat.

    Refuses (returns an error) if the project's git repo is missing on disk,
    rather than creating a workspace in the wrong place.
    """
    repo_path = repo_path_for_session(session_id)
    if not repo_path:
        return {"ok": False, "mode": "deeplink",
                "error": "Couldn't determine this chat's project repo."}
    if not os.path.isdir(repo_path):
        return {"ok": False, "mode": "deeplink", "repo_missing": True,
                "error": f"Project repo is missing on disk ({repo_path}); "
                         "not creating a new workspace."}
    return new_task(prompt, repo_path)


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
