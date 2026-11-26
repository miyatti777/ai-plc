#!/usr/bin/env python3
"""ppm-status・ppm-plan の補助: TODO の一覧の進行中の案件（`<!-- layer: ... -->` の注記）の backlog.yaml から、
自分（持ち主）が関わる未完了 Task の**件数**を案件ごとに出す。Task は列挙しない。読むだけで何も書かない。

- TODO の一覧の置き場と節は、共通の部品 ppm_files（`.claude/skills/ppm/ppm_files.py`）が設定 `.ai-plc/config.yaml` の
  `ppm:` から決める。ここでは直書きしない
- 「自分が関わる」= Task の owner 欄に、設定 `ppm.owner_words`（既定: 本人・user・human）のどれかを含む（大文字小文字は問わない）。
  「user・AI」のような共同の書き方も含める（見落としを減らすため多めに数える）
- 未完了 = status が completed・done・cancelled・dropped・完了・deferred のどれでもない（blocked は自分の対応待ちのことがあるので数える）
- 運用タスク（recurrence のある Task）は completed にならないので数えない
- 完了の印（`- [x]`）の付いた案件の行は数えない。リポジトリの外を指す layer の注記と、読めない backlog は黙って飛ばす
- TODO の一覧が無いときは「スキップ」と1行出して終わる（使えなくても止めない）
- 私生活の節（設定 `ppm.todo.private_sections`）の行の案件は、既定では Layer のパスと ID を出さない
  （件数だけ「私生活の案件」として出す。JSON でも scope・layer を null にする）。出すときは --show-private
- PyYAML が無いときは、案内の文を出して終了コード 2 で止まる

使い方（導入先のリポジトリのルートで）:
  python3 .claude/skills/ppm-status/owner_open_count.py [--root <リポジトリ>] [--json] [--show-private]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent

NOT_OPEN = frozenset({"completed", "done", "cancelled", "dropped", "完了", "deferred"})


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


def owner_pattern(words) -> re.Pattern | None:
    """owner_words から照合の正規表現を作る（空なら None＝だれも当たらない）。"""
    words = [w for w in (words or []) if isinstance(w, str) and w.strip()]
    if not words:
        return None
    return re.compile("|".join(re.escape(w.strip()) for w in words), re.IGNORECASE)


def is_owner_open_task(task, pattern) -> bool:
    """Task 1件（backlog.yaml の tasks の dict）が、自分が関わる未完了 Task か。"""
    if pattern is None or not isinstance(task, dict) or task.get("recurrence"):
        return False
    if str(task.get("status") or "").strip().lower() in NOT_OPEN:
        return False
    return bool(pattern.search(str(task.get("owner") or "")))


def count_owner_open_tasks(tasks, pattern) -> int:
    """tasks（list）のうち、自分が関わる未完了 Task の数。list でなければ 0。"""
    return sum(1 for t in tasks if is_owner_open_task(t, pattern)) if isinstance(tasks, list) else 0


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


def read_backlog(root: Path, rel: str):
    """Layer の backlog.yaml の dict（無い・読めない・外を指すなら None）。"""
    import yaml

    d = layer_dir(root, rel)
    if d is None:
        return None
    try:
        data = yaml.safe_load((d / "backlog.yaml").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 読めない backlog は飛ばす（使えなくても止めない）
        return None
    return data if isinstance(data, dict) else None


def yaml_available() -> bool:
    try:
        import yaml  # noqa: F401
    except ImportError:
        return False
    return True


YAML_MISSING = "[ERROR] この道具は backlog.yaml を読むのに PyYAML を使います（pip install pyyaml）"


def counts(root: Path, cfg: dict, todo: dict, pf, show_private: bool = False) -> list[dict]:
    """進行中の案件ごとの、自分が関わる未完了 Task の数（0 の案件は出さない）。
    私生活の節の行の案件は "private": True を付け、show_private でなければ scope・layer を None にする。"""
    pattern = owner_pattern(cfg.get("owner_words"))
    work = pf.inflight_layers(todo, group="work")
    private = {k: v for k, v in pf.inflight_layers(todo, group="private").items() if k not in work}
    rows = []
    for rel, scope in list(work.items()) + list(private.items()):
        data = read_backlog(root, rel)
        if data is None:
            continue
        n = count_owner_open_tasks(data.get("tasks"), pattern)
        if not n:
            continue
        if rel in private:
            rows.append({"scope": scope if show_private else None, "layer": rel if show_private else None,
                         "owner_open_tasks": n, "private": True})
        else:
            rows.append({"scope": scope, "layer": rel, "owner_open_tasks": n})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="自分が関わる未完了 Task の件数（読むだけ）")
    ap.add_argument("--root", default=None, help="リポジトリのルート（既定は導入先のリポジトリか今のフォルダ）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show-private", action="store_true", help="私生活の節の案件の scope・Layer のパスも出す")
    a = ap.parse_args(argv)
    if not yaml_available():
        print(YAML_MISSING, file=sys.stderr)
        return 2
    try:
        pf = load_ppm_files(a.root)
        root, cfg = pf.context(a.root)
    except (ImportError, ValueError) as exc:  # PpmConfigError は ValueError
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    todo = pf.read_todo(root, cfg)
    if todo is None:
        print(f"自分が関わる未完了 Task: TODO の一覧が無いのでスキップ（{pf.todo_path(root, cfg)}）", file=sys.stderr)
        if a.json:
            print("[]")
        return 0
    rows = counts(root, cfg, todo, pf, show_private=a.show_private)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    total = sum(r["owner_open_tasks"] for r in rows)
    print(f"自分が関わる未完了 Task: {total}件（{len(rows)}案件。TODO の一覧の進行中の案件だけ）")
    for r in rows:
        name = r["scope"] if r["scope"] else "私生活の案件（名前は伏せています。--show-private で出す）"
        print(f"- {name}: {r['owner_open_tasks']} 件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
