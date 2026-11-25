#!/usr/bin/env python3
"""Registry ビューアの回帰テスト（一時 SQLite・一時 Layer だけを使う。プロジェクトの DB や Flow には書かない）。

    python3 -m unittest discover -s experimental/registry-viewer/tests      # 公開リポの checkout で
    python3 -m unittest discover -s .claude/db/registry_viewer/tests        # プロジェクトに置いたとき

DB は合成する。スキーマは core の init_db.py の create_schema()（公開リポでは core/db/、プロジェクトに置いたときは
.claude/db/）でメモリ上に作った DB から写し、見つからなければ内蔵の最小スキーマを使う（プロジェクトの DB は開かない）。
v1.8.1〜v1.14.0 の公開版 init_db.py（英語語彙。tests/db/fixtures/init_db_v1_14_0.py）が見つかれば、そのスキーマでも
閲覧専用のテストを回す。
"""
import contextlib
import http.client
import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.dont_write_bytecode = True
import server  # noqa: E402

PUBLIC_REPO = HERE.parents[2]  # 公開リポでは <repo>/experimental/registry-viewer/tests
INSTALLED_DB_DIR = HERE.parents[1]  # プロジェクトに置いたときは <project>/.claude/db/registry_viewer/tests


def _first(env, candidates):
    v = os.environ.get(env)
    if v:
        return Path(v) if Path(v).is_file() else None
    return next((c for c in candidates if c and c.is_file()), None)


# 食い違い・機密判定のテストに使う依存。環境変数 → このプロジェクトの配置 → 公開リポの配置 の順。無ければ skip
_deps = server.find_dependencies(server.REPO) if server.REPO else (None, None, None)
AUDIT_PATH = _first("AIPLC_STATUS_AUDIT", [_deps[0], PUBLIC_REPO / "experimental" / "jev" / "scripts" / "aiplc_status_audit.py"])
_MISSING_DEPS = None if AUDIT_PATH else "aiplc_status_audit.py が見つかりません（AIPLC_STATUS_AUDIT で指定できます）"
FULL = {"audit_path": AUDIT_PATH}
# 今の core の init_db.py（日本語語彙・cancelled あり）
CORE_INIT_DB = _first("AIPLC_CORE_INIT_DB", [PUBLIC_REPO / "core" / "db" / "init_db.py",
                                             INSTALLED_DB_DIR / "init_db.py"])
