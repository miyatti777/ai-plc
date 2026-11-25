"""aiplc_paths（DB の場所）を一時 git リポで確かめる。

本物の .claude/db/ai_plc.db と本体の DB は開かない。リポ・worktree・サブモジュール・DB はすべて一時フォルダ。
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

DB_DIR = Path(__file__).resolve().parents[2] / "core" / "db"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


paths = _load("aiplc_paths_under_test", DB_DIR / "aiplc_paths.py")
# 公開版では DB のフォルダはこのファイルの置き場所で決まる（リポジトリの中では core/db）。
# 下の試験は導入先の形（.claude/db）の一時リポで確かめるので、そこに合わせる
paths.REL_DB = Path(".claude") / "db" / "ai_plc.db"
LOCAL_DB = "id_allocation:\n  mode: local-db\n"


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "core.hooksPath=/dev/null", "-c", "user.name=t",
                    "-c", "user.email=t@example.invalid", "-c", "protocol.file.allow=always",
                    "-c", "init.defaultBranch=main", *args],
                   check=True, capture_output=True, text=True)


def make_db(path, journal="delete"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(f"PRAGMA journal_mode={journal}")
        conn.execute("CREATE TABLE IF NOT EXISTS marker (name TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS projects (id INTEGER, status TEXT)")
        conn.execute("INSERT INTO marker VALUES (?)", (str(path),))
        conn.commit()
        if journal == "wal":  # 中身を本体ファイルに移す（-wal を消しても失われないように）
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def drop_sidecars(db):
    """-wal/-shm を消す。SQLite 3.43（macOS の /usr/bin/python3）は閉じたあとも -shm を残すので、
    error 14 が起きる形（WAL の DB で -wal/-shm が無い）をどの版でも同じに作る"""
    for suffix in ("-wal", "-shm"):
        with contextlib.suppress(FileNotFoundError):
            os.remove(f"{db}{suffix}")


class _Repo(unittest.TestCase):
    """main（DB と設定を commit 済み）＋その linked worktree"""
    config = LOCAL_DB

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aiplc-paths-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.main = self.tmp / "main"
        self.main.mkdir()
        git(self.main, "init", "-q")
        make_db(self.main / ".claude/db/ai_plc.db")
        if self.config is not None:
            (self.main / ".ai-plc").mkdir()
            (self.main / ".ai-plc/config.yaml").write_text(self.config, encoding="utf-8")
        git(self.main, "add", "-A")
        git(self.main, "commit", "-qm", "init")
        self.wt = self.tmp / "wt"
        git(self.main, "worktree", "add", "-q", "--no-track", "-b", "wt/test", str(self.wt))
        self.main_db = self.main / ".claude/db/ai_plc.db"
        self.wt_db = self.wt / ".claude/db/ai_plc.db"


class ResolveTest(_Repo):
    def test_env_wins_over_config_and_git(self):
        r = paths.resolve_db(self.wt, env={"AIPLC_DB": str(self.tmp / "x.db")})
        self.assertEqual((self.tmp / "x.db", "env"), (r.path, r.source))

    def test_worktree_resolves_to_main_db(self):
        self.assertTrue(self.wt_db.is_file())  # git 管理の古い写しは worktree にもある
        r = paths.resolve_db(self.wt, env={})
        self.assertEqual((self.main_db, "git-common-dir", "local-db"), (r.path, r.source, r.mode))
        self.assertEqual(self.main_db, paths.resolve_db(self.main, env={}).path)
        self.assertEqual(self.main, paths.main_root(self.wt))

    def test_config_db_path_relative_to_main_and_absolute(self):
        cfg = self.wt / ".ai-plc/config.yaml"
        cfg.write_text(LOCAL_DB + "  db_path: data/reg.db\n", encoding="utf-8")
        r = paths.resolve_db(self.wt, env={})
        self.assertEqual((self.main / "data/reg.db", "config"), (r.path, r.source))
        cfg.write_text(f"id_allocation:\n  db_path: {self.tmp / 'abs.db'}\n", encoding="utf-8")
        self.assertEqual(self.tmp / "abs.db", paths.resolve_db(self.wt, env={}).path)

    def test_submodule_and_its_worktree_resolve_to_main(self):
        flow_src = self.tmp / "flow-src"
        flow_src.mkdir()
        git(flow_src, "init", "-q")
        (flow_src / "README.md").write_text("flow\n", encoding="utf-8")
        git(flow_src, "add", "-A")
        git(flow_src, "commit", "-qm", "flow")
        git(self.main, "submodule", "add", "-q", str(flow_src), "Flow")
        flow = self.main / "Flow"
        flow_wt = self.tmp / "flow-wt"
        git(flow, "worktree", "add", "-q", "--no-track", "-b", "wt/flow", str(flow_wt))
        for start in (flow, flow_wt, flow_wt / "README.md"):
            with self.subTest(start=start):
                self.assertEqual(self.main, paths.main_root(start))
                self.assertIn("/.git/modules/", paths._git_dirs(start)[1].as_posix())
        for start in (flow, flow_wt):  # Flow に設定が無くても本体の設定を使う
            with self.subTest(start=start):
                self.assertEqual(self.main_db, paths.resolve_db(start, env={}).path)

    def test_write_to_worktree_copy_stops_with_DB_NOT_MAIN(self):
        with self.assertRaises(paths.DbNotMain) as ctx:
            paths.check_write(self.wt_db, env={})
        self.assertIn("DB_NOT_MAIN", str(ctx.exception))
        self.assertIn(str(self.main_db), str(ctx.exception))
        paths.check_write(self.main_db, env={})  # 本体は通る
        paths.check_write(self.wt_db, env={"AIPLC_DB": str(self.wt_db)})  # 明示は通る
        paths.check_write(self.tmp / "outside.db", env={})  # git の外は通る

    def test_read_from_worktree_copy_only_warns(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            paths.warn_read(self.wt_db, env={})
            paths.warn_read(self.main_db, env={})
        self.assertEqual(1, err.getvalue().count("DB_NOT_MAIN"))


class NoConfigTest(_Repo):
    config = None

    def test_without_config_behaves_as_before(self):
        r = paths.resolve_db(self.wt, env={})
        self.assertEqual((self.wt_db, "script", "solo"), (r.path, r.source, r.mode))
        plain = self.tmp / "plain"
        plain.mkdir()
        self.assertEqual(plain / ".claude/db/ai_plc.db", paths.resolve_db(plain, env={}).path)

    def test_solo_mode_and_bad_mode_do_not_use_git_common_dir(self):
        cfg = self.wt / ".ai-plc"
        cfg.mkdir()
        for text in ("id_allocation:\n  mode: solo\n", "id_allocation:\n  mode: nope\n", "id_allocation: 3\n"):
            with self.subTest(text=text):
                (cfg / "config.yaml").write_text(text, encoding="utf-8")
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(self.wt_db, paths.resolve_db(self.wt, env={}).path)


class OpenReadOnlyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aiplc-ro-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = self.tmp / "ai_plc.db"
        make_db(self.db, journal="wal")
        drop_sidecars(self.db)  # error 14 が起きた形（WAL の DB で -wal/-shm が無い）

    def fake_connect(self, failures):
        """最初の failures 回の接続は、最初の読み取りで error 14 になる（macOS 標準の SQLite 3.43 の形）"""
        real = sqlite3.connect
        calls = []

        class Failing:
            def execute(self, *_):
                raise sqlite3.OperationalError("unable to open database file")

            def close(self):
                pass

            def set_authorizer(self, *_):
                pass

        def fake(*a, **kw):
            calls.append(a[0])
            return Failing() if len(calls) <= failures else real(*a, **kw)

        return calls, mock.patch.object(paths.sqlite3, "connect", side_effect=fake)

    def assert_read_only(self, conn):
        for sql in ("INSERT INTO marker VALUES ('x')", "WITH x AS (SELECT 1) DELETE FROM marker",
                    "PRAGMA journal_mode=delete", "ATTACH DATABASE ':memory:' AS other"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                conn.execute(sql)

    def test_wal_db_without_sidecars_opens_read_only(self):
        self.assertFalse(Path(f"{self.db}-shm").exists())
        before = self.db.read_bytes()
        with closing(paths.open_ro(self.db)) as conn:
            self.assertEqual(1, conn.execute("SELECT count(*) FROM marker").fetchone()[0])
            self.assert_read_only(conn)
        self.assertEqual(before, self.db.read_bytes())

    def test_error_14_falls_back_to_query_only_connection(self):
        calls, patch = self.fake_connect(1)
        with patch, closing(paths.open_ro(self.db)) as conn:
            self.assertEqual(1, conn.execute("SELECT count(*) FROM marker").fetchone()[0])
            self.assertEqual(1, conn.execute("PRAGMA query_only").fetchone()[0])
            self.assert_read_only(conn)
        self.assertEqual(2, len(calls), calls)
        self.assertTrue(calls[1].endswith("?mode=rw"), calls)

    def test_error_14_fallback_sees_uncheckpointed_wal(self):
        """別の書き手がまだ checkpoint していない内容も読む（immutable=1 だと見落とす）"""
        writer = sqlite3.connect(self.db)
        self.addCleanup(writer.close)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO marker VALUES ('uncheckpointed')")
        writer.commit()
        self.assertGreater(os.path.getsize(f"{self.db}-wal"), 0)
        calls, patch = self.fake_connect(1)
        with patch, closing(paths.open_ro(self.db)) as conn:
            self.assertEqual(2, conn.execute("SELECT count(*) FROM marker").fetchone()[0])
        self.assertTrue(calls[1].endswith("?mode=rw"), calls)

    def test_immutable_is_last_resort_only_without_wal(self):
        calls, patch = self.fake_connect(2)
        with patch, contextlib.redirect_stderr(io.StringIO()) as err:
            with closing(paths.open_ro(self.db)) as conn:
                self.assertEqual(1, conn.execute("SELECT count(*) FROM marker").fetchone()[0])
                self.assert_read_only(conn)
        self.assertTrue(calls[2].endswith("?mode=ro&immutable=1"), calls)
        self.assertIn("immutable=1", err.getvalue())

    def test_no_immutable_when_wal_has_content(self):
        Path(f"{self.db}-wal").write_bytes(b"pending")  # 未 checkpoint の内容があるかもしれない
        calls, patch = self.fake_connect(2)
        with patch, self.assertRaises(sqlite3.OperationalError):
            paths.open_ro(self.db)
        self.assertEqual(2, len(calls), calls)

    def test_missing_db_still_raises(self):
        with self.assertRaises(sqlite3.OperationalError):
            paths.open_ro(self.tmp / "missing.db")
        self.assertFalse((self.tmp / "missing.db").exists())

    def leave_wal(self):
        """別のプロセスが書いて、閉じずに終わった形（-wal に未 checkpoint の内容が残る）"""
        code = ("import os, sqlite3, sys; c = sqlite3.connect(sys.argv[1]); c.execute('PRAGMA wal_autocheckpoint=0'); "
                "c.execute(\"INSERT INTO marker VALUES ('in-wal')\"); c.commit(); os._exit(0)")
        subprocess.run([sys.executable, "-c", code, str(self.db)], check=True)
        self.assertGreater(os.path.getsize(f"{self.db}-wal"), 0)

    @unittest.skipUnless(hasattr(sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE")
                         and hasattr(sqlite3.Connection, "setconfig"), "Python 3.12 以上だけ（3.9 は文書の注意だけ）")
    def test_fallback_close_does_not_checkpoint_wal(self):
        """読むだけの接続を閉じても、WAL を DB ファイルへ書き戻さない（ファイルの hash が変わらない）"""
        self.leave_wal()
        before, wal = self.db.read_bytes(), Path(f"{self.db}-wal").read_bytes()
        calls, patch = self.fake_connect(1)
        with patch, closing(paths.open_ro(self.db)) as conn:
            self.assertEqual(2, conn.execute("SELECT count(*) FROM marker").fetchone()[0])
        self.assertTrue(calls[1].endswith("?mode=rw"), calls)
        self.assertEqual(before, self.db.read_bytes())
        self.assertEqual(wal, Path(f"{self.db}-wal").read_bytes())

    def test_no_checkpoint_on_close_reports_support(self):
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(paths.no_checkpoint_on_close(conn),
                             hasattr(sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE") and hasattr(conn, "setconfig"))

    def test_corrupt_db_fails_on_later_read_as_before(self):
        bad = self.tmp / "bad.db"
        bad.write_bytes(b"this is not sqlite")
        conn = paths.open_ro(bad)
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("SELECT * FROM projects")
        conn.close()


class InstalledFolderTest(unittest.TestCase):
    """公開版: DB のフォルダは aiplc_paths.py の置き場所（.claude/db・.cursor/db）で決まる"""

    def test_rel_db_follows_the_installed_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for folder in (".claude", ".cursor"):
                (root / folder / "db").mkdir(parents=True)
                shutil.copy2(DB_DIR / "aiplc_paths.py", root / folder / "db" / "aiplc_paths.py")
                mod = _load(f"aiplc_paths_{folder[1:]}", root / folder / "db" / "aiplc_paths.py")
                self.assertEqual(Path(folder) / "db" / "ai_plc.db", mod.REL_DB)
                self.assertEqual(root, mod.ROOT)
                self.assertEqual(root / folder / "db" / "ai_plc.db",
                                 mod.resolve_db(root, env={}).path)


if __name__ == "__main__":
    unittest.main()
