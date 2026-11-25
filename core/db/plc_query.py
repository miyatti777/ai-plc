#!/usr/bin/env python3
"""AI-PLC SQLite クエリヘルパー

Usage:
    python3 .claude/db/plc_query.py projects             # 全プロジェクト一覧
    python3 .claude/db/plc_query.py tasks                # 全タスク一覧（タスク同期の凍結中は backlog.yaml を表示）
    python3 .claude/db/plc_query.py tasks L-1234         # 特定PJのタスク（Scope ID指定）
    python3 .claude/db/plc_query.py active               # activeプロジェクトのみ
    python3 .claude/db/plc_query.py dashboard            # ダッシュボード表示
    python3 .claude/db/plc_query.py sql "SELECT ..."     # 任意SQL
    python3 .claude/db/plc_query.py add-project          # プロジェクト追加（対話）
    python3 .claude/db/plc_query.py add-task             # タスク追加（タスク同期の凍結中は書き込まず [SKIP]）
    python3 .claude/db/plc_query.py someday-add <タイトル> [メモ]  # いつかやるPJをストック（planned）
    python3 .claude/db/plc_query.py someday              # ストック一覧（planned・登録日順）
    python3 .claude/db/plc_query.py someday-start <S-ID> # ストックを着手済みにし Collection 起動プロンプトを出す
    python3 .claude/db/plc_query.py someday-revert <S-ID> # 着手を取り消してストックに戻す

タスクの正は各 Layer の backlog.yaml。tasks テーブルは古い写しで、凍結中
（`python3 .claude/db/sync.py tasks-sync --status`）は読みも書きもしない。
"""

import datetime
import importlib.util
import json
import os
import re
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_plc.db")
# Project root: <root>/.claude/db/plc_query.py (or .cursor/db/) -> two levels up.
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TASK_FREEZE_KEY = "task_sync_frozen"
WORKSPACE_MANIFEST_PATH = os.path.join(os.path.dirname(DB_PATH), "workspace_identity.json")
SYNC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync.py")
SYNC = None  # sync.py module (shared Identity resolver); tests may inject one
SKIP_DIRS = {"node_modules", "Documents", "__pycache__", "venv"}


def get_conn():
    if not os.path.exists(DB_PATH):
        print(f"DB not found: {DB_PATH}")
        print("Run: python3 .claude/db/init_db.py --import")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def print_table(rows, columns=None):
    if not rows:
        print("(no results)")
        return

    if columns is None:
        columns = rows[0].keys()

    data = [[str(row[c] or "") for c in columns] for row in rows]
    widths = [max(len(c), max(len(d[i]) for d in data)) for i, c in enumerate(columns)]

    header = "  ".join(c.ljust(w) for c, w in zip(columns, widths))
    sep = "  ".join("-" * w for w in widths)
    print(header)
    print(sep)
    for d in data:
        print("  ".join(v.ljust(w) for v, w in zip(d, widths)))


def cmd_projects(conn):
    rows = conn.execute("""
        SELECT scope_id, name, status, depth, mode, owner
        FROM projects ORDER BY created_at DESC
    """).fetchall()
    print_table(rows)


def _tasks_frozen(conn):
    """Local tasks are a frozen copy; each Layer's backlog.yaml is the source.

    A malformed freeze record still counts as frozen here (never write task rows by
    mistake) but prints a warning; sync.py stops on it and `sync.py tasks-sync
    --unfreeze --approved-by NAME` clears it."""
    try:
        row = conn.execute("SELECT value FROM _metadata WHERE key=?", (TASK_FREEZE_KEY,)).fetchone()
    except sqlite3.OperationalError:
        return False
    if row is None:
        return False
    try:
        record = json.loads(row[0])
        ok = isinstance(record, dict) and isinstance(record.get("approved_by"), str)
    except (ValueError, TypeError):
        ok = False
    if not ok:
        print("WARNING: the task freeze record is malformed; treating tasks as frozen "
              "(check: python3 .claude/db/sync.py tasks-sync --status)", file=sys.stderr)
    return True


