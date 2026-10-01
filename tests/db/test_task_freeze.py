#!/usr/bin/env python3
"""Tests for the task sync freeze (core/db: init_db.py / plc_query.py / sync.py).

Standard library only (plus PyYAML, which AI-PLC already needs, for the backlog view). Every test
copies core/db into a throwaway project under the system temp directory; the caller's repository
and its DB are never touched. Needs Python 3.11+ for the installer test (sqlite serialize).

    python3 -m unittest tests/db/test_task_freeze.py -v
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FREEZE_KEY = "task_sync_frozen"
# The installer refuses symlinked targets (macOS /var -> /private/var), like tests/installers.
TMP = os.path.realpath(tempfile.gettempdir())


class TaskFreeze(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="ai-plc-freeze-", dir=TMP))
        self.db_dir = self.root / ".claude" / "db"
        self.db_dir.mkdir(parents=True)
        for name in ("init_db.py", "plc_query.py", "sync.py"):
            shutil.copy2(REPO / "core" / "db" / name, self.db_dir / name)
        self.db = self.db_dir / "ai_plc.db"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def run_py(self, script: str, *args: str) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items()
               if k not in ("AI_PLC_PROJECTS_DB_ID", "AI_PLC_TASKS_DB_ID", "NOTION_API_TOKEN")}
        return subprocess.run([sys.executable, str(self.db_dir / script), *args], cwd=self.root,
                              capture_output=True, text=True, env=env, timeout=60)

    def freeze_record(self) -> dict | None:
        with sqlite3.connect(self.db) as conn:
            row = conn.execute("SELECT value FROM _metadata WHERE key=?", (FREEZE_KEY,)).fetchone()
        return json.loads(row[0]) if row else None

    def task_count(self) -> int:
        with sqlite3.connect(self.db) as conn:
            return conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    def test_new_db_is_frozen(self) -> None:
        result = self.run_py("init_db.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = self.freeze_record()
        self.assertIsNotNone(record)
        self.assertEqual(record["approved_by"], "installer")
        self.assertIn("frozen_at", record)

    def test_existing_db_is_not_frozen_by_init(self) -> None:
        # An older DB (made before the freeze existed): full schema, no freeze record.
        with sqlite3.connect(self.db) as conn:
            self.run_py("init_db.py")
            conn.execute("DELETE FROM _metadata WHERE key=?", (FREEZE_KEY,))
        self.assertEqual(self.run_py("init_db.py").returncode, 0)
        self.assertIsNone(self.freeze_record())

    def test_add_task_is_skipped_while_frozen(self) -> None:
        self.run_py("init_db.py")
        result = self.run_py("plc_query.py", "add-task", "T001", "T-SCOPE-1", "name")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[SKIP]", result.stdout)
        self.assertEqual(self.task_count(), 0)

    def test_tasks_view_reads_backlog_while_frozen(self) -> None:
        self.run_py("init_db.py")
        layer = self.root / "work" / "layer1"
        layer.mkdir(parents=True)
        (layer / "intent.yaml").write_text('scope_id: "T-SCOPE-1"\n', encoding="utf-8")
        (layer / "backlog.yaml").write_text(
            "tasks:\n  - id: T007\n    name: from-backlog\n    status: pending\n", encoding="utf-8")
        result = self.run_py("plc_query.py", "tasks", "T-SCOPE-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("backlog.yaml", result.stdout)
        self.assertIn("T007", result.stdout)
        self.assertIn("from-backlog", result.stdout)

    def test_tasks_sync_status_freeze_unfreeze(self) -> None:
        self.run_py("init_db.py")
        status = self.run_py("sync.py", "tasks-sync", "--status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("FROZEN", status.stdout)

        self.assertEqual(self.run_py("sync.py", "tasks-sync", "--unfreeze").returncode, 2)
        unfreeze = self.run_py("sync.py", "tasks-sync", "--unfreeze", "--approved-by", "owner")
        self.assertEqual(unfreeze.returncode, 0, unfreeze.stdout + unfreeze.stderr)
        self.assertIsNone(self.freeze_record())
        self.assertIn("active", self.run_py("sync.py", "tasks-sync", "--status").stdout)
        self.assertEqual(self.run_py("sync.py", "tasks-sync", "--unfreeze", "--approved-by", "owner")
                         .returncode, 2)

        added = self.run_py("plc_query.py", "add-task", "T001", "T-SCOPE-1", "name")
        self.assertIn("[OK]", added.stdout)
        self.assertEqual(self.task_count(), 1)

        freeze = self.run_py("sync.py", "tasks-sync", "--freeze", "--approved-by", "owner",
                             "--reason", "backlog is the source")
        self.assertEqual(freeze.returncode, 0, freeze.stdout + freeze.stderr)
        record = self.freeze_record()
        self.assertEqual(record["approved_by"], "owner")
        self.assertEqual(record["reason"], "backlog is the source")
        again = self.run_py("sync.py", "tasks-sync", "--freeze", "--approved-by", "owner")
        self.assertIn("already frozen", again.stdout)
        self.assertEqual(self.task_count(), 1)  # the frozen copy is left as it is

    def test_tasks_sync_rejects_bad_options(self) -> None:
        self.run_py("init_db.py")
        self.assertEqual(self.run_py("sync.py", "tasks-sync").returncode, 2)
        self.assertEqual(self.run_py("sync.py", "tasks-sync", "--status", "--freeze").returncode, 2)
        self.assertEqual(self.run_py("sync.py", "tasks-sync", "--freeze").returncode, 2)
        self.assertEqual(self.run_py("sync.py", "tasks-sync", "--status", "--approved-by", "x")
                         .returncode, 2)


@unittest.skipIf(sys.version_info < (3, 11), "the installer needs Python 3.11+ (sqlite serialize)")
class InstalledDbIsFrozen(unittest.TestCase):
    def test_install_cc_creates_frozen_db_and_keeps_existing(self) -> None:
        target = Path(tempfile.mkdtemp(prefix="ai-plc-freeze-install-", dir=TMP))
        try:
            subprocess.run(["git", "init", "-q", str(target)], check=True)
            env = dict(os.environ, PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"])
            result = subprocess.run(["bash", str(REPO / "install-cc.sh"), "--target", str(target)],
                                    capture_output=True, text=True, env=env, timeout=300)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            db = target / ".claude" / "db" / "ai_plc.db"
            with sqlite3.connect(db) as conn:
                row = conn.execute("SELECT value FROM _metadata WHERE key=?", (FREEZE_KEY,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(json.loads(row[0])["approved_by"], "installer")

            # An existing DB is never rewritten by the installer (unfreeze, then reinstall).
            with sqlite3.connect(db) as conn:
                conn.execute("DELETE FROM _metadata WHERE key=?", (FREEZE_KEY,))
            again = subprocess.run(["bash", str(REPO / "install-cc.sh"), "--target", str(target)],
                                   capture_output=True, text=True, env=env, timeout=300)
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            with sqlite3.connect(db) as conn:
                self.assertIsNone(conn.execute("SELECT 1 FROM _metadata WHERE key=?",
                                               (FREEZE_KEY,)).fetchone())
        finally:
            shutil.rmtree(target, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
