#!/usr/bin/env python3
"""Tests for the opt-in `--with-jev` installer flag (experimental/jev).

Standard library only. Every install runs against a throwaway git repository under the system temp
directory; the caller's repository is never used as a target.

    python3 -m unittest tests/installers/test_with_jev.py -v

The "default behaviour is unchanged" tests compare the current installer against the installer at
BASELINE_REF (the last commit before --with-jev existed) on the same distribution content. Set
AI_PLC_JEV_BASELINE_REF to override; the tests fail (not skip) when the ref cannot be read, so the
comparison is never silently dropped.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
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
BASELINE_REF = os.environ.get("AI_PLC_JEV_BASELINE_REF", "e13c3fb")
INSTALLER_FILES = ("install.sh", "install-cc.sh", "install-cursor.sh", "install-codex.sh", "uninstall.sh",
                   "lib/ai_plc_safe_fs.py", "lib/ai_plc_multi_env.py")
MODES = ("cc", "both", "all", "cursor", "codex")
JEV_VERSION = (REPO / "experimental/jev/VERSION").read_text().strip()
JEV_FILES = sorted([
    ".claude/skills/ai-plc-jev/README.md",
    ".claude/skills/ai-plc-jev/01-collection-jev/SKILL.md",
    ".claude/skills/ai-plc-jev/02-inception-jev/SKILL.md",
    ".claude/skills/ai-plc-jev/03-construction-jev/SKILL.md",
    ".claude/skills/ai-plc-jev/04-operation-jev/SKILL.md",
    ".claude/commands/01-collection-jev.md",
    ".claude/commands/02-inception-jev.md",
    ".claude/commands/03-construction-jev.md",
    ".claude/commands/04-operation-jev.md",
    ".claude/ai-plc-jev/scripts/jev_client.py",
    ".claude/ai-plc-jev/scripts/jev_bt_monitor.py",
    ".claude/ai-plc-jev/scripts/jev_prompt_hook.py",
    ".claude/ai-plc-jev/scripts/jev_coverage_check.py",
    ".claude/ai-plc-jev/scripts/jev_regression_rank.py",
    ".claude/ai-plc-jev/scripts/aiplc_status_audit.py",
    ".claude/ai-plc-jev/scripts/README_jev.md",
    ".claude/ai-plc-jev/scripts/README_status_audit.md",
    ".claude/ai-plc-jev/scripts/jev_redact_extra.example.txt",
])
JEV_DIRS = (".claude/ai-plc-jev", ".claude/skills/ai-plc-jev")
STAMP = re.compile(r"\.bak\.[0-9]{8}T[0-9]{6}Z\.([0-9]+)")
ONLY_CC_MESSAGE = "Claude Code"
# The installer refuses symlinked path components (e.g. macOS /var -> /private/var), so use the real path.
TMP = os.path.realpath(tempfile.gettempdir())

# Prints a plan built directly by build_install_plan / build_uninstall_plan of the given distribution.
PLAN_SCRIPT = r"""
import hashlib, json, sys
from pathlib import Path
dist, target, action, mode = sys.argv[1:5]
sys.path.insert(0, str(Path(dist) / "lib"))
import ai_plc_safe_fs as safe, ai_plc_multi_env as multi
with safe.SafeRoot(Path(target)) as root:
    if action == "install":
        plan = multi.build_install_plan(Path(dist), root, mode)
        plan["payloads"] = {k: hashlib.sha256(v).hexdigest() for k, v in plan["payloads"].items()}
        plan["regions"] = {k: hashlib.sha256(v).hexdigest() for k, v in plan["regions"].items()}
        plan["seeds"] = {k: hashlib.sha256(v).hexdigest() for k, v in plan["seeds"].items()}
    else:
        plan = multi.build_uninstall_plan(Path(dist), root, mode)
        plan["regions"] = {k: hashlib.sha256(v).hexdigest() for k, v in plan["regions"].items()}