def _layer_backlogs(scope_filter=None):
    """Yield (scope_id, backlog_path) for Layers whose scope_id matches the prefix."""
    seen = set()
    intents = []
    for dirpath, dirnames, filenames in os.walk(BASE):
        # Skip hidden folders (.git, .claude ...), dependencies and Layer outputs.
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d not in SKIP_DIRS)
        if "intent.yaml" in filenames:
            intents.append(os.path.join(dirpath, "intent.yaml"))
    for intent in sorted(intents):
        try:
            with open(intent, encoding="utf-8") as handle:
                match = re.search(r'^scope_id:\s*["\']?([^"\'\n#]+?)["\']?\s*(?:#.*)?$',
                                  handle.read(), re.M)
        except (OSError, UnicodeDecodeError):
            continue
        if not match:
            continue
        sid = match.group(1).strip()
        if sid in seen or (scope_filter and not sid.startswith(scope_filter)):
            continue
        backlog = os.path.join(os.path.dirname(intent), "backlog.yaml")
        if os.path.isfile(backlog):
            seen.add(sid)
            yield sid, backlog


def _backlog_task_rows(scope_filter=None):
    try:
        import yaml
    except ImportError:
        print("ERROR: PyYAML is required to read backlog.yaml (pip install pyyaml)")
        return []
    rows = []
    for sid, path in _layer_backlogs(scope_filter):
        try:
            with open(path, encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        tasks = data.get("tasks") if isinstance(data, dict) else None
        for task in tasks if isinstance(tasks, list) else []:
            if not isinstance(task, dict):
                continue
            tid = task.get("id") or task.get("task_id")
            if tid:
                rows.append(_Row(task_id=str(tid), scope_id=sid, name=task.get("name") or "",
                                 status=task.get("status") or "", type=task.get("type") or "",
                                 priority=task.get("priority") or ""))
    rows.sort(key=lambda r: (r["scope_id"], r["task_id"]))
    return rows


class _Row(dict):
    def keys(self):  # print_table reads keys() like sqlite3.Row
        return list(super().keys())


def cmd_tasks(conn, scope_filter=None):
    if _tasks_frozen(conn):
        print("(task sync is frozen: showing backlog.yaml, the source of truth)")
        print_table(_backlog_task_rows(scope_filter))
        return
    if scope_filter:
        rows = conn.execute("""
            SELECT task_id, scope_id, name, status, type, priority, estimate_days
            FROM tasks WHERE scope_id LIKE ? ORDER BY task_id
        """, (scope_filter + "%",)).fetchall()
    else:
        rows = conn.execute("""
            SELECT task_id, scope_id, name, status, type, priority
            FROM tasks ORDER BY scope_id, task_id
        """).fetchall()
    print_table(rows)


def cmd_active(conn):
    rows = conn.execute("""
        SELECT scope_id, name, depth, mode
        FROM projects WHERE status = 'active'
        ORDER BY created_at DESC
    """).fetchall()
    print_table(rows)


def cmd_dashboard(conn):
    print("=" * 60)
    print("AI-PLC Dashboard")
    print("=" * 60)

    stats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) as active,
            SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as done,
            SUM(CASE WHEN status='paused' THEN 1 ELSE 0 END) as paused
        FROM projects
    """).fetchone()
    print(f"\nProjects: {stats['total']} total / {stats['active']} active / {stats['done']} done / {stats['paused']} paused")

    if _tasks_frozen(conn):
        print("Tasks: frozen (backlog.yaml is the source — `plc_query.py tasks <scope_id>`)")
        print("\n--- Active Projects ---")
        print_table(conn.execute(
            "SELECT scope_id, name, depth FROM projects WHERE status = 'active' "
            "ORDER BY scope_id").fetchall())
        return

    # tasks の状態は今の形（日本語＝Notion と同じ）。v1.14.0 までの公開版の DB（英語）もそのまま数える
    tstats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status IN ('未着手','planned') THEN 1 ELSE 0 END) as todo,
            SUM(CASE WHEN status IN ('進行中','active') THEN 1 ELSE 0 END) as wip,
            SUM(CASE WHEN status IN ('完了','completed') THEN 1 ELSE 0 END) as done
        FROM tasks
    """).fetchone()
    print(f"Tasks: {tstats['total']} total / {tstats['todo']} todo / {tstats['wip']} WIP / {tstats['done']} done")

    print("\n--- Active Projects with Tasks ---")
    rows = conn.execute("""
        SELECT p.scope_id, p.name, p.depth,
               COUNT(t.id) as tasks,
               SUM(CASE WHEN t.status IN ('完了','completed') THEN 1 ELSE 0 END) as done
        FROM projects p
        LEFT JOIN tasks t ON t.scope_id LIKE p.scope_id || '%'
        WHERE p.status = 'active'
        GROUP BY p.scope_id
        ORDER BY tasks DESC, p.scope_id
    """).fetchall()
    print_table(rows)


