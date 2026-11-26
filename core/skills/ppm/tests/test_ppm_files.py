"""ppm_files.py のテスト。データは全部合成（架空の題名・パス・ID）。"""
import io
import json
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import ppm_files as pf  # noqa: E402

TEMPLATES = HERE / "templates"


def write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.warnings = []

    def tearDown(self):
        self._tmp.cleanup()

    def cfg(self):
        return pf.load_config(self.root, warn=self.warnings.append)


class ConfigTest(Base):
    def test_no_file_gives_defaults(self):
        self.assertEqual(self.cfg(), pf.DEFAULTS)

    def test_no_ppm_section_gives_defaults(self):
        write(self.root, ".ai-plc/config.yaml", "id_allocation:\n  mode: solo\n")
        self.assertEqual(self.cfg(), pf.DEFAULTS)

    def test_partial_override_keeps_other_defaults(self):
        write(self.root, ".ai-plc/config.yaml", """
            ppm:
              todo:
                path: lists/tasks.md
                waiting_section: null
              plan:
                capacity_hours: 4.5
              sources:
                mail: auto
            """)
        c = self.cfg()
        self.assertEqual(c["todo"]["path"], "lists/tasks.md")
        self.assertIsNone(c["todo"]["waiting_section"])
        self.assertEqual(c["todo"]["inflight_sections"], ["進行中の仕事", "進行中の私生活"])
        self.assertEqual(c["plan"]["capacity_hours"], 4.5)
        self.assertEqual(c["plan"]["max_items"], 10)
        self.assertEqual(c["sources"], {"calendar": "auto", "mail": "auto"})
        self.assertEqual(pf.DEFAULTS["todo"]["path"], "todo/todo.md")  # 既定は書き換わらない

    def test_wrong_types_raise(self):
        cases = [
            "ppm: [1, 2]",
            "ppm:\n  todo: lists/tasks.md",
            "ppm:\n  todo:\n    path: 3",
            "ppm:\n  todo:\n    inflight_sections: 進行中の仕事",
            "ppm:\n  todo:\n    inflight_sections: []",
            "ppm:\n  todo:\n    work_subgroups: [1]",
            "ppm:\n  plan:\n    max_items: 0",
            "ppm:\n  plan:\n    max_items: true",
            "ppm:\n  plan:\n    capacity_hours: '6'",
            "ppm:\n  plan:\n    overflow_rule: drop",
            "ppm:\n  sources:\n    calendar: yes",
            "ppm:\n  inflight:\n    recent_days: 1.5",
        ]
        for text in cases:
            with self.subTest(text=text):
                write(self.root, ".ai-plc/config.yaml", text + "\n")
                with self.assertRaises(pf.PpmConfigError) as cm:
                    self.cfg()
                self.assertIn("ppm", str(cm.exception))

    def test_broken_yaml_raises(self):
        write(self.root, ".ai-plc/config.yaml", "ppm: [unclosed\n")
        with self.assertRaises(pf.PpmConfigError):
            self.cfg()

    def test_unknown_key_warns_and_is_ignored(self):
        write(self.root, ".ai-plc/config.yaml", "ppm:\n  colour: blue\n  todo:\n    shape: round\n")
        c = self.cfg()
        self.assertNotIn("colour", c)
        self.assertEqual(len(self.warnings), 2)

    def test_empty_lists_allowed_where_optional(self):
        write(self.root, ".ai-plc/config.yaml", "ppm:\n  todo:\n    work_subgroups: []\n    private_sections: null\n")
        c = self.cfg()
        self.assertEqual(c["todo"]["work_subgroups"], [])
        self.assertEqual(c["todo"]["private_sections"], [])

    def test_cli_config_error_exit_code(self):
        write(self.root, ".ai-plc/config.yaml", "ppm:\n  plan:\n    max_items: many\n")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(pf.main(["config", "--root", str(self.root)]), 2)
        self.assertIn("ppm.plan.max_items", err.getvalue())


