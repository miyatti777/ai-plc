"""ppm-plan の道具（scheduled_today.py・aipm_due_items.py）のテスト。データは全部合成（架空の題名・パス・ID）。

- 配布の形（core/skills/ppm-plan/ の隣に core/skills/ppm/）で関数を呼ぶテスト
- 一時フォルダに導入先と同じ形（<repo>/.claude/skills/ppm/・ppm-plan/・aipm-guided/・ai-plc/）の写しを置き、
  道具を実行して部品を見つけて動くことを確かめるテスト
- 道具は読むだけなので、実行の前後でリポジトリのファイルが1つも変わらないことも確かめる
"""
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr
from datetime import date
from unittest import mock
from pathlib import Path

sys.dont_write_bytecode = True
PLAN = Path(__file__).resolve().parents[1]          # core/skills/ppm-plan
SKILLS = PLAN.parent                                 # core/skills
sys.path.insert(0, str(PLAN))
import scheduled_today as st  # noqa: E402
import aipm_due_items as adi  # noqa: E402

PY = sys.executable
IGNORE = shutil.ignore_patterns("tests", "__pycache__", "*.pyc")
DAY = date(2026, 1, 7)  # 水曜


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


def todo_from_template(extra_main: str = "", extra_private: str = "") -> str:
    """同梱の TODO の雛形に、合成の案件の行を足した本文。"""
    text = (SKILLS / "ppm" / "templates" / "todo_template.md").read_text(encoding="utf-8")
    if extra_main:
        text = text.replace("### 主軸\n\n", "### 主軸\n\n" + textwrap.dedent(extra_main).lstrip("\n") + "\n", 1)
    if extra_private:
        text = text.replace("## 進行中の私生活\n\n", "## 進行中の私生活\n\n" + textwrap.dedent(extra_private).lstrip("\n") + "\n", 1)
    return text


EXTRA_MAIN = """
- [ ] アンケートの設問を見直す
  <!-- layer: Flow/202601/2026-01-02/survey-form scope: L-9002 -->
- [x] 案内の掲示を新しくする
  <!-- layer: Flow/202601/2026-01-03/printer-paper scope: L-9003 -->
- [ ] 外を指す注記
  <!-- layer: ../outside-layer scope: L-9004 -->
"""


def backlog_tasks():
    return {
        "Flow/202601/2026-01-05/sample-estimator": [
            {"id": "T001", "name": "計算の部分を作る", "status": "pending", "scheduled_for": "2026-01-07", "priority": "P1"},
            {"id": "T002", "name": "画面を直す", "status": "pending", "scheduled_for": "2026-01-05", "priority": "P0",
             "due": "2026-01-06"},
            {"id": "T003", "name": "まだ先の作業", "status": "pending", "scheduled_for": "2026-01-08"},
            {"id": "T004", "name": "済んだ作業", "status": "completed", "scheduled_for": "2026-01-01"},
            {"id": "T005", "name": "毎週の点検", "status": "pending", "scheduled_for": "2026-01-01", "recurrence": "weekly"},
            {"id": "T006", "name": "時期が読めない", "status": "pending", "scheduled_for": "来週のどこか"},
            {"id": "T007", "name": "週で書いた時期", "status": "in_progress", "scheduled_for": "2026-W02"},
        ],
        "Flow/202601/2026-01-02/survey-form": [
            {"id": "T001", "name": "設問の案を作る", "status": "pending", "scheduled_for": "2026-01-07", "priority": "P0"},
        ],
        # 完了の印の付いた案件の行（数えない）
        "Flow/202601/2026-01-03/printer-paper": [
            {"id": "T001", "name": "掲示の項目を決める", "status": "pending", "scheduled_for": "2026-01-01"},
        ],
    }


def make_repo(root: Path, todo_text: str | None = None) -> None:
    write(root, "todo/todo.md", todo_text if todo_text is not None else todo_from_template(EXTRA_MAIN))
    for rel, tasks in backlog_tasks().items():
        write_yaml(root, f"{rel}/backlog.yaml", {"tasks": tasks})
        write_yaml(root, f"{rel}/intent.yaml", {"scope_id": "L-9001", "status": "active"})
    # リポジトリの外（../outside-layer）にも backlog を置く（読まれないことを確かめる）
    write_yaml(root.parent, "outside-layer/backlog.yaml",
               {"tasks": [{"id": "T001", "name": "外の作業", "status": "pending", "scheduled_for": "2026-01-01"}]})


class TempRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def ctx(self):
        pf = st.load_ppm_files(self.root)
        root, cfg = pf.context(self.root)
        return pf, root, cfg


class ScheduledDateTest(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(st.scheduled_date("2026-01-07"), date(2026, 1, 7))
        self.assertEqual(st.scheduled_date("'2026-01-07T09:00:00'"), date(2026, 1, 7))
        self.assertEqual(st.scheduled_date("2026-w02"), date(2026, 1, 5))
        self.assertEqual(st.scheduled_date(date(2026, 1, 3)), date(2026, 1, 3))
        self.assertIsNone(st.scheduled_date(""))
        self.assertIsNone(st.scheduled_date("2026-13-40"))
        self.assertTrue(st.unreadable("来週"))
        self.assertFalse(st.unreadable(None))
        self.assertFalse(st.unreadable(""))


class ScheduledTodayTest(TempRepo):
    def test_collect_picks_due_open_tasks_in_order(self):
        make_repo(self.root)
        pf, root, cfg = self.ctx()
        warns = []
        rows = st.collect(root, pf.inflight_layers(pf.read_todo(root, cfg)), DAY, warn=warns.append)
        got = [(r["scope"], r["task_id"]) for r in rows]
        # 時期の早い順、同じ日は priority の順。済み・運用・先の時期・完了の印の行・外を指す注記は入らない
        self.assertEqual(got, [("L-9001", "T002"), ("L-9001", "T007"), ("L-9002", "T001"), ("L-9001", "T001")])
        t002 = rows[0]
        self.assertTrue(t002["overdue"])
        self.assertTrue(t002["due_overdue"])
        self.assertEqual(t002["layer"], "Flow/202601/2026-01-05/sample-estimator")
        self.assertEqual(len(warns), 1)
        self.assertIn("時期を読めない", warns[0])
        self.assertIn("T006", warns[0])

    def test_custom_config_paths_and_headings(self):
        write(self.root, ".ai-plc/config.yaml", """
            ppm:
              todo:
                path: lists/doing.md
                inflight_sections: [Doing]
                work_subgroups: []
                private_sections: []
                waiting_section: null
            """)
        write(self.root, "lists/doing.md", """
            # My list

            ## Doing

            - [ ] Survey form
              <!-- layer: Flow/202601/2026-01-02/survey-form scope: L-9002 -->

            ## Done later

            - [ ] Not read
              <!-- layer: Flow/202601/2026-01-05/sample-estimator scope: L-9001 -->
            """)
        for rel, tasks in backlog_tasks().items():
            write_yaml(self.root, f"{rel}/backlog.yaml", {"tasks": tasks})
        pf, root, cfg = self.ctx()
        rows = st.collect(root, pf.inflight_layers(pf.read_todo(root, cfg)), DAY, warn=lambda m: None)
        self.assertEqual([(r["scope"], r["task_id"]) for r in rows], [("L-9002", "T001")])

    def test_todo_without_sections_reads_nothing_but_does_not_fail(self):
        write(self.root, "todo/todo.md", "# TODO\n\n- [ ] 見出しの無い行\n")
        pf, root, cfg = self.ctx()
        self.assertEqual(st.collect(root, pf.inflight_layers(pf.read_todo(root, cfg)), DAY), [])

    def test_unreadable_backlog_is_skipped(self):
        make_repo(self.root)
        (self.root / "Flow/202601/2026-01-02/survey-form/backlog.yaml").write_text("tasks: [\n", encoding="utf-8")
        pf, root, cfg = self.ctx()
        rows = st.collect(root, pf.inflight_layers(pf.read_todo(root, cfg)), DAY, warn=lambda m: None)
        self.assertNotIn("L-9002", {r["scope"] for r in rows})

    def test_layer_dir_refuses_outside(self):
        self.assertIsNone(st.layer_dir(self.root, "../x"))
        self.assertIsNone(st.layer_dir(self.root, "/etc"))
        self.assertEqual(st.layer_dir(self.root, "Flow/a"), (self.root / "Flow/a").resolve())


class AipmSelectionTest(unittest.TestCase):
    def test_has_sheets(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            self.assertTrue(adi.has_sheets({"addons": [{"addon_id": "aipm"}], "aipm": {"registers": True}}, folder))
            self.assertTrue(adi.has_sheets({"work_style": "aipm", "aipm": {"registers": True}}, folder))
            self.assertFalse(adi.has_sheets({"addons": [{"addon_id": "aipm"}]}, folder))
            self.assertFalse(adi.has_sheets({"addons": [{"addon_id": "aipm-light"}]}, folder))   # 箱を作る前
            write(folder, "Sheets/format_contract.yaml", "x: 1\n")
            self.assertTrue(adi.has_sheets({"addons": [{"addon_id": "aipm-light"}]}, folder))
            self.assertFalse(adi.has_sheets({"goal": "AIPM を選んでいない"}, folder))
            self.assertFalse(adi.has_sheets(None, folder))


class FakeOps:
    """ops の代わり（check・_files・today_pick の形だけ）。"""

    def __init__(self, route="selected"):
        self.route = route

    def check(self, folder):
        return {"route": self.route}

    def _files(self, folder):
        return {}, {}, {"todo": folder / "Sheets" / "todo.yaml"}

    def today_pick(self, files, inp):
        return {"candidates": [
            {"reason": "期限を過ぎた ToDo", "items": [{"id": "D1", "title": "見積を送る", "due": "2026-01-05"}]},
            {"reason": "進行中の ToDo", "items": [{"id": "D2", "title": "出さない箱"}]},
        ]}


class AipmDueItemsUnitTest(TempRepo):
    def test_no_aipm_layer_gives_nothing(self):
        make_repo(self.root)
        pf, root, cfg = self.ctx()
        rows, unreadable = adi.due_items(root, pf.inflight_layers(pf.read_todo(root, cfg)), DAY, FakeOps(), st.layer_dir)
        self.assertEqual((rows, unreadable), ([], []))
        self.assertEqual(adi.not_in_todo(root, {}), [])

    def test_only_two_buckets_and_unreadable_count(self):
        make_repo(self.root)
        write_yaml(self.root, "Flow/202601/2026-01-02/survey-form/intent.yaml",
                   {"scope_id": "L-9002", "status": "active", "addons": [{"addon_id": "aipm"}], "aipm": {"registers": True}})
        pf, root, cfg = self.ctx()
        listed = pf.inflight_layers(pf.read_todo(root, cfg))
        rows, unreadable = adi.due_items(root, listed, DAY, FakeOps(), st.layer_dir)
        self.assertEqual([r["scope"] for r in rows], ["L-9002"])
        self.assertEqual([c["reason"] for c in rows[0]["candidates"]], ["期限を過ぎた ToDo"])
        rows, unreadable = adi.due_items(root, listed, DAY, FakeOps(route="held"), st.layer_dir)
        self.assertEqual((rows, unreadable), ([], ["L-9002"]))

    def test_not_in_todo_counts_open_layers_only(self):
        make_repo(self.root)
        aipm = {"addons": [{"addon_id": "aipm"}], "aipm": {"registers": True}}
        write_yaml(self.root, "Flow/202601/2026-01-04/unlisted/intent.yaml", {"scope_id": "L-9005", "status": "active", **aipm})
        write_yaml(self.root, "Flow/202601/2026-01-04/closed/intent.yaml", {"scope_id": "L-9006", "status": "completed", **aipm})
        write_yaml(self.root, "Flow/202601/2026-01-02/survey-form/intent.yaml", {"scope_id": "L-9002", "status": "active", **aipm})
        pf, root, cfg = self.ctx()
        listed = pf.inflight_layers(pf.read_todo(root, cfg))
        self.assertEqual(adi.not_in_todo(root, listed), ["L-9005"])


class PrivateRowsTest(TempRepo):
    """私生活の節の行の案件は、既定では scope・Layer・Task の名前を出さない。"""

    PRIVATE = """
    - [ ] 名札を印刷する
      <!-- layer: Flow/202601/2026-01-04/name-tags scope: L-9008 -->
    """

    def setUp(self):
        super().setUp()
        make_repo(self.root, todo_from_template(EXTRA_MAIN, self.PRIVATE))
        write_yaml(self.root, "Flow/202601/2026-01-04/name-tags/backlog.yaml", {"tasks": [
            {"id": "T001", "name": "版の形を選ぶ", "status": "pending", "scheduled_for": "2026-01-06"},
            {"id": "T002", "name": "紙を注文する", "status": "pending", "scheduled_for": "2026-01-07"},
        ]})
        write_yaml(self.root, "Flow/202601/2026-01-04/name-tags/intent.yaml",
                   {"scope_id": "L-9008", "status": "active", "addons": [{"addon_id": "aipm"}], "aipm": {"registers": True}})

    def run_main(self, tool, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", out), redirect_stderr(err):
            code = tool.main(["--root", str(self.root), "--date", DAY.isoformat(), *args])
        self.assertEqual(code, 0, err.getvalue())
        return out.getvalue()

    def test_scheduled_today_hides_private_rows(self):
        text = self.run_main(st)
        self.assertIn("私生活の案件（名前は伏せています", text)
        self.assertIn(": 2 件", text)
        for word in ("L-9008", "name-tags", "版の形を選ぶ", "紙を注文する"):
            self.assertNotIn(word, text)
        rows = json.loads(self.run_main(st, "--json"))
        hidden = [r for r in rows if r.get("private")]
        self.assertEqual(hidden, [{"private": True}, {"private": True}])
        self.assertIn(("L-9002", "T001"), [(r.get("scope"), r.get("task_id")) for r in rows])
        shown = json.loads(self.run_main(st, "--json", "--show-private"))
        self.assertEqual([(r["scope"], r["task_id"]) for r in shown if r.get("private")],
                         [("L-9008", "T001"), ("L-9008", "T002")])
        self.assertIn("版の形を選ぶ", self.run_main(st, "--show-private"))

    def test_unreadable_date_warning_hides_private_task(self):
        write_yaml(self.root, "Flow/202601/2026-01-04/name-tags/backlog.yaml", {"tasks": [
            {"id": "T007", "name": "版の形を選ぶ", "status": "pending", "scheduled_for": "1/5ごろ"},
        ]})
        err = io.StringIO()
        with mock.patch("sys.stdout", io.StringIO()), redirect_stderr(err):
            self.assertEqual(st.main(["--root", str(self.root), "--date", DAY.isoformat(), "--json"]), 0)
        for word in ("L-9008", "T007", "1/5ごろ"):
            self.assertNotIn(word, err.getvalue())
        self.assertIn("1 件", err.getvalue())
        err = io.StringIO()
        with mock.patch("sys.stdout", io.StringIO()), redirect_stderr(err):
            st.main(["--root", str(self.root), "--date", DAY.isoformat(), "--show-private"])
        self.assertIn("L-9008 T007", err.getvalue())

    def test_aipm_due_items_hides_private_layers(self):
        pf, root, cfg = self.ctx()
        todo = pf.read_todo(root, cfg)
        rows, _ = adi.due_items(root, pf.inflight_layers(todo), DAY, FakeOps(), st.layer_dir)
        self.assertEqual([r["scope"] for r in rows], ["L-9008"])
        self.assertEqual(adi.hide_private(rows, st.private_layers(todo, pf)), [{"private": True, "count": 1}])
        shown = adi.hide_private(rows, st.private_layers(todo, pf), show_private=True)
        self.assertEqual((shown[0]["scope"], shown[0]["private"]), ("L-9008", True))
        with mock.patch.object(adi, "pm_ops", return_value=FakeOps()):
            text = self.run_main(adi)
            self.assertIn("私生活の案件（名前は伏せています", text)
            for word in ("L-9008", "name-tags", "見積を送る"):
                self.assertNotIn(word, text)
            res = json.loads(self.run_main(adi, "--json"))
            self.assertEqual(res["layers"], [{"private": True, "count": 1}])
            self.assertIn("L-9008", self.run_main(adi, "--show-private"))

    def test_work_rows_win_when_same_layer_is_in_both(self):
        pf, root, cfg = self.ctx()
        todo = pf.parse_todo(textwrap.dedent("""
            ## 進行中の仕事
            - [ ] 仕事の行
              <!-- layer: Flow/202601/2026-01-04/name-tags scope: L-9008 -->
            ## 進行中の私生活
            - [ ] 私生活の行
              <!-- layer: Flow/202601/2026-01-04/name-tags scope: L-9008 -->
            """), cfg)
        self.assertEqual(st.private_layers(todo, pf), set())


class InstalledLayoutTest(unittest.TestCase):
    """導入先と同じ形の写しで、道具を実行する。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "repo"
        skills = cls.root / ".claude" / "skills"
        for name in ("ppm", "ppm-plan", "aipm-guided", "ai-plc"):
            shutil.copytree(SKILLS / name, skills / name, ignore=IGNORE)
        make_repo(cls.root)
        # AIPM ライトモードの箱を持つ合成の Layer（aipm-guided の package.py で作る）
        cls.light = "Flow/202601/2026-01-02/survey-form"
        layer = cls.root / cls.light
        write_yaml(cls.root, f"{cls.light}/intent.yaml", {
            "scope_id": "L-9002", "scope_name": "survey-form", "status": "active", "owner": "user",
            "goal": {"description": "合成の Layer"},
            "addons": [{"addon_id": "aipm-light", "source": "bundled", "addon_version": "0.1",
                        "selection_ref": "Context/aipm_recommendation/default_method.json"}]})
        write(cls.root, f"{cls.light}/Context/aipm_recommendation/default_method.json",
              json.dumps({"kind": "default_on_no_answer", "choice": "aipm-light"}))
        (layer / "Documents").mkdir(exist_ok=True)
        out = subprocess.run([PY, "-B", str(skills / "aipm-guided" / "package.py"), "init", "--layer", str(layer),
                              "--light", "--brief"], capture_output=True, text=True, cwd=cls.root)
        if out.returncode != 0:
            raise AssertionError(out.stdout + out.stderr)
        write_yaml(cls.root, f"{cls.light}/Sheets/todo.yaml", {"todo": [
            {"id": "D1", "title": "見積を送る", "status": "todo", "due": "2026-01-05"},
            {"id": "D2", "title": "まだ先の ToDo", "status": "todo", "due": "2026-02-01"},
            {"id": "D3", "title": "済んだ ToDo", "status": "done", "due": "2026-01-01"},
        ]})

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_tool(self, name, *args):
        before = tree_digest(self.root)
        out = subprocess.run([PY, "-B", str(self.root / ".claude/skills/ppm-plan" / name), *args],
                             capture_output=True, text=True, cwd=self.root)
        self.assertEqual(tree_digest(self.root), before, "道具がファイルを変えた")
        return out

    def test_scheduled_today_runs_from_installed_copy(self):
        out = self.run_tool("scheduled_today.py", "--date", DAY.isoformat(), "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        rows = json.loads(out.stdout)
        self.assertEqual([(r["scope"], r["task_id"]) for r in rows],
                         [("L-9001", "T002"), ("L-9001", "T007"), ("L-9002", "T001"), ("L-9001", "T001")])
        text = self.run_tool("scheduled_today.py", "--date", DAY.isoformat())
        self.assertIn("実行時期の Task", text.stdout)

    def test_aipm_due_items_with_real_ops(self):
        out = self.run_tool("aipm_due_items.py", "--date", DAY.isoformat(), "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        res = json.loads(out.stdout)
        self.assertEqual(res["unreadable"], 0, res)
        self.assertEqual([r["scope"] for r in res["layers"]], ["L-9002"])
        items = [i["id"] for c in res["layers"][0]["candidates"] for i in c["items"]]
        self.assertEqual(items, ["D1"])
        text = self.run_tool("aipm_due_items.py", "--date", DAY.isoformat())
        self.assertIn("D1 見積を送る", text.stdout)

    def test_missing_todo_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            other = Path(d)
            out = subprocess.run([PY, "-B", str(self.root / ".claude/skills/ppm-plan/scheduled_today.py"),
                                  "--root", str(other), "--json"], capture_output=True, text=True, cwd=other)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(out.stdout), [])
            self.assertIn("スキップ", out.stderr)

    def test_bad_config_stops_with_error(self):
        with tempfile.TemporaryDirectory() as d:
            other = Path(d)
            write(other, ".ai-plc/config.yaml", "ppm:\n  todo:\n    inflight_sections: 進行中の仕事\n")
            out = subprocess.run([PY, "-B", str(self.root / ".claude/skills/ppm-plan/scheduled_today.py"),
                                  "--root", str(other)], capture_output=True, text=True, cwd=other)
            self.assertEqual(out.returncode, 2)
            self.assertIn("inflight_sections", out.stderr)


class YamlMissingTest(unittest.TestCase):
    def test_tools_stop_with_message_and_exit_code(self):
        for tool in (st, adi):
            with self.subTest(tool=tool.__name__):
                err = io.StringIO()
                with mock.patch.dict(sys.modules, {"yaml": None}), redirect_stderr(err):
                    self.assertEqual(tool.main(["--date", DAY.isoformat()]), 2)
                self.assertIn("PyYAML", err.getvalue())


class DistributionLayoutTest(unittest.TestCase):
    def test_finds_ppm_files_beside_in_core(self):
        pf = st.load_ppm_files()
        self.assertTrue(Path(pf.__file__).resolve().samefile(SKILLS / "ppm" / "ppm_files.py"))


if __name__ == "__main__":
    unittest.main()
