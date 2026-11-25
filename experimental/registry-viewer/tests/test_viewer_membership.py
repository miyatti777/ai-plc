#!/usr/bin/env python3
"""Program・業務Project のまとまりの表示（business_registry.py の4つの表を読むだけ）の回帰テスト。

DB は合成する: core の init_db.py の create_schema() のスキーマ → projects に Identity v2.0 の列を足す →
business_registry.py の DDL。名前はすべて合成（Sample・合成の業務A など）。プロジェクトの DB は開かない。
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.dont_write_bytecode = True
import server  # noqa: E402
import test_viewer as tv  # noqa: E402

BUSINESS_REGISTRY = tv._first("AIPLC_BUSINESS_REGISTRY", [tv.PUBLIC_REPO / "core" / "db" / "business_registry.py",
                                                         tv.INSTALLED_DB_DIR / "business_registry.py"])
WS = "ws-synthetic"
IDENTITY_COLUMNS = ("workspace_id TEXT", "sync_uid TEXT", "ownership_epoch INTEGER", "identity_version INTEGER")


def business_ddl():
    return server._load("_rv_business_registry", BUSINESS_REGISTRY).DDL


class MembershipBase(unittest.TestCase):
    IDENTITY = True

    def setUp(self):
        if BUSINESS_REGISTRY is None:
            self.skipTest("business_registry.py が見つかりません（AIPLC_BUSINESS_REGISTRY で指定できます）")
        self.tmp = tempfile.TemporaryDirectory(prefix="rv_member_")
        self.root = Path(self.tmp.name)
        self.db = self.root / "ai_plc.db"
        conn = sqlite3.connect(self.db)
        for sql in tv.current_schema():
            conn.execute(sql)
        if self.IDENTITY:
            for col in IDENTITY_COLUMNS:
                conn.execute(f"ALTER TABLE projects ADD COLUMN {col}")
        for sql in business_ddl():
            conn.execute(sql)
        p = "INSERT INTO projects (scope_id, name, status) VALUES (?,?,?)"
        for sid in ("L-9101", "L-9102", "L-9103", "L-9104"):
            conn.execute(p, (sid, f"合成の案件 {sid}", "active"))
        if self.IDENTITY:
            for sid in ("L-9101", "L-9102", "L-9103", "L-9104"):
                conn.execute("UPDATE projects SET workspace_id=?, sync_uid=?, ownership_epoch=1, identity_version=2 "
                             "WHERE scope_id=?", (WS, "uid-" + sid, sid))
        self.ids = {r[0]: r[1] for r in conn.execute("SELECT scope_id, id FROM projects")}
        self.conn = conn
        self.add_program("PG-1", "Sample", "work")
        self.add_program("PG-2", "合成の私生活", "private")
        self.add_business("B-1", "合成の業務A", "PG-1")
        self.add_business("B-2", "合成の業務B", "PG-2")
        conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    # ---- 合成の行（business_registry.py が書く形に合わせる）
    def add_program(self, uid, name, group, state="active"):
        self.conn.execute("INSERT INTO programs VALUES (?,?,?,?,?,?,NULL,NULL,'test',1,2,1,?)",
                          (uid, WS, "stock:" + name, name, group, group, state))

    def add_business(self, uid, name, program, state="active"):
        self.conn.execute("INSERT INTO business_projects (business_uid, workspace_id, display_name, purpose, included_json, "
                          "excluded_json, visibility, source_ref, source_hash, source_as_of, ownership_epoch, "
                          "identity_version, row_revision, state) VALUES (?,?,?,'合成の目的','[]','[]','work','test','h',"
                          "'2099-01-01',1,2,1,?)", (uid, WS, name, state))
        if program:
            self.conn.execute("INSERT INTO program_memberships (membership_uid, workspace_id, program_uid, target_kind, "
                              "business_uid, source_ref, row_revision, state) VALUES (?,?,?,'business_project',?,'test',1,"
                              "'confirmed')", ("M-" + uid, WS, program, uid))

    def link(self, sid, business, relation="primary", uid=None, state="confirmed"):
        self.conn.execute("INSERT INTO business_project_links VALUES (?,?,?,?,?,1,2,'{}',?,NULL,NULL,'test',1,?)",
                          (f"K-{sid}-{business}", WS, business, self.ids[sid], uid or "uid-" + sid, relation, state))

    def direct(self, sid, program, uid=None):
        self.conn.execute("INSERT INTO program_memberships (membership_uid, workspace_id, program_uid, target_kind, "
                          "project_id, aiplc_uid, project_epoch, project_version, identity_snapshot, source_ref, "
                          "row_revision, state) VALUES (?,?,?,'aiplc_project',?,?,1,2,'{}','test',1,'confirmed')",
                          (f"D-{sid}", WS, program, self.ids[sid], uid or "uid-" + sid))

    def reg(self):
        self.conn.commit()
        return server.Registry(self.db, self.root, readonly_reason="テスト")

    def listing(self):
        data = self.reg().list_projects()
        return data, {p["scope_id"]: p["membership"] for p in data["projects"]}


class MembershipTests(MembershipBase):
    def test_direct_program(self):
        self.direct("L-9101", "PG-1")
        data, by = self.listing()
        self.assertEqual(by["L-9101"]["program"]["name"], "Sample")
        self.assertEqual(by["L-9101"]["program_source"], "direct")
        self.assertIsNone(by["L-9101"]["primary_business"])
        self.assertTrue(data["membership"] is not None)

    def test_primary_and_related(self):
        self.link("L-9101", "B-1")
        self.link("L-9101", "B-2", relation="related")
        _, by = self.listing()
        m = by["L-9101"]
        self.assertEqual(m["primary_business"]["name"], "合成の業務A")
        self.assertEqual(m["primary_business"]["display_id"], "BIZ-0001")
        self.assertEqual([b["name"] for b in m["related_business"]], ["合成の業務B"])
        # Program は主な業務Project の Program から引く
        self.assertEqual((m["program"]["name"], m["program_source"]), ("Sample", "business"))

    def test_unlinked_counts_and_related_only(self):
        self.link("L-9101", "B-1")
        self.link("L-9102", "B-1", relation="related")  # 関連だけは未紐付けに数える
        data, by = self.listing()
        self.assertIsNotNone(by["L-9102"])
        self.assertIsNone(by["L-9103"])
        self.assertEqual((data["membership"]["linked"], data["membership"]["unlinked"]), (1, 3))

    def test_only_private_program_is_sensitive(self):
        self.link("L-9101", "B-1")
        self.link("L-9102", "B-2")
        data, by = self.listing()
        self.assertFalse(by["L-9101"]["program"]["sensitive"])
        self.assertFalse(by["L-9101"]["primary_business"]["sensitive"])
        self.assertTrue(by["L-9102"]["program"]["sensitive"])
        self.assertTrue(by["L-9102"]["primary_business"]["sensitive"])
        groups = {p["name"]: p["group"] for p in data["membership"]["programs"]}
        self.assertEqual(groups, {"Sample": "work", "合成の私生活": "private"})

    def test_retired_and_archived_excluded(self):
        self.add_program("PG-3", "合成の退役", "work", state="retired")
        self.add_business("B-3", "合成の保管済み", "PG-1", state="archived")
        self.direct("L-9103", "PG-3")
        self.link("L-9104", "B-3")
        data, by = self.listing()
        self.assertIsNone(by["L-9103"])
        self.assertIsNone(by["L-9104"])
        self.assertNotIn("合成の退役", [p["name"] for p in data["membership"]["programs"]])
        self.assertNotIn("合成の保管済み", [b["name"] for b in data["membership"]["business_projects"]])

    def test_retired_link_ignored(self):
        self.link("L-9101", "B-1", state="retired")
        _, by = self.listing()
        self.assertIsNone(by["L-9101"])

    def test_identity_mismatch_counted(self):
        self.link("L-9101", "B-1", uid="uid-someone-else")
        data, by = self.listing()
        self.assertIsNone(by["L-9101"])
        self.assertEqual(data["membership"]["identity_mismatch"], 1)

    def test_null_sync_uid_not_matched(self):
        self.conn.execute("UPDATE projects SET sync_uid=NULL WHERE scope_id='L-9101'")
        self.link("L-9101", "B-1")
        data, by = self.listing()
        self.assertIsNone(by["L-9101"])
        self.assertEqual(data["membership"]["identity_mismatch"], 1)

    def test_detail_has_membership(self):
        self.link("L-9101", "B-1")
        d = self.reg().project_detail("L-9101")
        self.assertTrue(d["membership_available"])
        self.assertEqual(d["membership"]["primary_business"]["name"], "合成の業務A")

    def test_reading_does_not_change_db(self):
        self.link("L-9101", "B-1")
        self.conn.commit()
        before = self.db.read_bytes()
        r = self.reg()
        r.list_projects()
        r.project_detail("L-9101")
        self.assertEqual(before, self.db.read_bytes())

    def test_absent_tables_hidden(self):
        for t in ("business_project_links", "program_memberships", "business_projects", "programs"):
            self.conn.execute(f"DROP TABLE {t}")
        data, by = self.listing()
        self.assertIsNone(data["membership"])
        self.assertTrue(all(v is None for v in by.values()))
        self.assertFalse(self.reg().project_detail("L-9101")["membership_available"])

    def test_api_json_serializable(self):
        self.link("L-9101", "B-1")
        json.dumps(self.reg().list_projects(), ensure_ascii=False)


class NoIdentityTests(MembershipBase):
    """Identity v2.0 の列（sync_uid）が無い DB では、表があってもまとまりを出さない（今までの一覧）"""
    IDENTITY = False

    def test_without_sync_uid_hidden(self):
        data, by = self.listing()
        self.assertIsNone(data["membership"])
        self.assertTrue(all(v is None for v in by.values()))


if __name__ == "__main__":
    unittest.main()
