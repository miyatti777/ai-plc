"""Tests for `aiplc_status_audit.py --apply` / `--approval-template` / masked output.

Temporary copies only: a synthetic DB and synthetic Layers under a temp dir. The production DB is never opened
(checked by recording every sqlite3.connect path). No network.
"""
import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

try:
    import yaml  # noqa: F401  (the scripts need pyyaml; without it these tests are skipped, not errors)
except ImportError:
    raise unittest.SkipTest("pyyaml が無い（pip install pyyaml）")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import aiplc_status_audit as audit_mod  # noqa: E402
import jev_test_support as jts  # noqa: E402


def setUpModule():
    jts.isolate()  # fictional extra word list; never the real local file


def tearDownModule():
    jts.restore()


# --apply resolves the Registry writer at <repo>/.claude/db/plc_query.py. In a checkout of the AI-PLC repository
# (experimental/jev/scripts/tests) it is not installed; walk up and use core/db/plc_query.py instead. Without
# either, these tests are skipped.
if not audit_mod.PLC_QUERY.is_file():
    for _p in Path(__file__).resolve().parents:
        if (_p / "core" / "db" / "plc_query.py").is_file():
            audit_mod.PLC_QUERY = _p / "core" / "db" / "plc_query.py"
            break
needs_plc_query = unittest.skipUnless(audit_mod.PLC_QUERY.is_file(),
                                      "needs <repo>/.claude/db/plc_query.py or core/db/plc_query.py")
from test_aiplc_status_audit import TODAY, Fixture, sha, tree_hashes  # noqa: E402

F = "Flow/202609/2026-09-01"
SECRET_WORDS = ("L-ZET", "zetaproj-secret", "Zetaproj")
INTENT_B = """# 先頭コメント
scope_id: L-B
scope_name: b-all   # 名前
status: active  # ここを書き換える
goal:
  description: テスト用のゴール
extensions: []
# 末尾コメント
"""
BACKLOG_B = """# backlog コメント
tasks:
  - id: T001
    status: completed
  - id: T002
    status: cancelled
summary:
  next_action: x   # 残す
  status: 'active'
  task_count: 2
"""


def run_main(args):
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        rc = audit_mod.main(args)
    return rc, buf.getvalue(), err.getvalue()


class ApplyBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        f = Fixture(t)
        self.f = f
        # 1 kind1 x2 (L-K stays undecided)
        for sid in ("L-A", "L-K"):
            f.layer(f"{F}/{sid.lower()}", sid, "completed", [("T001", "completed")])
            f.project(sid, url=f"{F}/{sid.lower()}")
            f.rtask(sid, "T001", "完了")
        # 2 kind2 with comments / summary.status
        b = f.layer(f"{F}/b-all", "L-B", "active", [("T001", "completed"), ("T002", "cancelled")])
        (b / "intent.yaml").write_text(INTENT_B, encoding="utf-8")
        (b / "backlog.yaml").write_text(BACKLOG_B, encoding="utf-8")
        f.project("L-B", url=f"{F}/b-all")
        f.rtask("L-B", "T001", "完了")
        f.rtask("L-B", "T002", "完了")
        # confidential kind2
        f.layer(f"{F}/zetaproj-secret", "L-ZET", "active", [("T001", "completed")])
        f.project("L-ZET", url=f"{F}/zetaproj-secret", name="Zetaproj 何か")
        f.rtask("L-ZET", "T001", "完了")
        # 3 + 6(all terminal): registry completed, T002 row open; backlog has completed_at
        c = f.layer(f"{F}/c-comp", "L-C", "active")
        (c / "backlog.yaml").write_text(yaml.safe_dump({"tasks": [
            {"id": "T001", "status": "completed"},
            {"id": "T002", "status": "completed", "completed_at": "2026-09-20"}]}), encoding="utf-8")
        f.project("L-C", "completed", url=f"{F}/c-comp")
        f.rtask("L-C", "T001", "完了")
        f.rtask("L-C", "T002", "未着手")
        # 6 (choose) + 7
        f.layer(f"{F}/f-open", "L-F", "active", [("T001", "completed"), ("T002", "pending")])
        f.project("L-F", "completed", url=f"{F}/f-open")
        f.rtask("L-F", "T001", "完了")
        f.rtask("L-F", "T002", "完了")
        # 8 / 9 / duplicate_disagree: out of scope
        f.layer(f"{F}/g-miss", "L-G", "active", [("T001", "completed"), ("T002", "pending")])
        f.project("L-G", url=f"{F}/g-miss")
        f.rtask("L-G", "T001", "完了")
        f.layer(f"{F}/h-unreg", "L-H", "active", [("T001", "pending")])
        f.layer(f"{F}/dup", "L-DUP", "active", [("T001", "completed")])
        f.layer(".ai-plc/projects/L-DUP", "L-DUP", "active", [("T001", "pending")])
        f.project("L-DUP", url="")
        f.rtask("L-DUP", "T001", "完了")
        f.close()
        self.state = t / "state"
        self.base = ["--db", str(f.db), "--root", str(f.root), "--today", TODAY.isoformat(),
                     "--memory", str(t / "none.md"), "--state-dir", str(self.state)]
        self.report = audit_mod.audit(f.db, f.root, TODAY)
        self.by = {(c["scope_id"], c["kind"]): c for c in self.report["candidates"]}
        rc, _, _ = run_main(self.base + ["--quiet", "--approval-template"])
        self.assertEqual(rc, 0)
        self.template_path = self.state / "approvals" / f"approval_template_{TODAY.isoformat()}.json"
        self.template = json.loads(self.template_path.read_text(encoding="utf-8"))

    def tearDown(self):
        self.tmp.cleanup()

    def cid(self, sid, kind):
        return audit_mod.public_candidate_id(self.by[(sid, kind)])

    def approval(self, picks, path_name="appr.json", edit=None):
        """picks: {public candidate_id: alternative or None}; everything else stays undecided."""
        data = json.loads(json.dumps(self.template))
        for e in data["approvals"]:
            if e["candidate_id"] in picks:
                e["decision"] = "approve"
                e["alternative"] = picks[e["candidate_id"]]
                if edit:
                    edit(e)
        p = self.state / "approvals" / path_name
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return p

    def db_rows(self):
        c = sqlite3.connect(self.f.db)
        try:
            return ({r[0]: r[1] for r in c.execute("SELECT scope_id, status FROM projects")},
                    {(r[0], r[1]): (r[2], r[3]) for r in c.execute(
                        "SELECT scope_id, task_id, status, completed_at FROM tasks")})
        finally:
            c.close()

    def apply(self, path, yes=False, extra=()):
        return run_main(self.base + ["--apply", str(path)] + (["--yes"] if yes else []) + list(extra))

    def report_dirs(self):
        base = self.state / "reports" / TODAY.isoformat()
        return sorted(d for d in base.iterdir() if d.is_dir()) if base.is_dir() else []

    def log_lines(self):
        p = self.state / "apply_log.jsonl"
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


