#!/usr/bin/env python3
"""業務Project の表（Program・業務Project・所属・AI-PLC 案件とのつながり）を作り、行を足す道具。

AIPM の箱（aipm-guided）の archive は、保存先が Stock のとき（`.ai-plc/config.yaml` の `aipm_archive.where` が
stock、または既定の auto でリポジトリに `Stock/programs/` があるとき）で、`business` が registry（既定）なら、
Layer の主な（primary）業務Project を Registry から読んで、写しの行き先
`Stock/programs/<Program>/projects/<業務Project>/<project>/` を決める。この道具はその表を作る。
`Stock/programs/` が無いリポジトリでは箱は Layer の中に保存され、この表は読まれない。Stock があっても
読ませないときは `aipm_archive: {business: none}` を書く。

業務Project の visibility には、その Program の read_domain（work／private）と同じ値を書く。共有 Stock
（shared_stock.py）はこの一致を求める。
前提: Registry が Identity v2.0 であること（`sync.py adopt-existing` の後。projects に workspace_id・sync_uid がある）。
表を作ったあとは、init_db.py の初期化・作り直しが止まる（業務Project の関係を守るため。init_db の
INIT_DB_BUSINESS_TABLES_PRESENT）。

Usage:
    python3 .claude/db/business_registry.py list [--json]
    python3 .claude/db/business_registry.py init [--yes]
    python3 .claude/db/business_registry.py add-program <Program> [--key stock:<Program>] [--private] [--yes]
    python3 .claude/db/business_registry.py add-business <Program> <業務Project名> --purpose <目的> [--yes]
    python3 .claude/db/business_registry.py link <scope_id> <業務Project名|bpr_…> [--related] [--yes]
    python3 .claude/db/business_registry.py unlink <scope_id> <業務Project名|bpr_…> [--yes]
    python3 .claude/db/business_registry.py where <scope_id>
    （どれも --db PATH で DB を指定できる。--yes が無い書き込みは、何をするかを出すだけで書かない）

終了コード: 0 = できた（または書かずに案内した）/ 2 = 入力や今の行と合わない（何も書かない）/
3 = 表や Identity v2.0 が無いなど DB の状態のせいで進めない（何も書かない）/ 64 = 使い方の誤り。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLES = ("programs", "business_projects", "program_memberships", "business_project_links")
# Project の Identity のうち、つながりの写し（identity_snapshot）に入れる項目
IDENTITY_KEYS = ("id", "scope_id", "workspace_id", "sync_uid", "ownership_epoch",
                 "identity_version", "parent_scope", "status")

DDL = (
'''CREATE TABLE programs (
 program_uid TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, definition_key TEXT NOT NULL,
 display_name TEXT NOT NULL, display_group TEXT NOT NULL CHECK(display_group IN ('work','private')),
 read_domain TEXT NOT NULL CHECK(read_domain IN ('work','private')),
 owner_ref TEXT, steward_ref TEXT, source_ref TEXT NOT NULL,
 ownership_epoch INTEGER NOT NULL CHECK(ownership_epoch>=1), identity_version INTEGER NOT NULL CHECK(identity_version=2),
 row_revision INTEGER NOT NULL CHECK(row_revision>=1), state TEXT NOT NULL CHECK(state IN ('active','retired')),
 UNIQUE(workspace_id,program_uid), UNIQUE(workspace_id,definition_key))''',
'''CREATE TABLE business_projects (
 id INTEGER PRIMARY KEY AUTOINCREMENT, business_uid TEXT NOT NULL UNIQUE, workspace_id TEXT NOT NULL,
 display_name TEXT NOT NULL, purpose TEXT NOT NULL, included_json TEXT NOT NULL, excluded_json TEXT NOT NULL,
 owner_ref TEXT, steward_ref TEXT, period_start TEXT, period_end TEXT, visibility TEXT NOT NULL,
 source_ref TEXT NOT NULL, source_hash TEXT NOT NULL, source_as_of TEXT NOT NULL,
 ownership_epoch INTEGER NOT NULL CHECK(ownership_epoch>=1), identity_version INTEGER NOT NULL CHECK(identity_version=2),
 row_revision INTEGER NOT NULL CHECK(row_revision>=1), state TEXT NOT NULL CHECK(state IN ('active','archived')),
 UNIQUE(workspace_id,business_uid))''',
'''CREATE TABLE program_memberships (
 membership_uid TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, program_uid TEXT NOT NULL,
 target_kind TEXT NOT NULL CHECK(target_kind IN ('business_project','aiplc_project')),
 business_uid TEXT, project_id INTEGER REFERENCES projects(id), aiplc_uid TEXT,
 project_epoch INTEGER, project_version INTEGER, identity_snapshot TEXT,
 period_start TEXT, period_end TEXT, source_ref TEXT NOT NULL,
 row_revision INTEGER NOT NULL CHECK(row_revision>=1), state TEXT NOT NULL CHECK(state IN ('confirmed','retired')),
 FOREIGN KEY(workspace_id,program_uid) REFERENCES programs(workspace_id,program_uid),
 FOREIGN KEY(workspace_id,business_uid) REFERENCES business_projects(workspace_id,business_uid),
 CHECK((target_kind='business_project' AND business_uid IS NOT NULL AND project_id IS NULL AND aiplc_uid IS NULL AND identity_snapshot IS NULL)
 OR (target_kind='aiplc_project' AND business_uid IS NULL AND project_id IS NOT NULL AND aiplc_uid IS NOT NULL AND project_epoch IS NOT NULL AND project_version IS NOT NULL AND project_epoch>=1 AND project_version=2 AND identity_snapshot IS NOT NULL)))''',
'''CREATE TABLE business_project_links (
 link_uid TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, business_uid TEXT NOT NULL,
 project_id INTEGER NOT NULL REFERENCES projects(id), aiplc_uid TEXT NOT NULL,
 project_epoch INTEGER NOT NULL CHECK(project_epoch>=1), project_version INTEGER NOT NULL CHECK(project_version=2),
 identity_snapshot TEXT NOT NULL, relation_type TEXT NOT NULL CHECK(relation_type IN ('primary','related')),
 period_start TEXT, period_end TEXT, source_ref TEXT NOT NULL,
 row_revision INTEGER NOT NULL CHECK(row_revision>=1), state TEXT NOT NULL CHECK(state IN ('confirmed','retired')),
 FOREIGN KEY(workspace_id,business_uid) REFERENCES business_projects(workspace_id,business_uid))''',
'''CREATE UNIQUE INDEX business_membership_direct ON program_memberships(workspace_id,business_uid) WHERE state='confirmed' AND target_kind='business_project' ''',
'''CREATE UNIQUE INDEX aiplc_membership_direct ON program_memberships(workspace_id,project_id) WHERE state='confirmed' AND target_kind='aiplc_project' ''',
'''CREATE UNIQUE INDEX business_link_pair ON business_project_links(workspace_id,business_uid,project_id) WHERE state='confirmed' ''',
'''CREATE UNIQUE INDEX business_link_primary ON business_project_links(workspace_id,project_id) WHERE state='confirmed' AND relation_type='primary' ''',
)
SOURCE_REF = "business_registry.py"
USAGE_EXIT, REFUSED_EXIT, STATE_EXIT = 64, 2, 3


class Refused(RuntimeError):
    def __init__(self, code, message, exit_code=REFUSED_EXIT):
        super().__init__(message)
        self.code, self.exit_code = code, exit_code


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def _load_sibling(name, filename):
    path = HERE / filename
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def default_db():
    paths = _load_sibling("_business_registry_paths", "aiplc_paths.py")
    return Path(paths.db_path()) if paths else HERE / "ai_plc.db"


def _sync():
    sync = _load_sibling("_business_registry_sync", "sync.py")
    if sync is None:
        raise Refused("SYNC_MISSING", "sync.py is needed next to this script (Identity resolver)", STATE_EXIT)
    return sync


def _name(value, what):
    text = unicodedata.normalize("NFC", (value or "").strip())
    if not text:
        raise Refused("NAME_INVALID", "%s is empty" % what)
    return text


def business_folder(name):
    """箱（aipm-guided の package.py の business_folder）と同じ規則で、業務Project の名前を Stock のフォルダ名にする:
    NFC にそろえ、':' は全角の '：'、'/' は全角の '／' に置き換える。'\\'・制御文字や見えない文字・先頭の '.'・
    前後の空白・末尾の '.'・255 バイトを超える名前はフォルダにできないので断る"""
    n = unicodedata.normalize("NFC", name).replace(":", "\uff1a").replace("/", "\uff0f")
    bad = (not n.strip() or n in (".", "..") or n.startswith(".") or n != n.strip() or n.endswith(".")
           or len(n.encode()) > 255
           or any(ch in "/\\" or unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") for ch in n))
    if bad:
        raise Refused("NAME_INVALID", "%r cannot be a folder name under Stock/programs/" % name)
    return n


def folder_key(name):
    """大文字小文字を区別しないファイルシステムで、2つのフォルダ名が同じになるかを比べる値（フォルダにできなければ None）"""
    try:
        return business_folder(name).casefold()
    except Refused:
        return None


def _tables_present(conn):
    return {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?,?)", TABLES)}


def _require_tables(conn):
    present = _tables_present(conn)
    if present != set(TABLES):
        raise Refused("BUSINESS_TABLES_MISSING",
                      "run `business_registry.py init --yes` first (missing: %s)"
                      % ",".join(sorted(set(TABLES) - present)), STATE_EXIT)


def _workspace(conn, manifest_path):
    sync = _sync()
    selection = sync.resolve_identity_selection(conn, manifest_path=manifest_path)
    if selection["exit_code"] or selection["mode"] != "v2":
        finding = selection.get("finding") or {}
        raise Refused(finding.get("code") or "IDENTITY_V2_REQUIRED",
                      (finding.get("message") or "the Registry is not Identity v2.0")
                      + " (run `sync.py adopt-existing` first)", STATE_EXIT)
    return selection["context"]["workspace_id"]


def _begin(conn):
    """書き込みの取引を始める（Python の sqlite3 の暗黙の取引を閉じてから BEGIN IMMEDIATE）"""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")


def _project(conn, scope_id, manifest_path):
    sync = _sync()
    selection = sync.resolve_identity_selection(conn, scope_id=scope_id, manifest_path=manifest_path)
    if selection["exit_code"] or selection["mode"] != "v2":
        finding = selection.get("finding") or {}
        raise Refused(finding.get("code") or "PROJECT_NOT_FOUND",
                      (finding.get("message") or "no Project with an Identity for this scope_id")
                      + " (add it with plc_query.py add-project)", selection.get("exit_code") or REFUSED_EXIT)
    workspace_id = selection["context"]["workspace_id"]
    row = conn.execute("SELECT " + ",".join(IDENTITY_KEYS) + " FROM projects WHERE workspace_id=? AND sync_uid=?",
                       (workspace_id, selection["project"]["sync_uid"])).fetchone()
    return workspace_id, dict(zip(IDENTITY_KEYS, row))


def _program(conn, workspace_id, name_or_key):
    key = name_or_key if name_or_key.startswith("stock:") else "stock:" + name_or_key
    name = unicodedata.normalize("NFC", name_or_key)
    rows = conn.execute("SELECT * FROM programs WHERE workspace_id=? AND state='active' "
                        "AND (definition_key=? OR display_name=?)",
                        (workspace_id, unicodedata.normalize("NFC", key), name)).fetchall()
    if len(rows) != 1:
        raise Refused("PROGRAM_NOT_UNIQUE", "%d active Programs match %r (add-program first)"
                      % (len(rows), name_or_key))
    return rows[0]


def _business(conn, workspace_id, name_or_uid):
    rows = conn.execute("SELECT * FROM business_projects WHERE workspace_id=? AND state='active' "
                        "AND (business_uid=? OR display_name=?)",
                        (workspace_id, name_or_uid, unicodedata.normalize("NFC", name_or_uid))).fetchall()
    if len(rows) != 1:
        raise Refused("BUSINESS_NOT_UNIQUE", "%d active business projects match %r (use its bpr_ uid)"
                      % (len(rows), name_or_uid))
    return rows[0]


# ---- commands -------------------------------------------------------------------------------------

def cmd_init(conn, args, manifest_path):
    _workspace(conn, manifest_path)
    present = _tables_present(conn)
    if present == set(TABLES):
        print("[OK] business tables already exist (no change)")
        return 0
    if present:
        raise Refused("BUSINESS_TABLES_PARTIAL", "only some business tables exist: %s"
                      % ",".join(sorted(present)), STATE_EXIT)
    if not args.yes:
        print("[PLAN] create tables: %s (re-run with --yes). Afterwards init_db.py refuses to rebuild "
              "this DB (INIT_DB_BUSINESS_TABLES_PRESENT)." % ", ".join(TABLES))
        return 0
    _begin(conn)
    try:
        for statement in DDL:
            conn.execute(statement)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    print("[OK] business tables created: %s" % ", ".join(TABLES))
    return 0


def cmd_add_program(conn, args, manifest_path):
    _require_tables(conn)
    workspace_id = _workspace(conn, manifest_path)
    name = _name(args.name, "Program name")
    if business_folder(name) != name:  # 箱は Program 名をそのまま Stock/programs/<Program> のフォルダにする
        raise Refused("NAME_INVALID", "a Program name is a folder under Stock/programs/ "
                      "(no ':' or '/'): %r" % name)
    key = unicodedata.normalize("NFC", args.key) if args.key else "stock:" + name
    if args.key and key[len("stock:"):] and business_folder(key[len("stock:"):]) != key[len("stock:"):]:
        raise Refused("KEY_INVALID", "--key stock:<Program> must also be a folder name: %r" % args.key)
    if not key.startswith("stock:") or key == "stock:":
        raise Refused("KEY_INVALID", "--key must be stock:<Program>")
    if conn.execute("SELECT 1 FROM programs WHERE workspace_id=? AND definition_key=?",
                    (workspace_id, key)).fetchone():
        raise Refused("PROGRAM_EXISTS", "%s already exists" % key)
    folder = folder_key(key[len("stock:"):])
    if any(folder_key(row[0][len("stock:"):]) == folder for row in conn.execute(
            "SELECT definition_key FROM programs WHERE workspace_id=? AND state='active'", (workspace_id,))):
        raise Refused("PROGRAM_EXISTS", "another active Program has the same folder as %s "
                      "(names differing only in case share one folder)" % key)
    group = "private" if args.private else "work"
    if not args.yes:
        print("[PLAN] add Program %s (%s, %s) (re-run with --yes)" % (name, key, group))
        return 0
    uid = "prg_" + str(uuid.uuid4())
    conn.execute("INSERT INTO programs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (uid, workspace_id, key, name, group, group, None, None, SOURCE_REF, 1, 2, 1, "active"))
    conn.commit()
    print("[OK] Program added: %s (%s) %s" % (name, key, uid))
    return 0


def cmd_add_business(conn, args, manifest_path):
    _require_tables(conn)
    workspace_id = _workspace(conn, manifest_path)
    program = _program(conn, workspace_id, args.program)
    name = _name(args.name, "business project name")
    purpose = _name(args.purpose, "--purpose")
    business_folder(name)  # 箱の archive がフォルダにできない名前はここで断る
    _check_same_folder(conn, workspace_id, program, name)
    if not args.yes:
        print("[PLAN] add business project %r under %s (re-run with --yes)" % (name, program["definition_key"]))
        return 0
    business_uid = "bpr_" + str(uuid.uuid4())
    source = {"name": name, "purpose": purpose, "program": program["definition_key"]}
    _begin(conn)
    try:
        _check_same_folder(conn, workspace_id, program, name)  # 書く取引の中でもう一度
        cursor = conn.execute(
            "INSERT INTO business_projects(business_uid,workspace_id,display_name,purpose,included_json,"
            "excluded_json,owner_ref,steward_ref,period_start,period_end,visibility,source_ref,source_hash,"
            "source_as_of,ownership_epoch,identity_version,row_revision,state) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (business_uid, workspace_id, name, purpose, "[]", "[]", None, None, None, None,
             program["read_domain"], SOURCE_REF, digest(source), now(), 1, 2, 1, "active"))
        conn.execute("INSERT INTO program_memberships VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("pmb_" + str(uuid.uuid4()), workspace_id, program["program_uid"], "business_project",
                      business_uid, None, None, None, None, None, None, None, SOURCE_REF, 1, "confirmed"))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    print("[OK] business project added: BIZ-%04d %s under %s %s"
          % (cursor.lastrowid, name, program["definition_key"], business_uid))
    return 0


def _check_same_folder(conn, workspace_id, program, name):
    """同じ Program の有効な業務Project に、同じフォルダになる名前（NFC・'：'・大文字小文字をそろえて）があれば断る"""
    same = conn.execute(
        "SELECT b.display_name FROM program_memberships m JOIN business_projects b "
        "ON b.workspace_id=m.workspace_id AND b.business_uid=m.business_uid "
        "WHERE m.workspace_id=? AND m.program_uid=? AND m.target_kind='business_project' "
        "AND m.state='confirmed' AND b.state='active'", (workspace_id, program["program_uid"])).fetchall()
    if any(folder_key(row[0]) == folder_key(name) for row in same):
        raise Refused("BUSINESS_EXISTS", "%s already has an active business project whose folder is %r"
                      % (program["display_name"], business_folder(name)))


def cmd_link(conn, args, manifest_path):
    _require_tables(conn)
    workspace_id, project = _project(conn, args.scope_id, manifest_path)
    business = _business(conn, workspace_id, args.business)
    relation = "related" if args.related else "primary"
    links = conn.execute("SELECT * FROM business_project_links WHERE workspace_id=? AND project_id=? "
                         "AND state='confirmed'", (workspace_id, project["id"])).fetchall()
    if any(row["business_uid"] == business["business_uid"] for row in links):
        raise Refused("LINK_EXISTS", "%s is already linked to %s" % (project["scope_id"], business["display_name"]))
    if relation == "primary" and any(row["relation_type"] == "primary" for row in links):
        raise Refused("PRIMARY_EXISTS", "%s already has a primary business project (unlink it first, "
                      "or link this one with --related)" % project["scope_id"])
    if not args.yes:
        print("[PLAN] link %s to %s as %s (re-run with --yes)"
              % (project["scope_id"], business["display_name"], relation))
        return 0
    _begin(conn)
    try:
        current = conn.execute("SELECT " + ",".join(IDENTITY_KEYS) + " FROM projects WHERE id=?",
                               (project["id"],)).fetchone()
        if current is None or dict(zip(IDENTITY_KEYS, current)) != project:
            raise Refused("IDENTITY_CHANGED", "the Project changed while linking; run again")
        conn.execute("INSERT INTO business_project_links VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("bpl_" + str(uuid.uuid4()), workspace_id, business["business_uid"], project["id"],
                      project["sync_uid"], project["ownership_epoch"], project["identity_version"],
                      digest(project), relation, None, None, SOURCE_REF, 1, "confirmed"))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    print("[OK] %s linked to %s (%s)" % (project["scope_id"], business["display_name"], relation))
    return 0


def cmd_unlink(conn, args, manifest_path):
    _require_tables(conn)
    workspace_id, project = _project(conn, args.scope_id, manifest_path)
    business = _business(conn, workspace_id, args.business)
    row = conn.execute("SELECT link_uid, row_revision FROM business_project_links WHERE workspace_id=? "
                       "AND business_uid=? AND project_id=? AND state='confirmed'",
                       (workspace_id, business["business_uid"], project["id"])).fetchone()
    if row is None:
        raise Refused("LINK_NOT_FOUND", "%s is not linked to %s" % (project["scope_id"], business["display_name"]))
    if not args.yes:
        print("[PLAN] retire the link %s -> %s (re-run with --yes)" % (project["scope_id"], business["display_name"]))
        return 0
    _begin(conn)
    cursor = conn.execute("UPDATE business_project_links SET state='retired', row_revision=row_revision+1 "
                          "WHERE link_uid=? AND row_revision=? AND state='confirmed'",
                          (row["link_uid"], row["row_revision"]))
    if cursor.rowcount != 1:
        conn.rollback()
        raise Refused("LINK_CHANGED", "the link changed while retiring it; run again")
    conn.commit()
    print("[OK] link retired: %s -> %s" % (project["scope_id"], business["display_name"]))
    return 0


def cmd_list(conn, args, manifest_path):
    _require_tables(conn)
    rows = [dict(r) for r in conn.execute(
        "SELECT p.definition_key AS program, b.display_name AS business, b.business_uid, b.state, "
        "(SELECT group_concat(pr.scope_id || ':' || l.relation_type, ' ') FROM business_project_links l "
        " JOIN projects pr ON pr.id=l.project_id WHERE l.workspace_id=b.workspace_id "
        " AND l.business_uid=b.business_uid AND l.state='confirmed') AS links "
        "FROM business_projects b LEFT JOIN program_memberships m ON m.workspace_id=b.workspace_id "
        "AND m.business_uid=b.business_uid AND m.target_kind='business_project' AND m.state='confirmed' "
        "LEFT JOIN programs p ON p.workspace_id=m.workspace_id AND p.program_uid=m.program_uid "
        "ORDER BY program, business")]
    programs = [dict(r) for r in conn.execute(
        "SELECT definition_key, display_name, display_group, state FROM programs ORDER BY definition_key")]
    if args.json:
        print(json.dumps({"programs": programs, "business_projects": rows}, ensure_ascii=False, indent=2))
        return 0
    for program in programs:
        print("%s  %s  (%s, %s)" % (program["definition_key"], program["display_name"],
                                    program["display_group"], program["state"]))
    for row in rows:
        print("  %s / %s  [%s]  %s" % (row["program"], row["business"], row["state"], row["links"] or "-"))
    if not programs and not rows:
        print("(no Programs or business projects)")
    return 0


def cmd_where(conn, args, manifest_path):
    """Where the box archive would put a Layer's copies (same reading as aipm-guided archive_business)."""
    _require_tables(conn)
    workspace_id, project = _project(conn, args.scope_id, manifest_path)
    links = conn.execute("SELECT business_uid FROM business_project_links WHERE workspace_id=? AND project_id=? "
                         "AND relation_type='primary' AND state='confirmed'",
                         (workspace_id, project["id"])).fetchall()
    if len(links) != 1:
        raise Refused("NO_PRIMARY", "%s has no primary business project (link it first)" % project["scope_id"])
    business = conn.execute("SELECT display_name, state FROM business_projects WHERE workspace_id=? "
                            "AND business_uid=?", (workspace_id, links[0][0])).fetchone()
    programs = conn.execute(
        "SELECT p.definition_key FROM program_memberships m JOIN programs p ON p.workspace_id=m.workspace_id "
        "AND p.program_uid=m.program_uid WHERE m.workspace_id=? AND m.business_uid=? "
        "AND m.target_kind='business_project' AND m.state='confirmed' AND p.state='active'",
        (workspace_id, links[0][0])).fetchall()
    if business is None or business[1] != "active" or len(programs) != 1:
        raise Refused("NO_ACTIVE_BUSINESS", "the primary business project is not active in one Program")
    folder = business_folder(business[0])
    siblings = conn.execute(
        "SELECT b.display_name FROM program_memberships m JOIN business_projects b ON b.workspace_id=m.workspace_id "
        "AND b.business_uid=m.business_uid JOIN programs p ON p.workspace_id=m.workspace_id "
        "AND p.program_uid=m.program_uid WHERE m.workspace_id=? AND p.definition_key=? "
        "AND m.target_kind='business_project' AND m.state='confirmed' AND b.state='active' AND b.business_uid<>?",
        (workspace_id, programs[0][0], links[0][0])).fetchall()
    if any(folder_key(row[0]) == folder.casefold() for row in siblings):
        raise Refused("FOLDER_OVERLAP", "another active business project of %s has the folder name %r"
                      % (programs[0][0], folder))
    print("Stock/programs/%s/projects/%s/<project>/" % (programs[0][0][len("stock:"):], folder))
    return 0