IDENTITY_COLUMNS = {
    "projects": ("workspace_id", "sync_uid", "ownership_epoch", "identity_version"),
    "tasks": ("workspace_id", "project_sync_uid", "project_ownership_epoch",
              "identity_version"),
}


def _has_identity_columns(conn):
    for table in ("projects", "tasks"):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "workspace_id" not in columns:
            return False
    return True


def _identity_less_counts(conn):
    """Rows whose Identity is missing or partial (any Identity column NULL)."""
    counts = {}
    for table, wanted in IDENTITY_COLUMNS.items():
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        present = [name for name in wanted if name in columns]
        condition = " OR ".join(f"{name} IS NULL" for name in present)
        counts[table] = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {condition}").fetchone()[0]
    return counts


def cmd_sql(conn, query):
    """Identity 列がある schema（v2）では、Identity が欠けた行が増える文を rollback して exit 3 で止める。
    Project の中止（cancelled）への出入りは project_lifecycle.py だけで行う"""
    try:
        # Read the before state only after reserving the writer. Otherwise
        # cancel could commit between snapshot and BEGIN and be overwritten.
        conn.execute("BEGIN IMMEDIATE")
        project_status_before = dict(conn.execute('SELECT id,status FROM projects').fetchall())
        guarded = _has_identity_columns(conn)
        if guarded:
            before = _identity_less_counts(conn)
            changes = conn.total_changes
        rows = conn.execute(query).fetchall()
        project_status_after = dict(conn.execute('SELECT id,status FROM projects').fetchall())
        if any(project_status_before.get(pid) != project_status_after.get(pid) and
               'cancelled' in (project_status_before.get(pid),project_status_after.get(pid))
               for pid in project_status_before.keys() | project_status_after.keys()):
            conn.rollback()
            return _blocked('PROJECT_LIFECYCLE_COMMAND_REQUIRED',
                            'use project_lifecycle.py cancel/reopen with the human decision record',3)
        if guarded and conn.total_changes != changes:
            after = _identity_less_counts(conn)
            grown = sorted(table for table in before if after[table] > before[table])
            if grown:
                conn.rollback()
                return _blocked(
                    "IDENTITY_LESS_ROW_FORBIDDEN",
                    "this statement would leave rows without a complete Identity in "
                    f"{', '.join(grown)} (never pushed). Add rows with add-project / "
                    "add-task, then UPDATE the other columns", 3)
        if rows:
            print_table(rows)
        else:
            print("(no results)")
        conn.commit()
    except Exception as e:
        if conn.in_transaction:
            conn.rollback()
        print(f"Error: {e}")
    return 0


