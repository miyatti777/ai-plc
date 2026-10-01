#!/usr/bin/env python3
"""AI-PLC Registry ビューア（alpha）— ローカル専用の閲覧・status 変更サーバ。

    python3 .claude/db/registry_viewer/server.py [--port 8765] [--no-browser] [--db PATH] [--root PATH]

- aiplc_status_audit.py と plc_query.py が見つかればフル機能、無ければ閲覧のみ（find_dependencies）

- 127.0.0.1 でだけ待ち受ける。外部送信・CDN なし
- 読み取り: Registry（ai_plc.db を読み取り専用で開く）と、scripts/aiplc_status_audit.audit()（Layer の場所・食い違い）
- 書き込み: status だけ。Layer ファイル（intent.yaml / backlog.yaml）→ Registry の順（status_audit --apply と同じ）。
  行の追加はしない。変更前の値（expected）が1つでも違えば何も書かない（409）
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import tempfile
import threading
import webbrowser
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
VERSION = ((HERE / "VERSION").read_text(encoding="utf-8").strip() if (HERE / "VERSION").is_file() else "dev")


DB_DIRS = (Path(".claude") / "db", Path(".cursor") / "db")  # Claude Code / Cursor の配置


def find_root(start: Path = HERE):
    """server.py の場所から上にたどって、最初に .claude/db/ai_plc.db（無ければ .cursor/db/ai_plc.db）があるフォルダ。無ければ None"""
    for p in start.parents:
        if any((p / d / "ai_plc.db").is_file() for d in DB_DIRS):
            return p
    return None


def default_db(root: Path) -> Path:
    return next((root / d / "ai_plc.db" for d in DB_DIRS if (root / d / "ai_plc.db").is_file()),
                root / DB_DIRS[0] / "ai_plc.db")


# ビューアが status_audit から使うもの。1つでも欠けていれば（古い版・別の版）閲覧のみにする
AUDIT_API = ("audit", "Layer", "Confidential", "hash_id", "task_vocab", "detect_task_vocab", "reg_task_target", "norm",
             "read_yaml_status", "write_yaml_status", "_replace_value", "sql_lit", "open_ro")


REPO = find_root()  # 見つからなければ None（main は --root / --db の指定を求める）


def find_dependencies(root: Path):
    """(audit_path or None, plc_path or None, reason or None)。
    環境変数で指定したのに無いファイルは FileNotFoundError（打ち間違いで黙って閲覧のみにならないように）"""
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
    missing = [n for n, v in (("aiplc_status_audit.py", audit), ("plc_query.py", plc)) if v is None]
    return audit, plc, (f"{'・'.join(missing)} が見つからないため閲覧のみ" if missing else None)
ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")

PROJECT_CHOICES = {  # 画面の値 -> (intent に書く値, Registry に書く値)
    "active": ("active", "active"),
    "completed": ("completed", "completed"),
    "paused": ("deferred", "paused"),
}
# intent の値 -> 一致とみなす Registry の値（status_audit が食い違いと判定しない組み合わせに合わせる）
INTENT_REGISTRY_OK = {"active": {"active"}, "completed": {"completed"}, "done": {"completed"},
                      "deferred": {"paused"}, "blocked": {"active"}, "pending": {"planned", "active"},
                      "pending_init": {"planned", "active"}, "pending_inception": {"planned", "active"}}


def status_mismatch(layer, reg_status):
    if layer is None:
        return False
    ok = INTENT_REGISTRY_OK.get(str(layer.status or ""))
    return ok is not None and reg_status not in ok
TASK_CHOICES = ("pending", "in_progress", "completed", "blocked", "deferred", "cancelled")
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
    Registry の tasks テーブルは古い写しで、タスクの正は backlog.yaml だけ（読まない・書かない）"""
    try:
        return conn.execute(
            "SELECT 1 FROM _metadata WHERE key='task_sync_frozen'").fetchone() is not None
    except sqlite3.OperationalError:
        return False


