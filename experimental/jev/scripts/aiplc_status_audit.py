#!/usr/bin/env python3
"""AI-PLC status audit (read-only).

Lists deterministic mismatches between the Registry (.claude/db/ai_plc.db), Layer files
(intent.yaml / backlog.yaml), todo/todo.md and native memory, and writes one candidate per
(scope_id, kind) to report.md / report.json.

Design notes: which source wins for which field, the candidate kinds and the confidentiality policy are
summarised in .claude/ai-plc-jev/scripts/README_status_audit.md.

Guarantees
- The DB is opened with sqlite3.connect("file:...?mode=ro", uri=True) + PRAGMA query_only.
- Layer files, todo.md and MEMORY.md are only read. Without --apply the only files written are report.md /
  report.json (under --out, or a new <state-dir>/reports/YYYY-MM-DD/HHMMSS/ per run) and, with
  --approval-template, the approval template (with --jev, jev_client also appends hash-only decision logs to
  .claude/db/jev_decisions.jsonl). --apply --yes writes as described under "Apply" below.
- Nothing is closed automatically. proposed_changes are for the approval file (--apply).
- Without --jev nothing is sent anywhere. Confidential flags come from jev_client.redact() (the one word
  list), parent inheritance and intent declarations. Jev eligibility needs intent `jev_monitor: true`.
- With --jev only `stale` rows with jev_eligible=true are sent, one choice question each
  (done / handed_off / stalled / unknown). The status text is checked with jev_client.redact() right before
  sending (last gate; ask() checks again). The answer is a hint only: proposed_changes never change.
- report.md / report.json / the approval template never show a confidential row's scope_id or layer_path in plain
  text: they show "C-" + sha256(scope_id)[:8] (also in candidate_id).

Apply: `--apply <approval.json>` re-scans, resolves each approved candidate_id (hashed ids too) to
the current row and writes only approved changes: intent.yaml `status` -> backlog.yaml `summary.status` (only when
the key exists; the one line is rewritten, comments and order kept) -> Registry via plc_query.cmd_sql. The
Registry task vocabulary (完了/進行中/未着手 or completed/active/planned) follows the tasks.status CHECK
constraint. Dry-run by default; `--yes` writes. A change whose current value differs from the approval's `from` is a
conflict and nothing of that candidate is written; a value already at `to` is a noop. Rows that need new Registry
rows (kinds 8/9) and duplicate_disagree rows are out of scope. Every --yes run appends to apply_log.jsonl
(confidential rows hashed). todo.md and native memory are never written.

Usage:
    python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py [--out <dir>] [--stale-days 30] [--jev] [--approval-template [PATH]]
    python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --apply <approval.json> [--yes]
    python3 .claude/ai-plc-jev/scripts/aiplc_status_audit.py --brief [--scope SCOPE_ID ... | --layer PATH ...]
    (--scope/--layer limit the candidates to those scopes, for Phase 7 of the Layer being closed. --brief
    prints a short summary only, writes no file, never calls Jev, and exits 0 = no candidates / 10 = candidates.)
    (--db or $AIPLC_DB; --state-dir or $AIPLC_STATUS_HYGIENE_DIR, default .claude/db/status_hygiene/)
    Without --out each run writes to a new <state-dir>/reports/YYYY-MM-DD/HHMMSS/ (never overwritten).
    Guide: .claude/ai-plc-jev/scripts/README_status_audit.md
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
import shutil
import sqlite3
import sys

sys.dont_write_bytecode = True  # no __pycache__ next to the installed scripts (clean uninstall)
import tempfile
import urllib.parse
from datetime import date, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jev_client  # noqa: E402  (redact() always; ask() only with --jev)



def _find_repo(start: Path) -> Path:
    """<repo>/.claude/ai-plc-jev/scripts/x.py -> <repo>; <repo>/scripts/x.py -> <repo> (unchanged).

    $AIPLC_REPO overrides (tests / unusual layouts). Otherwise walk up to the first directory named .claude whose
    parent carries the AI-PLC install marker (.ai-plc-version or .ai-plc-install-manifest); fall back to the
    grandparent of this file (the historical <repo>/scripts/ layout)."""
    env = os.environ.get("AIPLC_REPO")
    if env:
        return Path(env).resolve()
    for p in start.parents:
        if p.name == ".claude" and ((p.parent / ".ai-plc-version").is_file()
                                    or (p.parent / ".ai-plc-install-manifest").is_file()):
            return p.parent
    return start.parent.parent


REPO = _find_repo(Path(__file__).resolve())
DEFAULT_DB = REPO / ".claude" / "db" / "ai_plc.db"
DEFAULT_STATE_DIR = REPO / ".claude" / "db" / "status_hygiene"  # reports, approvals/, apply_log.jsonl: add to .gitignore
PLC_QUERY = REPO / ".claude" / "db" / "plc_query.py"
ENV_DB = "AIPLC_DB"
ENV_STATE = "AIPLC_STATUS_HYGIENE_DIR"
# Claude Code keeps native memory under ~/.claude/projects/<repo path with non-alphanumerics as "-">/memory/
DEFAULT_MEMORY = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(REPO)) / "memory" / "MEMORY.md"

# Status sets.
TASK_TERMINAL = frozenset({"completed", "done", "cancelled", "dropped", "完了"})
TASK_DEFERRED = frozenset({"deferred"})
TASK_OPEN_KNOWN = frozenset({"pending", "in_progress", "blocked", "active", None})
LAYER_DONE = frozenset({"completed", "done"})
LAYER_OPEN = frozenset({"active", "blocked", "pending_inception", "pending_init", "pending"})
LAYER_PARKED = frozenset({"deferred"})
REGISTRY_DONE = "completed"
REG_TASK_DONE = "完了"
# intent status_map (pending→未着手 / in_progress→進行中 / blocked→未着手); others → 未着手
REG_TASK_MAP = {"in_progress": "進行中", "active": "進行中"}
# Registry tasks.status vocabulary. Japanese (完了/進行中/未着手) or English (the schema created by AI-PLC's
# init_db.py: planned/active/completed/paused). Detected from the CHECK constraint of the tasks.status column;
# Japanese when it cannot be told (the historical behaviour).
REG_VOCAB = {
    "ja": {"done": "完了", "in_progress": "進行中", "other": "未着手"},
    "en": {"done": "completed", "in_progress": "active", "other": "planned"},
}
REG_TASK_DONE_ALL = frozenset({"完了", "completed"})  # a Registry task row in either vocabulary counts as done
_STATUS_CHECK_RE = re.compile(r"\bstatus\s+TEXT\b[^,]*?\bCHECK\s*\(\s*status\s+IN\s*\(([^)]*)\)", re.I | re.S)

KINDS = [  # order = primary priority
    "intent_done_registry_open",
    "all_tasks_done_unclosed",
    "completed_project_open_tasks",
    "folder_missing",
    "stale",
    "registry_closed_layer_open",
    "task_status_mismatch",
    "registry_task_missing",
    "registry_missing",
]
REQUIRED_KINDS = KINDS[:5]
WATCH_DAYS = 14
NOTION_RE = re.compile(r"(notion\.so|app\.notion\.com|notion\.site)", re.IGNORECASE)
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MEM_SCOPE_RE = re.compile(r"\bL-?\d{3,4}(?:-[A-Za-z0-9]+)*")
TODO_SCOPE_RE = re.compile(r"scope:\s*(L-?[\w-]+)")
TODO_LAYER_RE = re.compile(r"layer:\s*(\S+)")


# ---------------------------------------------------------------- helpers
def norm(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s == REG_TASK_DONE else s.lower()


def to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if v is None:
        return None
    try:
        return date.fromisoformat(str(v).strip().strip("'\"")[:10])
    except ValueError:
        return None


YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)  # libyaml when available (same safe subset, ~10x faster;
# the exception class name recorded in info.unreadable may differ between libyaml and the pure-Python loader)


def load_yaml(path: Path):
    """Return (data, error). Never raises."""
    try:
        with path.open(encoding="utf-8") as f:
            return yaml.load(f, Loader=YAML_LOADER), None
    except Exception as e:  # yaml.YAMLError, UnicodeDecodeError, OSError
        return None, type(e).__name__


def open_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{urllib.parse.quote(str(Path(db_path).resolve()))}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    return conn


def goal_text(intent: dict) -> str:
    g = intent.get("goal")
    if isinstance(g, dict):
        return str(g.get("description") or "")
    return str(g or "")


def detect_task_vocab(conn):
    """'ja' / 'en' / None from the CHECK(status IN (...)) of the tasks.status column only (not the whole CREATE
    statement: a column named completed_at must not make a Japanese schema look English). Japanese is tested
    first."""
    try:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone()
    except sqlite3.Error:
        return None
    m = _STATUS_CHECK_RE.search((row[0] if row else None) or "")
    if not m:
        return None
    vals = m.group(1)
    if "'完了'" in vals:
        return "ja"
    if "'completed'" in vals:
        return "en"
    return None


def layer_status_map(layer):
    """status_map of the first sync_targets entry with type: sqlite in the Layer's intent.yaml (or None)."""
    if layer is None:
        return None
    targets = layer.intent.get("sync_targets")
    for st in targets if isinstance(targets, list) else []:
        if isinstance(st, dict) and str(st.get("type") or "").strip().lower() == "sqlite":
            sm = st.get("status_map")
            if isinstance(sm, dict) and sm:
                return {str(k): str(v) for k, v in sm.items() if v is not None}
    return None


def task_vocab(db_vocab, layer=None):
    """Registry task vocabulary for one Layer: {done, in_progress, other, map, done_set}.

    The DB decides. A Layer's sync_targets status_map is used only when the DB is English or cannot be told
    (a Japanese DB keeps the historical mapping, so Layers carrying their own status_map do not change it)."""
    v = dict(REG_VOCAB[db_vocab or "ja"])
    sm = layer_status_map(layer) if db_vocab in ("en", None) else None
    v["map"] = sm or {}
    v["done_set"] = REG_TASK_DONE_ALL | ({sm["completed"]} if sm and sm.get("completed") else set())
    return v


def reg_task_target(backlog_status, vocab=None):
    v = vocab or task_vocab("ja")
    sm = v.get("map") or {}
    if backlog_status in TASK_TERMINAL:
        return sm.get("completed") or v["done"]
    if backlog_status in ("in_progress", "active"):
        return sm.get("in_progress") or v["in_progress"]
    if backlog_status in sm:
        return sm[backlog_status]
    return sm.get("pending") or v["other"]


