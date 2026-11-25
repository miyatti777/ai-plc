"""ppm-collection の collect.py・project_match.py のテスト。案件・Program の名前は全部架空。"""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import collect  # noqa: E402
import project_match as pm  # noqa: E402

BUSINESS_DDL = """
CREATE TABLE programs(program_uid TEXT PRIMARY KEY, display_name TEXT, read_domain TEXT);
CREATE TABLE business_projects(business_uid TEXT PRIMARY KEY, display_name TEXT, purpose TEXT, state TEXT);
CREATE TABLE business_project_links(project_id INTEGER, business_uid TEXT, relation_type TEXT, state TEXT);
CREATE TABLE program_memberships(project_id INTEGER, business_uid TEXT, program_uid TEXT, target_kind TEXT, state TEXT);
"""
PROJECTS_DDL = "CREATE TABLE projects(id INTEGER PRIMARY KEY, scope_id TEXT UNIQUE, name TEXT, goal TEXT, status TEXT, top_page_url TEXT);"


def make_db(path: Path, sql: str, business: bool = True):
    con = sqlite3.connect(path)
    con.executescript(PROJECTS_DDL + (BUSINESS_DDL if business else "") + sql)
    con.commit()
    con.close()


def make_layer(root: Path, rel: str, intent: dict, context: dict | None = None):
    d = root / rel
    d.mkdir(parents=True)
    (d / "intent.yaml").write_text(json.dumps(intent, ensure_ascii=False), encoding="utf-8")
    if context is not None:
        (d / "context.yaml").write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "test.db"
        make_db(self.db, """
        INSERT INTO programs VALUES('prg_work','仕事','work'),('prg_priv','くらし','private');
        INSERT INTO projects VALUES(1,'L-0001','請求書入力UI改修','請求書の項目を画面で入力できるようにする','active','Flow/sample/invoice-edit');
        INSERT INTO projects VALUES(2,'L-0002','invoice-mvp','請求書の最小版','completed','Flow/sample/invoice-mvp');
        INSERT INTO projects VALUES(3,'L-0003','在庫の棚卸し','在庫の棚卸しの復旧','cancelled','Flow/sample/stock');
        INSERT INTO projects VALUES(4,'S-0004','請求書のテンプレート集','いつか請求書の雛形を集める','planned',NULL);
        INSERT INTO projects VALUES(5,'L-0005','旅行の計画を立てる','旅行の行き先と日程','active','Flow/sample/trip');
        INSERT INTO projects VALUES(6,'L-0006','外部ページの案件','請求書を外部のページで試す','active','https://example.com/page');
        INSERT INTO program_memberships VALUES(1,NULL,'prg_work','aiplc_project','confirmed');
        INSERT INTO program_memberships VALUES(2,NULL,'prg_work','aiplc_project','confirmed');
        INSERT INTO program_memberships VALUES(3,NULL,'prg_work','aiplc_project','confirmed');
        INSERT INTO program_memberships VALUES(5,NULL,'prg_priv','aiplc_project','confirmed');
        INSERT INTO program_memberships VALUES(6,NULL,'prg_work','aiplc_project','confirmed');
        """)
        make_layer(self.root, "Flow/sample/invoice-edit",
                   {"scope_id": "L-0001", "display_name": "請求書の項目の入力", "status": "active",
                    "goal": {"description": "請求書の項目を画面で入力できる",
                             "success_criteria": ["下書きを保存できる", "a", "b", "c", "d"]}},
                   {"context_documents": [{"name": "既存の画面", "summary": "項目は表計算に手入力"}]})
        make_layer(self.root, "Flow/sample/invoice-mvp", {"scope_id": "L-0002", "goal": "請求書の最小版"})
        make_layer(self.root, "Flow/sample/trip", {"scope_id": "L-0005", "goal": {"description": "旅行の計画"}})

    def tearDown(self):
        self.tmp.cleanup()

    def run_collect(self, text, **kw):
        return collect.collect(self.root, text, self.db, **kw)

    def test_all_statuses_are_candidates_with_labels(self):
        out = self.run_collect("請求書の項目を入力したい")
        by = {c["scope_id"]: c for c in out["candidates"]}
        self.assertEqual(by["L-0001"]["status_label"], "進行中")
        self.assertEqual(by["L-0002"]["status_label"], "済み")
        self.assertEqual(by["S-0004"]["status_label"], "いつかやる")
        self.assertIsNone(by["S-0004"]["layer"])
        self.assertFalse(by["S-0004"]["layer_detail"]["read"])
        self.assertEqual(out["candidates"][0]["scope_id"], "L-0001")
        self.assertNotIn("in_todo", by["L-0001"])  # 公開版は TODO の一覧を読まない

    def test_cancelled_is_candidate(self):
        out = self.run_collect("在庫の棚卸しをやりたい")
        c = [c for c in out["candidates"] if c["scope_id"] == "L-0003"][0]
        self.assertEqual(c["status_label"], "やめた")

    def test_layer_detail_reads_intent_and_context(self):
        out = self.run_collect("請求書の項目を入力したい")
        d = [c for c in out["candidates"] if c["scope_id"] == "L-0001"][0]["layer_detail"]
        self.assertTrue(d["read"])
        self.assertEqual(d["display_name"], "請求書の項目の入力")
        self.assertEqual(len(d["success_criteria"]), collect.SC_MAX)
        self.assertEqual(d["context"][0]["name"], "既存の画面")
        mvp = [c for c in out["candidates"] if c["scope_id"] == "L-0002"][0]["layer_detail"]
        self.assertEqual(mvp["goal"], "請求書の最小版")  # goal が文字列の古い形も読む

    def test_url_row_has_no_layer(self):
        out = self.run_collect("請求書を外部のページで試す")
        c = [c for c in out["candidates"] if c["scope_id"] == "L-0006"][0]
        self.assertIsNone(c["layer"])
        self.assertFalse(c["layer_detail"]["read"])

    def test_visibility_company_hides_private(self):
        out = self.run_collect("旅行の計画を立てたい")
        self.assertNotIn("L-0005", [c["scope_id"] for c in out["candidates"]])
        self.assertTrue(any("公開範囲" in n for n in out["notes"]))

    def test_visibility_private_only_private(self):
        out = self.run_collect("旅行の計画を立てたい", source_vis="private")
        self.assertEqual([c["scope_id"] for c in out["candidates"]], ["L-0005"])
        self.assertEqual(self.run_collect("請求書の項目", source_vis="private")["candidates"], [])

    def test_top_limits_layers_read(self):
        self.assertEqual(len(self.run_collect("請求書", top=1)["candidates"]), 1)
        self.assertLessEqual(len(self.run_collect("請求書", top=999)["candidates"]), collect.TOP_MAX)

    def test_exclude_removes_scope(self):
        ids = [c["scope_id"] for c in self.run_collect("請求書の項目を入力したい")["candidates"]]
        self.assertIn("L-0001", ids)
        ids2 = [c["scope_id"] for c in self.run_collect("請求書の項目を入力したい", exclude={"L-0001"})["candidates"]]
        self.assertNotIn("L-0001", ids2)
        self.assertEqual(set(ids) - {"L-0001"}, set(ids2))

    def test_no_words(self):
        out = self.run_collect("それをしたい")
        self.assertEqual(out["candidates"], [])
        self.assertTrue(out["notes"])

    def test_missing_db(self):
        out = collect.collect(self.root, "請求書", self.root / "none.db")
        self.assertEqual(out["candidates"], [])
        self.assertIn("Registry を開けない", out["notes"][0])
        self.assertFalse((self.root / "none.db").exists())

    def test_read_only(self):
        before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in self.root.rglob("*") if p.is_file()}
        self.run_collect("請求書の項目を入力したい")
        after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_cli_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            collect.main(["--root", str(self.root), "--db", str(self.db), "--text", "請求書の項目", "--top", "2"])
        self.assertEqual(len(json.loads(buf.getvalue())["candidates"]), 2)


