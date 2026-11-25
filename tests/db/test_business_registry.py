#!/usr/bin/env python3
"""business_registry.py（業務Project の表）を、合成の DB と一時フォルダだけで確かめる。

Registry は v1.14.0 の init_db で作り、sync.py adopt-existing で Identity v2.0 にしてから使う（利用者と同じ道）。
箱の道具（aipm-guided の package.py）に archive_business があれば、business: registry の行き先をこの表から
引けることも確かめる（無い版では skip）。Notion には送らない。

    python3 -m unittest tests/db/test_business_registry.py -v
"""

from __future__ import annotations

import contextlib
import importlib.util
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
from datetime import datetime, timedelta, timezone
from contextlib import closing
from pathlib import Path
from unittest import mock

try:  # unittest discovery imports test modules as top-level modules.
    from .test_sync_harness import DB_DIR, REPO_ROOT, load_module
except ImportError:  # pragma: no cover
    from test_sync_harness import DB_DIR, REPO_ROOT, load_module

HERE = Path(__file__).resolve().parent
OLD_INIT_DB = HERE / "fixtures" / "init_db_v1_14_0.py"
PACKAGE = REPO_ROOT / "core" / "skills" / "aipm-guided" / "package.py"
UIDS = [uuid.UUID("00000000-0000-4000-8000-0000000001%02x" % n) for n in range(1, 60)]


class BusinessRegistryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ai-plc-business-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db_dir = self.root / ".claude" / "db"
        self.db_dir.mkdir(parents=True)
        self.db = self.db_dir / "ai_plc.db"
        shutil.copy2(OLD_INIT_DB, self.db_dir / "init_db.py")
        proc = subprocess.run([sys.executable, str(self.db_dir / "init_db.py")],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        with closing(sqlite3.connect(self.db)) as conn:
            for scope in ("L-TEST-1", "L-TEST-2"):
                conn.execute("INSERT INTO projects (scope_id, name, status) VALUES (?, ?, 'active')",
                             (scope, "Project " + scope))
            conn.commit()
        for name in ("init_db.py", "sync.py", "plc_query.py", "aiplc_paths.py", "business_registry.py"):
            shutil.copy2(DB_DIR / name, self.db_dir / name)

    def _adopt(self):
        sync = load_module(self.db_dir / "sync.py", f"business_sync_{id(self)}")
        sync.TOKEN = "dummy"
        guard = mock.patch.object(sync.urllib.request, "urlopen",
                                  side_effect=AssertionError("network access is forbidden"))
        guard.start()
        self.addCleanup(guard.stop)
        decisions = self.root / "decisions.json"
        decisions.write_text(json.dumps({"adopt_decisions_version": 1, "decisions": []}), encoding="utf-8")
        plan = self.root / "adopt-plan.json"
        ids = iter(UIDS)
        out = io.StringIO()
        with mock.patch.object(sync.uuid, "uuid4", side_effect=lambda: next(ids)), \
                contextlib.redirect_stdout(out):
            self.assertEqual(0, sync.main(["adopt-existing", "--dry-run", "--decisions", str(decisions),
                                           "--writer-id", "writer-test", "--plan-out", str(plan)]),
                             out.getvalue())
            plan_id = json.loads(plan.read_text(encoding="utf-8"))["plan_id"]
            self.assertEqual(0, sync.main(["adopt-existing", "--plan", str(plan), "--plan-id", plan_id]),
                             out.getvalue())

    def _run(self, *args):
        env = {k: v for k, v in os.environ.items()
               if k not in ("AI_PLC_PROJECTS_DB_ID", "AI_PLC_TASKS_DB_ID", "NOTION_API_TOKEN", "AIPLC_DB")}
        proc = subprocess.run([sys.executable, str(self.db_dir / "business_registry.py"), *args],
                              cwd=self.root, capture_output=True, text=True, env=env, timeout=60)
        return proc.returncode, proc.stdout + proc.stderr

    def _count(self, table):
        with closing(sqlite3.connect(self.db)) as conn:
            return conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]

    def _setup_business(self):
        self._adopt()
        for args in (("init", "--yes"), ("add-program", "Sample", "--yes"),
                     ("add-business", "Sample", "Alpha Work", "--purpose", "first purpose", "--yes"),
                     ("link", "L-TEST-1", "Alpha Work", "--yes")):
            code, out = self._run(*args)
            self.assertEqual(0, code, out)

    # ---- tests ------------------------------------------------------------------------------------
    def test_v1_registry_is_refused_before_adopt(self):
        code, out = self._run("init", "--yes")
        self.assertEqual(3, code, out)
        self.assertIn("nothing was written", out)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertFalse(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='business_projects'").fetchone())

    def test_writes_need_yes(self):
        self._adopt()
        code, out = self._run("init")
        self.assertEqual(0, code, out)
        self.assertIn("[PLAN]", out)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertFalse(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='programs'").fetchone())
        self.assertEqual(0, self._run("init", "--yes")[0])
        self.assertIn("[PLAN]", self._run("add-program", "Sample")[1])
        self.assertEqual(0, self._count("programs"))

    def test_program_business_link_where_list(self):
        self._setup_business()
        code, out = self._run("where", "L-TEST-1")
        self.assertEqual((0, "Stock/programs/Sample/projects/Alpha Work/<project>/\n"), (code, out))
        with closing(sqlite3.connect(self.db)) as conn:
            conn.row_factory = sqlite3.Row
            link = conn.execute("SELECT * FROM business_project_links").fetchone()
            project = conn.execute("SELECT * FROM projects WHERE id=?", (link["project_id"],)).fetchone()
            self.assertEqual(project["sync_uid"], link["aiplc_uid"])
            self.assertEqual(project["workspace_id"], link["workspace_id"])
            self.assertEqual("primary", link["relation_type"])
            self.assertEqual([], conn.execute("PRAGMA foreign_key_check").fetchall())
        code, out = self._run("list")
        self.assertEqual(0, code, out)
        self.assertIn("stock:Sample / Alpha Work  [active]  L-TEST-1:primary", out)
        data = json.loads(self._run("list", "--json")[1])
        self.assertEqual(["stock:Sample"], [p["definition_key"] for p in data["programs"]])

    def test_refusals_write_nothing(self):
        self._setup_business()
        self.assertEqual(0, self._run("add-business", "Sample", "Beta Work", "--purpose", "p", "--yes")[0])
        before = {t: self._count(t) for t in ("programs", "business_projects", "program_memberships",
                                              "business_project_links")}
        cases = [
            (("add-program", "Sample", "--yes"), 2, "PROGRAM_EXISTS"),
            (("add-business", "Nope", "X", "--purpose", "p", "--yes"), 2, "PROGRAM_NOT_UNIQUE"),
            (("add-business", "Sample", "alpha work", "--purpose", "p", "--yes"), 2, "BUSINESS_EXISTS"),
            (("link", "L-TEST-1", "Beta Work", "--yes"), 2, "PRIMARY_EXISTS"),
            (("link", "L-TEST-1", "Alpha Work", "--related", "--yes"), 2, "LINK_EXISTS"),
            (("link", "L-MISSING", "Alpha Work", "--yes"), 3, "SCOPE_NOT_UNIQUE"),
            (("where", "L-TEST-2"), 2, "NO_PRIMARY"),
            (("add-program", "a/b", "--yes"), 2, "NAME_INVALID"),
            (("add-program", "a:b", "--yes"), 2, "NAME_INVALID"),
            (("add-program", "sample", "--yes"), 2, "PROGRAM_EXISTS"),
            (("add-business", "Sample", "Trail.", "--purpose", "p", "--yes"), 2, "NAME_INVALID"),
            (("add-business", "Sample", ".hidden", "--purpose", "p", "--yes"), 2, "NAME_INVALID"),
            (("add-business", "Sample", "Tab\there", "--purpose", "p", "--yes"), 2, "NAME_INVALID"),
        ]
        for args, expected, code_name in cases:
            with self.subTest(args=args):
                code, out = self._run(*args)
                self.assertEqual(expected, code, out)
                self.assertIn(code_name, out)
                self.assertIn("nothing was written", out)
        self.assertEqual(before, {t: self._count(t) for t in before})
        # related は別に足せる。主を外せば別の業務Project を主にできる
        self.assertEqual(0, self._run("link", "L-TEST-1", "Beta Work", "--related", "--yes")[0])
        self.assertEqual(0, self._run("unlink", "L-TEST-1", "Alpha Work", "--yes")[0])
        self.assertEqual(2, self._run("where", "L-TEST-1")[0])
        self.assertEqual(0, self._run("link", "L-TEST-2", "Alpha Work", "--yes")[0])
        self.assertEqual("Stock/programs/Sample/projects/Alpha Work/<project>/\n",
                         self._run("where", "L-TEST-2")[1])

    def test_folder_names_follow_the_box_rules(self):
        self._setup_business()
        # ':' と '/' は全角に置き換えたフォルダになる（箱の business_folder と同じ）
        self.assertEqual(0, self._run("add-business", "Sample", "FAQ/RAG", "--purpose", "p", "--yes")[0])
        self.assertEqual(0, self._run("link", "L-TEST-2", "FAQ/RAG", "--yes")[0])
        self.assertEqual("Stock/programs/Sample/projects/FAQ\uff0fRAG/<project>/\n",
                         self._run("where", "L-TEST-2")[1])
        # 同じフォルダになる名前（':' と '：'、大文字小文字）は足せない
        self.assertEqual(0, self._run("add-business", "Sample", "A:B", "--purpose", "p", "--yes")[0])
        for name in ("A\uff1aB", "a:b"):
            code, out = self._run("add-business", "Sample", name, "--purpose", "p", "--yes")
            self.assertEqual(2, code, out)
            self.assertIn("BUSINESS_EXISTS", out)
        # 既に重なっている行（別の道で入ったもの）があれば where は止まる（箱の archive と同じ）
        with closing(sqlite3.connect(self.db)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM business_projects WHERE display_name='Alpha Work'").fetchone()
            membership = conn.execute("SELECT * FROM program_memberships WHERE business_uid=?",
                                      (row["business_uid"],)).fetchone()
            dup = "bpr_00000000-0000-4000-8000-0000000002ff"
            conn.execute("INSERT INTO business_projects(business_uid,workspace_id,display_name,purpose,included_json,"
                         "excluded_json,visibility,source_ref,source_hash,source_as_of,ownership_epoch,"
                         "identity_version,row_revision,state) VALUES(?,?,?,?,?,?,?,?,?,?,1,2,1,'active')",
                         (dup, row["workspace_id"], "ALPHA WORK", "p", "[]", "[]", "restricted", "t", "h", "t"))
            conn.execute("INSERT INTO program_memberships VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         ("pmb_dup", row["workspace_id"], membership["program_uid"], "business_project", dup,
                          None, None, None, None, None, None, None, "t", 1, "confirmed"))
            conn.commit()
        code, out = self._run("where", "L-TEST-1")
        self.assertEqual(2, code, out)
        self.assertIn("FOLDER_OVERLAP", out)

    def test_shared_stock_live_store_runs_on_these_rows(self):
        """共有 Stock（shared_stock.py の LiveStore）が、この道具で作った行の上で bind・prepare・commit できる"""
        self._setup_business()
        self._run_live_store("Sample", "Alpha Work", "work")

    def test_shared_stock_live_store_runs_on_a_private_program(self):
        self._setup_business()
        for args in (("add-program", "Home", "--private", "--yes"),
                     ("add-business", "Home", "Family", "--purpose", "p", "--yes"),
                     ("link", "L-TEST-2", "Family", "--yes")):
            code, out = self._run(*args)
            self.assertEqual(0, code, out)
        self._run_live_store("Home", "Family", "private", scope_id="L-TEST-2")

    def _run_live_store(self, program, business, read_domain, scope_id="L-TEST-1"):
        core = load_module(DB_DIR / "shared_stock.py", f"business_stock_{id(self)}")
        with closing(sqlite3.connect(self.db)) as conn:
            conn.row_factory = sqlite3.Row
            link = conn.execute(
                "SELECT l.* FROM business_project_links l JOIN projects p ON p.id=l.project_id "
                "WHERE l.state='confirmed' AND p.scope_id=?", (scope_id,)).fetchone()
            program_uid = conn.execute(
                "SELECT program_uid FROM program_memberships WHERE business_uid=?", (link["business_uid"],)).fetchone()[0]
            scope = conn.execute("SELECT scope_id FROM projects WHERE id=?", (link["project_id"],)).fetchone()[0]
        selector = {"workspace_id": link["workspace_id"], "read_domain": read_domain,
                    "program_uid": program_uid, "business_uid": link["business_uid"]}
        (self.root / "Stock").mkdir(exist_ok=True)
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        issuance = self.root / "issuance.json"
        issuance.write_text(json.dumps({
            "version": "live-v1", "repo_root": str(self.root), "db_rel": ".claude/db/ai_plc.db",
            "stock_rel": "Stock", "lock_rel": ".claude/db/shared_stock.writer.lock",
            "staging_rel": ".claude/db/shared_stock_staging", "host_uid": os.getuid(), "selector": selector,
            "scope_id": scope, "aiplc_uid": link["aiplc_uid"], "adopted_folder": "programs/%s/projects/%s" % (program, business),
            "writer": "synthetic-writer", "task_id": "T001", "issued_at": "2026-10-28T00:00:00+00:00",
            "issued_by": "synthetic", "approval_ref": "synthetic", "expires_at": expires,
            "allow_schema_install": True}), encoding="utf-8")
        live = core.LiveStore(issuance)
        live.install_schema()
        binding = live.bind(selector, folder="programs/%s/projects/%s" % (program, business))
        live.project_identity(binding["binding_id"], scope, link["aiplc_uid"])
        plan = live.prepare(binding["binding_id"],
                            {"scope_id": scope, "aiplc_uid": link["aiplc_uid"], "task_id": "T001",
                             "as_of": "2026-10-28T00:00:00+00:00", "decision_ref": "synthetic"},
                            {"Flow/doc.md": "# x"},
                            {"k": {"kind": "unknown", "text": "x", "source_paths": ["Flow/doc.md"]}})
        result = live.commit(plan, approved_hash=core.digest(plan), request_id="r1",
                             writer="synthetic-writer", expires_at=expires)
        self.assertEqual(1, result["generation"])
        self.assertTrue((self.root / "Stock" / "programs" / program / "projects" / business).is_dir())

    def test_init_db_refuses_rebuild_after_business_tables(self):
        self._setup_business()
        env = {k: v for k, v in os.environ.items() if k != "AIPLC_DB"}
        proc = subprocess.run([sys.executable, str(self.db_dir / "init_db.py"), "--allow-production"],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(3, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn("INIT_DB_BUSINESS_TABLES_PRESENT", proc.stderr)
        self.assertEqual(1, self._count("business_project_links"))

    def test_box_archive_reads_the_target_from_these_tables(self):
        spec = importlib.util.spec_from_file_location("_business_box_package", PACKAGE) if PACKAGE.is_file() else None
        package = None
        if spec is not None:
            package = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(package)
        if package is None or not hasattr(package, "archive_business"):
            self.skipTest("this checkout's aipm-guided package.py has no archive_business yet")
        self._setup_business()
        layer = self.root / "layer"
        layer.mkdir()
        (layer / "intent.yaml").write_text('scope_id: "L-TEST-1"\n', encoding="utf-8")
        contract = {"bindings": {"project_id": "box-1"}}
        with mock.patch.object(package, "build_contract", return_value=contract):
            target = package.archive_business(layer, self.root, "Sample", registry_db=self.db)
        self.assertEqual("Stock/programs/Sample/projects/Alpha Work/box-1", target["target_rel"])
        self.assertEqual("Alpha Work", target["business_display_name"])
        with mock.patch.object(package, "build_contract", return_value=contract):
            with self.assertRaisesRegex(ValueError, "does not belong to the Program stock:Other"):
                package.archive_business(layer, self.root, "Other", registry_db=self.db)
        # where と箱の archive が同じフォルダを示す（':' と '/' を含む名前）
        self.assertEqual(0, self._run("add-business", "Sample", "FAQ/RAG: v2", "--purpose", "p", "--yes")[0])
        self.assertEqual(0, self._run("link", "L-TEST-2", "FAQ/RAG: v2", "--yes")[0])
        (layer / "intent.yaml").write_text('scope_id: "L-TEST-2"\n', encoding="utf-8")
        with mock.patch.object(package, "build_contract", return_value=contract):
            target = package.archive_business(layer, self.root, "Sample", registry_db=self.db)
        self.assertEqual(self._run("where", "L-TEST-2")[1].strip().replace("<project>/", "box-1"),
                         target["target_rel"])


if __name__ == "__main__":
    unittest.main()
