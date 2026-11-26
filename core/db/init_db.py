#!/usr/bin/env python3
"""AI-PLC SQLite DB 初期化スクリプト

Notion上の AI-PLC Projects / AI-PLC Tasks DBをローカルSQLiteで再現する。
新しく作る DB では、タスク同期を凍結した印（_metadata の task_sync_frozen）を入れる。
タスクの正は各 Layer の backlog.yaml で、tasks テーブルは使わない（RUL_plc_system §9）。
既存の DB にはこの印を足さない（凍結は `python3 .claude/db/sync.py tasks-sync --freeze
--approved-by <名前>` で行う）。
Notion から書き出した DB（nsync 形式）からデータをインポートする機能付き
（場所は環境変数 AI_PLC_NSYNC_DIR。中に AI_PLC_Projects.db・AI_PLC_Tasks.db）。

Usage:
    python3 .claude/db/init_db.py --help                           # usage のみ（DBを開かない）
    python3 .claude/db/init_db.py --db PATH                        # PATH に新規作成
    python3 .claude/db/init_db.py --db PATH --import               # nsync DBからデータもインポート
    python3 .claude/db/init_db.py --db PATH --reset                # PATH を削除して再作成
    python3 .claude/db/init_db.py --allow-production [--import]    # 既定の ai_plc.db（明示承認後だけ）

既定の `ai_plc.db`（このスクリプトの隣か設定で決まる本番の DB。symlink・別表記・同一実体を含む）への
書き込みは、まだ無いときも含めて `--allow-production` がない限り、DBを開く前に exit 3 で拒否する。
usage error は exit 64。
"""

