"""Build intent.addons / addon_init from an addon manifest (read-only).

Synthetic fixtures only.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml
SCRIPTS = Path(__file__).resolve().parents[1]   # .claude/skills/ai-plc/scripts (core/skills/ai-plc/scripts in the source tree)
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS / "tests")]
import plc_addon as addon
import plc_addon_binding as builder
from test_plc_addon import inventory, NOW

ROOT = SCRIPTS.parents[1]   # .claude/skills (core/skills in the source tree)


def make_layer(base):
    case = Path(base) / "layer"
    (case / "Documents/addon/forms").mkdir(parents=True)
    (case / "Context").mkdir()
    (case / "Documents/addon/guide.md").write_text("# 合成の案内\n")
    (case / "Documents/addon/common.md").write_text("# 合成の共通の約束\n")
    (case / "Documents/addon/forms/init.md").write_text("記録の箱の準備（合成）\n")
    (case / "Documents/addon/forms/weekly.md").write_text("週次の型（合成）\n")
    manifest = {"addon_id": "synthetic-pmo", "addon_version": "0.3",
                "guide": {"path": "guide.md", "version": "0.4"}, "common": {"path": "common.md", "version": "0.5"},
                "forms": [{"form_id": "project-init", "path": "forms/init.md", "version": "0.1"},
                          {"form_id": "weekly", "path": "forms/weekly.md", "version": "0.2"}],
                "init_form_id": "project-init", "read_limits": {"max_guide_items": 1, "max_form_items": 2}}
    (case / "Documents/addon/manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
    (case / "Context/addon-selection.md").write_text("- **選んだアドオン**：addon_id `synthetic-pmo`、addon_version `0.3`\n")
    (case / "intent.yaml").write_text(yaml.safe_dump({"scope_id": "SYNTH-LAUNCH", "status": "active"}, allow_unicode=True))
    return case, manifest


class BindingBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("PLCA1_TEST_ROOT"))
        self.case, self.manifest = make_layer(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write_manifest(self):
        (self.case / "Documents/addon/manifest.yaml").write_text(yaml.safe_dump(self.manifest, allow_unicode=True, sort_keys=False))

    def test_builds_binding_and_init_that_the_helper_accepts_without_writes(self):
        before = inventory(self.case)
        result = builder.build(self.case)
        self.assertEqual(result["route"], "binding", result)
        self.assertFalse(result["writes"])
        self.assertFalse(result["selection_created"])
        self.assertEqual(before, inventory(self.case))
        entry = result["addon_entry"]
        self.assertEqual(entry["forms"][0]["form_ref"]["relative_name"], "Documents/addon/forms/init.md")
        self.assertEqual(result["addon_init"]["declared_in"], "Documents/addon/manifest.yaml")
        # the caller writes the block; the existing helper then accepts it at Inception
        intent = yaml.safe_load((self.case / "intent.yaml").read_text())
        intent.update(yaml.safe_load(result["intent_block"]))
        (self.case / "intent.yaml").write_text(yaml.safe_dump(intent, allow_unicode=True, sort_keys=False))
        selection = {k: entry[k] for k in ("addon_id", "addon_version", "selection_ref")}
        for form_id, flag in (("project-init", True), ("weekly", False)):
            refs = addon.task_inputs(self.case, allowed_roots=[self.case], verified_selections=[selection], now=NOW,
                                     stage="inception", form_selected=True, form_id=form_id)
            self.assertEqual(refs["route"], "task_refs", refs)
            self.assertIs(refs["is_init_form"], flag)

    def test_manifest_without_init_returns_no_addon_init(self):
        del self.manifest["init_form_id"]
        self.write_manifest()
        result = builder.build(self.case)
        self.assertEqual(result["route"], "binding", result)
        self.assertIsNone(result["addon_init"])
        self.assertNotIn("addon_init", yaml.safe_load(result["intent_block"]))

    def test_selection_record_missing_or_naming_another_addon_holds(self):
        (self.case / "Context/addon-selection.md").write_text("addon_id `synthetic-pmo`、addon_version `0.2`\n")
        self.assertEqual(builder.build(self.case)["route"], "held")
        (self.case / "Context/addon-selection.md").unlink()
        self.assertEqual(builder.build(self.case)["route"], "held")

    def test_selection_values_must_match_exactly(self):
        for text in ("addon_id `synthetic-pmo-x`、addon_version `0.3`\n",
                     "addon_id `synthetic-pmo`、addon_version `0.30`\n",
                     "addon_id `synthetic-pmo`、addon_version `10.3`\n",
                     "addon_id `synthetic-pmo`\n",
                     "addon_id `synthetic-pmo`、addon_version `0.3`\naddon_id `other`、addon_version `0.3`\n",
                     "選んだ：synthetic-pmo 0.3\n"):
            with self.subTest(text=text):
                (self.case / "Context/addon-selection.md").write_text(text)
                self.assertEqual(builder.build(self.case)["route"], "held")
        (self.case / "Context/addon-selection.md").write_text("addon_id: synthetic-pmo\naddon_version: \"0.3\"\n")
        self.assertEqual(builder.build(self.case)["route"], "binding")  # quoted YAML value is accepted
        (self.case / "Context/addon-selection.md").write_text("addon_id: synthetic-pmo\naddon_version: 0.3\n")
        self.assertEqual(builder.build(self.case)["route"], "binding")

    def test_selection_ref_must_be_a_selection_record_under_context(self):
        for ref in ("Documents/addon/manifest.yaml", "intent.yaml", "Context/notes.md", "../Context/addon-selection.md"):
            with self.subTest(ref=ref):
                self.assertEqual(builder.build(self.case, selection_ref=ref)["route"], "held")
        self.assertEqual(builder.build(self.case, addon_dir=".")["route"], "held")
        self.assertEqual(builder.build(self.case, addon_dir="Documents")["route"], "held")

    def test_invalid_manifests_hold(self):
        cases = [
            lambda m: m.update(unknown=True),
            lambda m: m.pop("guide"),
            lambda m: m.update(init_form_id="missing"),
            lambda m: m["forms"].append({"form_id": "weekly", "path": "forms/weekly.md", "version": "0.2"}),
            lambda m: m["forms"][0].update(path="../../outside.md"),
            lambda m: m["forms"][0].update(path="/etc/hosts"),
            lambda m: m["forms"][0].update(extra="x"),
            lambda m: m["read_limits"].update(max_form_items=1),
            lambda m: m.update(forms=[]),
        ]
        original = yaml.safe_dump(self.manifest)
        for change in cases:
            with self.subTest(change=change):
                self.manifest = yaml.safe_load(original)
                change(self.manifest)
                self.write_manifest()
                self.assertEqual(builder.build(self.case)["route"], "held")

    def test_missing_manifest_or_resource_holds(self):
        (self.case / "Documents/addon/forms/weekly.md").unlink()
        self.assertEqual(builder.build(self.case)["route"], "held")
        (self.case / "Documents/addon/manifest.yaml").unlink()
        self.assertEqual(builder.build(self.case)["route"], "held")

    def test_symlinked_resource_and_outside_addon_dir_hold(self):
        outside = Path(self.tmp.name) / "outside.md"
        outside.write_text("outside")
        (self.case / "Documents/addon/forms/weekly.md").unlink()
        (self.case / "Documents/addon/forms/weekly.md").symlink_to(outside)
        self.assertEqual(builder.build(self.case)["route"], "held")
        self.assertEqual(builder.build(self.case, addon_dir="../")["route"], "held")

    def test_cli_prints_json_and_exit_codes(self):
        ok = subprocess.run([sys.executable, "-B", str(SCRIPTS / "plc_addon_binding.py"), "--layer", str(self.case)],
                            capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn('"route": "binding"', ok.stdout)
        (self.case / "Context/addon-selection.md").unlink()
        held = subprocess.run([sys.executable, "-B", str(SCRIPTS / "plc_addon_binding.py"), "--layer", str(self.case)],
                              capture_output=True, text=True)
        self.assertEqual(held.returncode, 1)


if __name__ == "__main__":
    unittest.main()