def cmd_add_project(conn, args):
    if len(args) < 3:
        print("Usage: add-project <scope_id> <name> <goal>")
        print('Example: add-project L-1234 "新PJ名" "Goalテキスト"')
        return 0
    scope_id, name, goal = args[0], args[1], args[2]
    sync, version = _begin_identity_write(conn)
    if version == 2:
        return _add_project_v2(conn, sync, scope_id, name, goal)
    if version != 1:
        conn.rollback()
        return _blocked("LOCAL_IDENTITY_SCHEMA_MIXED",
                        "projects and tasks use different Identity schema versions", 3)
    conn.execute("""
        INSERT INTO projects (scope_id, name, goal, status)
        VALUES (?, ?, ?, 'active')
    """, (scope_id, name, goal))
    conn.commit()
    print(f"[OK] Project added: {scope_id} - {name}")
    return 0


def cmd_add_task(conn, args):
    if len(args) < 3:
        print("Usage: add-task <task_id> <scope_id> <name> [type] [priority]")
        print('Example: add-task T001 L-1234 "タスク名" implementation P0')
        return 0
    task_id, scope_id, name = args[0], args[1], args[2]
    task_type = args[3] if len(args) > 3 else "implementation"
    priority = args[4] if len(args) > 4 else "P1"
    sync, version = _begin_identity_write(conn)
    if version == 2:
        return _add_task_v2(conn, sync, task_id, scope_id, name, task_type, priority)
    if version != 1:
        conn.rollback()
        return _blocked("LOCAL_IDENTITY_SCHEMA_MIXED",
                        "projects and tasks use different Identity schema versions", 3)
    conn.execute("""
        INSERT INTO tasks (task_id, scope_id, name, type, priority)
        VALUES (?, ?, ?, ?, ?)
    """, (task_id, scope_id, name, task_type, priority))
    conn.commit()
    print(f"[OK] Task added: {task_id} ({scope_id}) - {name}")
    return 0


# ---- いつかやるPJストック（someday） ----------------------------------------------------------------
SOMEDAY_STATUS = "planned"
SOMEDAY_ID = re.compile(r"S-\d{4}(-\d+)?")
STARTED_TAG = re.compile(r" \[着手 \d{4}-\d{2}-\d{2}\]$")


def _blocked(code, message, exit_code):
    print(f"[BLOCKED] {code}: {message} (exit {exit_code}; nothing was written)")
    return exit_code


# ---- Identity v2.0（sync.py の移行の後の表）への追加 -------------------------------------------------
# v1 の表では今までどおり Identity 列なしで追加する。v2 の表では、workspace manifest と SQLite が一致する
# 今の workspace の Identity を付けて追加する（Project は新しい sync_uid、Task は同じ workspace で Scope ID が
# 完全一致する親 Project の sync_uid）。解決できないときは何も書かずに止まる（exit 2 / 3 / 5）。

