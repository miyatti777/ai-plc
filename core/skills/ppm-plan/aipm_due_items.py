#!/usr/bin/env python3
"""ppm-plan の補助: TODO の一覧の進行中の案件（`<!-- layer: ... -->` の注記）のうち、AIPM の箱に ToDo のシートを持つ
Layer から、期限の近いものを WillDo の**候補**として出す。読むだけで何も書かない。

- 選び方は /pm-today と同じ（`.claude/skills/aipm-guided/ops.py` の check → _files → today_pick）。そのうち
  「期限を過ぎた ToDo」「7日以内が期限の論点」の2つだけを出す。論点・ToDo の正本は箱の中で、TODO の一覧へは書き写さない
- ToDo のシートがある Layer は3つ: AIPM で一覧（`aipm.registers: true`）を選んだもの、AIPM ライトモード（addons の
  `addon_id: aipm-light`。箱を作った後）、一覧の無い AIPM に2つのシートを足したもの（`Sheets/light_sheets.yaml` がある）
- AIPM を選んだ Layer が無ければ何も出さない。AIPM を選んでいない Layer は黙って飛ばす。シートがあるはずなのに箱を
  読めない Layer は、止めずに飛ばし、件数だけを「読めなかった」として出す（環境の問題に気づけるように）
- TODO の一覧の進行中に載っていない、ToDo のシートがある開いている Layer（`Flow/` の下）は件数だけ出す（中身は出さない）
- 私生活の節（設定 `ppm.todo.private_sections`）の行の案件は、既定では scope・Layer のパス・項目の ID と題名を出さない
  （JSON では `{"private": true, "count": <項目の数>}` の行、テキストでは「私生活の案件（名前は伏せています）」と件数）。
  出すときは --show-private
- TODO の一覧の置き場と節は、共通の部品 ppm_files が設定 `.ai-plc/config.yaml` の `ppm:` から決める
- PyYAML が無いときは、案内の文を出して終了コード 2 で止まる

使い方（導入先のリポジトリのルートで）:
  python3 .claude/skills/ppm-plan/aipm_due_items.py [--date YYYY-MM-DD] [--root <リポジトリ>] [--json] [--show-private]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent

BUCKETS = ("期限を過ぎた ToDo", "7日以内が期限の論点")   # today_pick の箱のうち plan に出す2つ
OPEN = frozenset({"active", "blocked", "pending", "pending_init", "pending_inception"})
SKIP_DIRS = frozenset({"Documents", "node_modules", "__pycache__"})
# ops.py が同じフォルダから import するもの。読み込んだ後は元に戻す（別の同名のモジュールと取り違えない）
SIBLINGS = ("package", "validate_package", "light")


def _load_sibling(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_scheduled_today():
    """同じフォルダの scheduled_today（ppm_files の読み込みと、layer のパスの確かめを共用する）。"""
    return _load_sibling("_ppm_plan_scheduled_today", HERE / "scheduled_today.py")


def _load_ops(path: Path):
    """ops.py を読み込む。ops は同じフォルダの package・light などを import するので、読む間だけそのフォルダを sys.path に足し、
    sys.path・sys.dont_write_bytecode・同名のモジュールを元に戻す。"""
    folder = path.parent
    saved_path, saved_bc = list(sys.path), sys.dont_write_bytecode
    saved_mods = {k: sys.modules.get(k) for k in SIBLINGS}
    try:
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(folder))
        for k in SIBLINGS:
            sys.modules.pop(k, None)
        return _load_sibling("_ppm_plan_aipm_ops", path)
    finally:
        sys.path[:] = saved_path
        sys.dont_write_bytecode = saved_bc
        for k, v in saved_mods.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def pm_ops(root=None):
    """aipm-guided/ops.py（無い・読めない・古くて関数が足りなければ None）。
    探す順: 隣の aipm-guided → root の .claude/・.cursor/・core/ の skills/aipm-guided。"""
    base = Path(root) if root else Path.cwd()
    dirs = [HERE.parent / "aipm-guided", base / ".claude" / "skills" / "aipm-guided",
            base / ".cursor" / "skills" / "aipm-guided", base / "core" / "skills" / "aipm-guided"]
    for d in dirs:
        f = d / "ops.py"
        if not f.is_file():
            continue
        try:
            module = _load_ops(f)
        except Exception:  # noqa: BLE001 — 読めなければ次へ
            continue
        if all(callable(getattr(module, n, None)) for n in ("check", "_files", "today_pick")):
            return module
    return None


def _addons(intent) -> list:
    return intent.get("addons") if isinstance(intent.get("addons"), list) else []


def _chose(intent, addon_id: str) -> bool:
    return any(isinstance(a, dict) and a.get("addon_id") == addon_id for a in _addons(intent))


def _aipm_with_registers(intent) -> bool:
    """AIPM（addons の addon_id: aipm か旧い work_style: aipm）を選び、一覧（aipm.registers: true）も選んでいるか。"""
    if not isinstance(intent, dict):
        return False
    chosen = intent.get("work_style") == "aipm" or _chose(intent, "aipm")
    aipm = intent.get("aipm") if isinstance(intent.get("aipm"), dict) else {}
    return chosen and aipm.get("registers") is True


def has_sheets(intent, folder: Path | None = None) -> bool:
    """箱に ToDo のシートがある Layer か（intent と印のファイルだけを見る。シートの中身は ops が読む）。"""
    if _aipm_with_registers(intent):
        return True
    if not isinstance(intent, dict):
        return False
    if _chose(intent, "aipm-light"):
        # 箱を作る前のライトモードは黙って飛ばす（「読めなかった」に数え続けない）
        return folder is not None and (folder / "Sheets" / "format_contract.yaml").is_file()
    chosen = intent.get("work_style") == "aipm" or _chose(intent, "aipm")
    return chosen and folder is not None and (folder / "Sheets" / "light_sheets.yaml").is_file()


def read_intent(folder: Path):
    import yaml

    try:
        return yaml.safe_load((folder / "intent.yaml").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def due_items(root: Path, listed: dict, day: date, ops, layer_dir) -> tuple[list[dict], list[str]]:
    """listed（{layer のパス: scope}）のうち ToDo のシートがある Layer ごとの候補（2つの箱。空の Layer は出さない）と、
    読めなかった Layer の scope。"""
    rows, unreadable = [], []
    for rel, scope in listed.items():
        folder = layer_dir(root, rel)
        if folder is None or not has_sheets(read_intent(folder), folder):
            continue
        try:
            if ops.check(folder).get("route") != "selected":
                raise ValueError("not selected")
            _, _, files = ops._files(folder)
            picked = ops.today_pick(files, {"today": day.isoformat()})
        except Exception:  # noqa: BLE001 — 読めない箱は止めずに飛ばし、件数だけ残す
            unreadable.append(scope)
            continue
        cands = [c for c in picked.get("candidates") or [] if c.get("reason") in BUCKETS]
        if cands:
            rows.append({"scope": scope, "layer": rel, "candidates": cands})
    return rows, unreadable


def not_in_todo(root: Path, listed: dict) -> list[str]:
    """TODO の一覧の進行中に載っていない、ToDo のシートがある開いている Layer の scope_id（`Flow/` の下。
    Documents/ と隠しフォルダは見ない）。"""
    known = {Path(rel).as_posix().rstrip("/") for rel in listed} | set(listed.values())
    found = []
    flow = Path(root) / "Flow"
    for dp, dns, fns in os.walk(flow) if flow.is_dir() else ():
        dns[:] = [d for d in dns if not d.startswith(".") and d not in SKIP_DIRS]
        if "intent.yaml" not in fns:
            continue
        folder = Path(dp)
        intent = read_intent(folder)
        if not has_sheets(intent, folder) or str(intent.get("status") or "").strip().lower() not in OPEN:
            continue
        rel = folder.relative_to(root).as_posix()
        sid = str(intent.get("scope_id") or rel)
        if rel not in known and sid not in known:
            found.append(sid)
    return sorted(set(found))


def hide_private(rows: list[dict], private: set, show_private: bool = False) -> list[dict]:
    """private（layer のパスの集まり）の Layer の行に "private": True を付ける。show_private でなければ、その行は
    {"private": True, "count": 項目の数} にして、scope・layer・項目の中身を伏せる。"""
    out = []
    for r in rows:
        if r.get("layer") not in private:
            out.append(r)
        elif show_private:
            out.append(dict(r, private=True))
        else:
            out.append({"private": True, "count": sum(len(c.get("items") or []) for c in r["candidates"])})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AIPM の箱の期限が迫った項目（WillDo の候補。読むだけ）")
    ap.add_argument("--date", default=None, help="基準日 YYYY-MM-DD（plan の対象日。既定は今日）")
    ap.add_argument("--root", default=None, help="リポジトリのルート（既定は導入先のリポジトリか今のフォルダ）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show-private", action="store_true", help="私生活の節の案件の scope・Layer・項目も出す")
    a = ap.parse_args(argv)
    try:
        day = date.fromisoformat(a.date) if a.date else date.today()
        st = load_scheduled_today()
        if not st.yaml_available():
            print(st.YAML_MISSING, file=sys.stderr)
            return 2
        pf = st.load_ppm_files(a.root)
        root, cfg = pf.context(a.root)
    except (ImportError, ValueError) as exc:  # PpmConfigError は ValueError
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    empty = {"date": day.isoformat(), "layers": [], "not_in_todo": 0, "unreadable": 0}
    ops = pm_ops(root)
    if ops is None:
        print("AIPM の箱の期限: スキップ（aipm-guided/ops.py が無いか古い）", file=sys.stderr)
        if a.json:
            print(json.dumps(empty, ensure_ascii=False, indent=2))
        return 0
    todo = pf.read_todo(root, cfg)
    if todo is None:
        print(f"AIPM の箱の期限: TODO の一覧が無いのでスキップ（{pf.todo_path(root, cfg)}）", file=sys.stderr)
        if a.json:
            print(json.dumps(empty, ensure_ascii=False, indent=2))
        return 0
    listed = pf.inflight_layers(todo)
    rows, unreadable = due_items(root, listed, day, ops, st.layer_dir)
    rows = hide_private(rows, st.private_layers(todo, pf), a.show_private)
    missing = not_in_todo(root, listed)
    if a.json:
        print(json.dumps({"date": day.isoformat(), "layers": rows, "not_in_todo": len(missing),
                          "unreadable": len(unreadable)}, ensure_ascii=False, indent=2))
        return 0
    print(f"AIPM の箱の期限（{day.isoformat()} 基準・WillDo の候補。1行は人の言葉に書き直す）"
          + ("" if rows else ": なし"))
    for r in rows:
        if "count" in r:
            print(f"- {st.HIDDEN}: {r['count']} 件")
            continue
        print(f"- {r['scope']}")
        for c in r["candidates"]:
            for it in c["items"]:
                head = it.get("title") or it.get("question") or ""
                print(f"  - {c['reason']}: {it.get('id')} {head} — 期限 {it.get('due')}")
    if unreadable:
        print(f"参考: 箱を読めなかった案件 {len(unreadable)} 件（箱の初期化や aipm-guided の導入を確かめる）")
    if missing:
        print(f"参考: TODO の一覧の進行中に載っていない、ToDo の箱がある案件 {len(missing)} 件 — 載せるなら /ppm-todo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