COMMANDS = {"init": cmd_init, "add-program": cmd_add_program, "add-business": cmd_add_business,
            "link": cmd_link, "unlink": cmd_unlink, "list": cmd_list, "where": cmd_where}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(USAGE_EXIT, "%s: error: %s\n" % (self.prog, message))


def build_parser():
    parser = _Parser(prog="python3 .claude/db/business_registry.py",
                     description="業務Project の表（箱の archive が読む形）を作り、行を足す。")
    parser.add_argument("--db", metavar="PATH", help="対象の DB（省略時は sync.py と同じ決め方の ai_plc.db。workspace manifest は DB の隣＝plc_query と同じ）")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    p = sub.add_parser("init", help="4つの表を作る")
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("add-program", help="Program（Stock/programs/<Program>）を足す")
    p.add_argument("name")
    p.add_argument("--key", help="definition_key（既定 stock:<Program>）")
    p.add_argument("--private", action="store_true", help="私生活の Program として分ける")
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("add-business", help="Program の下に業務Project を足す")
    p.add_argument("program")
    p.add_argument("name")
    p.add_argument("--purpose", required=True)
    p.add_argument("--yes", action="store_true")
    for name in ("link", "unlink"):
        p = sub.add_parser(name, help="AI-PLC の案件（scope_id）と業務Project をつなぐ / つながりを外す")
        p.add_argument("scope_id")
        p.add_argument("business")
        if name == "link":
            p.add_argument("--related", action="store_true", help="主ではない関係としてつなぐ")
        p.add_argument("--yes", action="store_true")
    p = sub.add_parser("list", help="Program・業務Project・つながりを一覧する")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("where", help="箱の archive の行き先を示す")
    p.add_argument("scope_id")
    return parser


def main(argv=None):
    parser = build_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else USAGE_EXIT
    db = Path(args.db).expanduser() if args.db else default_db()
    if not db.is_file():
        print("[BLOCKED] DB_NOT_FOUND: %s (nothing was written)" % db)
        return STATE_EXIT
    manifest_path = str(db.parent / "workspace_identity.json")
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        return COMMANDS[args.command](conn, args, manifest_path)
    except Refused as exc:
        if conn.in_transaction:
            conn.rollback()
        print("[BLOCKED] %s: %s (nothing was written)" % (exc.code, exc))
        return exc.exit_code
    except sqlite3.IntegrityError as exc:
        if conn.in_transaction:
            conn.rollback()
        print("[BLOCKED] LOCAL_CONSTRAINT_VIOLATION: %s (nothing was written)" % exc)
        return REFUSED_EXIT
    except sqlite3.OperationalError as exc:
        if conn.in_transaction:
            conn.rollback()
        code = "DB_BUSY" if "locked" in str(exc) or "busy" in str(exc) else "DB_ERROR"
        print("[BLOCKED] %s: %s (nothing was written)" % (code, exc))
        return STATE_EXIT
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
