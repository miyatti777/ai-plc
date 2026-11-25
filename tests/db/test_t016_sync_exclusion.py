"""T016: sync-excluded Scopes are never planned, pulled, backfilled or attached.

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
T011_UID_A = identity_tests.T011_UID_A


class T016SyncExclusionTest(identity_tests.IdentityV2AdoptExistingTest):
    """Reuses the T011 fixture; the inherited T011 tests are not re-run."""

    def run(self, result=None):  # keep inherited T011 tests out of this class
        if not self._testMethodName.startswith("test_t016_"):
            return result
        return super().run(result)

    # ── helpers ──────────────────────────────────────────────

    def _exclude(self, *argv):
        return self._main(["exclude", *argv])

    def _register_la(self):
        result, _calls, output = self._exclude(
            "--scope", "L-A", "--approved-by", "t016", "--reason", "confidential")
        self.assertEqual(0, result, output)
        return output

    def _remote_with_la(self, identity=True):
        # Notion still carries L-A pages (e.g. restored from the trash).
        uid = T011_UID_A if identity else None
        project = self._project_page("page-pa", "L-A", uid)
        project["parent"]["database_id"] = self.sync.PROJECTS_DB_ID
        task = self._task_page("page-ta1", "L-A", "T001", uid)
        task["parent"]["database_id"] = self.sync.TASKS_DB_ID
        return T014FakeNotion(self.sync, projects=[project], tasks=[task])

    def _push_plan(self, fake, **kwargs):
        with (
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
        ):
            return self.sync.build_push_plan(skip_preflight=True, **kwargs)

    def _la_rows(self):
        with closing(self._connect()) as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM projects WHERE scope_id='L-A' UNION ALL "
                "SELECT * FROM projects WHERE 0").fetchall()] + [dict(row) for row in
                conn.execute("SELECT * FROM tasks WHERE scope_id='L-A'").fetchall()]

    def _la_scopes_in(self, plan):
        return {op["display_scope_id"] for op in plan["operations"]}

    # ── AC2: registration clears local links, keeps Identity and content ──

    def test_t016_ac2_register_clears_links_and_keeps_rows(self):
        self._adopt()
        before = self._la_rows()
        self.assertTrue(all(row["notion_page_id"] for row in before))
        output = self._register_la()
        self.assertIn("projects 1, tasks 1", output)
        after = self._la_rows()
        self.assertEqual([None] * len(after), [row["notion_page_id"] for row in after])
        for old, new in zip(before, after):
            for column in ("name", "sync_uid", "workspace_id", "project_sync_uid",
                           "task_id", "status"):
                if column in old:
                    self.assertEqual(old[column], new[column], column)
        result, _calls, output = self._exclude("--list")
        self.assertEqual(0, result, output)
        self.assertIn("L-A approved_by=t016", output)
        self.assertIn("reason=confidential", output)
        result, _calls, output = self._exclude("--scope", "L-A", "--approved-by", "x")
        self.assertEqual(0, result, output)
        self.assertIn("already registered", output)

    def test_t016_ac2_cli_is_strict(self):
        for argv in ([], ["--list", "--scope", "L-A"], ["--scope", "L-A"],
                     ["--remove", "L-A"], ["--list", "--approved-by", "x"],
                     ["--remove", "L-A", "--approved-by", "x", "--reason", "r"]):
            result, _calls, _output = self._exclude(*argv)
            self.assertEqual(64, result, argv)
        self._adopt()
        result, _calls, output = self._exclude("--scope", "L-A", "--approved-by", " ")
        self.assertEqual(2, result, output)
        result, _calls, output = self._exclude("--remove", "L-Z", "--approved-by", "x")
        self.assertEqual(2, result, output)
        self.assertIn("EXCLUDE_SCOPE_NOT_REGISTERED", output)

    def test_t016_ac2_pending_journal_blocks_registration(self):
        self._adopt()
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO _metadata (key, value) VALUES "
                         "('pending_push:v2:opv2_x', '{}')")
            conn.commit()
        result, _calls, output = self._exclude("--scope", "L-A", "--approved-by", "x")
        self.assertEqual(3, result, output)
        self.assertIn("EXCLUDE_PENDING_JOURNAL", output)
        self.assertTrue(all(row["notion_page_id"] for row in self._la_rows()))

    # ── AC1 / AC4: never planned, never attached, never pulled ─────────

    def test_t016_ac1_push_plans_skip_excluded_rows_even_with_remote_pages(self):
        self._adopt()
        self._register_la()
        for identity in (False, True):
            fake = self._remote_with_la(identity=identity)
            plan = self._push_plan(fake)  # workspace-wide
            self.assertNotIn("L-A", self._la_scopes_in(plan))
            self.assertEqual([], [op for op in plan["operations"]
                                  if op["action"] == "attach_candidate"])
            self.assertEqual([], fake.mutations())

    def test_t016_ac3_explicit_selector_for_excluded_scope_is_refused(self):
        self._adopt()
        self._register_la()
        fake = self._remote_with_la()
        for kwargs in ({"scope_id": "L-A"}, {"sync_uid": T011_UID_A}):
            plan = self._push_plan(fake, **kwargs)
            self.assertEqual(3, plan["exit_code"], kwargs)
            self.assertEqual([], plan["operations"])
            self.assertIn("SCOPE_EXCLUDED", json.dumps(plan))
        self.assertEqual([], fake.mutations())

    def test_t016_ac1_pull_ignores_remote_pages_of_excluded_scope(self):
        self._adopt()
        self._register_la()
        before = self._la_rows()
        fake = self._remote_with_la(identity=True)
        fake._find("page-pa")["properties"]["PJ名"] = {
            "title": [{"plain_text": "Edited in Notion"}]}
        fake._find("page-pa")["last_edited_time"] = "2026-09-30T09:00:00.000Z"
        result, output = self._pull(fake)
        self.assertIn(result, (0,), output)
        self.assertEqual(before, self._la_rows())
        with closing(self._connect()) as conn:
            self.assertEqual(0, conn.execute(
                "SELECT COUNT(*) FROM projects WHERE name='Edited in Notion'").fetchone()[0])
        self.assertEqual([], fake.mutations())

    def test_t016_ac1_backfill_never_targets_excluded_rows(self):
        self._adopt()
        self._register_la()
        with closing(self._connect()) as conn:  # relinked by hand afterwards
            conn.execute("UPDATE projects SET notion_page_id='page-pa' "
                         "WHERE scope_id='L-A'")
            conn.commit()
        result, _calls, output = self._main([
            "backfill-remote-identity", "--dry-run",
            "--plan-out", str(self.root / "bf.json")])
        self.assertEqual(0, result, output)
        plan = json.loads((self.root / "bf.json").read_text(encoding="utf-8"))
        self.assertNotIn("L-A", {op["scope_id"] for op in plan["operations"]})

    def test_t016_ac4_excluded_row_is_not_matched_in_reconciliation(self):
        self._adopt()
        self._register_la()
        fake = self._remote_with_la(identity=False)
        with (
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
        ):
            report = self.sync.run_reconciliation()
        text = json.dumps(report)
        self.assertNotIn("page-pa", text)
        self.assertNotIn("page-ta1", text)
        with closing(self._connect()) as conn:
            excluded_ids = {row[0] for row in conn.execute(
                "SELECT id FROM projects WHERE scope_id='L-A'")}
        self.assertEqual([], [item for item in report["items"]
                              if item.get("entity") == "project"
                              and item.get("local_row_id") in excluded_ids])
        self.assertNotIn("L-A", {(item.get("stable_key") or [None])[0]
                                 for item in report["items"]})

    # ── reviewer #1 follow-ups ───────────────────────────────

    def test_t016_plan_saved_before_exclude_is_refused_at_execution(self):
        self._adopt()
        with closing(self._connect()) as conn:
            conn.execute("UPDATE projects SET goal='secret goal' WHERE scope_id='L-A'")
            conn.commit()
        fake = self._remote_with_la(identity=True)
        plan = self._push_plan(fake)
        self.assertIn("L-A", self._la_scopes_in(plan))
        self._register_la()
        output = io.StringIO()
        with (
            mock.patch.object(self.sync, "_revalidate_identity_plan_before_write",
                              return_value=0),
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
            contextlib.redirect_stdout(output),
        ):
            result = self.sync.execute_push_plan(plan)
        self.assertEqual(3, result, output.getvalue())
        self.assertIn("SCOPE_EXCLUDED", output.getvalue())
        self.assertEqual([], fake.mutations())

    def test_t016_task_of_excluded_project_with_other_scope_is_excluded(self):
        self._adopt()
        self._register_la()
        with closing(self._connect()) as conn:  # task moved to another display Scope
            conn.execute("UPDATE tasks SET scope_id='L-RENAMED' WHERE scope_id='L-A'")
            conn.execute("UPDATE projects SET scope_id='L-RENAMED' WHERE scope_id='L-A'")
            conn.commit()
        fake = T014FakeNotion(self.sync)
        plan = self._push_plan(fake)
        self.assertNotIn(T011_UID_A, {op["identity"]["project_sync_uid"]
                                      for op in plan["operations"]})
        plan = self._push_plan(fake, sync_uid=T011_UID_A)
        self.assertEqual(3, plan["exit_code"])
        self.assertIn("SCOPE_EXCLUDED", json.dumps(plan))
        self.assertEqual([], fake.mutations())

    def test_t016_link_clearing_uses_normalized_scope(self):
        self._adopt()
        with closing(self._connect()) as conn:
            conn.execute("UPDATE tasks SET scope_id='L-A ' WHERE scope_id='L-A'")
            conn.commit()
        output = self._register_la()
        self.assertIn("projects 1, tasks 1", output)
        with closing(self._connect()) as conn:
            self.assertEqual(0, conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE trim(scope_id)='L-A' "
                "AND notion_page_id IS NOT NULL").fetchone()[0])

    def test_t016_remove_keeps_an_audit_record(self):
        self._adopt()
        self._register_la()
        self.assertEqual(0, self._exclude("--remove", "L-A", "--approved-by", "t016b")[0])
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT value FROM _metadata WHERE key LIKE "
                                "'sync_exclusion_removed:L-A:%'").fetchall()
        self.assertEqual(1, len(rows))
        record = json.loads(rows[0][0])
        self.assertEqual("t016b", record["removed_by"])
        self.assertEqual("t016", record["previous"]["approved_by"])

    # ── remove + malformed record ─────────────────────────────

    def test_t016_remove_makes_rows_pushable_again(self):
        self._adopt()
        self._register_la()
        result, _calls, output = self._exclude("--remove", "L-A", "--approved-by", "t016")
        self.assertEqual(0, result, output)
        plan = self._push_plan(T014FakeNotion(self.sync))
        self.assertIn("L-A", self._la_scopes_in(plan))
        self.assertEqual({"create_remote"}, {
            op["action"] for op in plan["operations"]
            if op["display_scope_id"] == "L-A"})

    def test_t016_malformed_record_stops_push_and_pull(self):
        self._adopt()
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO _metadata (key, value) VALUES (?, ?)",
                         (self.sync.EXCLUDE_META_PREFIX + "L-A", "not-json"))
            conn.commit()
        fake = self._remote_with_la()
        plan = self._push_plan(fake)
        self.assertEqual(3, plan["exit_code"])
        self.assertIn("EXCLUDE_RECORD_INVALID", json.dumps(plan))
        result, output = self._pull(fake)
        self.assertEqual(3, result, output)
        result, _calls, output = self._exclude("--list")
        self.assertEqual(3, result, output)
        self.assertEqual([], fake.mutations())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
