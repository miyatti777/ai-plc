#!/usr/bin/env python3
"""Multi-environment install/uninstall coordinator for AI-PLC."""

from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path, PurePosixPath
import re
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
# Opt-in experimental package (install ... --with-jev). Claude Code only; never part of the default inventory.
JEV_COMPONENT = "experimental_jev"
JEV_SOURCE = "experimental/jev"
JEV_VERSION_FILE = f"{JEV_SOURCE}/VERSION"
JEV_KNOWN_RELEASES = f"{JEV_SOURCE}/KNOWN_RELEASES.sha256"
JEV_MANAGED_DIRS = (".claude/ai-plc-jev", ".claude/skills/ai-plc-jev")
JEV_COMMANDS_DIR = ".claude/commands"
JEV_COMMAND_NAME = re.compile(r"^0[1-4]-[a-z-]+-jev\.md$")
JEV_PACKAGE_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-exp\.([1-9][0-9]*)$")
JEV_CLEANUP_KEY = "experimental_jev_cleanup"  # journal entry that lets recovery resume the cleanup
BACKUP_SUFFIX = re.compile(r"^(?P<base>.+)\.bak\.[0-9]{8}T[0-9]{6}Z\.[0-9]+$")
JEV_ONLY_CC = ("--with-jev: 実験版は Claude Code 専用。cc / both / all と一緒に指定してください "
               "(experimental/jev is Claude Code only; use it with cc, both, or all)")


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


def jev_package_version(value: str) -> tuple[int, int, int, int]:
    match = JEV_PACKAGE_VERSION.fullmatch(value)
    if not match:
        raise safe.InstallError(f"invalid experimental package version: {value!r}")
    return tuple(int(x) for x in match.groups())  # type: ignore[return-value]


def read_jev_package_version(distribution: Path) -> str:
    value = safe.secure_source_read(distribution, JEV_VERSION_FILE).decode().strip()
    jev_package_version(value)
    return value


def add_direct_files(source: safe.SafeRoot, source_dir: str, target_dir: str, component: str,
                     owners: set[str], entries: dict[str, dict[str, Any]], payloads: dict[str, bytes]) -> None:
    """Like add_tree, but only regular files directly inside source_dir (skips tests/, __pycache__/, ...)."""
    for source_path in source.walk_regular_files(source_dir):
        suffix = source_path.removeprefix(source_dir + "/")
        if "/" not in suffix:
            add_file(source, source_path, f"{target_dir}/{suffix}", component, owners, entries, payloads)


def add_experimental_jev(source: safe.SafeRoot, entries: dict[str, dict[str, Any]], payloads: dict[str, bytes]) -> None:
    add_tree(source, f"{JEV_SOURCE}/skills/ai-plc-jev", ".claude/skills/ai-plc-jev", JEV_COMPONENT, {"cc"}, entries, payloads)
    add_tree(source, f"{JEV_SOURCE}/commands", JEV_COMMANDS_DIR, JEV_COMPONENT, {"cc"}, entries, payloads)
    add_direct_files(source, f"{JEV_SOURCE}/scripts", ".claude/ai-plc-jev/scripts", JEV_COMPONENT, {"cc"}, entries, payloads)


def inventory(distribution: Path, environments: set[str],
              with_jev: bool = False) -> tuple[dict[str, Any], dict[str, bytes]]:
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
        if with_jev:
            jev_entries: dict[str, dict[str, Any]] = {}
            add_experimental_jev(source, jev_entries, payloads)
            overlap = sorted(set(jev_entries) & set(entries))
            if overlap:
                raise safe.InstallError("experimental package overlaps core inventory: " + ", ".join(overlap))
            entries.update(jev_entries)
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
                       migrate_legacy: str | None = None, lock_held: bool = False,
                       with_jev: bool = False) -> dict[str, Any]:
    environments = ENVIRONMENTS[mode]
    if with_jev and "cc" not in environments:
        raise safe.InstallError(JEV_ONLY_CC)
    version = safe.secure_source_read(distribution, safe.VERSION_MARKER).decode().strip()
    safe.semver(version)
    jev_version = read_jev_package_version(distribution) if with_jev else None
    entries, payloads = inventory(distribution, environments, with_jev)
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
        if component == JEV_COMPONENT:
            # The experimental package is versioned on its own (X.Y.Z-exp.N); the core marker stays untouched.
            updated["package_version"] = jev_version
            old_package = (old_component or {}).get("package_version")
            if old_package:
                try:
                    if jev_package_version(jev_version) < jev_package_version(old_package):
                        conflicts.append(f"component downgrade refused: {component}")
                except safe.InstallError as exc:
                    conflicts.append(str(exc))
                if jev_version == old_package and old_component.get("inventory_sha256") != updated["inventory_sha256"]:
                    conflicts.append(f"mutable release refused: {component} {jev_version}")
            new_manifest["components"][component] = updated
            continue
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


