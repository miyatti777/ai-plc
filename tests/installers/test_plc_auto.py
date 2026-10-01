#!/usr/bin/env python3
"""Install plc-auto into disposable projects; never set a user's Goal.

Run: python3 -m unittest tests/installers/test_plc_auto.py -v
Needs the v1.12.0 tag for the real upgrade fixture (no silent skip).
"""
from __future__ import annotations

import contextlib
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
TMP = str(Path(tempfile.gettempdir()).resolve())
MODES = ("cc", "codex", "cursor")


def run(*args: str, cwd: Path | None = None, data: bytes | None = None):
    return subprocess.run(args, cwd=cwd, input=data, capture_output=True, timeout=90)


@contextlib.contextmanager
def project():
    with tempfile.TemporaryDirectory(prefix="plc-auto-target-", dir=TMP) as name:
        root = Path(name)
        result = run("git", "init", "-q", cwd=root)
        assert result.returncode == 0, result.stderr.decode()
        yield root


class PlcAutoDistribution(unittest.TestCase):
    def install(self, dist: Path, root: Path, mode: str):
        result = run("bash", str(dist / "install.sh"), mode, "--target", str(root))
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def assert_payload(self, root: Path, mode: str):
        base = root / (".cursor" if mode == "cursor" else ".claude")
        for rel in ("SKILL.md", "references/goal-preset.md"):
            self.assertEqual((base / "skills/plc-auto" / rel).read_bytes(),
                             (REPO / "core/skills/plc-auto" / rel).read_bytes())
        rules = base / "rules"
        for name in ("ai-plc-system", "ai-plc-session", "ai-plc-adaptive"):
            self.assertTrue((rules / (name + (".mdc" if mode == "cursor" else ".md"))).is_file())
        if mode == "codex":
            adapter = root / ".agents/skills/ai-plc/plc-auto"
            for rel in ("SKILL.md", "agents/openai.yaml"):
                self.assertEqual((adapter / rel).read_bytes(),
                                 (REPO / "codex/skills/ai-plc/plc-auto" / rel).read_bytes())
            self.assertIn('display_name: "plc-auto"', (adapter / "agents/openai.yaml").read_text())
            self.assertTrue((base / "rules/ai-plc-session.md").read_text().find("専用入口 `plc-auto`") >= 0)

    def test_fresh_install(self):
        for mode in MODES:
            with self.subTest(mode=mode), project() as root:
                self.install(REPO, root, mode)
                self.assert_payload(root, mode)
                self.assertEqual((root / ".ai-plc-version").read_bytes(), (REPO / ".ai-plc-version").read_bytes())

    def test_upgrade_from_1_12_0(self):
        archive = run("git", "archive", "v1.12.0", cwd=REPO)
        self.assertEqual(archive.returncode, 0, "Need full clone with v1.12.0 tag: " + archive.stderr.decode())
        with tempfile.TemporaryDirectory(prefix="plc-auto-baseline-", dir=TMP) as name:
            old = Path(name)
            extracted = run("tar", "-x", "-C", str(old), data=archive.stdout)
            self.assertEqual(extracted.returncode, 0, extracted.stderr.decode())
            self.assertFalse((old / "core/skills/plc-auto").exists())
            for mode in MODES:
                with self.subTest(mode=mode), project() as root:
                    self.install(old, root, mode)
                    (root / "user-note.md").write_text("user content\n")
                    self.install(REPO, root, mode)
                    self.assert_payload(root, mode)
                    self.assertEqual((root / "user-note.md").read_text(), "user content\n")

    def test_reinstall_is_idempotent(self):
        for mode in MODES:
            with self.subTest(mode=mode), project() as root:
                self.install(REPO, root, mode)
                def snapshot():
                    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
                            if p.is_file() and ".git" not in p.relative_to(root).parts}
                before = snapshot()
                self.install(REPO, root, mode)
                self.assert_payload(root, mode)
                self.assertEqual(snapshot(), before)


if __name__ == "__main__":
    unittest.main()