class _ReadonlyAudit:
    """aiplc_status_audit が無い環境用の最小の代替（読み取りだけ）。書き込み・食い違い検出・機密判定はしない"""
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
            self.tasks = [(str(t.get("id", t.get("task_id")) or "").strip() or None, _ReadonlyAudit.norm(t.get("status")),
                           t.get("completed_at")) for t in self.raw_tasks]
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
    def __init__(self, code: int, message: str, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


# ---------------------------------------------------------------- backlog task status 1行書き換え
_ITEM_RE = re.compile(r"^(?P<ind>[ \t]*)-[ \t]+(?P<key>[A-Za-z_][\w-]*)[ \t]*:")
_KEY_RE = re.compile(r"^(?P<ind>[ \t]*)(?P<key>[A-Za-z_][\w-]*)[ \t]*:")


def _task_blocks(lines):
    """[(start, end, keycol)] for every block-mapping list item (`- key: ...`)."""
    out = []
    for i, line in enumerate(lines):
        m = _ITEM_RE.match(line)
        if not m:
            continue
        ind = len(m.group("ind"))
        keycol = m.start("key")
        j = i + 1
        while j < len(lines):
            s = lines[j].strip()
            if s and not s.startswith("#"):
                cur = len(lines[j]) - len(lines[j].lstrip(" \t"))
                if cur <= ind:
                    break
            j += 1
        out.append((i, j, keycol))
    return out


def _keys_in_block(lines, start, end, keycol):
    """{key: line_index} for keys that sit exactly at keycol (the dash line counts)."""
    keys = {}
    m = _ITEM_RE.match(lines[start])
    keys.setdefault(m.group("key"), []).append(start)
    for j in range(start + 1, end):
        km = _KEY_RE.match(lines[j])
        if km and len(km.group("ind")) == keycol:
            keys.setdefault(km.group("key"), []).append(j)
    return keys


def _scalar(line, key):
    m = re.match(r"^[ \t]*(?:-[ \t]+)?" + re.escape(key) + r"[ \t]*:[ \t]*(?P<v>[^#\r\n]*?)[ \t]*(#.*)?\r?\n?$", line)
    if not m:
        return None
    v = m.group("v")
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1]
    return v


def _tasks_range(lines):
    """(start, end) of the top-level `tasks:` block (exclusive end)."""
    heads = [i for i, l in enumerate(lines) if re.match(r"^tasks[ \t]*:[ \t]*(#.*)?\r?\n?$", l)]
    if len(heads) != 1:
        raise WriteError(409, "backlog.yaml にトップレベルの tasks: ブロックが1つだけ見つかりません")
    j = heads[0] + 1
    while j < len(lines):
        s = lines[j].strip()
        if s and not s.startswith("#") and not lines[j][:1].isspace() and not lines[j].startswith("-"):
            break
        j += 1
    return heads[0] + 1, j


def edit_task_status_text(text, task_id, new, audit_mod):
    lines = text.splitlines(keepends=True)
    lo, hi = _tasks_range(lines)
    hits = []
    for start, end, keycol in _task_blocks(lines[:hi]):
        if start < lo:
            continue
        keys = _keys_in_block(lines, start, end, keycol)
        idk = "id" if "id" in keys else ("task_id" if "task_id" in keys else None)
        if not idk or len(keys[idk]) != 1:
            continue
        if _scalar(lines[keys[idk][0]], idk) == str(task_id):
            hits.append(keys)
    if len(hits) != 1:
        raise WriteError(409, f"backlog.yaml に {task_id} のタスクが {len(hits)} 件見つかりました（1件のときだけ書きます）")
    st = hits[0].get("status") or []
    if len(st) != 1:
        raise WriteError(409, f"{task_id} の status 行が {len(st)} 行あります（1行のときだけ書きます）")
    i = st[0]
    line = lines[i]
    m = _ITEM_RE.match(line)
    if m:  # `- status: x` (status が先頭キー)
        head = line[:m.start("key")]
        lines[i] = head + audit_mod._replace_value(line[m.start("key"):], new)
    else:
        lines[i] = audit_mod._replace_value(line, new)
    return "".join(lines)