class EdgeTest(unittest.TestCase):
    """Program に入っていない案件の公開範囲、Flow の外のパス、purpose が None、業務Project 経由の Program。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "t.db"
        make_db(self.db, f"""
        INSERT INTO programs VALUES('prg_work','仕事','work'),('prg_priv','くらし','private');
        INSERT INTO projects VALUES(1,'L-1','蔵書の整理','蔵書の全体を整理する','active','Flow/d/books');
        INSERT INTO projects VALUES(2,'L-2','蔵書の比較表','蔵書の比較','active','Flow/d/books2');
        INSERT INTO projects VALUES(3,'L-3','蔵書の資料','蔵書の資料を読む','active','Flow/d/books3');
        INSERT INTO projects VALUES(4,'L-4','蔵書の外','蔵書 Flow の外','active','Flow/../outside');
        INSERT INTO projects VALUES(5,'L-5','蔵書の絶対','蔵書 絶対パス','active','{self.root}/Flow/d/books5');
        INSERT INTO projects VALUES(6,'L-6','蔵書の業務','蔵書の業務の案件','active','Flow/d/books6');
        INSERT INTO business_projects VALUES('bpr_priv','家の蔵書',NULL,'active');
        INSERT INTO business_project_links VALUES(6,'bpr_priv','primary','confirmed');
        INSERT INTO program_memberships VALUES(NULL,'bpr_priv','prg_priv','business_project','confirmed');
        """)
        make_layer(self.root, "Flow/d/books", {"scope_id": "L-1", "goal": "蔵書の全体を整理する", "membership": {"read_domain": "private"}})
        make_layer(self.root, "Flow/d/books2", {"scope_id": "L-2", "goal": "比較", "membership": {"read_domain": "work"}})
        make_layer(self.root, "Flow/d/books3", {"scope_id": "L-3", "goal": "中身は見せない", "classification": {"affiliation": "sample-co"}})
        make_layer(self.root, "Flow/d/books5", {"scope_id": "L-5", "goal": "絶対パスの Layer", "membership": {"read_domain": "work"}})
        (self.root / "outside").mkdir()
        (self.root / "outside" / "intent.yaml").write_text('{"goal": "外の中身"}', encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_company_request_hides_private_and_names_only_unknown(self):
        out = collect.collect(self.root, "蔵書を整理したい", self.db)
        ids = {c["scope_id"]: c for c in out["candidates"]}
        self.assertNotIn("L-1", ids)                      # intent の membership.read_domain が private
        self.assertNotIn("L-6", ids)                      # 業務Project 経由で private の Program
        self.assertEqual(ids["L-2"]["read_domain_source"], "intent")
        self.assertTrue(ids["L-2"]["layer_detail"]["read"])
        self.assertEqual(ids["L-3"]["read_domain_source"], "unknown")  # 所属の名前から公開範囲を推さない
        self.assertFalse(ids["L-3"]["layer_detail"]["read"])
        self.assertNotIn("goal", ids["L-3"]["layer_detail"])
        self.assertIsNone(ids["L-3"]["registry_goal"])

    def test_private_request_sees_only_private(self):
        out = collect.collect(self.root, "蔵書を整理したい", self.db, source_vis="private")
        self.assertEqual(sorted(c["scope_id"] for c in out["candidates"]), ["L-1", "L-6"])

    def test_paths_outside_flow_and_absolute(self):
        out = collect.collect(self.root, "蔵書を整理したい", self.db)
        ids = {c["scope_id"]: c for c in out["candidates"]}
        self.assertIsNone(ids["L-4"]["layer"])
        self.assertFalse(ids["L-4"]["layer_detail"]["read"])
        self.assertEqual(ids["L-5"]["layer"], "Flow/d/books5")
        self.assertEqual(ids["L-5"]["layer_detail"]["goal"], "絶対パスの Layer")
        self.assertNotIn("外の中身", json.dumps(out, ensure_ascii=False))


class NoBusinessTablesTest(unittest.TestCase):
    """業務Project の表が無い DB（business_registry.py init をしていない導入先）でも止まらない。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "plain.db"
        make_db(self.db, """
        INSERT INTO projects VALUES(1,'L-9101','週報の自動化','週報の下書きを自動で作る','active','Flow/x/weekly');
        INSERT INTO projects VALUES(2,'L-9102','家の週報','家族の予定の週報','paused','Flow/x/home');
        INSERT INTO projects VALUES(3,'S-9103','週報のテンプレート','いつか週報の雛形を作る','planned',NULL);
        """, business=False)
        make_layer(self.root, "Flow/x/weekly", {"scope_id": "L-9101", "goal": {"description": "週報の下書きを自動で作る"}})
        make_layer(self.root, "Flow/x/home", {"scope_id": "L-9102", "goal": "家族の予定", "membership": {"read_domain": "private"}})

    def tearDown(self):
        self.tmp.cleanup()

    def test_company_request_reads_layers_without_programs(self):
        out = collect.collect(self.root, "週報を自動化したい", self.db)
        ids = {c["scope_id"]: c for c in out["candidates"]}
        self.assertEqual(set(ids), {"L-9101", "S-9103"})  # private と書いた Layer は出さない
        self.assertEqual(ids["L-9101"]["read_domain_source"], "unknown")
        self.assertTrue(ids["L-9101"]["layer_detail"]["read"])
        self.assertEqual(ids["L-9101"]["layer_detail"]["goal"], "週報の下書きを自動で作る")
        self.assertIsNone(ids["L-9101"]["program"])
        self.assertEqual(ids["S-9103"]["status_label"], "いつかやる")
        self.assertTrue(any("業務Project の表が無い" in n for n in out["notes"]))

    def test_private_request_sees_only_intent_private(self):
        out = collect.collect(self.root, "週報を見直したい", self.db, source_vis="private")
        self.assertEqual([c["scope_id"] for c in out["candidates"]], ["L-9102"])

    def test_default_db_follows_aiplc_paths(self):
        # 配布の形（core/skills/ppm-collection）では core/db/aiplc_paths.py が場所を決める。AIPLC_DB はそこで効く
        with mock.patch.dict(os.environ, {"AIPLC_DB": str(self.db)}):
            self.assertEqual(collect.default_db(self.root), self.db)


class LabelTest(unittest.TestCase):
    def test_someday_only_for_s_id(self):
        self.assertEqual(collect.status_label("planned", False, "S-1234"), "いつかやる")
        self.assertEqual(collect.status_label("planned", False, "L-9099"), "予定")
        self.assertEqual(collect.status_label("planned", True, "L-9099"), "予定")


class TokenTest(unittest.TestCase):
    def test_stop_words_not_split(self):
        toks = pm.tokens("似た案件を探すスキルを作る", bigrams=True)
        for g in ("スキ", "キル", "案件"):
            self.assertNotIn(g, toks)

    def test_bigrams(self):
        self.assertEqual(pm.tokens("請求テンプレート明細印刷"), ["請求", "テンプレート", "明細印刷"])
        self.assertIn("印刷", pm.tokens("請求テンプレート明細印刷", bigrams=True))


if __name__ == "__main__":
    unittest.main()
