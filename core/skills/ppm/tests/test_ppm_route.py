"""ppm_route.py（/ppm の振り分けの手がかり）のテスト。Layer は全部合成。

    python3 -m unittest discover -s core/skills/ppm/tests
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import ppm_route as pr  # noqa: E402


def dump(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        skills = self.root / ".claude" / "skills"
        for rel in list(pr.SKILLS.values()) + ["ai-plc/01-collection", "ai-plc/02-inception",
                                               "ai-plc/03-construction", "ai-plc/04-operation", "plc-lifecycle"]:
            (skills / rel).mkdir(parents=True)
            (skills / rel / "SKILL.md").write_text("---\nname: x\ndescription: x\n---\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def layer(self, rel="Flow/202601/2026-01-05/sample", intent=None, tasks=None, backlog_extra=None):
        d = self.root / rel
        d.mkdir(parents=True, exist_ok=True)
        it = {"scope_id": "L-9001", "status": "active", "workflow_depth": "standard"}
        it.update(intent or {})
        dump(d / "intent.yaml", it)
        dump(d / "context.yaml", {"scope_id": it["scope_id"]})
        bl = {"scope_id": it["scope_id"], "tasks": tasks if tasks is not None else []}
        bl.update(backlog_extra or {})
        dump(d / "backlog.yaml", bl)
        return rel

    def route(self, *a, **kw):
        return pr.route(*a, root=self.root, **kw)

    def test_each_entry(self):
        for action, rel in pr.SKILLS.items():
            with self.subTest(action=action):
                r = self.route(action)
                self.assertEqual(r["skill_path"], f".claude/skills/{rel}/SKILL.md")
                self.assertTrue(r["advisory_only"])

    def test_only_bundled_destinations(self):
        # 行き先は、配布物の core/skills/ に実在するスキルのフォルダだけ
        bundled = {d.name for d in Path(pr.HERE).parent.iterdir() if (d / "SKILL.md").is_file()}
        self.assertLessEqual(set(pr.SKILLS.values()), bundled)

    def test_new_requires_goal(self):
        with self.assertRaises(pr.RouteError):
            self.route("new")
        r = self.route("new", goal="手順書の目次を決める")
        self.assertTrue(r["existing_layer_search_required"])
        self.assertIn("01-collection", r["skill_path"])
        with self.assertRaises(pr.RouteError):
            self.route("status", goal="x")
        with self.assertRaises(pr.RouteError):
            self.route("status", layer="Flow/x")

    def test_resume_empty_backlog(self):
        rel = self.layer()
        self.assertEqual(self.route("resume", layer=rel)["stage"], "02-inception")
        rel = self.layer(intent={"workflow_depth": "simple"})
        self.assertEqual(self.route("resume", layer=rel)["stage"], "04-operation")

    def test_resume_ready_task_by_priority(self):
        rel = self.layer(tasks=[{"id": "T002", "status": "pending", "priority": "P1"},
                                {"id": "T003", "status": "pending", "priority": "P0", "dependencies": ["T001"]},
                                {"id": "T001", "status": "in_progress", "priority": "P2"}])
        r = self.route("resume", layer=rel)
        self.assertEqual((r["stage"], r["task_id"]), ("04-operation", "T002"))
        self.assertIn("Task: T002", r["prompt"])

    def test_resume_task_without_command_runs_from_backlog(self):
        rel = self.layer(tasks=[{"id": "T001", "status": "pending"}])
        self.assertEqual(self.route("resume", layer=rel)["task_id"], "T001")

    def test_resume_missing_agent(self):
        rel = self.layer(tasks=[{"id": "T001", "status": "pending", "command": "do"}],
                         backlog_extra={"construction": {"required": True, "tasks": ["T001"]}})
        self.assertEqual(self.route("resume", layer=rel)["stage"], "03-construction")
        agents = self.root / rel / "Agents"
        agents.mkdir()
        (agents / "AGT_T001_do.md").write_text("x", encoding="utf-8")
        self.assertEqual(self.route("resume", layer=rel)["stage"], "04-operation")

    def test_resume_holds_and_audit(self):
        rel = self.layer(intent={"status": "blocked"}, tasks=[{"id": "T001", "status": "pending"}])
        self.assertEqual(self.route("resume", layer=rel)["action"], "hold")
        rel = self.layer(intent={"status": "completed"})
        r = self.route("resume", layer=rel)
        self.assertEqual(r["action"], "completed")
        self.assertIn("ppm-audit", r["skill_path"])
        self.assertIn("完了済み", r["reason"])
        rel = self.layer(tasks=[{"id": "T001", "status": "completed"}], backlog_extra={"sublayers": [{"status": "active"}]})
        self.assertEqual(self.route("resume", layer=rel)["action"], "hold")
        rel = self.layer(tasks=[{"id": "T001", "status": "blocked"}])
        self.assertEqual(self.route("resume", layer=rel)["action"], "hold")

    def test_resume_paused_cancelled_planned(self):
        for st in ("paused", "deferred"):
            with self.subTest(status=st):
                rel = self.layer(intent={"status": st}, tasks=[{"id": "T001", "status": "pending"}])
                r = self.route("resume", layer=rel)
                self.assertEqual(r["action"], "hold")
                self.assertTrue(r["owner_confirmation_required"])
                self.assertIn("止めている", r["reason"])
        for st in ("cancelled", "dropped"):
            with self.subTest(status=st):
                rel = self.layer(intent={"status": st})
                r = self.route("resume", layer=rel)
                self.assertEqual(r["action"], "reopen")
                self.assertIn("plc-lifecycle", r["skill_path"])
        rel = self.layer(intent={"status": "planned"})
        r = self.route("resume", layer=rel)
        self.assertEqual((r["action"], r["stage"]), ("confirm_start", "02-inception"))
        self.assertIn("まだ始めていない", r["reason"])
        rel = self.layer(intent={"status": "planned"}, tasks=[{"id": "T001", "status": "pending"}])
        self.assertEqual(self.route("resume", layer=rel)["task_id"], "T001")
        rel = self.layer(intent={"status": "weird"})
        with self.assertRaises(pr.RouteError):
            self.route("resume", layer=rel)

    def test_resume_skips_future_and_recurring_tasks(self):
        today = date(2026, 1, 20)
        rel = self.layer(tasks=[{"id": "T001", "status": "pending", "priority": "P0", "scheduled_for": "2026-02-02"},
                                {"id": "T002", "status": "in_progress", "priority": "P0", "recurrence": "weekly"},
                                {"id": "T003", "status": "pending", "priority": "P2", "scheduled_for": "2026-01-20"},
                                {"id": "T004", "status": "pending", "priority": "P1", "scheduled_for": "2026-W05"}])
        r = self.route("resume", layer=rel, today=today)
        self.assertEqual(r["task_id"], "T003")  # 今日の分は動かせる。先の時期・運用タスクは候補にしない
        rel = self.layer(tasks=[{"id": "T001", "status": "pending", "scheduled_for": "2026-02-02"},
                                {"id": "T002", "status": "in_progress", "recurrence": "daily"}])
        r = self.route("resume", layer=rel, today=today)
        self.assertEqual(r["action"], "hold")
        self.assertEqual(r["scheduled_task_ids"], ["T001"])
        self.assertEqual(r["recurring_task_ids"], ["T002"])
        self.assertIn("2026-02-02", r["reason"])
        rel = self.layer(tasks=[{"id": "T001", "status": "completed"},
                                {"id": "T002", "status": "in_progress", "recurrence": "daily"}])
        r = self.route("resume", layer=rel, today=today)
        self.assertEqual(r["action"], "audit")  # 運用タスクは全部済みの判定に数えない
        self.assertEqual(r["recurring_task_ids"], ["T002"])

    def test_resume_order_scheduled_first(self):
        # /04-operation の Phase 2: 時期のある（今日以前）タスクを早い順に先に、その後に時期の無いタスクを優先度→ID
        today = date(2026, 1, 20)
        tasks = [{"id": "T001", "status": "pending", "priority": "P0"},
                 {"id": "T002", "status": "pending", "priority": "P2", "scheduled_for": "2026-01-19"},
                 {"id": "T003", "status": "pending", "priority": "P1", "scheduled_for": "2026-01-15"},
                 {"id": "T004", "status": "pending", "priority": "P0", "scheduled_for": "2026-01-15"}]
        rel = self.layer(tasks=tasks)
        r = self.route("resume", layer=rel, today=today)
        self.assertEqual(r["task_id"], "T004")  # 同じ日は優先度の順
        self.assertIn("2026-01-15", r["reason"])
        rel = self.layer(tasks=[t for t in tasks if t["id"] in ("T001", "T002")])
        self.assertEqual(self.route("resume", layer=rel, today=today)["task_id"], "T002")  # P0 でも時期なしは後
        rel = self.layer(tasks=[{"id": "T002", "status": "pending", "priority": "P1"},
                                {"id": "T001", "status": "pending", "priority": "P1"},
                                {"id": "T003", "status": "pending", "priority": "P0", "scheduled_for": "2026-02-01"}])
        self.assertEqual(self.route("resume", layer=rel, today=today)["task_id"], "T001")  # 先の時期は候補にしない

    def test_planned_hold_stays_hold(self):
        rel = self.layer(intent={"status": "planned"}, tasks=[{"id": "T001", "status": "blocked"}])
        r = self.route("resume", layer=rel)
        self.assertEqual(r["action"], "hold")
        self.assertTrue(r["reason"].startswith("まだ始めていない"))
        self.assertTrue(r["owner_confirmation_required"])

    def test_resume_jev_read_as_standard(self):
        rel = self.layer(intent={"pipeline_variant": "jev"}, tasks=[{"id": "T001", "status": "pending"}])
        r = self.route("resume", layer=rel)
        self.assertEqual((r["pipeline_variant"], r["variant_read_as"]), ("jev", "standard"))

    def test_resume_ai_plc_projects_allowed(self):
        rel = self.layer(".ai-plc/projects/manual-toc", intent={"scope_id": "manual-toc"},
                         tasks=[{"id": "T001", "status": "pending"}])
        self.assertEqual(self.route("resume", layer=rel)["scope_id"], "manual-toc")

    def test_resume_rejects_outside_and_bad_data(self):
        for bad in ("Stock/x", "../outside", "Flow", "todo"):
            with self.subTest(bad=bad), self.assertRaises(pr.RouteError):
                self.route("resume", layer=bad)
        outside = Path(tempfile.mkdtemp(dir=self.tmp.name, prefix="out-"))
        (self.root / "Flow").mkdir(exist_ok=True)
        os.symlink(outside, self.root / "Flow" / "link")
        with self.assertRaises(pr.RouteError):
            self.route("resume", layer="Flow/link")
        rel = self.layer(tasks=[{"id": "T001", "status": "pending"}])
        dump(self.root / rel / "context.yaml", {"scope_id": "L-9999"})
        with self.assertRaises(pr.RouteError):
            self.route("resume", layer=rel)
        rel = self.layer("Flow/202601/2026-01-06/bad", tasks=[{"id": "T001", "status": "weird"}])
        with self.assertRaises(pr.RouteError):
            self.route("resume", layer=rel)

    def test_flow_as_link_outside_repo(self):
        real_root = Path(tempfile.mkdtemp(dir=self.tmp.name, prefix="flowstore-"))
        repo = self.root / "repo"
        repo.mkdir()
        shutil.copytree(self.root / ".claude", repo / ".claude")
        os.symlink(real_root, repo / "Flow")
        d = real_root / "202601" / "2026-01-05" / "sample"
        d.mkdir(parents=True)
        dump(d / "intent.yaml", {"scope_id": "L-9001", "status": "active", "workflow_depth": "simple"})
        dump(d / "context.yaml", {"scope_id": "L-9001"})
        dump(d / "backlog.yaml", {"scope_id": "L-9001", "tasks": [{"id": "T001", "status": "pending"}]})
        for given in ("Flow/202601/2026-01-05/sample", str(repo / "Flow/202601/2026-01-05/sample"), str(d)):
            with self.subTest(given=given):
                r = pr.route("resume", layer=given, root=repo)
                self.assertEqual(r["layer"], "Flow/202601/2026-01-05/sample")
                self.assertEqual(r["task_id"], "T001")
        # Layer の中のファイルがリンクで外を指すものは断る（JSON のエラーと終了コード 2）
        other = Path(tempfile.mkdtemp(dir=self.tmp.name, prefix="other-"))
        dump(other / "backlog.yaml", {"scope_id": "L-9001", "tasks": []})
        (d / "backlog.yaml").unlink()
        os.symlink(other / "backlog.yaml", d / "backlog.yaml")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = pr.main(["resume", "--root", str(repo), "--layer", "Flow/202601/2026-01-05/sample"])
        self.assertEqual(code, 2)
        self.assertIn("backlog.yaml", json.loads(buf.getvalue())["error"])

    def cli(self, *args):
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            code = pr.main(list(args))
        return code, buf.getvalue()

    def test_cli_error_json(self):
        code, out = self.cli("resume", "--root", str(self.root))
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(out))

    def test_cli_bad_arguments_json(self):
        for args in (["nowhere"], ["status", "--unknown"], ["resume", "--layer"]):
            with self.subTest(args=args):
                code, out = self.cli("--root", str(self.root), *args)
                self.assertEqual(code, 2)
                self.assertIn("引数が違います", json.loads(out)["error"])
        rel = self.layer(tasks=[{"id": "T001", "status": "pending"}])
        for bad in ("2026/01/20", "tomorrow", "2026-02-30"):
            with self.subTest(today=bad):
                code, out = self.cli("resume", "--root", str(self.root), "--layer", rel, "--today", bad)
                self.assertEqual(code, 2)
                self.assertIn("--today は YYYY-MM-DD で指定してください", json.loads(out)["error"])
        code, out = self.cli("resume", "--root", str(self.root), "--layer", rel, "--today", "2026-01-20")
        self.assertEqual((code, json.loads(out)["task_id"]), (0, "T001"))


if __name__ == "__main__":
    unittest.main()