def jev_files(manifest: dict[str, Any] | None) -> dict[str, str]:
    """Managed experimental-package paths -> distributed sha256 (from a manifest snapshot)."""
    return {path: item.get("source_sha256") for path, item in ((manifest or {}).get("managed_files") or {}).items()
            if item.get("component") == JEV_COMPONENT and item.get("source_sha256")}


def load_known_jev_hashes(distribution: Path) -> dict[str, set[str]]:
    """Parse KNOWN_RELEASES.sha256 ("<sha256>  <installed relative path>" per line, '#' comments)."""
    known: dict[str, set[str]] = {}
    try:
        text = safe.secure_source_read(distribution, JEV_KNOWN_RELEASES).decode()
    except (OSError, ValueError, safe.InstallError):  # missing or undecodable list -> no extra hashes
        return known
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            continue
        try:
            path = safe.canonical_rel(parts[1].strip().lstrip("*"))
        except (safe.InstallError, ValueError):
            continue
        if is_jev_location(path):
            known.setdefault(path, set()).add(parts[0])
    return known


def is_jev_location(path: str) -> bool:
    if any(path.startswith(d + "/") for d in JEV_MANAGED_DIRS):
        return True
    parent = PurePosixPath(path).parent.as_posix()
    return parent == JEV_COMMANDS_DIR and bool(JEV_COMMAND_NAME.fullmatch(PurePosixPath(path).name))


def list_dir_entries(root: safe.SafeRoot, rel: str) -> list[tuple[str, str]]:
    """(name, kind) for entries of rel without following symlinks; kind is 'file', 'dir' or 'other'.

    Uses SafeRoot._open_parent (pinned root descriptor, O_NOFOLLOW on every component) on purpose;
    ai_plc_safe_fs has no public directory-listing helper and is intentionally left unchanged."""
    fd, name = root._open_parent(rel)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        dir_fd = os.open(name, flags, dir_fd=fd)
    finally:
        os.close(fd)
    try:
        result = []
        for child in sorted(os.listdir(dir_fd)):
            st = os.stat(child, dir_fd=dir_fd, follow_symlinks=False)
            kind = "file" if stat.S_ISREG(st.st_mode) else ("dir" if stat.S_ISDIR(st.st_mode) else "other")
            result.append((child, kind))
        return result
    finally:
        os.close(dir_fd)


def jev_backup_candidates(root: safe.SafeRoot) -> list[str]:
    """Leftover <path>.bak.<utc>.<seq> files at experimental-package locations only."""
    found: list[str] = []
    def visit(rel: str) -> None:
        try:
            children = list_dir_entries(root, rel)
        except (FileNotFoundError, NotADirectoryError):
            return
        except OSError as exc:  # e.g. a symlinked directory (ELOOP): never follow it
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                return
            raise
        for child, kind in children:
            path = f"{rel}/{child}"
            if kind == "dir":
                visit(path)
            elif kind == "file" and BACKUP_SUFFIX.fullmatch(child):
                found.append(path)
    for directory in JEV_MANAGED_DIRS:
        visit(directory)
    try:
        children = list_dir_entries(root, JEV_COMMANDS_DIR)
    except OSError as exc:
        if exc.errno not in (errno.ENOENT, errno.ELOOP, errno.ENOTDIR):
            raise
        children = []
    for child, kind in children:
        match = BACKUP_SUFFIX.fullmatch(child)
        if kind == "file" and match and JEV_COMMAND_NAME.fullmatch(match.group("base")):
            found.append(f"{JEV_COMMANDS_DIR}/{child}")
    return found


def remove_backup_if_matches(root: safe.SafeRoot, backup: str, allowed: set[str]) -> bool:
    if not root.exists(backup):
        return False
    st = root.lstat(backup)
    if st is None or not stat.S_ISREG(st.st_mode):
        return False
    if safe.sha256(root.read_bytes(backup)) not in allowed:
        return False
    root.unlink(backup)
    return True


