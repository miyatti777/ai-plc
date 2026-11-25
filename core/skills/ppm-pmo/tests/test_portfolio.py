"""ppm-pmo の補助スクリプト（portfolio.py・readback.py）のテスト。入力は全部架空（案件 A・B）。"""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import portfolio  # noqa: E402
import readback  # noqa: E402

SRC = {"path": "demo.md", "locator": "L1", "revision": "r1"}

BASE = {
    "schema_version": "portfolio-1",
    "portfolio_id": "DEMO",
    "as_of": "2026-09-10",
    "selected_projects": ["A", "B"],
    "staleness_days": 7,
    "projects": [
        {"id": "A", "name": "架空A", "owner": "担当A", "observed_at": "2026-09-08", "source": SRC,
         "items": [{"id": "X", "title": "連携機能", "status": "進行中", "forecast": "2026-09-20",
                    "confirmed_done": False, "source": SRC}],
         "issues": [{"id": "I1", "kind": "risk", "title": "外部の回答待ち", "status": "open",
                     "common_key": "vendor-wait", "source": SRC}]},
        {"id": "B", "name": "架空B", "owner": "担当B", "observed_at": "2026-09-09", "source": SRC,
         "items": [{"id": "Y", "title": "接続試験", "status": "待機", "forecast": None,
                    "confirmed_done": False, "source": SRC}],
         "issues": [{"id": "I9", "kind": "issue", "title": "外部の回答が来ない", "status": "open",
                     "common_key": "vendor-wait", "source": SRC}]},
    ],
    "dependencies": [{"id": "D1", "from": {"project_id": "A", "item_id": "X"},
                      "to": {"project_id": "B", "item_id": "Y"}, "needed_by": "2026-09-15", "source": SRC}],
    "resources": [{"id": "R1", "name": "共有の担当者", "unit": "hours_per_day", "capacity": 8,
                   "observed_at": "2026-09-09", "source": SRC}],
    "allocations": [
        {"id": "AL1", "resource_id": "R1", "project_id": "A", "start": "2026-09-14", "end": "2026-09-18",
         "load": 5, "unit": "hours_per_day", "source": SRC},
        {"id": "AL2", "resource_id": "R1", "project_id": "B", "start": "2026-09-16", "end": "2026-09-20",
         "load": 4, "unit": "hours_per_day", "source": SRC},
    ],
}


def data():
    return copy.deepcopy(BASE)


class AnalyzeTest(unittest.TestCase):
    def test_late_dependency_conflict_and_common_issue(self):
        result = portfolio.analyze(data(), "sha")
        dep = result["dependencies"][0]
        self.assertEqual(dep["state"], "late")
        self.assertEqual(dep["late_days"], 5)
        self.assertFalse(dep["provisional"])
        intervals = result["resources"][0]["intervals"]
        overlap = [x for x in intervals if x["cross_project_conflict"]]
        self.assertEqual([(x["start"], x["end"], x["load"]) for x in overlap], [("2026-09-16", "2026-09-18", 9.0)])
        self.assertEqual([c["common_key"] for c in result["common_issues"]], ["vendor-wait"])
        report = portfolio.report(result)
        self.assertIn("複数案件で上限超過", report)
        self.assertIn("必要日より後の見通し", report)

    def test_unknown_time_and_missing_issues_are_warned_not_filled(self):
        d = data()
        d["projects"][1]["observed_at"] = None
        d["projects"][1]["issues"] = []
        result = portfolio.analyze(d, "sha")
        codes = {w["code"] for w in result["warnings"]}
        self.assertIn("freshness_unknown", codes)
        self.assertIn("issues_not_provided", codes)
        self.assertTrue(result["dependencies"][0]["provisional"])
        self.assertEqual(result["common_issues"], [])

    def test_outside_allocation_is_kept_out_of_the_sum(self):
        d = data()
        d["selected_projects"] = ["A"]
        result = portfolio.analyze(d, "sha")
        res = result["resources"][0]
        self.assertEqual([a["id"] for a in res["outside_allocations"]], ["AL2"])
        self.assertFalse(any(x["over_capacity"] for x in res["intervals"]))

    def test_invalid_inputs_are_rejected(self):
        d = data()
        d["projects"][1]["id"] = "A"
        with self.assertRaises(ValueError):
            portfolio.analyze(d, "sha")
        d = data()
        d["allocations"][0]["start"] = "2026-9-14"
        with self.assertRaises(ValueError):
            portfolio.analyze(d, "sha")
        d = data()
        d["projects"][0]["issues_status"] = "confirmed_none"
        with self.assertRaises(ValueError):
            portfolio.analyze(d, "sha")


