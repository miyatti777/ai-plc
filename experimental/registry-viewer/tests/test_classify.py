#!/usr/bin/env python3
"""classify.py（Registry の分類情報）の回帰テスト。一時 DB・一時 Layer・一時語彙だけを使う。

    python3 -m unittest discover -s .claude/db/tests -p "test_classify.py"                 # プロジェクトで
    python3 -m unittest discover -s experimental/registry-viewer/tests -p "test_classify.py" # 公開リポの checkout で

init_db.py（スキーマ）と aiplc_status_audit.py（Layer 探索）は、プロジェクトの配置か公開リポの配置から探す
（環境変数 AIPLC_INIT_DB・AIPLC_STATUS_AUDIT でも指定できる）。見つからなければ skip。
"""
import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
DBDIR = HERE.parent  # classify.py のあるフォルダ（.claude/db か experimental/registry-viewer）
PUBLIC_REPO = HERE.parents[2]
sys.path.insert(0, str(DBDIR))
import classify  # noqa: E402


def _first(env, cands):
    v = os.environ.get(env)
    if v:
        return Path(v) if Path(v).is_file() else None
    return next((c for c in cands if c.is_file()), None)


INIT_DB = _first("AIPLC_INIT_DB", [DBDIR / "init_db.py", classify.DB_DIR / "init_db.py", PUBLIC_REPO / "core" / "db" / "init_db.py"])
AUDIT = _first("AIPLC_STATUS_AUDIT", [classify.REPO / "scripts" / "aiplc_status_audit.py",
                                      classify.REPO / ".claude" / "ai-plc-jev" / "scripts" / "aiplc_status_audit.py",
                                      PUBLIC_REPO / "experimental" / "jev" / "scripts" / "aiplc_status_audit.py"])
init_db = classify._load_module("_t_init_db", INIT_DB) if INIT_DB else None

VOCAB = """version: 1
affiliation:
  private: {label: "個人", keywords: ["ドラム"]}
  company: {label: "会社", keywords: ["社内"]}
  c1: {label: "秘密の顧客", confidential: true, keywords: ["秘密顧客"]}
kind:
  dev: {label: "開発", keywords: ["実装", "ツール"]}
  research: {label: "調査", keywords: ["調査"]}
"""

INTENT = """scope_id: "{sid}"
scope_name: "{name}"
status: active   # コメント
goal:
  description: "{goal}"
{extra}parent_scope: null
"""


class Base(unittest.TestCase):
    def setUp(self):
        if init_db is None or AUDIT is None:
            self.skipTest("init_db.py か aiplc_status_audit.py が見つかりません")
        self._env_audit = os.environ.get("AIPLC_STATUS_AUDIT")
        os.environ["AIPLC_STATUS_AUDIT"] = str(AUDIT)
        self.tmp = tempfile.TemporaryDirectory(prefix="cls_")
        self.root = Path(self.tmp.name)
        self.db = self.root / "ai_plc.db"
        conn = sqlite3.connect(self.db)
        with contextlib.redirect_stdout(io.StringIO()):
            init_db.create_schema(conn)
        classify.create_tables(conn)  # 公開版の init_db.py は分類の表を作らない
        conn.close()
        (self.root / "vocab.yaml").write_text(VOCAB, encoding="utf-8")
        self._env = os.environ.get("AIPLC_CLASSIFICATION_VOCAB")
        os.environ["AIPLC_CLASSIFICATION_VOCAB"] = str(self.root / "vocab.yaml")
        self.vocab = classify.load_vocab()
        self.flow = self.root / "Flow" / "209901" / "2099-01-01"

    def tearDown(self):
        if self._env_audit is None:
            os.environ.pop("AIPLC_STATUS_AUDIT", None)
        else:
            os.environ["AIPLC_STATUS_AUDIT"] = self._env_audit
        if self._env is None:
            os.environ.pop("AIPLC_CLASSIFICATION_VOCAB", None)
        else:
            os.environ["AIPLC_CLASSIFICATION_VOCAB"] = self._env
        self.tmp.cleanup()

    def layer(self, sid, folder, goal, extra="", backlog=None, name="PJ"):
        d = self.flow / folder
        d.mkdir(parents=True)
        (d / "intent.yaml").write_text(INTENT.format(sid=sid, name=name, goal=goal, extra=extra), encoding="utf-8")
        if backlog is not None:
            (d / "backlog.yaml").write_text(backlog, encoding="utf-8")
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO projects (scope_id, name, goal, status) VALUES (?,?,?,'active')", (sid, name, goal))
        conn.commit()
        conn.close()
        return d

    def q(self, sql, args=()):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = classify.main(["--db", str(self.db), "--root", str(self.root), *argv])
        return rc, out.getvalue()


