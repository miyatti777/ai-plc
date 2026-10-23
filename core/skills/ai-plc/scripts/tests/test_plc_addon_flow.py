"""A2 real helper/CLI integration and refusal boundaries. AI proof is separate."""
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml
SCRIPTS = Path(__file__).resolve().parents[1]   # .claude/skills/ai-plc/scripts (core/skills/ai-plc/scripts in the source tree)
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS / "tests")]
import plc_addon as addon
from test_plc_addon import make_case, inventory, NOW


class TaskInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("PLCA1_TEST_ROOT"))
        self.case, self.intent, self.backlog, self.selection = make_case(self.tmp.name)
        self.backlog["execution_contract"]["current_task"] = "DEMO-TASK"
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

    def register(self):
        result = self.call("inception")
        self.assertEqual(result["route"], "task_refs")
        self.backlog["tasks"][0]["addon_refs"] = result["addon_refs"]
        self.save()
        return result

    def agent(self):
        result = self.call("construction")
        self.assertEqual(result["route"], "task_refs")
        self.backlog["construction"]["tasks"] = ["DEMO-TASK"]
        self.backlog["tasks"][0]["command_template_ref"] = "agent.md"
        (self.case / "agent.md").write_text("# Synthetic agent\n<!-- ADDON_REFS:BEGIN -->\n" +
            result["reference_block"] + "<!-- ADDON_REFS:END -->\n")
        self.save()

    def test_generation_transport_and_consumption_without_writes(self):
        before = inventory(self.case)
        with mock.patch.object(addon, "_bytes", wraps=addon._bytes) as reader:
            result = self.call("inception")
            self.assertFalse(any(Path(c.args[0]).name == "form.md" for c in reader.call_args_list))
        self.assertEqual(before, inventory(self.case))
        self.register(); self.agent()
        before = inventory(self.case)
        result = self.call()
        self.assertEqual(result["route"], "task_inputs")
        self.assertEqual(result["read_coverage"]["retrieved_count"], 3)
        self.assertEqual(result["input_data"][-1]["role"], "form_ref")
        self.assertIn("型本文", result["input_data"][-1]["text"])
        self.assertFalse(result["dispatch"]); self.assertFalse(result["writes"])
        self.assertEqual(before, inventory(self.case))

    def test_cli_three_stages_and_original_consult_default(self):
        self.register(); self.agent()
        base = [sys.executable, "-B", str(Path(addon.__file__)), "--layer", str(self.case),
                "--read-root", str(self.case), "--selection", json.dumps(self.selection)]
        for stage in ("inception", "construction"):
            run = subprocess.run(base + ["--stage", stage, "--form-selected", "--form-id", "weekly-judgment",
                "--task-id", "DEMO-TASK", "--task-version", "v1"], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(json.loads(run.stdout)["route"], "task_refs")
        # Fixture clock is historical; CLI gets current time and must refuse expired operation.
        self.backlog["execution_budget"].update(started_at=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=1)).isoformat(),
            deadline=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=5)).isoformat())
        self.save()
        run = subprocess.run(base + ["--stage", "operation", "--form-selected", "--task-id", "DEMO-TASK",
            "--task-version", "v1", "--approved-task", "DEMO-TASK"], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(json.loads(run.stdout)["route"], "task_inputs")
        normal = subprocess.run(base, capture_output=True, text=True)
        self.assertEqual(json.loads(normal.stdout)["route"], "operational_guidance")

    def test_trial_precedes_every_read_for_all_stages(self):
        for stage in ("inception", "construction", "operation"):
            with mock.patch.object(addon, "_bytes", side_effect=AssertionError("no read")):
                self.assertEqual(self.call(stage, trial_requested=True)["route"], "held")
                self.assertEqual(self.call(stage, no_write_requested=None)["route"], "held")
        self.intent["trial_policy"] = None; self.save()
        self.assertEqual(self.call("inception")["route"], "held")

    def test_unselected_legacy_vs_missing_present_empty_and_removed_binding(self):
        self.assertEqual(self.call("inception", form_selected=False)["route"], "unselected")
        self.assertEqual(self.call(form_selected=False)["route"], "unselected")
        self.assertEqual(self.call()["route"], "held")
        for value in (None, [], [None], [{"addon_id": "wrong"}]):
            self.backlog["tasks"][0]["addon_refs"] = value; self.save()
            self.assertEqual(self.call(form_selected=False)["route"], "held")
        self.register(); self.intent.pop("addons"); self.save()
        self.assertEqual(self.call()["route"], "held")

    def test_task_selection_versions_form_hash_and_multiple_refs_hold(self):
        self.register()
        self.assertEqual(self.call(task_version="new")["route"], "held")
        self.assertEqual(self.call(form_id="other")["route"], "held")
        self.assertEqual(self.call(verified_selections=[])["route"], "held")
        self.backlog["tasks"][0]["addon_refs"] *= 2; self.save()
        self.assertEqual(self.call()["route"], "held")
        self.register(); (self.case / "form.md").write_text("unexpected new version")
        self.assertEqual(self.call()["route"], "held")

    def test_current_form_selection_removed_with_registered_refs_holds_before_resources(self):
        self.register()
        before = inventory(self.case)
        for stage in ("construction", "operation"):
            with mock.patch.object(addon, "_bytes", wraps=addon._bytes) as reader:
                result = self.call(stage, form_selected=False)
                self.assertEqual(result["route"], "held")
                self.assertFalse(any(Path(c.args[0]).name in ("guide.md", "common.md", "form.md")
                                     for c in reader.call_args_list))
        self.assertEqual(before, inventory(self.case))

    def test_agt_missing_stale_duplicate_and_outside_paths_hold(self):
        self.register(); self.agent()
        (self.case / "agent.md").write_text("no reference block")
        self.assertEqual(self.call()["route"], "held")
        self.agent(); body = (self.case / "agent.md").read_text()
        (self.case / "agent.md").write_text(body.replace("weekly-judgment", "other"))
        self.assertEqual(self.call()["route"], "held")
        (self.case / "agent.md").write_text(body + body)
        self.assertEqual(self.call()["route"], "held")
        self.backlog["tasks"][0]["command_template_ref"] = "../agent.md"; self.save()
        self.assertEqual(self.call()["route"], "held")

    def test_contract_current_task_deadline_reserve_and_upstream(self):
        self.register(); original = copy.deepcopy(self.backlog)
        changes = [lambda b: b["execution_contract"].update(current_task="other"),
                   lambda b: b["execution_contract"]["task_versions"].update({"DEMO-TASK": "new"}),
                   lambda b: b["execution_budget"].update(deadline=(NOW-dt.timedelta(seconds=1)).isoformat()),
                   lambda b: b["execution_budget"].update(recording_reserved_from=(NOW-dt.timedelta(seconds=1)).isoformat()),
                   lambda b: b["tasks"][0].update(dependencies=["absent"]),
                   lambda b: b["tasks"][0].update(status="completed")]
        for change in changes:
            self.backlog = copy.deepcopy(original); change(self.backlog); self.save()
            self.assertEqual(self.call()["route"], "held")
        self.backlog = original; self.save()
        self.assertEqual(self.call(approved_task_ids=[])["route"], "held")

    def test_page_root_symlink_and_source_shift_hold_without_writes(self):
        self.register()
        self.assertEqual(self.call(allowed_roots=[self.case / "missing"])["route"], "held")
        ref = self.intent["addons"][0]["forms"][0]["form_ref"]
        page = {"kind": "page", "scope": "case", "version": "0.1", "sha256": "1"*64, "resource_ref": "synthetic"}
        self.intent["addons"][0]["forms"][0]["form_ref"] = page
        self.backlog["tasks"][0]["addon_refs"][0]["form_ref"] = page; self.save()
        self.assertEqual(self.call()["route"], "held")
        self.intent["addons"][0]["forms"][0]["form_ref"] = ref
        self.backlog["tasks"][0]["addon_refs"][0]["form_ref"] = ref; self.save()
        raw = (self.case / "form.md").read_bytes(); (self.case / "form.md").unlink()
        (Path(self.tmp.name) / "outside.md").write_bytes(raw)
        (self.case / "form.md").symlink_to(Path(self.tmp.name) / "outside.md")
        self.assertEqual(self.call()["route"], "held")

    def test_projection_preserves_all_five_source_types(self):
        source_name = os.environ.get("PLCA1_SOURCE_SPEC")
        if not source_name:
            self.skipTest("actual original spec not provided")
        source = yaml.safe_load(Path(source_name).read_text())
        old = yaml.safe_load(addon.CONTRACT.read_text()); new = yaml.safe_load(addon.TASK_CONTRACT.read_text())
        self.assertEqual(new["schema_version"], "0.2")
        self.assertEqual({k: new["types"][k] for k in old["types"]}, old["types"])
        self.assertEqual(new["types"]["TaskAddonRef"], source["TaskAddonRef"])
        self.assertFalse(any(k in new for k in ("source", "project_id", "scope_id")))


if __name__ == "__main__":
    unittest.main()
