"""Focused tests, NOT the complete direct-consumer acceptance suite.
A full acceptance must additionally create Task/required AGT with actual common Skills,
consume them through actual Operation, and record commands/input/source/version/
output/side-effects. These unit examples alone do not satisfy that acceptance.
Run during scoped implementation/verification; never during a read-only review.
"""
import copy
import datetime as dt
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import tempfile
import hashlib
import yaml

spec = importlib.util.spec_from_file_location("binding_check", Path(__file__).resolve().parents[1] / "binding_check.py")
bc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bc)

class BindingContractTests(unittest.TestCase):
    def fixture(self, work=None):
        h = "a" * 64
        now = dt.datetime(2030, 1, 1, 12, tzinfo=dt.timezone.utc)
        b = {"schema_version": "1.0", "task_id": "NEUTRAL-T1", "request_id": "REQ1", "run_id": "RUN1",
             "kind": "development", "work_style": work, "dev_style": "neutral", "repo": "/neutral/repo",
             "profile": "neutral", "selection_ref": "synthetic/selection", "goal_sha256": h,
             "source_hashes": {"synthetic/source": h}, "entry": {"path": "/neutral/entry/SKILL.md", "sha256": h},
             "private_binding": "synthetic/binding", "candidate": None, "rules_refs": [{"ref": "synthetic/rules", "sha256": h}],
             "skill_refs": [{"ref": "synthetic/skill", "sha256": h}], "upstream_required_refs": ["synthetic/upstream"],
             "upstream_evidence": [{"ref": "synthetic/upstream", "sha256": h, "required": True,
                                    "state": "completed", "decision": "satisfied", "decision_ref": "synthetic/decision", "decision_sha256": h}],
             "permissions": {"ref": "synthetic/permission", "read": True, "implement": False, "review": False},
             "budget": {"budget_id": "SYNTHETIC-1", "started_at": "2030-01-01T11:00:00+00:00",
                        "deadline_at": "2030-01-01T13:00:00+00:00", "consumed_minutes": 1},
             "writer": {"owner": "synthetic-owner", "receipt": "synthetic/lease", "paths": ["/neutral/repo"],
                        "valid_until": "2030-01-01T13:00:00+00:00"},
             "input_ref": "synthetic/input", "return_ref": "synthetic/return", "agt_required": True}
        c = copy.deepcopy(b)
        c.update({"legacy_selector_conflict": False, "read_only_target": False, "selector_known": True,
                  "entry_realpath_and_hash_verified": True, "rules_refs_verified": True,
                  "skill_refs_verified": True, "upstream_evidence_verified": True, "upstream_conditions_satisfied": True, "permissions_verified": True,
                  "budget_history_verified": True, "writer_verified": True, "same_version_plan_approved": False})
        if work == "aipm":
            c.update(inception_task_registered=True, aipm_upstream_task_ids=["SYNTHETIC-UP"],
                     canonical_upstream_required_refs=["synthetic/upstream"],
                     canonical_upstream_hashes={"synthetic/upstream": h})
        return b, c, now

    def test_selected_combinations(self):
        for work in (None, "aipm"):
            b, c, now = self.fixture(work); block = bc.instructions(b)
            self.assertEqual(bc.check(b, c, block, block, now)["route"], "selected_development")

    def test_ordinary_never_reads_private(self):
        for kind in ("development", "non_development"):
            for work in (None, "aipm"):
                b = {"kind": kind, "work_style": work, "dev_style": None, "entry": None, "private_binding": None}
                c = dict(b); c["legacy_selector_conflict"] = False
                self.assertEqual(bc.check(b, c, "", None, dt.datetime.now(dt.timezone.utc))["private_reads"], 0)

    def test_ordinary_conflict_or_unknown_stops(self):
        b = {"kind": "non_development", "work_style": None, "dev_style": None, "entry": None, "private_binding": None}
        for conflict in (True, None):
            c = dict(b); c["legacy_selector_conflict"] = conflict
            with self.assertRaises(bc.BindingError): bc.check(b, c, "", None, dt.datetime.now(dt.timezone.utc))

    def test_selected_negative_observation_requires_false(self):
        for flag in ("legacy_selector_conflict", "read_only_target"):
            for value in (True, None):
                b, c, now = self.fixture(); c[flag] = value; block = bc.instructions(b)
                with self.assertRaises(bc.BindingError): bc.check(b, c, block, block, now)

    def test_mismatch(self):
        for key in ("task_id", "run_id", "request_id", "goal_sha256", "source_hashes", "profile", "selection_ref"):
            b, c, now = self.fixture(); b[key] = "wrong"
            with self.assertRaises(bc.BindingError): bc.check(b, c, bc.instructions(b), bc.instructions(b), now)

    def test_missing_carried_instructions(self):
        b, c, now = self.fixture(); block = bc.instructions(b)
        for task, agt in (("", block), (block, ""), (block + block, block)):
            with self.assertRaises(bc.BindingError): bc.check(b, c, task, agt, now)

    def test_actual_fact_gates(self):
        for flag in ("entry_realpath_and_hash_verified", "selector_known", "rules_refs_verified", "skill_refs_verified",
                     "upstream_evidence_verified", "upstream_conditions_satisfied", "permissions_verified", "budget_history_verified", "writer_verified"):
            b, c, now = self.fixture(); c[flag] = False; block = bc.instructions(b)
            with self.assertRaises(bc.BindingError): bc.check(b, c, block, block, now)

    def test_mixed_binding_blocks(self):
        b, c, now = self.fixture(); block = bc.instructions(b)
        other = copy.deepcopy(b); other["run_id"] = "OTHER-RUN"; mixed = block + bc.instructions(other)
        for task, agt in ((mixed, block), (block, mixed)):
            with self.assertRaises(bc.BindingError): bc.check(b, c, task, agt, now)

    def test_upstream_completion_separate_from_observation(self):
        for key, value in (("state", "incomplete"), ("state", "unknown"), ("decision", "unsatisfied"), ("decision", "unknown")):
            b, c, now = self.fixture(); b["upstream_evidence"][0][key] = value
            c["upstream_evidence"] = copy.deepcopy(b["upstream_evidence"]); block = bc.instructions(b)
            with self.assertRaises(bc.BindingError): bc.check(b, c, block, block, now)
        b, c, now = self.fixture(); b["upstream_evidence"] = []; c["upstream_evidence"] = []; block = bc.instructions(b)
        with self.assertRaises(bc.BindingError): bc.check(b, c, block, block, now)
        b, c, now = self.fixture(); c["upstream_conditions_satisfied"] = None; block = bc.instructions(b)
        with self.assertRaises(bc.BindingError): bc.check(b, c, block, block, now)

    def test_permission_time_consumption_writer(self):
        for group, key, value in (("permissions", "read", False), ("budget", "consumed_minutes", None),
                                  ("budget", "deadline_at", "2030-01-01T12:00:00+00:00"),
                                  ("writer", "valid_until", "2030-01-01T12:00:00+00:00")):
            b, c, now = self.fixture(); b[group][key] = value; c[group][key] = value; block = bc.instructions(b)
            with self.assertRaises(bc.BindingError): bc.check(b, c, block, block, now)

    def test_before_plan_approval(self):
        b, c, now = self.fixture(); b["permissions"]["implement"] = True; c["permissions"]["implement"] = True
        with self.assertRaises(bc.BindingError): bc.check(b, c, bc.instructions(b), bc.instructions(b), now, "implement")

    def test_wrong_result_run(self):
        b, c, now = self.fixture(); decision = bc.check(b, c, bc.instructions(b), bc.instructions(b), now)
        result = {k: b[k] for k in ("task_id", "request_id", "run_id", "work_style", "dev_style", "candidate")}
        result.update({"binding_sha256": decision["binding_sha256"], "status": "stop", "stop_reason": "fixture-stop",
                       "evidence_refs": ["synthetic/evidence"], "ac_judgments": [{"ac": "AC1", "judgment": "unknown", "evidence_ref": "synthetic/evidence"}]})
        self.assertEqual(bc.check_result(result, b)["status"], "stop")
        result["run_id"] = "another"
        with self.assertRaises(bc.BindingError): bc.check_result(result, b)


