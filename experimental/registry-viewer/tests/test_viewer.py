#!/usr/bin/env python3
"""Registry ビューアの回帰テスト（一時 SQLite・一時 Layer だけを使う。プロジェクトの DB や Flow には書かない）。

    python3 -m unittest discover -s experimental/registry-viewer/tests      # 公開リポの checkout で
    python3 -m unittest discover -s .claude/db/registry_viewer/tests        # プロジェクトに置いたとき

スキーマ（トリガ含む）は、上のフォルダにプロジェクトの ai_plc.db があればそこから読み取り専用で写し、無ければ内蔵の最小スキーマを使う。
公開版 init_db.py（英語語彙）が見つかれば、そのスキーマでも書き込みテストを回す。
"""
import contextlib
import http.client
import io
import json
import os
import sqlite3
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.dont_write_bytecode = True
import server  # noqa: E402

PROD_DB = server.default_db(server.REPO) if server.REPO else None
PUBLIC_REPO = HERE.parents[2]  # 公開リポでは <repo>/experimental/registry-viewer/tests


def _first(env, candidates):
    v = os.environ.get(env)
    if v:
        return Path(v) if Path(v).is_file() else None
    return next((c for c in candidates if c and c.is_file()), None)


# フル機能のテストに使う依存。環境変数 → このプロジェクトの配置 → 公開リポの配置 の順。無ければフル機能のテストは skip
_deps = server.find_dependencies(server.REPO) if server.REPO else (None, None, None)
AUDIT_PATH = _first("AIPLC_STATUS_AUDIT", [_deps[0], PUBLIC_REPO / "experimental" / "jev" / "scripts" / "aiplc_status_audit.py"])
PLC_PATH = _first("AIPLC_PLC_QUERY", [_deps[1], PUBLIC_REPO / "core" / "db" / "plc_query.py"])
_MISSING_DEPS = None if AUDIT_PATH and PLC_PATH else "aiplc_status_audit.py / plc_query.py が見つかりません（AIPLC_STATUS_AUDIT・AIPLC_PLC_QUERY で指定できます）"
FULL = {"audit_path": AUDIT_PATH, "plc_path": PLC_PATH}
# 公開版 init_db.py（英語語彙のスキーマ）。公開リポでは core/db/init_db.py を自動で使う
INIT_DB = _first("AIPLC_INIT_DB", [PUBLIC_REPO / "core" / "db" / "init_db.py"])
JA = {"todo": "未着手", "wip": "進行中", "done": "完了"}
EN = {"todo": "planned", "wip": "active", "done": "completed"}
FALLBACK_SCHEMA = [
    """CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, notion_page_id TEXT UNIQUE, scope_id TEXT NOT NULL UNIQUE,
       name TEXT NOT NULL, goal TEXT, owner TEXT DEFAULT 'owner', status TEXT NOT NULL DEFAULT 'planned'
       CHECK(status IN ('planned','active','completed','paused')), mode TEXT DEFAULT 'direct', depth TEXT DEFAULT 'standard',
       system TEXT DEFAULT 'AI-PLC', parent_scope TEXT, top_page_url TEXT, start_date TEXT, deadline TEXT,
       notion_last_edited TEXT, last_sync_at TEXT,
       created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
       updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))""",
    """CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, notion_page_id TEXT UNIQUE, task_id TEXT NOT NULL,
       scope_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT '未着手'
       CHECK(status IN ('未着手','進行中','完了')), type TEXT, priority TEXT DEFAULT 'P1', estimate_days REAL,
       output_url TEXT, completed_at TEXT, notion_last_edited TEXT, last_sync_at TEXT,
       created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
       updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))""",
    """CREATE TRIGGER trg_projects_updated AFTER UPDATE ON projects WHEN OLD.last_sync_at IS NEW.last_sync_at
       BEGIN UPDATE projects SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = NEW.id; END""",
    """CREATE TRIGGER trg_tasks_updated AFTER UPDATE ON tasks WHEN OLD.last_sync_at IS NEW.last_sync_at
       BEGIN UPDATE tasks SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = NEW.id; END""",
]


def prod_schema():
    if PROD_DB is None or not PROD_DB.is_file():
        return FALLBACK_SCHEMA
    conn = sqlite3.connect(f"file:{PROD_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT type, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
                            "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END").fetchall()
    finally:
        conn.close()
    return [sql for _, sql in rows]


INTENT = """scope_id: "{sid}"
scope_name: "{name}"
status: {status}   # コメントは残る
workflow_depth: standard
pipeline_variant: jev
goal:
  description: "テスト用の目標"
parent_scope: {parent}
jev_monitor: true
"""

