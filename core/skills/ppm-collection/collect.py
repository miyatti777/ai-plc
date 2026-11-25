#!/usr/bin/env python3
"""collect — ppm-collection の候補を絞る段。

依頼文（1〜2行）か新しい案件の Goal を受け取り、Registry の全状態（進行中・一時停止・いつかやる/予定・済み・やめた）から
似た案件を上位 N 件（既定10）に絞り、各件の Layer の intent（goal・success_criteria）と context.yaml の要約を添えて JSON で返す。
最大3件を選ぶのと行き先の勧めは、この JSON を読んだ AI が SKILL.md の手順で行う（ここでは決めない）。

当て方は同じフォルダの project_match.py。業務Project の表が無い DB でも止まらない（所属の手がかり無しで照らす）。
読み取り専用: Registry は読み取り専用で開き、ファイルも DB も書かない。

使い方（導入先のリポジトリのルートで）:
  python3 .claude/skills/ppm-collection/collect.py --text "<依頼文>" [--visibility company|private] [--top 10] [--title <題名>] [--exclude <scope_id> ...] [--db <DB>] [--root <リポジトリ>]
DB の既定は、隣の db フォルダ（.claude/db・.cursor/db）の aiplc_paths.py が決める場所（AIPLC_DB・.ai-plc/config.yaml を含む）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import project_match as pm  # noqa: E402

import yaml  # noqa: E402

ALL_STATUSES = ("active", "paused", "planned", "completed", "cancelled")
TOP_DEFAULT = 10
TOP_MAX = 20          # 読む Layer の上限（全 Layer を毎回読まない）
SC_MAX = 4            # success_criteria は先頭の何件まで添えるか
DOC_MAX = 3           # context の要約は何件まで
TEXT_MAX = 240        # 1項目の文字数の上限


# --- 場所と DB（読むだけ） ----------------------------------------------------

def default_root() -> Path:
    """導入先（<repo>/.claude/skills/ppm-collection/ または .cursor/...）ならそのリポジトリ、そうでなければ今のフォルダ。"""
    if HERE.parents[0].name == "skills" and HERE.parents[1].name in (".claude", ".cursor"):
        return HERE.parents[2]
    return Path.cwd()


def _paths_module(root: Path):
    """aiplc_paths.py（DB の場所を決める共通の関数）を読み込む。無ければ None。"""
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


def open_ro(db_path: Path | None, root: Path | None = None):
    """読み取り専用で開く。無い・開けないときは None。"""
    if not db_path or not Path(db_path).is_file():
        return None
    mod = _paths_module(root or default_root())
    try:
        if mod is not None and hasattr(mod, "open_ro"):
            con = mod.open_ro(str(db_path))
        else:
            con = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
            con.execute("PRAGMA query_only=1")
        con.row_factory = sqlite3.Row
        con.execute("SELECT 1 FROM projects LIMIT 1").fetchall()
        return con
    except sqlite3.Error:
        return None


def normalize_layer_path(root: Path, url) -> str | None:
    """Registry の top_page_url をリポジトリ相対の Flow/… に直す。Flow の下でなければ None（`Flow/../..` を通さない）。"""
    if not url:
        return None
    u = str(url).strip()
    root_r = root.resolve()
    try:
        p = (Path(u) if u.startswith("/") else root_r / u).resolve()
        rel = p.relative_to(root_r)
    except (ValueError, OSError):
        return None
    rel_s = rel.as_posix()
    return rel_s if rel_s.startswith("Flow/") else None


# --- 候補を絞る -------------------------------------------------------------

def status_label(status: str, has_layer: bool, scope_id: str) -> str:
    if status == "planned" and str(scope_id).startswith("S-"):
        return "いつかやる"  # ppm-someday のストック（S-ID）だけ。L-ID の planned は「予定」
    return {"active": "進行中", "paused": "一時停止", "planned": "予定", "completed": "済み", "cancelled": "やめた"}.get(status, status)


def _cut(s, n: int = TEXT_MAX) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def read_layer(root: Path, layer: str | None) -> dict:
    """Layer の intent と context.yaml の要約を読む（読むだけ）。読めないときは理由だけ返す。"""
    if not layer:
        return {"read": False, "why": "Layer が無い（Registry の行だけ）"}
    d = (root / layer).resolve()
    try:
        d.relative_to((root / "Flow").resolve())
    except ValueError:
        return {"read": False, "why": "Flow の外"}
    out: dict = {"read": True}
    intent = d / "intent.yaml"
    if intent.exists():
        try:
            it = yaml.safe_load(intent.read_text(encoding="utf-8")) or {}
            g = it.get("goal") or {}
            if isinstance(g, str):
                g = {"description": g}
            out["display_name"] = it.get("display_name") or it.get("scope_name")
            out["intent_status"] = it.get("status")
            out["goal"] = _cut(g.get("description"))
            out["success_criteria"] = [_cut(x, 160) for x in (g.get("success_criteria") or [])[:SC_MAX]]
        except Exception as e:  # noqa: BLE001
            out["intent_error"] = type(e).__name__
    else:
        out["intent_error"] = "intent.yaml が無い"
    ctx = d / "context.yaml"
    if ctx.exists():
        try:
            c = yaml.safe_load(ctx.read_text(encoding="utf-8")) or {}
            docs = c.get("context_documents") or []
            out["context"] = [{"name": _cut(x.get("name"), 60), "summary": _cut(x.get("summary"), 200)}
                              for x in docs[:DOC_MAX] if isinstance(x, dict)]
        except Exception as e:  # noqa: BLE001
            out["context_error"] = type(e).__name__
    return out


def collect(root: Path, text: str, db_path: Path | None, top: int = TOP_DEFAULT, source_vis: str = "company",
            title: str | None = None, exclude: set[str] | None = None) -> dict:
    """exclude: 候補から外す scope_id（/ppm-someday start から来た S-ID など）。"""
    top = max(1, min(int(top), TOP_MAX))
    exclude = set(exclude or ())
    body_toks = set(pm.tokens(text, bigrams=True))
    title_toks = set(pm.tokens(title, bigrams=True)) if title else set()
    notes: list[str] = []
    if not body_toks and not title_toks:
        return {"query": text, "visibility": source_vis, "candidates": [], "none_option": True,
                "notes": ["依頼文から当てられる語が取れない（もう少し具体的な言葉で頼む）"]}
    con = open_ro(db_path, root)
    if con is None:
        return {"query": text, "visibility": source_vis, "candidates": [], "none_option": True,
                "notes": ["Registry を開けないので候補を出せない"]}
    try:
        loaded = pm.load_side(con, root, ALL_STATUSES, normalize_layer_path, bigrams=True)
    except sqlite3.Error as e:
        return {"query": text, "visibility": source_vis, "candidates": [], "none_option": True,
                "notes": [f"Registry を読めないので候補を出せない（{type(e).__name__}）"]}
    finally:
        con.close()
    projects, side, df, progs = loaded["projects"], loaded["side"], loaded["df"], loaded["progs"]
    has_programs = loaded["business_tables"]
    scored = []
    held = 0
    for r in projects:
        if r["scope_id"] in exclude:
            continue
        sd = side[r["id"]]
        prog = progs.get(sd["prog_uid"]) if sd["prog_uid"] else None
        domain = prog["read_domain"] if prog else None
        if prog is not None and not pm.domain_allowed(domain, source_vis):
            held += 1
            continue
        score, hits, title_hits = pm.score(sd["toks"], body_toks, title_toks, df)
        if score is None:
            continue
        domain_source = "program"
        if prog is None:
            # Program に入っていない案件は Layer の intent の membership.read_domain だけを見る（推測しない）
            domain = pm.layer_domain_hint(root, r["layer"])
            domain_source = "intent" if domain else "unknown"
            if not pm.domain_allowed(domain, source_vis):
                held += 1
                continue
        words = sorted(hits | title_hits, key=lambda t: -pm.weight(t, df))
        scored.append({
            "scope_id": r["scope_id"], "name": r["name"], "registry_goal": _cut(r["goal"]),
            "status": r["status"], "status_label": status_label(r["status"], bool(r["layer"]), r["scope_id"]),
            "layer": r["layer"], "program": prog["display_name"] if prog else None, "read_domain": domain,
            "read_domain_source": domain_source,
            "business_projects": sorted(sd["linked_biz"]),
            "score": score, "matched_words": words[:6],
        })
    scored.sort(key=lambda x: (-x["score"], x["scope_id"]))
    picked = scored[:top]
    unknown = 0
    for c in picked:
        if c["read_domain_source"] == "unknown" and has_programs:
            # Program を使って公開範囲を分けている DB で、どこにも属さない案件は名前だけ返し、中身は返さない
            c["layer_detail"] = {"read": False, "why": "公開範囲が分からない（Program にも intent にも無い）ので中身は読まない"}
            c["registry_goal"] = None
            unknown += 1
        else:
            c["layer_detail"] = read_layer(root, c["layer"])
    if not scored:
        notes.append("名前・目的に当たる案件が無い（どれでもない）")
    if held:
        notes.append(f"公開範囲の守りで対象から外した案件がある（visibility={source_vis}）")
    if unknown:
        notes.append(f"公開範囲が分からない案件 {unknown} 件は名前だけ（中身は読んでいない）")
    if not has_programs:
        notes.append("業務Project の表が無い DB なので、所属（Program）の手がかり無しで Registry と Layer だけで照らした")
    return {"query": text, "visibility": source_vis, "candidates": picked, "none_option": True,
            "matched": len(scored), "projects_seen": len(projects), "query_words": len(body_toks), "notes": notes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ppm-collection: 依頼に似た既存の案件を絞る（読み取り専用）")
    ap.add_argument("--text")
    ap.add_argument("--file")
    ap.add_argument("--title")
    ap.add_argument("--visibility", choices=["company", "private"], default="company")
    ap.add_argument("--top", type=int, default=TOP_DEFAULT)
    ap.add_argument("--db")
    ap.add_argument("--root")
    ap.add_argument("--exclude", action="append", default=[], help="候補から外す scope_id（重ねられる）")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve() if a.root else default_root()
    if a.text is not None:
        text = a.text  # --text "" で標準入力を待たない
    elif a.file:
        text = Path(a.file).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()
    db = Path(a.db) if a.db else default_db(root)
    print(json.dumps(collect(root, text, db, a.top, a.visibility, a.title, set(a.exclude)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