class TableTests(Base):
    def test_tables_created_and_identity_inventory_passes(self):
        conn = sqlite3.connect(self.db)
        try:
            self.assertTrue(classify.has_tables(conn))
            if hasattr(init_db, "_validate_schema_inventory"):
                init_db._validate_schema_inventory(conn)  # projects / tasks は変えていない（Identity v2 の検査がある版だけ）
        finally:
            conn.close()

    def test_ddl_matches_init_db(self):
        """classify.py の DDL と init_db.create_classification_tables が同じ表を作る（2か所の定義をずらさない）"""
        if not hasattr(init_db, "create_classification_tables"):
            self.skipTest("この init_db.py には分類の表の定義が無い（公開版）")
        def schema(fn):
            c = sqlite3.connect(":memory:")
            fn(c)
            rows = c.execute("SELECT name, sql FROM sqlite_master WHERE name IN ('project_classification','task_execution') ORDER BY name").fetchall()
            c.close()
            return [(n, " ".join(q.split())) for n, q in rows]
        def own(c):
            c.executescript(classify.TABLES_SQL)
        self.assertEqual(schema(init_db.create_classification_tables), schema(own))

    def test_migrate_on_old_db(self):
        old = self.root / "old.db"
        conn = sqlite3.connect(old)
        conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, scope_id TEXT, name TEXT, goal TEXT)")
        conn.commit()
        conn.close()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            classify.main(["--db", str(old), "migrate"])
            self.assertIn("予定", out.getvalue())
            classify.main(["--db", str(old), "--state-dir", str(self.root / "st"), "migrate", "--yes"])
        conn = sqlite3.connect(old)
        self.assertTrue(classify.has_tables(conn))
        conn.close()
        self.assertTrue(list((self.root / "st").glob("ai_plc_backup_before_classify_*.db")))

    def test_executor_check_constraint(self):
        with self.assertRaises(sqlite3.IntegrityError):
            conn = sqlite3.connect(self.db)
            try:
                conn.execute("INSERT INTO project_classification (scope_id, executor) VALUES ('X','vim')")
            finally:
                conn.close()


class VocabTests(Base):
    def test_bad_key_rejected(self):
        p = self.root / "bad.yaml"
        p.write_text("affiliation:\n  Bad_Key: {label: x}\n", encoding="utf-8")
        with self.assertRaises(classify.ClassifyError):
            classify.load_vocab(p)

    def test_confidential_label_hidden(self):
        self.assertEqual(classify.label(self.vocab, "affiliation", "c1"), "c1（機密）")
        self.assertEqual(classify.label(self.vocab, "affiliation", "c1", reveal=True), "秘密の顧客")
        rc, out = self.run_cli("vocab")
        self.assertNotIn("秘密の顧客", out)

    def test_missing_env_file_stops(self):
        os.environ["AIPLC_CLASSIFICATION_VOCAB"] = str(self.root / "nope.yaml")
        with self.assertRaises(classify.ClassifyError):
            classify.vocab_path()


class EditTests(unittest.TestCase):
    def test_append_when_absent(self):
        t = 'scope_id: "A"\nstatus: active\n'
        out = classify.edit_classification_text(t, {"affiliation": "private", "kind": None, "executor": "codex"})
        self.assertEqual(out, t + "classification:\n  affiliation: private\n  executor: codex\n")

    def test_replace_existing_block_keeps_others(self):
        t = 'a: 1\nclassification:\n  affiliation: company\n  kind: dev\n\n# 次\nb: 2\n'
        out = classify.edit_classification_text(t, {"affiliation": "private", "kind": "dev", "executor": None})
        self.assertEqual(out, 'a: 1\nclassification:\n  affiliation: private\n  kind: dev\n\n# 次\nb: 2\n')

    def test_no_trailing_newline(self):
        out = classify.edit_classification_text("a: 1", {"affiliation": "x", "kind": None, "executor": None})
        self.assertEqual(out, "a: 1\nclassification:\n  affiliation: x\n")


