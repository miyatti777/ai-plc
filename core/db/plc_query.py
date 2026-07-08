#!/usr/bin/env python3
"""AI-PLC SQLite クエリヘルパー

Usage:
    python3 .claude/db/plc_query.py projects             # 全プロジェクト一覧
    python3 .claude/db/plc_query.py tasks                # 全タスク一覧
    python3 .claude/db/plc_query.py tasks L-1234         # 特定PJのタスク（Scope ID指定）
    python3 .claude/db/plc_query.py active               # activeプロジェクトのみ
    python3 .claude/db/plc_query.py dashboard            # ダッシュボード表示
    python3 .claude/db/plc_query.py sql "SELECT ..."     # 任意SQL
    python3 .claude/db/plc_query.py add-project          # プロジェクト追加（対話）
    python3 .claude/db/plc_query.py add-task             # タスク追加（対話）
"""

import sqlite3
import sys
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_plc.db")


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


def cmd_tasks(conn, scope_filter=None):
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

    tstats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status='未着手' THEN 1 ELSE 0 END) as todo,
            SUM(CASE WHEN status='進行中' THEN 1 ELSE 0 END) as wip,
            SUM(CASE WHEN status='完了' THEN 1 ELSE 0 END) as done
        FROM tasks
    """).fetchone()
    print(f"Tasks: {tstats['total']} total / {tstats['todo']} todo / {tstats['wip']} WIP / {tstats['done']} done")

    print("\n--- Active Projects with Tasks ---")
    rows = conn.execute("""
        SELECT p.scope_id, p.name, p.depth,
               COUNT(t.id) as tasks,
               SUM(CASE WHEN t.status='完了' THEN 1 ELSE 0 END) as done
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
        cmd_add_task(conn, sys.argv[2:])
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)

    conn.close()


if __name__ == "__main__":
    main()