BACKLOG = """scope_id: "L-9001"
tasks:
  - id: T001
    name: "一つ目"
    status: completed
    priority: P0
  - id: "T002"   # 引用符つき
    name: "二つ目"
    status: pending
    priority: P1
    dependencies: [T001]
  - status: in_progress
    id: T003
    name: "status が先頭"
summary:
  task_count: 3
  status: active
refactoring_log:
  - "- id: T002 のような文字列"
"""


def public_schema():
    """公開版 init_db.py の create_schema() でメモリ上に作った DB から DDL を写す"""
    mod = server._load("_rv_init_db", INIT_DB)
    conn = sqlite3.connect(":memory:")
    with contextlib.redirect_stdout(io.StringIO()):  # create_schema の完了表示を出さない
        mod.create_schema(conn)
    rows = conn.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
                        "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END").fetchall()
    conn.close()
    return [r[0] for r in rows]


class DataBase(unittest.TestCase):
    """一時 DB と一時 Layer だけを作る（依存の有無は見ない）"""
    V = JA  # tasks.status の語彙

    def schema(self):
        return prod_schema()

    def setUp(self):
        self._aiplc_repo = os.environ.get("AIPLC_REPO")
        self.tmp = tempfile.TemporaryDirectory(prefix="rv_test_")
        self.root = Path(self.tmp.name)
        self.db = self.root / "ai_plc.db"
        conn = sqlite3.connect(self.db)
        for sql in self.schema():
            conn.execute(sql)
        self._seed(conn)
        conn.commit()
        conn.close()
        self.flow = self.root / "Flow" / "209901" / "2099-01-01"
        self._layer("L-9001", "parent-layer", "active", BACKLOG)
        self._layer("L-9001-SG1", "child-layer", "active", None, parent='"L-9001"')
        self._layer("L-9003", "done-layer", "active",
                    'tasks:\n  - id: T001\n    name: "x"\n    status: completed\nsummary:\n  status: active\n')
        if PROD_DB is not None:
            self.assertNotEqual(self.db.resolve(), PROD_DB.resolve())

    def tearDown(self):
        # Registry が設定する AIPLC_REPO を元に戻す（次のテストに一時 root を持ち越さない）
        if self._aiplc_repo is None:
            os.environ.pop("AIPLC_REPO", None)
        else:
            os.environ["AIPLC_REPO"] = self._aiplc_repo
        self.tmp.cleanup()

    def _seed(self, conn):
        p = "INSERT INTO projects (scope_id, name, goal, status, parent_scope, start_date) VALUES (?,?,?,?,?,?)"
        conn.execute(p, ("L-9001", "親PJ", "目標1", "active", None, "2099-01-01"))
        conn.execute(p, ("L-9001-SG1", "子PJ", "目標2", "active", "L-9001", "2099-01-02"))
        conn.execute(p, ("L-9002", "Layerなし", "目標3", "active", None, "2099-01-03"))
        conn.execute(p, ("L-9003", "全部完了", "目標4", "active", None, "2099-01-04"))
        t = "INSERT INTO tasks (task_id, scope_id, name, status, priority) VALUES (?,?,?,?,?)"
        v = self.V
        conn.execute(t, ("T001", "L-9001", "一つ目", v["done"], "P0"))
        conn.execute(t, ("T002", "L-9001", "二つ目", v["todo"], "P1"))
        conn.execute(t, ("T004", "L-9001", "Registryだけ", v["wip"], "P2"))
        conn.execute(t, ("T001", "L-9003", "x", v["done"], "P0"))

    def _layer(self, sid, folder, status, backlog, parent="null"):
        d = self.flow / folder
        d.mkdir(parents=True)
        (d / "intent.yaml").write_text(INTENT.format(sid=sid, name=folder, status=status, parent=parent), encoding="utf-8")
        if backlog is not None:
            (d / "backlog.yaml").write_text(backlog, encoding="utf-8")
        return d

    def reg_status(self, sql, args):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(sql, args).fetchone()
        finally:
            conn.close()

    def backlog_text(self, folder="parent-layer"):
        return (self.flow / folder / "backlog.yaml").read_text(encoding="utf-8")


class Base(DataBase):
    """フル機能の Registry（依存が見つからなければ skip）"""

    def setUp(self):
        super().setUp()
        if _MISSING_DEPS:
            self.skipTest(_MISSING_DEPS)
        self.reg = server.Registry(self.db, self.root, **FULL)
        self.reg.log_dir = self.root / "log"


