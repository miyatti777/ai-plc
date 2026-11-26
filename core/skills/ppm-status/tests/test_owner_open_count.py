"""owner_open_count.py のテスト。データは全部合成（架空の題名・パス・ID・担当の書き方）。

- 配布の形（core/skills/ppm-status/ の隣に core/skills/ppm/）で関数を呼ぶテスト
- 一時フォルダに導入先と同じ形（<repo>/.claude/skills/ppm/・ppm-status/）の写しを置いて実行するテスト
- 読むだけなので、実行の前後でリポジトリのファイルが1つも変わらないことも確かめる
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
STATUS = Path(__file__).resolve().parents[1]        # core/skills/ppm-status
SKILLS = STATUS.parent
sys.path.insert(0, str(STATUS))
import owner_open_count as oc  # noqa: E402

PY = sys.executable
IGNORE = shutil.ignore_patterns("tests", "__pycache__", "*.pyc")


def write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return p


def write_yaml(root: Path, rel: str, data) -> Path:
    import yaml

    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def tree_digest(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def make_repo(root: Path) -> None:
    """同梱の雛形から作った TODO に、合成の案件を足す。"""
    text = (SKILLS / "ppm" / "templates" / "todo_template.md").read_text(encoding="utf-8")
    text = text.replace("## 進行中の私生活\n\n", textwrap.dedent("""
        ## 進行中の私生活

        - [ ] 名札を印刷する
          <!-- layer: Flow/202601/2026-01-03/name-tags scope: L-9003 -->
        - [x] 済んだ案件
          <!-- layer: Flow/202601/2026-01-04/finished scope: L-9004 -->

        """).lstrip("\n"), 1)
    write(root, "todo/todo.md", text)
    write_yaml(root, "Flow/202601/2026-01-05/sample-estimator/backlog.yaml", {"tasks": [
        {"id": "T001", "name": "a", "status": "pending", "owner": "user"},
        {"id": "T002", "name": "b", "status": "blocked", "owner": "AI・本人（確認）"},
        {"id": "T003", "name": "c", "status": "deferred", "owner": "user"},
        {"id": "T004", "name": "d", "status": "completed", "owner": "user"},
        {"id": "T005", "name": "e", "status": "pending", "owner": "AI"},
        {"id": "T006", "name": "f", "status": "pending", "owner": "User", "recurrence": "weekly"},
        {"id": "T007", "name": "g", "status": "in_progress", "owner": "Human"},
    ]})
    write_yaml(root, "Flow/202601/2026-01-03/name-tags/backlog.yaml", {"tasks": [
        {"id": "T001", "name": "版の形を選ぶ", "status": "pending", "owner": "当番の担当"},
    ]})
    write_yaml(root, "Flow/202601/2026-01-04/finished/backlog.yaml", {"tasks": [
        {"id": "T001", "name": "x", "status": "pending", "owner": "user"},
    ]})


class RuleTest(unittest.TestCase):
    def test_owner_rule(self):
        pat = oc.owner_pattern(["本人", "user", "human"])
        self.assertTrue(oc.is_owner_open_task({"status": "pending", "owner": "USER"}, pat))
        self.assertTrue(oc.is_owner_open_task({"status": "blocked", "owner": "AI／本人"}, pat))
        self.assertFalse(oc.is_owner_open_task({"status": "deferred", "owner": "user"}, pat))
        self.assertFalse(oc.is_owner_open_task({"status": "Completed", "owner": "user"}, pat))
        self.assertFalse(oc.is_owner_open_task({"status": "pending", "owner": "user", "recurrence": "daily"}, pat))
        self.assertFalse(oc.is_owner_open_task({"status": "pending"}, pat))
        self.assertFalse(oc.is_owner_open_task("T001", pat))
        self.assertIsNone(oc.owner_pattern([]))
        self.assertFalse(oc.is_owner_open_task({"status": "pending", "owner": "user"}, None))
        self.assertEqual(oc.count_owner_open_tasks(None, pat), 0)


class CountTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_counts(self, show_private=False):
        pf = oc.load_ppm_files(self.root)
        root, cfg = pf.context(self.root)
        return oc.counts(root, cfg, pf.read_todo(root, cfg), pf, show_private=show_private)

    def test_default_words(self):
        make_repo(self.root)
        rows = self.run_counts()
        # T001・T002・T007 の3件。私生活の案件は担当の語に当たらない。完了の印の案件は数えない
        self.assertEqual(rows, [{"scope": "L-9001", "layer": "Flow/202601/2026-01-05/sample-estimator",
                                 "owner_open_tasks": 3}])

    def test_owner_words_from_config(self):
        make_repo(self.root)
        write(self.root, ".ai-plc/config.yaml", "ppm:\n  owner_words: [当番]\n")
        # 私生活の節の案件は、既定では scope・layer を伏せる
        rows = self.run_counts()
        self.assertEqual(rows, [{"scope": None, "layer": None, "owner_open_tasks": 1, "private": True}])
        rows = self.run_counts(show_private=True)
        self.assertEqual([(r["scope"], r["layer"], r["private"]) for r in rows],
                         [("L-9003", "Flow/202601/2026-01-03/name-tags", True)])

    def test_empty_owner_words_counts_nothing(self):
        make_repo(self.root)
        write(self.root, ".ai-plc/config.yaml", "ppm:\n  owner_words: []\n")
        self.assertEqual(self.run_counts(), [])


class InstalledLayoutTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        for name in ("ppm", "ppm-status"):
            shutil.copytree(SKILLS / name, self.root / ".claude" / "skills" / name, ignore=IGNORE)

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, *args):
        before = tree_digest(self.root)
        out = subprocess.run([PY, "-B", str(self.root / ".claude/skills/ppm-status/owner_open_count.py"), *args],
                             capture_output=True, text=True, cwd=self.root)
        self.assertEqual(tree_digest(self.root), before, "道具がファイルを変えた")
        return out

    def test_runs_from_installed_copy(self):
        make_repo(self.root)
        out = self.run_tool("--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual([(r["scope"], r["owner_open_tasks"]) for r in json.loads(out.stdout)], [("L-9001", 3)])
        text = self.run_tool()
        self.assertIn("自分が関わる未完了 Task: 3件（1案件", text.stdout)

    def test_private_rows_hidden_in_output(self):
        make_repo(self.root)
        write(self.root, ".ai-plc/config.yaml", "ppm:\n  owner_words: [当番, user]\n")
        text = self.run_tool()
        self.assertEqual(text.returncode, 0, text.stderr)
        self.assertIn("私生活の案件", text.stdout)
        self.assertNotIn("L-9003", text.stdout)
        self.assertNotIn("name-tags", text.stdout)
        js = self.run_tool("--json")
        self.assertNotIn("name-tags", js.stdout)
        shown = self.run_tool("--show-private")
        self.assertIn("L-9003", shown.stdout)

    def test_missing_todo_skips(self):
        out = self.run_tool()
        self.assertEqual(out.returncode, 0)
        self.assertIn("スキップ", out.stderr)
        self.assertEqual(out.stdout, "")


class YamlMissingTest(unittest.TestCase):
    def test_stops_with_message_and_exit_code(self):
        err = io.StringIO()
        with mock.patch.dict(sys.modules, {"yaml": None}), redirect_stderr(err):
            self.assertEqual(oc.main([]), 2)
        self.assertIn("PyYAML", err.getvalue())


if __name__ == "__main__":
    unittest.main()
