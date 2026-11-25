#!/usr/bin/env python3
"""一覧の並び順（更新順）の根拠 project_activity.py と、画面の並べ替え・伏せ方の回帰テスト。
一時フォルダだけを使う。画面のテストは node があるときだけ（無ければ skip）。"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.dont_write_bytecode = True
import project_activity as pa  # noqa: E402
import server  # noqa: E402
import test_viewer as tv  # noqa: E402

SID = "L-9928"
NOW = datetime(2099, 6, 1, tzinfo=timezone.utc)


class Row(dict):
    def keys(self):
        return super().keys()


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rv_act_")
        self.root = Path(self.tmp.name)
        self.rel = "Flow/209901/2099-01-01/sample-layer"
        self.layer = self.root / self.rel
        self.layer.mkdir(parents=True)
        self.row = Row(scope_id=SID, created_at="2099-01-02")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text, mtime):
        p = self.layer / name
        p.write_text(text, encoding="utf-8")
        os.utime(p, (mtime.timestamp(), mtime.timestamp()))
        return p

    def ev(self, rel=None, row=None):
        return pa.evidence(self.root, self.rel if rel is None else rel, row or self.row, now=NOW)

    def test_newest_of_backlog_and_context(self):
        self.write("backlog.yaml", "tasks: []\n", NOW - timedelta(days=3))
        self.write("context.yaml", "artifacts: []\n", NOW - timedelta(days=1))
        e = self.ev()
        self.assertEqual((e["kind"], e["source"], e["precision"]), ("local_save", "context.yaml", "second"))
        self.assertEqual(e["path"], f"{self.rel}/context.yaml")
        self.assertTrue(e["at"].endswith("+09:00"))

    def test_intent_used_only_when_both_missing(self):
        self.write("intent.yaml", f"scope_id: {SID}\n", NOW - timedelta(days=5))
        self.assertEqual(self.ev()["source"], "intent.yaml")
        self.write("backlog.yaml", "tasks: []\n", NOW - timedelta(days=9))
        self.assertEqual(self.ev()["source"], "backlog.yaml")

    def test_other_scope_id_rejected(self):
        self.write("backlog.yaml", "scope_id: L-0000\ntasks: []\n", NOW - timedelta(days=1))
        e = self.ev()
        self.assertEqual(e["kind"], "unknown")
        self.assertTrue(any("YAML内容不正" in w for w in e["warnings"]))

    def test_future_mtime_ignored(self):
        self.write("backlog.yaml", "tasks: []\n", NOW + timedelta(days=1))
        e = self.ev()
        self.assertEqual(e["kind"], "unknown")
        self.assertTrue(any("未来" in w for w in e["warnings"]))

    def test_symlink_not_followed(self):
        target = self.root / "outside.yaml"
        target.write_text("tasks: []\n", encoding="utf-8")
        (self.layer / "backlog.yaml").symlink_to(target)
        e = self.ev()
        self.assertEqual(e["kind"], "unknown")
        self.assertTrue(e["warnings"])

    def test_symlinked_layer_dir_not_followed(self):
        real = self.root / "real-layer"
        real.mkdir()
        (real / "backlog.yaml").write_text("tasks: []\n", encoding="utf-8")
        link = self.root / "Flow" / "linked"
        link.symlink_to(real)
        self.assertEqual(self.ev(rel="Flow/linked")["kind"], "unknown")

    def test_fifo_not_read(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("mkfifo なし")
        os.mkfifo(self.layer / "backlog.yaml")
        e = self.ev()
        self.assertEqual(e["kind"], "unknown")
        self.assertTrue(any("通常YAML" in w for w in e["warnings"]))

    def test_too_large_ignored(self):
        self.write("backlog.yaml", "tasks: []\n# " + "x" * (pa.LIMIT + 10) + "\n", NOW - timedelta(days=1))
        self.assertEqual(self.ev()["kind"], "unknown")

    def test_bad_rel_rejected(self):
        e = self.ev(rel="../outside")
        self.assertEqual(e["kind"], "unknown")
        self.assertTrue(any("参照先不正" in w for w in e["warnings"]))

    def test_no_layer_uses_created_at(self):
        e = pa.evidence(self.root, None, self.row, now=NOW)
        self.assertEqual((e["kind"], e["precision"]), ("created", "day"))
        e = pa.evidence(self.root, None, Row(scope_id=SID, created_at="2199-01-01"), now=NOW)
        self.assertEqual(e["kind"], "unknown")

    def test_parse_time(self):
        self.assertEqual(pa.parse_time("2099-01-02T03:04:05Z", NOW)[1], "second")
        self.assertIsNone(pa.parse_time("2099-01-02T03:04:05+25:00", NOW))
        self.assertIsNone(pa.parse_time("not a date", NOW))

    def test_order_key(self):
        def p(sid, kind, ms):
            return {"scope_id": sid, "activity": {"kind": kind, "epoch_ms": ms}}
        items = [p("L-9005-12", "unknown", None), p("L-9005-2", "unknown", None), p("L-9001", "created", 5),
                 p("L-9002", "local_save", 1), p("L-9003", "local_save", 9)]
        self.assertEqual([x["scope_id"] for x in sorted(items, key=pa.order_key)],
                         ["L-9003", "L-9002", "L-9001", "L-9005-2", "L-9005-12"])

    def test_reading_does_not_write(self):
        p = self.write("backlog.yaml", "tasks: []\n", NOW - timedelta(days=1))
        before = (p.read_bytes(), p.stat().st_mtime_ns)
        self.ev()
        self.assertEqual(before, (p.read_bytes(), p.stat().st_mtime_ns))


class ApiTests(tv.DataBase):
    def setUp(self):
        super().setUp()
        self.reg = server.Registry(self.db, self.root, readonly_reason="テスト")

    def test_list_has_activity_and_notice(self):
        data = self.reg.list_projects()
        self.assertEqual(data["activity_notice"], pa.NOTICE)
        by = {p["scope_id"]: p for p in data["projects"]}
        self.assertEqual(by["L-9001"]["activity"]["kind"], "local_save")
        self.assertEqual(by["L-9002"]["activity"]["kind"], "created")  # Layer なし
        ranks = [{"local_save": 0, "created": 1, "unknown": 2}[p["activity"]["kind"]] for p in data["projects"]]
        self.assertEqual(ranks, sorted(ranks))

    def test_recently_saved_layer_first(self):
        old = datetime.now().timestamp() - 86400
        for folder in ("parent-layer", "child-layer", "done-layer"):
            for f in (self.flow / folder).glob("*.yaml"):
                os.utime(f, (old, old))
        p = self.flow / "done-layer" / "backlog.yaml"
        p.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertEqual(self.reg.list_projects()["projects"][0]["scope_id"], "L-9003")
        self.assertEqual(self.reg.project_detail("L-9003")["activity"]["source"], "backlog.yaml")


NODE = shutil.which("node")
INDEX = HERE.parent / "static" / "index.html"

UI_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const els = {};
const el = () => new Proxy({ style: {}, dataset: {}, hidden: false, value: "", innerHTML: "", textContent: "",
  querySelectorAll: () => [], setAttribute() {}, addEventListener() {} }, {});
const ctx = { console, JSON, Map, Set, Number, String, Array, Object, Math, Promise, Error, setTimeout, clearTimeout,
  localStorage: { getItem: () => null, setItem() {} }, location: { hash: "" },
  window: { addEventListener() {} }, navigator: {},
  document: { getElementById: (id) => (els[id] = els[id] || el()) },
  fetch: () => new Promise(() => {}) };
vm.createContext(ctx);
vm.runInContext(script + "\n;this.__t = { st, tree, matches, renderList, label, pname, progName, bizName, activityText };", ctx);
const t = ctx.__t;
const act = (ms) => ({ kind: "local_save", epoch_ms: ms, at: "2099-01-01T00:00:00+09:00", source: "backlog.yaml", warnings: [] });
const P = (sid, ms, extra) => Object.assign({ scope_id: sid, name: "合成 " + sid, status: "active", parent_scope: null,
  start_date: "2099-01-0" + (sid.length % 9 + 1), progress: { done: 0, total: 0 }, issues: 0, confidential: false,
  hash_id: "C-" + sid, classification: null, membership: null, activity: act(ms) }, extra || {});
const projects = [P("L-9001", 10), P("L-9001-SG1", 50, { parent_scope: "L-9001" }), P("L-9002", 30),
  P("L-9003", 20, { confidential: true, membership: { program: { uid: "PG-2", name: "合成の私生活", sensitive: true, masked: "PG-abc123" },
    program_source: "direct", primary_business: { uid: "B-2", display_id: "BIZ-0002", name: "合成の業務B", sensitive: true }, related_business: [] } })];
t.st.data = { projects, membership: null, counts: { by_status: {} } };
const out = {};
t.st.sort = "updated"; out.updated = t.tree().roots.map((p) => p.scope_id);
t.st.sort = "id"; out.id = t.tree().roots.map((p) => p.scope_id);
t.st.filter = new Set(["active"]); t.st.sort = "updated";
projects[1].status = "completed"; out.filtered = t.tree().roots.map((p) => p.scope_id);
t.st.share = true;
out.masked = [t.label(projects[3]), t.pname(projects[3]), t.activityText(projects[3])];
out.prog = t.progName(projects[3].membership.program);
out.biz = t.bizName(projects[3].membership.primary_business);
t.st.share = false;
out.prog_plain = t.progName(projects[3].membership.program);
console.log(JSON.stringify(out));
"""


