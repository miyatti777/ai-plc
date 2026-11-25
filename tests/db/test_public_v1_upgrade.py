#!/usr/bin/env python3
"""v1.14.0 の公開版で作った DB を、今の core/db で開いて Identity v2.0 へ移行できるかを確かめる。

v1.8.1〜v1.14.0 の init_db は tasks の状態が英語（planned/active/completed/paused）・owner の既定なし・
type と system の CHECK なしの形で DB を作った。今の core/db はこの形も受け付ける:
  - adopt-existing（Identity 列を足して workspace manifest を書く。表は作り直さない）
  - migrate_identity_v2（表を作り直す。tasks の状態は 未着手/進行中/完了 へ写し、paused の行があれば止める）
v1.14.0 の init_db は tests/db/fixtures/init_db_v1_14_0.py に控えたもの（git show v1.14.0:core/db/init_db.py）。
Notion には送らない（urlopen は試験の中で止める）。一時フォルダだけを使う。

    python3 -m unittest tests/db/test_public_v1_upgrade.py -v
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest import mock

try:  # unittest discovery imports test modules as top-level modules.
    from .test_sync_harness import DB_DIR, load_module
except ImportError:  # pragma: no cover
    from test_sync_harness import DB_DIR, load_module

HERE = Path(__file__).resolve().parent
OLD_INIT_DB = HERE / "fixtures" / "init_db_v1_14_0.py"
WORKSPACE = "wsp_00000000-0000-4000-8000-0000000000a1"
WRITER = "writer-upgrade-test"
UIDS = [uuid.UUID("00000000-0000-4000-8000-0000000000%02x" % n) for n in range(1, 40)]


class PublicV1UpgradeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ai-plc-v1-upgrade-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db_dir = self.root / ".claude" / "db"
        self.db_dir.mkdir(parents=True)
        self.db = self.db_dir / "ai_plc.db"

    # ---- v1.14.0 の DB を作る ------------------------------------------------------------
    def _make_v1_db(self, task_statuses=("planned", "active", "completed")):
        shutil.copy2(OLD_INIT_DB, self.db_dir / "init_db.py")
        proc = subprocess.run([sys.executable, str(self.db_dir / "init_db.py")],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("INSERT INTO projects (scope_id, name, goal, status) "
                         "VALUES ('L-TEST-1', 'Project One', 'goal', 'active')")
            conn.execute("INSERT INTO projects (scope_id, name, status, owner) "
                         "VALUES ('L-TEST-2', 'Project Two', 'paused', 'someone')")
            for n, status in enumerate(task_statuses, start=1):
                conn.execute("INSERT INTO tasks (task_id, scope_id, name, status, type) "
                             "VALUES (?, 'L-TEST-1', ?, ?, 'research')",
                             ("T%03d" % n, "task %d" % n, status))
            conn.commit()
        # 今の core/db に入れ替える（導入の更新と同じく DB は残す）
        for name in ("init_db.py", "sync.py", "plc_query.py", "aiplc_paths.py"):
            shutil.copy2(DB_DIR / name, self.db_dir / name)

    def _load(self):
        suffix = id(self)
        init_db = load_module(self.db_dir / "init_db.py", f"upgrade_init_{suffix}")
        sync = load_module(self.db_dir / "sync.py", f"upgrade_sync_{suffix}")
        plc = load_module(self.db_dir / "plc_query.py", f"upgrade_plc_{suffix}")
        self.assertEqual(str(self.db), sync.DB_PATH)  # aiplc_paths は隣の DB を選ぶ（設定なし＝solo）
        self.assertEqual(str(self.db), plc.DB_PATH)
        sync.TOKEN = "dummy"
        sync.RATE_LIMIT_DELAY = 0
        plc.SYNC = sync
        guard = mock.patch.object(sync.urllib.request, "urlopen",
                                  side_effect=AssertionError("network access is forbidden"))
        guard.start()
        self.addCleanup(guard.stop)
        return init_db, sync, plc

    def _rows(self, sql):
        with closing(sqlite3.connect(self.db)) as conn:
            return conn.execute(sql).fetchall()

    def _run(self, script, *args):
        env = {k: v for k, v in os.environ.items()
               if k not in ("AI_PLC_PROJECTS_DB_ID", "AI_PLC_TASKS_DB_ID", "NOTION_API_TOKEN")}
        return subprocess.run([sys.executable, str(self.db_dir / script), *args], cwd=self.root,
                              capture_output=True, text=True, env=env, timeout=60)

    # ---- 試験 --------------------------------------------------------------------------
    def test_new_version_opens_v1_db_and_keeps_rows(self):
        self._make_v1_db()
        # init_db を通しても行は残り、分類の表が足される（既定の DB なので --allow-production）
        self.assertEqual(3, self._run("init_db.py").returncode)
        proc = self._run("init_db.py", "--allow-production")
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertEqual(2, self._rows("SELECT COUNT(*) FROM projects")[0][0])
        self.assertEqual(3, self._rows("SELECT COUNT(*) FROM tasks")[0][0])
        tables = {r[0] for r in self._rows("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"project_classification", "task_execution"} <= tables)
        # 読む道具は今までどおり動く
        for args in (("projects",), ("dashboard",), ("someday",)):
            proc = self._run("plc_query.py", *args)
            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        proc = self._run("sync.py", "tasks-sync", "--status")
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn("FROZEN", proc.stdout)  # v1.14.0 が新しい DB に入れた凍結の印を読める

    def test_adopt_existing_moves_v1_db_to_identity_v2(self):
        self._make_v1_db()
        init_db, sync, plc = self._load()
        decisions = self.root / "decisions.json"
        decisions.write_text(json.dumps({"adopt_decisions_version": 1, "decisions": []}),
                             encoding="utf-8")
        plan_path = self.root / "adopt-plan.json"
        out = io.StringIO()
        ids = iter(UIDS)
        with mock.patch.object(sync.uuid, "uuid4", side_effect=lambda: next(ids)), \
                contextlib.redirect_stdout(out):
            result = sync.main(["adopt-existing", "--dry-run", "--decisions", str(decisions),
                                "--writer-id", WRITER, "--plan-out", str(plan_path)])
        self.assertEqual(0, result, out.getvalue())
        plan_id = json.loads(plan_path.read_text(encoding="utf-8"))["plan_id"]
        with contextlib.redirect_stdout(out):
            result = sync.main(["adopt-existing", "--plan", str(plan_path), "--plan-id", plan_id])
        self.assertEqual(0, result, out.getvalue())
        self.assertTrue((self.db_dir / "workspace_identity.json").exists())
        with closing(sqlite3.connect(self.db)) as conn:
            conn.row_factory = sqlite3.Row
            self.assertEqual(2, sync._local_identity_schema_version(conn))
            missing = conn.execute(
                "SELECT COUNT(*) FROM projects WHERE sync_uid IS NULL OR workspace_id IS NULL"
            ).fetchone()[0]
        self.assertEqual(0, missing, out.getvalue())
        # adopt-existing は表を作り直さないので、tasks の状態は v1.14.0 の英語のまま残る（写すのは表の作り直しだけ）
        self.assertEqual([("T001", "planned"), ("T002", "active"), ("T003", "completed")],
                         [tuple(r) for r in self._rows(
                             "SELECT task_id, status FROM tasks ORDER BY task_id")])
        with closing(sqlite3.connect(self.db)) as conn:  # 凍結を解いた v1 の DB（集計を見るため）
            conn.execute("DELETE FROM _metadata WHERE key='task_sync_frozen'")
            conn.commit()
        out_dash = io.StringIO()
        with closing(sqlite3.connect(self.db)) as conn, contextlib.redirect_stdout(out_dash):
            conn.row_factory = sqlite3.Row
            plc.cmd_dashboard(conn)
        self.assertIn("Tasks: 3 total / 1 todo / 1 WIP / 1 done", out_dash.getvalue())
        # 移行の後も plc_query add-project が Identity を付けて追加できる
        out = io.StringIO()
        ids = iter(UIDS[20:])
        with mock.patch.object(sync.uuid, "uuid4", side_effect=lambda: next(ids)), \
                contextlib.redirect_stdout(out):
            result = plc.main(["plc_query.py", "add-project", "L-TEST-3", "Project Three", "goal"])
        self.assertEqual(0, result, out.getvalue())
        self.assertIn("Identity v2", out.getvalue())
        row = self._rows("SELECT workspace_id, sync_uid, identity_version FROM projects "
                         "WHERE scope_id='L-TEST-3'")[0]
        self.assertTrue(row[0] and row[1])
        self.assertEqual(2, row[2])

    def test_enforced_rebuild_maps_english_task_statuses(self):
        self._make_v1_db()
        init_db, _sync, _plc = self._load()
        with closing(sqlite3.connect(self.db)) as conn:
            mapping = {"identity_version": 2, "workspace_id": WORKSPACE,
                       "projects": {}, "tasks": {}}
            uids = {}
            for n, (row_id, scope) in enumerate(conn.execute(
                    "SELECT id, scope_id FROM projects ORDER BY id").fetchall(), start=1):
                uids[scope] = "prj_00000000-0000-4000-8000-%012d" % n
                mapping["projects"][str(row_id)] = uids[scope]
            for row_id, scope in conn.execute("SELECT id, scope_id FROM tasks ORDER BY id"):
                mapping["tasks"][str(row_id)] = uids[scope]
            with contextlib.redirect_stdout(io.StringIO()):
                result = init_db.migrate_identity_v2(conn, mapping)
            self.assertFalse(result["already_migrated"])
            self.assertTrue(init_db._identity_v2_enforced(conn))
            self.assertEqual(
                [("T001", "未着手"), ("T002", "進行中"), ("T003", "完了")],
                [tuple(r) for r in conn.execute(
                    "SELECT task_id, status FROM tasks ORDER BY task_id").fetchall()])
            self.assertEqual([("L-TEST-1", None, "active"), ("L-TEST-2", "someone", "paused")],
                             [tuple(r) for r in conn.execute(
                                 "SELECT scope_id, owner, status FROM projects "
                                 "ORDER BY scope_id").fetchall()])
            # 2回目は「済み」として何も変えない
            self.assertTrue(init_db.migrate_identity_v2(conn, mapping)["already_migrated"])

    def test_enforced_rebuild_stops_on_paused_task(self):
        self._make_v1_db(task_statuses=("planned", "paused"))
        init_db, _sync, _plc = self._load()
        with closing(sqlite3.connect(self.db)) as conn:
            before = [tuple(r) for r in conn.execute("SELECT sql FROM sqlite_master ORDER BY name")]
            mapping = {"identity_version": 2, "workspace_id": WORKSPACE, "tasks": {},
                       "projects": {str(r[0]): "prj_00000000-0000-4000-8000-%012d" % r[0]
                                    for r in conn.execute("SELECT id FROM projects")}}
            first = mapping["projects"][str(conn.execute(
                "SELECT id FROM projects WHERE scope_id='L-TEST-1'").fetchone()[0])]
            for (row_id,) in conn.execute("SELECT id FROM tasks"):
                mapping["tasks"][str(row_id)] = first
            with self.assertRaisesRegex(ValueError, "PUBLIC_V1_TASK_STATUS_UNSUPPORTED: paused"):
                init_db.migrate_identity_v2(conn, mapping)
            self.assertEqual(before, [tuple(r) for r in conn.execute(
                "SELECT sql FROM sqlite_master ORDER BY name")])  # 何も変えていない

    def test_missing_notion_db_id_is_reported_without_network(self):
        self._make_v1_db()
        proc = self._run("init_db.py", "--allow-production")
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        env_extra = {"NOTION_API_TOKEN": "dummy"}  # トークンはあり、DB の ID が無い
        for args in (("preflight",), ("pull", "--dry-run")):
            env = {k: v for k, v in os.environ.items()
                   if k not in ("AI_PLC_PROJECTS_DB_ID", "AI_PLC_TASKS_DB_ID")}
            env.update(env_extra)
            proc = subprocess.run([sys.executable, str(self.db_dir / "sync.py"), *args],
                                  cwd=self.root, capture_output=True, text=True, env=env, timeout=60)
            out = proc.stdout + proc.stderr
            self.assertNotEqual(0, proc.returncode, out)
            self.assertIn("NOTION_DB_ID_MISSING", out)
            self.assertIn("AI_PLC_PROJECTS_DB_ID", out)
            self.assertNotIn("AUTH_ERROR", out)

    def test_other_shapes_are_still_refused(self):
        self._make_v1_db()
        init_db, _sync, _plc = self._load()
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("ALTER TABLE tasks ADD COLUMN extra TEXT")
            mapping = {"identity_version": 2, "workspace_id": WORKSPACE,
                       "projects": {}, "tasks": {}}
            with self.assertRaisesRegex(ValueError, "IDENTITY_MIGRATION_UNSUPPORTED_COLUMN"):
                init_db.migrate_identity_v2(conn, mapping)


if __name__ == "__main__":
    unittest.main()
