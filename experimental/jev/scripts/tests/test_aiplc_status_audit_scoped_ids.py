"""Tests for Registry task ids written with the scope in front ('L-S-T001' for backlog 'T001').

Synthetic DB + synthetic Layers under a temp dir only; the production DB is never opened. No network.
Matching uses the id without the own-scope prefix; proposals and --apply keep the Registry's own task_id.
"""
import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    raise unittest.SkipTest("pyyaml が無い（pip install pyyaml）")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import aiplc_status_audit as audit_mod  # noqa: E402
import jev_test_support as jts  # noqa: E402
from test_aiplc_status_audit import TODAY, Fixture  # noqa: E402
from test_aiplc_status_audit_apply import needs_plc_query  # noqa: E402  (also points PLC_QUERY at core/ in a checkout)

F = "Flow/202609/2026-09-01"


def setUpModule():
    jts.isolate()


def tearDownModule():
    jts.restore()


def run_main(args):
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        rc = audit_mod.main(args)
    return rc, buf.getvalue(), err.getvalue()


def backlog(folder: Path, tasks):
    (folder / "backlog.yaml").write_text(yaml.safe_dump({"tasks": tasks}), encoding="utf-8")


class CanonTaskIdTest(unittest.TestCase):
    def test_only_the_own_scope_prefix_is_dropped(self):
        c = audit_mod.canon_task_id
        self.assertEqual(c("L-S", "L-S-T001"), "T001")
        self.assertEqual(c("L-S", " L-S-T001 "), "T001")
        self.assertEqual(c("L-S", "T001"), "T001")
        self.assertEqual(c("L-S", "L-X-T001"), "L-X-T001")  # another scope's prefix stays
        self.assertEqual(c("L-S", "L-ST001"), "L-ST001")  # no '-' after the scope id
        self.assertEqual(c("L-S", "L-S-"), "L-S-")  # nothing left after the prefix
        self.assertEqual(c("L-S", "T001-L-S"), "T001-L-S")  # suffix form is not touched
        self.assertEqual(c("", "-T001"), "-T001")

    def test_canon_ids_keeps_both_rows_apart(self):
        self.assertEqual(audit_mod.canon_ids("L-S", ["L-S-T001", "T001", "L-S-T002", "L-X-T003"]),
                         {"T001": "T001", "L-S-T001": "L-S-T001", "T002": "L-S-T002", "L-X-T003": "L-X-T003"})


class ScopedIdsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        f = Fixture(t)
        self.f = f
        # mixed forms in one scope: T001 prefixed & agrees, T002 bare & agrees, T003 prefixed & disagrees (class 7)
        s = f.layer(f"{F}/s-mixed", "L-S", "active")
        backlog(s, [{"id": "T001", "status": "completed"}, {"id": "T002", "status": "pending"},
                    {"id": "T003", "status": "completed", "completed_at": "2026-09-15"}])
        f.project("L-S", url=f"{F}/s-mixed")
        f.rtask("L-S", "L-S-T001", "完了")
        f.rtask("L-S", "T002", "未着手")
        f.rtask("L-S", "L-S-T003", "未着手")
        # another scope's prefix is not dropped: T001 stays missing (class 8), the row stays extra
        f.layer(f"{F}/o-other", "L-O", "active", [("T001", "pending")])
        f.project("L-O", url=f"{F}/o-other")
        f.rtask("L-O", "L-X-T001", "未着手")
        # both 'T001' and 'L-D-T001': only the bare row is matched, the prefixed one is never proposed
        f.layer(f"{F}/d-both", "L-D", "active", [("T001", "completed"), ("T002", "pending")])
        f.project("L-D", url=f"{F}/d-both")
        f.rtask("L-D", "T001", "完了")
        f.rtask("L-D", "L-D-T001", "未着手")
        f.rtask("L-D", "T002", "未着手")
        # class 3: completed project, prefixed open row, backlog completed_at
        p = f.layer(f"{F}/p-comp", "L-P", "completed")
        backlog(p, [{"id": "T001", "status": "completed", "completed_at": "2026-09-20"},
                    {"id": "T002", "status": "completed"}])
        f.project("L-P", "completed", url=f"{F}/p-comp")
        f.rtask("L-P", "L-P-T001", "未着手")
        f.rtask("L-P", "L-P-T002", "完了")
        # the backlog itself carries the own-scope prefix: SG1 prefixed on both sides, SG2 not in the Registry,
        # T003 prefixed in the backlog only and disagreeing (class 7 on the bare Registry row)
        f.layer(f"{F}/q-blpre", "L-Q", "active",
                [("L-Q-SG1", "pending"), ("L-Q-SG2", "pending"), ("L-Q-T003", "completed")])
        f.project("L-Q", url=f"{F}/q-blpre")
        f.rtask("L-Q", "L-Q-SG1", "未着手")
        f.rtask("L-Q", "T003", "未着手")
        f.close()
        self.state = t / "state"
        self.base = ["--db", str(f.db), "--root", str(f.root), "--today", TODAY.isoformat(),
                     "--memory", str(t / "none.md"), "--state-dir", str(self.state)]
        self.report = audit_mod.audit(f.db, f.root, TODAY)
        self.by = {(c["scope_id"], c["kind"]): c for c in self.report["candidates"]}

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        c = sqlite3.connect(self.f.db)
        try:
            return sorted(c.execute("SELECT scope_id, task_id, status, completed_at FROM tasks"))
        finally:
            c.close()


