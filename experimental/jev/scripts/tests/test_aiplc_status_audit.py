"""Tests for aiplc_status_audit.py. Synthetic DB + synthetic Layers only.

The production DB is never opened here.
"""
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import yaml  # noqa: F401  (the scripts need pyyaml; without it these tests are skipped, not errors)
except ImportError:
    raise unittest.SkipTest("pyyaml が無い（pip install pyyaml）")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import aiplc_status_audit as audit_mod  # noqa: E402
import jev_client  # noqa: E402
import jev_test_support as jts  # noqa: E402


def setUpModule():
    jts.isolate()  # fictional extra word list; never the real local file


def tearDownModule():
    jts.restore()

TODAY = date(2026, 9, 28)
SCHEMA = """
CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, notion_page_id TEXT UNIQUE,
  scope_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, goal TEXT, owner TEXT DEFAULT 'owner',
  status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','active','completed','paused')),
  parent_scope TEXT, top_page_url TEXT,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')));
CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, scope_id TEXT NOT NULL,
  name TEXT NOT NULL, status TEXT NOT NULL DEFAULT '未着手' CHECK(status IN ('未着手','進行中','完了')),
  completed_at TEXT);
"""


def sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tree_hashes(root: Path):
    return {str(p.relative_to(root)): (sha(p), p.stat().st_mtime) for p in sorted(root.rglob("*")) if p.is_file()}


class Fixture:
    def __init__(self, tmp: Path):
        self.root = tmp / "repo"
        self.root.mkdir()
        self.db = tmp / "ai_plc.db"
        c = sqlite3.connect(self.db)
        c.executescript(SCHEMA)
        c.commit()
        self.conn = c

    def project(self, sid, status="active", url="", name="普通のPJ", goal="", parent=None,
                updated="2026-09-01T00:00:00Z"):
        self.conn.execute("INSERT INTO projects(scope_id,name,goal,status,parent_scope,top_page_url,updated_at) "
                          "VALUES (?,?,?,?,?,?,?)", (sid, name, goal, status, parent, url, updated))
        self.conn.commit()

    def rtask(self, sid, tid, status="未着手"):
        self.conn.execute("INSERT INTO tasks(task_id,scope_id,name,status) VALUES (?,?,?,?)", (tid, sid, tid, status))
        self.conn.commit()

    def layer(self, rel, sid, status="active", tasks=(), days_ago=1, extra=None, sublayers=None, summary=None,
              backlog=True):
        folder = self.root / rel
        folder.mkdir(parents=True, exist_ok=True)
        intent = {"scope_id": sid, "scope_name": rel.rsplit("/", 1)[-1], "status": status,
                  "goal": {"description": "テスト用のゴール"}}
        intent.update(extra or {})
        (folder / "intent.yaml").write_text(yaml.safe_dump(intent, allow_unicode=True), encoding="utf-8")
        files = [folder / "intent.yaml"]
        if backlog:
            bl = {"sublayers": sublayers or [],
                  "tasks": [{"id": t, "status": s} for t, s in tasks]}
            if summary is not None:
                bl["summary"] = summary
            (folder / "backlog.yaml").write_text(yaml.safe_dump(bl, allow_unicode=True), encoding="utf-8")
            files.append(folder / "backlog.yaml")
        ts = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time()).timestamp() + 3600
        for f in files:
            os.utime(f, (ts, ts))
        return folder

    def close(self):
        self.conn.close()


class AuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        f = Fixture(Path(cls.tmp.name))
        cls.f = f
        F = "Flow/202609/2026-09-01"
        # 1 intent done, registry open
        f.layer(f"{F}/a-done", "L-A", "completed", [("T001", "completed")])
        f.project("L-A", url=f"{F}/a-done")
        f.rtask("L-A", "T001", "完了")
        # 2 all tasks done, unclosed (+ open child variant)
        f.layer(f"{F}/b-all", "L-B", "active", [("T001", "completed"), ("T002", "cancelled")],
                summary={"status": "active", "next_action": "x"})
        f.project("L-B", url=f"{F}/b-all/")  # trailing slash
        f.rtask("L-B", "T001", "完了")
        f.layer(f"{F}/b2-child", "L-B2", "active", [("T001", "done")],
                sublayers=[{"scope_id": "L-B2-SG1", "status": "pending_init"}])
        f.project("L-B2", url=str(f.root / f"{F}/b2-child"))  # absolute path
        f.rtask("L-B2", "T001", "完了")
        # deferred only remaining -> not class 2
        f.layer(f"{F}/b3-def", "L-B3", "active", [("T001", "completed"), ("T002", "deferred")])
        f.project("L-B3", url=f"{F}/b3-def/README.md")  # README.md -> folder
        f.rtask("L-B3", "T001", "完了")
        f.rtask("L-B3", "T002", "未着手")
        # 3 completed project, open Registry task; backlog says completed (also class 6 all terminal + 7)
        f.layer(f"{F}/c-comp", "L-C", "active", [("T001", "completed"), ("T002", "completed")])
        f.project("L-C", "completed", url=f"{F}/c-comp")
        f.rtask("L-C", "T001", "完了")
        f.rtask("L-C", "T002", "未着手")
        # 4 folder missing (4 reasons) + Documents copy must not be picked
        f.project("L-D1", url="https://www.notion.so/abc")
        f.project("L-D2", url="")
        f.project("L-D3", url="Flow/202601/2026-01-01/nowhere")
        legacy = f.root / "Flow/202601/2026-01-02/legacy"
        legacy.mkdir(parents=True)
        (legacy / "layer.yaml.md").write_text("old", encoding="utf-8")
        f.project("L-D4", url="Flow/202601/2026-01-02/legacy")
        f.layer(f"{F}/other/Documents/snap", "L-D1", "active", [("T001", "pending")])
        # notion URL resolved via scope index
        f.layer(f"{F}/n-index", "L-N", "active", [("T001", "pending")], days_ago=2)
        f.project("L-N", url="https://app.notion.com/p/xyz")
        f.rtask("L-N", "T001", "未着手")
        # 5 stale boundary
        f.layer(f"{F}/e30", "L-E30", "active", [("T001", "completed"), ("T002", "pending")], days_ago=30)
        f.project("L-E30", url=f"{F}/e30")
        f.layer(f"{F}/e29", "L-E29", "active", [("T001", "pending")], days_ago=29)
        f.project("L-E29", url=f"{F}/e29")
        f.layer(f"{F}/efresh", "L-EF", "active", [("T001", "pending")], days_ago=3)
        f.project("L-EF", url=f"{F}/efresh", updated="2026-05-01T00:00:00Z")  # old registry, fresh layer
        f.layer(f"{F}/e-opt", "L-EOPT", "active", [("T001", "pending")], days_ago=40, extra={"jev_monitor": True})
        f.project("L-EOPT", url=f"{F}/e-opt")
        f.layer(f"{F}/zetaproj-thing", "L-EZET", "active", [("T001", "pending")], days_ago=40,
                extra={"jev_monitor": True})
        f.project("L-EZET", url=f"{F}/zetaproj-thing", name="Zetaproj 何か")
        f.layer(f"{F}/child-of-secret", "L-ECH", "active", [("T001", "pending")], days_ago=40,
                extra={"jev_monitor": True, "parent_scope": "L-SECRET"})
        f.project("L-ECH", url=f"{F}/child-of-secret", parent="L-SECRET")
        f.project("L-SECRET", "completed", url="https://notion.so/x", name="キャリアの検討")
        f.layer(f"{F}/priv", "L-EPRIV", "active", [("T001", "pending")], days_ago=40,
                extra={"jev_monitor": True, "extensions": ["privacy"]})
        f.project("L-EPRIV", url=f"{F}/priv")
        # 6 registry closed, layer open, not all terminal
        f.layer(f"{F}/f-open", "L-F", "active", [("T001", "completed"), ("T002", "pending")])
        f.project("L-F", "completed", url=f"{F}/f-open")
        f.rtask("L-F", "T001", "完了")
        f.rtask("L-F", "T002", "完了")
        # 8 registry task missing
        f.layer(f"{F}/g-miss", "L-G", "active", [("T001", "completed"), ("T002", "pending")], days_ago=2)
        f.project("L-G", url=f"{F}/g-miss")
        f.rtask("L-G", "T001", "完了")
        # 9 registry missing
        f.layer(f"{F}/h-unreg", "L-H", "active", [("T001", "pending")])
        # unreadable backlog in a confidential Layer: path must not leak into report.md
        broken = f.layer(f"{F}/zetaproj-broken", "L-BRK", "active", backlog=False)
        (broken / "backlog.yaml").write_text("tasks: [unclosed\n  - : :", encoding="utf-8")
        # git worktree copy must not win over the real Layer
        f.layer("Flow/.worktrees/wt1/Flow/202609/2026-09-01/w", "L-W", "completed", [("T001", "completed")])
        f.layer(f"{F}/w-real", "L-W", "active", [("T001", "pending")], days_ago=2)
        f.project("L-W", url="https://www.notion.so/w")
        f.rtask("L-W", "T001", "未着手")
        # stale copy vs recently touched copy: the newest copy decides (not stale)
        f.layer(f"{F}/cp-new", "L-CP", "active", [("T001", "pending")], days_ago=5)
        f.layer(".ai-plc/projects/L-CP", "L-CP", "active", [("T001", "pending")], days_ago=60)
        f.project("L-CP", url=".ai-plc/projects/L-CP")
        f.rtask("L-CP", "T001", "未着手")
        # two copies that disagree: nothing may be proposed
        f.layer(f"{F}/dup", "L-DUP", "active", [("T001", "completed")])
        f.layer(".ai-plc/projects/L-DUP", "L-DUP", "active", [("T001", "pending")])
        f.project("L-DUP", url="")
        f.rtask("L-DUP", "T001", "完了")
        # todo / memory
        (f.root / "todo").mkdir()
        (f.root / "todo" / "todo.md").write_text(
            f"- x\n  <!-- layer: {F}/b-all scope: L-B -->\n  <!-- layer: {F}/gone scope: L-EF -->\n", encoding="utf-8")
        cls.memory = f.root / "MEMORY.md"
        f.layer(f"{F}/m1", "L-9001", "completed", [("T001", "completed")])
        f.project("L-9001", "completed", url=f"{F}/m1")
        f.rtask("L-9001", "T001", "完了")
        f.layer(f"{F}/m2", "L-9002", "active", [("T001", "pending")])
        f.project("L-9002", url=f"{F}/m2")
        f.rtask("L-9002", "T001", "未着手")
        cls.memory.write_text("- [A L-9001](a.md) — 進行中PJ。x\n- [B L-9002](b.md) — 完了PJ。y\n"
                              "- [C L-9003](c.md) — 進行中PJ。z\n- [nolabel L-9002](d.md) — メモ\n", encoding="utf-8")
        f.close()
        cls.before_db = sha(f.db)
        cls.before_tree = tree_hashes(f.root)
        cls.out = Path(cls.tmp.name) / "out"
        rc = audit_mod.main(["--db", str(f.db), "--root", str(f.root), "--today", TODAY.isoformat(),
                             "--memory", str(cls.memory), "--out", str(cls.out), "--quiet"])
        assert rc == 0
        # report.json is the public (masked) view since T004; classification is checked on the in-memory report
        cls.public = json.loads((cls.out / "report.json").read_text(encoding="utf-8"))
        cls.report = audit_mod.audit(f.db, f.root, TODAY, 30, f.root / "todo" / "todo.md", cls.memory)
        cls.by = {}
        for c in cls.report["candidates"]:
            cls.by.setdefault(c["kind"], {})[c["scope_id"]] = c

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # ---- read-only
    def test_db_and_layer_files_unchanged(self):
        self.assertEqual(sha(self.f.db), self.before_db)
        self.assertEqual(tree_hashes(self.f.root), self.before_tree)

    def test_connection_is_read_only(self):
        conn = audit_mod.open_ro(self.f.db)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("UPDATE projects SET status='completed'")
        conn.close()
        self.assertEqual(sha(self.f.db), self.before_db)

    def test_reports_written(self):
        self.assertTrue((self.out / "report.md").is_file())
        self.assertEqual(len(self.public["candidates"]), len(self.report["candidates"]))
        self.assertFalse([k for k in self.public if k.startswith("_")])
        ids = [c["candidate_id"] for c in self.public["candidates"]]
        self.assertEqual(len(ids), len(set(ids)))
        for c in self.report["candidates"]:
            for k in ("scope_id", "kind", "evidence", "recommended_action", "proposed_changes", "confidential",
                      "jev_eligible", "reason"):
                self.assertIn(k, c)
        self.assertTrue(self.report["params"]["read_only"])

    def test_refuses_layer_folder_as_out(self):
        rc = audit_mod.main(["--db", str(self.f.db), "--root", str(self.f.root), "--today", TODAY.isoformat(),
                             "--memory", str(self.memory),
                             "--out", str(self.f.root / "Flow/202609/2026-09-01/a-done"), "--quiet"])
        self.assertEqual(rc, 2)
        self.assertEqual(tree_hashes(self.f.root), self.before_tree)

    def test_worktree_copy_excluded(self):
        idx, _, _ = audit_mod.scan_intents(self.f.root)
        self.assertEqual([l.rel for l in idx["L-W"]], ["Flow/202609/2026-09-01/w-real"])
        self.assertNotIn("L-W", self.by.get("intent_done_registry_open", {}))

    def test_stale_uses_newest_copy(self):
        self.assertNotIn("L-CP", self.by.get("stale", {}))

    def test_duplicate_disagree_proposes_nothing(self):
        c = self.by["all_tasks_done_unclosed"]["L-DUP"]
        self.assertTrue(c["duplicate_disagree"])
        self.assertEqual((c["recommended_action"], c["proposed_changes"]), ("record_only", []))
        self.assertEqual(c["alternatives"][0]["action"], "layer_close")
        dup = {d["scope_id"]: d["disagree"] for d in self.report["info"]["duplicate_folders"]}
        self.assertEqual(dup, {"L-DUP": True, "L-CP": False})
        self.assertFalse(self.by["all_tasks_done_unclosed"]["L-B"]["duplicate_disagree"])

    # ---- the 9 kinds
    def test_1_intent_done_registry_open(self):
        c = self.by["intent_done_registry_open"]["L-A"]
        self.assertEqual(c["recommended_action"], "registry_close")
        self.assertEqual(c["proposed_changes"], [{"target": "registry.projects", "scope_id": "L-A", "field": "status",
                                                  "from": "active", "to": "completed"}])
        self.assertEqual(c["resolved_via"], "url")

    def test_2_all_tasks_done_unclosed(self):
        c = self.by["all_tasks_done_unclosed"]["L-B"]
        self.assertEqual(c["recommended_action"], "layer_close")
        targets = [p["target"] for p in c["proposed_changes"]]
        self.assertEqual(targets, ["intent", "backlog.summary", "registry.projects"])
        self.assertFalse(c["backlog"]["has_open_child"])
        c2 = self.by["all_tasks_done_unclosed"]["L-B2"]
        self.assertTrue(c2["backlog"]["has_open_child"])
        self.assertEqual([p["target"] for p in c2["proposed_changes"]], ["intent", "registry.projects"])

    def test_2_deferred_only_is_not_all_done(self):
        self.assertNotIn("L-B3", self.by.get("all_tasks_done_unclosed", {}))
        self.assertIn("L-B3", [i["scope_id"] for i in self.report["info"]["deferred_only_remaining"]])
        self.assertNotIn("L-B3", self.by.get("stale", {}))

    def test_3_completed_project_open_tasks(self):
        c = self.by["completed_project_open_tasks"]["L-C"]
        self.assertEqual(c["recommended_action"], "registry_task_sync")
        self.assertEqual(c["proposed_changes"][0]["task_id"], "T002")
        self.assertEqual(c["proposed_changes"][0]["to"], "完了")
        self.assertTrue(c["primary"])
        self.assertIn("registry_closed_layer_open", c["also"])

    def test_4_folder_missing_reasons(self):
        fm = self.by["folder_missing"]
        self.assertEqual({s: fm[s]["folder_reason"] for s in ("L-D1", "L-D2", "L-D3", "L-D4")},
                         {"L-D1": "notion_only", "L-D2": "empty_url", "L-D3": "path_not_found", "L-D4": "legacy_aipo"})
        self.assertNotIn("L-SECRET", fm)  # Registry completed rows are not listed

    def test_documents_copy_not_indexed_and_notion_falls_back_to_index(self):
        self.assertIn("L-D1", self.by["folder_missing"])  # only a Documents/ copy exists
        c = self.by["registry_task_missing"].get("L-N") or self.by.get("stale", {}).get("L-N")
        self.assertIsNone(c)  # L-N is fresh and fully registered: no candidate
        # resolution check directly
        idx, _, _ = audit_mod.scan_intents(self.f.root)
        self.assertNotIn("L-D1", idx)
        self.assertEqual(self.report["counts"]["resolved_via"]["scope_index"], 3)  # L-N, L-W, L-DUP

    def test_url_normalisations(self):
        # trailing slash (L-B), absolute (L-B2), README.md (L-B3) all resolved via url
        for sid, kind in (("L-B", "all_tasks_done_unclosed"), ("L-B2", "all_tasks_done_unclosed")):
            self.assertEqual(self.by[kind][sid]["resolved_via"], "url")
        idx, _, _ = audit_mod.scan_intents(self.f.root)
        row = {"scope_id": "L-B3", "top_page_url": "Flow/202609/2026-09-01/b3-def/README.md"}
        layer, via, reason, _, _ = audit_mod.resolve(row, self.f.root.resolve(), idx)
        self.assertEqual((via, layer.scope_id), ("url", "L-B3"))

    def test_5_stale_boundary_and_registry_updated_at_ignored(self):
        stale = self.by["stale"]
        self.assertIn("L-E30", stale)
        self.assertEqual(stale["L-E30"]["days_since_touch"], 30)
        self.assertNotIn("L-E29", stale)
        self.assertIn("L-E29", [i["scope_id"] for i in self.report["info"]["watch"]])
        self.assertNotIn("L-EF", stale)
        self.assertEqual(stale["L-E30"]["recommended_action"], "review_stale")

    def test_stale_days_option(self):
        r = audit_mod.audit(self.f.db, self.f.root, TODAY, stale_days=29)
        self.assertIn("L-E29", [c["scope_id"] for c in r["candidates"] if c["kind"] == "stale"])

    def test_confidential_and_jev_eligibility(self):
        s = self.by["stale"]
        self.assertTrue(s["L-EOPT"]["jev_eligible"])  # opt-in, not confidential
        self.assertFalse(s["L-E30"]["jev_eligible"])  # no opt-in
        self.assertEqual(s["L-E30"]["jev_note"], "Jev対象外（opt-in なし）")
        self.assertEqual((s["L-EZET"]["confidential"], s["L-EZET"]["jev_eligible"]), (True, False))
        self.assertEqual(s["L-EZET"]["confidential_reason"], "redact")
        self.assertEqual(s["L-ECH"]["confidential_reason"], "parent:L-SECRET")
        self.assertFalse(s["L-ECH"]["jev_eligible"])
        self.assertEqual(s["L-EPRIV"]["confidential_reason"], "privacy_extension")
        md = (self.out / "report.md").read_text(encoding="utf-8")
        self.assertNotIn("zetaproj-thing", md)
        self.assertNotIn("child-of-secret", md)
        self.assertIn("e-opt", md)
        self.assertNotIn("zetaproj-broken", md)
        self.assertIn("zetaproj-broken/backlog.yaml", [i["path"].split("2026-09-01/")[-1] for i in self.report["info"]["unreadable"]])
        for c in self.report["candidates"]:
            self.assertIsNone(c["jev"])  # T002 never calls Jev

    def test_6_registry_closed_layer_open(self):
        c = self.by["registry_closed_layer_open"]["L-C"]
        self.assertTrue(c["backlog_all_terminal"])
        self.assertEqual(c["recommended_action"], "layer_close")
        f = self.by["registry_closed_layer_open"]["L-F"]
        self.assertFalse(f["backlog_all_terminal"])
        self.assertEqual(f["recommended_action"], "record_only")
        self.assertEqual([a["action"] for a in f["alternatives"]], ["layer_close", "registry_reopen"])

    def test_7_task_status_mismatch(self):
        c = self.by["task_status_mismatch"]["L-F"]
        self.assertEqual(c["proposed_changes"], [{"target": "registry.tasks", "scope_id": "L-F", "task_id": "T002",
                                                  "field": "status", "from": "完了", "to": "未着手"}])
        # L-C T002 is already proposed by class 3: not repeated in class 7 (one change per Registry row)
        self.assertNotIn("L-C", self.by["task_status_mismatch"])

    def test_no_registry_row_changed_by_two_candidates(self):
        keys = [(p["target"], p.get("scope_id") or p.get("path"), p.get("task_id"), p["field"], p.get("op"))
                for c in self.report["candidates"] for p in c["proposed_changes"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_8_registry_task_missing(self):
        c = self.by["registry_task_missing"]["L-G"]
        self.assertEqual(c["evidence"]["missing"], ["T002"])
        self.assertEqual(c["recommended_action"], "record_only")
        self.assertEqual(c["proposed_changes"][0]["op"], "add")
        # a Layer that also has a close candidate gets add_registry_rows (status mapped for cancelled -> 完了)
        b = self.by["registry_task_missing"]["L-B"]
        self.assertEqual(b["recommended_action"], "add_registry_rows")
        self.assertEqual((b["proposed_changes"][0]["task_id"], b["proposed_changes"][0]["to"]), ("T002", "完了"))
        self.assertEqual(self.by["registry_task_missing"]["L-E30"]["recommended_action"], "record_only")

    def test_9_registry_missing(self):
        c = self.by["registry_missing"]["L-H"]
        self.assertEqual(c["recommended_action"], "record_only")
        self.assertNotIn("L-D1", self.by["registry_missing"])  # Documents copy is not a Layer

    def test_all_required_kinds_present(self):
        for k in audit_mod.KINDS:
            self.assertGreaterEqual(self.report["counts"]["by_kind"][k], 1, k)

    def test_info_todo_and_memory(self):
        info = self.report["info"]
        self.assertEqual([i["scope_id"] for i in info["todo_points_to_done"]], ["L-B"])
        self.assertEqual([i["scope_id"] for i in info["todo_layer_path_missing"]], ["L-EF"])
        mm = {i["scope_id"]: i["why"] for i in info["memory_label_mismatch"]}
        self.assertEqual(mm, {"L-9001": "registry_or_intent_completed", "L-9002": "registry_not_completed",
                              "L-9003": "scope_not_in_registry"})

    # ---- constants
    def test_no_own_word_list(self):
        src = Path(audit_mod.__file__).read_text(encoding="utf-8")
        for w in ("経費申請", "人事評価", "役員会", "zetaproj"):
            self.assertNotIn(w, src)

    def test_redact_patterns_generic_and_extra_words(self):
        # generic words (code) + fictional environment words (jts extra file)
        for s in ["キャリアの相談", "経費申請完了", "人事評価", "役員会の資料", "給与テーブル",
                  "Zetaproj の件", "ゼータ案件の整理", "L-9999 の資料", "Flow/202601/2026-01-01/sample-zetagame"]:
            self.assertFalse(jev_client.redact(s)[0], s)
        for s in ["回帰評価の順位付け", "ai-harness-learning", "zetagameplan"]:
            self.assertTrue(jev_client.redact(s)[0], s)


# Registry vocabulary: the schema created by AI-PLC's init_db.py uses English task statuses
SCHEMA_EN = SCHEMA.replace("DEFAULT '未着手' CHECK(status IN ('未着手','進行中','完了'))",
                           "DEFAULT 'planned' CHECK(status IN ('planned','active','completed','paused'))")
# a Japanese schema that also has a completed_at column (must still be read as Japanese)
SCHEMA_JA_COMPLETED_AT = """
CREATE TABLE tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,             -- T001
    scope_id        TEXT NOT NULL,
    name            TEXT NOT NULL,             -- title (Notion)
    status          TEXT NOT NULL DEFAULT '未着手'
                    CHECK(status IN ('未着手','進行中','完了')),
    completed_at    TEXT,                      -- completed
    updated_at      TEXT
)
"""
SCHEMA_NO_CHECK = "CREATE TABLE tasks (id INTEGER PRIMARY KEY, task_id TEXT, scope_id TEXT, status TEXT);"
SQLITE_MAP = {"sync_targets": [{"type": "sqlite", "target_url": ".claude/db/ai_plc.db",
                                "status_map": {"pending": "todo", "in_progress": "doing",
                                               "completed": "done", "blocked": "todo"}}]}


class RegistryVocabTest(unittest.TestCase):
    def _conn(self, schema):
        c = sqlite3.connect(":memory:")
        c.executescript(schema)
        return c

    def test_detect_vocab(self):
        self.assertEqual(audit_mod.detect_task_vocab(self._conn(SCHEMA)), "ja")
        self.assertEqual(audit_mod.detect_task_vocab(self._conn(SCHEMA_EN)), "en")
        self.assertEqual(audit_mod.detect_task_vocab(self._conn(SCHEMA_JA_COMPLETED_AT)), "ja")
        self.assertIsNone(audit_mod.detect_task_vocab(self._conn(SCHEMA_NO_CHECK)))
        self.assertIsNone(audit_mod.detect_task_vocab(self._conn("CREATE TABLE other (x TEXT);")))

    def test_public_schema_file_is_english(self):
        init_db = next((p / "core" / "db" / "init_db.py" for p in Path(__file__).resolve().parents
                        if (p / "core" / "db" / "init_db.py").is_file()), None)
        if init_db is None:
            self.skipTest("core/db/init_db.py not in this checkout")
        src = init_db.read_text(encoding="utf-8")
        i = src.index("CREATE TABLE IF NOT EXISTS tasks")
        ddl = src[i:src.index(");", i) + 2].replace("IF NOT EXISTS ", "")
        self.assertEqual(audit_mod.detect_task_vocab(self._conn(ddl)), "en")

    def test_reg_task_target(self):
        en, ja = audit_mod.task_vocab("en"), audit_mod.task_vocab("ja")
        self.assertEqual([audit_mod.reg_task_target(s, en) for s in ("completed", "cancelled", "in_progress",
                                                                     "pending", "blocked", None)],
                         ["completed", "completed", "active", "planned", "planned", "planned"])
        self.assertEqual([audit_mod.reg_task_target(s, ja) for s in ("completed", "in_progress", "pending")],
                         ["完了", "進行中", "未着手"])
        self.assertEqual(audit_mod.reg_task_target("completed"), "完了")  # default = historical behaviour

    def _english_fixture(self, tmp, schema=None, extra=None):
        f = Fixture.__new__(Fixture)
        f.root = tmp / "repo"
        f.root.mkdir()
        f.db = tmp / "ai_plc.db"
        f.conn = sqlite3.connect(f.db)
        f.conn.executescript(schema or SCHEMA_EN)
        F = "Flow/202609/2026-09-01"
        # 7: backlog completed vs Registry planned; completed rows in English are not mismatches
        f.layer(f"{F}/e-mis", "L-E", "active", [("T001", "completed"), ("T002", "in_progress"), ("T003", "pending")],
                extra=extra)
        f.project("L-E", url=f"{F}/e-mis")
        f.rtask("L-E", "T001", "planned")
        f.rtask("L-E", "T002", "completed")
        # 3: Registry project completed, a task row still planned
        f.layer(f"{F}/c-comp", "L-C", "active", [("T001", "completed")], extra=extra)
        f.project("L-C", "completed", url=f"{F}/c-comp")
        f.rtask("L-C", "T001", "planned")
        # an English Registry with every task completed must not produce task candidates
        f.layer(f"{F}/ok", "L-OK", "active", [("T001", "completed"), ("T002", "pending")], extra=extra)
        f.project("L-OK", url=f"{F}/ok")
        f.rtask("L-OK", "T001", "completed")
        f.rtask("L-OK", "T002", "planned")
        f.close()
        return audit_mod.audit(f.db, f.root, TODAY, memory_path=tmp / "none.md")

    def _changes(self, report, sid, kind):
        c = next((c for c in report["candidates"] if c["scope_id"] == sid and c["kind"] == kind), None)
        return None if c is None else {(ch.get("task_id"), ch["from"], ch["to"]) for ch in c["proposed_changes"]}

    def test_english_registry(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._english_fixture(Path(d))
        self.assertEqual(self._changes(r, "L-E", "task_status_mismatch"),
                         {("T001", "planned", "completed"), ("T002", "completed", "active")})
        self.assertEqual(self._changes(r, "L-E", "registry_task_missing"), {("T003", None, "planned")})
        self.assertEqual(self._changes(r, "L-C", "completed_project_open_tasks"), {("T001", "planned", "completed")})
        self.assertIsNone(self._changes(r, "L-OK", "task_status_mismatch"))
        self.assertIsNone(self._changes(r, "L-OK", "completed_project_open_tasks"))

    def test_status_map_used_only_for_english_or_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._english_fixture(Path(d), extra=SQLITE_MAP)
        self.assertEqual(self._changes(r, "L-E", "task_status_mismatch"), {("T001", "planned", "done"),
                                                                           ("T002", "completed", "doing")})
        self.assertEqual(self._changes(r, "L-E", "registry_task_missing"), {("T003", None, "todo")})
        # a Japanese DB keeps the historical mapping even when the Layer has its own status_map
        with tempfile.TemporaryDirectory() as d:
            t = Path(d)
            f = Fixture(t)
            f.layer("Flow/202609/2026-09-01/j", "L-J", "active", [("T001", "completed"), ("T002", "pending")],
                    extra=SQLITE_MAP)
            f.project("L-J", url="Flow/202609/2026-09-01/j")
            f.rtask("L-J", "T001", "未着手")
            f.close()
            r = audit_mod.audit(f.db, f.root, TODAY, memory_path=t / "none.md")
        self.assertEqual(self._changes(r, "L-J", "task_status_mismatch"), {("T001", "未着手", "完了")})
        self.assertEqual(self._changes(r, "L-J", "registry_task_missing"), {("T002", None, "未着手")})


if __name__ == "__main__":
    unittest.main()
