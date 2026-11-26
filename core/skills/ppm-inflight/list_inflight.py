#!/usr/bin/env python3
"""進行中の候補を Layer の intent から洗い出し、TODO の一覧との差分を提案する（読むだけ）。

TODO の一覧も Layer も Registry も書き換えない。反映は /ppm-todo（本人が承認した行だけ書く）。

見る範囲:
- リポジトリの `Flow/` と `.ai-plc/projects/` の下の `intent.yaml`（親の Layer だけ）。
  `sublayers/` の下・`parent_scope` のある Layer・Layer の中の `Documents/`・`Context/` の写しは見ない。
  リンクで置き場の外を指す `intent.yaml`・`backlog.yaml` は読まない（置き場の `Flow` 自体はリンクでもよい）
- 進行中とみなすのは intent の status が active か blocked で、backlog の通常のタスクが全部は終わっていないもの
  （全部終わっていても、子の Layer が active・blocked なら進行中）
- TODO の一覧の注記の layer が絶対パスなら、リポジトリの中のものは相対パスに直して照らす。
  リポジトリの外を指す注記は「外す候補」にせず、別に数える
- 題名は intent の display_name（無ければ scope_name、無ければフォルダ名）。ID は intent の scope_id をそのまま使う
- 「足す候補」に出すのは、最近の Layer（設定 `ppm.inflight.recent_days`、既定 21 日）だけ。
  古い Layer は件数だけ出す（日付はフォルダの名前の YYYY-MM-DD → intent の start_date・created_at → intent.yaml の更新日の順で決める）

TODO の一覧の置き場と節の名前は、ppm スキルの ppm_files.py（設定 `.ai-plc/config.yaml` の `ppm:`）で決まる。

使い方（導入先のリポジトリのルートで）:
  python3 .claude/skills/ppm-inflight/list_inflight.py [--json] [--root <repo>] [--today YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.dont_write_bytecode = True

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML が要ります: python3 -m pip install pyyaml", file=sys.stderr)
    raise SystemExit(1)

HERE = Path(__file__).resolve().parent
LAYER_BASES = ("Flow", ".ai-plc/projects")
SKIP_PARTS = {"sublayers", "Documents", "Context"}
DONE = {"completed", "done", "cancelled", "dropped"}
CLOSED = {"completed", "cancelled", "done", "dropped"}
OPEN_INTENT = {"active", "blocked"}
TITLE_MAX = 40
FOLDER_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})$")
WEEK_RE = re.compile(r"^(\d{4})-[Ww](\d{2})$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- 隣のスキルの部品を読む ---------------------------------------------------------

def load_sibling(skill: str, filename: str, modname: str):
    """隣のスキル（同じ skills フォルダの <skill>/<filename>）を読み込む。
    配布の形（core/skills/…）でも導入先（.claude/skills/…・.cursor/skills/…）でも見つかる。"""
    if modname in sys.modules:
        return sys.modules[modname]
    cands = [HERE.parent / skill / filename]
    cwd = Path.cwd()
    cands += [cwd / d / "skills" / skill / filename for d in (".claude", ".cursor")]
    for f in cands:
        if f.is_file():
            spec = importlib.util.spec_from_file_location(modname, f)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[modname] = mod
            spec.loader.exec_module(mod)
            return mod
    raise ImportError(f"{skill}/{filename} が見つかりません（ppm スキルが入っているか確かめてください）")


def ppm_files():
    return load_sibling("ppm", "ppm_files.py", "ppm_files")


# --- 日付 -----------------------------------------------------------------------

def _as_date(raw) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip().strip("'\"")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def scheduled_date(value) -> date | None:
    """実行時期 scheduled_for（YYYY-MM-DD か YYYY-Www＝その週の月曜）。読めなければ None。"""
    if isinstance(value, (datetime, date)):
        return _as_date(value)
    v = str(value if value is not None else "").strip().strip("'\"").strip()
    m = WEEK_RE.match(v)
    try:
        if m:
            return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        if DAY_RE.match(v[:10]):
            return date.fromisoformat(v[:10])
    except ValueError:
        return None
    return None


# --- Layer を読む -------------------------------------------------------------------

def _read_yaml(path: Path):
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 壊れたファイルは読まずに数える
        return None
    return data


def _parent_scope(data: dict) -> str | None:
    raw = data.get("parent_scope")
    if isinstance(raw, str) and raw.strip() and raw.strip().lower() not in {"null", "none"}:
        return raw.strip()
    return None


def _inside(path: Path, top: Path) -> bool:
    """path（リンクを解いた先）が置き場 top（の実体）の中か。"""
    try:
        return path.resolve().is_relative_to(top.resolve())
    except OSError:
        return False


def iter_intents(root: Path):
    """親の Layer の intent.yaml のパス（Flow と .ai-plc/projects の下）と、それが置き場の中の実体か。"""
    root = Path(root)
    for base in LAYER_BASES:
        top = root / base
        if not top.is_dir():
            continue
        for p in sorted(top.rglob("intent.yaml")):
            rel_parts = p.relative_to(top).parts[:-1]
            if any(part in SKIP_PARTS or part.startswith(".") for part in rel_parts):
                continue
            yield p, _inside(p, top) and _inside(p.parent, top)


def _backlog(layer_dir: Path) -> dict:
    p = layer_dir / "backlog.yaml"
    data = _read_yaml(p) if p.is_file() and _inside(p, layer_dir) else None
    return data if isinstance(data, dict) else {}


def backlog_all_done(backlog: dict) -> bool | None:
    """通常のタスクが全部終わったか。タスクが無ければ None。運用タスク（recurrence）は retired_at が無ければ未完了。"""
    tasks = backlog.get("tasks") or []
    statuses = []
    for t in tasks if isinstance(tasks, list) else []:
        if not isinstance(t, dict):
            continue
        st = str(t.get("status") or "").strip().lower()
        if t.get("recurrence"):
            st = "completed" if t.get("retired_at") else "in_progress"
        statuses.append(st)
    if not statuses:
        return None
    return all(s in DONE for s in statuses)


def has_open_child(intent: dict, backlog: dict) -> bool:
    for key, src in (("sub_agent_scopes", intent), ("sublayers", backlog)):
        for item in src.get(key) or []:
            if isinstance(item, dict) and str(item.get("status") or "").strip().lower() in OPEN_INTENT:
                return True
    return False


def backlog_schedule(backlog: dict, today: date) -> tuple[str | None, bool]:
    """未完了の通常タスクから (いちばん早い先の実行時期, 全部が時期待ちか)。
    時期待ち = 今日より後の時期があり、in_progress・blocked でない。"""
    open_tasks = []
    tasks = backlog.get("tasks")
    for t in tasks if isinstance(tasks, list) else []:
        if not isinstance(t, dict) or t.get("recurrence"):
            continue
        st = str(t.get("status") or "").strip().lower()
        if st in DONE or st == "deferred":
            continue
        open_tasks.append((st, scheduled_date(t.get("scheduled_for"))))
    future = [d for _, d in open_tasks if d and d > today]
    waiting_only = bool(open_tasks) and all(
        st not in ("in_progress", "blocked") and d and d > today for st, d in open_tasks)
    return (min(future).isoformat() if future else None), waiting_only


def layer_date(intent_path: Path, rel_parts: tuple, intent: dict) -> tuple[date | None, str]:
    """Layer の日付と出どころ（folder / intent / mtime）。"""
    for part in reversed(rel_parts):
        m = FOLDER_DATE_RE.match(part)
        if m:
            d = _as_date(m.group(1))
            if d:
                return d, "folder"
    for key in ("start_date", "created_at", "created"):
        d = _as_date(intent.get(key))
        if d:
            return d, "intent"
    try:
        return datetime.fromtimestamp(intent_path.stat().st_mtime).date(), "mtime"
    except OSError:
        return None, ""


def make_title(intent: dict, layer_dir: Path) -> str:
    name = intent.get("display_name") or intent.get("scope_name") or layer_dir.name
    text = " ".join(str(name).split()) or layer_dir.name
    return text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1] + "…"


def read_layers(root: Path, today: date | None = None) -> dict:
    """全部の親の Layer を読む。返り値 {"layers": [行…], "unreadable": [パス…], "duplicates": [scope_id…],
    "outside_links": [パス…]}（outside_links はリンクで置き場の外を指すので読まなかった intent）。
    行: scope_id・title・layer（リポジトリからの相対パス）・status・deadline・open・all_done・…"""
    root = Path(root).resolve()
    today = today or date.today()
    out, unreadable, seen, dups, outside = [], [], set(), [], []
    for p, inside in iter_intents(root):
        rel = p.parent.relative_to(root).as_posix()
        if not inside:
            outside.append(rel)
            continue
        data = _read_yaml(p)
        if not isinstance(data, dict):
            unreadable.append(rel)
            continue
        if _parent_scope(data):
            continue
        scope = str(data.get("scope_id") or "").strip()
        if not scope:
            unreadable.append(rel)
            continue
        if scope in seen:
            dups.append(scope)
            continue
        seen.add(scope)
        backlog = _backlog(p.parent)
        status = str(data.get("status") or "").strip().lower()
        all_done = backlog_all_done(backlog)
        open_child = has_open_child(data, backlog)
        is_open = status in OPEN_INTENT and not (all_done is True and not open_child)
        deadline = _as_date(data.get("deadline"))
        d, d_from = layer_date(p, p.parent.relative_to(root).parts, data)
        nxt, waiting_only = backlog_schedule(backlog, today)
        out.append({
            "scope_id": scope, "title": make_title(data, p.parent), "layer": rel, "status": status,
            "open": is_open, "all_done": all_done, "deadline": deadline.isoformat() if deadline else None,
            "stale": bool(deadline and deadline < today),
            "blocked": status == "blocked" or bool(data.get("block_reason")),
            "layer_date": d.isoformat() if d else None, "layer_date_from": d_from,
            "next_scheduled": nxt, "schedule_waiting_only": waiting_only,
        })
    return {"layers": out, "unreadable": unreadable, "duplicates": sorted(set(dups)), "outside_links": outside}


def layer_index(root: Path, today: date | None = None) -> dict:
    """scope_id → Layer の行（閉じた Layer も含む）。待ちの見直し・まとめが案件の状態を引くのに使う。"""
    return {r["scope_id"]: r for r in read_layers(root, today)["layers"]}


# --- TODO の一覧と比べる ---------------------------------------------------------------

def _norm(path: str | None, root: Path | None = None) -> str | None:
    """注記の layer を、リポジトリからの相対パスの形にそろえる（os.path.normpath で `./`・`a/../b` を畳む）。
    絶対パス（`~` は展開する）でリポジトリの中なら相対に直す（途中に `..` があっても、畳んだ先が中なら直す）。
    リポジトリの外の絶対パスは絶対パスのまま、外に出る相対パスは `../…` の形で返す（outside_ref で見分ける）。"""
    if not path:
        return None
    s = str(path).strip().replace("\\", "/")
    if not s:
        return None
    if s.startswith("~"):
        s = os.path.expanduser(s)
    s = os.path.normpath(s).replace("\\", "/")
    if s.startswith("/") and root is not None:
        p = Path(s)
        for base in (Path(os.path.abspath(root)), Path(root).resolve()):
            if p.is_relative_to(base):
                s = p.relative_to(base).as_posix()
                break
    return None if s in (".", "") else s


def outside_ref(path: str | None, root: Path) -> bool:
    """注記の layer がリポジトリの外を指すか（外の絶対パス、または畳むと外に出る相対パス）。"""
    n = _norm(path, root)
    return bool(n) and (n.startswith("/") or n.startswith("~") or n == ".." or n.startswith("../"))


def todo_refs(todo: dict | None, text: str | None, pf, root: Path | None = None) -> dict:
    """TODO の一覧の進行中の行の layer・scope と、ほかの所（進行中の外）に書かれた layer・scope。"""
    listed: list[dict] = []
    keys_in: set = set()
    if todo is not None:
        for it in todo["inflight"]:
            if not (it.get("layer") or it.get("scope")):
                continue
            listed.append(it)
            keys_in.update(k for k in (it.get("scope"), _norm(it.get("layer"), root)) if k)
    elsewhere: set = set()
    for m in pf.LAYER_RE.finditer(text or ""):
        for k in (m.group(2), _norm(m.group(1), root)):
            if k and k not in keys_in:
                elsewhere.add(k)
    return {"listed": listed, "keys_in": keys_in, "elsewhere": elsewhere}


def _row_keys(r: dict) -> set:
    return {r["scope_id"], _norm(r["layer"])}


def diff_proposal(layers: dict, todo: dict | None, todo_text: str | None, cfg: dict, today: date, pf,
                  root: Path | None = None) -> dict:
    """keep（一覧にある）・add（足す候補）・parked（古いので候補にしない）・elsewhere（進行中の外に書いてある）・
    remove（外す候補）・stale（期限を過ぎたか止まっている）・outside_notes（リポジトリの外を指す注記）。"""
    rows = layers["layers"]
    open_rows = [r for r in rows if r["open"]]
    refs = todo_refs(todo, todo_text, pf, root)
    recent_days = cfg["inflight"]["recent_days"]
    by_key = {}
    for r in rows:
        for k in _row_keys(r):
            by_key.setdefault(k, r)

    def listed_item(r):
        for it in refs["listed"]:
            if {it.get("scope"), _norm(it.get("layer"), root)} & _row_keys(r):
                return it
        return None

    keep, add, parked, elsewhere = [], [], [], []
    for r in open_rows:
        it = listed_item(r)
        if it is not None:
            keep.append(dict(r, todo_title=it["title"], todo_done=it["done"], todo_line=it["line"]))
            continue
        if _row_keys(r) & refs["elsewhere"]:
            elsewhere.append(r)
            continue
        d = _as_date(r["layer_date"])
        recent = bool(d and (today - d).days <= recent_days)
        (add if recent else parked).append(r)

    remove, outside_notes = [], []
    for it in refs["listed"]:
        if it["done"]:
            continue
        keys = {it.get("scope"), _norm(it.get("layer"), root)} - {None}
        r = next((by_key[k] for k in keys if k in by_key), None)
        if r is not None and r["open"]:
            continue
        if r is None and root is not None and outside_ref(it.get("layer"), root):
            outside_notes.append({"title": it["title"], "scope_id": it.get("scope"), "layer": it.get("layer"),
                                  "line": it["line"]})
            continue
        if r is None:
            why = "Layer が見つからない"
        elif r["status"] in CLOSED:
            why = f"案件は閉じている（{r['status']}）"
        elif r["all_done"]:
            why = "タスクが全部終わっている"
        else:
            why = f"進行中でない（{r['status'] or '状態なし'}）"
        remove.append({"title": it["title"], "scope_id": it.get("scope"), "layer": it.get("layer"),
                       "line": it["line"], "reason": why})

    stale = [r for r in open_rows if r["stale"] or r["blocked"]]
    key = lambda r: (r["stale"], r["scope_id"])  # noqa: E731
    return {"keep": sorted(keep, key=key), "add": sorted(add, key=key), "parked": sorted(parked, key=key),
            "elsewhere": sorted(elsewhere, key=key), "remove": remove, "stale": sorted(stale, key=key),
            "outside_notes": outside_notes, "todo_found": todo is not None, "recent_days": recent_days,
            "unreadable": layers["unreadable"], "duplicates": layers["duplicates"],
            "outside_links": layers.get("outside_links", []),
            # 一覧はあるのに進行中の節の見出しが1つも無い（節の名前が設定と違うなど）
            "inflight_sections_missing": todo is not None and not any(
                sec["kind"] == "inflight" for sec in todo.get("sections", [])),
            "inflight_section_names": list(cfg["todo"]["inflight_sections"] or [])}


def propose(root=None, today: date | None = None) -> dict:
    """設定と TODO の一覧を読み、提案を作る（読むだけ）。"""
    pf = ppm_files()
    root, cfg = pf.context(root)
    today = today or date.today()
    path = pf.todo_path(root, cfg)
    text = path.read_text(encoding="utf-8") if path.is_file() else None
    todo = pf.parse_todo(text, cfg) if text is not None else None
    res = diff_proposal(read_layers(root, today), todo, text, cfg, today, pf, root)
    res["todo_path"] = str(path)
    res["today"] = today.isoformat()
    return res


# --- 出力 -------------------------------------------------------------------------

def schedule_note(r: dict) -> str:
    nxt = r.get("next_scheduled")
    if not (r.get("schedule_waiting_only") and nxt):
        return ""
    d = date.fromisoformat(nxt)
    return f"（時期待ち {d.month}/{d.day}〜）"


def _flags(r: dict) -> str:
    f = []
    if r.get("stale"):
        f.append(f"期限 {r['deadline']} を過ぎた")
    if r.get("blocked"):
        f.append("止まっている")
    return f"（{'・'.join(f)}）" if f else ""


def format_md(p: dict) -> str:
    lines = ["# 進行中の候補（TODO の一覧はまだ書き換えていない）", "",
             f"TODO の一覧: {p['todo_path']}" + ("" if p["todo_found"] else "（まだ無い）"),
             "反映は /ppm-todo で、本人が承認した行だけを書く。", ""]
    if p.get("inflight_sections_missing"):
        names = "・".join(f"「{n}」" for n in p.get("inflight_section_names") or []) or "（設定なし）"
        lines += [f"注意: TODO の一覧に進行中の節の見出し（{names}。設定 ppm.todo.inflight_sections）が1つも無い。"
                  "一覧の行を読めていないので、足す候補が多めに出る。", ""]

    def block(head, rows, fmt):
        lines.append(f"## {head}")
        if rows:
            for r in rows:
                lines.extend(fmt(r))
        else:
            lines.append("- なし")
        lines.append("")

    def layer_rows(r):
        return [f"- {r['title']}{_flags(r)}{schedule_note(r)}",
                f"  <!-- layer: {r['layer']} scope: {r['scope_id']} -->"]

    block("TODO の一覧にある", p["keep"],
          lambda r: [f"- {r['todo_title']}{_flags(r)}{schedule_note(r)}"
                     + ("（一覧では済みの印だが、案件はまだ進行中）" if r.get("todo_done") else "")])
    block("足す候補（TODO の一覧に無い、最近の進行中の案件）", p["add"], layer_rows)
    block("外す候補（TODO の一覧にあるが、もう進行中でない）", p["remove"],
          lambda r: [f"- {r['title']}（{r['reason']}）"])
    block("期限を過ぎたか止まっている（閉じる・延ばす・待つを決める）", p["stale"],
          lambda r: [f"- {r['title']}{_flags(r)}"])
    lines.append("## そのほか")
    lines.append(f"- {p['recent_days']}日より古く、TODO の一覧にも無い進行中の案件: {len(p['parked'])}件（候補にしない。一覧は --json）")
    if p["elsewhere"]:
        lines.append(f"- TODO の一覧の進行中の節の外（止めている案件の節など）に書いてある案件: {len(p['elsewhere'])}件（候補にしない）")
    if p.get("outside_notes"):
        lines.append(f"- リポジトリの外を指す注記: {len(p['outside_notes'])}件"
                     f"（{', '.join(r['title'] for r in p['outside_notes'][:5])}。外す候補にはしない。"
                     "注記の layer をリポジトリの中の相対パスに直すか、行を残すかを決める）")
    if p.get("outside_links"):
        lines.append(f"- リンクで置き場の外を指すので読まなかった intent.yaml: {len(p['outside_links'])}件"
                     f"（{', '.join(p['outside_links'][:5])}）")
    if p["unreadable"]:
        lines.append(f"- 読めなかった intent.yaml: {len(p['unreadable'])}件（{', '.join(p['unreadable'][:5])}）")
    if p["duplicates"]:
        lines.append(f"- 同じ scope_id の Layer が2つ以上ある: {', '.join(p['duplicates'])}（最初の1つだけ見た）")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="進行中の候補を Layer から洗い出し、TODO の一覧との差分を出す（読むだけ）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", default=None)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD（試験用）")
    a = ap.parse_args(argv)
    try:
        today = date.fromisoformat(a.today) if a.today else None
        p = propose(a.root, today)
    except (ImportError, ValueError) as exc:  # PpmConfigError は ValueError の仲間
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(p, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(format_md(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