print(json.dumps(plan, sort_keys=True, ensure_ascii=False))
"""


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None,
        input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=cwd, env=env, input=input_text, text=True,
                          capture_output=True, timeout=120, check=False)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextlib.contextmanager
def target_repo():
    with tempfile.TemporaryDirectory(prefix="ai-plc-jev-target-", dir=TMP) as name:
        root = Path(name)
        assert run("git", "init", "-q", cwd=root).returncode == 0
        yield root


@contextlib.contextmanager
def distribution_copy():
    """A private copy of the distribution (without .git) that tests may modify."""
    with tempfile.TemporaryDirectory(prefix="ai-plc-jev-dist-", dir=TMP) as name:
        dist = Path(name) / "dist"
        shutil.copytree(REPO, dist, ignore=shutil.ignore_patterns(".git", "__pycache__", "results"))
        yield dist


@contextlib.contextmanager
def baseline_distribution():
    """The current distribution content with the installer files taken from BASELINE_REF."""
    with distribution_copy() as dist:
        for rel in INSTALLER_FILES:
            result = run("git", "-C", str(REPO), "show", f"{BASELINE_REF}:{rel}")
            if result.returncode != 0:
                raise AssertionError(f"baseline {BASELINE_REF}:{rel} unavailable: {result.stderr.strip()}")
            (dist / rel).write_text(result.stdout)
        yield dist


def install(dist: Path, root: Path, mode: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return run("bash", str(dist / "install.sh"), mode, "--target", str(root), *extra)


def uninstall(dist: Path, root: Path, mode: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return run("bash", str(dist / "uninstall.sh"), mode, "--target", str(root), *extra)


def direct_plan(dist: Path, root: Path, action: str, mode: str) -> dict:
    result = run(sys.executable, "-c", PLAN_SCRIPT, str(dist), str(root), action, mode)
    if result.returncode != 0:
        return {"error": result.stderr.strip().splitlines()[-1:]}
    return json.loads(result.stdout)


def files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and ".git" not in p.relative_to(root).parts)


def normalized_tree(root: Path, keep_seq: bool = True) -> dict[str, str]:
    """Relative path (backup stamps normalized) -> content hash; volatile files compared by presence."""
    tree = {}
    for rel in files(root):
        key = STAMP.sub(r".bak.STAMP.\1" if keep_seq else ".bak.STAMP", rel)
        if rel.endswith(".db") or ".db.bak." in rel:
            tree[key] = "present"
        elif rel == ".ai-plc-uninstall-tombstone":
            data = json.loads((root / rel).read_text())
            tree[key] = json.dumps(sorted(data), sort_keys=True)
        else:
            tree[key] = sha(root / rel)
    return tree


def manifest(root: Path) -> dict:
    return json.loads((root / ".ai-plc-install-manifest").read_text())


def jev_leftovers(root: Path) -> list[str]:
    left = [rel for rel in files(root) if rel.startswith(tuple(d + "/" for d in JEV_DIRS))
            or re.search(r"(^|/)0[1-4]-[a-z-]+-jev\.md", rel)]
    left += [d for d in JEV_DIRS if (root / d).exists()]
    return sorted(left)


def script_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONDONTWRITEBYTECODE", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY")}
    env["JEV_DISABLE"] = "1"
    return env


class DefaultBehaviourUnchanged(unittest.TestCase):
    """Without --with-jev every plan and every result equals the pre-change installer."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._stack = contextlib.ExitStack()
        cls.old = cls._stack.enter_context(baseline_distribution())

    @classmethod
    def tearDownClass(cls) -> None:
        cls._stack.close()

    def compare_dry_runs(self, root: Path, label: str) -> None:
        for mode in MODES:
            with self.subTest(state=label, mode=mode, action="install"):
                old = install(self.old, root, mode, "--dry-run")
                new = install(REPO, root, mode, "--dry-run")
                self.assertEqual((old.returncode, old.stdout, old.stderr), (new.returncode, new.stdout, new.stderr))
                old_plan = install(self.old, root, mode, "--plan-only")
                new_plan = install(REPO, root, mode, "--plan-only")
                self.assertEqual((old_plan.returncode, old_plan.stdout), (new_plan.returncode, new_plan.stdout))
            if mode != "codex":  # install.sh codex goes through the unchanged safe_fs planner
                with self.subTest(state=label, mode=mode, action="install-direct"):
                    self.assertEqual(direct_plan(self.old, root, "install", mode), direct_plan(REPO, root, "install", mode))
            with self.subTest(state=label, mode=mode, action="uninstall"):
                old = uninstall(self.old, root, mode, "--dry-run")
                new = uninstall(REPO, root, mode, "--dry-run")
                self.assertEqual((old.returncode, old.stdout, old.stderr), (new.returncode, new.stdout, new.stderr))
                self.assertEqual(direct_plan(self.old, root, "uninstall", mode), direct_plan(REPO, root, "uninstall", mode))

    def test_plans_on_fresh_target(self) -> None:
        with target_repo() as root:
            self.compare_dry_runs(root, "fresh")
            self.assertEqual(files(root), [])

    def test_plans_on_installed_targets(self) -> None:
        for installed in ("cc", "all", "cursor"):
            with target_repo() as root:
                self.assertEqual(install(self.old, root, installed).returncode, 0)
                before = normalized_tree(root)
                self.compare_dry_runs(root, f"installed-{installed}")
                self.assertEqual(normalized_tree(root), before)

    def test_plans_with_collision(self) -> None:
        with target_repo() as root:
            (root / ".claude/commands").mkdir(parents=True)
            (root / ".claude/commands/01-collection.md").write_text("user file\n")
            self.compare_dry_runs(root, "collision")

    def test_plans_with_jev_already_installed(self) -> None:
        # A later install without the flag leaves the experimental package alone (untouched component).
        with target_repo() as root:
            self.assertEqual(install(REPO, root, "cc", "--with-jev").returncode, 0)
            old = install(self.old, root, "cc", "--dry-run")
            new = install(REPO, root, "cc", "--dry-run")
            self.assertEqual((old.returncode, old.stdout), (new.returncode, new.stdout))
            self.assertEqual(direct_plan(self.old, root, "install", "cc"), direct_plan(REPO, root, "install", "cc"))

    def test_real_lifecycle_matches_baseline(self) -> None:
        for mode in MODES:
            with self.subTest(mode=mode), target_repo() as old_root, target_repo() as new_root:
                for step in ("install", "reinstall", "uninstall"):
                    action = uninstall if step == "uninstall" else install
                    old = action(self.old, old_root, mode)
                    new = action(REPO, new_root, mode)
                    self.assertEqual(old.returncode, new.returncode, (step, old.stderr, new.stderr))
                    self.assertEqual(normalized_tree(old_root), normalized_tree(new_root), step)
                    if (old_root / ".ai-plc-install-manifest").exists():
                        self.assertEqual(manifest(old_root), manifest(new_root), step)


