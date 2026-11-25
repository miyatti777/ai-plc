#!/usr/bin/env python3
"""BacklogLive — AI-PLC Layer の backlog.yaml をライブで図示する閲覧専用サーバ。

127.0.0.1 だけで待ち受け、GET 以外は 405。Layer は起動引数で決まり、ブラウザから
パスを受け取らない。backlog.yaml が壊れていても最後の正常な状態を返す。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import time
import threading
import webbrowser
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

import yaml

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
DEFAULT_PORT = 8770
REPO_ROOT = HERE.parents[1]
# 追従モードで降りないフォルダ（Recollection の previous 等、Layer の写しが入る）
PRUNE_DIRS = frozenset({"documents", "context", "agents", "node_modules", "__pycache__"})  # 大文字小文字を区別しない
SCAN_TTL = 2.0
FULL_SCAN_TTL = 30.0
MONTH_DIR = re.compile(r"^\d{6}$")
DAY_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# ?layer= に受け付ける scope_id の形（パス区切り・ドットを含まない）
SCOPE_PARAM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MAX_CANDIDATES = 40
RESCAN_ON_MISS = 5.0  # 見つからない scope_id で全体を走査し直す最短間隔（秒）
_HEAD_FIELD = re.compile(r"^(scope_id|display_name|scope_name):[ \t]*(.*?)[ \t]*$", re.M)
MAX_READERS = 16
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}

# Registry ビューアと同じ値（あちらは import しない）
DONE = frozenset({"completed", "done", "完了"})
EXCLUDED = frozenset({"cancelled", "dropped", "deferred"})
IN_PROGRESS = frozenset({"in_progress", "in-progress", "doing", "wip", "active"})
BLOCKED = frozenset({"blocked"})
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
CATEGORIES = ("done", "in_progress", "ready", "waiting", "blocked", "excluded")
# 運用タスクを回す間隔（04-operation Phase 1 の決まり。plc-auto の plc_auto.py の RECURRING_GAP_DAYS と同じ値 — import しない）
RECURRING_GAP_DAYS = {"daily": 1, "weekly": 7}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _stat(path: Path) -> Optional[tuple[int, int]]:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _iso(ns: Optional[int]) -> Optional[str]:
    if ns is None:
        return None
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_yaml(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("ファイルが空です")
    return yaml.safe_load(text)


def _task_id(task: dict, index: int) -> str:
    tid = str(task.get("id") or task.get("task_id") or "").strip()
    return tid or f"#{index + 1}"


def _deps(task: dict) -> list[str]:
    raw = task.get("dependencies") or task.get("depends_on") or []
    if isinstance(raw, (str, int)):
        raw = [raw]
    return [str(d).strip() for d in raw if str(d).strip()] if isinstance(raw, list) else []


def _text(value: Any) -> str:
    """AC や goal が dict/list で書かれていても読める1行にする。"""
    if isinstance(value, dict):
        for key in ("criterion", "description", "text", "name", "title"):
            if value.get(key):
                return _text(value[key])
        return ", ".join(f"{k}: {_text(v)}" for k, v in value.items())
    if isinstance(value, list):
        return " / ".join(_text(v) for v in value)
    return str(value if value is not None else "").strip()


# 箱を押したときの詳細に出す項目。backlog に無い項目は返さない
DETAIL_FIELDS = ("description", "output", "result", "guardrails", "verification", "owner", "estimated_hours",
                 "started_at", "completed_at", "executed_by", "blocked_reason", "note", "pr_url", "origin",
                 "retired_at", "retired_reason")
DETAIL_MAX_RUNS = 30  # 実行の記録（runs）は新しい順にこの件数まで
DETAIL_MAX_CHARS = 2000
DETAIL_MAX_ITEMS = 50


def _clip(text: str) -> str:
    return text if len(text) <= DETAIL_MAX_CHARS else text[:DETAIL_MAX_CHARS] + "…（以下略）"


def _detail_value(value: Any) -> Any:
    """詳細の1項目を、文字列か文字列の list にする（dict は「キー: 値」の行に）。空なら None。"""
    if isinstance(value, dict):
        items = [f"{k}: {_text(v)}" for k, v in value.items()]
    elif isinstance(value, list):
        # list の中の dict は「キー: 値」を ／ でつなぐ（Python の表記で出さない）
        items = [" ／ ".join(f"{k}: {_text(x)}" for k, x in v.items()) if isinstance(v, dict) else _text(v) for v in value]
    else:
        text = _text(value)
        return _clip(text) if text else None
    items = [_clip(i) for i in items if i]
    if len(items) > DETAIL_MAX_ITEMS:
        items = items[:DETAIL_MAX_ITEMS] + [f"…ほか {len(items) - DETAIL_MAX_ITEMS} 件"]
    return items or None


def _run_sort_key(item: tuple) -> tuple:
    # (日付, 書いた位置)。同じ日付なら後に書いた方を新しいとみなす。読めない日付は最後
    i, run = item
    d = _scheduled(run.get("date"))
    return (d.isoformat() if d else "", i)


def _detail(task: dict) -> dict:
    out = {}
    for key in DETAIL_FIELDS:
        v = _detail_value(task.get(key))
        if v is not None:
            out[key] = v
    # 運用タスクの実行の記録（新しい順。読めない日付は最後）と、実行時期の変更履歴（書かれた順）
    runs = [r for r in (task.get("runs") or []) if isinstance(r, dict)] if isinstance(task.get("runs"), list) else []
    if runs:
        ordered = [r for _, r in sorted(enumerate(runs), key=_run_sort_key, reverse=True)]
        out["runs"] = [{"date": _clip(_text(r.get("date"))), "summary": _clip(_text(r.get("summary"))),
                        "output": _detail_value(r.get("output")), "checked_ac": _detail_value(r.get("checked_ac"))}
                       for r in ordered[:DETAIL_MAX_RUNS]]
        out["runs_total"] = len(runs)
    hist = task.get("schedule_history")
    rows = [h for h in hist if isinstance(h, dict)] if isinstance(hist, list) else []
    if rows:
        # 書かれた順のまま、多いときは新しい側（末尾）を残す
        out["schedule_history"] = [{k: _clip(_text(h.get(k))) for k in ("date", "from", "to", "reason")}
                                   for h in rows[-DETAIL_MAX_ITEMS:]]
        out["schedule_history_total"] = len(rows)
    return out


def build_flow(tasks: list[dict], current_order: Optional[int]) -> dict:
    """依存から「流れ」を作る（純粋関数）。各タスクに level（依存の深さ・0始まり）と in_cycle を書き込む。

    - 線は backlog に有る依存先だけ（重複IDは先勝ち）。自己参照・重複は除く
    - 循環（強連結成分で2件以上）に入ったタスクは同じ段に置いて in_cycle にし、その下流は深さどおりに並べる
    - critical: 未完了を含む最長の依存の連なり（全部終わっていれば全体の最長）
    - current_path: いまのタスクと、その依存元（たどれる全部）。線の強調（to_current）は直接の依存だけ
    """
    first: dict[str, int] = {}
    for t in tasks:
        first.setdefault(t["id"], t["order"])
    preds: dict[int, list[int]] = {t["order"]: [] for t in tasks}
    succ: dict[int, list[int]] = {t["order"]: [] for t in tasks}
    edges = []
    for t in tasks:
        for d in t["dependencies"]:
            src = first.get(d["id"])
            if src is None or src == t["order"] or src in preds[t["order"]]:
                continue
            preds[t["order"]].append(src)
            succ[src].append(t["order"])
            edges.append({"from": src, "to": t["order"]})

    # 強連結成分（Tarjan・反復版）で、本当に循環しているタスクだけを見つける
    nodes = sorted(preds)
    index: dict[int, int] = {}
    low: dict[int, int] = {}
    comp: dict[int, int] = {}
    on_stack: set[int] = set()
    stack: list[int] = []
    counter = 0
    ncomp = 0
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(succ[root]))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            v, it = work[-1]
            w = next(it, None)
            if w is not None:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(succ[w])))
                elif w in on_stack:
                    low[v] = min(low[v], index[w])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                while True:
                    x = stack.pop()
                    on_stack.discard(x)
                    comp[x] = ncomp
                    if x == v:
                        break
                ncomp += 1
    members: dict[int, list[int]] = {}
    for o, c in comp.items():
        members.setdefault(c, []).append(o)
    cyc = {o for ms in members.values() if len(ms) > 1 for o in ms}

    # 成分をまとめた DAG の上で段を決める（循環のまとまりは同じ段、下流は深さどおり）
    cpreds: dict[int, set[int]] = {c: set() for c in members}
    for o, ps in preds.items():
        for x in ps:
            if comp[x] != comp[o]:
                cpreds[comp[o]].add(comp[x])
    csucc: dict[int, set[int]] = {c: set() for c in members}
    for c, ps in cpreds.items():
        for x in ps:
            csucc[x].add(c)
    indeg = {c: len(ps) for c, ps in cpreds.items()}
    queue = sorted((c for c, n in indeg.items() if n == 0), key=lambda c: min(members[c]))
    clevel: dict[int, int] = {}
    corder: list[int] = []
    while queue:
        c = queue.pop(0)
        corder.append(c)
        clevel[c] = 1 + max((clevel[x] for x in cpreds[c]), default=-1)
        for nxt in csucc[c]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
        queue.sort(key=lambda c: min(members[c]))
    level = {o: clevel[comp[o]] for o in preds}

    # 最長の連なりは循環に入っていないタスクだけで求める
    topo = [o for c in corder for o in sorted(members[c]) if o not in cyc]
    dist: dict[int, int] = {}
    best: dict[int, Optional[int]] = {}
    for o in topo:
        ps = [x for x in preds[o] if x not in cyc]
        dist[o] = 1 + max((dist[x] for x in ps), default=0)
        best[o] = min((x for x in ps if dist[x] == dist[o] - 1), default=None) if ps else None
    cyclic = sorted(cyc)
    last = max(level.values(), default=-1)
    by_order = {t["order"]: t for t in tasks}
    for t in tasks:
        t["level"] = level[t["order"]]
        t["in_cycle"] = t["order"] in cyc

    def is_open(o: int) -> bool:
        return by_order[o]["category"] not in ("done", "excluded")

    def end_rank(o: int) -> tuple:
        t = by_order[o]
        return (-dist[o], PRIORITY_ORDER.get(t["priority"].upper(), 9), o)

    ends = [o for o in topo if is_open(o)] or topo
    critical: list[int] = []
    if ends:
        node: Optional[int] = min(ends, key=end_rank)
        while node is not None:
            critical.append(node)
            node = best[node]
        critical.reverse()
    crit_pairs = set(zip(critical, critical[1:]))

    current_path: set[int] = set()
    if current_order is not None:
        stack = [current_order]
        while stack:
            o = stack.pop()
            if o in current_path:
                continue
            current_path.add(o)
            stack.extend(preds.get(o, []))
    for e in edges:
        e["critical"] = (e["from"], e["to"]) in crit_pairs
        e["to_current"] = e["to"] == current_order  # いまのタスクへの直接の依存だけ
        e["cycle"] = e["from"] in cyc and comp[e["from"]] == comp[e["to"]]
    return {
        "level_count": last + 1,
        "edges": edges,
        "critical": critical,
        "current_path": sorted(current_path),
        "cycle": [by_order[o]["id"] for o in cyclic],
    }


def _scheduled(value: Any) -> Optional[date]:
    """実行時期 scheduled_for・期限 due（YYYY-MM-DD か YYYY-Www＝その週の月曜。w は大文字小文字を問わない）。
    引用符つきの日時は先頭10文字で読む。空・読めなければ None（ステータス点検と同じ決まり）。"""
    if isinstance(value, datetime):  # YAML reads "2026-10-26 09:00:00" as a datetime
        return value.date()
    if isinstance(value, date):
        return value
    v = str(value if value is not None else "").strip().strip("'\"").strip()
    m = re.match(r"^(\d{4})-[Ww](\d{2})$", v)
    try:
        if m:
            return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", v[:10]):
            return date.fromisoformat(v[:10])
    except ValueError:
        return None
    return None


def _is_week(value: Any) -> bool:
    """週の指定（YYYY-Www）か。_scheduled と同じ順で空白・引用符を除いて読む（判定を食い違わせない）。"""
    if isinstance(value, (date, datetime)):
        return False
    v = str(value if value is not None else "").strip().strip("'\"").strip()
    return bool(re.match(r"^\d{4}-[Ww]\d{2}$", v))


def build_agenda(tasks_in: list[dict], tasks: list[dict], today: date) -> dict:
    """「運用・予定」タブの予定。実行時期 scheduled_for と期限 due を1件ずつの行にして日付順に並べる。

    - 運用タスク（recurrence）は運用の欄に出すので入れない。完了・除外の Task は入れず件数だけ返す
    - bucket: past（今日より前）・today（今日。週の指定は今日を含む週）・future。読めない値は invalid に分ける
    """
    entries, invalid, hidden = [], [], 0
    for raw, t in zip(tasks_in, tasks):
        if t["recurring"]:
            continue
        for kind, key in (("scheduled", "scheduled_for"), ("due", "due")):
            value = raw.get(key)
            if value is None or str(value).strip() == "":
                continue
            if t["category"] in ("done", "excluded"):
                hidden += 1
                continue
            row = {"id": t["id"], "order": t["order"], "kind": kind}
            d = _scheduled(value)
            if d is None:
                invalid.append({**row, "raw": str(value)})
                continue
            week = _is_week(value)
            last = d + timedelta(days=6) if week else d
            bucket = "past" if last < today else "today" if d <= today else "future"
            entries.append({**row, "date": d.isoformat(), "week": week, "bucket": bucket,
                            "overdue": bool(kind == "due" and t["overdue"])})
    entries.sort(key=lambda e: (e["date"], 0 if e["kind"] == "scheduled" else 1, e["order"]))
    return {"entries": entries, "invalid": invalid, "hidden_done": hidden}


def _unreadable(value: Any) -> bool:
    """書いてあるのに読めない時期・期限（黙って時期なしにしない）。"""
    return value is not None and str(value).strip() != "" and _scheduled(value) is None


def _md(iso: str) -> str:
    """YYYY-MM-DD → M/D（画面の短い日付）。"""
    d = date.fromisoformat(iso)
    return f"{d.month}/{d.day}"


def summarize(backlog: Any, intent: Any = None, today: Optional[date] = None) -> dict:
    """backlog/intent の dict から画面用の状態を作る（純粋関数。today はテスト用で、既定は今日）。"""
    today = today or date.today()
    if not isinstance(backlog, dict):
        raise ValueError("backlog.yaml の最上位が mapping ではありません")
    raw_tasks = backlog.get("tasks") or []
    if not isinstance(raw_tasks, list):
        raise ValueError("tasks が list ではありません")
    tasks_in = [t for t in raw_tasks if isinstance(t, dict)]
    status_of: dict[str, str] = {}
    duplicates: list[str] = []
    for i, t in enumerate(tasks_in):  # 依存解決用。重複IDは先勝ちにして警告する
        tid = _task_id(t, i)
        if tid in status_of:
            duplicates.append(tid)
        else:
            status_of[tid] = _norm(t.get("status"))

    tasks = []
    for i, t in enumerate(tasks_in):
        tid = _task_id(t, i)
        st = _norm(t.get("status"))
        deps = _deps(t)
        open_deps = [d for d in deps if status_of.get(d) not in DONE]
        if st in DONE:
            cat = "done"
        elif st in EXCLUDED:
            cat = "excluded"
        elif st in IN_PROGRESS:
            cat = "in_progress"
        elif st in BLOCKED:
            cat = "blocked"
        else:  # pending ほか未知の値は未着手として扱う
            cat = "waiting" if open_deps else "ready"
        when = _scheduled(t.get("scheduled_for"))
        due = _scheduled(t.get("due"))
        if cat == "ready" and when and when > today:  # 実行時期の来ていない Task は「待ち」
            cat = "waiting"
        # 回す日: daily・weekly の運用タスクは 04-operation Phase 1 の決まりで、まだ回す日でなければ「待ち」。
        # 依存待ち・blocked・完了・除外の判定は先に決まったまま。retired_at のある運用タスクと他の recurrence は今どおり
        kind = _norm(t.get("recurrence"))
        retired = bool(t.get("retired_at"))
        gap = RECURRING_GAP_DAYS.get(kind) if kind and not retired else None
        last_run = next_run = None
        waiting_for_run = False
        if gap is not None:
            runs = [_scheduled(r.get("date")) for r in (t.get("runs") or []) if isinstance(r, dict)]
            runs = [r for r in runs if r and r <= today]   # 未来の日付の run は数えない
            last_run = max(runs) if runs else None
            if when and when > today:   # scheduled_for は回し始める日。その日まで出さない（実行時期の待ちとして示す）
                if cat in ("ready", "in_progress"):
                    cat = "waiting"
                if cat == "waiting" and not open_deps:   # 依存待ちには次の日を付けない
                    next_run = when
            elif cat in ("ready", "in_progress") and last_run and (today - last_run).days < gap:
                cat = "waiting"
                waiting_for_run = True
                next_run = last_run + timedelta(days=gap)
        # 前回回した日（どの recurrence でも。今日以前の読める日付の最大）。詳細の表示用で、回す日の判定には使わない
        last_run_any = None
        if kind:
            past = [d for d in (_scheduled(r.get("date")) for r in (t.get("runs") or []) if isinstance(r, dict)) if d and d <= today] \
                if isinstance(t.get("runs"), list) else []
            last_run_any = max(past).isoformat() if past else None
        ac = t.get("acceptance_criteria")
        tasks.append({
            "id": tid,
            "name": str(t.get("name") or t.get("title") or ""),
            "status": st or "pending",
            "category": cat,
            "priority": str(t.get("priority") or ""),
            "type": str(t.get("type") or ""),
            "dependencies": [{"id": d, "status": status_of.get(d, "not_in_backlog")} for d in deps],
            "open_dependencies": open_deps,
            "ac_count": len(ac) if isinstance(ac, list) else 0,
            "acceptance_criteria": [_clip(_text(a)) for a in ac] if isinstance(ac, list) else [],
            "detail": _detail(t),
            "order": i,
            # 繰り返す運用タスク（recurrence）は完了しないので完了率の分母と「いま」の候補から外す
            "recurring": bool(t.get("recurrence")),
            "recurrence": kind or None,
            "retired": retired,
            # daily・weekly の運用タスクだけ: 最後の run・次に回す日・回す日か
            "last_run": last_run.isoformat() if last_run else None,
            "last_run_any": last_run_any,
            "next_run": next_run.isoformat() if next_run else None,
            "waiting_for_run": waiting_for_run,
            "run_due": bool(gap is not None and cat in ("ready", "in_progress")),
            "scheduled_for": when.isoformat() if when else None,
            "waiting_for_schedule": bool(cat == "waiting" and when and when > today),   # 完了・進行中は時期が先でも待ちにしない
            # 読めない時期は時期なしとして並べ、元の値と印を返す
            "scheduled_for_raw": None if t.get("scheduled_for") is None else str(t.get("scheduled_for")),
            "scheduled_for_invalid": _unreadable(t.get("scheduled_for")),
            # 期限 due は並びと実行可能の判定に使わず、札に添えるだけ
            "due": due.isoformat() if due else (None if t.get("due") is None else str(t.get("due"))),
            "due_invalid": _unreadable(t.get("due")),
            "overdue": bool(due and due < today and cat not in ("done", "excluded")),
        })

    # この Task を依存先にしている Task（詳細の「この Task を待っている Task」）
    for t in tasks:
        t["dependents"] = [{"id": u["id"], "status": u["status"]} for u in tasks
                           if u is not t and any(d["id"] == t["id"] for d in u["dependencies"])]

    counts = {c: sum(1 for t in tasks if t["category"] == c) for c in CATEGORIES}
    # 帯と凡例は通常 Task だけを数える（運用タスクは下の operations で別に示す）
    counts_normal = {c: sum(1 for t in tasks if t["category"] == c and not t["recurring"]) for c in CATEGORIES}
    # いま回している運用タスク（retired_at が無く、除外・完了でないもの）
    ops = [t for t in tasks if t["recurring"] and not t["retired"] and t["category"] not in ("done", "excluded")]
    next_runs = sorted(t["next_run"] for t in ops if t["next_run"])
    operations = {"count": len(ops), "due": sum(1 for t in ops if t["run_due"]),
                  "next": next_runs[0] if next_runs else None}
    recurring = sum(1 for t in tasks if t["recurring"] and t["category"] != "excluded")
    target = len(tasks) - counts["excluded"] - recurring
    # 完了の分子も運用タスクを除く（誤って completed の運用タスクで 100% を超えない）
    done_normal = sum(1 for t in tasks if t["category"] == "done" and not t["recurring"])

    def rank(t: dict) -> tuple:
        # 実行時期のある Task（今日以前）を時期の早い順に先に、その後に時期の無い Task を優先度順
        due_now = t["scheduled_for"] and t["scheduled_for"] <= today.isoformat()  # a later date never comes first
        sched = (0, t["scheduled_for"]) if due_now else (1, "")
        return (sched, PRIORITY_ORDER.get(t["priority"].upper(), 9), t["order"])

    current, current_order, current_reason = None, None, None
    for cat, reason in (("in_progress", "進行中"), ("ready", "次に実行できるタスク")):
        cands = sorted((t for t in tasks if t["category"] == cat and not t["recurring"]), key=rank)
        if cands:
            current, current_order, current_reason = cands[0]["id"], cands[0]["order"], reason
            break

    # 流れの図は依存のつながりだけを描く。運用タスクは「運用・予定」のタブに出すので、段・線・最長の連なりに入れない
    flow = build_flow([t for t in tasks if not t["recurring"]], current_order)
    for t in tasks:
        if t["recurring"]:
            t["level"], t["in_cycle"] = None, False
    flow["hidden_recurring"] = sum(1 for t in tasks if t["recurring"])
    agenda = build_agenda(tasks_in, tasks, today)

    open_normal = [t for t in tasks if t["category"] not in ("done", "excluded") and not t["recurring"]]
    intent_status = _norm((intent if isinstance(intent, dict) else {}).get("status"))
    sublayers = backlog.get("sublayers")
    if intent_status == "cancelled":
        stage, stage_label = "cancelled", "中止（cancelled）"
    elif not tasks and isinstance(sublayers, list) and sublayers:
        stage, stage_label = "sublayers", f"SubLayer で進行（{len(sublayers)}件）"
    elif not tasks:
        stage, stage_label = "inception_wait", "Inception 待ち（タスク未作成）"
    elif target == 0 and recurring:
        # 通常 Task が無く運用タスクだけ。完了率は出さない（percent は null）
        # 閉じていない運用タスクが無ければ「運用中」と出さない（stage の値は operating のまま）
        stage, stage_label = "operating", (f"運用中（運用タスク {recurring}件）" if ops
                                           else f"運用タスクはすべて閉じています（{recurring}件）")
    elif open_normal and all(t["category"] == "waiting" and t["waiting_for_schedule"] for t in open_normal):
        # 未完了の通常 Task が全部、実行時期の来ていない待ち（Inception 待ちの後、Operation 中の前に判定する）
        nxt = min(t["scheduled_for"] for t in open_normal)
        stage, stage_label = "schedule_wait", f"実行時期待ち（次 {_md(nxt)}）"
    elif open_normal:
        stage, stage_label = "operation", "Operation 中"
    elif target > 0 and ops:
        # 通常 Task は全部完了で、運用タスクが残る。done/target と percent はそのまま
        stage, stage_label = "done_operating", f"通常タスク完了・運用中（運用タスク {len(ops)}件）"
    elif counts["done"] == 0:
        stage, stage_label = "all_excluded", "全タスク除外（完了0件）"
    else:
        stage, stage_label = "all_done", "全タスク完了"

    intent = intent if isinstance(intent, dict) else {}
    goal = intent.get("goal")
    goal_text = _text(goal.get("description") if isinstance(goal, dict) else goal)
    return {
        "scope_id": str(intent.get("scope_id") or backlog.get("scope_id") or ""),
        "name": str(intent.get("display_name") or intent.get("scope_name") or ""),
        "goal": str(goal_text or "").strip(),
        "tasks": tasks,
        "counts": counts,
        "counts_normal": counts_normal,
        "operations": operations,
        "total": len(tasks),
        "target": target,
        "recurring": recurring,
        "done": done_normal,
        # 未完了が残る間は 100% と出さない。運用タスクだけの Layer は完了率が無い（null。画面は「—」）
        "percent": None if stage == "operating" else (done_normal * 100 // target) if target else 0,
        "duplicate_ids": sorted(set(duplicates)),
        "current": current,
        "current_order": current_order,
        "current_reason": current_reason,
        "flow": flow,
        "agenda": agenda,
        # 「運用・予定」タブを出すか: 見るものがあるときだけ。閉じていない運用タスク（上の ops）か、
        # まだ終わっていない Task の実行時期・期限（読めない値を含む）がある。閉じた運用タスクや完了・除外の日付だけなら出さない
        "has_ops_tab": bool(ops or agenda["entries"] or agenda["invalid"]),
        "stage": stage,
        "stage_label": stage_label,
    }


@dataclass
class LayerReader:
    """Layer 1つを読む。stat が変わったときだけ読み直し、失敗時は最後の正常値を返す。"""

    folder: Path
    _key: Any = None
    _good: Optional[dict] = None
    _error: Optional[str] = None
    _intent_error: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def state(self) -> dict:
        backlog_p, intent_p = self.folder / "backlog.yaml", self.folder / "intent.yaml"
        key = (_stat(backlog_p), _stat(intent_p))
        with self._lock:
            if key != self._key:
                self._key = key
                self._reload(backlog_p, intent_p, key)
            body = dict(self._good) if self._good else {}
            body.update({
                "ok": self._good is not None and self._error is None,
                "error": self._error,
                "intent_error": self._intent_error,
                "stale": self._good is not None and self._error is not None,
                "layer_path": str(self.folder),
                "backlog_mtime": _iso(key[0][0]) if key[0] else None,
                "read_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            })
            return body

    def _reload(self, backlog_p: Path, intent_p: Path, key: tuple) -> None:
        if key[0] is None:
            self._error = "backlog.yaml が見つかりません"
            return
        try:
            backlog = _read_yaml(backlog_p)
            intent, intent_error = None, None
            if key[1] is not None:
                try:
                    intent = _read_yaml(intent_p)
                except Exception as exc:  # intent が壊れていてもタスク表示は続ける
                    intent_error = f"intent.yaml を読めませんでした（{type(exc).__name__}）"
            # 読んでいる間に保存されたら次のポーリングで読み直す
            if (_stat(backlog_p), _stat(intent_p)) != key:
                self._key = None
            self._good = summarize(backlog, intent)
            self._error, self._intent_error = None, intent_error
        except Exception as exc:  # 保存途中・不正 YAML
            self._error = f"backlog.yaml を読めませんでした（{type(exc).__name__}: {str(exc)[:160]}）"


def _visible_dirs(folder: Path) -> list[Path]:
    try:
        return sorted((e for e in folder.iterdir()
                       if e.is_dir() and not e.is_symlink() and not e.name.startswith(".")), reverse=True)
    except OSError:
        return []


def scan_layers(top: Path) -> set[str]:
    """top 配下の Layer（backlog.yaml と intent.yaml があるフォルダ）。

    隠しフォルダ・symlink・PRUNE_DIRS には降りない。
    """
    found: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() not in PRUNE_DIRS]
        if "backlog.yaml" in filenames and "intent.yaml" in filenames:
            found.add(dirpath)
    return found


def _backlog_mtime(layer: str, limit: int) -> Optional[int]:
    try:
        st = os.lstat(os.path.join(layer, "backlog.yaml"))
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_mtime_ns > limit:  # symlink・未来時刻は使わない
        return None
    return st.st_mtime_ns


def pick_latest(layers) -> Optional[tuple[Path, int]]:
    limit = time.time_ns() + 60 * 10**9
    best: Optional[tuple[int, str]] = None
    for layer in layers:
        mtime = _backlog_mtime(layer, limit)
        if mtime is not None and (best is None or (mtime, layer) > best):
            best = (mtime, layer)
    return (Path(best[1]), best[0]) if best else None


def find_latest_layer(flow_root: Path) -> Optional[tuple[Path, int]]:
    """Flow 配下で backlog.yaml の保存が最も新しい Layer（全体を走査する）。"""
    return pick_latest(scan_layers(flow_root))


def _head_value(raw: str) -> str:
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        end = raw.find(raw[0], 1)
        return raw[1:end] if end > 0 else raw[1:]
    return raw.split(" #", 1)[0].strip()


def read_intent_head(layer: str) -> dict:
    """intent.yaml の最上位の scope_id・display_name・scope_name だけを軽く読む（候補一覧・照合用）。"""
    try:
        with open(os.path.join(layer, "intent.yaml"), encoding="utf-8", errors="replace") as f:
            text = f.read(65536)
    except OSError:
        return {}
    head: dict = {}
    for m in _HEAD_FIELD.finditer(text):
        head.setdefault(m.group(1), _head_value(m.group(2)))
    return head


class Follower:
    """作業中（最後に backlog.yaml が保存された）Layer を追って表示する。

    Flow 全体の走査は FULL_SCAN_TTL ごと（実測 0.4〜1秒）。その間は、見つけ済みの Layer の
    stat と、日付の新しいフォルダ（Flow/<新しい月2つ>/<新しい日2つ>）だけを SCAN_TTL ごとに見る。
    """

    def __init__(self, flow_root: Path, repo_root: Path):
        self.flow_root, self.repo_root = flow_root, repo_root
        self._readers: dict[Path, LayerReader] = {}
        self._known: set[str] = set()
        self._latest: Optional[tuple[Path, int]] = None
        self._scanned_at = self._full_at = float("-inf")
        self._heads: dict[str, tuple[Any, dict]] = {}
        self._lock = threading.Lock()

    def _head(self, layer: str) -> dict:
        key = _stat(Path(layer) / "intent.yaml")
        cached = self._heads.get(layer)
        if cached is None or cached[0] != key:
            cached = (key, read_intent_head(layer))
            self._heads[layer] = cached
        return cached[1]

    def _rel(self, layer: str) -> str:
        try:
            return str(Path(layer).relative_to(self.repo_root))
        except ValueError:
            return layer

    def _ensure_fresh(self) -> None:
        if time.monotonic() - self._scanned_at >= SCAN_TTL:
            self._refresh()

    def _reader(self, folder: Path) -> LayerReader:
        reader = self._readers.pop(folder, None) or LayerReader(folder)
        self._readers[folder] = reader  # 末尾＝最近使った
        while len(self._readers) > MAX_READERS:
            self._readers.pop(next(iter(self._readers)))
        return reader

    def _recent_dirs(self) -> list[Path]:
        """日付の新しいフォルダ（Flow 直下の企画書・templates 等の日付以外は除く）。"""
        days: list[Path] = []
        for month in [m for m in _visible_dirs(self.flow_root) if MONTH_DIR.match(m.name)][:2]:
            days.extend([d for d in _visible_dirs(month) if DAY_DIR.match(d.name)][:2])
        return days

    def _refresh(self) -> None:
        now = time.monotonic()
        if now - self._full_at >= FULL_SCAN_TTL:
            self._known = scan_layers(self.flow_root)
            self._full_at = now
        else:
            known = {k for k in self._known if os.path.isdir(k)}
            # 見つけ済み Layer の sublayers/ と新しい日付フォルダで新規 Layer を拾う
            tops = [Path(k) / "sublayers" for k in known if os.path.isdir(os.path.join(k, "sublayers"))]
            for top in tops + self._recent_dirs():
                known |= scan_layers(top)
            self._known = known
        self._latest = pick_latest(self._known)
        self._scanned_at = now

    def _match(self, scope_id: str, at: Optional[str]) -> list[str]:
        limit = time.time_ns() + 60 * 10**9  # 追従と同じく symlink・未来時刻の backlog は使わない
        found = [k for k in self._known
                 if self._head(k).get("scope_id") == scope_id and _backlog_mtime(k, limit) is not None]
        if at is not None:
            found = [k for k in found if self._rel(k) == at]
        return sorted(found)

    def layers(self) -> dict:
        """候補一覧（backlog の保存が新しい順・上限 MAX_CANDIDATES）。"""
        with self._lock:
            self._ensure_fresh()
            limit = time.time_ns() + 60 * 10**9
            rows = [(m, k) for k in self._known if (m := _backlog_mtime(k, limit)) is not None]
            rows.sort(reverse=True)
            counts: dict[str, int] = {}
            for _, k in rows:
                sid = self._head(k).get("scope_id", "")
                counts[sid] = counts.get(sid, 0) + 1
            out = []
            for mtime, k in rows[:MAX_CANDIDATES]:
                head = self._head(k)
                sid = head.get("scope_id", "")
                row = {"scope_id": sid, "name": head.get("display_name") or head.get("scope_name") or "",
                       "rel": self._rel(k), "backlog_mtime": _iso(mtime)}
                if counts.get(sid, 0) > 1:
                    row["at"] = row["rel"]  # 同じ scope_id が複数あるときは一覧から1回で選べるように
                out.append(row)
        return {"available": True, "layers": out, "total": len(rows)}

    def pinned_state(self, scope_id: str, at: Optional[str]) -> dict:
        now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
        base = {"mode": "pinned", "requested_layer": scope_id, "read_at": now_iso}
        if not SCOPE_PARAM.match(scope_id) or (at is not None and len(at) > 512):
            return {**base, "ok": False, "error": "layer の指定が scope_id の形ではありません（例: ?layer=L-1234）"}
        with self._lock:
            self._ensure_fresh()
            found = self._match(scope_id, at)
            if not found and time.monotonic() - self._full_at >= RESCAN_ON_MISS:
                self._full_at = float("-inf")  # 古い日付の下に新しくできた Layer を拾い直す
                self._refresh()
                found = self._match(scope_id, at)
            if len(found) > 1:
                cands = [{"scope_id": scope_id, "rel": self._rel(k), "at": self._rel(k),
                          "name": self._head(k).get("display_name") or self._head(k).get("scope_name") or ""}
                         for k in found]
                return {**base, "ok": False, "candidates": cands,
                        "error": f"scope_id {scope_id} の Layer が {len(found)} 件あります。表示するものを選んでください"}
            reader = self._reader(Path(found[0])) if found else None
        if reader is None:
            return {**base, "ok": False, "error": f"scope_id {scope_id} の Layer が Flow の下に見つかりません"}
        body = reader.state()
        body.update({"mode": "pinned", "requested_layer": scope_id})
        _add_rel(body, self.repo_root)
        return body

    def state(self, query: Optional[dict] = None) -> dict:
        query = query or {}
        if query.get("layer") is not None:
            return self.pinned_state(query["layer"], query.get("at"))
        with self._lock:
            self._ensure_fresh()
            latest = self._latest
            reader = self._reader(latest[0]) if latest else None
        if reader is None:
            return {"ok": False, "error": f"{self.flow_root} の下に Layer（backlog.yaml と intent.yaml）が見つかりません",
                    "mode": "follow", "read_at": datetime.now().astimezone().isoformat(timespec="seconds")}
        body = reader.state()
        body.update({"mode": "follow", "follow_basis_mtime": _iso(latest[1])})
        _add_rel(body, self.repo_root)
        return body


def _add_rel(body: dict, repo_root: Path) -> None:
    try:
        body["layer_rel"] = str(Path(body["layer_path"]).relative_to(repo_root))
    except (KeyError, ValueError):
        body["layer_rel"] = body.get("layer_path")


class FixedSource:
    def __init__(self, folder: Path, repo_root: Path):
        self.reader, self.repo_root = LayerReader(folder), repo_root

    def state(self, query: Optional[dict] = None) -> dict:
        body = self.reader.state()
        body["mode"] = "fixed"
        if (query or {}).get("layer") is not None:
            body["layer_param_ignored"] = "起動時に --layer で固定しているため、URL の layer 指定は使えません"
        _add_rel(body, self.repo_root)
        return body

    def layers(self) -> dict:
        return {"available": False, "layers": [], "total": 0,
                "reason": "起動時に --layer で固定しているため、Layer は選べません"}


def make_handler(reader):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BacklogLive/0.1"

        def log_message(self, *_args):  # 静かにする
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
                             "frame-ancestors 'self'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            return host in ALLOWED_HOSTS

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"ok": False, "error": "Host が許可されていません"})
            parts = urlsplit(self.path)
            path = parts.path
            if path == "/api/state":
                try:
                    qs = parse_qs(parts.query, keep_blank_values=False, max_num_fields=8)
                except ValueError:
                    return self._json(400, {"ok": False, "error": "クエリが多すぎます"})
                query = {k: v[0] for k, v in qs.items() if k in ("layer", "at") and v}
                return self._json(200, reader.state(query))
            if path == "/api/layers":
                return self._json(200, reader.layers())
            if path in STATIC_FILES:
                name, ctype = STATIC_FILES[path]
                return self._send(200, (STATIC / name).read_bytes(), ctype)
            return self._json(404, {"ok": False, "error": "not found"})

        do_HEAD = do_GET

        def _reject(self):
            self._json(405, {"ok": False, "error": "閲覧専用です"})

        do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _reject

    return Handler


def build_server(layer: Optional[Path], port: int, root: Path = REPO_ROOT) -> ThreadingHTTPServer:
    """layer を渡せば固定表示、None なら root/Flow 配下の作業中 Layer を追従する。"""
    reader = FixedSource(layer, root) if layer is not None else Follower(root / "Flow", root)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(reader))
    server.daemon_threads = True
    return server


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AI-PLC backlog.yaml のライブビューア（閲覧専用）")
    ap.add_argument("--layer", help="固定表示する Layer フォルダ。省略時は最後に backlog.yaml が保存された Layer を追従")
    ap.add_argument("--root", default=str(REPO_ROOT), help="リポジトリのルート（追従時は <root>/Flow を見る）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"ポート（既定 {DEFAULT_PORT}、0 で空きポート）")
    ap.add_argument("--no-browser", action="store_true", help="ブラウザを開かない")
    args = ap.parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    layer = Path(args.layer).expanduser().resolve() if args.layer else None
    if layer is not None and not layer.is_dir():
        print(f"Layer フォルダが見つかりません: {layer}", file=sys.stderr)
        return 2
    if layer is None and not (root / "Flow").is_dir():
        print(f"追従する Flow フォルダが見つかりません: {root / 'Flow'}", file=sys.stderr)
        return 2
    try:
        server = build_server(layer, args.port, root)
    except OSError as exc:
        print(f"ポート {args.port} で起動できません（{exc}）。--port 0 を試してください", file=sys.stderr)
        return 2
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    target = f"Layer 固定: {layer}" if layer else f"追従: {root / 'Flow'}"
    print(f"BacklogLive: {url}  （{target}）  止めるときは Ctrl-C", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