import argparse
import sqlite3
import os
import sys
from pathlib import Path
import json
import re
import uuid
import urllib.parse
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _sibling_paths():
    """隣の aiplc_paths.py（無い単体コピーでは None）。本体の DB の決め方は aiplc_paths.main_db_for の 1 か所。
    ここは読み込むだけ。名前で import しないのは、ファイルの場所で読み込まれたとき（sys.path に無い）や、
    別の作業ツリーの aiplc_paths が先に読まれているときも、必ず隣のものを使うため。
    aiplc_paths を読み込むための関数で、aiplc_paths を読む前に使うので、aiplc_paths の中には置けない"""
    path = Path(__file__).resolve().with_name("aiplc_paths.py")
    if not path.is_file():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("_aiplc_paths_sibling", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _main_db():
    """本体の DB（worktree から呼んでも本体を指す）。aiplc_paths が無い単体コピーでは、今までどおり隣の ai_plc.db"""
    return PATHS.main_db_for(__file__) if PATHS else Path(__file__).resolve().with_name("ai_plc.db")


PATHS = _sibling_paths()


# 既定の対象と本番の守り（--allow-production）の基準。worktree から呼んでも本体の DB
DB_PATH = str(_main_db())

# Notion から書き出した DB（nsync 形式）の置き場所。--import のときだけ使う
NSYNC_DIR = os.environ.get("AI_PLC_NSYNC_DIR", "")
NSYNC_PROJECTS_DB = os.path.join(NSYNC_DIR, "AI_PLC_Projects.db") if NSYNC_DIR else ""
NSYNC_TASKS_DB = os.path.join(NSYNC_DIR, "AI_PLC_Tasks.db") if NSYNC_DIR else ""
# Notion の DB の ID（_metadata に控えるだけ。sync.py と同じ環境変数）
PROJECTS_NOTION_DB_ID = os.environ.get("AI_PLC_PROJECTS_DB_ID", "")
TASKS_NOTION_DB_ID = os.environ.get("AI_PLC_TASKS_DB_ID", "")
TASK_FREEZE_KEY = "task_sync_frozen"
# v1.8.1〜v1.14.0 の公開版の tasks の状態（英語）を Identity v2.0 の移行で今の形（Notion と同じ日本語）へ写す対応。
# paused には対応する値が無いので、paused の行があれば移行を止める
PUBLIC_V1_TASK_STATUS_MAP = {"planned": "未着手", "active": "進行中", "completed": "完了"}

IDENTITY_SCHEMA_VERSION = "2"
WORKSPACE_ID_PATTERN = re.compile(
    r"^wsp_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
PROJECT_UID_PATTERN = re.compile(
    r"^prj_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

LEGACY_PROJECT_COLUMNS = {
    "id", "notion_page_id", "scope_id", "name", "goal", "owner", "status",
    "mode", "depth", "system", "parent_scope", "top_page_url", "start_date",
    "deadline", "notion_last_edited", "last_sync_at", "created_at", "updated_at",
}
IDENTITY_PROJECT_COLUMNS = {
    "workspace_id", "sync_uid", "ownership_epoch", "identity_version",
}
LEGACY_TASK_COLUMNS = {
    "id", "notion_page_id", "task_id", "scope_id", "name", "status", "type",
    "priority", "estimate_days", "output_url", "completed_at",
    "notion_last_edited", "last_sync_at", "created_at", "updated_at",
}
IDENTITY_TASK_COLUMNS = {
    "workspace_id", "project_sync_uid", "project_ownership_epoch", "identity_version",
}
KNOWN_EXPLICIT_INDEXES = {
    "projects": {
        "idx_projects_scope", "idx_projects_status", "idx_projects_workspace",
    },
    "tasks": {
        "idx_tasks_scope", "idx_tasks_status", "idx_tasks_tid_scope",
        "idx_tasks_project_uid",
    },
}
KNOWN_TRIGGERS = {"trg_projects_updated", "trg_tasks_updated"}

LEGACY_COLUMN_CONTRACTS = {
    "projects": {
        "id": ("INTEGER", 0, None, 1),
        "notion_page_id": ("TEXT", 0, None, 0),
        "scope_id": ("TEXT", 1, None, 0),
        "name": ("TEXT", 1, None, 0),
        "goal": ("TEXT", 0, None, 0),
        "owner": ("TEXT", 0, None, 0),
        "status": ("TEXT", 1, "'planned'", 0),
        "mode": ("TEXT", 0, "'direct'", 0),
        "depth": ("TEXT", 0, "'standard'", 0),
        "system": ("TEXT", 0, "'AI-PLC'", 0),
        "parent_scope": ("TEXT", 0, None, 0),
        "top_page_url": ("TEXT", 0, None, 0),
        "start_date": ("TEXT", 0, None, 0),
        "deadline": ("TEXT", 0, None, 0),
        "notion_last_edited": ("TEXT", 0, None, 0),
        "last_sync_at": ("TEXT", 0, None, 0),
        "created_at": (
            "TEXT", 1, "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')", 0,
        ),
        "updated_at": (
            "TEXT", 1, "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')", 0,
        ),
    },
    "tasks": {
        "id": ("INTEGER", 0, None, 1),
        "notion_page_id": ("TEXT", 0, None, 0),
        "task_id": ("TEXT", 1, None, 0),
        "scope_id": ("TEXT", 1, None, 0),
        "name": ("TEXT", 1, None, 0),
        "status": ("TEXT", 1, "'未着手'", 0),
        "type": ("TEXT", 0, None, 0),
        "priority": ("TEXT", 0, "'P1'", 0),
        "estimate_days": ("REAL", 0, None, 0),
        "output_url": ("TEXT", 0, None, 0),
        "completed_at": ("TEXT", 0, None, 0),
        "notion_last_edited": ("TEXT", 0, None, 0),
        "last_sync_at": ("TEXT", 0, None, 0),
        "created_at": (
            "TEXT", 1, "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')", 0,
        ),
        "updated_at": (
            "TEXT", 1, "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')", 0,
        ),
    },
}
IDENTITY_COLUMN_TYPES = {
    "projects": {
        "workspace_id": "TEXT", "sync_uid": "TEXT",
        "ownership_epoch": "INTEGER", "identity_version": "INTEGER",
    },
    "tasks": {
        "workspace_id": "TEXT", "project_sync_uid": "TEXT",
        "project_ownership_epoch": "INTEGER", "identity_version": "INTEGER",
    },
}
INDEX_COLUMN_CONTRACTS = {
    "idx_projects_scope": ("scope_id",),
    "idx_projects_status": ("status",),
    "idx_projects_workspace": ("workspace_id",),
    "idx_tasks_scope": ("scope_id",),
    "idx_tasks_status": ("status",),
    "idx_tasks_tid_scope": ("task_id", "scope_id"),
    "idx_tasks_project_uid": ("project_sync_uid",),
}
TABLE_CHECK_CONTRACTS = {
    "projects": (
        "check(status in ('planned','active','completed','paused'))",
        "check(mode in ('direct','platform_builder'))",
        "check(depth in ('simple','standard','complex'))",
        "check(system in ('ai-plc','aipo'))",
    ),
    "tasks": (
        "check(status in ('未着手','進行中','完了'))",
        "check(type in ('research','design','implementation','content','verification','coordination'))",
        "check(priority in ('p0','p1','p2','p3'))",
    ),
}
# v1.8.1〜v1.14.0 の公開版の init_db が作った形。Identity v2.0 の移行はこの形も受け付け、
# tasks の状態を PUBLIC_V1_TASK_STATUS_MAP で今の形へ写す（type・system の CHECK は無かった）
PUBLIC_V1_COLUMN_OVERRIDES = {
    "tasks": {"status": ("TEXT", 1, "'planned'", 0)},
}
PUBLIC_V1_TABLE_CHECK_CONTRACTS = {
    "projects": TABLE_CHECK_CONTRACTS["projects"][:3],
    "tasks": (
        "check(status in ('planned','active','completed','paused'))",
        "check(priority in ('p0','p1','p2','p3'))",
    ),
}
TRIGGER_SQL_CONTRACTS = {
    "trg_projects_updated": """CREATE TRIGGER trg_projects_updated
        AFTER UPDATE ON projects
        WHEN OLD.last_sync_at IS NEW.last_sync_at
          OR (OLD.last_sync_at IS NULL AND NEW.last_sync_at IS NULL)
        BEGIN
            UPDATE projects SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = NEW.id;
        END""",
    "trg_tasks_updated": """CREATE TRIGGER trg_tasks_updated
        AFTER UPDATE ON tasks
        WHEN OLD.last_sync_at IS NEW.last_sync_at
          OR (OLD.last_sync_at IS NULL AND NEW.last_sync_at IS NULL)
        BEGIN
            UPDATE tasks SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = NEW.id;
        END""",
}


def create_schema(conn, *, freeze_new_tasks=False):
    """Notion DB構造を忠実に再現したSQLiteスキーマ。

    freeze_new_tasks=True のとき、projects テーブルが無い（新しい DB）ときだけタスク同期を凍結した印を入れる
    （init_db.py の CLI と導入の道具が使う）"""
    reject_business_schema_mutation(conn)
    new_db = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='projects'").fetchone() is None

    conn.executescript("""
        -- ============================================================
        -- AI-PLC Projects（Notion DB: 環境変数 AI_PLC_PROJECTS_DB_ID）
        -- ============================================================
        CREATE TABLE IF NOT EXISTS projects (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            notion_page_id  TEXT UNIQUE,
            scope_id        TEXT NOT NULL UNIQUE,    -- 例: L-MMDD[-N][-tag][-SGn]
            name            TEXT NOT NULL,            -- PJ名 (Notion title)
            goal            TEXT,                     -- Goalの要約
            owner           TEXT,
            status          TEXT NOT NULL DEFAULT 'planned'
                            CHECK(status IN ('planned','active','completed','paused','cancelled')),
            mode            TEXT DEFAULT 'direct'
                            CHECK(mode IN ('direct','platform_builder')),
            depth           TEXT DEFAULT 'standard'
                            CHECK(depth IN ('simple','standard','complex')),
            system          TEXT DEFAULT 'AI-PLC'
                            CHECK(system IN ('AI-PLC','AIPO')),
            parent_scope    TEXT,                     -- 親ScopeのID
            top_page_url    TEXT,                     -- トップページURL
            start_date      TEXT,                     -- ISO 8601
            deadline        TEXT,                     -- ISO 8601
            notion_last_edited TEXT,              -- Notion側の最終編集時刻（Pull時記録）
            last_sync_at    TEXT,                     -- この行を最後に同期した時刻
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );

        CREATE INDEX IF NOT EXISTS idx_projects_scope ON projects(scope_id);
        CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

        -- ============================================================
        -- AI-PLC Tasks（Notion DB: 環境変数 AI_PLC_TASKS_DB_ID）
        -- ============================================================
        CREATE TABLE IF NOT EXISTS tasks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            notion_page_id  TEXT UNIQUE,
            task_id         TEXT NOT NULL,             -- T001 形式
            scope_id        TEXT NOT NULL,             -- 所属プロジェクトのScope ID
            name            TEXT NOT NULL,             -- タスク名 (Notion title)
            status          TEXT NOT NULL DEFAULT '未着手'
                            CHECK(status IN ('未着手','進行中','完了')),
            type            TEXT
                            CHECK(type IN ('research','design','implementation',
                                           'content','verification','coordination')),
            priority        TEXT DEFAULT 'P1'
                            CHECK(priority IN ('P0','P1','P2','P3')),
            estimate_days   REAL,                     -- 見積工数（日）
            output_url      TEXT,                     -- 成果物URL
            completed_at    TEXT,                     -- ISO 8601
            notion_last_edited TEXT,              -- Notion側の最終編集時刻（Pull時記録）
            last_sync_at    TEXT,                     -- この行を最後に同期した時刻
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            -- scope_id は SubLayer（…-SG1 など）を含むため soft reference
        );

        CREATE INDEX IF NOT EXISTS idx_tasks_scope ON tasks(scope_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_tid_scope ON tasks(task_id, scope_id);

        -- ============================================================
        -- updated_at 自動更新トリガー
        -- last_sync_at が変更される場合はsync操作なのでスキップ
        -- ============================================================
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

        -- ============================================================
        -- メタデータ
        -- ============================================================
        CREATE TABLE IF NOT EXISTS _metadata (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)

    conn.execute(
        "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
        ("schema_version", "2.0")
    )
    conn.execute(
        "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
        ("created_at", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    )
    conn.execute(
        "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
        ("source", "Notion AI-PLC Projects/Tasks")
    )
    _record_notion_db_ids(conn)
    if freeze_new_tasks and new_db:
        conn.execute("INSERT OR IGNORE INTO _metadata (key, value) VALUES (?, ?)", (
            TASK_FREEZE_KEY,
            json.dumps({"approved_by": "installer",
                        "reason": "new database: backlog.yaml is the source of tasks",
                        "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                       ensure_ascii=False, sort_keys=True)))
    conn.commit()
    create_classification_tables(conn)
    print("[OK] Schema created (v2.0)")
    if freeze_new_tasks and new_db:
        print("[OK] Task sync frozen for the new database (tasks live in backlog.yaml)")


def _record_notion_db_ids(conn):
    """環境変数で Notion の DB の ID が決まっているときだけ _metadata に控える"""
    for key, value in (("projects_notion_db_id", PROJECTS_NOTION_DB_ID),
                       ("tasks_notion_db_id", TASKS_NOTION_DB_ID)):
        if value:
            conn.execute(
                "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)", (key, value))


CLASSIFICATION_EXECUTORS = ("claude-code", "codex", "cursor")  # experimental/registry-viewer/classify.py と同じ


def create_classification_tables(conn):
    """分類情報の別表。projects / tasks とは別に持つ: projects / tasks に列を足すと
    _validate_schema_inventory（Identity v2 移行の前の検査）が止まるため。何度実行しても同じ（IF NOT EXISTS）。
    正本は intent.yaml の classification と backlog.yaml の executed_by で、ここは写し（classify.py sync）。"""
    executors = ",".join("'%s'" % e for e in CLASSIFICATION_EXECUTORS)
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS project_classification (
            scope_id    TEXT PRIMARY KEY,
            affiliation TEXT,
            kind        TEXT,
            executor    TEXT CHECK(executor IS NULL OR executor IN ({executors})),
            source      TEXT NOT NULL DEFAULT 'intent' CHECK(source IN ('intent','backfill')),
            updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );
        CREATE TABLE IF NOT EXISTS task_execution (
            scope_id    TEXT NOT NULL,
            task_id     TEXT NOT NULL,
            executed_by TEXT NOT NULL CHECK(executed_by IN ({executors})),
            updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            PRIMARY KEY (scope_id, task_id)
        );
    """)
    conn.commit()


def outdated_classification_tables(conn):
    """分類の表のうち、executor・executed_by の CHECK に今の CLASSIFICATION_EXECUTORS の値が足りない表の名前。
    表が無いものは数えない（create_classification_tables で今の定義で作られる）"""
    out = []
    for name in ("project_classification", "task_execution"):
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        if row and any(f"'{e}'" not in row[0] for e in CLASSIFICATION_EXECUTORS):
            out.append(name)
    return out


def migrate_classification_executors(conn):
    """古い CHECK の分類の表を、今の CLASSIFICATION_EXECUTORS で作り直す（SQLite は CHECK を変えられないため、
    名前を変えて今の定義で作り、行をそのまま移して古い表を消す）。1つのトランザクションで行い、失敗したら元に戻る。
    戻り値: {表の名前: (移す前の行数, 移した後の行数)}"""
    tables = outdated_classification_tables(conn)
    if not tables:
        return {}
    cols = {"project_classification": "scope_id, affiliation, kind, executor, source, updated_at",
            "task_execution": "scope_id, task_id, executed_by, updated_at"}
    counts = {}
    iso = conn.isolation_level
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for name in tables:
                counts[name] = [conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0], None]
                conn.execute(f"ALTER TABLE {name} RENAME TO {name}__before_migration")
            executors = ",".join("'%s'" % e for e in CLASSIFICATION_EXECUTORS)
            ddl = {"project_classification": f"""CREATE TABLE project_classification (
            scope_id    TEXT PRIMARY KEY,
            affiliation TEXT,
            kind        TEXT,
            executor    TEXT CHECK(executor IS NULL OR executor IN ({executors})),
            source      TEXT NOT NULL DEFAULT 'intent' CHECK(source IN ('intent','backfill')),
            updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )""", "task_execution": f"""CREATE TABLE task_execution (
            scope_id    TEXT NOT NULL,
            task_id     TEXT NOT NULL,
            executed_by TEXT NOT NULL CHECK(executed_by IN ({executors})),
            updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            PRIMARY KEY (scope_id, task_id)
        )"""}
            for name in tables:
                conn.execute(ddl[name])
                conn.execute(f"INSERT INTO {name} ({cols[name]}) SELECT {cols[name]} FROM {name}__before_migration")
                conn.execute(f"DROP TABLE {name}__before_migration")
                counts[name][1] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                if counts[name][0] != counts[name][1]:
                    raise sqlite3.DatabaseError(f"{name}: 行数が合わない {counts[name]}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.isolation_level = iso
    return {k: tuple(v) for k, v in counts.items()}


def migrate_v1_to_v2(conn):
    """v1.0 → v2.0 マイグレーション: sync用カラム追加 + トリガー修正"""
    reject_business_schema_mutation(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()]
    added = 0
    if "notion_last_edited" not in cols:
        conn.execute("ALTER TABLE projects ADD COLUMN notion_last_edited TEXT")
        conn.execute("ALTER TABLE tasks ADD COLUMN notion_last_edited TEXT")
        added += 1
    if "last_sync_at" not in cols:
        conn.execute("ALTER TABLE projects ADD COLUMN last_sync_at TEXT")
        conn.execute("ALTER TABLE tasks ADD COLUMN last_sync_at TEXT")
        added += 1

    # トリガーを常に再作成（sync操作時はスキップする条件付き）
    conn.executescript("""
        DROP TRIGGER IF EXISTS trg_projects_updated;
        DROP TRIGGER IF EXISTS trg_tasks_updated;
        CREATE TRIGGER trg_projects_updated
        AFTER UPDATE ON projects
        WHEN OLD.last_sync_at IS NEW.last_sync_at
          OR (OLD.last_sync_at IS NULL AND NEW.last_sync_at IS NULL)
        BEGIN
            UPDATE projects SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = NEW.id;
        END;
        CREATE TRIGGER trg_tasks_updated
        AFTER UPDATE ON tasks
        WHEN OLD.last_sync_at IS NEW.last_sync_at
          OR (OLD.last_sync_at IS NULL AND NEW.last_sync_at IS NULL)
        BEGIN
            UPDATE tasks SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = NEW.id;
        END;
    """)

    if added:
        conn.execute(
            "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
            ("schema_version", "2.0")
        )
        _record_notion_db_ids(conn)
        conn.commit()
        print(f"[OK] Migrated v1.0 → v2.0 ({added} column pairs added)")


def _canonical_identity(prefix, pattern, value=None):
    identity = value or (prefix + str(uuid.uuid4()))
    if not pattern.fullmatch(identity):
        raise ValueError("invalid canonical Identity: %s" % identity)
    return identity


def new_workspace_id():
    """Return a cryptographically random, path-independent Workspace Identity."""
    return _canonical_identity("wsp_", WORKSPACE_ID_PATTERN)


def new_project_sync_uid():
    """Return a cryptographically random, path-independent Project Identity."""
    return _canonical_identity("prj_", PROJECT_UID_PATTERN)


def _column_names(conn, table):
    return {row[1] for row in conn.execute("PRAGMA table_info(%s)" % table)}


def _normalized_schema_sql(value):
    return " ".join((value or "").lower().split())


def _public_v1_tasks(conn):
    """tasks が v1.8.1〜v1.14.0 の公開版の形（状態が英語）なら True"""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone()
    compact = re.sub(r"\s+", "", _normalized_schema_sql(row[0] if row else ""))
    return re.sub(r"\s+", "", PUBLIC_V1_TABLE_CHECK_CONTRACTS["tasks"][0]) in compact


def _validate_schema_inventory(conn):
    """Fail before DDL if a rebuild would drop an unknown schema object.

    今の形と、v1.8.1〜v1.14.0 の公開版の形（tasks の状態が英語・type と system の CHECK なし）を受け付ける。
    公開版の形なら True を返す（移行で tasks の状態を PUBLIC_V1_TASK_STATUS_MAP で写す）"""
    public_v1 = _public_v1_tasks(conn)
    check_contracts = PUBLIC_V1_TABLE_CHECK_CONTRACTS if public_v1 else TABLE_CHECK_CONTRACTS
    allowed_columns = {
        "projects": LEGACY_PROJECT_COLUMNS | IDENTITY_PROJECT_COLUMNS,
        "tasks": LEGACY_TASK_COLUMNS | IDENTITY_TASK_COLUMNS,
    }
    for table in ("projects", "tasks"):
        column_rows = {
            row[1]: row for row in conn.execute("PRAGMA table_info(%s)" % table)
        }
        unknown_columns = set(column_rows) - allowed_columns[table]
        if unknown_columns:
            raise ValueError(
                "IDENTITY_MIGRATION_UNSUPPORTED_COLUMN: %s.%s"
                % (table, ",".join(sorted(unknown_columns)))
            )
        column_contracts = dict(LEGACY_COLUMN_CONTRACTS[table])
        if public_v1:
            column_contracts.update(PUBLIC_V1_COLUMN_OVERRIDES.get(table, {}))
        for name, expected in column_contracts.items():
            row = column_rows.get(name)
            actual = None if row is None else (
                (row[2] or "").upper(), row[3], row[4], row[5]
            )
            if actual != expected:
                raise ValueError(
                    "IDENTITY_MIGRATION_UNSUPPORTED_COLUMN_DEFINITION: %s.%s"
                    % (table, name)
                )
        for name, expected_type in IDENTITY_COLUMN_TYPES[table].items():
            row = column_rows.get(name)
            if row is not None and (row[2] or "").upper() != expected_type:
                raise ValueError(
                    "IDENTITY_MIGRATION_UNSUPPORTED_COLUMN_DEFINITION: %s.%s"
                    % (table, name)
                )
        table_sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        table_sql = _normalized_schema_sql(table_sql_row[0] if table_sql_row else "")
        compact_table_sql = re.sub(r"\s+", "", table_sql)
        if not all(
            re.sub(r"\s+", "", fragment) in compact_table_sql
            or (table == 'projects' and fragment == TABLE_CHECK_CONTRACTS['projects'][0]
                and "check(statusin('planned','active','completed','paused','cancelled'))" in compact_table_sql)
            for fragment in check_contracts[table]
        ):
            raise ValueError(
                "IDENTITY_MIGRATION_UNSUPPORTED_TABLE_CONSTRAINT: %s" % table
            )
        explicit_indexes = {
            row[1]
            for row in conn.execute("PRAGMA index_list(%s)" % table).fetchall()
            if not row[1].startswith("sqlite_autoindex_")
        }
        unknown_indexes = explicit_indexes - KNOWN_EXPLICIT_INDEXES[table]
        if unknown_indexes:
            raise ValueError(
                "IDENTITY_MIGRATION_UNSUPPORTED_INDEX: %s"
                % ",".join(sorted(unknown_indexes))
            )
        for index_name in explicit_indexes:
            columns = tuple(
                row[2] for row in conn.execute(
                    "PRAGMA index_info(%s)" % json.dumps(index_name)
                ).fetchall()
            )
            if columns != INDEX_COLUMN_CONTRACTS[index_name]:
                raise ValueError(
                    "IDENTITY_MIGRATION_UNSUPPORTED_INDEX_DEFINITION: %s"
                    % index_name
                )
        unique_columns = _unique_index_columns(conn, table)
        allowed_unique_shapes = {
            "projects": (
                {("notion_page_id",), ("scope_id",)},
                {("notion_page_id",), ("sync_uid",), ("workspace_id", "scope_id")},
            ),
            "tasks": (
                {("notion_page_id",), ("task_id", "scope_id")},
                {("notion_page_id",), ("project_sync_uid", "task_id")},
            ),
        }
        if unique_columns not in allowed_unique_shapes[table]:
            raise ValueError(
                "IDENTITY_MIGRATION_UNSUPPORTED_UNIQUE_DEFINITION: %s" % table
            )
    triggers = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name IN ('projects','tasks')"
        ).fetchall()
    }
    unknown_triggers = triggers - KNOWN_TRIGGERS
    if unknown_triggers:
        raise ValueError(
            "IDENTITY_MIGRATION_UNSUPPORTED_TRIGGER: %s"
            % ",".join(sorted(unknown_triggers))
        )
    for name in triggers:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)
        ).fetchone()[0]
        if _normalized_schema_sql(sql) != _normalized_schema_sql(
            TRIGGER_SQL_CONTRACTS[name]
        ):
            raise ValueError(
                "IDENTITY_MIGRATION_UNSUPPORTED_TRIGGER_DEFINITION: %s" % name
            )
    return public_v1


