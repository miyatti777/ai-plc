"""Offline tests for _find_repo (where the scripts look for <repo>) in jev_client and aiplc_status_audit.

Both modules carry the same function; each case runs against both so they cannot drift apart silently.
Only temporary directories are used; nothing is read from or written to the real repository.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import yaml  # noqa: F401  (the scripts need pyyaml; without it these tests are skipped, not errors)
except ImportError:
    raise unittest.SkipTest("pyyaml が無い（pip install pyyaml）")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import aiplc_status_audit  # noqa: E402
import jev_client  # noqa: E402

FINDERS = (("jev_client", jev_client._find_repo), ("aiplc_status_audit", aiplc_status_audit._find_repo))


class FindRepoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self._env = os.environ.pop("AIPLC_REPO", None)

    def tearDown(self):
        os.environ.pop("AIPLC_REPO", None)
        if self._env is not None:
            os.environ["AIPLC_REPO"] = self._env
        self.tmp.cleanup()

    def script(self, *parts):
        p = self.root.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# script\n", encoding="utf-8")
        return p

    def marker(self, repo, name=".ai-plc-version"):
        (repo / name).write_text("x\n", encoding="utf-8")

    def check(self, start, expected):
        for name, find in FINDERS:
            with self.subTest(module=name):
                self.assertEqual(find(start), expected)

    def test_installed_layout_with_version_marker(self):
        repo = self.root / "repo"
        start = self.script("repo", ".claude", "ai-plc-jev", "scripts", "jev_client.py")
        self.marker(repo)
        self.check(start, repo)

    def test_installed_layout_with_manifest_marker(self):
        repo = self.root / "repo"
        start = self.script("repo", ".claude", "ai-plc-jev", "scripts", "jev_client.py")
        self.marker(repo, ".ai-plc-install-manifest")
        self.check(start, repo)

    def test_scripts_directly_under_the_repo(self):
        # <repo>/scripts/x.py: no .claude on the way up, so the grandparent of the file (the historical layout)
        repo = self.root / "repo"
        start = self.script("repo", "scripts", "jev_client.py")
        self.check(start, repo)

    def test_no_marker_falls_back_to_the_grandparent(self):
        # a .claude without the install marker is not taken as the repo; the fallback is the file's grandparent.
        # This pins the existing behaviour when the marker is missing (the installer always writes one);
        # it is not a layout to aim for.
        start = self.script("repo", ".claude", "ai-plc-jev", "scripts", "jev_client.py")
        self.check(start, self.root / "repo" / ".claude" / "ai-plc-jev")

    def test_inner_claude_without_marker_is_skipped(self):
        outer = self.root / "outer"
        start = self.script("outer", ".claude", "work", ".claude", "ai-plc-jev", "scripts", "jev_client.py")
        self.marker(outer)
        self.check(start, outer)

    def test_env_override_wins(self):
        repo = self.root / "repo"
        start = self.script("repo", ".claude", "ai-plc-jev", "scripts", "jev_client.py")
        self.marker(repo)
        other = self.root / "other"
        other.mkdir()
        os.environ["AIPLC_REPO"] = str(self.root / "other" / ".." / "other")
        self.check(start, other)  # resolved, and preferred over the marker

    def test_empty_env_is_ignored(self):
        repo = self.root / "repo"
        start = self.script("repo", ".claude", "ai-plc-jev", "scripts", "jev_client.py")
        self.marker(repo)
        os.environ["AIPLC_REPO"] = ""
        self.check(start, repo)


if __name__ == "__main__":
    unittest.main()