class SyncTests(Base):
    def test_sync_project_and_tasks(self):
        d = self.layer("L-9001", "a", "ツールの実装", extra="classification:\n  affiliation: private\n  kind: dev\n  executor: claude-code\n",
                       backlog="tasks:\n  - id: T001\n    status: completed\n    executed_by: codex\n  - id: T002\n    status: pending\n")
        rc, out = self.run_cli("sync", "--layer", str(d))
        self.assertEqual(self.q("SELECT count(*) FROM project_classification")[0][0], 0)  # 予定だけ
        rc, out = self.run_cli("sync", "--layer", str(d), "--yes")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.q("SELECT affiliation, kind, executor, source FROM project_classification"),
                         [("private", "dev", "claude-code", "intent")])
        self.assertEqual(self.q("SELECT task_id, executed_by FROM task_execution"), [("T001", "codex")])
        # 正本を変えて写し直すと更新される
        (d / "intent.yaml").write_text((d / "intent.yaml").read_text(encoding="utf-8").replace("kind: dev", "kind: research"),
                                       encoding="utf-8")
        self.run_cli("sync", "--layer", str(d), "--yes")
        self.assertEqual(self.q("SELECT kind FROM project_classification")[0][0], "research")

    def test_sync_skips_unknown_vocab(self):
        d = self.layer("L-9002", "b", "x", extra="classification:\n  affiliation: unknown-org\n")
        rc, out = self.run_cli("sync", "--layer", str(d), "--yes")
        self.assertIn("語彙に無い", out)
        self.assertEqual(self.q("SELECT count(*) FROM project_classification")[0][0], 0)

    def test_sync_all(self):
        self.layer("L-9003", "c", "x", extra="classification:\n  kind: dev\n")
        rc, out = self.run_cli("sync", "--all", "--yes")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.q("SELECT scope_id, kind FROM project_classification"), [("L-9003", "dev")])


class RobustnessTests(Base):
    def test_broken_yaml_does_not_stop_all(self):
        self.layer("L-9401", "ok", "ツールの実装", extra="classification:\n  kind: dev\n")
        bad = self.layer("L-9402", "bad", "x")
        (bad / "backlog.yaml").write_text("tasks:\n  - id: [broken\n", encoding="utf-8")
        rc, out = self.run_cli("sync", "--all", "--yes")
        self.assertEqual(rc, 0, out)
        self.assertIn("L-9402", out)
        self.assertEqual(self.q("SELECT scope_id FROM project_classification"), [("L-9401",)])
        rc, out = self.run_cli("suggest", "--out", str(self.root / "s.json"))
        self.assertEqual(rc, 0, out)
        rep = json.loads((self.root / "s.json").read_text(encoding="utf-8"))
        self.assertIn("L-9402", [r["scope_id"] for r in rep["out_of_scope"]])

    def test_apply_without_tables_writes_nothing(self):
        d = self.layer("L-9403", "nt", "ツールの実装")
        conn = sqlite3.connect(self.db)
        conn.execute("DROP TABLE project_classification")
        conn.commit()
        conn.close()
        rep = {"kind": "classify.approval", "rows": [{"scope_id": "L-9403", "decision": "approve", "from": None,
                                                      "affiliation": "private", "kind": "dev", "executor": "codex"}]}
        p = self.root / "a.json"
        p.write_text(json.dumps(rep), encoding="utf-8")
        before = (d / "intent.yaml").read_text(encoding="utf-8")
        rc, out = self.run_cli("apply", str(p), "--yes")
        self.assertEqual(rc, 2, out)
        self.assertEqual((d / "intent.yaml").read_text(encoding="utf-8"), before)

    def test_unknown_subkey_refused(self):
        d = self.layer("L-9404", "sub", "x", extra="classification:\n  kind: dev\n  extra: 1\n")
        with self.assertRaises(classify.ClassifyError):
            classify.write_classification(d / "intent.yaml", {"affiliation": "private", "kind": "dev", "executor": None})

    def test_crlf_kept(self):
        out = classify.edit_classification_text("a: 1\r\n", {"affiliation": "x", "kind": None, "executor": None})
        self.assertEqual(out, "a: 1\r\nclassification:\r\n  affiliation: x\r\n")

    def test_vocab_duplicate_key(self):
        p = self.root / "dup.yaml"
        p.write_text("affiliation:\n  a: {label: x}\n  a: {label: y}\n", encoding="utf-8")
        with self.assertRaises(classify.ClassifyError):
            classify.load_vocab(p)

    def test_suggest_does_not_overwrite(self):
        self.layer("L-9405", "s", "ツール")
        st = self.root / "st"
        self.run_cli("--state-dir", str(st), "suggest")
        self.run_cli("--state-dir", str(st), "suggest")
        self.assertEqual(len(list((st / "approvals").glob("classify_*.json"))), 2)

    def test_broken_approval_json(self):
        p = self.root / "bad.json"
        p.write_text("{", encoding="utf-8")
        rc, out = self.run_cli("apply", str(p))
        self.assertEqual(rc, 2)
        self.assertIn("承認ファイルを読めません", out)


