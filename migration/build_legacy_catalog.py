#!/usr/bin/env python3
"""Build legacy-release catalogs for AI-PLC releases that predate the install manifest.

For every tag, the tag's own install-cc.sh / install-cursor.sh is run against an empty git
directory; the installed result (not the source tree) is hashed. Tags whose installed
inventories are identical are grouped into one catalog named after the group's first release.

Standard library only. The repository's .git is only read (``git archive``); every tag is
extracted with ``git archive <tag> | tar -x`` into a temporary directory that is removed on exit.

Usage:
  python3 migration/build_legacy_catalog.py                 # write catalogs + INDEX
  python3 migration/build_legacy_catalog.py --check         # regenerate in memory, compare with files
  python3 migration/build_legacy_catalog.py --work-dir DIR  # parent for temporary directories

The existing 1.1.0.yaml is never rewritten: its group is regenerated and compared with the
file (inventory equality) to validate the generator.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CATALOG_DIR = HERE / "legacy-releases"
INDEX_NAME = "INDEX"
PRESERVED = {"1.1.0.yaml"}  # hand-verified catalog; compared, never rewritten
DEFAULT_TAGS = (
    "v1.1.0", "v1.1.1", "v1.2.0", "v1.2.1", "v1.3.0", "v1.3.1", "v1.3.2", "v1.3.3",
    "v1.4.0", "v1.4.1", "v1.5.0", "v1.6.0",
)
ENVS = ("cc", "cursor")
START = "<!-- AI-PLC START -->"
END = "<!-- AI-PLC END -->"
REGIONS = {  # installed file -> (region id, distributed template)
    "CLAUDE.md": ("CLAUDE.md#ai-plc-cc", "claude/CLAUDE.md.template"),
    "AGENTS.md": ("AGENTS.md#ai-plc-cc", "claude/AGENTS.md.template"),
}
# User data seeded by the installers. Never catalogued as managed files (explicit list).
USER_DATA_EXCLUSIONS = {
    "cc": (".claude/settings.json", ".claude/soul.md", ".claude/wiki/**", ".claude/db/ai_plc.db"),
    "cursor": (".cursor/wiki/**", ".cursor/db/ai_plc.db"),
}
ALL_EXCLUSIONS = tuple(sorted({p for items in USER_DATA_EXCLUSIONS.values() for p in items}))
MARKERS = {
    "cc": (".claude/commands/01-collection.md",),
    "cursor": (".cursor/skills/ai-plc/01-collection/SKILL.md", ".cursor/rules/ai-plc-system.mdc"),
}
# installed prefix -> distributed prefix, per environment (verified by hash; fallback search by hash)
SOURCE_PREFIXES = {
    "cc": ((".claude/skills/", "core/skills/"), (".claude/rules/", "core/rules/"),
           (".claude/commands/", "claude/commands/"), (".claude/agents/", "claude/agents/"),
           (".claude/db/", "core/db/")),
    "cursor": ((".cursor/skills/", "core/skills/"), (".cursor/rules/", "cursor/rules/"),
               (".cursor/db/", "core/db/")),
}


class BuildError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, check=False)


def excluded(path: str) -> bool:
    for pattern in ALL_EXCLUSIONS:
        if pattern.endswith("/**"):
            if path.startswith(pattern[:-2]):
                return True
        elif path == pattern:
            return True
    return False


def extract(repo: Path, tag: str, dest: Path) -> None:
    """git archive <tag> | tar -x -C dest (no worktree, the repository is only read)."""
    dest.mkdir(parents=True)
    archive = subprocess.Popen(["git", "-C", str(repo), "archive", "--format=tar", tag],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    tar = subprocess.run(["tar", "-x", "-C", str(dest)], stdin=archive.stdout, capture_output=True, check=False)
    assert archive.stdout is not None
    archive.stdout.close()
    archive_err = archive.stderr.read() if archive.stderr else b""
    if archive.wait() != 0 or tar.returncode != 0:
        raise BuildError(f"extract {tag} failed: {archive_err.decode(errors='replace')} {tar.stderr.decode(errors='replace')}")


def walk(root: Path) -> list[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root)
        if rel_dir.parts[:1] == (".git",):
            dirnames[:] = []
            continue
        dirnames[:] = sorted(d for d in dirnames if not (rel_dir == Path(".") and d == ".git"))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink() or not path.is_file():
                raise BuildError(f"unexpected non-regular file installed: {path.relative_to(root)}")
            found.append((rel_dir / name).as_posix())
    return found


def region_bytes(data: bytes) -> bytes:
    text = data.decode("utf-8")
    if text.count(START) != 1 or text.count(END) != 1:
        raise BuildError("installed region markers are missing or duplicated")
    _, rest = text.split(START, 1)
    middle, _ = rest.split(END, 1)
    return (START + middle + END).encode()


def find_source(env: str, path: str, digest: str, source: Path, source_hashes: dict[str, list[str]]) -> str:
    if path == ".ai-plc-version":
        candidates = [".ai-plc-version"]
    else:
        candidates = [dst + path[len(src):] for src, dst in SOURCE_PREFIXES[env] if path.startswith(src)]
    for candidate in candidates:
        file = source / candidate
        if file.is_file() and sha256(file.read_bytes()) == digest:
            return candidate
    matches = source_hashes.get(digest, [])
    if matches:  # longest common suffix wins
        name = PurePosixPath(path).parts
        return max(matches, key=lambda m: (sum(1 for a, b in zip(reversed(PurePosixPath(m).parts), reversed(name)) if a == b), m))
    raise BuildError(f"{env}: no distributed source for installed file {path}")


def installed_inventory(tag: str, source: Path, work: Path) -> dict[str, Any]:
    source_hashes: dict[str, list[str]] = {}
    for rel in walk(source):
        source_hashes.setdefault(sha256((source / rel).read_bytes()), []).append(rel)
    result: dict[str, Any] = {}
    for env in ENVS:
        target = work / f"target-{env}"
        target.mkdir()
        init = run(["git", "init", "-q"], cwd=target)
        if init.returncode != 0:
            raise BuildError(f"git init failed: {init.stderr.decode(errors='replace')}")
        script = source / f"install-{'cc' if env == 'cc' else 'cursor'}.sh"
        installed = run(["bash", str(script), "--target", str(target)], cwd=target)
        if installed.returncode != 0:
            raise BuildError(f"{tag} {script.name} failed ({installed.returncode}): {installed.stderr.decode(errors='replace')}")
        files: dict[str, dict[str, str]] = {}
        regions: dict[str, dict[str, str]] = {}
        exclusions_seen: list[str] = []
        for rel in walk(target):
            data = (target / rel).read_bytes()
            if rel in REGIONS:
                region_id, template = REGIONS[rel]
                regions[region_id] = {
                    "path": rel, "source": template, "start_marker": START, "end_marker": END,
                    "content_sha256": sha256(region_bytes(data)),
                }
                continue
            if excluded(rel):
                exclusions_seen.append(rel)
                continue
            digest = sha256(data)
            files[rel] = {"source": find_source(env, rel, digest, source, source_hashes), "source_sha256": digest}
        for marker in MARKERS[env]:
            if marker not in files:
                raise BuildError(f"{tag}: {env} marker not installed: {marker}")
        result[env] = {"managed_files": files, "managed_regions": regions, "excluded_seen": exclusions_seen}
    return result


def inventory_key(inventory: dict[str, Any]) -> str:
    rows = []
    for env in ENVS:
        rows += [f"{env}:file:{p}:{v['source_sha256']}" for p, v in inventory[env]["managed_files"].items()]
        rows += [f"{env}:region:{r}:{v['content_sha256']}" for r, v in inventory[env]["managed_regions"].items()]
    return sha256("\n".join(sorted(rows)).encode())


def q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render(versions: list[str], tag: str, commit: str, inventory: dict[str, Any]) -> str:
    lines = [
        "schema_version: 1",
        f"release_version: {q(versions[0])}",
        "release_versions: [" + ", ".join(q(v) for v in versions) + "]",
        f"source_ref: {q('refs/tags/' + tag)}",
        f"source_commit: {q(commit)}",
        "hash_algorithm: sha256",
        "environments:",
    ]
    for env in ENVS:
        inv = inventory[env]
        lines += [f"  {env}:", "    authoritative_markers:"]
        for marker in MARKERS[env]:
            lines += ["      - type: file", f"        path: {q(marker)}",
                      f"        source_sha256: {q(inv['managed_files'][marker]['source_sha256'])}"]
        for region_id in sorted(inv["managed_regions"], key=lambda r: list(REGIONS).index(inv["managed_regions"][r]["path"])):
            lines += ["      - type: region", f"        id: {q(region_id)}",
                      f"        start_marker: {q(START)}", f"        end_marker: {q(END)}"]
        lines.append("    managed_files:")
        for path in sorted(inv["managed_files"], key=lambda p: (p.lower(), p)):
            item = inv["managed_files"][path]
            lines += [f"      {q(path)}:", f"        source: {q(item['source'])}",
                      f"        source_revision: {q(tag)}", f"        source_sha256: {q(item['source_sha256'])}"]
        if inv["managed_regions"]:
            lines.append("    managed_regions:")
            for region_id in sorted(inv["managed_regions"], key=lambda r: list(REGIONS).index(inv["managed_regions"][r]["path"])):
                item = inv["managed_regions"][region_id]
                lines += [f"      {q(region_id)}:", f"        path: {q(item['path'])}", f"        source: {q(item['source'])}",
                          f"        source_revision: {q(tag)}", f"        start_marker: {q(item['start_marker'])}",
                          f"        end_marker: {q(item['end_marker'])}", f"        content_sha256: {q(item['content_sha256'])}"]
        else:
            lines.append("    managed_regions: {}")
        lines.append("    user_data_exclusions:")
        lines += [f"      - {q(p)}" for p in USER_DATA_EXCLUSIONS[env]]
    lines += ["composition:", "  cc_only: [cc]", "  cursor_only: [cursor]", "  both: [cc, cursor]"]
    return "\n".join(lines) + "\n"


def load_safe_fs() -> Any:
    spec = importlib.util.spec_from_file_location("ai_plc_safe_fs_catalog", REPO / "lib/ai_plc_safe_fs.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parsed_inventory(content: bytes) -> dict[str, Any]:
    """Inventory (path/region -> hash) as the installer reads it."""
    parsed = load_safe_fs().parse_legacy_catalog(content)
    return {env: {
        "files": {p: v.get("source_sha256") for p, v in parsed.get(env, {}).get("managed_files", {}).items()},
        "regions": {r: (v.get("path"), v.get("content_sha256"), v.get("start_marker"), v.get("end_marker"))
                    for r, v in parsed.get(env, {}).get("managed_regions", {}).items()},
    } for env in ENVS}


def build(repo: Path, tags: list[str], work_parent: Path | None) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    work = Path(tempfile.mkdtemp(prefix="ai-plc-legacy-catalog-", dir=str(work_parent) if work_parent else None))
    try:
        for tag in tags:
            tag_dir = work / tag
            extract(repo, tag, tag_dir / "src")
            inventory = installed_inventory(tag, tag_dir / "src", tag_dir)
            commit = run(["git", "-C", str(repo), "rev-list", "-n", "1", tag]).stdout.decode().strip()
            key = inventory_key(inventory)
            shutil.rmtree(tag_dir)
            if groups and groups[-1]["key"] == key:
                groups[-1]["tags"].append(tag)
                continue
            if any(g["key"] == key for g in groups):
                raise BuildError(f"{tag} repeats an earlier, non-adjacent inventory; review grouping manually")
            groups.append({"key": key, "tags": [tag], "commit": commit, "inventory": inventory})
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for group in groups:
        versions = [t.removeprefix("v") for t in group["tags"]]
        group["versions"] = versions
        group["name"] = f"{versions[0]}.yaml"
        group["text"] = render(versions, group["tags"][0], group["commit"], group["inventory"])
    return groups


def verify(groups: list[dict[str, Any]], catalog_dir: Path) -> list[str]:
    problems: list[str] = []
    for group in groups:
        generated = group["text"].encode()
        inventory = parsed_inventory(generated)
        for env in ENVS:
            leaked = [p for p in inventory[env]["files"] if excluded(p) or p in REGIONS]
            if leaked:
                problems.append(f"{group['name']} {env}: user data in managed_files: {leaked}")
        existing = catalog_dir / group["name"]
        if group["name"] in PRESERVED:
            if not existing.is_file():
                problems.append(f"{group['name']}: preserved catalog missing")
            elif parsed_inventory(existing.read_bytes()) != inventory:
                problems.append(f"{group['name']}: regenerated inventory differs from the preserved catalog")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, default=REPO, help="git repository holding the release tags")
    parser.add_argument("--out", type=Path, default=CATALOG_DIR, help="catalog directory")
    parser.add_argument("--tags", help="comma-separated tags (default: v1.1.0 .. v1.6.0)")
    parser.add_argument("--work-dir", type=Path, help="parent directory for temporary files")
    parser.add_argument("--check", action="store_true", help="compare with the files on disk; write nothing")
    args = parser.parse_args(argv)
    tags = args.tags.split(",") if args.tags else list(DEFAULT_TAGS)
    groups = build(args.repo, tags, args.work_dir)
    problems = verify(groups, args.out)
    index = "".join(g["name"] + "\n" for g in groups)
    for group in groups:
        print(f"{group['name']}: {', '.join(group['versions'])} "
              f"(cc {len(group['inventory']['cc']['managed_files'])} files, "
              f"cursor {len(group['inventory']['cursor']['managed_files'])} files)")
    if args.check:
        for group in groups:
            path = args.out / group["name"]
            if group["name"] not in PRESERVED and (not path.is_file() or path.read_text() != group["text"]):
                problems.append(f"{group['name']}: out of date")
        if not (args.out / INDEX_NAME).is_file() or (args.out / INDEX_NAME).read_text() != index:
            problems.append(f"{INDEX_NAME}: out of date")
    elif not problems:
        args.out.mkdir(parents=True, exist_ok=True)
        for group in groups:
            if group["name"] not in PRESERVED:
                (args.out / group["name"]).write_text(group["text"])
        (args.out / INDEX_NAME).write_text(index)
    for problem in problems:
        print(f"[ERROR] {problem}", file=sys.stderr)
    if not problems:
        print("[OK] " + ("catalogs are up to date" if args.check else f"wrote {INDEX_NAME} and {len(groups)} catalog group(s)"))
    return 1 if problems else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2)
