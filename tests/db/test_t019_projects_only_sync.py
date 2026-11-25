"""T019: with task sync frozen, only Projects are pushed, pulled, backfilled.

API-free and production-free: the T011 adopt-existing fixture in a temporary
directory, an in-memory fake Notion (``urlopen`` replaced by AssertionError),
and the production ``ai_plc.db`` fingerprint asserted unchanged on cleanup.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from contextlib import closing
from unittest import mock

try:  # unittest discovery imports test modules as top-level modules.
    from . import test_sync_identity as identity_tests
    from . import test_t014_remote_backfill as t014_tests
except ImportError:  # pragma: no cover - exercised by discovery invocation.
    import test_sync_identity as identity_tests
    import test_t014_remote_backfill as t014_tests

T014FakeNotion = t014_tests.T014FakeNotion


class T019ProjectsOnlySyncTest(identity_tests.IdentityV2AdoptExistingTest):
    """Reuses the T011 fixture; the inherited T011 tests are not re-run."""

    def run(self, result=None):  # keep inherited T011 tests out of this class
        if not self._testMethodName.startswith("test_t019_"):
            return result
        return super().run(result)

    # ── helpers ──────────────────────────────────────────────

    def _freeze(self):
        result, _calls, output = self._main(
            ["tasks-sync", "--freeze", "--approved-by", "t019", "--reason", "backlog is source"])
        self.assertEqual(0, result, output)

    def _remote(self):
        fake = self._backfilled_remote()
        for entity, pages in fake.pages.items():
            for page in pages:
                page["parent"]["database_id"] = (
                    self.sync.PROJECTS_DB_ID if entity == "project" else self.sync.TASKS_DB_ID)
        return T014FakeNotion(self.sync, projects=fake.pages["project"],
                              tasks=fake.pages["task"])

    def _patched(self, fake):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(self.sync, "_query_db", side_effect=fake.query))
        stack.enter_context(mock.patch.object(self.sync, "_api_call", side_effect=fake.api))
        return stack

    def _tasks_db_calls(self, fake):
        return [call for call in fake.calls if call == ("QUERY", self.sync.TASKS_DB_ID)]

    def _tasks_snapshot(self):
        with closing(self._connect()) as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM tasks ORDER BY id")]

    def _dirty_everything(self):
        with closing(self._connect()) as conn:
            conn.execute("UPDATE projects SET goal='edited' WHERE scope_id='L-A'")
            conn.execute("UPDATE tasks SET name='edited task' WHERE scope_id='L-A'")
            conn.commit()

    # ── freeze CLI ───────────────────────────────────────────

    def test_t019_freeze_status_unfreeze_and_strict_cli(self):
        for argv in (["tasks-sync"], ["tasks-sync", "--freeze"],
                     ["tasks-sync", "--status", "--approved-by", "x"],
                     ["tasks-sync", "--freeze", "--unfreeze", "--approved-by", "x"],
                     ["tasks-sync", "--unfreeze", "--approved-by", "x", "--reason", "r"]):
            self.assertEqual(64, self._main(argv)[0], argv)
        self._adopt()
        result, _calls, output = self._main(["tasks-sync", "--status"])
        self.assertIn("Task sync: active", output)
        self._freeze()
        result, _calls, output = self._main(["tasks-sync", "--status"])
        self.assertIn("FROZEN", output)
        self.assertIn("approved_by=t019", output)
        result, _calls, output = self._main(["tasks-sync", "--freeze", "--approved-by", "x"])
        self.assertIn("already frozen", output)
        result, _calls, output = self._main(
            ["tasks-sync", "--unfreeze", "--approved-by", "t019b"])
        self.assertEqual(0, result, output)
        with closing(self._connect()) as conn:
            log = conn.execute("SELECT value FROM _metadata WHERE key LIKE "
                               "'task_sync_unfrozen:%'").fetchone()
        self.assertEqual("t019b", json.loads(log[0])["unfrozen_by"])
        result, _calls, output = self._main(
            ["tasks-sync", "--unfreeze", "--approved-by", "x"])
        self.assertEqual(2, result, output)

    # ── AC1: push / reconciliation / backfill never touch tasks ───────

    def test_t019_push_plans_only_projects_and_never_query_tasks_db(self):
        self._adopt()
        self._dirty_everything()
        self._freeze()
        fake = self._remote()
        with self._patched(fake):
            plan = self.sync.build_push_plan(skip_preflight=True)
            report = self.sync.run_reconciliation()
        self.assertEqual({"project"}, {op["entity"] for op in plan["operations"]})
        self.assertIn("L-A", {op["display_scope_id"] for op in plan["operations"]})
        self.assertEqual([], [item for item in report["items"] if item["entity"] == "task"])
        self.assertEqual([], self._tasks_db_calls(fake))

    def test_t019_plan_with_task_operations_is_refused_after_freeze(self):
        self._adopt()
        self._dirty_everything()
        fake = self._remote()
        with self._patched(fake):
            plan = self.sync.build_push_plan(skip_preflight=True)
        self.assertIn("task", {op["entity"] for op in plan["operations"]})
        self._freeze()
        output = io.StringIO()
        with (
            self._patched(fake),
            mock.patch.object(self.sync, "_revalidate_identity_plan_before_write",
                              return_value=0),
            contextlib.redirect_stdout(output),
        ):
            result = self.sync.execute_push_plan(plan)
        self.assertEqual(3, result, output.getvalue())
        self.assertIn("TASK_SYNC_FROZEN", output.getvalue())
        self.assertEqual([], fake.mutations())

    def test_t019_backfill_targets_only_projects(self):
        self._adopt()
        self._freeze()
        result, _calls, output = self._main([
            "backfill-remote-identity", "--dry-run", "--plan-out", str(self.root / "bf.json")])
        self.assertEqual(0, result, output)
        plan = json.loads((self.root / "bf.json").read_text(encoding="utf-8"))
        self.assertEqual({"project"}, {op["entity"] for op in plan["operations"]})

    def test_t019_preflight_skips_tasks_schema_and_links(self):
        self._adopt()
        self._freeze()
        checked = []

        def fake_validate(entity, db_id, schema):
            checked.append(entity)
            return {"last_edited_time": "x"}, []
        with (
            mock.patch.object(self.sync, "_validate_notion_database", side_effect=fake_validate),
            mock.patch.object(self.sync, "_classify_page_link",
                              side_effect=lambda entity, row, db: (
                                  checked.append("link:" + entity) or
                                  ({"state": "valid", "local_row_id": row["id"]}, None))),
        ):
            report = self.sync.run_preflight()
        self.assertEqual("pass", report["status"], report)
        self.assertNotIn("task", checked)
        self.assertNotIn("link:task", checked)
        self.assertIn("project", checked)

    # ── AC1 / AC2: pull ignores Notion tasks; local tasks stay frozen ─────

    def test_t019_pull_ignores_tasks_and_keeps_local_tasks_unchanged(self):
        self._adopt()
        self._freeze()
        fake = self._remote()
        task = fake._find("page-ta1")
        task["properties"]["タスク名"] = {"title": [{"plain_text": "edited in Notion"}]}
        task["last_edited_time"] = "2026-10-01T00:00:00.000Z"
        before = self._tasks_snapshot()
        result, output = self._pull(fake)
        self.assertEqual(0, result, output)
        self.assertEqual(before, self._tasks_snapshot())
        self.assertEqual([], self._tasks_db_calls(fake))
        self.assertEqual([], fake.mutations())

    def test_t019_status_reports_tasks_as_frozen(self):
        self._adopt()
        self._dirty_everything()
        self._freeze()
        result, output = self._status()
        self.assertIn("frozen (not synced", output)
        self.assertNotIn("edited task", output)

    # ── reviewer #1 follow-ups ───────────────────────────────

    def test_t019_status_audit_does_not_count_frozen_tasks(self):
        self._adopt()
        self._dirty_everything()
        self._freeze()
        fake = self._remote()
        with (
            self._patched(fake),
            mock.patch.object(self.sync, "run_preflight",
                              return_value={"status": "pass", "findings": [], "schemas": {},
                                            "links": {"projects": [], "tasks": []}}),
        ):
            report = self.sync.build_status_audit_report()
        with closing(self._connect()) as conn:
            project_dirty = conn.execute(
                "SELECT COUNT(*) FROM projects WHERE notion_page_id IS NULL OR last_sync_at "
                "IS NULL OR updated_at > last_sync_at").fetchone()[0]
            project_missing = conn.execute(
                "SELECT COUNT(*) FROM projects WHERE notion_page_id IS NULL").fetchone()[0]
        self.assertEqual(project_dirty, report["counts"]["dirty"])
        self.assertEqual(project_missing, report["counts"]["missing_id"])

    def test_t019_frozen_task_scope_mismatch_does_not_block_project_push(self):
        self._adopt()
        with closing(self._connect()) as conn:
            conn.execute("UPDATE tasks SET scope_id='L-OTHER' WHERE scope_id='L-A'")
            conn.execute("UPDATE projects SET goal='edited' WHERE scope_id='L-A'")
            conn.commit()
        self._freeze()
        with self._patched(self._remote()):
            plan = self.sync.build_push_plan(skip_preflight=True, scope_id="L-A")
        self.assertNotIn("TASK_SCOPE_IDENTITY_MISMATCH", json.dumps(plan))
        self.assertEqual(["project"], [op["entity"] for op in plan["operations"]])

    def test_t019_malformed_freeze_record_blocks_cleanly(self):
        self._adopt()
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO _metadata (key, value) VALUES ('task_sync_frozen', 'x')")
            conn.commit()
        with self._patched(self._remote()):
            plan = self.sync.build_push_plan(skip_preflight=True)
        self.assertEqual(3, plan["exit_code"])
        self.assertIn("TASK_FREEZE_RECORD_INVALID", json.dumps(plan))
        with mock.patch.object(self.sync, "_validate_notion_database",
                               return_value=({"last_edited_time": "x"}, [])):
            report = self.sync.run_preflight()
        self.assertEqual("blocked", report["status"])
        self.assertIn("TASK_FREEZE_RECORD_INVALID", json.dumps(report))

    # ── AC3: projects still sync normally ──────────────────────────────

    def test_t019_projects_still_push_with_post_verify(self):
        self._adopt()
        self._dirty_everything()
        self._freeze()
        fake = self._remote()
        with self._patched(fake):
            plan = self.sync.build_push_plan(skip_preflight=True)
        output = io.StringIO()
        with (
            self._patched(fake),
            mock.patch.object(self.sync, "run_preflight",
                              return_value={"status": "pass", "schemas": {}}),
            contextlib.redirect_stdout(output),
        ):
            result = self.sync.execute_push_plan(plan)
        self.assertEqual(0, result, output.getvalue())
        self.assertEqual(len(plan["operations"]),
                         output.getvalue().count("[POST-VERIFY PASS]"))
        self.assertFalse([c for c in fake.mutations() if "page-ta" in c[1]])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