class CliTest(unittest.TestCase):
    def run_cli(self, script, *args):
        return subprocess.run([sys.executable, "-B", str(SCRIPTS / script), *map(str, args)],
                              capture_output=True, text=True)

    def test_bundle_is_written_once_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "input.json"
            src.write_text(json.dumps(BASE, ensure_ascii=False), encoding="utf-8")
            out = tmp / "run-01"
            first = self.run_cli("portfolio.py", src, "--output", out)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue((out / "analysis.json").is_file())
            self.assertTrue((out / "portfolio_report.md").is_file())
            again = self.run_cli("portfolio.py", src, "--output", out)
            self.assertEqual(again.returncode, 0, again.stderr)  # 同じ入力の再実行は同じ内容
            changed = data()
            changed["as_of"] = "2026-09-11"
            src.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
            refused = self.run_cli("portfolio.py", src, "--output", out)
            self.assertEqual(refused.returncode, 2)
            self.assertIn("new run directory", refused.stderr)


class ReadbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.master = self.dir / "project_b.json"
        self.master.write_text(json.dumps({"priority": "low"}), encoding="utf-8")
        self.before_sha = portfolio.digest(self.master.read_bytes())

    def tearDown(self):
        self.tmp.cleanup()

    def request(self):
        return {"portfolio_id": "DEMO", "decision_id": "DEC1", "project_id": "B", "request_id": "RQ1",
                "revision": "1", "target_path": "project_b.json", "pointer": "/priority",
                "expected_before": "low", "expected_after": "high", "before_sha256": self.before_sha}

    def handoffs(self, req):
        return {"schema_version": "handoff-1", "portfolio_id": "DEMO", "decision_id": "DEC1", "requests": [req]}

    def state(self, req):
        result, _ = readback.verify(self.handoffs(req), self.dir)
        return result["requests"][0]["state"], result["state"]

    def test_without_confirmation_needs_review(self):
        self.assertEqual(self.state(self.request()), ("needs_review", "needs_review"))

    def test_confirmed_but_not_applied_is_unapplied(self):
        req = self.request()
        req["confirmation"] = {"actor": "責任者X", "authority": "優先順位", "at": "2026-09-11",
                               "request_sha256": readback.request_hash(req)}
        self.assertEqual(self.state(req), ("unapplied", "unapplied"))

    def test_applied_with_receipt_is_verified(self):
        req = self.request()
        rh = readback.request_hash(req)
        req["confirmation"] = {"actor": "責任者X", "authority": "優先順位", "at": "2026-09-11", "request_sha256": rh}
        self.master.write_text(json.dumps({"priority": "high"}), encoding="utf-8")
        after = portfolio.digest(self.master.read_bytes())
        self.assertEqual(self.state(req), ("evidence_missing", "needs_review"))  # 実行記録なし
        req["receipt"] = {"actor": "担当B", "at": "2026-09-12", "request_sha256": rh, "after_sha256": after}
        self.assertEqual(self.state(req), ("verified", "verified"))

    def test_unexpected_value_is_conflict(self):
        req = self.request()
        req["confirmation"] = {"actor": "責任者X", "authority": "優先順位", "at": "2026-09-11",
                               "request_sha256": readback.request_hash(req)}
        self.master.write_text(json.dumps({"priority": "medium"}), encoding="utf-8")
        self.assertEqual(self.state(req)[0], "conflict")

    def test_hash_ignores_confirmation_and_receipt(self):
        req = self.request()
        rh = readback.request_hash(req)
        req["confirmation"] = {"actor": "x"}
        req["receipt"] = {"actor": "y"}
        self.assertEqual(readback.request_hash(req), rh)


if __name__ == "__main__":
    unittest.main()
