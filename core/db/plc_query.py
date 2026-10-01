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

タスクの正は各 Layer の backlog.yaml。tasks テーブルは古い写しで、凍結中
（`python3 .claude/db/sync.py tasks-sync --status`）は読みも書きもしない。
"""

import json
import os
import re
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_plc.db")
# Project root: <root>/.claude/db/plc_query.py (or .cursor/db/) -> two levels up.
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TASK_FREEZE_KEY = "task_sync_frozen"
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

    tstats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status='planned' THEN 1 ELSE 0 END) as todo,
            SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) as wip,
            SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as done
        FROM tasks
    """).fetchone()
    print(f"Tasks: {tstats['total']} total / {tstats['todo']} todo / {tstats['wip']} WIP / {tstats['done']} done")

    print("\n--- Active Projects with Tasks ---")
    rows = conn.execute("""
        SELECT p.scope_id, p.name, p.depth,
               COUNT(t.id) as tasks,
               SUM(CASE WHEN t.status='completed' THEN 1 ELSE 0 END) as done
        FROM projects p
        LEFT JOIN tasks t ON t.scope_id LIKE p.scope_id || '%'
        WHERE p.status = 'active'
        GROUP BY p.scope_id
        ORDER BY tasks DESC, p.scope_id
    """).fetchall()
    print_table(rows)


def cmd_sql(conn, query):
    try:
        rows = conn.execute(query).fetchall()
        if rows:
            print_table(rows)
        else:
            print("(no results)")
        conn.commit()
    except Exception as e:
        print(f"Error: {e}")


def cmd_add_project(conn, args):
    if len(args) < 3:
        print("Usage: add-project <scope_id> <name> <goal>")
        print('Example: add-project L-1234 "新PJ名" "Goalテキスト"')
        return
    scope_id, name, goal = args[0], args[1], args[2]
    conn.execute("""
        INSERT INTO projects (scope_id, name, goal, status)
        VALUES (?, ?, ?, 'active')
    """, (scope_id, name, goal))
    conn.commit()
    print(f"[OK] Project added: {scope_id} - {name}")


def cmd_add_task(conn, args):
    if len(args) < 3:
        print("Usage: add-task <task_id> <scope_id> <name> [type] [priority]")
        print('Example: add-task T001 L-1234 "タスク名" implementation P0')
        return
    task_id, scope_id, name = args[0], args[1], args[2]
    task_type = args[3] if len(args) > 3 else "implementation"
    priority = args[4] if len(args) > 4 else "P1"
    conn.execute("""
        INSERT INTO tasks (task_id, scope_id, name, type, priority)
        VALUES (?, ?, ?, ?, ?)
    """, (task_id, scope_id, name, task_type, priority))
    conn.commit()
    print(f"[OK] Task added: {task_id} ({scope_id}) - {name}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    conn = get_conn()

    if cmd == "projects":
        cmd_projects(conn)
    elif cmd == "tasks":
        scope = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_tasks(conn, scope)
    elif cmd == "active":
        cmd_active(conn)
    elif cmd == "dashboard":
        cmd_dashboard(conn)
    elif cmd == "sql":
        if len(sys.argv) < 3:
            print("Usage: sql 'SELECT ...'")
        else:
            cmd_sql(conn, sys.argv[2])
    elif cmd == "add-project":
        cmd_add_project(conn, sys.argv[2:])
    elif cmd == "add-task":
        if _tasks_frozen(conn):
            # Older procedures may still call add-task: do not fail them, just do
            # not write (backlog.yaml is the source of truth).
            print("[SKIP] task sync is frozen: backlog.yaml is the source; "
                  "no Registry task row was added")
        else:
            cmd_add_task(conn, sys.argv[2:])
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)

    conn.close()


if __name__ == "__main__":
    main()