class ReadTests(Base):
    def test_list(self):
        data = self.reg.list_projects()
        by = {p["scope_id"]: p for p in data["projects"]}
        self.assertEqual(set(by), {"L-9001", "L-9001-SG1", "L-9002", "L-9003"})
        self.assertEqual(by["L-9001"]["layer_path"], "Flow/209901/2099-01-01/parent-layer")
        self.assertEqual(by["L-9001"]["progress"], {"done": 1, "total": 3, "source": "backlog"})
        self.assertEqual(by["L-9001-SG1"]["parent_scope"], "L-9001")
        self.assertIsNone(by["L-9002"]["layer_path"])
        self.assertEqual(data["counts"]["by_status"]["active"], 4)

    def test_detail_merges_tasks(self):
        d = self.reg.project_detail("L-9001")
        tasks = {t["task_id"]: t for t in d["tasks"]}
        self.assertEqual(list(tasks), ["T001", "T002", "T003", "T004"])
        self.assertTrue(tasks["T001"]["in_layer"] and tasks["T001"]["in_registry"])
        self.assertFalse(tasks["T001"]["mismatch"])
        self.assertFalse(tasks["T003"]["in_registry"])
        self.assertFalse(tasks["T004"]["in_layer"])
        self.assertEqual(d["children"], ["L-9001-SG1"])
        self.assertTrue(d["writable"])
        self.assertEqual(d["launch_prompt"], "/04-operation-jev を実行してください / Layer: Flow/209901/2099-01-01/parent-layer")

    def test_launch_prompt_by_state(self):
        d = self.flow / "empty-layer"
        d.mkdir()
        (d / "intent.yaml").write_text('scope_id: "L-9004"\nstatus: active\nworkflow_depth: standard\n', encoding="utf-8")
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO projects (scope_id, name, status) VALUES ('L-9004', '空', 'active')")
        conn.commit()
        conn.close()
        self.assertTrue(self.reg.project_detail("L-9004")["launch_prompt"].startswith("/02-inception "))
        (d / "intent.yaml").write_text('scope_id: "L-9004"\nstatus: active\nworkflow_depth: simple\n', encoding="utf-8")
        self.assertTrue(self.reg.project_detail("L-9004")["launch_prompt"].startswith("/04-operation "))
        (d / "intent.yaml").write_text('scope_id: "L-9004"\nstatus: completed\nworkflow_depth: simple\n', encoding="utf-8")
        self.assertIn("Re-Collection", self.reg.project_detail("L-9004")["launch_prompt"])

    def test_detail_readonly_without_layer(self):
        d = self.reg.project_detail("L-9002")
        self.assertFalse(d["writable"])
        self.assertIsNone(d["launch_prompt"])

    def test_detail_404(self):
        with self.assertRaises(server.WriteError) as cm:
            self.reg.project_detail("L-0000")
        self.assertEqual(cm.exception.code, 404)