class AuditScopedIdsTest(ScopedIdsBase):
    def test_prefixed_rows_match_backlog_ids(self):
        self.assertNotIn(("L-S", "registry_task_missing"), self.by)
        self.assertNotIn(("L-P", "registry_task_missing"), self.by)
        c7 = self.by[("L-S", "task_status_mismatch")]
        self.assertEqual(c7["proposed_changes"], [
            {"target": "registry.tasks", "scope_id": "L-S", "task_id": "L-S-T003", "field": "status",
             "from": "未着手", "to": "完了"}])
        self.assertEqual(set(c7["evidence"]["tasks"]), {"T003"})
        extra = {d["scope_id"]: d["task_ids"] for d in self.report["info"]["backlog_task_missing"]}
        self.assertNotIn("L-S", extra)
        self.assertNotIn("L-P", extra)

    def test_class3_keeps_registry_id(self):
        c3 = self.by[("L-P", "completed_project_open_tasks")]
        self.assertEqual([(x["task_id"], x["from"], x["to"]) for x in c3["proposed_changes"]],
                         [("L-P-T001", "未着手", "完了")])
        self.assertEqual(c3["evidence"]["open_task_rows"], ["L-P-T001"])
        self.assertEqual(c3["evidence"]["backlog_status"], {"L-P-T001": "completed"})
        self.assertNotIn(("L-P", "task_status_mismatch"), self.by)  # one change per Registry row

    def test_other_scope_prefix_is_kept(self):
        c8 = self.by[("L-O", "registry_task_missing")]
        self.assertEqual(c8["evidence"]["missing"], ["T001"])
        # op add keeps the backlog's bare id (the row form is not guessed per Layer)
        self.assertEqual([(x.get("op"), x["task_id"]) for x in c8["proposed_changes"]], [("add", "T001")])
        extra = {d["scope_id"]: d["task_ids"] for d in self.report["info"]["backlog_task_missing"]}
        self.assertEqual(extra["L-O"], ["L-X-T001"])

    def test_backlog_side_prefix(self):
        c8 = self.by[("L-Q", "registry_task_missing")]
        self.assertEqual(c8["evidence"]["missing"], ["L-Q-SG2"])  # SG1 matched on both sides
        self.assertEqual([(x.get("op"), x["task_id"]) for x in c8["proposed_changes"]], [("add", "L-Q-SG2")])
        c7 = self.by[("L-Q", "task_status_mismatch")]
        self.assertEqual([(x["task_id"], x["from"], x["to"]) for x in c7["proposed_changes"]], [("T003", "未着手", "完了")])
        self.assertEqual(set(c7["evidence"]["tasks"]), {"L-Q-T003"})
        extra = {d["scope_id"]: d["task_ids"] for d in self.report["info"]["backlog_task_missing"]}
        self.assertNotIn("L-Q", extra)

    def test_bare_and_prefixed_both_present(self):
        self.assertNotIn(("L-D", "task_status_mismatch"), self.by)  # bare T001 (完了) agrees with the backlog
        self.assertNotIn(("L-D", "registry_task_missing"), self.by)
        extra = {d["scope_id"]: d["task_ids"] for d in self.report["info"]["backlog_task_missing"]}
        self.assertEqual(extra["L-D"], ["L-D-T001"])
        for c in self.report["candidates"]:
            self.assertNotIn("L-D-T001", [x.get("task_id") for x in c["proposed_changes"]])


@needs_plc_query
class ApplyScopedIdsTest(ScopedIdsBase):
    def test_apply_yes_updates_the_prefixed_rows(self):
        rc, _, err = run_main(self.base + ["--quiet", "--approval-template"])
        self.assertEqual(rc, 0, err)
        tpath = self.state / "approvals" / f"approval_template_{TODAY.isoformat()}.json"
        data = json.loads(tpath.read_text(encoding="utf-8"))
        picks = {"L-S:task_status_mismatch", "L-P:completed_project_open_tasks"}
        self.assertTrue(picks <= {e["candidate_id"] for e in data["approvals"]})
        for e in data["approvals"]:
            if e["candidate_id"] in picks:
                e["decision"] = "approve"
        appr = self.state / "approvals" / "appr.json"
        appr.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        before = self.rows()
        rc, out, err = run_main(self.base + ["--apply", str(appr), "--yes"])
        self.assertEqual(rc, 0, out + err)
        after = self.rows()
        self.assertEqual(len(after), len(before))  # no duplicate row
        changed = sorted(set(after) - set(before))
        self.assertEqual(changed, [("L-P", "L-P-T001", "完了", "2026-09-20"),
                                   ("L-S", "L-S-T003", "完了", "2026-09-15")])
        self.assertEqual(sorted(set(before) - set(after)), [("L-P", "L-P-T001", "未着手", None),
                                                            ("L-S", "L-S-T003", "未着手", None)])
        ids = [(s, t) for s, t, _, _ in after]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn(("L-S", "T003"), ids)
        self.assertNotIn(("L-P", "T001"), ids)
        # re-scan: nothing left for those rows
        rep = audit_mod.audit(self.f.db, self.f.root, TODAY)
        kinds = {(c["scope_id"], c["kind"]) for c in rep["candidates"]}
        self.assertNotIn(("L-S", "task_status_mismatch"), kinds)
        self.assertNotIn(("L-P", "completed_project_open_tasks"), kinds)

    def test_completed_at_lookup_uses_the_matched_id(self):
        tgt = audit_mod.Target(self.f.db, self.f.root, self.report["_layers"], TODAY, write=False)
        try:
            self.assertEqual(tgt._task_completed_at("L-P", "L-P-T001"), "2026-09-20")
            self.assertEqual(tgt._task_completed_at("L-P", "T001"), "2026-09-20")
            self.assertEqual(tgt._task_completed_at("L-P", "L-X-T001"), TODAY.isoformat())  # other scope: no match
        finally:
            tgt.close()


if __name__ == "__main__":
    unittest.main()
