#!/usr/bin/env python3
"""AI-PLC DB Sync — Notion API ↔ .claude/db/ai_plc.db 双方向同期

Usage:
    python3 .claude/db/sync.py pull              # Notion → ローカル
    python3 .claude/db/sync.py push              # ローカル → Notion
    python3 .claude/db/sync.py sync              # 双方向 (pull → push)
    python3 .claude/db/sync.py status            # 差分プレビュー
    python3 .claude/db/sync.py preflight         # schema/page link事前検査
    python3 .claude/db/sync.py reconcile         # stable-key照合プレビュー
    python3 .claude/db/sync.py pull --dry-run    # dry-run
    python3 .claude/db/sync.py push --dry-run    # dry-run
    python3 .claude/db/sync.py push --dry-run --plan-out FILE
    python3 .claude/db/sync.py push --plan FILE --plan-id SHA256
    python3 .claude/db/sync.py push --scope SCOPE_ID --dry-run --plan-out FILE
    python3 .claude/db/sync.py push --scope SCOPE_ID --plan FILE --plan-id SHA256
    python3 .claude/db/sync.py push --sync-uid PRJ_UID --dry-run --plan-out FILE
    python3 .claude/db/sync.py push --scope SCOPE_ID --plan FILE --plan-id SHA256 --decline FILE
    python3 .claude/db/sync.py declines [--revoke ID --approved-by NAME]
    python3 .claude/db/sync.py exclude --list | --scope SCOPE_ID --approved-by NAME [--reason TEXT] | --remove SCOPE_ID --approved-by NAME
    python3 .claude/db/sync.py import-legacy --dry-run --out FILE | --apply FILE
    python3 .claude/db/sync.py tasks-sync --status | --freeze --approved-by NAME [--reason TEXT] | --unfreeze --approved-by NAME
    python3 .claude/db/sync.py fork-workspace --dry-run --writer-id ID --plan-out FILE
    python3 .claude/db/sync.py fork-workspace --plan FILE --plan-id SHA256
    python3 .claude/db/sync.py activate-writer --workspace-id WSP_ID --fork-plan FILE --plan-id SHA256
    python3 .claude/db/sync.py adopt-existing --dry-run --decisions FILE --writer-id ID --plan-out FILE
    python3 .claude/db/sync.py adopt-existing --plan FILE --plan-id SHA256 [--state FILE]
    python3 .claude/db/sync.py adopt-existing --status --plan FILE [--state FILE]
    python3 .claude/db/sync.py backfill-remote-identity --dry-run --plan-out FILE
    python3 .claude/db/sync.py backfill-remote-identity --plan FILE --plan-id SHA256 [--max-batches N] [--state FILE]
    python3 .claude/db/sync.py backfill-remote-identity --status --plan FILE [--state FILE]
    transfer-project / takeover-writer / handoff-repair -> V2_1_REQUIRED (exit 3)

Requires: NOTION_API_TOKEN environment variable, and the Notion DB IDs
  export AI_PLC_PROJECTS_DB_ID=<Projects DB の ID>
  export AI_PLC_TASKS_DB_ID=<Tasks DB の ID>（タスク同期を凍結していれば不要）
(Project Registry はローカルの ai_plc.db だけでも動く。Notion に触れるコマンドだけがこれらを使う)
"""

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:  # DB の場所（AIPLC_DB → config → git-common-dir → ここ）。単体でコピーしたときは今までどおり
    import aiplc_paths  # noqa: E402
except ImportError:  # pragma: no cover
    aiplc_paths = None

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# このスクリプトのあるフォルダ（Claude Code は .claude/db、Cursor は .cursor/db）
SCRIPT_DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = (aiplc_paths.db_path(BASE) if aiplc_paths
           else os.path.join(SCRIPT_DB_DIR, "ai_plc.db"))
WORKSPACE_MANIFEST_PATH = os.path.join(os.path.dirname(DB_PATH), "workspace_identity.json")
if not os.path.exists(WORKSPACE_MANIFEST_PATH):  # AIPLC_DB で DB だけ別の場所を指したとき
    WORKSPACE_MANIFEST_PATH = os.path.join(SCRIPT_DB_DIR, "workspace_identity.json")
BOOTSTRAP_STATE_PATH = os.path.join(
    SCRIPT_DB_DIR, "identity_bootstrap.state.json"
)
WORKSPACE_ID_PATTERN = re.compile(
    r"^wsp_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
PROJECT_UID_PATTERN = re.compile(
    r"^prj_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

NOTION_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com"

# 同期先の Notion DB の ID は環境変数で指定する:
#   export AI_PLC_PROJECTS_DB_ID=xxxxxxxx  /  export AI_PLC_TASKS_DB_ID=xxxxxxxx
PROJECTS_DB_ID = os.environ.get("AI_PLC_PROJECTS_DB_ID", "")
TASKS_DB_ID = os.environ.get("AI_PLC_TASKS_DB_ID", "")
MISSING_DB_ID_MESSAGE = (
    "ERROR: Notion sync を使うには、対象の Notion DB ID を環境変数で指定してください:\n"
    "  export AI_PLC_PROJECTS_DB_ID=<Projects DBのID>\n"
    "  export AI_PLC_TASKS_DB_ID=<Tasks DBのID>（タスク同期を凍結していれば不要）\n"
    "（Project Registry / External Sync はローカルの ai_plc.db だけでも動作します）"
)

RATE_LIMIT_DELAY = 0.35

PROJECTS_NOTION_SCHEMA = {
    "PJ名": "title",
    "Goal": "rich_text",
    "Scope ID": "rich_text",
    "Owner": "people",
    "ステータス": "status",
    "モード": "select",
    "深度": "select",
    "システム": "select",
    "親Scope": "rich_text",
    "トップページ": "url",
    "開始日": "date",
    "期限": "date",
    "Sync UID": "rich_text",
    "Workspace ID": "rich_text",
    "Ownership Epoch": "number",
    "Identity Version": "number",
}

TASKS_NOTION_SCHEMA = {
    "タスク名": "title",
    "Task ID": "rich_text",
    "Scope ID": "rich_text",
    "ステータス": "status",
    "タイプ": "select",
    "優先度": "select",
    "見積(日)": "number",
    "成果物": "url",
    "完了日": "date",
    "Project Sync UID": "rich_text",
    "Workspace ID": "rich_text",
    "Project Ownership Epoch": "number",
    "Identity Version": "number",
}

LOCAL_REQUIRED_COLUMNS = {
    "projects": {
        "id", "notion_page_id", "scope_id", "name", "goal", "owner",
        "status", "mode", "depth", "system", "parent_scope", "top_page_url",
        "start_date", "deadline", "notion_last_edited", "last_sync_at",
        "created_at", "updated_at",
    },
    "tasks": {
        "id", "notion_page_id", "task_id", "scope_id", "name", "status",
        "type", "priority", "estimate_days", "output_url", "completed_at",
        "notion_last_edited", "last_sync_at", "created_at", "updated_at",
    },
}

LOCAL_IDENTITY_COLUMNS = {
    "projects": {
        "workspace_id", "sync_uid", "ownership_epoch", "identity_version",
    },
    "tasks": {
        "workspace_id", "project_sync_uid", "project_ownership_epoch",
        "identity_version",
    },
}

# ── Notion API helpers ─────────────────────────────────────

def _get_token():
    token = os.environ.get("NOTION_API_TOKEN", "")
    if not token:
        env_files = [
            os.path.join(BASE, ".claude", "skills", "nsync", ".env"),
        ]
        for f in env_files:
            if os.path.exists(f):
                for line in open(f):
                    if line.startswith("NOTION_API_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        break
            if token:
                break
    if not token:
        print("ERROR: NOTION_API_TOKEN not set.")
        sys.exit(1)
    return token


TOKEN = None  # lazy init


def _headers():
    global TOKEN
    if TOKEN is None:
        TOKEN = _get_token()
    return {
        "Authorization": "Bearer " + TOKEN,
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _api_call(method, path, body=None, retries=3):
    if "/v1/databases//" in path or path.rstrip("/").endswith("/v1/databases") or (
            isinstance(body, dict) and body.get("parent") == {"database_id": ""}):
        raise SystemExit(MISSING_DB_ID_MESSAGE)  # Notion DB の ID が未設定（何も送らない）
    url = NOTION_BASE + path if path.startswith("/") else path
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    attempts = 1 if method == "POST" and path == "/v1/pages" else retries
    last_error = None
    for attempt in range(attempts):
        try:
            time.sleep(RATE_LIMIT_DELAY)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                last_error = e
                try:
                    wait = min(max(int(e.headers.get("Retry-After", "2")), 0), 60)
                except (TypeError, ValueError):
                    wait = 2
                print("  Rate limited, waiting %ds..." % wait)
                if attempt < attempts - 1:
                    time.sleep(wait)
                continue
            body_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
            print("API Error %d: %s %s" % (e.code, url, body_text[:300]))
            if 400 <= e.code < 500:
                raise
            last_error = e
            if attempt < attempts - 1:
                time.sleep(1)
                continue
            raise
        except urllib.error.URLError as e:
            last_error = e
            print("Network error: %s" % e.reason)
            if attempt < attempts - 1:
                time.sleep(2)
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("Notion API retry loop ended without a response")


def _query_db(db_id):
    """Query all rows from a Notion database (paginated)."""
    results = []
    body = {"page_size": 100}
    while True:
        resp = _api_call("POST", "/v1/databases/%s/query" % db_id, body)
        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        body["start_cursor"] = resp["next_cursor"]
    return results


# ── Preflight ─────────────────────────────────────────────

def _normalize_notion_id(value):
    return (value or "").replace("-", "").lower()


def _finding(code, message, **details):
    finding = {"code": code, "message": message}
    finding.update(details)
    return finding


def _empty_preflight_report():
    return {
        "status": "pass",
        "findings": [],
        "schemas": {},
        "links": {"projects": [], "tasks": []},
    }


def _missing_local_db_report():
    report = _empty_preflight_report()
    report["status"] = "blocked"
    report["findings"].append(_finding(
        "LOCAL_DB_UNAVAILABLE", "local SQLite database does not exist", path=DB_PATH
    ))
    return report


def _local_db_error_report(exc):
    report = _empty_preflight_report()
    report["status"] = "blocked"
    report["findings"].append(_finding(
        "LOCAL_DB_UNAVAILABLE", str(exc), path=DB_PATH
    ))
    return report


def _get_preflight_conn():
    """Open SQLite read-only so preflight cannot change journal mode or data."""
    if aiplc_paths:
        return aiplc_paths.open_ro(DB_PATH)  # error 14（WAL・古い SQLite）の対策つき
    conn = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(os.path.abspath(DB_PATH)), uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _validate_local_schema(conn):
    findings = []
    identity_profiles = {}
    for table, expected in LOCAL_REQUIRED_COLUMNS.items():
        try:
            actual = {
                row[1] for row in conn.execute("PRAGMA table_info(%s)" % table).fetchall()
            }
        except sqlite3.Error as exc:
            findings.append(_finding(
                "LOCAL_SCHEMA_ERROR", str(exc), entity=table
            ))
            continue
        missing = sorted(expected - actual)
        if missing:
            findings.append(_finding(
                "LOCAL_SCHEMA_MISMATCH",
                "missing local columns: %s" % ", ".join(missing),
                entity=table,
                missing=missing,
            ))
        identity_present = actual & LOCAL_IDENTITY_COLUMNS[table]
        identity_profiles[table] = (
            "v2" if identity_present == LOCAL_IDENTITY_COLUMNS[table]
            else "v1" if not identity_present
            else "partial"
        )
        if identity_present and identity_present != LOCAL_IDENTITY_COLUMNS[table]:
            findings.append(_finding(
                "LOCAL_IDENTITY_SCHEMA_PARTIAL",
                "Identity v2 columns are only partially installed",
                entity=table,
                present=sorted(identity_present),
                missing=sorted(LOCAL_IDENTITY_COLUMNS[table] - actual),
            ))
    if set(identity_profiles.values()) == {"v1", "v2"}:
        findings.append(_finding(
            "LOCAL_IDENTITY_SCHEMA_MIXED",
            "projects and tasks use different Identity schema versions",
            profiles=identity_profiles,
        ))
    return findings


def _validate_notion_database(entity, db_id, expected_schema):
    findings = []
    if not db_id:  # 環境変数 AI_PLC_PROJECTS_DB_ID / AI_PLC_TASKS_DB_ID が未設定（何も送らない）
        findings.append(_finding(
            "NOTION_DB_ID_MISSING",
            "set AI_PLC_%s_DB_ID to the Notion %s DB ID (Project Registry works with the "
            "local ai_plc.db alone)" % ("PROJECTS" if entity == "project" else "TASKS",
                                         "Projects" if entity == "project" else "Tasks"),
            entity=entity,
        ))
        return None, findings
    try:
        database = _api_call("GET", "/v1/databases/%s" % db_id)
    except SystemExit:
        findings.append(_finding(
            "AUTH_ERROR",
            "NOTION_API_TOKEN is missing or invalid",
            entity=entity,
            database_id=db_id,
        ))
        return None, findings
    except urllib.error.HTTPError as exc:
        code = "AUTH_ERROR" if exc.code in (401, 403) else "DATABASE_UNAVAILABLE"
        findings.append(_finding(
            code,
            "Notion database preflight failed with HTTP %d" % exc.code,
            entity=entity,
            database_id=db_id,
            http_status=exc.code,
        ))
        return None, findings
    except (urllib.error.URLError, OSError) as exc:
        findings.append(_finding(
            "DATABASE_UNAVAILABLE", str(exc), entity=entity, database_id=db_id
        ))
        return None, findings
    except (RuntimeError, ValueError) as exc:
        findings.append(_finding(
            "DATABASE_RESPONSE_INVALID", str(exc), entity=entity, database_id=db_id
        ))
        return None, findings

    if not isinstance(database, dict):
        findings.append(_finding(
            "DATABASE_RESPONSE_INVALID",
            "database response is not an object",
            entity=entity,
            database_id=db_id,
        ))
        return None, findings

    properties = database.get("properties")
    if not isinstance(properties, dict):
        findings.append(_finding(
            "SCHEMA_MISMATCH",
            "database response has no properties object",
            entity=entity,
            database_id=db_id,
        ))
        return database, findings

    mismatches = []
    for name, expected_type in expected_schema.items():
        actual = properties.get(name)
        actual_type = actual.get("type") if isinstance(actual, dict) else None
        if actual_type != expected_type:
            mismatches.append({
                "property": name,
                "expected": expected_type,
                "actual": actual_type,
            })
    if mismatches:
        findings.append(_finding(
            "SCHEMA_MISMATCH",
            "%d required properties are missing or have the wrong type" % len(mismatches),
            entity=entity,
            database_id=db_id,
            mismatches=mismatches,
        ))
    return database, findings


def _schema_fingerprint(database, expected_schema):
    properties = database.get("properties", {})
    canonical = {
        name: (properties.get(name) or {}).get("type")
        for name in sorted(expected_schema)
    }
    encoded = json.dumps(
        canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _classify_page_link(entity, row, expected_db_id):
    page_id = row["notion_page_id"]
    result = {
        "entity": entity,
        "local_row_id": row["id"],
        "page_id": page_id,
        "state": "missing" if not page_id else None,
    }
    if entity == "project":
        result["stable_key"] = [row["scope_id"]]
    else:
        result["stable_key"] = [row["scope_id"], row["task_id"]]
    if not page_id:
        return result, None

    try:
        page = _api_call("GET", "/v1/pages/%s" % page_id)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            result["state"] = "not_found"
            return result, _finding(
                "LINK_NOT_FOUND",
                "linked page is missing or inaccessible",
                entity=entity,
                page_id=page_id,
                http_status=exc.code,
                reconcilable=True,
            )
        result["state"] = None
        return result, _finding(
            "PAGE_ACCESS_ERROR",
            "linked page preflight failed with HTTP %d" % exc.code,
            entity=entity,
            page_id=page_id,
            http_status=exc.code,
        )
    except (urllib.error.URLError, OSError) as exc:
        result["state"] = None
        return result, _finding(
            "PAGE_ACCESS_ERROR", str(exc), entity=entity, page_id=page_id
        )
    except (RuntimeError, ValueError) as exc:
        result["state"] = None
        return result, _finding(
            "PAGE_RESPONSE_INVALID", str(exc), entity=entity, page_id=page_id
        )

    if not isinstance(page, dict):
        result["state"] = None
        return result, _finding(
            "PAGE_RESPONSE_INVALID",
            "page response is not an object",
            entity=entity,
            page_id=page_id,
        )

    if page.get("archived") or page.get("in_trash"):
        result["state"] = "trashed"
        return result, _finding(
            "LINK_TRASHED", "linked page is archived or in trash",
            entity=entity, page_id=page_id, reconcilable=True,
        )

    parent = page.get("parent") or {}
    parent_id = parent.get("database_id")
    if _normalize_notion_id(parent_id) != _normalize_notion_id(expected_db_id):
        result["state"] = "wrong_parent"
        result["actual_parent_id"] = parent_id
        return result, _finding(
            "LINK_WRONG_PARENT",
            "linked page belongs to a different database",
            entity=entity,
            page_id=page_id,
            expected_parent_id=expected_db_id,
            actual_parent_id=parent_id,
            reconcilable=True,
        )

    result["state"] = "valid"
    result["last_edited_time"] = page.get("last_edited_time")
    return result, None


def run_preflight(conn=None, allow_reconcilable_links=False, scope_id=None):
    """Validate local/remote schemas and every persisted page link read-only."""
    normalized_scope = (
        _normalize_identity_text(scope_id) if scope_id is not None else None
    )
    owns_connection = conn is None
    if owns_connection:
        if not os.path.exists(DB_PATH):
            return _missing_local_db_report()
        try:
            conn = _get_preflight_conn()
        except (sqlite3.Error, OSError) as exc:
            return _local_db_error_report(exc)

    report = _empty_preflight_report()
    try:
        report["findings"].extend(_validate_local_schema(conn))
        blocking_findings = [
            finding for finding in report["findings"]
            if not (allow_reconcilable_links and finding.get("reconcilable"))
        ]
        if blocking_findings:
            report["status"] = "blocked"
            return report
        try:
            tasks_frozen = _task_sync_frozen(conn)
        except IdentityLifecycleError as exc:
            report["findings"].append(_finding(exc.code, "task freeze record is malformed"))
            report["status"] = "blocked"
            return report
        specs = (
            ("project", PROJECTS_DB_ID, PROJECTS_NOTION_SCHEMA),
            ("task", TASKS_DB_ID, TASKS_NOTION_SCHEMA),
        )
        for entity, db_id, expected_schema in specs:
            if entity == "task" and tasks_frozen:
                continue
            database, findings = _validate_notion_database(
                entity, db_id, expected_schema
            )
            report["schemas"][entity] = {
                "database_id": db_id,
                "status": "pass" if not findings else "blocked",
            }
            if database:
                report["schemas"][entity]["last_edited_time"] = database.get(
                    "last_edited_time"
                )
                report["schemas"][entity]["fingerprint"] = _schema_fingerprint(
                    database, expected_schema
                )
            report["findings"].extend(findings)

        # Page classification depends on trusted database metadata.
        if not report["findings"]:
            link_specs = (
                ("project", "projects", PROJECTS_DB_ID),
                ("task", "tasks", TASKS_DB_ID),
            )
            for entity, table, db_id in link_specs:
                if entity == "task" and tasks_frozen:
                    continue
                rows = conn.execute(
                    "SELECT * FROM %s WHERE notion_page_id IS NOT NULL" % table
                ).fetchall()
                for row in rows:
                    if (normalized_scope is not None
                            and _normalize_identity_text(row["scope_id"])
                            != normalized_scope):
                        continue
                    link, finding = _classify_page_link(entity, row, db_id)
                    report["links"][table].append(link)
                    if finding:
                        report["findings"].append(finding)

        blocking_findings = [
            finding for finding in report["findings"]
            if not (allow_reconcilable_links and finding.get("reconcilable"))
        ]
        if blocking_findings:
            report["status"] = "blocked"
        return report
    finally:
        if owns_connection:
            conn.close()


def _print_preflight_report(report):
    print("=== Preflight: %s ===" % report["status"].upper())
    for entity in ("project", "task"):
        schema = report["schemas"].get(entity, {})
        print("  Schema %-7s: %s" % (entity, schema.get("status", "not_checked")))
    for table in ("projects", "tasks"):
        counts = {}
        for link in report["links"][table]:
            state = link["state"]
            if state is None:
                continue
            counts[state] = counts.get(state, 0) + 1
        if counts:
            summary = ", ".join("%s=%d" % item for item in sorted(counts.items()))
            print("  Links %-8s: %s" % (table, summary))
    for finding in report["findings"]:
        tag = "RECONCILE" if finding.get("reconcilable") else "BLOCK"
        print("  [%s] %s: %s" % (tag, finding["code"], finding["message"]))


def cmd_preflight():
    report = run_preflight()
    _print_preflight_report(report)
    return 0 if report["status"] == "pass" else 3


# ── Property extractors ────────────────────────────────────

def _extract_title(prop):
    parts = prop.get("title", [])
    return "".join(p.get("plain_text", "") for p in parts) if parts else ""


def _extract_rich_text(prop):
    parts = prop.get("rich_text", [])
    return "".join(p.get("plain_text", "") for p in parts) if parts else ""


def _extract_select(prop):
    sel = prop.get("select")
    return sel["name"] if sel else None


def _extract_status(prop):
    st = prop.get("status")
    return st["name"] if st else None


def _extract_number(prop):
    return prop.get("number")


def _extract_date(prop):
    d = prop.get("date")
    if d and d.get("start"):
        return d["start"]
    return None


def _extract_url(prop):
    return prop.get("url")


def _extract_people(prop):
    people = prop.get("people", [])
    if people:
        return people[0].get("name", "unknown")
    return None


def _record_value(record, key, default=None):
    if isinstance(record, dict):
        return record.get(key, default)
    try:
        return record[key]
    except (KeyError, IndexError, TypeError):
        return default


# ── Property builders (for Push) ───────────────────────────

def _build_title(text):
    if not text:
        return {"title": []}
    return {"title": [{"text": {"content": str(text)}}]}


def _build_rich_text(text):
    if not text:
        return {"rich_text": []}
    return {"rich_text": [{"text": {"content": str(text)}}]}


def _build_select(name):
    if not name:
        return {"select": None}
    return {"select": {"name": str(name)}}


def _build_status(name):
    if not name:
        return {"status": None}
    return {"status": {"name": str(name)}}


def _build_number(val):
    if val is None:
        return {"number": None}
    return {"number": float(val)}


def _build_date(iso_str):
    if not iso_str:
        return {"date": None}
    return {"date": {"start": str(iso_str)}}


def _build_url(url):
    if not url:
        return {"url": None}
    return {"url": str(url)}


# ── Row conversion ─────────────────────────────────────────

def _notion_row_to_project(page):
    props = page["properties"]
    return {
        "notion_page_id": page["id"],
        "scope_id": _extract_rich_text(props.get("Scope ID", {})) or "UNKNOWN",
        "name": _extract_title(props.get("PJ名", {})) or "Untitled",
        "goal": _extract_rich_text(props.get("Goal", {})),
        "owner": _extract_people(props.get("Owner", {})) or "",
        "status": _map_project_status(_extract_status(props.get("ステータス", {}))),
        "mode": _extract_select(props.get("モード", {})) or "direct",
        "depth": _extract_select(props.get("深度", {})) or "standard",
        "system": _extract_select(props.get("システム", {})) or "AI-PLC",
        "parent_scope": _extract_rich_text(props.get("親Scope", {})),
        "top_page_url": _extract_url(props.get("トップページ", {})),
        "start_date": _extract_date(props.get("開始日", {})),
        "deadline": _extract_date(props.get("期限", {})),
        "sync_uid": _extract_rich_text(props.get("Sync UID", {})),
        "workspace_id": _extract_rich_text(props.get("Workspace ID", {})),
        "ownership_epoch": _extract_number(props.get("Ownership Epoch", {})),
        "identity_version": _extract_number(props.get("Identity Version", {})),
        "notion_last_edited": page.get("last_edited_time", ""),
    }


def _notion_row_to_task(page):
    props = page["properties"]
    return {
        "notion_page_id": page["id"],
        "task_id": _extract_rich_text(props.get("Task ID", {})) or "T000",
        "scope_id": _extract_rich_text(props.get("Scope ID", {})) or "UNKNOWN",
        "name": _extract_title(props.get("タスク名", {})) or "Untitled",
        "status": _extract_status(props.get("ステータス", {})) or "未着手",
        "type": _extract_select(props.get("タイプ", {})),
        "priority": _extract_select(props.get("優先度", {})) or "P1",
        "estimate_days": _extract_number(props.get("見積(日)", {})),
        "output_url": _extract_url(props.get("成果物", {})),
        "completed_at": _extract_date(props.get("完了日", {})),
        "project_sync_uid": _extract_rich_text(
            props.get("Project Sync UID", {})
        ),
        "workspace_id": _extract_rich_text(props.get("Workspace ID", {})),
        "project_ownership_epoch": _extract_number(
            props.get("Project Ownership Epoch", {})
        ),
        "identity_version": _extract_number(props.get("Identity Version", {})),
        "notion_last_edited": page.get("last_edited_time", ""),
    }


def _project_to_notion_props(row):
    """Convert local project row → Notion properties dict (for PATCH)."""
    if row['status'] == 'cancelled':
        raise ValueError('PROJECT_CANCELLED_EXTERNAL_SYNC_UNSUPPORTED')
    return {
        "PJ名": _build_title(row["name"]),
        "Goal": _build_rich_text(row["goal"]),
        "Scope ID": _build_rich_text(row["scope_id"]),
        "ステータス": _build_status(row["status"]),
        "モード": _build_select(row["mode"]),
        "深度": _build_select(row["depth"]),
        "システム": _build_select(row["system"]),
        "親Scope": _build_rich_text(row["parent_scope"]),
        "トップページ": _build_url(row["top_page_url"]),
        "開始日": _build_date(row["start_date"]),
        "期限": _build_date(row["deadline"]),
        "Sync UID": _build_rich_text(_record_value(row, "sync_uid")),
        "Workspace ID": _build_rich_text(_record_value(row, "workspace_id")),
        "Ownership Epoch": _build_number(_record_value(row, "ownership_epoch")),
        "Identity Version": _build_number(_record_value(row, "identity_version")),
    }


def _task_to_notion_props(row):
    """Convert local task row → Notion properties dict (for PATCH)."""
    return {
        "タスク名": _build_title(row["name"]),
        "Task ID": _build_rich_text(row["task_id"]),
        "Scope ID": _build_rich_text(row["scope_id"]),
        "ステータス": _build_status(row["status"]),
        "タイプ": _build_select(row["type"]),
        "優先度": _build_select(row["priority"]),
        "見積(日)": _build_number(row["estimate_days"]),
        "成果物": _build_url(row["output_url"]),
        "完了日": _build_date(row["completed_at"]),
        "Project Sync UID": _build_rich_text(
            _record_value(row, "project_sync_uid")
        ),
        "Workspace ID": _build_rich_text(_record_value(row, "workspace_id")),
        "Project Ownership Epoch": _build_number(
            _record_value(row, "project_ownership_epoch")
        ),
        "Identity Version": _build_number(_record_value(row, "identity_version")),
    }


def _map_project_status(s):
    if (s or '').strip().lower() == 'cancelled':
        raise ValueError('PROJECT_CANCELLED_EXTERNAL_SYNC_UNSUPPORTED')
    mapping = {"planned": "planned", "active": "active",
               "completed": "completed", "paused": "paused"}
    return mapping.get((s or "").strip().lower(), "planned")


# ── Stable-key reconciliation ─────────────────────────────

def _normalize_identity_text(value):
    return unicodedata.normalize("NFC", str(value or "")).strip()


def _stable_key(entity, record):
    scope_id = _normalize_identity_text(record.get("scope_id"))
    if entity == "project":
        return (scope_id,)
    return (scope_id, _normalize_identity_text(record.get("task_id")))


def _valid_stable_key(entity, key):
    if not key[0] or key[0] == "UNKNOWN":
        return False
    if entity == "task" and (not key[1] or key[1] == "T000"):
        return False
    return True


def _mapped_fingerprint(entity, record):
    """Hash every Notion property controlled by push for safe recovery."""
    defaults = ({
        "name": None, "goal": None, "scope_id": None, "status": None,
        "mode": None, "depth": None, "system": None, "parent_scope": None,
        "top_page_url": None, "start_date": None, "deadline": None,
    } if entity == "project" else {
        "name": None, "task_id": None, "scope_id": None, "status": None,
        "type": None, "priority": None, "estimate_days": None,
        "output_url": None, "completed_at": None,
    })
    complete = dict(defaults)
    complete.update(dict(record))
    props = (_project_to_notion_props(complete) if entity == "project"
             else _task_to_notion_props(complete))
    payload = json.dumps(
        props, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _candidate_detail(entity, page, remote):
    detail = {
        "page_id": page.get("id"),
        "title": remote.get("name"),
        "scope_id": remote.get("scope_id"),
        "last_edited_time": page.get("last_edited_time"),
        "notion_parent": page.get("parent"),
        "mapped_fingerprint": _mapped_fingerprint(entity, remote),
    }
    if entity == "project":
        detail["parent_scope"] = remote.get("parent_scope")
    else:
        detail["task_id"] = remote.get("task_id")
    return detail


def _identity_compatible(entity, local, remote):
    if _normalize_identity_text(local.get("name")) != _normalize_identity_text(
        remote.get("name")
    ):
        return False
    if entity == "project":
        return _normalize_identity_text(local.get("parent_scope")) == (
            _normalize_identity_text(remote.get("parent_scope"))
        )
    return True


def _empty_reconciliation_report():
    return {
        "status": "pass",
        "exit_code": 0,
        "findings": [],
        "items": [],
        "summary": {
            "not_found": 0,
            "attach": 0,
            "collision": 0,
            "duplicate": 0,
            "invalid": 0,
            "remote_only": 0,
            "error": 0,
        },
    }


def _reconciliation_finding_id(code, entity, stable_key=None, page_ids=None):
    canonical = {
        "code": code,
        "entity": entity,
        "stable_key": list(stable_key or []),
        "page_ids": sorted(page_ids or []),
    }
    payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return "finding:" + hashlib.sha256(payload).hexdigest()


def _append_reconciliation_item(report, item):
    report["items"].append(item)
    classification = item["classification"]
    report["summary"][classification] += 1


def _identity_surface_present(local_records, remote_pages):
    local_fields = {
        "project": {"sync_uid", "workspace_id", "ownership_epoch", "identity_version"},
        "task": {
            "project_sync_uid", "workspace_id", "project_ownership_epoch",
            "identity_version",
        },
    }
    remote_fields = {
        "project": ("Sync UID", "Workspace ID", "Ownership Epoch", "Identity Version"),
        "task": (
            "Project Sync UID", "Workspace ID", "Project Ownership Epoch",
            "Identity Version",
        ),
    }
    for entity in ("project", "task"):
        for row in local_records.get(entity, []):
            if set(dict(row)) & local_fields[entity]:
                return True
        for page in remote_pages.get(entity, []):
            properties = page.get("properties", {}) if isinstance(page, dict) else {}
            for name in remote_fields[entity]:
                if name in properties:
                    return True
                prop = properties.get(name, {})
                if _extract_rich_text(prop) or _extract_number(prop) is not None:
                    return True
    return False


def _identity_record_state(entity, record):
    uid_field = "sync_uid" if entity == "project" else "project_sync_uid"
    epoch_field = "ownership_epoch" if entity == "project" else "project_ownership_epoch"
    values = {
        "uid": _normalize_identity_text(record.get(uid_field)),
        "workspace_id": _normalize_identity_text(record.get("workspace_id")),
        "epoch": record.get(epoch_field),
        "identity_version": record.get("identity_version"),
    }
    if not any(value not in (None, "") for value in values.values()):
        return "legacy", values
    if any(value in (None, "") for value in values.values()):
        return "missing", values
    uid_pattern = PROJECT_UID_PATTERN
    if not uid_pattern.fullmatch(values["uid"]):
        return "invalid", values
    if not WORKSPACE_ID_PATTERN.fullmatch(values["workspace_id"]):
        return "invalid", values
    epoch = values["epoch"]
    version = values["identity_version"]
    if isinstance(epoch, bool) or not isinstance(epoch, (int, float)):
        return "invalid", values
    if int(epoch) != epoch or int(epoch) < 1:
        return "invalid", values
    if isinstance(version, bool) or not isinstance(version, (int, float)):
        return "invalid", values
    if int(version) != version or int(version) != 2:
        return "invalid", values
    values["epoch"] = int(epoch)
    values["identity_version"] = int(version)
    return "valid", values


def _identity_key(entity, record):
    if entity == "project":
        return (_normalize_identity_text(record.get("sync_uid")),)
    return (
        _normalize_identity_text(record.get("project_sync_uid")),
        _normalize_identity_text(record.get("task_id")),
    )


def _identity_finding(report, code, message, entity, record=None, page=None, **details):
    record = record or {}
    stable_key = _stable_key(entity, record) if record else ()
    finding = _finding(
        code,
        message,
        entity=entity,
        stable_key=list(stable_key),
        **details,
    )
    identity_key = _identity_key(entity, record) if record else ()
    if any(identity_key):
        finding["identity_key"] = list(identity_key)
    if record.get("id") is not None:
        finding.setdefault("local_row_ids", [record.get("id")])
    if page and page.get("id"):
        finding["page_id"] = page.get("id")
    report["findings"].append(finding)
    return finding


def _identity_candidate_item(entity, local, classification, action, candidates, reason):
    return {
        "entity": entity,
        "local_row_id": local.get("id"),
        "stable_key": list(_stable_key(entity, local)),
        "identity_key": list(_identity_key(entity, local)),
        "classification": classification,
        "match_state": reason,
        "action": action,
        "candidates": [
            _candidate_detail(entity, page, remote)
            for page, remote in candidates
        ],
        "link_state": "missing" if not local.get("notion_page_id") else "valid",
        "local_fingerprint": _mapped_fingerprint(entity, local),
        "reason": reason,
    }


def build_identity_reconciliation_report(
    local_records, remote_pages, target_row_ids=None, link_states=None,
    reachable_stable_keys=None, declined=None,
):
    """Identity v2 reconciliation; Scope matches are audit evidence only.

    ``declined`` maps (entity, identity_key) to legacy page IDs a person has
    declined for that row (T015): those pages are never offered as attach
    candidates for it again, so the row is created as a distinct Identity.
    """
    declined = declined or {}
    report = _empty_reconciliation_report()
    blocking_codes = set()
    configs = (
        ("project", _notion_row_to_project),
        ("task", _notion_row_to_task),
    )
    required_remote_identity_properties = {
        "project": {"Sync UID", "Workspace ID", "Ownership Epoch", "Identity Version"},
        "task": {
            "Project Sync UID", "Workspace ID", "Project Ownership Epoch",
            "Identity Version",
        },
    }
    for entity, converter in configs:
        locals_for_entity = [dict(row) for row in local_records.get(entity, [])]
        converted_remote = []
        for page in remote_pages.get(entity, []):
            properties = page.get("properties", {}) if isinstance(page, dict) else {}
            missing_properties = sorted(
                required_remote_identity_properties[entity] - set(properties)
            )
            if missing_properties:
                _identity_finding(
                    report, "REMOTE_IDENTITY_PROPERTY_MISSING",
                    "remote row omits Identity properties from a v2 schema response",
                    entity, page=page, missing_properties=missing_properties,
                )
                blocking_codes.add("REMOTE_IDENTITY_PROPERTY_MISSING")
                continue
            try:
                remote = converter(page)
            except (KeyError, TypeError, ValueError) as exc:
                _identity_finding(
                    report, "REMOTE_ROW_INVALID", str(exc), entity, page=page
                )
                blocking_codes.add("REMOTE_ROW_INVALID")
                continue
            state, identity = _identity_record_state(entity, remote)
            converted_remote.append((page, remote, state, identity))
            if state in {"missing", "invalid"}:
                code = "IDENTITY_MISSING" if state == "missing" else "IDENTITY_INVALID"
                _identity_finding(
                    report, code, "remote Identity is incomplete or invalid",
                    entity, record=remote, page=page,
                )
                blocking_codes.add(code)

        valid_locals = []
        local_identity_index = {}
        for local in locals_for_entity:
            state, identity = _identity_record_state(entity, local)
            if state != "valid":
                code = "IDENTITY_MISSING" if state in {"legacy", "missing"} else "IDENTITY_INVALID"
                _identity_finding(
                    report, code, "local Identity is incomplete or invalid",
                    entity, record=local,
                )
                blocking_codes.add(code)
                _append_reconciliation_item(report, _identity_candidate_item(
                    entity, local, "invalid", "error", [], code
                ))
                continue
            key = _identity_key(entity, local)
            valid_locals.append((local, identity, key))
            local_identity_index.setdefault(key, []).append(local)

        for key, rows in local_identity_index.items():
            if len(rows) > 1:
                _identity_finding(
                    report, "IDENTITY_DUPLICATE",
                    "multiple local rows share the same Identity", entity,
                    record=rows[0], local_row_ids=[row.get("id") for row in rows],
                )
                blocking_codes.add("IDENTITY_DUPLICATE")

        remote_identity_index = {}
        remote_by_page = {}
        legacy_remote = []
        for page, remote, state, identity in converted_remote:
            if page.get("id"):
                remote_by_page[page.get("id")] = (page, remote, state, identity)
            if state == "valid":
                remote_identity_index.setdefault(
                    _identity_key(entity, remote), []
                ).append((page, remote, identity))
            elif state == "legacy":
                legacy_remote.append((page, remote))
                _identity_finding(
                    report, "IDENTITY_MISSING",
                    "remote row has no Identity v2 values", entity,
                    record=remote, page=page, audit_only=True,
                )

        for key, candidates in remote_identity_index.items():
            if len(candidates) > 1:
                pages = [(page, remote) for page, remote, _identity in candidates]
                _identity_finding(
                    report, "IDENTITY_DUPLICATE",
                    "multiple remote rows share the same Identity", entity,
                    record=candidates[0][1], page=candidates[0][0],
                    page_ids=sorted(page.get("id") for page, _remote in pages),
                )
                blocking_codes.add("IDENTITY_DUPLICATE")

        for local, local_identity, key in valid_locals:
            linked = remote_by_page.get(local.get("notion_page_id"))
            if linked:
                page, remote, remote_state, remote_identity = linked
                if remote_state == "legacy":
                    _identity_finding(
                        report, "LEGACY_LINKED_CANDIDATE",
                        "linked page has no Identity v2 values", entity,
                        record=local, page=page,
                    )
                    blocking_codes.add("LEGACY_LINKED_CANDIDATE")
                    _append_reconciliation_item(report, _identity_candidate_item(
                        entity, local, "attach", "attach_candidate",
                        [(page, remote)], "LEGACY_LINKED_CANDIDATE",
                    ))
                    continue
                if remote_state != "valid":
                    continue
                if _identity_key(entity, remote) != key:
                    _identity_finding(
                        report, "IDENTITY_SPLIT_BRAIN",
                        "linked local and remote Identity differ", entity,
                        record=local, page=page,
                    )
                    blocking_codes.add("IDENTITY_SPLIT_BRAIN")
                    _append_reconciliation_item(report, _identity_candidate_item(
                        entity, local, "collision", "collision",
                        [(page, remote)], "IDENTITY_SPLIT_BRAIN",
                    ))
                    continue
                if (remote_identity["workspace_id"] != local_identity["workspace_id"]
                        or remote_identity["epoch"] != local_identity["epoch"]):
                    _identity_finding(
                        report, "IDENTITY_WORKSPACE_MISMATCH",
                        "Identity matches but workspace or ownership epoch differs",
                        entity, record=local, page=page,
                    )
                    blocking_codes.add("IDENTITY_WORKSPACE_MISMATCH")
                    _append_reconciliation_item(report, _identity_candidate_item(
                        entity, local, "collision", "collision",
                        [(page, remote)], "IDENTITY_WORKSPACE_MISMATCH",
                    ))
                    continue
                _identity_finding(
                    report, "IDENTITY_EXACT", "Identity and namespace match",
                    entity, record=local, page=page,
                )
                continue

            exact = remote_identity_index.get(key, [])
            if len(exact) > 1:
                pages = [(page, remote) for page, remote, _identity in exact]
                _append_reconciliation_item(report, _identity_candidate_item(
                    entity, local, "duplicate", "duplicate", pages,
                    "IDENTITY_DUPLICATE",
                ))
                continue
            if len(exact) == 1:
                page, remote, remote_identity = exact[0]
                if (remote_identity["workspace_id"] != local_identity["workspace_id"]
                        or remote_identity["epoch"] != local_identity["epoch"]):
                    _identity_finding(
                        report, "IDENTITY_WORKSPACE_MISMATCH",
                        "Identity matches but workspace or ownership epoch differs",
                        entity, record=local, page=page,
                    )
                    blocking_codes.add("IDENTITY_WORKSPACE_MISMATCH")
                    _append_reconciliation_item(report, _identity_candidate_item(
                        entity, local, "collision", "collision", [(page, remote)],
                        "IDENTITY_WORKSPACE_MISMATCH",
                    ))
                else:
                    _identity_finding(
                        report, "IDENTITY_EXACT", "Identity and namespace match",
                        entity, record=local, page=page,
                    )
                    _append_reconciliation_item(report, _identity_candidate_item(
                        entity, local, "attach", "attach_candidate", [(page, remote)],
                        "IDENTITY_EXACT",
                    ))
                continue

            same_scope = [
                (page, remote) for page, remote, state, _identity in converted_remote
                if state == "valid" and _stable_key(entity, remote) == _stable_key(entity, local)
            ]
            if same_scope:
                _identity_finding(
                    report, "SAME_SCOPE_DIFFERENT_IDENTITY",
                    "Scope matches but Identity differs; rows are distinct",
                    entity, record=local,
                    page_ids=sorted(page.get("id") for page, _remote in same_scope),
                )

            legacy_candidates = [
                (page, remote) for page, remote in legacy_remote
                if _stable_key(entity, remote) == _stable_key(entity, local)
            ]
            declined_pages = declined.get((entity, tuple(key)), set())
            if declined_pages and any(page.get("id") in declined_pages
                                      for page, _remote in legacy_candidates):
                _identity_finding(
                    report, "LEGACY_CANDIDATE_DECLINED",
                    "legacy Scope candidate was declined; row is a distinct Identity",
                    entity, record=local, audit_only=True,
                    page_ids=sorted(page.get("id") for page, _remote in legacy_candidates
                                    if page.get("id") in declined_pages),
                )
                legacy_candidates = [
                    (page, remote) for page, remote in legacy_candidates
                    if page.get("id") not in declined_pages
                ]
            if len(legacy_candidates) == 1:
                page, remote = legacy_candidates[0]
                _identity_finding(
                    report, "LEGACY_ATTACH_CANDIDATE",
                    "legacy Scope candidate requires an approved Migration Plan",
                    entity, record=local, page=page,
                )
                blocking_codes.add("LEGACY_ATTACH_CANDIDATE")
                _append_reconciliation_item(report, _identity_candidate_item(
                    entity, local, "attach", "attach_candidate",
                    legacy_candidates, "LEGACY_ATTACH_CANDIDATE",
                ))
            elif len(legacy_candidates) > 1:
                _identity_finding(
                    report, "LEGACY_AMBIGUOUS",
                    "multiple legacy candidates match the display key", entity,
                    record=local,
                    page_ids=sorted(page.get("id") for page, _remote in legacy_candidates),
                )
                blocking_codes.add("LEGACY_AMBIGUOUS")
                _append_reconciliation_item(report, _identity_candidate_item(
                    entity, local, "collision", "collision",
                    legacy_candidates, "LEGACY_AMBIGUOUS",
                ))
            else:
                _append_reconciliation_item(report, _identity_candidate_item(
                    entity, local, "not_found", "create_remote", [], "IDENTITY_NOT_FOUND",
                ))

        local_keys = set(local_identity_index)
        for key, candidates in remote_identity_index.items():
            if key in local_keys:
                continue
            pages = [(page, remote) for page, remote, _identity in candidates]
            _append_reconciliation_item(report, {
                "entity": entity,
                "local_row_id": None,
                "stable_key": list(_stable_key(entity, pages[0][1])),
                "identity_key": list(key),
                "classification": "remote_only" if len(pages) == 1 else "duplicate",
                "match_state": "identity_remote_only",
                "action": "skip" if len(pages) == 1 else "duplicate",
                "candidates": [
                    _candidate_detail(entity, page, remote) for page, remote in pages
                ],
                "link_state": "valid",
            })

    identity_summary = {}
    for finding in report["findings"]:
        code = finding["code"]
        identity_summary[code] = identity_summary.get(code, 0) + 1
    report["identity_summary"] = identity_summary
    critical = {
        "IDENTITY_INVALID", "IDENTITY_WORKSPACE_MISMATCH",
        "IDENTITY_SPLIT_BRAIN", "REMOTE_ROW_INVALID",
        "REMOTE_IDENTITY_PROPERTY_MISSING",
    }
    if blocking_codes & critical:
        report["status"] = "blocked"
        report["exit_code"] = 3
    elif blocking_codes:
        report["status"] = "blocked"
        report["exit_code"] = 2
    return report


def build_reconciliation_report(
    local_records, remote_pages, target_row_ids=None, link_states=None,
    reachable_stable_keys=None, declined=None,
):
    """Classify local missing links against remote stable-key indexes."""
    if _identity_surface_present(local_records, remote_pages):
        return build_identity_reconciliation_report(
            local_records,
            remote_pages,
            target_row_ids=target_row_ids,
            link_states=link_states,
            reachable_stable_keys=reachable_stable_keys,
            declined=declined,
        )
    report = _empty_reconciliation_report()
    configs = (
        ("project", _notion_row_to_project),
        ("task", _notion_row_to_task),
    )

    for entity, converter in configs:
        locals_for_entity = [dict(row) for row in local_records.get(entity, [])]
        local_index = {}
        for local in locals_for_entity:
            key = _stable_key(entity, local)
            local_index.setdefault(key, []).append(local)
        explicit_targets = set((target_row_ids or {}).get(entity, []))
        reachable_keys = {
            tuple(key) for key in (reachable_stable_keys or {}).get(entity, [])
        }
        linked_page_owners = {
            local.get("notion_page_id"): local
            for local in locals_for_entity
            if local.get("notion_page_id")
        }

        invalid_keys = set()
        duplicate_keys = set()
        for key, rows in local_index.items():
            if not _valid_stable_key(entity, key):
                invalid_keys.add(key)
                report["findings"].append(_finding(
                    "INVALID_STABLE_KEY",
                    "local stable key is empty or reserved",
                    entity=entity,
                    stable_key=list(key),
                    local_row_ids=[row.get("id") for row in rows],
                ))
            if len(rows) > 1:
                duplicate_keys.add(key)
                report["findings"].append(_finding(
                    "LOCAL_DUPLICATE_KEY",
                    "multiple local rows share the same stable key",
                    entity=entity,
                    stable_key=list(key),
                    local_row_ids=[row.get("id") for row in rows],
                ))

        remote_index = {}
        for page in remote_pages.get(entity, []):
            if not isinstance(page, dict) or not page.get("id"):
                report["findings"].append(_finding(
                    "REMOTE_ROW_INVALID",
                    "remote page has no page ID",
                    entity=entity,
                ))
                continue
            try:
                remote = converter(page)
            except (KeyError, TypeError, ValueError) as exc:
                report["findings"].append(_finding(
                    "REMOTE_ROW_INVALID",
                    str(exc),
                    entity=entity,
                    page_id=page.get("id") if isinstance(page, dict) else None,
                ))
                continue
            key = _stable_key(entity, remote)
            if not _valid_stable_key(entity, key):
                report["findings"].append(_finding(
                    "REMOTE_INVALID_STABLE_KEY",
                    "remote stable key is empty or reserved",
                    entity=entity,
                    stable_key=list(key),
                    page_id=page.get("id"),
                ))
                continue
            remote_index.setdefault(key, []).append((page, remote))

        remote_duplicate_ids = {}
        for key, candidates in remote_index.items():
            if len(candidates) < 2:
                continue
            page_ids = sorted(page.get("id") for page, _remote in candidates)
            finding_id = _reconciliation_finding_id(
                "REMOTE_DUPLICATE_KEY", entity, key, page_ids
            )
            remote_duplicate_ids[key] = finding_id
            report["findings"].append(_finding(
                "REMOTE_DUPLICATE_KEY",
                "multiple remote rows share the same stable key",
                finding_id=finding_id,
                entity=entity,
                stable_key=list(key),
                page_ids=page_ids,
            ))

        for local in locals_for_entity:
            key = _stable_key(entity, local)
            if (local.get("notion_page_id") and local.get("id") not in explicit_targets
                    and key not in reachable_keys):
                continue
            base = {
                "entity": entity,
                "local_row_id": local.get("id"),
                "stable_key": list(key),
                "candidates": [],
                "link_state": (link_states or {}).get(entity, {}).get(
                    local.get("id"), "missing" if not local.get("notion_page_id") else "valid"
                ),
                "local_fingerprint": _mapped_fingerprint(entity, local),
            }
            if key in invalid_keys or key in duplicate_keys:
                _append_reconciliation_item(report, dict(
                    base, classification="invalid", match_state="none", action="error"
                ))
                continue

            candidates = remote_index.get(key, [])
            details = [
                _candidate_detail(entity, page, remote)
                for page, remote in candidates
            ]
            if not candidates:
                _append_reconciliation_item(report, dict(
                    base,
                    classification="not_found",
                    match_state="none",
                    action="create_remote",
                ))
            elif len(candidates) > 1:
                _append_reconciliation_item(report, dict(
                    base,
                    classification="duplicate",
                    match_state="multiple",
                    action="duplicate",
                    candidates=details,
                    duplicate_finding_id=remote_duplicate_ids[key],
                ))
            elif (candidates[0][0].get("id") in linked_page_owners
                  and linked_page_owners[candidates[0][0].get("id")].get("id")
                  == local.get("id")):
                # A selected/depended-on linked row finding its own page is a
                # healthy match. Leave it item-less so the planner keeps PATCH.
                continue
            elif (candidates[0][0].get("id") in linked_page_owners
                  and linked_page_owners[candidates[0][0].get("id")].get("id")
                  != local.get("id")):
                owner = linked_page_owners[candidates[0][0].get("id")]
                _append_reconciliation_item(report, dict(
                    base,
                    classification="collision",
                    match_state="unique_incompatible",
                    action="collision",
                    candidates=details,
                    reason="candidate_already_linked_local",
                    linked_local_row_id=owner.get("id"),
                ))
            elif _identity_compatible(entity, local, candidates[0][1]):
                _append_reconciliation_item(report, dict(
                    base,
                    classification="attach",
                    match_state="unique_compatible",
                    action="attach_candidate",
                    candidates=details,
                ))
            else:
                _append_reconciliation_item(report, dict(
                    base,
                    classification="collision",
                    match_state="unique_incompatible",
                    action="collision",
                    candidates=details,
                ))

        local_keys = {
            key for key in local_index
            if _valid_stable_key(entity, key)
        }
        for key in sorted(set(remote_index) - local_keys):
            details = [
                _candidate_detail(entity, page, remote)
                for page, remote in remote_index[key]
            ]
            if len(details) > 1:
                _append_reconciliation_item(report, {
                    "entity": entity,
                    "local_row_id": None,
                    "stable_key": list(key),
                    "classification": "duplicate",
                    "match_state": "multiple",
                    "action": "duplicate",
                    "candidates": details,
                    "duplicate_finding_id": remote_duplicate_ids[key],
                    "link_state": "valid",
                })
            else:
                _append_reconciliation_item(report, {
                    "entity": entity,
                    "local_row_id": None,
                    "stable_key": list(key),
                    "classification": "remote_only",
                    "match_state": "none",
                    "action": "skip",
                    "candidates": details,
                    "link_state": "valid",
                })

    summary = report["summary"]
    fatal_findings = [
        finding for finding in report["findings"]
        if finding.get("code") != "REMOTE_DUPLICATE_KEY"
    ]
    if fatal_findings or summary["invalid"] or summary["error"]:
        report["status"] = "blocked"
        report["exit_code"] = 3
    elif summary["attach"] or summary["collision"] or summary["duplicate"]:
        report["status"] = "blocked"
        report["exit_code"] = 2
    return report


def _hashed_projection_value(value):
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def project_reconciliation_for_push(
    report, selected, known_reachable_page_ids=None
):
    """Project raw reconciliation through push reachability without data loss."""
    selected_ids = {
        entity: {row.get("id") for row in selected.get(entity, [])}
        for entity in ("project", "task")
    }
    selected_keys = {
        entity: {_stable_key(entity, row) for row in selected.get(entity, [])}
        for entity in ("project", "task")
    }
    selected_identity_keys = {
        entity: {
            _identity_key(entity, row)
            for row in selected.get(entity, [])
            if any(_identity_key(entity, row))
        }
        for entity in ("project", "task")
    }
    # A selected Task depends on its Project Identity, not every Project that
    # happens to share the same human-facing Scope ID.
    selected_identity_keys["project"].update(
        (_normalize_identity_text(row.get("project_sync_uid")),)
        for row in selected.get("task", [])
        if _normalize_identity_text(row.get("project_sync_uid"))
    )
    dependency_keys = {
        "project": {
            (_normalize_identity_text(row.get("scope_id")),)
            for row in selected.get("task", [])
            if _normalize_identity_text(row.get("scope_id"))
        },
        "task": set(),
    }
    reachable_keys = {
        entity: selected_keys[entity] | dependency_keys[entity]
        for entity in ("project", "task")
    }
    reachable_pages = set(known_reachable_page_ids or [])
    reachable_pages.update(
        row.get("notion_page_id")
        for rows in selected.values()
        for row in rows
        if row.get("notion_page_id")
    )
    for item in report.get("items", []):
        entity = item.get("entity")
        key = tuple(item.get("stable_key") or [])
        identity_key = tuple(item.get("identity_key") or [])
        if (item.get("local_row_id") in selected_ids.get(entity, set())
                or identity_key in selected_identity_keys.get(entity, set())
                or (not identity_key and key in reachable_keys.get(entity, set()))):
            reachable_pages.update(
                candidate.get("page_id") for candidate in item.get("candidates", [])
                if candidate.get("page_id")
            )

    blocking, authorization, audit = [], [], []
    seen = set()

    def add(bucket, identity):
        token = json.dumps(identity, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
        marker = (id(bucket), token)
        if marker not in seen:
            seen.add(marker)
            bucket.append(identity)

    for finding in report.get("findings", []):
        entity = finding.get("entity")
        key = tuple(finding.get("stable_key") or [])
        identity_key = tuple(finding.get("identity_key") or [])
        row_ids = set(finding.get("local_row_ids") or [])
        page_ids = set(finding.get("page_ids") or [])
        if finding.get("page_id"):
            page_ids.add(finding["page_id"])
        unknown = (
            finding.get("code") == "REMOTE_IDENTITY_PROPERTY_MISSING"
            or (finding.get("code") == "REMOTE_ROW_INVALID"
                and not key and not page_ids)
        )
        reachable = bool(
            row_ids & selected_ids.get(entity, set())
            or identity_key in selected_identity_keys.get(entity, set())
            or (not identity_key and key in reachable_keys.get(entity, set()))
            or page_ids & reachable_pages
        )
        identity = {
            "code": finding.get("code"),
            "entity": entity,
            "stable_key_hash": _hashed_projection_value(list(key)),
            "page_ids_hash": _hashed_projection_value(sorted(page_ids)),
            "reason": finding.get("reason") or finding.get("message"),
        }
        code = finding.get("code")
        if code == "IDENTITY_EXACT":
            continue
        if finding.get("audit_only"):
            add(audit, identity)
        elif code == "SAME_SCOPE_DIFFERENT_IDENTITY":
            add(audit, identity)
        elif code == "LEGACY_LINKED_CANDIDATE":
            # T014: attach cannot write Identity onto an already linked page;
            # backfill-remote-identity must run first, so this never becomes
            # an authorizable no-op.
            add(blocking if reachable else audit, identity)
        elif code == "LEGACY_ATTACH_CANDIDATE":
            add(authorization if reachable else audit, identity)
        else:
            add(blocking if reachable or unknown else audit, identity)

    for item in report.get("items", []):
        entity = item.get("entity")
        key = tuple(item.get("stable_key") or [])
        identity_key = tuple(item.get("identity_key") or [])
        reachable = (item.get("local_row_id") in selected_ids.get(entity, set())
                     or identity_key in selected_identity_keys.get(entity, set())
                     or (not identity_key and key in reachable_keys.get(entity, set())))
        classification = item.get("classification")
        if classification in {"not_found"}:
            continue
        if item.get("duplicate_finding_id"):
            continue
        if classification == "invalid" and any(
            item.get("local_row_id") in (finding.get("local_row_ids") or [])
            for finding in report.get("findings", [])
        ):
            continue
        identity = {
            "code": "RECONCILIATION_" + str(classification).upper(),
            "entity": entity,
            "stable_key_hash": _hashed_projection_value(list(key)),
            "page_ids_hash": _hashed_projection_value(sorted(
                candidate.get("page_id") for candidate in item.get("candidates", [])
                if candidate.get("page_id")
            )),
            "reason": item.get("reason") or item.get("match_state"),
        }
        if (reachable and classification == "attach"
                and item.get("reason") == "LEGACY_LINKED_CANDIDATE"):
            # T014: an already linked page needs backfill-remote-identity, not
            # an authorizable attach (attach writes nothing to Notion).
            add(blocking, identity)
        elif reachable and classification == "attach":
            add(authorization, identity)
        elif reachable and classification in {"invalid", "duplicate", "collision", "error"}:
            add(blocking, identity)
        elif not reachable:
            add(audit, identity)

    def summary(entries):
        result = {"invalid": 0, "duplicate": 0, "collision": 0,
                  "attach": 0, "remote_only": 0, "error": 0,
                  "unknown_reachability": 0}
        for entry in entries:
            code = entry["code"]
            if code == "REMOTE_ROW_INVALID" and entry in blocking:
                result["unknown_reachability"] += 1
            elif "INVALID" in code:
                result["invalid"] += 1
            elif "DUPLICATE" in code:
                result["duplicate"] += 1
            elif "COLLISION" in code:
                result["collision"] += 1
            elif "ATTACH" in code:
                result["attach"] += 1
            elif "REMOTE_ONLY" in code:
                result["remote_only"] += 1
            elif "ERROR" in code:
                result["error"] += 1
        return result

    blocking_summary = summary(blocking)
    blocking_exit = 3 if (
        blocking_summary["invalid"] or blocking_summary["error"]
        or blocking_summary["unknown_reachability"]
        or any(entry["code"] == "LOCAL_DUPLICATE_KEY" for entry in blocking)
        or any(entry["code"] in {
            "IDENTITY_INVALID", "IDENTITY_WORKSPACE_MISMATCH",
            "IDENTITY_SPLIT_BRAIN", "REMOTE_IDENTITY_PROPERTY_MISSING",
        } for entry in blocking)
    ) else (2 if blocking else 0)
    audit_sorted = sorted(audit, key=lambda entry: json.dumps(
        entry, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ))
    raw_summary = dict(report.get("summary", {}))
    raw_summary["invalid"] = sum(
        1 for finding in report.get("findings", [])
        if "INVALID" in finding.get("code", "")
    ) + sum(1 for item in report.get("items", [])
            if item.get("classification") == "invalid"
            and not any(finding.get("local_row_ids")
                        and item.get("local_row_id") in finding["local_row_ids"]
                        for finding in report.get("findings", [])))
    raw_summary["duplicate"] = sum(
        1 for finding in report.get("findings", [])
        if "DUPLICATE" in finding.get("code", "")
    )
    if report.get("identity_summary"):
        raw_summary["identity_codes"] = dict(report["identity_summary"])
    return {
        "raw_summary": raw_summary,
        "blocking": {"findings": blocking, "summary": blocking_summary,
                     "exit_code": blocking_exit},
        "authorization_required": {"findings": authorization,
                                   "operation_ids": [],
                                   "summary": summary(authorization)},
        "audit_only": {"findings": audit_sorted, "summary": summary(audit_sorted),
                       "projection_digest": _hashed_projection_value(audit_sorted)},
        "execution_status": "blocked" if blocking_exit else "pass",
        "audit_status": "warning" if audit_sorted else "pass",
        "reachability": {"reachable_page_ids": sorted(reachable_pages)},
    }


def run_reconciliation(
    conn=None,
    remote_pages=None,
    only_if_missing=False,
    target_row_ids=None,
    link_states=None,
    reachable_stable_keys=None,
):
    """Load local/remote snapshots and build a non-mutating reconciliation report."""
    owns_connection = conn is None
    if owns_connection:
        if not os.path.exists(DB_PATH):
            report = _empty_reconciliation_report()
            report["status"] = "blocked"
            report["exit_code"] = 3
            report["findings"].append(_finding(
                "LOCAL_DB_UNAVAILABLE", "local SQLite database does not exist", path=DB_PATH
            ))
            return report
        try:
            conn = _get_preflight_conn()
        except (sqlite3.Error, OSError) as exc:
            report = _empty_reconciliation_report()
            report["status"] = "blocked"
            report["exit_code"] = 3
            report["findings"].append(_finding(
                "LOCAL_DB_UNAVAILABLE", str(exc), path=DB_PATH
            ))
            return report

    try:
        excluded_scopes = _load_excluded_scopes(conn)
        tasks_frozen = _task_sync_frozen(conn)
        local_records = {
            entity: [row for row in conn.execute("SELECT * FROM %s" % table).fetchall()
                     if not excluded_scopes.row(entity, dict(row))]
            for entity, table in (("project", "projects"), ("task", "tasks"))
            if not (entity == "task" and tasks_frozen)
        }
        if tasks_frozen:
            local_records["task"] = []
        has_explicit_targets = any((target_row_ids or {}).values())
        if only_if_missing and not has_explicit_targets and not any(
            (not row["notion_page_id"] or not row["last_sync_at"]
             or (row["updated_at"] or "") > (row["last_sync_at"] or ""))
            for rows in local_records.values()
            for row in rows
        ):
            return build_reconciliation_report(
                local_records,
                {"project": [], "task": []},
                target_row_ids=target_row_ids,
                link_states=link_states,
                reachable_stable_keys=reachable_stable_keys,
            )
        if remote_pages is None:
            try:
                remote_pages = {
                    "project": _query_db(PROJECTS_DB_ID),
                    "task": [] if tasks_frozen else _query_db(TASKS_DB_ID),
                }
            except (urllib.error.HTTPError, urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
                report = _empty_reconciliation_report()
                report["status"] = "blocked"
                report["exit_code"] = 3
                report["findings"].append(_finding(
                    "RECONCILIATION_QUERY_FAILED", str(exc)
                ))
                return report
        return build_reconciliation_report(
            local_records,
            _drop_excluded_remote(
                dict(remote_pages, task=[]) if tasks_frozen else remote_pages,
                excluded_scopes),
            target_row_ids=target_row_ids,
            link_states=link_states,
            reachable_stable_keys=reachable_stable_keys,
            declined=_load_declined_candidates(conn),
        )
    except IdentityLifecycleError as exc:
        report = _empty_reconciliation_report()
        report["status"] = "blocked"
        report["exit_code"] = exc.exit_code
        report["findings"].append(_finding(exc.code, "declined candidate record is malformed"))
        return report
    except sqlite3.Error as exc:
        report = _empty_reconciliation_report()
        report["status"] = "blocked"
        report["exit_code"] = 3
        report["findings"].append(_finding(
            "LOCAL_SCHEMA_ERROR", str(exc), path=DB_PATH
        ))
        return report
    finally:
        if owns_connection:
            conn.close()


def revalidate_create_absence(reconciliation):
    """Re-query both databases before any CREATE mutation and reclassify."""
    create_items = [
        item for item in reconciliation["items"]
        if item["local_row_id"] is not None and item["action"] == "create_remote"
    ]
    if not create_items:
        return _empty_reconciliation_report()

    try:
        remote_pages = {
            "project": _query_db(PROJECTS_DB_ID),
            "task": _query_db(TASKS_DB_ID),
        }
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
        report = _empty_reconciliation_report()
        report["status"] = "blocked"
        report["exit_code"] = 3
        report["findings"].append(_finding(
            "CREATE_ABSENCE_REVALIDATION_FAILED", str(exc)
        ))
        return report

    target_row_ids = {"project": [], "task": []}
    link_states = {"project": {}, "task": {}}
    for item in create_items:
        entity = item["entity"]
        row_id = item["local_row_id"]
        target_row_ids[entity].append(row_id)
        link_states[entity][row_id] = item.get("link_state", "missing")

    return run_reconciliation(
        remote_pages=remote_pages,
        target_row_ids=target_row_ids,
        link_states=link_states,
    )


def _print_reconciliation_report(report):
    print("=== Reconciliation: %s ===" % report["status"].upper())
    print("  " + "  ".join(
        "%s=%d" % (name, count)
        for name, count in report["summary"].items()
    ))
    for item in report["items"]:
        if item["classification"] in {"attach", "collision", "duplicate", "invalid"}:
            key = "/".join(item["stable_key"])
            print("  [%s] %s %s — candidates=%d" % (
                item["classification"].upper(), item["entity"], key,
                len(item["candidates"]),
            ))
            for candidate in item["candidates"]:
                notion_parent = candidate.get("notion_parent") or {}
                parent_type = notion_parent.get("type")
                parent = notion_parent.get(parent_type) if parent_type else None
                print("    id=%s parent=%s last_edited=%s" % (
                    candidate.get("page_id"), parent,
                    candidate.get("last_edited_time"),
                ))
    for finding in report["findings"]:
        print("  [BLOCK] %s: %s" % (finding["code"], finding["message"]))


def cmd_reconcile():
    preflight = run_preflight()
    _print_preflight_report(preflight)
    if preflight["status"] != "pass":
        return 3
    report = run_reconciliation()
    _print_reconciliation_report(report)
    return report["exit_code"]


# ── DB helpers ─────────────────────────────────────────────

def _get_conn():
    if not os.path.exists(DB_PATH):
        raise sqlite3.OperationalError("DB not found: %s" % DB_PATH)
    try:
        if aiplc_paths:
            aiplc_paths.check_write(DB_PATH)
    except aiplc_paths.DbNotMain as exc:
        raise sqlite3.OperationalError(str(exc))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _open_write_conn():
    try:
        return _get_conn(), None
    except (sqlite3.Error, OSError) as exc:
        return None, _local_db_error_report(exc)


def _open_read_conn():
    try:
        return _get_preflight_conn(), None
    except (sqlite3.Error, OSError) as exc:
        return None, _local_db_error_report(exc)


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _meta_get(conn, key):
    row = conn.execute("SELECT value FROM _metadata WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def _meta_set(conn, key, value):
    conn.execute(
        "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
        (key, value)
    )


# ── Identity v2 workspace lifecycle helpers ─────────────────

def _canonical_json_digest(value):
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _coerce_canonical_identity(prefix, pattern, value):
    text = str(value)
    if not text.startswith(prefix):
        text = prefix + text
    if not pattern.fullmatch(text):
        raise ValueError("invalid canonical Identity: %s" % text)
    return text


def _new_workspace_id(factory=None):
    value = (factory or uuid.uuid4)()
    return _coerce_canonical_identity("wsp_", WORKSPACE_ID_PATTERN, value)


def _new_project_sync_uid(factory=None):
    value = (factory or uuid.uuid4)()
    return _coerce_canonical_identity("prj_", PROJECT_UID_PATTERN, value)


def _atomic_json_write(path, value):
    path = os.fspath(path)
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    try:
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        # Some virtual filesystems do not support directory fsync. The file
        # itself has already been fsynced and atomically renamed.
        pass


def _read_json_file(path):
    with open(os.fspath(path), encoding="utf-8") as handle:
        return json.load(handle)


def _identity_failpoint(selected, point):
    if selected == point:
        raise RuntimeError("injected Identity lifecycle failure: %s" % point)


def _validate_workspace_manifest(manifest):
    if manifest.get("identity_version") != 2:
        raise ValueError("WORKSPACE_IDENTITY_VERSION_INVALID")
    workspace_id = _coerce_canonical_identity(
        "wsp_", WORKSPACE_ID_PATTERN, manifest.get("workspace_id", "")
    )
    writer_epoch = manifest.get("writer_epoch")
    if not isinstance(writer_epoch, int) or writer_epoch < 1:
        raise ValueError("WORKSPACE_WRITER_EPOCH_INVALID")
    writer_id = manifest.get("writer_id")
    if not isinstance(writer_id, str) or not writer_id:
        raise ValueError("WORKSPACE_WRITER_ID_INVALID")
    expected_hash = _canonical_json_digest({
        "workspace_id": workspace_id,
        "writer_id": writer_id,
        "writer_epoch": writer_epoch,
    })
    if manifest.get("writer_authority_hash_cache") != expected_hash:
        if not manifest.get("writer_authority_hash_cache"):
            raise ValueError("WORKSPACE_AUTHORITY_HASH_MISSING")
        raise ValueError("WORKSPACE_AUTHORITY_HASH_INVALID")
    return workspace_id


def _validate_bootstrap_state(state):
    if not isinstance(state, dict):
        raise ValueError("WORKSPACE_BOOTSTRAP_STATE_INVALID")
    lifecycle = state.get("state")
    if lifecycle not in {
        "planned", "authority_committed", "manifest_committed",
        "cache_committed", "verified",
    }:
        raise ValueError("WORKSPACE_BOOTSTRAP_STATE_INVALID")
    manifest = state.get("planned_manifest")
    authority_record = state.get("authority_record")
    if not isinstance(manifest, dict) or not isinstance(authority_record, dict):
        raise ValueError("WORKSPACE_BOOTSTRAP_STATE_INVALID")
    workspace_id = _validate_workspace_manifest(manifest)
    expected_authority = {
        "workspace_id": workspace_id,
        "writer_id": manifest["writer_id"],
        "writer_epoch": manifest["writer_epoch"],
        "authority_hash": manifest["writer_authority_hash_cache"],
    }
    if authority_record != expected_authority:
        raise ValueError("WORKSPACE_BOOTSTRAP_AUTHORITY_INVALID")
    if lifecycle != "planned":
        revision = state.get("authority_revision")
        if not isinstance(revision, int) or revision < 1:
            raise ValueError("WORKSPACE_BOOTSTRAP_REVISION_INVALID")
    return manifest, authority_record


def _verify_bootstrap_progress(
    conn, authority_store, manifest_path, state, manifest, authority_record
):
    """Read back every side effect implied by the durable lifecycle state."""
    lifecycle = state["state"]
    ranks = {
        "planned": 0,
        "authority_committed": 1,
        "manifest_committed": 2,
        "cache_committed": 3,
        "verified": 4,
    }
    rank = ranks[lifecycle]
    if rank >= 1:
        current = authority_store.get_workspace(manifest["workspace_id"])
        for key, expected in authority_record.items():
            if current.get(key) != expected:
                raise ValueError("WORKSPACE_AUTHORITY_MISMATCH")
        if current.get("revision") != state["authority_revision"]:
            raise ValueError("WORKSPACE_AUTHORITY_REVISION_MISMATCH")
    if rank >= 2:
        if not os.path.exists(os.fspath(manifest_path)):
            raise ValueError("WORKSPACE_COMMITTED_MANIFEST_MISSING")
        if _read_json_file(manifest_path) != manifest:
            raise ValueError("WORKSPACE_COMMITTED_MANIFEST_MISMATCH")
    if rank >= 3:
        expected_cache = {
            "active_workspace_id": manifest["workspace_id"],
            "active_writer_epoch": str(manifest["writer_epoch"]),
            "writer_authority_hash_cache": manifest["writer_authority_hash_cache"],
        }
        actual_cache = {key: _meta_get(conn, key) for key in expected_cache}
        if actual_cache != expected_cache:
            raise ValueError("WORKSPACE_COMMITTED_CACHE_MISMATCH")


def resolve_workspace_identity(
    conn,
    authority_store=None,
    *,
    manifest_path=WORKSPACE_MANIFEST_PATH,
    repair_missing_cache=False,
):
    """Resolve current Workspace Identity without ever issuing a new ID."""
    if not os.path.exists(os.fspath(manifest_path)):
        raise ValueError("WORKSPACE_IDENTITY_MANIFEST_MISSING")
    manifest = _read_json_file(manifest_path)
    workspace_id = _validate_workspace_manifest(manifest)
    authority = None
    if authority_store is not None:
        authority = authority_store.get_workspace(workspace_id)
        authoritative = {
            key: authority[key]
            for key in ("workspace_id", "writer_id", "writer_epoch", "authority_hash")
        }
        if (
            authority["workspace_id"] != workspace_id
            or authority["writer_epoch"] != manifest["writer_epoch"]
            or authority["authority_hash"] != manifest["writer_authority_hash_cache"]
            or _canonical_json_digest(authoritative)
            != _canonical_json_digest({
                "workspace_id": manifest["workspace_id"],
                "writer_id": manifest["writer_id"],
                "writer_epoch": manifest["writer_epoch"],
                "authority_hash": manifest["writer_authority_hash_cache"],
            })
        ):
            raise ValueError("WORKSPACE_AUTHORITY_MISMATCH")
    cached_workspace = _meta_get(conn, "active_workspace_id")
    cached_epoch = _meta_get(conn, "active_writer_epoch")
    cached_hash = _meta_get(conn, "writer_authority_hash_cache")
    if (
        repair_missing_cache
        and authority is not None
        and cached_workspace is None
        and cached_epoch is None
        and cached_hash is None
    ):
        try:
            conn.execute("BEGIN IMMEDIATE")
            _meta_set(conn, "active_workspace_id", workspace_id)
            _meta_set(conn, "active_writer_epoch", str(manifest["writer_epoch"]))
            _meta_set(
                conn,
                "writer_authority_hash_cache",
                manifest["writer_authority_hash_cache"],
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        cached_workspace = workspace_id
        cached_epoch = str(manifest["writer_epoch"])
        cached_hash = manifest["writer_authority_hash_cache"]
    if cached_workspace != workspace_id:
        raise ValueError("WORKSPACE_IDENTITY_SPLIT_BRAIN")
    if cached_epoch != str(manifest["writer_epoch"]):
        raise ValueError("WORKSPACE_IDENTITY_SPLIT_BRAIN")
    if cached_hash != manifest["writer_authority_hash_cache"]:
        raise ValueError("WORKSPACE_IDENTITY_SPLIT_BRAIN")
    return dict(manifest)


def bootstrap_workspace_identity(
    conn,
    authority_store,
    *,
    manifest_path=WORKSPACE_MANIFEST_PATH,
    state_path=BOOTSTRAP_STATE_PATH,
    workspace_id_factory=None,
    writer_id="writer-local",
    fail_at=None,
):
    """Durably bootstrap manifest -> Authority CAS -> active SQLite cache."""
    manifest_path = os.fspath(manifest_path)
    state_path = os.fspath(state_path)
    if not os.path.exists(state_path) and os.path.exists(manifest_path):
        return resolve_workspace_identity(
            conn,
            authority_store,
            manifest_path=manifest_path,
            repair_missing_cache=True,
        )
    if not os.path.exists(state_path):
        _identity_failpoint(fail_at, "before_planned")
        workspace_id = _new_workspace_id(workspace_id_factory)
        authority_core = {
            "workspace_id": workspace_id,
            "writer_id": writer_id,
            "writer_epoch": 1,
        }
        authority_hash = _canonical_json_digest(authority_core)
        authority_record = {**authority_core, "authority_hash": authority_hash}
        manifest = {
            "identity_version": 2,
            **authority_core,
            "writer_authority_hash_cache": authority_hash,
        }
        _atomic_json_write(state_path, {
            "state": "planned",
            "planned_manifest": manifest,
            "authority_record": authority_record,
        })
    state = _read_json_file(state_path)
    manifest, authority_record = _validate_bootstrap_state(state)
    _verify_bootstrap_progress(
        conn, authority_store, manifest_path, state, manifest, authority_record
    )
    _identity_failpoint(fail_at, "after_planned")

    if state["state"] == "planned":
        committed = authority_store.compare_and_swap(
            "workspace", manifest["workspace_id"], None, authority_record
        )
        _identity_failpoint(fail_at, "after_authority_cas")
        _atomic_json_write(state_path, {
            **state,
            "state": "authority_committed",
            "authority_revision": committed["revision"],
        })
        state = _read_json_file(state_path)
        manifest, authority_record = _validate_bootstrap_state(state)
        _verify_bootstrap_progress(
            conn, authority_store, manifest_path, state, manifest, authority_record
        )
    _identity_failpoint(fail_at, "after_authority_committed")

    if state["state"] == "authority_committed":
        current = authority_store.get_workspace(manifest["workspace_id"])
        for key, expected in authority_record.items():
            if current.get(key) != expected:
                raise ValueError("WORKSPACE_AUTHORITY_MISMATCH")
        _atomic_json_write(manifest_path, manifest)
        _identity_failpoint(fail_at, "after_manifest_commit")
        _atomic_json_write(state_path, {**state, "state": "manifest_committed"})
        state = _read_json_file(state_path)
        manifest, authority_record = _validate_bootstrap_state(state)
        _verify_bootstrap_progress(
            conn, authority_store, manifest_path, state, manifest, authority_record
        )
    _identity_failpoint(fail_at, "after_manifest_committed")

    if state["state"] == "manifest_committed":
        try:
            conn.execute("BEGIN IMMEDIATE")
            _meta_set(conn, "active_workspace_id", manifest["workspace_id"])
            _meta_set(conn, "active_writer_epoch", str(manifest["writer_epoch"]))
            _meta_set(
                conn,
                "writer_authority_hash_cache",
                manifest["writer_authority_hash_cache"],
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        _identity_failpoint(fail_at, "after_cache_commit")
        _atomic_json_write(state_path, {**state, "state": "cache_committed"})
        state = _read_json_file(state_path)
        manifest, authority_record = _validate_bootstrap_state(state)
        _verify_bootstrap_progress(
            conn, authority_store, manifest_path, state, manifest, authority_record
        )
    _identity_failpoint(fail_at, "after_cache_committed")

    result = resolve_workspace_identity(
        conn, authority_store, manifest_path=manifest_path
    )
    if state["state"] != "verified":
        _atomic_json_write(state_path, {**state, "state": "verified"})
    _identity_failpoint(fail_at, "after_verified")
    os.unlink(state_path)
    return result


def prepare_workspace_fork(conn, state_path, *, identity_factory=None):
    """Persist a new Workspace/Project mapping without mutating current rows."""
    state_path = os.fspath(state_path)
    project_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()
    }
    if not {"workspace_id", "sync_uid", "identity_version"}.issubset(project_columns):
        raise ValueError("WORKSPACE_FORK_REQUIRES_IDENTITY_V2")
    source_workspace_id = _meta_get(conn, "active_workspace_id")
    if source_workspace_id is None:
        raise ValueError("WORKSPACE_FORK_ACTIVE_WORKSPACE_MISSING")
    source_workspace_id = _coerce_canonical_identity(
        "wsp_", WORKSPACE_ID_PATTERN, source_workspace_id
    )
    current_projects = {
        str(row[0]): {
            "source_workspace_id": row[1],
            "source_sync_uid": row[2],
            "scope_id": row[3],
        }
        for row in conn.execute(
            "SELECT id, workspace_id, sync_uid, scope_id FROM projects "
            "WHERE workspace_id = ? ORDER BY id",
            (source_workspace_id,),
        ).fetchall()
    }
    source_rows_digest = _canonical_json_digest(current_projects)
    occupied_workspace_ids = {
        row[0] for row in conn.execute(
            "SELECT DISTINCT workspace_id FROM projects"
        ).fetchall()
    } | {source_workspace_id}
    occupied_project_uids = {
        row[0] for row in conn.execute("SELECT sync_uid FROM projects").fetchall()
    }
    if os.path.exists(state_path):
        state = _read_json_file(state_path)
        if state.get("identity_version") != 2 or state.get("state") != "planned":
            raise ValueError("WORKSPACE_FORK_STATE_INVALID")
        if state.get("source_workspace_id") != source_workspace_id:
            raise ValueError("WORKSPACE_FORK_STATE_SOURCE_MISMATCH")
        if state.get("source_rows_digest") != source_rows_digest:
            raise ValueError("WORKSPACE_FORK_STATE_SOURCE_MISMATCH")
        result_workspace_id = _coerce_canonical_identity(
            "wsp_", WORKSPACE_ID_PATTERN, state.get("result_workspace_id", "")
        )
        if result_workspace_id in occupied_workspace_ids:
            raise ValueError("WORKSPACE_FORK_REUSES_SOURCE_WORKSPACE")
        if set(state.get("projects", {})) != set(current_projects):
            raise ValueError("WORKSPACE_FORK_STATE_SOURCE_MISMATCH")
        result_uids = set()
        for row_id, expected in current_projects.items():
            planned = state["projects"][row_id]
            if any(planned.get(key) != value for key, value in expected.items()):
                raise ValueError("WORKSPACE_FORK_STATE_SOURCE_MISMATCH")
            result_uid = _coerce_canonical_identity(
                "prj_", PROJECT_UID_PATTERN, planned.get("result_sync_uid", "")
            )
            if result_uid in occupied_project_uids:
                raise ValueError("WORKSPACE_FORK_REUSES_SOURCE_PROJECT_UID")
            if result_uid in result_uids:
                raise ValueError("WORKSPACE_FORK_STATE_DUPLICATE_UID")
            result_uids.add(result_uid)
        return state
    workspace_id = _new_workspace_id(identity_factory)
    if workspace_id in occupied_workspace_ids:
        raise ValueError("WORKSPACE_FORK_REUSES_SOURCE_WORKSPACE")
    mapping = {}
    result_uids = set()
    for row_id, source in current_projects.items():
        result_uid = _new_project_sync_uid(identity_factory)
        if result_uid in occupied_project_uids:
            raise ValueError("WORKSPACE_FORK_REUSES_SOURCE_PROJECT_UID")
        if result_uid in result_uids:
            raise ValueError("WORKSPACE_FORK_STATE_DUPLICATE_UID")
        result_uids.add(result_uid)
        mapping[row_id] = {
            **source,
            "result_sync_uid": result_uid,
        }
    state = {
        "identity_version": 2,
        "state": "planned",
        "source_workspace_id": source_workspace_id,
        "source_rows_digest": source_rows_digest,
        "result_workspace_id": workspace_id,
        "projects": mapping,
    }
    _atomic_json_write(state_path, state)
    return state


# ── Identity v2.0 lifecycle runtime: fork / activate-writer (T007) ──

WORKSPACE_FORK_PLAN_VERSION = 1
WRITER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
FORK_COPY_EXCLUDED_COLUMNS = {"id", "notion_page_id", "notion_last_edited",
                              "last_sync_at"}
V2_1_DEFERRED_COMMANDS = {
    "transfer-project": "Project ownership transfer",
    "takeover-writer": "writer takeover of an existing workspace",
    "handoff-repair": "pending-operation writer handoff repair",
}


class IdentityLifecycleError(ValueError):
    """Fail-closed lifecycle refusal carrying the T001 §12.1 exit code."""

    def __init__(self, code, exit_code):
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


def _writer_manifest(workspace_id, writer_id, writer_epoch=1):
    core = {"workspace_id": workspace_id, "writer_id": writer_id,
            "writer_epoch": writer_epoch}
    return {"identity_version": 2, **core,
            "writer_authority_hash_cache": _canonical_json_digest(core)}


def _fork_schema_ready(conn):
    projects = _unique_index_column_sets(conn, "projects")
    tasks = _unique_index_column_sets(conn, "tasks")
    return (("workspace_id", "scope_id") in projects
            and ("sync_uid",) in projects and ("scope_id",) not in projects
            and ("project_sync_uid", "task_id") in tasks
            and ("task_id", "scope_id") not in tasks)


def _fork_source_rows(conn, workspace_id):
    projects = [dict(row) for row in conn.execute(
        "SELECT * FROM projects WHERE workspace_id=? ORDER BY id", (workspace_id,)
    ).fetchall()]
    tasks = [dict(row) for row in conn.execute(
        "SELECT * FROM tasks WHERE workspace_id=? ORDER BY id", (workspace_id,)
    ).fetchall()]
    return projects, tasks


def _fork_plan_id(plan):
    return _canonical_json_digest({key: value for key, value in plan.items()
                                   if key != "plan_id"})


def build_workspace_fork_plan(conn, *, writer_id, identity_factory=None,
                              manifest_path=None):
    """Fix a Workspace fork mapping before any mutation (Plan = durable mapping).

    Every Project of the manifest-selected workspace receives exactly one new
    ``sync_uid`` and the fork receives one new ``workspace_id``.  Notion links
    are not inherited; authority records are deferred to v2.1 (T010).
    """
    if not isinstance(writer_id, str) or not WRITER_ID_PATTERN.fullmatch(writer_id):
        raise IdentityLifecycleError("WORKSPACE_FORK_WRITER_ID_INVALID", 64)
    if _local_identity_schema_version(conn) != 2 or not _fork_schema_ready(conn):
        raise IdentityLifecycleError("WORKSPACE_FORK_REQUIRES_ENFORCED_V2", 3)
    try:
        manifest = resolve_workspace_identity(
            conn, manifest_path=manifest_path or WORKSPACE_MANIFEST_PATH)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise IdentityLifecycleError(str(exc) or "WORKSPACE_IDENTITY_INVALID", 3)
    source_workspace_id = manifest["workspace_id"]
    projects, tasks = _fork_source_rows(conn, source_workspace_id)
    project_epochs = {}
    for row in projects:
        state, values = _identity_record_state("project", row)
        if state != "valid":
            raise IdentityLifecycleError("WORKSPACE_FORK_SOURCE_IDENTITY_INVALID", 3)
        project_epochs[values["uid"]] = values["epoch"]
    for row in tasks:
        state, values = _identity_record_state("task", row)
        if state != "valid" or project_epochs.get(values["uid"]) != values["epoch"]:
            raise IdentityLifecycleError("WORKSPACE_FORK_TASK_ORPHAN", 3)
    occupied_workspaces = {
        row[0] for table in ("projects", "tasks")
        for row in conn.execute(
            "SELECT DISTINCT workspace_id FROM %s WHERE workspace_id IS NOT NULL"
            % table).fetchall()
    } | {source_workspace_id}
    occupied_uids = {
        row[0] for row in conn.execute(
            "SELECT sync_uid FROM projects WHERE sync_uid IS NOT NULL").fetchall()
    }
    result_workspace_id = _new_workspace_id(identity_factory)
    if result_workspace_id in occupied_workspaces:
        raise IdentityLifecycleError("WORKSPACE_FORK_REUSES_SOURCE_WORKSPACE", 2)
    mapping = {}
    for row in projects:
        result_uid = _new_project_sync_uid(identity_factory)
        if result_uid in occupied_uids or result_uid in mapping.values():
            raise IdentityLifecycleError("WORKSPACE_FORK_REUSES_SOURCE_PROJECT_UID", 2)
        mapping[row["sync_uid"]] = result_uid
    result_manifest = _writer_manifest(result_workspace_id, writer_id)
    plan = {
        "plan_schema_version": WORKSPACE_FORK_PLAN_VERSION,
        "direction": "workspace_fork",
        "identity_version": 2,
        "source": {
            "workspace_id": source_workspace_id,
            "rows_digest": _canonical_json_digest(
                {"projects": projects, "tasks": tasks}),
            "project_count": len(projects),
            "task_count": len(tasks),
        },
        "result": {
            "workspace_id": result_workspace_id,
            "writer_id": writer_id,
            "writer_epoch": 1,
            "writer_authority_hash": result_manifest["writer_authority_hash_cache"],
        },
        "projects": [{
            "source_row_id": row["id"], "source_sync_uid": row["sync_uid"],
            "scope_id": row["scope_id"], "result_sync_uid": mapping[row["sync_uid"]],
        } for row in projects],
        "tasks": [{
            "source_row_id": row["id"],
            "source_project_sync_uid": row["project_sync_uid"],
            "task_id": row["task_id"],
            "result_project_sync_uid": mapping[row["project_sync_uid"]],
        } for row in tasks],
        "mutation_budget": {"sqlite_project_inserts": len(projects),
                            "sqlite_task_inserts": len(tasks),
                            "notion": 0, "authority": 0},
        "authority": "deferred_v2_1",
        "links": "not_inherited",
    }
    plan["plan_id"] = _fork_plan_id(plan)
    return plan


def validate_workspace_fork_plan(plan, expected_plan_id=None):
    if not isinstance(plan, dict) or set(plan) != {
        "plan_id", "plan_schema_version", "direction", "identity_version",
        "source", "result", "projects", "tasks", "mutation_budget",
        "authority", "links",
    }:
        return False
    try:
        if (plan["plan_schema_version"] != WORKSPACE_FORK_PLAN_VERSION
                or plan["direction"] != "workspace_fork"
                or plan["identity_version"] != 2
                or plan["authority"] != "deferred_v2_1"
                or plan["links"] != "not_inherited"):
            return False
        if plan["plan_id"] != _fork_plan_id(plan):
            return False
        if expected_plan_id is not None and expected_plan_id != plan["plan_id"]:
            return False
        source, result = plan["source"], plan["result"]
        if (not WORKSPACE_ID_PATTERN.fullmatch(source["workspace_id"])
                or not WORKSPACE_ID_PATTERN.fullmatch(result["workspace_id"])
                or source["workspace_id"] == result["workspace_id"]
                or not WRITER_ID_PATTERN.fullmatch(result["writer_id"])
                or result["writer_epoch"] != 1
                or result["writer_authority_hash"] != _writer_manifest(
                    result["workspace_id"], result["writer_id"]
                )["writer_authority_hash_cache"]):
            return False
        if (source["project_count"] != len(plan["projects"])
                or source["task_count"] != len(plan["tasks"])
                or plan["mutation_budget"] != {
                    "sqlite_project_inserts": len(plan["projects"]),
                    "sqlite_task_inserts": len(plan["tasks"]),
                    "notion": 0, "authority": 0}):
            return False
        mapping = {}
        for item in plan["projects"]:
            if (not PROJECT_UID_PATTERN.fullmatch(item["source_sync_uid"])
                    or not PROJECT_UID_PATTERN.fullmatch(item["result_sync_uid"])
                    or item["source_sync_uid"] in mapping
                    or item["result_sync_uid"] in mapping.values()):
                return False
            mapping[item["source_sync_uid"]] = item["result_sync_uid"]
        if set(mapping) & set(mapping.values()):
            return False
        return all(
            mapping.get(item["source_project_sync_uid"])
            == item["result_project_sync_uid"] for item in plan["tasks"])
    except (KeyError, TypeError, AttributeError):
        return False


def _expected_fork_rows(plan, projects, tasks):
    mapping = {item["source_sync_uid"]: item["result_sync_uid"]
               for item in plan["projects"]}
    workspace_id = plan["result"]["workspace_id"]
    expected = {"projects": [], "tasks": []}
    for row in projects:
        copied = {key: value for key, value in row.items()
                  if key not in FORK_COPY_EXCLUDED_COLUMNS}
        copied.update(workspace_id=workspace_id, sync_uid=mapping[row["sync_uid"]],
                      ownership_epoch=1, identity_version=2)
        expected["projects"].append(copied)
    for row in tasks:
        copied = {key: value for key, value in row.items()
                  if key not in FORK_COPY_EXCLUDED_COLUMNS}
        copied.update(workspace_id=workspace_id,
                      project_sync_uid=mapping[row["project_sync_uid"]],
                      project_ownership_epoch=1, identity_version=2)
        expected["tasks"].append(copied)
    expected["projects"].sort(key=lambda row: row["sync_uid"])
    expected["tasks"].sort(key=lambda row: (row["project_sync_uid"], row["task_id"]))
    return expected


def _fork_result_rows(conn, workspace_id):
    projects = [
        {key: value for key, value in dict(row).items()
         if key not in FORK_COPY_EXCLUDED_COLUMNS}
        for row in conn.execute(
            "SELECT * FROM projects WHERE workspace_id=? ORDER BY sync_uid",
            (workspace_id,)).fetchall()]
    tasks = [
        {key: value for key, value in dict(row).items()
         if key not in FORK_COPY_EXCLUDED_COLUMNS}
        for row in conn.execute(
            "SELECT * FROM tasks WHERE workspace_id=? "
            "ORDER BY project_sync_uid, task_id", (workspace_id,)).fetchall()]
    linked = conn.execute(
        "SELECT (SELECT COUNT(*) FROM projects WHERE workspace_id=? AND "
        "(notion_page_id IS NOT NULL OR last_sync_at IS NOT NULL)) + "
        "(SELECT COUNT(*) FROM tasks WHERE workspace_id=? AND "
        "(notion_page_id IS NOT NULL OR last_sync_at IS NOT NULL))",
        (workspace_id, workspace_id)).fetchone()[0]
    return {"projects": projects, "tasks": tasks}, linked


def _fork_readback(conn, plan, expected_digest):
    rows, _linked = _fork_result_rows(conn, plan["result"]["workspace_id"])
    return (len(rows["projects"]) == plan["source"]["project_count"]
            and len(rows["tasks"]) == plan["source"]["task_count"]
            and _canonical_json_digest(rows) == expected_digest)


def _insert_copied_row(conn, table, row):
    columns = sorted(row)
    conn.execute("INSERT INTO %s (%s) VALUES (%s)" % (
        table, ", ".join(columns), ",".join("?" for _ in columns)),
        [row[column] for column in columns])


def execute_workspace_fork_plan(conn, plan, *, expected_plan_id, state_path,
                                manifest_path=None, fail_at=None):
    """Apply a fixed fork Plan once; resume never issues another Identity."""
    if not validate_workspace_fork_plan(plan, expected_plan_id):
        raise IdentityLifecycleError("WORKSPACE_FORK_PLAN_INVALID", 2)
    state_path = os.fspath(state_path)
    state = _read_json_file(state_path) if os.path.exists(state_path) else None
    if state is not None and (state.get("plan_id") != plan["plan_id"]
                              or state.get("state") not in {
                                  "planned", "rows_committed", "verified"}):
        raise IdentityLifecycleError("WORKSPACE_FORK_STATE_PLAN_MISMATCH", 2)
    if state is not None and state["state"] == "verified":
        # Terminal: the fork was read back once.  Result rows may legitimately
        # evolve afterwards, so a rerun is a no-op and never re-issues IDs.
        return {"plan_id": plan["plan_id"], "state": "verified",
                "inserted_rows": 0,
                "result_workspace_id": plan["result"]["workspace_id"]}
    try:
        manifest = resolve_workspace_identity(
            conn, manifest_path=manifest_path or WORKSPACE_MANIFEST_PATH)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise IdentityLifecycleError(str(exc) or "WORKSPACE_IDENTITY_INVALID", 3)
    if manifest["workspace_id"] not in {plan["source"]["workspace_id"],
                                        plan["result"]["workspace_id"]}:
        raise IdentityLifecycleError("WORKSPACE_FORK_SOURCE_MISMATCH", 2)
    if not _fork_schema_ready(conn):
        raise IdentityLifecycleError("WORKSPACE_FORK_REQUIRES_ENFORCED_V2", 3)
    result_ws = plan["result"]["workspace_id"]
    existing, _linked = _fork_result_rows(conn, result_ws)
    inserted = 0
    if not existing["projects"] and not existing["tasks"]:
        if state is not None and state["state"] != "planned":
            raise IdentityLifecycleError("WORKSPACE_FORK_RESULT_ROWS_MISSING", 3)
        projects, tasks = _fork_source_rows(conn, plan["source"]["workspace_id"])
        if _canonical_json_digest({"projects": projects, "tasks": tasks}) != (
                plan["source"]["rows_digest"]):
            raise IdentityLifecycleError("WORKSPACE_FORK_SOURCE_CHANGED", 2)
        result_uids = [item["result_sync_uid"] for item in plan["projects"]]
        if result_uids and conn.execute(
                "SELECT COUNT(*) FROM projects WHERE sync_uid IN (%s)" % ",".join(
                    "?" for _ in result_uids), result_uids).fetchone()[0]:
            raise IdentityLifecycleError("WORKSPACE_FORK_REUSES_SOURCE_PROJECT_UID", 2)
        expected = _expected_fork_rows(plan, projects, tasks)
        expected_digest = _canonical_json_digest(expected)
        if state is not None and state.get("expected_rows_digest") != expected_digest:
            raise IdentityLifecycleError("WORKSPACE_FORK_STATE_PLAN_MISMATCH", 2)
        # Durable intent before mutation: resume adopts exactly these rows.
        state = {"plan_id": plan["plan_id"], "state": "planned",
                 "expected_rows_digest": expected_digest}
        _atomic_json_write(state_path, state)
        _identity_failpoint(fail_at, "after_planned")
        try:
            conn.execute("BEGIN IMMEDIATE")
            for row in expected["projects"]:
                _insert_copied_row(conn, "projects", row)
            for row in expected["tasks"]:
                _insert_copied_row(conn, "tasks", row)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        inserted = len(expected["projects"]) + len(expected["tasks"])
        _identity_failpoint(fail_at, "after_sqlite_commit")
    elif state is None:
        raise IdentityLifecycleError("WORKSPACE_FORK_RESULT_WITHOUT_JOURNAL", 3)
    if not _fork_readback(conn, plan, state["expected_rows_digest"]):
        raise IdentityLifecycleError("WORKSPACE_FORK_READBACK_MISMATCH", 5)
    if state["state"] == "planned":
        state = dict(state, state="rows_committed")
        _atomic_json_write(state_path, state)
    if state["state"] == "rows_committed":
        state = dict(state, state="verified")
        _atomic_json_write(state_path, state)
    return {"plan_id": plan["plan_id"], "state": state["state"],
            "inserted_rows": inserted, "result_workspace_id": result_ws}


def _pending_journal_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM _metadata WHERE key LIKE 'pending_push:%'"
    ).fetchone()[0]


def _active_cache(conn):
    return {key: _meta_get(conn, key) for key in (
        "active_workspace_id", "active_writer_epoch", "writer_authority_hash_cache")}


def _cache_for_manifest(manifest):
    return {"active_workspace_id": manifest["workspace_id"],
            "active_writer_epoch": str(manifest["writer_epoch"]),
            "writer_authority_hash_cache": manifest["writer_authority_hash_cache"]}


def classify_writer_activation(conn, *, workspace_id, fork_plan=None,
                               fork_plan_id=None, fork_state_path=None,
                               bootstrap_state_path=None, activation_state_path=None,
                               manifest_path=None):
    """Read-only decision for ``activate-writer`` (no write connection).

    Allowed only for a verified fork result or a locally bootstrapped
    workspace whose cache is not yet active.  Any change of the writer of an
    existing workspace is a takeover and returns V2_1_REQUIRED.
    """
    manifest_path = os.fspath(manifest_path or WORKSPACE_MANIFEST_PATH)
    current = (_read_json_file(manifest_path)
               if os.path.exists(manifest_path) else None)
    cache = _active_cache(conn)
    activation = (_read_json_file(activation_state_path)
                  if activation_state_path and os.path.exists(activation_state_path)
                  else None)

    def decision(kind, exit_code, code, target=None, source=None):
        return {"decision": kind, "exit_code": exit_code, "code": code,
                "target_manifest": target, "source_manifest": source}

    if fork_plan is not None:
        if not validate_workspace_fork_plan(fork_plan, fork_plan_id):
            return decision("refuse", 2, "WORKSPACE_FORK_PLAN_INVALID")
        if fork_plan["result"]["workspace_id"] != workspace_id:
            return decision("refuse", 2, "ACTIVATION_TARGET_MISMATCH")
        target = _writer_manifest(workspace_id, fork_plan["result"]["writer_id"])
        fork_state = (_read_json_file(fork_state_path)
                      if fork_state_path and os.path.exists(fork_state_path) else {})
        if (fork_state.get("plan_id") != fork_plan["plan_id"]
                or fork_state.get("state") != "verified"):
            return decision("refuse", 3, "WORKSPACE_FORK_NOT_VERIFIED")
        # Already active: rerun is a no-op even after the fork rows evolved.
        if current == target and cache == _cache_for_manifest(target):
            return decision("noop", 0, "WRITER_ALREADY_ACTIVE", target)
        source_ws = fork_plan["source"]["workspace_id"]
        source_manifest = (activation or {}).get("source_manifest") or {}
        in_progress = (
            activation is not None
            and activation.get("plan_ref") == fork_plan["plan_id"]
            and activation.get("state") in {"planned", "manifest_committed"}
            and activation.get("target_manifest") == target
            and source_manifest.get("workspace_id") == source_ws
            and cache in (_cache_for_manifest(target),
                          _cache_for_manifest(source_manifest)))
        if (current and current.get("workspace_id") == workspace_id
                and current != target and not in_progress):
            return decision("deferred", 3, "V2_1_REQUIRED", target)
        if _pending_journal_count(conn):
            return decision("refuse", 3, "PENDING_JOURNAL_BLOCKS_ACTIVATION")
        if in_progress and current in (target, source_manifest):
            return decision("activate", 0, "ACTIVATE_FORK_RESUME", target,
                            source_manifest)
        # First activation: the fork result must still read back exactly.
        # A genuine fork result was never synced; linked rows mean an existing,
        # operating workspace would be taken over (v2.1 only).
        if _fork_result_rows(conn, workspace_id)[1]:
            return decision("deferred", 3, "V2_1_REQUIRED", target)
        if not _fork_readback(conn, fork_plan, fork_state.get("expected_rows_digest")):
            return decision("refuse", 3, "WORKSPACE_FORK_NOT_VERIFIED")
        if not current or current.get("workspace_id") != source_ws:
            return decision("refuse", 2, "ACTIVATION_SOURCE_MISMATCH")
        if cache != _cache_for_manifest(current):
            return decision("refuse", 3, "WORKSPACE_IDENTITY_SPLIT_BRAIN")
        return decision("activate", 0, "ACTIVATE_FORK", target, current)

    try:
        state = _read_json_file(bootstrap_state_path)
        planned, _authority = _validate_bootstrap_state(state)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return decision("refuse", 2, "BOOTSTRAP_STATE_INVALID")
    if planned["workspace_id"] != workspace_id:
        return decision("refuse", 2, "ACTIVATION_TARGET_MISMATCH")
    if state["state"] in {"planned", "authority_committed"}:
        return decision("refuse", 3, "BOOTSTRAP_INCOMPLETE")
    if current is None:
        return decision("refuse", 3, "WORKSPACE_IDENTITY_MANIFEST_MISSING")
    if current != planned:
        if current.get("workspace_id") == workspace_id:
            return decision("deferred", 3, "V2_1_REQUIRED", planned)
        return decision("refuse", 3, "WORKSPACE_IDENTITY_SPLIT_BRAIN")
    if cache == _cache_for_manifest(planned):
        return decision("noop", 0, "WRITER_ALREADY_ACTIVE", planned)
    if cache.get("active_workspace_id") == workspace_id:
        return decision("deferred", 3, "V2_1_REQUIRED", planned)
    if any(value is not None for value in cache.values()):
        return decision("refuse", 3, "WORKSPACE_IDENTITY_SPLIT_BRAIN")
    # Only the interrupted cache step of a *new* bootstrap is local activation.
    # A cache_committed/verified state, or a workspace that already owns rows
    # (clone, rebuilt DB), would re-activate an existing writer: v2.1 only.
    if state["state"] != "manifest_committed":
        return decision("deferred", 3, "V2_1_REQUIRED", planned)
    owned_rows = conn.execute(
        "SELECT (SELECT COUNT(*) FROM projects WHERE workspace_id=?) + "
        "(SELECT COUNT(*) FROM tasks WHERE workspace_id=?)",
        (workspace_id, workspace_id)).fetchone()[0]
    if owned_rows:
        return decision("deferred", 3, "V2_1_REQUIRED", planned)
    if _pending_journal_count(conn):
        return decision("refuse", 3, "PENDING_JOURNAL_BLOCKS_ACTIVATION")
    return decision("activate", 0, "ACTIVATE_BOOTSTRAP", planned, current)


def execute_writer_activation(conn, decision, *, plan_ref, activation_state_path,
                              manifest_path=None, fail_at=None):
    """Local-only activation: manifest (fork only) -> SQLite cache -> verify."""
    if decision["decision"] != "activate":
        raise IdentityLifecycleError(decision["code"], decision["exit_code"] or 2)
    manifest_path = os.fspath(manifest_path or WORKSPACE_MANIFEST_PATH)
    target = decision["target_manifest"]
    state = (_read_json_file(activation_state_path)
             if os.path.exists(activation_state_path) else None)
    if state is None or state.get("plan_ref") != plan_ref:
        state = {"plan_ref": plan_ref, "state": "planned", "target_manifest": target,
                 "source_manifest": decision["source_manifest"]}
        _atomic_json_write(activation_state_path, state)
    if state["target_manifest"] != target:
        raise IdentityLifecycleError("ACTIVATION_STATE_MISMATCH", 2)
    _identity_failpoint(fail_at, "after_planned")
    current = (_read_json_file(manifest_path)
               if os.path.exists(manifest_path) else None)
    if current != target:
        _atomic_json_write(manifest_path, target)
    _identity_failpoint(fail_at, "after_manifest_write")
    if state["state"] == "planned":
        state = dict(state, state="manifest_committed")
        _atomic_json_write(activation_state_path, state)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for key, value in _cache_for_manifest(target).items():
            _meta_set(conn, key, value)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    _identity_failpoint(fail_at, "after_cache_commit")
    resolved = resolve_workspace_identity(conn, manifest_path=manifest_path)
    if resolved != target:
        raise IdentityLifecycleError("ACTIVATION_READBACK_MISMATCH", 5)
    state = dict(state, state="verified")
    _atomic_json_write(activation_state_path, state)
    return {"state": "verified", "workspace_id": target["workspace_id"],
            "writer_epoch": target["writer_epoch"]}


def _lifecycle_exit(exc):
    if isinstance(exc, IdentityLifecycleError):
        print("ERROR: %s" % exc.code)
        return exc.exit_code
    print("ERROR: %s" % exc)
    return 3


def cmd_fork_workspace(options):
    plan_path = options.get("--plan")
    try:
        if options.get("--dry-run"):
            plan_out = options["--plan-out"]
            conn, error = _open_read_conn()
            if error:
                return 3
            try:
                if os.path.exists(plan_out):
                    # Rerun reuses the fixed mapping; it never issues new IDs.
                    plan = _read_json_file(plan_out)
                    if not validate_workspace_fork_plan(plan):
                        raise IdentityLifecycleError("WORKSPACE_FORK_PLAN_INVALID", 2)
                    projects, tasks = _fork_source_rows(
                        conn, plan["source"]["workspace_id"])
                    if (_canonical_json_digest({"projects": projects, "tasks": tasks})
                            != plan["source"]["rows_digest"]):
                        raise IdentityLifecycleError("WORKSPACE_FORK_SOURCE_CHANGED", 2)
                    if plan["result"]["writer_id"] != options["--writer-id"]:
                        raise IdentityLifecycleError("WORKSPACE_FORK_PLAN_CONFLICT", 2)
                    reused = True
                else:
                    plan = build_workspace_fork_plan(
                        conn, writer_id=options["--writer-id"])
                    reused = False
            finally:
                conn.close()
            if not reused:
                _atomic_json_write(plan_out, plan)
            print(json.dumps({
                "plan_id": plan["plan_id"], "state": "planned", "reused": reused,
                "source_workspace_id": _short_identity(plan["source"]["workspace_id"]),
                "result_workspace_id": _short_identity(plan["result"]["workspace_id"]),
                "projects": len(plan["projects"]), "tasks": len(plan["tasks"]),
            }, ensure_ascii=False, sort_keys=True))
            return 0
        state_path = options.get("--state") or plan_path + ".state.json"
        plan = _read_json_file(plan_path)
        if options.get("--status"):
            if not validate_workspace_fork_plan(plan):
                raise IdentityLifecycleError("WORKSPACE_FORK_PLAN_INVALID", 2)
            state = (_read_json_file(state_path) if os.path.exists(state_path)
                     else {"plan_id": plan["plan_id"], "state": "not_started"})
            if state.get("plan_id") != plan["plan_id"]:
                raise IdentityLifecycleError("WORKSPACE_FORK_STATE_PLAN_MISMATCH", 2)
            print(json.dumps({"plan_id": plan["plan_id"], "state": state["state"]},
                             sort_keys=True))
            return 0
        conn, error = _open_write_conn()
        if error:
            return 3
        try:
            result = execute_workspace_fork_plan(
                conn, plan, expected_plan_id=options["--plan-id"],
                state_path=state_path)
        finally:
            conn.close()
        print(json.dumps(dict(result, result_workspace_id=_short_identity(
            result["result_workspace_id"])), sort_keys=True))
        print("NEXT: activate-writer --workspace-id %s --fork-plan FILE --plan-id "
              "SHA256 enables the fork writer locally." % result["result_workspace_id"])
        return 0
    except (IdentityLifecycleError, KeyError, TypeError, ValueError, OSError,
            json.JSONDecodeError, sqlite3.Error) as exc:
        return _lifecycle_exit(exc)


def cmd_activate_writer(options):
    workspace_id = options["--workspace-id"]
    fork_plan_path = options.get("--fork-plan")
    bootstrap_state = options.get("--bootstrap-state")
    try:
        fork_plan = _read_json_file(fork_plan_path) if fork_plan_path else None
        ref_path = fork_plan_path or bootstrap_state
        activation_state_path = ref_path + ".activation.json"
        fork_state_path = (options.get("--fork-state") or (
            fork_plan_path + ".state.json")) if fork_plan_path else None
        conn, error = _open_read_conn()
        if error:
            return 3
        try:
            decision = classify_writer_activation(
                conn, workspace_id=workspace_id, fork_plan=fork_plan,
                fork_plan_id=options.get("--plan-id"),
                fork_state_path=fork_state_path,
                bootstrap_state_path=bootstrap_state,
                activation_state_path=activation_state_path,
            )
        finally:
            conn.close()
        print(json.dumps({"decision": decision["decision"], "code": decision["code"],
                          "workspace_id": _short_identity(workspace_id)},
                         sort_keys=True))
        if decision["decision"] == "deferred":
            print("V2_1_REQUIRED: changing the writer of an existing workspace "
                  "requires IdentityAuthorityStore/ApprovalStore (T010).")
        if decision["decision"] != "activate" or options.get("--dry-run"):
            return decision["exit_code"]
        conn, error = _open_write_conn()
        if error:
            return 3
        try:
            result = execute_writer_activation(
                conn, decision,
                plan_ref=fork_plan["plan_id"] if fork_plan else workspace_id,
                activation_state_path=activation_state_path)
        finally:
            conn.close()
        print(json.dumps(dict(result, workspace_id=_short_identity(
            result["workspace_id"])), sort_keys=True))
        return 0
    except (IdentityLifecycleError, KeyError, TypeError, ValueError, OSError,
            json.JSONDecodeError, sqlite3.Error) as exc:
        return _lifecycle_exit(exc)


def cmd_deferred_v21(command, options):
    """transfer/takeover/handoff: fail closed before any read, API, or write."""
    print("V2_1_REQUIRED: %s is not available in Identity v2.0 (%s)." % (
        command, V2_1_DEFERRED_COMMANDS[command]))
    print("  Requires IdentityAuthorityStore CAS, ApprovalStore, and WriterProof "
          "(T010). No database, manifest, or Notion access was performed.")
    return 3


# ── PULL ───────────────────────────────────────────────────

def _instant_gt(left, right):
    left_dt, right_dt = _parse_iso_datetime(left), _parse_iso_datetime(right)
    if left_dt is None:
        return False
    if right_dt is None:
        return True
    if left_dt.tzinfo is None:
        left_dt = left_dt.replace(tzinfo=timezone.utc)
    if right_dt.tzinfo is None:
        right_dt = right_dt.replace(tzinfo=timezone.utc)
    return left_dt.astimezone(timezone.utc) > right_dt.astimezone(timezone.utc)


def _operation_sync_baseline(now, observed_updated_at):
    """Return a Phase-B baseline that cannot precede the Phase-A row state."""
    return observed_updated_at if _instant_gt(observed_updated_at, now) else now


def build_pull_guard(conn, remote_pages):
    report = {"status": "pass", "exit_code": 0, "findings": [],
              "summary": {"insert_local": 0, "patch_local": 0, "no_op": 0,
                          "conflict": 0, "duplicate": 0, "invalid": 0,
                          "orphan": 0}}
    indexes = {}
    converted = {}
    for entity, table, converter in (
        ("project", "projects", _notion_row_to_project),
        ("task", "tasks", _notion_row_to_task),
    ):
        local_rows = [dict(row) for row in conn.execute(
            "SELECT * FROM %s" % table).fetchall()]
        local_index, linked = {}, {}
        for row in local_rows:
            local_index.setdefault(_stable_key(entity, row), []).append(row)
            if row.get("notion_page_id"):
                linked[row["notion_page_id"]] = row
        remote_index, remote_rows = {}, []
        for page in remote_pages[entity]:
            row = converter(page)
            key = _stable_key(entity, row)
            remote_index.setdefault(key, []).append((page, row))
            remote_rows.append((page, row, key))
        indexes[entity] = (local_index, remote_index, linked)
        converted[entity] = remote_rows
        for key, rows in local_index.items():
            if not _valid_stable_key(entity, key):
                report["summary"]["invalid"] += 1
            if len(rows) > 1:
                report["summary"]["duplicate"] += 1
        for key, rows in remote_index.items():
            if not _valid_stable_key(entity, key):
                report["summary"]["invalid"] += 1
            if len(rows) > 1:
                report["summary"]["duplicate"] += 1
    project_keys = set(indexes["project"][0]) | set(indexes["project"][1])
    for entity in ("project", "task"):
        local_index, _, linked = indexes[entity]
        for page, remote, key in converted[entity]:
            local_rows = local_index.get(key, [])
            linked_row = linked.get(page["id"])
            if linked_row is not None and _stable_key(entity, linked_row) != key:
                report["summary"]["conflict"] += 1
                report["findings"].append(_finding(
                    "LINKED_IDENTITY_CHANGED", "linked stable key changed",
                    entity=entity, page_id=page["id"]))
            elif not local_rows:
                if entity == "task" and key[0] not in project_keys:
                    report["summary"]["orphan"] += 1
                else:
                    report["summary"]["insert_local"] += 1
            elif len(local_rows) == 1:
                local = local_rows[0]
                if local.get("notion_page_id") != page["id"]:
                    report["summary"]["conflict"] += 1
                    report["findings"].append(_finding(
                        "STABLE_KEY_PAGE_COLLISION", "stable key belongs to another page",
                        entity=entity, stable_key=list(key)))
                else:
                    local_dirty = _instant_gt(local.get("updated_at"), local.get("last_sync_at"))
                    remote_dirty = _instant_gt(
                        remote.get("notion_last_edited"), local.get("notion_last_edited"))
                    if local_dirty:
                        report["summary"]["conflict"] += 1
                        report["findings"].append(_finding(
                            "BOTH_DIRTY" if remote_dirty else "LOCAL_DIRTY_PULL_BLOCKED",
                            "pull would overwrite local changes", entity=entity,
                            stable_key=list(key)))
                    elif remote_dirty:
                        report["summary"]["patch_local"] += 1
                    else:
                        report["summary"]["no_op"] += 1
    if report["summary"]["invalid"] or report["summary"]["orphan"]:
        report["status"], report["exit_code"] = "blocked", 3
    elif report["summary"]["conflict"] or report["summary"]["duplicate"]:
        report["status"], report["exit_code"] = "blocked", 2
    return report


def _unique_index_column_sets(conn, table):
    result = set()
    for row in conn.execute("PRAGMA index_list(%s)" % table).fetchall():
        if not row[2]:
            continue
        result.add(tuple(
            item[2] for item in conn.execute(
                "PRAGMA index_info(%s)" % json.dumps(row[1])
            ).fetchall()
        ))
    return result


def build_identity_pull_guard(conn, remote_pages, context):
    """Identity v2 pull classification; Scope never merges two Identities.

    Only valid remote rows of the manifest-selected workspace may INSERT/PATCH.
    Other workspaces and ``legacy`` (Identity-less / legacy_excluded) rows are
    audit-only and read-only.  Linked disagreement is split-brain (exit 3).
    """
    workspace_id = context["workspace_id"]
    report = {"status": "pass", "exit_code": 0, "findings": [], "operations": [],
              "summary": {"insert_local": 0, "patch_local": 0, "no_op": 0,
                          "conflict": 0, "duplicate": 0, "invalid": 0,
                          "orphan": 0, "foreign_workspace": 0,
                          "legacy_skipped": 0}}
    critical, ambiguous = set(), set()

    def block(code, message, bucket, entity, **details):
        report["findings"].append(_finding(code, message, entity=entity, **details))
        bucket.add(code)

    scope_unique_global = ("scope_id",) in _unique_index_column_sets(conn, "projects")
    task_scope_unique = ("task_id", "scope_id") in _unique_index_column_sets(
        conn, "tasks")
    local = {}
    for entity, table in (("project", "projects"), ("task", "tasks")):
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM %s ORDER BY id" % table).fetchall()]
        by_page, by_identity = {}, {}
        for row in rows:
            if row.get("notion_page_id"):
                by_page[row["notion_page_id"]] = row
            state, _values = _identity_record_state(entity, row)
            if state == "valid":
                by_identity.setdefault(_identity_key(entity, row), []).append(row)
        local[entity] = {"rows": rows, "by_page": by_page,
                         "by_identity": by_identity}

    converted = {}
    for entity, converter in (("project", _notion_row_to_project),
                              ("task", _notion_row_to_task)):
        items, remote_index = [], {}
        for page in remote_pages[entity]:
            try:
                remote = converter(page)
            except (KeyError, TypeError, ValueError):
                report["summary"]["invalid"] += 1
                block("REMOTE_ROW_INVALID", "remote row cannot be converted",
                      critical, entity)
                continue
            state, values = _identity_record_state(entity, remote)
            items.append((page, remote, state, values))
            if state == "valid":
                remote_index.setdefault(_identity_key(entity, remote), []).append(
                    (page, values))
        for key, pages in remote_index.items():
            if len(pages) < 2:
                continue
            report["summary"]["duplicate"] += 1
            # Only a duplicate touching this workspace (or one of its links)
            # blocks; another workspace's duplicate is audit-only (§8.3).
            touches_current = any(
                values["workspace_id"] == workspace_id
                or page.get("id") in local[entity]["by_page"]
                for page, values in pages) or any(
                row.get("workspace_id") == workspace_id
                for row in local[entity]["by_identity"].get(key, []))
            if touches_current:
                block("IDENTITY_DUPLICATE", "multiple remote rows share an Identity",
                      ambiguous, entity, identity_key=list(key))
            else:
                report["findings"].append(_finding(
                    "IDENTITY_DUPLICATE", "another workspace has duplicate rows",
                    entity=entity, identity_key=list(key), audit_only=True))
        converted[entity] = (items, remote_index)

    inserting_projects = {}
    for entity in ("project", "task"):
        items, remote_index = converted[entity]
        index = local[entity]
        for page, remote, state, values in items:
            linked = index["by_page"].get(page["id"])
            if state == "legacy":
                # Remote-only legacy or legacy_excluded: never INSERT/PATCH.
                report["summary"]["legacy_skipped"] += 1
                report["findings"].append(_finding(
                    "LEGACY_REMOTE_SKIPPED", "Identity-less remote row is read-only",
                    entity=entity, page_id=page["id"], audit_only=True))
                continue
            if state != "valid":
                report["summary"]["invalid"] += 1
                block("IDENTITY_INVALID" if state == "invalid" else "IDENTITY_MISSING",
                      "remote Identity is incomplete or invalid", critical, entity,
                      page_id=page["id"])
                continue
            key = _identity_key(entity, remote)
            if len(remote_index.get(key, [])) > 1:
                continue
            if linked is not None:
                linked_state, linked_values = _identity_record_state(entity, linked)
                if linked_state != "valid" or _identity_key(entity, linked) != key:
                    report["summary"]["conflict"] += 1
                    block("IDENTITY_SPLIT_BRAIN",
                          "linked local and remote Identity differ", critical,
                          entity, page_id=page["id"])
                    continue
                if (linked_values["workspace_id"] != values["workspace_id"]
                        or linked_values["epoch"] != values["epoch"]):
                    report["summary"]["conflict"] += 1
                    block("IDENTITY_WORKSPACE_MISMATCH",
                          "Identity matches but workspace or epoch differs",
                          critical, entity, page_id=page["id"])
                    continue
            # Same UID with another workspace/epoch is a mismatch (§3.2-4),
            # detected before any foreign-workspace audit skip.
            epoch_field = ("ownership_epoch" if entity == "project"
                           else "project_ownership_epoch")
            if any(row.get("workspace_id") != values["workspace_id"]
                   or row.get(epoch_field) != values["epoch"]
                   for row in index["by_identity"].get(key, [])):
                report["summary"]["conflict"] += 1
                block("IDENTITY_WORKSPACE_MISMATCH",
                      "local Identity is owned by another workspace or epoch",
                      critical, entity, page_id=page["id"])
                continue
            if values["workspace_id"] != workspace_id:
                report["summary"]["foreign_workspace"] += 1
                report["findings"].append(_finding(
                    "FOREIGN_WORKSPACE_SKIPPED",
                    "remote row belongs to another workspace Identity",
                    entity=entity, page_id=page["id"], audit_only=True))
                continue
            exact = index["by_identity"].get(key, [])
            if linked is None and exact:
                report["summary"]["conflict"] += 1
                code = ("IDENTITY_WORKSPACE_MISMATCH"
                        if any(row.get("workspace_id") != workspace_id for row in exact)
                        else "IDENTITY_PAGE_COLLISION")
                block(code, "local Identity is bound to another/no page",
                      critical if code == "IDENTITY_WORKSPACE_MISMATCH" else ambiguous,
                      entity, page_id=page["id"])
                continue
            if linked is not None:
                local_dirty = _instant_gt(linked.get("updated_at"),
                                          linked.get("last_sync_at"))
                remote_dirty = _instant_gt(remote.get("notion_last_edited"),
                                           linked.get("notion_last_edited"))
                if local_dirty:
                    report["summary"]["conflict"] += 1
                    block("BOTH_DIRTY" if remote_dirty else "LOCAL_DIRTY_PULL_BLOCKED",
                          "pull would overwrite local changes", ambiguous, entity,
                          page_id=page["id"])
                elif remote_dirty and _pull_patch_collides(
                        entity, remote, linked, index["rows"], workspace_id,
                        scope_unique_global, task_scope_unique):
                    report["summary"]["conflict"] += 1
                    block("SAME_SCOPE_DIFFERENT_IDENTITY",
                          "remote rename collides with another local Identity",
                          ambiguous, entity, page_id=page["id"])
                elif remote_dirty:
                    report["summary"]["patch_local"] += 1
                    report["operations"].append({
                        "entity": entity, "action": "patch", "page_id": page["id"],
                        "local_row_id": linked["id"], "identity_key": list(key),
                        "row": remote})
                else:
                    report["summary"]["no_op"] += 1
                continue
            # Unlinked, current-workspace, new Identity -> INSERT candidate.
            if entity == "project":
                scope = _normalize_identity_text(remote.get("scope_id"))
                same_scope = [
                    row for row in index["rows"]
                    if _normalize_identity_text(row.get("scope_id")) == scope
                    and (scope_unique_global or row.get("workspace_id") == workspace_id
                         or row.get("workspace_id") is None)
                ]
                if same_scope:
                    report["summary"]["conflict"] += 1
                    block("SAME_SCOPE_DIFFERENT_IDENTITY",
                          "Scope already belongs to another local Identity",
                          ambiguous, entity, page_id=page["id"])
                    continue
                inserting_projects[values["uid"]] = (values["workspace_id"],
                                                     values["epoch"])
            else:
                parent = local["project"]["by_identity"].get((values["uid"],), [])
                parent_ok = (bool(parent) and all(
                    row.get("workspace_id") == values["workspace_id"]
                    and row.get("ownership_epoch") == values["epoch"]
                    for row in parent)) or inserting_projects.get(values["uid"]) == (
                        values["workspace_id"], values["epoch"])
                if not parent_ok:
                    report["summary"]["orphan"] += 1
                    block("TASK_PROJECT_IDENTITY_MISSING",
                          "remote Task parent Identity is not local", critical,
                          entity, page_id=page["id"])
                    continue
                if task_scope_unique and any(
                        _normalize_identity_text(row.get("task_id"))
                        == _normalize_identity_text(remote.get("task_id"))
                        and _normalize_identity_text(row.get("scope_id"))
                        == _normalize_identity_text(remote.get("scope_id"))
                        for row in index["rows"]):
                    report["summary"]["conflict"] += 1
                    block("SAME_SCOPE_DIFFERENT_IDENTITY",
                          "Task display key already belongs to another Identity",
                          ambiguous, entity, page_id=page["id"])
                    continue
            report["summary"]["insert_local"] += 1
            report["operations"].append({
                "entity": entity, "action": "insert", "page_id": page["id"],
                "local_row_id": None, "identity_key": list(key), "row": remote})
    # Planned operations must not collide with each other on a display-key
    # UNIQUE (two INSERTs, or an INSERT and a rename PATCH, on one Scope).
    planned = {}
    for operation in report["operations"]:
        row = operation["row"]
        if operation["entity"] == "project":
            display_key = ("project", _normalize_identity_text(row.get("scope_id")))
        elif task_scope_unique:
            display_key = ("task", _normalize_identity_text(row.get("task_id")),
                           _normalize_identity_text(row.get("scope_id")))
        else:
            continue
        planned[display_key] = planned.get(display_key, 0) + 1
    for display_key, count in sorted(planned.items()):
        if count > 1:
            report["summary"]["conflict"] += 1
            block("SAME_SCOPE_DIFFERENT_IDENTITY",
                  "several pulled Identities target one display key", ambiguous,
                  display_key[0])
    if critical:
        report["status"], report["exit_code"] = "blocked", 3
    elif ambiguous:
        report["status"], report["exit_code"] = "blocked", 2
    return report


def _pull_patch_collides(entity, remote, linked, rows, workspace_id,
                         scope_unique_global, task_scope_unique):
    """Would PATCHing ``linked`` with ``remote`` violate a display-key UNIQUE?"""
    scope = _normalize_identity_text(remote.get("scope_id"))
    others = [row for row in rows if row.get("id") != linked.get("id")]
    if entity == "project":
        return any(
            _normalize_identity_text(row.get("scope_id")) == scope
            and (scope_unique_global or row.get("workspace_id") == workspace_id)
            for row in others)
    task_id = _normalize_identity_text(remote.get("task_id"))
    return task_scope_unique and any(
        _normalize_identity_text(row.get("task_id")) == task_id
        and _normalize_identity_text(row.get("scope_id")) == scope
        for row in others)


def _apply_identity_pull_operation(conn, operation, now):
    row = operation["row"]
    if operation["entity"] == "project":
        columns = ("notion_page_id", "scope_id", "name", "goal", "owner", "status",
                   "mode", "depth", "system", "parent_scope", "top_page_url",
                   "start_date", "deadline", "notion_last_edited")
        identity_columns = ("workspace_id", "sync_uid", "ownership_epoch",
                            "identity_version")
        table = "projects"
    else:
        columns = ("notion_page_id", "task_id", "scope_id", "name", "status", "type",
                   "priority", "estimate_days", "output_url", "completed_at",
                   "notion_last_edited")
        identity_columns = ("workspace_id", "project_sync_uid",
                            "project_ownership_epoch", "identity_version")
        table = "tasks"
    values = [row[column] for column in columns]
    identity_values = [
        int(row[column]) if column.endswith(("epoch", "version"))
        else _normalize_identity_text(row[column])
        for column in identity_columns
    ]
    if operation["action"] == "insert":
        # updated_at == last_sync_at: a freshly pulled row is not local-dirty.
        all_columns = columns + identity_columns + ("last_sync_at", "updated_at")
        cursor = conn.execute(
            "INSERT INTO %s (%s) VALUES (%s)" % (
                table, ", ".join(all_columns), ",".join("?" for _ in all_columns)),
            values + identity_values + [now, now])
        return cursor.rowcount == 1
    mutable = columns[1:]
    identity_where = " AND ".join("%s=?" % column for column in identity_columns)
    cursor = conn.execute(
        "UPDATE %s SET %s, last_sync_at=? WHERE id=? AND notion_page_id=? AND %s" % (
            table, ", ".join("%s=?" % column for column in mutable), identity_where),
        values[1:] + [now, operation["local_row_id"], operation["page_id"]]
        + identity_values)
    return cursor.rowcount == 1


def _verify_identity_pull_operation(conn, operation):
    table = "projects" if operation["entity"] == "project" else "tasks"
    row = conn.execute("SELECT * FROM %s WHERE notion_page_id=?" % table,
                       (operation["page_id"],)).fetchone()
    if not row:
        return False
    row = dict(row)
    return (_identity_key(operation["entity"], row)
            == tuple(operation["identity_key"])
            and _identity_record_state(operation["entity"], row)[0] == "valid"
            and _mapped_fingerprint(operation["entity"], row)
            == _mapped_fingerprint(operation["entity"], operation["row"]))


def _cmd_pull_identity_v2(dry_run, remote_pages, context):
    guard_conn, db_error = _open_read_conn()
    if db_error:
        _print_preflight_report(db_error)
        return 3
    try:
        guard = build_identity_pull_guard(guard_conn, remote_pages, context)
    finally:
        guard_conn.close()
    _print_pull_guard(guard)
    if guard["exit_code"]:
        return guard["exit_code"]
    print("=== Pull: Notion → Local %s(workspace=%s) ===" % (
        "(DRY RUN) " if dry_run else "", _short_identity(context["workspace_id"])))
    for operation in guard["operations"]:
        row = operation["row"]
        print("  [%s] %s%s" % (
            operation["action"].upper(), row.get("scope_id"),
            "/" + row["task_id"] if operation["entity"] == "task" else ""))
    if dry_run:
        return 0
    conn, db_error = _open_write_conn()
    if db_error:
        _print_preflight_report(db_error)
        return 3
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Revalidate under the write lock: the context and classification must
        # be unchanged, otherwise nothing is written.
        late_context = _identity_plan_context(conn)
        late_guard = build_identity_pull_guard(conn, remote_pages, late_context)
        if (late_context != context or late_guard["exit_code"]
                or late_guard["operations"] != guard["operations"]):
            conn.rollback()
            print("=== Pull Revalidation ===")
            _print_pull_guard(late_guard)
            return late_guard["exit_code"] or 2
        now = _now_iso()
        ordered = sorted(guard["operations"],
                         key=lambda op: 0 if op["entity"] == "project" else 1)
        for operation in ordered:
            if not _apply_identity_pull_operation(conn, operation, now):
                conn.rollback()
                return 4
        _meta_set(conn, "last_pull_at", now)
        conn.commit()
        failed = [op for op in ordered if not _verify_identity_pull_operation(conn, op)]
        print("  [POST-VERIFY %s] pull operations=%d" % (
            "FAIL" if failed else "PASS", len(ordered)))
        return 5 if failed else 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        conn.rollback()
        return 3
    except sqlite3.Error as exc:
        conn.rollback()
        print("ERROR: pull write failed: %s" % exc)
        return 4
    finally:
        conn.close()


def _print_pull_guard(report):
    print("=== Pull Plan: %s ===" % report["status"].upper())
    print("  " + "  ".join("%s=%d" % item for item in report["summary"].items()))
    for finding in report["findings"]:
        print("  [BLOCK] %s: %s" % (finding["code"], finding["message"]))


def _project_cancelled_sync_guard(scope_id=None, sync_uid=None):
    """External lifecycle schema/metadata support is intentionally deferred.
    Reject before writes; never map cancellation to planned/completed.
    """
    conn, error = _open_read_conn()
    if error:
        return False  # existing preflight reports DB errors
    try:
        where, params = "status='cancelled'", []
        if scope_id:
            where += ' AND scope_id=?'; params.append(scope_id)
        if sync_uid and 'sync_uid' in {r[1] for r in conn.execute('PRAGMA table_info(projects)')}:
            where += ' AND sync_uid=?'; params.append(sync_uid)
        if conn.execute('SELECT 1 FROM projects WHERE '+where+' LIMIT 1', params).fetchone():
            print('[BLOCK] PROJECT_CANCELLED_EXTERNAL_SYNC_UNSUPPORTED: local cancellation is preserved; external schema/metadata migration requires separate authorization')
            return True
        return False
    finally:
        conn.close()


def cmd_pull(dry_run=False, skip_preflight=False):
    if _project_cancelled_sync_guard():
        return 3
    if not skip_preflight:
        preflight = run_preflight()
        _print_preflight_report(preflight)
        if preflight["status"] != "pass":
            return 3
    guard_conn, db_error = _open_read_conn()
    if db_error:
        _print_preflight_report(db_error)
        return 3
    # Shared Identity projection decides the v1/v2 engine before any API read.
    selection = resolve_identity_selection(guard_conn)
    if selection["exit_code"]:
        guard_conn.close()
        print("  [BLOCK] %s: %s" % (selection["finding"]["code"],
                                   selection["finding"]["message"]))
        return selection["exit_code"]
    try:
        excluded_scopes = _load_excluded_scopes(guard_conn)
        tasks_frozen = _task_sync_frozen(guard_conn)
    except IdentityLifecycleError as exc:
        guard_conn.close()
        return _lifecycle_exit(exc)
    try:
        remote_pages = {
            "project": _query_db(PROJECTS_DB_ID),
            "task": [] if tasks_frozen else _query_db(TASKS_DB_ID),
        }
    except (urllib.error.HTTPError, urllib.error.URLError, OSError,
            RuntimeError, ValueError) as exc:
        guard_conn.close()
        print("ERROR: pull query failed: %s" % exc)
        return 4
    # T016: pages of sync-excluded Scopes are never pulled into local rows.
    remote_pages = _drop_excluded_remote(remote_pages, excluded_scopes)
    if selection["mode"] == "v2":
        guard_conn.close()
        return _cmd_pull_identity_v2(dry_run, remote_pages, selection["context"])
    guard = build_pull_guard(guard_conn, remote_pages)
    guard_conn.close()
    _print_pull_guard(guard)
    if guard["exit_code"]:
        return guard["exit_code"]
    conn, db_error = _open_read_conn() if dry_run else _open_write_conn()
    if db_error:
        _print_preflight_report(db_error)
        return 3
    if not dry_run:
        conn.execute("BEGIN IMMEDIATE")
        late_guard = build_pull_guard(conn, remote_pages)
        if late_guard["exit_code"]:
            conn.rollback()
            conn.close()
            print("=== Pull Revalidation ===")
            _print_pull_guard(late_guard)
            return late_guard["exit_code"]
    now = _now_iso()
    stats = {"inserted": 0, "updated": 0, "skipped": 0, "conflict": 0}

    print("=== Pull: Notion → Local %s===" % ("(DRY RUN) " if dry_run else ""))

    # Projects
    print("\n[Projects] Querying Notion DB...")
    pages = remote_pages["project"]
    print("  %d rows fetched from Notion" % len(pages))

    for page in pages:
        row = _notion_row_to_project(page)
        nid = row["notion_page_id"]
        local = conn.execute(
            "SELECT *, notion_last_edited, last_sync_at, updated_at FROM projects WHERE notion_page_id=?",
            (nid,)
        ).fetchone()

        if local is None:
            stats["inserted"] += 1
            if dry_run:
                print("  [INSERT] %s — %s" % (row["scope_id"], row["name"]))
            else:
                conn.execute("""
                    INSERT INTO projects
                        (notion_page_id, scope_id, name, goal, owner, status,
                         mode, depth, system, parent_scope, top_page_url,
                         start_date, deadline, notion_last_edited, last_sync_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (nid, row["scope_id"], row["name"], row["goal"],
                      row["owner"], row["status"], row["mode"], row["depth"],
                      row["system"], row["parent_scope"], row["top_page_url"],
                      row["start_date"], row["deadline"],
                      row["notion_last_edited"], now))
                print("  [INSERT] %s — %s" % (row["scope_id"], row["name"]))
        else:
            notion_newer = _instant_gt(
                row["notion_last_edited"], local["notion_last_edited"]
            )
            never_synced = local["last_sync_at"] is None
            local_dirty = _instant_gt(local["updated_at"], local["last_sync_at"])

            if not notion_newer and not never_synced:
                stats["skipped"] += 1
                continue

            if local_dirty and notion_newer:
                stats["conflict"] += 1
                print("  [CONFLICT] %s — %s (both modified)" % (row["scope_id"], row["name"]))
                continue

            stats["updated"] += 1
            if dry_run:
                print("  [UPDATE] %s — %s" % (row["scope_id"], row["name"]))
            else:
                conn.execute("""
                    UPDATE projects SET
                        scope_id=?, name=?, goal=?, owner=?, status=?,
                        mode=?, depth=?, system=?, parent_scope=?, top_page_url=?,
                        start_date=?, deadline=?, notion_last_edited=?, last_sync_at=?
                    WHERE notion_page_id=?
                """, (row["scope_id"], row["name"], row["goal"],
                      row["owner"], row["status"], row["mode"], row["depth"],
                      row["system"], row["parent_scope"], row["top_page_url"],
                      row["start_date"], row["deadline"],
                      row["notion_last_edited"], now, nid))
                print("  [UPDATE] %s — %s" % (row["scope_id"], row["name"]))

    # Tasks
    print("\n[Tasks] Querying Notion DB...")
    pages = remote_pages["task"]
    print("  %d rows fetched from Notion" % len(pages))

    for page in pages:
        row = _notion_row_to_task(page)
        nid = row["notion_page_id"]
        local = conn.execute(
            "SELECT *, notion_last_edited, last_sync_at, updated_at FROM tasks WHERE notion_page_id=?",
            (nid,)
        ).fetchone()

        if local is None:
            stats["inserted"] += 1
            if dry_run:
                print("  [INSERT] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))
            else:
                conn.execute("""
                    INSERT INTO tasks
                        (notion_page_id, task_id, scope_id, name, status,
                         type, priority, estimate_days, output_url,
                         completed_at, notion_last_edited, last_sync_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (nid, row["task_id"], row["scope_id"], row["name"],
                      row["status"], row["type"], row["priority"],
                      row["estimate_days"], row["output_url"],
                      row["completed_at"], row["notion_last_edited"], now))
                print("  [INSERT] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))
        else:
            notion_newer = _instant_gt(
                row["notion_last_edited"], local["notion_last_edited"]
            )
            never_synced = local["last_sync_at"] is None
            local_dirty = _instant_gt(local["updated_at"], local["last_sync_at"])

            if not notion_newer and not never_synced:
                stats["skipped"] += 1
                continue

            if local_dirty and notion_newer:
                stats["conflict"] += 1
                print("  [CONFLICT] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))
                continue

            stats["updated"] += 1
            if dry_run:
                print("  [UPDATE] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))
            else:
                conn.execute("""
                    UPDATE tasks SET
                        task_id=?, scope_id=?, name=?, status=?,
                        type=?, priority=?, estimate_days=?, output_url=?,
                        completed_at=?, notion_last_edited=?, last_sync_at=?
                    WHERE notion_page_id=?
                """, (row["task_id"], row["scope_id"], row["name"],
                      row["status"], row["type"], row["priority"],
                      row["estimate_days"], row["output_url"],
                      row["completed_at"], row["notion_last_edited"], now, nid))
                print("  [UPDATE] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))

    if not dry_run:
        _meta_set(conn, "last_pull_at", now)
        conn.commit()

    conn.close()
    print("\n--- Pull Summary ---")
    print("  Inserted: %d  Updated: %d  Skipped: %d  Conflicts: %d" % (
        stats["inserted"], stats["updated"], stats["skipped"], stats["conflict"]))
    return 0


# ── PUSH ───────────────────────────────────────────────────

def _legacy_cmd_push(dry_run=False, skip_preflight=False):
    target_row_ids = {"project": [], "task": []}
    link_states = {"project": {}, "task": {}}
    if not skip_preflight:
        preflight = run_preflight(allow_reconcilable_links=True)
        _print_preflight_report(preflight)
        if preflight["status"] != "pass":
            return 3
        for table, entity in (("projects", "project"), ("tasks", "task")):
            for link in preflight["links"][table]:
                link_states[entity][link["local_row_id"]] = link["state"]
                if link["state"] in {"not_found", "wrong_parent", "trashed"}:
                    target_row_ids[entity].append(link["local_row_id"])
    reconciliation = run_reconciliation(
        only_if_missing=True,
        target_row_ids=target_row_ids,
        link_states=link_states,
    )
    _print_reconciliation_report(reconciliation)
    if reconciliation["exit_code"]:
        return reconciliation["exit_code"]
    revalidation = revalidate_create_absence(reconciliation)
    print("=== Create Absence Revalidation ===")
    _print_reconciliation_report(revalidation)
    if revalidation["exit_code"]:
        return revalidation["exit_code"]
    reconciliation_actions = {
        (item["entity"], item["local_row_id"]): item["action"]
        for item in reconciliation["items"]
        if item["local_row_id"] is not None
    }
    conn, db_error = _open_read_conn() if dry_run else _open_write_conn()
    if db_error:
        _print_preflight_report(db_error)
        return 3
    now = _now_iso()
    stats = {"pushed": 0, "created": 0, "skipped": 0}

    print("=== Push: Local → Notion %s===" % ("(DRY RUN) " if dry_run else ""))

    # Projects — find locally modified rows
    print("\n[Projects]")
    rows = conn.execute("""
        SELECT * FROM projects
        WHERE notion_page_id IS NULL
           OR last_sync_at IS NULL
           OR updated_at > last_sync_at
    """).fetchall()
    selected_ids = {row["id"] for row in rows}
    stale_create_ids = [
        row_id for (entity, row_id), action in reconciliation_actions.items()
        if entity == "project" and action == "create_remote" and row_id not in selected_ids
    ]
    if stale_create_ids:
        placeholders = ",".join("?" for _ in stale_create_ids)
        rows.extend(conn.execute(
            "SELECT * FROM projects WHERE id IN (%s)" % placeholders,
            stale_create_ids,
        ).fetchall())

    for row in rows:
        force_create = reconciliation_actions.get(("project", row["id"])) == "create_remote"
        nid = None if force_create else row["notion_page_id"]
        row_dict = dict(row)

        if nid:
            stats["pushed"] += 1
            props = _project_to_notion_props(row_dict)
            if dry_run:
                print("  [PATCH] %s — %s" % (row["scope_id"], row["name"]))
            else:
                _api_call("PATCH", "/v1/pages/%s" % nid,
                          {"properties": props})
                conn.execute(
                    "UPDATE projects SET last_sync_at=?, notion_last_edited=? WHERE id=?",
                    (now, now, row["id"])
                )
                print("  [PATCH] %s — %s" % (row["scope_id"], row["name"]))
        else:
            stats["created"] += 1
            props = _project_to_notion_props(row_dict)
            if dry_run:
                print("  [CREATE] %s — %s" % (row["scope_id"], row["name"]))
            else:
                resp = _api_call("POST", "/v1/pages", {
                    "parent": {"database_id": PROJECTS_DB_ID},
                    "properties": props,
                })
                new_id = resp["id"]
                conn.execute(
                    "UPDATE projects SET notion_page_id=?, last_sync_at=?, notion_last_edited=? WHERE id=?",
                    (new_id, now, resp.get("last_edited_time", now), row["id"])
                )
                print("  [CREATE] %s — %s (id: %s)" % (row["scope_id"], row["name"], new_id))

    # Tasks — find locally modified rows
    print("\n[Tasks]")
    rows = conn.execute("""
        SELECT * FROM tasks
        WHERE notion_page_id IS NULL
           OR last_sync_at IS NULL
           OR updated_at > last_sync_at
    """).fetchall()
    selected_ids = {row["id"] for row in rows}
    stale_create_ids = [
        row_id for (entity, row_id), action in reconciliation_actions.items()
        if entity == "task" and action == "create_remote" and row_id not in selected_ids
    ]
    if stale_create_ids:
        placeholders = ",".join("?" for _ in stale_create_ids)
        rows.extend(conn.execute(
            "SELECT * FROM tasks WHERE id IN (%s)" % placeholders,
            stale_create_ids,
        ).fetchall())

    for row in rows:
        force_create = reconciliation_actions.get(("task", row["id"])) == "create_remote"
        nid = None if force_create else row["notion_page_id"]
        row_dict = dict(row)

        if nid:
            stats["pushed"] += 1
            props = _task_to_notion_props(row_dict)
            if dry_run:
                print("  [PATCH] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))
            else:
                _api_call("PATCH", "/v1/pages/%s" % nid,
                          {"properties": props})
                conn.execute(
                    "UPDATE tasks SET last_sync_at=?, notion_last_edited=? WHERE id=?",
                    (now, now, row["id"])
                )
                print("  [PATCH] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))
        else:
            stats["created"] += 1
            props = _task_to_notion_props(row_dict)
            if dry_run:
                print("  [CREATE] %s/%s — %s" % (row["scope_id"], row["task_id"], row["name"]))
            else:
                resp = _api_call("POST", "/v1/pages", {
                    "parent": {"database_id": TASKS_DB_ID},
                    "properties": props,
                })
                new_id = resp["id"]
                conn.execute(
                    "UPDATE tasks SET notion_page_id=?, last_sync_at=?, notion_last_edited=? WHERE id=?",
                    (new_id, now, resp.get("last_edited_time", now), row["id"])
                )
                print("  [CREATE] %s/%s — %s (id: %s)" % (
                    row["scope_id"], row["task_id"], row["name"], new_id))

    if not dry_run:
        _meta_set(conn, "last_push_at", now)
        conn.commit()

    conn.close()
    print("\n--- Push Summary ---")
    print("  Pushed: %d  Created: %d  Skipped: %d" % (
        stats["pushed"], stats["created"], stats["skipped"]))
    return 0


# ── STATUS ─────────────────────────────────────────────────

PUSH_PLAN_ACTIONS = (
    "create_remote", "patch_remote", "attach_candidate", "finalize_baseline",
    "skip", "conflict", "error",
)
ACTIVE_PUSH_CLAIMS = set()
PUSH_CLAIM_LEASE_SECONDS = 300


class ReadOnlyV1PushPlan(dict):
    """Loaded legacy artifact: inspectable, but never executable."""


def _push_plan_schema_version(plan):
    if not isinstance(plan, dict):
        return None
    version = plan.get("plan_schema_version", 1)
    return version if isinstance(version, int) and not isinstance(version, bool) else None


def _local_identity_schema_version(conn):
    profiles = []
    for table in ("projects", "tasks"):
        actual = {
            row[1] for row in conn.execute("PRAGMA table_info(%s)" % table).fetchall()
        }
        identity = LOCAL_IDENTITY_COLUMNS[table]
        profiles.append(2 if identity <= actual else 1 if not (identity & actual) else 0)
    return profiles[0] if profiles[0] == profiles[1] else 0


def _identity_plan_context(conn, manifest_path=None):
    if _local_identity_schema_version(conn) != 2:
        return None
    manifest = resolve_workspace_identity(
        conn,
        manifest_path=WORKSPACE_MANIFEST_PATH if manifest_path is None else manifest_path,
    )
    return {
        "identity_version": 2,
        "workspace_id": manifest["workspace_id"],
        "writer_epoch": manifest["writer_epoch"],
        "writer_authority_hash": manifest["writer_authority_hash_cache"],
    }


def _selection_result(exit_code, code=None, message=None, **details):
    return {
        "exit_code": exit_code,
        "finding": _finding(code, message, **details) if code else None,
        "mode": None, "context": None, "project": None,
    }


def resolve_identity_selection(conn, *, scope_id=None, sync_uid=None,
                               workspace_id=None, manifest_path=None):
    """Single Identity projection shared by push, pull, sync, and status.

    Scope is display/routing only.  In Identity v2 a Scope resolves only inside
    the manifest-selected workspace and only when it is unique there; a
    ``sync_uid`` selects exactly one Project Identity.  No latest/name/row-order
    fallback exists, and this function never issues or rewrites an Identity.
    ``manifest_path`` defaults to ``WORKSPACE_MANIFEST_PATH``; callers that own
    a different DB path (``plc_query.py``) pass the manifest next to it.
    """
    normalized_scope = (
        _normalize_identity_text(scope_id) if scope_id is not None else None
    )
    if scope_id is not None and not normalized_scope:
        return _selection_result(
            3, "SCOPE_INVALID", "scope selector is empty after normalization")
    try:
        schema_version = _local_identity_schema_version(conn)
    except sqlite3.Error:
        return _selection_result(
            3, "LOCAL_SCHEMA_ERROR",
            "local Projects schema cannot resolve the selector", path=DB_PATH)
    if schema_version == 0:
        return _selection_result(
            3, "LOCAL_IDENTITY_SCHEMA_MIXED",
            "projects and tasks use different Identity schema versions")
    if schema_version == 1:
        if sync_uid is not None or workspace_id is not None:
            return _selection_result(
                3, "IDENTITY_SELECTOR_REQUIRES_V2",
                "workspace/sync_uid selectors require the Identity v2 schema")
        result = _selection_result(0)
        result["mode"] = "v1"
        if normalized_scope is None:
            return result
        try:
            rows = conn.execute(
                "SELECT id FROM projects WHERE scope_id=? ORDER BY id",
                (normalized_scope,),
            ).fetchall()
        except sqlite3.Error:
            return _selection_result(
                3, "LOCAL_SCHEMA_ERROR",
                "local Projects schema cannot resolve the scope selector",
                path=DB_PATH)
        if len(rows) != 1:
            return _selection_result(
                3, "SCOPE_NOT_UNIQUE",
                "scope selector must match exactly one local Project",
                match_count=len(rows))
        result["project"] = {"id": rows[0]["id"], "scope_id": normalized_scope}
        return result

    try:
        context = _identity_plan_context(conn, manifest_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return _selection_result(
            3, "WORKSPACE_IDENTITY_INVALID",
            "Identity v2 workspace manifest/cache cannot be resolved",
            reason=str(exc))
    if workspace_id is not None and workspace_id != context["workspace_id"]:
        return _selection_result(
            3, "WORKSPACE_SELECTOR_MISMATCH",
            "workspace selector does not match the manifest-selected workspace")
    result = _selection_result(0)
    result["mode"] = "v2"
    result["context"] = context
    columns = ("SELECT id, workspace_id, sync_uid, ownership_epoch, "
               "identity_version, scope_id FROM projects ")
    try:
        if sync_uid is not None:
            rows = [dict(row) for row in conn.execute(
                columns + "WHERE sync_uid=? ORDER BY id", (sync_uid,)
            ).fetchall()]
            if not rows:
                return _selection_result(
                    3, "IDENTITY_SELECTOR_NOT_FOUND",
                    "sync_uid selector matches no local Project")
            if len(rows) > 1:
                return _selection_result(
                    2, "IDENTITY_DUPLICATE",
                    "sync_uid selector matches multiple local Projects",
                    match_count=len(rows))
            row = rows[0]
            if row["workspace_id"] != context["workspace_id"]:
                return _selection_result(
                    3, "IDENTITY_WORKSPACE_MISMATCH",
                    "selected Project belongs to another workspace")
            if normalized_scope is not None and (
                    _normalize_identity_text(row["scope_id"]) != normalized_scope):
                return _selection_result(
                    2, "SELECTOR_SCOPE_MISMATCH",
                    "scope assertion does not match the selected Project Identity")
        elif normalized_scope is not None:
            rows = [dict(row) for row in conn.execute(
                columns + "WHERE workspace_id=? AND scope_id=? ORDER BY id",
                (context["workspace_id"], normalized_scope),
            ).fetchall()]
            other_workspace = conn.execute(
                "SELECT COUNT(*) FROM projects WHERE scope_id=? AND "
                "(workspace_id IS NULL OR workspace_id<>?)",
                (normalized_scope, context["workspace_id"]),
            ).fetchone()[0]
            if not rows:
                return _selection_result(
                    3, "SCOPE_NOT_UNIQUE",
                    "scope selector must match exactly one local Project",
                    match_count=0, other_workspace_or_legacy_matches=other_workspace)
            if len(rows) > 1:
                return _selection_result(
                    2, "SCOPE_AMBIGUOUS",
                    "scope matches multiple Project Identities; pass --sync-uid",
                    match_count=len(rows))
            row = rows[0]
        else:
            return result
    except sqlite3.Error:
        return _selection_result(
            3, "LOCAL_SCHEMA_ERROR",
            "local Projects schema cannot resolve the selector", path=DB_PATH)
    state, _values = _identity_record_state("project", row)
    if state != "valid":
        return _selection_result(
            3, "IDENTITY_INVALID", "selected Project Identity is incomplete")
    row["scope_id"] = _normalize_identity_text(row["scope_id"])
    result["project"] = row
    return result


def _short_identity(value):
    """Display-only abbreviation; canonical values stay inside Plans/schema."""
    text = str(value or "")
    return text[:12] + "…" if len(text) > 13 else text


def _operation_identity(entity, row, writer_epoch=None):
    return {
        "identity_version": int(_record_value(row, "identity_version")),
        "workspace_id": _normalize_identity_text(_record_value(row, "workspace_id")),
        "writer_epoch": int(writer_epoch) if writer_epoch is not None else None,
        "project_sync_uid": _normalize_identity_text(
            _record_value(row, "sync_uid" if entity == "project" else "project_sync_uid")
        ),
        "ownership_epoch": int(_record_value(
            row, "ownership_epoch" if entity == "project" else "project_ownership_epoch"
        )),
        "entity": entity,
        "task_id": (
            None if entity == "project"
            else _normalize_identity_text(_record_value(row, "task_id"))
        ),
    }


def _identity_operation_id(identity, action):
    canonical = {"identity": identity, "action": action}
    return "opv2_" + _hashed_projection_value(canonical)


def _identity_operation_stable_key(identity):
    if identity["entity"] == "project":
        return [identity["project_sync_uid"]]
    return [identity["project_sync_uid"], identity["task_id"]]


def _identity_snapshot_digest(operations):
    snapshot = [{
        "operation_id": operation.get("operation_id"),
        "identity": operation.get("identity"),
        "local_row_id": operation.get("local_row_id"),
        "expected_local_updated_at": operation.get("expected_local_updated_at"),
        "expected_local_fingerprint": operation.get("expected_local_fingerprint"),
    } for operation in operations]
    return _hashed_projection_value(snapshot)


def _v2_pending_key(operation):
    return "pending_push:v2:%s" % operation["operation_id"]


def _v2_pending_owner(plan, operation):
    identity = operation["identity"]
    return {
        "identity_version": 2,
        "workspace_id": identity["workspace_id"],
        "writer_epoch": identity["writer_epoch"],
        "project_sync_uid": identity["project_sync_uid"],
        "ownership_epoch": identity["ownership_epoch"],
        "entity": identity["entity"],
        "task_id": identity["task_id"],
        "action": operation["action"],
        "operation_id": operation["operation_id"],
        "plan_id": plan["plan_id"],
        "fingerprint": operation["expected_local_fingerprint"],
    }


def _v2_remote_committed_pending(conn, plan, operation, item=None):
    row = conn.execute(
        "SELECT value FROM _metadata WHERE key=?", (_v2_pending_key(operation),)
    ).fetchone()
    if not row:
        return None
    try:
        value = json.loads(row["value"])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    expected = _v2_pending_owner(plan, operation)
    if (any(value.get(key) != expected_value
            for key, expected_value in expected.items())
            or value.get("state") != "remote_committed"
            or not value.get("remote_page_id")):
        return None
    if item is not None:
        candidates = item.get("candidates") or []
        if (item.get("action") != "attach_candidate" or len(candidates) != 1
                or candidates[0].get("page_id") != value["remote_page_id"]
                or candidates[0].get("mapped_fingerprint")
                != operation["expected_local_fingerprint"]):
            return None
    return value


def _operation_display_key(operation):
    if operation.get("identity", {}).get("identity_version") == 2:
        scope_id = operation.get("display_scope_id") or "IDENTITY_V2"
        task_id = operation.get("identity", {}).get("task_id")
        return "/".join([scope_id] + ([task_id] if task_id else []))
    return "/".join(operation.get("stable_key") or [])


def _valid_v2_plan_shape(plan):
    if _push_plan_schema_version(plan) != 2:
        return False
    if set(plan) != {
        "plan_id", "plan_schema_version", "generated_at", "direction", "identity",
        "selector", "preflight", "source_snapshot", "operations", "summary",
        "reconciliation", "exit_code",
    } or plan.get("direction") != "push":
        return False
    if (not isinstance(plan.get("generated_at"), str)
            or not isinstance(plan.get("preflight"), dict)
            or not isinstance(plan.get("operations"), list)
            or not isinstance(plan.get("summary"), dict)
            or not isinstance(plan.get("reconciliation"), dict)
            or isinstance(plan.get("exit_code"), bool)
            or not isinstance(plan.get("exit_code"), int)):
        return False
    identity = plan.get("identity")
    selector = plan.get("selector")
    source = plan.get("source_snapshot")
    if not isinstance(identity, dict) or set(identity) != {
        "identity_version", "workspace_id", "writer_epoch", "writer_authority_hash"
    }:
        return False
    if (identity.get("identity_version") != 2
            or not WORKSPACE_ID_PATTERN.fullmatch(str(identity.get("workspace_id", "")))
            or isinstance(identity.get("writer_epoch"), bool)
            or not isinstance(identity.get("writer_epoch"), int)
            or identity["writer_epoch"] < 1
            or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", str(identity.get("writer_authority_hash", ""))
            )):
        return False
    if not isinstance(selector, dict) or set(selector) != {
        "kind", "workspace_id", "scope_id", "project_sync_uid", "ownership_epoch"
    }:
        return False
    if selector.get("kind") not in {"workspace", "project"}:
        return False
    if selector.get("workspace_id") != identity["workspace_id"]:
        return False
    if selector["kind"] == "workspace":
        if any(selector.get(key) is not None for key in (
                "scope_id", "project_sync_uid", "ownership_epoch")):
            return False
    else:
        if (_normalize_identity_text(selector.get("scope_id")) != selector.get("scope_id")
                or not selector.get("scope_id")
                or not PROJECT_UID_PATTERN.fullmatch(str(selector.get("project_sync_uid", "")))
                or isinstance(selector.get("ownership_epoch"), bool)
                or not isinstance(selector.get("ownership_epoch"), int)
                or selector["ownership_epoch"] < 1):
            return False
    if not isinstance(source, dict) or set(source) != {
        "workspace_id", "writer_epoch", "db_updated_at_max",
        "selected_identity_digest", "operation_count"
    }:
        return False
    if (source.get("workspace_id") != identity["workspace_id"]
            or source.get("writer_epoch") != identity["writer_epoch"]
            or source.get("operation_count") != len(plan.get("operations", []))):
        return False
    for operation in plan["operations"]:
        if not isinstance(operation, dict) or set(operation) != {
            "operation_id", "entity", "stable_key", "action", "display_scope_id",
            "identity", "local_row_id", "remote_page_ids", "remote_candidates",
            "expected_reconciliation_reason", "link_state",
            "expected_local_updated_at", "expected_local_fingerprint",
            "mutable_properties",
        }:
            return False
        op_identity = operation.get("identity")
        if not isinstance(op_identity, dict) or set(op_identity) != {
            "identity_version", "workspace_id", "writer_epoch", "project_sync_uid",
            "ownership_epoch", "entity", "task_id"
        }:
            return False
        entity = op_identity.get("entity")
        action = operation.get("action")
        if (op_identity.get("identity_version") != 2
                or op_identity.get("workspace_id") != identity["workspace_id"]
                or op_identity.get("writer_epoch") != identity["writer_epoch"]
                or not PROJECT_UID_PATTERN.fullmatch(str(
                    op_identity.get("project_sync_uid", "")
                ))
                or isinstance(op_identity.get("ownership_epoch"), bool)
                or not isinstance(op_identity.get("ownership_epoch"), int)
                or op_identity["ownership_epoch"] < 1
                or entity not in {"project", "task"}
                or (entity == "project" and op_identity.get("task_id") is not None)
                or (entity == "task" and (
                    not op_identity.get("task_id")
                    or _normalize_identity_text(op_identity["task_id"])
                    != op_identity["task_id"]
                ))
                or action not in PUSH_PLAN_ACTIONS
                or isinstance(operation.get("local_row_id"), bool)
                or not isinstance(operation.get("local_row_id"), int)
                or operation["local_row_id"] < 1
                or _normalize_identity_text(operation.get("display_scope_id"))
                != operation.get("display_scope_id")
                or not operation.get("display_scope_id")
                or not isinstance(operation.get("stable_key"), list)
                or not isinstance(operation.get("remote_page_ids"), list)
                or not all(isinstance(page_id, str)
                           for page_id in operation["remote_page_ids"])
                or not isinstance(operation.get("remote_candidates"), list)
                or not all(isinstance(candidate, dict)
                           for candidate in operation["remote_candidates"])
                or not isinstance(operation.get("mutable_properties"), dict)
                or not isinstance(operation.get("expected_local_updated_at"), str)
                or not re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(operation.get("expected_local_fingerprint", "")),
                )):
            return False
        if operation.get("entity") != entity:
            return False
        if operation.get("stable_key") != _identity_operation_stable_key(op_identity):
            return False
        if operation.get("operation_id") != _identity_operation_id(
                op_identity, action):
            return False
        if selector["kind"] == "project" and (
                op_identity["project_sync_uid"] != selector["project_sync_uid"]
                or op_identity["ownership_epoch"] != selector["ownership_epoch"]
                or operation.get("display_scope_id") != selector["scope_id"]):
            return False
    if source.get("selected_identity_digest") != _identity_snapshot_digest(
            plan.get("operations", [])):
        return False
    expected_summary = {action: 0 for action in PUSH_PLAN_ACTIONS}
    for operation in plan.get("operations", []):
        expected_summary[operation["action"]] += 1
    if plan.get("summary") != expected_summary:
        return False
    reconciliation = plan["reconciliation"]
    blocking = reconciliation.get("blocking")
    authorization_required = reconciliation.get("authorization_required")
    if (not isinstance(blocking, dict)
            or not isinstance(authorization_required, dict)
            or isinstance(blocking.get("exit_code", 0), bool)
            or not isinstance(blocking.get("exit_code", 0), int)
            or not isinstance(authorization_required.get("operation_ids", []), list)
            or not all(isinstance(operation_id, str) for operation_id in
                       authorization_required.get("operation_ids", []))):
        return False
    blocking_exit = blocking.get("exit_code", 0)
    attach_ids = authorization_required.get("operation_ids", [])
    expected_attach_ids = sorted(
        operation["operation_id"] for operation in plan.get("operations", [])
        if operation["action"] == "attach_candidate"
    )
    if sorted(attach_ids) != expected_attach_ids:
        return False
    return plan.get("exit_code") == (blocking_exit or (2 if attach_ids else 0))


def _push_plan_id(plan):
    if _push_plan_schema_version(plan) == 2:
        canonical = {key: plan.get(key) for key in (
            "plan_schema_version", "direction", "identity", "selector",
            "preflight", "source_snapshot", "operations", "reconciliation",
            "summary", "exit_code",
        )}
        payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False,
                            separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
    canonical = {key: plan.get(key) for key in (
        "direction", "preflight", "source_snapshot", "operations", "reconciliation"
    )}
    if "selector" in plan:
        canonical["selector"] = plan.get("selector")
    payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_push_plan(plan, expected_plan_id=None):
    if not isinstance(plan, dict):
        return False
    expected = expected_plan_id or plan.get("plan_id")
    if plan.get("plan_id") != expected or expected != _push_plan_id(plan):
        return False
    return _valid_v2_plan_shape(plan) if _push_plan_schema_version(plan) == 2 else True


def _plan_scope_id(plan):
    if _push_plan_schema_version(plan) == 2:
        selector = plan.get("selector")
        if not isinstance(selector, dict):
            return False
        return selector.get("scope_id") if selector.get("kind") == "project" else None
    if "selector" not in plan:
        return None
    selector = plan.get("selector")
    if not isinstance(selector, dict) or set(selector) != {"scope_id"}:
        return False
    raw_scope = selector.get("scope_id")
    normalized = _normalize_identity_text(raw_scope)
    if not normalized or raw_scope != normalized:
        return False
    return normalized


def validate_plan_scope(plan, scope_id=None):
    """Bind a scoped Plan to the same explicit CLI selector."""
    plan_scope = _plan_scope_id(plan)
    if plan_scope is False:
        return False
    cli_scope = (
        _normalize_identity_text(scope_id) if scope_id is not None else None
    )
    if scope_id is not None and not cli_scope:
        return False
    if plan_scope is None:
        return cli_scope is None
    return cli_scope == plan_scope


def validate_plan_selector(plan, scope_id=None, sync_uid=None, workspace_id=None):
    """Bind a Plan to the exact CLI selector (Scope, Project UID, workspace).

    With no UID/workspace selector this is identical to ``validate_plan_scope``
    so existing global and Scope Plans keep their contract.
    """
    if sync_uid is None and workspace_id is None:
        return validate_plan_scope(plan, scope_id)
    if _push_plan_schema_version(plan) != 2:
        return False
    selector = plan.get("selector")
    if not isinstance(selector, dict):
        return False
    if workspace_id is not None and workspace_id != selector.get("workspace_id"):
        return False
    if sync_uid is None:
        return validate_plan_scope(plan, scope_id)
    if selector.get("kind") != "project" or sync_uid != selector.get(
            "project_sync_uid"):
        return False
    if scope_id is not None:
        return validate_plan_scope(plan, scope_id)
    return True


def _operations_match_plan_scope(plan):
    plan_scope = _plan_scope_id(plan)
    if plan_scope in (None, False):
        return plan_scope is None
    if _push_plan_schema_version(plan) == 2:
        selector = plan["selector"]
        return all(
            operation.get("display_scope_id") == plan_scope
            and operation.get("identity", {}).get("project_sync_uid")
            == selector["project_sync_uid"]
            and operation.get("identity", {}).get("ownership_epoch")
            == selector["ownership_epoch"]
            for operation in plan.get("operations", [])
        )
    for operation in plan.get("operations", []):
        entity = operation.get("entity")
        key = operation.get("stable_key")
        expected_size = 1 if entity == "project" else 2 if entity == "task" else 0
        if (not isinstance(key, list) or len(key) != expected_size
                or not key or _normalize_identity_text(key[0]) != plan_scope
                or key[0] != plan_scope):
            return False
    return True


def _local_rows_match_plan_scope(plan):
    """Verify scoped operation row IDs before reconciliation or mutation."""
    plan_scope = _plan_scope_id(plan)
    if plan_scope is None:
        return True
    if plan_scope is False:
        return False
    conn, error = _open_read_conn()
    if error:
        return None
    try:
        for operation in plan.get("operations", []):
            table = (
                "projects" if operation.get("entity") == "project"
                else "tasks" if operation.get("entity") == "task" else None
            )
            if table is None:
                return False
            row = conn.execute(
                "SELECT scope_id FROM %s WHERE id=?" % table,
                (operation.get("local_row_id"),),
            ).fetchone()
            if (not row or _normalize_identity_text(row["scope_id"]) != plan_scope
                    or row["scope_id"] != plan_scope):
                return False
        return True
    finally:
        conn.close()


def _validate_v2_plan_local_fencing(plan):
    """Validate Identity, snapshot, and journal ownership before remote/write calls."""
    conn, error = _open_read_conn()
    if error:
        return 3
    try:
        if _local_identity_schema_version(conn) != 2:
            return 3
        try:
            context = _identity_plan_context(conn)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 3
        if context != plan.get("identity"):
            return 2
        selector = plan["selector"]
        if selector["workspace_id"] != context["workspace_id"]:
            return 2
        pending_by_identity = {}
        for pending_row in conn.execute(
                "SELECT key, value FROM _metadata WHERE key LIKE 'pending_push:v2:%'"
                ).fetchall():
            try:
                pending_value = json.loads(pending_row["value"])
                pending_identity = (
                    pending_value["workspace_id"], pending_value["writer_epoch"],
                    pending_value["project_sync_uid"],
                    pending_value["ownership_epoch"], pending_value["entity"],
                    pending_value.get("task_id"),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                return 2
            pending_by_identity.setdefault(pending_identity, []).append(
                (pending_row["key"], pending_value)
            )
        rows_for_digest = []
        current_updated_at = []
        selected_scopes = set()
        for operation in plan.get("operations", []):
            entity = operation["entity"]
            table = "projects" if entity == "project" else "tasks"
            row = conn.execute(
                "SELECT * FROM %s WHERE id=?" % table,
                (operation["local_row_id"],),
            ).fetchone()
            if not row:
                return 2
            row = dict(row)
            try:
                current_identity = _operation_identity(
                    entity, row, context["writer_epoch"]
                )
            except (TypeError, ValueError):
                return 3
            if current_identity != operation["identity"]:
                return 2
            if _normalize_identity_text(row.get("scope_id")) != operation.get(
                    "display_scope_id"):
                return 2
            if (row.get("updated_at") != operation.get("expected_local_updated_at")
                    or _mapped_fingerprint(entity, row)
                    != operation.get("expected_local_fingerprint")):
                return 2
            canonical_properties = (
                _project_to_notion_props(row) if entity == "project"
                else _task_to_notion_props(row)
            )
            if operation.get("mutable_properties") != canonical_properties:
                return 2
            selected_scopes.add(_normalize_identity_text(row.get("scope_id")))
            rows_for_digest.append(operation)
            current_updated_at.append(row.get("updated_at") or "")
            identity = operation["identity"]
            owner_key = (
                identity["workspace_id"], identity["writer_epoch"],
                identity["project_sync_uid"], identity["ownership_epoch"],
                identity["entity"], identity["task_id"],
            )
            expected_owner = _v2_pending_owner(plan, operation)
            for pending_key, value in pending_by_identity.get(owner_key, []):
                if (pending_key != _v2_pending_key(operation)
                        or any(value.get(key) != expected
                               for key, expected in expected_owner.items())):
                    return 2
                if value.get("state") in {"claimed", "uncertain"}:
                    return 4
                if (value.get("state") != "remote_committed"
                        or not value.get("remote_page_id")):
                    return 2
        if plan["source_snapshot"]["selected_identity_digest"] != (
                _identity_snapshot_digest(rows_for_digest)):
            return 2
        if plan["source_snapshot"]["operation_count"] != len(rows_for_digest):
            return 2
        if plan["source_snapshot"]["db_updated_at_max"] != max(
                current_updated_at or [""]):
            return 2
        # v1 journals are never auto-owned by v2. An overlapping unresolved
        # Scope must be migrated/repaired explicitly before this Plan executes.
        legacy_rows = conn.execute(
            "SELECT value FROM _metadata WHERE key LIKE 'pending_push:%' "
            "AND key NOT LIKE 'pending_push:v2:%'"
        ).fetchall()
        for legacy_row in legacy_rows:
            try:
                legacy = json.loads(legacy_row["value"])
                key = legacy.get("stable_key") or []
            except (TypeError, ValueError, json.JSONDecodeError):
                return 2
            if key and _normalize_identity_text(key[0]) in selected_scopes:
                return 2
        return 0
    except sqlite3.Error:
        return 3
    finally:
        conn.close()


def validate_plan_authorization(plan, authorization):
    """Validate attach approval without mutating the immutable Plan."""
    if not authorization or authorization.get("plan_id") != plan.get("plan_id"):
        return False
    allowed = set(authorization.get("operation_ids", []))
    attach_ids = {op["operation_id"] for op in plan["operations"]
                  if op["action"] == "attach_candidate"}
    return bool(authorization.get("approved_by")) and attach_ids <= allowed


def _blocked_push_plan(preflight_view, scope_id=None):
    plan = {
        "plan_id": "", "generated_at": _now_iso(), "direction": "push",
        "preflight": preflight_view, "source_snapshot": {}, "operations": [],
        "summary": {action: 0 for action in PUSH_PLAN_ACTIONS}, "exit_code": 3,
    }
    if scope_id is not None:
        plan["selector"] = {"scope_id": scope_id}
    plan["plan_id"] = _push_plan_id(plan)
    return plan


def build_push_plan(skip_preflight=False, scope_id=None, sync_uid=None,
                    workspace_id=None):
    """Build the immutable selection/reconciliation artifact used by push."""
    normalized_scope = (
        _normalize_identity_text(scope_id) if scope_id is not None else None
    )
    target_ids = {"project": [], "task": []}
    link_states = {"project": {}, "task": {}}
    preflight_view = {"status": "pass", "findings": []}
    if scope_id is not None and not normalized_scope:
        preflight_view = {
            "status": "blocked",
            "findings": [_finding(
                "SCOPE_INVALID", "scope selector is empty after normalization"
            )],
        }
        return _blocked_push_plan(preflight_view)

    conn, error = _open_read_conn()
    if error:
        preflight_view = {
            "status": "blocked",
            "findings": [_finding(
                "LOCAL_DB_UNAVAILABLE", "local SQLite database is unavailable",
                path=DB_PATH,
            )],
        }
        return _blocked_push_plan(preflight_view, normalized_scope)
    # Shared Identity projection: the same resolver backs pull/status/sync.
    selection = resolve_identity_selection(
        conn, scope_id=normalized_scope, sync_uid=sync_uid,
        workspace_id=workspace_id,
    )
    if selection["exit_code"]:
        conn.close()
        preflight_view = {"status": "blocked",
                          "findings": [selection["finding"]]}
        plan = _blocked_push_plan(preflight_view, normalized_scope)
        if selection["exit_code"] != plan["exit_code"]:
            plan["exit_code"] = selection["exit_code"]
            plan["plan_id"] = _push_plan_id(plan)
        return plan
    identity_context = selection["context"]
    is_v2 = identity_context is not None
    selected_project_binding = selection["project"] if is_v2 else None
    if selected_project_binding is not None:
        # A sync_uid selection carries the Project's current display Scope as
        # an assertion so the Plan remains human-reviewable.
        normalized_scope = selected_project_binding["scope_id"]
    try:
        excluded_scopes = _load_excluded_scopes(conn)
        tasks_frozen = _task_sync_frozen(conn)
    except IdentityLifecycleError as exc:
        conn.close()
        return _blocked_push_plan({"status": "blocked", "findings": [_finding(
            exc.code, "sync exclusion or task freeze record is malformed")]},
            normalized_scope)
    if (normalized_scope is not None and normalized_scope in excluded_scopes) or (
            selected_project_binding is not None
            and _normalize_identity_text(selected_project_binding.get("sync_uid"))
            in excluded_scopes.uids):
        # T016: an explicit selector for a confidential Scope is refused
        # loudly instead of silently producing an empty Plan.
        conn.close()
        return _blocked_push_plan({"status": "blocked", "findings": [_finding(
            "SCOPE_EXCLUDED", "this Scope is registered as never synced to Notion")]},
            normalized_scope)
    if not skip_preflight:
        preflight = run_preflight(
            conn=conn, allow_reconcilable_links=True, scope_id=normalized_scope
        )
        preflight_view = {
            "status": preflight["status"],
            "findings": preflight["findings"],
            "schema_fingerprints": {
                entity: schema.get("fingerprint")
                for entity, schema in preflight.get("schemas", {}).items()
                if schema.get("fingerprint")
            },
        }
        if preflight["status"] != "pass":
            conn.close()
            return _blocked_push_plan(preflight_view, normalized_scope)
        for table, entity in (("projects", "project"), ("tasks", "task")):
            for link in preflight["links"][table]:
                link_states[entity][link["local_row_id"]] = link["state"]
                if link["state"] in {"not_found", "wrong_parent", "trashed"}:
                    target_ids[entity].append(link["local_row_id"])
    pending_rows = conn.execute(
        "SELECT key, value FROM _metadata WHERE key LIKE 'pending_push:%'"
    ).fetchall()
    pending = {}
    legacy_pending_scopes = set()
    for pending_row in pending_rows:
        try:
            value = json.loads(pending_row["value"])
            if is_v2 and value.get("identity_version") == 2:
                pending[(
                    value.get("entity"), value.get("project_sync_uid"),
                    value.get("task_id"), value.get("action"),
                )] = value
                continue
            stable_key = tuple(value["stable_key"])
            if is_v2 and stable_key:
                legacy_pending_scopes.add(_normalize_identity_text(stable_key[0]))
                continue
            if (normalized_scope is not None
                    and (not stable_key
                         or _normalize_identity_text(stable_key[0])
                         != normalized_scope)):
                continue
            pending[(value["entity"], stable_key)] = value
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    selected = {}
    for entity, table in (("project", "projects"), ("task", "tasks")):
        if entity == "task" and tasks_frozen:
            # T019: frozen tasks are never selected nor checked.
            selected["task"] = []
            continue
        if is_v2 and normalized_scope is None:
            selected_rows = conn.execute("""
                SELECT * FROM %s WHERE workspace_id=? AND (
                    notion_page_id IS NULL OR last_sync_at IS NULL
                    OR updated_at > last_sync_at
                ) ORDER BY id
            """ % table, (identity_context["workspace_id"],)).fetchall()
        elif normalized_scope is None:
            selected_rows = conn.execute("""
                SELECT * FROM %s
                WHERE notion_page_id IS NULL OR last_sync_at IS NULL
                   OR updated_at > last_sync_at ORDER BY id
            """ % table).fetchall()
        elif is_v2:
            # Identity projection: the selected Project UID, never the Scope.
            uid_column = "sync_uid" if entity == "project" else "project_sync_uid"
            selected_rows = conn.execute("""
                SELECT * FROM %s WHERE workspace_id=? AND %s=? AND (
                    notion_page_id IS NULL OR last_sync_at IS NULL
                    OR updated_at > last_sync_at
                ) ORDER BY id
            """ % (table, uid_column), (
                identity_context["workspace_id"],
                selected_project_binding["sync_uid"],
            )).fetchall()
            if entity == "task" and any(
                    _normalize_identity_text(row["scope_id"]) != normalized_scope
                    for row in selected_rows):
                conn.close()
                preflight_view = {
                    "status": "blocked",
                    "findings": [_finding(
                        "TASK_SCOPE_IDENTITY_MISMATCH",
                        "a Task of the selected Project Identity has another Scope",
                    )],
                }
                return _blocked_push_plan(preflight_view, normalized_scope)
        else:
            selected_rows = conn.execute("""
                SELECT * FROM %s WHERE scope_id=? AND (
                    notion_page_id IS NULL OR last_sync_at IS NULL
                    OR updated_at > last_sync_at
                ) ORDER BY id
            """ % table, (normalized_scope,)).fetchall()
        selected[entity] = [dict(row) for row in selected_rows]
        selected_ids = {row["id"] for row in selected[entity]}
        extra_ids = [row_id for row_id in target_ids[entity] if row_id not in selected_ids]
        if extra_ids:
            placeholders = ",".join("?" for _ in extra_ids)
            query = "SELECT * FROM %s WHERE id IN (%s)" % (table, placeholders)
            params = list(extra_ids)
            if is_v2:
                query += " AND workspace_id=?"
                params.append(identity_context["workspace_id"])
                if selected_project_binding is not None:
                    query += " AND %s=?" % (
                        "sync_uid" if entity == "project" else "project_sync_uid")
                    params.append(selected_project_binding["sync_uid"])
            query += " ORDER BY id"
            selected[entity].extend(
                dict(row) for row in conn.execute(query, params).fetchall()
            )
    for entity in selected:
        selected[entity] = [row for row in selected[entity]
                            if not excluded_scopes.row(entity, row)]
    dependency_scopes = sorted({
        (_normalize_identity_text(row.get("project_sync_uid")) if is_v2
         else _normalize_identity_text(row.get("scope_id")))
        for row in selected["task"]
        if (_normalize_identity_text(row.get("project_sync_uid")) if is_v2
            else _normalize_identity_text(row.get("scope_id")))
    })
    dependency_projects = []
    if dependency_scopes:
        placeholders = ",".join("?" for _ in dependency_scopes)
        dependency_column = "sync_uid" if is_v2 else "scope_id"
        dependency_projects = [dict(row) for row in conn.execute(
            "SELECT * FROM projects WHERE %s IN (%s) ORDER BY id" % (
                dependency_column, placeholders
            ), dependency_scopes,
        ).fetchall() if not excluded_scopes.row("project", dict(row))]
    if is_v2 and legacy_pending_scopes & {
            _normalize_identity_text(row.get("scope_id"))
            for rows in selected.values() for row in rows}:
        conn.close()
        preflight_view = {
            "status": "blocked",
            "findings": [_finding(
                "LEGACY_PENDING_JOURNAL_REQUIRES_MIGRATION",
                "v1 pending journal overlaps an Identity v2 selection",
            )],
        }
        plan = _blocked_push_plan(preflight_view, normalized_scope)
        plan["exit_code"] = 2
        plan["plan_id"] = _push_plan_id(plan)
        return plan
    conn.close()
    reachable_keys = {
        "project": sorted({
            list(_stable_key("project", row))[0]
            for row in selected["project"]
            if _stable_key("project", row)[0]
        } | {
            _normalize_identity_text(row.get("scope_id"))
            for row in selected["task"]
            if _normalize_identity_text(row.get("scope_id"))
        }),
        "task": [list(_stable_key("task", row)) for row in selected["task"]],
    }
    reachable_keys["project"] = [[key] for key in reachable_keys["project"]]
    reconciliation = run_reconciliation(
        only_if_missing=True, target_row_ids=target_ids, link_states=link_states,
        reachable_stable_keys=reachable_keys,
    )
    items = {(item["entity"], item["local_row_id"]): item
             for item in reconciliation["items"] if item["local_row_id"] is not None}
    plan_rows = {entity: list(rows) for entity, rows in selected.items()}
    selected_project_ids = {row["id"] for row in selected["project"]}
    plan_rows["project"].extend(
        row for row in dependency_projects
        if row["id"] not in selected_project_ids
        and items.get(("project", row["id"]), {}).get("action")
        == "attach_candidate"
    )
    operations = []
    for entity in ("project", "task"):
        for row in plan_rows[entity]:
            item = items.get((entity, row["id"]))
            action = "patch_remote" if row.get("notion_page_id") else "create_remote"
            remote_ids = []
            if is_v2:
                row_identity = _operation_identity(
                    entity, row, identity_context["writer_epoch"]
                )
                pending_op = pending.get((
                    entity, row_identity["project_sync_uid"],
                    row_identity["task_id"], action,
                ))
            else:
                row_identity = None
                pending_op = pending.get((entity, tuple(_stable_key(entity, row))))
            if item:
                action = item["action"]
                if is_v2 and action not in PUSH_PLAN_ACTIONS:
                    # T015: a reconciliation "collision" is not an executable
                    # action; keep it as a blocked conflict so the Plan stays
                    # well-formed and reports the collision (exit 2).
                    action = "conflict"
                remote_ids = sorted(c["page_id"] for c in item.get("candidates", []))
                if (not is_v2 and action == "attach_candidate"
                        and len(item.get("candidates", [])) == 1):
                    candidate = item["candidates"][0]
                    if (pending_op
                            and pending_op.get("fingerprint") == item.get("local_fingerprint")
                            and candidate.get("mapped_fingerprint") == item.get("local_fingerprint")):
                        action = "finalize_baseline"
            if (not is_v2 and action == "create_remote" and pending_op
                    and pending_op.get("remote_page_id")
                    and pending_op.get("fingerprint") == _mapped_fingerprint(entity, row)):
                action = "finalize_baseline"
                remote_ids = [pending_op["remote_page_id"]]
            key = (_identity_operation_stable_key(row_identity) if is_v2
                   else list(_stable_key(entity, row)))
            operation = {
                "operation_id": (_identity_operation_id(row_identity, action) if is_v2
                                 else "%s:%s" % (entity, "/".join(key))),
                "entity": entity, "stable_key": key, "action": action,
                "display_scope_id": _normalize_identity_text(row.get("scope_id")),
                "local_row_id": row["id"], "remote_page_ids": remote_ids,
                "remote_candidates": item.get("candidates", []) if item else [],
                "expected_reconciliation_reason": (
                    item.get("reason") if item else None
                ),
                "link_state": item.get("link_state") if item else "valid",
                "expected_local_updated_at": row.get("updated_at"),
                "expected_local_fingerprint": _mapped_fingerprint(entity, row),
                "mutable_properties": (_project_to_notion_props(row) if entity == "project"
                                       else _task_to_notion_props(row)),
            }
            if is_v2:
                operation["identity"] = row_identity
            operations.append(operation)
    operations.sort(key=lambda op: (0 if op["entity"] == "project" else 1,
                                    tuple(op["stable_key"]), op["action"],
                                    op["operation_id"]))
    summary = {action: 0 for action in PUSH_PLAN_ACTIONS}
    for operation in operations:
        summary[operation["action"]] = summary.get(operation["action"], 0) + 1
    projection_scope = {
        "project": selected["project"] + [
            row for row in dependency_projects
            if row["id"] not in {item["id"] for item in selected["project"]}
        ],
        "task": selected["task"],
    }
    projection = project_reconciliation_for_push(reconciliation, projection_scope)
    attach_ids = [op["operation_id"] for op in operations
                  if op["action"] == "attach_candidate"]
    projection["authorization_required"]["operation_ids"] = attach_ids
    local_max = max([row.get("updated_at") or "" for rows in plan_rows.values()
                     for row in rows] or [""])
    plan = {"plan_id": "", "generated_at": _now_iso(), "direction": "push",
            "preflight": preflight_view,
            "source_snapshot": {"db_updated_at_max": local_max},
            "operations": operations, "summary": summary,
            "reconciliation": projection,
            "exit_code": (projection["blocking"]["exit_code"]
                          or (2 if attach_ids else 0))}
    if is_v2:
        plan["plan_schema_version"] = 2
        plan["identity"] = identity_context
        plan["selector"] = {
            "kind": "project" if normalized_scope is not None else "workspace",
            "workspace_id": identity_context["workspace_id"],
            "scope_id": normalized_scope,
            "project_sync_uid": (
                selected_project_binding["sync_uid"]
                if selected_project_binding is not None else None
            ),
            "ownership_epoch": (
                selected_project_binding["ownership_epoch"]
                if selected_project_binding is not None else None
            ),
        }
        plan["source_snapshot"] = {
            "workspace_id": identity_context["workspace_id"],
            "writer_epoch": identity_context["writer_epoch"],
            "db_updated_at_max": local_max,
            "selected_identity_digest": _identity_snapshot_digest(operations),
            "operation_count": len(operations),
        }
    elif normalized_scope is not None:
        plan["selector"] = {"scope_id": normalized_scope}
    plan["plan_id"] = _push_plan_id(plan)
    return plan


def _push_failure_hook(point, operation, response=None):
    """No-op boundary replaced only by isolated failure-injection tests."""


def _pid_is_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True


def _process_identity(pid):
    """Return an OS start-time token so PID reuse cannot steal a live claim."""
    if not _pid_is_alive(pid):
        return None
    try:
        return subprocess.check_output(
            ["/bin/ps", "-o", "lstart=", "-p", str(int(pid))],
            text=True, stderr=subprocess.DEVNULL, timeout=2,
        ).strip() or None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _claim_is_fresh(claimed_at, now):
    try:
        claimed = datetime.fromisoformat(str(claimed_at).replace("Z", "+00:00"))
        current = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
        age = (current - claimed).total_seconds()
        return 0 <= age <= PUSH_CLAIM_LEASE_SECONDS
    except (TypeError, ValueError):
        return False


def _post_verify_operation(conn, table, operation, response, baseline_at):
    """Read back Phase B state without causing any additional mutation."""
    row = conn.execute(
        "SELECT * FROM %s WHERE id=?" % table, (operation["local_row_id"],)
    ).fetchone()
    findings = []
    expected_page_id = (response or {}).get("id")
    if not row:
        findings.append("LOCAL_ROW_MISSING")
    else:
        if expected_page_id and row["notion_page_id"] != expected_page_id:
            findings.append("PAGE_ID_MISMATCH")
        if _mapped_fingerprint(operation["entity"], dict(row)) != operation[
            "expected_local_fingerprint"
        ]:
            findings.append("MAPPED_FINGERPRINT_MISMATCH")
        if row["last_sync_at"] != baseline_at:
            findings.append("LAST_SYNC_BASELINE_MISMATCH")
        expected_edited = (response or {}).get("last_edited_time", baseline_at)
        if row["notion_last_edited"] != expected_edited:
            findings.append("NOTION_BASELINE_MISMATCH")
        expected_identity = operation.get("identity")
        if expected_identity:
            # POST-VERIFY is Identity-scoped: the written row must still be the
            # exact Project/Task Identity the Plan fenced.
            try:
                actual_identity = _operation_identity(
                    operation["entity"], dict(row),
                    expected_identity.get("writer_epoch"),
                )
            except (TypeError, ValueError):
                actual_identity = None
            if actual_identity != expected_identity:
                findings.append("IDENTITY_MISMATCH")
    return {
        "operation_id": operation["operation_id"],
        "status": "pass" if not findings else "failed",
        "findings": findings,
    }


def _plan_uses_identity_v2(plan):
    if _push_plan_schema_version(plan) == 2:
        return True
    for operation in plan.get("operations", []):
        properties = operation.get("mutable_properties") or {}
        if _extract_number(properties.get("Identity Version") or {}) == 2:
            return True
    return False


def _revalidate_identity_plan_before_write(plan):
    """Revalidate v2 schema and every mutation against a fresh remote snapshot."""
    conn, error = _open_read_conn()
    if error:
        return 3
    try:
        scope_id = _plan_scope_id(plan)
        preflight = run_preflight(
            conn=conn, allow_reconcilable_links=True, scope_id=scope_id
        )
        if preflight.get("status") != "pass":
            return 3
        expected_schemas = plan.get("preflight", {}).get(
            "schema_fingerprints", {}
        )
        for entity, expected in expected_schemas.items():
            current = preflight.get("schemas", {}).get(entity, {}).get("fingerprint")
            if expected and current != expected:
                return 3

        selected = {"project": [], "task": []}
        target_ids = {"project": [], "task": []}
        link_states = {"project": {}, "task": {}}
        for operation in plan.get("operations", []):
            if operation.get("action") == "skip":
                continue
            entity = operation.get("entity")
            table = "projects" if entity == "project" else "tasks"
            row = conn.execute(
                "SELECT * FROM %s WHERE id=?" % table,
                (operation.get("local_row_id"),),
            ).fetchone()
            if not row:
                return 4
            row = dict(row)
            if (row.get("updated_at") != operation.get("expected_local_updated_at")
                    or _mapped_fingerprint(entity, row)
                    != operation.get("expected_local_fingerprint")):
                return 4
            selected[entity].append(row)
            target_ids[entity].append(row["id"])
            link_states[entity][row["id"]] = operation.get("link_state", "valid")

        reconciliation = run_reconciliation(
            conn=conn, target_row_ids=target_ids, link_states=link_states
        )
        projection = project_reconciliation_for_push(reconciliation, selected)
        if projection["blocking"]["exit_code"]:
            return projection["blocking"]["exit_code"]
        fresh_items = {
            (item.get("entity"), item.get("local_row_id")): item
            for item in reconciliation.get("items", [])
            if item.get("local_row_id") is not None
        }
        for operation in plan.get("operations", []):
            action = operation.get("action")
            if action in {"skip", "patch_remote"}:
                if action == "patch_remote" and fresh_items.get((
                        operation["entity"], operation["local_row_id"])):
                    return 2
                continue
            item = fresh_items.get((operation["entity"], operation["local_row_id"]))
            if not item:
                return 2
            if action == "create_remote":
                if item.get("action") == "create_remote":
                    continue
                if (_push_plan_schema_version(plan) == 2
                        and _v2_remote_committed_pending(
                            conn, plan, operation, item=item
                        )):
                    continue
                else:
                    return 2
            if action not in {"attach_candidate", "finalize_baseline"}:
                return 2
            if item.get("action") != "attach_candidate":
                return 2
            fresh_page_ids = sorted(
                candidate.get("page_id") for candidate in item.get("candidates", [])
                if candidate.get("page_id")
            )
            if fresh_page_ids != sorted(operation.get("remote_page_ids") or []):
                return 2
            expected_reason = operation.get("expected_reconciliation_reason")
            if expected_reason and item.get("reason") != expected_reason:
                return 2
        return 0
    except sqlite3.Error:
        return 3
    finally:
        conn.close()


def execute_push_plan(plan, authorization=None, scope_id=None, sync_uid=None,
                      workspace_id=None):
    if not validate_push_plan(plan):
        return 2
    if isinstance(plan, ReadOnlyV1PushPlan):
        return 2
    if (not validate_plan_selector(plan, scope_id, sync_uid, workspace_id)
            or not _operations_match_plan_scope(plan)):
        return 2
    identity_v2_plan = _plan_uses_identity_v2(plan)
    if _push_plan_schema_version(plan) == 2:
        local_fencing = _validate_v2_plan_local_fencing(plan)
        if local_fencing:
            return local_fencing
    else:
        local_scope_match = _local_rows_match_plan_scope(plan)
        if local_scope_match is None:
            return 3
        if not local_scope_match:
            return 2
    base_exit = plan.get("reconciliation", {}).get(
        "blocking", {}
    ).get("exit_code", plan["exit_code"])
    if base_exit:
        return base_exit
    excluded_exit = _plan_touches_excluded(plan)
    if excluded_exit:
        return excluded_exit
    if plan.get("reconciliation", {}).get(
            "authorization_required", {}).get("operation_ids"):
        if not validate_plan_authorization(plan, authorization):
            return 2
    elif plan["exit_code"]:
        return plan["exit_code"]
    if identity_v2_plan:
        execution_revalidation = _revalidate_identity_plan_before_write(plan)
        if execution_revalidation:
            return execution_revalidation
    creates = [op for op in plan["operations"] if op["action"] == "create_remote"]
    if creates and not identity_v2_plan:
        print("=== Create Absence Revalidation ===")
        targets = {"project": [], "task": []}
        states = {"project": {}, "task": {}}
        for operation in creates:
            entity, row_id = operation["entity"], operation["local_row_id"]
            targets[entity].append(row_id)
            states[entity][row_id] = "missing"
        selected_snapshot = {"project": [], "task": []}
        for operation in plan["operations"]:
            entity = operation["entity"]
            row = {"id": operation["local_row_id"]}
            if entity == "project":
                row["scope_id"] = operation["stable_key"][0]
            else:
                row["scope_id"], row["task_id"] = operation["stable_key"]
            selected_snapshot[entity].append(row)
        reachable_keys = {
            "project": [[key] for key in sorted({
                row["scope_id"] for row in selected_snapshot["project"]
            } | {
                row["scope_id"] for row in selected_snapshot["task"]
            })],
            "task": [operation["stable_key"] for operation in plan["operations"]
                     if operation["entity"] == "task"],
        }
        absence = run_reconciliation(
            target_row_ids=targets, link_states=states,
            reachable_stable_keys=reachable_keys,
        )
        _print_reconciliation_report(absence)
        fresh_projection = project_reconciliation_for_push(
            absence, selected_snapshot,
            known_reachable_page_ids=plan.get("reconciliation", {}).get(
                "reachability", {}
            ).get("reachable_page_ids", []),
        )
        if fresh_projection["blocking"]["exit_code"]:
            return fresh_projection["blocking"]["exit_code"]
        actions = {(item["entity"], item["local_row_id"]): item["action"]
                   for item in absence["items"] if item["local_row_id"] is not None}
        if any(actions.get((op["entity"], op["local_row_id"])) != "create_remote"
               for op in creates):
            return 2
    conn, error = _open_write_conn()
    if error:
        return 3
    now = _now_iso()
    try:
        for operation in plan["operations"]:
            entity = operation["entity"]
            table = "projects" if entity == "project" else "tasks"
            row = conn.execute("SELECT * FROM %s WHERE id=?" % table,
                               (operation["local_row_id"],)).fetchone()
            if (not row or row["updated_at"] != operation["expected_local_updated_at"]
                    or _mapped_fingerprint(entity, dict(row))
                    != operation["expected_local_fingerprint"]):
                conn.rollback()
                return 4
            action, response = operation["action"], None
            if action == "create_remote":
                pending_key = (_v2_pending_key(operation) if identity_v2_plan
                               else "pending_push:%s" % operation["operation_id"])
                recovery = (_v2_remote_committed_pending(conn, plan, operation)
                            if identity_v2_plan else None)
                if recovery:
                    response = {
                        "id": recovery["remote_page_id"],
                        "last_edited_time": recovery.get("remote_last_edited", now),
                    }
                    conn.execute("UPDATE %s SET notion_page_id=? WHERE id=?" % table,
                                 (response["id"], row["id"]))
                    print("  [RECOVER] %s" % _operation_display_key(operation))
                else:
                    existing_claim = conn.execute(
                        "SELECT value FROM _metadata WHERE key=?", (pending_key,)
                    ).fetchone()
                    if existing_claim:
                        try:
                            claim_value = json.loads(existing_claim["value"])
                        except (TypeError, ValueError, json.JSONDecodeError):
                            claim_value = {}
                        claim_pid = claim_value.get("claimed_by_pid")
                        try:
                            claim_pid_number = int(claim_pid)
                        except (TypeError, ValueError):
                            claim_pid_number = None
                        stored_identity = claim_value.get("process_identity")
                        current_identity = (
                            _process_identity(claim_pid_number)
                            if claim_pid_number is not None
                            and claim_pid_number != os.getpid() else None
                        )
                        same_live_process = bool(
                            stored_identity and current_identity == stored_identity
                        )
                        fresh_live_pid = bool(
                            (not stored_identity or current_identity is None)
                            and claim_pid_number is not None
                            and claim_pid_number != os.getpid()
                            and _pid_is_alive(claim_pid_number)
                            and _claim_is_fresh(claim_value.get("claimed_at"), now)
                        )
                        if (pending_key in ACTIVE_PUSH_CLAIMS
                                or same_live_process or fresh_live_pid):
                            conn.rollback()
                            return 4
                        conn.execute(
                            "DELETE FROM _metadata WHERE key=?", (pending_key,)
                        )
                    pending_value = (
                        _v2_pending_owner(plan, operation) if identity_v2_plan else {
                            "entity": entity,
                            "stable_key": operation["stable_key"],
                            "fingerprint": operation["expected_local_fingerprint"],
                            "plan_id": plan["plan_id"],
                        }
                    )
                    pending_value.update({
                        "claimed_by_pid": os.getpid(),
                        "claimed_at": now,
                        "process_identity": _process_identity(os.getpid()),
                        "state": "claimed",
                    })
                    _meta_set(conn, pending_key, json.dumps(
                        pending_value, sort_keys=True, ensure_ascii=False,
                        separators=(",", ":")
                    ))
                    conn.commit()
                    ACTIVE_PUSH_CLAIMS.add(pending_key)
                    try:
                        try:
                            response = _api_call("POST", "/v1/pages", {
                                "parent": {"database_id": (
                                    PROJECTS_DB_ID if entity == "project" else TASKS_DB_ID
                                )},
                                "properties": operation["mutable_properties"],
                            })
                        except BaseException:
                            if identity_v2_plan:
                                pending_value["state"] = "uncertain"
                                _meta_set(conn, pending_key, json.dumps(
                                    pending_value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")
                                ))
                                conn.commit()
                            raise
                    finally:
                        ACTIVE_PUSH_CLAIMS.discard(pending_key)
                    if identity_v2_plan:
                        pending_value["state"] = "remote_committed"
                    pending_value["remote_page_id"] = response["id"]
                    pending_value["remote_last_edited"] = response.get(
                        "last_edited_time", now
                    )
                    _meta_set(conn, pending_key, json.dumps(
                        pending_value, sort_keys=True, ensure_ascii=False,
                        separators=(",", ":")
                    ))
                    conn.commit()
                    _push_failure_hook("after_remote_mutation", operation, response)
                    conn.execute("UPDATE %s SET notion_page_id=? WHERE id=?" % table,
                                 (response["id"], row["id"]))
                    print("  [CREATE] %s (id: %s)" % (
                        _operation_display_key(operation), response["id"]
                    ))
            elif action == "patch_remote":
                if not row["notion_page_id"]:
                    # A link cleared after planning (e.g. by exclude): never
                    # send the row's content anywhere.
                    conn.rollback()
                    print("ERROR: patch target link is missing; build a new Plan")
                    return 4
                response = _api_call("PATCH", "/v1/pages/%s" % row["notion_page_id"],
                                     {"properties": operation["mutable_properties"]})
                _push_failure_hook("after_remote_mutation", operation, response)
            elif action == "finalize_baseline":
                page_id = operation["remote_page_ids"][0]
                conn.execute("UPDATE %s SET notion_page_id=? WHERE id=?" % table,
                             (page_id, row["id"]))
                response = {"id": page_id, "last_edited_time": now}
            elif action == "attach_candidate":
                page_id = operation["remote_page_ids"][0]
                if identity_v2_plan and row["notion_page_id"] == page_id:
                    # T014: re-linking the same page writes nothing to Notion.
                    conn.rollback()
                    print("ERROR: REMOTE_IDENTITY_BACKFILL_REQUIRED "
                          "(run backfill-remote-identity first)")
                    return 2
                conn.execute("UPDATE %s SET notion_page_id=? WHERE id=?" % table,
                             (page_id, row["id"]))
                conn.commit()
                print("  [ATTACH] %s (id: %s)" % (
                    _operation_display_key(operation), page_id
                ))
                continue
            elif action == "skip":
                continue
            else:
                conn.rollback()
                return 2
            _push_failure_hook("before_phase_a_commit", operation, response)
            if action in {"create_remote", "finalize_baseline"}:
                pending_key = (_v2_pending_key(operation) if identity_v2_plan
                               else "pending_push:%s" % operation["operation_id"])
                conn.execute("DELETE FROM _metadata WHERE key=?", (pending_key,))
            conn.commit()
            _push_failure_hook("after_phase_a_commit", operation, response)
            current = conn.execute("SELECT * FROM %s WHERE id=?" % table,
                                   (row["id"],)).fetchone()
            expected_page_id = (response or {}).get("id")
            if (not current
                    or (expected_page_id
                        and current["notion_page_id"] != expected_page_id)
                    or _mapped_fingerprint(entity, dict(current))
                    != operation["expected_local_fingerprint"]):
                conn.rollback()
                return 4
            observed_updated_at = current["updated_at"]
            operation_baseline = _operation_sync_baseline(
                _now_iso(), observed_updated_at
            )
            _push_failure_hook("before_phase_b_commit", operation, response)
            updated = conn.execute(
                "UPDATE %s SET last_sync_at=?, notion_last_edited=? "
                "WHERE id=? AND updated_at=?" % table,
                (operation_baseline,
                 (response or {}).get("last_edited_time", operation_baseline),
                 row["id"], observed_updated_at),
            )
            if updated.rowcount != 1:
                conn.rollback()
                return 4
            phase_b_current = conn.execute(
                "SELECT * FROM %s WHERE id=?" % table, (row["id"],)
            ).fetchone()
            if (not phase_b_current
                    or (expected_page_id
                        and phase_b_current["notion_page_id"] != expected_page_id)
                    or _mapped_fingerprint(entity, dict(phase_b_current))
                    != operation["expected_local_fingerprint"]):
                conn.rollback()
                return 4
            conn.commit()
            _push_failure_hook("after_phase_b_commit", operation, response)
            verification = _post_verify_operation(
                conn, table, operation, response, operation_baseline
            )
            print("  [POST-VERIFY %s] %s" % (
                verification["status"].upper(), operation["operation_id"]
            ))
            for finding in verification["findings"]:
                print("    %s" % finding)
            if verification["status"] != "pass":
                return 5
        _meta_set(conn, "last_push_at", now)
        conn.commit()
        return 0
    except (urllib.error.HTTPError, urllib.error.URLError, OSError,
            RuntimeError, ValueError) as exc:
        conn.rollback()
        print("ERROR: push execution failed: %s" % exc)
        return 4
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _print_push_plan(plan, dry_run=False):
    print("=== Push Plan %s===" % ("(DRY RUN) " if dry_run else ""))
    print("  plan_id=%s" % plan["plan_id"])
    if "selector" in plan:
        print("  scope_id=%s" % plan["selector"]["scope_id"])
        if plan["selector"].get("project_sync_uid"):
            print("  project_sync_uid=%s workspace_id=%s" % (
                _short_identity(plan["selector"]["project_sync_uid"]),
                _short_identity(plan["selector"]["workspace_id"]),
            ))
    print("  " + "  ".join("%s=%d" % item for item in plan["summary"].items()))
    projection = plan.get("reconciliation", {})
    if projection:
        blocking = projection["blocking"]["summary"]
        authorization = projection["authorization_required"]["summary"]
        audit = projection["audit_only"]
        print("  Blocking: " + " ".join(
            "%s=%d" % item for item in blocking.items() if item[1]
        ))
        if blocking.get("attach"):
            print("  NEXT: linked Notion pages have no Identity yet; run "
                  "backfill-remote-identity before pushing them.")
        print("  Authorization: " + " ".join(
            "%s=%d" % item for item in authorization.items() if item[1]
        ))
        print("  Audit-only: " + " ".join(
            ["%s=%d" % item for item in audit["summary"].items() if item[1]]
            + ["digest=%s" % audit["projection_digest"]]
        ))
    for finding in plan["preflight"].get("findings", []):
        print("  [BLOCK] %s: %s" % (finding.get("code"), finding.get("message")))
    for operation in plan["operations"]:
        labels = {"attach_candidate": "ATTACH", "create_remote": "CREATE",
                  "patch_remote": "PATCH", "finalize_baseline": "FINALIZE"}
        label = labels.get(operation["action"], operation["action"].upper())
        if operation.get("link_state") in {"not_found", "wrong_parent", "trashed"}:
            print("  [RECONCILE] LINK_%s" % operation["link_state"].upper())
        print("  [%s] %s" % (label, _operation_display_key(operation)))
        candidates = operation.get("remote_candidates", [])
        if candidates:
            for candidate in candidates:
                parent = candidate.get("notion_parent") or {}
                parent_value = parent.get(parent.get("type")) if parent.get("type") else None
                print("    id=%s parent=%s last_edited=%s" % (
                    candidate.get("page_id"), parent_value,
                    candidate.get("last_edited_time")
                ))
        else:
            for page_id in operation.get("remote_page_ids", []):
                print("    id=%s" % page_id)


def write_push_plan(plan, path):
    if not validate_push_plan(plan):
        raise ValueError("cannot write invalid push plan")
    temporary = "%s.tmp.%d" % (path, os.getpid())
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(plan, handle, sort_keys=True, ensure_ascii=False,
                  separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_push_plan(path):
    with open(path, encoding="utf-8") as handle:
        plan = json.load(handle)
    if not validate_push_plan(plan):
        raise ValueError("push plan artifact failed integrity validation")
    if _push_plan_schema_version(plan) == 1:
        return ReadOnlyV1PushPlan(plan)
    return plan


# ── Sync-excluded Scopes (T016) ───────────────────────────
# Confidential Scopes a person has registered as "never in Notion".  Every
# path (push selection, reconciliation input, pull, remote backfill) drops
# their rows and any remote page carrying the same Scope ID.  Registration
# clears the local page links; Notion itself is never written here.

EXCLUDE_META_PREFIX = "sync_excluded_scope:"
LEGACY_SKIP_PREFIX = "legacy_skipped_page:"
TASK_FREEZE_KEY = "task_sync_frozen"


def _task_sync_frozen(conn):
    """T019: local tasks are a frozen copy of backlog.yaml; never synced."""
    row = conn.execute("SELECT value FROM _metadata WHERE key=?",
                       (TASK_FREEZE_KEY,)).fetchone()
    if row is None:
        return False
    try:
        record = json.loads(row[0])
        if not isinstance(record, dict) or not isinstance(record.get("approved_by"), str):
            raise ValueError
    except (ValueError, TypeError):
        raise IdentityLifecycleError("TASK_FREEZE_RECORD_INVALID", 3)
    return True


def _task_freeze_state(conn):
    """("active", None) / ("frozen", record) / ("malformed", raw_value) for the freeze record."""
    value = _meta_get(conn, TASK_FREEZE_KEY)
    if value is None:
        return "active", None
    try:
        record = json.loads(value)
        if not isinstance(record, dict) or not isinstance(record.get("approved_by"), str):
            raise ValueError
    except (ValueError, TypeError):
        return "malformed", value
    return "frozen", record


MALFORMED_HELP = ("The record can be cleared (it is kept in the history) with:\n"
                  "  python3 .claude/db/sync.py tasks-sync --unfreeze --approved-by <NAME>\n"
                  "and then frozen again with:\n"
                  "  python3 .claude/db/sync.py tasks-sync --freeze --approved-by <NAME>")


def _history_key(conn, prefix):
    """A unique history key: <prefix><UTC time with microseconds>[-N]."""
    base = prefix + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    key, n = base, 1
    while _meta_get(conn, key) is not None:
        n += 1
        key = "%s-%d" % (base, n)
    return key


def cmd_tasks_sync(options):
    """tasks-sync --status | --freeze --approved-by NAME [--reason R] | --unfreeze --approved-by NAME.

    A malformed freeze record stops the other commands (TASK_FREEZE_RECORD_INVALID); --status shows
    it and --unfreeze clears it (kept in the history)."""
    try:
        writing = not options.get("--status")
        conn, error = _open_write_conn() if writing else _open_read_conn()
        if error:
            _print_preflight_report(error)
            return 3
        try:
            if options.get("--status"):
                state, record = _task_freeze_state(conn)
                if state == "malformed":
                    print("Task sync: MALFORMED (the freeze record in _metadata is unreadable; "
                          "pull / push / sync / status stop until it is fixed)")
                    print(MALFORMED_HELP)
                    return 3
                frozen = state == "frozen"
                print("Task sync: %s%s" % (
                    "FROZEN (tasks are not pushed, pulled, backfilled or reconciled)"
                    if frozen else "active",
                    " approved_by=%s at=%s" % (record.get("approved_by"),
                                                record.get("frozen_at")) if frozen else ""))
                return 0
            approved_by = options["--approved-by"].strip()
            if not approved_by:
                raise IdentityLifecycleError("TASK_FREEZE_APPROVER_REQUIRED", 2)
            conn.execute("BEGIN IMMEDIATE")
            state, record = _task_freeze_state(conn)  # read inside the write lock
            if options.get("--freeze"):
                if state == "frozen":
                    conn.rollback()
                    print("  [FREEZE] already frozen (no change)")
                    return 0
                if state == "malformed":
                    conn.rollback()
                    print("ERROR: the task freeze record in _metadata is malformed")
                    print(MALFORMED_HELP)
                    return 3
                if conn.execute("SELECT 1 FROM _metadata WHERE substr(key, 1, 13) = "
                                "'pending_push:' LIMIT 1").fetchone():
                    conn.rollback()
                    raise IdentityLifecycleError("TASK_FREEZE_PENDING_JOURNAL", 3)
                _meta_set(conn, TASK_FREEZE_KEY, json.dumps({
                    "approved_by": approved_by, "reason": options.get("--reason") or "",
                    "frozen_at": _now_iso()}, ensure_ascii=False, sort_keys=True))
                conn.commit()
                print("  [FREEZE] task sync frozen by %s — local tasks and the Notion "
                      "Tasks DB are left as they are" % approved_by)
                return 0
            if state == "active":
                conn.rollback()
                raise IdentityLifecycleError("TASK_FREEZE_NOT_FROZEN", 2)
            previous = record if state == "frozen" else {"malformed_record": record}
            conn.execute("DELETE FROM _metadata WHERE key=?", (TASK_FREEZE_KEY,))
            _meta_set(conn, _history_key(conn, "task_sync_unfrozen:"), json.dumps({
                "unfrozen_by": approved_by, "previous": previous},
                ensure_ascii=False, sort_keys=True))
            conn.commit()
            if state == "malformed":
                print("  [UNFREEZE] malformed freeze record removed by %s (kept in the history); "
                      "freeze again with --freeze --approved-by <NAME>" % approved_by)
            else:
                print("  [UNFREEZE] task sync re-enabled by %s" % approved_by)
            return 0
        finally:
            conn.close()
    except (IdentityLifecycleError, sqlite3.Error) as exc:
        return _lifecycle_exit(exc)


class _Exclusions:
    """Excluded display Scopes plus the Project Identities they had."""

    def __init__(self, scopes=(), uids=(), pages=()):
        self.scopes = set(scopes)
        self.uids = set(uids)
        # T017: legacy pages a person decided to skip (never imported).
        self.pages = set(pages)

    def __bool__(self):
        return bool(self.scopes or self.uids or self.pages)

    def __contains__(self, scope_id):
        return _normalize_identity_text(scope_id) in self.scopes

    def row(self, entity, row):
        uid = row.get("sync_uid") if entity == "project" else row.get("project_sync_uid")
        return (_normalize_identity_text(row.get("scope_id")) in self.scopes
                or (bool(uid) and _normalize_identity_text(uid) in self.uids))

    def page(self, entity, page):
        if _normalize_notion_id(page.get("id")) in self.pages:
            return True
        props = page.get("properties") or {}
        uid = _extract_rich_text(props.get(
            "Sync UID" if entity == "project" else "Project Sync UID", {}))
        return (_normalize_identity_text(_extract_rich_text(props.get("Scope ID", {})))
                in self.scopes or (bool(uid) and _normalize_identity_text(uid) in self.uids))


def _parse_exclusion(key, value):
    scope = key[len(EXCLUDE_META_PREFIX):]
    try:
        record = json.loads(value)
        if (not isinstance(record, dict) or not isinstance(record.get("approved_by"), str)
                or not isinstance(record.get("project_sync_uids", []), list)):
            raise ValueError
    except (ValueError, TypeError):
        raise IdentityLifecycleError("EXCLUDE_RECORD_INVALID", 3)
    if not scope or _normalize_identity_text(scope) != scope:
        raise IdentityLifecycleError("EXCLUDE_RECORD_INVALID", 3)
    return scope, record


def _load_excluded_scopes(conn):
    exclusions = _Exclusions()
    for key, value in conn.execute(
            "SELECT key, value FROM _metadata WHERE substr(key, 1, ?) = ?",
            (len(EXCLUDE_META_PREFIX), EXCLUDE_META_PREFIX)).fetchall():
        scope, record = _parse_exclusion(key, value)
        exclusions.scopes.add(scope)
        exclusions.uids.update(_normalize_identity_text(uid)
                               for uid in record.get("project_sync_uids", []) if uid)
    for key, value in conn.execute(
            "SELECT key, value FROM _metadata WHERE substr(key, 1, ?) = ?",
            (len(LEGACY_SKIP_PREFIX), LEGACY_SKIP_PREFIX)).fetchall():
        try:
            if not isinstance(json.loads(value).get("approved_by"), str):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise IdentityLifecycleError("LEGACY_SKIP_RECORD_INVALID", 3)
        exclusions.pages.add(_normalize_notion_id(key[len(LEGACY_SKIP_PREFIX):]))
    return exclusions


def _is_excluded_scope(scope_id, excluded):
    return scope_id is not None and scope_id in excluded


def _drop_excluded_remote(remote_pages, excluded):
    if not excluded:
        return remote_pages
    return {entity: [page for page in pages if not excluded.page(entity, page)]
            for entity, pages in remote_pages.items()}


def _plan_touches_excluded(plan):
    """Pre-write fence: a Plan saved before ``exclude`` must not run after it."""
    conn, error = _open_read_conn()
    if error:
        return 3
    try:
        excluded = _load_excluded_scopes(conn)
        if _task_sync_frozen(conn) and any(
                operation.get("entity") == "task" for operation in plan.get("operations", [])):
            print("ERROR: TASK_SYNC_FROZEN (the Plan contains Task operations; "
                  "build a new Plan)")
            return 3
        if not excluded:
            return 0
        for operation in plan.get("operations", []):
            entity = operation.get("entity")
            table = "projects" if entity == "project" else "tasks"
            row = conn.execute("SELECT * FROM %s WHERE id=?" % table,
                               (operation.get("local_row_id"),)).fetchone()
            identity = operation.get("identity") or {}
            if (excluded.row(entity, dict(row) if row else {})
                    or _is_excluded_scope(operation.get("display_scope_id"), excluded)
                    or (identity.get("project_sync_uid")
                        and _normalize_identity_text(identity["project_sync_uid"])
                        in excluded.uids)):
                print("ERROR: SCOPE_EXCLUDED (the Plan touches a Scope registered as "
                      "never synced; build a new Plan)")
                return 3
        return 0
    except IdentityLifecycleError as exc:
        return _lifecycle_exit(exc)
    finally:
        conn.close()


def cmd_exclude(options):
    """exclude --list | --scope S --approved-by NAME [--reason R] | --remove S --approved-by NAME."""
    try:
        writing = not options.get("--list")
        conn, error = _open_write_conn() if writing else _open_read_conn()
        if error:
            _print_preflight_report(error)
            return 3
        try:
            excluded = _load_excluded_scopes(conn)
            if options.get("--list"):
                print("=== Sync-excluded Scopes: %d ===" % len(excluded.scopes))
                for scope in sorted(excluded.scopes):
                    record = json.loads(_meta_get(conn, EXCLUDE_META_PREFIX + scope))
                    print("  %s approved_by=%s at=%s%s" % (
                        scope, record.get("approved_by"), record.get("excluded_at"),
                        " reason=%s" % record["reason"] if record.get("reason") else ""))
                return 0
            approved_by = options["--approved-by"].strip()
            if not approved_by:
                raise IdentityLifecycleError("EXCLUDE_APPROVER_REQUIRED", 2)
            if options.get("--remove"):
                scope = _normalize_identity_text(options["--remove"])
                if scope not in excluded.scopes:
                    raise IdentityLifecycleError("EXCLUDE_SCOPE_NOT_REGISTERED", 2)
                conn.execute("BEGIN IMMEDIATE")
                previous = _meta_get(conn, EXCLUDE_META_PREFIX + scope)
                conn.execute("DELETE FROM _metadata WHERE key=?",
                             (EXCLUDE_META_PREFIX + scope,))
                # Audit trail of re-enabling sync for a confidential Scope.
                _meta_set(conn, "sync_exclusion_removed:%s:%s" % (scope, _now_iso()),
                          json.dumps({"removed_by": approved_by,
                                      "previous": json.loads(previous)},
                                     ensure_ascii=False, sort_keys=True))
                conn.commit()
                print("  [INCLUDE] %s by %s — its unlinked rows are pushed as new "
                      "pages by the next push" % (scope, approved_by))
                return 0
            scope = _normalize_identity_text(options["--scope"])
            if not scope:
                raise IdentityLifecycleError("SCOPE_INVALID", 3)
            if scope in excluded.scopes:
                print("  [EXCLUDE] %s already registered (no change)" % scope)
                return 0
            conn.execute("BEGIN IMMEDIATE")
            try:
                if conn.execute("SELECT 1 FROM _metadata WHERE substr(key, 1, 13) = "
                                "'pending_push:' LIMIT 1").fetchone():
                    raise IdentityLifecycleError("EXCLUDE_PENDING_JOURNAL", 3)
                uids = sorted({
                    _normalize_identity_text(row["sync_uid"])
                    for row in conn.execute("SELECT * FROM projects").fetchall()
                    if _normalize_identity_text(row["scope_id"]) == scope
                    and "sync_uid" in row.keys() and row["sync_uid"]})
                probe = _Exclusions([scope], uids)
                cleared = {}
                for entity, table in (("project", "projects"), ("task", "tasks")):
                    ids = [row["id"] for row in conn.execute(
                        "SELECT * FROM %s WHERE notion_page_id IS NOT NULL" % table)
                        if probe.row(entity, dict(row))]
                    # The link is cleared with last_sync_at so the row is not
                    # reported as a local edit by the updated_at trigger.
                    for row_id in ids:
                        conn.execute(
                            "UPDATE %s SET notion_page_id=NULL, notion_last_edited=NULL, "
                            "last_sync_at=NULL WHERE id=?" % table, (row_id,))
                    cleared[table] = len(ids)
                _meta_set(conn, EXCLUDE_META_PREFIX + scope, json.dumps({
                    "approved_by": approved_by,
                    "reason": options.get("--reason") or "",
                    "excluded_at": _now_iso(),
                    "cleared_links": cleared,
                    "project_sync_uids": uids,
                }, ensure_ascii=False, sort_keys=True))
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            print("  [EXCLUDE] %s by %s — local links cleared: projects %d, tasks %d "
                  "(Notion not touched)" % (scope, approved_by, cleared["projects"],
                                            cleared["tasks"]))
            return 0
        finally:
            conn.close()
    except (IdentityLifecycleError, sqlite3.Error) as exc:
        return _lifecycle_exit(exc)


# ── Legacy import (T017) ──────────────────────────────────
# Notion-only Projects (no Identity, not linked, not excluded, not skipped) are
# listed with their collisions; a person fills a triage file (import / skip /
# exclude).  Import creates local Identity rows linked to the pages (the
# Identity is written back to Notion by backfill-remote-identity); nothing
# ambiguous is decided automatically.

LEGACY_IMPORT_VERSION = 1
LEGACY_DECISIONS = {"import", "skip", "exclude"}
LEGACY_PROJECT_SYSTEMS = {"AI-PLC", "AIPO"}


def _legacy_candidates(conn, remote_pages):
    excluded = _load_excluded_scopes(conn)
    linked = {_normalize_notion_id(row[0]) for table in ("projects", "tasks")
              for row in conn.execute("SELECT notion_page_id FROM %s WHERE "
                                      "notion_page_id IS NOT NULL" % table)}
    items = []
    # 2026-10-01 Re-Collection: local tasks are frozen and Notion-only Task
    # rows are never imported, so only Projects are candidates.
    for entity in ("project",):
        for page in remote_pages.get(entity, []):
            if _normalize_notion_id(page.get("id")) in linked or excluded.page(entity, page):
                continue
            record = (_notion_row_to_project(page) if entity == "project"
                      else _notion_row_to_task(page))
            if _identity_record_state(entity, record)[0] != "legacy":
                continue
            scope = _normalize_identity_text(_extract_rich_text(
                (page.get("properties") or {}).get("Scope ID", {})))
            items.append({
                "page_id": page["id"], "entity": entity, "scope_id": scope,
                "task_id": record.get("task_id") if entity == "task" else None,
                "name": record.get("name"), "status": record.get("status"),
                "last_edited_time": page.get("last_edited_time"),
                "record": record,
            })
    return items


def _legacy_collisions(conn, items):
    local_scopes = {_normalize_identity_text(row[0])
                    for row in conn.execute("SELECT scope_id FROM projects")}
    groups = {}
    for item in items:
        key = (item["entity"], item["scope_id"],
               _normalize_identity_text(item["task_id"]) if item["task_id"] else None)
        groups.setdefault(key, []).append(item["page_id"])
    result = {}
    for item in items:
        codes = []
        scope = item["scope_id"]
        if not scope or scope == "UNKNOWN":
            codes.append("SCOPE_MISSING")
        else:
            if scope in local_scopes:
                codes.append("LOCAL_SCOPE_EXISTS")
            if item["record"].get("system") not in LEGACY_PROJECT_SYSTEMS:
                codes.append("VALUE_UNSUPPORTED")
        key = (item["entity"], scope,
               _normalize_identity_text(item["task_id"]) if item["task_id"] else None)
        if scope and len(groups.get(key, [])) > 1:
            codes.append("NOTION_DUPLICATE")
        result[item["page_id"]] = codes
    return result


def _legacy_digest(items):
    return _canonical_json_digest(sorted(
        [item["page_id"], item["entity"], item["scope_id"], item["task_id"],
         item["last_edited_time"]] for item in items))


def _legacy_remote():
    # Projects only: Notion-only Task rows are never imported (tasks frozen).
    return {"project": _query_db(PROJECTS_DB_ID), "task": []}


def build_legacy_import_template(conn, remote_pages):
    items = _legacy_candidates(conn, remote_pages)
    collisions = _legacy_collisions(conn, items)
    return {
        "legacy_import_version": LEGACY_IMPORT_VERSION,
        "candidates_digest": _legacy_digest(items),
        "approved_by": None,
        "items": [{
            "page_id": item["page_id"], "entity": item["entity"],
            "scope_id": item["scope_id"], "task_id": item["task_id"],
            "name": item["name"], "status": item["status"],
            "collisions": collisions[item["page_id"]],
            "decision": None,
        } for item in sorted(items, key=lambda i: (i["entity"] != "project",
                                                    i["scope_id"] or "",
                                                    i["task_id"] or ""))],
    }


def apply_legacy_import(conn, remote_pages, triage, *, manifest_path=None):
    if (not isinstance(triage, dict)
            or triage.get("legacy_import_version") != LEGACY_IMPORT_VERSION
            or not isinstance(triage.get("items"), list)):
        raise IdentityLifecycleError("LEGACY_TRIAGE_INVALID", 2)
    approved_by = triage.get("approved_by")
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise IdentityLifecycleError("LEGACY_TRIAGE_APPROVER_REQUIRED", 2)
    items = _legacy_candidates(conn, remote_pages)
    by_page = {item["page_id"]: item for item in items}
    decided = {}
    for entry in triage["items"]:
        if (not isinstance(entry, dict) or entry.get("page_id") in decided
                or entry.get("decision") not in LEGACY_DECISIONS):
            raise IdentityLifecycleError("LEGACY_TRIAGE_DECISION_INVALID", 2)
        decided[entry["page_id"]] = entry
    if not by_page and decided:
        excluded_now = _load_excluded_scopes(conn)
        linked_now = {_normalize_notion_id(row[0]) for row in conn.execute(
            "SELECT notion_page_id FROM projects WHERE notion_page_id IS NOT NULL")}
        if all(_normalize_notion_id(page_id) in linked_now | excluded_now.pages
               or _normalize_identity_text(entry.get("scope_id")) in excluded_now.scopes
               for page_id, entry in decided.items()):
            print("  [NOOP] every page in the triage file is already handled")
            return {"imported": 0, "skipped": 0, "excluded": 0, "noop": True}
        raise IdentityLifecycleError("LEGACY_SOURCE_CHANGED", 2)
    if (set(decided) != set(by_page)
            or triage.get("candidates_digest") != _legacy_digest(items)):
        raise IdentityLifecycleError("LEGACY_SOURCE_CHANGED", 2)
    for page_id, entry in decided.items():
        item = by_page[page_id]
        if (entry.get("entity"), entry.get("scope_id"), entry.get("task_id")) != (
                item["entity"], item["scope_id"], item["task_id"]):
            raise IdentityLifecycleError("LEGACY_TRIAGE_DECISION_INVALID", 2)
    collisions = _legacy_collisions(conn, items)
    imports = [by_page[p] for p, e in decided.items() if e["decision"] == "import"]
    import_project_scopes = {}
    for item in imports:
        codes = [c for c in collisions[item["page_id"]] if c != "NOTION_DUPLICATE"]
        if codes:
            raise IdentityLifecycleError("LEGACY_IMPORT_COLLISION", 2)
        if item["entity"] == "project":
            if item["scope_id"] in import_project_scopes:
                raise IdentityLifecycleError("LEGACY_IMPORT_COLLISION", 2)
            import_project_scopes[item["scope_id"]] = item
    # A local Project without a *live* link (none, or a page that is gone from
    # Notion) still has the legacy page as an attach candidate.
    live_pages = {_normalize_notion_id(page.get("id"))
                  for page in remote_pages.get("project", [])}
    unlinked_local_scopes = {
        _normalize_identity_text(row[0]) for row in conn.execute(
            "SELECT scope_id, notion_page_id FROM projects")
        if not row[1] or _normalize_notion_id(row[1]) not in live_pages}
    for page_id, entry in decided.items():
        item = by_page[page_id]
        if entry["decision"] == "exclude" and (
                not item["scope_id"] or item["scope_id"] == "UNKNOWN"):
            raise IdentityLifecycleError("LEGACY_EXCLUDE_SCOPE_MISSING", 2)
        if entry["decision"] == "exclude" and item["scope_id"] in import_project_scopes:
            # Importing and excluding the same Scope in one file is contradictory.
            raise IdentityLifecycleError("LEGACY_TRIAGE_CONFLICT", 2)
        if entry["decision"] == "skip" and item["scope_id"] in unlinked_local_scopes:
            # Skipping would silently decline the attach candidate of the
            # unlinked local Project; that is the push --decline flow (T015).
            raise IdentityLifecycleError("LEGACY_SKIP_NEEDS_DECLINE", 2)
    if any(entry["decision"] == "exclude" for entry in decided.values()) and conn.execute(
            "SELECT 1 FROM _metadata WHERE substr(key, 1, 13) = 'pending_push:' LIMIT 1"
            ).fetchone():
        raise IdentityLifecycleError("LEGACY_EXCLUDE_PENDING_JOURNAL", 3)
    manifest = resolve_workspace_identity(
        conn, manifest_path=manifest_path or WORKSPACE_MANIFEST_PATH)
    workspace_id = manifest["workspace_id"]
    now = _now_iso()
    counts = {"imported": 0, "skipped": 0, "excluded": 0}
    conn.execute("BEGIN IMMEDIATE")
    try:
        project_identity = {}
        for scope, item in import_project_scopes.items():
            record = item["record"]
            uid = _new_project_sync_uid()
            conn.execute("""
                INSERT INTO projects (notion_page_id, scope_id, name, goal, owner, status,
                    mode, depth, system, parent_scope, top_page_url, start_date, deadline,
                    notion_last_edited, last_sync_at, created_at, updated_at,
                    workspace_id, sync_uid, ownership_epoch, identity_version)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,2)
            """, (item["page_id"], scope, record["name"], record["goal"],
                  record["owner"], record["status"], record["mode"], record["depth"],
                  record["system"], record["parent_scope"], record["top_page_url"],
                  record["start_date"], record["deadline"], item["last_edited_time"],
                  now, now, now, workspace_id, uid))
            project_identity[scope] = (uid, 1)
            counts["imported"] += 1
        for page_id, entry in decided.items():
            item = by_page[page_id]
            if entry["decision"] == "skip":
                _meta_set(conn, LEGACY_SKIP_PREFIX + _normalize_notion_id(page_id),
                          json.dumps({"approved_by": approved_by.strip(),
                                      "scope_id": item["scope_id"],
                                      "skipped_at": now}, ensure_ascii=False,
                                     sort_keys=True))
                counts["skipped"] += 1
            elif entry["decision"] == "exclude":
                key = EXCLUDE_META_PREFIX + item["scope_id"]
                if _meta_get(conn, key) is None:
                    uids = sorted({
                        _normalize_identity_text(row["sync_uid"])
                        for row in conn.execute("SELECT * FROM projects")
                        if _normalize_identity_text(row["scope_id"]) == item["scope_id"]
                        and row["sync_uid"]})
                    # Same semantics as `exclude --scope`: clear local links.
                    probe = _Exclusions([item["scope_id"]], uids)
                    cleared = {}
                    for entity, table in (("project", "projects"), ("task", "tasks")):
                        ids = [row["id"] for row in conn.execute(
                            "SELECT * FROM %s WHERE notion_page_id IS NOT NULL" % table)
                            if probe.row(entity, dict(row))]
                        for row_id in ids:
                            conn.execute(
                                "UPDATE %s SET notion_page_id=NULL, notion_last_edited=NULL, "
                                "last_sync_at=NULL WHERE id=?" % table, (row_id,))
                        cleared[table] = len(ids)
                    _meta_set(conn, key, json.dumps({
                        "approved_by": approved_by.strip(),
                        "reason": "legacy triage (T017)", "excluded_at": now,
                        "cleared_links": cleared,
                        "project_sync_uids": uids}, ensure_ascii=False, sort_keys=True))
                counts["excluded"] += 1
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise IdentityLifecycleError("LEGACY_IMPORT_CONSTRAINT", 2)
    except BaseException:
        conn.rollback()
        raise
    return dict(counts, noop=False)


def cmd_import_legacy(options):
    """import-legacy --dry-run --out FILE | --apply FILE."""
    try:
        if options.get("--dry-run"):
            conn, error = _open_read_conn()
            if error:
                _print_preflight_report(error)
                return 3
            try:
                template = build_legacy_import_template(conn, _legacy_remote())
            finally:
                conn.close()
            _atomic_json_write(options["--out"], template)
            summary = {}
            for item in template["items"]:
                key = "%s:%s" % (item["entity"], ",".join(item["collisions"]) or "clean")
                summary[key] = summary.get(key, 0) + 1
            print(json.dumps({"candidates": len(template["items"]), "by_collision": summary},
                             ensure_ascii=False, sort_keys=True))
            print("NEXT: a person fills every decision (import / skip / exclude) and "
                  "approved_by, then runs import-legacy --apply FILE.")
            return 0
        with open(options["--apply"], encoding="utf-8") as handle:
            triage = json.load(handle)
        conn, error = _open_write_conn()
        if error:
            _print_preflight_report(error)
            return 3
        try:
            result = apply_legacy_import(conn, _legacy_remote(), triage,
                                         manifest_path=WORKSPACE_MANIFEST_PATH)
        finally:
            conn.close()
        print(json.dumps(result, sort_keys=True))
        if result.get("imported"):
            print("NEXT: run backfill-remote-identity --dry-run to write the Identity of "
                  "the imported rows back to their Notion pages.")
        return 0
    except urllib.error.HTTPError as exc:
        print("ERROR: LEGACY_IMPORT_API_ERROR %d" % exc.code)
        return 4
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        print("ERROR: LEGACY_IMPORT_API_ERROR network")
        return 4
    except (IdentityLifecycleError, KeyError, TypeError, ValueError, OSError,
            json.JSONDecodeError, sqlite3.Error) as exc:
        return _lifecycle_exit(exc)


# ── Declined legacy candidates (T015) ─────────────────────
# A person may decide that an Identity-less Notion page sharing a row's Scope
# ID is a different Project.  The decision is recorded locally (never in
# Notion); reconciliation then stops offering that page as an attach
# candidate, so the row is created as its own Identity by an ordinary push.

DECLINE_META_PREFIX = "declined_legacy_candidate:"
DECLINE_REASONS = {"LEGACY_ATTACH_CANDIDATE", "LEGACY_AMBIGUOUS"}


def _decline_meta_key(entity, identity_key):
    return DECLINE_META_PREFIX + json.dumps([entity, list(identity_key)],
                                            ensure_ascii=False)


def _decline_rows(conn):
    return conn.execute(
        "SELECT key, value FROM _metadata WHERE substr(key, 1, ?) = ? ORDER BY key",
        (len(DECLINE_META_PREFIX), DECLINE_META_PREFIX)).fetchall()


def _parse_decline_row(key, value):
    try:
        entity, identity_key = json.loads(key[len(DECLINE_META_PREFIX):])
        record = json.loads(value)
        pages = record["page_ids"]
        if (entity not in {"project", "task"} or not isinstance(identity_key, list)
                or not isinstance(pages, list)
                or not all(isinstance(page, str) for page in pages)):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise IdentityLifecycleError("DECLINE_RECORD_INVALID", 3)
    return entity, tuple(identity_key), record


def _load_declined_candidates(conn):
    declined = {}
    for row in _decline_rows(conn):
        entity, identity_key, record = _parse_decline_row(row[0], row[1])
        declined[(entity, identity_key)] = set(record["page_ids"])
    return declined


def _decline_record_id(key):
    return _canonical_json_digest(key)[len("sha256:"):][:12]


def _validate_decline_document(plan, decline):
    if not isinstance(decline, dict) or not set(decline) <= {
            "plan_id", "operation_ids", "approved_by", "reason"}:
        raise IdentityLifecycleError("DECLINE_DOCUMENT_INVALID", 2)
    if "reason" in decline and not isinstance(decline["reason"], str):
        raise IdentityLifecycleError("DECLINE_DOCUMENT_INVALID", 2)
    if decline.get("plan_id") != plan.get("plan_id"):
        raise IdentityLifecycleError("DECLINE_PLAN_MISMATCH", 2)
    approved_by = decline.get("approved_by")
    ids = decline.get("operation_ids")
    if (not isinstance(approved_by, str) or not approved_by.strip()
            or not isinstance(ids, list) or not ids
            or not all(isinstance(value, str) for value in ids)
            or len(set(ids)) != len(ids)):
        raise IdentityLifecycleError("DECLINE_DOCUMENT_INVALID", 2)
    by_id = {op["operation_id"]: op for op in plan["operations"]}
    selected = []
    for operation_id in ids:
        op = by_id.get(operation_id)
        if (op is None or op["action"] not in {"attach_candidate", "conflict"}
                or op.get("expected_reconciliation_reason") not in DECLINE_REASONS
                or not op.get("remote_page_ids")):
            raise IdentityLifecycleError("DECLINE_OPERATION_INVALID", 2)
        selected.append(op)
    return selected


def record_declined_candidates(conn, plan, decline):
    """Persist approved declines; no Notion call and no row mutation."""
    if _push_plan_schema_version(plan) != 2:
        raise IdentityLifecycleError("DECLINE_REQUIRES_V2_PLAN", 3)
    selected = _validate_decline_document(plan, decline)
    recorded = unchanged = 0
    lines = []
    conn.execute("BEGIN IMMEDIATE")
    try:
        for op in selected:
            identity = op["identity"]
            key = ((identity["project_sync_uid"],) if op["entity"] == "project"
                   else (identity["project_sync_uid"], identity["task_id"]))
            table = "projects" if op["entity"] == "project" else "tasks"
            row = conn.execute("SELECT * FROM %s WHERE id=?" % table,
                               (op["local_row_id"],)).fetchone()
            if row is None or _identity_key(op["entity"], dict(row)) != key \
                    or row["notion_page_id"]:
                raise IdentityLifecycleError("DECLINE_SOURCE_CHANGED", 2)
            meta_key = _decline_meta_key(op["entity"], key)
            existing = _meta_get(conn, meta_key)
            pages = set(op["remote_page_ids"])
            if existing and pages <= set(json.loads(existing)["page_ids"]):
                unchanged += 1
                continue
            if existing:
                pages |= set(json.loads(existing)["page_ids"])
            _meta_set(conn, meta_key, json.dumps({
                "page_ids": sorted(pages), "plan_id": plan["plan_id"],
                "operation_id": op["operation_id"],
                "approved_by": decline["approved_by"].strip(),
                "reason": decline.get("reason", ""),
                "display_scope_id": op["display_scope_id"],
                "declined_at": _now_iso(),
            }, ensure_ascii=False, sort_keys=True))
            recorded += 1
            lines.append("  [DECLINE] %s %s%s (%d legacy page(s) will not be attached)"
                         % (op["entity"], op["display_scope_id"],
                            "/" + identity["task_id"] if identity.get("task_id")
                            else "", len(op["remote_page_ids"])))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    for line in lines:  # only after the commit: nothing unsaved is reported
        print(line)
    return {"recorded": recorded, "unchanged": unchanged}


def cmd_declines(options):
    """declines [--revoke ID --approved-by NAME]: list or revoke declines."""
    try:
        if options.get("--revoke"):
            conn, error = _open_write_conn()
        else:
            conn, error = _open_read_conn()
        if error:
            _print_preflight_report(error)
            return 3
        try:
            rows = [(row[0],) + _parse_decline_row(row[0], row[1])
                    for row in _decline_rows(conn)]
            if not options.get("--revoke"):
                print("=== Declined legacy candidates: %d ===" % len(rows))
                for key, entity, identity_key, record in rows:
                    print("  %s %s %s%s pages=%d approved_by=%s at=%s%s" % (
                        _decline_record_id(key), entity,
                        record.get("display_scope_id", ""),
                        "/" + identity_key[1] if len(identity_key) > 1 else "",
                        len(record["page_ids"]), record.get("approved_by", ""),
                        record.get("declined_at", ""),
                        " reason=%s" % record["reason"] if record.get("reason") else ""))
                return 0
            approved_by = (options.get("--approved-by") or "").strip()
            matches = [row for row in rows
                       if _decline_record_id(row[0]) == options["--revoke"]]
            if not approved_by or len(matches) != 1:
                raise IdentityLifecycleError("DECLINE_REVOKE_INVALID", 2)
            conn.execute("DELETE FROM _metadata WHERE key=?", (matches[0][0],))
            conn.commit()
            print("  [REVOKE] %s %s by %s — the legacy page is offered as an "
                  "attach candidate again (if the row is still unlinked)" % (
                      options["--revoke"], matches[0][3].get("display_scope_id", ""),
                      approved_by))
            return 0
        finally:
            conn.close()
    except (IdentityLifecycleError, sqlite3.Error) as exc:
        return _lifecycle_exit(exc)


def cmd_push(dry_run=False, skip_preflight=False, plan=None, expected_plan_id=None,
             plan_path=None, plan_out=None, authorization=None,
             authorization_path=None, scope_id=None, sync_uid=None,
             workspace_id=None, decline_path=None):
    if _project_cancelled_sync_guard(scope_id, sync_uid):
        return 3
    if plan is not None and plan_path:
        print("ERROR: pass either plan or plan_path")
        return 64
    built_here = plan is None and not plan_path
    try:
        plan = plan or (load_push_plan(plan_path) if plan_path else
                        build_push_plan(
                            skip_preflight=skip_preflight, scope_id=scope_id,
                            sync_uid=sync_uid, workspace_id=workspace_id,
                        ))
        if authorization is None and authorization_path:
            with open(authorization_path, encoding="utf-8") as handle:
                authorization = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("ERROR: %s" % exc)
        return 2
    if not validate_push_plan(plan, expected_plan_id):
        print("ERROR: push plan artifact does not match plan_id")
        return 2
    # A selector refusal built here is already a blocked Plan carrying the
    # contract exit code; re-checking its (v1-shaped) selector would mask it.
    built_blocked = built_here and plan["exit_code"] and not plan["operations"]
    if (not built_blocked
            and not validate_plan_selector(plan, scope_id, sync_uid, workspace_id)):
        print("ERROR: push plan selector does not match --scope/--sync-uid/--workspace-id")
        return 2
    if decline_path:
        # T015: record the approved declines only; the next dry-run builds
        # ordinary CREATE operations for those rows.
        try:
            with open(decline_path, encoding="utf-8") as handle:
                decline = json.load(handle)
            conn, error = _open_write_conn()
            if error:
                _print_preflight_report(error)
                return 3
            try:
                result = record_declined_candidates(conn, plan, decline)
            finally:
                conn.close()
        except (OSError, ValueError, json.JSONDecodeError, KeyError,
                sqlite3.Error) as exc:
            return _lifecycle_exit(exc)
        print(json.dumps(result, sort_keys=True))
        print("NEXT: rerun push --dry-run for this selector; declined rows are "
              "planned as create_remote (the legacy pages stay untouched).")
        return 0
    _print_push_plan(plan, dry_run=dry_run)
    if plan_out:
        try:
            write_push_plan(plan, plan_out)
        except (OSError, ValueError) as exc:
            print("ERROR: %s" % exc)
            return 3
    if built_blocked:
        return plan["exit_code"]
    return plan["exit_code"] if dry_run else execute_push_plan(
        plan, authorization=authorization, scope_id=scope_id,
        sync_uid=sync_uid, workspace_id=workspace_id,
    )


def _parse_iso_datetime(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _last_pull_warning(last_pull, now=None, threshold_hours=24):
    if not last_pull:
        return "LAST_PULL_NEVER"
    pulled = _parse_iso_datetime(last_pull)
    current = _parse_iso_datetime(now or _now_iso())
    if not pulled or not current:
        return "LAST_PULL_INVALID"
    if pulled.tzinfo is None:
        pulled = pulled.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age_seconds = (current.astimezone(timezone.utc)
                   - pulled.astimezone(timezone.utc)).total_seconds()
    if age_seconds < 0:
        return "LAST_PULL_FUTURE"
    if age_seconds > threshold_hours * 3600:
        return "LAST_PULL_STALE"
    return None


def build_status_audit_report():
    """Aggregate local state and the read-only push planner classifications."""
    conn, error = _open_read_conn()
    if error:
        return {
            "status": "blocked", "exit_code": 3,
            "counts": {"dirty": 0, "missing_id": 0, "stale_link": 0,
                       "collision": 0, "duplicate": 0, "schema_error": 1},
            "warnings": [], "plan": None,
        }
    try:
        tasks_frozen = _task_sync_frozen(conn)
    except IdentityLifecycleError:
        conn.close()
        return {
            "status": "blocked", "exit_code": 3,
            "counts": {"dirty": 0, "missing_id": 0, "stale_link": 0,
                       "collision": 0, "duplicate": 0, "schema_error": 1},
            "warnings": ["TASK_FREEZE_RECORD_INVALID"], "plan": None,
        }
    task_dirty_sql = "" if tasks_frozen else """
          UNION ALL
          SELECT id FROM tasks WHERE notion_page_id IS NULL OR last_sync_at IS NULL
             OR updated_at > last_sync_at"""
    dirty = conn.execute("""
        SELECT COUNT(*) c FROM (
          SELECT id FROM projects WHERE notion_page_id IS NULL OR last_sync_at IS NULL
             OR updated_at > last_sync_at%s
        )
    """ % task_dirty_sql).fetchone()["c"]
    missing = conn.execute("""
        SELECT (SELECT COUNT(*) FROM projects WHERE notion_page_id IS NULL)%s c
    """ % ("" if tasks_frozen else
           " + (SELECT COUNT(*) FROM tasks WHERE notion_page_id IS NULL)")).fetchone()["c"]
    last_pull = _meta_get(conn, "last_pull_at")
    conn.close()
    plan = build_push_plan()
    stale_links = sum(
        1 for operation in plan["operations"]
        if operation.get("link_state") in {"not_found", "wrong_parent", "trashed"}
    )
    schema_errors = sum(
        1 for finding in plan["preflight"].get("findings", [])
        if finding.get("code") in {"SCHEMA_MISMATCH", "LOCAL_SCHEMA_MISMATCH",
                                   "LOCAL_IDENTITY_SCHEMA_PARTIAL",
                                   "LOCAL_IDENTITY_SCHEMA_MIXED",
                                   "LOCAL_DB_UNAVAILABLE"}
    )
    warning = _last_pull_warning(last_pull)
    projection = plan.get("reconciliation", {})
    blocking_summary = projection.get("blocking", {}).get("summary", {})
    audit_summary = projection.get("audit_only", {}).get("summary", {})
    counts = {
        "dirty": dirty,
        "missing_id": missing,
        "stale_link": stale_links,
        "collision": (blocking_summary.get("collision", 0)
                      + audit_summary.get("collision", 0)),
        "duplicate": (blocking_summary.get("duplicate", 0)
                      + audit_summary.get("duplicate", 0)),
        "schema_error": schema_errors,
    }
    return {
        "status": "blocked" if plan["exit_code"] else "pass",
        "exit_code": plan["exit_code"], "counts": counts,
        "warnings": [warning] if warning else [], "plan": plan,
    }


def _print_status_audit_report(report):
    print("\n=== Sync Audit: %s ===" % report["status"].upper())
    print("  " + "  ".join(
        "%s=%d" % item for item in report["counts"].items()
    ))
    for warning in report["warnings"]:
        print("  [WARN] %s" % warning)
    if report.get("plan"):
        print("  Plan: " + "  ".join(
            "%s=%d" % item for item in report["plan"]["summary"].items()
        ))
        projection = report["plan"].get("reconciliation", {})
        if projection:
            print("  Blocking: " + "  ".join(
                "%s=%d" % item
                for item in projection["blocking"]["summary"].items()
            ))
            print("  Audit-only: " + "  ".join(
                ["%s=%d" % item
                 for item in projection["audit_only"]["summary"].items()]
                + ["digest=%s" % projection["audit_only"]["projection_digest"]]
            ))
            identity_codes = projection.get("raw_summary", {}).get(
                "identity_codes", {}
            )
            if identity_codes:
                print("  Identity: " + "  ".join(
                    "%s=%d" % item for item in sorted(identity_codes.items())
                ))


def build_identity_status(conn):
    """Read-only Identity projection for status (None on a v1 schema)."""
    selection = resolve_identity_selection(conn)
    if selection["mode"] == "v1":
        return None
    if selection["exit_code"]:
        return {"status": "blocked", "code": selection["finding"]["code"]}
    workspace_id = selection["context"]["workspace_id"]
    counts = {}
    for entity, table in (("project", "projects"), ("task", "tasks")):
        row = conn.execute("""
            SELECT
              SUM(CASE WHEN workspace_id=? THEN 1 ELSE 0 END) current_ws,
              SUM(CASE WHEN workspace_id IS NOT NULL AND workspace_id<>? THEN 1
                  ELSE 0 END) other_ws,
              SUM(CASE WHEN workspace_id IS NULL THEN 1 ELSE 0 END) legacy,
              SUM(CASE WHEN workspace_id=? AND (notion_page_id IS NULL
                  OR last_sync_at IS NULL OR updated_at > last_sync_at)
                  THEN 1 ELSE 0 END) dirty
            FROM %s
        """ % table, (workspace_id, workspace_id, workspace_id)).fetchone()
        counts[entity] = {key: int(row[key] or 0)
                          for key in ("current_ws", "other_ws", "legacy", "dirty")}
    return {"status": "pass", "workspace_id": workspace_id,
            "writer_epoch": selection["context"]["writer_epoch"],
            "counts": counts}


def _print_identity_status(report):
    if report["status"] != "pass":
        print("  Identity: BLOCKED %s (read-only; no Identity is issued)" % report["code"])
        return
    print("  Identity: v2 workspace=%s writer_epoch=%d" % (
        _short_identity(report["workspace_id"]), report["writer_epoch"]))
    for entity in ("project", "task"):
        counts = report["counts"][entity]
        print("    %s: current_workspace=%d dirty=%d other_workspace=%d "
              "legacy_read_only=%d" % (
                  entity, counts["current_ws"], counts["dirty"],
                  counts["other_ws"], counts["legacy"]))


def _render_status_with_connection(conn, audit=False):
    last_pull = _meta_get(conn, "last_pull_at") or "(never)"
    last_push = _meta_get(conn, "last_push_at") or "(never)"

    print("=== AI-PLC DB Sync Status ===")
    print("  DB: %s" % DB_PATH)
    print("  Last Pull: %s" % last_pull)
    print("  Last Push: %s" % last_push)
    identity_status = build_identity_status(conn)
    identity_exit = 0
    if identity_status is not None:
        _print_identity_status(identity_status)
        if identity_status["status"] != "pass":
            # manifest/cache split-brain or unresolved workspace (§12.1: 3).
            identity_exit = 3

    # Locally dirty rows
    dirty_projects = conn.execute("""
        SELECT scope_id, name, updated_at, last_sync_at FROM projects
        WHERE notion_page_id IS NULL
           OR last_sync_at IS NULL
           OR updated_at > last_sync_at
    """).fetchall()
    dirty_tasks = conn.execute("""
        SELECT task_id, scope_id, name, updated_at, last_sync_at FROM tasks
        WHERE notion_page_id IS NULL
           OR last_sync_at IS NULL
           OR updated_at > last_sync_at
    """).fetchall()

    # New rows (no notion_page_id)
    new_projects = conn.execute(
        "SELECT scope_id, name FROM projects WHERE notion_page_id IS NULL"
    ).fetchall()
    new_tasks = conn.execute(
        "SELECT task_id, scope_id, name FROM tasks WHERE notion_page_id IS NULL"
    ).fetchall()

    total_p = conn.execute("SELECT COUNT(*) c FROM projects").fetchone()["c"]
    total_t = conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]

    print("\n  Projects: %d total, %d dirty, %d new" % (
        total_p, len(dirty_projects), len(new_projects)))
    if dirty_projects:
        for r in dirty_projects:
            tag = "(new)" if r["last_sync_at"] is None else "(modified)"
            print("    %s %s — %s" % (tag, r["scope_id"], r["name"]))

    if _task_sync_frozen(conn):
        print("  Tasks: %d total — frozen (not synced; backlog.yaml is the source)" % total_t)
        dirty_tasks = []
    else:
        print("  Tasks: %d total, %d dirty, %d new" % (
            total_t, len(dirty_tasks), len(new_tasks)))
    if dirty_tasks:
        for r in dirty_tasks:
            tag = "(new)" if r["last_sync_at"] is None else "(modified)"
            print("    %s %s/%s — %s" % (tag, r["scope_id"], r["task_id"], r["name"]))

    if not audit:
        return identity_exit
    report = build_status_audit_report()
    _print_status_audit_report(report)
    return identity_exit or report["exit_code"]


def cmd_status(audit=False):
    """Render status while converting local schema failures to exit 3."""
    conn = None
    try:
        conn = _get_preflight_conn()
        return _render_status_with_connection(conn, audit=audit)
    except (sqlite3.Error, OSError) as exc:
        print("ERROR: LOCAL_SCHEMA_MISMATCH: %s" % exc)
        if audit:
            _print_status_audit_report({
                "status": "blocked", "exit_code": 3,
                "counts": {"dirty": 0, "missing_id": 0, "stale_link": 0,
                           "collision": 0, "duplicate": 0, "schema_error": 1},
                "warnings": [], "plan": None,
            })
        return 3
    finally:
        if conn is not None:
            conn.close()


# ── SYNC (bidirectional) ───────────────────────────────────

def cmd_sync(dry_run=False):
    print("=== Bidirectional Sync %s===\n" % ("(DRY RUN) " if dry_run else ""))
    preflight = run_preflight()
    _print_preflight_report(preflight)
    if preflight["status"] != "pass":
        return 3
    print("--- Phase 1: Pull (Notion → Local) ---")
    result = cmd_pull(dry_run=dry_run, skip_preflight=True)
    if result:
        return result
    print("\n--- Phase 2: Push (Local → Notion) ---")
    result = cmd_push(dry_run=dry_run, skip_preflight=True)
    if result:
        return result
    print("\nSync complete.")
    return 0


# ── Identity migration Plan (T006) ─────────────────────────

IDENTITY_MIGRATION_PLAN_VERSION = 1
IDENTITY_MIGRATION_BATCH_SIZE = 10
IDENTITY_MIGRATION_DECISIONS = {"fixed_mapping", "legacy_excluded"}


def _migration_plan_id(plan):
    canonical = {key: plan.get(key) for key in (
        "plan_schema_version", "direction", "identity", "source_snapshot",
        "decision_digest", "decisions", "operations", "batches",
        "mutation_budget",
    )}
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _migration_table_columns(conn, table):
    return {row[1] for row in conn.execute("PRAGMA table_info(%s)" % table)}


def identity_migration_inventory(conn):
    """Return a privacy-safe deterministic inventory without mutating SQLite."""
    rows = conn.execute("""
        SELECT t.id, t.scope_id, t.task_id,
               CASE WHEN t.notion_page_id IS NULL OR trim(t.notion_page_id)=''
                    THEN 0 ELSE 1 END AS linked
        FROM tasks t LEFT JOIN projects p ON p.scope_id=t.scope_id
        WHERE p.id IS NULL ORDER BY t.scope_id, t.task_id, t.id
    """).fetchall()
    orphans = [{
        "routing_key": "%s/%s" % (row[1], row[2]),
        "scope_id": row[1], "task_id": row[2], "linked": bool(row[3]),
    } for row in rows]
    return {
        "state": "adjudication_required" if orphans else "inventory",
        "counts": {
            "projects": conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
            "tasks": conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
            "orphans": len(orphans),
        },
        "orphans": orphans,
    }


def _migration_source_snapshot(conn, intents):
    projects = [tuple(row) for row in conn.execute(
        "SELECT id, notion_page_id, scope_id, updated_at FROM projects ORDER BY id"
    )]
    tasks = [tuple(row) for row in conn.execute(
        "SELECT id, notion_page_id, scope_id, task_id, updated_at FROM tasks ORDER BY id"
    )]
    return {
        "sqlite_digest": _canonical_json_digest({"projects": projects, "tasks": tasks}),
        "intent_digest": _canonical_json_digest(intents),
        "counts": {"projects": len(projects), "tasks": len(tasks)},
    }


def _migration_preservation_digest(row):
    return _canonical_json_digest({
        "notion_page_id": row.get("notion_page_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "last_sync_at": row.get("last_sync_at"),
    })


def build_identity_migration_plan(conn, workspace_id, decisions, intents, *,
                                  project_uid_mappings=None, remote=None,
                                  batch_size=10):
    """Build an immutable, fully adjudicated migration Plan before mutation.

    ``intents`` is a mapping keyed by exact scope_id.  A fixed orphan mapping
    may target an existing Project UID or request a missing Project from an
    exact intent.  No path/name/prefix fallback is performed.
    """
    workspace_id = _coerce_canonical_identity(
        "wsp_", WORKSPACE_ID_PATTERN, workspace_id
    )
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) \
            or not 1 <= batch_size <= IDENTITY_MIGRATION_BATCH_SIZE:
        raise ValueError("IDENTITY_MIGRATION_INVALID_BATCH_SIZE")
    inventory = identity_migration_inventory(conn)
    by_key = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ValueError("IDENTITY_MIGRATION_INVALID_DECISION")
        key = decision.get("routing_key")
        if key in by_key:
            raise ValueError("IDENTITY_MIGRATION_DUPLICATE_DECISION")
        if decision.get("decision") not in IDENTITY_MIGRATION_DECISIONS:
            raise ValueError("IDENTITY_MIGRATION_INVALID_DECISION")
        by_key[key] = dict(decision)
    expected = {item["routing_key"] for item in inventory["orphans"]}
    if set(by_key) != expected:
        raise ValueError("IDENTITY_MIGRATION_ADJUDICATION_INCOMPLETE")

    fixed_project_uids = dict(project_uid_mappings or {})
    project_rows = [dict(zip(
        [item[0] for item in cursor.description], row
    )) for cursor in [conn.execute("SELECT * FROM projects ORDER BY id")]
        for row in cursor.fetchall()]
    project_uids = {}
    used_uids = set()
    for row in project_rows:
        existing = row.get("sync_uid")
        uid = existing or fixed_project_uids.get(row["scope_id"])
        if not uid:
            raise ValueError("IDENTITY_MIGRATION_FIXED_UID_REQUIRED")
        uid = _coerce_canonical_identity("prj_", PROJECT_UID_PATTERN, uid)
        if uid in used_uids:
            raise ValueError("IDENTITY_MIGRATION_UID_COLLISION")
        used_uids.add(uid)
        project_uids[row["scope_id"]] = uid

    new_projects = {}
    normalized_decisions = []
    for orphan in inventory["orphans"]:
        decision = by_key[orphan["routing_key"]]
        normalized = {
            "routing_key": orphan["routing_key"],
            "decision": decision["decision"],
            "evidence_digest": decision.get("evidence_digest"),
        }
        if not normalized["evidence_digest"]:
            raise ValueError("IDENTITY_MIGRATION_EVIDENCE_REQUIRED")
        if decision["decision"] == "fixed_mapping":
            uid = decision.get("project_sync_uid")
            if uid:
                uid = _coerce_canonical_identity("prj_", PROJECT_UID_PATTERN, uid)
            if orphan["scope_id"] in project_uids:
                expected_uid = project_uids[orphan["scope_id"]]
                if uid and uid != expected_uid:
                    raise ValueError("IDENTITY_MIGRATION_FIXED_MAPPING_CONFLICT")
                uid = expected_uid
            else:
                intent = intents.get(orphan["scope_id"])
                if not isinstance(intent, dict) or intent.get("scope_id") != orphan["scope_id"]:
                    raise ValueError("IDENTITY_MIGRATION_EXACT_INTENT_REQUIRED")
                if not uid:
                    raise ValueError("IDENTITY_MIGRATION_FIXED_UID_REQUIRED")
                prior = new_projects.get(orphan["scope_id"])
                if uid in used_uids and not prior:
                    raise ValueError("IDENTITY_MIGRATION_UID_COLLISION")
                if prior and prior["project_sync_uid"] != uid:
                    raise ValueError("IDENTITY_MIGRATION_FIXED_MAPPING_CONFLICT")
                new_projects[orphan["scope_id"]] = {
                    "scope_id": orphan["scope_id"],
                    "project_sync_uid": uid,
                    "intent_digest": _canonical_json_digest(intent),
                    "name": intent.get("name") or intent.get("goal") or orphan["scope_id"],
                    "status": intent.get("status") or "planned",
                }
                project_uids[orphan["scope_id"]] = uid
                used_uids.add(uid)
            normalized["project_sync_uid"] = uid
        normalized_decisions.append(normalized)

    operations = []
    for row in project_rows:
        uid = project_uids[row["scope_id"]]
        operations.append({
            "operation_id": "project:%s" % row["id"], "entity": "project",
            "action": "backfill", "row_id": row["id"], "scope_id": row["scope_id"],
            "project_sync_uid": uid, "notion_linked": bool(row.get("notion_page_id")),
            "preservation_digest": _migration_preservation_digest(row),
        })
    for item in sorted(new_projects.values(), key=lambda value: value["scope_id"]):
        operations.append({
            "operation_id": "project:new:%s" % item["scope_id"],
            "entity": "project", "action": "create_from_intent",
            **item,
        })
    decision_by_key = {item["routing_key"]: item for item in normalized_decisions}
    task_cursor = conn.execute("SELECT * FROM tasks ORDER BY id")
    task_names = [item[0] for item in task_cursor.description]
    for raw in task_cursor.fetchall():
        row = dict(zip(task_names, raw))
        key = "%s/%s" % (row["scope_id"], row["task_id"])
        decision = decision_by_key.get(key)
        if decision and decision["decision"] == "legacy_excluded":
            continue
        uid = (decision or {}).get("project_sync_uid") or project_uids.get(row["scope_id"])
        if not uid:
            raise ValueError("IDENTITY_MIGRATION_TASK_PARENT_MISSING")
        operations.append({
            "operation_id": "task:%s" % row["id"], "entity": "task",
            "action": "backfill", "row_id": row["id"], "scope_id": row["scope_id"],
            "task_id": row["task_id"], "project_sync_uid": uid,
            "notion_linked": bool(row.get("notion_page_id")),
            "preservation_digest": _migration_preservation_digest(row),
        })
    target_by_scope = {op["scope_id"]: op["project_sync_uid"] for op in operations
                       if op["entity"] == "project"}
    for scope_id, uid in target_by_scope.items():
        intent = intents.get(scope_id)
        if not isinstance(intent, dict) or intent.get("scope_id") != scope_id:
            raise ValueError("IDENTITY_MIGRATION_EXACT_INTENT_REQUIRED")
        current_identity = intent.get("identity")
        if current_identity is not None and not isinstance(current_identity, dict):
            raise ValueError("IDENTITY_MIGRATION_INTENT_IDENTITY_INVALID")
        current_identity = current_identity or {}
        target_identity = {
            "version": 2, "workspace_id": workspace_id, "sync_uid": uid,
            "ownership_epoch": 1,
        }
        if any(current_identity.get(key) not in (None, value)
               for key, value in target_identity.items()):
            raise ValueError("IDENTITY_MIGRATION_INTENT_COLLISION")
        for op in operations:
            if op["entity"] == "project" and op["scope_id"] == scope_id:
                op["expected_intent_identity"] = current_identity
                op["intent_digest"] = _canonical_json_digest(intent)
                break
    for op in operations:
        op["workspace_id"] = workspace_id
        current = (_migration_remote_identity(remote.read(op["entity"], op))
                   if remote is not None else None)
        target = {
            "workspace_id": workspace_id,
            "project_sync_uid": op["project_sync_uid"],
            "ownership_epoch": 1, "identity_version": 2,
        }
        if current is not None and any(
                current.get(key) not in (None, value) for key, value in target.items()):
            raise ValueError("IDENTITY_MIGRATION_REMOTE_COLLISION")
        op["expected_remote_identity"] = current
    batches = [
        [op["operation_id"] for op in operations[index:index + batch_size]]
        for index in range(0, len(operations), batch_size)
    ]
    plan = {
        "plan_id": "", "plan_schema_version": IDENTITY_MIGRATION_PLAN_VERSION,
        "generated_at": _now_iso(), "direction": "identity_migration",
        "identity": {"workspace_id": workspace_id, "identity_version": 2,
                     "schema_state": "dual_read"},
        "source_snapshot": _migration_source_snapshot(conn, intents),
        "decision_digest": _canonical_json_digest(normalized_decisions),
        "decisions": normalized_decisions, "operations": operations,
        "batches": batches,
        "mutation_budget": {
            "sqlite": len(operations), "intent": len(target_by_scope),
            "notion": len(operations), "batch_size": batch_size,
        },
    }
    plan["plan_id"] = _migration_plan_id(plan)
    return plan


def validate_identity_migration_plan(plan, expected_plan_id=None):
    if not isinstance(plan, dict) or plan.get("direction") != "identity_migration":
        return False
    expected = expected_plan_id or plan.get("plan_id")
    if plan.get("plan_id") != expected or expected != _migration_plan_id(plan):
        return False
    operations = plan.get("operations")
    batches = plan.get("batches")
    if not isinstance(operations, list) or not isinstance(batches, list):
        return False
    ids = [op.get("operation_id") for op in operations]
    if len(ids) != len(set(ids)) or [item for batch in batches for item in batch] != ids:
        return False
    if any(not 1 <= len(batch) <= IDENTITY_MIGRATION_BATCH_SIZE for batch in batches):
        return False
    return True


def write_identity_migration_plan(path, plan):
    if not validate_identity_migration_plan(plan):
        raise ValueError("IDENTITY_MIGRATION_PLAN_INVALID")
    _atomic_json_write(path, plan)


def _ensure_identity_dual_read_schema(conn):
    additions = {
        "projects": (("workspace_id", "TEXT"), ("sync_uid", "TEXT"),
                     ("ownership_epoch", "INTEGER"), ("identity_version", "INTEGER")),
        "tasks": (("workspace_id", "TEXT"), ("project_sync_uid", "TEXT"),
                  ("project_ownership_epoch", "INTEGER"), ("identity_version", "INTEGER")),
    }
    for table, columns in additions.items():
        existing = _migration_table_columns(conn, table)
        for name, data_type in columns:
            if name not in existing:
                conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, data_type))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_sync_uid_v2 "
                 "ON projects(sync_uid) WHERE sync_uid IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project_uid_v2 "
                 "ON tasks(project_sync_uid) WHERE project_sync_uid IS NOT NULL")


def _migration_remote_upsert(remote, operation, projection):
    current = _migration_remote_identity(remote.read(operation["entity"], operation))
    if current == projection:
        return "unchanged"
    expected = operation.get("expected_remote_identity")
    if current != expected:
        raise ValueError("IDENTITY_MIGRATION_REMOTE_CAS_FAILED")
    remote.upsert(operation["entity"], operation, projection,
                  expected_current=expected)
    return "mutated"


def _migration_remote_identity(value):
    """Keep only the non-sensitive Identity projection in Plan/log state."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("IDENTITY_MIGRATION_REMOTE_IDENTITY_INVALID")
    return {key: value.get(key) for key in (
        "workspace_id", "project_sync_uid", "ownership_epoch", "identity_version"
    )}


def _migration_identity_update(conn, table, sql, params, row_id):
    """Apply one Identity update without allowing timestamp triggers to rewrite history."""
    trigger_name = "trg_%s_updated" % table
    trigger = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (trigger_name,),
    ).fetchone()
    updated_at = conn.execute(
        "SELECT updated_at FROM %s WHERE id=?" % table, (row_id,)
    ).fetchone()
    if trigger:
        conn.execute("DROP TRIGGER %s" % trigger_name)
    try:
        cursor = conn.execute(sql, params)
        if updated_at is not None:
            conn.execute("UPDATE %s SET updated_at=? WHERE id=?" % table,
                         (updated_at[0], row_id))
    finally:
        if trigger:
            conn.execute(trigger[0])
    return cursor


def _migration_local_identity(conn, operation):
    table = "projects" if operation["entity"] == "project" else "tasks"
    columns = _migration_table_columns(conn, table)
    names = (("workspace_id", "sync_uid", "ownership_epoch", "identity_version")
             if operation["entity"] == "project" else
             ("workspace_id", "project_sync_uid", "project_ownership_epoch",
              "identity_version"))
    if not set(names).issubset(columns):
        return (None, None, None, None)
    if operation["action"] == "create_from_intent":
        row = conn.execute(
            "SELECT %s FROM %s WHERE workspace_id=? AND scope_id=?" %
            (",".join(names), table),
            (operation.get("workspace_id"), operation["scope_id"]),
        ).fetchone()
        return tuple(row) if row else (None, None, None, None)
    row = conn.execute(
        "SELECT %s FROM %s WHERE id=?" % (",".join(names), table),
        (operation["row_id"],),
    ).fetchone()
    return tuple(row) if row else None


def _preflight_identity_migration_surfaces(conn, plan, remote, intents, state):
    completed = set(state.get("completed", []))
    remote_committed = set(state.get("remote_committed", []))
    workspace_id = plan["identity"]["workspace_id"]
    repaired_remote = set(remote_committed)
    repaired_completed = set(completed)
    for op in plan["operations"]:
        target = (workspace_id, op["project_sync_uid"], 1, 2)
        remote_target = {
            "workspace_id": workspace_id,
            "project_sync_uid": op["project_sync_uid"],
            "ownership_epoch": 1, "identity_version": 2,
        }
        current_remote = _migration_remote_identity(remote.read(op["entity"], op))
        expected_remote = op.get("expected_remote_identity")
        allowed_remote = ([remote_target] if op["operation_id"] in remote_committed
                          else [expected_remote, remote_target])
        if current_remote not in allowed_remote:
            raise ValueError("IDENTITY_MIGRATION_REMOTE_PREFLIGHT_COLLISION")
        if current_remote == remote_target:
            repaired_remote.add(op["operation_id"])
        local = _migration_local_identity(conn, op)
        allowed_local = {target} if op["operation_id"] in completed else {
            (None, None, None, None), target
        }
        if local not in allowed_local:
            raise ValueError("IDENTITY_MIGRATION_LOCAL_PREFLIGHT_COLLISION")
        if op["entity"] == "project":
            intent = intents.get(op["scope_id"])
            current_identity = intent.get("identity") if isinstance(intent, dict) else None
            current_identity = current_identity or {}
            target_intent = {"version": 2, "workspace_id": workspace_id,
                             "sync_uid": op["project_sync_uid"],
                             "ownership_epoch": 1}
            expected_intent = op.get("expected_intent_identity", {})
            allowed_intent = ([target_intent] if op["operation_id"] in completed
                              else [expected_intent, target_intent])
            if current_identity not in allowed_intent:
                raise ValueError("IDENTITY_MIGRATION_INTENT_PREFLIGHT_COLLISION")
            intent_converged = current_identity == target_intent
        else:
            intent_converged = True
        if current_remote == remote_target and local == target and intent_converged:
            repaired_completed.add(op["operation_id"])
    state["remote_committed"] = sorted(repaired_remote)
    state["completed"] = sorted(repaired_completed)


def execute_identity_migration_plan(conn, plan, remote, intents, *, state_path,
                                    expected_plan_id, intent_paths=None,
                                    fail_at=None):
    """Execute/resume one immutable Plan against injected local/remote surfaces."""
    if not validate_identity_migration_plan(plan, expected_plan_id):
        raise ValueError("IDENTITY_MIGRATION_PLAN_INVALID")
    state_exists = os.path.exists(os.fspath(state_path))
    if not state_exists and plan.get("source_snapshot") != _migration_source_snapshot(conn, intents):
        raise ValueError("IDENTITY_MIGRATION_SOURCE_SNAPSHOT_CHANGED")
    state = (_read_json_file(state_path) if state_exists else {
        "plan_id": plan["plan_id"], "state": "planned", "completed": [],
        "remote_committed": [], "batches": [], "uid_regenerations": 0,
    })
    if state.get("plan_id") != plan["plan_id"]:
        raise ValueError("IDENTITY_MIGRATION_STATE_PLAN_MISMATCH")
    _preflight_identity_migration_surfaces(conn, plan, remote, intents, state)
    completed = set(state.get("completed", []))
    remote_committed = set(state.get("remote_committed", []))
    operation_by_id = {op["operation_id"]: op for op in plan["operations"]}
    workspace_id = plan["identity"]["workspace_id"]
    state["state"] = "applying"
    _atomic_json_write(state_path, state)
    _ensure_identity_dual_read_schema(conn)
    conn.commit()

    for batch_index, batch in enumerate(plan["batches"]):
        for operation_id in batch:
            if operation_id in completed:
                continue
            op = operation_by_id[operation_id]
            projection = {
                "workspace_id": workspace_id,
                "project_sync_uid": op["project_sync_uid"],
                "ownership_epoch": 1, "identity_version": 2,
            }
            if operation_id not in remote_committed:
                _migration_remote_upsert(remote, op, projection)
                remote_committed.add(operation_id)
                state["remote_committed"] = sorted(remote_committed)
                _atomic_json_write(state_path, state)
                if fail_at == "after_remote_commit":
                    raise RuntimeError("injected migration failure: after_remote_commit")
            with conn:
                if op["entity"] == "project" and op["action"] == "create_from_intent":
                    row = conn.execute(
                        "SELECT id, sync_uid FROM projects WHERE workspace_id=? AND scope_id=?",
                        (workspace_id, op["scope_id"]),
                    ).fetchone()
                    if row is None:
                        conn.execute("""
                            INSERT INTO projects(scope_id,name,status,workspace_id,sync_uid,
                                                 ownership_epoch,identity_version)
                            VALUES(?,?,?,?,?,1,2)
                        """, (op["scope_id"], op["name"], op["status"], workspace_id,
                              op["project_sync_uid"]))
                    elif row[1] != op["project_sync_uid"]:
                        raise ValueError("IDENTITY_MIGRATION_LOCAL_CAS_FAILED")
                elif op["entity"] == "project":
                    cursor = _migration_identity_update(conn, "projects", """
                        UPDATE projects SET workspace_id=?,sync_uid=?,ownership_epoch=1,
                                            identity_version=2
                        WHERE id=? AND (sync_uid IS NULL OR sync_uid=?)
                    """, (workspace_id, op["project_sync_uid"], op["row_id"],
                          op["project_sync_uid"]), op["row_id"])
                    if cursor.rowcount != 1:
                        raise ValueError("IDENTITY_MIGRATION_LOCAL_CAS_FAILED")
                else:
                    cursor = _migration_identity_update(conn, "tasks", """
                        UPDATE tasks SET workspace_id=?,project_sync_uid=?,
                                         project_ownership_epoch=1,identity_version=2
                        WHERE id=? AND (project_sync_uid IS NULL OR project_sync_uid=?)
                    """, (workspace_id, op["project_sync_uid"], op["row_id"],
                          op["project_sync_uid"]), op["row_id"])
                    if cursor.rowcount != 1:
                        raise ValueError("IDENTITY_MIGRATION_LOCAL_CAS_FAILED")
            if op["entity"] == "project":
                if fail_at == "before_intent_projection":
                    raise RuntimeError("injected migration failure: before_intent_projection")
                intent = dict(intents[op["scope_id"]])
                existing_identity = intent.get("identity") or {}
                expected_identity = op.get("expected_intent_identity", {})
                target_identity = {
                    "version": 2, "workspace_id": workspace_id,
                    "sync_uid": op["project_sync_uid"], "ownership_epoch": 1,
                }
                if existing_identity not in (expected_identity, target_identity):
                    raise ValueError("IDENTITY_MIGRATION_INTENT_CAS_FAILED")
                intent["identity"] = target_identity
                intents[op["scope_id"]] = intent
                if intent_paths and op["scope_id"] in intent_paths:
                    _atomic_json_write(intent_paths[op["scope_id"]], intent)
                if fail_at == "after_intent_write_before_journal":
                    raise RuntimeError(
                        "injected migration failure: after_intent_write_before_journal"
                    )
            completed.add(operation_id)
            state["completed"] = sorted(completed)
            _atomic_json_write(state_path, state)
            if fail_at == "after_local_projection":
                raise RuntimeError("injected migration failure: after_local_projection")
        if batch not in state["batches"]:
            state["batches"].append(batch)
        _atomic_json_write(state_path, state)

    # Three-surface readback. Excluded rows must remain without v2 projection.
    for op in plan["operations"]:
        expected = {"workspace_id": workspace_id,
                    "project_sync_uid": op["project_sync_uid"],
                    "ownership_epoch": 1, "identity_version": 2}
        if _migration_remote_identity(remote.read(op["entity"], op)) != expected:
            raise ValueError("IDENTITY_MIGRATION_REMOTE_READBACK_FAILED")
        table = "projects" if op["entity"] == "project" else "tasks"
        identity_columns = (
            "workspace_id,sync_uid,ownership_epoch,identity_version"
            if op["entity"] == "project" else
            "workspace_id,project_sync_uid,project_ownership_epoch,identity_version"
        )
        if op["action"] == "create_from_intent":
            local = conn.execute(
                "SELECT %s FROM %s WHERE workspace_id=? AND scope_id=?" %
                (identity_columns, table), (workspace_id, op["scope_id"]),
            ).fetchone()
        else:
            local = conn.execute(
                "SELECT %s FROM %s WHERE id=?" % (identity_columns, table),
                (op["row_id"],),
            ).fetchone()
        expected_local = (workspace_id, op["project_sync_uid"], 1, 2)
        if local is None or tuple(local) != expected_local:
            raise ValueError("IDENTITY_MIGRATION_SQLITE_READBACK_FAILED")
        if op.get("preservation_digest"):
            available = _migration_table_columns(conn, table)
            preservation_columns = [name for name in (
                "notion_page_id", "created_at", "updated_at", "last_sync_at"
            ) if name in available]
            cursor = conn.execute(
                "SELECT %s FROM %s WHERE id=?" %
                (",".join(preservation_columns), table), (op["row_id"],)
            )
            names = [item[0] for item in cursor.description]
            preserved = dict(zip(names, cursor.fetchone()))
            if _migration_preservation_digest(preserved) != op["preservation_digest"]:
                raise ValueError("IDENTITY_MIGRATION_PRESERVATION_READBACK_FAILED")
    for decision in plan["decisions"]:
        if decision["decision"] == "legacy_excluded":
            scope_id, task_id = decision["routing_key"].split("/", 1)
            row = conn.execute(
                "SELECT project_sync_uid FROM tasks WHERE scope_id=? AND task_id=?",
                (scope_id, task_id),
            ).fetchone()
            if row is None or row[0] is not None:
                raise ValueError("IDENTITY_MIGRATION_EXCLUSION_FENCE_FAILED")
    for op in plan["operations"]:
        if op["entity"] == "project":
            intent = intents.get(op["scope_id"], {})
            identity = intent.get("identity") or {}
            if (identity.get("workspace_id") != workspace_id
                    or identity.get("sync_uid") != op["project_sync_uid"]
                    or identity.get("version") != 2
                    or identity.get("ownership_epoch") != 1):
                raise ValueError("IDENTITY_MIGRATION_INTENT_READBACK_FAILED")
    state.update({"state": "verified", "verified_at": _now_iso(),
                  "residual_operations": 0})
    _atomic_json_write(state_path, state)
    return state


class _FixtureMigrationRemote:
    """Durable file-backed remote used only by the T006 disposable CLI."""

    def __init__(self, path):
        self.path = os.fspath(path)
        self.rows = _read_json_file(self.path) if os.path.exists(self.path) else {}

    def read(self, entity, operation):
        value = self.rows.get(operation["operation_id"])
        return json.loads(json.dumps(value)) if value is not None else None

    def upsert(self, entity, operation, projection, expected_current=None):
        if self.rows.get(operation["operation_id"]) != expected_current:
            raise ValueError("IDENTITY_MIGRATION_REMOTE_CAS_FAILED")
        self.rows[operation["operation_id"]] = projection
        _atomic_json_write(self.path, self.rows)


def _migration_fixture_paths(root):
    root = os.path.abspath(os.fspath(root))
    marker = os.path.join(root, ".identity-migration-fixture")
    database = os.path.join(root, "ai_plc.db")
    if not os.path.isfile(marker):
        raise ValueError("IDENTITY_MIGRATION_FIXTURE_MARKER_REQUIRED")
    # 本体の DB（DB_PATH）も、この作業ツリーの DB（worktree の写し）も守る
    for production in (DB_PATH, os.path.join(SCRIPT_DB_DIR, "ai_plc.db")):
        if (os.path.realpath(database) == os.path.realpath(production)
                or (os.path.exists(database) and os.path.exists(production)
                    and os.path.samefile(database, production))):
            raise ValueError("IDENTITY_MIGRATION_PRODUCTION_DB_FORBIDDEN")
    return root, database, os.path.join(root, "remote.json")


def _load_fixture_intents(root):
    aggregate_path = os.path.join(root, "intents.json")
    intents = _read_json_file(aggregate_path)
    paths = {}
    for scope_id in list(intents):
        path = os.path.join(root, "intents", scope_id, "intent.yaml")
        paths[scope_id] = path
        if os.path.exists(path):
            intents[scope_id] = _read_json_file(path)
    return intents, paths, aggregate_path


def cmd_migrate_identity(options):
    """Run the complete CLI contract against an explicitly marked fixture only."""
    try:
        plan_path = options.get("--plan")
        state_path = options.get("--state") or (
            (plan_path + ".state.json") if plan_path else None
        )
        if options.get("--status"):
            plan = _read_json_file(plan_path)
            if not validate_identity_migration_plan(plan):
                raise ValueError("IDENTITY_MIGRATION_PLAN_INVALID")
            state = (_read_json_file(state_path) if state_path and os.path.exists(state_path)
                     else {"plan_id": plan["plan_id"], "state": "planned",
                           "completed": [], "residual_operations": len(plan["operations"])})
            if state.get("plan_id") != plan["plan_id"]:
                raise ValueError("IDENTITY_MIGRATION_STATE_PLAN_MISMATCH")
            print(json.dumps({
                "plan_id": plan["plan_id"], "state": state.get("state"),
                "completed": len(state.get("completed", [])),
                "total": len(plan["operations"]),
                "residual_operations": (len(plan["operations"])
                                        - len(state.get("completed", []))),
            }, ensure_ascii=False, sort_keys=True))
            return 0

        root, database, remote_path = _migration_fixture_paths(
            options.get("--fixture-root")
        )
        intents, intent_paths, aggregate_path = _load_fixture_intents(root)
        remote = _FixtureMigrationRemote(remote_path)
        if options.get("--dry-run"):
            decision_artifact = _read_json_file(options["--decisions"])
            with sqlite3.connect("file:%s?mode=ro" % database, uri=True) as conn:
                plan = build_identity_migration_plan(
                    conn, decision_artifact["workspace_id"],
                    decision_artifact["decisions"], intents,
                    project_uid_mappings=decision_artifact.get("project_uid_mappings"),
                    remote=remote,
                    batch_size=decision_artifact.get("batch_size", 10),
                )
            write_identity_migration_plan(options["--plan-out"], plan)
            print(json.dumps({"plan_id": plan["plan_id"], "state": "planned",
                              "operations": len(plan["operations"]),
                              "batches": [len(batch) for batch in plan["batches"]]},
                             ensure_ascii=False, sort_keys=True))
            return 0

        plan = _read_json_file(plan_path)
        with sqlite3.connect(database) as conn:
            result = execute_identity_migration_plan(
                conn, plan, remote, intents, state_path=state_path,
                expected_plan_id=options["--plan-id"], intent_paths=intent_paths,
            )
        _atomic_json_write(aggregate_path, intents)
        print(json.dumps({"plan_id": plan["plan_id"], "state": result["state"],
                          "residual_operations": result["residual_operations"]},
                         ensure_ascii=False, sort_keys=True))
        return 0
    except (KeyError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        print("ERROR: %s" % exc)
        return 3


# ── Identity v2.0 adopt-existing: local manifest without Authority (T011) ──
#
# Adopts the already-operating v1 SQLite registry as the current workspace:
# one fixed Plan issues the workspace_id and every Project UID exactly once,
# the orphan adjudication (fixed_mapping / legacy_excluded) is part of the
# Plan hash, and execution only touches Local surfaces (SQLite dual_read
# projection -> manifest -> active cache).  No IdentityAuthorityStore,
# ApprovalStore, WriterProof, Notion, or intent.yaml access happens here;
# Notion/intent projection stays with migrate-identity (T009 adapter).

ADOPT_EXISTING_PLAN_VERSION = 1
ADOPT_DECISIONS_VERSION = 1
ADOPT_PROJECT_STATUSES = ("planned", "active", "completed", "paused")
ADOPT_STATES = ("planned", "checkpointed", "rows_committed",
                "manifest_committed", "cache_committed", "verified")
ADOPT_PLAN_KEYS = {
    "plan_id", "plan_schema_version", "direction", "identity_version",
    "schema_target", "source", "workspace", "decision_digest", "decisions",
    "decision_counts", "projects", "new_projects", "tasks", "excluded_tasks",
    "mutation_budget", "authority", "notion", "intent",
}
ADOPT_MARKER_KEY = "identity_adopt_plan_id"
EVIDENCE_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
INTENT_SCOPE_LINE_PATTERN = re.compile(
    r"""^scope_id:[ \t]*(?:"([^"\n]*)"|'([^'\n]*)'|([^\s#'"][^\s#]*))"""
    r"""[ \t]*(?:#[^\n]*)?[ \t]*$""", re.M)


def _adopt_meta(conn, key):
    row = conn.execute("SELECT value FROM _metadata WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def _adopt_cache(conn):
    return {key: _adopt_meta(conn, key) for key in (
        "active_workspace_id", "active_writer_epoch", "writer_authority_hash_cache")}


def _adopt_legacy_rows(conn, table, exclude_ids=()):
    """Legacy (non-Identity) columns of every row: the preservation surface."""
    columns = sorted(column for column in _migration_table_columns(conn, table)
                     if column not in LOCAL_IDENTITY_COLUMNS[table])
    id_index = columns.index("id")
    excluded = set(exclude_ids)
    rows = [list(row) for row in conn.execute(
        "SELECT %s FROM %s ORDER BY id" % (",".join(columns), table)).fetchall()
        if row[id_index] not in excluded]
    return {"columns": columns, "rows": rows}


def _adopt_source(conn, exclude_project_ids=()):
    projects = _adopt_legacy_rows(conn, "projects", exclude_project_ids)
    tasks = _adopt_legacy_rows(conn, "tasks")
    return {
        "rows_digest": _canonical_json_digest({"projects": projects, "tasks": tasks}),
        "project_count": len(projects["rows"]),
        "task_count": len(tasks["rows"]),
    }


def _adopt_schema_digest(conn):
    rows = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE tbl_name IN ('projects', 'tasks') ORDER BY type, name").fetchall()
    return _canonical_json_digest([list(row) for row in rows])


def _adopt_quick_check(conn):
    return conn.execute("PRAGMA quick_check").fetchone()[0]


def _adopt_decision_digest(decisions):
    """Digest of the human adjudication (paths excluded; evidence covers content)."""
    return _canonical_json_digest(sorted((
        {key: item.get(key) for key in (
            "routing_key", "decision", "evidence_digest", "project_name",
            "project_status")}
        for item in decisions), key=lambda item: item["routing_key"]))


def load_adopt_decisions(path):
    """Strictly parse the Mob-approved orphan adjudication artifact."""
    try:
        artifact = _read_json_file(path)
    except (OSError, ValueError, json.JSONDecodeError):
        raise IdentityLifecycleError("ADOPT_DECISIONS_INVALID", 2)
    if (not isinstance(artifact, dict)
            or set(artifact) != {"adopt_decisions_version", "decisions"}
            or artifact["adopt_decisions_version"] != ADOPT_DECISIONS_VERSION
            or not isinstance(artifact["decisions"], list)):
        raise IdentityLifecycleError("ADOPT_DECISIONS_INVALID", 2)
    return artifact["decisions"]


def _adopt_intent_evidence(intent_path, base_dir, scope_id):
    """sha256 of the exact intent file whose top-level scope_id equals scope_id."""
    if not isinstance(intent_path, str) or not intent_path:
        raise IdentityLifecycleError("ADOPT_EXACT_INTENT_REQUIRED", 2)
    path = (intent_path if os.path.isabs(intent_path)
            else os.path.join(base_dir, intent_path))
    try:
        with open(path, "rb") as handle:
            payload = handle.read()
        text = payload.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise IdentityLifecycleError("ADOPT_EXACT_INTENT_REQUIRED", 2)
    values = [next(group for group in match.groups() if group is not None)
              for match in INTENT_SCOPE_LINE_PATTERN.finditer(text)]
    if values != [scope_id]:
        raise IdentityLifecycleError("ADOPT_EXACT_INTENT_REQUIRED", 2)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _adopt_normalize_decisions(inventory, decisions, decisions_base):
    """Validate the adjudication against the orphan inventory (no Identity issued)."""
    by_key = {}
    duplicate = False
    for item in decisions:
        if not isinstance(item, dict):
            raise IdentityLifecycleError("ADOPT_DECISION_INVALID", 2)
        kind = item.get("decision")
        allowed = {"routing_key", "decision", "evidence_digest"}
        if kind == "fixed_mapping":
            allowed |= {"intent_path", "project_name", "project_status"}
        if kind not in IDENTITY_MIGRATION_DECISIONS or set(item) != allowed:
            raise IdentityLifecycleError("ADOPT_DECISION_INVALID", 2)
        if not isinstance(item["routing_key"], str):
            raise IdentityLifecycleError("ADOPT_DECISION_INVALID", 2)
        duplicate = duplicate or item["routing_key"] in by_key
        by_key[item["routing_key"]] = item
    expected = {orphan["routing_key"] for orphan in inventory["orphans"]}
    # §12.1: an unresolved orphan is an integrity failure (3) and wins over 2.
    if expected - set(by_key):
        raise IdentityLifecycleError("ADOPT_ADJUDICATION_INCOMPLETE", 3)
    if duplicate:
        raise IdentityLifecycleError("ADOPT_DUPLICATE_DECISION", 2)
    if set(by_key) - expected:
        raise IdentityLifecycleError("ADOPT_DECISION_NOT_ORPHAN", 2)
    # One Scope gets one adjudication: a mapped Project would silently adopt
    # an "excluded" sibling Task later (T006 would no longer see it as orphan).
    kinds_by_scope = {}
    for orphan in inventory["orphans"]:
        kinds_by_scope.setdefault(orphan["scope_id"], set()).add(
            by_key[orphan["routing_key"]]["decision"])
    if any(len(kinds) > 1 for kinds in kinds_by_scope.values()):
        raise IdentityLifecycleError("ADOPT_DECISION_CONFLICT", 2)
    new_projects = {}
    for orphan in inventory["orphans"]:
        item = by_key[orphan["routing_key"]]
        if not isinstance(item["evidence_digest"], str) or not (
                EVIDENCE_DIGEST_PATTERN.fullmatch(item["evidence_digest"])):
            raise IdentityLifecycleError("ADOPT_EVIDENCE_REQUIRED", 2)
        if item["decision"] != "fixed_mapping":
            continue
        name, status = item["project_name"], item["project_status"]
        if (not isinstance(name, str) or not name.strip()
                or status not in ADOPT_PROJECT_STATUSES):
            raise IdentityLifecycleError("ADOPT_DECISION_INVALID", 2)
        spec = {"intent_path": item["intent_path"],
                "evidence_digest": item["evidence_digest"],
                "name": name, "status": status}
        prior = new_projects.get(orphan["scope_id"])
        if prior is not None:
            if prior != spec:
                raise IdentityLifecycleError("ADOPT_DECISION_CONFLICT", 2)
            continue
        if _adopt_intent_evidence(item["intent_path"], decisions_base,
                                  orphan["scope_id"]) != item["evidence_digest"]:
            raise IdentityLifecycleError("ADOPT_EVIDENCE_MISMATCH", 2)
        new_projects[orphan["scope_id"]] = spec
    return by_key, new_projects


def _adopt_preconditions(conn, manifest_path):
    if _local_identity_schema_version(conn) != 1:
        raise IdentityLifecycleError("ADOPT_REQUIRES_V1_SCHEMA", 3)
    if os.path.exists(manifest_path):
        raise IdentityLifecycleError("ADOPT_MANIFEST_EXISTS", 3)
    if any(value is not None for value in _adopt_cache(conn).values()):
        raise IdentityLifecycleError("ADOPT_ACTIVE_CACHE_EXISTS", 3)
    if _adopt_meta(conn, ADOPT_MARKER_KEY) is not None:
        raise IdentityLifecycleError("ADOPT_FOREIGN_PROJECTION", 3)
    if _pending_journal_count(conn):
        raise IdentityLifecycleError("PENDING_JOURNAL_BLOCKS_ADOPT", 3)


def build_adopt_existing_plan(conn, *, writer_id, decisions, decisions_base=".",
                              identity_factory=None, manifest_path=None):
    """Fix workspace_id, every Project UID and the orphan adjudication once.

    The Plan file is the durable mapping (T001 §4.2/§10.1): it is written
    before any mutation and reused on rerun, so no Identity is ever
    re-issued.  Read-only; the caller persists the Plan.
    """
    if not isinstance(writer_id, str) or not WRITER_ID_PATTERN.fullmatch(writer_id):
        raise IdentityLifecycleError("ADOPT_WRITER_ID_INVALID", 64)
    manifest_path = os.fspath(manifest_path or WORKSPACE_MANIFEST_PATH)
    _adopt_preconditions(conn, manifest_path)
    inventory = identity_migration_inventory(conn)
    by_key, new_specs = _adopt_normalize_decisions(
        inventory, decisions, decisions_base)
    issued = set()

    def issue_project_uid():
        uid = _new_project_sync_uid(identity_factory)
        if uid in issued:
            raise IdentityLifecycleError("ADOPT_UID_COLLISION", 2)
        issued.add(uid)
        return uid

    workspace_id = _new_workspace_id(identity_factory)
    projects = [{"row_id": row[0], "scope_id": row[1],
                 "sync_uid": issue_project_uid()}
                for row in conn.execute(
                    "SELECT id, scope_id FROM projects ORDER BY id").fetchall()]
    new_projects = [{"scope_id": scope_id, "sync_uid": issue_project_uid(),
                     "name": spec["name"], "status": spec["status"],
                     "intent_digest": spec["evidence_digest"]}
                    for scope_id, spec in sorted(new_specs.items())]
    uid_by_scope = {item["scope_id"]: item["sync_uid"]
                    for item in projects + new_projects}
    tasks, excluded = [], []
    for row_id, scope_id, task_id in conn.execute(
            "SELECT id, scope_id, task_id FROM tasks ORDER BY id").fetchall():
        routing_key = "%s/%s" % (scope_id, task_id)
        decision = by_key.get(routing_key)
        if decision is not None and decision["decision"] == "legacy_excluded":
            excluded.append({"row_id": row_id, "routing_key": routing_key})
            continue
        uid = uid_by_scope.get(scope_id)
        if uid is None:
            raise IdentityLifecycleError("ADOPT_TASK_PARENT_MISSING", 3)
        tasks.append({"row_id": row_id, "scope_id": scope_id, "task_id": task_id,
                      "project_sync_uid": uid})
    normalized = []
    for routing_key in sorted(by_key):
        item = by_key[routing_key]
        entry = {"routing_key": routing_key, "decision": item["decision"],
                 "evidence_digest": item["evidence_digest"]}
        if item["decision"] == "fixed_mapping":
            entry["project_sync_uid"] = uid_by_scope[routing_key.split("/", 1)[0]]
        normalized.append(entry)
    manifest = _writer_manifest(workspace_id, writer_id)
    plan = {
        "plan_schema_version": ADOPT_EXISTING_PLAN_VERSION,
        "direction": "workspace_adopt_existing",
        "identity_version": 2,
        "schema_target": "dual_read",
        "source": dict(_adopt_source(conn),
                       schema_digest=_adopt_schema_digest(conn),
                       orphan_count=len(inventory["orphans"])),
        "workspace": {
            "workspace_id": workspace_id, "writer_id": writer_id,
            "writer_epoch": 1,
            "writer_authority_hash": manifest["writer_authority_hash_cache"],
        },
        "decision_digest": _adopt_decision_digest(decisions),
        "decisions": normalized,
        "decision_counts": {
            kind: sum(1 for item in normalized if item["decision"] == kind)
            for kind in sorted(IDENTITY_MIGRATION_DECISIONS)},
        "projects": projects,
        "new_projects": new_projects,
        "tasks": tasks,
        "excluded_tasks": excluded,
        "mutation_budget": {
            "sqlite_project_updates": len(projects),
            "sqlite_project_inserts": len(new_projects),
            "sqlite_task_updates": len(tasks),
            "sqlite_excluded_rows": 0,
            "manifest_writes": 1, "cache_writes": 1,
            "notion": 0, "authority": 0, "intent": 0,
        },
        "authority": "deferred_v2_1",
        "notion": "not_touched",
        "intent": "deferred_to_migrate_identity",
    }
    plan["plan_id"] = _fork_plan_id(plan)
    return plan


def validate_adopt_existing_plan(plan, expected_plan_id=None):
    """Structural + hash validation; any tampering (incl. exclusions) fails."""
    if not isinstance(plan, dict) or set(plan) != ADOPT_PLAN_KEYS:
        return False
    try:
        if (plan["plan_schema_version"] != ADOPT_EXISTING_PLAN_VERSION
                or plan["direction"] != "workspace_adopt_existing"
                or plan["identity_version"] != 2
                or plan["schema_target"] != "dual_read"
                or plan["authority"] != "deferred_v2_1"
                or plan["notion"] != "not_touched"
                or plan["intent"] != "deferred_to_migrate_identity"):
            return False
        if plan["plan_id"] != _fork_plan_id(plan):
            return False
        if expected_plan_id is not None and expected_plan_id != plan["plan_id"]:
            return False
        workspace = plan["workspace"]
        if (not WORKSPACE_ID_PATTERN.fullmatch(workspace["workspace_id"])
                or not WRITER_ID_PATTERN.fullmatch(workspace["writer_id"])
                or workspace["writer_epoch"] != 1
                or workspace["writer_authority_hash"] != _writer_manifest(
                    workspace["workspace_id"], workspace["writer_id"]
                )["writer_authority_hash_cache"]):
            return False
        uids, scopes = set(), set()
        for item in plan["projects"] + plan["new_projects"]:
            if (not PROJECT_UID_PATTERN.fullmatch(item["sync_uid"])
                    or item["sync_uid"] in uids or item["scope_id"] in scopes):
                return False
            uids.add(item["sync_uid"])
            scopes.add(item["scope_id"])
        for item in plan["new_projects"]:
            if (item["status"] not in ADOPT_PROJECT_STATUSES
                    or not isinstance(item["name"], str) or not item["name"].strip()
                    or not EVIDENCE_DIGEST_PATTERN.fullmatch(item["intent_digest"])):
                return False
        project_row_ids = [item["row_id"] for item in plan["projects"]]
        task_row_ids = [item["row_id"] for item in plan["tasks"]]
        excluded_row_ids = [item["row_id"] for item in plan["excluded_tasks"]]
        if (len(set(project_row_ids)) != len(project_row_ids)
                or len(set(task_row_ids + excluded_row_ids))
                != len(task_row_ids) + len(excluded_row_ids)):
            return False
        uid_by_scope = {item["scope_id"]: item["sync_uid"]
                        for item in plan["projects"] + plan["new_projects"]}
        if any(uid_by_scope.get(item["scope_id"]) != item["project_sync_uid"]
               for item in plan["tasks"]):
            return False
        # An excluded orphan's Scope must stay Project-less, otherwise a later
        # migration would adopt it as an ordinary Task of that Project.
        if any(item["routing_key"].split("/", 1)[0] in uid_by_scope
               for item in plan["excluded_tasks"]):
            return False
        source = plan["source"]
        if (source["project_count"] != len(plan["projects"])
                or source["task_count"] != len(task_row_ids) + len(excluded_row_ids)
                or source["orphan_count"] != len(plan["decisions"])):
            return False
        decisions = {item["routing_key"]: item for item in plan["decisions"]}
        if len(decisions) != len(plan["decisions"]):
            return False
        excluded_keys = {item["routing_key"] for item in plan["excluded_tasks"]}
        if excluded_keys != {key for key, item in decisions.items()
                             if item["decision"] == "legacy_excluded"}:
            return False
        if len(excluded_keys) != len(plan["excluded_tasks"]):
            return False
        new_uids = {item["scope_id"]: item["sync_uid"] for item in plan["new_projects"]}
        task_keys = {"%s/%s" % (item["scope_id"], item["task_id"]): item
                     for item in plan["tasks"]}
        for key, item in decisions.items():
            if (item["decision"] not in IDENTITY_MIGRATION_DECISIONS
                    or not EVIDENCE_DIGEST_PATTERN.fullmatch(item["evidence_digest"])):
                return False
            if item["decision"] == "fixed_mapping":
                scope_id = key.split("/", 1)[0]
                if (new_uids.get(scope_id) != item.get("project_sync_uid")
                        or key not in task_keys):
                    return False
            elif "project_sync_uid" in item or key in task_keys:
                return False
        if set(new_uids) != {key.split("/", 1)[0] for key, item in decisions.items()
                             if item["decision"] == "fixed_mapping"}:
            return False
        if plan["decision_counts"] != {
                kind: sum(1 for item in plan["decisions"] if item["decision"] == kind)
                for kind in sorted(IDENTITY_MIGRATION_DECISIONS)}:
            return False
        return plan["mutation_budget"] == {
            "sqlite_project_updates": len(plan["projects"]),
            "sqlite_project_inserts": len(plan["new_projects"]),
            "sqlite_task_updates": len(plan["tasks"]),
            "sqlite_excluded_rows": 0,
            "manifest_writes": 1, "cache_writes": 1,
            "notion": 0, "authority": 0, "intent": 0,
        }
    except (KeyError, TypeError, AttributeError, IndexError):
        return False


def _adopt_verify_source(conn, plan):
    """Pre-mutation fence: still the exact v1 source the Plan was built from."""
    if _local_identity_schema_version(conn) != 1:
        raise IdentityLifecycleError("ADOPT_REQUIRES_V1_SCHEMA", 3)
    if _adopt_schema_digest(conn) != plan["source"]["schema_digest"]:
        raise IdentityLifecycleError("ADOPT_SOURCE_CHANGED", 2)
    if _adopt_source(conn)["rows_digest"] != plan["source"]["rows_digest"]:
        raise IdentityLifecycleError("ADOPT_SOURCE_CHANGED", 2)


def _adopt_default_checkpoint_path(conn, plan):
    """Keep the full SQLite copy next to the adopted DB (never next to a Plan
    that may live in a tracked Flow folder); ``*.db`` there is git-ignored."""
    main = next((row[2] for row in conn.execute("PRAGMA database_list").fetchall()
                 if row[1] == "main" and row[2]), None)
    directory = os.path.dirname(os.path.abspath(main or DB_PATH))
    digest = plan["plan_id"].split(":", 1)[-1][:16]
    return os.path.join(directory, "identity_adopt_checkpoint_%s.db" % digest)


def _adopt_take_checkpoint(conn, plan, checkpoint_path):
    """Maintenance checkpoint: a verified SQLite backup of the planned source."""
    temporary = checkpoint_path + ".tmp.db"
    if os.path.exists(temporary):
        os.unlink(temporary)
    target = sqlite3.connect(temporary)
    try:
        conn.backup(target)
        quick_check = _adopt_quick_check(target)
        source = _adopt_source(target)
        schema_digest = _adopt_schema_digest(target)
    finally:
        target.close()
    if (quick_check != "ok" or source["rows_digest"] != plan["source"]["rows_digest"]
            or schema_digest != plan["source"]["schema_digest"]):
        os.unlink(temporary)
        raise IdentityLifecycleError("ADOPT_CHECKPOINT_MISMATCH", 3)
    with open(temporary, "r+b") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
        os.fsync(handle.fileno())
    os.replace(temporary, checkpoint_path)
    return {"sha256": digest, "rows_digest": source["rows_digest"],
            "quick_check": quick_check}


def _adopt_apply_projection(conn, plan):
    """One transaction: dual_read columns, Identity backfill, new Projects, marker."""
    workspace_id = plan["workspace"]["workspace_id"]
    triggers = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' "
        "AND tbl_name IN ('projects', 'tasks') ORDER BY name").fetchall()
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Re-check under the write lock: nothing changed since the checkpoint
        # (a concurrent executor that committed first is refused, not merged).
        if _adopt_meta(conn, ADOPT_MARKER_KEY) is not None:
            raise IdentityLifecycleError("ADOPT_CONCURRENT_PROJECTION", 3)
        _adopt_verify_source(conn, plan)
        _ensure_identity_dual_read_schema(conn)
        # Timestamp triggers would rewrite updated_at (dirtying every row);
        # they are restored verbatim inside the same transaction.
        for name, _sql in triggers:
            conn.execute("DROP TRIGGER %s" % json.dumps(name))
        for item in plan["projects"]:
            cursor = conn.execute(
                "UPDATE projects SET workspace_id=?, sync_uid=?, ownership_epoch=1, "
                "identity_version=2 WHERE id=? AND scope_id=? AND sync_uid IS NULL",
                (workspace_id, item["sync_uid"], item["row_id"], item["scope_id"]))
            if cursor.rowcount != 1:
                raise IdentityLifecycleError("ADOPT_LOCAL_CAS_FAILED", 3)
        for item in plan["new_projects"]:
            conn.execute(
                "INSERT INTO projects (scope_id, name, status, workspace_id, sync_uid, "
                "ownership_epoch, identity_version) VALUES (?, ?, ?, ?, ?, 1, 2)",
                (item["scope_id"], item["name"], item["status"], workspace_id,
                 item["sync_uid"]))
        for item in plan["tasks"]:
            cursor = conn.execute(
                "UPDATE tasks SET workspace_id=?, project_sync_uid=?, "
                "project_ownership_epoch=1, identity_version=2 "
                "WHERE id=? AND scope_id=? AND task_id=? AND project_sync_uid IS NULL",
                (workspace_id, item["project_sync_uid"], item["row_id"],
                 item["scope_id"], item["task_id"]))
            if cursor.rowcount != 1:
                raise IdentityLifecycleError("ADOPT_LOCAL_CAS_FAILED", 3)
        for _name, sql in triggers:
            conn.execute(sql)
        conn.execute("INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
                     (ADOPT_MARKER_KEY, plan["plan_id"]))
        if _adopt_quick_check(conn) != "ok":
            raise IdentityLifecycleError("ADOPT_QUICK_CHECK_FAILED", 3)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return (len(plan["projects"]) + len(plan["new_projects"]) + len(plan["tasks"]))


def _adopt_rows_readback(conn, plan, *, preservation=True):
    """Read back every planned Identity; excluded rows stay Identity-less."""
    if _local_identity_schema_version(conn) != 2:
        return ["SCHEMA_NOT_DUAL_READ"]
    if _adopt_meta(conn, ADOPT_MARKER_KEY) != plan["plan_id"]:
        return ["ADOPT_MARKER_MISMATCH"]
    workspace_id = plan["workspace"]["workspace_id"]
    failures = []
    for item in plan["projects"]:
        row = conn.execute(
            "SELECT scope_id, workspace_id, sync_uid, ownership_epoch, identity_version "
            "FROM projects WHERE id=?", (item["row_id"],)).fetchone()
        if row is None or tuple(row) != (item["scope_id"], workspace_id,
                                         item["sync_uid"], 1, 2):
            failures.append("PROJECT_IDENTITY")
    new_ids = []
    for item in plan["new_projects"]:
        rows = conn.execute(
            "SELECT id, name, status, workspace_id, sync_uid, ownership_epoch, "
            "identity_version FROM projects WHERE scope_id=?",
            (item["scope_id"],)).fetchall()
        if len(rows) != 1 or tuple(rows[0])[1:] != (
                item["name"], item["status"], workspace_id, item["sync_uid"], 1, 2):
            failures.append("NEW_PROJECT_IDENTITY")
            continue
        new_ids.append(rows[0][0])
    for item in plan["tasks"]:
        row = conn.execute(
            "SELECT scope_id, task_id, workspace_id, project_sync_uid, "
            "project_ownership_epoch, identity_version FROM tasks WHERE id=?",
            (item["row_id"],)).fetchone()
        if row is None or tuple(row) != (item["scope_id"], item["task_id"],
                                         workspace_id, item["project_sync_uid"], 1, 2):
            failures.append("TASK_IDENTITY")
    for item in plan["excluded_tasks"]:
        row = conn.execute(
            "SELECT workspace_id, project_sync_uid, project_ownership_epoch, "
            "identity_version FROM tasks WHERE id=?", (item["row_id"],)).fetchone()
        if row is None or any(value is not None for value in row):
            failures.append("EXCLUSION_FENCE")
    if preservation and not failures:
        source = _adopt_source(conn, exclude_project_ids=new_ids)
        if (source["rows_digest"] != plan["source"]["rows_digest"]
                or source["project_count"] != plan["source"]["project_count"]
                or source["task_count"] != plan["source"]["task_count"]):
            failures.append("PRESERVATION")
    return failures


def _adopt_write_state(state_path, state, lifecycle, **fields):
    state = dict(state, state=lifecycle, **fields)
    _atomic_json_write(state_path, state)
    return state


def execute_adopt_existing_plan(conn, plan, *, expected_plan_id, state_path,
                                checkpoint_path=None, manifest_path=None,
                                fail_at=None):
    """Apply/resume one fixed adopt Plan: rows -> manifest -> cache -> verify.

    Never issues an Identity (every value comes from the Plan), never touches
    Notion, intent.yaml, or any Authority/Approval store.
    """
    if not validate_adopt_existing_plan(plan, expected_plan_id):
        raise IdentityLifecycleError("ADOPT_PLAN_INVALID", 2)
    manifest_path = os.fspath(manifest_path or WORKSPACE_MANIFEST_PATH)
    state_path = os.fspath(state_path)
    checkpoint_path = os.fspath(
        checkpoint_path or _adopt_default_checkpoint_path(conn, plan))
    state = _read_json_file(state_path) if os.path.exists(state_path) else None
    if state is not None and (state.get("plan_id") != plan["plan_id"]
                              or state.get("state") not in ADOPT_STATES):
        raise IdentityLifecycleError("ADOPT_STATE_PLAN_MISMATCH", 2)
    workspace = plan["workspace"]
    result = {"plan_id": plan["plan_id"], "workspace_id": workspace["workspace_id"],
              "rows_projected": 0, "manifest_written": 0, "cache_written": 0}
    target = _writer_manifest(workspace["workspace_id"], workspace["writer_id"])
    if state is not None and state["state"] == "verified":
        # Terminal: rows may legitimately evolve after adoption; a rerun is a
        # no-op and never re-issues the manifest or any UID -- but it must not
        # report success while the adopted manifest/cache no longer agree.
        try:
            resolved = resolve_workspace_identity(conn, manifest_path=manifest_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            resolved = None
        if resolved != target:
            raise IdentityLifecycleError("WORKSPACE_IDENTITY_SPLIT_BRAIN", 3)
        return dict(result, state="verified", noop=True)
    target_cache = _cache_for_manifest(target)
    current = (_read_json_file(manifest_path)
               if os.path.exists(manifest_path) else None)
    if current is not None and current != target:
        # Another workspace/writer already owns this Repository: replacing it
        # would be a takeover (v2.1).
        raise IdentityLifecycleError("ADOPT_MANIFEST_CONFLICT", 3)
    cache = _adopt_cache(conn)
    if cache != target_cache and any(value is not None for value in cache.values()):
        raise IdentityLifecycleError("WORKSPACE_IDENTITY_SPLIT_BRAIN", 3)
    if cache == target_cache and current != target:
        raise IdentityLifecycleError("WORKSPACE_IDENTITY_SPLIT_BRAIN", 3)
    marker = _adopt_meta(conn, ADOPT_MARKER_KEY)
    if marker not in (None, plan["plan_id"]):
        raise IdentityLifecycleError("ADOPT_FOREIGN_PROJECTION", 3)
    if marker is None and current is not None:
        raise IdentityLifecycleError("ADOPT_MANIFEST_WITHOUT_PROJECTION", 3)
    if _pending_journal_count(conn):
        raise IdentityLifecycleError("PENDING_JOURNAL_BLOCKS_ADOPT", 3)

    if marker is None:
        _adopt_verify_source(conn, plan)
        if _adopt_quick_check(conn) != "ok":
            raise IdentityLifecycleError("ADOPT_QUICK_CHECK_FAILED", 3)
        if state is None:
            state = _adopt_write_state(state_path, {"plan_id": plan["plan_id"]},
                                       "planned", checkpoint_path=checkpoint_path)
        _identity_failpoint(fail_at, "after_planned")
        if (state["state"] == "planned" or not os.path.exists(checkpoint_path)):
            checkpoint = _adopt_take_checkpoint(conn, plan, checkpoint_path)
            state = _adopt_write_state(state_path, state, "checkpointed",
                                       checkpoint=checkpoint)
        _identity_failpoint(fail_at, "after_checkpoint")
        result["rows_projected"] = _adopt_apply_projection(conn, plan)
        _identity_failpoint(fail_at, "after_rows_commit")
    try:
        # Legacy bytes are compared only while the workspace cannot be live
        # yet (before the manifest step).  Once manifest/cache may be active,
        # or the state was lost, pull/push may legitimately have changed rows,
        # so only the Identity projection is re-verified on resume.
        preservation = state is not None and state["state"] in {
            "planned", "checkpointed", "rows_committed"}
        if _adopt_rows_readback(conn, plan, preservation=preservation):
            raise IdentityLifecycleError("ADOPT_ROWS_READBACK_MISMATCH", 5)
        if state is None:
            state = {"plan_id": plan["plan_id"], "recovered_without_state": True}
        if state.get("state") not in {"rows_committed", "manifest_committed",
                                      "cache_committed"}:
            state = _adopt_write_state(state_path, state, "rows_committed")
        if not os.path.exists(manifest_path):
            _atomic_json_write(manifest_path, target)
            result["manifest_written"] = 1
        _identity_failpoint(fail_at, "after_manifest_write")
        if _read_json_file(manifest_path) != target:
            raise IdentityLifecycleError("ADOPT_MANIFEST_READBACK_MISMATCH", 5)
        if state["state"] == "rows_committed":
            state = _adopt_write_state(state_path, state, "manifest_committed")
        if _adopt_cache(conn) != target_cache:
            try:
                conn.execute("BEGIN IMMEDIATE")
                for key, value in target_cache.items():
                    conn.execute("INSERT OR REPLACE INTO _metadata (key, value) "
                                 "VALUES (?, ?)", (key, value))
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            result["cache_written"] = 1
        _identity_failpoint(fail_at, "after_cache_commit")
        if state["state"] == "manifest_committed":
            state = _adopt_write_state(state_path, state, "cache_committed")
        # Shared resolver (T007) is the only judge of manifest/cache agreement.
        try:
            resolved = resolve_workspace_identity(conn, manifest_path=manifest_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            raise IdentityLifecycleError("ADOPT_RESOLVE_READBACK_MISMATCH", 5)
        if resolved != target or _adopt_quick_check(conn) != "ok":
            raise IdentityLifecycleError("ADOPT_RESOLVE_READBACK_MISMATCH", 5)
        counts = {
            "projects_with_identity": conn.execute(
                "SELECT COUNT(*) FROM projects WHERE workspace_id=?",
                (workspace["workspace_id"],)).fetchone()[0],
            "tasks_with_identity": conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE workspace_id=?",
                (workspace["workspace_id"],)).fetchone()[0],
            "legacy_read_only_tasks": conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE workspace_id IS NULL").fetchone()[0],
        }
        state = _adopt_write_state(state_path, state, "verified", counts=counts,
                                   verified_at=_now_iso())
    except (OSError, sqlite3.Error) as exc:
        # Rows are committed: the same Plan resumes (exit 4 = partial success).
        raise IdentityLifecycleError("ADOPT_PARTIAL_RESUMABLE: %s" % exc, 4)
    return dict(result, state="verified", noop=False, counts=counts)


def _adopt_reuse_plan(conn, plan, *, writer_id, decisions, decisions_base,
                      manifest_path):
    """dry-run rerun: the persisted Plan is the mapping; never re-issue IDs."""
    if not validate_adopt_existing_plan(plan):
        raise IdentityLifecycleError("ADOPT_PLAN_INVALID", 2)
    if (plan["workspace"]["writer_id"] != writer_id
            or plan["decision_digest"] != _adopt_decision_digest(decisions)):
        raise IdentityLifecycleError("ADOPT_PLAN_CONFLICT", 2)
    marker = _adopt_meta(conn, ADOPT_MARKER_KEY)
    if marker == plan["plan_id"]:
        return "applied"
    if marker is not None:
        raise IdentityLifecycleError("ADOPT_FOREIGN_PROJECTION", 3)
    if os.path.exists(manifest_path):
        raise IdentityLifecycleError("ADOPT_MANIFEST_EXISTS", 3)
    _adopt_verify_source(conn, plan)
    # Evidence (intent bytes) is re-checked, not only the adjudication digest.
    _adopt_normalize_decisions(identity_migration_inventory(conn), decisions,
                               decisions_base)
    return "planned"


def _adopt_plan_summary(plan):
    return {
        "plan_id": plan["plan_id"],
        "workspace_id": _short_identity(plan["workspace"]["workspace_id"]),
        "writer_id": plan["workspace"]["writer_id"],
        "projects": len(plan["projects"]),
        "new_projects": len(plan["new_projects"]),
        "tasks": len(plan["tasks"]),
        "excluded_tasks": len(plan["excluded_tasks"]),
        "decision_counts": plan["decision_counts"],
        "mutation_budget": plan["mutation_budget"],
    }


def cmd_adopt_existing(options):
    """adopt-existing --dry-run | --plan (execute/resume) | --status."""
    plan_path = options.get("--plan")
    manifest_path = WORKSPACE_MANIFEST_PATH
    try:
        if options.get("--dry-run"):
            plan_out = options["--plan-out"]
            decisions_path = options["--decisions"]
            decisions = load_adopt_decisions(decisions_path)
            conn, error = _open_read_conn()
            if error:
                _print_preflight_report(error)
                return 3
            try:
                if os.path.exists(plan_out):
                    try:
                        plan = _read_json_file(plan_out)
                    except (ValueError, json.JSONDecodeError):
                        raise IdentityLifecycleError("ADOPT_PLAN_INVALID", 2)
                    lifecycle = _adopt_reuse_plan(
                        conn, plan, writer_id=options["--writer-id"],
                        decisions=decisions,
                        decisions_base=os.path.dirname(os.path.abspath(decisions_path)),
                        manifest_path=manifest_path)
                    reused = True
                else:
                    plan = build_adopt_existing_plan(
                        conn, writer_id=options["--writer-id"], decisions=decisions,
                        decisions_base=os.path.dirname(os.path.abspath(decisions_path)),
                        manifest_path=manifest_path)
                    lifecycle, reused = "planned", False
            finally:
                conn.close()
            if not reused:
                # The Plan is the durable mapping: persisted before any mutation.
                _atomic_json_write(plan_out, plan)
            print(json.dumps(dict(_adopt_plan_summary(plan), state=lifecycle,
                                  reused=reused), ensure_ascii=False, sort_keys=True))
            return 0
        state_path = options.get("--state") or plan_path + ".state.json"
        try:
            plan = _read_json_file(plan_path)
        except (ValueError, json.JSONDecodeError):
            raise IdentityLifecycleError("ADOPT_PLAN_INVALID", 2)
        if options.get("--status"):
            if not validate_adopt_existing_plan(plan):
                raise IdentityLifecycleError("ADOPT_PLAN_INVALID", 2)
            state = (_read_json_file(state_path) if os.path.exists(state_path)
                     else {"plan_id": plan["plan_id"], "state": "not_started"})
            if state.get("plan_id") != plan["plan_id"]:
                raise IdentityLifecycleError("ADOPT_STATE_PLAN_MISMATCH", 2)
            print(json.dumps(dict(
                _adopt_plan_summary(plan), state=state.get("state"),
                checkpoint=bool(state.get("checkpoint")),
                counts=state.get("counts")), ensure_ascii=False, sort_keys=True))
            return 0
        conn, error = _open_write_conn()
        if error:
            _print_preflight_report(error)
            return 3
        try:
            result = execute_adopt_existing_plan(
                conn, plan, expected_plan_id=options["--plan-id"],
                state_path=state_path, manifest_path=manifest_path)
        finally:
            conn.close()
        print(json.dumps(dict(result, workspace_id=_short_identity(
            result["workspace_id"])), ensure_ascii=False, sort_keys=True))
        print("NEXT: status/pull/push now run on the Identity v2 path. If Notion pages are "
              "already linked, run backfill-remote-identity --dry-run --plan-out FILE first.")
        return 0
    except (IdentityLifecycleError, KeyError, TypeError, ValueError, OSError,
            json.JSONDecodeError, sqlite3.Error) as exc:
        return _lifecycle_exit(exc)


# ── Remote Identity backfill (T014) ────────────────────────
# Writes the four Identity properties onto Notion pages that are already
# linked to current-workspace rows but still Identity-less (T001: legacy
# linked pages are backfilled only through a fixed, approved Plan).  No other
# property, no unlinked row, no legacy_excluded row and no other workspace is
# ever touched.  The Plan is local-only; remote state is checked per page at
# execution time with read -> PATCH -> read-back.

REMOTE_BACKFILL_DIRECTION = "remote_identity_backfill"
REMOTE_BACKFILL_BATCH_SIZE = 10
REMOTE_BACKFILL_PROPERTIES = {
    "project": ("Sync UID", "Workspace ID", "Ownership Epoch", "Identity Version"),
    "task": ("Project Sync UID", "Workspace ID", "Project Ownership Epoch",
             "Identity Version"),
}


def _remote_backfill_targets(conn, workspace_id):
    excluded_scopes = _load_excluded_scopes(conn)
    tasks_frozen = _task_sync_frozen(conn)
    targets = []
    for entity, table, uid_col, epoch_col in (
            ("project", "projects", "sync_uid", "ownership_epoch"),
            ("task", "tasks", "project_sync_uid", "project_ownership_epoch")):
        if entity == "task" and tasks_frozen:
            continue
        key_cols = "scope_id" if entity == "project" else "scope_id, task_id"
        rows = conn.execute(
            "SELECT id, notion_page_id, %s, workspace_id, %s AS uid, %s AS epoch, "
            "identity_version FROM %s WHERE workspace_id=? AND notion_page_id IS "
            "NOT NULL AND trim(notion_page_id)<>'' ORDER BY id"
            % (key_cols, uid_col, epoch_col, table), (workspace_id,)).fetchall()
        for row in rows:
            if excluded_scopes.row(entity, dict(row, **{uid_col: row["uid"]})):
                continue
            record = dict(row)
            record[uid_col] = record.pop("uid")
            record[epoch_col] = record.pop("epoch")
            state, values = _identity_record_state(entity, record)
            if state != "valid":
                raise IdentityLifecycleError("REMOTE_BACKFILL_LOCAL_IDENTITY_INVALID", 3)
            targets.append({
                "entity": entity, "row_id": row["id"],
                "page_id": row["notion_page_id"],
                "scope_id": row["scope_id"],
                "task_id": row["task_id"] if entity == "task" else None,
                "identity": {"uid": values["uid"],
                             "workspace_id": values["workspace_id"],
                             "epoch": values["epoch"],
                             "identity_version": values["identity_version"]},
            })
    return targets


def _remote_backfill_op_id(target):
    return "rib_" + _canonical_json_digest({
        key: target[key] for key in ("entity", "row_id", "page_id", "identity")
    })[len("sha256:"):]


def build_remote_identity_backfill_plan(conn, *, manifest_path=None):
    """Fix the backfill targets before any remote call (local SQLite only)."""
    manifest = resolve_workspace_identity(
        conn, manifest_path=manifest_path or WORKSPACE_MANIFEST_PATH)
    workspace_id = manifest["workspace_id"]
    targets = _remote_backfill_targets(conn, workspace_id)
    operations = []
    for index, target in enumerate(targets):
        operations.append(dict(target, operation_id=_remote_backfill_op_id(target),
                               batch=index // REMOTE_BACKFILL_BATCH_SIZE))
    plan = {
        "direction": REMOTE_BACKFILL_DIRECTION,
        "plan_schema_version": 1,
        "workspace_id": workspace_id,
        "writer_epoch": manifest["writer_epoch"],
        "batch_size": REMOTE_BACKFILL_BATCH_SIZE,
        "source_digest": _canonical_json_digest(targets),
        "operations": operations,
        "counts": {
            "project": sum(1 for op in operations if op["entity"] == "project"),
            "task": sum(1 for op in operations if op["entity"] == "task"),
            "batches": (len(operations) + REMOTE_BACKFILL_BATCH_SIZE - 1)
            // REMOTE_BACKFILL_BATCH_SIZE,
        },
        "mutation_budget": {"notion_page_patches": len(operations),
                            "properties_per_patch": 4, "sqlite_identity": 0},
    }
    plan["plan_id"] = _fork_plan_id(plan)
    return plan


def validate_remote_identity_backfill_plan(plan, expected_plan_id=None):
    if not isinstance(plan, dict) or plan.get("direction") != REMOTE_BACKFILL_DIRECTION:
        return False
    if plan.get("plan_id") != _fork_plan_id(plan):
        return False
    if expected_plan_id is not None and plan["plan_id"] != expected_plan_id:
        return False
    for op in plan.get("operations", []):
        target = {key: op.get(key) for key in (
            "entity", "row_id", "page_id", "identity")}
        if op.get("operation_id") != _remote_backfill_op_id(target):
            return False
        if op.get("entity") not in REMOTE_BACKFILL_PROPERTIES:
            return False
    return True


def _remote_backfill_properties(op):
    names = REMOTE_BACKFILL_PROPERTIES[op["entity"]]
    identity = op["identity"]
    return {
        names[0]: _build_rich_text(identity["uid"]),
        names[1]: _build_rich_text(identity["workspace_id"]),
        names[2]: _build_number(identity["epoch"]),
        names[3]: _build_number(identity["identity_version"]),
    }


def _remote_page_identity(op, page):
    record = (_notion_row_to_project(page) if op["entity"] == "project"
              else _notion_row_to_task(page))
    state, values = _identity_record_state(op["entity"], record)
    return state, values, record


def _remote_non_identity_digest(op, page):
    # Only the synced schema properties: Notion-computed ones (last edited
    # time/by, formula, rollup) change as a side effect of our own PATCH.
    schema = (PROJECTS_NOTION_SCHEMA if op["entity"] == "project"
              else TASKS_NOTION_SCHEMA)
    skip = set(REMOTE_BACKFILL_PROPERTIES[op["entity"]])
    props = page.get("properties") or {}
    return _canonical_json_digest({name: props.get(name) for name in sorted(schema)
                                   if name not in skip})


def _remote_backfill_check_page(op, page):
    """Return legacy|done for a page that may be written; raise otherwise."""
    expected_db = PROJECTS_DB_ID if op["entity"] == "project" else TASKS_DB_ID
    parent = (page.get("parent") or {}).get("database_id")
    if page.get("archived") or page.get("in_trash"):
        raise IdentityLifecycleError("REMOTE_BACKFILL_PAGE_ARCHIVED", 3)
    if _normalize_notion_id(parent) != _normalize_notion_id(expected_db):
        raise IdentityLifecycleError("REMOTE_BACKFILL_PAGE_PARENT_MISMATCH", 3)
    state, values, record = _remote_page_identity(op, page)
    keys_match = (_normalize_identity_text(record.get("scope_id"))
                  == _normalize_identity_text(op["scope_id"]))
    if op["entity"] == "task":
        keys_match = keys_match and (_normalize_identity_text(record.get("task_id"))
                                     == _normalize_identity_text(op["task_id"]))
    if not keys_match:
        raise IdentityLifecycleError("REMOTE_BACKFILL_KEY_MISMATCH", 3)
    if state == "legacy":
        return "legacy"
    if state == "valid" and all(values[key] == op["identity"][key] for key in (
            "uid", "workspace_id", "epoch", "identity_version")):
        return "done"
    raise IdentityLifecycleError("IDENTITY_SPLIT_BRAIN", 3)


def _remote_backfill_state(state_path, plan):
    if os.path.exists(state_path):
        state = _read_json_file(state_path)
        if state.get("plan_id") != plan["plan_id"]:
            raise IdentityLifecycleError("REMOTE_BACKFILL_STATE_PLAN_MISMATCH", 2)
        return state
    return {"plan_id": plan["plan_id"], "state": "planned", "operations": {}}


def _remote_backfill_local_baseline(conn, op, pre_edited, post_edited):
    """Move the local Notion baseline without hiding local or remote edits.

    - remote edited since the last sync (pre > local baseline): leave the
      baseline so the next pull still sees the remote edit.
    - local clean: advance baseline and last_sync_at together (stays clean).
    - local dirty: advance the baseline only; the updated_at trigger keeps the
      row dirty so the next push sends the local edit as patch_remote.
    """
    table = "projects" if op["entity"] == "project" else "tasks"
    row = conn.execute(
        "SELECT notion_page_id, notion_last_edited, last_sync_at, updated_at "
        "FROM %s WHERE id=?" % table, (op["row_id"],)).fetchone()
    if row is None or row["notion_page_id"] != op["page_id"]:
        raise IdentityLifecycleError("REMOTE_BACKFILL_SOURCE_CHANGED", 2)
    if _instant_gt(pre_edited, row["notion_last_edited"]):
        return "remote_dirty_kept"
    locally_dirty = (row["last_sync_at"] is None
                     or _instant_gt(row["updated_at"], row["last_sync_at"]))
    if locally_dirty:
        conn.execute("UPDATE %s SET notion_last_edited=? WHERE id=?" % table,
                     (post_edited, op["row_id"]))
        conn.commit()
        return "local_dirty_kept"
    baseline = _operation_sync_baseline(_now_iso(), row["updated_at"])
    conn.execute("UPDATE %s SET notion_last_edited=?, last_sync_at=? WHERE id=?"
                 % table, (post_edited, baseline, op["row_id"]))
    conn.commit()
    return "clean"


def execute_remote_identity_backfill_plan(conn, plan, *, expected_plan_id,
                                          state_path, manifest_path=None,
                                          max_batches=None, fail_at=None):
    if not validate_remote_identity_backfill_plan(plan, expected_plan_id):
        raise IdentityLifecycleError("REMOTE_BACKFILL_PLAN_INVALID", 2)
    manifest = resolve_workspace_identity(
        conn, manifest_path=manifest_path or WORKSPACE_MANIFEST_PATH)
    if (manifest["workspace_id"] != plan["workspace_id"]
            or manifest["writer_epoch"] != plan["writer_epoch"]):
        raise IdentityLifecycleError("IDENTITY_WORKSPACE_MISMATCH", 3)
    state = _remote_backfill_state(state_path, plan)
    ops_state = state.setdefault("operations", {})
    current = {_remote_backfill_op_id(target): target
               for target in _remote_backfill_targets(conn, plan["workspace_id"])}
    counts = {"patched": 0, "already": 0, "remote_dirty_kept": 0,
              "local_dirty_kept": 0, "clean": 0, "skipped_source_changed": 0}
    for op in plan["operations"]:
        if ops_state.get(op["operation_id"], {}).get("status") in {"done", "skipped"}:
            continue
        if op["operation_id"] not in current:
            if ops_state.get(op["operation_id"], {}).get("status") == "claimed":
                # A PATCH may already have landed on the old page: do not
                # report it as skipped; a person must look at that page.
                raise IdentityLifecycleError(
                    "REMOTE_BACKFILL_CLAIMED_SOURCE_CHANGED", 5)
            # The row was relinked/removed after the Plan: never write to the
            # old page.  Keeping the same Plan (and its claims) avoids the
            # stale-baseline trap of re-planning after a crash.
            ops_state[op["operation_id"]] = {"status": "skipped",
                                             "reason": "source_changed"}
            counts["skipped_source_changed"] += 1
            print("  [SKIP] %s row changed after the Plan" % op["entity"])
    _atomic_json_write(state_path, state)
    batches_run = 0
    for batch in sorted({op["batch"] for op in plan["operations"]}):
        pending = [op for op in plan["operations"] if op["batch"] == batch
                   and ops_state.get(op["operation_id"], {}).get("status")
                   not in {"done", "skipped"}]
        if not pending:
            continue
        if max_batches is not None and batches_run >= max_batches:
            break
        batches_run += 1
        for op in pending:
            entry = ops_state.get(op["operation_id"], {})
            page = _api_call("GET", "/v1/pages/%s" % op["page_id"])
            remote = _remote_backfill_check_page(op, page)
            if remote == "legacy":
                # The PATCH has not landed: the page as read now is the
                # baseline (a stale claimed value could hide a later edit).
                pre_edited = page.get("last_edited_time")
                before_digest = _remote_non_identity_digest(op, page)
                ops_state[op["operation_id"]] = {
                    "status": "claimed", "pre_edited": pre_edited,
                    "before_digest": before_digest}
                state["state"] = "running"
                _atomic_json_write(state_path, state)
                _identity_failpoint(fail_at, "before_patch")
                _api_call("PATCH", "/v1/pages/%s" % op["page_id"],
                          {"properties": _remote_backfill_properties(op)})
                _identity_failpoint(fail_at, "after_patch")
                counts["patched"] += 1
            elif entry.get("status") == "claimed":
                # Resumed after the PATCH committed remotely: finish locally
                # with the baseline captured before the PATCH.
                pre_edited = entry["pre_edited"]
                before_digest = entry.get("before_digest")
            else:
                # Already carried this Identity (e.g. created by a v2 push):
                # verify only, never move the local baseline.
                counts["already"] += 1
                ops_state[op["operation_id"]] = {"status": "done",
                                                 "outcome": "already"}
                _atomic_json_write(state_path, state)
                continue
            verified = _api_call("GET", "/v1/pages/%s" % op["page_id"])
            if _remote_backfill_check_page(op, verified) != "done":
                raise IdentityLifecycleError("REMOTE_BACKFILL_READBACK_MISMATCH", 5)
            if (before_digest is not None
                    and _remote_non_identity_digest(op, verified) != before_digest):
                # Only the 4 Identity properties are ever sent, so a change in
                # any other property is a concurrent edit in Notion: keep the
                # local baseline so the next pull still sees it.
                print("  [WARN] %s changed in Notion during backfill; "
                      "left for the next pull" % op["operation_id"][:16])
                outcome = "remote_dirty_kept"
            else:
                outcome = _remote_backfill_local_baseline(
                    conn, op, pre_edited, verified.get("last_edited_time"))
            counts[outcome] += 1
            ops_state[op["operation_id"]] = {"status": "done", "outcome": outcome}
            _atomic_json_write(state_path, state)
            print("  [BACKFILL] %s %s (%s)" % (
                op["entity"], op["scope_id"] + ("/" + op["task_id"]
                                                if op["task_id"] else ""), outcome))
    done = sum(1 for op in plan["operations"]
               if ops_state.get(op["operation_id"], {}).get("status") == "done")
    skipped = sum(1 for op in plan["operations"]
                  if ops_state.get(op["operation_id"], {}).get("status") == "skipped")
    if done == len(plan["operations"]):
        state["state"] = "verified"
    elif done + skipped == len(plan["operations"]):
        state["state"] = "verified_with_skips"
    else:
        state["state"] = "partial"
    state["done"] = done
    state["skipped"] = skipped
    _atomic_json_write(state_path, state)
    return {"plan_id": plan["plan_id"], "state": state["state"],
            "done": done, "skipped": skipped, "total": len(plan["operations"]),
            "batches_run": batches_run, "counts": counts}


def _remote_backfill_summary(plan):
    return {"plan_id": plan["plan_id"], "workspace_id": _short_identity(
        plan["workspace_id"]), "counts": plan["counts"],
        "mutation_budget": plan["mutation_budget"]}


def cmd_backfill_remote_identity(options):
    """backfill-remote-identity --dry-run | --plan (execute/resume) | --status."""
    plan_path = options.get("--plan")
    try:
        if options.get("--dry-run"):
            plan_out = options["--plan-out"]
            conn, error = _open_read_conn()
            if error:
                _print_preflight_report(error)
                return 3
            try:
                plan = build_remote_identity_backfill_plan(
                    conn, manifest_path=WORKSPACE_MANIFEST_PATH)
            finally:
                conn.close()
            reused = False
            if os.path.exists(plan_out):
                existing = _read_json_file(plan_out)
                if not validate_remote_identity_backfill_plan(existing):
                    raise IdentityLifecycleError("REMOTE_BACKFILL_PLAN_INVALID", 2)
                if existing["plan_id"] != plan["plan_id"]:
                    raise IdentityLifecycleError("REMOTE_BACKFILL_SOURCE_CHANGED", 2)
                reused = True
            else:
                _atomic_json_write(plan_out, plan)
            print(json.dumps(dict(_remote_backfill_summary(plan), state="planned",
                                  reused=reused), ensure_ascii=False, sort_keys=True))
            return 0
        state_path = options.get("--state") or plan_path + ".state.json"
        try:
            plan = _read_json_file(plan_path)
        except (ValueError, json.JSONDecodeError):
            raise IdentityLifecycleError("REMOTE_BACKFILL_PLAN_INVALID", 2)
        if options.get("--status"):
            if not validate_remote_identity_backfill_plan(plan):
                raise IdentityLifecycleError("REMOTE_BACKFILL_PLAN_INVALID", 2)
            state = _remote_backfill_state(state_path, plan)
            done = sum(1 for entry in state.get("operations", {}).values()
                       if entry.get("status") == "done")
            skipped = sum(1 for entry in state.get("operations", {}).values()
                          if entry.get("status") == "skipped")
            print(json.dumps(dict(_remote_backfill_summary(plan),
                                  state=state.get("state"), done=done,
                                  skipped=skipped),
                             ensure_ascii=False, sort_keys=True))
            return 0
        max_batches = options.get("--max-batches")
        if max_batches is not None:
            if not re.fullmatch(r"[1-9][0-9]{0,3}", max_batches):
                print("ERROR: --max-batches requires a positive integer")
                return 64
            max_batches = int(max_batches)
        conn, error = _open_write_conn()
        if error:
            _print_preflight_report(error)
            return 3
        try:
            result = execute_remote_identity_backfill_plan(
                conn, plan, expected_plan_id=options["--plan-id"],
                state_path=state_path, manifest_path=WORKSPACE_MANIFEST_PATH,
                max_batches=max_batches)
        finally:
            conn.close()
        print(json.dumps(dict(result, plan_id=result["plan_id"]),
                         ensure_ascii=False, sort_keys=True))
        if result["state"] == "partial":
            print("NEXT: rerun the same --plan/--plan-id to continue the "
                  "remaining batches.")
        elif result["state"] == "verified_with_skips":
            print("NEXT: rows changed after the Plan were skipped; run "
                  "--dry-run with a NEW --plan-out file name to cover them.")
        return 0
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500 and exc.code != 429:
            # Permission/schema/not-found: rerunning cannot fix it.
            print("ERROR: REMOTE_BACKFILL_API_REJECTED %d" % exc.code)
            return 3
        # 429/5xx: rerun the same Plan; claimed pages are re-read first.
        print("ERROR: REMOTE_BACKFILL_API_ERROR %d" % exc.code)
        return 4
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        print("ERROR: REMOTE_BACKFILL_API_ERROR network")
        return 4
    except (IdentityLifecycleError, KeyError, TypeError, ValueError, OSError,
            json.JSONDecodeError, sqlite3.Error) as exc:
        return _lifecycle_exit(exc)


# ── Main ───────────────────────────────────────────────────

CLI_COMMAND_OPTIONS = {
    "pull": {"flags": ("--dry-run",), "values": ()},
    "push": {
        "flags": ("--dry-run",),
        "values": (
            "--scope", "--plan", "--plan-id", "--plan-out", "--authorization",
            "--sync-uid", "--workspace-id", "--decline",
        ),
    },
    "sync": {"flags": ("--dry-run",), "values": ()},
    "status": {"flags": ("--audit",), "values": ()},
    "preflight": {"flags": (), "values": ()},
    "reconcile": {"flags": (), "values": ()},
    "adopt-existing": {
        "flags": ("--dry-run", "--status"),
        "values": ("--decisions", "--writer-id", "--plan-out", "--plan",
                   "--plan-id", "--state"),
    },
    "declines": {"flags": (), "values": ("--revoke", "--approved-by")},
    "import-legacy": {"flags": ("--dry-run",), "values": ("--out", "--apply")},
    "tasks-sync": {"flags": ("--status", "--freeze", "--unfreeze"),
                   "values": ("--approved-by", "--reason")},
    "exclude": {"flags": ("--list",),
                "values": ("--scope", "--remove", "--approved-by", "--reason")},
    "migrate-identity": {
        "flags": ("--dry-run", "--status"),
        "values": ("--decisions", "--plan-out", "--plan", "--plan-id",
                   "--fixture-root", "--state"),
    },
    "backfill-remote-identity": {
        "flags": ("--dry-run", "--status"),
        "values": ("--plan-out", "--plan", "--plan-id", "--state",
                   "--max-batches"),
    },
    "fork-workspace": {
        "flags": ("--dry-run", "--status"),
        "values": ("--plan-out", "--writer-id", "--plan", "--plan-id", "--state"),
    },
    "activate-writer": {
        "flags": ("--dry-run",),
        "values": ("--workspace-id", "--fork-plan", "--plan-id", "--fork-state",
                   "--bootstrap-state"),
    },
    "transfer-project": {
        "flags": ("--dry-run",), "values": ("--sync-uid", "--to-workspace"),
    },
    "takeover-writer": {
        "flags": ("--dry-run",), "values": ("--workspace-id", "--writer-id"),
    },
    "handoff-repair": {
        "flags": ("--dry-run",),
        "values": ("--workspace-id", "--plan", "--plan-id"),
    },
}

CLI_REQUIRED_OPTIONS = {
    "transfer-project": ("--sync-uid", "--to-workspace"),
    "takeover-writer": ("--workspace-id", "--writer-id"),
    "handoff-repair": ("--workspace-id",),
    "activate-writer": ("--workspace-id",),
}

CLI_VALUE_PATTERNS = {
    "--sync-uid": PROJECT_UID_PATTERN,
    "--workspace-id": WORKSPACE_ID_PATTERN,
    "--to-workspace": WORKSPACE_ID_PATTERN,
    "--writer-id": WRITER_ID_PATTERN,
}

CLI_VALUE_LABELS = {
    "--scope": "SCOPE_ID",
    "--plan": "FILE",
    "--plan-id": "SHA256",
    "--plan-out": "FILE",
    "--authorization": "FILE",
    "--decline": "FILE",
    "--revoke": "ID",
    "--remove": "SCOPE_ID",
    "--out": "FILE",
    "--apply": "FILE",
    "--reason": "TEXT",
    "--approved-by": "NAME",
    "--decisions": "FILE",
    "--fixture-root": "DIR",
    "--state": "FILE",
    "--sync-uid": "PRJ_UID",
    "--workspace-id": "WSP_ID",
    "--to-workspace": "WSP_ID",
    "--writer-id": "WRITER_ID",
    "--fork-plan": "FILE",
    "--fork-state": "FILE",
    "--bootstrap-state": "FILE",
    "--max-batches": "N",
}


def _print_cli_help(command=None):
    if command is None:
        print(__doc__)
        print("Use 'python3 .claude/db/sync.py COMMAND --help' for command options.")
        return
    spec = CLI_COMMAND_OPTIONS[command]
    options = ["[%s]" % option for option in spec["flags"]]
    options.extend(
        "[%s %s]" % (option, CLI_VALUE_LABELS[option])
        for option in spec["values"]
    )
    suffix = " " + " ".join(options) if options else ""
    print("Usage:")
    print("    python3 .claude/db/sync.py %s%s" % (command, suffix))
    print("    python3 .claude/db/sync.py %s --help" % command)


def _parse_cli(argv):
    """Parse every CLI token before any command handler can run."""
    if not argv:
        return None, "missing command"
    if argv == ["--help"]:
        return {"action": "help", "command": None, "options": {}}, None

    command = argv[0]
    if command not in CLI_COMMAND_OPTIONS:
        return None, "unknown command: %s" % command
    tokens = argv[1:]
    if "--help" in tokens:
        if tokens == ["--help"]:
            return {"action": "help", "command": command, "options": {}}, None
        return None, "--help cannot be combined with other arguments"

    spec = CLI_COMMAND_OPTIONS[command]
    flags = set(spec["flags"])
    values = set(spec["values"])
    options = {}
    seen = set()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in seen:
            return None, "duplicate option: %s" % token
        if token in flags:
            seen.add(token)
            options[token] = True
            index += 1
            continue
        if token in values:
            if (index + 1 >= len(tokens) or not tokens[index + 1]
                    or tokens[index + 1].startswith("-")):
                return None, "%s requires a value" % token
            seen.add(token)
            options[token] = tokens[index + 1]
            index += 2
            continue
        if token.startswith("-"):
            return None, "unknown option for %s: %s" % (command, token)
        return None, "unexpected argument for %s: %s" % (command, token)

    for option, pattern in CLI_VALUE_PATTERNS.items():
        if option in options and not pattern.fullmatch(options[option]):
            return None, "%s has an invalid %s value" % (
                option, CLI_VALUE_LABELS[option])
    for option in CLI_REQUIRED_OPTIONS.get(command, ()):
        if option not in options:
            return None, "%s requires %s" % (command, option)
    if command == "handoff-repair" and (
            bool(options.get("--plan")) != bool(options.get("--plan-id"))):
        return None, "handoff-repair --plan and --plan-id must be passed together"
    if command == "fork-workspace":
        dry_run = options.get("--dry-run", False)
        status = options.get("--status", False)
        execute = bool(options.get("--plan")) and not status
        if int(bool(dry_run)) + int(bool(status)) + int(execute) != 1:
            return None, "fork-workspace requires exactly one of --dry-run, --status, or --plan"
        if dry_run and (not options.get("--plan-out") or not options.get("--writer-id")):
            return None, "fork-workspace --dry-run requires --plan-out and --writer-id"
        if dry_run and any(key in options for key in ("--plan", "--plan-id", "--state")):
            return None, "fork-workspace --dry-run has incompatible options"
        if execute and not options.get("--plan-id"):
            return None, "fork-workspace --plan requires --plan-id"
        if (execute or status) and any(
                key in options for key in ("--plan-out", "--writer-id")):
            return None, "fork-workspace --plan/--status has incompatible options"
        if status and (not options.get("--plan") or "--plan-id" in options):
            return None, "fork-workspace --status requires only --plan [--state]"
    if command == "adopt-existing":
        dry_run = options.get("--dry-run", False)
        status = options.get("--status", False)
        execute = bool(options.get("--plan")) and not status
        if int(bool(dry_run)) + int(bool(status)) + int(execute) != 1:
            return None, "adopt-existing requires exactly one of --dry-run, --status, or --plan"
        if dry_run and not all(options.get(key) for key in (
                "--decisions", "--writer-id", "--plan-out")):
            return None, "adopt-existing --dry-run requires --decisions, --writer-id, and --plan-out"
        if dry_run and any(key in options for key in ("--plan", "--plan-id", "--state")):
            return None, "adopt-existing --dry-run has incompatible options"
        if execute and not options.get("--plan-id"):
            return None, "adopt-existing --plan requires --plan-id"
        if (execute or status) and any(key in options for key in (
                "--decisions", "--writer-id", "--plan-out")):
            return None, "adopt-existing --plan/--status has incompatible options"
        if status and (not options.get("--plan") or "--plan-id" in options):
            return None, "adopt-existing --status requires only --plan [--state]"
    if command == "tasks-sync":
        modes = sum(1 for key in ("--status", "--freeze", "--unfreeze") if options.get(key))
        if modes != 1:
            return None, "tasks-sync requires exactly one of --status, --freeze, or --unfreeze"
        if options.get("--status") and any(
                key in options for key in ("--approved-by", "--reason")):
            return None, "tasks-sync --status takes no other options"
        if not options.get("--status") and not options.get("--approved-by"):
            return None, "tasks-sync --freeze/--unfreeze requires --approved-by"
        if options.get("--unfreeze") and "--reason" in options:
            return None, "tasks-sync --unfreeze does not take --reason"
    if command == "import-legacy":
        if bool(options.get("--dry-run")) == bool(options.get("--apply")):
            return None, "import-legacy requires exactly one of --dry-run or --apply"
        if options.get("--dry-run") and not options.get("--out"):
            return None, "import-legacy --dry-run requires --out"
        if options.get("--apply") and "--out" in options:
            return None, "import-legacy --apply does not take --out"
    if command == "exclude":
        modes = sum(1 for key in ("--list", "--scope", "--remove") if options.get(key))
        if modes != 1:
            return None, "exclude requires exactly one of --list, --scope, or --remove"
        if options.get("--list") and any(
                key in options for key in ("--approved-by", "--reason")):
            return None, "exclude --list takes no other options"
        if (options.get("--scope") or options.get("--remove")) and not options.get(
                "--approved-by"):
            return None, "exclude --scope/--remove requires --approved-by"
        if options.get("--remove") and "--reason" in options:
            return None, "exclude --remove does not take --reason"
    if command == "declines" and bool(options.get("--revoke")) != bool(
            options.get("--approved-by")):
        return None, "declines --revoke requires --approved-by (and vice versa)"
    if command == "backfill-remote-identity":
        dry_run = options.get("--dry-run", False)
        status = options.get("--status", False)
        execute = bool(options.get("--plan")) and not status
        if int(bool(dry_run)) + int(bool(status)) + int(execute) != 1:
            return None, "backfill-remote-identity requires exactly one of --dry-run, --status, or --plan"
        if dry_run and not options.get("--plan-out"):
            return None, "backfill-remote-identity --dry-run requires --plan-out"
        if dry_run and any(key in options for key in (
                "--plan", "--plan-id", "--state", "--max-batches")):
            return None, "backfill-remote-identity --dry-run has incompatible options"
        if execute and not options.get("--plan-id"):
            return None, "backfill-remote-identity --plan requires --plan-id"
        if (execute or status) and "--plan-out" in options:
            return None, "backfill-remote-identity --plan/--status has incompatible options"
        if status and (not options.get("--plan") or any(
                key in options for key in ("--plan-id", "--max-batches"))):
            return None, "backfill-remote-identity --status requires only --plan [--state]"
    if command == "activate-writer":
        fork_plan = options.get("--fork-plan")
        bootstrap = options.get("--bootstrap-state")
        if bool(fork_plan) == bool(bootstrap):
            return None, "activate-writer requires exactly one of --fork-plan or --bootstrap-state"
        if fork_plan and not options.get("--plan-id"):
            return None, "activate-writer --fork-plan requires --plan-id"
        if bootstrap and any(key in options for key in ("--plan-id", "--fork-state")):
            return None, "activate-writer --bootstrap-state has incompatible options"
    if command == "push":
        if "--scope" in options and not _normalize_identity_text(options["--scope"]):
            return None, "--scope requires a non-empty SCOPE_ID"
        plan_path = options.get("--plan")
        plan_id = options.get("--plan-id")
        if plan_path and not plan_id:
            return None, "--plan requires --plan-id"
        if plan_id and not plan_path:
            return None, "--plan-id requires --plan"
        if "--decline" in options and (
                not plan_path or options.get("--dry-run")
                or any(key in options for key in ("--authorization", "--plan-out"))):
            return None, ("--decline requires --plan/--plan-id and cannot be combined "
                          "with --dry-run, --authorization, or --plan-out")
    if command == "migrate-identity":
        dry_run = options.get("--dry-run", False)
        status = options.get("--status", False)
        plan_path = options.get("--plan")
        plan_id = options.get("--plan-id")
        decisions = options.get("--decisions")
        plan_out = options.get("--plan-out")
        execute = bool(plan_path) and not status
        modes = int(bool(dry_run)) + int(bool(status)) + int(execute)
        if modes != 1:
            return None, "migrate-identity requires exactly one of --dry-run, --status, or --plan"
        fixture_root = options.get("--fixture-root")
        state_path = options.get("--state")
        if dry_run and (not decisions or not plan_out or not fixture_root):
            return None, "migrate-identity --dry-run requires --decisions, --plan-out, and --fixture-root"
        if dry_run and (plan_path or plan_id or state_path):
            return None, "migrate-identity --dry-run has incompatible options"
        if execute and (not plan_id or not fixture_root):
            return None, "migrate-identity --plan requires --plan-id and --fixture-root"
        if execute and (decisions or plan_out):
            return None, "migrate-identity --plan has incompatible options"
        if plan_path and not plan_id and not status:
            return None, "migrate-identity --plan requires --plan-id"
        if plan_id and not plan_path:
            return None, "migrate-identity --plan-id requires --plan"
        if status and not plan_path:
            return None, "migrate-identity --status requires --plan"
        if status and (decisions or plan_out or plan_id or fixture_root):
            return None, "migrate-identity --status cannot be combined with mutation options"
    return {"action": "run", "command": command, "options": options}, None


def main(argv=None):
    cli_argv = list(sys.argv[1:] if argv is None else argv)
    parsed, error = _parse_cli(cli_argv)
    if error:
        print("ERROR: %s" % error)
        _print_cli_help()
        return 64
    if parsed["action"] == "help":
        _print_cli_help(parsed["command"])
        return 0

    cmd = parsed["command"]
    options = parsed["options"]
    dry_run = options.get("--dry-run", False)
    if cmd == "pull":
        return cmd_pull(dry_run=dry_run)
    if cmd in V2_1_DEFERRED_COMMANDS:
        return cmd_deferred_v21(cmd, options)
    if cmd == "push":
        push_kwargs = {
            "dry_run": dry_run,
            "plan_path": options.get("--plan"),
            "expected_plan_id": options.get("--plan-id"),
            "plan_out": options.get("--plan-out"),
            "authorization_path": options.get("--authorization"),
            "scope_id": options.get("--scope"),
        }
        # Identity selectors are passed only when given, keeping the v1 call shape.
        if "--sync-uid" in options:
            push_kwargs["sync_uid"] = options["--sync-uid"]
        if "--workspace-id" in options:
            push_kwargs["workspace_id"] = options["--workspace-id"]
        if "--decline" in options:
            push_kwargs["decline_path"] = options["--decline"]
        return cmd_push(**push_kwargs)
    if cmd == "fork-workspace":
        return cmd_fork_workspace(options)
    if cmd == "activate-writer":
        return cmd_activate_writer(options)
    if cmd == "adopt-existing":
        return cmd_adopt_existing(options)
    if cmd == "backfill-remote-identity":
        return cmd_backfill_remote_identity(options)
    if cmd == "declines":
        return cmd_declines(options)
    if cmd == "exclude":
        return cmd_exclude(options)
    if cmd == "import-legacy":
        return cmd_import_legacy(options)
    if cmd == "tasks-sync":
        return cmd_tasks_sync(options)
    if cmd == "sync":
        return cmd_sync(dry_run=dry_run)
    if cmd == "status":
        return cmd_status(audit=options.get("--audit", False))
    if cmd == "preflight":
        return cmd_preflight()
    if cmd == "migrate-identity":
        return cmd_migrate_identity(options)
    return cmd_reconcile()


if __name__ == "__main__":
    sys.exit(main())
