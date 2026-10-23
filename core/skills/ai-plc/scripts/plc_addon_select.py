"""Which addons are selected in a Layer (bundled catalog + legacy work_style alias + case bindings).

Stage 1. Read-only: never writes intent, never selects, never authenticates.
Contract: .claude/skills/ai-plc/references/addon-seam-contract_v0.5.yaml (BundledAddonSelection,
AddonCatalog [v0.5 adds the row operations], AddonProfileDeclaration, LegacyAlias, AddonSelectionResult).
Catalog:  .claude/skills/ai-plc/references/addon-catalog.yaml
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plc_addon as base  # noqa: E402  reuse the bounded reader, strict YAML loader and case binding check

CATALOG = base.CONTRACT.with_name("addon-catalog.yaml")
BUNDLED_REQUIRED = {"addon_id", "source", "addon_version"}
BUNDLED_FIELDS = BUNDLED_REQUIRED | {"selection_ref"}
CATALOG_TOP = {"specification", "schema_version", "contract", "exclusive_groups", "addons"}
GROUP_FIELDS = {"meaning", "max_selected", "none_allowed", "case_declaration", "undeclared_case_with_member"}
ROW_REQUIRED = {"addon_id", "source", "display_name", "addon_version", "exclusive_group", "hash_pinned",
                "entry", "init", "stage_reads"}
ROW_FIELDS = ROW_REQUIRED | {"settings_key", "legacy_alias", "operations"}   # operations: catalog schema 0.2 only (contract v0.5)
CATALOG_SCHEMAS = ("0.1", "0.2")
OPERATION_FIELDS = {"name", "entry", "writes", "before_selection"}
OPERATION_NAME = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)+")
ALIAS_FIELDS = {"intent_field", "value", "selection_source_field"}
PROFILE_BEGIN, PROFILE_END = "<!-- ADDON_PROFILE:BEGIN -->", "<!-- ADDON_PROFILE:END -->"
NONE_GROUP = "none"


class Hold(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code + (": " + detail if detail else ""))
        self.code, self.detail = code, detail


def load_catalog(path=None):
    """Return the validated catalog mapping or raise Hold('invalid_catalog')."""
    path = Path(path or CATALOG).resolve()
    try:
        data = base._yaml(base._bytes(path, [path.parent], base.MAX_INPUT_BYTES))
    except (base.Held, OSError, ValueError, yaml.YAMLError) as exc:
        raise Hold("invalid_catalog", str(exc))
    try:
        if set(data) != CATALOG_TOP or data["schema_version"] not in CATALOG_SCHEMAS:
            raise ValueError("unknown catalog top fields or schema")
        groups = data["exclusive_groups"]
        if not isinstance(groups, dict) or not groups:
            raise ValueError("exclusive_groups must be a nonempty mapping")
        for name, group in groups.items():
            if name == NONE_GROUP or not isinstance(group, dict) or set(group) != GROUP_FIELDS:
                raise ValueError("invalid exclusive group: " + str(name))
            if type(group["max_selected"]) is not int or group["max_selected"] < 1:
                raise ValueError("max_selected must be a positive integer")
            if group["undeclared_case_with_member"] not in ("hold", "allow"):
                raise ValueError("unknown undeclared_case_with_member")
        rows = data["addons"]
        if not isinstance(rows, list) or not rows:
            raise ValueError("addons must be a nonempty list")
        by_id, aliases = {}, {}
        for row in rows:
            if not isinstance(row, dict) or not ROW_REQUIRED <= set(row) or set(row) - ROW_FIELDS:
                raise ValueError("invalid catalog row fields")
            addon_id = base._text(row["addon_id"], "addon_id")
            if addon_id in by_id or row["source"] != "bundled":
                raise ValueError("duplicate addon_id or non-bundled row: " + addon_id)
            base._text(row["addon_version"], "addon_version")
            if row["exclusive_group"] is not None and row["exclusive_group"] not in groups:
                raise ValueError("row names an undefined exclusive group")
            if not isinstance(row["init"], dict) or not isinstance(row["init"].get("record"), str):
                raise ValueError("init must be a mapping with a record")
            if row["hash_pinned"] is not False:
                raise ValueError("bundled rows are not hash pinned")
            if "operations" in row:
                _check_operations(row["operations"], data["schema_version"])
            alias = row.get("legacy_alias")
            if alias is not None:
                if not isinstance(alias, dict) or set(alias) != ALIAS_FIELDS:
                    raise ValueError("invalid legacy_alias")
                key = (alias["intent_field"], alias["value"])
                if key in aliases:
                    raise ValueError("duplicate legacy_alias")
                aliases[key] = addon_id
            by_id[addon_id] = row
    except (KeyError, TypeError, ValueError, base.Held) as exc:
        raise Hold("invalid_catalog", str(exc))
    return {"groups": groups, "rows": by_id, "aliases": aliases}


def _check_operations(ops, schema):
    """The operations of one catalog row (contract v0.5): the method's operations on items inside its boxes.
    A list, never a permission. Raises ValueError (-> invalid_catalog)."""
    if schema != "0.2":
        raise ValueError("operations need catalog schema 0.2")
    if not isinstance(ops, list) or not ops:
        raise ValueError("operations must be a nonempty list")
    names = set()
    for op in ops:
        if not isinstance(op, dict) or not {"name", "entry", "writes"} <= set(op) or set(op) - OPERATION_FIELDS:
            raise ValueError("operation needs name, entry, writes and optional before_selection")
        name, entry = op["name"], op["entry"]
        if not isinstance(name, str) or not OPERATION_NAME.fullmatch(name) or name in names:
            raise ValueError("operation name must be unique <prefix>-<operation>: " + str(name))
        names.add(name)
        if not isinstance(entry, str) or not entry.strip() or entry.startswith("/") or ".." in Path(entry).parts:
            raise ValueError("operation entry must be a repository-relative path: " + str(entry))
        if type(op["writes"]) is not bool or type(op.get("before_selection", False)) is not bool:
            raise ValueError("writes and before_selection must be true or false")


WORD_TEMPLATE = r"(?<![A-Za-z0-9_-]){}(?![A-Za-z0-9_-])"


def _verify_selection(case, ref, addon_id):
    """(verified, basis). A record check, not authentication; never raises."""
    if not isinstance(ref, str) or not ref.strip():
        return False, "選択の出典なし"
    relative = Path(ref)
    if relative.is_absolute() or ".." in relative.parts or "\\" in ref or relative.parts[:1] != ("Context",):
        return False, "選択の出典が Layer の Context/ の下のファイルでない"
    try:
        raw = base._bytes(case / relative, [case], base.MAX_INPUT_BYTES)
        text = raw.decode("utf-8")
    except (base.Held, OSError, ValueError, UnicodeDecodeError):
        return False, "選択の出典を読めない（無い・symlink・大きすぎる等）"
    try:
        record = json.loads(text)
    except ValueError:
        record = None
    if isinstance(record, dict) and "choice" in record:
        ok = record.get("kind") == "user_reported" and record.get("choice") == addon_id
        return ok, "受領記録の choice が一致" if ok else "受領記録の choice が一致しない"
    if "selection" not in relative.name:
        return False, "選択の出典の名前に selection を含まない"
    if re.search(WORD_TEMPLATE.format(re.escape(addon_id)), text, re.IGNORECASE):
        return True, "Context の selection の記録が名指し"
    return False, "選択の記録が addon_id を名指ししない"


def _profile(case, binding, read_roots, common_root):
    """Exclusive group declared in the case common file: group name, 'none', or None (undeclared/unreadable)."""
    ref = binding["common_contract_ref"]
    if ref.get("kind") != "file":
        return None, "宣言を読めない（file 以外）"
    try:
        if ref.get("scope") == "case":
            target, roots = case / ref["relative_name"], [Path(r).resolve(strict=True) for r in (read_roots or [])]
        elif common_root is not None:
            root = Path(common_root).resolve(strict=True)
            target, roots = root / ref["relative_name"], [root]
        else:
            return None, "宣言を読めない（common の root なし）"
    except (OSError, ValueError, TypeError) as exc:
        return None, "宣言を読めない（読取の root を開けない: " + type(exc).__name__ + "）"
    if not roots:
        return None, "宣言を読めない（読取の root なし）"
    try:
        raw = base._bytes(target, roots, base.MAX_RESOURCE_BYTES)
    except (base.Held, OSError) as exc:
        return None, "宣言を読めない（" + type(exc).__name__ + "）"
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise Hold("case_profile_hash_mismatch", binding["addon_id"])
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise Hold("invalid_profile_declaration", "common is not UTF-8")
    begins, ends = text.count(PROFILE_BEGIN), text.count(PROFILE_END)
    if begins == 0 and ends == 0:
        return None, "宣言なし"
    if begins != 1 or ends != 1 or text.index(PROFILE_BEGIN) > text.index(PROFILE_END):
        raise Hold("invalid_profile_declaration", "ADDON_PROFILE markers must appear exactly once in order")
    body = text.split(PROFILE_BEGIN)[1].split(PROFILE_END)[0].strip()
    try:
        block = base._yaml(body.encode("utf-8")) if body else {}
    except (base.Held, yaml.YAMLError) as exc:
        raise Hold("invalid_profile_declaration", str(exc))
    if set(block) != {"exclusive_group"} or not isinstance(block["exclusive_group"], str):
        raise Hold("invalid_profile_declaration", "only exclusive_group is allowed")
    return block["exclusive_group"], None


def split_addons(bindings, rows, check_case=None):
    """Split intent.addons into (bundled entries by addon_id, case bindings in order). Raise Hold.

    Bundled entries (with a source field) are checked against the catalog rows; each case binding is
    passed to check_case (if given) in list order, so the first bad entry decides the Hold as before.
    Shared with plc_addon.py, which processes only the case bindings.
    """
    explicit, cases = {}, []
    for item in bindings:
        if not isinstance(item, dict):
            raise Hold("invalid_addons", "addon entry must be a mapping")
        if "source" not in item:
            if check_case is not None:
                check_case(item)
            cases.append(item)
            continue
        if item["source"] != "bundled":
            raise Hold("unknown_source", str(item["source"]))
        addon_id = item.get("addon_id")
        if not isinstance(addon_id, str) or addon_id not in rows:
            raise Hold("bundled_not_in_catalog", str(addon_id))
        if set(item) - BUNDLED_FIELDS or not BUNDLED_REQUIRED <= set(item):
            raise Hold("bundled_invalid_fields", addon_id)
        try:
            base._text(item["addon_version"], "addon_version")
            if "selection_ref" in item:
                base._text(item["selection_ref"], "selection_ref")
        except base.Held as exc:
            raise Hold("bundled_invalid_fields", str(exc))
        if addon_id in explicit:
            raise Hold("duplicate_bundled", addon_id)
        explicit[addon_id] = item
    return explicit, cases


def _result(**fields):
    out = {"route": "unselected", "method": None, "work_style_value": None, "selected": [], "case_addons": [],
           "has_case_addons": False, "notes": [], "hold_reasons": [], "writes": False}
    out.update(fields)
    return out


def selected_addons(layer, *, read_roots=None, common_root=None, catalog_path=None):
    """Return the AddonSelectionResult (contract v0.4) for one Layer. Never writes."""
    try:
        catalog = load_catalog(catalog_path)
        rows, groups, aliases = catalog["rows"], catalog["groups"], catalog["aliases"]
        try:
            case = Path(layer).resolve(strict=True)
            # Same reading as aipm-guided/package.py intent(): duplicate keys rejected, anchors allowed
            # (existing Layers use anchors). The catalog and the profile blocks stay on the strict loader.
            raw = base._bytes(case / "intent.yaml", [case], base.MAX_INPUT_BYTES)
            intent = yaml.load(raw.decode("utf-8"), Loader=base.UniqueLoader)
        except (base.Held, OSError, ValueError, yaml.YAMLError) as exc:
            raise Hold("invalid_intent", str(exc))
        if not isinstance(intent, dict):
            raise Hold("invalid_intent", "intent root must be a mapping")

        bindings = intent.get("addons")
        if bindings is None:
            bindings = []
        if not isinstance(bindings, list) or len(bindings) > base.MAX_BINDINGS:
            raise Hold("invalid_addons", "addons must be a bounded list")
        types = base._yaml(base._bytes(base.TASK_CONTRACT, [base.TASK_CONTRACT.parent], base.MAX_INPUT_BYTES))["types"]

        def check_case(item):
            try:
                base._binding(item, types)
            except (base.Held, KeyError, TypeError) as exc:
                raise Hold("invalid_case_binding", str(exc))

        explicit, cases = split_addons(bindings, rows, check_case)

        # legacy alias (work_style: aipm) — read as the bundled entry, never written back
        legacy = {}
        for field in sorted({f for f, _ in aliases}):
            value = intent.get(field)
            if value is None:
                continue
            addon_id = aliases.get((field, value)) if isinstance(value, str) else None
            if addon_id is None:
                aliased = [a for (f, _), a in aliases.items() if f == field]
                if any(a in explicit for a in aliased):
                    raise Hold("work_style_conflict", field + "=" + str(value))
                raise Hold("unsupported_work_style", field + "=" + str(value))
            legacy[addon_id] = field

        notes, selected = [], []
        for addon_id in [a for a in rows if a in explicit or a in legacy]:
            row, item = rows[addon_id], explicit.get(addon_id)
            alias = row.get("legacy_alias") or {}
            via = "both" if item is not None and addon_id in legacy else "addons" if item is not None else "legacy_alias"
            version = item["addon_version"] if item is not None else row["addon_version"]
            if version != row["addon_version"]:
                notes.append("版の差：intent " + version + " / 目録 " + row["addon_version"] + "（" + addon_id + "）")
            ref = item.get("selection_ref") if item is not None else None
            if ref is None and addon_id in legacy:
                ref = intent.get(alias.get("selection_source_field"))
            verified, basis = _verify_selection(case, ref, addon_id)
            if not verified:
                notes.append("選択の照合なし：" + basis + "（" + addon_id + "）")
            selected.append({"addon_id": addon_id, "source": "bundled", "via": via, "addon_version": version,
                             "catalog_version": row["addon_version"], "exclusive_group": row["exclusive_group"],
                             "entry": row["entry"], "init_record": row["init"].get("record"),
                             "selection_ref": ref if isinstance(ref, str) else None,
                             "selection_verified": verified, "selection_basis": basis})

        case_out = []
        for binding in cases:
            group, why = _profile(case, binding, read_roots, common_root)
            if group is not None and group != NONE_GROUP and group not in groups:
                raise Hold("invalid_profile_declaration", "unknown exclusive group: " + group)
            if why is not None and why != "宣言なし":
                notes.append(why + "（" + binding["addon_id"] + "）")
            case_out.append({"addon_id": binding["addon_id"], "addon_version": binding["addon_version"],
                             "exclusive_group": group})

        for name, group in groups.items():
            members = [s["addon_id"] for s in selected if s["exclusive_group"] == name]
            members += [c["addon_id"] for c in case_out if c["exclusive_group"] == name]
            if len(members) > group["max_selected"]:
                raise Hold("exclusive_group_multiple", name + ": " + ", ".join(members))
            undeclared = [c["addon_id"] for c in case_out if c["exclusive_group"] is None]
            if members and undeclared and group["undeclared_case_with_member"] == "hold":
                raise Hold("undeclared_case_with_method", ", ".join(undeclared) + " with " + ", ".join(members))

        method = next((s["addon_id"] for s in selected if s["exclusive_group"] == "work_method"), None)
        method = method or next((c["addon_id"] for c in case_out if c["exclusive_group"] == "work_method"), None)
        work_style_value = None
        for s in selected:
            alias = rows[s["addon_id"]].get("legacy_alias") or {}
            if alias.get("intent_field") == "work_style":
                work_style_value = alias["value"]
        route = "selected" if selected or case_out else "unselected"
        return _result(route=route, method=method, work_style_value=work_style_value, selected=selected,
                       case_addons=case_out, has_case_addons=bool(case_out), notes=notes)
    except Hold as exc:
        return _result(route="held", hold_reasons=[exc.code], detail=exc.detail)
    except (OSError, TypeError, ValueError, KeyError, AttributeError, UnicodeDecodeError, yaml.YAMLError) as exc:
        # Anything unexpected is a hold with a reason, never a traceback (the CLI still prints JSON).
        held = Hold("invalid_input", type(exc).__name__ + ": " + str(exc))
        return _result(route="held", hold_reasons=[held.code], detail=held.detail)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--layer", required=True)
    parser.add_argument("--read-root", action="append", default=[])
    parser.add_argument("--common-root")
    args = parser.parse_args(argv)
    result = selected_addons(args.layer, read_roots=args.read_root or None, common_root=args.common_root)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["route"] == "held" else 0


if __name__ == "__main__":
    raise SystemExit(main())