def cleanup_experimental_jev(root: safe.SafeRoot, backups: list[dict[str, Any]], old_files: dict[str, str],
                             known: dict[str, set[str]] | None, deleted: list[str]) -> list[str]:
    """Post-commit cleanup for the experimental package; runs while the installer lock is still held.

    1. Backups taken by this transaction for experimental paths whose content equals the pre-transaction
       manifest hash (i.e. a pristine distributed copy) are removed.
    2. When `known` is given (uninstall), leftover backups from earlier transactions at experimental
       locations are removed if they match the pre-transaction manifest or a known release hash.
    3. Experimental directories emptied by the above are removed, deepest first.
    Core components, shared directories and non-matching files are never touched. Returns warnings."""
    warnings: list[str] = []
    touched_dirs: set[str] = set()
    for item in list(backups):
        path, backup = item.get("path"), item.get("backup")
        if path not in old_files or not isinstance(backup, str) or item.get("sha256") != old_files[path]:
            continue
        match = BACKUP_SUFFIX.fullmatch(backup)
        if not match or match.group("base") != path or not is_jev_location(path):
            continue
        try:
            if remove_backup_if_matches(root, backup, {old_files[path]}):
                touched_dirs.add(PurePosixPath(backup).parent.as_posix())
        except (OSError, safe.InstallError) as exc:
            warnings.append(f"backup kept: {backup} ({exc})")
    if known is not None:
        try:
            candidates = jev_backup_candidates(root)
        except (OSError, safe.InstallError) as exc:
            candidates = []
            warnings.append(f"backup scan skipped ({exc})")
        kept = 0
        for backup in candidates:
            base = BACKUP_SUFFIX.fullmatch(PurePosixPath(backup).name).group("base")
            base_path = f"{PurePosixPath(backup).parent.as_posix()}/{base}"
            allowed = set(known.get(base_path, set()))
            if base_path in old_files:
                allowed.add(old_files[base_path])
            try:
                if remove_backup_if_matches(root, backup, allowed):
                    touched_dirs.add(PurePosixPath(backup).parent.as_posix())
                else:
                    kept += 1
            except (OSError, safe.InstallError) as exc:
                kept += 1
                warnings.append(f"backup kept: {backup} ({exc})")
        if kept:
            warnings.append(f"{kept} backup file(s) with unknown content kept")
    for path in deleted:
        if path in old_files:
            touched_dirs.add(PurePosixPath(path).parent.as_posix())
    prune: set[str] = set()
    for directory in touched_dirs:
        for top in JEV_MANAGED_DIRS:
            if directory == top or directory.startswith(top + "/"):
                current = PurePosixPath(directory)
                while True:
                    prune.add(current.as_posix())
                    if current.as_posix() == top:
                        break
                    current = current.parent
    for directory in sorted(prune, key=lambda d: (-d.count("/"), d)):
        try:
            st = root.lstat(directory)
            if st is not None and stat.S_ISDIR(st.st_mode):
                root.prune_empty_dir(directory)
        except (OSError, safe.InstallError) as exc:
            warnings.append(f"directory kept: {directory} ({exc})")
    if known is not None:
        for top in JEV_MANAGED_DIRS:
            if top in prune and root.exists(top):
                warnings.append(f"directory kept (not empty): {top}")
    return warnings


def run_jev_cleanup(root: safe.SafeRoot, state: dict[str, Any], distribution: Path) -> list[str]:
    spec = state.get(JEV_CLEANUP_KEY) or {}
    old_files = {str(k): str(v) for k, v in (spec.get("old_files") or {}).items() if is_jev_location(str(k))}
    known = load_known_jev_hashes(distribution) if spec.get("sweep") else None
    return cleanup_experimental_jev(root, list(state.get("backups") or []), old_files, known,
                                    [str(x) for x in spec.get("deleted") or []])


def commit_with_jev_cleanup(tx: safe.Transaction, root: safe.SafeRoot, distribution: Path,
                            old_files: dict[str, str], deleted: list[str], sweep: bool) -> list[str]:
    """Mark the transaction committed, run the cleanup while the lock is still held, then release it.

    The cleanup parameters are stored in the committed journal. If the process dies during the cleanup,
    recovery completes the transaction without rollback and main() resumes the cleanup (see
    pending_jev_cleanup). If releasing the lock fails, the error is marked `committed` so the caller
    does not roll back a transaction whose backups may already be gone."""
    tx.state[JEV_CLEANUP_KEY] = {"old_files": old_files, "deleted": sorted(deleted), "sweep": sweep}
    tx.state["phase"] = "committed"
    tx.save()
    try:
        warnings = run_jev_cleanup(root, tx.state, distribution)
    except Exception as exc:  # cleanup is best effort; the committed install/uninstall stands
        warnings = [f"cleanup skipped ({exc})"]
    try:
        tx.commit()
    except Exception as exc:
        error = safe.InstallError(f"committed, but releasing the installer lock failed ({exc}); rerun to recover")
        error.committed = True  # type: ignore[attr-defined]
        raise error from exc
    return warnings


