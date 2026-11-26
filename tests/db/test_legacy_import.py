"""Import Notion-only legacy Projects through a human triage file.

Local tasks are frozen, so Notion-only Task rows are
never listed or imported (only Projects).

API-free and production-free: the adopt-existing fixture in a temporary
directory, an in-memory fake Notion (``urlopen`` replaced by AssertionError),
and the production ``ai_plc.db`` fingerprint asserted unchanged on cleanup.
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
    from . import test_remote_backfill as t014_tests
except ImportError:  # pragma: no cover - exercised by discovery invocation.
    import test_sync_identity as identity_tests
    import test_remote_backfill as t014_tests

T014FakeNotion = t014_tests.T014FakeNotion
T011_UID_A = identity_tests.T011_UID_A
LEGACY_EDIT = "2026-08-01T00:00:00.000Z"


class T017LegacyImportTest(identity_tests.IdentityV2AdoptExistingTest):
    """Reuses the adopt-existing fixture; its inherited tests are not re-run."""

    def run(self, result=None):  # keep inherited adopt-existing tests out of this class
        if not self._testMethodName.startswith("test_t017_"):
            return result
        return super().run(result)

    # ── fixture ──────────────────────────────────────────────

    def _legacy_project(self, page_id, scope, name, system="AI-PLC"):
        page = self._project_page(page_id, scope, name=name, edited=LEGACY_EDIT)
        page["parent"]["database_id"] = self.sync.PROJECTS_DB_ID
        page["properties"]["システム"] = {"select": {"name": system}}
        return page

    def _legacy_task(self, page_id, scope, task_id):
        page = self._task_page(page_id, scope, task_id)
        page["parent"]["database_id"] = self.sync.TASKS_DB_ID
        page["last_edited_time"] = LEGACY_EDIT
        return page

    def _remote(self):
        # Pages already linked to local rows (with Identity), as after migrate-identity.
        base = self._backfilled_remote()
        for entity, pages in base.pages.items():
            for page in pages:
                page["parent"]["database_id"] = (
                    self.sync.PROJECTS_DB_ID if entity == "project" else self.sync.TASKS_DB_ID)
        projects = base.pages["project"] + [
            self._legacy_project("lg-n1", "L-N1", "New from Notion"),  # clean
            self._legacy_project("lg-a", "L-A", "Other L-A"),          # LOCAL_SCOPE_EXISTS
            self._legacy_project("lg-d1", "L-D", "Dup one"),           # NOTION_DUPLICATE
            self._legacy_project("lg-d2", "L-D", "Dup two"),           # NOTION_DUPLICATE
            self._legacy_project("lg-p", "L-P", "Other only", system="Other"),
        ]
        tasks = base.pages["task"] + [                                  # never candidates
            self._legacy_task("lg-n1-t1", "L-N1", "T001"),
            self._legacy_task("lg-b-t9", "L-B", "T009"),
        ]
        return T014FakeNotion(self.sync, projects=projects, tasks=tasks)

    def _patched(self, fake):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(self.sync, "_query_db", side_effect=fake.query))
        stack.enter_context(mock.patch.object(self.sync, "_api_call", side_effect=fake.api))
        return stack

    def _legacy_dry_run(self, fake):
        path = self.root / "triage.json"
        with self._patched(fake):
            result, _calls, output = self._main(
                ["import-legacy", "--dry-run", "--out", str(path)])
        self.assertEqual(0, result, output)
        return json.loads(path.read_text(encoding="utf-8"))

    def _legacy_apply(self, fake, triage):
        path = self.root / "triage-filled.json"
        path.write_text(json.dumps(triage, ensure_ascii=False), encoding="utf-8")
        with self._patched(fake):
            return self._main(["import-legacy", "--apply", str(path)])

    @staticmethod
    def _decide(template, decisions, approved_by="t017"):
        triage = copy.deepcopy(template)
        triage["approved_by"] = approved_by
        for item in triage["items"]:
            item["decision"] = decisions.get(item["page_id"], "skip")
        return triage

    def _good_decisions(self):
        return {"lg-n1": "import", "lg-d1": "import", "lg-p": "exclude"}

    # ── Dry-run lists candidates with collisions, writes nothing ─────

    def test_t017_ac1_dry_run_lists_candidates_and_collisions(self):
        self._adopt()
        fake = self._remote()
        before = self._snapshot()
        template = self._legacy_dry_run(fake)
        self.assertEqual(before, self._snapshot())
        self.assertEqual([], fake.mutations())
        by_page = {item["page_id"]: item for item in template["items"]}
        self.assertNotIn("page-pa", by_page)
        self.assertEqual({"lg-n1", "lg-a", "lg-d1", "lg-d2", "lg-p"}, set(by_page))
        self.assertEqual({"project"}, {item["entity"] for item in template["items"]})
        self.assertEqual([], by_page["lg-n1"]["collisions"])
        self.assertEqual(["LOCAL_SCOPE_EXISTS"], by_page["lg-a"]["collisions"])
        self.assertEqual(["NOTION_DUPLICATE"], by_page["lg-d1"]["collisions"])
        self.assertEqual(["VALUE_UNSUPPORTED"], by_page["lg-p"]["collisions"])
        self.assertTrue(all(item["decision"] is None for item in template["items"]))
        self.assertIsNone(template["approved_by"])

    # ── Import links rows with Identity; backfill + rerun are clean ───

    def test_t017_ac3_import_then_backfill_is_clean(self):
        self._adopt()
        ticks = iter("2026-10-01T00:%02d:00Z" % n for n in range(60))
        self.sync._now_iso = lambda: next(ticks)  # a moving clock, as in real runs
        fake = self._remote()
        template = self._legacy_dry_run(fake)
        result, _calls, output = self._legacy_apply(fake, self._decide(template, self._good_decisions()))
        self.assertEqual(0, result, output)
        self.assertIn('"imported": 2', output)
        self.assertEqual([], fake.mutations())  # apply itself never writes Notion
        with closing(self._connect()) as conn:
            project = dict(conn.execute("SELECT * FROM projects WHERE scope_id='L-N1'").fetchone())
            imported_tasks = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE notion_page_id LIKE 'lg-%'").fetchone()[0]
        self.assertEqual("lg-n1", project["notion_page_id"])
        self.assertTrue(project["sync_uid"].startswith("prj_"))
        self.assertEqual((1, 2), (project["ownership_epoch"], project["identity_version"]))
        self.assertEqual(0, imported_tasks)  # Notion-only tasks are never imported
        self.assertFalse(self.sync._instant_gt(project["updated_at"], project["last_sync_at"]))
        # Identity is written back to Notion by the existing backfill path.
        result, _calls, output = self._main([
            "backfill-remote-identity", "--dry-run", "--plan-out", str(self.root / "bf.json")])
        self.assertEqual(0, result, output)
        plan = json.loads((self.root / "bf.json").read_text(encoding="utf-8"))
        imported = {"lg-n1", "lg-d1"}
        self.assertTrue(imported <= {op["page_id"] for op in plan["operations"]})
        with self._patched(fake):
            result, _calls, output = self._main([
                "backfill-remote-identity", "--plan", str(self.root / "bf.json"),
                "--plan-id", plan["plan_id"]])
        self.assertEqual(0, result, output)
        self.assertEqual(imported, {pid for pid, _ in fake.patch_bodies})
        # After backfill nothing is left to push for the imported rows.
        with self._patched(fake):
            push = self.sync.build_push_plan(skip_preflight=True)
        self.assertFalse({"L-N1", "L-D"} & {op["display_scope_id"] for op in push["operations"]})

    def test_t017_ac3_reapplying_the_same_file_is_a_noop(self):
        self._adopt()
        fake = self._remote()
        triage = self._decide(self._legacy_dry_run(fake), self._good_decisions())
        self.assertEqual(0, self._legacy_apply(fake, triage)[0])
        before = self._snapshot()
        result, _calls, output = self._legacy_apply(fake, triage)
        self.assertEqual(0, result, output)
        self.assertIn("NOOP", output)
        self.assertEqual(before, self._snapshot())

    # ── Strict file, collisions and missing parents stop ─────

    def test_t017_ac2_invalid_triage_files_stop_before_writing(self):
        self._adopt()
        fake = self._remote()
        template = self._legacy_dry_run(fake)
        good = self._decide(template, self._good_decisions())
        cases = []
        no_approver = copy.deepcopy(good); no_approver["approved_by"] = " "
        cases.append((no_approver, "LEGACY_TRIAGE_APPROVER_REQUIRED"))
        missing = copy.deepcopy(good); missing["items"][0]["decision"] = None
        cases.append((missing, "LEGACY_TRIAGE_DECISION_INVALID"))
        dropped = copy.deepcopy(good); dropped["items"] = dropped["items"][1:]
        cases.append((dropped, "LEGACY_SOURCE_CHANGED"))
        unknown = copy.deepcopy(good)
        unknown["items"].append(dict(unknown["items"][0], page_id="lg-unknown"))
        cases.append((unknown, "LEGACY_SOURCE_CHANGED"))
        tampered = copy.deepcopy(good); tampered["items"][0]["scope_id"] = "L-X"
        cases.append((tampered, "LEGACY_TRIAGE_DECISION_INVALID"))
        wrong_version = copy.deepcopy(good); wrong_version["legacy_import_version"] = 9
        cases.append((wrong_version, "LEGACY_TRIAGE_INVALID"))
        before = self._snapshot()
        for triage, code in cases:
            result, _calls, output = self._legacy_apply(fake, triage)
            self.assertEqual(2, result, (code, output))
            self.assertIn(code, output)
            self.assertEqual(before, self._snapshot())

    def test_t017_ac2_remote_change_after_dry_run_is_refused(self):
        self._adopt()
        fake = self._remote()
        triage = self._decide(self._legacy_dry_run(fake), self._good_decisions())
        fake.pages["project"].append(self._legacy_project("lg-new", "L-NEW", "Added later"))
        before = self._snapshot()
        result, _calls, output = self._legacy_apply(fake, triage)
        self.assertEqual(2, result, output)
        self.assertIn("LEGACY_SOURCE_CHANGED", output)
        self.assertEqual(before, self._snapshot())

    def test_t017_ac2_edit_of_a_candidate_after_dry_run_is_refused(self):
        self._adopt()
        fake = self._remote()
        triage = self._decide(self._legacy_dry_run(fake), self._good_decisions())
        fake._find("lg-n1")["last_edited_time"] = "2026-10-01T09:00:00.000Z"
        before = self._snapshot()
        result, _calls, output = self._legacy_apply(fake, triage)
        self.assertEqual(2, result, output)
        self.assertIn("LEGACY_SOURCE_CHANGED", output)
        self.assertEqual(before, self._snapshot())

    def test_t017_ac1_pages_with_identity_are_never_candidates(self):
        self._adopt()
        fake = self._remote()
        page = self._project_page("v2-unlinked", "L-V2", "prj_00000000-0000-4000-8000-0000000000aa")
        page["parent"]["database_id"] = self.sync.PROJECTS_DB_ID
        fake.pages["project"].append(page)
        template = self._legacy_dry_run(fake)
        self.assertNotIn("v2-unlinked", {item["page_id"] for item in template["items"]})

    def test_t017_ac3_collisions_and_missing_parent_are_never_imported(self):
        self._adopt()
        fake = self._remote()
        template = self._legacy_dry_run(fake)
        before = self._snapshot()
        for extra, code in (({"lg-a": "import"}, "LEGACY_IMPORT_COLLISION"),
                            ({"lg-p": "import"}, "LEGACY_IMPORT_COLLISION"),
                            ({"lg-d2": "import"}, "LEGACY_IMPORT_COLLISION")):
            decisions = dict(self._good_decisions(), **extra)
            result, _calls, output = self._legacy_apply(fake, self._decide(template, decisions))
            self.assertEqual(2, result, (extra, output))
            self.assertIn(code, output)
            self.assertEqual(before, self._snapshot())  # all-or-nothing

    # ── Skip / exclude disappear from later lists and reconciliation ──

    def test_t017_ac4_skipped_and_excluded_pages_do_not_come_back(self):
        self._adopt()
        fake = self._remote()
        self.assertEqual(0, self._legacy_apply(
            fake, self._decide(self._legacy_dry_run(fake), self._good_decisions()))[0])
        template = self._legacy_dry_run(fake)
        self.assertEqual([], template["items"])
        with self._patched(fake):
            report = self.sync.run_reconciliation()
        text = json.dumps(report)
        for page in ("lg-a", "lg-d2", "lg-p"):
            self.assertNotIn(page, text)
        result, _calls, output = self._main(["exclude", "--list"])
        self.assertIn("L-P approved_by=t017", output)
        result, output = self._pull(fake)
        self.assertEqual(0, result, output)
        self.assertEqual([], fake.mutations())

    # ── follow-up cases ────────────────────────────────

    def test_t017_exclude_decision_clears_local_links_like_exclude(self):
        self._adopt()
        fake = self._remote()
        decisions = dict(self._good_decisions(), **{"lg-a": "exclude"})
        result, _calls, output = self._legacy_apply(
            fake, self._decide(self._legacy_dry_run(fake), decisions))
        self.assertEqual(0, result, output)
        with closing(self._connect()) as conn:
            self.assertIsNone(conn.execute(
                "SELECT notion_page_id FROM projects WHERE scope_id='L-A'").fetchone()[0])
            record = json.loads(conn.execute(
                "SELECT value FROM _metadata WHERE key='sync_excluded_scope:L-A'").fetchone()[0])
        self.assertEqual(1, record["cleared_links"]["projects"])

    def test_t017_import_and_exclude_of_one_scope_is_a_conflict(self):
        self._adopt()
        fake = self._remote()
        decisions = dict(self._good_decisions(), **{"lg-d2": "exclude"})
        before = self._snapshot()
        result, _calls, output = self._legacy_apply(
            fake, self._decide(self._legacy_dry_run(fake), decisions))
        self.assertEqual(2, result, output)
        self.assertIn("LEGACY_TRIAGE_CONFLICT", output)
        self.assertEqual(before, self._snapshot())

    def test_t017_skip_that_would_decline_an_unlinked_local_project_is_refused(self):
        self._adopt()
        fake = self._remote()
        fake.pages["project"].append(self._legacy_project("lg-b", "L-B", "Other L-B"))
        before = self._snapshot()
        result, _calls, output = self._legacy_apply(
            fake, self._decide(self._legacy_dry_run(fake), self._good_decisions()))
        self.assertEqual(2, result, output)
        self.assertIn("LEGACY_SKIP_NEEDS_DECLINE", output)
        self.assertEqual(before, self._snapshot())

    def test_t017_skip_is_refused_when_the_local_link_is_stale(self):
        self._adopt()
        fake = self._remote()
        # The local L-A project still points at page-pa, which is gone (trashed).
        fake.pages["project"] = [p for p in fake.pages["project"] if p["id"] != "page-pa"]
        before = self._snapshot()
        result, _calls, output = self._legacy_apply(
            fake, self._decide(self._legacy_dry_run(fake), self._good_decisions()))
        self.assertEqual(2, result, output)
        self.assertIn("LEGACY_SKIP_NEEDS_DECLINE", output)
        self.assertEqual(before, self._snapshot())

    def test_t017_unrelated_file_with_no_candidates_is_not_a_noop(self):
        self._adopt()
        fake = self._remote()
        triage = self._decide(self._legacy_dry_run(fake), self._good_decisions())
        fake.pages["project"] = [p for p in fake.pages["project"] if not p["id"].startswith("lg-")]
        result, _calls, output = self._legacy_apply(fake, triage)
        self.assertEqual(2, result, output)
        self.assertIn("LEGACY_SOURCE_CHANGED", output)

    def test_t017_import_legacy_never_queries_the_tasks_db(self):
        self._adopt()
        fake = self._remote()
        self._legacy_dry_run(fake)
        self.assertNotIn(("QUERY", self.sync.TASKS_DB_ID), fake.calls)

    def test_t017_cli_is_strict(self):
        for argv in (["import-legacy"], ["import-legacy", "--dry-run"],
                     ["import-legacy", "--dry-run", "--apply", "x"],
                     ["import-legacy", "--apply", "x", "--out", "y"]):
            result, _calls, _output = self._main(argv)
            self.assertEqual(64, result, argv)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