PUBLIC_V1_TASK_TYPES = (
    'research', 'design', 'implementation', 'content', 'verification', 'coordination',
)


def _validate_public_v1_rows(conn):
    """公開版の形の行が今の形の CHECK に入るかを、DDL の前に確かめる"""
    statuses = [row[0] for row in conn.execute(
        "SELECT DISTINCT status FROM tasks ORDER BY status")]
    unmapped = [value for value in statuses if value not in PUBLIC_V1_TASK_STATUS_MAP]
    if unmapped:
        raise ValueError(
            "IDENTITY_MIGRATION_PUBLIC_V1_TASK_STATUS_UNSUPPORTED: %s"
            % ",".join(str(value) for value in unmapped))
    types = [row[0] for row in conn.execute(
        "SELECT DISTINCT type FROM tasks WHERE type IS NOT NULL ORDER BY type")]
    unknown_types = [value for value in types if value not in PUBLIC_V1_TASK_TYPES]
    if unknown_types:
        raise ValueError(
            "IDENTITY_MIGRATION_PUBLIC_V1_TASK_TYPE_UNSUPPORTED: %s"
            % ",".join(str(value) for value in unknown_types))
    systems = [row[0] for row in conn.execute(
        "SELECT DISTINCT system FROM projects WHERE system IS NOT NULL ORDER BY system")]
    unknown_systems = [value for value in systems if value not in ("AI-PLC", "AIPO")]
    if unknown_systems:
        raise ValueError(
            "IDENTITY_MIGRATION_PUBLIC_V1_PROJECT_SYSTEM_UNSUPPORTED: %s"
            % ",".join(str(value) for value in unknown_systems))