# v1.14.0 までの公開版 init_db.py（英語語彙のスキーマ）
INIT_DB = _first("AIPLC_INIT_DB", [PUBLIC_REPO / "tests" / "db" / "fixtures" / "init_db_v1_14_0.py"])
JA = {"todo": "未着手", "wip": "進行中", "done": "完了"}
EN = {"todo": "planned", "wip": "active", "done": "completed"}
FALLBACK_SCHEMA = [
    """CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, notion_page_id TEXT UNIQUE, scope_id TEXT NOT NULL UNIQUE,
       name TEXT NOT NULL, goal TEXT, owner TEXT DEFAULT 'owner', status TEXT NOT NULL DEFAULT 'planned'
       CHECK(status IN ('planned','active','completed','paused','cancelled')), mode TEXT DEFAULT 'direct', depth TEXT DEFAULT 'standard',
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
]


def schema_from(init_db_path):
    """init_db.py の create_schema() でメモリ上に作った DB から DDL を写す（行は写さない）"""
    mod = server._load("_rv_init_db_" + str(abs(hash(str(init_db_path)))), init_db_path)
    conn = sqlite3.connect(":memory:")
    with contextlib.redirect_stdout(io.StringIO()):  # create_schema の完了表示を出さない
        mod.create_schema(conn)
    rows = conn.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
                        "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END").fetchall()
    conn.close()
    return [r[0] for r in rows]


def current_schema():
    return schema_from(CORE_INIT_DB) if CORE_INIT_DB else FALLBACK_SCHEMA


INTENT = """scope_id: "{sid}"
scope_name: "{name}"
status: {status}   # コメントは残る
workflow_depth: standard
pipeline_variant: jev
goal:
  description: "テスト用の目標"
parent_scope: {parent}
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
"""


class DataBase(unittest.TestCase):
    """一時 DB と一時 Layer だけを作る（依存の有無は見ない）"""
    V = JA  # tasks.status の語彙

    def schema(self):
        return current_schema()

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

    def sql(self, sql, args=()):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(sql, args)
            conn.commit()
        finally:
            conn.close()

    def reg_status(self, sql, args):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(sql, args).fetchone()
        finally:
            conn.close()

    def backlog_text(self, folder="parent-layer"):
        return (self.flow / folder / "backlog.yaml").read_text(encoding="utf-8")

    def files_and_db(self):
        c = sqlite3.connect(self.db)
        try:
            rows = tuple(c.iterdump())
        finally:
            c.close()
        files = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*.yaml")}
        return rows, files


class Base(DataBase):
    """status_audit つきの Registry（見つからなければ skip）"""

    def setUp(self):
        super().setUp()
        if _MISSING_DEPS:
            self.skipTest(_MISSING_DEPS)
        self.reg = server.Registry(self.db, self.root, **FULL)


class ListCacheTests(Base):
    def test_cached_list_reuses_result_within_ttl(self):
        first = self.reg.list_projects_cached(ttl=60)
        self.assertIs(self.reg.list_projects_cached(ttl=60), first)
        self.assertIsNot(self.reg.list_projects_cached(ttl=0), first)

    def test_cached_list_recomputes_when_db_changes(self):
        first = self.reg.list_projects_cached(ttl=60)
        st = self.db.stat()
        os.utime(self.db, (st.st_atime, st.st_mtime + 5))
        self.assertIsNot(self.reg.list_projects_cached(ttl=60), first)


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
        self.assertEqual(data["viewer_mode"], "readonly")
        self.assertIn("閲覧専用", data["viewer_mode_reason"])
        self.assertIn("activity", by["L-9001"])

    def test_detail_merges_tasks(self):
        d = self.reg.project_detail("L-9001")
        tasks = {t["task_id"]: t for t in d["tasks"]}
        self.assertEqual(list(tasks), ["T001", "T002", "T003", "T004"])
        self.assertTrue(tasks["T001"]["in_layer"] and tasks["T001"]["in_registry"])
        self.assertFalse(tasks["T001"]["mismatch"])
        self.assertFalse(tasks["T003"]["in_registry"])
        self.assertFalse(tasks["T004"]["in_layer"])
        self.assertEqual(d["children"], ["L-9001-SG1"])
        self.assertFalse(d["writable"])
        # pipeline_variant: jev の Layer も本体版のコマンドを出す（実験版 ai-plc-jev は凍結中）
        self.assertEqual(d["launch_prompt"], "/04-operation を実行してください / Layer: Flow/209901/2099-01-01/parent-layer")

    def test_launch_prompt_by_state(self):
        d = self.flow / "empty-layer"
        d.mkdir()
        (d / "intent.yaml").write_text('scope_id: "L-9004"\nstatus: active\nworkflow_depth: standard\n', encoding="utf-8")
        self.sql("INSERT INTO projects (scope_id, name, status) VALUES ('L-9004', '空', 'active')")
        self.assertTrue(self.reg.project_detail("L-9004")["launch_prompt"].startswith("/02-inception "))
        (d / "intent.yaml").write_text('scope_id: "L-9004"\nstatus: active\nworkflow_depth: simple\n', encoding="utf-8")
        self.assertTrue(self.reg.project_detail("L-9004")["launch_prompt"].startswith("/04-operation "))
        (d / "intent.yaml").write_text('scope_id: "L-9004"\nstatus: completed\nworkflow_depth: simple\n', encoding="utf-8")
        self.assertIn("Re-Collection", self.reg.project_detail("L-9004")["launch_prompt"])
        self.assertNotIn("-jev", self.reg.project_detail("L-9004")["launch_prompt"])

    def test_cancelled_project_listed_without_launch_prompt(self):
        if CORE_INIT_DB is None and "cancelled" not in FALLBACK_SCHEMA[0]:
            self.skipTest("cancelled の無いスキーマ")
        self.sql("UPDATE projects SET status='cancelled' WHERE scope_id='L-9003'")
        p = self.flow / "done-layer" / "intent.yaml"
        p.write_text(p.read_text(encoding="utf-8").replace("status: active", "status: cancelled")
                     + "cancellation:\n  reason: \"合成の理由\"\n  decided_at: \"2099-01-05\"\n", encoding="utf-8")
        data = self.reg.list_projects()
        self.assertEqual(data["counts"]["by_status"]["cancelled"], 1)
        self.assertIn("L-9003", {x["scope_id"] for x in data["projects"]})
        self.assertFalse({x["scope_id"]: x for x in data["projects"]}["L-9003"]["status_mismatch"])
        d = self.reg.project_detail("L-9003")
        self.assertIsNone(d["launch_prompt"])
        self.assertEqual(d["cancellation"]["reason"], "合成の理由")

    def test_detail_task_has_schedule_and_due(self):
        """タスクの詳細に backlog の scheduled_for と due を書いたまま出す（無ければ None）"""
        p = self.flow / "parent-layer" / "backlog.yaml"
        text = p.read_text(encoding="utf-8").replace('    priority: P1\n', "    priority: P1\n    scheduled_for: 2099-W44\n    due: '2099-10-30'\n", 1)
        p.write_text(text, encoding="utf-8")
        tasks = {t["task_id"]: t for t in self.reg.project_detail("L-9001")["tasks"]}
        self.assertEqual((tasks["T002"]["scheduled_for"], tasks["T002"]["due"]), ("2099-W44", "2099-10-30"))
        self.assertEqual((tasks["T001"]["scheduled_for"], tasks["T001"]["due"]), (None, None))
        self.assertEqual((tasks["T004"]["scheduled_for"], tasks["T004"]["due"]), (None, None))  # Registry だけ

    def test_recurring_task_not_counted(self):
        p = self.flow / "parent-layer" / "backlog.yaml"
        p.write_text(p.read_text(encoding="utf-8").replace(
            "summary:", "  - id: R1\n    name: \"毎週の運用\"\n    status: in_progress\n    recurrence: weekly\nsummary:", 1),
            encoding="utf-8")
        by = {x["scope_id"]: x for x in self.reg.list_projects()["projects"]}
        self.assertEqual(by["L-9001"]["progress"], {"done": 1, "total": 3, "source": "backlog"})
        tasks = {t["task_id"]: t for t in self.reg.project_detail("L-9001")["tasks"]}
        self.assertEqual(tasks["R1"]["recurrence"], "weekly")  # 詳細の表には出す

    def test_list_sorted_with_numeric_scope_ids(self):
        """更新の根拠が同じ（どれも Layer なし）なら、scope_id の数字は数として比べる（-2 が -12 より前）"""
        for sid in ("L-9005-12", "L-9005-2"):
            self.sql("INSERT INTO projects (scope_id, name, status, created_at) VALUES (?, 'x', 'active', '2099-01-01')",
                     (sid,))
        ids = [x["scope_id"] for x in self.reg.list_projects()["projects"]]
        self.assertLess(ids.index("L-9005-2"), ids.index("L-9005-12"))

    def test_detail_readonly_without_layer(self):
        d = self.reg.project_detail("L-9002")
        self.assertFalse(d["writable"])
        self.assertIsNone(d["launch_prompt"])

    def test_detail_404(self):
        with self.assertRaises(server.WriteError) as cm:
            self.reg.project_detail("L-0000")
        self.assertEqual(cm.exception.code, 404)


class ReadonlyMutationTests(Base):
    def test_all_old_direct_mutations_reject_without_changes(self):
        before = self.files_and_db()
        self.reg.mode = "full"  # 以前の版の印を書き換えても書けない
        for sid in ("L-9001", "L-9003", "L-9002", "UNKNOWN"):
            for status in ("active", "paused", "completed", "cancelled", "invalid"):
                with self.subTest(sid=sid, status=status):
                    with self.assertRaises(server.WriteError) as cm:
                        self.reg.set_project_status(sid, status, {"intent": "active", "registry": "active"})
                    self.assertEqual(405, cm.exception.code)
                    self.assertIn("VIEWER_READ_ONLY", str(cm.exception))
                    with self.assertRaises(server.WriteError) as cm:
                        self.reg.set_task_status(sid, "T002", status, {"backlog": "pending", "registry": self.V["todo"]})
                    self.assertEqual(405, cm.exception.code)
        self.assertEqual(before, self.files_and_db())
        self.assertFalse(self.reg.project_detail("L-9001")["writable"])
        self.assertTrue(all(not t["editable"] for t in self.reg.project_detail("L-9001")["tasks"]))

    def test_write_helpers_removed(self):
        for name in ("write_task_status", "_atomic_write", "edit_task_status_text", "PROJECT_CHOICES", "TASK_CHOICES"):
            self.assertFalse(hasattr(server, name))
        for name in ("_registry_update", "_rollback", "_current_layer", "_log"):
            self.assertFalse(hasattr(self.reg, name))

    def test_flow_and_block_tasks_remain_readable(self):
        (self.flow / "done-layer" / "backlog.yaml").write_text("tasks:\n  - {id: T001, name: x, status: completed}\n")
        self.assertEqual("completed", self.reg.project_detail("L-9003")["tasks"][0]["layer_status"])

    def test_reading_does_not_change_db_or_files(self):
        before = self.files_and_db()
        db_bytes = self.db.read_bytes()
        self.reg.list_projects()
        self.reg.project_detail("L-9001")
        self.assertEqual(before, self.files_and_db())
        self.assertEqual(db_bytes, self.db.read_bytes())


class HttpTests(Base):
    def setUp(self):
        super().setUp()
        self.httpd, self.token, _ = server.build_server(self.db, self.root, 0, token="tkn", **FULL)
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

    def test_index_has_token(self):
        st, data = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b'const TOKEN = "tkn"', data)

    def test_api_projects(self):
        st, data = self.req("GET", "/api/projects")
        self.assertEqual(st, 200)
        self.assertEqual(len(json.loads(data)["projects"]), 4)

    def test_api_health(self):
        st, data = self.req("GET", "/api/health")
        self.assertEqual(st, 200)
        self.assertTrue(json.loads(data)["ok"])

    def test_head_has_no_body(self):
        st, data = self.req("HEAD", "/api/health")
        self.assertEqual((st, data), (200, b""))

    def test_bad_host(self):
        st, _ = self.req("GET", "/api/projects", headers={"Host": f"evil.example:{self.port}"})
        self.assertEqual(st, 403)

    def test_mutation_methods_reject_without_changes(self):
        before = self.files_and_db()
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            for path in ("/api/projects/L-9001-SG1/status", "/api/projects/L-9001/tasks/T002/status", "/api/projects"):
                for headers in ({}, {"Content-Type": "application/json", "X-Viewer-Token": "tkn",
                                     "Origin": f"http://127.0.0.1:{self.port}"}):
                    with self.subTest(method=method, path=path, headers=headers):
                        code, data = self.req(method, path, {"to": "completed", "expected": {"registry": "active"}},
                                              headers=headers)
                        self.assertEqual(405, code, data)
                        self.assertIn("VIEWER_READ_ONLY", json.loads(data)["error"])
        self.assertEqual(before, self.files_and_db())

    def test_mutation_bad_origin_rejected(self):
        code, _ = self.req("POST", "/api/projects/L-9001/status", {"to": "paused"},
                           {"Content-Type": "application/json", "Origin": "http://evil.example"})
        self.assertEqual(403, code)

    def test_html_contains_no_edit_controls(self):
        code, html = self.req("GET", "/")
        self.assertEqual(200, code)
        for marker in (b"project-status-apply", b"task-status-apply", b"project-status-select", b"confirm-dialog",
                       b"async function post(", b"method: \"POST\""):
            self.assertNotIn(marker, html)

    def test_bad_ids(self):
        st, _ = self.req("GET", "/api/projects/..%2F..%2Fetc")
        self.assertEqual(st, 404)

    def test_unknown_routes_are_404(self):
        for path in ("/api/unknown", "/api/projects/L-9001/tasks", "/static/../server.py"):
            st, _ = self.req("GET", path, headers={"X-Viewer-Token": "tkn"})
            self.assertEqual(st, 404, path)


# ---------------------------------------------------------------- v1.14.0 までの公開版スキーマ（英語語彙）
class _PublicV1Schema:
    V = EN

    def schema(self):
        return schema_from(INIT_DB)

    def setUp(self):
        if INIT_DB is None:
            self.skipTest("v1.14.0 の公開版 init_db.py が見つかりません（AIPLC_INIT_DB で指定できます）")
        super().setUp()


class PublicV1ReadTests(_PublicV1Schema, ReadTests):
    def test_cancelled_project_listed_without_launch_prompt(self):
        self.skipTest("v1.14.0 までのスキーマには cancelled が無いことがある")


class PublicV1ReadonlyMutationTests(_PublicV1Schema, ReadonlyMutationTests):
    pass


# ---------------------------------------------------------------- 依存の探し方・DB の場所・閲覧のみの表示
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
        self.assertIn("食い違い", why)

    def test_search_order(self):
        jev = self.touch(".claude/ai-plc-jev/scripts/aiplc_status_audit.py")
        plc = self.touch(".cursor/db/plc_query.py")
        self.assertEqual(server.find_dependencies(self.root)[:2], (jev, plc))
        own = self.touch("scripts/aiplc_status_audit.py")
        plc2 = self.touch(".claude/db/plc_query.py")
        self.assertEqual(server.find_dependencies(self.root), (own, plc2, None))

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


class DbPathTests(unittest.TestCase):
    """DB の場所: aiplc_paths.py があればその決め方（.ai-plc/config.yaml の db_path など）、無ければ隣の DB"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rv_path_")
        self.root = Path(self.tmp.name)
        (self.root / ".claude" / "db").mkdir(parents=True)
        (self.root / ".claude" / "db" / "ai_plc.db").write_bytes(b"")

    def tearDown(self):
        self.tmp.cleanup()

    def test_without_aiplc_paths_uses_neighbor_db(self):
        orig = server._aiplc_paths
        server._aiplc_paths = lambda: None
        try:
            self.assertEqual(server.default_db(self.root), self.root / ".claude" / "db" / "ai_plc.db")
        finally:
            server._aiplc_paths = orig

    def test_broken_aiplc_paths_falls_back(self):
        class Broken:
            @staticmethod
            def resolve_db(*_a, **_k):
                raise RuntimeError("壊れた版")
        orig = server._aiplc_paths
        server._aiplc_paths = lambda: Broken
        try:
            self.assertEqual(server.default_db(self.root), self.root / ".claude" / "db" / "ai_plc.db")
        finally:
            server._aiplc_paths = orig

    def test_config_db_path_followed(self):
        paths = server._aiplc_paths()
        if paths is None:
            self.skipTest("aiplc_paths.py が見つかりません")
        other = self.root / "elsewhere" / "ai_plc.db"
        other.parent.mkdir()
        other.write_bytes(b"")
        (self.root / ".ai-plc").mkdir()
        (self.root / ".ai-plc" / "config.yaml").write_text(
            "id_allocation:\n  mode: solo\n  db_path: elsewhere/ai_plc.db\n", encoding="utf-8")
        self.assertEqual(server.default_db(self.root).resolve(), other.resolve())


