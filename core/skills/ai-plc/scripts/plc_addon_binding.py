"""Build one intent.addons entry (AddonBinding) and optional intent.addon_init from an addon manifest.

Read-only: prints YAML/JSON for the caller (01-collection) to write. It never writes,
never selects an addon, and never creates the human selection record. The selection record is only
checked to exist inside the Layer and to name the same addon_id/version; that is not authentication.

Manifest (Layer-relative <addon-dir>/manifest.yaml):
  addon_id: <id>
  addon_version: "<version>"
  guide: {path: guide.md, version: "<v>"}
  common: {path: common.md, version: "<v>"}
  forms:
    - {form_id: <id>, path: forms/<file>.md, version: "<v>"}
  init_form_id: <form_id>        # optional
  read_limits: {max_guide_items: 1, max_form_items: <n>}
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plc_addon as base  # noqa: E402  reuse the bounded reader, YAML loader and binding check

MANIFEST_FIELDS = {"addon_id", "addon_version", "guide", "common", "forms", "init_form_id", "read_limits"}
RESOURCE_FIELDS = {"path", "version"}
FORM_FIELDS = {"form_id", "path", "version"}


SELECTION_ID = re.compile(r"addon_id[\s:：]*[`'\"]?([A-Za-z0-9][A-Za-z0-9._-]*)[`'\"]?")
SELECTION_VERSION = re.compile(r"addon_version[\s:：]*[`'\"]?([A-Za-z0-9][A-Za-z0-9._-]*)[`'\"]?")


def _selection_matches(text, addon_id, addon_version):
    """The record must name exactly this addon_id and version (whole values, no other values)."""
    ids, versions = set(SELECTION_ID.findall(text)), set(SELECTION_VERSION.findall(text))
    return ids == {addon_id} and versions == {addon_version}


def _relative(name, label):
    name = base._text(name, label)
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise base.Held(label + " must stay inside the addon folder")
    return relative


def build(layer, *, addon_dir="Documents/addon", selection_ref="Context/addon-selection.md"):
    """Return {"route": "binding", "addon_entry": ..., "addon_init": ...|None, ...} or a held result."""
    try:
        case = Path(layer).resolve(strict=True)
        roots = [case]
        folder = _relative(addon_dir, "addon_dir")
        if folder.parts[:1] != ("Documents",) or len(folder.parts) < 2:
            raise base.Held("addon_dir must be a folder under Documents/")
        selection_rel = _relative(selection_ref, "selection_ref")
        if (selection_rel.parts[:1] != ("Context",) or len(selection_rel.parts) < 2
                or "selection" not in selection_rel.name):
            raise base.Held("selection_ref must be a selection record under Context/")
        manifest_rel = folder / "manifest.yaml"
        manifest_raw = base._bytes(case / manifest_rel, roots, base.MAX_INPUT_BYTES)
        manifest = base._yaml(manifest_raw)
        if not isinstance(manifest, dict) or set(manifest) - MANIFEST_FIELDS:
            raise base.Held("invalid or unknown manifest fields")
        for key in ("addon_id", "addon_version"):
            base._text(manifest.get(key), key)

        def ref(entry, label, fields):
            if not isinstance(entry, dict) or set(entry) != fields:
                raise base.Held("invalid manifest entry: " + label)
            rel = folder / _relative(entry["path"], label + ".path")
            raw = base._bytes(case / rel, roots, base.MAX_RESOURCE_BYTES)
            return {"kind": "file", "scope": "case", "version": base._text(entry["version"], label + ".version"),
                    "relative_name": rel.as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}

        forms = manifest.get("forms")
        if not isinstance(forms, list) or not forms:
            raise base.Held("manifest forms must be a non-empty list")
        form_entries = []
        for form in forms:
            if not isinstance(form, dict) or set(form) != FORM_FIELDS:
                raise base.Held("invalid manifest form entry")
            form_entries.append({"form_id": base._text(form["form_id"], "form_id"),
                                 "form_ref": ref({"path": form["path"], "version": form["version"]}, "form", RESOURCE_FIELDS)})
        binding = {"schema_version": "0.1", "addon_id": manifest["addon_id"], "addon_version": manifest["addon_version"],
                   "selection_ref": selection_rel.as_posix(),
                   "guide_ref": ref(manifest.get("guide"), "guide", RESOURCE_FIELDS),
                   "common_contract_ref": ref(manifest.get("common"), "common", RESOURCE_FIELDS),
                   "forms": form_entries, "read_limits": manifest.get("read_limits")}
        declaration = base._yaml(base._bytes(base.TASK_CONTRACT, [base.TASK_CONTRACT.parent], base.MAX_INPUT_BYTES))
        base._binding(binding, declaration["types"])
        if len(binding["forms"]) > binding["read_limits"]["max_form_items"]:
            raise base.Held("manifest forms exceed max_form_items")

        # selection record: must exist inside the Layer and name the same addon/version (not authentication)
        selection_raw = base._bytes(case / selection_rel, roots, base.MAX_INPUT_BYTES)
        if not _selection_matches(selection_raw.decode("utf-8"), manifest["addon_id"], manifest["addon_version"]):
            raise base.Held("selection record does not name exactly this addon_id/version")

        init = None
        if "init_form_id" in manifest:
            form_id = base._text(manifest["init_form_id"], "init_form_id")
            if form_id not in [f["form_id"] for f in binding["forms"]]:
                raise base.Held("init_form_id is not one of the manifest forms")
            init = {"addon_id": manifest["addon_id"], "addon_version": manifest["addon_version"], "form_id": form_id,
                    "declared_in": manifest_rel.as_posix(), "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest()}
            base._addon_init_flag({"addon_init": init}, binding, form_id, lambda rel: base._bytes(case / rel, roots, base.MAX_INPUT_BYTES))
        block = {"addons": [binding]}
        if init is not None:
            block["addon_init"] = init
        return {"route": "binding", "addon_entry": binding, "addon_init": init,
                "intent_block": yaml.safe_dump(block, allow_unicode=True, sort_keys=False),
                "writes": False, "selection_created": False,
                "note": "intent.yaml への書き込みは呼び出す側（Collection）が、本人の選択の記録を確かめた範囲で行う"}
    except (base.Held, OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return {"route": "held", "reason": type(exc).__name__ + ": " + str(exc), "writes": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--layer", required=True)
    parser.add_argument("--addon-dir", default="Documents/addon")
    parser.add_argument("--selection-ref", default="Context/addon-selection.md")
    args = parser.parse_args()
    result = build(args.layer, addon_dir=args.addon_dir, selection_ref=args.selection_ref)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["route"] != "held" else 1


if __name__ == "__main__":
    raise SystemExit(main())
