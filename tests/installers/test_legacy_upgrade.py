#!/usr/bin/env python3
"""Upgrade-path tests: legacy releases without a manifest, and manifest releases (v1.7.x / v1.8.0-exp.1).

Standard library only. Fixtures are real installs made by each tag's own installer: every tag is
extracted with ``git archive <tag> | tar -x`` into a temporary directory under /private/tmp (the
repository's .git is only read), installed into a throwaway git repository, and removed on exit.

    python3 -m unittest tests/installers/test_legacy_upgrade.py -v

Covered: automatic detection for every legacy group (G1-G6) x CC/Cursor, dry-run / --plan-only with
zero changes, idempotent re-run, edited files (stop + hint, or --backup-modified), ambiguity and the
below-threshold stop, the superset rule (G3 contains G2) and its cancellation when only G3's db is
edited, targets upgraded step by step with the old installers, different releases per environment,
--with-jev, ordinary updates from v1.7.0 / v1.7.1 / v1.8.0-exp.1, the manifest-write fault injection
(rollback restores the target; the next run succeeds), legacy uninstall and catalog index errors.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
from fault_driver import IsolatedDistribution, patch_copy, tree_snapshot  # noqa: E402

sys.dont_write_bytecode = True
sys.path.insert(0, str(REPO / "lib"))
import ai_plc_safe_fs as safe_fs  # noqa: E402

TMP = "/private/tmp"
VERSION = (REPO / ".ai-plc-version").read_text().strip()
MANIFEST = ".ai-plc-install-manifest"
# Legacy groups: catalog name -> tags whose installed result is that catalog (T002).
GROUPS = {
    "1.1.0": ("v1.1.0",),
    "1.1.1": ("v1.1.1",),
    "1.2.0": ("v1.2.0",),
    "1.2.1": ("v1.2.1", "v1.3.0", "v1.3.1", "v1.3.2", "v1.3.3", "v1.4.0", "v1.4.1"),
    "1.5.0": ("v1.5.0",),
    "1.6.0": ("v1.6.0",),
}
MANIFEST_TAGS = ("v1.7.0", "v1.7.1", "v1.8.0-exp.1")
JEV_MARKER_FILE = ".claude/skills/ai-plc-jev/README.md"
RULE = ".claude/rules/ai-plc-system.md"
CURSOR_RULE = ".cursor/rules/ai-plc-system.mdc"
SKILL = ".claude/skills/ai-plc/02-inception/SKILL.md"
DB_SCRIPT = ".claude/db/plc_query.py"

_WORK: Path | None = None
_SOURCES: dict[str, Path] = {}
_FIXTURES: dict[tuple, Path] = {}


def setUpModule() -> None:
    global _WORK
    _WORK = Path(tempfile.mkdtemp(prefix="ai-plc-legacy-upgrade-", dir=TMP))


def tearDownModule() -> None:
    if _WORK is not None:
        shutil.rmtree(_WORK, ignore_errors=True)


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=cwd, stdin=subprocess.DEVNULL, text=True,
                          capture_output=True, timeout=300, check=False)


def source(tag: str) -> Path:
    """The tag's tree, extracted once with git archive | tar -x (no worktree)."""
    if tag not in _SOURCES:
        assert _WORK is not None
        dest = _WORK / "src" / tag
        dest.mkdir(parents=True)
        archive = subprocess.Popen(["git", "-C", str(REPO), "archive", "--format=tar", tag],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        tar = subprocess.run(["tar", "-x", "-C", str(dest)], stdin=archive.stdout, capture_output=True, check=False)
        assert archive.stdout is not None
        archive.stdout.close()
        err = archive.stderr.read() if archive.stderr else b""
        if archive.stderr:
            archive.stderr.close()
        if archive.wait() != 0 or tar.returncode != 0:
            raise AssertionError(f"extract {tag} failed: {err!r} {tar.stderr!r}")
        _SOURCES[tag] = dest
    return _SOURCES[tag]


def old_install(tag: str, how: str, root: Path) -> None:
    """Install one release with that release's own installer.

    how: "cc" / "cursor" for legacy releases (install-cc.sh / install-cursor.sh), or install.sh
    arguments for manifest releases (e.g. "cc --with-jev")."""
    src = source(tag)
    if tag in MANIFEST_TAGS:
        result = run("bash", str(src / "install.sh"), *how.split(), "--target", str(root))
    else:
        result = run("bash", str(src / f"install-{how}.sh"), "--target", str(root), cwd=root)
    if result.returncode != 0:
        raise AssertionError(f"{tag} install {how} failed: {result.stdout}\n{result.stderr}")


@contextlib.contextmanager
def fixture(*steps: tuple[str, str]):
    """A private copy of a target built by the given old installs (built once, copied per use)."""
    assert _WORK is not None
    if steps not in _FIXTURES:
        base = _WORK / "fixtures" / f"f{len(_FIXTURES)}"
        base.mkdir(parents=True)
        assert run("git", "init", "-q", cwd=base).returncode == 0
        for tag, how in steps:
            old_install(tag, how, base)
        _FIXTURES[steps] = base
    with tempfile.TemporaryDirectory(prefix="ai-plc-legacy-target-", dir=TMP) as name:
        root = Path(name) / "target"
        shutil.copytree(_FIXTURES[steps], root, symlinks=True)
        yield root


def install(root: Path, mode: str, *extra: str, dist: Path = REPO) -> subprocess.CompletedProcess[str]:
    return run("bash", str(dist / "install.sh"), mode, "--target", str(root), *extra)


def uninstall(root: Path, mode: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return run("bash", str(REPO / "uninstall.sh"), mode, "--target", str(root), *extra)


def manifest(root: Path) -> dict:
    return json.loads((root / MANIFEST).read_text())


def changed_count(result: subprocess.CompletedProcess[str]) -> int:
    match = re.search(r"install committed: ([0-9]+) changed file", result.stdout)
    if not match:
        raise AssertionError(f"no commit line: {result.stdout}\n{result.stderr}")
    return int(match.group(1))


def parse_catalog(name: str) -> dict:
    return safe_fs.parse_legacy_catalog((REPO / "migration/legacy-releases" / name).read_bytes())


def inventory_items(name: str, env: str) -> set[tuple[str, str]]:
    parsed = parse_catalog(name)[env]
    items = {(p, i["source_sha256"]) for p, i in parsed["managed_files"].items()}
    items |= {(r, i["content_sha256"]) for r, i in parsed["managed_regions"].items()}
    return items


def append(path: Path, text: str) -> None:
    path.write_text(path.read_text() + text)


def edit_region(path: Path) -> None:
    text = path.read_text()
    assert text.count("<!-- AI-PLC END -->") == 1
    path.write_text(text.replace("<!-- AI-PLC END -->", "my own line inside the region\n<!-- AI-PLC END -->"))


def jev_package_files(tree: Path) -> dict[str, bytes]:
    """The files --with-jev installs (skills/, commands/, and files directly inside scripts/)."""
    base = tree / "experimental/jev"
    found = {}
    for sub in ("skills", "commands", "scripts"):
        for path in (base / sub).rglob("*"):
            rel = path.relative_to(base).as_posix()
            if path.is_file() and "__pycache__" not in rel and (sub != "scripts" or rel.count("/") == 1):
                found[rel] = path.read_bytes()
    return found


class Base(unittest.TestCase):
    maxDiff = None

    def dry(self, root: Path, mode: str, *extra: str, dist: Path = REPO, expect: int = 0) -> tuple[dict, str]:
        before = tree_snapshot(root)
        result = install(root, mode, "--dry-run", *extra, dist=dist)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        self.assertEqual(tree_snapshot(root), before, "dry-run changed the target")
        plan_only = install(root, mode, "--plan-only", *extra, dist=dist)
        self.assertEqual(plan_only.returncode, expect, plan_only.stderr)
        self.assertEqual(tree_snapshot(root), before, "--plan-only changed the target")
        return json.loads(result.stdout), result.stderr

    def refused(self, root: Path, mode: str, *extra: str, dist: Path = REPO) -> subprocess.CompletedProcess[str]:
        before = tree_snapshot(root)
        result = install(root, mode, *extra, dist=dist)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(tree_snapshot(root), before, "a refused install changed the target")
        return result

    def installed(self, root: Path, mode: str, *extra: str, dist: Path = REPO) -> subprocess.CompletedProcess[str]:
        result = install(root, mode, *extra, dist=dist)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = manifest(root)
        self.assertNotIn(".ai-plc-version", data["managed_files"])  # P1-1
        self.assertEqual((root / ".ai-plc-version").read_text(), VERSION + "\n")
        rerun = [a for i, a in enumerate(extra) if a != "--migrate-legacy" and (i == 0 or extra[i - 1] != "--migrate-legacy")]
        again = install(root, mode, *rerun, dist=dist)  # --migrate-legacy is only valid without a manifest
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(changed_count(again), 0, "re-run is not idempotent")
        return result


class PristineLegacyGroups(Base):
    """G1-G6 x CC/Cursor: no flag, detected automatically, dry-run changes nothing, install succeeds."""

    def test_every_legacy_tag_and_environment(self) -> None:
        for catalog, tags in GROUPS.items():
            for tag in tags:
                for env in ("cc", "cursor"):
                    with self.subTest(tag=tag, env=env), fixture((tag, env)) as root:
                        summary, stderr = self.dry(root, env)
                        release = summary["legacy_release"][env]
                        self.assertEqual((release["catalog"], release["match"]), (catalog, "exact"))
                        self.assertIn(tag.removeprefix("v"), release["versions"])
                        self.assertEqual((release["modified"], release["missing"], summary["conflicts"]), ([], [], []))
                        self.assertIn(f"catalog {catalog})", stderr)
                        self.assertNotIn("[HINT]", stderr)
                        result = self.installed(root, env)
                        self.assertIn("[INFO] legacy release detected", result.stderr)
                        self.assertNotIn("[BACKUP]", result.stdout)
                        self.assertEqual(manifest(root)["environments"], {env: {"version": VERSION}})
                        self.assertNotIn("user_backups", manifest(root))

    def test_group_display_names_the_tag_range(self) -> None:
        with fixture(("v1.3.3", "cc")) as root:
            _, stderr = self.dry(root, "cc")
            self.assertIn("[INFO] legacy release detected: cc v1.2.1–v1.4.1 (catalog 1.2.1)", stderr)

    def test_both_mode_and_with_jev(self) -> None:
        with fixture(("v1.3.3", "cc"), ("v1.3.3", "cursor")) as root:
            summary, _ = self.dry(root, "both")
            self.assertEqual({e: r["catalog"] for e, r in summary["legacy_release"].items()},
                             {"cc": "1.2.1", "cursor": "1.2.1"})
            self.installed(root, "both")
            self.assertEqual(set(manifest(root)["environments"]), {"cc", "cursor"})
        with fixture(("v1.3.3", "cc")) as root:
            self.installed(root, "cc", "--with-jev")
            self.assertTrue((root / JEV_MARKER_FILE).is_file())
            self.assertIn("experimental_jev", manifest(root)["components"])

    def test_cc_only_install_also_adopts_exact_cursor(self) -> None:
        with fixture(("v1.1.1", "cc"), ("v1.1.1", "cursor")) as root:
            summary, _ = self.dry(root, "cc")
            self.assertEqual(set(summary["legacy_release"]), {"cc", "cursor"})
            self.installed(root, "cc")
            result = install(root, "cursor")
            self.assertEqual(result.returncode, 0, result.stderr)


class SupersetRules(Base):
    """P1-2 (G3 contains G2) and the T001 §9 cancellation when only G3's db is edited."""

    def test_g3_is_a_strict_superset_of_g2_and_wins(self) -> None:
        for env in ("cc", "cursor"):
            with self.subTest(env=env):
                self.assertLess(inventory_items("1.1.1.yaml", env), inventory_items("1.2.0.yaml", env))
                with fixture(("v1.2.0", env)) as root:
                    summary, _ = self.dry(root, env)
                    self.assertEqual(summary["legacy_release"][env]["catalog"], "1.2.0")
                with fixture(("v1.1.1", env)) as root:
                    summary, _ = self.dry(root, env)
                    self.assertEqual(summary["legacy_release"][env]["catalog"], "1.1.1")

    def test_g3_with_only_db_edited_is_not_taken_for_g2(self) -> None:
        self.assertNotIn(DB_SCRIPT, parse_catalog("1.1.1.yaml")["cc"]["managed_files"])
        self.assertIn(DB_SCRIPT, parse_catalog("1.2.0.yaml")["cc"]["managed_files"])
        with fixture(("v1.2.0", "cc")) as root:
            append(root / DB_SCRIPT, "# local change\n")
            summary, stderr = self.dry(root, "cc", expect=1)
            self.assertNotIn("legacy_release", summary)  # not adopted as 1.1.1
            self.assertIn(f"unmanaged file collision: {DB_SCRIPT}", summary["conflicts"])
            self.assertEqual(stderr.count("[HINT]"), 1)
            self.refused(root, "cc")
            summary, _ = self.dry(root, "cc", "--backup-modified")
            release = summary["legacy_release"]["cc"]
            self.assertEqual((release["catalog"], release["match"], release["modified"]),
                             ("1.2.0", "estimated", [DB_SCRIPT]))
            result = self.installed(root, "cc", "--backup-modified")
            self.assertIn(f"[BACKUP] {DB_SCRIPT} -> ", result.stdout)
            rows = manifest(root)["user_backups"]
            self.assertEqual([r["path"] for r in rows], [DB_SCRIPT])
            self.assertTrue((root / rows[0]["backup"]).read_text().endswith("# local change\n"))

    def test_g3_with_a_db_file_deleted_is_restored(self) -> None:
        with fixture(("v1.2.0", "cc")) as root:
            (root / DB_SCRIPT).unlink()
            summary, _ = self.dry(root, "cc", "--backup-modified")
            release = summary["legacy_release"]["cc"]
            self.assertEqual((release["catalog"], release["missing"]), ("1.2.0", [DB_SCRIPT]))
            self.assertIn(DB_SCRIPT, summary["restored_missing"])
            result = self.installed(root, "cc", "--backup-modified")
            self.assertIn("[RESTORED]", result.stdout)
            self.assertTrue((root / DB_SCRIPT).is_file())


class EditedLegacyTargets(Base):
    """Edited files: stop with one hint and no change, or back up and continue with --backup-modified."""

    def test_cc_edits_without_and_with_flag(self) -> None:
        with fixture(("v1.3.3", "cc")) as root:
            append(root / RULE, "\nmy rule\n")
            edit_region(root / "CLAUDE.md")
            append(root / "CLAUDE.md", "\nmy notes outside the markers\n")
            (root / SKILL).unlink()
            summary, stderr = self.dry(root, "cc", expect=1)
            self.assertTrue(summary["conflicts"])
            self.assertEqual(stderr.count("[HINT]"), 1)
            result = self.refused(root, "cc")
            self.assertEqual(result.stderr.count("[HINT]"), 1)
            edited_rule = (root / RULE).read_text()
            summary, _ = self.dry(root, "cc", "--backup-modified")
            release = summary["legacy_release"]["cc"]
            self.assertEqual((release["catalog"], release["match"]), ("1.2.1", "estimated"))
            self.assertEqual(sorted(release["modified"]), sorted([RULE, "CLAUDE.md#ai-plc-cc"]))
            self.assertEqual(release["missing"], [SKILL])
            self.assertEqual(sorted(b["path"] for b in summary["backups"]), sorted([RULE, "CLAUDE.md"]))
            result = self.installed(root, "cc", "--backup-modified")
            self.assertEqual(result.stdout.count("[BACKUP] "), 2)
            self.assertIn("[RESTORED]", result.stdout)
            self.assertIn("[NOTE]", result.stdout)
            rows = {r["path"]: r for r in manifest(root)["user_backups"]}
            self.assertEqual(set(rows), {RULE, "CLAUDE.md"})
            self.assertEqual((root / rows[RULE]["backup"]).read_text(), edited_rule)
            self.assertIn("my own line inside the region", (root / rows["CLAUDE.md"]["backup"]).read_text())
            claude = (root / "CLAUDE.md").read_text()
            self.assertIn("my notes outside the markers", claude)
            self.assertNotIn("my own line inside the region", claude)
            self.assertTrue((root / SKILL).is_file())

    def test_cursor_edit_with_flag(self) -> None:
        with fixture(("v1.5.0", "cursor")) as root:
            append(root / CURSOR_RULE, "\nmy cursor rule\n")
            self.dry(root, "cursor", expect=1)
            self.refused(root, "cursor")
            summary, _ = self.dry(root, "cursor", "--backup-modified")
            self.assertEqual(summary["legacy_release"]["cursor"]["catalog"], "1.5.0")
            self.installed(root, "cursor", "--backup-modified")
            self.assertEqual([r["path"] for r in manifest(root)["user_backups"]], [CURSOR_RULE])

    def test_heavy_edits_stop_even_with_flag(self) -> None:
        # Every skill edited. v1.5.0: the best catalog is unique but matches 45% (< 50%).
        # v1.3.3: 1.2.0 and 1.2.1 tie at the same count without forming a chain (ambiguous).
        for tag, expected in (("v1.5.0", "legacy release not identified for cc"),
                              ("v1.3.3", "legacy release ambiguous for cc")):
            with self.subTest(tag=tag), fixture((tag, "cc")) as root:
                for path in sorted((root / ".claude/skills").rglob("*")):
                    if path.is_file():
                        append(path, "\nedited\n")
                summary, _ = self.dry(root, "cc", "--backup-modified", expect=1)
                self.assertTrue(any(c.startswith(expected) for c in summary["conflicts"]), summary["conflicts"])
                self.refused(root, "cc", "--backup-modified")

    def test_codex_only_backup_modified_is_refused(self) -> None:
        with fixture(("v1.3.3", "cc")) as root:
            result = self.refused(root, "codex", "--backup-modified")
            self.assertEqual(result.returncode, 2)


def fake_catalog(text: str, version: str, drop: str) -> str:
    """A copy of a catalog renamed to `version` with one cc managed file entry removed."""
    lines = text.splitlines(keepends=True)
    out, skip, env = [], 0, None
    for line in lines:
        if re.fullmatch(r"  (cc|cursor):\n", line):
            env = line.strip()[:-1]
        if skip:
            skip -= 1
            continue
        if env == "cc" and line == f'      "{drop}":\n':
            skip = 3
            continue
        out.append(line)
    result = "".join(out)
    assert result != text, drop
    result = re.sub(r'(?m)^release_version: ".*"$', f'release_version: "{version}"', result)
    return re.sub(r"(?m)^release_versions: \[.*\]$", f'release_versions: ["{version}"]', result)


class AmbiguityAndIndex(Base):
    """Catalogs whose inventories do not form a chain stop with no change; so does a broken INDEX."""

    @contextlib.contextmanager
    def distribution(self, index: list[str]):
        with IsolatedDistribution(REPO) as dist:
            folder = dist / "migration/legacy-releases"
            base = (folder / "1.2.1.yaml").read_text()
            (folder / "0.0.1.yaml").write_text(fake_catalog(base, "0.0.1", RULE))
            (folder / "0.0.2.yaml").write_text(fake_catalog(base, "0.0.2", SKILL))
            (folder / "INDEX").write_text("".join(f"{name}\n" for name in index))
            yield dist

    def test_exact_matches_that_are_not_a_chain(self) -> None:
        with self.distribution(["0.0.1.yaml", "0.0.2.yaml", "1.2.1.yaml"]) as dist, fixture(("v1.3.3", "cc")) as root:
            summary, _ = self.dry(root, "cc", dist=dist, expect=1)
            self.assertTrue(any(c.startswith("legacy release ambiguous for cc") for c in summary["conflicts"]))
            self.refused(root, "cc", dist=dist)
            self.refused(root, "cc", "--backup-modified", dist=dist)
            summary, _ = self.dry(root, "cc", "--migrate-legacy", "1.3.3", dist=dist)  # the escape hatch
            self.assertEqual(summary["legacy_release"]["cc"]["catalog"], "1.2.1")
            self.installed(root, "cc", "--migrate-legacy", "1.3.3", dist=dist)

    def test_estimated_tie_that_is_not_a_chain(self) -> None:
        with self.distribution(["0.0.1.yaml", "0.0.2.yaml"]) as dist, fixture(("v1.3.3", "cc")) as root:
            append(root / ".claude/rules/ai-plc-session.md", "\nedited\n")
            summary, _ = self.dry(root, "cc", "--backup-modified", dist=dist, expect=1)
            self.assertTrue(any(c.startswith("legacy release ambiguous for cc") for c in summary["conflicts"]))
            self.refused(root, "cc", "--backup-modified", dist=dist)

    def test_broken_index_stops(self) -> None:
        cases = {"missing": None, "bad entry": "1.2.1.yaml\nnot-a-catalog\n",
                 "missing catalog": "1.2.1.yaml\n9.9.9.yaml\n", "truncated": "1.2.1.yaml"}
        for label, content in cases.items():
            with self.subTest(case=label), IsolatedDistribution(REPO) as dist, fixture(("v1.3.3", "cc")) as root:
                index = dist / "migration/legacy-releases/INDEX"
                if content is None:
                    index.unlink()
                else:
                    index.write_text(content)
                summary, _ = self.dry(root, "cc", dist=dist, expect=1)
                self.assertTrue(any("legacy release detection failed" in c for c in summary["conflicts"]))
                self.refused(root, "cc", dist=dist)


class UpgradeHistories(Base):
    """Targets upgraded step by step with the old installers, and different releases per environment."""

    def test_sequential_old_installers(self) -> None:
        for env in ("cc", "cursor"):
            steps = (("v1.1.0", env), ("v1.3.3", env), ("v1.6.0", env))
            with self.subTest(env=env), fixture(*steps) as root:
                leftovers = {p: tree_snapshot(root)[p] for p in tree_snapshot(root) if ".bak." in p}
                summary, _ = self.dry(root, env)
                release = summary["legacy_release"][env]
                self.assertEqual((release["catalog"], release["match"]), ("1.6.0", "exact"))
                self.installed(root, env)
                after = tree_snapshot(root)
                for path, item in leftovers.items():  # old installers' backups stay untouched
                    self.assertEqual(after.get(path), item, path)

    def test_different_release_per_environment(self) -> None:
        with fixture(("v1.3.3", "cc"), ("v1.5.0", "cursor")) as root:
            summary, stderr = self.dry(root, "both")
            self.assertEqual({e: (r["catalog"], r["match"]) for e, r in summary["legacy_release"].items()},
                             {"cc": ("1.2.1", "exact"), "cursor": ("1.5.0", "exact")})
            self.assertIn("cc v1.2.1–v1.4.1 (catalog 1.2.1); cursor v1.5.0 (catalog 1.5.0)", stderr)
            self.installed(root, "both")
            self.assertEqual(set(manifest(root)["environments"]), {"cc", "cursor"})


class ManifestReleases(Base):
    """v1.7.0 / v1.7.1 / v1.8.0-exp.1 have a manifest: ordinary updates, no legacy output, no hint."""

    def assert_ordinary(self, root: Path, mode: str, *extra: str) -> None:
        summary, stderr = self.dry(root, mode, *extra)
        self.assertEqual(set(summary), {"mode", "conflicts", "writes"})
        self.assertNotIn("[INFO] legacy", stderr)
        result = self.installed(root, mode, *extra)
        self.assertNotIn("legacy", result.stderr)
        self.assertNotIn("user_backups", manifest(root))

    def test_v170_and_v171(self) -> None:
        for tag, mode in (("v1.7.0", "cc"), ("v1.7.0", "all"), ("v1.7.1", "cc"), ("v1.7.1", "both"), ("v1.7.1", "all")):
            with self.subTest(tag=tag, mode=mode), fixture((tag, mode)) as root:
                self.assert_ordinary(root, mode)
                self.assertTrue(all(v["version"] == VERSION for v in manifest(root)["environments"].values()))

    def test_v171_edited_file(self) -> None:
        with fixture(("v1.7.1", "cc")) as root:
            append(root / RULE, "\nmy rule\n")
            summary, stderr = self.dry(root, "cc", expect=1)
            self.assertIn(f"user-modified managed file: {RULE}", summary["conflicts"])
            self.assertNotIn("[HINT]", stderr)  # v1.7.x output is unchanged (T001 §5-3)
            result = self.refused(root, "cc")
            self.assertNotIn("[HINT]", result.stderr)
            self.installed(root, "cc", "--backup-modified")
            self.assertEqual([r["path"] for r in manifest(root)["user_backups"]], [RULE])

    def test_v180_exp1_with_jev_component(self) -> None:
        with fixture(("v1.8.0-exp.1", "cc --with-jev")) as root:
            self.assertIn("experimental_jev", manifest(root)["components"])
            jev_before = {p: v for p, v in tree_snapshot(root).items() if "ai-plc-jev" in p or "-jev.md" in p}
            self.assert_ordinary(root, "cc")
            data = manifest(root)
            self.assertEqual(data["components"]["experimental_jev"]["package_version"], "1.8.0-exp.1")
            self.assertEqual({p: v for p, v in tree_snapshot(root).items() if p in jev_before}, jev_before)
            # --with-jev again updates the package from 1.8.0-exp.1 to the current release (neither a
            # mutable release nor a downgrade). Same version with other content is covered by test_with_jev.py.
            current = (REPO / "experimental/jev/VERSION").read_text().strip()
            self.assertNotEqual(current, "1.8.0-exp.1")
            self.assertNotEqual(jev_package_files(source("v1.8.0-exp.1")), jev_package_files(REPO))
            summary, _ = self.dry(root, "cc", "--with-jev")
            self.assertEqual(summary["conflicts"], [])
            self.installed(root, "cc", "--with-jev")
            component = manifest(root)["components"]["experimental_jev"]
            self.assertEqual(component["package_version"], current)
            self.assertEqual(component["version"], VERSION)
            installed = {p: (root / p).read_bytes() for p, v in tree_snapshot(root).items()
                         if v["type"] == "file" and ("ai-plc-jev" in p or "-jev.md" in p)}
            expected = {(".claude/ai-plc-jev/" if rel.startswith("scripts/") else ".claude/") + rel: data
                        for rel, data in jev_package_files(REPO).items()}
            self.assertEqual(installed, expected)  # the new release's content, no .bak left behind
            # and it uninstalls completely
            result = uninstall(root, "cc")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse([p for p in tree_snapshot(root) if "ai-plc-jev" in p or "-jev.md" in p])


    def test_known_releases_lists_the_v180_exp1_files(self) -> None:
        # uninstall sweeps leftover .bak files of earlier releases by these hashes, so they must equal
        # what the tag's installer put in place (a mismatch would only leave files behind silently).
        known: dict[str, set[str]] = {}
        section = None
        for line in (REPO / "experimental/jev/KNOWN_RELEASES.sha256").read_text().splitlines():
            if line.startswith("# 1.") and "(" in line:
                section = line[2:].split()[0]
            elif line.strip() and not line.startswith("#") and section == "1.8.0-exp.1":
                digest, path = line.split(None, 1)
                known.setdefault(path.strip(), set()).add(digest)
        expected = {(".claude/ai-plc-jev/" if rel.startswith("scripts/") else ".claude/") + rel:
                    {hashlib.sha256(data).hexdigest()} for rel, data in jev_package_files(source("v1.8.0-exp.1")).items()}
        self.assertEqual(len(expected), 18)
        self.assertEqual(known, expected)

class FaultInjection(Base):
    """P1-1: a failure while adopting a legacy release rolls back completely; the next run succeeds."""

    ANCHOR = "        changed += int(root.write_atomic(safe.MANIFEST, manifest, tx))\n"

    def test_fault_at_manifest_write(self) -> None:
        variants = {
            "before": "        raise OSError('injected fault before the manifest write')\n",
            "after": self.ANCHOR + "        raise OSError('injected fault after the manifest write')\n",
        }
        for label, replacement in variants.items():
            for tag, env in (("v1.3.3", "cc"), ("v1.1.0", "cc"), ("v1.6.0", "cursor")):
                with self.subTest(fault=label, tag=tag, env=env), IsolatedDistribution(REPO) as dist, \
                        fixture((tag, env)) as root:
                    patch_copy(dist / "lib/ai_plc_multi_env.py", self.ANCHOR, replacement)
                    before = tree_snapshot(root)
                    result = install(root, env, dist=dist)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("injected fault", result.stderr)
                    self.assertEqual(tree_snapshot(root), before, "rollback did not restore the target")
                    self.installed(root, env)

    def test_fault_with_backup_modified(self) -> None:
        with IsolatedDistribution(REPO) as dist, fixture(("v1.3.3", "cc")) as root:
            patch_copy(dist / "lib/ai_plc_multi_env.py", self.ANCHOR,
                       self.ANCHOR + "        raise OSError('injected fault after the manifest write')\n")
            append(root / RULE, "\nmy rule\n")
            before = tree_snapshot(root)
            result = install(root, "cc", "--backup-modified", dist=dist)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(tree_snapshot(root), before)
            self.installed(root, "cc", "--backup-modified")
            self.assertEqual([r["path"] for r in manifest(root)["user_backups"]], [RULE])


class LegacyUninstall(Base):
    """P2-6 / §9: uninstall adopts a legacy release only when every detected environment matches exactly."""

    def test_uninstall(self) -> None:
        with fixture(("v1.3.3", "cc"), ("v1.3.3", "cursor")) as root:
            before = tree_snapshot(root)
            dry = uninstall(root, "both", "--dry-run")
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertEqual(tree_snapshot(root), before)
            result = uninstall(root, "both", "--yes")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((root / ".claude/commands/01-collection.md").exists())
            self.assertFalse((root / CURSOR_RULE).exists())
        with fixture(("v1.3.3", "cc"), ("v1.3.3", "cursor")) as root:
            append(root / CURSOR_RULE, "\nedited\n")
            before = tree_snapshot(root)
            result = uninstall(root, "both", "--yes")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(tree_snapshot(root), before)


if __name__ == "__main__":
    unittest.main()
