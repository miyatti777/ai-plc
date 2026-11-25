"""Optional intent.addon_init (initialization Task declaration).

Synthetic fixtures only. Reuses make_case without editing older tests.
"""
import copy
import hashlib
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


class AddonInitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("PLCA1_TEST_ROOT"))
        self.case, self.intent, self.backlog, self.selection = make_case(self.tmp.name)
        (self.case / "init.md").write_text("記録の箱の準備（合成）")
        binding = self.intent["addons"][0]
        binding["forms"].append({"form_id": "project-init", "form_ref": {
            "kind": "file", "scope": "case", "version": "0.1", "relative_name": "init.md",
            "sha256": hashlib.sha256((self.case / "init.md").read_bytes()).hexdigest()}})
        binding["read_limits"]["max_form_items"] = 2
        (self.case / "manifest.yaml").write_text("addon_id: synthetic-addon\ninit_form_id: project-init\n")
        self.intent["addon_init"] = {"addon_id": "synthetic-addon", "addon_version": "0.1", "form_id": "project-init",
                                     "declared_in": "manifest.yaml",
                                     "manifest_sha256": hashlib.sha256((self.case / "manifest.yaml").read_bytes()).hexdigest()}
        self.save()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self):
        for name, value in [("intent.yaml", self.intent), ("backlog.yaml", self.backlog)]:
            (self.case / name).write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False))

    def inception(self, form_id):
        return addon.task_inputs(self.case, allowed_roots=[self.case], verified_selections=[self.selection], now=NOW,
                                 stage="inception", form_selected=True, form_id=form_id)

    def test_declared_form_is_flagged_and_others_are_not(self):
        before = inventory(self.case)
        init = self.inception("project-init")
        other = self.inception("weekly-judgment")
        self.assertEqual(init["route"], "task_refs", init)
        self.assertTrue(init["is_init_form"])
        self.assertEqual(other["route"], "task_refs", other)
        self.assertFalse(other["is_init_form"])
        self.assertEqual(before, inventory(self.case))

    def test_absent_declaration_keeps_previous_behavior(self):
        del self.intent["addon_init"]
        self.save()
        result = self.inception("project-init")
        self.assertEqual(result["route"], "task_refs", result)
        self.assertFalse(result["is_init_form"])

    def test_declaration_without_manifest_reference_is_allowed(self):
        del self.intent["addon_init"]["declared_in"], self.intent["addon_init"]["manifest_sha256"]
        self.save()
        self.assertTrue(self.inception("project-init")["is_init_form"])

    def test_inconsistent_declarations_hold(self):
        cases = [
            lambda i: i.update(addon_version="9.9"),
            lambda i: i.update(form_id="missing-form"),
            lambda i: i.update(unknown_field=True),
            lambda i: i.pop("form_id"),
            lambda i: i.pop("manifest_sha256"),
            lambda i: i.update(manifest_sha256="0" * 64),
            lambda i: i.update(declared_in="../outside.yaml"),
            lambda i: i.update(declared_in="/etc/hosts"),
        ]
        original = copy.deepcopy(self.intent["addon_init"])
        for change in cases:
            with self.subTest(change=change):
                self.intent["addon_init"] = copy.deepcopy(original)
                change(self.intent["addon_init"])
                self.save()
                self.assertEqual(self.inception("project-init")["route"], "held")

    def test_declaration_for_another_addon_is_not_an_init_form(self):
        self.intent["addon_init"]["addon_id"] = "other-addon"
        self.save()
        result = self.inception("project-init")
        self.assertEqual(result["route"], "task_refs", result)
        self.assertFalse(result["is_init_form"])

    def test_unselected_form_ignores_even_invalid_declaration(self):
        self.intent["addon_init"] = "not-a-mapping"
        self.save()
        result = addon.task_inputs(self.case, allowed_roots=[self.case], verified_selections=[self.selection], now=NOW,
                                   stage="inception", form_selected=False)
        self.assertEqual(result["route"], "unselected")

    def test_non_mapping_declaration_holds(self):
        for value in ("project-init", ["project-init"], True):
            with self.subTest(value=value):
                self.intent["addon_init"] = value
                self.save()
                self.assertEqual(self.inception("weekly-judgment")["route"], "held")

    def test_manifest_change_after_declaration_holds(self):
        (self.case / "manifest.yaml").write_text("changed\n")
        self.assertEqual(self.inception("project-init")["route"], "held")


if __name__ == "__main__":
    unittest.main()