def print_jev_warnings(warnings: list[str]) -> None:
    if warnings:
        print("[WARN] experimental_jev: " + "; ".join(warnings))


def pending_jev_cleanup(root: safe.SafeRoot) -> dict[str, Any] | None:
    """Read-only peek: a dead transaction whose committed journal still asks for the experimental cleanup."""
    try:
        if not root.exists(safe.LOCK):
            return None
        journal = str(json.loads(root.read_bytes(safe.LOCK)).get("journal_name", ""))
        if not journal.startswith(safe.JOURNAL_PREFIX) or "/" in journal or not root.exists(journal):
            return None
        state = json.loads(root.read_bytes(journal))
    except Exception:
        return None
    if state.get("phase") == "committed" and isinstance(state.get(JEV_CLEANUP_KEY), dict):
        return state
    return None


def resume_jev_cleanup(root: safe.SafeRoot, state: dict[str, Any], distribution: Path) -> None:
    tx = safe.Transaction(root)
    tx.acquire()
    try:
        warnings = run_jev_cleanup(root, state, distribution)
    except Exception as exc:
        warnings = [f"cleanup skipped ({exc})"]
    tx.commit()
    print("[OK] experimental_jev cleanup resumed after recovery")
    print_jev_warnings(warnings)


def execute_install(distribution: Path, root: safe.SafeRoot, mode: str,
                    migrate_legacy: str | None, with_jev: bool = False) -> int:
    tx = safe.Transaction(root)
    tx.acquire()
    try:
        safe.validate_or_consume_tombstone(root, mutate=True)
        safe.assert_fresh_transaction_artifacts(root, tx)
        old_jev = jev_files(safe.load_manifest(root)) if with_jev else {}
        plan = build_install_plan(distribution, root, mode, migrate_legacy, lock_held=True, with_jev=with_jev)
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
        warnings: list[str] = []
        if with_jev:
            warnings = commit_with_jev_cleanup(tx, root, distribution, old_jev, plan["stale_files"], False)
        else:
            tx.commit()
    except Exception as exc:
        if not getattr(exc, "committed", False):
            tx.rollback()
        raise
    print(f"[OK] {plan['mode']} install committed: {changed} changed file(s)")
    print_jev_warnings(warnings)
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
        old_manifest = safe.load_manifest(root)
        plan = build_uninstall_plan(distribution, root, mode)
        old_jev = jev_files(old_manifest)
        jev_removed = (JEV_COMPONENT in ((old_manifest or {}).get("components") or {})
                       and JEV_COMPONENT not in plan["manifest"].get("components", {}))
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
        warnings: list[str] = []
        if jev_removed:
            warnings = commit_with_jev_cleanup(tx, root, distribution, old_jev, sorted(old_jev), True)
        else:
            tx.commit()
    except Exception as exc:
        if not getattr(exc, "committed", False):
            tx.rollback()
        raise
    print(f"[OK] {plan['mode']} uninstall committed: {changed} changed file(s)")
    print_jev_warnings(warnings)
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
    p.add_argument("--with-jev", action="store_true",
                   help="install only: also install experimental/jev (Claude Code only: cc, both, all)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.with_jev and args.action != "install":
        raise safe.InstallError("--with-jev is only valid for install; uninstall removes experimental/jev with cc")
    if args.with_jev and "cc" not in ENVIRONMENTS[args.mode]:
        raise safe.InstallError(JEV_ONLY_CC)
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
            pending = pending_jev_cleanup(root)
            safe.recover_if_needed(root)
            if pending:
                resume_jev_cleanup(root, pending, distribution)
        else:
            safe.validate_or_consume_tombstone(root, mutate=False)
        plan = (build_install_plan(distribution, root, args.mode, args.migrate_legacy, with_jev=args.with_jev)
                if args.action == "install" else build_uninstall_plan(distribution, root, args.mode))
        if args.dry_run or args.plan_only:
            summary = {k: plan[k] for k in ("mode", "conflicts")}
            summary["writes" if args.action == "install" else "deletes"] = plan["writes" if args.action == "install" else "deletes"]
            print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
            return 1 if plan["conflicts"] else 0
        if args.action == "install":
            execute_install(distribution, root, args.mode, args.migrate_legacy, args.with_jev)
        else:
            execute_uninstall(distribution, root, args.mode)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (safe.InstallError, OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2)