class TemplateAndMaskTest(ApplyBase):
    def test_template_rows_and_out_of_scope(self):
        ids = {e["candidate_id"]: e for e in self.template["approvals"]}
        self.assertIn("L-A:intent_done_registry_open", ids)
        self.assertIn("L-B:all_tasks_done_unclosed", ids)
        self.assertTrue(all(e["decision"] == "undecided" for e in ids.values()))
        f6 = ids["L-F:registry_closed_layer_open"]
        self.assertEqual(f6["alternatives_available"], ["layer_close", "registry_reopen"])
        self.assertEqual(set(f6["from"]), {"layer_close", "registry_reopen"})
        self.assertEqual(ids["L-A:intent_done_registry_open"]["from"],
                         [{"target": "registry.projects", "field": "status", "from": "active", "to": "completed"}])
        oos = {e["candidate_id"] for e in self.template["out_of_scope"]}
        for sid, kind in (("L-G", "registry_task_missing"), ("L-H", "registry_missing"),
                          ("L-DUP", "all_tasks_done_unclosed")):
            self.assertIn(f"{sid}:{kind}", oos)
            self.assertNotIn(f"{sid}:{kind}", ids)

    def test_confidential_hashed_in_report_and_template(self):
        pal = self.by[("L-ZET", "all_tasks_done_unclosed")]
        self.assertTrue(pal["confidential"])
        hid = audit_mod.hash_id("L-ZET")
        self.assertRegex(hid, r"^C-[0-9a-f]{8}$")
        self.assertIn(f"{hid}:all_tasks_done_unclosed", {e["candidate_id"] for e in self.template["approvals"]})
        out = self.report_dirs()[0]
        texts = [self.template_path.read_text(encoding="utf-8"), (out / "report.json").read_text(encoding="utf-8"),
                 (out / "report.md").read_text(encoding="utf-8")]
        for t in texts:
            for w in SECRET_WORDS:
                self.assertNotIn(w, t)
            self.assertIn(hid, t)
        pub = json.loads(texts[1])
        row = next(c for c in pub["candidates"] if c["scope_id"] == hid)
        self.assertIsNone(row["layer_path"])
        self.assertEqual(row["candidate_id"], f"{hid}:all_tasks_done_unclosed")
        self.assertTrue(all(ch.get("path", "").startswith(audit_mod.PATH_MASK) or "path" not in ch
                            for ch in row["proposed_changes"]))
        # non-confidential rows keep their plain ids and paths
        b = next(c for c in pub["candidates"] if c["candidate_id"] == "L-B:all_tasks_done_unclosed")
        self.assertEqual(b["layer_path"], f"{F}/b-all")

    def test_default_report_dir_is_state_dir(self):
        dirs = self.report_dirs()
        self.assertEqual(len(dirs), 1)
        self.assertRegex(dirs[0].name, r"^\d{6}$")
        self.assertTrue((dirs[0] / "report.json").is_file())
        self.assertTrue((dirs[0] / "report.md").is_file())

    def test_each_run_gets_a_new_report_dir(self):
        """Default output never overwrites an earlier run on the same date (also within the same second)."""
        first = self.report_dirs()[0]
        before = (first / "report.json").read_bytes(), (first / "report.json").stat().st_mtime_ns
        fixed = datetime(2026, 9, 28, 9, 30, 0)
        orig = audit_mod.default_report_dir
        with mock.patch.object(audit_mod, "default_report_dir",
                               side_effect=lambda state, today, now=None: orig(state, today, fixed)):
            for _ in range(3):
                rc, _, err = run_main(self.base + ["--quiet"])
                self.assertEqual(rc, 0, err)
        names = sorted(d.name for d in self.report_dirs())
        self.assertEqual(len(names), 4)
        self.assertIn("093000", names)
        self.assertIn("093000-2", names)
        self.assertIn("093000-3", names)
        self.assertEqual(((first / "report.json").read_bytes(), (first / "report.json").stat().st_mtime_ns), before)

    def test_explicit_out_is_used_as_is(self):
        out = Path(self.tmp.name) / "explicit"
        rc, _, err = run_main(self.base + ["--quiet", "--out", str(out)])
        self.assertEqual(rc, 0, err)
        self.assertTrue((out / "report.json").is_file())
        self.assertEqual([p.name for p in out.iterdir() if p.is_dir()], [])  # no HHMMSS subdir under --out
        self.assertEqual(len(self.report_dirs()), 1)  # the default dir got nothing new