class AmbiguityTests(Base):
    def test_duplicate_scope_not_synced_or_suggested(self):
        self.layer("L-9201", "dup1", "x", extra="classification:\n  kind: dev\n")
        d2 = self.flow / "dup2"
        d2.mkdir()
        (d2 / "intent.yaml").write_text('scope_id: "L-9201"\nstatus: active\nclassification:\n  kind: research\n', encoding="utf-8")
        rc, out = self.run_cli("sync", "--all", "--yes")
        self.assertEqual(self.q("SELECT count(*) FROM project_classification WHERE scope_id='L-9201'")[0][0], 0)
        rep_path = self.root / "a.json"
        self.run_cli("suggest", "--out", str(rep_path))
        rep = json.loads(rep_path.read_text(encoding="utf-8"))
        self.assertIn("L-9201", [r["scope_id"] for r in rep["out_of_scope"]])

    def test_duplicate_resolved_by_url(self):
        d1 = self.layer("L-9202", "dupa", "x", extra="classification:\n  kind: dev\n")
        d2 = self.flow / "dupb"
        d2.mkdir()
        (d2 / "intent.yaml").write_text('scope_id: "L-9202"\nstatus: active\n', encoding="utf-8")
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE projects SET top_page_url=? WHERE scope_id='L-9202'", (os.path.relpath(d1, self.root),))
        conn.commit()
        conn.close()
        self.run_cli("sync", "--all", "--yes")
        self.assertEqual(self.q("SELECT kind FROM project_classification WHERE scope_id='L-9202'"), [("dev",)])


class WorkspaceGuardTests(Base):
    def test_multiple_workspace_rows_stop(self):
        d = self.layer("L-9301", "ws", "x", extra="classification:\n  kind: dev\n")
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE projects2 AS SELECT * FROM projects")
        conn.execute("DROP INDEX IF EXISTS idx_projects_scope")
        conn.commit()
        conn.close()
        # scope_id の一意制約がある本番スキーマでは重複行を作れないので、関数を直接呼んで検査を確かめる
        conn = sqlite3.connect(self.db)
        conn.execute("DROP TABLE projects")
        conn.execute("ALTER TABLE projects2 RENAME TO projects")
        conn.execute("INSERT INTO projects (scope_id, name) VALUES ('L-9301', 'dup')")
        conn.commit()
        conn.close()
        with self.assertRaises(classify.ClassifyError):
            classify.sync_rows(self.root, self.db, [("L-9301", d)], True, self.vocab)


