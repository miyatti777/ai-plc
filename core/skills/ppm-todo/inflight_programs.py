#!/usr/bin/env python3
"""進行中の候補（ppm-inflight の list_inflight.py の提案）を、Program と業務プロジェクトごとにまとめて見せる（読むだけ）。

業務プロジェクトの4つの表（programs・business_projects・program_memberships・business_project_links。
`.claude/db/business_registry.py init` で作る）が Registry にあるときだけ、業務プロジェクトごとに分ける。
表が無い・Registry が無い・読めないときは、止まらずに平らな一覧で出す（その旨を1行添える）。

分け方:
- 業務プロジェクトは、案件（projects の scope_id）の confirmed な primary のつながり（business_project_links）。
  Program は、その業務プロジェクトの所属（program_memberships の business_project）。業務プロジェクトが無ければ、
  案件の所属（aiplc_project）で Program だけを引く
- 所属が引けない案件は落とさず、理由ごとに「どの業務にもつながっていない案件」に入れる
- 1件の判断は1つだけに数える（外す候補 → 一覧にある → 期限を過ぎたか止まっている → 足す候補 の順）
- 私生活の Program（display_group が private）では、業務の目的の文を出さない

Registry・TODO の一覧・Layer には書かない。Registry は読み取り専用で開く。

使い方（導入先のリポジトリのルートで）:
  python3 .claude/skills/ppm-todo/inflight_programs.py [--detail] [--json] [--db <DB>] [--root <repo>] [--today YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BUSINESS_TABLES = ("programs", "business_projects", "program_memberships", "business_project_links")
NO_BUSINESS = "（業務プロジェクトなし）"
GROUP_SCREEN = {"work": "仕事", "private": "私生活"}
REASONS = [
    ("no_project", "Registry にまだ登録されていない案件 {n}件（登録すると業務に入る）"),
    ("no_membership", "業務がまだ選ばれていない案件 {n}件（業務を選ぶと入る）"),
    ("todo_only", "TODO の一覧にだけあり、Layer の注記が無い行 {n}件（案件として立てるか、一覧のまま持つかを決める）"),
]


def load_sibling(skill: str, filename: str, modname: str):
    """隣のスキルの部品を読む（配布の形 core/skills/… と導入先 .claude/skills/…・.cursor/skills/… の両方）。"""
    if modname in sys.modules:
        return sys.modules[modname]
    cands = [HERE.parent / skill / filename]
    cands += [Path.cwd() / d / "skills" / skill / filename for d in (".claude", ".cursor")]
    for f in cands:
        if f.is_file():
            spec = importlib.util.spec_from_file_location(modname, f)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[modname] = mod
            spec.loader.exec_module(mod)
            return mod
    raise ImportError(f"{skill}/{filename} が見つかりません")


def _paths_module(root: Path):
    """aiplc_paths.py（DB の場所を決める共通の関数）。無ければ None。"""
    for d in (HERE.parents[1] / "db", root / ".claude" / "db", root / ".cursor" / "db"):
        f = d / "aiplc_paths.py"
        if f.is_file():
            spec = importlib.util.spec_from_file_location("aiplc_paths", f)
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except Exception:  # noqa: BLE001
                continue
            return mod
    return None


def default_db(root: Path) -> Path | None:
    mod = _paths_module(root)
    if mod is not None:
        try:
            return Path(mod.resolve_db(root).path)
        except Exception:  # noqa: BLE001
            pass
    for d in (".claude", ".cursor"):
        p = root / d / "db" / "ai_plc.db"
        if p.is_file():
            return p
    return None


def open_ro(db_path, root: Path):
    """(接続 or None, 注記 or None)。読み取り専用。"""
    if not db_path or not Path(db_path).is_file():
        return None, "Registry が見つからないので、業務プロジェクトに分けずに出す"
    mod = _paths_module(root)
    try:
        if mod is not None and hasattr(mod, "open_ro"):
            con = mod.open_ro(str(db_path))
        else:
            con = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
            con.execute("PRAGMA query_only=1")
        con.row_factory = sqlite3.Row
        con.execute("SELECT 1 FROM projects LIMIT 1").fetchall()
        return con, None
    except sqlite3.Error as exc:
        return None, f"Registry を読めないので、業務プロジェクトに分けずに出す（{type(exc).__name__}）"


def business_tables_present(con) -> bool:
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    return all(t in names for t in BUSINESS_TABLES)


# --- 行を集める ------------------------------------------------------------------

def collect_rows(proposal: dict, todo: dict | None) -> list[dict]:
    """足す・一覧にある・期限切れ・外す候補と、注記の無い進行中の行。1件1行。"""
    rows: dict = {}
    for kind in ("keep", "add", "stale"):
        for r in proposal.get(kind) or []:
            row = rows.setdefault(("scope", r["scope_id"]), {
                "title": r.get("todo_title") or r["title"], "scope_id": r["scope_id"], "layer": r["layer"],
                "stale_flag": bool(r.get("stale")), "blocked": bool(r.get("blocked")),
                "deadline": r.get("deadline"), "tags": set()})
            row["tags"].add(kind)
            if kind == "keep":
                row["title"] = r.get("todo_title") or row["title"]
    for r in proposal.get("remove") or []:
        key = ("scope", r.get("scope_id") or r.get("layer") or r["title"])
        row = rows.setdefault(key, {"title": r["title"], "scope_id": r.get("scope_id"), "layer": r.get("layer"),
                                    "stale_flag": False, "blocked": False, "deadline": None, "tags": set(),
                                    "reason": r["reason"]})
        row["tags"].add("remove")
    for it in (todo or {}).get("inflight", []):
        if it["done"] or it.get("layer") or it.get("scope"):
            continue
        rows.setdefault(("todo", it["line"]), {"title": it["title"], "scope_id": None, "layer": None,
                                               "stale_flag": False, "blocked": False, "deadline": None,
                                               "tags": {"todo_only"}, "section": it["section"],
                                               "private": it["group"] == "private"})
    out = []
    for row in rows.values():
        row["tags"] = sorted(row["tags"])
        out.append(row)
    return out


def row_kind(row: dict) -> str:
    tags = row["tags"]
    for k in ("remove", "keep", "stale", "add"):
        if k in tags:
            return k
    return "todo_only"


def counts(rows: list[dict]) -> dict:
    c = {"keep": 0, "add": 0, "remove": 0, "stale": 0, "keep_expired": 0, "todo_only": 0}
    for r in rows:
        k = row_kind(r)
        c[k] += 1
        if k == "keep" and "stale" in r["tags"]:
            c["keep_expired"] += 1
    return c


# --- 分ける ----------------------------------------------------------------------

def lookup_scope(con, scope_id: str) -> dict:
    p = con.execute("SELECT id FROM projects WHERE scope_id=?", (scope_id,)).fetchone()
    if p is None:
        return {"state": "no_project"}
    links = con.execute(
        "SELECT l.business_uid, l.relation_type, b.display_name, b.purpose FROM business_project_links l"
        " JOIN business_projects b ON b.business_uid=l.business_uid AND b.workspace_id=l.workspace_id"
        " WHERE l.project_id=? AND l.state='confirmed' AND b.state='active' ORDER BY b.display_name",
        (p["id"],)).fetchall()
    primary = next((r for r in links if r["relation_type"] == "primary"), None)
    related = [r["display_name"] for r in links if r["relation_type"] == "related"]
    program = None
    if primary is not None:
        program = con.execute(
            "SELECT g.program_uid, g.display_name, g.display_group FROM program_memberships m"
            " JOIN programs g ON g.program_uid=m.program_uid AND g.workspace_id=m.workspace_id"
            " WHERE m.target_kind='business_project' AND m.business_uid=? AND m.state='confirmed'"
            " AND g.state='active' ORDER BY g.display_name LIMIT 1", (primary["business_uid"],)).fetchone()
    if program is None:
        program = con.execute(
            "SELECT g.program_uid, g.display_name, g.display_group FROM program_memberships m"
            " JOIN programs g ON g.program_uid=m.program_uid AND g.workspace_id=m.workspace_id"
            " WHERE m.target_kind='aiplc_project' AND m.project_id=? AND m.state='confirmed'"
            " AND g.state='active' ORDER BY g.display_name LIMIT 1", (p["id"],)).fetchone()
    if program is None:
        return {"state": "no_membership"}
    business = ({"uid": primary["business_uid"], "name": primary["display_name"], "purpose": primary["purpose"]}
                if primary is not None else {"uid": None, "name": NO_BUSINESS, "purpose": None})
    return {"state": "linked", "related": related, "business": business,
            "program": {"uid": program["program_uid"], "name": program["display_name"],
                        "group": program["display_group"]}}


def group(rows: list[dict], con=None, note: str | None = None) -> dict:
    """con が業務プロジェクトの表を持つときだけ分ける。返り値の mode は grouped / flat。"""
    if con is not None and not business_tables_present(con):
        con, note = None, "Registry に業務プロジェクトの表が無いので、平らな一覧で出す（表は business_registry.py init で作れる）"
    if con is None:
        return {"mode": "flat", "note": note, "rows": rows, "decisions": decisions_of(rows, [])}
    programs: dict = {}
    loose = {k: [] for k, _ in REASONS}
    try:
        for row in rows:
            if not row.get("scope_id"):
                loose["todo_only"].append(row)
                continue
            info = lookup_scope(con, row["scope_id"])
            if info["state"] != "linked":
                loose[info["state"]].append(row)
                continue
            prog = programs.setdefault(info["program"]["uid"], {
                "program": info["program"]["name"], "program_uid": info["program"]["uid"],
                "group": info["program"]["group"], "businesses": {}})
            biz = prog["businesses"].setdefault(info["business"]["uid"] or "", {
                "business": info["business"]["name"], "business_uid": info["business"]["uid"],
                "purpose": info["business"]["purpose"], "rows": []})
            biz["rows"].append(dict(row, related=info["related"]))
    except sqlite3.Error as exc:  # 列の無い古い表など。止めずに平らに出す
        return {"mode": "flat", "note": f"Registry を読めないので、平らな一覧で出す（{type(exc).__name__}）",
                "rows": rows, "decisions": decisions_of(rows, [])}
    out = []
    for p in programs.values():
        bs = sorted(p["businesses"].values(), key=lambda b: (-len(b["rows"]), b["business"]))
        for b in bs:
            if p["group"] == "private":
                b["purpose"] = None
            b["counts"] = counts(b["rows"])
            b["stalled"] = not (b["counts"]["keep"] or b["counts"]["add"] or b["counts"]["remove"])
        out.append(dict(p, businesses=bs, count=sum(len(b["rows"]) for b in bs)))
    out.sort(key=lambda p: (0 if p["group"] == "work" else 1, -p["count"], p["program"]))
    unclassified = [{"reason": k, "rows": loose[k]} for k, _ in REASONS if loose[k]]
    biz_rows = [((p["program_uid"], b["business_uid"] or b["business"]), r)
                for p in out for b in p["businesses"] for r in b["rows"]]
    loose_rows = [r for u in unclassified for r in u["rows"]]
    return {"mode": "grouped", "note": note, "programs": out, "unclassified": unclassified,
            "decisions": decisions_of([r for _, r in biz_rows] + loose_rows, biz_rows, len(loose_rows))}


def decisions_of(rows: list[dict], biz_rows: list, unlinked: int | None = None) -> dict:
    kinds = [row_kind(r) for r in rows]
    return {"add": kinds.count("add"),
            "add_businesses": len({k for k, r in biz_rows if row_kind(r) == "add"}),
            "expired": kinds.count("stale"),
            "expired_in_todo": sum(1 for r in rows if row_kind(r) == "keep" and "stale" in r["tags"]),
            "remove": kinds.count("remove"),
            "todo_only": kinds.count("todo_only"),
            "unlinked": unlinked}


# --- 出力 -----------------------------------------------------------------------

def _row_line(row: dict) -> list[str]:
    flags = []
    if row.get("stale_flag"):
        flags.append(f"期限 {row['deadline']} を過ぎた" if row.get("deadline") else "期限を過ぎた")
    if row.get("blocked"):
        flags.append("止まっている")
    if row.get("reason"):
        flags.append(row["reason"])
    kind = {"keep": "一覧にある", "add": "一覧に無い", "stale": "一覧に無い", "remove": "外す候補",
            "todo_only": "一覧だけ"}[row_kind(row)]
    extra = f"（{'・'.join(flags)}）" if flags else ""
    rel = f" ／関連: {'・'.join(row['related'])}" if row.get("related") else ""
    lines = [f"- {row['title']}［{kind}］{extra}{rel}"]
    if row.get("layer"):
        lines.append(f"  <!-- layer: {row['layer']} scope: {row.get('scope_id')} -->")
    return lines


def _relation(c: dict) -> str:
    parts = []
    if c["keep"]:
        inner = f"（うち期限を過ぎたか止まっているもの {c['keep_expired']}件）" if c["keep_expired"] else ""
        parts.append(f"TODO の一覧に入っている案件 {c['keep']}件{inner}")
    if c["add"]:
        parts.append(f"入っていない進行中の案件 {c['add']}件（足すかを決める）")
    if c["stale"]:
        parts.append(f"入っていない、期限を過ぎたか止まったままの案件 {c['stale']}件（閉じるか、期限を延ばすか、待つかを決める）")
    if c["remove"]:
        parts.append(f"一覧にあるが、もう進行中でない案件 {c['remove']}件（外すかを決める）")
    return "。".join(parts) + "。" if parts else "決めることはない。"


def _decision_lines(d: dict) -> list[str]:
    lines = ["## 今日決めること", ""]
    span = f"（業務 {d['add_businesses']}件にまたがる）" if d.get("add_businesses") else ""
    lines.append(f"- TODO の一覧に入っていない進行中の案件を足すか：{d['add']}件{span}")
    lines.append(f"- 一覧に入っていない、期限を過ぎたか止まったままの案件を閉じるか・延ばすか・待つか：{d['expired']}件")
    if d["expired_in_todo"]:
        lines.append(f"- 一覧に入っているのに、期限を過ぎたか止まっている案件をどうするか：{d['expired_in_todo']}件")
    if d["remove"]:
        lines.append(f"- 一覧にあるが、もう進行中でない案件を外すか：{d['remove']}件")
    if d.get("unlinked") is not None:
        lines.append(f"- どの業務にもつながっていない案件：{d['unlinked']}件（一番下。足す・閉じるの対象は上の数にも含む）")
    lines += ["", "数え方：1件は1回だけ数える（外す候補 → 一覧にある → 期限を過ぎたか止まっている → 足す候補 の順に決める）。", ""]
    return lines


def format_md(g: dict, detail: bool = False) -> str:
    lines = ["# 進行中の仕事の全体" + ("（業務プロジェクトごと）" if g["mode"] == "grouped" else ""), "",
             "TODO の一覧を見直すための一覧。TODO の一覧はまだ書き換えていない。", ""]
    if g.get("note"):
        lines += [f"> {g['note']}", ""]
    lines += _decision_lines(g["decisions"])
    if g["mode"] == "flat":
        heads = [("remove", "外す候補"), ("keep", "TODO の一覧にある"), ("stale", "期限を過ぎたか止まっている（一覧に無い）"),
                 ("add", "足す候補"), ("todo_only", "TODO の一覧にだけある（Layer の注記なし）")]
        for k, head in heads:
            rs = [r for r in g["rows"] if row_kind(r) == k]
            if not rs:
                continue
            lines.append(f"## {head}（{len(rs)}件）")
            for r in rs:
                lines.extend(_row_line(r))
            lines.append("")
        return "\n".join(lines)
    for p in g["programs"]:
        active = [b for b in p["businesses"] if not b["stalled"]]
        stalled = [b for b in p["businesses"] if b["stalled"]]
        more = f"、止まっている業務 {len(stalled)}件" if stalled else ""
        lines.append(f"## {p['program']}（{GROUP_SCREEN.get(p['group'], p['group'])}）— 動いている業務 {len(active)}件{more}")
        for b in active:
            lines += ["", f"**{b['business']}**"]
            if b.get("purpose"):
                lines.append(f"- 何の業務か：{b['purpose']}")
            lines.append(f"- TODO の一覧との関係：{_relation(b['counts'])}")
            if detail:
                lines.append("- 案件：")
                lines += ["  " + x for r in b["rows"] for x in _row_line(r)]
        if stalled:
            n = sum(len(b["rows"]) for b in stalled)
            names = "、".join(b["business"] for b in stalled)
            lines += ["", f"**止まっている業務 {len(stalled)}件**（中の案件 {n}件がどれも期限を過ぎたか止まったままで、"
                          f"TODO の一覧にも無い。案件を閉じるか、期限を延ばすか、止まっている理由を解くと消える）：{names}"]
            if detail:
                for b in stalled:
                    lines += ["", f"**{b['business']}**"] + ["  " + x for r in b["rows"] for x in _row_line(r)]
        lines.append("")
    total = sum(len(u["rows"]) for u in g["unclassified"])
    lines += [f"## どの業務にもつながっていない案件（{total}件）", ""]
    if not g["unclassified"]:
        lines.append("- なし")
    labels = dict(REASONS)
    for u in g["unclassified"]:
        lines.append("- " + labels[u["reason"]].format(n=len(u["rows"])))
        if detail:
            lines += ["  " + x for r in u["rows"] for x in _row_line(r)]
    if not detail:
        lines += ["", "案件を1件ずつ見たいときは `--detail` を付ける。"]
    lines.append("")
    return "\n".join(lines)


def to_json(g: dict) -> dict:
    def ser(r):
        return {k: r.get(k) for k in ("title", "tags", "scope_id", "layer", "related", "stale_flag", "blocked",
                                      "deadline", "section", "reason") if k in r}
    if g["mode"] == "flat":
        return {"mode": "flat", "note": g["note"], "rows": [ser(r) for r in g["rows"]], "decisions": g["decisions"]}
    return {"mode": "grouped", "note": g["note"], "decisions": g["decisions"],
            "programs": [{"program": p["program"], "program_uid": p["program_uid"], "group": p["group"],
                          "count": p["count"],
                          "businesses": [{"business": b["business"], "business_uid": b["business_uid"],
                                          "purpose": b["purpose"], "counts": b["counts"], "stalled": b["stalled"],
                                          "rows": [ser(r) for r in b["rows"]]} for b in p["businesses"]]}
                         for p in g["programs"]],
            "unclassified": [{"reason": u["reason"], "rows": [ser(r) for r in u["rows"]]} for u in g["unclassified"]]}


def build(root=None, db=None, today: date | None = None) -> dict:
    li = load_sibling("ppm-inflight", "list_inflight.py", "ppm_list_inflight")
    pf = li.ppm_files()
    root, cfg = pf.context(root)
    proposal = li.propose(root, today)
    todo = pf.read_todo(root, cfg)
    rows = collect_rows(proposal, todo)
    con, note = open_ro(Path(db) if db else default_db(root), root)
    try:
        return group(rows, con, note)
    finally:
        if con is not None:
            con.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="進行中の候補を業務プロジェクトごとにまとめる（読むだけ）")
    ap.add_argument("--detail", action="store_true", help="案件の行も出す")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--db", default=None)
    ap.add_argument("--root", default=None)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD（試験用）")
    a = ap.parse_args(argv)
    try:
        g = build(a.root, a.db, date.fromisoformat(a.today) if a.today else None)
    except (ImportError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(to_json(g), ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(format_md(g, a.detail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
