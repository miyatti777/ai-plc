"""T015: approved decline of legacy attach candidates + collision normalization.

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
T011_UID_B = identity_tests.T011_UID_B


class T015AttachDeclineTest(identity_tests.IdentityV2AdoptExistingTest):
    """Reuses the T011 fixture; the inherited T011 tests are not re-run."""

    def run(self, result=None):  # keep inherited T011 tests out of this class
        if not self._testMethodName.startswith("test_t015_"):
            return result
        return super().run(result)

    # ── helpers ──────────────────────────────────────────────

    def _other_project_page(self, page_id, name="Another team's project"):
        # Same display Scope ID as the local unlinked L-B, but Identity-less and
        # a different Project (the production L-OLD-14 / L-OLD-28 situation).
        page = self._project_page(page_id, "L-B", name=name)
        page["parent"]["database_id"] = self.sync.PROJECTS_DB_ID
        return page

    def _fake(self, *legacy_pages):
        return T014FakeNotion(self.sync, projects=list(legacy_pages), tasks=[])

    def _plan_for(self, fake, scope_id="L-B"):
        with (
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
        ):
            return self.sync.build_push_plan(skip_preflight=True, scope_id=scope_id)

    def _write_plan(self, plan, name="push-plan.json"):
        path = self.root / name
        self.sync.write_push_plan(plan, str(path))
        return path

    def _decline_file(self, plan, op_ids, **overrides):
        document = {"plan_id": plan["plan_id"], "operation_ids": op_ids,
                    "approved_by": "t015-reviewer"}
        document.update(overrides)
        path = self.root / "decline.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def _decline(self, fake, plan_path, plan_id, decline_path, scope_id="L-B"):
        output = io.StringIO()
        with (
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
            contextlib.redirect_stdout(output),
        ):
            result = self.sync.cmd_push(
                plan_path=str(plan_path), expected_plan_id=plan_id,
                decline_path=str(decline_path), scope_id=scope_id)
        return result, output.getvalue()

    def _declined_meta(self):
        with closing(self._connect()) as conn:
            return {row[0]: json.loads(row[1]) for row in conn.execute(
                "SELECT key, value FROM _metadata WHERE key LIKE ?",
                (self.sync.DECLINE_META_PREFIX + "%",)).fetchall()}

    def _project_ops(self, plan):
        return [op for op in plan["operations"] if op["entity"] == "project"]

    def _attach_plan(self, fake):
        plan = self._plan_for(fake)
        ops = self._project_ops(plan)
        self.assertEqual(["attach_candidate"], [op["action"] for op in ops])
        self.assertEqual("LEGACY_ATTACH_CANDIDATE",
                         ops[0]["expected_reconciliation_reason"])
        return plan, ops[0]

    # ── AC1 / AC3: decline -> ordinary CREATE, legacy page untouched ───

    def test_t015_ac1_declined_candidate_is_created_as_new_identity(self):
        self._adopt()
        legacy = self._other_project_page("legacy-lb")
        fake = self._fake(legacy)
        legacy_before = json.loads(json.dumps(legacy))
        plan, attach = self._attach_plan(fake)
        plan_path = self._write_plan(plan)
        result, output = self._decline(
            fake, plan_path, plan["plan_id"],
            self._decline_file(plan, [attach["operation_id"]]))
        self.assertEqual(0, result, output)
        self.assertIn("[DECLINE] project L-B", output)
        self.assertEqual([], fake.mutations())  # recording is local only
        meta = list(self._declined_meta().values())
        self.assertEqual([["legacy-lb"]], [entry["page_ids"] for entry in meta])
        self.assertEqual("t015-reviewer", meta[0]["approved_by"])

        # AC3: the next Plan no longer offers the page; the row is a CREATE.
        plan = self._plan_for(fake)
        ops = self._project_ops(plan)
        self.assertEqual(["create_remote"], [op["action"] for op in ops])
        self.assertEqual(0, plan["exit_code"])
        self.assertEqual([], plan["reconciliation"]["authorization_required"]
                         ["operation_ids"])
        output = io.StringIO()
        # Only the Notion schema GET is stubbed; the pre-write revalidation
        # still re-runs reconciliation (which must honour the decline).
        with (
            mock.patch.object(self.sync, "run_preflight",
                              return_value={"status": "pass", "schemas": {}}),
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
            contextlib.redirect_stdout(output),
        ):
            result = self.sync.execute_push_plan(plan, scope_id="L-B")
        self.assertEqual(0, result, output.getvalue())
        self.assertEqual(len(plan["operations"]),
                         output.getvalue().count("[POST-VERIFY PASS]"))
        self.assertEqual(legacy_before, fake._find("legacy-lb"))
        created = [page for page in fake.pages["project"] if page["id"] != "legacy-lb"]
        self.assertEqual(1, len(created))
        self.assertEqual(T011_UID_B, created[0]["properties"]["Sync UID"][
            "rich_text"][0]["plain_text"])
        with closing(self._connect()) as conn:
            linked = conn.execute("SELECT notion_page_id FROM projects "
                                  "WHERE scope_id='L-B'").fetchone()[0]
        self.assertEqual(created[0]["id"], linked)
        rerun = self._plan_for(fake)
        self.assertEqual((0, []), (rerun["exit_code"], rerun["operations"]))

    def test_t015_ac1_rerecording_the_same_decline_is_a_noop(self):
        self._adopt()
        fake = self._fake(self._other_project_page("legacy-lb"))
        plan, attach = self._attach_plan(fake)
        plan_path = self._write_plan(plan)
        decline = self._decline_file(plan, [attach["operation_id"]])
        self.assertEqual(0, self._decline(fake, plan_path, plan["plan_id"], decline)[0])
        before = self._declined_meta()
        result, output = self._decline(fake, plan_path, plan["plan_id"], decline)
        self.assertEqual(0, result, output)
        self.assertIn('"unchanged": 1', output)
        self.assertEqual(before, self._declined_meta())

    # ── AC2: approval document is strict; nothing is written on refusal ──

    def test_t015_ac2_invalid_decline_documents_stop_before_writing(self):
        self._adopt()
        fake = self._fake(self._other_project_page("legacy-lb"))
        plan, attach = self._attach_plan(fake)
        plan_path = self._write_plan(plan)
        create_ids = [op["operation_id"] for op in plan["operations"]
                      if op["action"] == "create_remote"]
        cases = (
            ({"approved_by": ""}, "DECLINE_DOCUMENT_INVALID"),
            ({"plan_id": "0" * 64}, "DECLINE_PLAN_MISMATCH"),
            ({"extra": 1}, "DECLINE_DOCUMENT_INVALID"),
            ({"operation_ids": []}, "DECLINE_DOCUMENT_INVALID"),
            ({"operation_ids": [attach["operation_id"]] * 2},
             "DECLINE_DOCUMENT_INVALID"),
            ({"operation_ids": create_ids[:1]}, "DECLINE_OPERATION_INVALID"),
            ({"operation_ids": ["opv2_unknown"]}, "DECLINE_OPERATION_INVALID"),
        )
        for overrides, code in cases:
            ids = overrides.pop("operation_ids", [attach["operation_id"]])
            decline = self._decline_file(plan, ids, **overrides)
            result, output = self._decline(fake, plan_path, plan["plan_id"], decline)
            self.assertEqual(2, result, (overrides, output))
            self.assertIn(code, output)
            self.assertEqual({}, self._declined_meta())
        self.assertEqual([], fake.mutations())

    def test_t015_ac2_exact_identity_attach_cannot_be_declined(self):
        """Only legacy (Identity-less) candidates are declinable."""
        self._adopt()
        same = self._project_page("exact-lb", "L-B", T011_UID_B)
        same["parent"]["database_id"] = self.sync.PROJECTS_DB_ID
        fake = self._fake(same)
        plan = self._plan_for(fake)
        ops = self._project_ops(plan)
        self.assertEqual("IDENTITY_EXACT", ops[0]["expected_reconciliation_reason"])
        result, output = self._decline(
            fake, self._write_plan(plan), plan["plan_id"],
            self._decline_file(plan, [ops[0]["operation_id"]]))
        self.assertEqual(2, result, output)
        self.assertIn("DECLINE_OPERATION_INVALID", output)
        self.assertEqual({}, self._declined_meta())

    def test_t015_ac2_row_changed_after_plan_is_refused(self):
        self._adopt()
        fake = self._fake(self._other_project_page("legacy-lb"))
        plan, attach = self._attach_plan(fake)
        plan_path = self._write_plan(plan)
        with closing(self._connect()) as conn:
            conn.execute("UPDATE projects SET notion_page_id='page-linked-meanwhile' "
                         "WHERE scope_id='L-B'")
            conn.commit()
        result, output = self._decline(
            fake, plan_path, plan["plan_id"],
            self._decline_file(plan, [attach["operation_id"]]))
        self.assertEqual(2, result, output)
        self.assertIn("DECLINE_SOURCE_CHANGED", output)
        self.assertEqual({}, self._declined_meta())

    def test_t015_ac2_cli_rejects_decline_with_other_modes(self):
        for argv in (["push", "--dry-run", "--decline", "d.json"],
                     ["push", "--decline", "d.json"],
                     ["push", "--plan", "p.json", "--plan-id", "x",
                      "--decline", "d.json", "--authorization", "a.json"],
                     ["push", "--plan", "p.json", "--plan-id", "x",
                      "--decline", "d.json", "--plan-out", "o.json"]):
            result, _calls, _output = self._main(argv)
            self.assertEqual(64, result, argv)

    # ── AC4: collision is a blocked conflict, never a malformed Plan ──────

    def test_t015_ac4_ambiguous_legacy_is_a_valid_blocked_plan_and_declinable(self):
        self._adopt()
        fake = self._fake(self._other_project_page("legacy-1"),
                          self._other_project_page("legacy-2", name="Third project"))
        plan = self._plan_for(fake)
        ops = self._project_ops(plan)
        self.assertEqual(["conflict"], [op["action"] for op in ops])
        self.assertEqual("LEGACY_AMBIGUOUS", ops[0]["expected_reconciliation_reason"])
        self.assertTrue(self.sync.validate_push_plan(plan))
        self.assertEqual(2, plan["exit_code"])
        # The same holds for a workspace-wide Plan (was "plan_id mismatch").
        with (
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
        ):
            workspace_plan = self.sync.build_push_plan(skip_preflight=True)
        self.assertTrue(self.sync.validate_push_plan(workspace_plan))
        self.assertEqual(2, workspace_plan["exit_code"])
        # Declining both candidates turns the row into an ordinary CREATE.
        plan_path = self._write_plan(plan)
        result, output = self._decline(
            fake, plan_path, plan["plan_id"],
            self._decline_file(plan, [ops[0]["operation_id"]]))
        self.assertEqual(0, result, output)
        plan = self._plan_for(fake)
        self.assertEqual(["create_remote"],
                         [op["action"] for op in self._project_ops(plan)])
        self.assertEqual([], fake.mutations())

    def test_t015_ac4_declined_page_is_audit_only_and_other_pages_still_offered(self):
        self._adopt()
        fake = self._fake(self._other_project_page("legacy-1"),
                          self._other_project_page("legacy-2", name="Same project"))
        plan = self._plan_for(fake)
        conflict = self._project_ops(plan)[0]
        # Record a decline for only one of the two pages (as an older decision).
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO _metadata (key, value) VALUES (?, ?)", (
                self.sync._decline_meta_key("project", (T011_UID_B,)),
                json.dumps({"page_ids": ["legacy-1"], "plan_id": plan["plan_id"],
                            "operation_id": conflict["operation_id"],
                            "approved_by": "x", "declined_at": "2026-09-30T00:00:00Z"})))
            conn.commit()
        plan = self._plan_for(fake)
        ops = self._project_ops(plan)
        self.assertEqual(["attach_candidate"], [op["action"] for op in ops])
        self.assertEqual(["legacy-2"], ops[0]["remote_page_ids"])
        with (
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
        ):
            report = self.sync.run_reconciliation()
        declined = [f for f in report["findings"]
                    if f["code"] == "LEGACY_CANDIDATE_DECLINED"]
        self.assertEqual(1, len(declined))
        self.assertTrue(declined[0].get("audit_only"))
        self.assertEqual(["legacy-1"], declined[0]["page_ids"])

    # ── reviewer #1 follow-ups ───────────────────────────────

    def _legacy_task_page(self, page_id):
        page = self._task_page(page_id, "L-B", "T001")
        page["parent"]["database_id"] = self.sync.TASKS_DB_ID
        return page

    def test_t015_task_decline_uses_project_uid_and_task_id_key(self):
        self._adopt()
        fake = T014FakeNotion(self.sync, projects=[self._other_project_page("legacy-lb")],
                              tasks=[self._legacy_task_page("legacy-lb-t1")])
        plan = self._plan_for(fake)
        task_ops = [op for op in plan["operations"] if op["entity"] == "task"]
        self.assertEqual(["attach_candidate"], [op["action"] for op in task_ops])
        ids = [op["operation_id"] for op in plan["operations"]
               if op["action"] == "attach_candidate"]
        result, output = self._decline(fake, self._write_plan(plan), plan["plan_id"],
                                       self._decline_file(plan, ids, reason="別PJ"))
        self.assertEqual(0, result, output)
        keys = set(self._declined_meta())
        self.assertIn(self.sync._decline_meta_key("task", (T011_UID_B, "T001")), keys)
        self.assertIn(self.sync._decline_meta_key("project", (T011_UID_B,)), keys)
        self.assertEqual({"別PJ"}, {entry["reason"] for entry in self._declined_meta().values()})
        plan = self._plan_for(fake)
        self.assertEqual({"create_remote"}, {op["action"] for op in plan["operations"]})

    def test_t015_multi_op_decline_rolls_back_when_a_later_op_fails(self):
        self._adopt()
        fake = T014FakeNotion(self.sync, projects=[self._other_project_page("legacy-lb")],
                              tasks=[self._legacy_task_page("legacy-lb-t1")])
        plan = self._plan_for(fake)
        ids = [op["operation_id"] for op in plan["operations"]
               if op["action"] == "attach_candidate"]
        with closing(self._connect()) as conn:  # task linked after the Plan
            conn.execute("UPDATE tasks SET notion_page_id='linked-meanwhile' "
                         "WHERE scope_id='L-B' AND task_id='T001'")
            conn.commit()
        result, output = self._decline(fake, self._write_plan(plan), plan["plan_id"],
                                       self._decline_file(plan, ids))
        self.assertEqual(2, result, output)
        self.assertNotIn("[DECLINE]", output)
        self.assertEqual({}, self._declined_meta())

    def test_t015_attach_plan_from_before_the_decline_is_refused(self):
        self._adopt()
        fake = self._fake(self._other_project_page("legacy-lb"))
        plan, attach = self._attach_plan(fake)
        self.assertEqual(0, self._decline(
            fake, self._write_plan(plan), plan["plan_id"],
            self._decline_file(plan, [attach["operation_id"]]))[0])
        output = io.StringIO()
        with (
            mock.patch.object(self.sync, "run_preflight",
                              return_value={"status": "pass", "schemas": {}}),
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
            contextlib.redirect_stdout(output),
        ):
            result = self.sync.execute_push_plan(plan, scope_id="L-B", authorization={
                "plan_id": plan["plan_id"], "operation_ids": [attach["operation_id"]],
                "approved_by": "t015"})
        self.assertNotEqual(0, result, output.getvalue())
        self.assertEqual([], fake.mutations())
        with closing(self._connect()) as conn:
            self.assertIsNone(conn.execute("SELECT notion_page_id FROM projects "
                                           "WHERE scope_id='L-B'").fetchone()[0])

    def test_t015_workspace_cli_dry_run_reports_collision_with_exit_2(self):
        self._adopt()
        fake = self._fake(self._other_project_page("legacy-1"),
                          self._other_project_page("legacy-2", name="Third"))
        output = io.StringIO()
        with (
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
            contextlib.redirect_stdout(output),
        ):
            result = self.sync.cmd_push(dry_run=True, skip_preflight=True)
        self.assertEqual(2, result, output.getvalue())
        self.assertNotIn("does not match plan_id", output.getvalue())
        self.assertIn("collision=1", output.getvalue())

    def test_t015_declines_list_and_revoke(self):
        self._adopt()
        fake = self._fake(self._other_project_page("legacy-lb"))
        plan, attach = self._attach_plan(fake)
        self.assertEqual(0, self._decline(
            fake, self._write_plan(plan), plan["plan_id"],
            self._decline_file(plan, [attach["operation_id"]], reason="not ours"))[0])
        result, _calls, output = self._main(["declines"])
        self.assertEqual(0, result, output)
        self.assertIn("reason=not ours", output)
        record_id = self.sync._decline_record_id(next(iter(self._declined_meta())))
        self.assertIn(record_id, output)
        for argv in (["declines", "--revoke", record_id],
                     ["declines", "--approved-by", "x"]):
            self.assertEqual(64, self._main(argv)[0], argv)
        result, _calls, output = self._main(
            ["declines", "--revoke", "000000000000", "--approved-by", "x"])
        self.assertEqual(2, result, output)
        result, _calls, output = self._main(
            ["declines", "--revoke", record_id, "--approved-by", "t015"])
        self.assertEqual(0, result, output)
        self.assertEqual({}, self._declined_meta())
        plan, _attach = self._attach_plan(fake)  # offered again after revoke

    def test_t015_malformed_decline_record_blocks_reconciliation_cleanly(self):
        self._adopt()
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO _metadata (key, value) VALUES (?, ?)",
                         (self.sync.DECLINE_META_PREFIX + "not-json", "{}"))
            conn.execute("INSERT INTO _metadata (key, value) VALUES (?, ?)",
                         ("declinedXlegacyXcandidate:x", "ignored"))
            conn.commit()
        fake = self._fake(self._other_project_page("legacy-lb"))
        with (
            mock.patch.object(self.sync, "_query_db", side_effect=fake.query),
            mock.patch.object(self.sync, "_api_call", side_effect=fake.api),
        ):
            report = self.sync.run_reconciliation()
        self.assertEqual(3, report["exit_code"])
        self.assertIn("DECLINE_RECORD_INVALID",
                      [f["code"] for f in report["findings"]])
        result, _calls, output = self._main(["declines"])
        self.assertEqual(3, result, output)
        self.assertIn("DECLINE_RECORD_INVALID", output)

    def test_t015_lookalike_metadata_keys_are_not_decline_records(self):
        self._adopt()
        with closing(self._connect()) as conn:  # "_" must not act as a wildcard
            conn.execute("INSERT INTO _metadata (key, value) VALUES (?, ?)",
                         ("declinedXlegacyXcandidate:x", "not a decline"))
            conn.commit()
            self.assertEqual({}, self.sync._load_declined_candidates(conn))
        result, _calls, output = self._main(["declines"])
        self.assertEqual(0, result, output)
        self.assertIn("Declined legacy candidates: 0", output)

    def test_t015_reason_must_be_a_string(self):
        self._adopt()
        fake = self._fake(self._other_project_page("legacy-lb"))
        plan, attach = self._attach_plan(fake)
        result, output = self._decline(
            fake, self._write_plan(plan), plan["plan_id"],
            self._decline_file(plan, [attach["operation_id"]], reason=5))
        self.assertEqual(2, result, output)
        self.assertEqual({}, self._declined_meta())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
