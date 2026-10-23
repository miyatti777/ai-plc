"""Which addons are selected (bundled catalog, legacy work_style alias, case bindings).

Synthetic fixtures only (synthetic-addon / synthetic-method). Read-only: intent bytes never change.
"""
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml
SCRIPTS = Path(__file__).resolve().parents[1]   # .claude/skills/ai-plc/scripts (core/skills/ai-plc/scripts in the source tree)
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS / "tests")]
import plc_addon_binding as builder
import plc_addon_select as select
from test_plc_addon import inventory

ROOT = SCRIPTS.parents[1]   # .claude/skills (core/skills in the source tree)
REFS = SCRIPTS.parent / "references"
RECEIPT = "Context/aipm_recommendation/receipts/r1.json"


class SelectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("PLCA1_TEST_ROOT"))
        self.case = Path(self.tmp.name) / "layer"
        (self.case / "Context/aipm_recommendation/receipts").mkdir(parents=True)
        (self.case / RECEIPT).write_text(json.dumps({"kind": "user_reported", "choice": "aipm", "answer": "AIPM方式で進める"}))
        self.intent = {"scope_id": "SYNTH-SELECT", "status": "active"}

    def tearDown(self):
        self.tmp.cleanup()

    def write_intent(self, **fields):
        data = dict(self.intent, **fields)
        (self.case / "intent.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))

    def case_addon(self, addon_id, profile=None, folder=None):
        """Build one case AddonBinding with the existing builder; profile=None writes no ADDON_PROFILE block."""
        folder = folder or ("Documents/" + addon_id)
        base = self.case / folder
        (base / "forms").mkdir(parents=True)
        (base / "guide.md").write_text("# 合成の案内\n")
        common = "# 合成の共通の約束\n"
        if profile is not None:
            common += "\n" + select.PROFILE_BEGIN + "\nexclusive_group: " + profile + "\n" + select.PROFILE_END + "\n"
        (base / "common.md").write_text(common)
        (base / "forms/weekly.md").write_text("週次の型（合成）\n")
        manifest = {"addon_id": addon_id, "addon_version": "0.1", "guide": {"path": "guide.md", "version": "0.1"},
                    "common": {"path": "common.md", "version": "0.1"},
                    "forms": [{"form_id": "weekly", "path": "forms/weekly.md", "version": "0.1"}],
                    "read_limits": {"max_guide_items": 1, "max_form_items": 1}}
        (base / "manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
        selection = "Context/" + addon_id + "-selection.md"
        (self.case / selection).write_text("addon_id `" + addon_id + "`、addon_version `0.1`\n")
        result = builder.build(self.case, addon_dir=folder, selection_ref=selection)
        self.assertEqual(result["route"], "binding", result)
        return result["addon_entry"]

    def run_select(self, roots=True, **kw):
        before = inventory(self.case)
        result = select.selected_addons(self.case, read_roots=[self.case] if roots else None, **kw)
        self.assertEqual(before, inventory(self.case), "selected_addons must not write")
        self.assertFalse(result["writes"])
        return result

    def held(self, result, code):
        self.assertEqual(result["route"], "held", result)
        self.assertEqual(result["hold_reasons"], [code], result)

    # 1 読み替え
    def test_legacy_work_style_reads_as_bundled_aipm_without_rewriting_intent(self):
        self.write_intent(work_style="aipm", work_style_source=RECEIPT)
        raw = (self.case / "intent.yaml").read_bytes()
        result = self.run_select()
        self.assertEqual((result["route"], result["method"], result["work_style_value"]), ("selected", "aipm", "aipm"))
        entry = result["selected"][0]
        self.assertEqual((entry["via"], entry["source"], entry["addon_version"], entry["init_record"]),
                         ("legacy_alias", "bundled", "2.0", "mode_init"))
        self.assertEqual(entry["entry"], ".claude/skills/aipm-guided/SKILL.md")
        self.assertFalse(result["has_case_addons"])
        self.assertEqual(raw, (self.case / "intent.yaml").read_bytes())

    # 2 両方の欄
    def test_both_fields_are_one_selection(self):
        self.write_intent(work_style="aipm", addons=[{"addon_id": "aipm", "source": "bundled", "addon_version": "2.0",
                                                     "selection_ref": RECEIPT}])
        result = self.run_select()
        self.assertEqual(len(result["selected"]), 1, result)
        self.assertEqual(result["selected"][0]["via"], "both")
        self.assertEqual(result["notes"], [])

    def test_bundled_entry_alone_selects_aipm(self):
        self.write_intent(addons=[{"addon_id": "aipm", "source": "bundled", "addon_version": "2.0", "selection_ref": RECEIPT}])
        result = self.run_select()
        self.assertEqual((result["method"], result["selected"][0]["via"], result["work_style_value"]),
                         ("aipm", "addons", "aipm"))

    # 3 値の衝突
    def test_conflicting_work_style_with_bundled_aipm_holds(self):
        self.write_intent(work_style="other", addons=[{"addon_id": "aipm", "source": "bundled", "addon_version": "2.0"}])
        self.held(self.run_select(), "work_style_conflict")

    def test_unknown_work_style_holds_as_today(self):
        self.write_intent(work_style="other")
        self.held(self.run_select(), "unsupported_work_style")

    # 4 目録に無い bundled
    def test_bundled_not_in_catalog_holds(self):
        self.write_intent(addons=[{"addon_id": "synthetic-addon", "source": "bundled", "addon_version": "0.1"}])
        self.held(self.run_select(), "bundled_not_in_catalog")

    def test_bundled_with_case_fields_holds(self):
        self.write_intent(addons=[{"addon_id": "aipm", "source": "bundled", "addon_version": "2.0", "guide_ref": {}}])
        self.held(self.run_select(), "bundled_invalid_fields")
        self.write_intent(addons=[{"addon_id": "aipm", "source": "bundled"}])
        self.held(self.run_select(), "bundled_invalid_fields")

    def test_unknown_source_and_duplicate_bundled_hold(self):
        self.write_intent(addons=[{"addon_id": "aipm", "source": "case", "addon_version": "2.0"}])
        self.held(self.run_select(), "unknown_source")
        one = {"addon_id": "aipm", "source": "bundled", "addon_version": "2.0"}
        self.write_intent(addons=[one, dict(one)])
        self.held(self.run_select(), "duplicate_bundled")

    # 5 同じ組から2件
    def test_bundled_and_declared_case_method_hold(self):
        entry = self.case_addon("synthetic-method", profile="work_method")
        self.write_intent(work_style="aipm", work_style_source=RECEIPT, addons=[entry])
        self.held(self.run_select(), "exclusive_group_multiple")

    def test_two_declared_case_methods_hold(self):
        a = self.case_addon("synthetic-method", profile="work_method")
        b = self.case_addon("synthetic-method-b", profile="work_method")
        self.write_intent(addons=[a, b])
        self.held(self.run_select(), "exclusive_group_multiple")

    def test_two_bundled_rows_in_one_group_hold(self):
        catalog = yaml.safe_load((REFS / "addon-catalog.yaml").read_text())
        second = dict(copy.deepcopy(catalog["addons"][0]), addon_id="synthetic-bundled", display_name="合成の同梱")
        second.pop("legacy_alias")
        catalog["addons"].append(second)
        path = Path(self.tmp.name) / "catalog.yaml"
        path.write_text(yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False))
        self.write_intent(work_style="aipm", addons=[{"addon_id": "synthetic-bundled", "source": "bundled", "addon_version": "2.0"}])
        self.held(self.run_select(catalog_path=path), "exclusive_group_multiple")

    def test_declared_case_method_alone_is_the_method(self):
        entry = self.case_addon("synthetic-method", profile="work_method")
        self.write_intent(addons=[entry])
        result = self.run_select()
        self.assertEqual((result["route"], result["method"], result["work_style_value"]), ("selected", "synthetic-method", None))
        self.assertTrue(result["has_case_addons"])

    # 6 宣言の無い持ち込み
    def test_undeclared_case_with_aipm_holds(self):
        entry = self.case_addon("synthetic-addon")
        self.write_intent(work_style="aipm", work_style_source=RECEIPT, addons=[entry])
        self.held(self.run_select(), "undeclared_case_with_method")
        self.held(self.run_select(roots=False), "undeclared_case_with_method")

    def test_unreadable_declaration_counts_as_undeclared(self):
        entry = self.case_addon("synthetic-addon", profile="none")
        self.write_intent(work_style="aipm", addons=[entry])
        self.held(self.run_select(roots=False), "undeclared_case_with_method")
        self.write_intent(addons=[entry])
        result = self.run_select(roots=False)
        self.assertEqual(result["case_addons"][0]["exclusive_group"], None)
        self.assertTrue(any("宣言を読めない" in n for n in result["notes"]), result)

    def test_undeclared_case_alone_does_not_hold(self):
        entry = self.case_addon("synthetic-addon")
        self.write_intent(addons=[entry])
        result = self.run_select()
        self.assertEqual((result["route"], result["method"], result["has_case_addons"]), ("selected", None, True))

    def test_case_declared_outside_group_combines_with_aipm(self):
        entry = self.case_addon("synthetic-addon", profile="none")
        self.write_intent(work_style="aipm", work_style_source=RECEIPT, addons=[entry])
        result = self.run_select()
        self.assertEqual((result["route"], result["method"]), ("selected", "aipm"), result)
        self.assertEqual(result["case_addons"], [{"addon_id": "synthetic-addon", "addon_version": "0.1", "exclusive_group": "none"}])

    # 7 selection_verified
    def test_receipt_choice_verifies(self):
        self.write_intent(work_style="aipm", work_style_source=RECEIPT)
        entry = self.run_select()["selected"][0]
        self.assertTrue(entry["selection_verified"])
        self.assertEqual(entry["selection_ref"], RECEIPT)

    def test_missing_source_is_unverified_but_still_selected(self):
        self.write_intent(work_style="aipm")
        result = self.run_select()
        self.assertEqual(result["method"], "aipm")
        self.assertFalse(result["selected"][0]["selection_verified"])
        self.assertTrue(any(n.startswith("選択の照合なし") for n in result["notes"]))

    def test_selection_record_naming_rules(self):
        (self.case / "Context/aipm-selection.md").write_text("本人の選択：案件管理はAIPM で進める\n")
        (self.case / "Context/other-selection.md").write_text("addon_id `synthetic-aipmx`\n")
        (self.case / "Context/notes.md").write_text("aipm を選んだ\n")
        (self.case / "Context/wrong.json").write_text(json.dumps({"kind": "user_reported", "choice": "standard"}))
        cases = {"Context/aipm-selection.md": True, "Context/other-selection.md": False,
                 "Context/notes.md": False, "Context/wrong.json": False, "../outside-selection.md": False,
                 "本人の明示選択（会話）": False}
        for ref, expected in cases.items():
            self.write_intent(work_style="aipm", work_style_source=ref)
            self.assertEqual(self.run_select()["selected"][0]["selection_verified"], expected, ref)

    def test_symlinked_selection_is_unverified(self):
        target = Path(self.tmp.name) / "outside-selection.md"
        target.write_text("aipm\n")
        os.symlink(target, self.case / "Context/link-selection.md")
        self.write_intent(work_style="aipm", work_style_source="Context/link-selection.md")
        self.assertFalse(self.run_select()["selected"][0]["selection_verified"])

    # 8 版の差
    def test_version_difference_is_a_note_not_a_hold(self):
        self.write_intent(addons=[{"addon_id": "aipm", "source": "bundled", "addon_version": "1.9", "selection_ref": RECEIPT}])
        result = self.run_select()
        self.assertEqual(result["route"], "selected")
        entry = result["selected"][0]
        self.assertEqual((entry["addon_version"], entry["catalog_version"]), ("1.9", "2.0"))
        self.assertIn("版の差：intent 1.9 / 目録 2.0（aipm）", result["notes"])

    # 解除・未選択
    def test_unselected_and_released(self):
        self.write_intent()
        self.assertEqual(self.run_select()["route"], "unselected")
        self.write_intent(addons=[])
        result = self.run_select()
        self.assertEqual((result["route"], result["method"], result["work_style_value"]), ("unselected", None, None))

    # hash 違い・宣言の形
    def test_common_hash_mismatch_holds(self):
        entry = self.case_addon("synthetic-addon", profile="none")
        (self.case / "Documents/synthetic-addon/common.md").write_text("# 書き換えた\n")
        self.write_intent(addons=[entry])
        self.held(self.run_select(), "case_profile_hash_mismatch")

    def test_invalid_profile_blocks_hold(self):
        for body in (select.PROFILE_BEGIN + "\nexclusive_group: none\n",
                     select.PROFILE_BEGIN + "\nexclusive_group: unknown_group\n" + select.PROFILE_END,
                     select.PROFILE_BEGIN + "\nexclusive_group: none\nextra: 1\n" + select.PROFILE_END):
            with self.subTest(body=body):
                folder = "Documents/a" + str(abs(hash(body)))
                entry = self.case_addon("synthetic-addon", folder=folder)
                common = self.case / folder / "common.md"
                common.write_text(body + "\n")
                entry["common_contract_ref"]["sha256"] = hashlib.sha256(common.read_bytes()).hexdigest()
                self.write_intent(addons=[entry])
                self.held(self.run_select(), "invalid_profile_declaration")

    def test_invalid_shapes_hold(self):
        self.write_intent(addons="aipm")
        self.held(self.run_select(), "invalid_addons")
        self.write_intent(addons=[{"addon_id": "synthetic-addon"}])
        self.held(self.run_select(), "invalid_case_binding")
        (self.case / "intent.yaml").write_text("- not a mapping\n")
        self.held(self.run_select(), "invalid_intent")
        (self.case / "intent.yaml").write_text("scope_id: A\nscope_id: B\n")
        self.held(self.run_select(), "invalid_intent")

    def test_intent_anchors_are_read_like_package_py(self):
        (self.case / "intent.yaml").write_text("scope_id: SYNTH\nwork_style: aipm\nx: &a {k: 1}\ny: *a\n")
        self.assertEqual(self.run_select()["method"], "aipm")

    # 壊れた入力は例外でなく Hold
    def test_non_string_work_style_holds(self):
        for value in (["aipm"], {"a": 1}, 1, True):
            with self.subTest(value=value):
                self.write_intent(work_style=value)
                self.held(self.run_select(), "unsupported_work_style")
        self.write_intent(work_style=["aipm"], addons=[{"addon_id": "aipm", "source": "bundled", "addon_version": "2.0"}])
        self.held(self.run_select(), "work_style_conflict")

    def test_missing_roots_count_as_unreadable(self):
        entry = self.case_addon("synthetic-addon", profile="none")
        self.write_intent(work_style="aipm", addons=[entry])
        missing = Path(self.tmp.name) / "no-such-root"
        result = select.selected_addons(self.case, read_roots=[missing])
        self.assertEqual(result["hold_reasons"], ["undeclared_case_with_method"], result)
        common = dict(entry, common_contract_ref=dict(entry["common_contract_ref"], scope="common"))
        self.write_intent(addons=[common])
        result = select.selected_addons(self.case, read_roots=[self.case], common_root=missing)
        self.assertEqual((result["route"], result["case_addons"][0]["exclusive_group"]), ("selected", None), result)

    def test_non_utf8_common_holds(self):
        entry = self.case_addon("synthetic-addon", profile="none")
        common = self.case / "Documents/synthetic-addon/common.md"
        common.write_bytes(b"\xff\xfe not utf-8")
        entry["common_contract_ref"]["sha256"] = hashlib.sha256(common.read_bytes()).hexdigest()
        self.write_intent(addons=[entry])
        self.held(self.run_select(), "invalid_profile_declaration")

    def test_catalog_init_must_be_a_mapping(self):
        catalog = yaml.safe_load((REFS / "addon-catalog.yaml").read_text())
        catalog["addons"][0]["init"] = "package.py init"
        path = Path(self.tmp.name) / "catalog.yaml"
        path.write_text(yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False))
        self.write_intent(work_style="aipm")
        self.held(self.run_select(catalog_path=path), "invalid_catalog")

    def test_unexpected_errors_become_invalid_input(self):
        self.write_intent(work_style="aipm")
        original = select._verify_selection
        select._verify_selection = lambda *a: (_ for _ in ()).throw(TypeError("synthetic"))
        try:
            self.held(self.run_select(), "invalid_input")
        finally:
            select._verify_selection = original

    def test_cli_returns_held_json_for_broken_input(self):
        self.write_intent(work_style={"a": 1})
        run = subprocess.run([sys.executable, "-B", str(SCRIPTS / "plc_addon_select.py"), "--layer", str(self.case),
                              "--read-root", str(Path(self.tmp.name) / "missing"), "--common-root", str(Path(self.tmp.name) / "missing2")],
                             capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual(json.loads(run.stdout)["hold_reasons"], ["unsupported_work_style"])
        self.assertEqual(run.stderr, "")
        run = subprocess.run([sys.executable, "-B", str(SCRIPTS / "plc_addon_select.py"), "--layer", str(Path(self.tmp.name) / "no-layer")],
                             capture_output=True, text=True, check=False)
        self.assertEqual((run.returncode, json.loads(run.stdout)["hold_reasons"]), (1, ["invalid_intent"]))

    # 目録・契約の形
    def test_catalog_shape(self):
        catalog = yaml.safe_load((REFS / "addon-catalog.yaml").read_text())
        self.assertEqual(list(catalog["exclusive_groups"]), ["work_method"])
        self.assertEqual(catalog["exclusive_groups"]["work_method"]["max_selected"], 1)
        self.assertEqual([r["addon_id"] for r in catalog["addons"]], ["aipm"])
        row = catalog["addons"][0]
        self.assertEqual(row["legacy_alias"], {"intent_field": "work_style", "value": "aipm", "selection_source_field": "work_style_source"})
        self.assertEqual(row["init"]["record"], "mode_init")
        self.assertTrue((ROOT / row["entry"].replace(".claude/skills/", "", 1)).is_file())
        schema = yaml.safe_load((ROOT / "aipm-guided/format_schema.yaml").read_text())
        self.assertEqual(row["addon_version"], str(schema["version"]))
        self.assertEqual(sorted(select.load_catalog()["rows"]), ["aipm"])

    def test_broken_catalog_holds(self):
        catalog = yaml.safe_load((REFS / "addon-catalog.yaml").read_text())
        catalog["addons"][0]["guide_ref"] = "x"
        path = Path(self.tmp.name) / "catalog.yaml"
        path.write_text(yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False))
        self.write_intent(work_style="aipm")
        self.held(self.run_select(catalog_path=path), "invalid_catalog")

    def test_contract_v04_derives_v03(self):
        v3 = yaml.safe_load((REFS / "addon-seam-contract_v0.3.yaml").read_text())
        v4 = yaml.safe_load((REFS / "addon-seam-contract_v0.4.yaml").read_text())
        self.assertEqual((v4["schema_version"], v4["derived_from"]), ("0.4", "0.3"))
        for name, body in v3["types"].items():
            self.assertEqual(v4["types"][name], body, name)
        self.assertEqual(v4["implemented_routes"], v3["implemented_routes"] + ["bundled_addon_selection_readonly"])
        for name in ("BundledAddonSelection", "AddonCatalog", "AddonProfileDeclaration", "LegacyAlias", "AddonSelectionResult"):
            self.assertEqual(v4["types"][name]["added_in"], "0.4")
        codes = set(v4["types"]["AddonSelectionResult"]["hold_reason_values"])
        source = (SCRIPTS / "plc_addon_select.py").read_text()
        used = set(re.findall(r'Hold\("([a-z_]+)"', source))
        self.assertEqual(used, codes)

    def test_contract_v05_adds_catalog_operations_only(self):
        v4 = yaml.safe_load((REFS / "addon-seam-contract_v0.4.yaml").read_text())
        v5 = yaml.safe_load((REFS / "addon-seam-contract_v0.5.yaml").read_text())
        self.assertEqual((v5["schema_version"], v5["derived_from"], v4["schema_version"]), ("0.5", "0.4", "0.4"))
        for name, body in v4["types"].items():
            if name != "AddonCatalog":
                self.assertEqual(v5["types"][name], body, name)
        cat4, cat5 = v4["types"]["AddonCatalog"], v5["types"]["AddonCatalog"]
        self.assertEqual(cat5["row_optional"], cat4["row_optional"] + ["operations"])
        self.assertEqual(cat5["accepted_catalog_schema_versions"], ["0.1", "0.2"])
        self.assertEqual(v5["implemented_routes"], v4["implemented_routes"])

    def test_catalog_operations(self):
        real = yaml.safe_load(select.CATALOG.read_text())
        ops = {o["name"]: o for o in select.load_catalog()["rows"]["aipm"]["operations"]}
        self.assertEqual(len(ops), 8)
        self.assertEqual({n for n, o in ops.items() if o["writes"]}, {"pm-issue", "pm-hypothesis", "pm-todo"})
        self.assertEqual({n for n, o in ops.items() if o.get("before_selection")}, {"pm-init"})
        for o in ops.values():
            self.assertTrue((ROOT / o["entry"].replace(".claude/skills/", "", 1)).is_file(), o["entry"])
        good = {"name": "pm-x", "entry": "a/b.md", "writes": False}
        bad = [[], "x", [dict(good, name="PM X")], [good, good], [dict(good, entry="/abs.md")], [dict(good, entry="../a.md")],
               [dict(good, writes="yes")], [dict(good, before_selection=1)], [dict(good, extra=1)], [{"name": "pm-x", "entry": "a.md"}]]
        for i, value in enumerate(bad):
            catalog = yaml.safe_load(select.CATALOG.read_text());catalog["addons"][0]["operations"] = value
            path = Path(self.tmp.name) / ("bad%d.yaml" % i);path.write_text(yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False))
            with self.assertRaises(select.Hold, msg=str(value)):
                select.load_catalog(path)
        old = dict(real, schema_version="0.1");path = Path(self.tmp.name) / "old.yaml"
        path.write_text(yaml.safe_dump(old, allow_unicode=True, sort_keys=False))
        with self.assertRaises(select.Hold):
            select.load_catalog(path)   # operations need catalog schema 0.2
        for row in old["addons"]:
            row.pop("operations", None)
        path.write_text(yaml.safe_dump(old, allow_unicode=True, sort_keys=False))
        self.assertIn("aipm", select.load_catalog(path)["rows"])   # a 0.1 catalog without operations still reads

    # CLI
    def test_cli_prints_json_and_exit_codes(self):
        self.write_intent(work_style="aipm", work_style_source=RECEIPT)
        run = subprocess.run([sys.executable, "-B", str(SCRIPTS / "plc_addon_select.py"), "--layer", str(self.case)],
                             capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["method"], "aipm")
        self.write_intent(work_style="other")
        run = subprocess.run([sys.executable, "-B", str(SCRIPTS / "plc_addon_select.py"), "--layer", str(self.case)],
                             capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 1)
        self.assertEqual(json.loads(run.stdout)["hold_reasons"], ["unsupported_work_style"])


if __name__ == "__main__":
    unittest.main()
