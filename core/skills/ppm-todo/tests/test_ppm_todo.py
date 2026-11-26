"""ppm-todo の道具（inflight_programs・todo_waiting・todo_summary）のテスト。全部合成のデータ（架空の題名）。

    python3 -m unittest discover -s core/skills/ppm-todo/tests
"""
import contextlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
SKILLS = Path(__file__).resolve().parents[2]
CORE = SKILLS.parent
sys.path.insert(0, str(SKILLS / "ppm-todo"))
sys.path.insert(0, str(CORE / "db"))
import inflight_programs as ip  # noqa: E402
import todo_summary as ts  # noqa: E402
import todo_waiting as tw  # noqa: E402

TODAY = date(2026, 1, 20)
WS = "ws_test"
# 合成の TODO の一覧（同梱の雛形の例の文言には依存しない。見出しは既定の名前）
TODO_TEXT = """# TODO

## 進行中の仕事

### 主軸

- [ ] 手順書の目次を決める（1/30 まで）
  <!-- layer: Flow/202601/2026-01-05/manual-toc scope: L-9001 -->
  2026-01-06: 入力の画面までできた。計算の部分が残る。

### 支援課題

- [ ] チームの週報の書き方をそろえる
  <!-- source: Flow/202601/2026-01-05/notes.md candidate: weekly_report -->
- [ ] 古いアンケートの設問を見直す（1/10 まで）
  <!-- layer: Flow/202512/2025-12-01/survey-form scope: L-9004 -->

## 進行中の私生活

- [ ] 借りた傘を返す

## 待ち／要確認

- 備品の届く日を確かめる（1/15 ごろ）
  届いたら受付に置く
- アンケートの設問の確認待ち（L-9004）
- 来週の打ち合わせの日を決める
- Registry だけの案件の返事（L-9006）
- 名札の用紙の返事（tags-2026）

## 未再計画（旧案件）

- 議事録の様式をそろえる

## いつでもいい雑務

- [ ] 社内の用語集に1語足す :15
"""


def write_layer(root: Path, rel: str, intent: dict, tasks=None):
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "intent.yaml").write_text(json.dumps(intent, ensure_ascii=False), encoding="utf-8")
    (d / "backlog.yaml").write_text(json.dumps({"scope_id": intent["scope_id"],
                                                "tasks": tasks or [{"id": "T001", "status": "pending"}]}),
                                    encoding="utf-8")
    (d / "context.yaml").write_text(json.dumps({"scope_id": intent["scope_id"]}), encoding="utf-8")


