"""Offline tests for jev_bt_monitor --pending / --override-pending (judgments with no human accept/reject yet)."""
import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    raise unittest.SkipTest("pyyaml が無い（pip install pyyaml）")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jev_test_support as jts  # noqa: E402


def tearDownModule():
    jts.restore()


def row(did, use_case, scope, answers, action="answered", task="T001", ts="2026-01-01T10:00:00+09:00"):
    return {"decision_id": did, "ts": ts, "use_case": use_case, "scope_id": scope, "task_id": task,
            "input_sha256": "0" * 64, "answers": answers, "action": action}


class PendingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.log, self.ov = d / "log.jsonl", d / "ov.jsonl"
        self._env = {k: os.environ.get(k) for k in ("JEV_LOG_PATH", "JEV_OVERRIDE_PATH", "JEV_COUNTS_STATE_PATH")}
        os.environ["JEV_LOG_PATH"] = str(self.log)
        os.environ["JEV_OVERRIDE_PATH"] = str(self.ov)
        os.environ["JEV_COUNTS_STATE_PATH"] = str(d / "counts_state.json")
        import jev_client
        import jev_bt_monitor
        importlib.reload(jev_client)
        self.m = importlib.reload(jev_bt_monitor)
        jts.isolate()
        self.jc = self.m.jev_client
        self.layer = d / "layer"
        self.layer.mkdir()
        (self.layer / "intent.yaml").write_text(yaml.safe_dump({"scope_id": "L-0000-1", "jev_monitor": True}),
                                                encoding="utf-8")
        rows = [
            row("b1", "bt_monitor", "L-0000-1", {"blocker": 0.9}),               # hint
            row("b2", "bt_monitor", "L-0000-1", {"drift": 0.1}, task=None),      # no hint: still listed
            row("c1", "coverage", "L-0000-1", {"c1": {"choice": "T001", "probabilities": {"T001": 0.9}},
                                              "c2": {"choice": "__NONE__", "probabilities": {"__NONE__": 0.8}}},
                task="inception"),
            row("c2", "coverage", "L-0000-1", {"c1": None}, task="inception"),   # unparsed answer: still listed
            row("h1", "prompt_hook", "L-0000-1", {"user_signal": 0.94}, task="prompt"),  # hint shown
            row("h2", "prompt_hook", "L-0000-1", {"user_signal": 0.2}, task="prompt"),   # not shown: excluded
            row("h3", "prompt_hook", "L-0000-1", {"user_signal": None}, task="prompt"),  # not shown: excluded
            row("s1", "bt_monitor", "L-0000-1", None, action="skipped(redacted)"),       # not answered
            row("s2", "status_audit", "L-0000-1", {"status": {"choice": "done"}}),       # other use case
            row("o1", "bt_monitor", "L-0000-2", {"blocker": 0.9}),                       # other Layer
            row("o2", "prompt_hook", None, {"user_signal": 0.9}),                        # no Layer
            row("r1", "bt_monitor", "L-0000-1", {"blocker": 0.7}),                       # recorded below
        ]
        with self.log.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
            f.write("not json\n")
        self.jc.record_override("r1", "reject")

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def ids(self, layer=None):
        return [r["decision_id"] for r in self.m.pending(layer or self.layer)[1]]

    def run_main(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.m.main(argv)
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def ov_rows(self):
        return [json.loads(l) for l in self.ov.read_text(encoding="utf-8").splitlines() if l.strip()]

    def test_extraction_rules(self):
        # bt_monitor / coverage: all answered; prompt_hook: only shown hints; recorded, other Layers, skipped excluded
        self.assertEqual(self.ids(), ["b1", "b2", "c1", "c2", "h1"])

    def test_layer_by_scope_id_and_by_intent_path(self):
        self.assertEqual(self.ids("L-0000-1"), ["b1", "b2", "c1", "c2", "h1"])
        self.assertEqual(self.ids(str(self.layer / "intent.yaml")), ["b1", "b2", "c1", "c2", "h1"])
        self.assertEqual(self.ids("L-0000-2"), ["o1"])

    def test_report_format(self):
        out = self.run_main(["--pending", "--layer", str(self.layer)])
        lines = out.strip().splitlines()
        self.assertEqual(lines[0], "🧭 未確認の Jev 判定: 5件（L-0000-1）")
        self.assertIn("- b1  bt_monitor  T001  p=0.90  2026-01-01T10:00:00+09:00", lines)
        self.assertIn("- b2  bt_monitor  -  p=0.10  2026-01-01T10:00:00+09:00", lines)
        self.assertIn("- c1  coverage  inception  p=0.80  2026-01-01T10:00:00+09:00", lines)
        self.assertIn("- c2  coverage  inception  p=-  2026-01-01T10:00:00+09:00", lines)
        self.assertEqual(lines[-1], "貼り付け用: Jev判定 b1・b2・c1・c2・h1 は accept")
        self.assertNotIn("input_sha256", out)

    def test_zero(self):
        out = self.run_main(["--pending", "--layer", "L-0000-9"])
        self.assertEqual(out.strip(), "未確認の Jev 判定なし（L-0000-9）")

    def test_needs_layer(self):
        self.assertIn("--layer が必要", self.run_main(["--pending"]))
        self.assertIn("--layer が必要", self.run_main(["--override-pending", "accept"]))
        self.assertEqual(len(self.ov_rows()), 1)

    def test_override_pending_records_all(self):
        out = self.run_main(["--override-pending", "accept", "--layer", str(self.layer)])
        self.assertIn("human_override を記録: 5件 = accept（L-0000-1）", out)
        rows = self.ov_rows()
        self.assertEqual([r["decision_id"] for r in rows], ["r1", "b1", "b2", "c1", "c2", "h1"])
        self.assertTrue(all(r["human_override"] == "accept" for r in rows[1:]))
        self.assertEqual(self.ids(), [])
        self.assertEqual(self.ids("L-0000-2"), ["o1"])  # other Layer untouched
        # a second run writes nothing twice
        out = self.run_main(["--override-pending", "accept", "--layer", str(self.layer)])
        self.assertIn("未確認の Jev 判定なし（L-0000-1）", out)
        self.assertEqual(len(self.ov_rows()), 6)

    def test_except_ids_are_not_recorded(self):
        self.run_main(["--override", "h1", "reject"])  # the individual verdict first
        out = self.run_main(["--override-pending", "accept", "--layer", "L-0000-1", "--except", "b2", "c2"])
        self.assertIn("human_override を記録: 2件 = accept", out)
        self.assertIn("除外 2件", out)
        rows = {r["decision_id"]: r["human_override"] for r in self.ov_rows()}
        self.assertEqual(rows, {"r1": "reject", "h1": "reject", "b1": "accept", "c1": "accept"})
        self.assertEqual(self.ids(), ["b2", "c2"])  # excluded ones stay pending

    def test_reject_verdict_and_function(self):
        sid, ids = self.m.override_pending(self.layer, "reject", except_ids=["b1"])
        self.assertEqual((sid, ids), ("L-0000-1", ["b2", "c1", "c2", "h1"]))
        self.assertTrue(all(r["human_override"] == "reject" for r in self.ov_rows()))
        with self.assertRaises(ValueError):
            self.m.override_pending(self.layer, "maybe")

    def test_unreadable_layer(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        self.assertIn("scope_id が読めません", self.run_main(["--pending", "--layer", str(empty)]))
        self.assertIn("何も記録していません", self.run_main(["--override-pending", "accept", "--layer", str(empty)]))
        self.assertEqual(len(self.ov_rows()), 1)

    def test_missing_logs(self):
        self.log.unlink()
        self.ov.unlink()
        self.assertEqual(self.ids(), [])
        self.assertIn("未確認の Jev 判定なし", self.run_main(["--pending", "--layer", "L-0000-1"]))


if __name__ == "__main__":
    unittest.main()
