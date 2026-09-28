"""Tests for --scope / --layer / --brief of scripts/aiplc_status_audit.py.

Synthetic DB + synthetic Layers in a temp dir only; no network (jev_client.ask is replaced by a function that fails).
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

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

F = "Flow/202609/2026-09-01"


def all_files(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


class BriefTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        f = Fixture(t)
        self.f = f
        # L-A: class 1 (intent done, Registry open) -> applicable
        f.layer(f"{F}/a-done", "L-A", "completed", [("T001", "completed")])
        f.project("L-A", url=f"{F}/a-done")
        f.rtask("L-A", "T001", "完了")
        # L-B: class 5 stale -> not applicable
        f.layer(f"{F}/b-stale", "L-B", "active", [("T001", "pending")], days_ago=40)
        f.project("L-B", url=f"{F}/b-stale")
        f.rtask("L-B", "T001", "未着手")
        # L-SEC: confidential (redact word in the name / folder), class 1
        f.layer(f"{F}/zetaproj-secret", "L-SEC", "completed", [("T001", "completed")])
        f.project("L-SEC", url=f"{F}/zetaproj-secret", name="Zetaproj 秘密の件")
        f.rtask("L-SEC", "T001", "完了")
        # L-OK: consistent, no candidate
        f.layer(f"{F}/ok", "L-OK", "active", [("T001", "pending")], days_ago=1)
        f.project("L-OK", url=f"{F}/ok")
        f.rtask("L-OK", "T001", "未着手")
        # an intent.yaml inside node_modules is never a Layer (scan pruning)
        f.layer(f"{F}/ok/app/node_modules/pkg", "L-NM", "active", [("T001", "pending")])
        f.close()
        self.state = t / "state"
        self.memory = t / "MEMORY.md"
        self.memory.write_text("", encoding="utf-8")
        self.before_db = sha(f.db)
        self.before_tree = tree_hashes(t)
        self._ask = jev_client.ask

        def no_net(*a, **k):
            raise AssertionError("Jev must not be called")
        jev_client.ask = no_net

    def tearDown(self):
        jev_client.ask = self._ask
        self.tmp.cleanup()

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = audit_mod.main(["--db", str(self.f.db), "--root", str(self.f.root), "--today", TODAY.isoformat(),
                                 "--memory", str(self.memory), "--state-dir", str(self.state), *args])
        return rc, out.getvalue(), err.getvalue()

    def assert_nothing_written(self):
        self.assertFalse(self.state.exists())
        self.assertEqual(sha(self.f.db), self.before_db)
        self.assertEqual(tree_hashes(Path(self.tmp.name)), self.before_tree)

    # ---- --scope / --layer
    def test_scope_filters_other_scopes(self):
        rc, out, _ = self.run_main("--brief", "--scope", "L-A")
        self.assertEqual(rc, 10)
        self.assertIn("L-A:intent_done_registry_open: intent 完了なのに Registry 未完了 — Registry を completed に — "
                      "反映するなら --approval-template → --apply", out)
        self.assertNotIn("L-B", out)
        self.assertNotIn(audit_mod.hash_id("L-SEC"), out)
        self.assertIn("候補 1 件", out)

    def test_scope_repeatable_and_report_filtered(self):
        outdir = Path(self.tmp.name) / "out"
        rc, _, _ = self.run_main("--scope", "L-A", "--scope", "L-B", "--out", str(outdir), "--quiet")
        self.assertEqual(rc, 0)  # non-brief exit codes unchanged
        pub = json.loads((outdir / "report.json").read_text(encoding="utf-8"))
        self.assertEqual({c["scope_id"] for c in pub["candidates"]}, {"L-A", "L-B"})
        self.assertEqual(pub["counts"]["candidates"], 2)
        self.assertNotIn("L-SEC", (outdir / "report.md").read_text(encoding="utf-8"))

    def test_scope_filter_in_audit_builds_only_those_candidates(self):
        r = audit_mod.audit(self.f.db, self.f.root, TODAY, 30, None, None, scope_filter={"L-B"})
        self.assertEqual([c["candidate_id"] for c in r["candidates"]], ["L-B:stale"])

    def test_layer_resolves_to_scope_id(self):
        self.assertEqual(audit_mod.layer_scope_id(f"{F}/b-stale", self.f.root), ("L-B", None))
        self.assertEqual(audit_mod.layer_scope_id(str(self.f.root / F / "b-stale" / "intent.yaml"), self.f.root),
                         ("L-B", None))
        rc, out, _ = self.run_main("--brief", "--layer", f"{F}/b-stale")
        self.assertEqual(rc, 10)
        self.assertIn("L-B:stale: N日以上更新なし（停滞） — 停滞の中身を確認 — --apply の対象外（人が判断）", out)
        self.assertNotIn("L-A", out)

    def test_layer_without_intent_is_error(self):
        rc, _, err = self.run_main("--brief", "--layer", f"{F}/nowhere")
        self.assertEqual(rc, 2)
        self.assertIn("--layer", err)

    def test_unknown_scope_is_error_and_hashed(self):
        rc, out, err = self.run_main("--brief", "--scope", "L-TYPO")
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertNotIn("L-TYPO", err)
        self.assertIn(audit_mod.hash_id("L-TYPO"), err)

    # ---- --brief
    def test_brief_writes_no_file(self):
        for args in (("--brief",), ("--brief", "--scope", "L-A"), ("--brief", "--scope", "L-OK")):
            self.run_main(*args)
        self.assert_nothing_written()

    def test_brief_confidential_scope_hashed(self):
        rc, out, err = self.run_main("--brief", "--scope", "L-SEC")
        self.assertEqual(rc, 10)
        self.assertIn(f"{audit_mod.hash_id('L-SEC')}:intent_done_registry_open:", out)
        for s in ("L-SEC", "zetaproj", "Zetaproj", "秘密"):
            self.assertNotIn(s, out + err)
        # the hash id is accepted as --scope too
        rc2, out2, _ = self.run_main("--brief", "--scope", audit_mod.hash_id("L-SEC"))
        self.assertEqual((rc2, out2), (rc, out))

    def test_brief_exit_codes(self):
        rc, out, _ = self.run_main("--brief", "--scope", "L-OK")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "ステータス点検: 食い違いなし")
        rc, _, _ = self.run_main("--brief", "--layer", f"{F}/a-done")
        self.assertEqual(rc, 10)

    def test_brief_without_scope_prints_counts_only(self):
        rc, out, _ = self.run_main("--brief")
        self.assertEqual(rc, 10)
        self.assertIn("| 1. intent 完了なのに Registry 未完了 | 2 |", out)
        self.assertIn("| 5. N日以上更新なし（停滞） | 1 |", out)
        self.assertNotIn("L-A", out)
        self.assertNotIn(audit_mod.hash_id("L-SEC"), out)
        self.assertTrue(out.strip().splitlines()[-1].startswith("ステータス点検: 候補 3 件"))
        self.assertIn("反映できる 2 件", out)

    def test_brief_rejects_jev_and_writers(self):
        for extra in (("--jev",), ("--approval-template",), ("--out", str(Path(self.tmp.name) / "o"))):
            rc, out, err = self.run_main("--brief", *extra)
            self.assertEqual(rc, 2, extra)
            self.assertEqual(out, "")
        rc, _, _ = self.run_main("--apply", str(Path(self.tmp.name) / "x.json"), "--scope", "L-A")
        self.assertEqual(rc, 2)
        self.assert_nothing_written()

    def test_node_modules_intent_not_a_layer(self):
        r = audit_mod.audit(self.f.db, self.f.root, TODAY, 30, None, None)
        self.assertNotIn("L-NM", {c["scope_id"] for c in r["candidates"]})


if __name__ == "__main__":
    unittest.main()
