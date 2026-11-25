#!/usr/bin/env python3
"""AI-PLC Registry ビューア（alpha）— ローカル専用の閲覧サーバ。

    python3 .claude/db/registry_viewer/server.py [--port 8765] [--no-browser] [--db PATH] [--root PATH]

- 127.0.0.1 でだけ待ち受ける。外部送信・CDN なし
- 読み取り: Registry（ai_plc.db を読み取り専用で開く）と Layer の intent.yaml / backlog.yaml。
  aiplc_status_audit.py が見つかれば、その audit()（Layer の場所・食い違い・機密判定）も使う
- 閲覧専用: 状態を変える HTTP API は無い（GET / HEAD 以外は 405）。status の変更は /plc-lifecycle や
  各 Stage の実行（/04-operation など）で行う
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import project_activity  # noqa: E402

STATIC = HERE / "static"
VERSION = ((HERE / "VERSION").read_text(encoding="utf-8").strip() if (HERE / "VERSION").is_file() else "dev")
LIST_CACHE_SECONDS = 15.0
READONLY_MESSAGE = "閲覧専用です（status の変更は /plc-lifecycle や各 Stage の実行で行います）"


DB_DIRS = (Path(".claude") / "db", Path(".cursor") / "db")  # Claude Code / Cursor の配置


def find_root(start: Path = HERE):
    """server.py の場所から上にたどって、最初に .claude/db/ai_plc.db（無ければ .cursor/db/ai_plc.db）があるフォルダ。無ければ None"""
    for p in start.parents:
        if any((p / d / "ai_plc.db").is_file() for d in DB_DIRS):
            return p
    return None


def _aiplc_paths():
    """DB の場所の共通関数 aiplc_paths.py。プロジェクトに置いたときは隣のフォルダ（.claude/db/）、
    公開リポの checkout では core/db/ にある。見つからない・読み込めないときは None（隣の DB で動く）"""
    for p in (HERE.parent / "aiplc_paths.py", HERE.parents[1] / "core" / "db" / "aiplc_paths.py"):
        if p.is_file():
            try:
                return _load("_rv_aiplc_paths", p)
            except Exception:  # noqa: BLE001  (古い版・壊れたファイル)
                return None
    return None


def default_db(root: Path) -> Path:
    paths = _aiplc_paths()  # .ai-plc/config.yaml の db_path や、worktree から開いたときの本体の DB を見る
    if paths is not None:
        try:
            r = paths.resolve_db(root, env={})
            if r.source != "script" and Path(r.path).is_file():
                return Path(r.path)
        except Exception:  # noqa: BLE001  (git が無いなど。今までどおり隣の DB を使う)
            pass
    return next((root / d / "ai_plc.db" for d in DB_DIRS if (root / d / "ai_plc.db").is_file()),
                root / DB_DIRS[0] / "ai_plc.db")


# ビューアが status_audit から使うもの。1つでも欠けていれば（古い版・別の版）使わない
AUDIT_API = ("audit", "Layer", "Confidential", "hash_id", "task_vocab", "detect_task_vocab",
             "reg_task_target", "norm", "open_ro")


REPO = find_root()  # 見つからなければ None（main は --root / --db の指定を求める）


def find_dependencies(root: Path):
    """(audit_path or None, plc_path or None, reason or None)。
    環境変数で指定したのに無いファイルは FileNotFoundError（打ち間違いで黙って表示が減らないように）"""
    def pick(env, candidates):
        v = os.environ.get(env)
        if v:
            if not Path(v).is_file():
                raise FileNotFoundError(f"{env}={v} が見つかりません")
            return Path(v)
        return next((c for c in candidates if c.is_file()), None)
    audit = pick("AIPLC_STATUS_AUDIT", [root / "scripts" / "aiplc_status_audit.py",
                                        root / ".claude" / "ai-plc-jev" / "scripts" / "aiplc_status_audit.py"])
    plc = pick("AIPLC_PLC_QUERY", [root / d / "plc_query.py" for d in DB_DIRS])
    return audit, plc, (None if audit else "aiplc_status_audit.py が見つからないため、食い違い・機密判定は出ません")


ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")

# intent の値 -> 一致とみなす Registry の値（status_audit が食い違いと判定しない組み合わせに合わせる）
INTENT_REGISTRY_OK = {"active": {"active"}, "completed": {"completed"}, "done": {"completed"},
                      "deferred": {"paused"}, "blocked": {"active"}, "pending": {"planned", "active"},
                      "pending_init": {"planned", "active"}, "pending_inception": {"planned", "active"},
                      "cancelled": {"cancelled"}, "paused": {"paused"}}


def status_mismatch(layer, reg_status):
    if layer is None:
        return False
    ok = INTENT_REGISTRY_OK.get(str(layer.status or ""))
    return ok is not None and reg_status not in ok


TASK_DONE = frozenset({"completed", "done", "完了"})
TASK_EXCLUDED = frozenset({"cancelled", "dropped", "deferred"})


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_FAST_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _yaml(path: Path) -> dict:
    try:
        d = yaml.load(path.read_text(encoding="utf-8"), Loader=_FAST_LOADER)
        return d if isinstance(d, dict) else {}
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return {}


def _registry_tasks_frozen(conn):
    """`sync.py tasks-sync --freeze`（または core 1.12.0 以降の新しい DB）でタスク同期が凍結されていれば、
    Registry の tasks テーブルは古い写しで、タスクの正は backlog.yaml だけ（読まない）"""
    try:
        return conn.execute(
            "SELECT 1 FROM _metadata WHERE key='task_sync_frozen'").fetchone() is not None
    except sqlite3.OperationalError:
        return False


class _ReadonlyAudit:
    """aiplc_status_audit が無い環境用の最小の代替（読み取りだけ）。食い違い検出・機密判定はしない"""
    SKIP = frozenset({"Documents", "node_modules", "__pycache__", "venv", "site-packages"})
    TERMINAL = frozenset({"completed", "done", "cancelled", "dropped", "完了"})

    @staticmethod
    def norm(v):
        if v is None:
            return None
        v = str(v).strip()
        return v if v == "完了" else v.lower()

    @staticmethod
    def open_ro(db):
        import urllib.parse
        conn = sqlite3.connect(f"file:{urllib.parse.quote(str(Path(db).resolve()))}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only = ON")
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def hash_id(sid):
        return "C-" + hashlib.sha256(str(sid).encode("utf-8")).hexdigest()[:8]

    class Layer:
        def __init__(self, root, folder):
            self.root, self.folder = Path(root), Path(folder)
            self.rel = self.folder.relative_to(self.root).as_posix()
            self.intent, self.backlog = _yaml(self.folder / "intent.yaml"), _yaml(self.folder / "backlog.yaml")
            self.scope_id = str(self.intent.get("scope_id") or "").strip() or None
            self.status_raw = self.intent.get("status")
            self.status = _ReadonlyAudit.norm(self.status_raw)
            raw = self.backlog.get("tasks")
            self.raw_tasks = [t for t in raw if isinstance(t, dict)] if isinstance(raw, list) else []
            # 運用タスク（recurrence）は tasks・open から外し、raw_tasks にだけ残す（進捗に数えない）
            self.tasks = [(str(t.get("id", t.get("task_id")) or "").strip() or None, _ReadonlyAudit.norm(t.get("status")),
                           t.get("completed_at")) for t in self.raw_tasks if not t.get("recurrence")]
            self.open = sum(1 for _, st, _ in self.tasks if st not in _ReadonlyAudit.TERMINAL and st != "deferred")
            summary = self.backlog.get("summary")
            self.summary_has_status = isinstance(summary, dict) and "status" in summary
            self.summary_status = summary.get("status") if self.summary_has_status else None

    @classmethod
    def audit(cls, db, root, today, **_kw):
        root = Path(root)
        index = {}
        for base in ("Flow", ".ai-plc"):
            for dp, dns, fns in os.walk(root / base):
                dns[:] = sorted(d for d in dns if not d.startswith(".") and d not in cls.SKIP)
                if "intent.yaml" in fns:  # 一覧用の索引は intent.yaml の scope_id だけを読む
                    sid = str(_yaml(Path(dp) / "intent.yaml").get("scope_id") or "").strip()
                    if sid:
                        index.setdefault(sid, []).append(Path(dp).relative_to(root).as_posix())
        return {"_layers": {sid: rels[0] for sid, rels in index.items()}, "candidates": [],
                "counts": {"candidates": 0, "by_kind": {}},
                "info": {"duplicate_folders": [{"scope_id": s, "folders": r} for s, r in index.items() if len(r) > 1]}}

    class Confidential:
        def __init__(self, *_a):
            pass

        def check(self, _sid):
            return None

    @staticmethod
    def detect_task_vocab(_conn):
        return None

    @staticmethod
    def task_vocab(_v, _layer=None):
        return {}

    @staticmethod
    def reg_task_target(_s, _v=None):
        return None


class _ClassifiedConfidential:
    """status_audit の機密判定に、分類の『機密の所属（confidential: true）』を足す（画面共有モードで行ごと伏せるため）"""

    def __init__(self, inner, cls):
        self.inner, self.cls = inner, cls

    def check(self, sid):
        c = self.cls["projects"].get(sid) if self.cls.get("available") else None
        if c and c.get("affiliation"):
            e = self.cls["vocab"].get("affiliation", {}).get(c["affiliation"])
            if e and e.get("confidential"):
                return "confidential_affiliation"
        return self.inner.check(sid)


class WriteError(Exception):
    """HTTP の応答コードつきのエラー（名前は以前の版との互換のため）"""

    def __init__(self, code: int, message: str, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


MEMBERSHIP_TABLES = frozenset({"programs", "business_projects", "business_project_links", "program_memberships"})


# ---------------------------------------------------------------- core
class Registry:
    def __init__(self, db: Path, root: Path, audit_path: Path | None = None, plc_path: Path | None = None,
                 readonly_reason: str | None = None):
        """audit_path を省略すると find_dependencies(root) で探す。依存の有無にかかわらず閲覧専用
        （plc_path は以前の版との互換のために受け取るだけで使わない）"""
        self.db, self.root = Path(db), Path(root)
        if audit_path is None and plc_path is None and readonly_reason is None:
            audit_path, plc_path, readonly_reason = find_dependencies(self.root)
        reasons = [readonly_reason] if readonly_reason else []
        self.audit = _ReadonlyAudit
        self.audit_rel = None
        if audit_path is not None:
            # status_audit / jev_client は自分のリポジトリを AIPLC_REPO から決める（機密語リストの場所もここから引く）
            os.environ.setdefault("AIPLC_REPO", str(self.root))
            try:
                mod = _load("_rv_audit", audit_path)
            except Exception as e:  # noqa: BLE001  (隣の jev_client.py が無い・構文エラーなど)
                mod = None
                reasons.append(f"aiplc_status_audit.py を読み込めない（{type(e).__name__}: {e}）ため、食い違い・機密判定は出ません")
            lacking = [n for n in AUDIT_API if mod is not None and not hasattr(mod, n)]
            if lacking:
                reasons.append(f"aiplc_status_audit.py に {', '.join(lacking)} が無い（版が違う）ため、食い違い・機密判定は出ません")
            elif mod is not None:
                self.audit = mod
                self.audit_rel = (os.path.relpath(audit_path, self.root)
                                  if Path(audit_path).resolve().is_relative_to(self.root.resolve()) else str(audit_path))
        self.plc = None  # 互換のための属性。書き込みのモジュールは読み込まない
        # 分類（所属・種類・実行環境）: classify.py（環境変数 → DB と同じフォルダ → server.py の隣）と分類の表が
        # あるときだけ表示する（無ければ今までどおり）
        self.classify = None
        env_cls = os.environ.get("AIPLC_CLASSIFY")
        cls_path = Path(env_cls) if env_cls else next(
            (p for p in (self.db.parent / "classify.py", HERE / "classify.py") if p.is_file()), HERE / "classify.py")
        if cls_path.is_file():
            try:
                self.classify = _load("_rv_classify", cls_path)
            except Exception:  # noqa: BLE001
                self.classify = None
        self.mode = "readonly"
        self.mode_reason = "／".join(dict.fromkeys([READONLY_MESSAGE, *reasons]))
        # 一覧は毎回 YAML を全部読む（Layer が多いと数秒）。HTTP からの一覧だけ短い間使い回し、同時の要求は1回の計算を待たせる
        self._list_lock = threading.Lock()
        self._list_cache = None  # (monotonic 時刻, DB の mtime, 結果)

    # -------- read
    def _ro(self):
        return self.audit.open_ro(self.db)  # URL-quoted read-only URI, row_factory=Row

    def _report(self):
        today = date.today()
        return self.audit.audit(self.db, self.root, today,
                                todo_path=self.root / "todo" / "todo.md",
                                memory_path=Path("/nonexistent/MEMORY.md"))

    def _layer(self, rel):
        return self.audit.Layer(self.root, self.root / rel) if rel else None

    def snapshot(self):
        report = self._report()
        layers_rel = report["_layers"]
        conn = self._ro()
        try:
            projects = {r["scope_id"]: r for r in conn.execute("SELECT * FROM projects ORDER BY scope_id")}
            reg_tasks = {}
            if not _registry_tasks_frozen(conn):  # 凍結中は backlog.yaml だけを見る
                for r in conn.execute("SELECT * FROM tasks ORDER BY scope_id, task_id"):
                    reg_tasks.setdefault(r["scope_id"], []).append(r)
            cls = self._read_classification(conn)
            cls["membership"] = self._read_membership(conn, projects)
        finally:
            conn.close()
        layers = {sid: self._layer(rel) for sid, rel in layers_rel.items() if sid in projects}
        conf = _ClassifiedConfidential(self.audit.Confidential(projects, layers), cls)
        cands = {}
        for c in report["candidates"]:
            cands.setdefault(c["scope_id"], []).append(c)
        mtime = datetime.fromtimestamp(self._db_mtime()).isoformat(timespec="seconds")
        return report, projects, reg_tasks, layers, conf, cands, mtime, cls

    def _read_classification(self, conn):
        """{'available': bool, 'projects': {sid: {...}}, 'tasks': {sid: {tid: executed_by}}, 'vocab': {...}}"""
        out = {"available": False, "projects": {}, "tasks": {}, "vocab": {"affiliation": {}, "kind": {}}}
        if self.classify is None:
            return out
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"project_classification", "task_execution"} <= names:
            return out
        try:
            vocab = self.classify.load_vocab()
        except Exception:  # noqa: BLE001  (語彙の形式が崩れていても一覧は出す)
            vocab = {"affiliation": {}, "kind": {}}
        out["available"] = True
        out["vocab"] = {a: vocab.get(a, {}) for a in ("affiliation", "kind")}
        for r in conn.execute("SELECT scope_id, affiliation, kind, executor FROM project_classification"):
            out["projects"][r["scope_id"]] = dict(r)
        for r in conn.execute("SELECT scope_id, task_id, executed_by FROM task_execution"):
            out["tasks"].setdefault(r["scope_id"], {})[r["task_id"]] = r["executed_by"]
        return out

    @staticmethod
    def _read_membership(conn, projects):
        """Program・業務Project の確定済みの関係（business_registry.py が作る4つの表）。同じ読み取り専用の接続で
        読むだけで、表が無い DB・Identity v2.0 でない DB（projects に sync_uid が無い）では使わない。
        紐付けは link の aiplc_uid が projects.sync_uid と一致するものだけ採る（食い違いは identity_mismatch に数える）。"""
        out = {"available": False, "programs": {}, "business": {}, "by_project": {}, "identity_mismatch": 0}
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not MEMBERSHIP_TABLES <= names:
            return out
        if "sync_uid" not in {r[1] for r in conn.execute("PRAGMA table_info(projects)")}:
            return out
        out["available"] = True
        for r in conn.execute("SELECT program_uid, definition_key, display_name, display_group FROM programs "
                              "WHERE state='active' ORDER BY display_name"):
            out["programs"][r["program_uid"]] = {
                "uid": r["program_uid"], "key": r["definition_key"] or "", "name": r["display_name"],
                "group": r["display_group"],
                # 画面共有モードで伏せる: 私生活の Program（business_registry.py add-program --private）
                "sensitive": r["display_group"] == "private",
                "masked": "PG-" + hashlib.sha256(r["program_uid"].encode()).hexdigest()[:6]}
        biz_program = {r["business_uid"]: r["program_uid"] for r in conn.execute(
            "SELECT business_uid, program_uid FROM program_memberships "
            "WHERE state='confirmed' AND target_kind='business_project'")}
        for r in conn.execute("SELECT id, business_uid, display_name FROM business_projects WHERE state='active' ORDER BY id"):
            prog = biz_program.get(r["business_uid"])
            out["business"][r["business_uid"]] = {
                "uid": r["business_uid"], "display_id": f"BIZ-{r['id']:04d}", "name": r["display_name"],
                "program_uid": prog if prog in out["programs"] else None,
                "sensitive": bool(prog in out["programs"] and out["programs"][prog]["sensitive"])}
        by_id = {p["id"]: (sid, p["sync_uid"]) for sid, p in projects.items()}

        def entry(pid, uid):
            sid, sync_uid = by_id.get(pid, (None, None))
            if sid is None:
                return None
            if uid != sync_uid or sync_uid is None:  # NULL の sync_uid も照合できないので採らない
                out["identity_mismatch"] += 1
                return None
            return out["by_project"].setdefault(sid, {"program_uid": None, "program_source": None,
                                                       "primary_business": None, "related_business": []})
        for r in conn.execute("SELECT program_uid, project_id, aiplc_uid FROM program_memberships "
                              "WHERE state='confirmed' AND target_kind='aiplc_project'"):
            e = entry(r["project_id"], r["aiplc_uid"])
            if e is not None and r["program_uid"] in out["programs"]:
                e["program_uid"], e["program_source"] = r["program_uid"], "direct"
        for r in conn.execute("SELECT business_uid, project_id, aiplc_uid, relation_type FROM business_project_links "
                              "WHERE state='confirmed' ORDER BY business_uid"):
            if r["business_uid"] not in out["business"]:
                continue
            e = entry(r["project_id"], r["aiplc_uid"])
            if e is None:
                continue
            if r["relation_type"] == "primary":
                e["primary_business"] = r["business_uid"]
            else:
                e["related_business"].append(r["business_uid"])
        # 直接の所属が無い（または直接の所属先が retired）なら、主な（primary）業務Project の Program を使う
        for e in out["by_project"].values():
            if e["program_uid"] is None and e["primary_business"]:
                e["program_uid"] = out["business"][e["primary_business"]]["program_uid"]
                e["program_source"] = "business" if e["program_uid"] else None
        return out

    @staticmethod
    def membership_of(cls, sid):
        """一覧・詳細に出す所属。紐付けの無い Project は None（推定しない）。伏せるのは画面側"""
        m = cls.get("membership") or {}
        if not m.get("available"):
            return None
        e = m["by_project"].get(sid)
        if not e or not (e["program_uid"] or e["primary_business"] or e["related_business"]):
            return None
        biz = lambda u: {k: m["business"][u][k] for k in ("uid", "display_id", "name", "program_uid", "sensitive")}  # noqa: E731
        return {"program": dict(m["programs"][e["program_uid"]]) if e["program_uid"] else None,
                "program_source": e["program_source"],
                "primary_business": biz(e["primary_business"]) if e["primary_business"] else None,
                "related_business": [biz(u) for u in e["related_business"]]}

    @staticmethod
    def membership_index(cls, items):
        m = cls.get("membership") or {}
        if not m.get("available"):
            return None
        # 画面の「未紐付け」と同じ基準: Program か主な業務Project があれば紐付き（関連だけの Project は未紐付け）
        linked = sum(1 for i in items if i.get("membership") and (i["membership"]["program"] or i["membership"]["primary_business"]))
        return {"programs": list(m["programs"].values()),
                "business_projects": list(m["business"].values()),  # id 順（読込順）
                "linked": linked, "unlinked": len(items) - linked, "identity_mismatch": m["identity_mismatch"]}

    @staticmethod
    def classification_of(cls, sid):
        """一覧・詳細に出す分類。表示名は語彙から（機密の所属は confidential を立てる。伏せるのは画面側）"""
        if not cls["available"]:
            return None
        c = cls["projects"].get(sid) or {}
        voc = cls["vocab"]

        def lab(axis):
            k = c.get(axis)
            e = voc.get(axis, {}).get(k) if k else None
            return {"key": k, "label": (e or {}).get("label") if k else None,
                    "confidential": bool((e or {}).get("confidential")), "known": e is not None}
        execs = sorted({v for v in [c.get("executor"), *cls["tasks"].get(sid, {}).values()] if v})
        return {"affiliation": lab("affiliation"), "kind": lab("kind"), "executor": c.get("executor"), "executors": execs}

    @staticmethod
    def vocab_options(cls):
        if not cls["available"]:
            return None
        return {axis: [{"key": k, "label": e.get("label") or k, "confidential": bool(e.get("confidential"))}
                       for k, e in cls["vocab"].get(axis, {}).items()] for axis in ("affiliation", "kind")}

    @staticmethod
    def _counted_statuses(layer):
        """進捗に数えるタスクの status。運用タスク（recurrence）は外す。
        公開版の aiplc_status_audit は運用タスクも tasks に入れる（tasks と raw_tasks が1対1）ので、ここで外す"""
        raw = getattr(layer, "raw_tasks", None)
        if isinstance(raw, list) and len(raw) == len(layer.tasks):
            return [s for (_, s, _), t in zip(layer.tasks, raw) if not (isinstance(t, dict) and t.get("recurrence"))]
        return [s for _, s, _ in layer.tasks]

    @staticmethod
    def progress(layer, reg_rows):
        sts = Registry._counted_statuses(layer) if layer is not None and layer.tasks else []
        if sts:
            total = sum(1 for s in sts if s not in TASK_EXCLUDED)
            done = sum(1 for s in sts if s in TASK_DONE)
            return {"done": done, "total": total, "source": "backlog"}
        if reg_rows:
            return {"done": sum(1 for r in reg_rows if r["status"] in TASK_DONE), "total": len(reg_rows),
                    "source": "registry"}
        return {"done": 0, "total": 0, "source": None}

    @staticmethod
    def launch_prompt(sid, row, layer):
        if row["status"] == "cancelled" or (layer is not None and layer.status == "cancelled"):
            return None  # 中止した Project は Operation で黙って再開しない（再開は /plc-lifecycle）
        if layer is None:
            return None
        # 実験版 ai-plc-jev は凍結中。pipeline_variant: jev の Layer も本体版のコマンドを出す
        status = str(layer.status or row["status"] or "").lower()
        if status in ("completed", "done"):
            return f"/01-collection を実行してください（Re-Collection）/ Layer: {layer.rel}"
        if not layer.tasks:
            if any(isinstance(t, dict) and t.get("recurrence") for t in getattr(layer, "raw_tasks", None) or []):
                return f"/04-operation を実行してください / Layer: {layer.rel}"  # 運用タスクだけの Layer
            # simple 深度は Stage 1 → 4 に直行できる（Stage 2・3 を飛ばす）
            if str(layer.intent.get("workflow_depth") or "").strip().lower() == "simple":
                return f"/04-operation を実行してください / Layer: {layer.rel}"
            return f"/02-inception を実行してください / Layer: {layer.rel}"
        return f"/04-operation を実行してください / Layer: {layer.rel}"

    def _db_mtime(self):
        wal = Path(str(self.db) + "-wal")
        return max([self.db.stat().st_mtime] + ([wal.stat().st_mtime] if wal.exists() else []))

    def list_projects_cached(self, ttl: float = LIST_CACHE_SECONDS):
        """HTTP 用。ttl 秒以内で DB が変わっていなければ前回の結果を返す（YAML の変更は ttl 後に反映）。"""
        with self._list_lock:
            mtime, now = self._db_mtime(), time.monotonic()
            c = self._list_cache
            if c is not None and now - c[0] < ttl and c[1] == mtime:
                return c[2]
            data = self.list_projects()
            self._list_cache = (time.monotonic(), mtime, data)
            return data

    def list_projects(self):
        report, projects, reg_tasks, layers, conf, cands, mtime, cls = self.snapshot()
        items = []
        for sid, r in projects.items():
            layer = layers.get(sid)
            items.append({
                "scope_id": sid, "name": r["name"], "status": r["status"], "depth": r["depth"],
                "parent_scope": (r["parent_scope"] or None), "deadline": r["deadline"],
                "start_date": r["start_date"], "updated_at": r["updated_at"],
                "activity": project_activity.evidence(self.root, layer.rel if layer else None, r),
                "layer_path": layer.rel if layer else None,
                "intent_status": layer.status_raw if layer else None,
                "status_mismatch": self.audit is not _ReadonlyAudit and status_mismatch(layer, r["status"]),
                "progress": self.progress(layer, reg_tasks.get(sid)),
                "issues": len(cands.get(sid, [])),
                "confidential": conf.check(sid) is not None,
                "hash_id": self.audit.hash_id(sid),
                "classification": self.classification_of(cls, sid),
                "membership": self.membership_of(cls, sid),
            })
        cnt = report["counts"]
        return {"generated_at": datetime.now().isoformat(timespec="seconds"), "db_mtime": mtime,
                "version": VERSION, "viewer_mode": self.mode, "viewer_mode_reason": self.mode_reason,
                "audit_available": self.audit is not _ReadonlyAudit,
                "classification_available": cls["available"], "vocab": self.vocab_options(cls),
                "projects": sorted(items, key=project_activity.order_key),
                "membership": self.membership_index(cls, items),
                "activity_notice": project_activity.NOTICE,
                "counts": {"total": len(items),
                           "by_status": {s: sum(1 for i in items if i["status"] == s)
                                         for s in ("planned", "active", "completed", "paused", "cancelled")},
                           "issues": cnt["candidates"],
                           "registry_missing": cnt["by_kind"].get("registry_missing", 0)}}

    def project_detail(self, sid):
        report, projects, reg_tasks, layers, conf, cands, mtime, cls = self.snapshot()
        row = projects.get(sid)
        if row is None:
            raise WriteError(404, f"{sid} は Registry にありません")
        layer = layers.get(sid)
        merged, order = {}, []
        if layer is not None:
            for t in layer.raw_tasks:
                tid = str(t.get("id", t.get("task_id")) or "").strip()
                if not tid:
                    continue
                order.append(tid)
                merged[tid] = {"task_id": tid, "name": t.get("name"), "priority": t.get("priority"),
                               "type": t.get("type"), "layer_status": t.get("status"), "registry_status": None,
                               "in_layer": True, "in_registry": False, "output": t.get("output"),
                               "recurrence": t.get("recurrence"),
                               # 実行時期・期限は backlog に書いたままの値（日付は文字列にする）
                               "scheduled_for": None if t.get("scheduled_for") is None else str(t.get("scheduled_for")),
                               "due": None if t.get("due") is None else str(t.get("due"))}
        for r in reg_tasks.get(sid, []):
            tid = str(r["task_id"]).strip()
            if tid not in merged:
                order.append(tid)
                merged[tid] = {"task_id": tid, "name": r["name"], "priority": r["priority"], "type": r["type"],
                               "layer_status": None, "in_layer": False, "output": None, "recurrence": None,
                               "scheduled_for": None, "due": None}
            merged[tid].update({"registry_status": r["status"], "in_registry": True})
            merged[tid]["name"] = merged[tid]["name"] or r["name"]
        for tid, t in merged.items():
            t["executed_by"] = cls["tasks"].get(sid, {}).get(tid) if cls["available"] else None
        vocab = self.audit.task_vocab(self._vocab(), layer)
        for t in merged.values():
            t["editable"], t["readonly_reason"] = False, READONLY_MESSAGE
            t["mismatch"] = (self.audit is not _ReadonlyAudit and t["in_layer"] and t["in_registry"] and t["layer_status"] is not None
                             and self.audit.reg_task_target(self.audit.norm(t["layer_status"]), vocab)
                             != t["registry_status"])
        children = [s for s, r in projects.items() if (r["parent_scope"] or "") == sid]
        return {
            "scope_id": sid, "name": row["name"], "goal": row["goal"], "status": row["status"],
            "mode": row["mode"], "depth": row["depth"], "owner": row["owner"],
            "parent_scope": row["parent_scope"] or None, "children": children,
            "start_date": row["start_date"], "deadline": row["deadline"], "updated_at": row["updated_at"],
            "activity": project_activity.evidence(self.root, layer.rel if layer else None, row),
            "activity_notice": project_activity.NOTICE,
            "layer_path": layer.rel if layer else None,
            "intent_status": layer.status_raw if layer else None,
            "cancellation": layer.intent.get("cancellation") if layer else None,
            "status_mismatch": self.audit is not _ReadonlyAudit and status_mismatch(layer, row["status"]),
            "summary_status": layer.summary_status if layer and layer.summary_has_status else None,
            "writable": False,
            "readonly_reason": READONLY_MESSAGE,
            "viewer_mode": self.mode, "audit_available": self.audit is not _ReadonlyAudit, "audit_path": self.audit_rel,
            "duplicate_folder": sid in self._dup_scopes(report),
            "confidential": conf.check(sid) is not None, "hash_id": self.audit.hash_id(sid),
            "classification": self.classification_of(cls, sid), "classification_available": cls["available"],
            "membership": self.membership_of(cls, sid),
            "membership_available": bool((cls.get("membership") or {}).get("available")),
            "progress": self.progress(layer, reg_tasks.get(sid)),
            "tasks": [merged[t] for t in order],
            "issues": [{"kind": c["kind"], "reason": c["reason"], "recommended_action": c["recommended_action"]}
                       for c in cands.get(sid, [])],
            "launch_prompt": self.launch_prompt(sid, row, layer),
            "db_mtime": mtime,
        }

    def _vocab(self):
        conn = self._ro()
        try:
            return self.audit.detect_task_vocab(conn)
        finally:
            conn.close()

    @staticmethod
    def _dup_scopes(report):
        return {d["scope_id"] for d in report["info"].get("duplicate_folders", [])}

    # 以前の版の書き込みの入口。何も読まず・書かずに断る
    def set_project_status(self, *_args, **_kw):
        raise WriteError(405, "VIEWER_READ_ONLY: " + READONLY_MESSAGE)

    def set_task_status(self, *_args, **_kw):
        raise WriteError(405, "VIEWER_READ_ONLY: " + READONLY_MESSAGE)


# ---------------------------------------------------------------- HTTP
def make_handler(reg: Registry, token: str, port_ref: dict):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RegistryViewer/" + VERSION
        registry = reg
        _head = False

        def log_message(self, fmt, *args):  # 静かにする（エラーは応答で返す）
            pass

        def _host_ok(self):
            host = (self.headers.get("Host") or "").strip().lower()
            port = port_ref["port"]
            return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

        def _origin_ok(self):
            origin = self.headers.get("Origin")
            if origin is None:
                return True
            port = port_ref["port"]
            return origin.lower() in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
            try:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                if ctype.startswith("text/html"):
                    self.send_header("Content-Security-Policy",
                                     "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
                                     "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
                                     "frame-ancestors 'none'")
                self.end_headers()
                if not self._head:
                    self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass  # 相手が待ちきれずに切った。ログを汚さない

        def _err(self, e: WriteError):
            self._send(e.code, {"ok": False, "error": e.message, **e.extra})

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"ok": False, "error": "Host が不正です"})
            path = self.path.split("?", 1)[0]
            try:
                if path in ("/", "/index.html"):
                    html = (STATIC / "index.html").read_text(encoding="utf-8").replace("__VIEWER_TOKEN__", token)
                    return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                if path == "/api/health":  # 起動確認用（一覧の計算をしない）
                    return self._send(200, {"ok": True, "version": VERSION})
                if path == "/api/projects":
                    return self._send(200, reg.list_projects_cached())
                m = re.match(r"^/api/projects/([^/]+)$", path)
                if m and ID_RE.match(m.group(1)):
                    return self._send(200, reg.project_detail(m.group(1)))
                return self._send(404, {"ok": False, "error": "not found"})
            except WriteError as e:
                return self._err(e)
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

        def do_HEAD(self):
            self._head = True
            try:
                self.do_GET()
            finally:
                self._head = False

        def _reject_mutation(self):
            if not self._host_ok() or not self._origin_ok():
                return self._send(403, {"ok": False, "error": "Host / Origin が不正です"})
            # 本文は読まず、トークンも比べず、どこにも書かない
            return self._send(405, {"ok": False, "error": "VIEWER_READ_ONLY: " + READONLY_MESSAGE})

        do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = do_CONNECT = _reject_mutation

    return Handler


def build_server(db: Path, root: Path, port: int = 0, token: str | None = None, **registry_kw):
    reg = Registry(db, root, **registry_kw)
    token = token or secrets.token_urlsafe(24)
    port_ref = {"port": port}
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(reg, token, port_ref))
    port_ref["port"] = httpd.server_address[1]
    return httpd, token, reg


def main(argv=None):
    ap = argparse.ArgumentParser(description="AI-PLC Registry ビューア（ローカル専用・閲覧専用）")
    ap.add_argument("--port", type=int, default=8765, help="待ち受けポート（0=空きポート。既定 8765）")
    ap.add_argument("--db", type=Path, default=None,
                    help="既定: 環境変数 AIPLC_DB → aiplc_paths.py があれば .ai-plc/config.yaml の db_path・本体の DB"
                         "（git-common-dir）→ <root>/.claude/db/ai_plc.db → <root>/.cursor/db/ai_plc.db")
    ap.add_argument("--root", type=Path, default=REPO, help="Flow/ を含むプロジェクトのルート（既定: 上にたどって .claude/db/ai_plc.db がある所）")
    ap.add_argument("--no-browser", action="store_true", help="ブラウザを開かない")
    args = ap.parse_args(argv)
    if args.root is None:
        print("プロジェクトのルートが見つかりません（上のフォルダに .claude/db/ai_plc.db がありません）。"
              "--root <プロジェクトのフォルダ> を指定してください", file=sys.stderr)
        return 2
    args.db = args.db or Path(os.environ.get("AIPLC_DB") or default_db(args.root))
    if not args.db.is_file():
        print(f"DB が見つかりません: {args.db}", file=sys.stderr)
        return 2
    paths = _aiplc_paths()
    if paths is not None and hasattr(paths, "warn_read"):
        try:
            paths.warn_read(args.db)  # 閲覧だけなので止めない
        except Exception:  # noqa: BLE001
            pass
    try:
        httpd, _token, _ = build_server(args.db.resolve(), args.root.resolve(), args.port)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    except OSError as e:
        print(f"ポート {args.port} を開けません（{e}）。--port 0 で空きポートを使えます", file=sys.stderr)
        return 2
    reg = httpd.RequestHandlerClass.registry
    print(f"mode: {reg.mode}（{reg.mode_reason}）", flush=True)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"AI-PLC Registry ビューア: {url}  （止めるときは Ctrl-C）", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
