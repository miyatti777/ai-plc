"""BacklogLive のテスト（仮 Layer を一時フォルダに作って検証する）。

実行: python3 -m unittest discover -s tools/BacklogLive/tests
"""
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

BACKLOG = """\
scope_id: L-TEST
tasks:
  - {id: T001, name: 土台, status: completed, priority: P0, acceptance_criteria: [a, b]}
  - {id: T002, name: 画面, status: pending, priority: P1, dependencies: [T001], acceptance_criteria: [a]}
  - {id: T003, name: 追従, status: pending, priority: P0, dependencies: [T001]}
  - {id: T004, name: 後続, status: pending, priority: P0, dependencies: [T002]}
  - {id: T005, name: 止まり, status: blocked, priority: P2}
  - {id: T006, name: 先送り, status: deferred, priority: P2}
"""
INTENT = """\
scope_id: L-TEST
display_name: テスト用Layer
goal: {description: 仮のゴール}
"""


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    # mtime の分解能に依存せず変化を検出させる
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


class SummarizeTest(unittest.TestCase):
    def setUp(self):
        import yaml
        self.state = server.summarize(yaml.safe_load(BACKLOG), yaml.safe_load(INTENT))

    def test_counts_and_percent(self):
        s = self.state
        self.assertEqual(s["counts"], {"done": 1, "in_progress": 0, "ready": 2, "waiting": 1,
                                       "blocked": 1, "excluded": 1})
        self.assertEqual((s["total"], s["target"], s["done"], s["percent"]), (6, 5, 1, 20))
        self.assertEqual(s["name"], "テスト用Layer")
        self.assertEqual(s["goal"], "仮のゴール")

    def test_current_is_highest_priority_ready(self):
        self.assertEqual(self.state["current"], "T003")  # P0 の ready が P1 より先
        self.assertEqual(self.state["current_reason"], "次に実行できるタスク")

    def test_in_progress_wins(self):
        import yaml
        b = yaml.safe_load(BACKLOG)
        b["tasks"][1]["status"] = "in_progress"
        s = server.summarize(b, None)
        self.assertEqual((s["current"], s["current_reason"]), ("T002", "進行中"))
        t4 = next(t for t in s["tasks"] if t["id"] == "T004")
        self.assertEqual((t4["category"], t4["open_dependencies"]), ("waiting", ["T002"]))

    def test_task_detail(self):
        t2 = next(t for t in self.state["tasks"] if t["id"] == "T002")
        self.assertEqual(t2["ac_count"], 1)
        self.assertEqual(t2["dependencies"], [{"id": "T001", "status": "completed"}])

    def test_dependents_list_tasks_waiting_on_it(self):
        """詳細の「この Task を待っている Task」"""
        t1 = next(t for t in self.state["tasks"] if t["id"] == "T001")
        self.assertEqual(t1["dependents"], [{"id": "T002", "status": "pending"}, {"id": "T003", "status": "pending"}])
        t5 = next(t for t in self.state["tasks"] if t["id"] == "T005")
        self.assertEqual(t5["dependents"], [])

    def test_detail_fields(self):
        """詳細に出す項目。無い項目は返さず、list・dict は文字列の list、長い値は切る"""
        long = "あ" * 2500
        b = {"tasks": [
            {"id": "T001", "name": "x", "status": "pending", "description": "<b>説明</b>",
             "output": ["a.py", "b.md"], "result": {"件数": 3, "メモ": "ok"}, "guardrails": long,
             "estimated_hours": 2, "owner": "", "acceptance_criteria": [long]},
            {"id": "T002", "name": "y", "status": "pending"},
        ]}
        s = server.summarize(b, None)
        d1 = s["tasks"][0]["detail"]
        self.assertEqual(d1["description"], "<b>説明</b>")  # 画面で文字として入れる（textContent）。サーバは手を加えない
        self.assertEqual(d1["output"], ["a.py", "b.md"])
        self.assertEqual(d1["result"], ["件数: 3", "メモ: ok"])
        self.assertEqual(d1["estimated_hours"], "2")
        self.assertNotIn("owner", d1)  # 空の値は返さない
        self.assertEqual(len(d1["guardrails"]), server.DETAIL_MAX_CHARS + len("…（以下略）"))
        self.assertTrue(s["tasks"][0]["acceptance_criteria"][0].endswith("…（以下略）"))
        self.assertEqual(s["tasks"][1]["detail"], {})

    def test_detail_list_of_dicts_is_readable(self):
        b = {"tasks": [{"id": "T001", "status": "pending", "output": [{"path": "a.py", "kind": "code"}, "b.md"]}]}
        out = server.summarize(b, None)["tasks"][0]["detail"]["output"]
        self.assertEqual(out, ["path: a.py ／ kind: code", "b.md"])

    def test_detail_runs_newest_first_and_capped(self):
        """実行の記録は新しい順・上限つき・件数つき"""
        runs = [{"date": f"2026-10-{d:02d}", "summary": f"回{d}", "output": "a.md", "checked_ac": ["x", "y"]} for d in range(1, 32)]
        runs.append({"date": "読めない", "summary": "?"})
        b = {"tasks": [{"id": "T001", "status": "in_progress", "recurrence": "weekly", "runs": runs,
                        "retired_at": "2026-11-01", "retired_reason": "Goal 達成"}]}
        d = server.summarize(b, None, today=server.date(2026, 11, 2))["tasks"][0]["detail"]
        self.assertEqual(d["runs_total"], 32)
        self.assertEqual(len(d["runs"]), server.DETAIL_MAX_RUNS)
        self.assertEqual(d["runs"][0], {"date": "2026-10-31", "summary": "回31", "output": "a.md", "checked_ac": ["x", "y"]})
        self.assertEqual((d["retired_at"], d["retired_reason"]), ("2026-11-01", "Goal 達成"))

    def test_last_run_any_ignores_future_and_unreadable_runs(self):
        """前回回した日は今日以前の読める日付だけ。per_meeting にも出す"""
        today = server.date(2026, 10, 29)
        b = {"tasks": [
            {"id": "T001", "status": "in_progress", "recurrence": "daily", "runs": [{"date": "2026-12-01"}, {"date": "読めない"}]},
            {"id": "T002", "status": "in_progress", "recurrence": "per_meeting", "runs": [{"date": "2026-10-20"}, {"date": "2026-10-26"}]},
            {"id": "T003", "status": "pending", "runs": [{"date": "2026-10-20"}]},
        ]}
        ts = server.summarize(b, None, today=today)["tasks"]
        self.assertEqual((ts[0]["last_run_any"], ts[0]["run_due"]), (None, True))
        self.assertEqual(ts[1]["last_run_any"], "2026-10-26")
        self.assertIsNone(ts[2]["last_run_any"])  # 運用タスクでなければ出さない

    def test_detail_runs_same_date_later_written_first(self):
        b = {"tasks": [{"id": "T001", "status": "in_progress", "recurrence": "weekly",
                        "runs": [{"date": "2026-10-26", "summary": "1回目"}, {"date": "2026-10-26", "summary": "2回目"}]}]}
        runs = server.summarize(b, None)["tasks"][0]["detail"]["runs"]
        self.assertEqual([r["summary"] for r in runs], ["2回目", "1回目"])

    def test_detail_schedule_history_keeps_newest(self):
        hist = [{"date": f"d{i}", "from": "a", "to": "b"} for i in range(60)]
        d = server.summarize({"tasks": [{"id": "T001", "status": "pending", "schedule_history": hist}]}, None)["tasks"][0]["detail"]
        self.assertEqual((d["schedule_history_total"], len(d["schedule_history"]), d["schedule_history"][-1]["date"]),
                         (60, server.DETAIL_MAX_ITEMS, "d59"))

    def test_agenda_buckets_weeks_and_hidden(self):
        """予定は日付順・今日より前／今日（今週）／この先・読めない値は別・完了は件数だけ・運用は入れない"""
        today = server.date(2026, 10, 29)  # 木曜。2026-W44 は 10/26〜11/1
        b = {"tasks": [
            {"id": "T001", "status": "pending", "scheduled_for": "2026-11-05", "due": "2026-10-20"},
            {"id": "T002", "status": "pending", "scheduled_for": "2026-W44"},
            {"id": "T003", "status": "pending", "scheduled_for": "2026-10-29"},
            {"id": "T004", "status": "completed", "due": "2026-10-01"},
            {"id": "T005", "status": "pending", "due": "来週"},
            {"id": "T006", "status": "in_progress", "recurrence": "weekly", "scheduled_for": "2026-11-02"},
            {"id": "T007", "status": "pending"},
        ]}
        s = server.summarize(b, None, today=today)
        ag = s["agenda"]
        self.assertEqual([(e["id"], e["kind"], e["bucket"]) for e in ag["entries"]],
                         [("T001", "due", "past"), ("T002", "scheduled", "today"), ("T003", "scheduled", "today"),
                          ("T001", "scheduled", "future")])
        self.assertTrue(ag["entries"][0]["overdue"])
        self.assertTrue(ag["entries"][1]["week"])
        self.assertEqual(ag["invalid"], [{"id": "T005", "order": 4, "kind": "due", "raw": "来週"}])
        self.assertEqual(ag["hidden_done"], 1)
        self.assertTrue(s["has_ops_tab"])

    def test_week_spec_is_read_the_same_as_scheduled(self):
        """週の判定は _scheduled と同じ読み方（引用符・空白・小文字の w）"""
        for v in ("2026-W44", "' 2026-w44 '", " 2026-W44 "):
            self.assertTrue(server._is_week(v), v)
        for v in ("2026-10-26", None, server.date(2026, 10, 26), "W44"):
            self.assertFalse(server._is_week(v), v)

    def test_no_ops_tab_without_recurrence_or_dates(self):
        s = server.summarize({"tasks": [{"id": "T001", "status": "pending"}, {"id": "T002", "status": "completed"}]}, None)
        self.assertFalse(s["has_ops_tab"])
        self.assertEqual(s["agenda"], {"entries": [], "invalid": [], "hidden_done": 0})

    def test_ops_tab_only_when_there_is_something_to_see(self):
        """閉じていない運用タスクか、まだ終わっていない Task の日付があるときだけタブを出す"""
        today = server.date(2026, 10, 30)
        tab = lambda tasks: server.summarize({"tasks": tasks}, None, today=today)["has_ops_tab"]
        # 出ない: 閉じた運用タスクだけ／除外の運用タスクだけ／完了・除外の Task の日付だけ
        self.assertFalse(tab([{"id": "T001", "status": "in_progress", "recurrence": "per_meeting", "retired_at": "2026-10-01"}]))
        self.assertFalse(tab([{"id": "T001", "status": "cancelled", "recurrence": "weekly"}]))
        self.assertFalse(tab([{"id": "T001", "status": "completed", "due": "2026-10-01"},
                              {"id": "T002", "status": "deferred", "scheduled_for": "2026-11-01"},
                              {"id": "T003", "status": "pending"}]))
        # 出る: 閉じていない運用タスク／まだ終わっていない Task の日付／読めない日付
        self.assertTrue(tab([{"id": "T001", "status": "in_progress", "recurrence": "weekly"}]))
        self.assertTrue(tab([{"id": "T001", "status": "pending", "due": "2026-11-05"}]))
        self.assertTrue(tab([{"id": "T001", "status": "blocked", "scheduled_for": "来月"}]))
        # 運用タスクの scheduled_for が先の日でも、閉じていなければ出る。completed の運用タスクだけなら出ない
        self.assertTrue(tab([{"id": "T001", "status": "in_progress", "recurrence": "weekly", "scheduled_for": "2026-11-20"}]))
        self.assertFalse(tab([{"id": "T001", "status": "completed", "recurrence": "weekly"}]))
        # タブが無くても流れの図の外した件数は数える（画面はボタンではなく文だけを出す）
        s0 = server.summarize({"tasks": [{"id": "T001", "status": "in_progress", "recurrence": "daily", "retired_at": "2026-10-01"},
                                         {"id": "T002", "status": "pending"}]}, None, today=today)
        self.assertEqual((s0["has_ops_tab"], s0["flow"]["hidden_recurring"]), (False, 1))
        # 閉じた運用タスクだけの Layer は「運用中」と出さない（stage の値は operating のまま。P3-1）
        s1 = server.summarize({"tasks": [{"id": "T001", "status": "in_progress", "recurrence": "daily", "retired_at": "2026-10-01"}]}, None, today=today)
        self.assertEqual((s1["stage"], s1["stage_label"]), ("operating", "運用タスクはすべて閉じています（1件）"))
        # 出るときは、閉じた運用タスクと完了の日付の件数も今までどおり返す（画面の運用の欄と一行）
        s = server.summarize({"tasks": [
            {"id": "T001", "status": "in_progress", "recurrence": "weekly"},
            {"id": "T002", "status": "in_progress", "recurrence": "daily", "retired_at": "2026-10-01"},
            {"id": "T003", "status": "completed", "due": "2026-10-01"}]}, None, today=today)
        self.assertTrue(s["has_ops_tab"])
        self.assertEqual(sum(t["recurring"] for t in s["tasks"]), 2)
        self.assertEqual(s["agenda"]["hidden_done"], 1)

    def test_detail_schedule_history(self):
        b = {"tasks": [{"id": "T001", "status": "pending", "scheduled_for": "2027-05-01",
                        "schedule_history": [{"date": "2026-10-23", "from": None, "to": "2027-05-01", "reason": "満了待ち"}, "壊れた行"]},
                       {"id": "T002", "status": "pending", "runs": "壊れた値"}]}
        ts = server.summarize(b, None)["tasks"]
        self.assertEqual(ts[0]["detail"]["schedule_history"], [{"date": "2026-10-23", "from": "", "to": "2027-05-01", "reason": "満了待ち"}])
        self.assertNotIn("runs", ts[1]["detail"])
        self.assertNotIn("schedule_history", ts[1]["detail"])

    def test_detail_list_is_capped(self):
        b = {"tasks": [{"id": "T001", "status": "pending", "output": [f"f{i}" for i in range(60)]}]}
        out = server.summarize(b, None)["tasks"][0]["detail"]["output"]
        self.assertEqual(len(out), server.DETAIL_MAX_ITEMS + 1)
        self.assertEqual(out[-1], "…ほか 10 件")

    def test_recurring_task_is_outside_the_denominator(self):
        """a recurring operation task is not counted in target and is never the current task."""
        b = {"tasks": [{"id": "T001", "status": "completed"},
                       {"id": "T002", "status": "in_progress", "recurrence": "weekly"},
                       {"id": "T003", "status": "pending"}]}
        s = server.summarize(b, None)
        self.assertEqual((s["target"], s["recurring"], s["percent"], s["current"]), (2, 1, 50, "T003"))
        b["tasks"][2]["status"] = "completed"
        s = server.summarize(b, None)
        self.assertEqual((s["target"], s["percent"], s["current"]), (2, 100, None))
        self.assertNotEqual(s["stage"], "operation")

    def test_scheduled_task_waits_and_orders_first(self):
        """a task whose date is later is waiting; dated tasks (today or earlier) come before undated ones."""
        from datetime import date
        today = date(2026, 10, 21)
        b = {"tasks": [{"id": "T001", "status": "pending", "priority": "P0"},
                       {"id": "T002", "status": "pending", "priority": "P2", "scheduled_for": "2026-10-20"},
                       {"id": "T003", "status": "pending", "priority": "P0", "scheduled_for": "2026-W44"}]}
        s = server.summarize(b, None, today=today)
        by = {t["id"]: t for t in s["tasks"]}
        self.assertEqual((by["T003"]["category"], by["T003"]["waiting_for_schedule"], by["T003"]["scheduled_for"]),
                         ("waiting", True, "2026-10-26"))
        self.assertEqual(s["current"], "T002")
        s = server.summarize(b, None, today=date(2026, 10, 26))
        self.assertEqual(s["current"], "T002")  # both dated: the earlier date first
        b["tasks"][1]["status"] = "completed"
        self.assertEqual(server.summarize(b, None, today=date(2026, 10, 26))["current"], "T003")
        # a datetime value and an in-progress task with a later date 
        from datetime import datetime
        b2 = {"tasks": [{"id": "A", "status": "in_progress", "priority": "P0", "scheduled_for": "2026-11-30"},
                        {"id": "B", "status": "in_progress", "priority": "P1"},
                        {"id": "C", "status": "pending", "scheduled_for": datetime(2026, 10, 26, 9, 0)}]}
        s = server.summarize(b2, None, today=today)
        self.assertEqual(s["current"], "A")  # a later date does not come first, but does not push it back either
        self.assertEqual({t["id"]: t["category"] for t in s["tasks"]}["C"], "waiting")

    def test_schedule_wait_stage(self):
        """every open normal task waits for a later date -> stage schedule_wait with the earliest date."""
        from datetime import date
        today = date(2026, 10, 21)
        b = {"tasks": [{"id": "T1", "status": "completed"},
                       {"id": "T2", "status": "pending", "scheduled_for": "2026-11-02"},
                       {"id": "T3", "status": "pending", "scheduled_for": "2026-W44"},
                       {"id": "R", "status": "in_progress", "recurrence": "weekly"}]}
        s = server.summarize(b, None, today=today)
        self.assertEqual((s["stage"], s["stage_label"]), ("schedule_wait", "実行時期待ち（次 10/26）"))
        self.assertIsNone(s["current"])
        b["tasks"].append({"id": "T4", "status": "pending", "scheduled_for": "2026-10-21"})  # a date of today
        self.assertEqual(server.summarize(b, None, today=today)["stage"], "operation")
        b["tasks"][-1] = {"id": "T4", "status": "blocked", "scheduled_for": "2026-11-30"}   # blocked is not waiting
        self.assertEqual(server.summarize(b, None, today=today)["stage"], "operation")

    def test_done_or_running_task_is_not_waiting_for_schedule(self):
        """a task finished early or running is not shown as waiting for its date."""
        from datetime import date
        b = {"tasks": [{"id": "T1", "status": "completed", "scheduled_for": "2026-11-02"},
                       {"id": "T2", "status": "in_progress", "scheduled_for": "2026-11-02"},
                       {"id": "T3", "status": "pending", "scheduled_for": "2026-11-02"}]}
        s = server.summarize(b, None, today=date(2026, 10, 21))
        flags = {t["id"]: t["waiting_for_schedule"] for t in s["tasks"]}
        self.assertEqual(flags, {"T1": False, "T2": False, "T3": True})

    def test_schedule_reader_table_and_unreadable_flag(self):
        """the same value table as the status audit; an unreadable date is kept with a flag."""
        for value, want in [("2026-W44", "2026-10-26"), ("2026-w44", "2026-10-26"), ("来週", None),
                            ('"2026-10-26 09:00"', "2026-10-26"), ("2026-10-26 09:00", "2026-10-26"),
                            ("2026/10/26", None)]:
            got = server._scheduled(value)
            self.assertEqual(got.isoformat() if got else None, want, value)
        from datetime import date
        s = server.summarize({"tasks": [{"id": "T1", "status": "pending", "scheduled_for": "来週"},
                                        {"id": "T2", "status": "pending", "scheduled_for": "2026-w45"},
                                        {"id": "T3", "status": "pending"}]}, None, today=date(2026, 10, 21))
        by = {t["id"]: t for t in s["tasks"]}
        self.assertEqual((by["T1"]["scheduled_for"], by["T1"]["scheduled_for_raw"], by["T1"]["scheduled_for_invalid"],
                          by["T1"]["category"]), (None, "来週", True, "ready"))   # placed as a task without a date
        self.assertEqual((by["T2"]["scheduled_for"], by["T2"]["scheduled_for_invalid"]), ("2026-11-02", False))
        self.assertEqual((by["T3"]["scheduled_for_raw"], by["T3"]["scheduled_for_invalid"]), (None, False))

    def test_due_and_overdue(self):
        """due is shown with overdue; the order and the ready judgement do not change."""
        from datetime import date
        today = date(2026, 10, 21)
        b = {"tasks": [{"id": "T1", "status": "pending", "priority": "P1", "due": "2026-10-20"},
                       {"id": "T2", "status": "pending", "priority": "P0", "due": "2026-10-30"},
                       {"id": "T3", "status": "completed", "due": "2026-10-01"},
                       {"id": "T4", "status": "pending", "priority": "P2", "due": "そのうち"}]}
        s = server.summarize(b, None, today=today)
        by = {t["id"]: t for t in s["tasks"]}
        self.assertEqual((by["T1"]["due"], by["T1"]["overdue"]), ("2026-10-20", True))
        self.assertFalse(by["T2"]["overdue"])
        self.assertFalse(by["T3"]["overdue"])
        self.assertEqual((by["T4"]["due"], by["T4"]["due_invalid"], by["T4"]["overdue"]), ("そのうち", True, False))
        self.assertEqual(s["current"], "T2")   # priority order, not the due date
        self.assertEqual({t["category"] for t in s["tasks"] if t["id"] != "T3"}, {"ready"})

    def test_empty_tasks(self):
        s = server.summarize({"tasks": []}, None)
        self.assertEqual((s["total"], s["percent"], s["current"]), (0, 0, None))

    def test_duplicate_ids_use_own_status(self):
        s = server.summarize({"tasks": [{"id": "T1", "status": "pending"}, {"id": "T1", "status": "completed"}]})
        self.assertEqual((s["done"], s["counts"]["ready"], s["duplicate_ids"]), (1, 1, ["T1"]))

    def test_edge_tasks(self):
        s = server.summarize({"tasks": [
            {"name": "IDなし", "status": "active"},
            {"id": "T2", "status": "pending", "dependencies": ["SG7"],
             "acceptance_criteria": [{"id": "AC1", "criterion": "見える"}]},
            None,
        ], "summary": {}}, {"goal": ["a", "b"]})
        t1, t2 = s["tasks"]
        self.assertEqual((t1["id"], t1["category"]), ("#1", "in_progress"))
        self.assertEqual(t2["dependencies"], [{"id": "SG7", "status": "not_in_backlog"}])
        self.assertEqual(t2["category"], "waiting")
        self.assertEqual(t2["acceptance_criteria"], ["見える"])
        self.assertEqual(s["goal"], "a / b")

    def test_operating_stage_for_operation_tasks_only(self):
        """only recurring operation tasks -> stage operating, no percent (null)."""
        b = {"tasks": [{"id": "R1", "status": "in_progress", "recurrence": "weekly"},
                       {"id": "R2", "status": "in_progress", "recurrence": "daily"}]}
        s = server.summarize(b, {"status": "active"})
        self.assertEqual((s["stage"], s["stage_label"], s["percent"], s["target"], s["done"]),
                         ("operating", "運用中（運用タスク 2件）", None, 0, 0))
        self.assertIsNone(s["current"])
        # the order: cancelled and sublayers still come first; normal tasks bring back schedule_wait / operation
        self.assertEqual(server.summarize(b, {"status": "cancelled"})["stage"], "cancelled")
        b["tasks"].append({"id": "T1", "status": "pending"})
        self.assertEqual(server.summarize(b, None)["stage"], "operation")
        b["tasks"][-1]["scheduled_for"] = "2999-01-04"
        self.assertEqual(server.summarize(b, None)["stage"], "schedule_wait")

    def test_completed_operation_task_never_pushes_percent_over_100(self):
        """an operation task marked completed by mistake is not in done or the percent."""
        b = {"tasks": [{"id": "T1", "status": "completed"},
                       {"id": "R1", "status": "completed", "recurrence": "weekly"}]}
        s = server.summarize(b, None)
        self.assertEqual((s["percent"], s["done"], s["target"]), (100, 1, 1))
        for normal_done in range(0, 3):
            for rec_done in range(0, 3):
                tasks = [{"id": f"T{i}", "status": "completed" if i < normal_done else "pending"} for i in range(2)]
                tasks += [{"id": f"R{i}", "status": "completed" if i < rec_done else "in_progress",
                           "recurrence": "weekly"} for i in range(2)]
                s = server.summarize({"tasks": tasks}, None)
                self.assertLessEqual(s["percent"], 100)
                self.assertLessEqual(s["done"], s["target"])

    # ---- 運用タスクの回す日・帯の数え方・通常完了＋運用中 ----
    def _ops(self, task, today="2026-10-22"):
        from datetime import date
        s = server.summarize({"tasks": [{"id": "T1", "status": "pending"}, dict(task, id="R")]}, None,
                             today=date.fromisoformat(today))
        return s, {t["id"]: t for t in s["tasks"]}["R"]

    def test_weekly_waits_until_seven_days_after_the_last_run(self):
        """weekly run 6 days ago -> waiting with the next run date; 7 days ago -> runnable (status kept)."""
        base = {"status": "in_progress", "recurrence": "weekly"}
        s, r = self._ops(dict(base, runs=[{"date": "2026-10-09"}, {"date": "2026-10-16"}]))
        self.assertEqual((r["category"], r["waiting_for_run"], r["last_run"], r["next_run"], r["run_due"]),
                         ("waiting", True, "2026-10-16", "2026-10-23", False))
        self.assertFalse(r["waiting_for_schedule"])
        self.assertEqual(s["operations"], {"count": 1, "due": 0, "next": "2026-10-23"})
        s, r = self._ops(dict(base, runs=[{"date": "2026-10-15"}]))
        self.assertEqual((r["category"], r["waiting_for_run"], r["next_run"], r["run_due"]),
                         ("in_progress", False, None, True))
        self.assertEqual(s["operations"], {"count": 1, "due": 1, "next": None})
        _, r = self._ops(dict(base, status="pending", runs=[{"date": "2026-10-15"}]))
        self.assertEqual(r["category"], "ready")

    def test_daily_waits_after_a_run_today(self):
        """daily run today -> waiting (next is tomorrow); run yesterday -> runnable."""
        base = {"status": "in_progress", "recurrence": "daily"}
        _, r = self._ops(dict(base, runs=[{"date": "2026-10-22"}]))
        self.assertEqual((r["category"], r["next_run"]), ("waiting", "2026-10-23"))
        _, r = self._ops(dict(base, runs=[{"date": "2026-10-21"}]))
        self.assertEqual((r["category"], r["run_due"]), ("in_progress", True))

    def test_no_runs_or_only_future_runs_means_a_run_day(self):
        """no runs yet -> a run day; a run dated in the future is not counted (same as plc_auto.due_recurring)."""
        for runs in (None, [], [{"date": "2026-10-30"}], ["2026-10-20"]):
            _, r = self._ops({"status": "in_progress", "recurrence": "weekly", "runs": runs})
            self.assertEqual((r["category"], r["last_run"], r["run_due"]), ("in_progress", None, True), runs)

    def test_scheduled_for_later_keeps_the_schedule_wait(self):
        """scheduled_for (the start day) later than today stays the schedule wait, even with a recent run."""
        _, r = self._ops({"status": "in_progress", "recurrence": "weekly", "scheduled_for": "2026-11-02",
                          "runs": [{"date": "2026-10-20"}]})
        self.assertEqual((r["category"], r["waiting_for_schedule"], r["waiting_for_run"], r["next_run"]),
                         ("waiting", True, False, "2026-11-02"))
        _, r = self._ops({"status": "pending", "recurrence": "daily", "scheduled_for": "2026-10-22"})
        self.assertEqual(r["category"], "ready")   # the start day itself is a run day

    def test_other_recurrence_and_retired_are_unchanged(self):
        """monthly / per_meeting have no gap rule; a retired task is left out of the rule and the summary."""
        recent = [{"date": "2026-10-21"}]
        for kind in ("monthly", "per_meeting"):
            s, r = self._ops({"status": "in_progress", "recurrence": kind, "runs": recent})
            self.assertEqual((r["category"], r["waiting_for_run"], r["run_due"], r["next_run"]),
                             ("in_progress", False, False, None), kind)
            self.assertEqual(s["operations"], {"count": 1, "due": 0, "next": None})
        s, r = self._ops({"status": "in_progress", "recurrence": "weekly", "runs": recent, "retired_at": "2026-10-21"})
        self.assertEqual((r["category"], r["retired"], r["run_due"]), ("in_progress", True, False))
        self.assertEqual(s["operations"], {"count": 0, "due": 0, "next": None})

    def test_dependency_blocked_and_done_judgements_come_first(self):
        """a waiting dependency, blocked or completed operation task is not changed by the run rule."""
        from datetime import date
        b = {"tasks": [{"id": "T1", "status": "pending"},
                       {"id": "R1", "status": "pending", "recurrence": "weekly", "dependencies": ["T1"]},
                       {"id": "R2", "status": "blocked", "recurrence": "weekly", "runs": [{"date": "2026-10-20"}]},
                       {"id": "R3", "status": "completed", "recurrence": "daily", "runs": [{"date": "2026-10-22"}]}]}
        by = {t["id"]: t for t in server.summarize(b, None, today=date(2026, 10, 22))["tasks"]}
        self.assertEqual([(by[i]["category"], by[i]["waiting_for_run"]) for i in ("R1", "R2", "R3")],
                         [("waiting", False), ("blocked", False), ("done", False)])

    def test_counts_normal_and_operations_summary(self):
        """counts are kept; counts_normal leaves out operation tasks; operations sums count / due / next."""
        from datetime import date
        b = {"tasks": [{"id": "T1", "status": "completed"},
                       {"id": "T2", "status": "pending"},
                       {"id": "R1", "status": "in_progress", "recurrence": "weekly", "runs": [{"date": "2026-10-20"}]},
                       {"id": "R2", "status": "in_progress", "recurrence": "daily", "runs": [{"date": "2026-10-22"}]},
                       {"id": "R3", "status": "in_progress", "recurrence": "daily"},
                       {"id": "R4", "status": "in_progress", "recurrence": "weekly", "retired_at": "2026-10-01"},
                       {"id": "R5", "status": "cancelled", "recurrence": "weekly"}]}
        s = server.summarize(b, None, today=date(2026, 10, 22))
        self.assertEqual(s["counts"], {"done": 1, "in_progress": 2, "ready": 1, "waiting": 2, "blocked": 0, "excluded": 1})
        self.assertEqual(s["counts_normal"], {"done": 1, "in_progress": 0, "ready": 1, "waiting": 0, "blocked": 0,
                                              "excluded": 0})
        self.assertEqual(s["operations"], {"count": 3, "due": 1, "next": "2026-10-23"})  # R4 retired, R5 excluded
        self.assertEqual((s["stage"], s["current"]), ("operation", "T2"))
        no_ops = server.summarize({"tasks": [{"id": "T1", "status": "pending"}]}, None)
        self.assertEqual(no_ops["operations"], {"count": 0, "due": 0, "next": None})

    def test_done_operating_stage(self):
        """normal tasks all done and operation tasks remain -> done_operating; done/target and percent kept."""
        from datetime import date
        b = {"tasks": [{"id": "T1", "status": "completed"},
                       {"id": "T2", "status": "cancelled"},
                       {"id": "R1", "status": "in_progress", "recurrence": "weekly", "runs": [{"date": "2026-10-20"}]},
                       {"id": "R2", "status": "in_progress", "recurrence": "daily"}]}
        s = server.summarize(b, {"status": "active"}, today=date(2026, 10, 22))
        self.assertEqual((s["stage"], s["stage_label"], s["done"], s["target"], s["percent"]),
                         ("done_operating", "通常タスク完了・運用中（運用タスク 2件）", 1, 1, 100))
        self.assertEqual(s["counts_normal"]["waiting"] + s["counts_normal"]["in_progress"], 0)
        self.assertIsNone(s["current"])
        # retired / completed / excluded operation tasks do not keep it operating -> all_done as before
        b["tasks"][2]["retired_at"] = "2026-10-21"
        b["tasks"][3]["status"] = "completed"
        self.assertEqual(server.summarize(b, None, today=date(2026, 10, 22))["stage"], "all_done")
        # cancelled still comes first
        self.assertEqual(server.summarize(b, {"status": "cancelled"})["stage"], "cancelled")

    def test_operation_tasks_only_stay_operating(self):
        """a Layer with only operation tasks keeps the existing operating stage and null percent."""
        from datetime import date
        b = {"tasks": [{"id": "R1", "status": "in_progress", "recurrence": "weekly", "runs": [{"date": "2026-10-20"}]}]}
        s = server.summarize(b, None, today=date(2026, 10, 22))
        self.assertEqual((s["stage"], s["percent"], s["operations"]),
                         ("operating", None, {"count": 1, "due": 0, "next": "2026-10-27"}))

    def test_percent_never_100_until_done(self):
        tasks = [{"id": f"T{i}", "status": "completed"} for i in range(199)] + [{"id": "X", "status": "pending"}]
        self.assertEqual(server.summarize({"tasks": tasks})["percent"], 99)
        self.assertEqual(server.summarize({"tasks": None})["total"], 0)

    def test_stage(self):
        self.assertEqual(server.summarize({"tasks": []})["stage"], "inception_wait")
        self.assertEqual(self.state["stage"], "operation")
        done = server.summarize({"tasks": [{"id": "A", "status": "completed"}, {"id": "B", "status": "cancelled"}]})
        self.assertEqual((done["stage"], done["stage_label"]), ("all_done", "全タスク完了"))
        self.assertEqual(server.summarize({"tasks": [{"id": "A", "status": "cancelled"}]})["stage"], "all_excluded")
        self.assertEqual(server.summarize({"tasks": [], "sublayers": [{"id": "SG1"}]})["stage"], "sublayers")
        self.assertEqual(server.summarize({"tasks": [{"id": "A"}]}, {"status": "cancelled"})["stage"], "cancelled")

    def test_duplicate_current_order(self):
        s = server.summarize({"tasks": [{"id": "T1", "status": "completed"}, {"id": "T1", "status": "pending"}]})
        self.assertEqual((s["current"], s["current_order"]), ("T1", 1))

    def test_bad_shape_raises(self):
        with self.assertRaises(ValueError):
            server.summarize(["x"], None)
        with self.assertRaises(ValueError):
            server.summarize({"tasks": "x"}, None)


