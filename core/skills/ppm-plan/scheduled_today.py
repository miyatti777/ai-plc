#!/usr/bin/env python3
"""ppm-plan の補助: TODO の一覧の進行中の案件（`<!-- layer: ... -->` の注記）の backlog.yaml から、
実行時期 `scheduled_for` が対象日以前で未完了の通常 Task（recurrence の無いもの）を一覧にする。読むだけで何も書かない。

- TODO の一覧の置き場と節は、共通の部品 ppm_files（`.claude/skills/ppm/ppm_files.py`）が設定 `.ai-plc/config.yaml` の
  `ppm:` から決める。ここでは直書きしない
- 実行時期と期限は `YYYY-MM-DD` か `YYYY-Www`（その週の月曜）。日時は先頭10文字で読む。書いてあるのに読めない値は
  候補にせず、標準エラーに「時期を読めない」「期限を読めない」と1行出す（黙って時期なしにしない）
- 完了の印（`- [x]`）の付いた案件の行、リポジトリの外を指す layer の注記、読めない backlog は黙って飛ばす
- TODO の一覧が無いときは「スキップ」と1行出して終わる（使えなくても止めない）
- 私生活の節（設定 `ppm.todo.private_sections`）の行の案件の Task は、既定では scope・Layer のパス・Task の ID・名前を出さない
  （JSON では `"private": true` だけを残した行、テキストでは「私生活の案件（名前は伏せています）」と件数）。出すときは --show-private
- PyYAML が無いときは、案内の文を出して終了コード 2 で止まる

使い方（導入先のリポジトリのルートで）:
  python3 .claude/skills/ppm-plan/scheduled_today.py [--date YYYY-MM-DD] [--root <リポジトリ>] [--json] [--show-private]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent

DONE = frozenset({"completed", "done", "cancelled", "dropped", "deferred", "blocked", "完了"})
WEEK_RE = re.compile(r"^(\d{4})-[Ww](\d{2})$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_ppm_files(root=None):
    """共通の部品 ppm_files を読み込む。配布の形（core/skills/ppm/）と導入先（.claude/skills/ppm/・.cursor/skills/ppm/）の
    どちらでも、隣の ppm フォルダを先に探し、無ければ root（または今のフォルダ）の下を探す。見つからなければ ImportError。"""
    base = Path(root) if root else Path.cwd()
    for d in (HERE.parent / "ppm", base / ".claude" / "skills" / "ppm", base / ".cursor" / "skills" / "ppm",
              base / "core" / "skills" / "ppm"):
        f = d / "ppm_files.py"
        if f.is_file():
            spec = importlib.util.spec_from_file_location("_ppm_files_shared", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise ImportError("共通の部品 ppm_files.py が見つかりません（.claude/skills/ppm/ に入っているか確かめてください）")


def scheduled_date(value) -> date | None:
    """`YYYY-MM-DD` か `YYYY-Www`（その週の月曜。w は大文字小文字を問わない）。引用符つきの日時は先頭10文字で読む。
    空・読めなければ None。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
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


def unreadable(value) -> bool:
    """書いてあるのに読めない時期・期限か。"""
    return value is not None and str(value).strip() != "" and scheduled_date(value) is None


def layer_dir(root: Path, rel: str) -> Path | None:
    """layer の注記のパスを、リポジトリの中のフォルダにする（外を指す・絶対パスなら None）。"""
    p = Path(rel)
    if p.is_absolute():
        return None
    full = (Path(root) / p).resolve()
    try:
        full.relative_to(Path(root).resolve())
    except ValueError:
        return None
    return full


def yaml_available() -> bool:
    try:
        import yaml  # noqa: F401
    except ImportError:
        return False
    return True


YAML_MISSING = "[ERROR] この道具は backlog.yaml・intent.yaml を読むのに PyYAML を使います（pip install pyyaml）"


def _warn(msg: str) -> None:
    print(msg, file=sys.stderr)