def _sync_module():
    """Load sync.py once; its resolver is the single Identity projection."""
    global SYNC
    if SYNC is None:
        spec = importlib.util.spec_from_file_location("_plc_query_sync", SYNC_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        SYNC = module
    return SYNC


def _begin_identity_write(conn):
    """BEGIN IMMEDIATE, then read the Identity schema version inside the lock."""
    sync = _sync_module()
    conn.execute("BEGIN IMMEDIATE")
    try:
        return sync, sync._local_identity_schema_version(conn)
    except Exception:
        conn.rollback()
        raise


def _selection_blocked(conn, selection, hint=None):
    conn.rollback()
    finding = selection.get("finding") or {}
    message = finding.get("message") or "Identity selection failed"
    if hint:
        message = f"{message}. {hint}"
    return _blocked(finding.get("code") or "IDENTITY_INVALID", message,
                    selection["exit_code"])


def _identity_write_error(conn, exc):
    conn.rollback()
    if isinstance(exc, sqlite3.IntegrityError):
        return _blocked("LOCAL_CONSTRAINT_VIOLATION", str(exc), 2)
    return _blocked("LOCAL_SCHEMA_ERROR", str(exc), 3)


def _add_project_v2(conn, sync, scope_id, name, goal, status="active",
                    start_date=None, label="Project", announce=print):
    scope = sync._normalize_identity_text(scope_id)
    if not scope:
        conn.rollback()
        return _blocked("SCOPE_INVALID", "scope_id is empty after normalization", 3)
    try:
        selection = sync.resolve_identity_selection(
            conn, manifest_path=WORKSPACE_MANIFEST_PATH)
        if selection["exit_code"] or selection["mode"] != "v2":
            return _selection_blocked(conn, selection)
        workspace_id = selection["context"]["workspace_id"]
        existing = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE workspace_id=? AND scope_id=?",
            (workspace_id, scope),
        ).fetchone()[0]
        if existing:
            conn.rollback()
            return _blocked(
                "SCOPE_ALREADY_EXISTS",
                f"{scope} already exists in the current workspace; "
                "use the existing Project (a new sync_uid is not issued)", 2)
        sync_uid = sync._new_project_sync_uid()
        cursor = conn.execute("""
            INSERT INTO projects (scope_id, name, goal, status, start_date, workspace_id,
                                  sync_uid, ownership_epoch, identity_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, 2)
        """, (scope, name, goal, status, start_date, workspace_id, sync_uid))
        row = conn.execute(
            "SELECT workspace_id, sync_uid, ownership_epoch, identity_version "
            "FROM projects WHERE id=?", (cursor.lastrowid,)).fetchone()
        state, values = sync._identity_record_state("project", dict(row))
        if (state != "valid" or values["workspace_id"] != workspace_id
                or values["uid"] != sync_uid):
            conn.rollback()
            return _blocked("IDENTITY_READBACK_MISMATCH",
                            "inserted Project Identity did not read back", 5)
        conn.commit()
    except sqlite3.Error as exc:
        return _identity_write_error(conn, exc)
    announce(f"[OK] {label} added: {scope} - {name} "
             f"(Identity v2 workspace={sync._short_identity(workspace_id)} "
             f"sync_uid={sync._short_identity(sync_uid)})")
    return 0


def _add_task_v2(conn, sync, task_id, scope_id, name, task_type, priority):
    normalized_task = sync._normalize_identity_text(task_id)
    if not normalized_task:
        conn.rollback()
        return _blocked("TASK_ID_INVALID", "task_id is empty after normalization", 3)
    if not sync._normalize_identity_text(scope_id):
        conn.rollback()
        return _blocked("SCOPE_INVALID", "scope_id is empty after normalization", 3)
    try:
        selection = sync.resolve_identity_selection(
            conn, scope_id=scope_id, manifest_path=WORKSPACE_MANIFEST_PATH)
        if selection["exit_code"] or selection["mode"] != "v2":
            hint = None
            if (selection.get("finding") or {}).get("code") == "SCOPE_NOT_UNIQUE":
                hint = ("The parent Project must exist with an Identity in the current "
                        "workspace (add-project first); a Task is never attached by guess")
            return _selection_blocked(conn, selection, hint)
        workspace_id = selection["context"]["workspace_id"]
        project = selection["project"]
        existing = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE project_sync_uid=? AND task_id=?",
            (project["sync_uid"], normalized_task),
        ).fetchone()[0]
        if existing:
            conn.rollback()
            return _blocked(
                "TASK_ALREADY_EXISTS",
                f"{normalized_task} already exists in {project['scope_id']}", 2)
        cursor = conn.execute("""
            INSERT INTO tasks (task_id, scope_id, name, type, priority,
                               workspace_id, project_sync_uid,
                               project_ownership_epoch, identity_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 2)
        """, (normalized_task, project["scope_id"], name, task_type, priority,
              workspace_id, project["sync_uid"], int(project["ownership_epoch"])))
        row = conn.execute(
            "SELECT workspace_id, project_sync_uid, project_ownership_epoch, "
            "identity_version FROM tasks WHERE id=?", (cursor.lastrowid,)).fetchone()
        state, values = sync._identity_record_state("task", dict(row))
        if (state != "valid" or values["workspace_id"] != workspace_id
                or values["uid"] != project["sync_uid"]):
            conn.rollback()
            return _blocked("IDENTITY_READBACK_MISMATCH",
                            "inserted Task Identity did not read back", 5)
        conn.commit()
    except sqlite3.Error as exc:
        return _identity_write_error(conn, exc)
    print(f"[OK] Task added: {normalized_task} ({project['scope_id']}) - {name} "
          f"(Identity v2 project={sync._short_identity(project['sync_uid'])})")
    return 0


