"""Addon x work_budget_v1: plc_addon.py uses plc_execution's work-budget judgement.

Synthetic fixtures only. Covers deadline_kind none / hard_stop and the legacy v2 deadline for the bulk
Operation path (task_inputs) and the consult Next path (_next), each before the limit, at the limit and
with inconsistent records.
"""
import copy
import datetime as dt
import os
import tempfile
import unittest

import yaml
from pathlib import Path
import sys
SCRIPTS = Path(__file__).resolve().parents[1]   # .claude/skills/ai-plc/scripts (core/skills/ai-plc/scripts in the source tree)
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS / "tests")]
import plc_addon as addon
from test_plc_addon import make_case, NOW

LIMIT = 150


def minutes(n):
    return dt.timedelta(minutes=n)


class WorkBudgetAddonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("PLCA1_TEST_ROOT"))
        self.addCleanup(self.tmp.cleanup)
        self.case, self.intent, self.backlog, self.selection = make_case(self.tmp.name)
        self.backlog["execution_contract"]["current_task"] = "DEMO-TASK"
        self.save()
        result = self.task_inputs(stage="inception")
        self.assertEqual(result["route"], "task_refs", result)
        self.backlog["tasks"][0]["addon_refs"] = result["addon_refs"]
        self.save()

    def save(self):
        for name, value in [("intent.yaml", self.intent), ("backlog.yaml", self.backlog)]:
            (self.case / name).write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False))

    def task_inputs(self, at=NOW, stage="operation"):
        return addon.task_inputs(self.case, stage=stage, allowed_roots=[self.case], verified_selections=[self.selection],
                                 now=at, form_selected=True, form_id="weekly-judgment", task_id="DEMO-TASK",
                                 task_version="v1", approved_task_ids=["DEMO-TASK"])

    def next_entry(self, at=NOW):
        result = addon.consult(self.case, allowed_roots=[self.case], verified_selections=[self.selection], now=at,
                               approved_task_ids=["DEMO-TASK"])
        self.assertEqual(result["route"], "operational_guidance", result)
        return result["next_actions"][0]["entry"]

    def use(self, kind):
        budget = self.backlog["execution_budget"]
        if kind == "legacy":
            return budget
        budget.pop("deadline")
        budget.update(time_policy="work_budget_v1", deadline_kind="none", deadline_source="none",
                      started_at=(NOW - minutes(60)).isoformat(), active_since=(NOW - minutes(60)).isoformat(),
                      work_limit_minutes=LIMIT, work_used_minutes=0, break_minutes=0, answer_wait_minutes=0,
                      pause_history=[])
        if kind == "hard_stop":
            budget.update(deadline_kind="hard_stop", deadline_source="user", deadline=(NOW + minutes(30)).isoformat())
        self.save()
        return budget

    def assert_continues(self, at=NOW):
        result = self.task_inputs(at)
        self.assertEqual(result["route"], "task_inputs", result)
        self.assertEqual(result["authorization_mode"], "bulk_execution")
        self.assertEqual(self.next_entry(at), "$04-operation")

    def assert_blocked(self, reason_prefix, at=NOW):
        result = self.task_inputs(at)
        self.assertEqual(result["route"], "held")
        reason = result["reason"].removeprefix("Held: ")
        self.assertTrue(reason.startswith(reason_prefix), result["reason"])
        self.assertEqual(self.next_entry(at), "$plc-brief")
        return reason

    # deadline_kind none
    def test_none_continues_before_the_work_ceiling(self):
        self.use("none")
        self.assert_continues()
        self.assert_continues(NOW + minutes(89))

    def test_none_stops_at_the_work_ceiling(self):
        self.use("none")
        self.assert_blocked("work budget stop: cumulative work ceiling reached", NOW + minutes(LIMIT - 60))

    def test_none_inconsistent_record_holds(self):
        for fields in ({"active_since": (NOW - minutes(10)).isoformat()}, {"break_minutes": 5},
                       {"work_limit_minutes": 0}, {"deadline": (NOW + minutes(30)).isoformat()}):
            with self.subTest(fields=fields):
                self.use("none") if "time_policy" not in self.backlog["execution_budget"] else None
                original = copy.deepcopy(self.backlog)
                self.backlog["execution_budget"].update(fields); self.save()
                self.assert_blocked("work budget hold: ")
                self.backlog = original; self.save()

    def test_none_batch_is_not_always_held(self):
        # Before this change the bulk path read budget["deadline"] and always Held ('deadline').
        self.use("none")
        result = self.task_inputs()
        self.assertEqual(result["route"], "task_inputs", result)
        self.assertEqual(result["authorization_mode"], "bulk_execution")
        self.assertIn("型本文", result["input_data"][-1]["text"])

    # deadline_kind hard_stop
    def test_hard_stop_continues_before_both_limits(self):
        self.use("hard_stop")
        self.assert_continues()
        self.assert_continues(NOW + minutes(29))

    def test_hard_stop_stops_at_the_deadline_or_the_ceiling(self):
        self.use("hard_stop")
        self.assert_blocked("work budget stop: user/service deadline ended", NOW + minutes(30))
        self.backlog["execution_budget"]["work_limit_minutes"] = 70; self.save()
        self.assert_blocked("work budget stop: cumulative work ceiling reached", NOW + minutes(10))

    def test_hard_stop_inconsistent_record_holds(self):
        budget = self.use("hard_stop")
        for fields in ({"active_since": (NOW - minutes(10)).isoformat()}, {"deadline_source": "ai"},
                       {"deadline": (NOW - minutes(90)).isoformat()}):
            with self.subTest(fields=fields):
                original = copy.deepcopy(self.backlog)
                self.backlog["execution_budget"].update(fields); self.save()
                self.assert_blocked("work budget hold: ")
                self.backlog = original; self.save()
        self.assertTrue(budget)

    def test_unknown_time_policy_holds(self):
        self.use("none")
        self.backlog["execution_budget"]["time_policy"] = "future"; self.save()
        self.assert_blocked("unknown time policy")

    # legacy v2 (budget["deadline"]): behaviour and output unchanged
    def test_legacy_continues_before_the_deadline(self):
        self.use("legacy")
        self.assert_continues()
        self.assert_continues(NOW + minutes(59))

    def test_legacy_stops_at_the_deadline(self):
        self.use("legacy")
        self.assert_blocked("current finite allocation unavailable", NOW + minutes(60))

    def test_legacy_inconsistent_record_holds(self):
        self.use("legacy")
        for mutate, reason in [(lambda b: b.update(deadline=(NOW - minutes(120)).isoformat()), "current finite allocation unavailable"),
                               (lambda b: b.pop("deadline"), "KeyError: 'deadline'"),
                               (lambda b: b.update(recording_reserved_from=(NOW - minutes(1)).isoformat()), "recording-only reserve reached")]:
            with self.subTest(reason=reason):
                original = copy.deepcopy(self.backlog)
                mutate(self.backlog["execution_budget"]); self.save()
                self.assert_blocked(reason)
                self.backlog = original; self.save()


if __name__ == "__main__":
    unittest.main()
