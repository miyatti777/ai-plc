#!/usr/bin/env python3
"""AI-PLC SQLite DB 初期化スクリプト

AI-PLC の Project Registry（プロジェクト横断台帳）と Tasks をローカル SQLite で作成する。
空のDBを生成するだけ — 個人データは含まない。

新しく作る DB では、タスク同期を凍結した印（_metadata の task_sync_frozen）を入れる。
タスクの正は各 Layer の backlog.yaml で、tasks テーブルは使わない（RUL_plc_system §9）。
既存の DB にはこの印を足さない（凍結は `python3 .claude/db/sync.py tasks-sync --freeze
--approved-by <名前>` で行う）。

Usage:
    python3 init_db.py            # 空DBを作成（既存があればスキーマのみ保証）
    python3 init_db.py --reset    # 既存DBを削除して作り直す

DBは このスクリプトと同じディレクトリの ai_plc.db に作られる
（Claude Code 既定: .claude/db/ai_plc.db）。
"""

import json
import sqlite3
import os
import sys
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_plc.db")
TASK_FREEZE_KEY = "task_sync_frozen"


def create_schema(conn):
    """AI-PLC Projects / Tasks のスキーマを作成する。

    projects テーブルが無い（新しい DB）ときだけ、タスク同期を凍結した印を入れる。"""
    new_db = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='projects'").fetchone() is None
    conn.executescript("""
        -- ============================================================
        -- Projects — プロジェクト横断台帳（Project Registry）
        -- ============================================================
        CREATE TABLE IF NOT EXISTS projects (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            notion_page_id  TEXT UNIQUE,
            scope_id        TEXT NOT NULL UNIQUE,      -- 例: L-1234
            name            TEXT NOT NULL,             -- プロジェクト名
            goal            TEXT,                      -- Goalの要約
            owner           TEXT,                      -- 担当（任意）
            status          TEXT NOT NULL DEFAULT 'planned'
                            CHECK(status IN ('planned','active','completed','paused')),
            mode            TEXT DEFAULT 'direct'
                            CHECK(mode IN ('direct','platform_builder')),
            depth           TEXT DEFAULT 'standard'
                            CHECK(depth IN ('simple','standard','complex')),
            system          TEXT DEFAULT 'AI-PLC',
            parent_scope    TEXT,                      -- 親ScopeのID
            top_page_url    TEXT,
            start_date      TEXT,                      -- ISO 8601
            deadline        TEXT,                      -- ISO 8601
            notion_last_edited TEXT,
            last_sync_at    TEXT,
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_projects_scope  ON projects(scope_id);
        CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

        -- ============================================================
        -- Tasks — 旧い External Sync 先（新しい DB では凍結。タスクの正は backlog.yaml）
        -- ============================================================
        CREATE TABLE IF NOT EXISTS tasks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            notion_page_id  TEXT UNIQUE,
            task_id         TEXT NOT NULL,             -- 例: T001
            scope_id        TEXT NOT NULL,             -- 所属プロジェクトのScope ID
            name            TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'planned'
                            CHECK(status IN ('planned','active','completed','paused')),
            type            TEXT,
            priority        TEXT DEFAULT 'P1'
                            CHECK(priority IN ('P0','P1','P2','P3')),
            estimate_days   REAL,
            output_url      TEXT,
            completed_at    TEXT,
            notion_last_edited TEXT,
            last_sync_at    TEXT,
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_scope  ON tasks(scope_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_tid_scope ON tasks(task_id, scope_id);

        -- updated_at 自動更新（sync操作時はスキップ）
        CREATE TRIGGER IF NOT EXISTS trg_projects_updated
        AFTER UPDATE ON projects
        WHEN OLD.last_sync_at IS NEW.last_sync_at
          OR (OLD.last_sync_at IS NULL AND NEW.last_sync_at IS NULL)
        BEGIN
            UPDATE projects SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = NEW.id;
        END;
        CREATE TRIGGER IF NOT EXISTS trg_tasks_updated
        AFTER UPDATE ON tasks
        WHEN OLD.last_sync_at IS NEW.last_sync_at
          OR (OLD.last_sync_at IS NULL AND NEW.last_sync_at IS NULL)
        BEGIN
            UPDATE tasks SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = NEW.id;
        END;

        CREATE TABLE IF NOT EXISTS _metadata (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.execute("INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
                 ("schema_version", "2.0"))
    conn.execute("INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
                 ("created_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    if new_db:
        conn.execute("INSERT OR IGNORE INTO _metadata (key, value) VALUES (?, ?)", (
            TASK_FREEZE_KEY,
            json.dumps({"approved_by": "installer",
                        "reason": "new database: backlog.yaml is the source of tasks",
                        "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                       ensure_ascii=False, sort_keys=True)))
    conn.commit()
    print("[OK] Schema created (projects / tasks / _metadata)")
    if new_db:
        print("[OK] Task sync frozen for the new database (tasks live in backlog.yaml)")


def main():
    if "--reset" in sys.argv and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"[RESET] Removed existing DB: {DB_PATH}")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    create_schema(conn)
    conn.close()
    print(f"\nDB location: {DB_PATH}")
    print("Done.")


if __name__ == "__main__":
    main()