class PathsTest(Base):
    def test_default_paths(self):
        c = self.cfg()
        d = date(2026, 1, 6)
        self.assertEqual(pf.todo_path(self.root, c), self.root / "todo/todo.md")
        self.assertEqual(pf.first_task_path(self.root, c), self.root / "todo/first_task.md")
        self.assertEqual(pf.daily_task_path(self.root, c), self.root / "todo/daily_task.md")
        self.assertEqual(pf.day_dir(self.root, c, d), self.root / "Flow/202601/2026-01-06")
        self.assertEqual(pf.will_do_path(self.root, c, "2026-01-06"), self.root / "Flow/202601/2026-01-06/will_do.md")
        self.assertEqual(pf.task_diary_path(self.root, c, d), self.root / "Flow/202601/2026-01-06/task_diary.md")

    def test_custom_paths(self):
        write(self.root, ".ai-plc/config.yaml", """
            ppm:
              todo: {path: lists/tasks.md}
              day_dir: days/{YYYY}/{MM}/{DD}
              will_do: {file: plan.md}
            """)
        c = self.cfg()
        self.assertEqual(pf.todo_path(self.root, c), self.root / "lists/tasks.md")
        self.assertEqual(pf.will_do_path(self.root, c, date(2026, 1, 6)), self.root / "days/2026/01/06/plan.md")

    def test_unknown_placeholder_raises(self):
        write(self.root, ".ai-plc/config.yaml", "ppm:\n  day_dir: Flow/{WEEK}\n")
        with self.assertRaises(pf.PpmConfigError):
            pf.day_dir(self.root, self.cfg(), date(2026, 1, 6))

    def test_template_order(self):
        c = self.cfg()
        self.assertEqual(pf.template_path(self.root, c, "todo"), TEMPLATES / "todo_template.md")
        own = write(self.root, "todo/templates/will_do_template.md", "# WillDo {{YYYY-MM-DD}}\n")
        self.assertEqual(pf.template_path(self.root, c, "will_do"), own)
        self.assertEqual(pf.load_template(self.root, c, "will_do", "2026-01-06"), "# WillDo 2026-01-06\n")
        write(self.root, ".ai-plc/config.yaml", "ppm:\n  will_do:\n    template: tpl/mine.md\n")
        with self.assertRaises(pf.PpmConfigError):
            pf.template_path(self.root, self.cfg(), "will_do")
        mine = write(self.root, "tpl/mine.md", "x\n")
        self.assertEqual(pf.template_path(self.root, self.cfg(), "will_do"), mine)

    def test_bundled_templates_exist(self):
        for name in pf.TEMPLATE_NAMES:
            self.assertTrue((TEMPLATES / f"{name}_template.md").is_file(), name)

    def test_missing_files_return_none(self):
        c = self.cfg()
        self.assertIsNone(pf.read_todo(self.root, c))
        self.assertIsNone(pf.read_first_task(self.root, c))
        self.assertIsNone(pf.read_daily_tasks(self.root, c))
        self.assertIsNone(pf.read_will_do(self.root, c, "2026-01-06"))
        self.assertIsNone(pf.read_task_diary(self.root, c, "2026-01-06"))
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(pf.main(["todo", "--root", str(self.root)]), 1)
        self.assertIn("todo_template.md", err.getvalue())


class TodoTemplateTest(Base):
    """既定の書式（同梱の雛形そのもの）を読む。"""

    def setUp(self):
        super().setUp()
        self.todo = pf.parse_todo((TEMPLATES / "todo_template.md").read_text(encoding="utf-8"))

    def test_inflight(self):
        titles = [(i["section"], i["subgroup"], i["group"]) for i in self.todo["inflight"]]
        self.assertEqual(titles, [("進行中の仕事", "主軸", "work"), ("進行中の仕事", "支援課題", "work"),
                                  ("進行中の私生活", None, "private")])
        self.assertTrue(self.todo["has_subgroups"])

    def test_annotations_and_notes(self):
        first, second, _ = self.todo["inflight"]
        self.assertEqual((first["layer"], first["scope"]), ("Flow/202601/2026-01-05/sample-estimator", "L-9001"))
        self.assertEqual(first["notes"][0]["date"], "2026-01-06")
        self.assertEqual((second["source"], second["candidate"]), ("Flow/202601/2026-01-05/notes.md", "weekly_report"))
        self.assertIsNone(second["layer"])
        self.assertEqual(pf.inflight_layers(self.todo), {"Flow/202601/2026-01-05/sample-estimator": "L-9001"})

    def test_waiting_misc_and_end(self):
        self.assertEqual([w["text"] for w in self.todo["waiting"]], ["備品の届く日を確かめる（1/15 ごろ）"])
        self.assertEqual([(m["title"], m["estimate_min"]) for m in self.todo["misc"]], [("玄関の電球を替える", 15)])
        self.assertIsNotNone(self.todo["end_line"])
        kinds = {s["name"]: (s["kind"], s["after_end"]) for s in self.todo["sections"]}
        self.assertEqual(kinds["未再計画（旧案件）"], ("other", True))
        self.assertEqual(kinds["いつでもいい雑務"], ("misc", True))

    def test_cli_todo(self):
        write(self.root, "todo/todo.md", (TEMPLATES / "todo_template.md").read_text(encoding="utf-8"))
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(pf.main(["todo", "--json", "--root", str(self.root)]), 0)
        self.assertEqual(len(json.loads(out.getvalue())["inflight"]), 3)