class ReadonlyModeTests(DataBase):
    """status_audit が無い環境（core だけ）での閲覧"""

    def setUp(self):
        super().setUp()
        self.ro = server.Registry(self.db, self.root, readonly_reason="テストでは依存なし")

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
        self.assertIn("閲覧専用", d["readonly_reason"])
        self.assertEqual([t["task_id"] for t in d["tasks"]], ["T001", "T002", "T003", "T004"])
        self.assertFalse(any(t["mismatch"] or t["editable"] for t in d["tasks"]))
        self.assertEqual(d["mode"], "direct")  # Project の mode 列は上書きされない

    def test_recurring_tasks_match_the_real_audit(self):
        """代わりの読み取りでも運用タスクは tasks・open から外し（raw_tasks には残す）、本物の status audit と進捗が合う。
        運用タスクだけの Layer は /04-operation から始める"""
        d = self.root / "Flow" / "209901" / "2099-01-01" / "ops-layer"
        d.mkdir(parents=True)
        (d / "intent.yaml").write_text('scope_id: "L-9031"\nstatus: active\nworkflow_depth: standard\n', encoding="utf-8")
        weekly = "  - id: R1\n    status: in_progress\n    recurrence: weekly\n"
        (d / "backlog.yaml").write_text("tasks:\n  - id: T1\n    status: completed\n  - id: T2\n    status: pending\n"
                                        + weekly, encoding="utf-8")
        ro = server._ReadonlyAudit.Layer(self.root, d)
        self.assertEqual([t for t, _, _ in ro.tasks], ["T1", "T2"])
        self.assertEqual(ro.open, 1)
        self.assertEqual([t["id"] for t in ro.raw_tasks], ["T1", "T2", "R1"])
        self.assertEqual(server.Registry.progress(ro, []), {"done": 1, "total": 2, "source": "backlog"})
        if AUDIT_PATH is not None:
            # 公開版の status audit は運用タスクも tasks に入れるが、進捗はビューア側で外すので同じになる
            real = server._load("_rv_audit_rec", AUDIT_PATH).Layer(self.root, d)
            self.assertEqual(server.Registry.progress(real, []), server.Registry.progress(ro, []))
        (d / "backlog.yaml").write_text("tasks:\n" + weekly, encoding="utf-8")
        ro = server._ReadonlyAudit.Layer(self.root, d)
        row = {"status": "active"}
        self.assertEqual(server.Registry.launch_prompt("L-9031", row, ro),
                         "/04-operation を実行してください / Layer: Flow/209901/2099-01-01/ops-layer")
        if AUDIT_PATH is not None:
            real = server._load("_rv_audit_rec2", AUDIT_PATH).Layer(self.root, d)
            self.assertEqual(server.Registry.launch_prompt("L-9031", row, real), server.Registry.launch_prompt("L-9031", row, ro))

    def test_writes_refused(self):
        for call in (lambda: self.ro.set_task_status("L-9001", "T002", "completed", {}),
                     lambda: self.ro.set_project_status("L-9003", "completed", {})):
            with self.assertRaises(server.WriteError) as cm:
                call()
            self.assertEqual(cm.exception.code, 405)
        self.assertIn("    status: pending", self.backlog_text())

    def test_duplicate_folder_marked(self):
        self._layer("L-9003", "done-layer-copy", "active", None)
        self.assertTrue(self.ro.project_detail("L-9003")["duplicate_folder"])

    def test_audit_found_shows_audit_features(self):
        if AUDIT_PATH is None:
            self.skipTest("aiplc_status_audit.py が見つかりません")
        r = server.Registry(self.db, self.root, audit_path=AUDIT_PATH)
        data = r.list_projects()
        self.assertEqual(data["viewer_mode"], "readonly")
        self.assertTrue(data["audit_available"])

    def test_unloadable_audit_falls_back(self):
        bad = self.root / "broken_audit.py"
        bad.write_text("import jev_client_that_does_not_exist\n", encoding="utf-8")
        data = server.Registry(self.db, self.root, audit_path=bad).list_projects()
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
        data = server.Registry(self.db, self.root, audit_path=old).list_projects()
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
        self.sql("DROP TABLE project_classification")
        data = self.reg.list_projects()
        self.assertFalse(data["classification_available"])
        self.assertIsNone(data["projects"][0]["classification"])


