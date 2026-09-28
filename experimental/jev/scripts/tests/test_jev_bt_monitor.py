"""Offline tests for scripts/jev_bt_monitor.py."""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import yaml  # noqa: F401  (the scripts need pyyaml; without it these tests are skipped, not errors)
except ImportError:
    raise unittest.SkipTest("pyyaml が無い（pip install pyyaml）")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jev_test_support as jts  # noqa: E402


def tearDownModule():
    jts.restore()


def mk_layer(root, tasks, opt_in):
    root = Path(root)
    intent = {"scope_id": "L-TEST", "goal": {"description": "テスト用のゴール"}}
    if opt_in:
        intent["jev_monitor"] = True
    (root / "intent.yaml").write_text(yaml.safe_dump(intent, allow_unicode=True), encoding="utf-8")
    (root / "backlog.yaml").write_text(yaml.safe_dump({"tasks": tasks}, allow_unicode=True), encoding="utf-8")
    return root


def t(i, status="pending", origin="inception", result=None):
    return {"id": i, "status": status, "origin": origin, "result": result, "description": f"desc {i}"}


class MonitorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["JEV_LOG_PATH"] = str(Path(self.tmp.name) / "log.jsonl")
        os.environ["JEV_OVERRIDE_PATH"] = str(Path(self.tmp.name) / "ov.jsonl")
        os.environ["JEV_COUNTS_STATE_PATH"] = str(Path(self.tmp.name) / "counts_state.json")
        import jev_client
        import jev_bt_monitor
        importlib.reload(jev_client)
        self.m = importlib.reload(jev_bt_monitor)
        jts.isolate()  # a reload rebuilds the default word list
        self.jc = self.m.jev_client

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts(self):
        st, trig = self.m.counts({"tasks": [t("T1", "completed"), t("T2", "completed"), t("T3"), t("T4", origin="ad-hoc"),
                                            t("T5", origin="re-inception"), t("T6", "cancelled")]})
        self.assertEqual((st["total"], st["done"], st["adhoc"]), (5, 2, 2))
        self.assertEqual(trig, ["BT-B: ad-hoc 2件"])
        st, trig = self.m.counts({"tasks": [t("T1", "completed"), t("T2")]})
        self.assertEqual(trig, ["BT-B: 完了率50%到達"])
        st, trig = self.m.counts({"tasks": [t("T1", "completed"), t("T2", "completed")]})
        self.assertEqual(trig, ["BT-C: 全タスク完了 → GAP分析"])
        self.assertEqual(self.m.counts({"tasks": []})[1], [])

    def test_real_origin_values(self):
        planned = ["inception", "inception_2026-07-29（Goal分解）", "Inception", "user_goal", None, "decomposition",
                   "goal_decomposition", "Stage 2 Inception", "L-0000-CMP / inception", "Inception分解 (L-0000-2)",
                   "Stage1 collection (C採択)", "t05_pilot_run1"]
        added = ["re_inception_2026-08-06（BT-A）", "re-inception (T004 Mob CP, 2026-09-24)", "ad-hoc", "adhoc",
                 "re-inception-v6", "reinception_20260914_beta", "Re-Inception: Internal Publication Goal",
                 "backtrack", "re_collection_goal_expansion", "BT-B drift"]
        for o in planned:
            self.assertFalse(self.m.is_adhoc({"origin": o}), o)
        for o in added:
            self.assertTrue(self.m.is_adhoc({"origin": o}), o)

    def test_malformed_backlog_is_safe(self):
        layer = Path(self.tmp.name)
        (layer / "intent.yaml").write_text("- a list, not a dict\n", encoding="utf-8")
        (layer / "backlog.yaml").write_text("tasks: [1, 'x', {id: T1, status: completed}]\n", encoding="utf-8")
        out, rec = self.m.monitor(layer, "6b", ask=mock.Mock())
        self.assertIsNone(rec)
        self.assertIn("BT-C", out[0])

    def test_6b_counting_shows_only_new_conditions(self):
        root = Path(self.tmp.name) / "L"; root.mkdir()
        tasks = [t("T1", "completed"), t("T2", "completed"), t("T3"), t("T4", origin="re-inception"), t("T5", origin="ad-hoc")]
        mk_layer(root, tasks, opt_in=False)
        first, _ = self.m.monitor(root, "6b", ask=mock.Mock())
        self.assertIn("ad-hoc 2件", first[0])
        again, _ = self.m.monitor(root, "6b", ask=mock.Mock())
        self.assertFalse(any("数え上げ" in l for l in again))  # same state -> no re-show
        tasks[2]["status"] = "completed"  # 3/5 -> 50% newly reached
        mk_layer(root, tasks, opt_in=False)
        third, _ = self.m.monitor(root, "6b", ask=mock.Mock())
        self.assertIn("完了率50%", third[0]); self.assertNotIn("ad-hoc", third[0])
        tasks.append(t("T6", origin="backtrack"))  # ad-hoc grows 2 -> 3
        mk_layer(root, tasks, opt_in=False)
        fourth, _ = self.m.monitor(root, "6b", ask=mock.Mock())
        self.assertIn("ad-hoc 3件", fourth[0]); self.assertNotIn("50%", fourth[0])
        for x in tasks: x["status"] = "completed"
        mk_layer(root, tasks, opt_in=False)
        fifth, _ = self.m.monitor(root, "6b", ask=mock.Mock())
        self.assertIn("BT-C", fifth[0])
        tasks.append(t("T7"))  # reopened -> all_done forgotten; later all done again with new total re-fires
        mk_layer(root, tasks, opt_in=False); self.m.monitor(root, "6b", ask=mock.Mock())
        tasks[-1]["status"] = "completed"; mk_layer(root, tasks, opt_in=False)
        sixth, _ = self.m.monitor(root, "6b", ask=mock.Mock())
        self.assertIn("BT-C", sixth[0])
        raw = Path(os.environ["JEV_COUNTS_STATE_PATH"]).read_text(encoding="utf-8")
        self.assertNotIn("desc", raw)  # counts and keys only

    def test_6b_state_is_per_layer_and_survives_corruption(self):
        a = Path(self.tmp.name) / "A"; b = Path(self.tmp.name) / "B"; a.mkdir(); b.mkdir()
        for root, sid in ((a, "L-A"), (b, "L-B")):
            mk_layer(root, [t("T1", "completed"), t("T2")], opt_in=False)
            y = yaml.safe_load((root / "intent.yaml").read_text()); y["scope_id"] = sid
            (root / "intent.yaml").write_text(yaml.safe_dump(y, allow_unicode=True))
        self.assertIn("50%", self.m.monitor(a, "6b", ask=mock.Mock())[0][0])
        self.assertIn("50%", self.m.monitor(b, "6b", ask=mock.Mock())[0][0])  # other Layer unaffected
        Path(os.environ["JEV_COUNTS_STATE_PATH"]).write_text("{broken", encoding="utf-8")
        out, _ = self.m.monitor(a, "6b", ask=mock.Mock())
        self.assertIn("50%", out[0])  # corrupted state -> treated as first run
        self.assertEqual(self.m.main(["--layer", str(a), "--phase", "6b"]), 0)

    def test_6b_state_keeps_all_layers_under_concurrent_updates(self):
        import threading
        roots = []
        for i in range(8):
            r = Path(self.tmp.name) / f"C{i}"; r.mkdir(); mk_layer(r, [t("T1", "completed"), t("T2")], opt_in=False); roots.append(r)
        ths = [threading.Thread(target=self.m.monitor, args=(r, "6b"), kwargs={"ask": mock.Mock()}) for r in roots]
        [x.start() for x in ths]; [x.join() for x in ths]
        state = json.loads(Path(os.environ["JEV_COUNTS_STATE_PATH"]).read_text(encoding="utf-8"))
        self.assertEqual(len(state), 8)  # no lost update
        for r in roots:
            out, _ = self.m.monitor(r, "6b", ask=mock.Mock())
            self.assertFalse(any("数え上げ" in l for l in out))

    def test_6b_same_scope_id_in_two_dirs_is_separate(self):
        a = Path(self.tmp.name) / "X1"; b = Path(self.tmp.name) / "X2"; a.mkdir(); b.mkdir()
        for r in (a, b):
            mk_layer(r, [t("T1", "completed"), t("T2")], opt_in=False)  # both scope_id L-TEST
        self.assertIn("50%", self.m.monitor(a, "6b", ask=mock.Mock())[0][0])
        self.assertIn("50%", self.m.monitor(b, "6b", ask=mock.Mock())[0][0])

    def test_opt_out_never_asks(self):
        layer = mk_layer(self.tmp.name, [t("T1", "completed", result="r"), t("T2")], opt_in=False)
        ask = mock.Mock()
        out, rec = self.m.monitor(layer, "6b", ask=ask)
        ask.assert_not_called()
        self.assertIsNone(rec)
        self.assertIn("無効", out[-1])
        self.assertIn("完了率50%", out[0])  # counting still works without sending anything

    def test_hint_above_threshold(self):
        layer = mk_layer(self.tmp.name, [t("T1", "completed", result="外部APIの形式が設計と違う"), t("T2")], opt_in=True)
        fake = {"decision_id": "d1", "action": "answered", "answers": {"blocker": 0.83}}
        ask = mock.Mock(return_value=fake)
        out, _ = self.m.monitor(layer, "5.5b", task="T1", ask=ask)
        state, qs = ask.call_args[0][0], ask.call_args[0][1]
        self.assertEqual(list(qs), ["blocker"])
        self.assertIn("外部APIの形式が設計と違う", state)
        self.assertIn("進捗: 1/2完了", state)
        self.assertTrue(out[-1].startswith("💡"))
        self.assertIn("decision_id=d1", out[-1])

    def test_below_threshold_and_skip(self):
        self.assertIn("異常なし", self.m.hint_line({"action": "answered", "answers": {"drift": 0.2}, "decision_id": "x"}, "drift"))
        self.assertIn("スキップ", self.m.hint_line({"action": "skipped(unavailable:http_529)"}, "drift"))

    def test_main_always_exit0(self):
        self.assertEqual(self.m.main(["--layer", "/nonexistent", "--phase", "6b"]), 0)
        self.assertEqual(self.m.main(["--phase", "bogus"]), 0)

    def test_noise_report(self):
        with open(os.environ["JEV_LOG_PATH"], "w") as f:
            for i, p in enumerate([0.9, 0.7, 0.2, 0.8]):
                f.write(json.dumps({"decision_id": f"d{i}", "use_case": "bt_monitor", "action": "answered",
                                    "answers": {"drift": p}}) + "\n")
        self.jc.record_override("d0", "accept")
        self.jc.record_override("d1", "reject")
        self.jc.record_override("d2", "accept")  # a "no anomaly" judgment confirmed right
        r = self.m.noise_report()
        self.assertIn("総数 4件", r)
        self.assertIn("人が確認 3件", r)
        self.assertIn("外れ 1件", r)
        self.assertIn("出した 3件", r)
        self.assertIn("人が判定 2件", r)
        self.assertIn("却下率 50.0%", r)

    def write_status_audit_log(self):
        rows = [("s0", {"choice": "stalled", "probabilities": {"stalled": 0.99, "done": 0.01}}),
                ("s1", {"choice": "done", "probabilities": {"done": 0.8, "stalled": 0.2}}),
                ("s2", {"choice": "handed_off", "probabilities": {"handed_off": 0.7}}),
                ("s3", {"choice": "unknown", "probabilities": {"unknown": 0.6}}),
                ("s4", {"probabilities": {"done": 0.9, "stalled": 0.1}})]  # choice missing -> most probable
        with open(os.environ["JEV_LOG_PATH"], "w") as f:
            for did, ans in rows:
                f.write(json.dumps({"decision_id": did, "use_case": "status_audit", "action": "answered",
                                    "answers": {"status": ans}}) + "\n")
            # other use cases and non-answered rows are not counted
            f.write(json.dumps({"decision_id": "b0", "use_case": "bt_monitor", "action": "answered",
                                "answers": {"drift": 0.9}}) + "\n")
            f.write(json.dumps({"decision_id": "s9", "use_case": "status_audit",
                                "action": "skipped(unavailable:http_500)"}) + "\n")

    def test_noise_report_status_audit(self):
        self.write_status_audit_log()
        self.jc.record_override("s0", "accept")
        self.jc.record_override("s1", "reject")
        self.jc.record_override("s2", "accept")
        r = self.m.noise_report("status_audit")
        self.assertIn("Jev監視の判定（status_audit）", r)
        self.assertIn("総数 5件", r)
        self.assertIn("人が確認 3件", r)
        self.assertIn("外れ 1件", r)
        self.assertIn("出した 3件", r)   # s1 done / s2 handed_off / s4 done (by probability)
        self.assertIn("人が判定 2件", r)
        self.assertIn("却下 1件", r)
        self.assertIn("却下率 50.0%", r)
        self.assertIn("stalled / unknown はヒントに数えない", r)
        # the bt_monitor view is unchanged by status_audit rows
        self.assertIn("総数 1件", self.m.noise_report())

    def test_cli_use_case_status_audit(self):
        self.write_status_audit_log()
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.m.main(["--noise-report", "--use-case", "status_audit"])
        self.assertEqual(rc, 0)
        self.assertIn("Jev監視の判定（status_audit）: 総数 5件", buf.getvalue())

if __name__ == "__main__":
    unittest.main()