class TodoShapesTest(Base):
    def test_no_subgroups_and_no_optional_sections(self):
        todo = pf.parse_todo(textwrap.dedent("""
            # TODO
            ## 進行中の仕事
            - [ ] 見積もりツールを進める
            - [x] 借りた傘を返す
            """))
        self.assertFalse(todo["has_subgroups"])
        self.assertEqual([(i["title"], i["subgroup"], i["done"]) for i in todo["inflight"]],
                         [("見積もりツールを進める", None, False), ("借りた傘を返す", None, True)])
        self.assertEqual(len(pf.inflight_items(todo)), 1)
        self.assertEqual(len(pf.inflight_items(todo, include_done=True)), 2)
        self.assertEqual((todo["waiting"], todo["misc"], todo["end_line"]), ([], [], None))

    def test_end_marker_stops_inflight(self):
        todo = pf.parse_todo(textwrap.dedent("""
            ## 進行中の仕事
            - [ ] 前の案件
              <!-- layer: Flow/202601/2026-01-05/sample-a scope: L-9001 -->
            ## 未再計画
            ## 進行中の仕事
            - [ ] 印の後の案件
              <!-- layer: Flow/202601/2026-01-05/sample-b scope: L-9002 -->
            """))
        self.assertEqual([i["title"] for i in todo["inflight"]], ["前の案件"])
        self.assertEqual(list(pf.inflight_layers(todo)), ["Flow/202601/2026-01-05/sample-a"])

    def test_waiting_one_line_each_with_continuation(self):
        todo = pf.parse_todo(textwrap.dedent("""
            ## 待ち／要確認
            - 返事を待つ（1/20）
              続きの行
            - [ ] 箱の形でも1件
            決めごとの段落（読まない）
            - 3件目
            """))
        self.assertEqual([w["text"] for w in todo["waiting"]], ["返事を待つ（1/20）", "[ ] 箱の形でも1件", "3件目"])
        self.assertEqual(todo["waiting"][0]["lines"], ["続きの行"])

    def test_waiting_disabled(self):
        cfg = pf.default_config()
        cfg["todo"]["waiting_section"] = None
        todo = pf.parse_todo("## 待ち／要確認\n- 返事を待つ\n", cfg)
        self.assertEqual(todo["waiting"], [])

    def test_custom_headings(self):
        cfg = pf.default_config()
        cfg["todo"].update({"inflight_sections": ["Doing", "Home"], "work_subgroups": ["Main"],
                            "private_sections": ["Home"], "waiting_section": "Waiting",
                            "misc_section": "Someday chores", "end_marker": "Parked"})
        todo = pf.parse_todo(textwrap.dedent("""
            ## Doing
            ### Main
            - [ ] 見積もりツールを進める
            ### Extra
            - [ ] 表を整える
            ## 進行中の仕事
            - [ ] 既定の名前は読まない
            ## Home
            - [ ] 借りた傘を返す
            ## Waiting
            - 備品を待つ
            ## Parked
            ## Doing
            - [ ] 読まない
            ## Someday chores
            - [ ] 郵便物を出す :10
            """), cfg)
        got = [(i["title"], i["subgroup"], i["known_subgroup"], i["group"]) for i in todo["inflight"]]
        self.assertEqual(got, [("見積もりツールを進める", "Main", True, "work"), ("表を整える", "Extra", False, "work"),
                               ("借りた傘を返す", None, True, "private")])
        self.assertEqual([w["text"] for w in todo["waiting"]], ["備品を待つ"])
        self.assertEqual([m["title"] for m in todo["misc"]], ["郵便物を出す"])

    def test_heading_suffix_and_exact_names(self):
        todo = pf.parse_todo(textwrap.dedent("""
            ## 進行中の仕事（今月）
            - [ ] 当たる
            ## 進行中の仕事たち
            - [ ] 当たらない
            """))
        self.assertEqual([i["title"] for i in todo["inflight"]], ["当たる"])

    def test_notes_comments_and_item_end(self):
        todo = pf.parse_todo(textwrap.dedent("""
            ## 進行中の仕事
            - [ ] 見積もりツールを進める

              <!-- layer: Flow/202601/2026-01-05/sample-estimator scope: L-9001 -->
              <!-- 別のコメントは読まない -->
              2026-01-07: 一つ進んだ
              日付の無いメモ
            <!--
            - [ ] コメントの中の行は読まない
              <!-- layer: Flow/202601/2026-01-05/hidden scope: L-9009 -->
            -->
            ```
            - [ ] コードの中の行も読まない
            ```
            字下げの無い文で行が終わる
              2026-01-08: これはどの行にも付かない
            - [ ] 借りた傘を返す
              <!-- source: Flow/202601/2026-01-05/notes.md candidate: desk -->
              <!-- layer: Flow/202601/2026-01-05/later scope: L-9003 -->
            """))
        a, b = todo["inflight"]
        self.assertEqual(a["layer"], "Flow/202601/2026-01-05/sample-estimator")
        self.assertEqual([(n["date"], n["text"]) for n in a["notes"]],
                         [("2026-01-07", "2026-01-07: 一つ進んだ"), (None, "日付の無いメモ")])
        self.assertEqual((b["source"], b["candidate"], b["layer"], b["scope"]),
                         ("Flow/202601/2026-01-05/notes.md", "desk", "Flow/202601/2026-01-05/later", "L-9003"))

    def test_layer_without_scope(self):
        todo = pf.parse_todo("## 進行中の仕事\n- [ ] 案件\n  <!-- layer: Flow/202601/2026-01-05/sample -->\n")
        it = todo["inflight"][0]
        self.assertEqual((it["layer"], it["scope"]), ("Flow/202601/2026-01-05/sample", None))
        self.assertEqual(pf.inflight_layers(todo), {"Flow/202601/2026-01-05/sample": "Flow/202601/2026-01-05/sample"})

    def test_private_filter(self):
        todo = pf.parse_todo((TEMPLATES / "todo_template.md").read_text(encoding="utf-8"))
        self.assertEqual([i["title"] for i in pf.inflight_items(todo, group="private")], ["借りた傘を返す"])