def make_db(path: Path, business: bool):
    import business_registry as br
    import init_db
    con = sqlite3.connect(path)
    with contextlib.redirect_stdout(io.StringIO()):
        init_db.create_schema(con)
    for sid, name, st in (("L-9001", "手順書の目次", "active"), ("L-9002", "名札を印刷する", "active"),
                          ("L-9004", "アンケートの設問", "completed"), ("L-9006", "Registry だけの案件", "completed")):
        con.execute("INSERT INTO projects(scope_id, name, status) VALUES(?,?,?)", (sid, name, st))
    if business:
        for s in br.DDL:
            con.execute(s)
        pid = {r[0]: r[1] for r in con.execute("SELECT scope_id, id FROM projects")}
        con.execute("INSERT INTO programs VALUES('prg_work',?, 'stock:仕事','仕事','work','work',NULL,NULL,'t',1,2,1,'active')", (WS,))
        con.execute("INSERT INTO programs VALUES('prg_home',?, 'stock:くらし','くらし','private','private',NULL,NULL,'t',1,2,1,'active')", (WS,))
        con.execute("INSERT INTO business_projects(business_uid, workspace_id, display_name, purpose, included_json,"
                    " excluded_json, visibility, source_ref, source_hash, source_as_of, ownership_epoch,"
                    " identity_version, row_revision, state) VALUES('bpr_tools',?,'社内の道具','社内で使う小さな道具を作る',"
                    "'[]','[]','work','t','h','2026-01-01',1,2,1,'active')", (WS,))
        con.execute("INSERT INTO program_memberships(membership_uid, workspace_id, program_uid, target_kind, business_uid,"
                    " source_ref, row_revision, state) VALUES('m1',?,'prg_work','business_project','bpr_tools','t',1,'confirmed')", (WS,))
        con.execute("INSERT INTO business_project_links VALUES('k1',?,'bpr_tools',?,'u1',1,2,'{}','primary',NULL,NULL,'t',1,'confirmed')",
                    (WS, pid["L-9001"]))
        con.execute("INSERT INTO program_memberships(membership_uid, workspace_id, program_uid, target_kind, project_id,"
                    " aiplc_uid, project_epoch, project_version, identity_snapshot, source_ref, row_revision, state)"
                    " VALUES('m2',?,'prg_home','aiplc_project',?,'u2',1,2,'{}','t',1,'confirmed')", (WS, pid["L-9002"]))
    con.commit()
    con.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "todo").mkdir()
        self.todo = self.root / "todo" / "todo.md"
        self.todo.write_text(TODO_TEXT, encoding="utf-8")
        write_layer(self.root, "Flow/202601/2026-01-05/manual-toc",
                    {"scope_id": "L-9001", "display_name": "手順書の目次", "status": "active", "deadline": "2026-01-30"})
        write_layer(self.root, "Flow/202601/2026-01-15/name-tags",
                    {"scope_id": "L-9002", "display_name": "名札を印刷する", "status": "active"})
        write_layer(self.root, "Flow/202512/2025-12-01/survey-form",
                    {"scope_id": "L-9004", "display_name": "アンケートの設問", "status": "completed"},
                    [{"id": "T001", "status": "completed"}])
        write_layer(self.root, ".ai-plc/projects/tags",
                    {"scope_id": "tags-2026", "display_name": "名札の用紙", "status": "cancelled"},
                    [{"id": "T001", "status": "cancelled"}])
        self.cfg = tw.ppm_files().load_config(self.root)
        out = tempfile.TemporaryDirectory()  # 承認ファイルはリポジトリの外に置く
        self.addCleanup(out.cleanup)
        self.outside = Path(out.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()


class InflightProgramsTest(Base):
    def test_flat_without_db(self):
        g = ip.build(self.root, db=self.root / "none.db", today=TODAY)
        self.assertEqual(g["mode"], "flat")
        self.assertIn("見つからない", g["note"])
        kinds = {r["title"]: ip.row_kind(r) for r in g["rows"]}
        self.assertEqual(kinds["手順書の目次を決める（1/30 まで）"], "keep")
        self.assertEqual(kinds["名札を印刷する"], "add")
        self.assertEqual(kinds["古いアンケートの設問を見直す（1/10 まで）"], "remove")
        self.assertEqual(kinds["チームの週報の書き方をそろえる"], "todo_only")  # source の注記だけで Layer 無し
        self.assertEqual(g["decisions"]["add"], 1)

    def test_flat_when_business_tables_absent(self):
        db = self.root / "plain.db"
        make_db(db, business=False)
        g = ip.build(self.root, db=db, today=TODAY)
        self.assertEqual(g["mode"], "flat")
        self.assertIn("業務プロジェクトの表が無い", g["note"])
        self.assertIn("今日決めること", ip.format_md(g))

    def test_grouped_with_business_tables(self):
        db = self.root / "biz.db"
        make_db(db, business=True)
        g = ip.build(self.root, db=db, today=TODAY)
        self.assertEqual(g["mode"], "grouped")
        progs = {p["program"]: p for p in g["programs"]}
        self.assertEqual(progs["仕事"]["businesses"][0]["business"], "社内の道具")
        self.assertEqual(progs["仕事"]["businesses"][0]["purpose"], "社内で使う小さな道具を作る")
        home = progs["くらし"]["businesses"][0]
        self.assertEqual(home["business"], ip.NO_BUSINESS)
        self.assertIsNone(home["purpose"])
        reasons = {u["reason"]: len(u["rows"]) for u in g["unclassified"]}
        self.assertEqual(reasons.get("no_membership"), 1)  # L-9004（外す候補）は所属が無い
        self.assertEqual(reasons.get("todo_only"), 2)
        md = ip.format_md(g, detail=True)
        self.assertIn("## 仕事（仕事）", md)
        self.assertIn("社内で使う小さな道具を作る", md)
        json.dumps(ip.to_json(g), ensure_ascii=False)

    def test_db_is_not_written(self):
        db = self.root / "biz.db"
        make_db(db, business=True)
        before = db.read_bytes()
        ip.build(self.root, db=db, today=TODAY)
        self.assertEqual(before, db.read_bytes())


class WaitingTest(Base):
    def review(self, db=None):
        return tw.review(self.todo.read_text(encoding="utf-8"), self.cfg, self.root, TODAY, db)

    def test_classify(self):
        r = self.review()
        kinds = {i["body"]: i["kind"] for i in r["items"]}
        self.assertEqual(kinds["備品の届く日を確かめる（1/15 ごろ）"], "past")
        self.assertEqual(kinds["アンケートの設問の確認待ち（L-9004）"], "resolved")
        self.assertEqual(kinds["来週の打ち合わせの日を決める"], "unknown")
        self.assertEqual(kinds["名札の用紙の返事（tags-2026）"], "resolved")  # ID の形を決め打ちしない
        self.assertEqual(kinds["Registry だけの案件の返事（L-9006）"], "unknown")  # DB を渡さなければ分からない

    def test_registry_fallback(self):
        db = self.root / "plain.db"
        make_db(db, business=False)
        kinds = {i["body"]: (i["kind"], i["reason"]) for i in self.review(db)["items"]}
        kind, reason = kinds["Registry だけの案件の返事（L-9006）"]
        self.assertEqual(kind, "resolved")
        self.assertIn("Registry の写し", reason)

    def test_apply_changes_only_approved_lines(self):
        text = self.todo.read_text(encoding="utf-8")
        r = self.review()
        keys = {i["body"]: i["key"] for i in r["items"]}
        approval = {"todo_sha256": r["todo_sha256"], "items": [
            {"key": keys["備品の届く日を確かめる（1/15 ごろ）"], "action": "delete"},
            {"key": keys["来週の打ち合わせの日を決める"], "action": "rewrite", "text": "打ち合わせの日を 2/3 に決める"}]}
        new, notes = tw.apply(text, approval, self.cfg)
        self.assertEqual(len(notes), 2)
        old_lines = text.split("\n")
        removed = {"- 備品の届く日を確かめる（1/15 ごろ）", "  届いたら受付に置く", "- 来週の打ち合わせの日を決める"}
        expect = []
        for line in old_lines:
            if line == "- 来週の打ち合わせの日を決める":
                expect.append("- 打ち合わせの日を 2/3 に決める")
            elif line not in removed:
                expect.append(line)
        self.assertEqual(new.split("\n"), expect)  # ほかの行は1文字も変わらない

    def test_apply_refuses(self):
        text = self.todo.read_text(encoding="utf-8")
        r = self.review()
        k = r["items"][0]["key"]
        with self.assertRaises(tw.ApplyError):
            tw.apply(text + "x", {"todo_sha256": r["todo_sha256"], "items": [{"key": k, "action": "delete"}]}, self.cfg)
        for bad in ([{"key": "nope0000", "action": "delete"}], [{"key": k, "action": "move"}],
                    [{"key": k, "action": "rewrite", "text": "a\nb"}], [{"key": k, "action": "rewrite", "text": " "}],
                    [{"key": k, "action": "delete"}, {"key": k, "action": "delete"}], []):
            with self.subTest(bad=bad), self.assertRaises(tw.ApplyError):
                tw.apply(text, {"todo_sha256": r["todo_sha256"], "items": bad}, self.cfg)

    def test_unusual_line_break_refused(self):
        text = self.todo.read_text(encoding="utf-8").replace("借りた傘を返す", "借りた傘を\u2028返す")
        items = tw.parse_waiting(text, self.cfg)
        with self.assertRaises(tw.ApplyError):
            tw.apply(text, {"todo_sha256": tw.sha256(text), "items": [{"key": items[0]["key"], "action": "delete"}]}, self.cfg)

    def test_crlf_kept(self):
        text = self.todo.read_text(encoding="utf-8").replace("\n", "\r\n")
        items = tw.parse_waiting(text, self.cfg)
        k = [i for i in items if i["body"] == "来週の打ち合わせの日を決める"][0]["key"]
        new, _ = tw.apply(text, {"todo_sha256": tw.sha256(text), "items": [{"key": k, "action": "rewrite", "text": "決めた"}]}, self.cfg)
        self.assertIn("- 決めた\r\n", new)
        self.assertEqual(new.replace("- 決めた\r\n", "- 来週の打ち合わせの日を決める\r\n"), text)

    def test_same_body_gets_distinct_keys(self):
        text = self.todo.read_text(encoding="utf-8").replace("- 来週の打ち合わせの日を決める",
                                                             "- 来週の打ち合わせの日を決める\n- 来週の打ち合わせの日を決める")
        keys = [i["key"] for i in tw.parse_waiting(text, self.cfg)]
        self.assertEqual(len(keys), len(set(keys)))

    def test_custom_section_and_disabled(self):
        cfg_dir = self.root / ".ai-plc"
        cfg_dir.mkdir(exist_ok=True)
        (cfg_dir / "config.yaml").write_text("ppm:\n  todo:\n    waiting_section: 返事待ち\n", encoding="utf-8")
        text = self.todo.read_text(encoding="utf-8").replace("## 待ち／要確認", "## 返事待ち")
        cfg = tw.ppm_files().load_config(self.root)
        self.assertEqual(len(tw.parse_waiting(text, cfg)), 5)
        (cfg_dir / "config.yaml").write_text("ppm:\n  todo:\n    waiting_section: null\n", encoding="utf-8")
        cfg = tw.ppm_files().load_config(self.root)
        r = tw.review(text, cfg, self.root, TODAY)
        self.assertFalse(r["enabled"])
        self.assertIn("使わない設定", tw.format_review(r))
        with self.assertRaises(tw.ApplyError):
            tw.apply(text, {"todo_sha256": tw.sha256(text), "items": [{"key": "x", "action": "delete"}]}, cfg)

    def test_apply_bad_approval_shape(self):
        text = self.todo.read_text(encoding="utf-8")
        h = tw.sha256(text)
        for bad, word in (([{"key": "x", "action": "delete"}], "全体は"),
                          ({"todo_sha256": h, "items": ["x"]}, "1件目"),
                          ({"todo_sha256": h, "items": [{"key": 1, "action": "delete"}]}, "文字列"),
                          ({"todo_sha256": h, "items": "x"}, "items"),
                          ({"items": [{"key": "x", "action": "delete"}]}, "todo_sha256")):
            with self.subTest(bad=bad), self.assertRaises(tw.ApplyError) as cm:
                tw.apply(text, bad, self.cfg)
            self.assertIn(word, str(cm.exception))
            self.assertNotIn("変わっている", str(cm.exception))

    def test_short_and_numeric_ids_not_matched(self):
        known = {"15": ("completed", "Registry の写し"), "a1": ("completed", "Registry の写し"),
                 "2026-01": ("completed", "Registry の写し"), "L-9004": ("completed", "案件の intent"),
                 "box": ("completed", "Registry の写し")}
        self.assertEqual(tw.scopes_in("備品の届く日を確かめる（1/15 ごろ・a1 の箱）", known), [])
        self.assertEqual(tw.scopes_in("2026-01 の分の確認（L-9004）", known), ["L-9004"])
        self.assertEqual(tw.scopes_in("toolbox と box-2 の返事", known), [])  # 語の途中には当てない
        self.assertEqual(tw.scopes_in("box の返事", known), ["box"])

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tw.main(["--root", str(self.root), "--today", "2026-01-20", "--db", str(self.root / "none.db"), *args])
        return code, out.getvalue(), err.getvalue()

    def test_cli_write_and_hash_guard(self):
        code, out, _ = self.run_cli("--json")
        r = json.loads(out)
        k = [i["key"] for i in r["items"] if i["kind"] == "past"][0]
        appr = self.outside / "approval.json"
        appr.write_text(json.dumps({"todo_sha256": r["todo_sha256"], "items": [{"key": k, "action": "delete"}]}), encoding="utf-8")
        before = self.todo.read_text(encoding="utf-8")
        code, out, _ = self.run_cli("--apply", str(appr))
        self.assertEqual(code, 0)
        self.assertEqual(self.todo.read_text(encoding="utf-8"), before)  # --write が無ければ書かない
        code, out, _ = self.run_cli("--apply", str(appr), "--write")
        self.assertEqual(code, 0)
        self.assertNotIn("備品の届く日", self.todo.read_text(encoding="utf-8"))
        code, _, err = self.run_cli("--apply", str(appr), "--write")  # 一覧が変わったので同じ承認は通らない
        self.assertEqual(code, 2)
        self.assertIn("変わっている", err)


class WriteFileTest(Base):
    """保存するときに、元のファイルの権限とリンクを保つこと。"""

    def approval(self):
        r = tw.review(self.todo.read_text(encoding="utf-8"), self.cfg, self.root, TODAY)
        k = [i["key"] for i in r["items"] if i["kind"] == "past"][0]
        appr = self.outside / "approval.json"
        appr.write_text(json.dumps({"todo_sha256": r["todo_sha256"], "items": [{"key": k, "action": "delete"}]}),
                        encoding="utf-8")
        return appr

    def run_write(self, appr):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tw.main(["--root", str(self.root), "--today", "2026-01-20", "--db", str(self.root / "none.db"),
                            "--apply", str(appr), "--write"])
        return code, err.getvalue()

    def test_mode_kept(self):
        os.chmod(self.todo, 0o600)
        code, err = self.run_write(self.approval())
        self.assertEqual(code, 0, err)
        self.assertEqual(os.stat(self.todo).st_mode & 0o777, 0o600)
        self.assertNotIn("備品の届く日", self.todo.read_text(encoding="utf-8"))
        self.assertEqual([p.name for p in self.todo.parent.iterdir()], ["todo.md"])  # 一時ファイルを残さない

    def test_symlink_kept_and_target_updated(self):
        real = self.root / "lists" / "todo_real.md"
        real.parent.mkdir()
        self.todo.rename(real)
        os.chmod(real, 0o640)
        os.symlink(Path("..") / "lists" / "todo_real.md", self.todo)
        code, err = self.run_write(self.approval())
        self.assertEqual(code, 0, err)
        self.assertTrue(self.todo.is_symlink())
        self.assertNotIn("備品の届く日", real.read_text(encoding="utf-8"))
        self.assertEqual(os.stat(real).st_mode & 0o777, 0o640)

    def test_symlink_outside_repo_refused(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        outside = Path(other.name).resolve() / "todo.md"
        self.assertFalse(outside.resolve().is_relative_to(self.root))
        self.todo.rename(outside)
        os.symlink(outside, self.todo)
        appr = self.approval()
        before = outside.read_bytes()
        code, err = self.run_write(appr)
        self.assertEqual(code, 2)
        self.assertIn("リポジトリの外", err)
        self.assertEqual(outside.read_bytes(), before)
        self.assertTrue(self.todo.is_symlink())

    def test_approval_inside_repo_refused(self):
        r = tw.review(self.todo.read_text(encoding="utf-8"), self.cfg, self.root, TODAY)
        k = [i["key"] for i in r["items"] if i["kind"] == "past"][0]
        before = self.todo.read_bytes()
        for rel in ("approval.json", "todo/approval.json"):
            with self.subTest(rel=rel):
                appr = self.root / rel
                appr.write_text(json.dumps({"todo_sha256": r["todo_sha256"], "items": [{"key": k, "action": "delete"}]}),
                                encoding="utf-8")
                code, err = self.run_write(appr)
                self.assertEqual(code, 2)
                self.assertIn("リポジトリの中", err)
                appr.unlink()
        self.assertEqual(self.todo.read_bytes(), before)

    def test_not_utf8_and_deep_nesting_hold(self):
        appr = self.outside / "deep.json"
        appr.write_text("[" * 200000 + "]" * 200000, encoding="utf-8")
        code, err = self.run_write(appr)
        self.assertEqual(code, 2)
        self.assertIn("[HOLD]", err)
        self.assertNotIn("Traceback", err)
        good = self.approval()
        self.todo.write_bytes("## 待ち／要確認\n\n- 返事待ち\n".encode("cp932"))
        for args in ([], ["--apply", str(good)]):
            with self.subTest(args=args):
                out, errbuf = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(errbuf):
                    code = tw.main(["--root", str(self.root), "--today", "2026-01-20",
                                    "--db", str(self.root / "none.db"), *args])
                self.assertEqual(code, 2)
                self.assertIn("UTF-8", errbuf.getvalue())

    def test_outside_path_in_config_refused(self):
        # 設定で一覧の置き場をリポジトリの外にできないので、外の実体に書くのはリンクのときだけ（上で断る）
        cfg_dir = self.root / ".ai-plc"
        cfg_dir.mkdir(exist_ok=True)
        for bad in (str(self.outside / "todo.md"), "../todo.md"):
            with self.subTest(bad=bad):
                (cfg_dir / "config.yaml").write_text(f"ppm:\n  todo:\n    path: {json.dumps(bad)}\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    tw.ppm_files().load_config(self.root)


class SummaryTest(Base):
    def test_summary(self):
        s = ts.build(self.root, self.cfg, TODAY)
        md = ts.format_summary(s)
        self.assertIn("**主軸（1件）**", md)
        self.assertIn("**支援課題（2件）**", md)
        self.assertIn("**進行中の私生活（1件。題名だけ）**", md)
        self.assertIn("1/30（金）　手順書の目次を決める", md)
        self.assertIn("案件はもう閉じている：古いアンケートの設問を見直す", md)
        self.assertIn("あなたに聞く", md)
        self.assertNotIn("期限の1/10", md)  # 閉じた案件は期限切れとして重ねて出さない
        json.dumps(ts.to_json(s), ensure_ascii=False)

    def test_file_without_sections(self):
        self.todo.write_text("# TODO\n\n## 進行中の仕事\n\n- [ ] 名札を印刷する（2/1 まで）\n- [ ] 手紙を書く\n", encoding="utf-8")
        md = ts.format_summary(ts.build(self.root, self.cfg, TODAY))
        self.assertIn("**仕事（2件）**", md)
        self.assertIn("2/1（日）　名札を印刷する", md)
        self.assertNotIn("主軸", md)

    def test_intent_deadline_and_overdue(self):
        write_layer(self.root, "Flow/202601/2026-01-05/manual-toc",
                    {"scope_id": "L-9001", "display_name": "手順書の目次", "status": "active", "deadline": "2026-01-12"})
        self.todo.write_text(self.todo.read_text(encoding="utf-8").replace("（1/30 まで）", ""), encoding="utf-8")
        md = ts.format_summary(ts.build(self.root, self.cfg, TODAY))
        self.assertIn("案件に書かれた期限の1/12（月）を過ぎている：手順書の目次を決める", md)


class InstalledLayoutTest(unittest.TestCase):
    """導入先と同じ形（.claude/skills/…・.claude/db）に写して、道具が部品と DB を見つけて動くこと。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        skills = self.root / ".claude" / "skills"
        for name in ("ppm", "ppm-todo", "ppm-inflight"):
            shutil.copytree(SKILLS / name, skills / name, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        shutil.copytree(CORE / "db", self.root / ".claude" / "db", ignore=shutil.ignore_patterns("__pycache__", "*.md"))
        make_db(self.root / ".claude" / "db" / "ai_plc.db", business=True)
        (self.root / "todo").mkdir()
        (self.root / "todo" / "todo.md").write_text(TODO_TEXT, encoding="utf-8")
        write_layer(self.root, "Flow/202601/2026-01-05/manual-toc",
                    {"scope_id": "L-9001", "display_name": "手順書の目次", "status": "active"})

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, rel, *args, cwd=None):
        env = {k: v for k, v in os.environ.items() if k != "AIPLC_DB"}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([sys.executable, "-B", str(self.root / rel), *args], cwd=cwd or self.root,
                              capture_output=True, text=True, env=env, timeout=60)

    def test_tools_run_from_installed_copy(self):
        p = self.run_tool(".claude/skills/ppm-todo/inflight_programs.py", "--json", "--today", "2026-01-20")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["mode"], "grouped")  # 隣の .claude/db の DB を見つけた
        for rel in (".claude/skills/ppm-inflight/list_inflight.py", ".claude/skills/ppm-todo/todo_waiting.py",
                    ".claude/skills/ppm-todo/todo_summary.py"):
            with self.subTest(rel=rel):
                p = self.run_tool(rel, "--today", "2026-01-20", cwd=Path(self.tmp.name).parent)  # 別のフォルダから呼んでも動く
                self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(list(self.root.rglob("__pycache__")))


if __name__ == "__main__":
    unittest.main()
