#!/usr/bin/env python3
"""/ppm-todo の最後に出す「結局いまどうなっているか」のまとめ（読むだけ。どこにも書かない）。

今の TODO の一覧を読み直して、自然な日本語で短くまとめる。

並び: 期限が近いもの（上位5件・日付つき）→ 仕事の小区分ごと（設定 `ppm.todo.work_subgroups`、既定は主軸・支援課題。
小区分が無い一覧では「仕事」1つ）→ 私生活の節（設定 `ppm.todo.private_sections`。題名だけ）→ 気になる点
（期限を過ぎた行・一覧にあるのに案件が閉じた行・待ちの節で日付が過ぎたか解消した行と、本人に聞く行）。
期限は題名の日付（「（1/30 まで）」など）を使い、無ければ Layer の intent の deadline を使う。

使い方（導入先のリポジトリのルートで）:
  python3 .claude/skills/ppm-todo/todo_summary.py [--json] [--root <repo>] [--db <DB>] [--today YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WEEKDAY = "月火水木金土日"
TOP_N = 5
CLOSED = {"completed", "cancelled", "done", "dropped"}
DATE_PAREN_RE = re.compile(r"（\s*\d{1,2}/\d{1,2}\s*まで\s*）")
NO_SUBGROUP = "仕事"


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


def _plain_title(title: str) -> str:
    """横に日付を出すときは、題名の「（M/D まで）」だけを外す。"""
    return DATE_PAREN_RE.sub("", title).strip() or title


def _md(d: date) -> str:
    return f"{d.month}/{d.day}（{WEEKDAY[d.weekday()]}）"


def group_of(item: dict, cfg: dict, pf) -> str:
    """行の区分の名前。私生活の節はその節の名前、仕事は小区分（設定の名前に当たれば設定の名前）。"""
    if item["group"] == "private":
        return item["section"]
    sub = item.get("subgroup")
    if not sub:
        return NO_SUBGROUP
    for g in cfg["todo"]["work_subgroups"]:
        if pf.heading_matches(sub, g):
            return g
    return sub


def build(root, cfg, today: date, db_path=None) -> dict:
    pf = load_sibling("ppm", "ppm_files.py", "ppm_files")
    tw = load_sibling("ppm-todo", "todo_waiting.py", "ppm_todo_waiting")
    li = load_sibling("ppm-inflight", "list_inflight.py", "ppm_list_inflight")
    path = pf.todo_path(root, cfg)
    text = path.read_text(encoding="utf-8")
    todo = pf.parse_todo(text, cfg)
    index = li.layer_index(root, today)
    by_layer = {r["layer"]: r for r in index.values()}
    items = []
    for it in pf.inflight_items(todo):
        layer = index.get(it.get("scope") or "") or by_layer.get(li._norm(it.get("layer"), root) or "")
        dates = tw.find_dates(it["title"], today)
        if dates:
            deadline, src = min(dates), "title"
        elif layer and layer.get("deadline"):
            deadline, src = date.fromisoformat(layer["deadline"]), "intent"
        else:
            deadline, src = None, ""
        items.append({"title": it["title"], "group": group_of(it, cfg, pf), "private": it["group"] == "private",
                      "deadline": deadline, "deadline_from": src,
                      "closed": bool(layer and layer["status"] in CLOSED)})
    open_items = [i for i in items if not i["closed"]]
    upcoming = sorted((i for i in open_items if i["deadline"] and i["deadline"] >= today), key=lambda i: i["deadline"])
    overdue = sorted((i for i in open_items if i["deadline"] and i["deadline"] < today), key=lambda i: i["deadline"])
    rev = tw.review(text, cfg, Path(root), today, db_path)
    order = []
    for g in cfg["todo"]["work_subgroups"] + [NO_SUBGROUP]:
        if g not in order:
            order.append(g)
    for i in items:  # 設定に無い小区分の名前と、私生活の節は出てきた順
        if i["group"] not in order and not i["private"]:
            order.append(i["group"])
    private_order = []
    for s in cfg["todo"]["private_sections"]:
        private_order.append(s)
    for i in items:
        if i["private"] and i["group"] not in private_order:
            private_order.append(i["group"])
    return {"today": today, "items": items, "upcoming": upcoming[:TOP_N], "overdue": overdue,
            "closed": [i for i in items if i["closed"]], "work_order": order, "private_order": private_order,
            "has_subgroups": todo["has_subgroups"],
            "waiting_enabled": rev["enabled"],
            "waiting_ask": [w for w in rev["items"] if w["kind"] == "unknown"],
            "waiting_stale": [w for w in rev["items"] if w["kind"] in ("past", "resolved")],
            "registry_ok": rev["registry_ok"]}


def _label(i: dict) -> str:
    return "私生活" if i["private"] else i["group"]


def format_summary(s: dict) -> str:
    today = s["today"]
    work_groups = [(g, [i for i in s["items"] if not i["private"] and i["group"] == g]) for g in s["work_order"]]
    work_groups = [(g, rows) for g, rows in work_groups if rows or (s["has_subgroups"] and g != NO_SUBGROUP)]
    private_groups = [(g, [i for i in s["items"] if i["private"] and i["group"] == g]) for g in s["private_order"]]
    lines = [f"## 結局いまどうなっているか（{_md(today)}時点）", ""]
    parts = [f"{g} {len(rows)}" for g, rows in work_groups] + [f"{g} {len(rows)}" for g, rows in private_groups if rows]
    lines.append(f"TODO の一覧の進行中は {len(s['items'])}件" + (f"（{'・'.join(parts)}）" if parts else "") + "。")
    lines += ["", "**期限が近いもの**"]
    if s["upcoming"]:
        for i in s["upcoming"]:
            note = "" if i["deadline_from"] == "title" else "（案件に書かれた期限）"
            lines.append(f"- {_md(i['deadline'])}　{_plain_title(i['title'])}{note} — {_label(i)}")
    else:
        lines.append("- 日付のついた行は無い")
    lines.append("")
    for g, rows in work_groups:
        lines.append(f"**{g}（{len(rows)}件）**" + ("" if rows else "：なし"))
        lines += [f"- {i['title']}" for i in rows]
        lines.append("")
    for g, rows in private_groups:
        if not rows:
            continue
        lines.append(f"**{g}（{len(rows)}件。題名だけ）**")
        lines += [f"- {_plain_title(i['title'])}" for i in rows]
        lines.append("")
    lines.append("**気になる点**")
    notes = []
    for i in s["overdue"]:
        src = "" if i["deadline_from"] == "title" else "案件に書かれた"
        notes.append(f"{src}期限の{_md(i['deadline'])}を過ぎている：{_plain_title(i['title'])}（終えるか、期限を延ばすかを決める）")
    for i in s["closed"]:
        notes.append(f"TODO の一覧にあるが、案件はもう閉じている：{i['title']}（外すかを決める）")
    if s["waiting_stale"]:
        notes.append(f"待ちの節に、日付が過ぎたか解消した行が {len(s['waiting_stale'])}件残っている")
    if s["waiting_ask"]:
        notes.append(f"待ちの節に、続いているか分からない行が {len(s['waiting_ask'])}件ある（あなたに聞く）")
    if not s.get("registry_ok", True):
        notes.append("Registry を読めなかったため、Layer の無い案件が閉じたかは確かめていない")
    lines += [f"- {n}" for n in notes] if notes else ["- 特に無い"]
    lines.append("")
    return "\n".join(lines)


def to_json(s: dict) -> dict:
    def ser(i):
        return {"title": i["title"], "group": _label(i), "deadline": i["deadline"].isoformat() if i["deadline"] else None,
                "deadline_from": i["deadline_from"] or None, "closed": i["closed"]}
    return {"today": s["today"].isoformat(), "items": [ser(i) for i in s["items"]],
            "upcoming": [ser(i) for i in s["upcoming"]], "overdue": [ser(i) for i in s["overdue"]],
            "closed": [ser(i) for i in s["closed"]],
            "waiting_ask": len(s["waiting_ask"]), "waiting_stale": len(s["waiting_stale"])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TODO の一覧の今の状況をまとめる（読むだけ）")
    ap.add_argument("--root", default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD（試験用）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        pf = load_sibling("ppm", "ppm_files.py", "ppm_files")
        root, cfg = pf.context(a.root)
        today = date.fromisoformat(a.today) if a.today else date.today()
    except (ImportError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    if not pf.todo_path(root, cfg).is_file():
        print(f"TODO の一覧がありません: {pf.todo_path(root, cfg)}", file=sys.stderr)
        return 1
    db = a.db
    if db is None:
        db = load_sibling("ppm-todo", "inflight_programs.py", "ppm_inflight_programs").default_db(root)
    s = build(root, cfg, today, db)
    if a.json:
        print(json.dumps(to_json(s), ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(format_summary(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