# ---------------------------------------------------------------- Layer loading
class Layer:
    def __init__(self, root: Path, folder: Path):
        self.root = root
        self.folder = folder
        self.rel = folder.relative_to(root).as_posix()
        self.errors = []  # (file, error)
        self.intent, err = load_yaml(folder / "intent.yaml")
        if err or not isinstance(self.intent, dict):
            self.errors.append(("intent.yaml", err or "not_a_mapping"))
            self.intent = {}
        bpath = folder / "backlog.yaml"
        self.backlog = {}
        if bpath.is_file():
            data, err = load_yaml(bpath)
            if err or not isinstance(data, (dict, type(None))):
                self.errors.append(("backlog.yaml", err or "not_a_mapping"))
            else:
                self.backlog = data or {}
        self.scope_id = str(self.intent.get("scope_id") or "").strip() or None
        self.status_raw = self.intent.get("status")
        self.status = norm(self.status_raw)
        raw_tasks = self.backlog.get("tasks")
        self.tasks = []  # [(task_id or None, status_norm, completed_at)]
        self.raw_tasks = []  # the task dicts (read only; used for the Jev status text)
        for t in raw_tasks if isinstance(raw_tasks, list) else []:
            if isinstance(t, dict):
                self.raw_tasks.append(t)
                tid = t.get("id", t.get("task_id"))
                self.tasks.append((str(tid).strip() if tid is not None else None, norm(t.get("status")),
                                   t.get("completed_at")))
        self.terminal = sum(1 for _, s, _ in self.tasks if s in TASK_TERMINAL)
        self.deferred = sum(1 for _, s, _ in self.tasks if s in TASK_DEFERRED)
        self.open = len(self.tasks) - self.terminal - self.deferred
        self.unknown_task_status = sorted({str(s) for _, s, _ in self.tasks
                                           if s not in TASK_TERMINAL | TASK_DEFERRED | TASK_OPEN_KNOWN})
        summary = self.backlog.get("summary")
        self.summary_has_status = isinstance(summary, dict) and "status" in summary
        self.summary_status = summary.get("status") if self.summary_has_status else None
        # last touched: newest of backlog mtime and max tasks[].completed_at. intent.yaml mtime is used only
        # when there is no backlog.yaml: editing intent metadata (e.g. adding `jev_monitor: true`, which the report
        # itself suggests) is not work and must not hide a stale Layer
        mt = [datetime.fromtimestamp(p.stat().st_mtime).date()
              for p in ((bpath,) if bpath.is_file() else (folder / "intent.yaml",))]
        ca = [d for d in (to_date(c) for _, _, c in self.tasks) if d]
        m, c = (max(mt) if mt else None), (max(ca) if ca else None)
        if c and (not m or c > m):
            self.last_touched, self.last_touched_source = c, "completed_at"
        else:
            self.last_touched, self.last_touched_source = m, "mtime"

    @property
    def all_terminal(self):
        return bool(self.tasks) and self.terminal == len(self.tasks)

    @property
    def deferred_only_remaining(self):
        return bool(self.tasks) and self.open == 0 and self.deferred > 0

    def child_refs(self):
        """[(scope_id or None, status_norm or None)] from backlog.sublayers and intent.sub_agent_scopes."""
        out = []
        for src in (self.backlog.get("sublayers"), self.intent.get("sub_agent_scopes")):
            for x in src if isinstance(src, list) else []:
                if isinstance(x, dict):
                    out.append((x.get("scope_id"), norm(x.get("status"))))
                elif isinstance(x, str):
                    m = MEM_SCOPE_RE.search(x)
                    st = "completed" if "completed" in x.lower() else None
                    out.append((m.group(0) if m else None, st))
        return out


SCAN_SKIP_DIRS = frozenset({"Documents", "node_modules", "__pycache__", "venv", "site-packages"})


def iter_intent_files(bdir: Path):
    """Sorted intent.yaml paths below bdir. Pruned while walking (rglob was slow on large trees): Documents/
    copies, hidden folders (e.g. Flow/.worktrees/ git worktrees) and dependency folders (node_modules etc.;
    an intent.yaml there is never a Layer). Symlinks are not followed (same as Path.rglob)."""
    found = []
    for dp, dns, fns in os.walk(bdir):
        dns[:] = [d for d in dns if not d.startswith(".") and d not in SCAN_SKIP_DIRS]
        if "intent.yaml" in fns:
            found.append(Path(dp) / "intent.yaml")
    return sorted(found)


def scan_intents(root: Path):
    """scope_id -> [Layer], Flow first. Copies are skipped: any Documents/ folder and any hidden
    folder below Flow/ or .ai-plc/ (e.g. Flow/.worktrees/ git worktrees)."""
    index, flow_layers, unreadable = {}, [], []
    for base in ("Flow", ".ai-plc"):
        bdir = root / base
        if not bdir.is_dir():
            continue
        for p in iter_intent_files(bdir):
            layer = Layer(root, p.parent)
            for f, err in layer.errors:
                unreadable.append({"path": f"{layer.rel}/{f}", "error": err})
            if not layer.scope_id:
                continue
            index.setdefault(layer.scope_id, []).append(layer)
            if base == "Flow":
                flow_layers.append(layer)
    return index, flow_layers, unreadable


def resolve(row, root: Path, index):
    """Return (layer or None, resolved_via, reason, duplicate_folders, note)."""
    sid = row["scope_id"]
    url = (row["top_page_url"] or "").strip()
    cands = index.get(sid, [])
    dups = [l.rel for l in cands] if len(cands) > 1 else []
    reason, note = None, None
    if not url:
        reason = "empty_url"
    elif NOTION_RE.search(url):
        reason = "notion_only"
    elif re.match(r"^https?://", url):
        reason = "path_not_found"
    else:
        rel = url
        for prefix in (str(root).rstrip("/") + "/", str(REPO).rstrip("/") + "/"):
            if rel.startswith(prefix):
                rel = rel[len(prefix):]
                break
        if rel.startswith("/"):
            try:
                rel = Path(rel).resolve().relative_to(root).as_posix()
            except (ValueError, OSError):
                pass
        rel = rel.rstrip("/")
        if rel.lower().endswith(".md"):
            rel = rel.rsplit("/", 1)[0] if "/" in rel else ""
        folder = (root / rel) if rel and not rel.startswith("/") and ".." not in Path(rel).parts else None
        if (folder is not None and (folder / "intent.yaml").is_file() and "Documents" not in Path(rel).parts
                and not any(x.startswith(".") for x in Path(rel).parts[1:])):
            layer = next((l for l in cands if l.folder == folder), None) or Layer(root, folder)
            if layer.scope_id == sid:
                return layer, "url", None, dups, None
            note = "url_scope_mismatch"
            reason = "path_not_found"
        else:
            reason = "legacy_aipo" if folder is not None and folder.is_dir() else "path_not_found"
    if cands:
        return cands[0], "scope_index", None, dups, note
    return None, "none", reason, dups, note


# ---------------------------------------------------------------- confidentiality
class Confidential:
    """fail-closed: redact() over Layer metadata, parent inheritance (5 levels), intent declarations."""

    def __init__(self, projects, layers_by_scope):
        self.projects = projects
        self.layers = layers_by_scope
        self.cache = {}

    def _own(self, sid):
        row = self.projects.get(sid)
        layer = self.layers.get(sid)
        texts = [sid]
        if row is not None:
            texts += [row["name"] or "", row["goal"] or "", row["top_page_url"] or ""]
        if layer is not None:
            it = layer.intent
            texts += [layer.rel, str(it.get("scope_name") or ""), goal_text(it)]
            ext = it.get("extensions")
            if isinstance(ext, list) and "privacy" in [str(e).strip().lower() for e in ext]:
                return "privacy_extension"
            if it.get("jev_monitor") is False:
                return "jev_monitor_false"
        ok, _ = jev_client.redact("\n".join(texts))
        return None if ok else "redact"

    def parent_of(self, sid):
        row = self.projects.get(sid)
        layer = self.layers.get(sid)
        p = (row["parent_scope"] if row is not None else None) or (layer.intent.get("parent_scope") if layer else None)
        p = str(p).strip() if p else None
        return p if p and p.lower() not in ("null", "none") and p != sid else None

    def check(self, sid):
        if sid in self.cache:
            return self.cache[sid]
        reason = self._own(sid)
        cur, depth = sid, 0
        while reason is None and depth < 5:
            cur = self.parent_of(cur)
            if not cur:
                break
            if self._own(cur):
                reason = f"parent:{cur}"
            depth += 1
        self.cache[sid] = reason
        return reason


# ---------------------------------------------------------------- Jev hint for stale rows
JEV_USE_CASE = "status_audit"
JEV_CHOICES = {  # label -> description. Only these labels are ever recorded.
    "done": "実質完了（ゴールは達成済みで、残タスクは不要か形だけ）",
    "handed_off": "他Layerへ引き継ぎ済み（残りの作業は別のプロジェクトに移っている）",
    "stalled": "本当に停滞（ゴール未達で、残タスクが手つかずのまま止まっている）",
    "unknown": "判断不能（この情報だけでは決められない）",
}
JEV_QUESTION = ("This is the status of a project that has not been updated for a long time. "
                "Which best describes it: done, handed_off, stalled or unknown? Choose unknown if unsure.")
JEV_NOTE_MAX = 400
DONE_TASK = frozenset({"completed", "done", "完了"})


