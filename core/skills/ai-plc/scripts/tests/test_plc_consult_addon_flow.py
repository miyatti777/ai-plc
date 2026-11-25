"""Caller/CLI and installed canonical contract checks; AI-flow proof is separate."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml
SCRIPTS = Path(__file__).resolve().parents[1]   # .claude/skills/ai-plc/scripts (core/skills/ai-plc/scripts in the source tree)
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS / "tests")]
import plc_addon as addon
import test_plc_addon as fixtures

SKILLS = SCRIPTS.parents[1]   # .claude/skills (core/skills in the source tree)


def strip_html_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def seam_sections(text):
    """Map each '## ' heading (without a trailing （…） note) to its body, ignoring HTML comments."""
    sections, current = {}, None
    for line in strip_html_comments(text).splitlines():
        if line.startswith("## "):
            current = re.sub(r"（[^（）]*）\s*$", "", line[3:]).strip()
            sections[current] = ""
        elif current is not None:
            sections[current] += line + "\n"
    return sections


class CallerFlowTests(unittest.TestCase):
    def test_cli_consumes_guide_and_emits_only_readonly_advice(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("PLCA1_TEST_ROOT")) as base:
            case, intent, backlog, selected = fixtures.make_case(base)
            before = fixtures.inventory(case)
            command = [sys.executable, "-B", str(SCRIPTS/"plc_addon.py"), "--layer", str(case),
                       "--read-root", str(case), "--selection", json.dumps(selected)]
            run = subprocess.run(command, capture_output=True, text=True, check=True)
            result = json.loads(run.stdout)
            self.assertEqual(result["route"], "operational_guidance")
            self.assertIn("週次判断", result["guide_data"][0]["text"])
            self.assertEqual(len(result["next_actions"]), 1)
            self.assertEqual(result["next_actions"][0]["entry"], "$plc-brief")
            self.assertIn("相談のみ", result["execution_note"])
            self.assertEqual(before, fixtures.inventory(case))
            cc = subprocess.run(command + ["--executor", "claude-code"], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(cc.stdout)["next_actions"][0]["entry"], "/plc-brief")
            self.assertEqual(before, fixtures.inventory(case))
            trial = subprocess.run(command+["--trial-requested"], capture_output=True, text=True)
            self.assertEqual(trial.returncode, 1)
            self.assertEqual(json.loads(trial.stdout)["route"], "held")
            self.assertEqual(before, fixtures.inventory(case))

    def test_canonical_entry_front_guard_and_single_next_contract(self):
        # Each SKILL is checked for a live front-guard line whose addon-seam.md link resolves and whose named
        # sections exist, and each clause is checked inside the section that owns it.
        seam_path = (SKILLS/"ai-plc/references/addon-seam.md").resolve()
        sections = seam_sections(seam_path.read_text())
        owners = {
            "全入口の前置条件": ("別の明示通常記録許可",),
            "通常consult / next": ("唯一のNext", "ReadCoverage", "自己再帰", "--executor claude-code",
                                   "--executor codex", "addon-read-scope.md", "手読み"),
        }
        for heading, terms in owners.items():
            with self.subTest(section=heading):
                self.assertIn(heading, sections)
                for term in terms:
                    self.assertIn(term, sections[heading])
        cases = ["plc-consult/SKILL.md", "plc-next/SKILL.md", "plc-backfill/SKILL.md"]
        # The public package has no 本人専用情報 line by default; when one is present it must follow the guard.
        for name in cases:
            with self.subTest(skill=name):
                path = SKILLS/name
                live = strip_html_comments(path.read_text())
                lines = live.splitlines()
                guard = [i for i, line in enumerate(lines) if line.startswith("**アドオンの前置判定")]
                self.assertEqual(len(guard), 1, "front-guard line missing or commented out")
                self.assertIn("Hold", live)
                line = lines[guard[0]]
                links = re.findall(r"\[addon-seam\.md\]\(([^)#\s]+)\)", line)
                self.assertTrue(links, "front-guard line has no addon-seam.md link")
                for link in links:
                    target = (path.parent/link).resolve()
                    self.assertTrue(target.is_file(), f"link target does not exist: {link}")
                    self.assertEqual(target, seam_path)
                named = re.findall(r"「([^」]+)」", line.split("addon-seam.md", 1)[1].split("を最初に適用", 1)[0])
                self.assertTrue(named, "front-guard line names no addon-seam.md section")
                for section in named:
                    self.assertIn(section, sections, f"named section missing in addon-seam.md: {section}")
                personal = [i for i, line in enumerate(lines) if line.startswith("**本人専用情報:**")]
                self.assertLessEqual(len(personal), 1)
                if personal:
                    self.assertLess(guard[0], personal[0])
        consult = strip_html_comments((SKILLS/cases[0]).read_text())
        self.assertIn("5分類", consult)
        self.assertIn("実呼出", consult)
        scope = (SKILLS/"ai-plc/references/addon-read-scope.md").read_text()
        for term in ("intent.yaml", "backlog.yaml", "selection_ref", "command_template_ref", "64KiB", "256KiB", "max_form_items", "temp/cache"):
            self.assertIn(term, scope)

    def test_common_projection_has_no_case_metadata_and_exact_source_types(self):
        contract = yaml.safe_load(addon.CONTRACT.read_text())
        self.assertEqual(contract["schema_version"], "0.1")
        self.assertNotIn("source", contract)
        self.assertNotIn("project_id", contract)
        self.assertNotIn("scope_id", contract)
        self.assertIsNone(re.search(r"\bL-\d{4}", addon.CONTRACT.read_text()))
        source_name = os.environ.get("PLCA1_SOURCE_SPEC")
        if not source_name:
            self.skipTest("Provide actual original specification for projection equality check")
        source_path = Path(source_name)
        self.assertEqual(hashlib.sha256(source_path.read_bytes()).hexdigest(), contract["source_spec_sha256"])
        source = yaml.safe_load(source_path.read_text())
        for key, value in contract["types"].items():
            original = dict(source[key])
            if key == "TrialPolicy":
                original.pop("current_request_is_trial", None)
            self.assertEqual(value, original)


if __name__ == "__main__":
    unittest.main()
