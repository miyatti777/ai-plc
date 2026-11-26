"""Post-migration operations (plc_query Identity + init_db production guard).

API-free and production-free: every DB here is a temporary SQLite file, Notion
is an in-memory fake with ``urlopen`` replaced by AssertionError, and every test
asserts the production ``ai_plc.db`` fingerprint is unchanged on cleanup.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

try:  # unittest discovery imports test modules as top-level modules.
    from .test_sync_harness import DB_DIR, PRODUCTION_DB, file_fingerprint, load_module
    from .test_sync_identity import (
        FIXED_NOW, FIXED_PROJECT_A, FIXED_PROJECT_B, FIXED_WORKSPACE_A,
        FIXED_WORKSPACE_B, T007_OLD_EDIT, T007FakeNotion)
except ImportError:  # pragma: no cover - exercised by discovery invocation.
    from test_sync_harness import DB_DIR, PRODUCTION_DB, file_fingerprint, load_module
    from test_sync_identity import (
        FIXED_NOW, FIXED_PROJECT_A, FIXED_PROJECT_B, FIXED_WORKSPACE_A,
        FIXED_WORKSPACE_B, T007_OLD_EDIT, T007FakeNotion)


T012_LINKED_AT = "2026-07-15T11:30:00Z"
T012_UID_A = "prj_00000000-0000-4000-8000-000000000201"
T012_UID_NEW = "prj_00000000-0000-4000-8000-000000000202"
T012_UID_NEW2 = "prj_00000000-0000-4000-8000-000000000203"
T012_WRITER = "writer-main"


class _T012Base(unittest.TestCase):
    def setUp(self):
        self.production_before = file_fingerprint(PRODUCTION_DB)
        self.addCleanup(self._assert_production_unchanged)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="ai-plc-post-migration-")
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "ai_plc.db"
        self.manifest_path = self.root / "workspace_identity.json"
        suffix = id(self)
        self.init_db = load_module(DB_DIR / "init_db.py", f"t012_init_{suffix}")
        self.sync = load_module(DB_DIR / "sync.py", f"t012_sync_{suffix}")
        self.plc = load_module(DB_DIR / "plc_query.py", f"t012_plc_{suffix}")
        self.sync.DB_PATH = str(self.db_path)
        self.sync.WORKSPACE_MANIFEST_PATH = str(self.manifest_path)
        self.sync.TOKEN = "dummy-t012-token"
        self.sync.RATE_LIMIT_DELAY = 0
        self.sync._now_iso = lambda: FIXED_NOW
        self.plc.DB_PATH = str(self.db_path)
        self.plc.WORKSPACE_MANIFEST_PATH = str(self.manifest_path)
        self.plc.SYNC = self.sync
        guard = mock.patch.object(
            self.sync.urllib.request, "urlopen",
            side_effect=AssertionError("network access is forbidden in these tests"))
        guard.start()
        self.addCleanup(guard.stop)

    def _assert_production_unchanged(self):
        self.assertEqual(self.production_before, file_fingerprint(PRODUCTION_DB))

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _create_legacy_db(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            with contextlib.redirect_stdout(io.StringIO()):
                self.init_db.create_schema(conn)
            conn.execute("""
                INSERT INTO projects (notion_page_id, scope_id, name, status,
                    notion_last_edited, last_sync_at, created_at, updated_at)
                VALUES ('page-pa', 'L-A', 'Project A', 'active', ?, ?, ?, ?)
            """, (T007_OLD_EDIT, T012_LINKED_AT, T012_LINKED_AT, T012_LINKED_AT))
            for page_id, task_id, scope_id in (("page-ta1", "T001", "L-A"),
                                               ("page-x1", "T004", "L-X-SG0")):
                conn.execute("""
                    INSERT INTO tasks (notion_page_id, task_id, scope_id, name, status,
                        notion_last_edited, last_sync_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, '未着手', ?, ?, ?, ?)
                """, (page_id, task_id, scope_id, "Task %s" % task_id, T007_OLD_EDIT,
                      T012_LINKED_AT, T012_LINKED_AT, T012_LINKED_AT))
            conn.commit()

    def _plc(self, *args, uuids=None):
        """Run plc_query.main in-process; returns (exit, stdout)."""
        output = io.StringIO()
        with contextlib.ExitStack() as stack:
            if uuids is None:
                stack.enter_context(mock.patch.object(
                    self.sync.uuid, "uuid4",
                    side_effect=AssertionError("unexpected Identity issuance")))
            else:
                values = iter(uuids)
                stack.enter_context(mock.patch.object(
                    self.sync.uuid, "uuid4", side_effect=lambda: next(values)))
            stack.enter_context(contextlib.redirect_stdout(output))
            result = self.plc.main(["plc_query.py"] + list(args))
        return result, output.getvalue()

    def _snapshot(self):
        with closing(self._connect()) as conn:
            return {table: [dict(row) for row in conn.execute(
                "SELECT * FROM %s ORDER BY %s" % (
                    table, "key" if table == "_metadata" else "id")).fetchall()]
                for table in ("projects", "tasks", "_metadata")}

    def _row(self, sql, params=()):
        with closing(self._connect()) as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None


class T012PlcQueryIdentityTest(_T012Base):
    """v2 add-project / add-task carry the current workspace Identity."""

    def _adopt(self):
        """Production path: v1 DB -> adopt-existing (dual_read v2 + manifest)."""
        self._create_legacy_db()
        decisions = self.root / "decisions.json"
        decisions.write_text(json.dumps({"adopt_decisions_version": 1, "decisions": [
            {"routing_key": "L-X-SG0/T004", "decision": "legacy_excluded",
             "evidence_digest": "sha256:" + "a" * 64}]}), encoding="utf-8")
        plan_path = self.root / "adopt-plan.json"
        ids = iter((FIXED_WORKSPACE_A, T012_UID_A))
        output = io.StringIO()
        with mock.patch.object(self.sync.uuid, "uuid4", side_effect=lambda: next(ids)), \
                contextlib.redirect_stdout(output):
            result = self.sync.main([
                "adopt-existing", "--dry-run", "--decisions", str(decisions),
                "--writer-id", T012_WRITER, "--plan-out", str(plan_path)])
        self.assertEqual(0, result, output.getvalue())
        plan_id = json.loads(plan_path.read_text(encoding="utf-8"))["plan_id"]
        with contextlib.redirect_stdout(output):
            result = self.sync.main(["adopt-existing", "--plan", str(plan_path),
                                     "--plan-id", plan_id])
        self.assertEqual(0, result, output.getvalue())

    def _backfilled_remote(self):
        def rich(value):
            return {"rich_text": [] if not value else [{"plain_text": value}]}
        project = {
            "id": "page-pa", "last_edited_time": T007_OLD_EDIT,
            "parent": {"type": "database_id", "database_id": "projects-db"},
            "properties": {
                "PJ名": {"title": [{"plain_text": "Project A"}]},
                "Scope ID": rich("L-A"), "ステータス": {"status": {"name": "active"}},
                "Sync UID": rich(T012_UID_A), "Workspace ID": rich(FIXED_WORKSPACE_A),
                "Ownership Epoch": {"number": 1}, "Identity Version": {"number": 2}}}

        def task(page_id, scope_id, task_id, uid):
            return {
                "id": page_id, "last_edited_time": T007_OLD_EDIT,
                "parent": {"type": "database_id", "database_id": "tasks-db"},
                "properties": {
                    "タスク名": {"title": [{"plain_text": "Task %s" % task_id}]},
                    "Task ID": rich(task_id), "Scope ID": rich(scope_id),
                    "ステータス": {"status": {"name": "未着手"}},
                    "Project Sync UID": rich(uid),
                    "Workspace ID": rich(FIXED_WORKSPACE_A if uid else None),
                    "Project Ownership Epoch": {"number": 1 if uid else None},
                    "Identity Version": {"number": 2 if uid else None}}}
        return T007FakeNotion(self.sync, projects=[project], tasks=[
            task("page-ta1", "L-A", "T001", T012_UID_A),
            task("page-x1", "L-X-SG0", "T004", None)])

    def _build_push_plan(self, fake, **selector):
        with mock.patch.object(self.sync, "_query_db", side_effect=fake.query), \
                mock.patch.object(self.sync, "_api_call", side_effect=fake.api):
            return self.sync.build_push_plan(skip_preflight=True, **selector)

    def _create_enforced_db(self):
        """enforced v2 (table rebuild) with a same-Scope row in workspace B."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            with contextlib.redirect_stdout(io.StringIO()):
                self.init_db.create_schema(conn)
            conn.execute("INSERT INTO projects (scope_id, name, status, created_at, "
                         "updated_at) VALUES ('L-E', 'Enforced A', 'active', ?, ?)",
                         (FIXED_NOW, FIXED_NOW))
            conn.commit()
            mapping = self.init_db.build_identity_migration_mapping(
                conn, FIXED_WORKSPACE_A, project_uid_factory=lambda: FIXED_PROJECT_A)
            self.init_db.migrate_identity_v2(conn, mapping)
            conn.execute("""
                INSERT INTO projects (workspace_id, sync_uid, ownership_epoch,
                    identity_version, scope_id, name, status, created_at, updated_at)
                VALUES (?, ?, 1, 2, 'L-BONLY', 'Workspace B only', 'active', ?, ?)
            """, (FIXED_WORKSPACE_B, FIXED_PROJECT_B, FIXED_NOW, FIXED_NOW))
            conn.commit()
        manifest = self.sync._writer_manifest(FIXED_WORKSPACE_A, T012_WRITER)
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with closing(sqlite3.connect(self.db_path)) as conn:
            for key, value in (("active_workspace_id", FIXED_WORKSPACE_A),
                               ("active_writer_epoch", "1"),
                               ("writer_authority_hash_cache",
                                manifest["writer_authority_hash_cache"])):
                conn.execute("INSERT OR REPLACE INTO _metadata(key, value) VALUES (?, ?)",
                             (key, value))
            conn.commit()

    # ── dual_read (post adopt-existing) ─────────────────

    def test_t012_ac1_dual_read_added_rows_get_identity_and_are_pushed(self):
        self._adopt()
        result, output = self._plc("add-project", "L-NEW", "New Project", "Goal",
                                   uuids=[T012_UID_NEW])
        self.assertEqual(0, result, output)
        self.assertIn("Identity v2", output)
        self.assertNotIn(T012_UID_NEW, output)  # display is shortened
        result, output = self._plc("add-task", "T001", "L-NEW", "New task",
                                   "design", "P0")
        self.assertEqual(0, result, output)
        result, output = self._plc("add-task", "T002", "L-A", "Second A task")
        self.assertEqual(0, result, output)
        self.assertEqual({
            "workspace_id": FIXED_WORKSPACE_A, "sync_uid": T012_UID_NEW,
            "ownership_epoch": 1, "identity_version": 2, "status": "active",
            "goal": "Goal"}, self._row(
                "SELECT workspace_id, sync_uid, ownership_epoch, identity_version, "
                "status, goal FROM projects WHERE scope_id='L-NEW'"))
        self.assertEqual(
            [("L-A", "T002", FIXED_WORKSPACE_A, T012_UID_A, 1, 2, "implementation", "P1"),
             ("L-NEW", "T001", FIXED_WORKSPACE_A, T012_UID_NEW, 1, 2, "design", "P0")],
            [tuple(row.values()) for row in [self._row(
                "SELECT scope_id, task_id, workspace_id, project_sync_uid, "
                "project_ownership_epoch, identity_version, type, priority FROM tasks "
                "WHERE scope_id=? AND task_id=?", key)
                for key in (("L-A", "T002"), ("L-NEW", "T001"))]])
        # status: new rows are current_workspace; legacy_excluded stays read-only.
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, self.sync.cmd_status())
        self.assertIn("project: current_workspace=2 dirty=1 other_workspace=0 "
                      "legacy_read_only=0", output.getvalue())
        self.assertIn("task: current_workspace=3 dirty=2 other_workspace=0 "
                      "legacy_read_only=1", output.getvalue())
        # push: exactly the three added rows become CREATE operations with Identity.
        fake = self._backfilled_remote()
        plan = self._build_push_plan(fake)
        self.assertEqual(0, plan["exit_code"], plan.get("preflight"))
        self.assertEqual("workspace", plan["selector"]["kind"])
        self.assertEqual(
            sorted([("project", T012_UID_NEW, None), ("task", T012_UID_A, "T002"),
                    ("task", T012_UID_NEW, "T001")]),
            sorted((op["identity"]["entity"], op["identity"]["project_sync_uid"],
                    op["identity"]["task_id"]) for op in plan["operations"]))
        self.assertTrue(all(op["identity"]["workspace_id"] == FIXED_WORKSPACE_A
                            for op in plan["operations"]))
        scoped = self._build_push_plan(fake, scope_id="L-NEW")
        self.assertEqual(0, scoped["exit_code"], scoped.get("preflight"))
        self.assertEqual(2, len(scoped["operations"]))
        output = io.StringIO()
        with mock.patch.object(self.sync, "_revalidate_identity_plan_before_write",
                               return_value=0), \
                mock.patch.object(self.sync, "_query_db", side_effect=fake.query), \
                mock.patch.object(self.sync, "_api_call", side_effect=fake.api), \
                contextlib.redirect_stdout(output):
            result = self.sync.execute_push_plan(plan)
        self.assertEqual(0, result, output.getvalue())
        self.assertEqual(3, output.getvalue().count("[POST-VERIFY PASS]"))
        created = [page for page in fake.pages["project"] if page["id"].startswith("t007-")]
        self.assertEqual([T012_UID_NEW], [
            page["properties"]["Sync UID"]["rich_text"][0]["plain_text"]
            for page in created])
        mutations = len(fake.mutations())
        rerun = self._build_push_plan(fake)
        self.assertEqual((0, []), (rerun["exit_code"], rerun["operations"]))
        self.assertEqual(mutations, len(fake.mutations()))

    def test_t012_ac1_dual_read_refusals_write_nothing(self):
        self._adopt()
        base = self._snapshot()
        cases = [
            # legacy_excluded Scope has no Project in the workspace: never guessed.
            (("add-task", "T009", "L-X-SG0", "x"), 3, "SCOPE_NOT_UNIQUE"),
            (("add-task", "T001", "L-MISSING", "x"), 3, "SCOPE_NOT_UNIQUE"),
            (("add-task", "T001", "L-A", "dup"), 2, "TASK_ALREADY_EXISTS"),
            (("add-task", " T001 ", " L-A ", "dup normalized"), 2, "TASK_ALREADY_EXISTS"),
            (("add-project", "L-A", "dup", "g"), 2, "SCOPE_ALREADY_EXISTS"),
            (("add-project", "  ", "empty", "g"), 3, "SCOPE_INVALID"),
            (("add-task", "  ", "L-A", "empty"), 3, "TASK_ID_INVALID"),
            (("add-task", "T010", "L-A", "bad type", "bogus"), 2,
             "LOCAL_CONSTRAINT_VIOLATION"),
        ]
        for argv, expected, code in cases:
            with self.subTest(argv=argv):
                result, output = self._plc(*argv)
                self.assertEqual(expected, result, output)
                self.assertIn(code, output)
                self.assertIn("nothing was written", output)
                self.assertEqual(base, self._snapshot())
        # SCOPE_ALREADY_EXISTS is decided before a UID would be issued; a legacy
        # row with the same Scope (dual_read global UNIQUE) is a constraint stop.
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO projects (scope_id, name, status) "
                         "VALUES ('L-LEGACY', 'legacy', 'active')")
            conn.commit()
        base = self._snapshot()
        result, output = self._plc("add-project", "L-LEGACY", "n", "g",
                                   uuids=[T012_UID_NEW])
        self.assertEqual((2, True), (result, "LOCAL_CONSTRAINT_VIOLATION" in output))
        self.assertEqual(base, self._snapshot())
        # A task under a legacy (Identity-less) Project is refused, not adopted.
        result, output = self._plc("add-task", "T001", "L-LEGACY", "x")
        self.assertEqual((3, True), (result, "SCOPE_NOT_UNIQUE" in output))
        self.assertEqual(base, self._snapshot())

    def test_t012_ac1_workspace_identity_problems_stop_before_insert(self):
        self._adopt()
        base_db = self.db_path.read_bytes()
        base_manifest = self.manifest_path.read_bytes()

        def manifest_missing():
            self.manifest_path.unlink()

        def cache_epoch():
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("UPDATE _metadata SET value='2' "
                             "WHERE key='active_writer_epoch'")
                conn.commit()

        def other_writer():
            self.manifest_path.write_text(json.dumps(self.sync._writer_manifest(
                FIXED_WORKSPACE_A, "writer-intruder")), encoding="utf-8")

        def mixed_schema():
            with closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute("ALTER TABLE projects DROP COLUMN identity_version")
                conn.commit()

        for name, tamper, code in (
                ("manifest_missing", manifest_missing, "WORKSPACE_IDENTITY_INVALID"),
                ("cache_epoch", cache_epoch, "WORKSPACE_IDENTITY_INVALID"),
                ("other_writer", other_writer, "WORKSPACE_IDENTITY_INVALID"),
                ("mixed_schema", mixed_schema, "LOCAL_IDENTITY_SCHEMA_MIXED")):
            for argv in (("add-project", "L-NEW", "n", "g"),
                         ("add-task", "T002", "L-A", "t")):
                with self.subTest(case=name, command=argv[0]):
                    self.db_path.write_bytes(base_db)
                    self.manifest_path.write_bytes(base_manifest)
                    tamper()
                    before = self._snapshot()
                    result, output = self._plc(*argv)
                    self.assertEqual(3, result, output)
                    self.assertIn(code, output)
                    self.assertEqual(before, self._snapshot())

    def test_t012_ac1_uses_shared_resolver_with_plc_manifest_path(self):
        self._adopt()
        real = self.sync.resolve_identity_selection
        calls = []

        def spy(conn, **kwargs):
            calls.append(kwargs)
            return real(conn, **kwargs)

        with mock.patch.object(self.sync, "resolve_identity_selection", side_effect=spy):
            self.assertEqual(0, self._plc("add-project", "L-NEW", "n", "g",
                                          uuids=[T012_UID_NEW])[0])
            self.assertEqual(0, self._plc("add-task", "T001", "L-NEW", "t")[0])
        self.assertEqual([
            {"manifest_path": str(self.manifest_path)},
            {"scope_id": "L-NEW", "manifest_path": str(self.manifest_path)}], calls)
        # The resolver default is unchanged for sync.py's own callers.
        with closing(self._connect()) as conn:
            self.assertEqual(FIXED_WORKSPACE_A, real(conn)["context"]["workspace_id"])

    # ── enforced v2 ─────────────────────────────────────

    def test_t012_ac1_enforced_v2_add_rows_use_current_workspace_only(self):
        self._create_enforced_db()
        # Older versions: the enforced schema rejected plc_query inserts (NOT NULL).
        result, output = self._plc("add-task", "T001", "L-E", "enforced task")
        self.assertEqual(0, result, output)
        self.assertEqual((FIXED_WORKSPACE_A, FIXED_PROJECT_A, 1, 2), tuple(self._row(
            "SELECT workspace_id, project_sync_uid, project_ownership_epoch, "
            "identity_version FROM tasks WHERE task_id='T001' AND scope_id='L-E'"
        ).values()))
        # A Scope that exists only in another workspace is not selected.
        base = self._snapshot()
        result, output = self._plc("add-task", "T001", "L-BONLY", "x")
        self.assertEqual((3, True), (result, "SCOPE_NOT_UNIQUE" in output))
        self.assertEqual(base, self._snapshot())
        # Same Scope ID in the current workspace becomes a different Identity.
        result, output = self._plc("add-project", "L-BONLY", "A copy", "g",
                                   uuids=[T012_UID_NEW2])
        self.assertEqual(0, result, output)
        with closing(self._connect()) as conn:
            self.assertEqual(
                [(FIXED_WORKSPACE_A, T012_UID_NEW2), (FIXED_WORKSPACE_B, FIXED_PROJECT_B)],
                sorted(tuple(row) for row in conn.execute(
                    "SELECT workspace_id, sync_uid FROM projects "
                    "WHERE scope_id='L-BONLY'").fetchall()))
        result, output = self._plc("add-task", "T001", "L-BONLY", "now resolvable")
        self.assertEqual(0, result, output)
        self.assertEqual(T012_UID_NEW2, self._row(
            "SELECT project_sync_uid FROM tasks WHERE scope_id='L-BONLY' "
            "AND task_id='T001'")["project_sync_uid"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, self.sync.cmd_status())
        self.assertIn("project: current_workspace=2 dirty=2 other_workspace=1 "
                      "legacy_read_only=0", output.getvalue())
        self.assertIn("task: current_workspace=2 dirty=2 other_workspace=0 "
                      "legacy_read_only=0", output.getvalue())
        # push: every current-workspace row added above is a CREATE; workspace B is not.
        fake = T007FakeNotion(self.sync)
        plan = self._build_push_plan(fake)
        self.assertEqual(0, plan["exit_code"], plan.get("preflight"))
        self.assertEqual(sorted([
            ("project", FIXED_PROJECT_A, None), ("project", T012_UID_NEW2, None),
            ("task", FIXED_PROJECT_A, "T001"), ("task", T012_UID_NEW2, "T001")]),
            sorted((op["identity"]["entity"], op["identity"]["project_sync_uid"],
                    op["identity"]["task_id"]) for op in plan["operations"]))
        self.assertTrue(all(op["identity"]["workspace_id"] == FIXED_WORKSPACE_A
                            for op in plan["operations"]))
        self.assertEqual([], fake.mutations())

    # ── Other local add paths (sql) and error hints ─────

    def test_t012_ac1_sql_guard_blocks_identity_less_rows_on_v2(self):
        self._adopt()
        base = self._snapshot()
        for statement in (
                "INSERT INTO projects (scope_id, name, status) VALUES ('L-RAW', 'raw', 'active')",
                "INSERT INTO tasks (task_id, scope_id, name) VALUES ('T050', 'L-A', 'raw')",
                "UPDATE tasks SET workspace_id=NULL, project_sync_uid=NULL, "
                "project_ownership_epoch=NULL, identity_version=NULL WHERE task_id='T001'",
                # Python does not auto-BEGIN before WITH; the guard's explicit
                # BEGIN IMMEDIATE must still make this rollback-able.
                "WITH x AS (SELECT 1) INSERT INTO projects (scope_id, name, status) "
                "VALUES ('L-WITH', 'with', 'active')",
                # Partial Identity (workspace_id only) is also refused.
                "INSERT INTO projects (scope_id, name, status, workspace_id) VALUES "
                "('L-PART', 'partial', 'active', '%s')" % FIXED_WORKSPACE_A):
            with self.subTest(statement=statement[:30]):
                result, output = self._plc("sql", statement)
                self.assertEqual(3, result, output)
                self.assertIn("IDENTITY_LESS_ROW_FORBIDDEN", output)
                self.assertEqual(base, self._snapshot())
        # Collection-style registration: add-project, then UPDATE the other columns.
        self.assertEqual(0, self._plc("add-project", "L-COL", "Collected", "Goal",
                                      uuids=[T012_UID_NEW])[0])
        result, output = self._plc(
            "sql", "UPDATE projects SET owner='owner-a', mode='direct', depth='standard', "
                   "parent_scope='L-A', deadline='2026-10-01' WHERE scope_id='L-COL'")
        self.assertEqual(0, result, output)
        self.assertEqual((FIXED_WORKSPACE_A, T012_UID_NEW, "L-A", "2026-10-01"),
                         tuple(self._row(
                             "SELECT workspace_id, sync_uid, parent_scope, deadline "
                             "FROM projects WHERE scope_id='L-COL'").values()))
        # Reads and Identity-complete writes are unaffected.
        self.assertEqual(0, self._plc("sql", "SELECT COUNT(*) FROM projects")[0])
        result, output = self._plc(
            "sql", "INSERT INTO tasks (task_id, scope_id, name, workspace_id, "
                   "project_sync_uid, project_ownership_epoch, identity_version) VALUES "
                   "('T060', 'L-COL', 'explicit', '%s', '%s', 1, 2)"
                   % (FIXED_WORKSPACE_A, T012_UID_NEW))
        self.assertEqual(0, result, output)
        self.assertIsNotNone(self._row("SELECT id FROM tasks WHERE task_id='T060'"))

    def test_t012_ac1_parent_hint_only_for_missing_parent(self):
        self._adopt()
        result, output = self._plc("add-task", "T001", "L-MISSING", "x")
        self.assertEqual(3, result)
        self.assertIn("add-project first", output)
        self.manifest_path.unlink()
        result, output = self._plc("add-task", "T002", "L-A", "x")
        self.assertEqual(3, result)
        self.assertIn("WORKSPACE_IDENTITY_INVALID", output)
        self.assertNotIn("add-project first", output)

    # ── v1 schema unchanged ─────────────────────────────

    def test_t012_ac1_v1_schema_inserts_exactly_as_before(self):
        self._create_legacy_db()
        result, output = self._plc("add-project", "L-V1", "V1 Project", "Goal")
        self.assertEqual((0, "[OK] Project added: L-V1 - V1 Project\n"), (result, output))
        result, output = self._plc("add-task", "T001", "L-V1", "V1 task")
        self.assertEqual((0, "[OK] Task added: T001 (L-V1) - V1 task\n"), (result, output))
        # Orphan tasks stay possible on v1 exactly as before (no parent check).
        result, output = self._plc("add-task", "T001", "L-NO-PARENT", "orphan", "research", "P2")
        self.assertEqual(0, result, output)
        with closing(self._connect()) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
            self.assertNotIn("sync_uid", columns)
            self.assertEqual(("L-V1", "V1 Project", "Goal", "active"), tuple(conn.execute(
                "SELECT scope_id, name, goal, status FROM projects "
                "WHERE scope_id='L-V1'").fetchone()))
            self.assertEqual(
                [("T001", "L-NO-PARENT", "orphan", "research", "P2"),
                 ("T001", "L-V1", "V1 task", "implementation", "P1")],
                sorted(tuple(row) for row in conn.execute(
                    "SELECT task_id, scope_id, name, type, priority FROM tasks "
                    "WHERE scope_id IN ('L-V1', 'L-NO-PARENT')").fetchall()))
        self.assertFalse(self.manifest_path.exists())
        # v1: raw INSERT through sql behaves as before (no Identity guard).
        result, output = self._plc(
            "sql", "INSERT INTO projects (scope_id, name, status) VALUES ('L-RAW', 'r', 'active')")
        self.assertEqual((0, "(no results)\n"), (result, output))
        self.assertIsNotNone(self._row("SELECT id FROM projects WHERE scope_id='L-RAW'"))
        # Usage lines and read commands keep exit 0.
        self.assertEqual(0, self._plc("add-project", "only-one")[0])
        self.assertEqual(0, self._plc("projects")[0])


class T012InitDbGuardTest(_T012Base):
    """--help never opens a DB; production writes need --allow-production."""

    def _forbid_side_effects(self):
        stack = contextlib.ExitStack()
        for target, name in ((self.init_db.sqlite3, "connect"), (self.init_db.os, "remove"),
                             (self.init_db.os, "makedirs")):
            stack.enter_context(mock.patch.object(
                target, name, side_effect=AssertionError("%s must not be called" % name)))
        return stack

    def _main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = self.init_db.main(argv)
        return result, out.getvalue(), err.getvalue()

    def test_t012_ac2_help_prints_usage_without_opening_any_db(self):
        self.assertTrue(self.init_db.is_production_db_path(self.init_db.DB_PATH))
        with self._forbid_side_effects():
            for argv in (["--help"], ["-h"], ["--import", "--help"],
                         ["--reset", "--allow-production", "--help"]):
                with self.subTest(argv=argv):
                    result, out, err = self._main(argv)
                    self.assertEqual(0, result, err)
                    self.assertIn("usage: python3 .claude/db/init_db.py", out)
                    self.assertIn("--allow-production", out)
                    self.assertIn("--db PATH", out)
        # 公開版のリポジトリには ai_plc.db が無い（無いままであることを確かめる）
        stat_before = file_fingerprint(PRODUCTION_DB)
        proc = subprocess.run([sys.executable, str(DB_DIR / "init_db.py"), "--help"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("usage:", proc.stdout)
        self.assertEqual(stat_before, file_fingerprint(PRODUCTION_DB))

    def test_t012_ac2_production_path_refused_without_flag_before_open(self):
        production = Path(self.init_db.DB_PATH)
        link = self.root / "prod-link.db"
        link.symlink_to(production)
        dir_link = self.root / "dir-link"
        dir_link.symlink_to(production.parent, target_is_directory=True)
        relative = os.path.relpath(production, os.getcwd())
        dotted = str(production.parent / ".." / production.parent.name / production.name)
        targets = [None, str(production), relative, dotted, str(link),
                   str(dir_link / production.name)]
        variant = str(production.parent / production.name.upper())
        if os.path.exists(variant):  # case-insensitive filesystem (macOS default)
            targets.append(variant)
        with self._forbid_side_effects():
            for target in targets:
                for extra in ([], ["--import"], ["--reset"], ["--reset", "--import"]):
                    argv = ([] if target is None else ["--db", target]) + extra
                    with self.subTest(argv=argv):
                        result, out, err = self._main(argv)
                        self.assertEqual(3, result, out + err)
                        self.assertIn("INIT_DB_PRODUCTION_WRITE_FORBIDDEN", err)
                        self.assertIn("Nothing was opened or written", err)

    def test_t012_ac2_usage_errors_exit_64_before_open(self):
        with self._forbid_side_effects():
            for argv in (["--unknown"], ["--allow"], ["--imp"], ["--db"], ["--db", ""],
                         ["positional"]):
                with self.subTest(argv=argv):
                    result, _out, err = self._main(argv)
                    self.assertEqual(64, result, err)

    def test_t012_ac2_explicit_path_and_flag_still_initialize(self):
        target = self.root / "copy" / "new.db"
        result, out, err = self._main(["--db", str(target)])
        self.assertEqual(0, result, err)
        self.assertIn("DB location: %s" % target, out)
        with closing(sqlite3.connect(target)) as conn:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"projects", "tasks", "_metadata"} <= tables)
        with closing(sqlite3.connect(target)) as conn:
            conn.execute("INSERT INTO projects (scope_id, name) VALUES ('L-R', 'r')")
            conn.commit()
        for suffix in ("-wal", "-shm"):
            Path(str(target) + suffix).write_bytes(b"stale sidecar")
        result, out, err = self._main(["--db", str(target), "--reset"])
        self.assertEqual(0, result, err)
        self.assertNotEqual(b"stale sidecar", Path(str(target) + "-wal").read_bytes()
                            if Path(str(target) + "-wal").exists() else b"")
        with closing(sqlite3.connect(target)) as conn:
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
        # A module whose production path is a temp file: guard, then explicit flag.
        fake_production = self.root / "fake-production.db"
        self.init_db.DB_PATH = str(fake_production)
        with self._forbid_side_effects():
            result, _out, err = self._main([])
            self.assertEqual(3, result, err)
        self.assertFalse(fake_production.exists())
        result, out, err = self._main(["--allow-production"])
        self.assertEqual(0, result, err)
        self.assertTrue(fake_production.exists())
        # The real CLI works end to end against a temp path.
        proc = subprocess.run([sys.executable, str(DB_DIR / "init_db.py"), "--db",
                               str(self.root / "cli.db")],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertTrue((self.root / "cli.db").exists())


if __name__ == "__main__":
    unittest.main()