@unittest.skipIf(NODE is None, "node が見つかりません")
class UiTests(unittest.TestCase):
    def run_ui(self):
        with tempfile.TemporaryDirectory(prefix="rv_ui_") as d:
            h = Path(d) / "harness.js"
            h.write_text(UI_HARNESS, encoding="utf-8")
            r = subprocess.run([NODE, str(h), str(INDEX)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_sort_filter_and_mask(self):
        out = self.run_ui()
        # 更新順: 子 L-9001-SG1（50）の更新が親 L-9001 のグループ順位に反映される
        self.assertEqual(out["updated"], ["L-9001", "L-9002", "L-9003"])
        self.assertEqual(out["id"], ["L-9001", "L-9002", "L-9003"])
        # 子が絞り込みで外れると、親は自分の更新時刻で並ぶ
        self.assertEqual(out["filtered"], ["L-9002", "L-9003", "L-9001"])
        self.assertEqual(out["masked"], ["C-L-9003", "（機密のため非表示）", "更新情報は非表示"])
        self.assertEqual((out["prog"], out["biz"], out["prog_plain"]), ("PG-abc123", "BIZ-0002", "合成の私生活"))

    def test_page_has_no_scope_ids(self):
        """画面の文言に案件の ID を書かない"""
        html = INDEX.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\bL-\d{4}\b", html))


if __name__ == "__main__":
    unittest.main()
