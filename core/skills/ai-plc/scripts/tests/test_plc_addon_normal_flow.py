"""Normal (non-bulk) Operation path for one current Task.

Synthetic fixtures only. Uses the existing make_case fixture without editing older tests.
"""
import os
import tempfile
import unittest

import yaml
from pathlib import Path
import sys
SCRIPTS = Path(__file__).resolve().parents[1]   # .claude/skills/ai-plc/scripts (core/skills/ai-plc/scripts in the source tree)
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS / "tests")]
import plc_addon as addon
from test_plc_addon import make_case, inventory, NOW


class NormalSingleTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("PLCA1_TEST_ROOT"))
        self.case, self.intent, self.backlog, self.selection = make_case(self.tmp.name)
        # normal flow: no bulk execution record at all
        self.backlog.pop("execution_contract")
        self.backlog.pop("execution_budget")
        self.save()
        result = self.call("inception")
        self.assertEqual(result["route"], "task_refs")
        self.backlog["tasks"][0]["addon_refs"] = result["addon_refs"]
        self.save()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self):
        for name, value in [("intent.yaml", self.intent), ("backlog.yaml", self.backlog)]:
            (self.case / name).write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False))

    def call(self, stage="operation", **kwargs):
        args = dict(allowed_roots=[self.case], verified_selections=[self.selection], now=NOW,
                    form_selected=True, form_id="weekly-judgment", task_id="DEMO-TASK",
                    task_version="v1", approved_task_ids=["DEMO-TASK"])
        args.update(kwargs)
        return addon.task_inputs(self.case, stage=stage, **args)

    def assertHeld(self, result):
        self.assertEqual(result["route"], "held", result)

    def test_normal_single_task_reads_form_without_writes(self):
        before = inventory(self.case)
        result = self.call()
        self.assertEqual(result["route"], "task_inputs", result)
        self.assertEqual(result["authorization_mode"], "normal_single_task")
        self.assertEqual([r["role"] for r in result["input_data"]], ["guide_ref", "common_contract_ref", "form_ref"])
        self.assertFalse(result["writes"])
        self.assertEqual(before, inventory(self.case))

    def test_old_completed_records_are_ignored_not_read_as_approval(self):
        self.backlog["execution_contract"] = {"status": "completed", "current_task": "OTHER", "scope_tasks": ["OTHER"],
                                              "task_versions": {"OTHER": "v9"}, "authorization_scope": "end_to_end"}
        self.backlog["execution_budget"] = {"status": "completed", "budget_id": "OLD"}
        self.save()
        result = self.call()
        self.assertEqual(result["route"], "task_inputs", result)
        self.assertEqual(result["authorization_mode"], "normal_single_task")

    def test_active_or_stopped_contract_states_hold(self):
        for status in ("running", "paused", "stopped", "cancelled", "blocked", "unknown-state", None):
            with self.subTest(status=status):
                self.backlog["execution_contract"] = {"status": status, "current_task": "OTHER"}
                self.backlog.pop("execution_budget", None)
                self.save()
                self.assertHeld(self.call())

    def test_budget_not_completed_holds_even_if_contract_completed_or_absent(self):
        for contract in (None, {"status": "completed"}):
            for status in ("running", "paused", "stopped", "blocked", None):
                with self.subTest(contract=contract, status=status):
                    self.backlog.pop("execution_contract", None)
                    if contract is not None:
                        self.backlog["execution_contract"] = contract
                    self.backlog["execution_budget"] = {"status": status, "budget_id": "B"}
                    self.save()
                    self.assertHeld(self.call())

    def test_approval_must_be_exactly_this_one_task(self):
        for approved in ([], ["DEMO-TASK", "OTHER"], ["OTHER"], ["DEMO-TASK", "DEMO-TASK"]):
            with self.subTest(approved=approved):
                self.assertHeld(self.call(approved_task_ids=approved))

    def test_task_version_missing_or_different_holds(self):
        self.assertHeld(self.call(task_version="v2"))
        self.assertHeld(self.call(task_version=None))
        del self.backlog["tasks"][0]["task_version"]
        self.save()
        self.assertHeld(self.call())

    def test_upstream_incomplete_and_terminal_task_hold(self):
        self.backlog["tasks"].append({"id": "UP", "task_version": "v1", "status": "pending", "dependencies": []})
        self.backlog["tasks"][0]["dependencies"] = ["UP"]
        self.save()
        self.assertHeld(self.call())
        self.backlog["tasks"][0]["dependencies"] = []
        self.backlog["tasks"][0]["status"] = "completed"
        self.save()
        self.assertHeld(self.call())

    def test_form_hash_change_holds(self):
        (self.case / "form.md").write_text("changed")
        self.assertHeld(self.call())

    def test_bulk_path_unchanged_reports_bulk_mode(self):
        result_case = make_case(tempfile.mkdtemp(dir=self.tmp.name))
        case, intent, backlog, selection = result_case
        backlog["execution_contract"]["current_task"] = "DEMO-TASK"
        for name, value in [("intent.yaml", intent), ("backlog.yaml", backlog)]:
            (case / name).write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False))
        args = dict(allowed_roots=[case], verified_selections=[selection], now=NOW, form_selected=True,
                    form_id="weekly-judgment", task_id="DEMO-TASK", task_version="v1", approved_task_ids=["DEMO-TASK"])
        refs = addon.task_inputs(case, stage="inception", **args)["addon_refs"]
        backlog["tasks"][0]["addon_refs"] = refs
        (case / "backlog.yaml").write_text(yaml.safe_dump(backlog, allow_unicode=True, sort_keys=False))
        result = addon.task_inputs(case, stage="operation", **args)
        self.assertEqual(result["route"], "task_inputs", result)
        self.assertEqual(result["authorization_mode"], "bulk_execution")
        # two approved Tasks are allowed only on the bulk path, unchanged
        self.assertEqual(addon.task_inputs(case, stage="operation", **{**args, "approved_task_ids": ["DEMO-TASK", "X"]})["route"],
                         "task_inputs")


if __name__ == "__main__":
    unittest.main()