class FlowTest(unittest.TestCase):
    def flow(self, tasks):
        s = server.summarize({"tasks": tasks})
        return s, {t["id"]: t["level"] for t in s["tasks"]}

    def test_levels_parallel_and_join(self):
        s, lv = self.flow([
            {"id": "A", "status": "completed"},
            {"id": "B", "status": "pending", "dependencies": ["A"]},
            {"id": "C", "status": "pending", "dependencies": ["A"], "priority": "P0"},
            {"id": "D", "status": "pending", "dependencies": ["B", "C"]},
            {"id": "E", "status": "pending"},
        ])
        self.assertEqual(lv, {"A": 0, "B": 1, "C": 1, "D": 2, "E": 0})
        self.assertEqual(s["flow"]["level_count"], 3)
        self.assertEqual(len(s["flow"]["edges"]), 4)
        self.assertEqual(s["flow"]["cycle"], [])

    def test_critical_prefers_longest_open_chain(self):
        s, _ = self.flow([
            {"id": "A", "status": "completed"},
            {"id": "B", "status": "completed", "dependencies": ["A"]},
            {"id": "C", "status": "completed", "dependencies": ["B"]},
            {"id": "X", "status": "pending"},
            {"id": "Y", "status": "pending", "dependencies": ["X"]},
        ])
        ids = [s["tasks"][o]["id"] for o in s["flow"]["critical"]]
        self.assertEqual(ids, ["X", "Y"])  # 未完了を含む連なり（A→B→C は完了済み）
        crit = [e for e in s["flow"]["edges"] if e["critical"]]
        self.assertEqual([(e["from"], e["to"]) for e in crit], [(3, 4)])

    def test_critical_when_all_done(self):
        s, _ = self.flow([
            {"id": "A", "status": "completed"},
            {"id": "B", "status": "completed", "dependencies": ["A"]},
            {"id": "C", "status": "completed"},
        ])
        self.assertEqual([s["tasks"][o]["id"] for o in s["flow"]["critical"]], ["A", "B"])

    def test_cycle_missing_and_duplicate(self):
        s, lv = self.flow([
            {"id": "A", "status": "pending", "dependencies": ["C"]},
            {"id": "B", "status": "pending", "dependencies": ["A", "SG9", "B"]},
            {"id": "C", "status": "pending", "dependencies": ["B"]},
            {"id": "D", "status": "pending"},
            {"id": "D", "status": "pending", "dependencies": ["D"]},
        ])
        self.assertEqual(sorted(s["flow"]["cycle"]), ["A", "B", "C"])
        # 循環 A・B・C は外からの依存が無いので段0にまとまる。2つ目の D の依存「D」は先勝ちで1つ目の D を指すので段1
        self.assertEqual([t["level"] for t in s["tasks"]], [0, 0, 0, 0, 1])
        self.assertEqual([(e["from"], e["to"], e["cycle"]) for e in s["flow"]["edges"]],
                         [(2, 0, True), (0, 1, True), (1, 2, True), (3, 4, False)])
        self.assertTrue(all(t["in_cycle"] == (t["id"] in "ABC") for t in s["tasks"]))

    def test_cycle_downstream_is_not_cycle(self):
        s, lv = self.flow([
            {"id": "A", "status": "pending", "dependencies": ["B"]},
            {"id": "B", "status": "pending", "dependencies": ["A"]},
            {"id": "C", "status": "pending", "dependencies": ["A"]},
            {"id": "D", "status": "pending", "dependencies": "C"},
            {"id": "E", "status": "pending"},
        ])
        self.assertEqual(s["flow"]["cycle"], ["A", "B"])
        self.assertEqual(lv, {"A": 0, "B": 0, "C": 1, "D": 2, "E": 0})
        self.assertEqual([t["in_cycle"] for t in s["tasks"]], [True, True, False, False, False])
        cd = next(e for e in s["flow"]["edges"] if (e["from"], e["to"]) == (2, 3))
        self.assertFalse(cd["cycle"])
        self.assertEqual([s["tasks"][o]["id"] for o in s["flow"]["critical"]], ["C", "D"])

    def test_all_excluded_and_single_string_dependency(self):
        s, lv = self.flow([
            {"id": "A", "status": "cancelled"},
            {"id": "B", "status": "dropped", "dependencies": "A"},
        ])
        self.assertEqual(lv, {"A": 0, "B": 1})
        self.assertEqual(s["stage"], "all_excluded")

    def test_current_path(self):
        s, _ = self.flow([
            {"id": "A", "status": "completed"},
            {"id": "B", "status": "completed", "dependencies": ["A"]},
            {"id": "C", "status": "in_progress", "dependencies": ["B"]},
            {"id": "Z", "status": "pending"},
        ])
        self.assertEqual(s["flow"]["current_path"], [0, 1, 2])
        self.assertEqual([(e["from"], e["to"], e["to_current"]) for e in s["flow"]["edges"]],
                         [(0, 1, False), (1, 2, True)])  # 直接の依存だけ強調

    def test_recurring_tasks_are_left_out_of_the_flow(self):
        """運用タスクは段・線・最長の連なりに入れず、件数だけ返す"""
        s, lv = self.flow([
            {"id": "A", "status": "pending"},
            {"id": "OPS", "status": "in_progress", "recurrence": "weekly"},
            {"id": "B", "status": "pending", "dependencies": ["A"]},
            {"id": "C", "status": "pending", "dependencies": ["OPS"]},  # 決まりに反する依存も線にしない
        ])
        self.assertEqual(s["flow"]["hidden_recurring"], 1)
        self.assertIsNone(lv["OPS"])
        self.assertEqual((lv["A"], lv["B"], lv["C"]), (0, 1, 0))
        orders = {o for e in s["flow"]["edges"] for o in (e["from"], e["to"])} | set(s["flow"]["critical"])
        self.assertNotIn(1, orders)  # OPS の order

    def test_empty(self):
        s = server.summarize({"tasks": []})
        self.assertEqual(s["flow"], {"level_count": 0, "edges": [], "critical": [], "current_path": [], "cycle": [],
                                     "hidden_recurring": 0})


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.layer = Path(self.tmp.name) / "layer"
        self.layer.mkdir()
        write(self.layer / "backlog.yaml", BACKLOG)
        write(self.layer / "intent.yaml", INTENT)
        self.srv = server.build_server(self.layer, 0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def req(self, method="GET", path="/api/state", host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": host} if host else {}
        conn.request(method, path, headers=headers)
        res = conn.getresponse()
        body = res.read()
        conn.close()
        return res, body

    def state(self):
        res, body = self.req()
        self.assertEqual(res.status, 200)
        return json.loads(body)

    def test_binds_loopback_only(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_state_and_reload_on_save(self):
        s = self.state()
        self.assertTrue(s["ok"])
        self.assertEqual((s["done"], s["current"]), (1, "T003"))
        write(self.layer / "backlog.yaml", BACKLOG.replace("name: 追従, status: pending", "name: 追従, status: in_progress"))
        s = self.state()
        self.assertEqual((s["current"], s["current_reason"]), ("T003", "進行中"))

    def test_broken_yaml_keeps_last_good(self):
        self.state()
        write(self.layer / "backlog.yaml", "tasks: [\n  - {id: T001, status: ")
        s = self.state()
        self.assertFalse(s["ok"])
        self.assertTrue(s["stale"])
        self.assertIn("読めませんでした", s["error"])
        self.assertEqual(s["done"], 1)  # 最後の正常値
        write(self.layer / "backlog.yaml", "")
        s = self.state()
        self.assertTrue(s["stale"])
        write(self.layer / "backlog.yaml", BACKLOG)
        s = self.state()
        self.assertTrue(s["ok"])
        self.assertIsNone(s["error"])

    def test_broken_from_start(self):
        write(self.layer / "backlog.yaml", "{{{")
        s = self.state()
        self.assertFalse(s["ok"])
        self.assertFalse(s["stale"])
        self.assertNotIn("tasks", s)

    def test_broken_intent_still_shows_tasks(self):
        write(self.layer / "intent.yaml", "goal: [")
        s = self.state()
        self.assertTrue(s["ok"])
        self.assertIn("intent.yaml", s["intent_error"])
        self.assertEqual(s["done"], 1)

    def test_missing_backlog(self):
        (self.layer / "backlog.yaml").unlink()
        s = self.state()
        self.assertFalse(s["ok"])
        self.assertIn("見つかりません", s["error"])

    def test_non_get_rejected(self):
        for m in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            res, _ = self.req(m)
            self.assertEqual(res.status, 405, m)
        self.assertEqual((self.layer / "backlog.yaml").read_text(encoding="utf-8"), BACKLOG)

    def test_foreign_host_rejected(self):
        res, _ = self.req(host="evil.example:8770")
        self.assertEqual(res.status, 403)

    def test_static_allowlist(self):
        for path in ("/", "/app.js", "/style.css"):
            res, body = self.req(path=path)
            self.assertEqual(res.status, 200, path)
            self.assertIn("default-src 'self'", res.getheader("Content-Security-Policy"))
        for path in ("/server.py", "/../server.py", "/static/index.html", "/api/state/../../etc"):
            res, _ = self.req(path=path)
            self.assertEqual(res.status, 404, path)

    def test_no_external_urls_in_static(self):
        for f in server.STATIC.iterdir():
            # SVG の名前空間は識別子で、読み込みは起きないので除く
            text = f.read_text(encoding="utf-8").replace("http://www.w3.org/2000/svg", "")
            self.assertNotRegex(text, r"https?://", f.name)


def make_layer(folder: Path, backlog: str = BACKLOG, intent: str = INTENT, mtime: float = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "intent.yaml").write_text(intent, encoding="utf-8")
    (folder / "backlog.yaml").write_text(backlog, encoding="utf-8")
    if mtime is not None:
        os.utime(folder / "backlog.yaml", (mtime, mtime))
    return folder


class FollowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        flow = self.root / "Flow" / "202610" / "2026-10-15"
        base = time.time() - 100
        self.a = make_layer(flow / "layer-a", intent="scope_id: L-A\n", mtime=base)
        self.b = make_layer(flow / "layer-b", backlog="tasks: []\n", intent="scope_id: L-B\n", mtime=base + 10)
        # 追従してはいけないもの: Documents の写し・隠しフォルダ・intent の無いフォルダ・未来時刻
        make_layer(self.a / "Documents" / "previous", mtime=base + 50)
        make_layer(self.a / "documents" / "fixture", mtime=base + 50)  # 小文字も写し扱い
        make_layer(flow / ".hidden", mtime=base + 50)
        (flow / "no-intent").mkdir()
        (flow / "no-intent" / "backlog.yaml").write_text("tasks: []\n", encoding="utf-8")
        make_layer(flow / "future", mtime=time.time() + 3600)
        self.flow = flow
        self.old_ttl = server.SCAN_TTL
        server.SCAN_TTL = 0

    def tearDown(self):
        server.SCAN_TTL = self.old_ttl
        self.tmp.cleanup()

    def test_picks_latest_and_ignores_copies(self):
        latest = server.find_latest_layer(self.root / "Flow")
        self.assertEqual(latest[0], self.b)

    def test_symlink_not_followed(self):
        target = make_layer(self.root / "outside", mtime=time.time())
        os.symlink(target, self.flow / "linked")
        self.assertEqual(server.find_latest_layer(self.root / "Flow")[0], self.b)

    def test_switches_on_save(self):
        f = server.Follower(self.root / "Flow", self.root)
        s = f.state()
        self.assertEqual((s["mode"], s["scope_id"], s["stage"]), ("follow", "L-B", "inception_wait"))
        self.assertEqual(s["layer_rel"], "Flow/202610/2026-10-15/layer-b")
        self.assertTrue(s["follow_basis_mtime"])
        write(self.a / "backlog.yaml", BACKLOG)
        os.utime(self.a / "backlog.yaml", None)  # いまの時刻にする
        s = f.state()
        self.assertEqual((s["scope_id"], s["stage"]), ("L-A", "operation"))

    def test_fixed_mode_does_not_switch(self):
        srv = server.build_server(self.b, 0, self.root)
        try:
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            os.utime(self.a / "backlog.yaml", None)
            conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
            conn.request("GET", "/api/state")
            s = json.loads(conn.getresponse().read())
            conn.close()
            self.assertEqual((s["mode"], s["scope_id"]), ("fixed", "L-B"))
        finally:
            srv.shutdown()
            srv.server_close()

    def test_incremental_scan_between_full_scans(self):
        server.FULL_SCAN_TTL, old_full = 3600, server.FULL_SCAN_TTL
        try:
            old = make_layer(self.root / "Flow" / "202601" / "2026-01-01" / "old", intent="scope_id: L-OLD\n",
                             mtime=time.time() - 1000)
            f = server.Follower(self.root / "Flow", self.root)
            self.assertEqual(f.state()["scope_id"], "L-B")  # 初回は全体走査
            new = make_layer(self.flow / "layer-new", intent="scope_id: L-NEW\n")  # 新しい日付フォルダに新規
            self.assertEqual(f.state()["scope_id"], "L-NEW")
            os.utime(old / "backlog.yaml", None)  # 古い月の見つけ済み Layer を保存
            self.assertEqual(f.state()["scope_id"], "L-OLD")
            import shutil
            shutil.rmtree(old)
            shutil.rmtree(new)
            self.assertEqual(f.state()["scope_id"], "L-B")
        finally:
            server.FULL_SCAN_TTL = old_full

    def test_non_date_dirs_and_sublayers_in_incremental_scan(self):
        server.FULL_SCAN_TTL, old_full = 3600, server.FULL_SCAN_TTL
        try:
            for name in ("templates", "企画書", "temp"):  # 逆順で日付より前に並ぶ名前
                (self.root / "Flow" / name).mkdir()
            old = make_layer(self.root / "Flow" / "202601" / "2026-01-01" / "old", intent="scope_id: L-OLD\n",
                             mtime=time.time() - 1000)
            f = server.Follower(self.root / "Flow", self.root)
            self.assertEqual(f.state()["scope_id"], "L-B")
            make_layer(self.flow / "layer-new", intent="scope_id: L-NEW\n")
            self.assertEqual(f.state()["scope_id"], "L-NEW")
            make_layer(old / "sublayers" / "sg1", intent="scope_id: L-OLD-SG1\n")  # 古い日付の下の新 SubLayer
            self.assertEqual(f.state()["scope_id"], "L-OLD-SG1")
        finally:
            server.FULL_SCAN_TTL = old_full

    def test_pinned_by_scope_id_does_not_follow(self):
        f = server.Follower(self.root / "Flow", self.root)
        s = f.state({"layer": "L-A"})
        self.assertEqual((s["mode"], s["scope_id"], s["requested_layer"]), ("pinned", "L-A", "L-A"))
        os.utime(self.b / "backlog.yaml", None)  # 別の Layer を保存しても
        self.assertEqual(f.state({"layer": "L-A"})["scope_id"], "L-A")
        self.assertEqual(f.state()["scope_id"], "L-B")  # 指定なしは追従

    def test_pinned_rejects_bad_values_without_reading(self):
        f = server.Follower(self.root / "Flow", self.root)
        for bad in ("../layer-a", "a/b", "L.1", "", "x" * 65, "Flow/202610/2026-10-15/layer-a"):
            s = f.state({"layer": bad}) if bad else f.pinned_state(bad, None)
            self.assertFalse(s["ok"], bad)
            self.assertNotIn("tasks", s, bad)
        s = f.state({"layer": "L-NOPE"})
        self.assertFalse(s["ok"])
        self.assertIn("見つかりません", s["error"])

    def test_pinned_quoted_scope_and_duplicates(self):
        make_layer(self.flow / "dup-1", intent='scope_id: "L-DUP"  # comment\ndisplay_name: "重複1"\n')
        make_layer(self.flow / "dup-2", intent="scope_id: 'L-DUP'\n")
        f = server.Follower(self.root / "Flow", self.root)
        s = f.state({"layer": "L-DUP"})
        self.assertFalse(s["ok"])
        rels = [c["rel"] for c in s["candidates"]]
        self.assertEqual(rels, ["Flow/202610/2026-10-15/dup-1", "Flow/202610/2026-10-15/dup-2"])
        s = f.state({"layer": "L-DUP", "at": rels[1]})
        self.assertEqual((s["ok"], s["layer_rel"]), (True, rels[1]))
        s = f.state({"layer": "L-DUP", "at": "Flow/../../etc"})
        self.assertFalse(s["ok"])

    def test_pinned_finds_layer_created_in_old_dir(self):
        server.FULL_SCAN_TTL, old_full = 3600, server.FULL_SCAN_TTL
        server.RESCAN_ON_MISS, old_miss = 0, server.RESCAN_ON_MISS
        try:
            f = server.Follower(self.root / "Flow", self.root)
            f.state()
            make_layer(self.root / "Flow" / "202601" / "2026-01-02" / "late", intent="scope_id: L-LATE\n")
            self.assertEqual(f.state({"layer": "L-LATE"})["scope_id"], "L-LATE")
        finally:
            server.FULL_SCAN_TTL, server.RESCAN_ON_MISS = old_full, old_miss

    def test_layers_list_sorted_and_names(self):
        make_layer(self.flow / "named", intent="scope_id: L-N\ndisplay_name: 名前つき\n")
        d = server.Follower(self.root / "Flow", self.root).layers()
        self.assertTrue(d["available"])
        self.assertEqual([r["scope_id"] for r in d["layers"]][:3], ["L-N", "L-B", "L-A"])
        self.assertEqual(d["layers"][0]["name"], "名前つき")
        self.assertNotIn("L-DEMO", [r["scope_id"] for r in d["layers"]])
        rels = [r["rel"] for r in d["layers"]]
        self.assertFalse(any("Documents" in r or ".hidden" in r or "future" in r for r in rels))

    def test_http_layer_param_and_layers_api(self):
        srv = server.build_server(None, 0, self.root)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            def get(path):
                conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
                conn.request("GET", path)
                res = conn.getresponse()
                body = res.read()
                conn.close()
                return res.status, json.loads(body)
            self.assertEqual(get("/api/state?layer=L-A")[1]["scope_id"], "L-A")
            self.assertEqual(get("/api/state?layer=L-A&layer=L-B")[1]["scope_id"], "L-A")  # 先頭だけ
            self.assertEqual(get("/api/state?unknown=1")[1]["mode"], "follow")
            status, body = get("/api/layers")
            self.assertEqual((status, body["available"]), (200, True))
            status, _ = get("/api/state?" + "&".join(f"k{i}=1" for i in range(20)))
            self.assertEqual(status, 400)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_fixed_mode_ignores_layer_param(self):
        src = server.FixedSource(self.b, self.root)
        s = src.state({"layer": "L-A"})
        self.assertEqual((s["mode"], s["scope_id"]), ("fixed", "L-B"))
        self.assertIn("--layer", s["layer_param_ignored"])
        self.assertFalse(src.layers()["available"])

    def test_pinned_excludes_symlinked_backlog(self):
        outside = make_layer(self.root / "outside", backlog=BACKLOG)
        lnk = self.flow / "linked-file"
        lnk.mkdir()
        (lnk / "intent.yaml").write_text("scope_id: L-LINK\n", encoding="utf-8")
        os.symlink(outside / "backlog.yaml", lnk / "backlog.yaml")
        s = server.Follower(self.root / "Flow", self.root).state({"layer": "L-LINK"})
        self.assertFalse(s["ok"])
        self.assertNotIn("tasks", s)

    def test_layers_marks_duplicates_with_at_and_names(self):
        make_layer(self.flow / "dup-1", intent="scope_id: L-DUP\nscope_name: dup-one\n")
        make_layer(self.flow / "dup-2", intent="scope_id: L-DUP\n")
        f = server.Follower(self.root / "Flow", self.root)
        rows = [r for r in f.layers()["layers"] if r["scope_id"] == "L-DUP"]
        self.assertEqual(sorted(r["at"] for r in rows), ["Flow/202610/2026-10-15/dup-1", "Flow/202610/2026-10-15/dup-2"])
        self.assertNotIn("at", next(r for r in f.layers()["layers"] if r["scope_id"] == "L-A"))
        cands = f.state({"layer": "L-DUP"})["candidates"]
        self.assertEqual(cands[0]["name"], "dup-one")
        self.assertEqual(cands[0]["at"], cands[0]["rel"])

    def test_empty_flow(self):
        empty = self.root / "empty"
        (empty / "Flow").mkdir(parents=True)
        s = server.Follower(empty / "Flow", empty).state()
        self.assertFalse(s["ok"])
        self.assertEqual(s["mode"], "follow")


if __name__ == "__main__":
    unittest.main()
