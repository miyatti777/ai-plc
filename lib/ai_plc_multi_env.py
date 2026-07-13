#!/usr/bin/env python3
"""Multi-environment install/uninstall coordinator for AI-PLC."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
from typing import Any

import ai_plc_safe_fs as safe


ENVIRONMENTS = {
    "cc": {"cc"},
    "cursor": {"cursor"},
    "both": {"cc", "cursor"},
    "codex": {"codex"},
    "all": {"cc", "cursor", "codex"},
}
CC_START = "<!-- AI-PLC START -->"
CC_END = "<!-- AI-PLC END -->"


def add_tree(source: safe.SafeRoot, source_dir: str, target_dir: str, component: str,
             owners: set[str], entries: dict[str, dict[str, Any]], payloads: dict[str, bytes]) -> None:
    for source_path in source.walk_regular_files(source_dir):
        suffix = source_path.removeprefix(source_dir + "/")
        add_file(source, source_path, f"{target_dir}/{suffix}", component, owners, entries, payloads)


def add_file(source: safe.SafeRoot, source_path: str, target: str, component: str,
             owners: set[str], entries: dict[str, dict[str, Any]], payloads: dict[str, bytes]) -> None:
    data = source.read_bytes(source_path)
    target = safe.canonical_rel(target)
    payloads[target] = data
    entries[target] = {
        "component": component, "source_sha256": safe.sha256(data),
        "owners": sorted(owners), "protection": None,
    }


def inventory(distribution: Path, environments: set[str]) -> tuple[dict[str, Any], dict[str, bytes]]:
    entries: dict[str, dict[str, Any]] = {}
    payloads: dict[str, bytes] = {}
    with safe.SafeRoot(distribution) as source:
        shared_owners = environments & {"cc", "codex"}
        if shared_owners:
            add_tree(source, "core/skills", ".claude/skills", "shared_claude_runtime", shared_owners, entries, payloads)
            for name in ("ai-plc-system.md", "ai-plc-session.md", "ai-plc-adaptive.md"):
                add_file(source, f"core/rules/{name}", f".claude/rules/{name}", "shared_claude_runtime", shared_owners, entries, payloads)
            for name in ("init_db.py", "plc_query.py", "sync.py", "README.md"):
                add_file(source, f"core/db/{name}", f".claude/db/{name}", "shared_claude_runtime", shared_owners, entries, payloads)
        if "cc" in environments:
            add_tree(source, "claude/commands", ".claude/commands", "cc_runtime", {"cc"}, entries, payloads)
            add_tree(source, "claude/agents", ".claude/agents", "cc_runtime", {"cc"}, entries, payloads)
        if "cursor" in environments:
            add_tree(source, "core/skills", ".cursor/skills", "cursor_runtime", {"cursor"}, entries, payloads)
            add_tree(source, "cursor/rules", ".cursor/rules", "cursor_runtime", {"cursor"}, entries, payloads)
            for name in ("init_db.py", "plc_query.py", "sync.py", "README.md"):
                add_file(source, f"core/db/{name}", f".cursor/db/{name}", "cursor_runtime", {"cursor"}, entries, payloads)
        if "codex" in environments:
            add_tree(source, "codex/skills/ai-plc", ".agents/skills/ai-plc", "codex_adapter", {"codex"}, entries, payloads)
            add_tree(source, "core/skills/utility", ".agents/skills/utility", "codex_adapter", {"codex"}, entries, payloads)
    return entries, payloads


def region_result(existing: bytes | None, template: bytes, start: str, end: str) -> bytes:
    if existing is None:
        return template
    text = existing.decode()
    template_text = template.decode()
    if text.count(start) == 0 and text.count(end) == 0:
        separator = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        return (text + separator + template_text).encode()
    if text.count(start) != 1 or text.count(end) != 1:
        raise safe.InstallError("managed region markers are missing or duplicated")
    prefix, rest = text.split(start, 1)
    _, suffix = rest.split(end, 1)
    return (prefix + safe.extract_region(template, start, end).decode() + suffix).encode()


def component_hash(entries: dict[str, Any], regions: dict[str, Any], component: str) -> str:
    rows = [f"file:{p}:{v['source_sha256']}" for p, v in entries.items() if v["component"] == component]
    rows += [f"region:{p}:{v['content_sha256']}" for p, v in regions.items() if v["component"] == component]
    return safe.sha256(("\n".join(sorted(rows)) + "\n").encode())


def legacy_manifest(distribution: Path, root: safe.SafeRoot, version: str) -> dict[str, Any]:
    legacy = safe.legacy_state(root, safe.secure_source_read(
        distribution, f"migration/legacy-releases/{version}.yaml"))
    manifest: dict[str, Any] = {
        "schema_version": 1, "status": "active", "environments": {}, "components": {},
        "managed_files": {}, "managed_regions": {}, "residuals": [],
    }
    for env in legacy["environments"]:
        manifest["environments"][env] = {"version": version}
    for path, item in legacy["managed_files"].items():
        owner = item["owner"]
        component = "cursor_runtime" if owner == "cursor" else (
            "shared_claude_runtime" if path.startswith((".claude/skills/", ".claude/rules/", ".claude/db/")) else "cc_runtime")
        manifest["managed_files"][path] = {
            "component": component, "source_sha256": item["source_sha256"],
            "owners": [owner], "protection": None,
        }
    for region_id, item in legacy["managed_regions"].items():
        manifest["managed_regions"][region_id] = {
            "path": item["path"], "component": "cc_runtime", "start_marker": item["start_marker"],
            "end_marker": item["end_marker"], "content_sha256": item["content_sha256"],
            "owners": [item["owner"]], "protection": None,
        }
    for component in {x["component"] for x in manifest["managed_files"].values()} | {x["component"] for x in manifest["managed_regions"].values()}:
        owners = sorted({o for x in manifest["managed_files"].values() if x["component"] == component for o in x["owners"]} |
                        {o for x in manifest["managed_regions"].values() if x["component"] == component for o in x["owners"]})
        manifest["components"][component] = {
            "version": version, "owners": owners,
            "inventory_sha256": component_hash(manifest["managed_files"], manifest["managed_regions"], component),
        }
    return manifest


def build_install_plan(distribution: Path, root: safe.SafeRoot, mode: str,
                       migrate_legacy: str | None = None, lock_held: bool = False) -> dict[str, Any]:
    environments = ENVIRONMENTS[mode]
    version = safe.secure_source_read(distribution, safe.VERSION_MARKER).decode().strip()
    safe.semver(version)
    entries, payloads = inventory(distribution, environments)
    manifest = safe.load_manifest(root)
    conflicts: list[str] = []
    writes: list[str] = []
    preserved: list[str] = []
    if safe.control_artifacts(root) and not lock_held:
        conflicts.append("target is busy or needs recovery")
    if migrate_legacy:
        if manifest:
            conflicts.append("legacy migration requires a target without a manifest")
        elif migrate_legacy == version:
            conflicts.append("legacy migration requires a newer distribution version")
        else:
            try:
                manifest = legacy_manifest(distribution, root, migrate_legacy)
            except (safe.InstallError, FileNotFoundError) as exc:
                conflicts.append(f"legacy migration failed: {exc}")
    if manifest and manifest.get("status") == "detached":
        conflicts.append("manifest is detached; resolve residuals before install")
    old_files = (manifest or {}).get("managed_files", {})
    for path, item in entries.items():
        if not root.exists(path):
            writes.append(path)
            continue
        current = safe.sha256(root.read_bytes(path))
        old = old_files.get(path)
        if old:
            if current != old.get("source_sha256"):
                conflicts.append(f"user-modified managed file: {path}")
            elif current != item["source_sha256"]:
                writes.append(path)
        elif current == item["source_sha256"]:
            preserved.append(path)
        else:
            conflicts.append(f"unmanaged file collision: {path}")

    region_specs: dict[str, dict[str, Any]] = {}
    region_outputs: dict[str, bytes] = {}
    if "cc" in environments:
        for region_id, path, template_path in (
            ("CLAUDE.md#ai-plc-cc", "CLAUDE.md", "claude/CLAUDE.md.template"),
            ("AGENTS.md#ai-plc-cc", "AGENTS.md", "claude/AGENTS.md.template"),
        ):
            template = safe.secure_source_read(distribution, template_path)
            existing = root.read_bytes(path) if root.exists(path) else None
            try:
                if existing and CC_START.encode() in existing:
                    current_hash = safe.sha256(safe.extract_region(existing, CC_START, CC_END))
                    old = (manifest or {}).get("managed_regions", {}).get(region_id)
                    if old and current_hash != old.get("content_sha256"):
                        raise safe.InstallError("user-modified managed region")
                    if not old and current_hash != safe.sha256(safe.extract_region(template, CC_START, CC_END)):
                        raise safe.InstallError("unmanaged marker region")
                output = region_result(existing, template, CC_START, CC_END)
                region_outputs[path] = output
                if output != existing:
                    writes.append(region_id)
                region_specs[region_id] = {
                    "path": path, "component": "cc_runtime", "start_marker": CC_START,
                    "end_marker": CC_END, "content_sha256": safe.sha256(safe.extract_region(template, CC_START, CC_END)),
                    "owners": ["cc"], "protection": None,
                }
            except safe.InstallError as exc:
                conflicts.append(f"{path}: {exc}")
    if "codex" in environments:
        template = safe.secure_source_read(distribution, "codex/AGENTS.md.template")
        existing = region_outputs.get("AGENTS.md", root.read_bytes("AGENTS.md") if root.exists("AGENTS.md") else None)
        region_id = "AGENTS.md#ai-plc-codex"
        try:
            if existing and safe.CODEX_START.encode() in existing:
                current_hash = safe.sha256(safe.extract_region(existing, safe.CODEX_START, safe.CODEX_END))
                old = (manifest or {}).get("managed_regions", {}).get(region_id)
                if old and current_hash != old.get("content_sha256"):
                    raise safe.InstallError("user-modified managed Codex region")
                if not old and current_hash != safe.sha256(safe.extract_region(template, safe.CODEX_START, safe.CODEX_END)):
                    raise safe.InstallError("unmanaged Codex marker region")
            output = region_result(existing, template, safe.CODEX_START, safe.CODEX_END)
            region_outputs["AGENTS.md"] = output
            if output != existing:
                writes.append(region_id)
            region_specs[region_id] = {
                "path": "AGENTS.md", "component": "codex_adapter", "start_marker": safe.CODEX_START,
                "end_marker": safe.CODEX_END, "content_sha256": safe.sha256(safe.extract_region(template, safe.CODEX_START, safe.CODEX_END)),
                "owners": ["codex"], "protection": None,
            }
        except safe.InstallError as exc:
            conflicts.append(f"AGENTS.md: {exc}")

    old_regions = (manifest or {}).get("managed_regions", {})
    for region_id, item in region_specs.items():
        old = old_regions.get(region_id)
        if old:
            item["owners"] = sorted(set(old.get("owners", [])) | set(item["owners"]))

    seed_refs: dict[str, str] = {}
    if "cc" in environments:
        seed_refs.update({
            ".claude/settings.json": "claude/settings.json", ".claude/soul.md": "templates/soul.md",
            ".claude/wiki/wiki.md": "templates/wiki/wiki.md", ".claude/wiki/index.md": "templates/wiki/index.md",
            ".claude/wiki/log.md": "templates/wiki/log.md", ".claude/wiki/queries/README.md": "templates/wiki/queries/README.md",
            ".claude/wiki/sources/README.md": "templates/wiki/sources/README.md",
        })
    if "codex" in environments:
        seed_refs.update({
            ".claude/wiki/wiki.md": "templates/wiki/wiki.md", ".claude/wiki/index.md": "templates/wiki/index.md",
            ".claude/wiki/log.md": "templates/wiki/log.md", ".claude/wiki/queries/README.md": "templates/wiki/queries/README.md",
            ".claude/wiki/sources/README.md": "templates/wiki/sources/README.md",
        })
    if "cursor" in environments:
        seed_refs.update({
            ".cursor/wiki/wiki.md": "templates/wiki/wiki.md", ".cursor/wiki/index.md": "templates/wiki/index.md",
            ".cursor/wiki/log.md": "templates/wiki/log.md", ".cursor/wiki/queries/README.md": "templates/wiki/queries/README.md",
            ".cursor/wiki/sources/README.md": "templates/wiki/sources/README.md",
        })
    seeds = {target: safe.secure_source_read(distribution, source) for target, source in seed_refs.items()}
    for path in seeds:
        (preserved if root.exists(path) else writes).append(path)
    db_targets = []
    if environments & {"cc", "codex"}:
        db_targets.append(".claude/db/ai_plc.db")
    if "cursor" in environments:
        db_targets.append(".cursor/db/ai_plc.db")
    for path in db_targets:
        (preserved if root.exists(path) else writes).append(path)

    if root.exists(safe.VERSION_MARKER):
        marker = root.read_bytes(safe.VERSION_MARKER)
        expected = (manifest or {}).get("version_marker", {}).get("expected_sha256")
        if expected and safe.sha256(marker) != expected:
            conflicts.append(f"user-modified managed file: {safe.VERSION_MARKER}")
        try:
            if safe.semver(marker.decode().strip()) > safe.semver(version):
                conflicts.append("downgrade refused")
        except safe.InstallError as exc:
            conflicts.append(str(exc))
    else:
        writes.append(safe.VERSION_MARKER)

    new_manifest = json.loads(json.dumps(manifest or {
        "schema_version": 1, "status": "active", "environments": {}, "components": {},
        "managed_files": {}, "managed_regions": {}, "residuals": [],
    }))
    new_manifest["status"] = "active"
    for environment in environments:
        new_manifest["environments"][environment] = {"version": version}
    for path, item in entries.items():
        old_owners = new_manifest["managed_files"].get(path, {}).get("owners", [])
        item = dict(item)
        item["owners"] = sorted(set(old_owners) | set(item["owners"]))
        new_manifest["managed_files"][path] = item
    new_manifest["managed_regions"].update(region_specs)
    touched_components = {item["component"] for item in entries.values()} | {item["component"] for item in region_specs.values()}
    stale_files: list[str] = []
    for path, old in list(new_manifest["managed_files"].items()):
        if old.get("component") not in touched_components or path in entries:
            continue
        owners = set(old.get("owners", []))
        if not (owners & environments):
            continue
        remaining = owners - environments
        if remaining:
            old["owners"] = sorted(remaining)
        elif not root.exists(path):
            del new_manifest["managed_files"][path]
        elif safe.sha256(root.read_bytes(path)) == old.get("source_sha256"):
            stale_files.append(path)
            writes.append(f"DELETE:{path}")
            del new_manifest["managed_files"][path]
        else:
            conflicts.append(f"user-modified stale managed file: {path}")
    for component in touched_components:
        owners = sorted({owner for item in new_manifest["managed_files"].values() if item["component"] == component for owner in item["owners"]} |
                        {owner for item in new_manifest["managed_regions"].values() if item["component"] == component for owner in item["owners"]})
        updated = {
            "version": version, "owners": owners,
            "inventory_sha256": component_hash(new_manifest["managed_files"], new_manifest["managed_regions"], component),
        }
        old_component = (manifest or {}).get("components", {}).get(component)
        if old_component:
            if safe.semver(version) < safe.semver(old_component["version"]):
                conflicts.append(f"component downgrade refused: {component}")
            if version == old_component["version"] and old_component.get("inventory_sha256") != updated["inventory_sha256"]:
                conflicts.append(f"mutable release refused: {component} {version}")
        new_manifest["components"][component] = updated
    new_manifest["version_marker"] = {"path": safe.VERSION_MARKER, "expected_sha256": safe.sha256((version + "\n").encode())}
    return {
        "version": version, "mode": mode, "entries": entries, "payloads": payloads,
        "regions": region_outputs, "seeds": seeds, "db_targets": db_targets,
        "manifest": new_manifest, "writes": sorted(set(writes)), "preserved": sorted(set(preserved)),
        "stale_files": sorted(stale_files), "conflicts": sorted(set(conflicts)),
    }


def execute_install(distribution: Path, root: safe.SafeRoot, mode: str,
                    migrate_legacy: str | None) -> int:
    tx = safe.Transaction(root)
    tx.acquire()
    try:
        safe.validate_or_consume_tombstone(root, mutate=True)
        safe.assert_fresh_transaction_artifacts(root, tx)
        plan = build_install_plan(distribution, root, mode, migrate_legacy, lock_held=True)
    except Exception:
        tx.rollback()
        raise
    if plan["conflicts"]:
        for conflict in plan["conflicts"]:
            print(f"[CONFLICT] {conflict}", file=sys.stderr)
        tx.rollback()
        raise safe.InstallError("preflight failed; target unchanged")
    changed = 0
    try:
        for path in plan["stale_files"]:
            changed += int(root.delete_transactional(path, tx))
        for path, data in plan["payloads"].items():
            changed += int(root.write_atomic(path, data, tx))
        for path, data in plan["regions"].items():
            changed += int(root.write_atomic(path, data, tx))
        for path, data in plan["seeds"].items():
            if not root.exists(path):
                changed += int(root.write_atomic(path, data, tx))
        db_data = None
        for path in plan["db_targets"]:
            if not root.exists(path):
                db_data = db_data or safe.create_db_bytes(safe.secure_source_read(distribution, "core/db/init_db.py"))
                changed += int(root.write_atomic(path, db_data, tx))
        changed += int(root.write_atomic(safe.VERSION_MARKER, (plan["version"] + "\n").encode(), tx))
        manifest = json.dumps(plan["manifest"], ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
        changed += int(root.write_atomic(safe.MANIFEST, manifest, tx))
        tx.commit()
    except Exception:
        tx.rollback()
        raise
    print(f"[OK] {plan['mode']} install committed: {changed} changed file(s)")
    return changed


def remove_region(content: bytes, start: str, end: str) -> bytes:
    text = content.decode()
    if text.count(start) != 1 or text.count(end) != 1:
        raise safe.InstallError("managed region markers are missing or duplicated")
    prefix, rest = text.split(start, 1)
    _, suffix = rest.split(end, 1)
    return (prefix.rstrip("\n") + ("\n" if prefix.rstrip("\n") and suffix.lstrip("\n") else "") + suffix.lstrip("\n")).encode()


def build_uninstall_plan(distribution: Path, root: safe.SafeRoot, mode: str) -> dict[str, Any]:
    requested = ENVIRONMENTS[mode]
    manifest = safe.load_manifest(root)
    legacy_mode = False
    if manifest and manifest.get("status") == "detached":
        raise safe.InstallError("manifest is detached; use explicit residual cleanup/adopt/purge")
    if not manifest:
        if mode == "codex":
            raise safe.InstallError("no install manifest; Codex candidates are preserved for safety")
        requested = requested & {"cc", "cursor"}
        version = safe.secure_source_read(distribution, safe.VERSION_MARKER).decode().strip()
        manifest = legacy_manifest(distribution, root, version)
        legacy_mode = True
    installed = set(manifest.get("environments", {}))
    selected = requested & installed
    conflicts: list[str] = []
    deletes: list[str] = []
    region_outputs: dict[str, bytes] = {}
    residuals: list[dict[str, Any]] = []
    new_manifest = json.loads(json.dumps(manifest))
    for path, item in list(new_manifest["managed_files"].items()):
        owners = set(item.get("owners", []))
        removing = owners & selected
        if not removing:
            continue
        remaining = owners - selected
        if remaining:
            item["owners"] = sorted(remaining)
            continue
        if not root.exists(path):
            del new_manifest["managed_files"][path]
        elif safe.sha256(root.read_bytes(path)) == item.get("source_sha256"):
            deletes.append(path)
            del new_manifest["managed_files"][path]
        else:
            residuals.append({
                "type": "file", "path": path, "reason": "modified", "component": item.get("component"),
                "owners": sorted(owners), "expected_sha256": item.get("source_sha256"),
                "current_sha256": safe.sha256(root.read_bytes(path)),
            })
            del new_manifest["managed_files"][path]
    for region_id, item in list(new_manifest["managed_regions"].items()):
        owners = set(item.get("owners", []))
        if not (owners & selected):
            continue
        remaining = owners - selected
        if remaining:
            item["owners"] = sorted(remaining)
            continue
        path = item["path"]
        if not root.exists(path):
            del new_manifest["managed_regions"][region_id]
            continue
        content = region_outputs.get(path, root.read_bytes(path))
        try:
            current = safe.sha256(safe.extract_region(content, item["start_marker"], item["end_marker"]))
            if current != item.get("content_sha256"):
                raise safe.InstallError("managed region modified")
            region_outputs[path] = remove_region(content, item["start_marker"], item["end_marker"])
            del new_manifest["managed_regions"][region_id]
        except safe.InstallError:
            residuals.append({
                "type": "region", "path": path, "region_id": region_id, "reason": "modified",
                "component": item.get("component"), "owners": sorted(owners),
                "expected_sha256": item.get("content_sha256"),
            })
            del new_manifest["managed_regions"][region_id]
    for environment in selected:
        new_manifest["environments"].pop(environment, None)
    for component in list(new_manifest["components"]):
        owners = sorted({o for item in new_manifest["managed_files"].values() if item["component"] == component for o in item["owners"]} |
                        {o for item in new_manifest["managed_regions"].values() if item["component"] == component for o in item["owners"]})
        if owners:
            new_manifest["components"][component]["owners"] = owners
            new_manifest["components"][component]["inventory_sha256"] = component_hash(
                new_manifest["managed_files"], new_manifest["managed_regions"], component)
        else:
            del new_manifest["components"][component]
    new_manifest["residuals"] = residuals
    new_manifest["status"] = "detached" if residuals else "active"
    versions = [v["version"] for v in new_manifest["environments"].values()] + [v["version"] for v in new_manifest["components"].values()]
    if residuals and not versions:
        versions = [max((v["version"] for v in manifest["environments"].values()), key=safe.semver)]
    version = max(versions, key=safe.semver) if versions else None
    if version:
        new_manifest["version_marker"] = {"path": safe.VERSION_MARKER, "expected_sha256": safe.sha256((version + "\n").encode())}
    return {
        "mode": mode, "selected": sorted(selected), "deletes": sorted(deletes), "regions": region_outputs,
        "manifest": new_manifest, "version": version, "residuals": residuals,
        "legacy_mode": legacy_mode, "conflicts": conflicts,
    }


def execute_uninstall(distribution: Path, root: safe.SafeRoot, mode: str) -> int:
    tx = safe.Transaction(root)
    tx.acquire()
    try:
        safe.validate_or_consume_tombstone(root, mutate=True)
        safe.assert_fresh_transaction_artifacts(root, tx)
        plan = build_uninstall_plan(distribution, root, mode)
    except Exception:
        tx.rollback()
        raise
    changed = 0
    try:
        for path in plan["deletes"]:
            changed += int(root.delete_transactional(path, tx))
        for path, data in plan["regions"].items():
            changed += int(root.write_atomic(path, data, tx))
        if plan["version"] or plan["residuals"]:
            changed += int(root.write_atomic(safe.VERSION_MARKER, (plan["version"] + "\n").encode(), tx))
            payload = json.dumps(plan["manifest"], ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
            changed += int(root.write_atomic(safe.MANIFEST, payload, tx))
        elif plan["legacy_mode"]:
            if root.exists(safe.VERSION_MARKER):
                changed += int(root.delete_transactional(safe.VERSION_MARKER, tx))
        else:
            tombstone = {
                "schema_version": 1, "transaction_id": tx.transaction_id,
                "old_manifest_sha256": safe.sha256(root.read_bytes(safe.MANIFEST)),
                "state": "deleted", "completed_at": safe.utc_stamp(),
            }
            changed += int(root.write_atomic(".ai-plc-uninstall-tombstone", json.dumps(tombstone, sort_keys=True).encode() + b"\n", tx))
            if root.exists(safe.VERSION_MARKER):
                changed += int(root.delete_transactional(safe.VERSION_MARKER, tx))
            changed += int(root.delete_transactional(safe.MANIFEST, tx))
        tx.commit()
    except Exception:
        tx.rollback()
        raise
    print(f"[OK] {plan['mode']} uninstall committed: {changed} changed file(s)")
    if plan["residuals"]:
        print(f"[WARN] {len(plan['residuals'])} modified item(s) preserved; manifest detached")
    return changed


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AI-PLC multi-environment coordinator")
    p.add_argument("action", choices=("install", "uninstall"))
    p.add_argument("mode", choices=tuple(ENVIRONMENTS))
    p.add_argument("--target")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--plan-only", action="store_true")
    p.add_argument("--migrate-legacy", metavar="VERSION")
    p.add_argument("--yes", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    distribution = Path(__file__).resolve().parent.parent
    target = safe.determine_target(args.target)
    if args.action == "install" and args.mode in ("cc", "both", "codex", "all") and not (args.dry_run or args.plan_only):
        is_git = subprocess.run(["git", "-C", str(target), "rev-parse", "--is-inside-work-tree"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not is_git and not args.yes:
            if not sys.stdin.isatty():
                raise safe.InstallError("non-git target requires --yes or interactive confirmation")
            if input("Continue without initializing git? [y/N] ").strip().lower() not in ("y", "yes"):
                raise safe.InstallError("installation was not confirmed")
    with safe.SafeRoot(target) as root:
        if not (args.dry_run or args.plan_only):
            safe.recover_if_needed(root)
        else:
            safe.validate_or_consume_tombstone(root, mutate=False)
        plan = (build_install_plan(distribution, root, args.mode, args.migrate_legacy)
                if args.action == "install" else build_uninstall_plan(distribution, root, args.mode))
        if args.dry_run or args.plan_only:
            summary = {k: plan[k] for k in ("mode", "conflicts")}
            summary["writes" if args.action == "install" else "deletes"] = plan["writes" if args.action == "install" else "deletes"]
            print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
            return 1 if plan["conflicts"] else 0
        if args.action == "install":
            execute_install(distribution, root, args.mode, args.migrate_legacy)
        else:
            execute_uninstall(distribution, root, args.mode)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (safe.InstallError, OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2)
