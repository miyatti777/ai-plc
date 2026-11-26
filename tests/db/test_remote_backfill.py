"""backfill-remote-identity (Identity onto already linked Notion pages).

API-free and production-free: the DB is the adopt-existing fixture in a
temporary directory, Notion is an in-memory fake with ``urlopen`` replaced by
AssertionError, and the production ``ai_plc.db`` fingerprint is asserted
unchanged on cleanup (inherited from the adopt-existing fixture setUp).
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import unittest
from contextlib import closing
from unittest import mock

try:  # unittest discovery imports test modules as top-level modules.
    from . import test_sync_identity as identity_tests
except ImportError:  # pragma: no cover - exercised by discovery invocation.
    import test_sync_identity as identity_tests

# Module attributes only: importing the adopt-existing TestCase class by name would make
# the loader collect and re-run every adopt-existing test from this module.
T007FakeNotion = identity_tests.T007FakeNotion
T011_UID_A = identity_tests.T011_UID_A
_built_to_read_properties = identity_tests._built_to_read_properties

T014_PATCH_EDIT = "2026-09-30T08:00:00.000Z"
T014_REMOTE_EDIT = "2026-09-01T00:00:00.000Z"
LINKED_TASK_PAGES = ["page-ta1", "page-o2"] + ["page-o%d" % n for n in range(3, 9)]


class T014FakeNotion(T007FakeNotion):
    """The shared fake Notion plus page GET / PATCH (PATCH merges properties)."""

    def __init__(self, sync, projects=None, tasks=None, fail_patch_for=None):
        super().__init__(sync, projects=projects, tasks=tasks)
        self.patch_bodies = []
        self.fail_patch_for = fail_patch_for

    def _find(self, page_id):
        for pages in self.pages.values():
            for page in pages:
                if page["id"] == page_id:
                    return page
        raise AssertionError("unknown page %s" % page_id)

    def api(self, method, path, body=None, retries=3):
        if path.startswith("/v1/pages/") and method in {"GET", "PATCH"}:
            self.calls.append((method, path))
            page = self._find(path.rsplit("/", 1)[1])
            if method == "PATCH":
                self.patch_bodies.append((page["id"], copy.deepcopy(body)))
                page["properties"].update(
                    _built_to_read_properties(body["properties"]))
                page["last_edited_time"] = T014_PATCH_EDIT
            return copy.deepcopy(page)
        return super().api(method, path, body, retries)


class T014RemoteIdentityBackfillTest(identity_tests.IdentityV2AdoptExistingTest):
    """Reuses the adopt-existing fixture; its inherited tests are not re-run."""

    def run(self, result=None):  # keep inherited adopt-existing tests out of this class
        if not self._testMethodName.startswith("test_t014_"):
            return result
        return super().run(result)

    # ── helpers ──────────────────────────────────────────────

    def _legacy_remote(self, **overrides):
        projects = [self._project_page("page-pa", "L-A")]
        tasks = [self._task_page("page-ta1", "L-A", "T001"),
                 self._task_page("page-x1", "L-OLD-A-SG0", "T004"),
                 self._task_page("page-o2", "L-OLD-B-X1", "T020")]
        tasks += [self._task_page("page-o%d" % (n + 2), "L-OLD-C-X2-SG1", "T%03d" % n)
                  for n in range(1, 7)]
        for page in projects:
            page["parent"]["database_id"] = self.sync.PROJECTS_DB_ID
        for page in tasks:
            page["parent"]["database_id"] = self.sync.TASKS_DB_ID
        return T014FakeNotion(self.sync, projects=projects, tasks=tasks, **overrides)

    def _bf_plan_path(self):
        return self.root / "backfill-plan.json"

    def _bf_dry_run(self):
        return self._main(["backfill-remote-identity", "--dry-run",
                           "--plan-out", str(self._bf_plan_path())])

    def _bf_plan(self):
        return json.loads(self._bf_plan_path().read_text(encoding="utf-8"))

    def _bf_execute(self, fake, *extra, plan_id=None):
        plan_id = plan_id or self._bf_plan()["plan_id"]
        with mock.patch.object(self.sync, "_api_call", side_effect=fake.api):
            return self._main(["backfill-remote-identity", "--plan",
                               str(self._bf_plan_path()), "--plan-id", plan_id,
                               *extra])

    def _row(self, table, where):
        with closing(self._connect()) as conn:
            return dict(conn.execute("SELECT * FROM %s WHERE %s" % (table, where))
                        .fetchone())

    def _adopted_and_planned(self):
        self._adopt()
        result, _calls, output = self._bf_dry_run()
        self.assertEqual(0, result, output)
        return self._bf_plan()

    # ── Only linked current-workspace pages, only 4 properties ─────

    def test_t014_ac1_plan_targets_only_linked_current_workspace_rows(self):
        plan = self._adopted_and_planned()
        pages = {op["page_id"] for op in plan["operations"]}
        self.assertEqual({"page-pa", *LINKED_TASK_PAGES}, pages)
        self.assertNotIn("page-x1", pages)  # legacy_excluded
        self.assertEqual({"project": 1, "task": 8, "batches": 1}, plan["counts"])
        self.assertTrue(self.sync.validate_remote_identity_backfill_plan(plan))
        # dry-run rerun reuses the same Plan
        result, _calls, output = self._bf_dry_run()
        self.assertEqual(0, result, output)
        self.assertIn('"reused": true', output)

    def test_t014_ac1_patches_exactly_four_identity_properties(self):
        self._adopted_and_planned()
        fake = self._legacy_remote()
        before = {page["id"]: copy.deepcopy(page["properties"])
                  for pages in fake.pages.values() for page in pages}
        result, _calls, output = self._bf_execute(fake)
        self.assertEqual(0, result, output)
        self.assertEqual(9, len(fake.patch_bodies))
        for page_id, body in fake.patch_bodies:
            names = set(body["properties"])
            expected = (self.sync.REMOTE_BACKFILL_PROPERTIES["project"]
                        if page_id == "page-pa"
                        else self.sync.REMOTE_BACKFILL_PROPERTIES["task"])
            self.assertEqual(set(expected), names)
        for pages in fake.pages.values():
            for page in pages:
                entity = "project" if page["id"] == "page-pa" else "task"
                skip = set(self.sync.REMOTE_BACKFILL_PROPERTIES[entity])
                self.assertEqual(
                    {k: v for k, v in before[page["id"]].items() if k not in skip},
                    {k: v for k, v in page["properties"].items() if k not in skip})
        excluded = fake._find("page-x1")
        self.assertEqual(before["page-x1"], excluded["properties"])
        project = fake._find("page-pa")
        self.assertEqual(T011_UID_A, project["properties"]["Sync UID"][
            "rich_text"][0]["plain_text"])

    def test_t014_ac1_split_brain_and_foreign_pages_stop_before_patch(self):
        self._adopted_and_planned()
        other = "prj_00000000-0000-4000-8000-00000000ffff"
        fake = self._legacy_remote()
        fake.pages["project"][0] = self._project_page("page-pa", "L-A", other)
        fake.pages["project"][0]["parent"]["database_id"] = self.sync.PROJECTS_DB_ID
        result, _calls, output = self._bf_execute(fake)
        self.assertEqual(3, result, output)
        self.assertIn("IDENTITY_SPLIT_BRAIN", output)
        self.assertEqual([], fake.patch_bodies)

        for mutate, code in (
                (lambda p: p["parent"].update(database_id="other-db"),
                 "REMOTE_BACKFILL_PAGE_PARENT_MISMATCH"),
                (lambda p: p["properties"].update(
                    {"Scope ID": self._rich("L-OTHER")}),
                 "REMOTE_BACKFILL_KEY_MISMATCH"),
                (lambda p: p.update(archived=True),
                 "REMOTE_BACKFILL_PAGE_ARCHIVED")):
            fake = self._legacy_remote()
            mutate(fake.pages["project"][0])
            result, _calls, output = self._bf_execute(fake)
            self.assertEqual(3, result, output)
            self.assertIn(code, output)
            self.assertEqual([], fake.patch_bodies)

    # ── Journal, resume, rerun 0, fixed Plan ─────────────

    def test_t014_ac2_resume_after_patch_does_not_patch_twice(self):
        plan = self._adopted_and_planned()
        fake = self._legacy_remote()
        state_path = str(self._bf_plan_path()) + ".state.json"
        with closing(self._connect()) as conn, \
                mock.patch.object(self.sync, "_api_call", side_effect=fake.api):
            with self.assertRaises(RuntimeError):
                self.sync.execute_remote_identity_backfill_plan(
                    conn, plan, expected_plan_id=plan["plan_id"],
                    state_path=state_path,
                    manifest_path=str(self.manifest_path), fail_at="after_patch")
        self.assertEqual(1, len(fake.patch_bodies))
        result, _calls, output = self._bf_execute(fake)
        self.assertEqual(0, result, output)
        self.assertEqual(9, len(fake.patch_bodies))
        self.assertEqual(1, len({pid for pid, _ in fake.patch_bodies
                                 if pid == fake.patch_bodies[0][0]}))
        # completed Plan: rerun makes no API call at all
        calls_before = len(fake.calls)
        result, _calls, output = self._bf_execute(fake)
        self.assertEqual(0, result, output)
        self.assertEqual(calls_before, len(fake.calls))
        self.assertIn('"state": "verified"', output)

    def test_t014_ac2_resume_before_patch_uses_current_remote_time(self):
        """A Notion edit made after a failed PATCH stays visible."""
        plan = self._adopted_and_planned()
        fake = self._legacy_remote()
        state_path = str(self._bf_plan_path()) + ".state.json"
        with closing(self._connect()) as conn, \
                mock.patch.object(self.sync, "_api_call", side_effect=fake.api):
            with self.assertRaises(RuntimeError):
                self.sync.execute_remote_identity_backfill_plan(
                    conn, plan, expected_plan_id=plan["plan_id"],
                    state_path=state_path,
                    manifest_path=str(self.manifest_path), fail_at="before_patch")
        self.assertEqual([], fake.patch_bodies)
        first = plan["operations"][0]["page_id"]
        fake._find(first)["last_edited_time"] = T014_REMOTE_EDIT  # user edit
        table = "projects" if first == "page-pa" else "tasks"
        before = self._row(table, "notion_page_id='%s'" % first)
        result, _calls, output = self._bf_execute(fake)
        self.assertEqual(0, result, output)
        after = self._row(table, "notion_page_id='%s'" % first)
        self.assertEqual(before["notion_last_edited"], after["notion_last_edited"])
        self.assertTrue(self.sync._instant_gt(
            fake._find(first)["last_edited_time"], after["notion_last_edited"]))

    def test_t014_ac2_concurrent_edit_is_left_for_pull_not_exit_5(self):
        """Other-property change during backfill keeps remote dirty."""
        self._adopted_and_planned()
        fake = self._legacy_remote()
        original = fake.api

        def api(method, path, body=None, retries=3):
            response = original(method, path, body, retries)
            if method == "PATCH" and path.endswith("page-ta1"):
                page = fake._find("page-ta1")
                page["properties"]["ステータス"] = {"status": {"name": "完了"}}
                response = copy.deepcopy(page)
            return response
        fake.api = api
        before = self._row("tasks", "notion_page_id='page-ta1'")
        result, _calls, output = self._bf_execute(fake)
        self.assertEqual(0, result, output)
        self.assertIn("[WARN]", output)
        after = self._row("tasks", "notion_page_id='page-ta1'")
        self.assertEqual(before["notion_last_edited"], after["notion_last_edited"])

    def test_t014_ac2_computed_properties_changed_by_patch_are_not_edits(self):
        """Last-edited/formula style properties move on PATCH."""
        self._adopted_and_planned()
        fake = self._legacy_remote()
        original = fake.api
        counter = {"n": 0}

        def api(method, path, body=None, retries=3):
            response = original(method, path, body, retries)
            if method == "PATCH":
                counter["n"] += 1
                page = fake._find(path.rsplit("/", 1)[1])
                page["properties"]["最終更新"] = {
                    "last_edited_time": "2026-09-30T08:0%d:00.000Z" % (counter["n"] % 10)}
                response = copy.deepcopy(page)
            return response
        fake.api = api
        result, _calls, output = self._bf_execute(fake)
        self.assertEqual(0, result, output)
        self.assertNotIn("[WARN]", output)
        clean = self._row("tasks", "notion_page_id='page-ta1'")
        self.assertEqual(T014_PATCH_EDIT, clean["notion_last_edited"])

    def test_t014_ac2_claimed_op_whose_row_changed_stops_with_exit_5(self):
        """A PATCH may have landed; never report it as skipped."""
        plan = self._adopted_and_planned()
        fake = self._legacy_remote()
        state_path = str(self._bf_plan_path()) + ".state.json"
        with closing(self._connect()) as conn, \
                mock.patch.object(self.sync, "_api_call", side_effect=fake.api):
            with self.assertRaises(RuntimeError):
                self.sync.execute_remote_identity_backfill_plan(
                    conn, plan, expected_plan_id=plan["plan_id"],
                    state_path=state_path,
                    manifest_path=str(self.manifest_path), fail_at="after_patch")
        first = plan["operations"][0]["page_id"]
        table = "projects" if first == "page-pa" else "tasks"
        with closing(self._connect()) as conn:
            conn.execute("UPDATE %s SET notion_page_id='page-moved' "
                         "WHERE notion_page_id=?" % table, (first,))
            conn.commit()
        result, _calls, output = self._bf_execute(fake)
        self.assertEqual(5, result, output)
        self.assertIn("REMOTE_BACKFILL_CLAIMED_SOURCE_CHANGED", output)
        self.assertEqual(1, len(fake.patch_bodies))

    def test_t014_ac2_readback_mismatch_is_exit_5_and_api_errors_map(self):
        plan = self._adopted_and_planned()
        fake = self._legacy_remote()
        original = fake.api

        def lossy(method, path, body=None, retries=3):
            if method == "PATCH":
                fake.patch_bodies.append((path, body))
                return {}
            return original(method, path, body, retries)
        result, _calls, output = self._bf_execute(
            type("F", (), {"api": staticmethod(lossy)})())
        self.assertEqual(5, result, output)
        self.assertIn("REMOTE_BACKFILL_READBACK_MISMATCH", output)
        for code, expected in ((503, 4), (429, 4), (404, 3), (400, 3)):
            def failing(method, path, body=None, retries=3, _code=code):
                raise self.sync.urllib.error.HTTPError(path, _code, "x", {}, None)
            result, _calls, output = self._bf_execute(
                type("F", (), {"api": staticmethod(failing)})(),
                plan_id=plan["plan_id"])
            self.assertEqual(expected, result, (code, output))

    def test_t014_ac2_fresh_plan_after_completion_patches_nothing(self):
        self._adopted_and_planned()
        fake = self._legacy_remote()
        self.assertEqual(0, self._bf_execute(fake)[0])
        self._bf_plan_path().unlink()
        (self.root / "backfill-plan.json.state.json").unlink()
        result, _calls, output = self._bf_dry_run()
        self.assertEqual(0, result, output)
        patches = len(fake.patch_bodies)
        result, _calls, output = self._bf_execute(fake)
        self.assertEqual(0, result, output)
        self.assertEqual(patches, len(fake.patch_bodies))
        self.assertIn('"already": 9', output)

    def test_t014_ac2_tampered_plan_and_source_change_stop_before_api(self):
        plan = self._adopted_and_planned()
        fake = self._legacy_remote()
        result, _calls, output = self._bf_execute(fake, plan_id="sha256:" + "0" * 64)
        self.assertEqual(2, result, output)
        tampered = dict(plan, operations=[dict(plan["operations"][0],
                                               page_id="page-x1")]
                        + plan["operations"][1:])
        self._bf_plan_path().write_text(json.dumps(tampered), encoding="utf-8")
        result, _calls, output = self._bf_execute(fake, plan_id=plan["plan_id"])
        self.assertEqual(2, result, output)
        self.assertEqual([], fake.calls)
        # A row relinked after the Plan is skipped (never written), the rest runs.
        self._bf_plan_path().write_text(json.dumps(plan), encoding="utf-8")
        with closing(self._connect()) as conn:
            conn.execute("UPDATE tasks SET notion_page_id='page-moved' "
                         "WHERE notion_page_id='page-ta1'")
            conn.commit()
        result, _calls, output = self._bf_execute(fake)
        self.assertEqual(0, result, output)
        self.assertIn('"state": "verified_with_skips"', output)
        self.assertIn('"skipped_source_changed": 1', output)
        self.assertNotIn("page-ta1", {pid for pid, _ in fake.patch_bodies})
        self.assertNotIn(("GET", "/v1/pages/page-ta1"), fake.calls)
        self.assertEqual(8, len(fake.patch_bodies))

    def test_t014_ac2_max_batches_runs_partially_then_resumes(self):
        self.sync.REMOTE_BACKFILL_BATCH_SIZE = 2
        plan = self._adopted_and_planned()
        self.assertEqual(5, plan["counts"]["batches"])
        fake = self._legacy_remote()
        result, _calls, output = self._bf_execute(fake, "--max-batches", "1")
        self.assertEqual(0, result, output)
        self.assertIn('"state": "partial"', output)
        self.assertEqual(2, len(fake.patch_bodies))
        result, _calls, output = self._bf_execute(fake)
        self.assertEqual(0, result, output)
        self.assertEqual(9, len(fake.patch_bodies))

    # ── Local baseline keeps local/remote edits visible ──────

    def test_t014_ac3_baseline_clean_dirty_and_remote_dirty(self):
        self._adopted_and_planned()
        with closing(self._connect()) as conn:
            conn.execute("UPDATE projects SET goal='edited' WHERE scope_id='L-A'")
            conn.commit()
        fake = self._legacy_remote()
        fake._find("page-o2")["last_edited_time"] = T014_REMOTE_EDIT
        before_o2 = self._row("tasks", "notion_page_id='page-o2'")
        result, _calls, output = self._bf_execute(fake)
        self.assertEqual(0, result, output)
        self.assertIn("local_dirty_kept", output)
        self.assertIn("remote_dirty_kept", output)
        project = self._row("projects", "scope_id='L-A'")
        self.assertEqual(T014_PATCH_EDIT, project["notion_last_edited"])
        self.assertTrue(self.sync._instant_gt(project["updated_at"],
                                              project["last_sync_at"]))
        clean = self._row("tasks", "notion_page_id='page-ta1'")
        self.assertEqual(T014_PATCH_EDIT, clean["notion_last_edited"])
        self.assertFalse(self.sync._instant_gt(clean["updated_at"],
                                               clean["last_sync_at"]))
        o2 = self._row("tasks", "notion_page_id='page-o2'")
        self.assertEqual(before_o2["notion_last_edited"], o2["notion_last_edited"])
        # After backfill, the dirty linked project is an ordinary patch_remote.
        fake.pages["project"][0]["last_edited_time"] = T014_PATCH_EDIT
        plan = self._build_push_plan(fake)
        project_ops = [op for op in plan["operations"] if op["entity"] == "project"
                       and op["identity"]["project_sync_uid"] == T011_UID_A]
        self.assertEqual(["patch_remote"], [op["action"] for op in project_ops])

    # ── v2 push never reports a no-op attach as success ────────

    def test_t014_ac4_linked_legacy_page_blocks_push_with_backfill_hint(self):
        self._adopt()
        with closing(self._connect()) as conn:
            conn.execute("UPDATE projects SET goal='edited' WHERE scope_id='L-A'")
            conn.commit()
        fake = self._legacy_remote()
        plan = self._build_push_plan(fake)
        self.assertNotEqual(0, plan["exit_code"])
        projection = plan["reconciliation"]
        self.assertEqual(1, projection["blocking"]["summary"].get("attach"))
        self.assertEqual(0, projection["authorization_required"]["summary"]
                         .get("attach", 0))
        self.assertEqual([], fake.mutations())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.sync._print_push_plan(plan, dry_run=True)
        self.assertIn("backfill-remote-identity", output.getvalue())

    def test_t014_ac4_execute_guard_refuses_old_authorized_linked_attach(self):
        """An attach Plan approved before backfill-remote-identity existed must not report a no-op success."""
        self._adopt()
        with closing(self._connect()) as conn:
            conn.execute("UPDATE projects SET goal='edited' WHERE scope_id='L-A'")
            conn.commit()
        fake = self._legacy_remote()
        plan = self._build_push_plan(fake)
        attach_ids = [op["operation_id"] for op in plan["operations"]
                      if op["action"] == "attach_candidate"]
        self.assertEqual(1, len(attach_ids))
        # Re-shape into what the older classifier produced (authorization).
        rec = plan["reconciliation"]
        rec["authorization_required"]["operation_ids"] = attach_ids
        rec["blocking"]["exit_code"] = 0
        rec["blocking"]["findings"] = []
        plan["exit_code"] = 0
        plan["plan_id"] = self.sync._push_plan_id(plan)
        before = self._row("projects", "scope_id='L-A'")
        output = io.StringIO()
        with (
            mock.patch.object(self.sync, "_revalidate_identity_plan_before_write",
                              return_value=0),
            mock.patch.object(self.sync, "validate_push_plan", return_value=True),
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
            contextlib.redirect_stdout(output),
        ):
            result = self.sync.execute_push_plan(plan, authorization={
                "plan_id": plan["plan_id"], "operation_ids": attach_ids,
                "approved_by": "t014"})
        self.assertEqual(2, result, output.getvalue())
        self.assertIn("REMOTE_IDENTITY_BACKFILL_REQUIRED", output.getvalue())
        self.assertNotIn("[ATTACH]", output.getvalue())
        self.assertEqual(before, self._row("projects", "scope_id='L-A'"))

    # ── CLI strictness and read-only status ─────────────────────

    def test_t014_cli_rejects_bad_modes_and_status_is_read_only(self):
        for argv in (["backfill-remote-identity"],
                     ["backfill-remote-identity", "--dry-run"],
                     ["backfill-remote-identity", "--dry-run", "--plan-out", "x",
                      "--max-batches", "1"],
                     ["backfill-remote-identity", "--plan", "x"],
                     ["backfill-remote-identity", "--status", "--plan", "x",
                      "--plan-id", "y"],
                     ["backfill-remote-identity", "--status"]):
            result, _calls, _output = self._main(argv)
            self.assertEqual(64, result, argv)
        plan = self._adopted_and_planned()
        fake = self._legacy_remote()
        snapshot = self._snapshot()
        with mock.patch.object(self.sync, "_api_call", side_effect=fake.api):
            result, _calls, output = self._main([
                "backfill-remote-identity", "--status", "--plan",
                str(self._bf_plan_path())])
        self.assertEqual(0, result, output)
        self.assertEqual([], fake.calls)
        self.assertEqual(snapshot, self._snapshot())
        self.assertIn(plan["plan_id"], output)
        result, _calls, output = self._bf_execute(fake, "--max-batches", "0")
        self.assertEqual(64, result, output)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