def _today():
    return datetime.date.today()


def _next_someday_id(conn, today):
    """S-MMDD for the first stock of the day, then S-MMDD-2, -3 ..."""
    base = f"S-{today:%m%d}"
    rows = conn.execute("SELECT scope_id FROM projects WHERE scope_id = ? OR scope_id LIKE ?",
                        (base, base + "-%")).fetchall()
    used = set()
    for (scope,) in rows:
        if scope == base:
            used.add(1)
        else:
            m = re.fullmatch(re.escape(base) + r"-(\d+)", scope)
            if m:
                used.add(int(m.group(1)))
    return base if not used else f"{base}-{max(used) + 1}"


def cmd_someday_add(conn, args):
    if len(args) < 1 or not args[0].strip() or args[0].startswith("-"):
        print('Usage: someday-add "<タイトル>" ["<メモ>"]')
        return 0
    name = args[0].strip()
    goal = args[1].strip() if len(args) > 1 and args[1].strip() else name
    today = _today()
    sync, version = _begin_identity_write(conn)  # the ID is chosen inside the write lock
    scope_id = _next_someday_id(conn, today)
    if version == 2:
        return _add_project_v2(conn, sync, scope_id, name, goal, status=SOMEDAY_STATUS,
                               start_date=today.isoformat(), label="Someday")
    if version != 1:
        conn.rollback()
        return _blocked("LOCAL_IDENTITY_SCHEMA_MIXED",
                        "projects and tasks use different Identity schema versions", 3)
    conn.execute("INSERT INTO projects (scope_id, name, goal, status, start_date) VALUES (?, ?, ?, ?, ?)",
                 (scope_id, name, goal, SOMEDAY_STATUS, today.isoformat()))
    conn.commit()
    print(f"[OK] Someday added: {scope_id} - {name}")
    return 0


def cmd_someday(conn):
    rows = conn.execute("""
        SELECT scope_id, name, start_date AS added,
               CASE WHEN goal IS NULL OR goal = name THEN ''
                    WHEN length(goal) > 40 THEN substr(goal, 1, 40) || '…'
                    ELSE goal END AS memo
        FROM projects WHERE status = ? AND scope_id LIKE 'S-%'
        ORDER BY start_date, id
    """, (SOMEDAY_STATUS,)).fetchall()
    print_table(rows)
    if rows:
        print("\n着手するとき: someday-start <S-ID>")
    return 0