def collect(root: Path, layers: dict, day: date, warn=_warn, quiet_layers=()) -> list[dict]:
    """layers（{layer のパス: scope}）の backlog から、実行時期が day 以前の未完了の通常 Task。
    並びは時期の早い順、同じ日は priority（P0→P1→…。無ければ最後）の順。
    quiet_layers の Layer では、読めない値の警告に scope・Task の ID・値を出さず、最後に件数だけを出す。"""
    import yaml

    rows = []
    hidden = 0
    for rel, scope in layers.items():
        d = layer_dir(root, rel)
        if d is None:
            continue
        try:
            data = yaml.safe_load((d / "backlog.yaml").read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 — 読めない Layer は黙って飛ばす（使えなくても止めない）
            continue
        if not isinstance(data, dict):
            continue
        for t in data.get("tasks") or []:
            if not isinstance(t, dict) or t.get("recurrence") or str(t.get("status", "")).strip().lower() in DONE:
                continue
            if rel in quiet_layers:
                hidden += int(unreadable(t.get("scheduled_for"))) + int(unreadable(t.get("due")))
            else:
                if unreadable(t.get("scheduled_for")):
                    warn(f"時期を読めない: {scope} {t.get('id')} {t.get('scheduled_for')}")
                if unreadable(t.get("due")):
                    warn(f"期限を読めない: {scope} {t.get('id')} {t.get('due')}")
            when = scheduled_date(t.get("scheduled_for"))
            if when is None or when > day:
                continue
            due = scheduled_date(t.get("due"))
            rows.append({"scope": scope, "layer": rel, "task_id": t.get("id"), "name": t.get("name"),
                         "scheduled_for": when.isoformat(), "overdue": when < day,
                         "due": due.isoformat() if due else t.get("due"),
                         "due_overdue": bool(due and due < day), "priority": t.get("priority")})
    if hidden:
        warn(f"私生活の案件で、時期か期限を読めない Task が {hidden} 件あります（--show-private で出す）")
    rows.sort(key=lambda r: (r["scheduled_for"], str(r.get("priority") or "P9")))
    return rows


def private_layers(todo: dict, pf) -> set:
    """私生活の節の行だけに出る layer のパス（仕事の節にも同じ注記があれば仕事として扱う）。"""
    work = pf.inflight_layers(todo, group="work")
    return {k for k in pf.inflight_layers(todo, group="private") if k not in work}


HIDDEN = "私生活の案件（名前は伏せています。--show-private で出す）"


def hide_private(rows: list[dict], private: set, show_private: bool = False) -> list[dict]:
    """private（layer のパスの集まり）に入る行に "private": True を付ける。show_private でなければ、その行は
    "private": True だけを残し、scope・layer・task_id・name などを伏せる（件数は行の数で分かる）。"""
    out = []
    for r in rows:
        if r.get("layer") not in private:
            out.append(r)
        elif show_private:
            out.append(dict(r, private=True))
        else:
            out.append({"private": True})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="実行時期が来た Task を一覧にする（読むだけ）")
    ap.add_argument("--date", default=None, help="対象日 YYYY-MM-DD（既定は今日）")
    ap.add_argument("--root", default=None, help="リポジトリのルート（既定は導入先のリポジトリか今のフォルダ）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show-private", action="store_true", help="私生活の節の案件の scope・Layer・Task も出す")
    a = ap.parse_args(argv)
    if not yaml_available():
        print(YAML_MISSING, file=sys.stderr)
        return 2
    try:
        day = date.fromisoformat(a.date) if a.date else date.today()
        pf = load_ppm_files(a.root)
        root, cfg = pf.context(a.root)
    except (ImportError, ValueError) as exc:  # PpmConfigError は ValueError
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    todo = pf.read_todo(root, cfg)
    if todo is None:
        print(f"実行時期の Task: TODO の一覧が無いのでスキップ（{pf.todo_path(root, cfg)}）", file=sys.stderr)
        if a.json:
            print("[]")
        return 0
    private = private_layers(todo, pf)
    rows = hide_private(collect(root, pf.inflight_layers(todo), day, quiet_layers=() if a.show_private else private),
                        private, a.show_private)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif not rows:
        print(f"実行時期の Task（{day.isoformat()} 以前）: なし")
    else:
        print(f"実行時期の Task（{day.isoformat()} 以前・WillDo の候補。1行は人の言葉に書き直す）")
        hidden = sum(1 for r in rows if r.get("private") and "scope" not in r)
        for r in rows:
            if r.get("private") and "scope" not in r:
                continue
            late = "（時期を過ぎている）" if r["overdue"] else ""
            due = (f" — 期限 {r['due']}" + ("（期限超過）" if r["due_overdue"] else "")) if r.get("due") else ""
            print(f"- {r['scope']} {r['task_id']} {r['name']} — 時期 {r['scheduled_for']}{late}{due}")
        if hidden:
            print(f"- {HIDDEN}: {hidden} 件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