class WithJevInstall(unittest.TestCase):

    def test_installs_18_files_and_records_package_version(self) -> None:
        for mode in ("cc", "both", "all"):
            with self.subTest(mode=mode), target_repo() as root:
                result = install(REPO, root, mode, "--with-jev")
                self.assertEqual(result.returncode, 0, result.stderr)
                data = manifest(root)
                jev = sorted(p for p, v in data["managed_files"].items() if v["component"] == "experimental_jev")
                self.assertEqual(jev, JEV_FILES)
                self.assertEqual(len(jev), 18)
                for rel in JEV_FILES:
                    self.assertTrue((root / rel).is_file(), rel)
                    self.assertEqual(data["managed_files"][rel]["owners"], ["cc"])
                    self.assertEqual(data["managed_files"][rel]["source_sha256"], sha(root / rel))
                component = data["components"]["experimental_jev"]
                self.assertEqual(component["package_version"], JEV_VERSION)
                self.assertEqual(component["version"], (REPO / ".ai-plc-version").read_text().strip())
                self.assertEqual(component["owners"], ["cc"])
                self.assertEqual((root / ".ai-plc-version").read_text(), (REPO / ".ai-plc-version").read_text())
                self.assertFalse((root / ".claude/ai-plc-jev/scripts/tests").exists())

    def test_with_jev_is_default_plus_18_files(self) -> None:
        with target_repo() as plain, target_repo() as jev:
            self.assertEqual(install(REPO, plain, "cc").returncode, 0)
            self.assertEqual(install(REPO, jev, "cc", "--with-jev").returncode, 0)
            plain_tree, jev_tree = normalized_tree(plain), normalized_tree(jev)
            self.assertEqual(sorted(set(jev_tree) - set(plain_tree)), JEV_FILES)
            for rel in plain_tree:
                if rel not in (".ai-plc-install-manifest",):
                    self.assertEqual(plain_tree[rel], jev_tree[rel], rel)
            # settings.json (hooks) is the untouched default seed
            self.assertEqual(sha(plain / ".claude/settings.json"), sha(jev / ".claude/settings.json"))

    def test_existing_settings_json_is_not_touched(self) -> None:
        with target_repo() as root:
            (root / ".claude").mkdir()
            (root / ".claude/settings.json").write_text('{"hooks": {"UserPromptSubmit": []}, "user": true}\n')
            before = sha(root / ".claude/settings.json")
            self.assertEqual(install(REPO, root, "cc", "--with-jev").returncode, 0)
            self.assertEqual(install(REPO, root, "cc", "--with-jev").returncode, 0)
            self.assertEqual(uninstall(REPO, root, "cc").returncode, 0)
            self.assertEqual(sha(root / ".claude/settings.json"), before)

    def test_dry_run_lists_jev_writes_without_changing_target(self) -> None:
        with target_repo() as root:
            result = install(REPO, root, "cc", "--with-jev", "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr)
            writes = json.loads(result.stdout)["writes"]
            plain = json.loads(install(REPO, root, "cc", "--dry-run").stdout)["writes"]
            self.assertEqual(sorted(set(writes) - set(plain)), JEV_FILES)
            self.assertEqual(files(root), [])

    def test_codex_and_cursor_reject_with_jev(self) -> None:
        with target_repo() as root:
            for mode in ("codex", "cursor"):
                with self.subTest(entry="install.sh", mode=mode):
                    result = install(REPO, root, mode, "--with-jev")
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(ONLY_CC_MESSAGE, result.stderr)
                    self.assertIn("cc / both / all", result.stderr)
            result = run("bash", str(REPO / "install-cursor.sh"), "--target", str(root), "--with-jev")
            self.assertEqual(result.returncode, 2)
            self.assertIn(ONLY_CC_MESSAGE, result.stderr)
            result = run("bash", str(REPO / "install-codex.sh"), "--target", str(root), "--with-jev")
            self.assertEqual(result.returncode, 2)
            self.assertIn("--with-jev", result.stderr)
            for mode in ("codex", "cursor"):
                result = run(sys.executable, str(REPO / "lib/ai_plc_multi_env.py"), "install", mode,
                             "--target", str(root), "--with-jev", "--dry-run")
                self.assertEqual(result.returncode, 2)
                self.assertIn(ONLY_CC_MESSAGE, result.stderr)
            result = run(sys.executable, str(REPO / "lib/ai_plc_multi_env.py"), "uninstall", "cc",
                         "--target", str(root), "--with-jev")
            self.assertEqual(result.returncode, 2)
            result = uninstall(REPO, root, "cc", "--with-jev")  # uninstall.sh has no such option
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(files(root), [])

    def test_help_mentions_flag(self) -> None:
        result = run("bash", str(REPO / "install.sh"), "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--with-jev", result.stdout)
        self.assertIn(JEV_VERSION, result.stdout)

    def test_reinstall_same_version_is_idempotent(self) -> None:
        with target_repo() as root:
            self.assertEqual(install(REPO, root, "cc", "--with-jev").returncode, 0)
            tree, data = normalized_tree(root), manifest(root)
            again = install(REPO, root, "cc", "--with-jev")
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertIn("0 changed file(s)", again.stdout)
            self.assertEqual(normalized_tree(root), tree)
            self.assertEqual(manifest(root), data)
            # without the flag the package stays and its record (incl. package_version) is unchanged
            plain = install(REPO, root, "cc")
            self.assertEqual(plain.returncode, 0, plain.stderr)
            self.assertEqual(manifest(root)["components"]["experimental_jev"], data["components"]["experimental_jev"])
            for rel in JEV_FILES:
                self.assertTrue((root / rel).is_file())

    def test_unmanaged_collision_is_refused(self) -> None:
        with target_repo() as root:
            (root / ".claude/commands").mkdir(parents=True)
            (root / ".claude/commands/01-collection-jev.md").write_text("mine\n")
            result = install(REPO, root, "cc", "--with-jev")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unmanaged file collision: .claude/commands/01-collection-jev.md", result.stderr)
            self.assertEqual(files(root), [".claude/commands/01-collection-jev.md"])


class WithJevUninstall(unittest.TestCase):

    def assert_uninstalled(self, root: Path, plain_tree_after: dict[str, str]) -> None:
        self.assertEqual(jev_leftovers(root), [])
        tree = normalized_tree(root, keep_seq=False)
        extra = {k for k in tree if k.startswith(".claude/db/jev_")}
        self.assertEqual({k: v for k, v in tree.items() if k not in extra and not k.startswith(".ai-plc-")},
                         {k: v for k, v in plain_tree_after.items() if not k.startswith(".ai-plc-")})

    def plain_lifecycle(self, mode: str) -> dict[str, str]:
        with target_repo() as root:
            assert install(REPO, root, mode).returncode == 0
            assert uninstall(REPO, root, mode).returncode == 0
            return normalized_tree(root, keep_seq=False)

    def test_uninstall_removes_everything_it_installed(self) -> None:
        for mode in ("cc", "all"):
            with self.subTest(mode=mode), target_repo() as root:
                self.assertEqual(install(REPO, root, mode, "--with-jev").returncode, 0)
                result = uninstall(REPO, root, mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("[WARN]", result.stdout)
                self.assert_uninstalled(root, self.plain_lifecycle(mode))

    def test_uninstall_after_running_scripts(self) -> None:
        with target_repo() as root:
            self.assertEqual(install(REPO, root, "cc", "--with-jev").returncode, 0)
            scripts = root / ".claude/ai-plc-jev/scripts"
            env = script_env()
            for args in (["jev_bt_monitor.py", "--override", "D-0000-1", "accept"],
                         ["jev_bt_monitor.py", "--noise-report"],
                         ["jev_coverage_check.py", "--help"],
                         ["jev_regression_rank.py", "--help"]):
                run(sys.executable, str(scripts / args[0]), *args[1:], cwd=root, env=env)
            run(sys.executable, str(scripts / "jev_prompt_hook.py"), cwd=root, env=env, input_text="{}")
            self.assertFalse((scripts / "__pycache__").exists())
            generated = sorted(p.name for p in (root / ".claude/db").glob("jev_*"))
            self.assertIn("jev_overrides.jsonl", generated)
            result = uninstall(REPO, root, "cc")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(jev_leftovers(root), [])
            # generated logs are user data outside the manifest and stay, like ai_plc.db
            self.assertEqual(sorted(p.name for p in (root / ".claude/db").glob("jev_*")), generated)

    def test_uninstall_codex_or_cursor_keeps_package(self) -> None:
        with target_repo() as root:
            self.assertEqual(install(REPO, root, "all", "--with-jev").returncode, 0)
            for mode in ("cursor", "codex"):
                self.assertEqual(uninstall(REPO, root, mode).returncode, 0)
                for rel in JEV_FILES:
                    self.assertTrue((root / rel).is_file(), rel)
                self.assertIn("experimental_jev", manifest(root)["components"])
            self.assertEqual(uninstall(REPO, root, "cc").returncode, 0)
            self.assertEqual(jev_leftovers(root), [])

    def test_user_modified_file_is_kept_as_residual(self) -> None:
        with target_repo() as root:
            self.assertEqual(install(REPO, root, "cc", "--with-jev").returncode, 0)
            edited = root / ".claude/ai-plc-jev/scripts/README_jev.md"
            edited.write_text("my notes\n")
            result = uninstall(REPO, root, "cc")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(edited.read_text(), "my notes\n")
            self.assertEqual(jev_leftovers(root), [".claude/ai-plc-jev", ".claude/ai-plc-jev/scripts/README_jev.md"])
            self.assertEqual([r["path"] for r in manifest(root)["residuals"]], [".claude/ai-plc-jev/scripts/README_jev.md"])

    def test_old_backups_removed_only_when_hash_matches(self) -> None:
        with target_repo() as root:
            self.assertEqual(install(REPO, root, "cc", "--with-jev").returncode, 0)
            client = root / ".claude/ai-plc-jev/scripts/jev_client.py"
            same = client.with_name("jev_client.py.bak.20260101T000000Z.1")
            other = client.with_name("jev_client.py.bak.20260101T000000Z.2")
            cmd = root / ".claude/commands/01-collection-jev.md.bak.20260101T000000Z.3"
            core_bak = root / ".claude/commands/01-collection.md.bak.20260101T000000Z.4"
            shutil.copyfile(client, same)
            other.write_text("unknown\n")
            shutil.copyfile(root / ".claude/commands/01-collection-jev.md", cmd)
            shutil.copyfile(root / ".claude/commands/01-collection.md", core_bak)
            result = uninstall(REPO, root, "cc")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(same.exists())
            self.assertFalse(cmd.exists())
            self.assertTrue(other.exists())
            self.assertTrue(core_bak.exists())  # core backups are never touched
            self.assertIn("[WARN]", result.stdout)
            self.assertEqual(jev_leftovers(root), [".claude/ai-plc-jev", ".claude/ai-plc-jev/scripts/jev_client.py.bak.20260101T000000Z.2"])

    def test_known_release_hash_allows_old_backup_removal(self) -> None:
        with distribution_copy() as dist, target_repo() as root:
            self.assertEqual(install(dist, root, "cc", "--with-jev").returncode, 0)
            old_bak = root / ".claude/ai-plc-jev/scripts/jev_client.py.bak.20260101T000000Z.1"
            old_bak.write_text("exp.0 content\n")
            digest = hashlib.sha256(b"exp.0 content\n").hexdigest()
            with open(dist / "experimental/jev/KNOWN_RELEASES.sha256", "a") as fh:
                fh.write(f"{digest}  .claude/ai-plc-jev/scripts/jev_client.py\n")
            self.assertEqual(uninstall(dist, root, "cc").returncode, 0)
            self.assertEqual(jev_leftovers(root), [])

    def test_symlink_inside_package_directory_is_not_followed(self) -> None:
        with target_repo() as root, tempfile.TemporaryDirectory(dir=TMP) as outside_name:
            self.assertEqual(install(REPO, root, "cc", "--with-jev").returncode, 0)
            outside = Path(outside_name)
            planted = outside / "jev_client.py.bak.20260101T000000Z.9"
            planted.write_bytes((root / ".claude/ai-plc-jev/scripts/jev_client.py").read_bytes())
            (root / ".claude/ai-plc-jev/scripts/linked").symlink_to(outside, target_is_directory=True)
            result = uninstall(REPO, root, "cc")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(planted.exists())  # never reached through the symlink
            self.assertTrue((root / ".claude/ai-plc-jev/scripts/linked").is_symlink())
            warn = [line for line in result.stdout.splitlines() if line.startswith("[WARN] experimental_jev")]
            self.assertEqual(len(warn), 1, result.stdout)  # one warning line
            self.assertIn("directory kept (not empty): .claude/ai-plc-jev", warn[0])
            self.assertFalse((root / ".claude/skills/ai-plc-jev").exists())


class WithJevUpgrade(unittest.TestCase):

    @staticmethod
    def make_release(dist: Path, version: str, change: bool = True, drop: str | None = None) -> None:
        (dist / "experimental/jev/VERSION").write_text(version + "\n")
        if change:
            with open(dist / "experimental/jev/scripts/README_jev.md", "a") as fh:
                fh.write(f"\n<!-- {version} -->\n")
        if drop:
            (dist / "experimental/jev" / drop).unlink()

    def test_upgrade_removes_package_backups_and_stale_files(self) -> None:
        with distribution_copy() as dist, target_repo() as root:
            self.assertEqual(install(dist, root, "cc", "--with-jev").returncode, 0)
            core_before = {k for k in normalized_tree(root) if ".bak." in k}
            self.make_release(dist, "1.8.0-exp.99", drop="scripts/jev_regression_rank.py")
            result = install(dist, root, "cc", "--with-jev")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("[WARN]", result.stdout)
            self.assertFalse((root / ".claude/ai-plc-jev/scripts/jev_regression_rank.py").exists())
            self.assertEqual([p for p in jev_leftovers(root) if ".bak." in p], [])
            data = manifest(root)
            self.assertEqual(data["components"]["experimental_jev"]["package_version"], "1.8.0-exp.99")
            self.assertNotIn(".claude/ai-plc-jev/scripts/jev_regression_rank.py", data["managed_files"])
            # core backups: only what the core already had (the manifest/marker writes are core behaviour)
            core_after = {k for k in normalized_tree(root) if ".bak." in k and not k.startswith(".ai-plc-")}
            self.assertEqual(core_after, {k for k in core_before if not k.startswith(".ai-plc-")})
            self.assertEqual(uninstall(dist, root, "cc").returncode, 0)
            self.assertEqual(jev_leftovers(root), [])

    def test_mutable_and_downgrade_are_refused(self) -> None:
        with distribution_copy() as dist, target_repo() as root:
            self.assertEqual(install(dist, root, "cc", "--with-jev").returncode, 0)
            before = normalized_tree(root)
            self.make_release(dist, JEV_VERSION, change=True)
            result = install(dist, root, "cc", "--with-jev")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"mutable release refused: experimental_jev {JEV_VERSION}", result.stderr)
            self.make_release(dist, "1.7.9-exp.5", change=False)
            result = install(dist, root, "cc", "--with-jev")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("component downgrade refused: experimental_jev", result.stderr)
            self.assertEqual(normalized_tree(root), before)

    def test_invalid_package_version_is_refused(self) -> None:
        with distribution_copy() as dist, target_repo() as root:
            (dist / "experimental/jev/VERSION").write_text("1.8.0\n")
            result = install(dist, root, "cc", "--with-jev")
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid experimental package version", result.stderr)
            self.assertEqual(files(root), [])


class CleanupHoldsLock(unittest.TestCase):

    def test_cleanup_runs_while_lock_is_held(self) -> None:
        sys.path.insert(0, str(REPO / "lib"))
        try:
            safe = importlib.import_module("ai_plc_safe_fs")
            multi = importlib.import_module("ai_plc_multi_env")
        finally:
            sys.path.pop(0)
        with target_repo() as root:
            self.assertEqual(install(REPO, root, "cc", "--with-jev").returncode, 0)
            (root / ".claude/ai-plc-jev/scripts/jev_client.py.bak.20260101T000000Z.1").write_bytes(
                (root / ".claude/ai-plc-jev/scripts/jev_client.py").read_bytes())
            seen: list[tuple[str, bool]] = []
            original_unlink, original_prune = safe.SafeRoot.unlink, safe.SafeRoot.prune_empty_dir

            def unlink(self_, rel):
                if ".bak." in rel and "ai-plc-install" not in rel:
                    seen.append((rel, self_.exists(safe.LOCK)))
                return original_unlink(self_, rel)

            def prune(self_, rel, identity=None):
                seen.append((rel, self_.exists(safe.LOCK)))
                return original_prune(self_, rel, identity)

            safe.SafeRoot.unlink, safe.SafeRoot.prune_empty_dir = unlink, prune
            try:
                with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), safe.SafeRoot(root) as handle:
                    multi.execute_uninstall(REPO, handle, "cc")
            finally:
                safe.SafeRoot.unlink, safe.SafeRoot.prune_empty_dir = original_unlink, original_prune
            self.assertTrue(any(".bak." in rel for rel, _ in seen))
            self.assertTrue(any(rel == ".claude/ai-plc-jev" for rel, _ in seen))
            self.assertTrue(all(locked for _, locked in seen), seen)
            self.assertFalse((root / safe.LOCK).exists())
            self.assertEqual(jev_leftovers(root), [])

    CRASH = r"""
import os, sys
from pathlib import Path
dist, target, action = sys.argv[1:4]
sys.path.insert(0, str(Path(dist) / "lib"))
import ai_plc_safe_fs as safe, ai_plc_multi_env as multi
multi.cleanup_experimental_jev = lambda *a, **k: os._exit(9)
with safe.SafeRoot(Path(target)) as root:
    if action == "uninstall":
        multi.execute_uninstall(Path(dist), root, "cc")
    else:
        multi.execute_install(Path(dist), root, "cc", None, True)
"""

    def test_crash_during_uninstall_cleanup_is_resumed(self) -> None:
        for follow_up in ("install", "uninstall"):
            with self.subTest(follow_up=follow_up), target_repo() as root:
                self.assertEqual(install(REPO, root, "cc", "--with-jev").returncode, 0)
                result = run(sys.executable, "-c", self.CRASH, str(REPO), str(root), "uninstall")
                self.assertEqual(result.returncode, 9)
                self.assertTrue((root / ".ai-plc-install.lock").exists())
                self.assertTrue(any(".bak." in p for p in jev_leftovers(root)))  # cleanup did not run
                # the next run recovers the committed transaction (no rollback) and resumes the cleanup
                action = install if follow_up == "install" else uninstall
                again = action(REPO, root, "cc")
                self.assertIn("experimental_jev cleanup resumed after recovery", again.stdout, again.stderr)
                self.assertFalse((root / ".ai-plc-install.lock").exists())
                self.assertEqual(jev_leftovers(root), [])
                if follow_up == "install":
                    self.assertEqual(again.returncode, 0, again.stderr)
                    self.assertNotIn("experimental_jev", manifest(root)["components"])

    def test_crash_during_upgrade_cleanup_is_resumed(self) -> None:
        with distribution_copy() as dist, target_repo() as root:
            self.assertEqual(install(dist, root, "cc", "--with-jev").returncode, 0)
            WithJevUpgrade.make_release(dist, "1.8.0-exp.99")
            result = run(sys.executable, "-c", self.CRASH, str(dist), str(root), "install")
            self.assertEqual(result.returncode, 9)
            self.assertTrue(any(".bak." in p for p in jev_leftovers(root)))
            again = install(dist, root, "cc", "--with-jev")
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertIn("experimental_jev cleanup resumed after recovery", again.stdout)
            self.assertEqual([p for p in jev_leftovers(root) if ".bak." in p], [])
            self.assertEqual(manifest(root)["components"]["experimental_jev"]["package_version"], "1.8.0-exp.99")

    def test_lock_release_failure_does_not_roll_back(self) -> None:
        sys.path.insert(0, str(REPO / "lib"))
        try:
            safe = importlib.import_module("ai_plc_safe_fs")
            multi = importlib.import_module("ai_plc_multi_env")
        finally:
            sys.path.pop(0)
        with target_repo() as root:
            self.assertEqual(install(REPO, root, "cc", "--with-jev").returncode, 0)
            original = safe.Transaction.commit
            def failing_commit(self_):
                raise OSError("simulated")
            safe.Transaction.commit = failing_commit
            try:
                with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), safe.SafeRoot(root) as handle:
                    with self.assertRaises(safe.InstallError) as ctx:
                        multi.execute_uninstall(REPO, handle, "cc")
            finally:
                safe.Transaction.commit = original
            self.assertTrue(getattr(ctx.exception, "committed", False))
            self.assertIn("rerun to recover", str(ctx.exception))
            # not rolled back: package files stay deleted and the committed journal is left for recovery
            self.assertFalse((root / ".claude/ai-plc-jev").exists())
            self.assertFalse((root / ".ai-plc-install-manifest").exists())
            self.assertTrue((root / ".ai-plc-install.lock").exists())

    def test_undecodable_known_releases_does_not_block_cleanup(self) -> None:
        with distribution_copy() as dist, target_repo() as root:
            self.assertEqual(install(dist, root, "cc", "--with-jev").returncode, 0)
            (dist / "experimental/jev/KNOWN_RELEASES.sha256").write_bytes(b"\xff\xfe broken\n")
            result = uninstall(dist, root, "cc")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(jev_leftovers(root), [])


if __name__ == "__main__":
    unittest.main()