class EstimateTest(unittest.TestCase):
    def test_split_estimate(self):
        cases = {
            "借りた傘を返す :30": ("借りた傘を返す", 30),
            "借りた傘を返す": ("借りた傘を返す", None),
            "10:30 の会議の準備 :15": ("10:30 の会議の準備", 15),
            "書類を窓口に出す :20（理由: 今日が締切）": ("書類を窓口に出す（理由: 今日が締切）", 20),
            "理由: なし": ("理由: なし", None),
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(pf.split_estimate(text), want)


class FirstAndDailyTest(Base):
    def test_first_template(self):
        r = pf.parse_first_task((TEMPLATES / "first_task_template.md").read_text(encoding="utf-8"))
        self.assertTrue(r["heading_found"])
        self.assertEqual((r["task"]["title"], r["task"]["estimate_min"]), ("見積もりツールの計算の部分を1つ通す", 60))

    def test_first_skips_done_and_other_sections(self):
        r = pf.parse_first_task(textwrap.dedent("""
            # First Task
            ## 履歴
            - [ ] 古い
            ## ⭐ 現在のFirst Task
            <!-- - [ ] コメントは読まない -->
            - [x] 終わった
            - [ ] 今日の1件 :45
            - [ ] 次の候補
            ## 履歴2
            - [ ] 読まない
            """))
        self.assertEqual(r["task"]["title"], "今日の1件")
        self.assertEqual(len(r["open"]), 2)

    def test_first_missing_heading(self):
        r = pf.parse_first_task("# First\n- [ ] 見出しの外\n")
        self.assertEqual((r["heading_found"], r["task"]), (False, None))

    def test_first_custom_heading(self):
        cfg = pf.default_config()
        cfg["first_task"]["heading"] = "Now"
        r = pf.parse_first_task("## Now\n- [ ] 借りた傘を返す :10\n", cfg)
        self.assertEqual(r["task"]["title"], "借りた傘を返す")

    def test_daily_applies(self):
        tue = date(2026, 1, 6)  # 火曜
        self.assertTrue(pf.daily_applies("daily", tue))
        self.assertTrue(pf.daily_applies("weekly:火土", tue))
        self.assertFalse(pf.daily_applies("weekly:月水金", tue))
        self.assertTrue(pf.daily_applies("monthly:6", tue))
        self.assertFalse(pf.daily_applies("monthly:31", date(2026, 2, 28)))
        self.assertFalse(pf.daily_applies(None, tue))
        self.assertTrue(pf.daily_applies("weekly:日", "2026-01-11"))

    def test_daily_template(self):
        rows = pf.parse_daily_tasks((TEMPLATES / "daily_task_template.md").read_text(encoding="utf-8"), date(2026, 1, 1))
        got = {r["title"]: (r["tag"], r["estimate_min"], r["applies"]) for r in rows}
        self.assertEqual(got["社内の掲示を見る"], ("daily", 15, True))
        self.assertEqual(got["週報を書く"], ("weekly:金", 30, False))  # 2026-01-01 は木曜
        self.assertEqual(got["共用のプリンターの用紙を足す"], ("monthly:1", 10, True))
        self.assertEqual(rows[0]["section"], "毎日")

    def test_daily_plain_and_untagged_lines(self):
        rows = pf.parse_daily_tasks("## 朝\n- 水を飲む [daily]\n- [ ] タグなし :5\n- [x] 済み [daily]\n")
        self.assertEqual([(r["title"], r["tag"], r["applies"], r["done"]) for r in rows],
                         [("水を飲む", "daily", None, False), ("タグなし", None, None, False), ("済み", "daily", None, True)])
        rows = pf.parse_daily_tasks("- [ ] タグなし\n", "2026-01-06")
        self.assertFalse(rows[0]["applies"])


class WillDoAndDiaryTest(Base):
    def test_willdo_template_is_empty_frame(self):
        text = pf.load_template(self.root, self.cfg(), "will_do", "2026-01-06")
        r = pf.parse_will_do(text)
        self.assertEqual(r["date"], "2026-01-06")
        self.assertEqual(r["sections"], {k: [] for k, _ in pf.WILLDO_SECTIONS})  # コメントの中の行は読まない
        self.assertTrue(r["retrospective"]["present"])
        self.assertEqual(r["unknown_sections"], [])
        for name in pf.RETRO_SUBSECTIONS:
            self.assertIn(name, r["retrospective"])

    def test_willdo_filled(self):
        r = pf.parse_will_do(textwrap.dedent("""
            # WillDo 2026-01-06（このリストは当日増えない）
            ## 1. First Task
            - [x] 見積もりツールの計算を通す :60
            ## 2. 差し込み（Task Diaryから）
            - [ ] 備品の申請を出す :15
            ## 3. 繰り越し（前日の未完了）
            - [ ] 週報の型を直す :30
            ## 4. TODOから（余裕枠）
            - [ ] 借りた傘を返す
            ## 5. Daily Task
            - [x] 社内の掲示を見る :15
            ---
            ## 📈 振り返り（/ppm-close が記入）
            - タスク総数: 5 / 実行: 2
            ### FUN
            - 計算が通った
            ### DONE（WillDo外）
            - [x] 急ぎの問い合わせに答えた :10
            ## メモ
            - 自由に書いた欄
            """))
        s = r["sections"]
        self.assertEqual([i["title"] for i in s["first"]], ["見積もりツールの計算を通す"])
        self.assertEqual([i["done"] for i in s["daily"]], [True])
        self.assertEqual(pf.will_do_counts(r), {"total": 5, "done": 2, "open": 3, "estimate_min": 120,
                                               "without_estimate": 1})
        self.assertEqual(pf.will_do_counts(r, include_daily=False)["total"], 4)
        self.assertEqual(r["retrospective"]["FUN"][0]["text"], "計算が通った")
        extra = r["retrospective"]["DONE（WillDo外）"][0]
        self.assertEqual((extra["text"], extra["done"], extra["estimate_min"], extra["is_task"]),
                         ("急ぎの問い合わせに答えた", True, 10, True))
        self.assertEqual(r["unknown_sections"], ["メモ"])

    def test_diary(self):
        tpl = pf.parse_task_diary(pf.load_template(self.root, self.cfg(), "task_diary", "2026-01-06"))
        self.assertEqual((tpl["date"], tpl["scheduled"], tpl["urgent"]), ("2026-01-06", [], []))
        r = pf.parse_task_diary(textwrap.dedent("""
            # Task Diary 2026-01-07
            ## 予定タスク（前日以前にこの日へ送られた差し込み）
            - [ ] 備品の申請を出す :15
            ## 緊急（当日発生・例外 — 理由必須）
            - [ ] 書類を窓口に出す :20（理由: 今日が窓口の締切）
            """))
        self.assertEqual(r["scheduled"][0]["estimate_min"], 15)
        self.assertEqual(r["urgent"][0]["reason"], "今日が窓口の締切")

    def test_read_from_day_folder(self):
        c = self.cfg()
        write(self.root, "Flow/202601/2026-01-06/will_do.md", "# WillDo 2026-01-06\n## 1. First Task\n- [ ] 借りた傘を返す :10\n")
        r = pf.read_will_do(self.root, c, date(2026, 1, 6))
        self.assertEqual(r["sections"]["first"][0]["estimate_min"], 10)
        self.assertTrue(r["path"].endswith("will_do.md"))


class PathSafetyTest(Base):
    """書き込みに使うパスはルートの中だけ。雛形の場所は読むだけなので外も可。"""

    def test_outside_paths_are_refused(self):
        cases = [
            "ppm:\n  todo:\n    path: /tmp/todo.md\n",
            "ppm:\n  todo:\n    path: ~/todo.md\n",
            "ppm:\n  todo:\n    path: ../todo.md\n",
            "ppm:\n  first_task:\n    path: lists/../../first.md\n",
            "ppm:\n  daily_task:\n    path: '..'\n",
            "ppm:\n  day_dir: ../days/{YYYY-MM-DD}\n",
            "ppm:\n  day_dir: /var/days/{YYYY-MM-DD}\n",
            "ppm:\n  will_do:\n    file: sub/will_do.md\n",
            "ppm:\n  task_diary:\n    file: ../diary.md\n",
            "ppm:\n  will_do:\n    file: '..'\n",
            "ppm:\n  will_do:\n    file: .git\n",
        ]
        for text in cases:
            with self.subTest(text=text):
                write(self.root, ".ai-plc/config.yaml", text)
                with self.assertRaises(pf.PpmConfigError):
                    self.cfg()

    def test_reserved_folders_are_refused(self):
        cases = [
            "ppm:\n  todo:\n    path: .git/todo.md\n",
            "ppm:\n  todo:\n    path: .claude/todo.md\n",
            "ppm:\n  first_task:\n    path: lists/.ai-plc/first.md\n",
            "ppm:\n  daily_task:\n    path: x/../.Git/daily.md\n",
            "ppm:\n  day_dir: .ai-plc/{YYYY-MM-DD}\n",
        ]
        for text in cases:
            with self.subTest(text=text):
                write(self.root, ".ai-plc/config.yaml", text)
                with self.assertRaises(pf.PpmConfigError):
                    self.cfg()
        with self.assertRaises(pf.PpmConfigError):
            pf.check_inside_path(".claude/skills/x.md", "todo.path")
        self.assertEqual(pf.check_inside_path("lists/.github-notes/todo.md", "todo.path"), "lists/.github-notes/todo.md")

    def test_dotdot_that_stays_inside_is_allowed(self):
        write(self.root, ".ai-plc/config.yaml", "ppm:\n  todo:\n    path: lists/../todo/list.md\n")
        c = self.cfg()
        self.assertEqual(pf.todo_path(self.root, c), self.root / "lists/../todo/list.md")

    def test_resolve_path_checks_even_without_load_config(self):
        c = pf.default_config()
        c["todo"]["path"] = "../x.md"
        with self.assertRaises(pf.PpmConfigError):
            pf.todo_path(self.root, c)
        c = pf.default_config()
        c["will_do"]["file"] = "a/b.md"
        with self.assertRaises(pf.PpmConfigError):
            pf.will_do_path(self.root, c, "2026-01-06")

    def test_templates_may_point_outside(self):
        outside = Path(self._tmp.name).parent / "shared-tpl-for-test"
        rel = "../" + outside.name + "/will_do_template.md"
        try:
            write(outside, "will_do_template.md", "# shared {{YYYY-MM-DD}}\n")
            write(self.root, ".ai-plc/config.yaml", f"ppm:\n  will_do:\n    template: {rel}\n  templates_dir: ~/no-such-dir\n")
            c = self.cfg()
            self.assertEqual(pf.load_template(self.root, c, "will_do", "2026-01-06"), "# shared 2026-01-06\n")
            self.assertEqual(pf.template_path(self.root, c, "todo"), TEMPLATES / "todo_template.md")
        finally:
            (outside / "will_do_template.md").unlink(missing_ok=True)
            outside.rmdir() if outside.exists() else None

    def test_cli_reports_outside_path(self):
        write(self.root, ".ai-plc/config.yaml", "ppm:\n  todo:\n    path: ../todo.md\n")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(pf.main(["paths", "--root", str(self.root)]), 2)
        self.assertIn("ppm.todo.path", err.getvalue())


class PrivateTextTest(Base):
    TODO = textwrap.dedent("""
        ## 進行中の仕事
        - [ ] 見積もりツールを進める
          <!-- layer: Flow/202601/2026-01-05/sample-estimator scope: L-9001 -->
        ## 進行中の私生活
        - [ ] 借りた傘を返す
          <!-- layer: Flow/202601/2026-01-05/umbrella scope: L-9007 -->
        """)

    def test_todo_text_hides_private_layer_by_default(self):
        write(self.root, "todo/todo.md", self.TODO)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(pf.main(["todo", "--root", str(self.root)]), 0)
        text = out.getvalue()
        self.assertIn("sample-estimator", text)
        self.assertIn("借りた傘を返す", text)
        self.assertNotIn("umbrella", text)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(pf.main(["todo", "--show-private", "--root", str(self.root)]), 0)
        self.assertIn("umbrella", out.getvalue())

    def test_inflight_layers_group(self):
        todo = pf.parse_todo(self.TODO)
        self.assertEqual(list(pf.inflight_layers(todo, group="work")), ["Flow/202601/2026-01-05/sample-estimator"])
        self.assertEqual(list(pf.inflight_layers(todo, group="private")), ["Flow/202601/2026-01-05/umbrella"])


class DispositionTest(unittest.TestCase):
    def test_split_disposition(self):
        cases = {
            "週報の型を直す :30 → 繰り越し": ("週報の型を直す :30", "carryover", None),
            "週報の型を直す :90 → 繰り越し: 週報の見出しを直す :30": ("週報の型を直す :90", "carryover", "週報の見出しを直す :30"),
            "週報の型を直す →TODOへ": ("週報の型を直す", "to_todo", None),
            "週報の型を直す → TODO へ": ("週報の型を直す", "to_todo", None),
            "週報の型を直す :30 → やめた": ("週報の型を直す :30", "dropped", None),
            "表を読む → 丸める → 出す": ("表を読む → 丸める → 出す", None, None),
            "表を読む → TODO へ移す手順を書く": ("表を読む → TODO へ移す手順を書く", None, None),
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(pf.split_disposition(text), want)

    def test_willdo_items_carry_marks(self):
        r = pf.parse_will_do(textwrap.dedent("""
            # WillDo 2026-01-05
            ## 3. 繰り越し（前日の未完了）
            - [ ] 週報の型を直す :90 → 繰り越し: 週報の見出しを直す :30
            - [ ] 古い表を読む :15 → やめた
            - [x] 備品の申請を出す :15
            """))
        a, b, c = r["sections"]["carryover"]
        self.assertEqual((a["title"], a["estimate_min"], a["done"]), ("週報の型を直す", 90, False))
        self.assertEqual((a["disposition"], a["carry_title"], a["carry_estimate_min"]), ("carryover", "週報の見出しを直す", 30))
        self.assertIn("→ 繰り越し", a["raw"])
        self.assertEqual((b["title"], b["disposition"], b["carry_title"]), ("古い表を読む", "dropped", None))
        self.assertIsNone(c["disposition"])
        # 印の付いた行も未完了のまま数える（実行率は 完了 ÷ 全体）
        self.assertEqual(pf.will_do_counts(r)["done"], 1)
        self.assertEqual(pf.will_do_counts(r)["total"], 3)


class CarryCandidatesTest(Base):
    """close の印と、飛ばした日の日記・WillDo を plan の候補に集める。"""

    def wd(self, day: str, body: str):
        y, m, _ = day.split("-")
        write(self.root, f"Flow/{y}{m}/{day}/will_do.md", f"# WillDo {day}\n" + textwrap.dedent(body))

    def diary(self, day: str, scheduled: str = "", urgent: str = ""):
        y, m, _ = day.split("-")
        write(self.root, f"Flow/{y}{m}/{day}/task_diary.md",
              f"# Task Diary {day}\n## 予定タスク\n{textwrap.dedent(scheduled)}\n## 緊急\n{textwrap.dedent(urgent)}\n")

    def titles(self, res, bucket):
        return [r["plan_title"] for r in res[bucket]]

    def test_after_close_no_duplicates_and_dropped_rows_stay_out(self):
        self.wd("2026-01-05", """
            ## 1. First Task
            - [x] 見積もりツールの計算を通す :60
            ## 2. 差し込み（Task Diaryから）
            - [ ] 備品の申請を出す :15 → 繰り越し
            - [x] 前の日に入った差し込み :15
            ## 3. 繰り越し（前日の未完了）
            - [ ] 週報の型を直す :30 → TODO へ
            ## 4. TODOから（余裕枠）
            - [ ] 古い表を読む :60 → やめた
            - [ ] 議事録の様式をそろえる :90 → 繰り越し: 議事録の見出しを決める :30
            ## 5. Daily Task
            - [ ] 社内の掲示を見る :15
            - [ ] 郵便物を出す :10 → 繰り越し
            """)
        # 前の日の日記: WillDo に同じ題名がある予定タスクは読まない。緊急は close の印で決まる
        self.diary("2026-01-05", scheduled="- [ ] 前の日に入った差し込み :15\n",
                   urgent="- [ ] 書類を窓口に出す :20（理由: 締切）→ 繰り越し\n- [ ] 電話を折り返す :10 → やめた\n"
                          "- [x] 済んだ緊急 :10\n")
        # 対象日の日記に、同じ題名の行が混ざっていても1回だけ
        self.diary("2026-01-06", scheduled="- [ ] 植木に水をやる :5\n- [ ] 備品の申請を出す :15\n")
        res = pf.carry_candidates(self.root, self.cfg(), "2026-01-06")
        self.assertEqual(res["last_will_do"], "2026-01-05")
        self.assertEqual(self.titles(res, "carryover"), ["備品の申請を出す", "議事録の見出しを決める", "郵便物を出す"])
        self.assertEqual(res["carryover"][1]["plan_estimate_min"], 30)
        self.assertEqual(self.titles(res, "urgent"), ["書類を窓口に出す（理由: 締切）"])
        self.assertEqual(self.titles(res, "scheduled"), ["植木に水をやる"])
        self.assertEqual(sorted(r["title"] for r in res["set_aside"]), ["古い表を読む", "週報の型を直す", "電話を折り返す"])
        every = self.titles(res, "carryover") + self.titles(res, "urgent") + self.titles(res, "scheduled")
        self.assertEqual(len(every), len(set(every)))
        self.assertNotIn("前の日に入った差し込み", every)
        self.assertNotIn("社内の掲示を見る", every)  # Daily は印が無ければ繰り越さない

    def test_skipped_close_and_skipped_days_are_picked_up(self):
        # 金曜に組んだが締めていない（印なし）。土日は WillDo なし。月曜の分を組む
        self.wd("2026-01-09", """
            ## 1. First Task
            - [ ] 見積もりツールの計算を通す :60
            ## 4. TODOから（余裕枠）
            - [x] 週報を書く :30
            """)
        self.diary("2026-01-09", urgent="- [ ] 書類を窓口に出す :20（理由: 締切）\n")
        self.diary("2026-01-10", scheduled="- [ ] 傘を返す :10\n")
        self.diary("2026-01-11", scheduled="- [ ] 電球を替える :15\n", urgent="- [ ] 宅配の荷物を受け取る :10（理由: 不在）\n")
        self.diary("2026-01-12", scheduled="- [ ] 郵便物を出す :10\n")
        res = pf.carry_candidates(self.root, self.cfg(), "2026-01-12")
        self.assertEqual(res["last_will_do"], "2026-01-09")
        self.assertEqual(self.titles(res, "carryover"), ["見積もりツールの計算を通す"])
        self.assertEqual(self.titles(res, "scheduled"), ["傘を返す", "電球を替える", "郵便物を出す"])
        self.assertEqual(self.titles(res, "urgent"), ["書類を窓口に出す（理由: 締切）", "宅配の荷物を受け取る（理由: 不在）"])
        self.assertEqual(res["diary_days"], ["2026-01-09", "2026-01-10", "2026-01-11", "2026-01-12"])

    def test_today_mode_includes_target_urgent_and_skips_urgent_already_in_willdo(self):
        self.wd("2026-01-05", """
            ## 2. 差し込み（Task Diaryから）
            - [ ] 書類を窓口に出す :20（理由: 締切）
            """)
        self.diary("2026-01-05", urgent="- [ ] 書類を窓口に出す :20（理由: 締切）\n")
        self.diary("2026-01-06", urgent="- [ ] 宅配の荷物を受け取る :10（理由: 不在）\n")
        res = pf.carry_candidates(self.root, self.cfg(), "2026-01-06")
        self.assertEqual(self.titles(res, "carryover"), ["書類を窓口に出す（理由: 締切）"])
        self.assertEqual(self.titles(res, "urgent"), [])
        res = pf.carry_candidates(self.root, self.cfg(), "2026-01-06", include_target_urgent=True)
        self.assertEqual(self.titles(res, "urgent"), ["宅配の荷物を受け取る（理由: 不在）"])

    def test_rows_added_to_last_day_diary_after_its_willdo_are_picked_up(self):
        # 前の日の WillDo を組んだ後に、その日の日記の予定タスクへ足された行（WillDo に無い）も候補に出る
        self.wd("2026-01-05", """
            ## 2. 差し込み（Task Diaryから）
            - [x] 名札を印刷する :20
            ## 4. TODOから（余裕枠）
            - [ ] アンケートの設問を見直す :30
            """)
        self.diary("2026-01-05", scheduled="- [ ] 名札を印刷する :20\n- [ ] 案内の掲示を新しくする :30\n"
                                           "- [ ] 図書館に返す日を確かめる :5 → TODO へ\n- [x] 済んだ予定 :10\n"
                                           "- [ ] アンケートの設問を見直す :30\n")
        res = pf.carry_candidates(self.root, self.cfg(), "2026-01-06")
        self.assertEqual(self.titles(res, "carryover"), ["アンケートの設問を見直す"])
        self.assertEqual(self.titles(res, "scheduled"), ["案内の掲示を新しくする"])
        self.assertEqual([(r["title"], r["from"]) for r in res["set_aside"]],
                         [("図書館に返す日を確かめる", "diary_scheduled")])
        self.assertEqual(res["scheduled"][0]["date"], "2026-01-05")

    def test_lookback_limit(self):
        self.wd("2026-01-01", "## 1. First Task\n- [ ] 古い行 :30\n")
        c = self.cfg()
        self.assertEqual(pf.find_last_will_do(self.root, c, "2026-01-10"), date(2026, 1, 1))
        self.assertIsNone(pf.find_last_will_do(self.root, c, "2026-01-10", lookback_days=5))
        self.assertIsNone(pf.find_last_will_do(self.root, c, "2026-01-01"))  # 対象日そのものは見ない
        write(self.root, ".ai-plc/config.yaml", "ppm:\n  plan:\n    lookback_days: 3\n")
        self.diary("2026-01-07", scheduled="- [ ] 傘を返す :10\n")
        res = pf.carry_candidates(self.root, self.cfg(), "2026-01-10")
        self.assertIsNone(res["last_will_do"])
        self.assertEqual(self.titles(res, "carryover"), [])
        self.assertEqual(self.titles(res, "scheduled"), ["傘を返す"])

    def test_cli_carry(self):
        self.wd("2026-01-05", "## 3. 繰り越し\n- [ ] 傘を返す :10\n")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(pf.main(["carry", "--date", "2026-01-06", "--root", str(self.root)]), 0)
        res = json.loads(out.getvalue())
        self.assertEqual([r["plan_title"] for r in res["carryover"]], ["傘を返す"])


if __name__ == "__main__":
    unittest.main()