class TaskWriteTests(Base):
    def test_task_status_both_copies(self):
        before = self.backlog_text()
        r = self.reg.set_task_status("L-9001", "T002", "completed", {"backlog": "pending", "registry": self.V["todo"]})
        self.assertEqual(r["wrote"], ["Flow/209901/2099-01-01/parent-layer/backlog.yaml", "registry.tasks"])
        after = self.backlog_text()
        diff = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
        self.assertEqual(diff, [("    status: pending", "    status: completed")])
        st, ca = self.reg_status("SELECT status, completed_at FROM tasks WHERE scope_id=? AND task_id=?", ("L-9001", "T002"))
        self.assertEqual(st, self.V["done"])
        self.assertIsNotNone(ca)
        log = (self.root / "log" / "viewer_log.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(log[-1])["result"], "ok")
        self.assertRegex(json.loads(log[-1])["at"], r"[+-]\d{2}:\d{2}$")  # タイムゾーンつき

    def test_status_first_key_item(self):
        self.reg.set_task_status("L-9001", "T003", "blocked", {"backlog": "in_progress", "registry": None})
        self.assertIn("  - status: blocked\n    id: T003", self.backlog_text())

    def test_registry_only_task(self):
        r = self.reg.set_task_status("L-9001", "T004", "completed", {"backlog": None, "registry": self.V["wip"]})
        self.assertEqual(r["wrote"], ["registry.tasks"])

    def test_expected_mismatch_writes_nothing(self):
        before = self.backlog_text()
        with self.assertRaises(server.WriteError) as cm:
            self.reg.set_task_status("L-9001", "T002", "completed", {"backlog": "in_progress", "registry": self.V["todo"]})
        self.assertEqual(cm.exception.code, 409)
        self.assertEqual(self.backlog_text(), before)
        self.assertEqual(self.reg_status("SELECT status FROM tasks WHERE scope_id=? AND task_id=?", ("L-9001", "T002"))[0], self.V["todo"])

    def test_invalid_status(self):
        with self.assertRaises(server.WriteError) as cm:
            self.reg.set_task_status("L-9001", "T002", "done'; DROP TABLE tasks;--", {})
        self.assertEqual(cm.exception.code, 400)

    def test_unknown_task(self):
        with self.assertRaises(server.WriteError) as cm:
            self.reg.set_task_status("L-9001", "T999", "completed", {"backlog": None, "registry": None})
        self.assertEqual(cm.exception.code, 404)

    def test_no_layer_is_readonly(self):
        with self.assertRaises(server.WriteError) as cm:
            self.reg.set_task_status("L-9002", "T001", "completed", {})
        self.assertEqual(cm.exception.code, 409)

    def test_registry_failure_rolls_back_backlog(self):
        before = self.backlog_text()
        orig = self.reg._registry_update

        def boom(*a, **k):
            raise server.WriteError(409, "simulated conflict")
        self.reg._registry_update = boom
        try:
            with self.assertRaises(server.WriteError):
                self.reg.set_task_status("L-9001", "T002", "completed", {"backlog": "pending", "registry": self.V["todo"]})
        finally:
            self.reg._registry_update = orig
        self.assertEqual(self.backlog_text(), before)

    def test_registry_changed_underneath(self):
        # expected は合っているが、Registry を書く直前に他で変わった → 読み戻しで検出して backlog を戻す
        before = self.backlog_text()
        orig = self.reg._registry_update

        def racing(table, sets, where, readback, to):
            conn = sqlite3.connect(self.db)
            conn.execute("UPDATE tasks SET status=? WHERE scope_id='L-9001' AND task_id='T002'", (self.V["wip"],))
            conn.commit()
            conn.close()
            return orig(table, sets, where, readback, to)
        self.reg._registry_update = racing
        try:
            with self.assertRaises(server.WriteError) as cm:
                self.reg.set_task_status("L-9001", "T002", "completed", {"backlog": "pending", "registry": self.V["todo"]})
        finally:
            self.reg._registry_update = orig
        self.assertEqual(cm.exception.code, 409)
        self.assertEqual(self.backlog_text(), before)


class ProjectWriteTests(Base):
    def test_complete_with_open_tasks_refused(self):
        with self.assertRaises(server.WriteError) as cm:
            self.reg.set_project_status("L-9001", "completed", {"intent": "active", "registry": "active"})
        self.assertEqual(cm.exception.code, 409)
        self.assertIn("status: active", (self.flow / "parent-layer" / "intent.yaml").read_text(encoding="utf-8"))

    def test_complete_all_done(self):
        r = self.reg.set_project_status("L-9003", "completed", {"intent": "active", "registry": "active"})
        self.assertEqual(r["wrote"], ["Flow/209901/2099-01-01/done-layer/intent.yaml",
                                      "Flow/209901/2099-01-01/done-layer/backlog.yaml", "registry.projects"])
        intent = (self.flow / "done-layer" / "intent.yaml").read_text(encoding="utf-8")
        self.assertIn("status: completed   # コメントは残る", intent)
        self.assertIn("  status: completed", self.backlog_text("done-layer"))
        self.assertEqual(self.reg_status("SELECT status FROM projects WHERE scope_id=?", ("L-9003",))[0], "completed")
        self.assertEqual(self.reg.project_detail("L-9003")["issues"], [])

    def test_pause_maps_to_deferred(self):
        self.reg.set_project_status("L-9001-SG1", "paused", {"intent": "active", "registry": "active"})
        self.assertIn("status: deferred", (self.flow / "child-layer" / "intent.yaml").read_text(encoding="utf-8"))
        self.assertEqual(self.reg_status("SELECT status FROM projects WHERE scope_id=?", ("L-9001-SG1",))[0], "paused")
        self.assertFalse(self.reg.project_detail("L-9001-SG1")["status_mismatch"])

    def test_project_expected_mismatch(self):
        with self.assertRaises(server.WriteError) as cm:
            self.reg.set_project_status("L-9001-SG1", "paused", {"intent": "completed", "registry": "active"})
        self.assertEqual(cm.exception.code, 409)

    def test_registry_failure_rolls_back_intent_and_summary(self):
        intent_before = (self.flow / "done-layer" / "intent.yaml").read_text(encoding="utf-8")
        backlog_before = self.backlog_text("done-layer")

        def boom(*a, **k):
            raise server.WriteError(500, "simulated failure")
        self.reg._registry_update = boom
        with self.assertRaises(server.WriteError):
            self.reg.set_project_status("L-9003", "completed", {"intent": "active", "registry": "active"})
        self.assertEqual((self.flow / "done-layer" / "intent.yaml").read_text(encoding="utf-8"), intent_before)
        self.assertEqual(self.backlog_text("done-layer"), backlog_before)

    def test_duplicate_folders_readonly(self):
        self._layer("L-9003", "done-layer-copy", "active", None)
        self.assertFalse(self.reg.project_detail("L-9003")["writable"])
        with self.assertRaises(server.WriteError) as cm:
            self.reg.set_project_status("L-9003", "completed", {"intent": "active", "registry": "active"})
        self.assertEqual(cm.exception.code, 409)


class ReviewFixTests(Base):
    def test_flow_style_task_not_editable(self):
        (self.flow / "done-layer" / "backlog.yaml").write_text(
            "tasks:\n  - {id: T001, name: x, status: completed}\nsummary:\n  status: active\n", encoding="utf-8")
        t = self.reg.project_detail("L-9003")["tasks"][0]
        self.assertFalse(t["editable"])
        self.assertIn("flow", t["readonly_reason"])

    def test_block_task_editable(self):
        tasks = {t["task_id"]: t for t in self.reg.project_detail("L-9001")["tasks"]}
        self.assertTrue(tasks["T002"]["editable"])

    def test_ids_outside_tasks_block_ignored(self):
        p = self.flow / "parent-layer" / "backlog.yaml"
        p.write_text(p.read_text(encoding="utf-8") + "decisions:\n  - id: T002\n    status: open\n", encoding="utf-8")
        self.reg.set_task_status("L-9001", "T002", "in_progress", {"backlog": "pending", "registry": self.V["todo"]})
        self.assertIn("    status: open", p.read_text(encoding="utf-8"))

    def test_duplicate_task_message(self):
        p = self.flow / "parent-layer" / "backlog.yaml"
        p.write_text(p.read_text(encoding="utf-8").replace("  - status: in_progress\n    id: T003",
                                                             "  - status: in_progress\n    id: T002"), encoding="utf-8")
        with self.assertRaises(server.WriteError) as cm:
            self.reg.set_task_status("L-9001", "T002", "completed", {"backlog": "pending", "registry": self.V["todo"]})
        self.assertIn("2 件", cm.exception.message)

    def test_empty_intent_status_refused(self):
        p = self.flow / "done-layer" / "intent.yaml"
        p.write_text(p.read_text(encoding="utf-8").replace("status: active   # コメントは残る", "status:"), encoding="utf-8")
        with self.assertRaises(server.WriteError) as cm:
            self.reg.set_project_status("L-9003", "completed", {"intent": None, "registry": "active"})
        self.assertEqual(cm.exception.code, 409)

    def test_rollback_skips_file_changed_by_others(self):
        p = self.flow / "parent-layer" / "backlog.yaml"

        def boom(*a, **k):
            p.write_text(p.read_text(encoding="utf-8").replace("    status: completed\n    priority: P1",
                                                                 "    status: blocked\n    priority: P1"), encoding="utf-8")
            raise server.WriteError(500, "simulated")
        self.reg._registry_update = boom
        with self.assertRaises(server.WriteError) as cm:
            self.reg.set_task_status("L-9001", "T002", "completed", {"backlog": "pending", "registry": self.V["todo"]})
        self.assertIn("戻していません", cm.exception.message)
        self.assertIn("    status: blocked\n    priority: P1", p.read_text(encoding="utf-8"))


class IdentityV2Tests(Base):
    """Identity v2 schema（workspace_id 等の列あり）では cmd_sql が BEGIN IMMEDIATE とガードを通る。status の UPDATE は通ること。"""

    def setUp(self):
        super().setUp()
        if not hasattr(self.reg.plc, "IDENTITY_COLUMNS"):
            self.skipTest("この plc_query.py は Identity v2 に対応していません")
        conn = sqlite3.connect(self.db)
        for table, cols in self.reg.plc.IDENTITY_COLUMNS.items():
            have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if set(cols) <= have:
                continue  # 写したスキーマが既に本物の v2（本番が移行済み）: 一意制約などがあるので列も値も触らない
            for c in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {c} TEXT")
            conn.execute(f"UPDATE {table} SET " + ", ".join(f"{c}='x'" for c in cols))
        conn.commit()
        conn.close()
        conn = sqlite3.connect(self.db)
        self.assertTrue(self.reg.plc._has_identity_columns(conn))
        conn.close()

    def test_task_update_passes_guard(self):
        self.reg.set_task_status("L-9001", "T002", "completed", {"backlog": "pending", "registry": self.V["todo"]})
        self.assertEqual(self.reg_status("SELECT status FROM tasks WHERE scope_id=? AND task_id=?",
                                         ("L-9001", "T002"))[0], self.V["done"])

    def test_project_update_passes_guard(self):
        self.reg.set_project_status("L-9003", "completed", {"intent": "active", "registry": "active"})
        self.assertEqual(self.reg_status("SELECT status FROM projects WHERE scope_id=?", ("L-9003",))[0], "completed")


class EditorTests(unittest.TestCase):
    audit = server._load("_rv_audit_t", AUDIT_PATH) if AUDIT_PATH else None

    def setUp(self):
        if self.audit is None:
            self.skipTest("aiplc_status_audit.py が見つかりません")

    def edit(self, text, tid, new):
        return server.edit_task_status_text(text, tid, new, self.audit)

    def test_crlf_and_quotes_kept(self):
        text = 'tasks:\r\n  - id: "T1"\r\n    status: "pending"  # c\r\n'
        self.assertEqual(self.edit(text, "T1", "completed"), 'tasks:\r\n  - id: "T1"\r\n    status: "completed"  # c\r\n')

    def test_duplicate_id_refused(self):
        text = "tasks:\n  - id: T1\n    status: pending\n  - id: T1\n    status: pending\n"
        with self.assertRaises(server.WriteError):
            self.edit(text, "T1", "completed")

    def test_nested_status_not_touched(self):
        text = textwrap.dedent("""\
            tasks:
              - id: T1
                sub:
                  status: keep
                status: pending
            """)
        out = self.edit(text, "T1", "completed")
        self.assertIn("      status: keep", out)
        self.assertIn("    status: completed", out)

    def test_flow_style_item_refused(self):
        with self.assertRaises(server.WriteError):
            self.edit("tasks:\n  - {id: T1, status: pending}\n", "T1", "completed")

    def test_write_verifies_parse(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "backlog.yaml"
            p.write_text("tasks:\n  - id: T1\n    status: pending\n", encoding="utf-8")
            server.write_task_status(p, "T1", "completed", self.audit)
            self.assertEqual(p.read_text(encoding="utf-8"), "tasks:\n  - id: T1\n    status: completed\n")


class HttpTests(Base):
    def setUp(self):
        super().setUp()
        self.httpd, self.token, _ = server.build_server(self.db, self.root, 0, token="tkn", **FULL)
        self.httpd.RequestHandlerClass  # noqa: B018
        self.port = self.httpd.server_address[1]
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def post_headers(self, **kw):
        h = {"Content-Type": "application/json", "X-Viewer-Token": "tkn"}
        h.update(kw)
        return h

    def test_index_has_token(self):
        st, data = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b'const TOKEN = "tkn"', data)

    def test_api_projects(self):
        st, data = self.req("GET", "/api/projects")
        self.assertEqual(st, 200)
        self.assertEqual(len(json.loads(data)["projects"]), 4)

    def test_bad_host(self):
        st, _ = self.req("GET", "/api/projects", headers={"Host": f"evil.example:{self.port}"})
        self.assertEqual(st, 403)

    def test_post_requires_token(self):
        st, _ = self.req("POST", "/api/projects/L-9001-SG1/status", {"to": "paused"},
                         headers={"Content-Type": "application/json"})
        self.assertEqual(st, 403)

    def test_post_bad_origin(self):
        st, _ = self.req("POST", "/api/projects/L-9001-SG1/status", {"to": "paused"},
                         headers=self.post_headers(Origin="http://evil.example"))
        self.assertEqual(st, 403)

    def test_post_requires_json(self):
        st, _ = self.req("POST", "/api/projects/L-9001-SG1/status", {"to": "paused"},
                         headers=self.post_headers(**{"Content-Type": "text/plain"}))
        self.assertEqual(st, 415)

    def test_post_ok(self):
        st, data = self.req("POST", "/api/projects/L-9001-SG1/status",
                            {"to": "paused", "expected": {"intent": "active", "registry": "active"}},
                            headers=self.post_headers(Origin=f"http://127.0.0.1:{self.port}"))
        self.assertEqual(st, 200, data)
        self.assertTrue(json.loads(data)["ok"])

    def test_negative_content_length(self):
        st, _ = self.req("POST", "/api/projects/L-9001-SG1/status", None,
                         headers=self.post_headers(**{"Content-Length": "-1"}))
        self.assertEqual(st, 400)

    def test_bad_ids(self):
        st, _ = self.req("GET", "/api/projects/..%2F..%2Fetc")
        self.assertEqual(st, 404)


# ---------------------------------------------------------------- 公開版スキーマ（英語語彙）で同じ書き込みテストを回す
class _PublicSchema:
    V = EN

    def schema(self):
        return public_schema()

    def setUp(self):
        if INIT_DB is None:
            self.skipTest("公開版 init_db.py が見つかりません（AIPLC_INIT_DB で指定できます）")
        super().setUp()


class PublicTaskWriteTests(_PublicSchema, TaskWriteTests):
    pass


class PublicProjectWriteTests(_PublicSchema, ProjectWriteTests):
    pass


class PublicReviewFixTests(_PublicSchema, ReviewFixTests):
    pass


# ---------------------------------------------------------------- 依存の探し方と閲覧のみモード
class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rv_dep_")
        self.root = Path(self.tmp.name)
        self._env = {k: os.environ.pop(k) for k in ("AIPLC_STATUS_AUDIT", "AIPLC_PLC_QUERY") if k in os.environ}

    def tearDown(self):
        os.environ.update(self._env)
        self.tmp.cleanup()

    def touch(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
        return p

    def test_nothing_found(self):
        a, p, why = server.find_dependencies(self.root)
        self.assertIsNone(a)
        self.assertIsNone(p)
        self.assertIn("閲覧のみ", why)

    def test_search_order(self):
        jev = self.touch(".claude/ai-plc-jev/scripts/aiplc_status_audit.py")
        plc = self.touch(".cursor/db/plc_query.py")
        self.assertEqual(server.find_dependencies(self.root)[:2], (jev, plc))
        own = self.touch("scripts/aiplc_status_audit.py")
        plc2 = self.touch(".claude/db/plc_query.py")
        self.assertEqual(server.find_dependencies(self.root)[:2], (own, plc2))

    def test_env_missing_file_stops(self):
        os.environ["AIPLC_STATUS_AUDIT"] = str(self.root / "nope.py")
        try:
            with self.assertRaises(FileNotFoundError):
                server.find_dependencies(self.root)
        finally:
            del os.environ["AIPLC_STATUS_AUDIT"]

    def test_find_root(self):
        self.touch(".cursor/db/ai_plc.db")
        self.assertEqual(server.find_root(self.root / "a" / "b" / "server.py"), self.root)
        self.assertEqual(server.default_db(self.root), self.root / ".cursor" / "db" / "ai_plc.db")


class ReadonlyModeTests(DataBase):
    """status_audit が無い環境（公開版 core だけ）での閲覧"""

    def setUp(self):
        super().setUp()
        self.ro = server.Registry(self.db, self.root, readonly_reason="テストでは依存なし")
        self.ro.log_dir = self.root / "log"

    def test_list_and_detail(self):
        data = self.ro.list_projects()
        self.assertEqual(data["viewer_mode"], "readonly")
        self.assertFalse(data["audit_available"])
        by = {p["scope_id"]: p for p in data["projects"]}
        self.assertEqual(by["L-9001"]["layer_path"], "Flow/209901/2099-01-01/parent-layer")
        self.assertEqual(by["L-9001"]["progress"], {"done": 1, "total": 3, "source": "backlog"})
        self.assertFalse(by["L-9001"]["confidential"])
        d = self.ro.project_detail("L-9001")
        self.assertFalse(d["writable"])
        self.assertIn("閲覧のみ", d["readonly_reason"])
        self.assertEqual([t["task_id"] for t in d["tasks"]], ["T001", "T002", "T003", "T004"])
        self.assertFalse(any(t["mismatch"] or t["editable"] for t in d["tasks"]))
        self.assertEqual(d["mode"], "direct")  # Project の mode 列は上書きされない

    def test_writes_refused(self):
        for call in (lambda: self.ro.set_task_status("L-9001", "T002", "completed", {}),
                     lambda: self.ro.set_project_status("L-9003", "completed", {})):
            with self.assertRaises(server.WriteError) as cm:
                call()
            self.assertEqual(cm.exception.code, 409)
        self.assertIn("    status: pending", self.backlog_text())

    def test_duplicate_folder_marked(self):
        self._layer("L-9003", "done-layer-copy", "active", None)
        self.assertTrue(self.ro.project_detail("L-9003")["duplicate_folder"])

    def test_audit_without_plc_query(self):
        """status_audit は有るが plc_query が無い: 表示はフル、書き込みだけ不可"""
        if AUDIT_PATH is None:
            self.skipTest("aiplc_status_audit.py が見つかりません")
        r = server.Registry(self.db, self.root, audit_path=AUDIT_PATH, plc_path=None)
        data = r.list_projects()
        self.assertEqual(data["viewer_mode"], "readonly")
        self.assertTrue(data["audit_available"])
        self.assertIn("plc_query", data["viewer_mode_reason"])
        with self.assertRaises(server.WriteError):
            r.set_task_status("L-9001", "T002", "completed", {"backlog": "pending", "registry": self.V["todo"]})

    def test_unloadable_audit_falls_back(self):
        bad = self.root / "broken_audit.py"
        bad.write_text("import jev_client_that_does_not_exist\n", encoding="utf-8")
        r = server.Registry(self.db, self.root, audit_path=bad, plc_path=PLC_PATH or bad)
        data = r.list_projects()
        self.assertFalse(data["audit_available"])
        self.assertIn("読み込めない", data["viewer_mode_reason"])

    def test_no_status_mismatch_without_audit(self):
        p = self.flow / "child-layer" / "intent.yaml"
        p.write_text(p.read_text(encoding="utf-8").replace("status: active", "status: deferred"), encoding="utf-8")
        by = {x["scope_id"]: x for x in self.ro.list_projects()["projects"]}
        self.assertFalse(by["L-9001-SG1"]["status_mismatch"])
        self.assertFalse(self.ro.project_detail("L-9001-SG1")["status_mismatch"])

    def test_old_audit_version_falls_back(self):
        old = self.root / "old_audit.py"
        old.write_text("def audit(*a, **k):\n    return {}\n", encoding="utf-8")
        r = server.Registry(self.db, self.root, audit_path=old, plc_path=PLC_PATH or old)
        data = r.list_projects()
        self.assertFalse(data["audit_available"])
        self.assertIn("版が違う", data["viewer_mode_reason"])


# ---------------------------------------------------------------- 分類（所属・種類・実行環境）の表示
CLASSIFY_PY = _first("AIPLC_CLASSIFY", [server.REPO / ".claude" / "db" / "classify.py" if server.REPO else None,
                                       server.HERE / "classify.py"])


class ClassificationViewTests(Base):
    VOCAB = """affiliation:
  private: {label: "個人"}
  c1: {label: "秘密の顧客", confidential: true}
kind:
  dev: {label: "開発"}
"""

    def setUp(self):
        super().setUp()
        if CLASSIFY_PY is None:
            self.skipTest("classify.py が見つかりません")
        self._env = {k: os.environ.get(k) for k in ("AIPLC_CLASSIFY", "AIPLC_CLASSIFICATION_VOCAB")}
        (self.root / "vocab.yaml").write_text(self.VOCAB, encoding="utf-8")
        os.environ["AIPLC_CLASSIFY"] = str(CLASSIFY_PY)
        os.environ["AIPLC_CLASSIFICATION_VOCAB"] = str(self.root / "vocab.yaml")
        cls = server._load("_t_classify", CLASSIFY_PY)
        conn = sqlite3.connect(self.db)
        with contextlib.redirect_stdout(io.StringIO()):
            cls.create_tables(conn)
        conn.execute("INSERT INTO project_classification (scope_id, affiliation, kind, executor) VALUES ('L-9001','private','dev','claude-code')")
        conn.execute("INSERT INTO project_classification (scope_id, affiliation) VALUES ('L-9003','c1')")
        conn.execute("INSERT INTO task_execution (scope_id, task_id, executed_by) VALUES ('L-9001','T002','codex')")
        conn.commit()
        conn.close()
        self.reg = server.Registry(self.db, self.root, **FULL)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def test_list_has_classification(self):
        data = self.reg.list_projects()
        self.assertTrue(data["classification_available"])
        self.assertEqual([e["key"] for e in data["vocab"]["affiliation"]], ["private", "c1"])
        by = {p["scope_id"]: p for p in data["projects"]}
        c = by["L-9001"]["classification"]
        self.assertEqual((c["affiliation"]["label"], c["kind"]["label"], c["executors"]), ("個人", "開発", ["claude-code", "codex"]))
        self.assertIsNone(by["L-9001-SG1"]["classification"]["affiliation"]["key"])

    def test_confidential_affiliation_marks_row(self):
        by = {p["scope_id"]: p for p in self.reg.list_projects()["projects"]}
        self.assertTrue(by["L-9003"]["confidential"])
        self.assertTrue(by["L-9003"]["classification"]["affiliation"]["confidential"])

    def test_detail_task_executor(self):
        d = self.reg.project_detail("L-9001")
        self.assertTrue(d["classification_available"])
        self.assertEqual({t["task_id"]: t["executed_by"] for t in d["tasks"]}["T002"], "codex")

    def test_without_tables_hidden(self):
        conn = sqlite3.connect(self.db)
        conn.execute("DROP TABLE project_classification")
        conn.commit()
        conn.close()
        data = self.reg.list_projects()
        self.assertFalse(data["classification_available"])
        self.assertIsNone(data["projects"][0]["classification"])


if __name__ == "__main__":
    unittest.main()