class RegisteredCallerTests(BindingContractTests):
    """Canonical-file caller cases; still not the fresh-context Skill trial."""
    def prepare(self, root, work="aipm"):
        root = Path(root)
        (root / "Documents").mkdir()
        (root / "Documents/story.md").write_text("synthetic story map v1")
        (root / "Documents/decision.yaml").write_text("decision: satisfied\nsource: synthetic\n")
        (root / "intent.yaml").write_text(yaml.safe_dump({"work_style": work, "dev_style": "neutral"}))
        tasks = [{"id": "UP-INIT", "status": "completed", "dependencies": []},
                 {"id": "UP-FINAL", "status": "completed", "dependencies": ["UP-INIT"],
                  "output": ["Documents/story.md"]},
                 {"id": "NEUTRAL-T1", "id_status": "registered", "status": "pending",
                  "development_scope": {"kind": "development"},
                  "dependencies": ["UP-FINAL"], "aipm_upstream_tasks": ["UP-FINAL"]}]
        (root / "backlog.yaml").write_text(yaml.safe_dump({"tasks": tasks}))
        b, c, now = self.fixture(work)
        h = hashlib.sha256((root / "Documents/story.md").read_bytes()).hexdigest()
        dh = hashlib.sha256((root / "Documents/decision.yaml").read_bytes()).hexdigest()
        b["permissions"].update(interview=True, plan=True)
        b["upstream_required_refs"] = ["Documents/story.md"]
        b["upstream_evidence"] = [{"ref": "Documents/story.md", "sha256": h, "required": True,
                                  "state": "completed", "decision": "satisfied",
                                  "decision_ref": "Documents/decision.yaml", "decision_sha256": dh}]
        for key in ("permissions", "upstream_required_refs", "upstream_evidence"):
            c[key] = copy.deepcopy(b[key])
        return b, c, now, tasks

    def invoke(self, root, b, c, now, phase="interview"):
        block = bc.instructions(b)
        return bc.check_registered(b, c, block, block, now, layer=root, phase=phase)

    def test_canonical_normal_all_preapproval_phases(self):
        with tempfile.TemporaryDirectory() as root:
            b,c,now,tasks = self.prepare(root)
            for phase in ("read", "interview", "plan"):
                self.assertEqual(self.invoke(root,b,c,now,phase)["route"], "selected_development")

    def test_canonical_unregistered_missing_and_dependency_closure(self):
        mutations = (lambda ts: ts[-1].pop("id_status"), lambda ts: ts.pop(),
                     lambda ts: ts[0].update(status="pending"),
                     lambda ts: ts[1].update(status="pending"),
                     lambda ts: ts[0].update(dependencies=["UP-FINAL"]),
                     lambda ts: ts[-1].update(aipm_upstream_tasks=[]),
                     lambda ts: ts[-1].update(dependencies=[]),
                     lambda ts: ts[1].update(output=[]),
                     lambda ts: ts.append(copy.deepcopy(ts[-1])))
        for mutate in mutations:
            with self.subTest(mutation=mutate), tempfile.TemporaryDirectory() as root:
                b,c,now,tasks = self.prepare(root);mutate(tasks)
                (Path(root)/"backlog.yaml").write_text(yaml.safe_dump({"tasks":tasks}))
                with self.assertRaises(bc.BindingError):self.invoke(root,b,c,now)

    def test_empty_binding_cannot_hide_registered_outputs(self):
        with tempfile.TemporaryDirectory() as root:
            b,c,now,tasks = self.prepare(root)
            for value in (b,c):value.update(upstream_required_refs=[],upstream_evidence=[])
            with self.assertRaisesRegex(bc.BindingError,"aipm_canonical_upstream_mismatch"):
                self.invoke(root,b,c,now)

    def test_current_style_lie_cannot_bypass_canonical(self):
        with tempfile.TemporaryDirectory() as root:
            b,c,now,tasks = self.prepare(root)
            b["work_style"]=None;c["work_style"]=None
            with self.assertRaisesRegex(bc.BindingError,"canonical_selector_mismatch"):
                self.invoke(root,b,c,now)

    def test_changed_deleted_or_escaping_output_stops(self):
        for mode in ("change", "delete", "escape"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                b,c,now,tasks = self.prepare(root);p=Path(root)/"Documents/story.md"
                if mode=="change":p.write_text("changed since binding")
                elif mode=="delete":p.unlink()
                else:
                    tasks[1]["output"]=["../outside.md"]
                    (Path(root)/"backlog.yaml").write_text(yaml.safe_dump({"tasks":tasks}))
                with self.assertRaises(bc.BindingError):self.invoke(root,b,c,now)

    def test_dev_style_only_does_not_require_aipm(self):
        with tempfile.TemporaryDirectory() as root:
            b,c,now,tasks = self.prepare(root,work=None)
            tasks[-1]["aipm_upstream_tasks"]=[];tasks[-1]["dependencies"]=[]
            (Path(root)/"backlog.yaml").write_text(yaml.safe_dump({"tasks":tasks}))
            for value in (b,c):value.update(upstream_required_refs=[],upstream_evidence=[])
            self.assertEqual(self.invoke(root,b,c,now)["route"],"selected_development")

    def test_decision_version_missing_and_escape_stops(self):
        # Leave decision outside output deliberately to exercise its own gate.
        for mode in ("change", "delete", "absolute", "escape"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                b,c,now,tasks = self.prepare(root)
                decision = Path(root)/"Documents/decision.yaml"
                if mode == "change": decision.write_text("decision: unsatisfied\n")
                elif mode == "delete": decision.unlink()
                else:
                    for value in (b,c):
                        value["upstream_evidence"][0]["decision_ref"] = (
                            str(decision) if mode == "absolute" else "../outside.yaml")
                with self.assertRaises(bc.BindingError): self.invoke(root,b,c,now)

    def test_complete_output_includes_decision(self):
        with tempfile.TemporaryDirectory() as root:
            b,c,now,tasks = self.prepare(root)
            tasks[1]["output"].append("Documents/decision.yaml")
            (Path(root)/"backlog.yaml").write_text(yaml.safe_dump({"tasks":tasks}))
            evidence=copy.deepcopy(b["upstream_evidence"][0])
            evidence.update(ref="Documents/decision.yaml",sha256=evidence["decision_sha256"])
            for value in (b,c):
                value["upstream_required_refs"].append(evidence["ref"])
                value["upstream_evidence"].append(copy.deepcopy(evidence))
            self.assertEqual(self.invoke(root,b,c,now)["route"],"selected_development")

    def test_canonical_ordinary_no_private_path_access(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            (root/"intent.yaml").write_text(yaml.safe_dump({"work_style":"aipm","dev_style":None}))
            (root/"backlog.yaml").write_text(yaml.safe_dump({"tasks":[{"id":"ORD","development_scope":{"kind":"non_development"}}]}))
            b={"task_id":"ORD","kind":"non_development","work_style":"aipm","dev_style":None,"entry":None,"private_binding":None}
            c={**b,"legacy_selector_conflict":False}
            result=bc.check_registered(b,c,"",None,dt.datetime.now(dt.timezone.utc),layer=root)
            self.assertEqual(result["private_reads"],0)


# <skills>/ai-plc/extensions/tests: works in the source tree (core/skills) and the installed tree (.claude/skills).
AI_PLC = Path(__file__).resolve().parents[2]
CATALOG_VERSION = next(x["addon_version"] for x in yaml.safe_load((AI_PLC / "references/addon-catalog.yaml").read_text())["addons"] if x["addon_id"] == "aipm")
BUNDLED = {"addon_id": "aipm", "source": "bundled", "addon_version": CATALOG_VERSION}


class BundledCanonicalTests(RegisteredCallerTests):
    """The PM selected only as the bundled entry in intent.addons (no work_style). Synthetic only.
    The binding/current work_style value stays aipm or null."""
    def bundled_intent(self, root, **extra):
        (Path(root) / "intent.yaml").write_text(yaml.safe_dump({"dev_style": "neutral", "addons": [dict(BUNDLED)], **extra}))

    def test_bundled_only_passes_all_preapproval_phases(self):
        with tempfile.TemporaryDirectory() as root:
            b, c, now, tasks = self.prepare(root)
            self.bundled_intent(root)
            for phase in ("read", "interview", "plan"):
                self.assertEqual(self.invoke(root, b, c, now, phase)["route"], "selected_development")
            observed = bc.observe_registered_upstream(root, "NEUTRAL-T1")
            self.assertEqual(observed["canonical_work_style"], "aipm")
            self.assertEqual(bc.canonical_pm(Path(root).resolve(), yaml.safe_load((Path(root) / "intent.yaml").read_text())), "aipm")

    def test_bundled_only_current_null_lie_cannot_bypass(self):
        with tempfile.TemporaryDirectory() as root:
            b, c, now, tasks = self.prepare(root)
            self.bundled_intent(root)
            b["work_style"] = None; c["work_style"] = None
            with self.assertRaisesRegex(bc.BindingError, "canonical_selector_mismatch"):
                self.invoke(root, b, c, now)

    def test_legacy_and_bundled_both_read_as_aipm(self):
        with tempfile.TemporaryDirectory() as root:
            b, c, now, tasks = self.prepare(root)
            self.bundled_intent(root, work_style="aipm")
            self.assertEqual(self.invoke(root, b, c, now)["route"], "selected_development")

    def test_held_selection_stops(self):
        cases = ({"addons": [{"addon_id": "not-in-catalog", "source": "bundled", "addon_version": "1"}]},
                 {"addons": [dict(BUNDLED), dict(BUNDLED)]},
                 {"addons": [dict(BUNDLED)], "work_style": "other"},
                 {"work_style": "other"})
        for n, extra in enumerate(cases):
            with self.subTest(case=n), tempfile.TemporaryDirectory() as root:
                b, c, now, tasks = self.prepare(root)
                (Path(root) / "intent.yaml").write_text(yaml.safe_dump({"dev_style": "neutral", **extra}))
                with self.assertRaisesRegex(bc.BindingError, "addon_selection_held"):
                    self.invoke(root, b, c, now)
                with self.assertRaisesRegex(bc.BindingError, "addon_selection_held"):
                    bc.observe_registered_upstream(root, "NEUTRAL-T1")

    def test_neither_field_does_not_load_the_selector(self):
        with tempfile.TemporaryDirectory() as root:
            b, c, now, tasks = self.prepare(root, work=None)
            tasks[-1]["aipm_upstream_tasks"] = []; tasks[-1]["dependencies"] = []
            (Path(root) / "backlog.yaml").write_text(yaml.safe_dump({"tasks": tasks}))
            for value in (b, c): value.update(upstream_required_refs=[], upstream_evidence=[])
            with patch.object(bc, "_selector", side_effect=AssertionError("selector read")):
                self.assertEqual(self.invoke(root, b, c, now)["route"], "selected_development")

    def test_selector_unavailable_stops_and_restores_sys_path(self):
        with tempfile.TemporaryDirectory() as root:
            b, c, now, tasks = self.prepare(root)
            self.bundled_intent(root)
            saved, before = bc._SELECTOR, list(sys.path)
            try:
                bc._SELECTOR = None
                with patch("importlib.util.spec_from_file_location", return_value=None):
                    with self.assertRaisesRegex(bc.BindingError, "selector_unavailable"):
                        self.invoke(root, b, c, now)
                self.assertEqual(sys.path, before)
                bc._SELECTOR = None
                self.assertEqual(self.invoke(root, b, c, now)["route"], "selected_development")
                self.assertEqual(sys.path, before)
            finally:
                bc._SELECTOR = saved


# Reuse the fixtures only; the inherited cases are not collected twice.
for _cls in (BindingContractTests, RegisteredCallerTests):
    for _name in [n for n in vars(_cls) if n.startswith("test_")]:
        setattr(BundledCanonicalTests, _name, None)
del _cls, _name  # a module-level TestCase name would be collected again

if __name__ == "__main__":
    unittest.main()
