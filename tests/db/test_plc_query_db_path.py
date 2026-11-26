#!/usr/bin/env python3
"""plc_query.py の DB の場所（sync.py・init_db.py と同じく aiplc_paths.py で決める）を確かめる。

どの試験も core/db を一時フォルダの導入先の形（<root>/.claude/db）へ写して動かす。
利用者のリポジトリの DB と本番の DB は開かない。

    python3 -m unittest tests/db/test_plc_query_db_path.py -v
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
# macOS の /var -> /private/var をそろえる（パスを比べるため）
TMP = os.path.realpath(tempfile.gettempdir())
SCRIPTS = ("init_db.py", "plc_query.py", "sync.py", "aiplc_paths.py")


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "core.hooksPath=/dev/null", "-c", "user.name=t",
                    "-c", "user.email=t@example.invalid", "-c", "init.defaultBranch=main", *args],
                   check=True, capture_output=True, text=True)


class PlcQueryDbPath(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="ai-plc-query-path-", dir=TMP))
        self.project = self.root / "project"
        self.db_dir = self.project / ".claude" / "db"
        self.db_dir.mkdir(parents=True)
        for name in SCRIPTS:
            shutil.copy2(REPO / "core" / "db" / name, self.db_dir / name)
        self.sibling = self.db_dir / "ai_plc.db"
        self.other = self.root / "elsewhere" / "other.db"
        self.other.parent.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def run_py(self, db_dir: Path, script: str, *args: str, env_extra=None):
        env = {k: v for k, v in os.environ.items()
               if k not in ("AIPLC_DB", "AI_PLC_PROJECTS_DB_ID", "AI_PLC_TASKS_DB_ID",
                            "NOTION_API_TOKEN")}
        env.update(env_extra or {})
        return subprocess.run([sys.executable, "-B", str(db_dir / script), *args],
                              cwd=db_dir.parents[1], capture_output=True, text=True, env=env,
                              timeout=60)

    def init(self, db_dir: Path, db: Path | None = None) -> None:
        args = ["--allow-production"] if db is None else ["--db", str(db)]
        result = self.run_py(db_dir, "init_db.py", *args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @staticmethod
    def scopes(db: Path) -> list[str]:
        with closing(sqlite3.connect(db)) as conn:
            return [row[0] for row in conn.execute("SELECT scope_id FROM projects ORDER BY scope_id")]

    def test_default_uses_the_sibling_db(self) -> None:
        self.init(self.db_dir)
        self.init(self.db_dir, self.other)
        result = self.run_py(self.db_dir, "plc_query.py", "add-project", "L-0001", "sample", "goal")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(["L-0001"], self.scopes(self.sibling))
        self.assertEqual([], self.scopes(self.other))
        listed = self.run_py(self.db_dir, "plc_query.py", "projects")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("L-0001", listed.stdout)

    def test_aiplc_db_points_plc_query_at_that_db(self) -> None:
        self.init(self.db_dir)
        self.init(self.db_dir, self.other)
        env = {"AIPLC_DB": str(self.other)}
        result = self.run_py(self.db_dir, "plc_query.py", "add-project", "L-0002", "sample", "goal",
                             env_extra=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(["L-0002"], self.scopes(self.other))
        self.assertEqual([], self.scopes(self.sibling))
        listed = self.run_py(self.db_dir, "plc_query.py", "projects", env_extra=env)
        self.assertIn("L-0002", listed.stdout)
        self.assertNotIn("L-0002", self.run_py(self.db_dir, "plc_query.py", "projects").stdout)
        read = self.run_py(self.db_dir, "plc_query.py", "sql", "SELECT scope_id FROM projects",
                           env_extra=env)
        self.assertIn("L-0002", read.stdout)

    def test_config_db_path_is_used(self) -> None:
        self.init(self.db_dir)
        self.init(self.db_dir, self.other)
        (self.project / ".ai-plc").mkdir()
        (self.project / ".ai-plc" / "config.yaml").write_text(
            "id_allocation:\n  db_path: %s\n" % self.other, encoding="utf-8")
        result = self.run_py(self.db_dir, "plc_query.py", "add-project", "L-0003", "sample", "goal")
        if "PyYAML" in result.stderr or "読めない" in result.stderr:
            self.skipTest("PyYAML is not available for this interpreter")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(["L-0003"], self.scopes(self.other))
        self.assertEqual([], self.scopes(self.sibling))

    def test_without_aiplc_paths_the_sibling_db_is_used(self) -> None:
        (self.db_dir / "aiplc_paths.py").unlink()
        self.init(self.db_dir)
        self.init(self.db_dir, self.other)
        result = self.run_py(self.db_dir, "plc_query.py", "add-project", "L-0004", "sample", "goal",
                             env_extra={"AIPLC_DB": str(self.other)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(["L-0004"], self.scopes(self.sibling))
        self.assertEqual([], self.scopes(self.other))

    def test_read_sql_with_a_write_is_treated_as_a_write(self) -> None:
        self.init(self.db_dir)
        self.assertEqual(0, self.run_py(self.db_dir, "plc_query.py", "add-project", "L-0005",
                                        "sample", "goal").returncode)
        result = self.run_py(self.db_dir, "plc_query.py", "sql",
                             "WITH x AS (SELECT 1) UPDATE projects SET name='renamed' "
                             "WHERE scope_id='L-0005'")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with closing(sqlite3.connect(self.sibling)) as conn:
            self.assertEqual("renamed", conn.execute(
                "SELECT name FROM projects WHERE scope_id='L-0005'").fetchone()[0])

    def test_writes_to_a_worktree_copy_stop_with_db_not_main(self) -> None:
        git(self.project, "init")
        git(self.project, "add", "--", ".claude/db")
        git(self.project, "commit", "-m", "scripts")
        worktree = self.root / "wt"
        git(self.project, "worktree", "add", "--detach", str(worktree))
        wt_db_dir = worktree / ".claude" / "db"
        self.init(self.db_dir, self.other)  # 空の DB を作って worktree の中へ写す
        shutil.copy2(self.other, wt_db_dir / "ai_plc.db")
        # 既定（設定なし＝solo）では、今までどおり worktree の隣の DB に書ける
        plain = self.run_py(wt_db_dir, "plc_query.py", "add-project", "L-0002", "sample", "goal")
        self.assertEqual(plain.returncode, 0, plain.stdout + plain.stderr)
        self.assertEqual(["L-0002"], self.scopes(wt_db_dir / "ai_plc.db"))
        shutil.copy2(self.other, wt_db_dir / "ai_plc.db")  # 空に戻す
        # 設定で本体の DB を使うと決めた（local-db）のに、本体に DB が無く worktree の写しに決まったときは止める
        (worktree / ".ai-plc").mkdir()
        (worktree / ".ai-plc" / "config.yaml").write_text("id_allocation:\n  mode: local-db\n", encoding="utf-8")
        result = self.run_py(wt_db_dir, "plc_query.py", "add-project", "L-0006", "sample", "goal")
        if "PyYAML" in result.stderr or "読めない" in result.stderr:
            self.skipTest("PyYAML is not available for this interpreter")
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("DB_NOT_MAIN", result.stdout)
        self.assertEqual([], self.scopes(wt_db_dir / "ai_plc.db"))
        # 読むだけのコマンドは警告だけで続ける
        listed = self.run_py(wt_db_dir, "plc_query.py", "projects")
        self.assertEqual(listed.returncode, 0, listed.stdout + listed.stderr)
        self.assertIn("DB_NOT_MAIN", listed.stderr)
        # AIPLC_DB で明示したときは通す
        explicit = self.run_py(wt_db_dir, "plc_query.py", "add-project", "L-0006", "sample", "goal",
                               env_extra={"AIPLC_DB": str(wt_db_dir / "ai_plc.db")})
        self.assertEqual(explicit.returncode, 0, explicit.stdout + explicit.stderr)
        self.assertEqual(["L-0006"], self.scopes(wt_db_dir / "ai_plc.db"))


if __name__ == "__main__":
    unittest.main()