def cmd_someday_start(conn, args):
    args = [a for a in args if not a.startswith("--")]
    if len(args) < 1:
        print("Usage: someday-start <S-ID>")
        return 0
    scope_id = args[0].strip()
    if not SOMEDAY_ID.fullmatch(scope_id):
        return _blocked("SOMEDAY_NOT_FOUND", f"{scope_id} is not a someday ID (S-MMDD[-n])", 2)
    row = conn.execute("SELECT name, goal, status FROM projects WHERE scope_id = ?", (scope_id,)).fetchone()
    if row is None:
        return _blocked("SOMEDAY_NOT_FOUND", f"{scope_id} is not in projects", 2)
    if row["status"] != SOMEDAY_STATUS:
        return _blocked("SOMEDAY_NOT_PLANNED", f"{scope_id} is {row['status']}, not {SOMEDAY_STATUS}", 2)
    today = _today().isoformat()
    goal = row["goal"] or row["name"]
    cursor = conn.execute("UPDATE projects SET status = 'completed', goal = ? WHERE scope_id = ? AND status = ?",
                          (f"{goal} [着手 {today}]", scope_id, SOMEDAY_STATUS))
    if cursor.rowcount != 1:
        conn.rollback()
        return _blocked("SOMEDAY_NOT_PLANNED", f"{scope_id} changed while starting", 2)
    conn.commit()
    memo = "" if goal == row["name"] else f"。{goal}"
    print(f"[OK] Someday started: {scope_id} (status {SOMEDAY_STATUS} → completed)")
    print("\nコピペ用プロンプト:")
    print(f"/01-collection を実行してください / Goal: {row['name']}{memo} / 起点ストック: {scope_id}")
    print(f"\n（Collection を始めなかったときは someday-revert {scope_id} でストックに戻せます）")
    return 0


def cmd_someday_revert(conn, args):
    if len(args) < 1:
        print("Usage: someday-revert <S-ID>")
        return 0
    scope_id = args[0].strip()
    if not SOMEDAY_ID.fullmatch(scope_id):
        return _blocked("SOMEDAY_NOT_FOUND", f"{scope_id} is not a someday ID (S-MMDD[-n])", 2)
    row = conn.execute("SELECT goal, status FROM projects WHERE scope_id = ?", (scope_id,)).fetchone()
    if row is None:
        return _blocked("SOMEDAY_NOT_FOUND", f"{scope_id} is not in projects", 2)
    goal = row["goal"] or ""
    if row["status"] != "completed" or not STARTED_TAG.search(goal):
        return _blocked("SOMEDAY_NOT_STARTED", f"{scope_id} was not started by someday-start (status {row['status']})", 2)
    cursor = conn.execute("UPDATE projects SET status = ?, goal = ? WHERE scope_id = ? AND status = 'completed'",
                          (SOMEDAY_STATUS, STARTED_TAG.sub("", goal), scope_id))
    if cursor.rowcount != 1:
        conn.rollback()
        return _blocked("SOMEDAY_NOT_STARTED", f"{scope_id} changed while reverting", 2)
    conn.commit()
    print(f"[OK] Someday reverted: {scope_id} (status completed → {SOMEDAY_STATUS})")
    return 0


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if len(argv) < 2:
        print(__doc__)
        return

    cmd = argv[1]
    conn = get_conn()
    code = 0

    if cmd == "projects":
        cmd_projects(conn)
    elif cmd == "tasks":
        scope = argv[2] if len(argv) > 2 else None
        cmd_tasks(conn, scope)
    elif cmd == "active":
        cmd_active(conn)
    elif cmd == "dashboard":
        cmd_dashboard(conn)
    elif cmd == "sql":
        if len(argv) < 3:
            print("Usage: sql 'SELECT ...'")
        else:
            code = cmd_sql(conn, argv[2])
    elif cmd == "add-project":
        code = cmd_add_project(conn, argv[2:])
    elif cmd == "add-task":
        if _tasks_frozen(conn):
            # Older procedures may still call add-task: do not fail them, just do
            # not write (backlog.yaml is the source of truth).
            print("[SKIP] task sync is frozen: backlog.yaml is the source; "
                  "no Registry task row was added")
        else:
            code = cmd_add_task(conn, argv[2:])
    elif cmd == "someday-add":
        code = cmd_someday_add(conn, argv[2:])
    elif cmd == "someday":
        code = cmd_someday(conn)
    elif cmd == "someday-start":
        code = cmd_someday_start(conn, argv[2:])
    elif cmd == "someday-revert":
        code = cmd_someday_revert(conn, argv[2:])
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)

    conn.close()
    return code


if __name__ == "__main__":
    sys.exit(main() or 0)