class TaskFreezeTests(Base):
    """タスク同期の凍結中（_metadata の task_sync_frozen）は、Registry の古い tasks 行を読まない"""

    def setUp(self):
        super().setUp()
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE IF NOT EXISTS _metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT OR REPLACE INTO _metadata (key, value) VALUES ('task_sync_frozen', ?)",
                     (json.dumps({"approved_by": "test", "reason": "", "frozen_at": "2099-01-01T00:00:00Z"}),))
        # 凍結前に残った古い行: 完了済み Layer に未完了の Registry タスク
        conn.execute("INSERT INTO tasks (task_id, scope_id, name, status, priority) VALUES (?,?,?,?,?)",
                     ("T009", "L-9003", "古い写し", self.V["todo"], "P1"))
        conn.commit()
        conn.close()

    def test_detail_ignores_registry_tasks(self):
        d = self.reg.project_detail("L-9001")
        tasks = {t["task_id"]: t for t in d["tasks"]}
        self.assertEqual(list(tasks), ["T001", "T002", "T003"])  # Registry だけの T004 は出ない
        self.assertFalse(any(t["in_registry"] for t in tasks.values()))
        self.assertTrue(all(t["in_layer"] for t in tasks.values()))

    def test_stale_rows_do_not_affect_progress(self):
        by = {p["scope_id"]: p for p in self.reg.list_projects()["projects"]}
        self.assertEqual(by["L-9003"]["progress"], {"done": 1, "total": 1, "source": "backlog"})
        self.assertEqual(by["L-9002"]["progress"], {"done": 0, "total": 0, "source": None})

    def test_task_write_rejected_and_rows_unchanged(self):
        before = self.files_and_db()
        with self.assertRaises(server.WriteError) as cm:
            self.reg.set_task_status("L-9001", "T002", "completed", {"backlog": "pending", "registry": None})
        self.assertEqual(405, cm.exception.code)
        self.assertEqual(before, self.files_and_db())


if __name__ == "__main__":
    unittest.main()
