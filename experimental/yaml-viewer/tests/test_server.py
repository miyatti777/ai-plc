"""YamlViewer のテスト（合成の箱を一時フォルダに作って検証する。本物の箱には触らない）。

実行: python3 -m unittest discover -s tools/YamlViewer/tests
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

HYP = "hypotheses:\n- {id: H1, kind: validation, claim: 合成の主張, status: unknown, sources: [Context/x.md]}\n"
ISS = "charter: {change_conditions: ['[unknown]'], exit_conditions: ['[unknown]']}\nissues:\n- {id: I1, question: 合成の問い, status: open, priority: '[unknown]', owner: '[unknown]', due: undecided, sources: [H1]}\n"
WBS = "wbs:\n- {id: W1, deliverable: 成果, exit_criteria: 条件, owner: x, status: draft, milestone_id: MS1, schedule: {forecast: {start: '2026-01-01', end: '2026-01-02'}}}\n- {id: W1.1, deliverable: 子, exit_criteria: 条件, owner: x, status: draft, milestone_id: MS1}\n"
RM = "roadmap:\n- {id: MS1, milestone: 節目, period: 2026-01-01〜2026-01-31, status: planned, wbs_ids: [W1]}\n"
TODO = "todo:\n- {id: D1, title: やること, status: todo, owner: x, wbs_id: W1, due: '2026-01-05', source: I1}\n"
INTENT = "scope_id: L-TEST\ndisplay_name: 合成の Layer\ngoal: {description: 仮}\n"


def make_box(root: Path, form: str) -> Path:
    layer = root / "202610" / "2026-10-28" / f"box-{form}"
    reg = layer / ("Sheets" if form == "sheets" else "Documents/aipm_project/registers")
    reg.mkdir(parents=True)
    (layer / "intent.yaml").write_text(INTENT.replace("L-TEST", f"L-{form}"), encoding="utf-8")
    for name, body in (("hypotheses", HYP), ("issues", ISS), ("wbs", WBS), ("roadmap", RM), ("todo", TODO)):
        (reg / f"{name}.yaml").write_text(body, encoding="utf-8")
    return layer


def touch_later(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        flow = cls.root / "Flow"
        cls.sheets = make_box(flow, "sheets")
        cls.old = make_box(flow, "registers")
        # Flow の外（worktree を模す）の箱を --path で渡す
        cls.outside = make_box(cls.root / "elsewhere", "sheets")
        server.RELOAD_TTL = 0.0
        cls.srv = server.build_server([cls.outside], 0, cls.root, flow=True)
        cls.port = cls.srv.server_address[1]
        cls.th = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.th.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close(); cls.tmp.cleanup()

    def get(self, path, host="127.0.0.1", method="GET"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest(method, path, skip_host=True); c.putheader("Host", f"{host}:{self.port}"); c.endheaders()
        r = c.getresponse(); body = r.read(); c.close()
        return r.status, body

    def test_list_has_both_forms_and_fixed_path(self):
        st, body = self.get("/api/list"); self.assertEqual(st, 200)
        items = json.loads(body)["items"]
        forms = {(i["origin"], i["form"]) for i in items}
        self.assertIn(("path", "sheets"), forms)
        self.assertIn(("flow", "sheets"), forms)
        self.assertIn(("flow", "registers"), forms)
        self.assertEqual(items[0]["origin"], "path")  # --path が先頭

    def test_state_rows_and_charter(self):
        st, body = self.get("/api/state?i=0"); self.assertEqual(st, 200)
        j = json.loads(body); self.assertTrue(j["ok"])
        self.assertEqual([r["id"] for r in j["files"]["wbs"]["rows"]], ["W1", "W1.1"])
        self.assertEqual(j["files"]["issues"]["charter"]["exit_conditions"], ["[unknown]"])
        self.assertTrue(j["files"]["intent"]["exists"])
        self.assertEqual(j["files"]["intent"]["data"]["scope_id"], "L-sheets")

    def test_broken_yaml_keeps_last_good(self):
        st, body = self.get("/api/list"); items = json.loads(body)["items"]
        idx = next(i["index"] for i in items if i["origin"] == "flow" and i["form"] == "registers")
        _, body = self.get(f"/api/state?i={idx}")
        self.assertEqual(json.loads(body)["files"]["todo"]["rows"][0]["id"], "D1")
        p = self.old / "Documents/aipm_project/registers/todo.yaml"
        touch_later(p, "todo:\n- {id: D1, title: [壊れ\n")
        _, body = self.get(f"/api/state?i={idx}")
        f = json.loads(body)["files"]["todo"]
        self.assertTrue(f["error"]); self.assertEqual(f["rows"][0]["id"], "D1")
        touch_later(p, TODO)
        _, body = self.get(f"/api/state?i={idx}")
        self.assertIsNone(json.loads(body)["files"]["todo"]["error"])

    def test_read_only_and_local_only(self):
        st, body = self.get("/api/state?i=0", method="POST"); self.assertEqual(st, 405)
        st, _ = self.get("/api/list", host="evil.example"); self.assertEqual(st, 403)
        st, _ = self.get("/api/state?i=abc"); self.assertEqual(st, 400)
        st, body = self.get("/api/state?i=999"); self.assertFalse(json.loads(body)["ok"])
        st, _ = self.get("/../server.py"); self.assertEqual(st, 404)

    def test_static_served(self):
        for p in ("/", "/app.js", "/style.css"):
            st, body = self.get(p); self.assertEqual(st, 200); self.assertTrue(body)


    def test_unjsonable_yaml_does_not_break_response(self):
        st, body = self.get("/api/list"); items = json.loads(body)["items"]
        idx = next(i["index"] for i in items if i["origin"] == "flow" and i["form"] == "sheets")
        ctx = self.sheets / "context.yaml"
        touch_later(ctx, "generated_at: 2026-10-28\nhistory: {2026-10-28: x, 1.5: y}\nn: .nan\n")
        st, body = self.get(f"/api/state?i={idx}"); self.assertEqual(st, 200)
        f = json.loads(body)["files"]["context"]
        self.assertIsNone(f["error"]); self.assertEqual(f["data"]["history"]["2026-10-28"], "x")
        self.assertEqual(f["data"]["generated_at"], "2026-10-28"); self.assertEqual(f["data"]["n"], "nan")
        touch_later(ctx, "a: &a\n  self: *a\n")
        st, body = self.get(f"/api/state?i={idx}"); self.assertEqual(st, 200)
        f = json.loads(body)["files"]["context"]
        self.assertTrue(f["error"]); self.assertEqual(f["data"]["history"]["2026-10-28"], "x")  # 最後の正常な状態

    def test_same_mtime_fix_is_reread_while_in_error(self):
        st, body = self.get("/api/list"); items = json.loads(body)["items"]
        idx = next(i["index"] for i in items if i["origin"] == "flow" and i["form"] == "sheets")
        p = self.sheets / "Sheets" / "roadmap.yaml"
        st0 = p.stat()
        p.write_text("roadmap: [\n", encoding="utf-8"); os.utime(p, ns=(st0.st_atime_ns, st0.st_mtime_ns))
        _, body = self.get(f"/api/state?i={idx}")
        # サイズが変わったので読み直され、エラーになる
        self.assertTrue(json.loads(body)["files"]["roadmap"]["error"])
        p.write_text(RM, encoding="utf-8"); os.utime(p, ns=(st0.st_atime_ns, st0.st_mtime_ns))  # 元の mtime・サイズに戻す
        _, body = self.get(f"/api/state?i={idx}")
        self.assertIsNone(json.loads(body)["files"]["roadmap"]["error"])

    def test_shape_warning_and_unicode_digit(self):
        st, body = self.get("/api/list"); items = json.loads(body)["items"]
        idx = next(i["index"] for i in items if i["origin"] == "flow" and i["form"] == "sheets")
        p = self.sheets / "Sheets" / "hypotheses.yaml"
        touch_later(p, "- H1\n")
        _, body = self.get(f"/api/state?i={idx}")
        f = json.loads(body)["files"]["hypotheses"]
        self.assertIn("形が契約と違います", f["error"]); self.assertEqual(f["rows"], [])
        touch_later(p, HYP)
        st, _ = self.get("/api/state?i=%C2%B2"); self.assertEqual(st, 400)

    def test_symlink_outside_is_not_read(self):
        with tempfile.TemporaryDirectory() as d:
            outside = Path(d) / "secret.yaml"; outside.write_text("todo: [{id: D9, title: 外, status: todo, owner: x}]", encoding="utf-8")
            reg = Path(d) / "box" / "Sheets"; reg.mkdir(parents=True)
            (reg / "todo.yaml").symlink_to(outside)
            yf = server.YamlFile(reg / "todo.yaml", reg)
            r = yf.read(); self.assertTrue(r["error"]); self.assertIsNone(r["data"])


    def test_layer_only_path_has_layer_files_but_no_box(self):
        with tempfile.TemporaryDirectory() as d:
            layer = Path(d) / "layer-only"; layer.mkdir()
            (layer / "intent.yaml").write_text(INTENT, encoding="utf-8")
            (layer / "backlog.yaml").write_text("tasks:\n- {id: T001, name: 作る, status: pending, priority: P0, dependencies: []}\n", encoding="utf-8")
            (layer / "context.yaml").write_text("context_documents:\n- {name: 資料, url: '@Context/01.md', summary: 要約}\n", encoding="utf-8")
            src = server.Source(0, layer, Path(d), "path")
            h = src.head(); self.assertFalse(h["has_registers"]); self.assertTrue(h["has_layer"]); self.assertIsNone(h["form"])
            st = src.state()
            self.assertEqual(set(st["files"]), {"intent", "context", "backlog"})
            self.assertEqual(st["files"]["backlog"]["data"]["tasks"][0]["id"], "T001")
            self.assertEqual(st["files"]["context"]["data"]["context_documents"][0]["name"], "資料")


    def test_plain_yaml_file_and_file_inside_box(self):
        with tempfile.TemporaryDirectory() as d:
            plain = Path(d) / "conf" / "settings.yaml"; plain.parent.mkdir()
            plain.write_text("name: x\nitems:\n- {id: 1, title: a}\n- {id: 2, title: b}\n", encoding="utf-8")
            src = server.Source(0, plain, Path(d), "path")
            h = src.head(); self.assertEqual(h["form"], "plain"); self.assertEqual(h["opened"], "settings"); self.assertFalse(h["has_layer"])
            st = src.state(); self.assertEqual(list(st["files"]), ["plain"]); self.assertEqual(st["files"]["plain"]["data"]["name"], "x")
            layer = make_box(Path(d) / "F", "sheets")
            inbox = server.Source(1, layer / "Sheets" / "wbs.yaml", Path(d), "path")
            self.assertEqual(inbox.head()["form"], "sheets"); self.assertEqual(inbox.head()["opened"], "wbs"); self.assertIsNone(inbox.plain)
            atroot = server.Source(2, layer / "intent.yaml", Path(d), "path")
            self.assertTrue(atroot.head()["has_layer"]); self.assertIsNone(atroot.plain)
            docs = layer / "Documents"; docs.mkdir(); memo = docs / "memo.yaml"; memo.write_text("k: v\n", encoding="utf-8")
            indocs = server.Source(3, memo, Path(d), "path")
            self.assertEqual(indocs.head()["form"], "plain")


    def test_plain_rule_scalar_and_hard_error(self):
        with tempfile.TemporaryDirectory() as d:
            layer = make_box(Path(d) / "F", "sheets")
            # Layer 直下・Sheets の中の契約外ファイルは一般の YAML
            (layer / "variables.yaml").write_text("x: 1\n", encoding="utf-8")
            (layer / "Sheets" / "meta.yaml").write_text("y: 2\n", encoding="utf-8")
            self.assertEqual(server.Source(0, layer / "variables.yaml", Path(d), "path").head()["form"], "plain")
            self.assertEqual(server.Source(1, layer / "Sheets" / "meta.yaml", Path(d), "path").head()["form"], "plain")
            # 無関係なフォルダの todo.yaml（隣に registers の別ファイルが無い）も一般の YAML
            lone = Path(d) / "lone"; lone.mkdir(); (lone / "todo.yaml").write_text("todo: 5\n", encoding="utf-8")
            self.assertEqual(server.Source(2, lone / "todo.yaml", Path(d), "path").head()["form"], "plain")
            # 最上位がスカラー
            sc = lone / "hello.yaml"; sc.write_text("hello world\n", encoding="utf-8")
            self.assertEqual(server.Source(3, sc, Path(d), "path").state()["files"]["plain"]["data"], "hello world")
            # 複数ドキュメント
            md = lone / "multi.yaml"; md.write_text("a: 1\n---\nb: 2\n", encoding="utf-8")
            self.assertEqual(server.Source(4, md, Path(d), "path").state()["files"]["plain"]["data"], [{"a": 1}, {"b": 2}])
            # 大きすぎる: 同じ mtime では読み直さない
            big = lone / "big.yaml"; big.write_text("k: v\n", encoding="utf-8")
            old = server.MAX_BYTES; server.MAX_BYTES = 2
            try:
                yf = server.YamlFile(big, lone); r1 = yf.read(); self.assertIn("大きすぎます", r1["error"])
                calls = []
                orig = server._read_yaml
                server._read_yaml = lambda *a, **k: (calls.append(1), orig(*a, **k))[1]
                yf._checked = 0.0; yf.read()
                self.assertEqual(calls, [])  # 読み直していない
            finally:
                server.MAX_BYTES = old; server._read_yaml = orig
            self.assertEqual(server._key_name(True), "true"); self.assertEqual(server._key_name(None), "null")

    def test_find_by_scope_id(self):
        st, body = self.get("/api/find?layer=L-registers"); self.assertEqual(st, 200)
        j = json.loads(body); self.assertTrue(j["ok"])
        st, body = self.get(f"/api/state?i={j['index']}")
        d = json.loads(body); self.assertEqual(d["scope_id"], "L-registers"); self.assertEqual(d["form"], "registers")
        # --path で渡した置き場と Flow の箱が同じ scope_id のときは、--path の方（渡した順が先）
        st, body = self.get("/api/find?layer=L-sheets"); j = json.loads(body)
        self.assertEqual(json.loads(self.get(f"/api/state?i={j['index']}")[1])["origin"], "path")

    def test_find_rejects_bad_and_unknown(self):
        st, body = self.get("/api/find?layer=L-does-not-exist"); j = json.loads(body)
        self.assertEqual(st, 200); self.assertFalse(j["ok"]); self.assertIn("見つかりません", j["error"])
        for bad in ("", "..%2F..%2Fetc", "%2FUsers%2Fx", "a%20b", "L-" + "x" * 90):
            st, _ = self.get(f"/api/find?layer={bad}"); self.assertEqual(st, 400, bad)
        st, _ = self.get("/api/find"); self.assertEqual(st, 400)
        st, _ = self.get("/api/find?layer=L-sheets", method="POST"); self.assertEqual(st, 405)
        st, _ = self.get("/api/find?layer=L-sheets", host="evil.example"); self.assertEqual(st, 403)


class FindTest(unittest.TestCase):
    """起動した後に Flow が変わる場合（ServerTest の箱の並びを変えないよう、別の一時フォルダと別のサーバで確かめる）。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.flow = cls.root / "Flow"
        make_box(cls.flow, "sheets")
        server.RELOAD_TTL = 0.0
        cls.srv = server.build_server([], 0, cls.root, flow=True)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close(); cls.tmp.cleanup()

    get = ServerTest.get

    def test_find_new_box_without_restart(self):
        # 起動した後にできた箱は、SCAN_TTL を待たずに /api/find で拾う（一覧にはまだ無い）
        new = self.flow / "202610" / "2026-10-28" / "box-late"
        (new / "Sheets").mkdir(parents=True)
        (new / "intent.yaml").write_text(INTENT.replace("L-TEST", "L-late"), encoding="utf-8")
        (new / "Sheets" / "todo.yaml").write_text(TODO, encoding="utf-8")
        (new / "Sheets" / "wbs.yaml").write_text(WBS, encoding="utf-8")
        before = [it["scope_id"] for it in json.loads(self.get("/api/list")[1])["items"]]
        self.assertNotIn("L-late", before)
        st, body = self.get("/api/find?layer=L-late"); j = json.loads(body)
        self.assertEqual(st, 200); self.assertTrue(j["ok"])
        d = json.loads(self.get(f"/api/state?i={j['index']}")[1])
        self.assertEqual(d["scope_id"], "L-late"); self.assertTrue(d["has_registers"])
        self.assertEqual(d["files"]["todo"]["rows"][0]["id"], "D1")

    def test_find_layer_then_box_created(self):
        # 箱の無い Layer も scope_id で開ける。後から箱ができたら、次の /api/find で箱つきになる
        layer = self.flow / "202610" / "2026-10-28" / "no-box-yet"
        layer.mkdir(parents=True)
        (layer / "intent.yaml").write_text(INTENT.replace("L-TEST", "L-nobox"), encoding="utf-8")
        j = json.loads(self.get("/api/find?layer=L-nobox")[1]); self.assertTrue(j["ok"])
        d = json.loads(self.get(f"/api/state?i={j['index']}")[1])
        self.assertFalse(d["has_registers"]); self.assertTrue(d["has_layer"])
        (layer / "Sheets").mkdir()
        (layer / "Sheets" / "todo.yaml").write_text(TODO, encoding="utf-8")
        j2 = json.loads(self.get("/api/find?layer=L-nobox")[1])
        self.assertEqual(j2["index"], j["index"])
        d = json.loads(self.get(f"/api/state?i={j['index']}")[1])
        self.assertTrue(d["has_registers"]); self.assertEqual(d["files"]["todo"]["rows"][0]["id"], "D1")
        # 消えたファイルは、最後の正常な行を残したままエラーを返す（画面はこれを「読めません」に数える）。一度も無いファイルは行なし
        (layer / "Sheets" / "todo.yaml").unlink()
        f = json.loads(self.get(f"/api/state?i={j['index']}")[1])["files"]
        self.assertFalse(f["todo"]["exists"]); self.assertTrue(f["todo"]["error"]); self.assertEqual(f["todo"]["rows"][0]["id"], "D1")
        self.assertFalse(f["hypotheses"]["exists"]); self.assertEqual(f["hypotheses"]["rows"], [])


class HelperTest(unittest.TestCase):
    def test_jsonable(self):
        import datetime
        v = {datetime.date(2026, 1, 1): [float("nan"), datetime.datetime(2026, 1, 1, 9, 0)], 1: None}
        self.assertEqual(server._jsonable(v), {"2026-01-01": ["nan", "2026-01-01 09:00:00"], "1": None})
        a = {}; a["self"] = a
        with self.assertRaises(ValueError):
            server._jsonable(a)

    def test_registers_dir_of(self):
        with tempfile.TemporaryDirectory() as d:
            layer = make_box(Path(d), "registers")
            reg = layer / "Documents/aipm_project/registers"
            self.assertEqual(server.registers_dir_of(layer), reg)
            self.assertEqual(server.registers_dir_of(reg), reg)
            self.assertEqual(server.layer_dir_of(reg), layer)
            self.assertIsNone(server.registers_dir_of(Path(d)))


if __name__ == "__main__":
    unittest.main()