class DryRunAndApplyTest(ApplyBase):
    def picks(self):
        return {"L-A:intent_done_registry_open": None, "L-B:all_tasks_done_unclosed": None,
                self.cid("L-ZET", "all_tasks_done_unclosed"): None,
                "L-C:completed_project_open_tasks": None, "L-F:registry_closed_layer_open": "layer_close",
                "L-F:task_status_mismatch": None}

    def test_dry_run_writes_nothing(self):
        p = self.approval(self.picks())
        db0, tree0 = sha(self.f.db), tree_hashes(self.f.root)
        rc, out, _ = self.apply(p)
        self.assertEqual(rc, 0)
        self.assertEqual((sha(self.f.db), tree_hashes(self.f.root)), (db0, tree0))
        self.assertFalse((self.state / "apply_log.jsonl").exists())
        self.assertIn("dry-run", out)
        self.assertIn("would_apply 6", out)
        for w in SECRET_WORDS:
            self.assertNotIn(w, out)

    @needs_plc_query
    def test_yes_writes_only_approved_then_rerun_is_noop(self):
        p = self.approval(self.picks())
        rc, out, _ = self.apply(p, yes=True)
        self.assertEqual(rc, 0, out)
        self.assertIn("applied 6", out)
        proj, tasks = self.db_rows()
        self.assertEqual(proj["L-A"], "completed")
        self.assertEqual(proj["L-K"], "active")  # undecided -> untouched
        self.assertEqual(proj["L-B"], "completed")
        self.assertEqual(proj["L-ZET"], "completed")
        self.assertEqual(proj["L-G"], "active")
        self.assertEqual(tasks[("L-C", "T002")], ("完了", "2026-09-20"))  # completed_at from backlog
        self.assertEqual(tasks[("L-F", "T002")], ("未着手", None))
        # intent: only the status line changed, comments and order kept
        b = self.f.root / F / "b-all"
        self.assertEqual((b / "intent.yaml").read_text(encoding="utf-8"),
                         INTENT_B.replace("status: active  # ここを", "status: completed  # ここを"))
        self.assertEqual((b / "backlog.yaml").read_text(encoding="utf-8"),
                         BACKLOG_B.replace("status: 'active'", "status: 'completed'"))
        self.assertEqual(yaml.safe_load((self.f.root / F / "f-open" / "intent.yaml").read_text())["status"],
                         "completed")
        self.assertEqual(yaml.safe_load((self.f.root / F / "l-k" / "intent.yaml").read_text())["status"],
                         "completed")  # untouched (was already completed)
        # log: before/after for each written change, confidential hashed
        log = self.log_lines()
        applied = [x for x in log if x["result"] == "applied"]
        self.assertEqual(len(applied), 9)  # A1 + B3 + ZET2 + C1 + F-intent1 + F-task1
        a = next(x for x in applied if x["candidate_id"] == "L-A:intent_done_registry_open")
        self.assertEqual((a["before"], a["after"]), ("active", "completed"))
        raw = (self.state / "apply_log.jsonl").read_text(encoding="utf-8")
        for w in SECRET_WORDS:
            self.assertNotIn(w, raw)
        self.assertIn(audit_mod.hash_id("L-ZET"), raw)
        # order for one row: intent -> backlog.summary -> registry
        self.assertEqual([x["target"] for x in applied if x["candidate_id"] == "L-B:all_tasks_done_unclosed"],
                         ["intent", "backlog.summary", "registry.projects"])
        # rerun: noop, nothing changes
        db1, tree1 = sha(self.f.db), tree_hashes(self.f.root)
        rc, out, _ = self.apply(p, yes=True)
        self.assertEqual(rc, 0)
        self.assertIn("noop 6", out)
        self.assertEqual((sha(self.f.db), tree_hashes(self.f.root)), (db1, tree1))

    @needs_plc_query
    def test_from_mismatch_is_conflict_and_row_untouched(self):
        def bad(e):
            for ch in e["from"]:
                if ch["target"] == "intent":
                    ch["from"] = "blocked"
        p = self.approval({"L-B:all_tasks_done_unclosed": None}, edit=bad)
        db0, tree0 = sha(self.f.db), tree_hashes(self.f.root)
        rc, out, _ = self.apply(p, yes=True)
        self.assertEqual(rc, 3)  # conflicts are signalled by exit code 3
        self.assertIn("conflict 1", out)
        self.assertEqual((sha(self.f.db), tree_hashes(self.f.root)), (db0, tree0))
        self.assertEqual([x["result"] for x in self.log_lines()], ["conflict"])

    @needs_plc_query
    def test_value_changed_after_report_is_conflict(self):
        p = self.approval({"L-A:intent_done_registry_open": None})
        c = sqlite3.connect(self.f.db)
        c.execute("UPDATE projects SET status='paused' WHERE scope_id='L-A'")
        c.commit()
        c.close()
        rc, out, _ = self.apply(p, yes=True)
        # the audit no longer proposes L-A kind1? (paused is still open) -> proposal from=paused vs approval active
        self.assertIn("conflict 1", out)
        self.assertEqual(self.db_rows()[0]["L-A"], "paused")

    @needs_plc_query
    def test_out_of_scope_rows_never_written(self):
        tpl_oos = [e["candidate_id"] for e in self.template["out_of_scope"]]
        data = json.loads(json.dumps(self.template))
        data["approvals"] = [{"candidate_id": cid, "decision": "approve", "alternative": None,
                              "from": [{"target": "registry.tasks", "field": "status", "from": None, "to": "完了",
                                        "task_id": "T002"}]} for cid in tpl_oos]
        p = self.state / "approvals" / "oos.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        db0, tree0 = sha(self.f.db), tree_hashes(self.f.root)
        rc, out, _ = self.apply(p, yes=True)
        self.assertEqual(rc, 0)
        self.assertIn(f"out_of_scope {len(tpl_oos)}", out)
        self.assertIn("add-task", out)
        self.assertEqual((sha(self.f.db), tree_hashes(self.f.root)), (db0, tree0))

    @needs_plc_query
    def test_choose_row_needs_alternative(self):
        p = self.approval({"L-F:registry_closed_layer_open": None})
        rc, out, _ = self.apply(p, yes=True)
        self.assertIn("invalid 1", out)
        self.assertEqual(self.db_rows()[0]["L-F"], "completed")

    @needs_plc_query
    def test_registry_reopen_alternative(self):
        p = self.approval({"L-F:registry_closed_layer_open": "registry_reopen"})
        rc, out, _ = self.apply(p, yes=True)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.db_rows()[0]["L-F"], "active")
        self.assertEqual(yaml.safe_load((self.f.root / F / "f-open" / "intent.yaml").read_text())["status"], "active")

    @needs_plc_query
    def test_registry_writes_go_through_plc_query_and_blocked_stops_row(self):
        real = audit_mod._plc_query()
        calls = []

        class Wrapped:
            def cmd_sql(self, conn, q):
                calls.append(q)
                return real.cmd_sql(conn, q)

        with mock.patch.object(audit_mod, "_plc_query", lambda: Wrapped()):
            rc, out, _ = self.apply(self.approval({"L-A:intent_done_registry_open": None}), yes=True)
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("UPDATE projects SET status='completed' WHERE scope_id='L-A'"))

        class Blocked:
            def cmd_sql(self, conn, q):
                print("[BLOCKED] GUARD_REJECTED_ROW: x (exit 3; nothing was written)")
                return 3

        with mock.patch.object(audit_mod, "_plc_query", lambda: Blocked()):
            rc, out, _ = self.apply(self.approval({"L-B:all_tasks_done_unclosed": None}, "b.json"), yes=True)
        self.assertEqual(rc, 1)
        self.assertIn("partial", out)
        self.assertEqual(self.db_rows()[0]["L-B"], "active")
        self.assertEqual(self.log_lines()[-1]["result"], "failed")

    @needs_plc_query
    def test_production_db_never_opened(self):
        opened = []
        real_connect = sqlite3.connect

        def rec(path, *a, **k):
            opened.append(str(path))
            return real_connect(path, *a, **k)

        p = self.approval(self.picks())
        with mock.patch("sqlite3.connect", rec):
            self.apply(p)
            self.apply(p, yes=True)
            run_main(self.base + ["--quiet"])
        prod = str(audit_mod.DEFAULT_DB.resolve())
        self.assertTrue(opened)
        self.assertFalse([x for x in opened if prod in urllib_unquote(x)])

    @needs_plc_query
    def test_env_db_and_state_dir(self):
        p = self.approval({"L-A:intent_done_registry_open": None})
        args = ["--root", str(self.f.root), "--today", TODAY.isoformat(), "--apply", str(p), "--yes"]
        with mock.patch.dict(os.environ, {audit_mod.ENV_DB: str(self.f.db), audit_mod.ENV_STATE: str(self.state)}):
            rc, out, _ = run_main(args)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.db_rows()[0]["L-A"], "completed")
        self.assertTrue((self.state / "apply_log.jsonl").is_file())

    @needs_plc_query
    def test_plain_confidential_id_accepted_but_never_echoed(self):
        hid = self.cid("L-ZET", "all_tasks_done_unclosed")
        data = json.loads(json.dumps(self.template))
        e = next(x for x in data["approvals"] if x["candidate_id"] == hid)
        e["candidate_id"], e["decision"] = "L-ZET:all_tasks_done_unclosed", "approve"
        data["approvals"].append({"candidate_id": "L-ZET:stale", "decision": "undecided"})
        p = self.state / "approvals" / "plain.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        rc, out, _ = self.apply(p, yes=True)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.db_rows()[0]["L-ZET"], "completed")
        raw = (self.state / "apply_log.jsonl").read_text(encoding="utf-8")
        for w in SECRET_WORDS:
            self.assertNotIn(w, out)
            self.assertNotIn(w, raw)

    @needs_plc_query
    def test_write_error_text_does_not_leak(self):
        """P1-1: an OSError while writing a confidential Layer must not put its path into output or log."""
        hid = self.cid("L-ZET", "all_tasks_done_unclosed")
        p = self.approval({hid: None})

        def boom(*a, **k):
            raise PermissionError(13, "Permission denied", str(self.f.root / F / "zetaproj-secret" / "intent.yaml"))

        with mock.patch.object(audit_mod, "write_yaml_status", boom):
            rc, out, err = self.apply(p, yes=True)
        self.assertEqual(rc, 1)
        self.assertIn("PermissionError(errno=13)", out)
        raw = (self.state / "apply_log.jsonl").read_text(encoding="utf-8")
        for w in SECRET_WORDS:
            self.assertNotIn(w, out + err + raw)
        self.assertEqual(self.db_rows()[0]["L-ZET"], "active")  # Registry not written after the intent failure

    @needs_plc_query
    def test_reapply_after_manual_revert_is_blocked(self):
        """P2-2: the same approval run again after a human changed the value back does not write again."""
        p = self.approval({"L-A:intent_done_registry_open": None})
        self.assertEqual(self.apply(p, yes=True)[0], 0)
        c = sqlite3.connect(self.f.db)
        c.execute("UPDATE projects SET status='active' WHERE scope_id='L-A'")
        c.commit()
        c.close()
        rc, out, _ = self.apply(p, yes=True)
        self.assertEqual(rc, 3)
        self.assertIn("already applied", out)
        self.assertEqual(self.db_rows()[0]["L-A"], "active")
        rc, out, _ = self.apply(p, yes=True, extra=["--allow-reapply"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.db_rows()[0]["L-A"], "completed")

    @needs_plc_query
    def test_malformed_candidate_id_not_echoed(self):
        data = {"approvals": [{"candidate_id": "L-ZET", "decision": "approve", "from": []},
                              {"candidate_id": "L-ZET:foo:bar", "decision": "approve", "from": []}]}
        p = self.state / "approvals" / "bad.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        rc, out, _ = self.apply(p, yes=True)
        self.assertEqual(rc, 3)
        self.assertIn("invalid 2", out)
        for w in SECRET_WORDS:
            self.assertNotIn(w, out)

    @needs_plc_query
    def test_unknown_id_like_folder_name_not_echoed(self):
        data = {"approvals": [{"candidate_id": "secret-folder-name:stale", "decision": "approve", "from": []}]}
        p = self.state / "approvals" / "unknown.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        rc, out, _ = self.apply(p, yes=True)
        self.assertEqual(rc, 3)
        self.assertNotIn("secret-folder-name", out)
        log = self.state / "apply_log.jsonl"
        if log.exists():
            self.assertNotIn("secret-folder-name", log.read_text(encoding="utf-8"))

    def test_yes_needs_apply(self):
        rc, _, _ = run_main(self.base + ["--yes"])
        self.assertEqual(rc, 2)


def urllib_unquote(s):
    import urllib.parse
    return urllib.parse.unquote(s)


class DuplicateFolderTest(unittest.TestCase):
    """P2-1: copies with the same content -> writing only one would create a disagreement -> out of scope."""

    def test_identical_copies_are_out_of_scope_for_layer_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(Path(tmp))
            f.layer(f"{F}/same", "L-S", "active", [("T001", "completed")])
            f.layer(".ai-plc/projects/L-S", "L-S", "active", [("T001", "completed")])
            f.project("L-S", url=f"{F}/same")
            f.rtask("L-S", "T001", "完了")
            f.close()
            rep = audit_mod.audit(f.db, f.root, TODAY)
            c = next(x for x in rep["candidates"] if x["candidate_id"] == "L-S:all_tasks_done_unclosed")
            self.assertFalse(c["duplicate_disagree"])
            self.assertEqual(audit_mod.scope_state(c)[0], "out_of_scope")
            tpl = audit_mod.approval_template(rep)
            self.assertIn("L-S:all_tasks_done_unclosed", [e["candidate_id"] for e in tpl["out_of_scope"]])


class MaskerTest(unittest.TestCase):
    def test_known_sibling_stays_and_unknown_child_prefix_hidden(self):
        mk = audit_mod.Masker({"_mask": {"scopes": ["L-0000"], "paths": []}, "_scopes": ["L-0000", "L-0000-2"]})
        h = audit_mod.hash_id("L-0000")
        self.assertEqual(mk.text("L-0000 / L-0000-2 / L-0000-SGX"), f"{h} / L-0000-2 / {h}-SGX")

    def test_task_id_under_known_nonconfidential_sibling_stays(self):
        mk = audit_mod.Masker({"_mask": {"scopes": ["L-0000"], "paths": []}, "_scopes": ["L-0000", "L-0000-2"]})
        self.assertEqual(mk.text("L-0000-2-T001"), "L-0000-2-T001")


class YamlEditTest(unittest.TestCase):
    def test_crlf_and_empty_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "intent.yaml"
            p.write_bytes(b"scope_id: X\r\nstatus: active # c\r\nb: 1\r\n")
            audit_mod.write_yaml_status(p, "completed")
            self.assertEqual(p.read_bytes(), b"scope_id: X\r\nstatus: completed # c\r\nb: 1\r\n")
        self.assertEqual(audit_mod.edit_status_line("status:\nx: 1\n", "completed"), "status: completed\nx: 1\n")

    def test_top_level_keeps_comment_and_quotes(self):
        t = 'a: 1\nstatus: "active"   # c\nb:\n  status: x\n'
        self.assertEqual(audit_mod.edit_status_line(t, "completed"), 'a: 1\nstatus: "completed"   # c\nb:\n  status: x\n')

    def test_summary_child_only(self):
        t = "summary:\n  # note\n  status: active\n  nested:\n    status: keep\nstatus: top\n"
        self.assertEqual(audit_mod.edit_status_line(t, "completed", summary=True),
                         "summary:\n  # note\n  status: completed\n  nested:\n    status: keep\nstatus: top\n")

    def test_inline_or_missing_raises(self):
        for t, s in (("summary: {status: active}\n", True), ("x: 1\n", False), ("status: a\nstatus: b\n", False),
                     ("status: |\n  a\n", False)):
            with self.assertRaises(audit_mod.ApplyError):
                audit_mod.edit_status_line(t, "completed", summary=s)


class EnglishRegistryApplyTest(unittest.TestCase):
    """Registry created by AI-PLC's init_db.py: tasks.status is planned/active/completed/paused (CHECK)."""

    @needs_plc_query
    def test_apply_writes_english_values(self):
        from test_aiplc_status_audit import SCHEMA_EN
        with tempfile.TemporaryDirectory() as d:
            t = Path(d)
            f = Fixture.__new__(Fixture)
            f.root = t / "repo"
            f.root.mkdir()
            f.db = t / "ai_plc.db"
            f.conn = sqlite3.connect(f.db)
            f.conn.executescript(SCHEMA_EN)
            c = f.layer(f"{F}/c-comp", "L-C", "active")
            (c / "backlog.yaml").write_text(yaml.safe_dump({"tasks": [
                {"id": "T001", "status": "completed", "completed_at": "2026-09-20"}]}), encoding="utf-8")
            f.project("L-C", "completed", url=f"{F}/c-comp")
            f.rtask("L-C", "T001", "planned")
            f.close()
            state = t / "state"
            base = ["--db", str(f.db), "--root", str(f.root), "--today", TODAY.isoformat(),
                    "--memory", str(t / "none.md"), "--state-dir", str(state)]
            rc, _, _ = run_main(base + ["--quiet", "--approval-template"])
            self.assertEqual(rc, 0)
            tpl_path = state / "approvals" / f"approval_template_{TODAY.isoformat()}.json"
            data = json.loads(tpl_path.read_text(encoding="utf-8"))
            for e in data["approvals"]:
                if e["candidate_id"] == "L-C:completed_project_open_tasks":
                    e["decision"] = "approve"
            p = state / "approvals" / "appr.json"
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            rc, out, _ = run_main(base + ["--apply", str(p), "--yes"])
            self.assertEqual(rc, 0, out)
            conn = sqlite3.connect(f.db)
            try:
                row = conn.execute("SELECT status, completed_at FROM tasks WHERE scope_id='L-C'").fetchone()
            finally:
                conn.close()
            self.assertEqual(tuple(row), ("completed", "2026-09-20"))


if __name__ == "__main__":
    unittest.main()