def _one_line(v, n):
    s = " ".join(str(v or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def jev_state(layer, days):
    """Status text sent to Jev: goal (1 line), last completed task's result/status_note (<=400 chars),
    progress X/Y and days since the last update. Nothing else from the Layer is sent."""
    done = [t for t in layer.raw_tasks if norm(t.get("status")) in DONE_TASK]
    last = None
    if done:
        dated = [(to_date(t.get("completed_at")), i, t) for i, t in enumerate(done) if to_date(t.get("completed_at"))]
        last = max(dated, key=lambda x: x[:2])[2] if dated else done[-1]  # same date -> later in the list
    lines = [f"ゴール: {_one_line(goal_text(layer.intent), 200)}"]
    if last is None:
        lines.append("最後の完了タスク: なし")
    else:
        note = last.get("result") or last.get("status_note")
        lines.append(f"最後の完了タスク: {_one_line(last.get('name') or last.get('id'), 80)}"
                     + (f" — 結果: {_one_line(note, JEV_NOTE_MAX)}" if note else "（結果の記録なし）"))
    lines.append(f"進捗: {layer.terminal}/{len(layer.tasks)} タスク終了（未完了 {layer.open}）")
    lines.append(f"停滞日数: 最終更新から {days} 日")
    return "\n".join(lines)


def jev_questions():
    return {"status": {"type": "choice", "instructions": JEV_QUESTION, "criteria": dict(JEV_CHOICES)}}


def jev_hint(c, layer, ask):
    """Return the `jev` field for one stale candidate. Never raises; never touches proposed_changes."""
    if c["confidential"]:
        return {"status": "not_eligible", "reason": "confidential", "label": "Jev対象外（機密）— コード判定のみ"}
    if not c["jev_opt_in"]:
        return {"status": "not_eligible", "reason": "no_opt_in", "label": "Jev対象外（opt-inなし）— コード判定のみ"}
    if layer is None:
        return {"status": "not_eligible", "reason": "no_layer", "label": "Jev対象外（Layer なし）— コード判定のみ"}
    state, questions = jev_state(layer, c["days_since_touch"]), jev_questions()
    ok, _ = jev_client.redact(state + "\n" + json.dumps(questions, ensure_ascii=False))  # last gate
    if not ok:
        return {"status": "skipped", "reason": "redact", "label": "スキップ（redact）"}
    try:
        rec = ask(state, questions, JEV_USE_CASE, scope_id=c["scope_id"], task_id="stale", timeout=10, retries=1)
    except Exception as e:  # never break the report
        rec = {"action": f"skipped(unavailable:internal_{type(e).__name__})"}
    action = str((rec or {}).get("action") or "skipped(unavailable:no_record)")
    # a request left the machine unless ask() stopped before the HTTP call (redacted / no key / internal error)
    sent = not any(x in action for x in ("skipped(redacted", "no_key", "internal_", "no_record"))
    if action != "answered":
        reason = "redact" if action.startswith("skipped(redacted") else "unavailable"
        return {"status": "skipped", "reason": reason, "action": action, "sent": sent,
                "decision_id": (rec or {}).get("decision_id"), "label": f"スキップ（{reason}）"}
    ans = ((rec.get("answers") or {}).get("status")) or {}
    probs = ans.get("probabilities") if isinstance(ans, dict) else None
    probs = {k: v for k, v in (probs or {}).items()
             if k in JEV_CHOICES and isinstance(v, (int, float)) and not isinstance(v, bool)}
    choice = ans.get("choice") if isinstance(ans, dict) and ans.get("choice") in JEV_CHOICES else None
    if choice is None and not probs:
        return {"status": "skipped", "reason": "unavailable", "action": "answered_without_label", "sent": True,
                "decision_id": rec.get("decision_id"), "label": "スキップ（unavailable）"}
    if choice is None:
        choice = max(probs, key=probs.get)
    p = probs.get(choice)
    return {"status": "answered", "sent": True, "choice": choice, "probability": p, "probabilities": probs,
            "decision_id": rec.get("decision_id"), "cost": rec.get("cost"),
            "label": f"ヒント: {choice}" + (f" p={p:.2f}" if p is not None else "")
                     + f"（decision_id={rec.get('decision_id')}）"}


# ---------------------------------------------------------------- audit
def audit(db_path: Path, root: Path, today: date, stale_days: int = 30,
          todo_path: Path | None = None, memory_path: Path | None = None, jev: bool = False, ask=None,
          scope_filter=None):
    """scope_filter: a set of scope ids (or C-hash ids). When given, only candidates of those scopes are
    built (so --jev asks only about them); detection itself still reads everything (confidentiality inherits from
    parents). main() then applies filter_report() for the info section."""
    conn = open_ro(db_path)
    try:
        projects = {r["scope_id"]: r for r in conn.execute(
            "SELECT scope_id, name, goal, status, parent_scope, top_page_url, updated_at FROM projects ORDER BY scope_id")}
        reg_tasks = {}
        for r in conn.execute("SELECT scope_id, task_id, status FROM tasks ORDER BY id"):
            reg_tasks.setdefault(r["scope_id"], {})[str(r["task_id"]).strip()] = r["status"]
        db_vocab = detect_task_vocab(conn)
    finally:
        conn.close()

    index, flow_layers, unreadable = scan_intents(root)
    info = {k: [] for k in ("todo_points_to_done", "todo_layer_path_missing", "memory_label_mismatch",
                            "unreadable", "no_tasks", "duplicate_folders", "unknown_status", "watch",
                            "deferred_only_remaining", "backlog_task_missing", "orphan_registry_tasks",
                            "updated_at_format", "url_scope_mismatch", "task_without_id")}
    info["unreadable"] = unreadable
    for sid, ls in sorted(index.items()):
        if len(ls) > 1:
            info["duplicate_folders"].append({"scope_id": sid, "folders": [l.rel for l in ls]})

    resolved = {}  # scope_id -> (layer, via, reason, dups)
    for sid, row in projects.items():
        layer, via, reason, dups, note = resolve(row, root, index)
        resolved[sid] = (layer, via, reason, dups)
        if note:
            info["url_scope_mismatch"].append({"scope_id": sid})
        ua = row["updated_at"] or ""
        if ua and not TS_RE.match(ua):
            info["updated_at_format"].append({"scope_id": sid, "updated_at": ua})
    layers_by_scope = {sid: v[0] for sid, v in resolved.items() if v[0] is not None}
    for sid, ls in index.items():
        layers_by_scope.setdefault(sid, ls[0])
    conf = Confidential(projects, layers_by_scope)
    for sid in sorted(set(reg_tasks) - set(projects)):
        info["orphan_registry_tasks"].append({"scope_id": sid, "rows": len(reg_tasks[sid])})

    raw = []  # (sid, kind, reason, evidence, action, changes, extra)

    def add(sid, kind, reason, evidence, action, changes, **extra):
        raw.append((sid, kind, reason, evidence, action, changes, extra))

    def touched(sid, layer):
        """Newest last-touched date over the resolved Layer and every copy of the same scope. A copy's mtime may be
        the time it was copied, not worked on; that errs toward missing a stale Layer, never toward closing one
        (same policy as last_touched). Returns (date, source) or (None, None)."""
        cands = [(l.last_touched, l.last_touched_source) for l in [layer] + index.get(sid, []) if l.last_touched]
        return max(cands) if cands else (None, None)

    dup_disagree = {sid for sid, ls in index.items()
                    if len(ls) > 1 and len({(l.status, l.terminal, l.deferred, len(l.tasks)) for l in ls}) > 1}
    for d in info["duplicate_folders"]:
        d["disagree"] = d["scope_id"] in dup_disagree

    for sid, row in projects.items():
        layer, via, freason, dups = resolved[sid]
        class3_ids = set()
        rstat = norm(row["status"])
        rtasks = reg_tasks.get(sid, {})
        reg_open = rstat != REGISTRY_DONE
        proj_change = {"target": "registry.projects", "scope_id": sid, "field": "status",
                       "from": row["status"], "to": REGISTRY_DONE}
        tv = task_vocab(db_vocab, layer)

        # 3: completed project with non-完了 Registry task rows (needs no Layer)
        if not reg_open:
            open_rows = sorted(t for t, s in rtasks.items() if s not in tv["done_set"])
            if open_rows:
                bl = {t: s for t, s, _ in layer.tasks} if layer else {}
                ch = [{"target": "registry.tasks", "scope_id": sid, "task_id": t, "field": "status",
                       "from": rtasks[t], "to": reg_task_target("completed", tv)} for t in open_rows
                      if bl.get(t) in TASK_TERMINAL]
                class3_ids = {x["task_id"] for x in ch}
                add(sid, "completed_project_open_tasks",
                    f"Registry は completed だが tasks に完了以外の行が {len(open_rows)} 件",
                    {"projects.status": row["status"], "open_task_rows": open_rows,
                     "backlog_status": {t: bl.get(t) for t in open_rows}},
                    "registry_task_sync" if ch else "record_only", ch)

        if layer is None:
            if reg_open:  # 4: folder_missing (Registry open rows only)
                add(sid, "folder_missing", f"Layer フォルダを解決できない（{freason}）",
                    {"reason": freason, "top_page_url_kind": freason}, "record_only", [], folder_reason=freason)
            continue

        ist = layer.status
        if ist not in LAYER_DONE | LAYER_OPEN | LAYER_PARKED:
            info["unknown_status"].append({"scope_id": sid, "where": "intent.status", "value": str(layer.status_raw)})
        if layer.unknown_task_status:
            info["unknown_status"].append({"scope_id": sid, "where": "backlog.tasks[].status",
                                           "values": layer.unknown_task_status})
        if any(t is None for t, _, _ in layer.tasks):
            info["task_without_id"].append({"scope_id": sid})
        lt, lt_src = touched(sid, layer)
        days = (today - lt).days if lt else None
        intent_change = {"target": "intent", "path": f"{layer.rel}/intent.yaml", "field": "status",
                         "from": layer.status_raw, "to": "completed"}
        summary_change = ({"target": "backlog.summary", "path": f"{layer.rel}/backlog.yaml", "field": "status",
                           "from": layer.summary_status, "to": "completed"}
                          if layer.summary_has_status and norm(layer.summary_status) not in LAYER_DONE else None)
        layer_close_changes = [intent_change] + ([summary_change] if summary_change else [])
        closing = False

        # 1
        if ist in LAYER_DONE and reg_open:
            add(sid, "intent_done_registry_open", f"intent は {layer.status_raw} だが Registry は {row['status']}",
                {"intent.status": layer.status_raw, "projects.status": row["status"]}, "registry_close", [proj_change])
            closing = True
        # 2
        if reg_open and ist not in LAYER_DONE and layer.all_terminal:
            open_children = []
            for csid, cst in layer.child_refs():
                if cst is None and csid and csid in layers_by_scope:
                    cst = layers_by_scope[csid].status
                if cst in LAYER_OPEN:
                    open_children.append(csid or "?")
            add(sid, "all_tasks_done_unclosed",
                f"backlog の全 {len(layer.tasks)} タスクが終端だが intent は {layer.status_raw}・Registry は {row['status']}",
                {"intent.status": layer.status_raw, "projects.status": row["status"],
                 "tasks": f"{layer.terminal}/{len(layer.tasks)}", "has_open_child": bool(open_children),
                 "open_children": open_children},
                "layer_close", layer_close_changes + [proj_change], has_open_child=bool(open_children))
            closing = True
        if reg_open and ist not in LAYER_DONE and layer.deferred_only_remaining:
            info["deferred_only_remaining"].append({"scope_id": sid, "tasks": len(layer.tasks),
                                                    "deferred": layer.deferred})
        # 5 stale / watch
        if reg_open and ist in LAYER_OPEN and (layer.open > 0 or not layer.tasks) and days is not None:
            if days >= stale_days:
                add(sid, "stale", f"最終更新から {days} 日（しきい値 {stale_days} 日）・未完了タスク {layer.open} 件",
                    {"days_since_touch": days, "last_touched": lt.isoformat(), "last_touched_source": lt_src,
                     "tasks": f"{layer.terminal}/{len(layer.tasks)}", "open": layer.open,
                     "registry.updated_at": row["updated_at"]},
                    "review_stale", [])
            elif days >= WATCH_DAYS:
                info["watch"].append({"scope_id": sid, "days_since_touch": days})
        if reg_open and not layer.tasks:
            info["no_tasks"].append({"scope_id": sid, "days_since_touch": days})
        # 6
        if not reg_open and ist not in LAYER_DONE:
            if layer.all_terminal:
                add(sid, "registry_closed_layer_open",
                    f"Registry は completed だが intent は {layer.status_raw}（backlog 全終端）",
                    {"projects.status": row["status"], "intent.status": layer.status_raw,
                     "backlog_all_terminal": True, "tasks": f"{layer.terminal}/{len(layer.tasks)}"},
                    "layer_close", layer_close_changes, backlog_all_terminal=True)
                closing = True
            else:
                add(sid, "registry_closed_layer_open",
                    f"Registry は completed だが intent は {layer.status_raw}（backlog 非全終端）",
                    {"projects.status": row["status"], "intent.status": layer.status_raw,
                     "backlog_all_terminal": False, "tasks": f"{layer.terminal}/{len(layer.tasks)}",
                     "deferred": layer.deferred},
                    "record_only", [], backlog_all_terminal=False,
                    alternatives=[{"action": "layer_close", "proposed_changes": layer_close_changes},
                                  {"action": "registry_reopen", "proposed_changes": [
                                      {"target": "registry.projects", "scope_id": sid, "field": "status",
                                       "from": row["status"], "to": "active"}]}])
        # 7 / 8
        bl = {t: s for t, s, _ in layer.tasks if t}
        # task ids already proposed by class 3 are not repeated here (one change per Registry row)
        mism = sorted(t for t in bl if t in rtasks and t not in class3_ids
                      and (bl[t] in TASK_TERMINAL) != (rtasks[t] in tv["done_set"]))
        if mism:
            add(sid, "task_status_mismatch", f"backlog と Registry で終端かどうかが食い違うタスク {len(mism)} 件",
                {"tasks": {t: {"backlog": bl[t], "registry": rtasks[t]} for t in mism}}, "registry_task_sync",
                [{"target": "registry.tasks", "scope_id": sid, "task_id": t, "field": "status",
                  "from": rtasks[t], "to": reg_task_target(bl[t], tv),
                  **({"mapped_from": bl[t]} if bl[t] in ("cancelled", "dropped") else {})} for t in mism])
        missing = sorted(t for t in bl if t not in rtasks)
        if missing:
            add(sid, "registry_task_missing", f"backlog にあって Registry tasks に無いタスク {len(missing)} 件",
                {"missing": missing, "registry_rows": len(rtasks), "backlog_tasks": len(bl)},
                "__closing__", [{"target": "registry.tasks", "op": "add", "scope_id": sid, "task_id": t,
                                 "field": "status", "from": None, "to": reg_task_target(bl[t], tv)} for t in missing])
        extra_reg = sorted(t for t in rtasks if t not in bl)
        if extra_reg and layer.tasks:
            info["backlog_task_missing"].append({"scope_id": sid, "task_ids": extra_reg})
        resolved[sid] = (layer, via, freason, dups, closing, days)

    # 9: Flow Layer without Registry row
    seen = set()
    for layer in flow_layers:
        sid = layer.scope_id
        if sid in projects or sid in seen:
            continue
        seen.add(sid)
        lt, lt_src = touched(sid, layer)
        days = (today - lt).days if lt else None
        add(sid, "registry_missing", "Layer（Flow の intent）はあるが Registry projects に無い",
            {"intent.status": layer.status_raw, "tasks": f"{layer.terminal}/{len(layer.tasks)}",
             "days_since_touch": days}, "record_only",
            [{"target": "registry.projects", "op": "add", "scope_id": sid, "field": "status", "from": None,
              "to": REGISTRY_DONE if layer.status in LAYER_DONE else "active"}])
        resolved[sid] = (layer, "flow_scan", None, [l.rel for l in index.get(sid, [])] if len(index.get(sid, [])) > 1 else [],
                         False, days)

    # ---- assemble candidates
    kinds_by_scope = {}
    for sid, kind, *_ in raw:
        kinds_by_scope.setdefault(sid, []).append(kind)
    candidates = []
    for sid, kind, reason, evidence, action, changes, extra in raw:
        if scope_filter is not None and sid not in scope_filter and hash_id(sid) not in scope_filter:
            continue
        tup = resolved.get(sid)
        layer, via, freason, dups = tup[:4]
        closing = tup[4] if len(tup) > 4 else False
        days = tup[5] if len(tup) > 5 else None
        if action == "__closing__":
            action = "add_registry_rows" if closing else "record_only"
        ks = sorted(set(kinds_by_scope[sid]), key=KINDS.index)
        row = projects.get(sid)
        creason = conf.check(sid)
        opt_in = bool(layer is not None and layer.intent.get("jev_monitor") is True)
        eligible = kind == "stale" and opt_in and creason is None
        rt = reg_tasks.get(sid, {})
        last = touched(sid, layer) if layer else (None, None)
        c = {
            "candidate_id": f"{sid}:{kind}",
            "scope_id": sid,
            "kind": kind,
            "primary": ks[0] == kind,
            "also": [k for k in ks if k != kind],
            "layer_path": layer.rel if layer else None,
            "resolved_via": via,
            "duplicate_folders": dups,
            "registry": ({"status": row["status"], "updated_at": row["updated_at"], "top_page_url": row["top_page_url"],
                          "parent_scope": row["parent_scope"]} if row is not None else None),
            "intent": {"status": layer.status_raw} if layer else None,
            "backlog": ({"tasks_total": len(layer.tasks), "terminal": layer.terminal, "deferred": layer.deferred,
                         "open": layer.open, "deferred_only_remaining": layer.deferred_only_remaining,
                         "has_open_child": extra.get("has_open_child", False),
                         "summary_status": layer.summary_status} if layer else None),
            "registry_tasks": {"total": len(rt), "done": sum(1 for s in rt.values() if s in REG_TASK_DONE_ALL)},
            "last_touched": last[0].isoformat() if last[0] else None,
            "last_touched_source": last[1],
            "days_since_touch": days,
            "confidential": creason is not None,
            "confidential_reason": creason,
            "jev_opt_in": opt_in,
            "jev_eligible": eligible,
            "jev_note": ("Jev対象" if eligible else
                         ("Jev対象外（機密）" if kind == "stale" and creason else
                          ("Jev対象外（opt-in なし）" if kind == "stale" else "Jev対象外（コード判定のみ）"))),
            "reason": reason,
            "evidence": evidence,
            "recommended_action": action,
            "proposed_changes": changes,
            "jev": None,
        }
        for k in ("folder_reason", "backlog_all_terminal", "alternatives"):
            if k in extra:
                c[k] = extra[k]
        # copies of the same scope disagree (never pick one silently) -> nothing is proposed
        c["duplicate_disagree"] = sid in dup_disagree
        if c["duplicate_disagree"]:
            c["evidence"] = {**evidence, "duplicate_disagree": True, "duplicate_folders": len(index.get(sid, []))}
            if changes:
                c["alternatives"] = c.get("alternatives", []) + [{"action": action, "proposed_changes": changes}]
            c["recommended_action"], c["proposed_changes"] = "record_only", []
            c["reason"] = reason + "（同じ scope のフォルダが複数あり中身が食い違う。どれが正か人が確認）"
        if jev and kind == "stale":
            c["jev"] = jev_hint(c, layer, ask or jev_client.ask)
        candidates.append(c)
    candidates.sort(key=lambda c: (KINDS.index(c["kind"]), c["scope_id"]))
    stale_rows = [c for c in candidates if c["kind"] == "stale"]
    jev_summary = {"enabled": bool(jev), "use_case": JEV_USE_CASE,
                   "stale": len(stale_rows),
                   "addable_by_opt_in": sum(1 for c in stale_rows if not c["confidential"] and not c["jev_opt_in"])}
    if jev:
        js = [c["jev"] for c in stale_rows]
        costs = [j["cost"] for j in js if j.get("status") == "answered" and isinstance(j.get("cost"), (int, float))]
        jev_summary.update({
            "eligible": sum(1 for c in stale_rows if c["jev_eligible"]),
            "sent": sum(1 for j in js if j.get("sent")),
            "answered": sum(1 for j in js if j["status"] == "answered"),
            "skipped_redact": sum(1 for j in js if j["status"] == "skipped" and j["reason"] == "redact"),
            "skipped_unavailable": sum(1 for j in js if j["status"] == "skipped" and j["reason"] == "unavailable"),
            "not_eligible_confidential": sum(1 for j in js if j.get("reason") == "confidential"),
            "not_eligible_no_opt_in": sum(1 for j in js if j.get("reason") == "no_opt_in"),
            "not_eligible_other": sum(1 for j in js if j.get("reason") == "no_layer"),
            "cost_total": round(sum(costs), 8) if costs else None,
        })

    # ---- info: todo.md / MEMORY.md (read only)
    def done_state(sid):
        row = projects.get(sid)
        layer = layers_by_scope.get(sid)
        return {"registry": row["status"] if row is not None else None,
                "intent": layer.status_raw if layer else None,
                "backlog_all_terminal": layer.all_terminal if layer else None,
                "deferred": layer.deferred if layer else None}

    if todo_path and Path(todo_path).is_file():
        for line in Path(todo_path).read_text(encoding="utf-8").splitlines():
            sm, lm = TODO_SCOPE_RE.search(line), TODO_LAYER_RE.search(line)
            if lm and not (root / lm.group(1).rstrip("/") / "intent.yaml").is_file():
                info["todo_layer_path_missing"].append({"scope_id": sm.group(1) if sm else None, "layer": lm.group(1)})
            if sm:
                sid = sm.group(1)
                st = done_state(sid)
                if (norm(st["intent"]) in LAYER_DONE or norm(st["registry"]) == REGISTRY_DONE
                        or st["backlog_all_terminal"]):
                    info["todo_points_to_done"].append({"scope_id": sid, **st, "duplicate_disagree": sid in dup_disagree,
                                                        "action": "todo.md の該当行を手で直してください"})
    if memory_path and Path(memory_path).is_file():
        for line in Path(memory_path).read_text(encoding="utf-8").splitlines():
            hits = sorted((line.find(lb), lb) for lb in ("完了PJ", "進行中PJ") if lb in line)
            label = hits[0][1] if hits else None
            m = MEM_SCOPE_RE.search(line.split("—")[0]) or MEM_SCOPE_RE.search(line)
            if not label or not m:
                continue
            sid = m.group(0)
            st = done_state(sid)
            if st["registry"] is None:
                info["memory_label_mismatch"].append({"scope_id": sid, "label": label, "why": "scope_not_in_registry"})
            elif label == "完了PJ" and norm(st["registry"]) != REGISTRY_DONE:
                info["memory_label_mismatch"].append({"scope_id": sid, "label": label, "why": "registry_not_completed",
                                                      "registry": st["registry"], "intent": st["intent"]})
            elif label == "進行中PJ" and (norm(st["registry"]) == REGISTRY_DONE or norm(st["intent"]) in LAYER_DONE):
                info["memory_label_mismatch"].append({"scope_id": sid, "label": label, "why": "registry_or_intent_completed",
                                                      "registry": st["registry"], "intent": st["intent"]})

    # masking data: every known scope that is confidential and every folder of such a scope. Keys starting
    # with "_" are internal: public_report() drops them before anything is written or printed
    known = set(projects) | set(index) | {str(r["parent_scope"]).strip() for r in projects.values()
                                          if r["parent_scope"] and str(r["parent_scope"]).strip()}
    conf_scopes = {s for s in known if conf.check(s)}
    conf_paths = {l.rel for s in conf_scopes for l in index.get(s, [])}
    conf_paths |= {layers_by_scope[s].rel for s in conf_scopes if s in layers_by_scope}
    by_kind = {k: sum(1 for c in candidates if c["kind"] == k) for k in KINDS}
    by_kind_primary = {k: sum(1 for c in candidates if c["kind"] == k and c["primary"]) for k in KINDS}
    return {
        "generated_at": today.isoformat(),
        "params": {"stale_days": stale_days, "db": str(db_path), "root": str(root), "read_only": True},
        "counts": {
            "by_kind": by_kind,
            "by_kind_primary": by_kind_primary,
            "candidates": len(candidates),
            "scopes": len({c["scope_id"] for c in candidates}),
            "registry_total": len(projects),
            "registry_active": sum(1 for r in projects.values() if norm(r["status"]) == "active"),
            "resolved_via": {v: sum(1 for sid in projects if resolved[sid][1] == v)
                             for v in ("url", "scope_index", "none")},
            "confidential_candidates": sum(1 for c in candidates if c["confidential"]),
            "stale_jev_eligible": sum(1 for c in candidates if c["jev_eligible"]),
            "stale_addable_by_opt_in": jev_summary["addable_by_opt_in"],
            "info": {k: len(v) for k, v in info.items()},
        },
        "jev_summary": jev_summary,
        "candidates": candidates,
        "info": info,
        "_mask": {"scopes": sorted(conf_scopes), "paths": sorted(conf_paths)},
        "_layers": {s: l.rel for s, l in layers_by_scope.items()},
        "_scopes": sorted(known),
    }


# ---------------------------------------------------------------- report
ACTION_JA = {"registry_close": "Registry を completed に", "layer_close": "intent を completed に（→Registry）",
             "registry_task_sync": "Registry tasks を backlog に合わせる", "registry_reopen": "Registry を戻す",
             "add_registry_rows": "Registry に行を追加", "review_stale": "停滞の中身を確認", "record_only": "記録のみ（人が選ぶ）"}
KIND_JA = {"intent_done_registry_open": "1. intent 完了なのに Registry 未完了",
           "all_tasks_done_unclosed": "2. 全タスク完了なのに未クローズ",
           "completed_project_open_tasks": "3. 完了PJに未完了タスク行",
           "folder_missing": "4. Layer フォルダ不明",
           "stale": "5. N日以上更新なし（停滞）",
           "registry_closed_layer_open": "6. Registry 完了なのに intent 未完了",
           "task_status_mismatch": "7. タスク status の食い違い",
           "registry_task_missing": "8. Registry にタスク行が無い",
           "registry_missing": "9. Registry に PJ 行が無い"}


def _ev(ev):
    parts = []
    for k, v in ev.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
            v = v if len(v) <= 80 else v[:77] + "..."
        parts.append(f"{k}={v}")
    return "; ".join(parts).replace("|", "/")


def render_md(report):
    p, cnt = report["params"], report["counts"]
    out = [f"# AI-PLC ステータス監査レポート（{report['generated_at']}）", "",
           f"- 読み取り専用: {p['read_only']} ／ 停滞しきい値: {p['stale_days']} 日 ／ Registry: 全 {cnt['registry_total']} 件・active {cnt['registry_active']} 件",
           f"- 候補: {cnt['candidates']} 行（{cnt['scopes']} scope）／ 機密: {cnt['confidential_candidates']} 行 ／ Jev対象の停滞: {cnt['stale_jev_eligible']} 件",
           "- 自動クローズはしない。反映は承認ファイルに載せた candidate_id だけ（`--apply`、既定 dry-run・`--yes` で書く）。"
           "機密行は scope_id を `C-`+ハッシュで表示し、Layer 名・パスを出さない",
           f"- opt-in（intent.yaml に `jev_monitor: true`）を足すと Jev で分類できる非機密の停滞 Layer: {cnt['stale_addable_by_opt_in']} 件"]
    if p.get("scope_filter"):
        out.append(f"- 絞り込み: `--scope` / `--layer` で {p['scope_filter']} scope に限定（候補・件数・参考欄とも）")
    js = report.get("jev_summary") or {}
    if js.get("enabled"):
        out.append(f"- Jev 分類ヒント（--jev）: 対象 {js['eligible']} 件 → 送信 {js['sent']}（回答 {js['answered']} ／ "
                   f"スキップ（unavailable）{js['skipped_unavailable']}）／ 送る前にスキップ（redact）"
                   f"{js['skipped_redact']} ／ 対象外（機密）"
                   f"{js['not_eligible_confidential']} ／ 対象外（opt-inなし）{js['not_eligible_no_opt_in']} ／ 費用 "
                   f"{js['cost_total'] if js['cost_total'] is not None else '-'}。分類はヒントのみで、閉じる提案は変えない。"
                   "妥当/外れは `python3 .claude/ai-plc-jev/scripts/jev_bt_monitor.py --override <decision_id> accept|reject` で記録")
    else:
        out.append("- Jev: 呼んでいない（`--jev` なし。外部送信 0 件）")
    out += ["",
           "## 分類別件数", "", "| 分類 | 件数 | うち primary |", "| --- | --- | --- |"]
    for k in KINDS:
        out.append(f"| {KIND_JA[k]} (`{k}`) | {cnt['by_kind'][k]} | {cnt['by_kind_primary'][k]} |")
    for k in KINDS:
        rows = [c for c in report["candidates"] if c["kind"] == k]
        if not rows:
            continue
        out += ["", f"## {KIND_JA[k]}", "", "| scope_id | Layer | 経過日数 | 根拠 | 推奨アクション | 機密 | Jev |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        for c in rows:
            name = "（機密のため非表示）" if c["confidential"] else (c["layer_path"].rsplit("/", 1)[-1] if c["layer_path"] else "-")
            d = c["days_since_touch"] if c["days_since_touch"] is not None else "-"
            flag = f"true（{c['confidential_reason']}）" if c["confidential"] else "false"
            out.append(f"| {c['scope_id']} | {name} | {d} | {_ev(c['evidence'])} | "
                       f"{ACTION_JA.get(c['recommended_action'], c['recommended_action'])} | {flag} | "
                       f"{c['jev']['label'] if c.get('jev') else c['jev_note']} |")
    out += ["", "## 参考情報（候補行ではない）", ""]
    for k, items in report["info"].items():
        if not items:
            continue
        out.append(f"- **{k}**（{len(items)}）: " + ", ".join(
            str(i.get("scope_id") or "（パスは report.json 参照）") + (f"({i['why']})" if "why" in i else "")
            + ("(食い違いあり)" if i.get("disagree") or i.get("duplicate_disagree") else "")
            for i in items))
    if report["info"]["todo_points_to_done"]:
        out += ["", "todo.md の行は本レポートでは変更しない。todo.md の該当行を手で直してください。"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- public (masked) view
PATH_MASK = "（機密）"
URL_MASK = "（機密のため非表示）"


def hash_id(sid) -> str:
    """Public id of a confidential scope: "C-" + first 8 hex of sha256(scope_id). Not a secret (scope ids are
    guessable); it keeps names off screens, files and logs. --apply resolves it by re-scanning."""
    return "C-" + hashlib.sha256(str(sid).encode("utf-8")).hexdigest()[:8]


def public_scope(sid, conf_scopes):
    return hash_id(sid) if sid in conf_scopes else sid


def public_candidate_id(c):
    return f"{hash_id(c['scope_id'])}:{c['kind']}" if c["confidential"] else c["candidate_id"]


class Masker:
    """Replaces confidential scope ids and Layer paths in any JSON-like value (fail-closed: over-masking is fine)."""

    TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*")

    def __init__(self, report):
        m = report.get("_mask") or {}
        self.scopes = set(m.get("scopes") or [])
        self.known = set(report.get("_scopes") or []) | self.scopes
        self.paths = sorted(m.get("paths") or [], key=len, reverse=True)

    def _token(self, mm):
        t = mm.group(0)
        if t in self.scopes:
            return hash_id(t)
        if t in self.known:
            return t  # a known non-confidential scope stays readable (e.g. L-0000-2 next to a confidential L-0000)
        parts = t.split("-")
        for i in range(len(parts) - 1, 0, -1):  # unknown id that starts with a confidential scope: hide the prefix
            head = "-".join(parts[:i])
            if head in self.known and head not in self.scopes:
                return t  # longest known prefix is non-confidential (e.g. L-0000-2-T001): keep readable
            if head in self.scopes:
                return hash_id(head) + "-" + "-".join(parts[i:])
        return t

    def text(self, s):
        for p in self.paths:
            s = s.replace(p, PATH_MASK)
        return self.TOKEN_RE.sub(self._token, s) if self.scopes else s

    def deep(self, v, paths_redact=False):
        if isinstance(v, str):
            t = self.text(v)
            if paths_redact and "/" in t and not jev_client.redact(t)[0]:
                return PATH_MASK  # a path that is not under a known Layer but still hits the word list
            return t
        if isinstance(v, list):
            return [self.deep(x, paths_redact) for x in v]
        if isinstance(v, dict):
            return {(self.text(k) if isinstance(k, str) else k): self.deep(x, paths_redact) for k, x in v.items()}
        return v


def public_report(report):
    """The only form of a report that is written or printed: no "_" keys, confidential rows hashed."""
    mk = Masker(report)
    out = {k: copy.deepcopy(v) for k, v in report.items() if not k.startswith("_") and k not in ("candidates", "info")}
    cands = []
    for c in report["candidates"]:
        pc = mk.deep(c)
        if c["confidential"]:
            pc["scope_id"], pc["candidate_id"] = hash_id(c["scope_id"]), public_candidate_id(c)
            pc["layer_path"] = None
            pc["duplicate_folders"] = [PATH_MASK for _ in c.get("duplicate_folders") or []]
            if pc.get("registry"):
                pc["registry"]["top_page_url"] = URL_MASK if c["registry"].get("top_page_url") else None
                par = c["registry"].get("parent_scope")
                pc["registry"]["parent_scope"] = hash_id(par) if par else None
        else:  # own ids stay readable
            pc["scope_id"], pc["candidate_id"], pc["layer_path"] = c["scope_id"], c["candidate_id"], c["layer_path"]
        cands.append(pc)
    out["candidates"] = cands
    out["info"] = {k: [mk.deep(i, paths_redact=True) for i in items] for k, items in report["info"].items()}
    return out


def write_report(report, out_dir: Path):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pub = public_report(report)
    md = render_md(pub)
    (out_dir / "report.md").write_text(md, encoding="utf-8")
    (out_dir / "report.json").write_text(json.dumps(pub, ensure_ascii=False, indent=2, default=str) + "\n",
                                         encoding="utf-8")
    return md


# ---------------------------------------------------------------- approval file
APPLY_TARGETS = ("intent", "backlog.summary", "registry.projects", "registry.tasks")  # = write order
ADD_KINDS = frozenset({"registry_task_missing", "registry_missing"})


DUP_REASON = "同じ scope のフォルダが複数ある（1つだけ書くと写しが食い違う。人が写しを整理してから）"


def touches_layer(changes):
    return any(x.get("target") in ("intent", "backlog.summary") for x in changes or [])


def scope_state(c):
    """(state, reason): ok | choose (needs `alternative`) | out_of_scope | nothing."""
    if c.get("duplicate_disagree"):
        return "out_of_scope", "duplicate_disagree（同じ scope のフォルダが食い違う。人が解消してから）"
    all_changes = list(c["proposed_changes"]) + [x for a in c.get("alternatives") or []
                                                 for x in a.get("proposed_changes") or []]
    if c["kind"] in ADD_KINDS or any(x.get("op") == "add" for x in all_changes):
        return "out_of_scope", "行の追加が要る（add-task / add-project で別途追加）"
    if any(x.get("target") not in APPLY_TARGETS for x in all_changes):
        return "out_of_scope", "未対応の反映先"
    if c.get("duplicate_folders") and touches_layer(c["proposed_changes"]):
        return "out_of_scope", DUP_REASON
    if c["proposed_changes"]:
        return "ok", None
    if c.get("alternatives"):
        return "choose", None
    return "nothing", "反映する変更の提案なし（記録・確認のみ）"


def change_key(ch):
    return (ch.get("target"), str(ch["task_id"]) if ch.get("task_id") is not None else None, ch.get("field"))


def slim_change(ch):
    d = {"target": ch["target"], "field": ch["field"], "from": ch.get("from"), "to": ch.get("to")}
    if ch.get("task_id") is not None:
        d["task_id"] = ch["task_id"]
    return d


def approval_template(report):
    """Template for humans: every row that --apply can write, decision 'undecided' (= not applied). Set 'approve'
    (and `alternative` where asked) on the rows to apply, delete or leave the rest."""
    pub_by_id = {}
    rows, out_scope, nothing = [], [], 0
    for c in report["candidates"]:
        st, why = scope_state(c)
        pid = public_candidate_id(c)
        pub_by_id[pid] = c
        if st == "nothing":
            nothing += 1
            continue
        if st == "out_of_scope":
            out_scope.append({"candidate_id": pid, "kind": c["kind"], "reason": why})
            continue
        e = {"candidate_id": pid, "kind": c["kind"], "decision": "undecided",
             "recommended_action": c["recommended_action"], "confidential": c["confidential"]}
        if c.get("backlog") and c["backlog"].get("has_open_child"):
            e["warning"] = "未完了の子Layerあり"
        if st == "ok":
            e["alternative"] = None
            e["from"] = [slim_change(x) for x in c["proposed_changes"]]
        else:
            e["alternative"] = None
            e["alternatives_available"] = [a["action"] for a in c["alternatives"]]
            e["from"] = {a["action"]: [slim_change(x) for x in a["proposed_changes"]] for a in c["alternatives"]}
        rows.append(e)
    return {
        "version": 1,
        "kind": "aiplc_status_audit.approval",
        "report_date": report["generated_at"],
        "how_to": ("反映する行だけ decision を \"approve\" にする（選択肢がある行は alternative も書く）。"
                   "それ以外の行は消すか undecided / skip のままにする。from はレポート時点の値で、反映直前の値と"
                   "違えば書かずに conflict になる。実行: --apply <このファイル>（既定 dry-run、--yes で書く）"),
        "approvals": rows,
        "out_of_scope": out_scope,
        "no_changes_rows": nothing,
    }


# ---------------------------------------------------------------- apply
class ApplyError(Exception):
    pass


def _plc_query():
    spec = importlib.util.spec_from_file_location("_aiplc_plc_query", PLC_QUERY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sql_lit(v) -> str:
    s = str(v)
    if "\x00" in s:
        raise ApplyError("NUL in SQL value")
    return "'" + s.replace("'", "''") + "'"


def same(a, b) -> bool:
    return (None if a is None else str(a)) == (None if b is None else str(b))


VALUE_RE = re.compile(r"^(?P<head>[ \t]*status[ \t]*:[ \t]*)(?P<val>[^#\r\n]*?)(?P<tail>[ \t]+#[^\r\n]*)?(?P<eol>\r?\n)?$")


def _replace_value(line, new):
    m = VALUE_RE.match(line)
    if not m:
        raise ApplyError("status line not recognised")
    old = m.group("val")
    if old[:1] in ("|", ">", "&", "*", "{", "[", "!"):
        raise ApplyError("status is not a plain scalar")
    q = old[:1] if old[:1] in ("'", '"') and old[-1:] == old[:1] and len(old) >= 2 else ""
    head = m.group("head")
    if not head.endswith((" ", "\t")):
        head += " "  # `status:` with an empty value
    return head + f"{q}{new}{q}" + (m.group("tail") or "") + (m.group("eol") or "")


def _indent(line):
    return len(line) - len(line.lstrip(" \t"))


def _content(line):
    s = line.strip()
    return bool(s) and not s.startswith("#")


def edit_status_line(text, new, summary=False):
    """Rewrite one `status:` line (top level, or the direct child of top-level `summary:`). Everything else stays
    byte-identical. Raises ApplyError when the line is not found exactly once."""
    lines = text.splitlines(keepends=True)
    if not summary:
        idx = [i for i, l in enumerate(lines) if re.match(r"^status[ \t]*:", l)]
    else:
        heads = [i for i, l in enumerate(lines) if re.match(r"^summary[ \t]*:[ \t]*(#.*)?\r?\n?$", l)]
        if len(heads) != 1:
            raise ApplyError("summary block not found (or not a block mapping)")
        block = []
        for j in range(heads[0] + 1, len(lines)):
            if _content(lines[j]) and _indent(lines[j]) == 0:
                break
            block.append(j)
        body = [j for j in block if _content(lines[j])]
        if not body:
            raise ApplyError("summary block is empty")
        child = _indent(lines[body[0]])
        idx = [j for j in body if _indent(lines[j]) == child and re.match(r"^[ \t]*status[ \t]*:", lines[j])]
    if len(idx) != 1:
        raise ApplyError(f"status line found {len(idx)} times")
    lines[idx[0]] = _replace_value(lines[idx[0]], new)
    return "".join(lines)


def read_yaml_status(path: Path, summary=False):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ApplyError("not a mapping")
    if summary:
        s = data.get("summary")
        if not isinstance(s, dict) or "status" not in s:
            raise ApplyError("summary.status missing")
        return s.get("status")
    if "status" not in data:
        raise ApplyError("status missing")
    return data.get("status")


def write_yaml_status(path: Path, new, summary=False):
    """One-line edit, verified by parsing: the new document must equal the old one with only that value changed."""
    text = path.read_bytes().decode("utf-8")  # keep CRLF as is
    old = yaml.safe_load(text)
    new_text = edit_status_line(text, new, summary)
    expect = copy.deepcopy(old)
    (expect["summary"] if summary else expect)["status"] = new
    if yaml.safe_load(new_text) != expect:
        raise ApplyError("edit changed more than the status value")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".aiplc_apply_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Target:
    """Reads the current value of one change and (with --yes) writes it."""

    def __init__(self, db_path: Path, root: Path, layers, today: date, write: bool):
        self.root, self.layers, self.today, self.write = root, layers, today, write
        self.db_path = Path(db_path)
        if write:
            self.conn = sqlite3.connect(str(self.db_path))
        else:
            self.conn = open_ro(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.task_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(tasks)")}
        dv = detect_task_vocab(self.conn)
        self.done_values = REG_TASK_DONE_ALL | {REG_VOCAB[dv or "ja"]["done"]}
        self.plc = _plc_query() if write else None

    def close(self):
        self.conn.close()

    def layer_file(self, sid, target):
        rel = self.layers.get(sid)
        if not rel:
            raise ApplyError("Layer not resolved")
        return self.root / rel / ("intent.yaml" if target == "intent" else "backlog.yaml")

    def rows(self, sid, ch):
        if ch["target"] == "registry.projects":
            return self.conn.execute("SELECT status FROM projects WHERE scope_id=?", (sid,)).fetchall()
        return self.conn.execute("SELECT status, completed_at FROM tasks WHERE scope_id=? AND task_id=?",
                                 (sid, str(ch["task_id"]))).fetchall()

    def current(self, sid, ch):
        t = ch["target"]
        if t in ("intent", "backlog.summary"):
            return read_yaml_status(self.layer_file(sid, t), summary=(t == "backlog.summary"))
        rows = self.rows(sid, ch)
        if len(rows) != 1:
            raise ApplyError(f"{len(rows)} Registry rows match")
        return rows[0]["status"]

    def _task_completed_at(self, sid, task_id):
        rel = self.layers.get(sid)
        if rel:
            data, _ = load_yaml(self.root / rel / "backlog.yaml")
            for t in (data or {}).get("tasks") or [] if isinstance(data, dict) else []:
                if isinstance(t, dict) and str(t.get("id", t.get("task_id"))).strip() == str(task_id):
                    d = to_date(t.get("completed_at"))
                    if d:
                        return d.isoformat()
        return self.today.isoformat()

    def apply(self, sid, ch, frm):
        t = ch["target"]
        if t in ("intent", "backlog.summary"):
            write_yaml_status(self.layer_file(sid, t), ch["to"], summary=(t == "backlog.summary"))
            return
        if t == "registry.projects":
            q = (f"UPDATE projects SET status={sql_lit(ch['to'])} "
                 f"WHERE scope_id={sql_lit(sid)} AND status={sql_lit(frm)}")
        else:
            sets = [f"status={sql_lit(ch['to'])}"]
            if ch["to"] in self.done_values and "completed_at" in self.task_cols:
                sets.append(f"completed_at=COALESCE(completed_at, {sql_lit(self._task_completed_at(sid, ch['task_id']))})")
            q = (f"UPDATE tasks SET {', '.join(sets)} WHERE scope_id={sql_lit(sid)} "
                 f"AND task_id={sql_lit(ch['task_id'])} AND status={sql_lit(frm)}")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.plc.cmd_sql(self.conn, q)  # plc_query's sql path (some schemas add a guard there)
        out = buf.getvalue()
        if rc or "Error:" in out or "[BLOCKED]" in out:
            raise ApplyError(f"plc_query sql failed (rc={rc}): {out.strip()[:200]}")
        if self.conn.in_transaction:
            self.conn.rollback()
            raise ApplyError("transaction left open by plc_query")


def _hash_map(report):
    return {hash_id(s): s for s in report.get("_scopes") or []}


CID_RE = re.compile(r"^([^:\s]+):([a-z_]+)$")


def err_text(ex, mk):
    """Error text safe for output/logs: OSError / YAML errors carry absolute paths or file excerpts -> type only."""
    if isinstance(ex, (ApplyError, sqlite3.Error)):
        return mk.text(str(ex))[:200]
    return type(ex).__name__ + (f"(errno={ex.errno})" if isinstance(ex, OSError) and ex.errno else "")


def applied_before(log_path: Path):
    """{(candidate_id, target, task_id, field, before, after)} already applied by an earlier --yes run."""
    done = set()
    if not log_path.is_file():
        return done
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            x = json.loads(line)
        except ValueError:
            continue
        if isinstance(x, dict) and x.get("result") == "applied":
            done.add((x.get("candidate_id"), x.get("target"), None if x.get("task_id") is None else str(x["task_id"]),
                      x.get("field"), str(x.get("before")), str(x.get("after"))))
    return done


def run_apply(db_path: Path, root: Path, today: date, approval_path: Path, yes: bool, state_dir: Path,
              stale_days: int = 30, echo=print, allow_reapply: bool = False):
    """Returns (exit_code, results). results: one dict per approval entry (public ids only)."""
    try:
        appr = json.loads(Path(approval_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        echo(f"approval file unreadable: {type(e).__name__}")
        return 2, []
    if not isinstance(appr, dict) or not isinstance(appr.get("approvals"), list):
        echo("approval file must be a JSON object with an 'approvals' list")
        return 2, []
    report = audit(db_path, root, today, stale_days)
    conf_scopes = set((report.get("_mask") or {}).get("scopes") or [])
    by_id, ambiguous = {}, set()
    for c in report["candidates"]:
        for cid in {public_candidate_id(c), c["candidate_id"]}:
            if cid in by_id and by_id[cid] is not c:
                ambiguous.add(cid)
            by_id[cid] = c
    hmap = _hash_map(report)
    mk = Masker(report)
    tgt = Target(db_path, root, report["_layers"], today, write=yes)
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + hashlib.sha256(os.urandom(8)).hexdigest()[:6]
    log_path = Path(state_dir) / "apply_log.jsonl"
    results, failed = [], False
    prior = set() if allow_reapply else applied_before(log_path)

    def log(entry):
        nonlocal failed
        if not yes:
            return
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "run_id": run_id,
                                    "approval_file": mk.text(Path(approval_path).name), **entry},
                                   ensure_ascii=False) + "\n")
        except OSError as ex:  # a lost log line must not abort mid-run; report it as a failure instead
            failed = True
            print(f"[apply] ログを書けませんでした: {err_text(ex, mk)}", file=sys.stderr)

    def pub_path(sid, ch):
        if ch["target"] not in ("intent", "backlog.summary"):
            return None
        rel = report["_layers"].get(sid)
        name = "intent.yaml" if ch["target"] == "intent" else "backlog.yaml"
        return f"{PATH_MASK}/{name}" if sid in conf_scopes or not rel else f"{rel}/{name}"

    def fmt(ch):
        return f"{ch['target']}{('[' + str(ch['task_id']) + ']') if ch.get('task_id') is not None else ''}.{ch['field']}"

    try:
        seen = set()
        for n, e in enumerate(appr["approvals"]):
            if not isinstance(e, dict) or not isinstance(e.get("candidate_id"), str):
                results.append({"entry": n, "result": "invalid", "reason": "candidate_id missing"})
                continue
            cid_in = e["candidate_id"]
            m_id = CID_RE.match(cid_in)
            if not m_id or m_id.group(2) not in KINDS:
                results.append({"entry": n, "result": "invalid", "reason": "candidate_id must be <scope>:<kind>"})
                continue
            sp, kp = m_id.group(1), m_id.group(2)
            if sp in conf_scopes:
                shown = f"{hash_id(sp)}:{kp}"  # never echo a plain confidential id
            elif sp in mk.known or sp.startswith("C-"):
                shown = mk.text(cid_in)
            else:
                shown = f"entry#{n}:{kp}"  # unknown id (e.g. a mistyped folder name) is not echoed
            r = {"candidate_id": shown, "result": None}
            results.append(r)
            if e.get("decision") != "approve":
                r["result"], r["reason"] = "skipped", f"decision={e.get('decision')!r}"
                continue
            if cid_in in seen:
                r["result"], r["reason"] = "invalid", "duplicate entry"
                continue
            seen.add(cid_in)
            if cid_in in ambiguous:
                r["result"], r["reason"] = "conflict", "ambiguous candidate_id"
                log({"candidate_id": shown, "result": "conflict", "reason": r["reason"]})
                continue
            c = by_id.get(cid_in)
            appr_from = e.get("from")
            alt = e.get("alternative")
            if c is not None:
                pid = public_candidate_id(c)
                r["candidate_id"] = pid  # never echo a plain confidential id back
                sid = c["scope_id"]
                st, why = scope_state(c)
                if st in ("out_of_scope", "nothing"):
                    r["result"], r["reason"] = ("out_of_scope" if st == "out_of_scope" else "nothing_to_apply"), why
                    log({"candidate_id": pid, "kind": c["kind"], "result": r["result"], "reason": why})
                    continue
                if st == "choose":
                    alts = {a["action"]: a["proposed_changes"] for a in c["alternatives"]}
                    if alt not in alts:
                        r["result"], r["reason"] = "invalid", f"alternative required: {sorted(alts)}"
                        continue
                    changes = alts[alt]
                    if c.get("duplicate_folders") and touches_layer(changes):
                        r["result"], r["reason"] = "out_of_scope", DUP_REASON
                        log({"candidate_id": pid, "kind": c["kind"], "result": "out_of_scope", "reason": DUP_REASON})
                        continue
                    if isinstance(appr_from, dict):
                        appr_from = appr_from.get(alt)
                else:
                    if alt not in (None, c["recommended_action"]):
                        r["result"], r["reason"] = "invalid", "this row has no alternatives"
                        continue
                    changes = c["proposed_changes"]
            else:  # not proposed any more: allowed only as a noop (already applied)
                sid = hmap.get(sp, sp) if sp.startswith("C-") else sp
                if sid in conf_scopes:
                    r["candidate_id"] = f"{hash_id(sid)}:{kp}"
                if isinstance(appr_from, dict):
                    appr_from = appr_from.get(alt)
                changes = None
            if not isinstance(appr_from, list) or not appr_from or not all(isinstance(x, dict) for x in appr_from):
                r["result"], r["reason"] = "invalid", "from (list of changes) missing"
                continue
            approved = {}
            for x in appr_from:
                approved[change_key(x)] = x
            plan, problems = [], []
            if changes is None:
                # re-check every approved change: all at `to` -> noop; otherwise the row is not current
                states = []
                for k, x in approved.items():
                    ch = {"target": k[0], "task_id": k[1], "field": k[2], "to": x.get("to")}
                    if ch["target"] not in APPLY_TARGETS:
                        states.append("unknown")
                        continue
                    try:
                        cur = tgt.current(sid, ch)
                    except (ApplyError, OSError, UnicodeError, yaml.YAMLError, sqlite3.Error):
                        states.append("unreadable")
                        continue
                    states.append("noop" if same(cur, x.get("to")) else "open")
                if states and all(s == "noop" for s in states):
                    r["result"], r["reason"] = "noop", "already applied (candidate no longer proposed)"
                else:
                    r["result"] = "not_found" if not states or "unreadable" in states else "not_current"
                    r["reason"] = "candidate not in the current scan; re-run the report and approve again"
                log({"candidate_id": r["candidate_id"], "result": r["result"], "reason": r["reason"]})
                continue
            keys = [change_key(ch) for ch in changes]
            if set(keys) != set(approved):
                problems.append("approved changes differ from the current proposal")
            for ch in sorted(changes, key=lambda x: APPLY_TARGETS.index(x["target"])):
                a = approved.get(change_key(ch))
                if a is None:
                    continue
                if not same(a.get("to"), ch["to"]):
                    problems.append(f"{fmt(ch)}: to differs")
                    continue
                try:
                    cur = tgt.current(sid, ch)
                except (ApplyError, OSError, UnicodeError, yaml.YAMLError, sqlite3.Error) as ex:
                    problems.append(f"{fmt(ch)}: unreadable ({type(ex).__name__})")
                    continue
                if (pid, ch["target"], None if ch.get("task_id") is None else str(ch["task_id"]), ch["field"],
                        str(a.get("from")), str(ch["to"])) in prior and not same(cur, ch["to"]):
                    problems.append(f"{fmt(ch)}: already applied by an earlier run and changed back since "
                                    "(re-approve with --allow-reapply if intended)")
                    continue
                if same(cur, ch["to"]):
                    plan.append((ch, a.get("from"), cur, "noop"))
                elif same(cur, a.get("from")):
                    plan.append((ch, a.get("from"), cur, "apply"))
                else:
                    problems.append(f"{fmt(ch)}: current={cur!r} from={a.get('from')!r}")
            r["kind"] = c["kind"]
            r["changes"] = [{"change": fmt(ch), "path": pub_path(sid, ch), "from": frm, "to": ch["to"],
                             "state": s} for ch, frm, _, s in plan]
            if problems:
                r["result"], r["reason"] = "conflict", "; ".join(problems)
                log({"candidate_id": r["candidate_id"], "kind": c["kind"], "result": "conflict", "reason": r["reason"]})
                continue
            todo = [p for p in plan if p[3] == "apply"]
            if not todo:
                r["result"] = "noop"
                log({"candidate_id": r["candidate_id"], "kind": c["kind"], "result": "noop"})
                continue
            if not yes:
                r["result"] = "would_apply"
                continue
            done_n = 0
            for ch, frm, cur, _ in todo:
                entry = {"candidate_id": r["candidate_id"], "kind": c["kind"], "target": ch["target"],
                         "field": ch["field"], "task_id": ch.get("task_id"), "path": pub_path(sid, ch),
                         "before": cur}
                try:
                    cur2 = tgt.current(sid, ch)  # immediately before writing
                    if not same(cur2, frm):
                        raise ApplyError(f"value changed to {cur2!r}")
                    tgt.apply(sid, ch, frm)
                    after = tgt.current(sid, ch)
                    if not same(after, ch["to"]):
                        raise ApplyError(f"read back {after!r}")
                except (ApplyError, OSError, UnicodeError, yaml.YAMLError, sqlite3.Error) as ex:
                    failed = True
                    log({**entry, "result": "failed", "reason": err_text(ex, mk)})
                    r["result"], r["reason"] = "failed" if not done_n else "partial", \
                        f"{fmt(ch)}: {err_text(ex, mk)} (later changes of this row not written)"
                    break
                done_n += 1
                log({**entry, "after": after, "result": "applied"})
            else:
                r["result"] = "applied"
    finally:
        tgt.close()
    if failed:
        return 1, results
    attention = {"conflict", "invalid", "not_current", "not_found"}
    return (3 if any(r["result"] in attention for r in results) else 0), results


def render_apply(results, yes):
    head = "反映（--yes）" if yes else "dry-run（書き込みなし。--yes で反映）"
    counts = {}
    for r in results:
        counts[r["result"]] = counts.get(r["result"], 0) + 1
    out = [f"# 承認ファイルの反映: {head}", "",
           "- 集計: " + " / ".join(f"{k} {v}" for k, v in sorted(counts.items())), ""]
    for r in results:
        out.append(f"- {r.get('candidate_id', r.get('entry'))}: **{r['result']}**"
                   + (f" — {r['reason']}" if r.get("reason") else ""))
        for ch in r.get("changes") or []:
            out.append(f"  - {ch['change']}{(' (' + ch['path'] + ')') if ch['path'] else ''}: "
                       f"{ch['from']!r} → {ch['to']!r} [{ch['state']}]")
    return "\n".join(out) + "\n"


def default_report_dir(state: Path, today: date, now: datetime | None = None) -> Path:
    """Create and return a new report directory per run: <state>/reports/YYYY-MM-DD/HHMMSS.
    Runs in the same second get HHMMSS-2, -3, ... so an earlier report is never overwritten (design note: a report
    was once lost when the template was regenerated into the same dated directory). The date part follows --today."""
    base = Path(state) / "reports" / today.isoformat()
    stem = (now or datetime.now()).strftime("%H%M%S")
    base.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        cand = base / (stem if n == 1 else f"{stem}-{n}")
        try:
            cand.mkdir()  # atomic: fails if another run took this name
            return cand
        except FileExistsError:
            n += 1


# ---------------------------------------------------------------- scope filter / brief
BRIEF_EXIT_NONE, BRIEF_EXIT_FOUND = 0, 10  # --brief only; 1/2/3 keep their meaning (README_status_audit.md)


def layer_scope_id(path, root: Path):
    """scope_id from <path>/intent.yaml (path relative to root, or absolute). Returns (scope_id, error)."""
    p = Path(path)
    p = p if p.is_absolute() else root / p
    if p.name == "intent.yaml":
        p = p.parent
    data, err = load_yaml(p / "intent.yaml")
    if err or not isinstance(data, dict):
        return None, "指定したフォルダの intent.yaml を読めない（パスは機密の可能性があるため表示しない）"
    sid = str(data.get("scope_id") or "").strip()
    return (sid, None) if sid else (None, "指定したフォルダの intent.yaml に scope_id が無い")


def resolve_scopes(args_scopes, report):
    """Map --scope values (plain scope_id or the C-xxxxxxxx hash) to known scope ids. Returns (set, unknown)."""
    known = set(report.get("_scopes") or [])
    by_hash = {hash_id(s): s for s in known}
    out, unknown = set(), []
    for a in args_scopes:
        a = str(a).strip()
        if a in known:
            out.add(a)
        elif a in by_hash:
            out.add(by_hash[a])
        else:
            unknown.append(a)
    return out, unknown


def filter_report(report, scopes):
    """Keep only candidates (and info items) of the given scope ids; recompute the counts that depend on them."""
    r = dict(report)
    cands = [c for c in report["candidates"] if c["scope_id"] in scopes]
    info = {k: [i for i in items if i.get("scope_id") in scopes] for k, items in report["info"].items()}
    cnt = dict(report["counts"])
    cnt.update({
        "by_kind": {k: sum(1 for c in cands if c["kind"] == k) for k in KINDS},
        "by_kind_primary": {k: sum(1 for c in cands if c["kind"] == k and c["primary"]) for k in KINDS},
        "candidates": len(cands),
        "scopes": len({c["scope_id"] for c in cands}),
        "confidential_candidates": sum(1 for c in cands if c["confidential"]),
        "stale_jev_eligible": sum(1 for c in cands if c["jev_eligible"]),
        "stale_addable_by_opt_in": sum(1 for c in cands if c["kind"] == "stale" and not c["confidential"]
                                       and not c["jev_opt_in"]),
        "info": {k: len(v) for k, v in info.items()},
    })
    r.update({"candidates": cands, "info": info, "counts": cnt,
              "params": {**report["params"], "scope_filter": len(scopes)}})
    return r


def _kind_name(kind):
    return KIND_JA[kind].split(". ", 1)[-1]


def render_brief(report, scoped: bool):
    """Short summary for people and the main model (Phase 7 / weekly). Only fixed Japanese labels, counts and
    public candidate ids (confidential scopes as C-hash) are printed; nothing else from Layers or the Registry."""
    cands = report["candidates"]
    if not cands:
        return "ステータス点検: 食い違いなし"
    applicable = 0
    lines = []
    for c in cands:
        st, _ = scope_state(c)
        if st in ("ok", "choose"):
            applicable += 1
            tail = "反映するなら --approval-template → --apply"
        else:
            tail = "--apply の対象外（人が判断）"
        if scoped:
            lines.append(f"{public_candidate_id(c)}: {_kind_name(c['kind'])} — "
                         f"{ACTION_JA.get(c['recommended_action'], c['recommended_action'])} — {tail}")
    if not scoped:
        cnt = report["counts"]["by_kind"]
        lines += ["| 分類 | 件数 |", "| --- | --- |"]
        lines += [f"| {KIND_JA[k]} | {cnt[k]} |" for k in KINDS if cnt[k]]
    n_scopes = len({c["scope_id"] for c in cands})
    lines.append(f"ステータス点検: 候補 {len(cands)} 件（{n_scopes} scope）— うち --apply で反映できる {applicable} 件・"
                 f"人が判断 {len(cands) - applicable} 件。詳細は --brief を外して実行")
    return "\n".join(lines)


def _refuse_layer_dir(p: Path):
    return (p / "intent.yaml").exists() or (p / "backlog.yaml").exists()


def main(argv=None):
    ap = argparse.ArgumentParser(description="AI-PLC status audit (read-only) and approved apply")
    ap.add_argument("--db", default=None, help=f"default: ${ENV_DB} or {DEFAULT_DB}")
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--today", default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--stale-days", type=int, default=30)
    ap.add_argument("--todo", default=None, help="default: <root>/todo/todo.md")
    ap.add_argument("--memory", default=str(DEFAULT_MEMORY))
    ap.add_argument("--state-dir", default=None,
                    help=f"dir for reports / approvals / apply_log.jsonl; keep it out of git (default: ${ENV_STATE} or {DEFAULT_STATE_DIR})")
    ap.add_argument("--out", "--out-dir", dest="out", default=None,
                    help="directory for report.md / report.json (default: a new <state-dir>/reports/YYYY-MM-DD/HHMMSS per run)")
    ap.add_argument("--quiet", action="store_true", help="do not print the md report to stdout")
    ap.add_argument("--jev", action="store_true",
                    help="ask Jev (choice) about stale rows with jev_eligible=true only; hint only")
    ap.add_argument("--approval-template", nargs="?", const="", default=None, metavar="PATH",
                    help="also write an approval template (default: <state-dir>/approvals/approval_template_YYYY-MM-DD.json)")
    ap.add_argument("--apply", default=None, metavar="APPROVAL_JSON", help="apply approved rows (dry-run unless --yes)")
    ap.add_argument("--yes", action="store_true", help="with --apply: really write")
    ap.add_argument("--allow-reapply", action="store_true",
                    help="with --apply: allow a change that apply_log.jsonl shows as applied before and that was changed back")
    ap.add_argument("--scope", action="append", default=[], metavar="SCOPE_ID",
                    help="only candidates of this scope_id (repeatable; C-xxxxxxxx hash ids too)")
    ap.add_argument("--layer", action="append", default=[], metavar="PATH",
                    help="like --scope, with the scope_id read from PATH/intent.yaml (repeatable)")
    ap.add_argument("--brief", action="store_true",
                    help="print a short summary only; writes no file, sends nothing; exit 0 = no candidates, 10 = some")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    today = date.fromisoformat(a.today) if a.today else date.today()
    db = Path(a.db or os.environ.get(ENV_DB) or DEFAULT_DB)
    state = Path(a.state_dir or os.environ.get(ENV_STATE) or DEFAULT_STATE_DIR)
    if not db.is_file():
        print(f"DB not found: {db}", file=sys.stderr)
        return 2
    if a.yes and not a.apply:
        print("--yes needs --apply", file=sys.stderr)
        return 2
    if a.apply and (a.brief or a.scope or a.layer):
        print("--apply cannot be combined with --brief / --scope / --layer", file=sys.stderr)
        return 2
    if a.brief and (a.jev or a.approval_template is not None or a.out):
        print("--brief is read-only and writes nothing: it cannot be combined with --jev / --approval-template / --out",
              file=sys.stderr)
        return 2
    scope_args = list(a.scope)
    for lp in a.layer:
        sid, err = layer_scope_id(lp, root)
        if err:
            print(f"--layer: {err}", file=sys.stderr)
            return 2
        scope_args.append(sid)
    if a.apply:
        if a.jev or a.approval_template is not None:
            print("--apply cannot be combined with --jev / --approval-template", file=sys.stderr)
            return 2
        if _refuse_layer_dir(state):
            print(f"refusing to use a Layer folder as state dir: {state}", file=sys.stderr)
            return 2
        rc, results = run_apply(db, root, today, Path(a.apply), a.yes, state, a.stale_days,
                                echo=lambda s: print(s, file=sys.stderr), allow_reapply=a.allow_reapply)
        if results:
            print(render_apply(results, a.yes))
        if a.yes:
            print(f"log: {state / 'apply_log.jsonl'}", file=sys.stderr)
        return rc
    report = audit(db, root, today, a.stale_days,
                   Path(a.todo) if a.todo else root / "todo" / "todo.md",
                   Path(a.memory) if a.memory else None, jev=a.jev,
                   scope_filter=set(scope_args) if scope_args else None)
    if scope_args:
        scopes, unknown = resolve_scopes(scope_args, report)
        if unknown:
            # the value may be a confidential scope id typed by hand: echo it only as a hash
            print("unknown scope (not in the Registry nor in any Layer): "
                  + ", ".join(hash_id(u) for u in unknown), file=sys.stderr)
            return 2
        report = filter_report(report, scopes)
    if a.brief:
        print(render_brief(report, scoped=bool(scope_args)))
        return BRIEF_EXIT_FOUND if report["candidates"] else BRIEF_EXIT_NONE
    out = Path(a.out) if a.out else None
    tpath = None
    if a.approval_template is not None:
        tpath = Path(a.approval_template) if a.approval_template else \
            state / "approvals" / f"approval_template_{today.isoformat()}.json"
    for d in ([out] if out else [state / "reports"]) + ([tpath.parent] if tpath else []):
        if _refuse_layer_dir(d):
            print(f"refusing to write into a Layer folder: {d}", file=sys.stderr)
            return 2
    if out is None:
        out = default_report_dir(state, today)
    md = write_report(report, out)
    if not a.quiet:
        print(md)
    print(f"wrote {out / 'report.md'} and {out / 'report.json'}", file=sys.stderr)
    if tpath:
        tpath.parent.mkdir(parents=True, exist_ok=True)
        tpath.write_text(json.dumps(approval_template(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {tpath}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
