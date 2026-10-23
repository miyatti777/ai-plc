"""Recurring operation Task templates declared in the selected addon guide (contract v0.3).

Synthetic fixtures only. Reuses make_case without editing older tests.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

SCRIPTS = Path(__file__).resolve().parents[1]   # .claude/skills/ai-plc/scripts (core/skills/ai-plc/scripts in the source tree)
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS / "tests")]
try:
    import plc_addon as addon
except ImportError:  # discover from scripts/tests cannot resolve the scripts package (same as the sibling addon tests)
    raise unittest.SkipTest("run from the repository root: python3 -m unittest scripts.tests.test_plc_addon_recurring")
from test_plc_addon import make_case, inventory, NOW


BLOCK = """
<!-- RECURRING_TEMPLATES:BEGIN -->
recurring_templates:
- name: 週次の締めと見直し（合成）
  recurrence: weekly
  description: 一週間の到達点を締め、次週の見直しを書く（合成）
  acceptance_criteria:
  - 今週の到達点と未達が1行ずつある
  - 次週に見直す点が1つ以上ある
<!-- RECURRING_TEMPLATES:END -->
"""


class RecurringTemplateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("PLCA1_TEST_ROOT"))
        self.case, self.intent, self.backlog, self.selection = make_case(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def save(self):
        for name, value in [("intent.yaml", self.intent), ("backlog.yaml", self.backlog)]:
            (self.case / name).write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False))

    def set_guide(self, extra):
        guide = self.case / "guide.md"
        guide.write_text("# 合成案内\n週次判断の型を案内する。\n" + extra)
        self.intent["addons"][0]["guide_ref"]["sha256"] = hashlib.sha256(guide.read_bytes()).hexdigest()
        self.save()

    def call(self, **kwargs):
        kwargs.setdefault("verified_selections", [self.selection])
        return addon.recurring_templates(self.case, allowed_roots=[self.case], now=NOW, **kwargs)

    def test_declared_guide_gives_one_weekly_proposal_without_writes(self):
        self.set_guide(BLOCK)
        before = inventory(self.case)
        result = self.call()
        self.assertEqual(before, inventory(self.case))
        self.assertEqual(result["route"], "recurring_proposals", result)
        self.assertEqual(len(result["proposals"]), 1)
        task = result["proposals"][0]["task"]
        self.assertEqual(task, {"id": "R?", "name": "週次の締めと見直し（合成）",
                                "description": "一週間の到達点を締め、次週の見直しを書く（合成）",
                                "type": "operation", "recurrence": "weekly", "runs": [], "status": "pending",
                                "dependencies": [], "acceptance_criteria": ["今週の到達点と未達が1行ずつある",
                                                                           "次週に見直す点が1つ以上ある"]})
        self.assertEqual(result["proposals"][0]["source"]["addon_id"], "synthetic-addon")
        self.assertFalse(result["writes"])
        self.assertFalse(result["dispatch"])
        self.assertIn("承認の後に backlog に書く", result["registration"])

    def test_no_declaration_gives_zero(self):
        before = inventory(self.case)
        result = self.call()
        self.assertEqual(before, inventory(self.case))
        self.assertEqual(result["route"], "recurring_proposals", result)
        self.assertEqual(result["proposals"], [])
        self.assertIn("no recurring_templates", result["reason"])

    def test_empty_list_gives_zero(self):
        self.set_guide("<!-- RECURRING_TEMPLATES:BEGIN -->\nrecurring_templates: []\n<!-- RECURRING_TEMPLATES:END -->\n")
        result = self.call()
        self.assertEqual(result["route"], "recurring_proposals", result)
        self.assertEqual(result["proposals"], [])

    def test_unselected_layer_gives_zero(self):
        del self.intent["addons"]
        self.save()
        before = inventory(self.case)
        result = self.call()
        self.assertEqual(before, inventory(self.case))
        self.assertEqual(result["route"], "unselected")
        self.assertEqual(result["proposals"], [])

    def test_invalid_declarations_hold_with_reason_and_no_writes(self):
        template = yaml.safe_load(BLOCK.split("BEGIN -->")[1].split("<!--")[0])["recurring_templates"][0]
        def block(items):
            body = yaml.safe_dump({"recurring_templates": items}, allow_unicode=True, sort_keys=False)
            return "<!-- RECURRING_TEMPLATES:BEGIN -->\n" + body + "<!-- RECURRING_TEMPLATES:END -->\n"
        cases = {
            "unknown recurrence": (block([{**template, "recurrence": "monthly"}]), "unknown recurring template recurrence"),
            "empty name": (block([{**template, "name": "  "}]), "name must be a nonempty string"),
            "missing name": (block([{k: v for k, v in template.items() if k != "name"}]), "name must be a nonempty string"),
            "empty ac": (block([{**template, "acceptance_criteria": []}]), "acceptance_criteria"),
            "blank ac": (block([{**template, "acceptance_criteria": [""]}]), "acceptance criterion"),
            "unknown field": (block([{**template, "owner": "誰か"}]), "unknown recurring template field"),
            "duplicate name": (block([template, copy.deepcopy(template)]), "duplicate recurring template name"),
            "too many": (block([{**template, "name": "n%d" % i, "acceptance_criteria": ["ac"]} for i in range(addon.MAX_TEMPLATES + 1)]), "bounded list"),
            "not a list": ("<!-- RECURRING_TEMPLATES:BEGIN -->\nrecurring_templates: weekly\n<!-- RECURRING_TEMPLATES:END -->\n", "bounded list"),
            "extra root key": ("<!-- RECURRING_TEMPLATES:BEGIN -->\nrecurring_templates: []\nother: 1\n<!-- RECURRING_TEMPLATES:END -->\n", "only recurring_templates"),
            "missing end": ("<!-- RECURRING_TEMPLATES:BEGIN -->\nrecurring_templates: []\n", "markers"),
            "two blocks": (BLOCK + BLOCK, "markers"),
            "empty block": ("<!-- RECURRING_TEMPLATES:BEGIN -->\n<!-- RECURRING_TEMPLATES:END -->\n", "only recurring_templates"),
        }
        for label, (extra, expected) in cases.items():
            with self.subTest(label=label):
                self.set_guide(extra)
                before = inventory(self.case)
                result = self.call()
                self.assertEqual(before, inventory(self.case))
                self.assertEqual(result["route"], "held", result)
                self.assertEqual(result["proposals"], [])
                self.assertIn(expected, result["reason"])

    def test_guide_hash_and_selection_are_checked(self):
        self.set_guide(BLOCK)
        (self.case / "guide.md").write_text("# 書き換えた案内\n" + BLOCK)
        self.assertIn("hash mismatch", self.call()["reason"])
        self.set_guide(BLOCK)
        self.assertEqual(self.call(verified_selections=[])["route"], "held")
        self.assertEqual(self.call(requested_addon="other-addon")["route"], "held")
        self.assertEqual(self.call(trial_requested=True)["route"], "held")

    def test_existing_same_task_in_backlog_is_not_proposed_again(self):
        self.set_guide(BLOCK)
        self.backlog["tasks"].append({"id": "R1", "name": "週次の締めと見直し（合成）", "recurrence": "weekly",
                                      "status": "in_progress", "runs": []})
        self.save()
        result = self.call()
        self.assertEqual(result["proposals"], [])
        self.assertEqual(result["already_in_backlog"], [{"name": "週次の締めと見直し（合成）", "recurrence": "weekly"}])

    def test_missing_backlog_is_allowed_for_new_inception(self):
        self.set_guide(BLOCK)
        (self.case / "backlog.yaml").unlink()
        result = self.call()
        self.assertEqual(len(result["proposals"]), 1, result)

    def test_existing_routes_unchanged_by_guide_block(self):
        self.set_guide(BLOCK)
        consult = addon.consult(self.case, allowed_roots=[self.case], verified_selections=[self.selection], now=NOW)
        self.assertEqual(consult["route"], "operational_guidance", consult)
        refs = addon.task_inputs(self.case, allowed_roots=[self.case], verified_selections=[self.selection], now=NOW,
                                 stage="inception", form_selected=True, form_id="weekly-judgment")
        self.assertEqual(refs["route"], "task_refs", refs)

    def test_old_contracts_unchanged_and_v03_extends_v02(self):
        v02 = yaml.safe_load(addon.TASK_CONTRACT.read_text())
        v03 = yaml.safe_load(addon.RECURRING_CONTRACT.read_text())
        self.assertEqual(addon.CONTRACT.name, "addon-seam-contract_v0.1.yaml")
        self.assertEqual(addon.TASK_CONTRACT.name, "addon-seam-contract_v0.2.yaml")
        self.assertEqual(v02["schema_version"], "0.2")
        self.assertEqual(v03["schema_version"], "0.3")
        for name, value in v02["types"].items():
            self.assertEqual(v03["types"][name], value, name)
        self.assertEqual(v03["implemented_routes"][:2], v02["implemented_routes"])

    def test_cli_returns_json_and_writes_nothing(self):
        self.set_guide(BLOCK)
        before = inventory(self.case)
        script = Path(addon.__file__).resolve()
        proc = subprocess.run([sys.executable, "-B", str(script), "--stage", "inception_recurring",
                               "--layer", str(self.case), "--read-root", str(self.case),
                               "--selection", json.dumps(self.selection, ensure_ascii=False)],
                              capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["proposals"][0]["task"]["recurrence"], "weekly")
        self.assertEqual(before, inventory(self.case))


if __name__ == "__main__":
    unittest.main()
