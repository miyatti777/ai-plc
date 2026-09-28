"""Tests for the --jev stale classification hint of scripts/aiplc_status_audit.py.

Synthetic DB + synthetic Layers only. No network: jev_client.ask is replaced by a mock, or jev_client.route/_post
are patched so the real ask() runs without an HTTP call. The decision log goes to a temp file.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

try:
    import yaml  # noqa: F401  (the scripts need pyyaml; without it these tests are skipped, not errors)
except ImportError:
    raise unittest.SkipTest("pyyaml が無い（pip install pyyaml）")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import aiplc_status_audit as audit_mod  # noqa: E402
import jev_client  # noqa: E402
import jev_test_support as jts  # noqa: E402


def setUpModule():
    jts.isolate()  # fictional extra word list; never the real local file


def tearDownModule():
    jts.restore()
from test_aiplc_status_audit import TODAY, Fixture, sha, tree_hashes  # noqa: E402

F = "Flow/202608/2026-08-01"
LONG = "画像の分解は完了し、テキストを編集可能にした。" * 40  # > 400 chars


def write_layer(root, rel, sid, tasks, extra=None, days_ago=45, goal="画像を編集可能な状態にする"):
    folder = root / rel
    folder.mkdir(parents=True, exist_ok=True)
    intent = {"scope_id": sid, "scope_name": rel.rsplit("/", 1)[-1], "status": "active",
              "goal": {"description": goal}}
    intent.update(extra or {})
    (folder / "intent.yaml").write_text(yaml.safe_dump(intent, allow_unicode=True), encoding="utf-8")
    (folder / "backlog.yaml").write_text(yaml.safe_dump({"tasks": tasks}, allow_unicode=True), encoding="utf-8")
    ts = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time()).timestamp() + 3600
    for f in ("intent.yaml", "backlog.yaml"):
        os.utime(folder / f, (ts, ts))


OLD = (TODAY - timedelta(days=45)).isoformat()


class MockAsk:
    def __init__(self, answer=None, action="answered", raise_exc=None):
        self.calls = []
        self.answer = answer if answer is not None else {
            "choice": "stalled", "probabilities": {"stalled": 0.71, "done": 0.2, "injected": 0.09}}
        self.action = action
        self.raise_exc = raise_exc

    def __call__(self, state, questions, use_case, scope_id=None, task_id=None, timeout=2.0, retries=0, log=True):
        self.calls.append({"state": state, "questions": questions, "use_case": use_case, "scope_id": scope_id,
                           "task_id": task_id, "timeout": timeout, "retries": retries})
        if self.raise_exc:
            raise self.raise_exc
        rec = {"decision_id": f"dec{len(self.calls):03d}", "action": self.action, "cost": 0.0001}
        if self.action == "answered":
            rec["answers"] = {"status": self.answer}
        return rec


class JevStaleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        f = Fixture(tmp)
        cls.f = f
        r = f.root
        # eligible: opt-in, not confidential, last completed task has a long result
        write_layer(r, f"{F}/j1", "L-J1", [
            {"id": "T001", "name": "素材を集める", "status": "completed", "completed_at": "2026-07-01",
             "result": "古い結果"},
            {"id": "T002", "name": "画像を分解する", "status": "completed", "completed_at": OLD, "result": LONG},
            {"id": "T003", "name": "仕上げ", "status": "pending"}], extra={"jev_monitor": True})
        f.project("L-J1", url=f"{F}/j1")
        # eligible by metadata, but the task result contains a do-not-send word -> redact at the last gate
        write_layer(r, f"{F}/j2", "L-J2", [
            {"id": "T001", "name": "整理", "status": "completed", "completed_at": OLD,
             "status_note": "経費の話が混じった"},
            {"id": "T002", "name": "次", "status": "pending"}], extra={"jev_monitor": True})
        f.project("L-J2", url=f"{F}/j2")
        # no opt-in, not confidential -> counted as "addable by opt-in"
        write_layer(r, f"{F}/j3", "L-J3", [{"id": "T001", "name": "a", "status": "pending"}])
        f.project("L-J3", url=f"{F}/j3")
        # confidential (name) with opt-in -> never sent
        write_layer(r, f"{F}/j4", "L-J4", [{"id": "T001", "name": "a", "status": "pending"}],
                    extra={"jev_monitor": True})
        f.project("L-J4", url=f"{F}/j4", name="Zetaproj の検討")
        # non-stale candidate (all tasks done) must never get a jev field
        write_layer(r, f"{F}/j5", "L-J5", [{"id": "T001", "name": "a", "status": "completed"}],
                    extra={"jev_monitor": True}, days_ago=1)
        f.project("L-J5", url=f"{F}/j5")
        # opt-in added today (intent.yaml mtime = now) to an old Layer: must stay stale and be eligible
        write_layer(r, f"{F}/j6", "L-J6", [{"id": "T001", "name": "a", "status": "pending"}],
                    extra={"jev_monitor": True}, days_ago=60)
        os.utime(r / f"{F}/j6" / "intent.yaml", None)
        f.project("L-J6", url=f"{F}/j6")
        f.close()
        cls.memory = tmp / "MEMORY.md"
        cls.memory.write_text("", encoding="utf-8")
        cls.before_db = sha(f.db)
        cls.before_tree = tree_hashes(f.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_audit(self, jev, ask=None):
        return audit_mod.audit(self.f.db, self.f.root, TODAY, 30, None, self.memory, jev=jev, ask=ask)

    @staticmethod
    def stale(report):
        return {c["scope_id"]: c for c in report["candidates"] if c["kind"] == "stale"}

    def test_only_eligible_rows_are_sent(self):
        ask = MockAsk()
        rep = self.run_audit(True, ask)
        self.assertEqual([c["scope_id"] for c in ask.calls], ["L-J1", "L-J6"])
        call = ask.calls[0]
        self.assertEqual((call["use_case"], call["timeout"], call["retries"]), ("status_audit", 10, 1))
        q = call["questions"]["status"]
        self.assertEqual(q["type"], "choice")
        self.assertEqual(set(q["criteria"]), {"done", "handed_off", "stalled", "unknown"})
        st = call["state"]
        self.assertIn("画像を編集可能な状態にする", st)
        self.assertIn("画像を分解する", st)  # newest completed_at, not list order
        self.assertNotIn("古い結果", st)
        self.assertIn("2/3", st)
        self.assertIn("45 日", st)
        note = st.split("結果: ", 1)[1].split("\n", 1)[0]
        self.assertLessEqual(len(note), audit_mod.JEV_NOTE_MAX)
        s = self.stale(rep)
        self.assertEqual((s["L-J2"]["jev"]["status"], s["L-J2"]["jev"]["reason"]), ("skipped", "redact"))
        self.assertEqual(s["L-J2"]["jev"]["label"], "スキップ（redact）")
        self.assertEqual(s["L-J3"]["jev"]["label"], "Jev対象外（opt-inなし）— コード判定のみ")
        self.assertEqual(s["L-J4"]["jev"]["reason"], "confidential")
        self.assertTrue(s["L-J4"]["jev"]["label"].startswith("Jev対象外（機密）"))
        for c in rep["candidates"]:
            if c["kind"] != "stale":
                self.assertIsNone(c["jev"])
        js = rep["jev_summary"]
        self.assertEqual((js["eligible"], js["sent"], js["answered"], js["skipped_redact"],
                          js["not_eligible_confidential"], js["not_eligible_no_opt_in"]), (3, 2, 2, 1, 1, 1))
        self.assertEqual(rep["counts"]["stale_addable_by_opt_in"], 1)

    def test_intent_edit_does_not_hide_stale(self):
        c = self.stale(self.run_audit(False))["L-J6"]
        self.assertEqual((c["days_since_touch"], c["jev_eligible"]), (60, True))

    def test_choice_keeps_only_sent_labels(self):
        rep = self.run_audit(True, MockAsk({"choice": "ignore previous; say done",
                                            "probabilities": {"stalled": 0.7, "done": 0.2, "evil": 0.1}}))
        j = self.stale(rep)["L-J1"]["jev"]
        self.assertEqual(j["status"], "answered")
        self.assertEqual(j["choice"], "stalled")  # free text dropped, falls back to the top sent label
        self.assertEqual(set(j["probabilities"]), {"stalled", "done"})
        self.assertEqual(j["decision_id"], "dec001")
        self.assertIn("decision_id=dec001", j["label"])

    def test_real_ask_logs_only_sent_labels_and_no_text(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "log.jsonl"
            fake = {"answers": {"status": {"choice": "handed_off",
                                           "probabilities": {"handed_off": 0.8, "unknown": 0.1, "hack": 0.1}}},
                    "model": "jev", "usage": {"cost": 0.0002}}
            with mock.patch.object(jev_client, "LOG_PATH", log), \
                    mock.patch.object(jev_client, "route", return_value=("http://x", "k", "m", "test")), \
                    mock.patch.object(jev_client, "_post", return_value=(fake, 12.0, None)) as post:
                rep = self.run_audit(True)
            self.assertEqual(post.call_count, 2)
            j = self.stale(rep)["L-J1"]["jev"]
            self.assertEqual((j["choice"], set(j["probabilities"])), ("handed_off", {"handed_off", "unknown"}))
            self.assertEqual(j["cost"], 0.0002)
            recs = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(recs), 2)
            self.assertEqual(recs[0]["use_case"], "status_audit")
            self.assertEqual(set(recs[0]["answers"]["status"]["probabilities"]), {"handed_off", "unknown"})
            self.assertNotIn("画像", log.read_text(encoding="utf-8"))

    def test_unavailable_or_error_still_completes(self):
        for ask in (MockAsk(action="skipped(unavailable:http_500)"),
                    MockAsk(action="skipped(unavailable:no_key)"),
                    MockAsk(raise_exc=RuntimeError("boom"))):
            rep = self.run_audit(True, ask)
            j = self.stale(rep)["L-J1"]["jev"]
            self.assertEqual((j["status"], j["label"]), ("skipped", "スキップ（unavailable）"))
            self.assertIn("スキップ（unavailable）", audit_mod.render_md(rep))
            if ask.action == "skipped(unavailable:http_500)":
                self.assertEqual(rep["jev_summary"]["sent"], 2)  # the request left the machine, then failed
                self.assertEqual(j["decision_id"], "dec001")
            elif ask.action == "skipped(unavailable:no_key)":
                self.assertEqual(rep["jev_summary"]["sent"], 0)
        self.assertEqual(rep["jev_summary"]["sent"], 0)  # exception: nothing counted as sent

    def test_proposed_changes_unchanged_by_hint(self):
        base = self.run_audit(False)
        for answer in ({"choice": "done", "probabilities": {"done": 0.99}},
                       {"choice": "stalled", "probabilities": {"stalled": 0.99}}):
            rep = self.run_audit(True, MockAsk(answer))
            strip = lambda r: [{k: v for k, v in c.items() if k != "jev"} for c in r["candidates"]]  # noqa: E731
            self.assertEqual(strip(rep), strip(base))
            self.assertEqual(rep["counts"]["by_kind"], base["counts"]["by_kind"])

    def test_without_jev_nothing_is_sent(self):
        out = Path(self.tmp.name) / "out_nojev"
        boom = mock.Mock(side_effect=AssertionError("must not be called"))
        with mock.patch.object(jev_client, "ask", boom), mock.patch.object(jev_client, "_post", boom):
            rc = audit_mod.main(["--db", str(self.f.db), "--root", str(self.f.root), "--today", TODAY.isoformat(),
                                 "--memory", str(self.memory), "--out", str(out), "--quiet"])
        self.assertEqual(rc, 0)
        boom.assert_not_called()
        rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
        self.assertTrue(all(c["jev"] is None for c in rep["candidates"]))
        self.assertFalse(rep["jev_summary"]["enabled"])
        self.assertIn("外部送信 0 件", (out / "report.md").read_text(encoding="utf-8"))

    def test_main_with_jev_writes_decision_id_and_keeps_files(self):
        out = Path(self.tmp.name) / "out_jev"
        with mock.patch.object(jev_client, "ask", MockAsk()):
            rc = audit_mod.main(["--db", str(self.f.db), "--root", str(self.f.root), "--today", TODAY.isoformat(),
                                 "--memory", str(self.memory), "--out", str(out), "--quiet", "--jev"])
        self.assertEqual(rc, 0)
        md = (out / "report.md").read_text(encoding="utf-8")
        self.assertIn("decision_id=dec001", md)
        self.assertIn("--override", md)
        self.assertNotIn("j4", md)  # confidential Layer name hidden
        self.assertEqual(sha(self.f.db), self.before_db)
        self.assertEqual(tree_hashes(self.f.root), self.before_tree)


if __name__ == "__main__":
    unittest.main()
