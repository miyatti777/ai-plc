#!/usr/bin/env python3
"""AI-PLC DB Sync — Notion API ↔ .claude/db/ai_plc.db 双方向同期

Usage:
    python3 .claude/db/sync.py pull              # Notion → ローカル
    python3 .claude/db/sync.py push              # ローカル → Notion
    python3 .claude/db/sync.py sync              # 双方向 (pull → push)
    python3 .claude/db/sync.py status            # 差分プレビュー
    python3 .claude/db/sync.py pull --dry-run    # dry-run
    python3 .claude/db/sync.py push --dry-run    # dry-run

Requires: NOTION_API_TOKEN environment variable
"""

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_plc.db")

NOTION_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com"

# 自分の Notion DB ID を環境変数で指定する（Notion sync を使う場合のみ）:
#   export AI_PLC_PROJECTS_DB_ID=xxxxxxxx  /  export AI_PLC_TASKS_DB_ID=xxxxxxxx
PROJECTS_DB_ID = os.environ.get("AI_PLC_PROJECTS_DB_ID", "")
TASKS_DB_ID = os.environ.get("AI_PLC_TASKS_DB_ID", "")

RATE_LIMIT_DELAY = 0.35

# ── Notion API helpers ─────────────────────────────────────

def _get_token():
    token = os.environ.get("NOTION_API_TOKEN", "")
    if not token:
        env_files = [
            os.path.join(BASE, ".claude", "skills", "nsync", ".env"),
        ]
        for f in env_files:
            if os.path.exists(f):
                for line in open(f):
                    if line.startswith("NOTION_API_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        break
            if token:
                break
    if not token:
        print("ERROR: NOTION_API_TOKEN not set.")
        sys.exit(1)
    return token


TOKEN = None  # lazy init


def _headers():
    global TOKEN
    if TOKEN is None:
        TOKEN = _get_token()
    return {
        "Authorization": "Bearer " + TOKEN,
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _api_call(method, path, body=None, retries=3):
    url = NOTION_BASE + path if path.startswith("/") else path
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    for attempt in range(retries):
        try:
            time.sleep(RATE_LIMIT_DELAY)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("Retry-After", "2"))
                print("  Rate limited, waiting %ds..." % wait)
                time.sleep(wait)
                continue
            body_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
            print("API Error %d: %s %s" % (e.code, url, body_text[:300]))
            if attempt < retries - 1:
                time.sleep(1)
                continue
            raise
        except urllib.error.URLError as e:
            print("Network error: %s" % e.reason)
            if attempt < retries - 1:
                time.sleep(2)
                continue
            raise


def _query_db(db_id):
    """Query all rows from a Notion database (paginated)."""
    results = []
    body = {"page_size": 100}
    while True:
        resp = _api_call("POST", "/v1/databases/%s/query" % db_id, body)
        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        body["start_cursor"] = resp["next_cursor"]
    return results


# ── Property extractors ────────────────────────────────────

def _extract_title(prop):
    parts = prop.get("title", [])
    return "".join(p.get("plain_text", "") for p in parts) if parts else ""


def _extract_rich_text(prop):
    parts = prop.get("rich_text", [])
    return "".join(p.get("plain_text", "") for p in parts) if parts else ""


def _extract_select(prop):
    sel = prop.get("select")
    return sel["name"] if sel else None


def _extract_status(prop):
    st = prop.get("status")
    return st["name"] if st else None


def _extract_number(prop):
    return prop.get("number")


def _extract_date(prop):
    d = prop.get("date")
    if d and d.get("start"):
        return d["start"]
    return None


def _extract_url(prop):
    return prop.get("url")


def _extract_people(prop):
    people = prop.get("people", [])
    if people:
        return people[0].get("name", "unknown")
    return None


# ── Property builders (for Push) ───────────────────────────

def _build_title(text):
    if not text:
        return {"title": []}
    return {"title": [{"text": {"content": str(text)}}]}


def _build_rich_text(text):
    if not text:
        return {"rich_text": []}
    return {"rich_text": [{"text": {"content": str(text)}}]}


def _build_select(name):
    if not name:
        return {"select": None}
    return {"select": {"name": str(name)}}


def _build_status(name):
    if not name:
        return {"status": None}
    return {"status": {"name": str(name)}}


def _build_number(val):
    if val is None:
        return {"number": None}
    return {"number": float(val)}


def _build_date(iso_str):
    if not iso_str:
        return {"date": None}
    return {"date": {"start": str(iso_str)}}


def _build_url(url):
    if not url:
        return {"url": None}
    return {"url": str(url)}


# ── Row conversion ─────────────────────────────────────────

def _notion_row_to_project(page):
    props = page["properties"]
    return {
        "notion_page_id": page["id"],
        "scope_id": _extract_rich_text(props.get("Scope ID", {})) or "UNKNOWN",
        "name": _extract_title(props.get("PJ名", {})) or "Untitled",
        "goal": _extract_rich_text(props.get("Goal", {})),
        "owner": _extract_people(props.get("Owner", {})) or "",
        "status": _map_project_status(_extract_status(props.get("ステータス", {}))),
        "mode": _extract_select(props.get("モード", {})) or "direct",
        "depth": _extract_select(props.get("深度", {})) or "standard",
        "system": _extract_select(props.get("システム", {})) or "AI-PLC",
        "parent_scope": _extract_rich_text(props.get("親Scope", {})),
        "top_page_url": _extract_url(props.get("トップページ", {})),
        "start_date": _extract_date(props.get("開始日", {})),
        "deadline": _extract_date(props.get("期限", {})),
        "notion_last_edited": page.get("last_edited_time", ""),
    }


def _notion_row_to_task(page):
    props = page["properties"]
    return {
        "notion_page_id": page["id"],
        "task_id": _extract_rich_text(props.get("Task ID", {})) or "T000",
        "scope_id": _extract_rich_text(props.get("Scope ID", {})) or "UNKNOWN",
        "name": _extract_title(props.get("タスク名", {})) or "Untitled",
        "status": _extract_status(props.get("ステータス", {})) or "未着手",
        "type": _extract_select(props.get("タイプ", {})),
        "priority": _extract_select(props.get("優先度", {})) or "P1",
        "estimate_days": _extract_number(props.get("見積(日)", {})),
        "output_url": _extract_url(props.get("成果物", {})),
        "completed_at": _extract_date(props.get("完了日", {})),
        "notion_last_edited": page.get("last_edited_time", ""),
    }


def _project_to_notion_props(row):
    """Convert local project row → Notion properties dict (for PATCH)."""
    return {
        "PJ名": _build_title(row["name"]),
        "Goal": _build_rich_text(row["goal"]),
        "Scope ID": _build_rich_text(row["scope_id"]),
        "ステータス": _build_status(row["status"]),
        "モード": _build_select(row["mode"]),
        "深度": _build_select(row["depth"]),
        "システム": _build_select(row["system"]),
        "親Scope": _build_rich_text(row["parent_scope"]),
        "トップページ": _build_url(row["top_page_url"]),
        "開始日": _build_date(row["start_date"]),
        "期限": _build_date(row["deadline"]),
    }


def _task_to_notion_props(row):
    """Convert local task row → Notion properties dict (for PATCH)."""
    return {
        "タスク名": _build_title(row["name"]),
        "Task ID": _build_rich_text(row["task_id"]),
        "Scope ID": _build_rich_text(row["scope_id"]),
        "ステータス": _build_status(row["status"]),
        "タイプ": _build_select(row["type"]),
        "優先度": _build_select(row["priority"]),
        "見積(日)": _build_number(row["estimate_days"]),
        "成果物": _build_url(row["output_url"]),
        "完了日": _build_date(row["completed_at"]),
    }


def _map_project_status(s):
    mapping = {"planned": "planned", "active": "active",
               "completed": "completed", "paused": "paused"}
    return mapping.get((s or "").strip().lower(), "planned")


# ── DB helpers ─────────────────────────────────────────────

def _get_conn():
    if not os.path.exists(DB_PATH):
        print("DB not found: %s" % DB_PATH)
        print("Run: python3 .claude/db/init_db.py --import")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _meta_get(conn, key):
    row = conn.execute("SELECT value FROM _metadata WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def _meta_set(conn, key, value):
    conn.execute(
        "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
        (key, value)
    )


# ── PULL ───────────────────────────────────────────────────

def cmd_pull(dry_run=False):
    conn = _get_conn()
    now = _now_iso()
    stats = {"inserted": 0, "updated": 0, "skipped": 0, "conflict": 0}

    print("=== Pull: Notion → Local %s===" % ("(DRY RUN) " if dry_run else ""))

    # Projects
    print("\n[Projects] Querying Notion DB...")
    pages = _query_db(PROJECTS_DB_ID)
    print("  %d rows fetched from Notion" % len(pages))

    for page in pages:
        row = _notion_row_to_project(page)
        nid = row["notion_page_id"]
        local = conn.execute(
            "SELECT *, notion_last_edited, last_sync_at, updated_at FROM projects WHERE notion_page_id=?",
            (nid,)
        ).fetchone()

        if local is None:
            stats["inserted"] += 1
            if dry_run:
                print("  [INSERT] %s — %s" % (row["scope_id"], row["name"]))
            else:
                conn.execute("""
                    INSERT INTO projects
                        (notion_page_id, scope_id, name, goal, owner, status,
                         mode, depth, system, parent_scope, top_page_url,
                         start_date, deadline, notion_last_edited, last_sync_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (nid, row["scope_id"], row["name"], row["goal"],
                      row["owner"], row["status"], row["mode"], row["depth"],
                      row["system"], row["parent_scope"], row["top_page_url"],
                      row["start_date"], row["deadline"],
                      row["notion_last_edited"], now))
                print("  [INSERT] %s — %s" % (row["scope_id"], row["name"]))
        else:
            notion_newer = (row["notion_last_edited"] or "") > (local["notion_last_edited"] or "")
            never_synced = local["last_sync_at"] is None
            local_dirty = not never_synced and (local["last_sync_at"] or "") < (local["updated_at"] or "")

            if not notion_newer and not never_synced:
                stats["skipped"] += 1
                continue

            if local_dirty and notion_newer:
                stats["conflict"] += 1
                print("  [CONFLICT] %s — %s (both modified)" % (row["scope_id"], row["name"]))
                continue

            stats["updated"] += 1
            if dry_run:
                print("  [UPDATE] %s — %s" % (row["scope_id"], row["name"]))
            else:
                conn.execute("""
                    UPDATE projects SET
                        scope_id=?, name=?, goal=?, owner=?, status=?,
                        mode=?, depth=?, system=?, parent_scope=?, top_page_url=?,
                        start_date=?, deadline=?, notion_last_edited=?, last_sync_at=?
                    WHERE notion_page_id=?
                """, (row["scope_id"], row["name"], row["goal"],
                      row["owner"], row["status"], row["mode"], row["depth"],
                      row["system"], row["parent_scope"], row["top_page_url"],
                      row["start_date"], row["deadline"],
                      row["notion_last_edited"], now, nid))
                print("  [UPDATE] %s — %s" % (row["scope_id"], row["name"]))

    # Tasks
    print("\n[Tasks] Querying Notion DB...")
    pages = _query_db(TASKS_DB_ID)
    print("  %d rows fetched from Notion" % len(pages))

    for page in pages:
        row = _notion_row_to_task(page)
        nid = row["notion_page_id"]
        local = conn.execute(
            "SELECT *, notion_last_edited, last_sync_at, updated_at FROM tasks WHERE notion_page_id=?",
            (nid,)
        ).fetchone()

        if local is None:
            stats["inserted"] += 1
            if dry_run:
                print("  [INSERT] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))
            else:
                conn.execute("""
                    INSERT INTO tasks
                        (notion_page_id, task_id, scope_id, name, status,
                         type, priority, estimate_days, output_url,
                         completed_at, notion_last_edited, last_sync_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (nid, row["task_id"], row["scope_id"], row["name"],
                      row["status"], row["type"], row["priority"],
                      row["estimate_days"], row["output_url"],
                      row["completed_at"], row["notion_last_edited"], now))
                print("  [INSERT] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))
        else:
            notion_newer = (row["notion_last_edited"] or "") > (local["notion_last_edited"] or "")
            never_synced = local["last_sync_at"] is None
            local_dirty = not never_synced and (local["last_sync_at"] or "") < (local["updated_at"] or "")

            if not notion_newer and not never_synced:
                stats["skipped"] += 1
                continue

            if local_dirty and notion_newer:
                stats["conflict"] += 1
                print("  [CONFLICT] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))
                continue

            stats["updated"] += 1
            if dry_run:
                print("  [UPDATE] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))
            else:
                conn.execute("""
                    UPDATE tasks SET
                        task_id=?, scope_id=?, name=?, status=?,
                        type=?, priority=?, estimate_days=?, output_url=?,
                        completed_at=?, notion_last_edited=?, last_sync_at=?
                    WHERE notion_page_id=?
                """, (row["task_id"], row["scope_id"], row["name"],
                      row["status"], row["type"], row["priority"],
                      row["estimate_days"], row["output_url"],
                      row["completed_at"], row["notion_last_edited"], now, nid))
                print("  [UPDATE] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))

    if not dry_run:
        _meta_set(conn, "last_pull_at", now)
        conn.commit()

    conn.close()
    print("\n--- Pull Summary ---")
    print("  Inserted: %d  Updated: %d  Skipped: %d  Conflicts: %d" % (
        stats["inserted"], stats["updated"], stats["skipped"], stats["conflict"]))


# ── PUSH ───────────────────────────────────────────────────

def cmd_push(dry_run=False):
    conn = _get_conn()
    now = _now_iso()
    stats = {"pushed": 0, "created": 0, "skipped": 0}

    print("=== Push: Local → Notion %s===" % ("(DRY RUN) " if dry_run else ""))

    # Projects — find locally modified rows
    print("\n[Projects]")
    rows = conn.execute("""
        SELECT * FROM projects
        WHERE last_sync_at IS NULL
           OR updated_at > last_sync_at
    """).fetchall()

    for row in rows:
        nid = row["notion_page_id"]
        row_dict = dict(row)

        if nid:
            stats["pushed"] += 1
            props = _project_to_notion_props(row_dict)
            if dry_run:
                print("  [PATCH] %s — %s" % (row["scope_id"], row["name"]))
            else:
                _api_call("PATCH", "/v1/pages/%s" % nid,
                          {"properties": props})
                conn.execute(
                    "UPDATE projects SET last_sync_at=?, notion_last_edited=? WHERE id=?",
                    (now, now, row["id"])
                )
                print("  [PATCH] %s — %s" % (row["scope_id"], row["name"]))
        else:
            stats["created"] += 1
            props = _project_to_notion_props(row_dict)
            if dry_run:
                print("  [CREATE] %s — %s" % (row["scope_id"], row["name"]))
            else:
                resp = _api_call("POST", "/v1/pages", {
                    "parent": {"database_id": PROJECTS_DB_ID},
                    "properties": props,
                })
                new_id = resp["id"]
                conn.execute(
                    "UPDATE projects SET notion_page_id=?, last_sync_at=?, notion_last_edited=? WHERE id=?",
                    (new_id, now, resp.get("last_edited_time", now), row["id"])
                )
                print("  [CREATE] %s — %s (id: %s)" % (row["scope_id"], row["name"], new_id))

    # Tasks — find locally modified rows
    print("\n[Tasks]")
    rows = conn.execute("""
        SELECT * FROM tasks
        WHERE last_sync_at IS NULL
           OR updated_at > last_sync_at
    """).fetchall()

    for row in rows:
        nid = row["notion_page_id"]
        row_dict = dict(row)

        if nid:
            stats["pushed"] += 1
            props = _task_to_notion_props(row_dict)
            if dry_run:
                print("  [PATCH] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))
            else:
                _api_call("PATCH", "/v1/pages/%s" % nid,
                          {"properties": props})
                conn.execute(
                    "UPDATE tasks SET last_sync_at=?, notion_last_edited=? WHERE id=?",
                    (now, now, row["id"])
                )
                print("  [PATCH] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))
        else:
            stats["created"] += 1
            props = _task_to_notion_props(row_dict)
            if dry_run:
                print("  [CREATE] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))
            else:
                resp = _api_call("POST", "/v1/pages", {
                    "parent": {"database_id": TASKS_DB_ID},
                    "properties": props,
                })
                new_id = resp["id"]
                conn.execute(
                    "UPDATE tasks SET notion_page_id=?, last_sync_at=?, notion_last_edited=? WHERE id=?",
                    (new_id, now, resp.get("last_edited_time", now), row["id"])
                )
                print("  [CREATE] %s/%s — %s (id: %s)" % (
                    row["scope_id"], row["task_id"], row["name"], new_id))

    if not dry_run:
        _meta_set(conn, "last_push_at", now)
        conn.commit()

    conn.close()
    print("\n--- Push Summary ---")
    print("  Pushed: %d  Created: %d  Skipped: %d" % (
        stats["pushed"], stats["created"], stats["skipped"]))


# ── STATUS ─────────────────────────────────────────────────

def cmd_status():
    conn = _get_conn()
    last_pull = _meta_get(conn, "last_pull_at") or "(never)"
    last_push = _meta_get(conn, "last_push_at") or "(never)"

    print("=== AI-PLC DB Sync Status ===")
    print("  DB: %s" % DB_PATH)
    print("  Last Pull: %s" % last_pull)
    print("  Last Push: %s" % last_push)

    # Locally dirty rows
    dirty_projects = conn.execute("""
        SELECT scope_id, name, updated_at, last_sync_at FROM projects
        WHERE last_sync_at IS NULL OR updated_at > last_sync_at
    """).fetchall()
    dirty_tasks = conn.execute("""
        SELECT task_id, scope_id, name, updated_at, last_sync_at FROM tasks
        WHERE last_sync_at IS NULL OR updated_at > last_sync_at
    """).fetchall()

    # New rows (no notion_page_id)
    new_projects = conn.execute(
        "SELECT scope_id, name FROM projects WHERE notion_page_id IS NULL"
    ).fetchall()
    new_tasks = conn.execute(
        "SELECT task_id, scope_id, name FROM tasks WHERE notion_page_id IS NULL"
    ).fetchall()

    total_p = conn.execute("SELECT COUNT(*) c FROM projects").fetchone()["c"]
    total_t = conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]

    print("\n  Projects: %d total, %d dirty, %d new" % (
        total_p, len(dirty_projects), len(new_projects)))
    if dirty_projects:
        for r in dirty_projects:
            tag = "(new)" if r["last_sync_at"] is None else "(modified)"
            print("    %s %s — %s" % (tag, r["scope_id"], r["name"]))

    print("  Tasks: %d total, %d dirty, %d new" % (
        total_t, len(dirty_tasks), len(new_tasks)))
    if dirty_tasks:
        for r in dirty_tasks:
            tag = "(new)" if r["last_sync_at"] is None else "(modified)"
            print("    %s %s/%s — %s" % (tag, r["scope_id"], r["task_id"], r["name"]))

    conn.close()


# ── SYNC (bidirectional) ───────────────────────────────────

def cmd_sync(dry_run=False):
    print("=== Bidirectional Sync %s===\n" % ("(DRY RUN) " if dry_run else ""))
    print("--- Phase 1: Pull (Notion → Local) ---")
    cmd_pull(dry_run=dry_run)
    print("\n--- Phase 2: Push (Local → Notion) ---")
    cmd_push(dry_run=dry_run)
    print("\nSync complete.")


# ── Main ───────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    if not PROJECTS_DB_ID or not TASKS_DB_ID:
        print("ERROR: Notion sync を使うには、対象の Notion DB ID を環境変数で指定してください:")
        print("  export AI_PLC_PROJECTS_DB_ID=<Projects DBのID>")
        print("  export AI_PLC_TASKS_DB_ID=<Tasks DBのID>")
        print("（Project Registry / External Sync はローカルの ai_plc.db だけでも動作します）")
        return

    if cmd == "pull":
        cmd_pull(dry_run=dry_run)
    elif cmd == "push":
        cmd_push(dry_run=dry_run)
    elif cmd == "sync":
        cmd_sync(dry_run=dry_run)
    elif cmd == "status":
        cmd_status()
    else:
        print("Unknown command: %s" % cmd)
        print(__doc__)


if __name__ == "__main__":
    main()
