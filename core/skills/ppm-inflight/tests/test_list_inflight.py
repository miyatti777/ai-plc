"""list_inflight.py のテスト。Layer・TODO の一覧は全部合成（架空の題名）。

    python3 -m unittest discover -s core/skills/ppm-inflight/tests
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS / "ppm-inflight"))
import list_inflight as li  # noqa: E402

TODAY = date(2026, 1, 20)
# 合成の TODO の一覧（同梱の雛形の例の文言には依存しない。見出しは既定の名前）
TODO_TEXT = """# TODO

## 進行中の仕事

### 主軸

- [ ] 手順書の目次を決める（1/30 まで）
  <!-- layer: Flow/202601/2026-01-05/manual-toc scope: L-9001 -->

### 支援課題

- [ ] チームの週報の書き方をそろえる
  <!-- source: Flow/202601/2026-01-05/notes.md candidate: weekly_report -->
- [ ] 古いアンケートの設問を見直す
  <!-- layer: Flow/202512/2025-12-01/survey-form scope: L-9004 -->

## 進行中の私生活

- [ ] 借りた傘を返す

## 待ち／要確認

- 備品の届く日を確かめる（1/15 ごろ）

## 未再計画（旧案件）

- 議事録の様式をそろえる
  <!-- layer: Flow/202601/2026-01-10/minutes-format scope: L-9005 -->

## いつでもいい雑務