def _find_task(data, task_id):
    found = [t for t in (data or {}).get("tasks") or [] if isinstance(t, dict)
             and str(t.get("id", t.get("task_id"))).strip() == str(task_id)]
    return found


def write_task_status(path: Path, task_id, new, audit_mod):
    text = path.read_bytes().decode("utf-8")
    old = yaml.safe_load(text)
    if not isinstance(old, dict) or len(_find_task(old, task_id)) != 1:
        raise WriteError(409, f"backlog.yaml で {task_id} を1件に特定できません")
    new_text = edit_task_status_text(text, task_id, new, audit_mod)
    expect = copy.deepcopy(old)
    _find_task(expect, task_id)[0]["status"] = new
    if yaml.safe_load(new_text) != expect:
        raise WriteError(500, "書き換えで status 以外が変わるため中止しました")
    _atomic_write(path, new_text, orig=text)


_MISSING = object()


def read_task_status(path: Path, task_id):
    """status of the task, or _MISSING when the task is not in backlog.yaml. Duplicates / no status key -> 409."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    hits = _find_task(data if isinstance(data, dict) else {}, task_id)
    if not hits:
        return _MISSING
    if len(hits) > 1:
        raise WriteError(409, f"backlog.yaml に {task_id} が {len(hits)} 件あります（1件のときだけ書きます）")
    if "status" not in hits[0] or hits[0]["status"] is None:
        raise WriteError(409, f"backlog.yaml の {task_id} に status がありません（書き換える行が無いため書きません）")
    return hits[0]["status"]


def _atomic_write(path: Path, text: str, orig: str | None = None):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".registry_viewer_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        shutil.copymode(path, tmp)
        if orig is not None and path.read_bytes().decode("utf-8") != orig:
            raise WriteError(409, f"{path.name} が書き込みの直前に他で変更されました。再読み込みしてください")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------- core
class Registry:
    def __init__(self, db: Path, root: Path, audit_path: Path | None = None, plc_path: Path | None = None,
                 readonly_reason: str | None = None):
        """audit_path / plc_path を省略すると find_dependencies(root) で探す。どちらかが無ければ閲覧のみ"""
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
                reasons.append(f"aiplc_status_audit.py を読み込めない（{type(e).__name__}: {e}）ため閲覧のみ")
            lacking = [n for n in AUDIT_API if mod is not None and not hasattr(mod, n)]
            if lacking:
                reasons.append(f"aiplc_status_audit.py に {', '.join(lacking)} が無い（版が違う）ため閲覧のみ")
            elif mod is not None:
                self.audit = mod
                self.audit_rel = (os.path.relpath(audit_path, self.root)
                                  if Path(audit_path).resolve().is_relative_to(self.root.resolve()) else str(audit_path))
        self.plc = _load("_rv_plc", plc_path) if plc_path is not None else None
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
        if self.plc is None and not reasons:
            reasons.append("plc_query.py が見つからないため閲覧のみ")
        # audit が有れば、plc_query が無くても表示（食い違い・機密判定）はフル。書き込みは両方そろったときだけ
        self.mode_reason = "／".join(dict.fromkeys(reasons)) or None
        self.mode = "full" if self.mode_reason is None else "readonly"
        self.lock = threading.Lock()
        self.log_dir = Path(os.environ.get("AIPLC_STATUS_HYGIENE_DIR") or (self.db.parent / "status_hygiene"))

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
        finally:
            conn.close()
        layers = {sid: self._layer(rel) for sid, rel in layers_rel.items() if sid in projects}
        conf = _ClassifiedConfidential(self.audit.Confidential(projects, layers), cls)
        cands = {}
        for c in report["candidates"]:
            cands.setdefault(c["scope_id"], []).append(c)
        wal = Path(str(self.db) + "-wal")
        ts = max([self.db.stat().st_mtime] + ([wal.stat().st_mtime] if wal.exists() else []))
        mtime = datetime.fromtimestamp(ts).isoformat(timespec="seconds")
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
    def progress(layer, reg_rows):
        if layer is not None and layer.tasks:
            sts = [s for _, s, _ in layer.tasks]
            total = sum(1 for s in sts if s not in TASK_EXCLUDED)
            done = sum(1 for s in sts if s in TASK_DONE)
            return {"done": done, "total": total, "source": "backlog"}
        if reg_rows:
            return {"done": sum(1 for r in reg_rows if r["status"] in TASK_DONE), "total": len(reg_rows),
                    "source": "registry"}
        return {"done": 0, "total": 0, "source": None}

    @staticmethod
    def launch_prompt(sid, row, layer):
        if layer is None:
            return None
        jev = "-jev" if str(layer.intent.get("pipeline_variant") or "").strip() == "jev" else ""
        status = str(layer.status or row["status"] or "").lower()
        if status in ("completed", "done"):
            return f"/01-collection{jev} を実行してください（Re-Collection）/ Layer: {layer.rel}"
        if not layer.tasks:
            # simple 深度は Stage 1 → 4 に直行できる（Stage 2・3 を飛ばす）
            if str(layer.intent.get("workflow_depth") or "").strip().lower() == "simple":
                return f"/04-operation{jev} を実行してください / Layer: {layer.rel}"
            return f"/02-inception{jev} を実行してください / Layer: {layer.rel}"
        return f"/04-operation{jev} を実行してください / Layer: {layer.rel}"

    def list_projects(self):
        report, projects, reg_tasks, layers, conf, cands, mtime, cls = self.snapshot()
        items = []
        for sid, r in projects.items():
            layer = layers.get(sid)
            items.append({
                "scope_id": sid, "name": r["name"], "status": r["status"], "depth": r["depth"],
                "parent_scope": (r["parent_scope"] or None), "deadline": r["deadline"],
                "start_date": r["start_date"], "updated_at": r["updated_at"],
                "layer_path": layer.rel if layer else None,
                "intent_status": layer.status_raw if layer else None,
                "status_mismatch": self.audit is not _ReadonlyAudit and status_mismatch(layer, r["status"]),
                "progress": self.progress(layer, reg_tasks.get(sid)),
                "issues": len(cands.get(sid, [])),
                "confidential": conf.check(sid) is not None,
                "hash_id": self.audit.hash_id(sid),
                "classification": self.classification_of(cls, sid),
            })
        cnt = report["counts"]
        return {"generated_at": datetime.now().isoformat(timespec="seconds"), "db_mtime": mtime,
                "version": VERSION, "viewer_mode": self.mode, "viewer_mode_reason": self.mode_reason,
                "audit_available": self.audit is not _ReadonlyAudit,
                "classification_available": cls["available"], "vocab": self.vocab_options(cls),
                "projects": items,
                "counts": {"total": len(items),
                           "by_status": {s: sum(1 for i in items if i["status"] == s)
                                         for s in ("planned", "active", "completed", "paused")},
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
                               "in_layer": True, "in_registry": False, "output": t.get("output")}
        for r in reg_tasks.get(sid, []):
            tid = str(r["task_id"]).strip()
            if tid not in merged:
                order.append(tid)
                merged[tid] = {"task_id": tid, "name": r["name"], "priority": r["priority"], "type": r["type"],
                               "layer_status": None, "in_layer": False, "output": None}
            merged[tid].update({"registry_status": r["status"], "in_registry": True})
            merged[tid]["name"] = merged[tid]["name"] or r["name"]
        for tid, t in merged.items():
            t["executed_by"] = cls["tasks"].get(sid, {}).get(tid) if cls["available"] else None
        vocab = self.audit.task_vocab(self._vocab(), layer)
        btext = None
        if layer is not None and (layer.folder / "backlog.yaml").is_file():
            btext = (layer.folder / "backlog.yaml").read_text(encoding="utf-8")
        for t in merged.values():
            t["editable"], t["readonly_reason"] = self.mode == "full", None
            if t["in_layer"] and self.mode == "full":  # 書き換えられるかの空実行
                try:
                    edit_task_status_text(btext, t["task_id"], "completed", self.audit)
                except Exception as e:  # noqa: BLE001
                    t["editable"] = False
                    t["readonly_reason"] = (e.message if isinstance(e, WriteError) else str(e)) + \
                        "（flow 形式 `- {id: ..}` などは1行書き換えの対象外）"
        for t in merged.values():
            t["mismatch"] = (self.audit is not _ReadonlyAudit and t["in_layer"] and t["in_registry"] and t["layer_status"] is not None
                             and self.audit.reg_task_target(self.audit.norm(t["layer_status"]), vocab)
                             != t["registry_status"])
        children = [s for s, r in projects.items() if (r["parent_scope"] or "") == sid]
        return {
            "scope_id": sid, "name": row["name"], "goal": row["goal"], "status": row["status"],
            "mode": row["mode"], "depth": row["depth"], "owner": row["owner"],
            "parent_scope": row["parent_scope"] or None, "children": children,
            "start_date": row["start_date"], "deadline": row["deadline"], "updated_at": row["updated_at"],
            "layer_path": layer.rel if layer else None,
            "intent_status": layer.status_raw if layer else None,
            "status_mismatch": self.audit is not _ReadonlyAudit and status_mismatch(layer, row["status"]),
            "summary_status": layer.summary_status if layer and layer.summary_has_status else None,
            "writable": self.mode == "full" and layer is not None and sid not in self._dup_scopes(report),
            "readonly_reason": (f"閲覧のみモード（{self.mode_reason}）" if self.mode != "full" else
                                None if layer is not None and sid not in self._dup_scopes(report) else
                                ("Layer フォルダが見つからない" if layer is None else "同じ scope_id のフォルダが複数ある")),
            "viewer_mode": self.mode, "audit_available": self.audit is not _ReadonlyAudit, "audit_path": self.audit_rel,
            "duplicate_folder": sid in self._dup_scopes(report),
            "confidential": conf.check(sid) is not None, "hash_id": self.audit.hash_id(sid),
            "classification": self.classification_of(cls, sid), "classification_available": cls["available"],
            "progress": self.progress(layer, reg_tasks.get(sid)),
            "tasks": [merged[t] for t in order],
            "issues": [{"kind": c["kind"], "reason": c["reason"], "recommended_action": c["recommended_action"]}
                       for c in cands.get(sid, [])],
            "launch_prompt": self.launch_prompt(sid, row, layer),
            "db_mtime": mtime,
        }

    def _require_full(self):
        if self.mode != "full":
            raise WriteError(409, f"閲覧のみモードです（{self.mode_reason}）")

    def _vocab(self):
        conn = self._ro()
        try:
            return self.audit.detect_task_vocab(conn)
        finally:
            conn.close()

    # -------- write
    def _registry_update(self, table, sets, where, readback, to):
        """UPDATE via plc_query.cmd_sql (Identity guard on v2), then read the row back: total_changes is not usable
        because the updated_at triggers count as changes too."""
        conn = sqlite3.connect(str(self.db), timeout=10)
        try:
            q = f"UPDATE {table} SET {sets} WHERE {where}"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = self.plc.cmd_sql(conn, q)
            out = buf.getvalue()
            if rc or "Error:" in out or "[BLOCKED]" in out:
                raise WriteError(500, f"Registry の更新に失敗しました: {out.strip()[:200]}")
            if conn.in_transaction:
                conn.rollback()
                raise WriteError(500, "Registry の更新でトランザクションが残りました（戻しました）")
            rows = conn.execute(readback[0], readback[1]).fetchall()
            if len(rows) != 1 or rows[0][0] != to:
                got = rows[0][0] if len(rows) == 1 else f"{len(rows)} 行"
                raise WriteError(409, f"Registry を読み戻すと {got} でした（他で変更された可能性）")
        finally:
            conn.close()

    def _current_layer(self, sid):
        report = self._report()
        if sid in self._dup_scopes(report):
            raise WriteError(409, "同じ scope_id の Layer フォルダが複数あるため書き込みません（どれが正か人が確認）")
        rel = report["_layers"].get(sid)
        return self._layer(rel)

    @staticmethod
    def _dup_scopes(report):
        return {d["scope_id"] for d in report["info"].get("duplicate_folders", [])}

    def set_project_status(self, sid, to, expected):
        self._require_full()
        if to not in PROJECT_CHOICES:
            raise WriteError(400, f"status は {', '.join(PROJECT_CHOICES)} のどれかです")
        intent_to, reg_to = PROJECT_CHOICES[to]
        with self.lock:
            layer = self._current_layer(sid)
            if layer is None:
                raise WriteError(409, "Layer フォルダが見つからないため書き込みません（Registry だけ変えると食い違うため）")
            conn = self._ro()
            try:
                rows = conn.execute("SELECT status FROM projects WHERE scope_id=?", (sid,)).fetchall()
            finally:
                conn.close()
            if len(rows) != 1:
                raise WriteError(404, f"{sid} は Registry にありません（行の追加は plc_query.py add-project）")
            intent_path = layer.folder / "intent.yaml"
            backlog_path = layer.folder / "backlog.yaml"
            try:
                cur_intent = self.audit.read_yaml_status(intent_path)
            except Exception as e:  # noqa: BLE001  (ApplyError: status missing / not a mapping)
                raise WriteError(409, f"intent.yaml の status を読めません（{e}）")
            if cur_intent is None or str(cur_intent).strip() == "":
                raise WriteError(409, "intent.yaml の status が空のため書きません")
            cur_reg = rows[0]["status"]
            cur_summary = layer.summary_status if layer.summary_has_status else None
            exp = expected or {}
            if to == "completed":
                conn = self._ro()
                try:
                    vocab = self.audit.task_vocab(self.audit.detect_task_vocab(conn), layer)
                    reg_open = 0 if _registry_tasks_frozen(conn) else conn.execute(
                        f"SELECT COUNT(*) FROM tasks WHERE scope_id=? AND status NOT IN "
                        f"({','.join('?' * len(vocab['done_set']))})", (sid, *sorted(vocab["done_set"]))).fetchone()[0]
                finally:
                    conn.close()
                if layer.open or reg_open:
                    raise WriteError(409, f"未完了のタスクがあります（backlog {layer.open} 件・Registry {reg_open} 件）。"
                                          "先にタスクを completed か cancelled にしてください（deferred・blocked は Registry で未着手になり、"
                                          "閉じると食い違いになるため）",
                                     open_tasks={"backlog": layer.open, "registry": reg_open})
            if str(cur_intent) != str(exp.get("intent")) or str(cur_reg) != str(exp.get("registry")):
                raise WriteError(409, "画面を読んだ後に値が変わっています。再読み込みしてください",
                                 current={"intent": cur_intent, "registry": cur_reg})
            done = []  # (path, old, summary)
            try:
                if str(cur_intent) != intent_to:
                    self.audit.write_yaml_status(intent_path, intent_to)
                    done.append((intent_path, cur_intent, False, intent_to))
                if layer.summary_has_status and str(cur_summary) != intent_to:
                    self.audit.write_yaml_status(backlog_path, intent_to, summary=True)
                    done.append((backlog_path, cur_summary, True, intent_to))
                if cur_reg != reg_to:
                    lit = self.audit.sql_lit
                    self._registry_update("projects", f"status={lit(reg_to)}",
                                          f"scope_id={lit(sid)} AND status={lit(cur_reg)}",
                                          ("SELECT status FROM projects WHERE scope_id=?", (sid,)), reg_to)
            except Exception as e:
                rollback = self._rollback(done)
                err = self._wrap(e, rollback)
                self._log({"op": "project_status", "scope_id": sid, "to": to, "result": "error", "error": err.message})
                raise err
            self._log({"op": "project_status", "scope_id": sid, "to": to, "result": "ok",
                       "before": {"intent": cur_intent, "summary": cur_summary, "registry": cur_reg},
                       "after": {"intent": intent_to, "registry": reg_to}})
            return {"ok": True, "scope_id": sid, "intent": intent_to, "registry": reg_to,
                    "wrote": [str(p.relative_to(self.root)) for p, _, _, _ in done] + (["registry.projects"] if cur_reg != reg_to else [])}

    def set_task_status(self, sid, tid, to, expected):
        self._require_full()
        if to not in TASK_CHOICES:
            raise WriteError(400, f"status は {', '.join(TASK_CHOICES)} のどれかです")
        with self.lock:
            layer = self._current_layer(sid)
            if layer is None:
                raise WriteError(409, "Layer フォルダが見つからないため書き込みません（Registry だけ変えると食い違うため）")
            backlog_path = layer.folder / "backlog.yaml"
            cur_layer = read_task_status(backlog_path, tid) if backlog_path.is_file() else _MISSING
            in_layer = cur_layer is not _MISSING
            if not in_layer:
                cur_layer = None
            conn = self._ro()
            try:
                rows = [] if _registry_tasks_frozen(conn) else conn.execute(
                    "SELECT status FROM tasks WHERE scope_id=? AND task_id=?", (sid, tid)).fetchall()
                vocab = self.audit.task_vocab(self.audit.detect_task_vocab(conn), layer)
            finally:
                conn.close()
            if len(rows) > 1:
                raise WriteError(409, f"Registry に {sid}/{tid} が {len(rows)} 行あります")
            cur_reg = rows[0]["status"] if rows else None
            if not in_layer and cur_reg is None:
                raise WriteError(404, f"{tid} は backlog.yaml にも Registry にもありません")
            exp = expected or {}
            if str(cur_layer) != str(exp.get("backlog")) or str(cur_reg) != str(exp.get("registry")):
                raise WriteError(409, "画面を読んだ後に値が変わっています。再読み込みしてください",
                                 current={"backlog": cur_layer, "registry": cur_reg})
            reg_to = self.audit.reg_task_target(to, vocab)
            done = []
            wrote = []
            try:
                if in_layer and str(cur_layer) != to:
                    write_task_status(backlog_path, tid, to, self.audit)
                    done.append((backlog_path, cur_layer, ("task", tid), to))
                    wrote.append(str(backlog_path.relative_to(self.root)))
                if cur_reg is not None and cur_reg != reg_to:
                    lit = self.audit.sql_lit
                    sets = [f"status={lit(reg_to)}"]
                    if reg_to in vocab["done_set"]:
                        sets.append(f"completed_at=COALESCE(completed_at, {lit(date.today().isoformat())})")
                    self._registry_update("tasks", ", ".join(sets),
                                          f"scope_id={lit(sid)} AND task_id={lit(tid)} AND status={lit(cur_reg)}",
                                          ("SELECT status FROM tasks WHERE scope_id=? AND task_id=?", (sid, tid)), reg_to)
                    wrote.append("registry.tasks")
            except Exception as e:
                rollback = self._rollback(done)
                err = self._wrap(e, rollback)
                self._log({"op": "task_status", "scope_id": sid, "task_id": tid, "to": to, "result": "error",
                           "error": err.message})
                raise err
            self._log({"op": "task_status", "scope_id": sid, "task_id": tid, "to": to, "result": "ok",
                       "before": {"backlog": cur_layer, "registry": cur_reg}, "after": {"backlog": to if in_layer else None,
                                                                                         "registry": reg_to if cur_reg is not None else None}})
            return {"ok": True, "scope_id": sid, "task_id": tid, "backlog": to if in_layer else None,
                    "registry": reg_to if cur_reg is not None else None, "wrote": wrote}

    def _log(self, rec):
        """1変更1行の記録（git 管理外の status_hygiene/）。記録の失敗で書き込みは失敗させない。"""
        try:
            d = self.log_dir
            d.mkdir(parents=True, exist_ok=True)
            rec = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), **rec}  # 例 2026-09-29T17:17:51+09:00
            with open(d / "viewer_log.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _rollback(self, done):
        failed = []
        for path, old, kind, ours in reversed(done):
            try:
                cur = (read_task_status(path, kind[1]) if isinstance(kind, tuple)
                       else self.audit.read_yaml_status(path, summary=kind))
                if str(cur) != str(ours):
                    failed.append(f"{path.name}: 他で {cur} に変更されていたため戻していません")
                    continue
                if isinstance(kind, tuple):
                    write_task_status(path, kind[1], old, self.audit)
                else:
                    self.audit.write_yaml_status(path, old, summary=kind)
            except Exception as e:  # noqa: BLE001
                failed.append(f"{path.name}: {e}")
        return failed

    @staticmethod
    def _wrap(e, rollback_failed):
        if isinstance(e, WriteError):
            err = e
        else:
            err = WriteError(500, f"書き込みに失敗しました: {e}")
        if rollback_failed:
            err.message += "。Layer ファイルの書き戻しにも失敗しました（status_audit で検出できます）: " + "; ".join(rollback_failed)
            err.extra["rollback_failed"] = rollback_failed
        return err


# ---------------------------------------------------------------- HTTP
def make_handler(reg: Registry, token: str, port_ref: dict):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RegistryViewer/" + VERSION
        registry = reg

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
            self.wfile.write(data)

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
                if path == "/api/projects":
                    return self._send(200, reg.list_projects())
                m = re.match(r"^/api/projects/([^/]+)$", path)
                if m and ID_RE.match(m.group(1)):
                    return self._send(200, reg.project_detail(m.group(1)))
                return self._send(404, {"ok": False, "error": "not found"})
            except WriteError as e:
                return self._err(e)
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

        def do_POST(self):
            if not self._host_ok() or not self._origin_ok():
                return self._send(403, {"ok": False, "error": "Host / Origin が不正です"})
            if not secrets.compare_digest(self.headers.get("X-Viewer-Token") or "", token):
                return self._send(403, {"ok": False, "error": "トークンが不正です"})
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                return self._send(415, {"ok": False, "error": "Content-Type は application/json"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n < 0:
                    return self._send(400, {"ok": False, "error": "Content-Length が不正です"})
                if n > 10_000:
                    return self._send(413, {"ok": False, "error": "too large"})
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"ok": False, "error": "JSON が不正です"})
            path = self.path.split("?", 1)[0]
            try:
                m = re.match(r"^/api/projects/([^/]+)/status$", path)
                if m and ID_RE.match(m.group(1)):
                    return self._send(200, reg.set_project_status(m.group(1), body.get("to"), body.get("expected")))
                m = re.match(r"^/api/projects/([^/]+)/tasks/([^/]+)/status$", path)
                if m and ID_RE.match(m.group(1)) and ID_RE.match(m.group(2)):
                    return self._send(200, reg.set_task_status(m.group(1), m.group(2), body.get("to"),
                                                               body.get("expected")))
                return self._send(404, {"ok": False, "error": "not found"})
            except WriteError as e:
                return self._err(e)
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    return Handler


def build_server(db: Path, root: Path, port: int = 0, token: str | None = None, **registry_kw):
    reg = Registry(db, root, **registry_kw)
    token = token or secrets.token_urlsafe(24)
    port_ref = {"port": port}
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(reg, token, port_ref))
    port_ref["port"] = httpd.server_address[1]
    return httpd, token, reg


def main(argv=None):
    ap = argparse.ArgumentParser(description="AI-PLC Registry ビューア（ローカル専用）")
    ap.add_argument("--port", type=int, default=8765, help="待ち受けポート（0=空きポート。既定 8765）")
    ap.add_argument("--db", type=Path, default=None, help="既定: 環境変数 AIPLC_DB → <root>/.claude/db/ai_plc.db → <root>/.cursor/db/ai_plc.db")
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
    try:
        httpd, _token, _ = build_server(args.db.resolve(), args.root.resolve(), args.port)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    except OSError as e:
        print(f"ポート {args.port} を開けません（{e}）。--port 0 で空きポートを使えます", file=sys.stderr)
        return 2
    reg = httpd.RequestHandlerClass.registry
    print(f"mode: {reg.mode}" + (f"（{reg.mode_reason}）" if reg.mode_reason else ""), flush=True)
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