def _map_public_v1_snapshot(snapshot):
    """移行の前の控えの tasks の状態を、移行の後の値（今の形）に読み替える"""
    status_index = 5  # identity_migration_snapshot の tasks の列の順（id, notion_page_id, task_id, scope_id, name, status, ...）
    snapshot["rows"]["tasks"] = [
        row[:status_index] + (PUBLIC_V1_TASK_STATUS_MAP[row[status_index]],) + row[status_index + 1:]
        for row in snapshot["rows"]["tasks"]
    ]
    return snapshot


def _metadata_value(conn, key):
    row = conn.execute(
        "SELECT value FROM _metadata WHERE key = ?", (key,)
    ).fetchone()
    return row[0] if row else None


def identity_migration_snapshot(conn):
    """Capture the invariants that an Identity table rebuild must preserve."""
    snapshot = {"counts": {}, "links": {}, "timestamps": {}, "rows": {}}
    row_columns = {
        "projects": (
            "id", "notion_page_id", "scope_id", "name", "goal", "owner", "status",
            "mode", "depth", "system", "parent_scope", "top_page_url", "start_date",
            "deadline", "notion_last_edited", "last_sync_at", "created_at", "updated_at",
        ),
        "tasks": (
            "id", "notion_page_id", "task_id", "scope_id", "name", "status", "type",
            "priority", "estimate_days", "output_url", "completed_at",
            "notion_last_edited", "last_sync_at", "created_at", "updated_at",
        ),
    }
    for table in ("projects", "tasks"):
        snapshot["counts"][table] = conn.execute(
            "SELECT COUNT(*) FROM %s" % table
        ).fetchone()[0]
        snapshot["links"][table] = [
            tuple(row)
            for row in conn.execute(
                "SELECT id, notion_page_id FROM %s ORDER BY id" % table
            ).fetchall()
        ]
        snapshot["timestamps"][table] = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT id, created_at, updated_at, last_sync_at
                FROM %s ORDER BY id
                """ % table
            ).fetchall()
        ]
        snapshot["rows"][table] = [
            tuple(row)
            for row in conn.execute(
                "SELECT %s FROM %s ORDER BY id"
                % (", ".join(row_columns[table]), table)
            ).fetchall()
        ]
    return snapshot


def _select_dicts(conn, query):
    cursor = conn.execute(query)
    names = [item[0] for item in cursor.description]
    return [
        dict(row) if isinstance(row, sqlite3.Row) else dict(zip(names, row))
        for row in cursor.fetchall()
    ]


def identity_row_snapshot(conn):
    """Return deterministic v2 Identity projections, or empty legacy projections."""
    if not {
        "workspace_id", "sync_uid", "ownership_epoch", "identity_version"
    }.issubset(_column_names(conn, "projects")):
        return {"projects": [], "tasks": []}
    return {
        "projects": [
            tuple(row)
            for row in conn.execute(
                """
                SELECT id, workspace_id, sync_uid, ownership_epoch, identity_version
                FROM projects ORDER BY id
                """
            ).fetchall()
        ],
        "tasks": [
            tuple(row)
            for row in conn.execute(
                """
                SELECT id, workspace_id, project_sync_uid,
                       project_ownership_epoch, identity_version
                FROM tasks ORDER BY id
                """
            ).fetchall()
        ],
    }


def build_identity_migration_mapping(
    conn,
    workspace_id,
    *,
    project_uid_factory=None,
    task_project_overrides=None,
):
    """Build a fixed mapping before any schema mutation.

    Callers must persist this mapping in their migration Plan before invoking
    ``migrate_identity_v2``. Existing valid v2 values win over the factory.
    Orphan Tasks require an explicit row-id -> Project UID override.
    """
    workspace_id = _canonical_identity(
        "wsp_", WORKSPACE_ID_PATTERN, workspace_id
    )
    factory = project_uid_factory or new_project_sync_uid
    overrides = {
        str(key): value for key, value in (task_project_overrides or {}).items()
    }
    project_columns = _column_names(conn, "projects")
    task_columns = _column_names(conn, "tasks")
    project_rows = _select_dicts(conn, "SELECT * FROM projects ORDER BY id")
    project_mapping = {}
    scope_mapping = {}
    assigned_uids = set()
    for row in project_rows:
        existing_workspace = row.get("workspace_id") if "workspace_id" in project_columns else None
        if existing_workspace and existing_workspace != workspace_id:
            raise ValueError("IDENTITY_WORKSPACE_MISMATCH: project %s" % row["id"])
        existing_uid = row.get("sync_uid") if "sync_uid" in project_columns else None
        uid = existing_uid or factory()
        uid = _canonical_identity("prj_", PROJECT_UID_PATTERN, uid)
        if uid in assigned_uids:
            raise ValueError("IDENTITY_DUPLICATE_PROJECT_UID: %s" % uid)
        assigned_uids.add(uid)
        project_mapping[str(row["id"])] = uid
        if row["scope_id"] in scope_mapping:
            raise ValueError("IDENTITY_DUPLICATE_SCOPE_IN_WORKSPACE: %s" % row["scope_id"])
        scope_mapping[row["scope_id"]] = uid

    task_mapping = {}
    task_rows = _select_dicts(conn, "SELECT * FROM tasks ORDER BY id")
    for row in task_rows:
        existing_workspace = row.get("workspace_id") if "workspace_id" in task_columns else None
        if existing_workspace and existing_workspace != workspace_id:
            raise ValueError("IDENTITY_WORKSPACE_MISMATCH: task %s" % row["id"])
        existing_parent = row.get("project_sync_uid") if "project_sync_uid" in task_columns else None
        parent_uid = existing_parent or overrides.get(str(row["id"])) or scope_mapping.get(
            row["scope_id"]
        )
        if not parent_uid:
            raise ValueError(
                "TASK_PROJECT_IDENTITY_MISSING: task row %s scope %s"
                % (row["id"], row["scope_id"])
            )
        parent_uid = _canonical_identity("prj_", PROJECT_UID_PATTERN, parent_uid)
        if parent_uid not in assigned_uids:
            raise ValueError(
                "TASK_PROJECT_IDENTITY_MISSING: unknown Project UID %s" % parent_uid
            )
        task_mapping[str(row["id"])] = parent_uid

    return {
        "identity_version": 2,
        "workspace_id": workspace_id,
        "projects": project_mapping,
        "tasks": task_mapping,
    }


def _unique_index_columns(conn, table):
    indexes = set()
    for row in conn.execute("PRAGMA index_list(%s)" % table).fetchall():
        if not row[2]:
            continue
        indexes.add(tuple(
            item[2] for item in conn.execute(
                "PRAGMA index_info(%s)" % json.dumps(row[1])
            ).fetchall()
        ))
    return indexes


def _identity_v2_enforced(conn):
    project_info = {
        row[1]: row for row in conn.execute("PRAGMA table_info(projects)")
    }
    task_info = {
        row[1]: row for row in conn.execute("PRAGMA table_info(tasks)")
    }
    project_required = {
        "workspace_id", "sync_uid", "ownership_epoch", "identity_version"
    }
    task_required = {
        "workspace_id", "project_sync_uid", "project_ownership_epoch",
        "identity_version"
    }
    if not project_required.issubset(project_info) or not task_required.issubset(task_info):
        return False
    if any(project_info[name][3] != 1 for name in project_required):
        return False
    if any(task_info[name][3] != 1 for name in task_required):
        return False
    expected_types = {
        "workspace_id": "TEXT",
        "sync_uid": "TEXT",
        "ownership_epoch": "INTEGER",
        "identity_version": "INTEGER",
    }
    if any(project_info[name][2].upper() != value for name, value in expected_types.items()):
        return False
    task_types = {
        "workspace_id": "TEXT",
        "project_sync_uid": "TEXT",
        "project_ownership_epoch": "INTEGER",
        "identity_version": "INTEGER",
    }
    if any(task_info[name][2].upper() != value for name, value in task_types.items()):
        return False
    project_sql_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='projects'"
    ).fetchone()
    task_sql_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'"
    ).fetchone()
    project_sql = " ".join((project_sql_row[0] or "").lower().split())
    task_sql = " ".join((task_sql_row[0] or "").lower().split())
    if not all(fragment in project_sql for fragment in (
        "check(ownership_epoch >= 1)",
        "check(identity_version = 2)",
        "unique(workspace_id, scope_id)",
    )):
        return False
    if not all(fragment in task_sql for fragment in (
        "check(project_ownership_epoch >= 1)",
        "check(identity_version = 2)",
        "unique(project_sync_uid, task_id)",
    )):
        return False
    if not (
        ("sync_uid",) in _unique_index_columns(conn, "projects")
        and ("workspace_id", "scope_id") in _unique_index_columns(conn, "projects")
        and ("project_sync_uid", "task_id") in _unique_index_columns(conn, "tasks")
        and _metadata_value(conn, "identity_schema_version") == IDENTITY_SCHEMA_VERSION
    ):
        return False
    required_indexes = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name IN (?,?,?,?,?,?)",
            (
                "idx_projects_scope", "idx_projects_status", "idx_projects_workspace",
                "idx_tasks_scope", "idx_tasks_status", "idx_tasks_project_uid",
            ),
        ).fetchall()
    }
    if required_indexes != {
        "idx_projects_scope", "idx_projects_status", "idx_projects_workspace",
        "idx_tasks_scope", "idx_tasks_status", "idx_tasks_project_uid",
    }:
        return False
    triggers = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND name IN (?,?)",
            ("trg_projects_updated", "trg_tasks_updated"),
        ).fetchall()
    }
    if triggers != KNOWN_TRIGGERS:
        return False
    invalid_projects = conn.execute("""
        SELECT COUNT(*) FROM projects
        WHERE identity_version != 2 OR ownership_epoch < 1
           OR workspace_id IS NULL OR sync_uid IS NULL
    """).fetchone()[0]
    invalid_tasks = conn.execute("""
        SELECT COUNT(*) FROM tasks t
        LEFT JOIN projects p ON p.sync_uid = t.project_sync_uid
        WHERE t.identity_version != 2 OR t.project_ownership_epoch < 1
           OR t.workspace_id IS NULL OR t.project_sync_uid IS NULL
           OR p.sync_uid IS NULL OR t.workspace_id != p.workspace_id
           OR t.project_ownership_epoch != p.ownership_epoch
    """).fetchone()[0]
    if invalid_projects or invalid_tasks:
        return False
    try:
        for workspace_id, sync_uid in conn.execute(
            "SELECT workspace_id, sync_uid FROM projects"
        ).fetchall():
            _canonical_identity("wsp_", WORKSPACE_ID_PATTERN, workspace_id)
            _canonical_identity("prj_", PROJECT_UID_PATTERN, sync_uid)
    except ValueError:
        return False
    return True


def _validate_mapping_against_rows(conn, mapping):
    if mapping.get("identity_version") != 2:
        raise ValueError("identity migration mapping version must be 2")
    workspace_id = _canonical_identity(
        "wsp_", WORKSPACE_ID_PATTERN, mapping.get("workspace_id")
    )
    project_rows = conn.execute("SELECT id FROM projects ORDER BY id").fetchall()
    task_rows = conn.execute("SELECT id FROM tasks ORDER BY id").fetchall()
    expected_projects = {str(row[0]) for row in project_rows}
    expected_tasks = {str(row[0]) for row in task_rows}
    if set(mapping.get("projects", {})) != expected_projects:
        raise ValueError("PROJECT_IDENTITY_MAPPING_INCOMPLETE")
    if set(mapping.get("tasks", {})) != expected_tasks:
        raise ValueError("TASK_IDENTITY_MAPPING_INCOMPLETE")
    project_uids = set()
    for value in mapping["projects"].values():
        uid = _canonical_identity("prj_", PROJECT_UID_PATTERN, value)
        if uid in project_uids:
            raise ValueError("IDENTITY_DUPLICATE_PROJECT_UID: %s" % uid)
        project_uids.add(uid)
    for value in mapping["tasks"].values():
        uid = _canonical_identity("prj_", PROJECT_UID_PATTERN, value)
        if uid not in project_uids:
            raise ValueError("TASK_PROJECT_IDENTITY_MISSING: %s" % uid)
    return workspace_id


def _create_identity_v2_tables(conn):
    conn.execute("DROP TABLE IF EXISTS _projects_identity_v2_new")
    conn.execute("DROP TABLE IF EXISTS _tasks_identity_v2_new")
    conn.execute("""
        CREATE TABLE _projects_identity_v2_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notion_page_id TEXT UNIQUE,
            scope_id TEXT NOT NULL,
            name TEXT NOT NULL,
            goal TEXT,
            owner TEXT,
            status TEXT NOT NULL DEFAULT 'planned'
                CHECK(status IN ('planned','active','completed','paused','cancelled')),
            mode TEXT DEFAULT 'direct'
                CHECK(mode IN ('direct','platform_builder')),
            depth TEXT DEFAULT 'standard'
                CHECK(depth IN ('simple','standard','complex')),
            system TEXT DEFAULT 'AI-PLC'
                CHECK(system IN ('AI-PLC','AIPO')),
            parent_scope TEXT,
            top_page_url TEXT,
            start_date TEXT,
            deadline TEXT,
            notion_last_edited TEXT,
            last_sync_at TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            workspace_id TEXT NOT NULL,
            sync_uid TEXT NOT NULL UNIQUE,
            ownership_epoch INTEGER NOT NULL CHECK(ownership_epoch >= 1),
            identity_version INTEGER NOT NULL CHECK(identity_version = 2),
            UNIQUE(workspace_id, scope_id)
        )
    """)
    conn.execute("""
        CREATE TABLE _tasks_identity_v2_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notion_page_id TEXT UNIQUE,
            task_id TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '未着手'
                CHECK(status IN ('未着手','進行中','完了')),
            type TEXT CHECK(type IN (
                'research','design','implementation','content','verification','coordination'
            )),
            priority TEXT DEFAULT 'P1' CHECK(priority IN ('P0','P1','P2','P3')),
            estimate_days REAL,
            output_url TEXT,
            completed_at TEXT,
            notion_last_edited TEXT,
            last_sync_at TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            workspace_id TEXT NOT NULL,
            project_sync_uid TEXT NOT NULL,
            project_ownership_epoch INTEGER NOT NULL
                CHECK(project_ownership_epoch >= 1),
            identity_version INTEGER NOT NULL CHECK(identity_version = 2),
            UNIQUE(project_sync_uid, task_id)
        )
    """)


def _copy_identity_v2_rows(conn, mapping, workspace_id, *, public_v1=False):
    project_columns = _column_names(conn, "projects")
    task_columns = _column_names(conn, "tasks")
    conn.row_factory = sqlite3.Row
    for row in conn.execute("SELECT * FROM projects ORDER BY id").fetchall():
        row = dict(row)
        uid = mapping["projects"][str(row["id"])]
        if row.get("workspace_id") not in (None, "", workspace_id):
            raise ValueError("IDENTITY_WORKSPACE_MISMATCH: project %s" % row["id"])
        if row.get("sync_uid") not in (None, "", uid):
            raise ValueError("IDENTITY_SPLIT_BRAIN: project %s" % row["id"])
        conn.execute("""
            INSERT INTO _projects_identity_v2_new (
                id, notion_page_id, scope_id, name, goal, owner, status, mode,
                depth, system, parent_scope, top_page_url, start_date, deadline,
                notion_last_edited, last_sync_at, created_at, updated_at,
                workspace_id, sync_uid, ownership_epoch, identity_version
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            row["id"], row["notion_page_id"], row["scope_id"], row["name"],
            row["goal"], row["owner"], row["status"], row["mode"], row["depth"],
            row["system"], row["parent_scope"], row["top_page_url"],
            row["start_date"], row["deadline"], row.get("notion_last_edited"),
            row.get("last_sync_at"), row["created_at"], row["updated_at"],
            workspace_id, uid, row.get("ownership_epoch") or 1, 2,
        ))
    for row in conn.execute("SELECT * FROM tasks ORDER BY id").fetchall():
        row = dict(row)
        parent_uid = mapping["tasks"][str(row["id"])]
        if row.get("workspace_id") not in (None, "", workspace_id):
            raise ValueError("IDENTITY_WORKSPACE_MISMATCH: task %s" % row["id"])
        if row.get("project_sync_uid") not in (None, "", parent_uid):
            raise ValueError("IDENTITY_SPLIT_BRAIN: task %s" % row["id"])
        conn.execute("""
            INSERT INTO _tasks_identity_v2_new (
                id, notion_page_id, task_id, scope_id, name, status, type,
                priority, estimate_days, output_url, completed_at,
                notion_last_edited, last_sync_at, created_at, updated_at,
                workspace_id, project_sync_uid, project_ownership_epoch,
                identity_version
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            row["id"], row["notion_page_id"], row["task_id"], row["scope_id"],
            row["name"],
            PUBLIC_V1_TASK_STATUS_MAP[row["status"]] if public_v1 else row["status"],
            row["type"], row["priority"],
            row["estimate_days"], row["output_url"], row["completed_at"],
            row.get("notion_last_edited"), row.get("last_sync_at"),
            row["created_at"], row["updated_at"], workspace_id, parent_uid,
            row.get("project_ownership_epoch") or 1, 2,
        ))


def _create_identity_v2_indexes_and_triggers(conn):
    conn.execute("CREATE INDEX idx_projects_scope ON projects(scope_id)")
    conn.execute("CREATE INDEX idx_projects_status ON projects(status)")
    conn.execute("CREATE INDEX idx_projects_workspace ON projects(workspace_id)")
    conn.execute("CREATE INDEX idx_tasks_scope ON tasks(scope_id)")
    conn.execute("CREATE INDEX idx_tasks_status ON tasks(status)")
    conn.execute("CREATE INDEX idx_tasks_project_uid ON tasks(project_sync_uid)")
    conn.execute("""
        CREATE TRIGGER trg_projects_updated AFTER UPDATE ON projects
        WHEN OLD.last_sync_at IS NEW.last_sync_at
          OR (OLD.last_sync_at IS NULL AND NEW.last_sync_at IS NULL)
        BEGIN
            UPDATE projects SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = NEW.id;
        END
    """)
    conn.execute("""
        CREATE TRIGGER trg_tasks_updated AFTER UPDATE ON tasks
        WHEN OLD.last_sync_at IS NEW.last_sync_at
          OR (OLD.last_sync_at IS NULL AND NEW.last_sync_at IS NULL)
        BEGIN
            UPDATE tasks SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = NEW.id;
        END
    """)


def migrate_identity_v2(conn, mapping, *, fail_at=None):
    """Transactionally rebuild legacy tables with enforced Identity v2 fields."""
    reject_business_schema_mutation(conn)
    public_v1 = _validate_schema_inventory(conn)
    workspace_id = _validate_mapping_against_rows(conn, mapping)
    if _identity_v2_enforced(conn):
        current = identity_row_snapshot(conn)
        for row in current["projects"]:
            if row[1] != workspace_id or row[2] != mapping["projects"][str(row[0])]:
                raise ValueError("IDENTITY_SPLIT_BRAIN: existing Project mapping")
        for row in current["tasks"]:
            if row[1] != workspace_id or row[2] != mapping["tasks"][str(row[0])]:
                raise ValueError("IDENTITY_SPLIT_BRAIN: existing Task mapping")
        return {
            "already_migrated": True,
            "identity_schema_version": IDENTITY_SCHEMA_VERSION,
            "counts": identity_migration_snapshot(conn)["counts"],
        }

    if public_v1:
        _validate_public_v1_rows(conn)
    before = identity_migration_snapshot(conn)
    if public_v1:
        before = _map_public_v1_snapshot(before)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _create_identity_v2_tables(conn)
        _copy_identity_v2_rows(conn, mapping, workspace_id, public_v1=public_v1)
        if fail_at == "after_projects_copy":
            raise RuntimeError("injected migration failure: after_projects_copy")

        copied = {
            "projects": conn.execute(
                "SELECT COUNT(*) FROM _projects_identity_v2_new"
            ).fetchone()[0],
            "tasks": conn.execute(
                "SELECT COUNT(*) FROM _tasks_identity_v2_new"
            ).fetchone()[0],
        }
        if copied != before["counts"]:
            raise ValueError("IDENTITY_MIGRATION_COUNT_MISMATCH")
        inconsistent_tasks = conn.execute("""
            SELECT COUNT(*) FROM _tasks_identity_v2_new t
            LEFT JOIN _projects_identity_v2_new p
              ON p.sync_uid = t.project_sync_uid
            WHERE p.sync_uid IS NULL
               OR t.workspace_id != p.workspace_id
               OR t.project_ownership_epoch != p.ownership_epoch
        """).fetchone()[0]
        if inconsistent_tasks:
            raise ValueError(
                "TASK_PROJECT_IDENTITY_MISMATCH: %s rows" % inconsistent_tasks
            )
        if fail_at == "before_swap":
            raise RuntimeError("injected migration failure: before_swap")

        conn.execute("DROP TRIGGER IF EXISTS trg_projects_updated")
        conn.execute("DROP TRIGGER IF EXISTS trg_tasks_updated")
        conn.execute("DROP TABLE projects")
        if fail_at == "after_projects_swap":
            raise RuntimeError("injected migration failure: after_projects_swap")
        conn.execute("DROP TABLE tasks")
        conn.execute("ALTER TABLE _projects_identity_v2_new RENAME TO projects")
        conn.execute("ALTER TABLE _tasks_identity_v2_new RENAME TO tasks")
        _create_identity_v2_indexes_and_triggers(conn)
        conn.execute(
            "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
            ("identity_schema_version", IDENTITY_SCHEMA_VERSION),
        )
        conn.execute(
            "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
            ("identity_migration_workspace_id", workspace_id),
        )
        quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise ValueError("IDENTITY_MIGRATION_QUICK_CHECK_FAILED: %s" % quick_check)
        after = identity_migration_snapshot(conn)
        if before != after:
            raise ValueError("IDENTITY_MIGRATION_PRESERVATION_MISMATCH")
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "already_migrated": False,
        "identity_schema_version": IDENTITY_SCHEMA_VERSION,
        "counts": before["counts"],
    }


def import_from_nsync(conn):
    """nsync DBからデータをインポート"""
    reject_business_schema_mutation(conn)

    imported = 0
    if not NSYNC_DIR:
        print("[SKIP] AI_PLC_NSYNC_DIR is not set (folder with AI_PLC_Projects.db / AI_PLC_Tasks.db)")
        return 0

    # --- Projects ---
    if os.path.exists(NSYNC_PROJECTS_DB):
        src = sqlite3.connect(NSYNC_PROJECTS_DB)
        src.row_factory = sqlite3.Row
        rows = src.execute("SELECT * FROM data").fetchall()
        for row in rows:
            conn.execute("""
                INSERT OR REPLACE INTO projects
                    (notion_page_id, scope_id, name, goal, owner, status,
                     mode, depth, system, parent_scope, top_page_url,
                     start_date, deadline, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["_notion_page_id"],
                row["Scope ID"] or "UNKNOWN",
                row["PJ名"] or "Untitled",
                row["Goal"],
                row["Owner"] or None,
                map_project_status(row["ステータス"]),
                row["モード"] or "direct",
                row["深度"] or "standard",
                row["システム"] or "AI-PLC",
                row["親Scope"],
                row["トップページ"],
                row["開始日"],
                row["期限"],
                row["登録日時"] or row["_created_time"],
            ))
            imported += 1
        src.close()
        print(f"[OK] Projects: {imported} rows imported from nsync")
    else:
        print(f"[SKIP] nsync Projects DB not found: {NSYNC_PROJECTS_DB}")

    # --- Tasks ---
    task_count = 0
    if os.path.exists(NSYNC_TASKS_DB):
        src = sqlite3.connect(NSYNC_TASKS_DB)
        src.row_factory = sqlite3.Row
        rows = src.execute("SELECT * FROM data").fetchall()
        for row in rows:
            conn.execute("""
                INSERT OR REPLACE INTO tasks
                    (notion_page_id, task_id, scope_id, name, status,
                     type, priority, estimate_days, output_url,
                     completed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["_notion_page_id"],
                row["Task ID"] or "T000",
                row["Scope ID"] or "UNKNOWN",
                row["タスク名"] or "Untitled",
                row["ステータス"] or "未着手",
                row["タイプ"],
                row["優先度"] or "P1",
                parse_float(row["見積(日)"]),
                row["成果物"],
                row["完了日"],
                row["_created_time"],
            ))
            task_count += 1
        src.close()
        print(f"[OK] Tasks: {task_count} rows imported from nsync")
    else:
        print(f"[SKIP] nsync Tasks DB not found: {NSYNC_TASKS_DB}")

    conn.commit()
    return imported + task_count


def map_project_status(notion_status):
    """nsyncで取得されたステータス文字列をスキーマ定義に正規化"""
    if (notion_status or '').strip().lower() == 'cancelled':
        raise ValueError('PROJECT_CANCELLED_EXTERNAL_SYNC_UNSUPPORTED')
    mapping = {
        "planned": "planned",
        "active": "active",
        "completed": "completed",
        "paused": "paused",
    }
    if notion_status:
        return mapping.get(notion_status.strip().lower(), "planned")
    return "planned"


def parse_float(val):
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


BUSINESS_GUARD_CODE = "INIT_DB_BUSINESS_TABLES_PRESENT"


def reject_business_schema_mutation(conn):
    """Reject before mutation: this initializer cannot preserve business relations."""
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name IN ('business_projects','business_project_links') LIMIT 1"
    ).fetchone():
        raise ValueError(BUSINESS_GUARD_CODE)


def _guard_business_db_path(target):
    if not os.path.exists(target):
        return
    uri = "file:" + urllib.parse.quote(os.path.abspath(target), safe="/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        reject_business_schema_mutation(conn)
    finally:
        conn.close()


PRODUCTION_GUARD_CODE = "INIT_DB_PRODUCTION_WRITE_FORBIDDEN"
USAGE_ERROR_EXIT = 64
PRODUCTION_GUARD_EXIT = 3


class _InitDbArgumentParser(argparse.ArgumentParser):
    """argparse with the repository's usage-error exit code (64)."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(USAGE_ERROR_EXIT, "%s: error: %s\n" % (self.prog, message))


def _build_parser():
    parser = _InitDbArgumentParser(
        prog="python3 .claude/db/init_db.py",
        allow_abbrev=False,
        description=(
            "AI-PLC SQLite DB を作成し、schema を適用する。"
            "--help はDBを開かずに終了する。"
        ),
        epilog=(
            "既定の ai_plc.db（symlink・別表記・同一実体を含む）への書き込みは "
            "--allow-production がない限り、DBを開く前に exit 3 (%s) で拒否する。"
            "新しく作る DB はタスク同期を凍結して作る。"
            "usage error は exit 64。" % PRODUCTION_GUARD_CODE
        ),
    )
    parser.add_argument("--db", metavar="PATH", default=None,
                        help="対象DBのパス（省略時はこのスクリプトの隣か設定で決まる ai_plc.db）")
    parser.add_argument("--import", dest="do_import", action="store_true",
                        help="Notion から書き出した DB（AI_PLC_NSYNC_DIR）からデータをインポートする")
    parser.add_argument("--reset", action="store_true",
                        help="対象DBを削除してから再作成する（不可逆）")
    parser.add_argument("--allow-production", action="store_true",
                        help="本番DBへの書き込みを明示的に許可する（明示承認後だけ）")
    return parser


def _same_path_text(left, right):
    return os.path.normcase(left).casefold() == os.path.normcase(right).casefold()


def is_production_db_path(target, production=None):
    """True when ``target`` would reach the production DB file.

    Compared without opening SQLite: resolved real path (symlinks, ``..``,
    relative paths), case-insensitive spelling, and ``samefile`` (hard links).
    Any error while comparing is treated as production (fail closed).
    """
    production = DB_PATH if production is None else production
    try:
        target_real = os.path.realpath(os.path.abspath(os.fspath(target)))
        production_real = os.path.realpath(os.path.abspath(os.fspath(production)))
        if target_real == production_real or _same_path_text(target_real, production_real):
            return True
        if os.path.exists(target_real) and os.path.exists(production_real):
            return os.path.samefile(target_real, production_real)
        return False
    except (OSError, ValueError, TypeError):
        return True


def main(argv=None):
    parser = _build_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:  # --help (0) or usage error (64): DB untouched
        return exc.code if isinstance(exc.code, int) else USAGE_ERROR_EXIT
    target = DB_PATH if args.db is None else args.db
    if not target:
        parser.print_usage(sys.stderr)
        print("error: --db requires a non-empty PATH", file=sys.stderr)
        return USAGE_ERROR_EXIT
    if is_production_db_path(target) and not args.allow_production:
        print(
            "[BLOCKED] %s: refusing to open or write the production DB (%s) "
            "without --allow-production. Nothing was opened or written. "
            "Use --db PATH for a copy, or re-run with --allow-production only "
            "after explicit approval." % (PRODUCTION_GUARD_CODE, target),
            file=sys.stderr,
        )
        return PRODUCTION_GUARD_EXIT
    if PATHS is not None and is_production_db_path(target):  # 本体の DB が worktree の写しなら止める
        try:
            PATHS.check_main_write(target)
        except PATHS.DbNotMain as exc:
            print("[BLOCKED] %s Nothing was opened or written." % exc, file=sys.stderr)
            return PRODUCTION_GUARD_EXIT

    try:
        _guard_business_db_path(target)
    except (ValueError, sqlite3.Error):
        print("[BLOCKED] " + BUSINESS_GUARD_CODE, file=sys.stderr)
        return PRODUCTION_GUARD_EXIT

    if args.reset and os.path.exists(target):
        os.remove(target)
        for sidecar in (target + "-wal", target + "-shm"):
            if os.path.exists(sidecar):
                os.remove(sidecar)
        print(f"[RESET] Removed existing DB: {target}")

    parent = os.path.dirname(os.path.abspath(target))
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    create_schema(conn, freeze_new_tasks=True)
    migrate_v1_to_v2(conn)
    create_classification_tables(conn)

    if args.do_import:
        total = import_from_nsync(conn)
        print(f"\nTotal imported: {total} rows")

    conn.close()
    print(f"\nDB location: {target}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