- [ ] 社内の用語集に1語足す :15
"""


def write_layer(root: Path, rel: str, intent: dict, tasks=None, extra_backlog=None):
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "intent.yaml").write_text(json.dumps(intent, ensure_ascii=False), encoding="utf-8")
    backlog = {"scope_id": intent.get("scope_id"), "tasks": tasks or []}
    backlog.update(extra_backlog or {})
    (d / "backlog.yaml").write_text(json.dumps(backlog, ensure_ascii=False), encoding="utf-8")
    (d / "context.yaml").write_text(json.dumps({"scope_id": intent.get("scope_id")}), encoding="utf-8")
    return d


def open_task(tid="T001", **kw):
    return dict({"id": tid, "status": "pending"}, **kw)


class ListInflightTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "todo").mkdir()
        (self.root / "todo" / "todo.md").write_text(TODO_TEXT, encoding="utf-8")
        write_layer(self.root, "Flow/202601/2026-01-05/manual-toc",
                    {"scope_id": "L-9001", "display_name": "手順書の目次", "status": "active", "deadline": "2026-01-30"},
                    [open_task()])
        write_layer(self.root, "Flow/202601/2026-01-15/name-tags",
                    {"scope_id": "L-9002", "scope_name": "名札を印刷する", "status": "active"}, [open_task()])
        write_layer(self.root, "Flow/202510/2025-10-01/old-idea",
                    {"scope_id": "L-9003", "display_name": "古い思いつき", "status": "active"}, [open_task()])
        write_layer(self.root, "Flow/202512/2025-12-01/survey-form",
                    {"scope_id": "L-9004", "display_name": "アンケートの設問", "status": "completed"},
                    [{"id": "T001", "status": "completed"}])
        write_layer(self.root, "Flow/202601/2026-01-10/minutes-format",
                    {"scope_id": "L-9005", "display_name": "議事録の様式", "status": "active"}, [open_task()])
        # 数えないもの: SubLayer・Documents の写し・全部済み・parent_scope つき
        write_layer(self.root, "Flow/202601/2026-01-15/name-tags/sublayers/SG1",
                    {"scope_id": "L-9002-SG1", "status": "active"}, [open_task()])
        write_layer(self.root, "Flow/202601/2026-01-15/name-tags/Documents/copy",
                    {"scope_id": "L-9010", "status": "active"}, [open_task()])
        write_layer(self.root, "Flow/202601/2026-01-16/finished",
                    {"scope_id": "L-9011", "status": "active"}, [{"id": "T001", "status": "completed"}])
        write_layer(self.root, "Flow/202601/2026-01-16/child",
                    {"scope_id": "L-9012", "status": "active", "parent_scope": "L-9002"}, [open_task()])

    def tearDown(self):
        self.tmp.cleanup()

    def propose(self):
        return li.propose(self.root, TODAY)

    def ids(self, rows):
        return sorted(r["scope_id"] for r in rows)

    def test_buckets(self):
        p = self.propose()
        self.assertEqual(self.ids(p["keep"]), ["L-9001"])
        self.assertEqual(self.ids(p["add"]), ["L-9002"])
        self.assertEqual(self.ids(p["parked"]), ["L-9003"])
        self.assertEqual(self.ids(p["elsewhere"]), ["L-9005"])
        self.assertEqual([r["scope_id"] for r in p["remove"]], ["L-9004"])
        self.assertIn("閉じている", p["remove"][0]["reason"])

    def test_ignored_layers(self):
        seen = {r["scope_id"] for r in li.read_layers(self.root, TODAY)["layers"]}
        self.assertNotIn("L-9002-SG1", seen)
        self.assertNotIn("L-9010", seen)
        self.assertNotIn("L-9012", seen)
        rows = {r["scope_id"]: r for r in li.read_layers(self.root, TODAY)["layers"]}
        self.assertFalse(rows["L-9011"]["open"])  # 全部済み

    def test_titles_from_intent(self):
        p = self.propose()
        self.assertEqual(p["add"][0]["title"], "名札を印刷する")  # display_name が無ければ scope_name
        self.assertEqual(p["keep"][0]["todo_title"], "手順書の目次を決める（1/30 まで）")

    def test_open_child_keeps_parent(self):
        write_layer(self.root, "Flow/202601/2026-01-16/finished",
                    {"scope_id": "L-9011", "status": "active", "sub_agent_scopes": [{"status": "active"}]},
                    [{"id": "T001", "status": "completed"}])
        self.assertIn("L-9011", self.ids(self.propose()["add"]))

    def test_recurrence_task_keeps_open_until_retired(self):
        write_layer(self.root, "Flow/202601/2026-01-16/ops",
                    {"scope_id": "L-9013", "status": "active"},
                    [{"id": "T001", "status": "completed"}, {"id": "T002", "status": "completed", "recurrence": "weekly"}])
        self.assertIn("L-9013", self.ids(self.propose()["add"]))
        write_layer(self.root, "Flow/202601/2026-01-16/ops",
                    {"scope_id": "L-9013", "status": "active"},
                    [{"id": "T002", "status": "completed", "recurrence": "weekly", "retired_at": "2026-01-18"}])
        self.assertNotIn("L-9013", self.ids(self.propose()["add"]))

    def test_stale_and_blocked(self):
        write_layer(self.root, "Flow/202601/2026-01-15/name-tags",
                    {"scope_id": "L-9002", "scope_name": "名札を印刷する", "status": "blocked", "deadline": "2026-01-10"},
                    [open_task()])
        p = self.propose()
        st = {r["scope_id"]: r for r in p["stale"]}
        self.assertTrue(st["L-9002"]["stale"] and st["L-9002"]["blocked"])

    def test_scheduled_note(self):
        write_layer(self.root, "Flow/202601/2026-01-15/name-tags",
                    {"scope_id": "L-9002", "scope_name": "名札を印刷する", "status": "active"},
                    [open_task(scheduled_for="2026-02-02")])
        md = li.format_md(self.propose())
        self.assertIn("（時期待ち 2/2〜）", md)

    def test_ai_plc_projects_and_free_form_id(self):
        write_layer(self.root, ".ai-plc/projects/tags",
                    {"scope_id": "tags-2026", "display_name": "名札の用紙", "status": "active", "start_date": "2026-01-12"},
                    [open_task()])
        p = self.propose()
        row = [r for r in p["add"] if r["scope_id"] == "tags-2026"][0]
        self.assertEqual(row["layer"], ".ai-plc/projects/tags")
        self.assertEqual(row["layer_date_from"], "intent")

    def test_recent_days_from_config(self):
        (self.root / ".ai-plc").mkdir()
        (self.root / ".ai-plc" / "config.yaml").write_text("ppm:\n  inflight:\n    recent_days: 200\n", encoding="utf-8")
        self.assertIn("L-9003", self.ids(self.propose()["add"]))

    def test_todo_path_from_config_and_missing(self):
        (self.root / ".ai-plc").mkdir()
        (self.root / ".ai-plc" / "config.yaml").write_text("ppm:\n  todo:\n    path: lists/todo.md\n", encoding="utf-8")
        p = self.propose()
        self.assertFalse(p["todo_found"])
        self.assertEqual(p["keep"], [])
        self.assertIn("L-9001", self.ids(p["add"]))

    def test_absolute_layer_note(self):
        todo = self.root / "todo" / "todo.md"
        text = todo.read_text(encoding="utf-8")
        inside = str(self.root / "Flow/202601/2026-01-05/manual-toc")
        text = text.replace("<!-- layer: Flow/202601/2026-01-05/manual-toc scope: L-9001 -->",
                            f"<!-- layer: {inside} -->")
        text = text.replace("- [ ] 借りた傘を返す",
                            "- [ ] 借りた傘を返す\n  <!-- layer: /elsewhere/notes/loan -->")
        todo.write_text(text, encoding="utf-8")
        p = self.propose()
        self.assertEqual(self.ids(p["keep"]), ["L-9001"])  # 中の絶対パスは相対に直して結ぶ
        self.assertNotIn("L-9001", self.ids(p["add"]))
        self.assertEqual([r["title"] for r in p["outside_notes"]], ["借りた傘を返す"])
        self.assertNotIn("借りた傘を返す", [r["title"] for r in p["remove"]])
        self.assertIn("リポジトリの外を指す注記: 1件", li.format_md(p))

    def test_linked_intent_outside_not_read(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        ext = write_layer(Path(other.name), "ext", {"scope_id": "L-9020", "status": "active"}, [open_task()])
        d = self.root / "Flow/202601/2026-01-17/linked"
        d.mkdir(parents=True)
        os.symlink(ext / "intent.yaml", d / "intent.yaml")
        rows = li.read_layers(self.root, TODAY)
        self.assertNotIn("L-9020", {r["scope_id"] for r in rows["layers"]})
        self.assertEqual(rows["outside_links"], ["Flow/202601/2026-01-17/linked"])
        self.assertIn("読まなかった intent.yaml: 1件", li.format_md(self.propose()))

    def test_flow_itself_may_be_a_link(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        repo = Path(other.name).resolve() / "repo"
        store = Path(other.name).resolve() / "store"
        repo.mkdir()
        write_layer(store, "202601/2026-01-18/badge", {"scope_id": "L-9021", "status": "active"}, [open_task()])
        os.symlink(store, repo / "Flow")
        rows = li.read_layers(repo, TODAY)
        self.assertEqual([r["scope_id"] for r in rows["layers"]], ["L-9021"])
        self.assertEqual(rows["outside_links"], [])

    def test_layer_note_normalized(self):
        todo = self.root / "todo" / "todo.md"
        text = todo.read_text(encoding="utf-8")
        odd = str(self.root / "Flow/202601/x/../2026-01-05/./manual-toc")  # 途中に .. と . がある絶対パス
        text = text.replace("<!-- layer: Flow/202601/2026-01-05/manual-toc scope: L-9001 -->",
                            f"<!-- layer: {odd} -->")
        text = text.replace("- [ ] 借りた傘を返す",
                            "- [ ] 借りた傘を返す\n  <!-- layer: Flow/../../elsewhere/loan -->")
        todo.write_text(text, encoding="utf-8")
        p = self.propose()
        self.assertEqual(self.ids(p["keep"]), ["L-9001"])
        self.assertEqual([r["title"] for r in p["outside_notes"]], ["借りた傘を返す"])  # 相対でも外に出るもの
        self.assertNotIn("借りた傘を返す", [r["title"] for r in p["remove"]])
        self.assertEqual(li._norm("./Flow/a/../b/"), "Flow/b")
        self.assertTrue(li.outside_ref("Flow/../../x", self.root))
        self.assertFalse(li.outside_ref("Flow/a/../b", self.root))

    def test_warns_when_no_inflight_heading(self):
        todo = self.root / "todo" / "todo.md"
        text = todo.read_text(encoding="utf-8").replace("## 進行中の仕事", "## 仕事").replace("## 進行中の私生活", "## 私生活")
        todo.write_text(text, encoding="utf-8")
        p = self.propose()
        self.assertTrue(p["inflight_sections_missing"])
        self.assertIn("進行中の節の見出し", li.format_md(p))
        todo.write_text(TODO_TEXT, encoding="utf-8")
        p = self.propose()
        self.assertFalse(p["inflight_sections_missing"])
        self.assertNotIn("進行中の節の見出し", li.format_md(p))

    def test_layer_index_includes_closed(self):
        idx = li.layer_index(self.root, TODAY)
        self.assertEqual(idx["L-9004"]["status"], "completed")

    def test_cli_reads_only(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        buf = io.StringIO()
        cwd = os.getcwd()
        try:
            os.chdir(self.root)
            with redirect_stdout(buf):
                self.assertEqual(li.main(["--json", "--root", str(self.root), "--today", "2026-01-20"]), 0)
        finally:
            os.chdir(cwd)
        out = json.loads(buf.getvalue())
        self.assertEqual([r["scope_id"] for r in out["add"]], ["L-9002"])
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_markdown_plain_words(self):
        md = li.format_md(self.propose())
        for word in ("keep", "stale", "parked"):
            self.assertNotIn(word, md)
        self.assertIn("足す候補", md)


if __name__ == "__main__":
    unittest.main()