class SuggestApplyTests(Base):
    def setUp(self):
        super().setUp()
        self.a = self.layer("L-9101", "drum", "ドラムの練習ツールを実装する", name="ドラム練習")
        self.b = self.layer("L-9102", "legacy", "社内の調査", extra="executor: Codex\n")
        self.c = self.layer("L-9103", "done", "x", extra="classification:\n  affiliation: private\n  kind: dev\n  executor: cursor\n")
        self.out = self.root / "approval.json"

    def suggest(self):
        rc, out = self.run_cli("suggest", "--out", str(self.out))
        self.assertEqual(rc, 0, out)
        return json.loads(self.out.read_text(encoding="utf-8"))

    def test_suggest_candidates(self):
        rep = self.suggest()
        rows = {r["scope_id"]: r for r in rep["rows"]}
        self.assertNotIn("L-9103", rows)  # もう付いている
        self.assertEqual((rows["L-9101"]["affiliation"], rows["L-9101"]["kind"], rows["L-9101"]["executor"]), ("private", "dev", None))
        self.assertEqual((rows["L-9102"]["affiliation"], rows["L-9102"]["kind"], rows["L-9102"]["executor"]), ("company", "research", "codex"))
        self.assertTrue(all(r["decision"] == "undecided" for r in rep["rows"]))
        self.assertNotIn("秘密の顧客", self.out.read_text(encoding="utf-8"))

    def test_undecided_writes_nothing(self):
        self.suggest()
        before = (self.a / "intent.yaml").read_text(encoding="utf-8")
        rc, out = self.run_cli("apply", str(self.out), "--yes")
        self.assertIn("approve の行がありません", out)
        self.assertEqual((self.a / "intent.yaml").read_text(encoding="utf-8"), before)

    def test_apply_approved_row(self):
        rep = self.suggest()
        for r in rep["rows"]:
            if r["scope_id"] == "L-9101":
                r["decision"] = "approve"
                r["executor"] = "claude-code"  # 人が直した値
        self.out.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
        rc, out = self.run_cli("apply", str(self.out))  # dry-run
        self.assertIn("planned", out)
        self.assertNotIn("classification", (self.a / "intent.yaml").read_text(encoding="utf-8"))
        rc, out = self.run_cli("--state-dir", str(self.root / "st"), "apply", str(self.out), "--yes")
        self.assertEqual(rc, 0, out)
        text = (self.a / "intent.yaml").read_text(encoding="utf-8")
        self.assertIn("status: active   # コメント", text)  # 他の行はそのまま
        self.assertIn("classification:\n  affiliation: private\n  kind: dev\n  executor: claude-code\n", text)
        self.assertEqual(self.q("SELECT affiliation, kind, executor FROM project_classification WHERE scope_id='L-9101'"),
                         [("private", "dev", "claude-code")])
        log = (self.root / "st" / "classify_log.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(log[-1])["scope_id"], "L-9101")
        # もう一度流すと noop（反映済み）
        rc, out = self.run_cli("--state-dir", str(self.root / "st"), "apply", str(self.out), "--yes")
        self.assertIn("L-9101: noop", out)

    def test_apply_conflict_when_changed(self):
        rep = self.suggest()
        for r in rep["rows"]:
            r["decision"] = "approve"
        self.out.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
        (self.a / "intent.yaml").write_text((self.a / "intent.yaml").read_text(encoding="utf-8")
                                            + "classification:\n  kind: research\n", encoding="utf-8")
        rc, out = self.run_cli("apply", str(self.out), "--yes")
        self.assertIn("L-9101: conflict", out)

    def test_apply_rejects_unknown_value(self):
        rep = self.suggest()
        for r in rep["rows"]:
            if r["scope_id"] == "L-9101":
                r["decision"] = "approve"
                r["affiliation"] = "nope"
        self.out.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
        rc, out = self.run_cli("apply", str(self.out), "--yes")
        self.assertEqual(rc, 1)
        self.assertIn("語彙にありません", out)

    def test_show_hides_confidential(self):
        d = self.layer("L-9104", "secret", "x", extra="classification:\n  affiliation: c1\n")
        self.run_cli("sync", "--layer", str(d), "--yes")
        rc, out = self.run_cli("show")
        self.assertIn("c1（機密）", out)
        self.assertNotIn("秘密の顧客", out)
        rc, out = self.run_cli("show", "--reveal")
        self.assertIn("秘密の顧客", out)


if __name__ == "__main__":
    unittest.main()
