#!/usr/bin/env python3
"""AI-PLC Registry の分類情報（所属・種類・実行環境）を扱う。

正本は Layer の intent.yaml（classification ブロック）と backlog.yaml（tasks[].executed_by）。
Registry（ai_plc.db）の別表 project_classification / task_execution はその写し。

    python3 .claude/db/classify.py vocab [--check]
    python3 .claude/db/classify.py migrate [--yes]
    python3 .claude/db/classify.py sync (--layer PATH ... | --all) [--yes]
    python3 .claude/db/classify.py suggest [--scope ID ...] [--out FILE]
    python3 .claude/db/classify.py apply FILE [--yes]
    python3 .claude/db/classify.py show [--scope ID] [--reveal]

- 書き込むのは --yes を付けたときだけ（既定は予定の表示だけ）
- 語彙はローカルの .claude/db/classification_vocab.yaml（git 管理外）。無ければ classification_vocab.example.yaml
- 機密（confidential: true）の所属の表示名は、--reveal を付けたときだけ画面に出す
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

import yaml

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
DB_DIRS = (Path(".claude") / "db", Path(".cursor") / "db")  # Claude Code / Cursor の配置


def _find_root(start: Path = HERE) -> Path:
    """このファイルから上にたどって、最初に .claude/db/ai_plc.db（無ければ .cursor/db/ai_plc.db）があるフォルダ。
    .claude/db/ に置いても、.claude/db/registry_viewer/ に置いても同じプロジェクトを指す"""
    for p in [start, *start.parents]:
        if any((p / d / "ai_plc.db").is_file() for d in DB_DIRS):
            return p
    return start.parent.parent


REPO = _find_root()
DB_DIR = next((REPO / d for d in DB_DIRS if (REPO / d / "ai_plc.db").is_file()), REPO / DB_DIRS[0])
DEFAULT_DB = DB_DIR / "ai_plc.db"
# 語彙: このファイルの隣 → DB と同じフォルダ の順。サンプルはこのファイルの隣
VOCAB_LOCALS = (HERE / "classification_vocab.yaml", DB_DIR / "classification_vocab.yaml")
VOCAB_EXAMPLE = HERE / "classification_vocab.example.yaml"
EXECUTORS = ("claude-code", "codex", "cursor")
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
AXES = ("affiliation", "kind")
LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class _StrictLoader(yaml.SafeLoader):
    """語彙用: 同じキーが2回あればエラー（YAML は黙って後の値で上書きするため）"""


def _no_dup_mapping(loader, node, deep=False):
    keys = set()
    for k, _v in node.value:
        key = loader.construct_object(k, deep=deep)
        if key in keys:
            raise ClassifyError(f"語彙のキー {key!r} が重複しています")
        keys.add(key)
    return loader.construct_mapping(node, deep=deep)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dup_mapping)
LEGACY_EXECUTOR = {"codex": "codex", "claude": "claude-code", "claude code": "claude-code", "claude-code": "claude-code",
                   "cc": "claude-code", "cursor": "cursor"}


class ClassifyError(Exception):
    pass


def _load_module(name, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- vocabulary
def vocab_path() -> Path:
    env = os.environ.get("AIPLC_CLASSIFICATION_VOCAB")
    if env:
        if not Path(env).is_file():
            raise ClassifyError(f"AIPLC_CLASSIFICATION_VOCAB={env} が見つかりません")
        return Path(env)
    return next((p for p in VOCAB_LOCALS if p.is_file()), VOCAB_EXAMPLE)


def load_vocab(path: Path | None = None) -> dict:
    """{'affiliation': {key: {label, confidential, keywords}}, 'kind': {...}, '_path': str}。形式が崩れていれば ClassifyError"""
    path = path or vocab_path()
    if not path.is_file():
        return {"affiliation": {}, "kind": {}, "_path": None}
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader) or {}
    except yaml.YAMLError as e:
        raise ClassifyError(f"{path.name}: YAML として読めません（{e}）")
    if not isinstance(data, dict):
        raise ClassifyError(f"{path.name}: mapping ではありません")
    out = {"_path": str(path)}
    for axis in AXES:
        entries = data.get(axis) or {}
        if not isinstance(entries, dict):
            raise ClassifyError(f"{path.name}: {axis} が mapping ではありません")
        norm = {}
        for key, v in entries.items():
            key = str(key)
            if not KEY_RE.match(key):
                raise ClassifyError(f"{path.name}: {axis} のキー {key!r} は形式外（英小文字・数字・ハイフン、40字まで）")
            v = v if isinstance(v, dict) else {}
            kws = v.get("keywords") or []
            norm[key] = {"label": str(v.get("label") or key), "has_label": bool(v.get("label")),
                         "confidential": bool(v.get("confidential")),
                         "keywords": [str(k) for k in kws if str(k).strip()] if isinstance(kws, list) else []}
        out[axis] = norm
    return out


def label(vocab, axis, key, reveal=False):
    if key is None:
        return "—"
    e = vocab.get(axis, {}).get(key)
    if e is None:
        return f"{key}（語彙に無い）"
    if e["confidential"] and not reveal:
        return f"{key}（機密）"
    return e["label"]


def validate_value(vocab, axis, value):
    if value is None:
        return None
    if axis == "executor":
        if value not in EXECUTORS:
            raise ClassifyError(f"executor は {', '.join(EXECUTORS)} のどれか（{value!r}）")
        return value
    if value not in vocab.get(axis, {}):
        raise ClassifyError(f"{axis} の {value!r} は語彙にありません（classify.py vocab で確認）")
    return value


# ---------------------------------------------------------------- DB
# 分類の別表。projects / tasks に列を足すと、Identity v2 移行の前の検査（init_db._validate_schema_inventory）が止まるため別表
_EXEC_SQL = ",".join("'%s'" % e for e in EXECUTORS)
TABLES_SQL = f"""
    CREATE TABLE IF NOT EXISTS project_classification (
        scope_id    TEXT PRIMARY KEY,
        affiliation TEXT,
        kind        TEXT,
        executor    TEXT CHECK(executor IS NULL OR executor IN ({_EXEC_SQL})),
        source      TEXT NOT NULL DEFAULT 'intent' CHECK(source IN ('intent','backfill')),
        updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    );
    CREATE TABLE IF NOT EXISTS task_execution (
        scope_id    TEXT NOT NULL,
        task_id     TEXT NOT NULL,
        executed_by TEXT NOT NULL CHECK(executed_by IN ({_EXEC_SQL})),
        updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        PRIMARY KEY (scope_id, task_id)
    );
"""


def create_tables(conn):
    """init_db.py に create_classification_tables があればそれを使い（1か所で管理）、無ければ同じ DDL を実行する"""
    for p in (HERE / "init_db.py", DB_DIR / "init_db.py"):
        if p.is_file():
            try:
                mod = _load_module("_cls_init_db", p)
            except Exception:  # noqa: BLE001
                continue
            if hasattr(mod, "create_classification_tables"):
                mod.create_classification_tables(conn)
                return
    conn.executescript(TABLES_SQL)
    conn.commit()


def has_tables(conn) -> bool:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {"project_classification", "task_execution"} <= names


def backup_db(db: Path, state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    dest = state_dir / f"ai_plc_backup_before_classify_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    src = sqlite3.connect(str(db))
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dest


# ---------------------------------------------------------------- Layers
def audit_module():
    """Layer の探索に使う aiplc_status_audit.py。環境変数 → <root>/scripts/ → <root>/.claude/ai-plc-jev/scripts/（Jev 実験版）"""
    env = os.environ.get("AIPLC_STATUS_AUDIT")
    cands = [Path(env)] if env else [REPO / "scripts" / "aiplc_status_audit.py",
                                     REPO / ".claude" / "ai-plc-jev" / "scripts" / "aiplc_status_audit.py"]
    path = next((c for c in cands if c.is_file()), None)
    if path is None:
        raise ClassifyError("aiplc_status_audit.py が見つかりません（Jev 実験版に入っています）。AIPLC_STATUS_AUDIT で指定できます")
    os.environ.setdefault("AIPLC_REPO", str(REPO))
    return _load_module("_cls_audit", path)


def layer_index(root: Path, db: Path):
    """(scope_id -> Layer フォルダ, 1つに決まらない scope_id の集合)。
    同じ scope_id のフォルダが複数あるときは、Registry の top_page_url で1つに決まる（status_audit の resolve が
    'url' で解決する）ものだけを使い、それ以外は ambiguous として写さない・提案しない"""
    audit = audit_module()
    index, _flow, _unreadable = audit.scan_intents(root)
    out, ambiguous = {}, set()
    for sid, ls in index.items():
        if len(ls) == 1:
            out[sid] = ls[0].folder
        else:
            ambiguous.add(sid)
    if db.is_file():
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            for row in conn.execute("SELECT scope_id, top_page_url FROM projects"):
                layer, via, *_ = audit.resolve(row, root, index)
                if layer is not None and (row["scope_id"] not in ambiguous or via == "url"):
                    out[row["scope_id"]] = layer.folder
                    ambiguous.discard(row["scope_id"])
        finally:
            conn.close()
    return out, ambiguous


class UnreadableLayer(ClassifyError):
    pass


def read_yaml(path: Path, strict=False) -> dict:
    """読めない YAML は、strict なら UnreadableLayer、そうでなければ空の dict（全体を止めない）"""
    if not path.is_file():
        return {}
    try:
        d = yaml.load(path.read_text(encoding="utf-8-sig"), Loader=LOADER)
    except (yaml.YAMLError, UnicodeDecodeError, OSError) as e:
        if strict:
            raise UnreadableLayer(f"{path.name} を読めません（{type(e).__name__}）")
        return {}
    return d if isinstance(d, dict) else {}


def layer_classification(folder: Path):
    """(intent, classification dict or None, {task_id: executed_by})。intent.yaml / backlog.yaml が壊れていれば UnreadableLayer"""
    intent = read_yaml(folder / "intent.yaml", strict=True)
    c = intent.get("classification")
    c = {k: (str(c.get(k)).strip() if c.get(k) not in (None, "") else None) for k in ("affiliation", "kind", "executor")} \
        if isinstance(c, dict) else None
    tasks = read_yaml(folder / "backlog.yaml", strict=True).get("tasks") or []
    ex = {}
    for t in tasks if isinstance(tasks, list) else []:
        if isinstance(t, dict) and t.get("executed_by"):
            tid = str(t.get("id", t.get("task_id")) or "").strip()
            if tid:
                ex[tid] = str(t["executed_by"]).strip()
    return intent, c, ex


# ---------------------------------------------------------------- intent.yaml の classification ブロックの書き換え
def render_block(values: dict, eol: str = "\n") -> str:
    lines = ["classification:" + eol]
    for k in ("affiliation", "kind", "executor"):
        if values.get(k) is not None:
            lines.append(f"  {k}: {values[k]}{eol}")
    return "".join(lines)


HEAD_RE = re.compile(r"""^(?:\ufeff)?(?:classification|"classification"|'classification')[ \t]*:""")


def edit_classification_text(text: str, values: dict) -> str:
    """トップレベルの classification: ブロックを置き換える（無ければ末尾に足す）。ほかの行はそのまま"""
    lines = text.splitlines(keepends=True)
    heads = [i for i, l in enumerate(lines) if HEAD_RE.match(l)]
    eol = "\r\n" if "\r\n" in text else "\n"
    block = render_block(values, eol)
    if len(heads) > 1:
        raise ClassifyError("classification: が2つ以上あります")
    if not heads:
        if text and not text.endswith("\n"):
            text += eol
        return text + block
    i = heads[0]
    j = i + 1
    while j < len(lines):
        s = lines[j]
        if s.strip() and not s.startswith((" ", "\t", "#")):
            break
        j += 1
    # ブロック末尾の空行・コメントは残す（次のトップレベルキーの前置き）
    k = j
    while k > i + 1 and (not lines[k - 1].strip() or lines[k - 1].lstrip().startswith("#")) and not lines[k - 1].startswith((" ", "\t")):
        k -= 1
    return "".join(lines[:i]) + block + "".join(lines[k:])


def write_classification(path: Path, values: dict):
    text = path.read_bytes().decode("utf-8")
    try:
        old = yaml.load(text.lstrip("\ufeff"), Loader=LOADER)
    except yaml.YAMLError as e:
        raise ClassifyError(f"{path.name}: YAML として読めません（{type(e).__name__}）")
    if not isinstance(old, dict):
        raise ClassifyError(f"{path}: mapping ではありません")
    cur = old.get("classification")
    if cur is not None and (not isinstance(cur, dict) or set(cur) - {"affiliation", "kind", "executor"}):
        raise ClassifyError(f"{path.name}: classification に想定外の形・キーがあるため書きません（手で直してください）")
    if "classification" in old and not any(HEAD_RE.match(l) for l in text.splitlines()):
        raise ClassifyError(f"{path.name}: classification の見出しの行を特定できません")
    new_text = edit_classification_text(text, values)
    expect = copy.deepcopy(old)
    expect["classification"] = {k: v for k, v in values.items() if v is not None}
    try:
        got = yaml.load(new_text.lstrip("\ufeff"), Loader=LOADER)
    except yaml.YAMLError as e:
        raise ClassifyError(f"{path.name}: 書き換え後が YAML として読めないため中止しました（{type(e).__name__}）")
    if got != expect:
        raise ClassifyError(f"{path.name}: 書き換えで classification 以外が変わるため中止しました")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".classify_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
        os.chmod(tmp, path.stat().st_mode & 0o777)
        if path.read_bytes().decode("utf-8") != text:
            raise ClassifyError(f"{path.name} が書き込みの直前に他で変更されました")
        os.replace(tmp, path)
    except OSError as e:
        raise ClassifyError(f"{path.name} を書けません（{e}）")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------- sync（正本 → Registry）
def sync_rows(root: Path, db: Path, folders, yes: bool, vocab) -> list:
    """folders: [(scope_id, folder)]。正本に無いものは写さない（消さない）"""
    plan = []
    for sid, folder in folders:
        try:
            _intent, c, ex = layer_classification(folder)
        except UnreadableLayer as e:
            plan.append({"scope_id": sid, "result": "skipped", "reason": str(e)})
            continue
        if c is not None:
            for axis in AXES:
                if c[axis] is not None and c[axis] not in vocab.get(axis, {}):
                    plan.append({"scope_id": sid, "result": "skipped", "reason": f"{axis}={c[axis]} が語彙に無い"})
                    break
            else:
                if c["executor"] is not None and c["executor"] not in EXECUTORS:
                    plan.append({"scope_id": sid, "result": "skipped", "reason": f"executor={c['executor']} は形式外"})
                else:
                    plan.append({"scope_id": sid, "project": c})
        for tid, e in ex.items():
            if e in EXECUTORS:
                plan.append({"scope_id": sid, "task_id": tid, "executed_by": e})
            else:
                plan.append({"scope_id": sid, "task_id": tid, "result": "skipped", "reason": f"executed_by={e} は形式外"})
    if yes and plan:
        precheck_db(db, {p["scope_id"] for p in plan})
        conn = sqlite3.connect(str(db), timeout=10)
        try:
            with conn:
                for p in plan:
                    if "project" in p:
                        c = p["project"]
                        conn.execute(
                            "INSERT INTO project_classification (scope_id, affiliation, kind, executor, source) "
                            "VALUES (?,?,?,?,'intent') ON CONFLICT(scope_id) DO UPDATE SET affiliation=excluded.affiliation, "
                            "kind=excluded.kind, executor=excluded.executor, source='intent', "
                            "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')",
                            (p["scope_id"], c["affiliation"], c["kind"], c["executor"]))
                        p["result"] = "written"
                    elif "executed_by" in p:
                        conn.execute(
                            "INSERT INTO task_execution (scope_id, task_id, executed_by) VALUES (?,?,?) "
                            "ON CONFLICT(scope_id, task_id) DO UPDATE SET executed_by=excluded.executed_by, "
                            "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')",
                            (p["scope_id"], p["task_id"], p["executed_by"]))
                        p["result"] = "written"
        finally:
            conn.close()
    return plan


def precheck_db(db: Path, scopes):
    """書く前の検査: 分類の表があること・1つの DB に1つの workspace（別表の主キーは scope_id。Identity v2 で同じ
    scope_id が複数 workspace に入った DB では止める。将来は sync_uid をキーにする）"""
    conn = sqlite3.connect(str(db), timeout=10)
    try:
        if not has_tables(conn):
            raise ClassifyError("分類の表がありません。先に classify.py migrate --yes")
        for sid in scopes:
            n = conn.execute("SELECT COUNT(*) FROM projects WHERE scope_id=?", (sid,)).fetchone()[0]
            if n > 1:
                raise ClassifyError(f"projects に {sid} が {n} 行あります（複数 workspace の DB には未対応）")
    finally:
        conn.close()


# ---------------------------------------------------------------- suggest（候補 → 承認ファイル）
def _guess(vocab, axis, text):
    scores = {}
    low = text.lower()
    for key, e in vocab.get(axis, {}).items():
        n = sum(1 for kw in e["keywords"] if kw.lower() in low)
        if n:
            scores[key] = n
    if not scores:
        return None, "キーワードの一致なし"
    best = max(scores.values())
    tops = sorted(k for k, v in scores.items() if v == best)
    if len(tops) > 1:
        return None, f"同点 {'/'.join(tops)}"
    return tops[0], f"キーワード一致 {best} 件"


def _guess_executor(intent, ex):
    legacy = intent.get("executor")
    if isinstance(legacy, str) and legacy.strip().lower() in LEGACY_EXECUTOR:
        return LEGACY_EXECUTOR[legacy.strip().lower()], "既存の executor: の行"
    vals = [v for v in ex.values() if v in EXECUTORS]
    if vals:
        top = max(set(vals), key=vals.count)
        if vals.count(top) * 2 > len(vals):
            return top, f"タスクの executed_by の多数決（{vals.count(top)}/{len(vals)}）"
    return None, "手がかりなし（推測しない）"


def suggest(root: Path, db: Path, vocab, scopes=None) -> dict:
    index, dups = layer_index(root, db)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        projects = {r["scope_id"]: r for r in conn.execute("SELECT scope_id, name, goal FROM projects")}
    finally:
        conn.close()
    rows, out_of_scope = [], []
    for sid in sorted(projects):
        if scopes and sid not in scopes:
            continue
        folder = index.get(sid)
        if folder is None or sid in dups:
            out_of_scope.append({"scope_id": sid, "reason": "Layer フォルダが見つからない" if folder is None
                                 else "同じ scope_id のフォルダが複数ある"})
            continue
        try:
            intent, c, ex = layer_classification(folder)
        except UnreadableLayer as e:
            out_of_scope.append({"scope_id": sid, "reason": str(e)})
            continue
        if c is not None and all(c.get(k) for k in ("affiliation", "kind", "executor")):
            continue  # もう付いている
        row = projects[sid]
        text = " ".join(str(x or "") for x in (row["name"], row["goal"], folder.name,
                                                (intent.get("goal") or {}).get("description") if isinstance(intent.get("goal"), dict) else ""))
        cur = c or {"affiliation": None, "kind": None, "executor": None}
        prop, why = {}, {}
        for axis in AXES:
            prop[axis], why[axis] = (cur[axis], "intent に既にある") if cur.get(axis) else _guess(vocab, axis, text)
        prop["executor"], why["executor"] = (cur["executor"], "intent に既にある") if cur.get("executor") else _guess_executor(intent, ex)
        rows.append({"scope_id": sid, "layer": os.path.relpath(folder, root), "decision": "undecided",
                     "from": cur, **prop, "why": why})
    return {"version": 1, "kind": "classify.approval", "generated_at": date.today().isoformat(),
            "vocab": vocab.get("_path"), "rows": rows, "out_of_scope": out_of_scope}


# ---------------------------------------------------------------- apply
def apply(root: Path, db: Path, vocab, approval: dict, yes: bool, log_path: Path) -> list:
    if approval.get("kind") != "classify.approval":
        raise ClassifyError("承認ファイルの kind が classify.approval ではありません")
    index, dups = layer_index(root, db)
    approved = [r for r in approval.get("rows") or [] if r.get("decision") == "approve"]
    if yes and approved:
        precheck_db(db, {r.get("scope_id") for r in approved})
    results = []

    def log(rec):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now().astimezone().isoformat(timespec="seconds"), **rec},
                               ensure_ascii=False) + "\n")

    for r in approval.get("rows") or []:
        sid = r.get("scope_id")
        if r.get("decision") != "approve":
            continue
        res = {"scope_id": sid}
        try:
            folder = index.get(sid)
            if folder is None or sid in dups:
                raise ClassifyError("Layer フォルダを1つに特定できません")
            values = {"affiliation": validate_value(vocab, "affiliation", r.get("affiliation")),
                      "kind": validate_value(vocab, "kind", r.get("kind")),
                      "executor": validate_value(vocab, "executor", r.get("executor"))}
            if all(v is None for v in values.values()):
                raise ClassifyError("値が1つもありません")
            _intent, cur, _ex = layer_classification(folder)
            frm = r.get("from") or {"affiliation": None, "kind": None, "executor": None}
            now = cur or {"affiliation": None, "kind": None, "executor": None}
            merged = {k: values[k] if values[k] is not None else frm.get(k) for k in values}
            if merged == {k: now.get(k) for k in merged}:
                res.update(result="noop")  # もう反映済み（同じ承認ファイルの流し直し）
                results.append(res)
                continue
            if any(now.get(k) != frm.get(k) for k in ("affiliation", "kind", "executor")):
                res.update(result="conflict", reason="提案の後に intent.yaml の classification が変わっています")
                results.append(res)
                continue
            res.update(before=now, after=merged)
            if yes:
                write_classification(folder / "intent.yaml", merged)
                log({"op": "apply", "scope_id": sid, "before": now, "after": merged, "registry": "pending"})
                try:
                    sync_rows(root, db, [(sid, folder)], True, vocab)
                except ClassifyError as e:
                    res.update(result="applied_intent_only",
                               reason=f"intent.yaml は反映済み・Registry への写しに失敗（classify.py sync --layer で写し直せます）: {e}")
                    log({"op": "sync_failed", "scope_id": sid, "error": str(e)})
                    results.append(res)
                    continue
                log({"op": "synced", "scope_id": sid})
                res["result"] = "applied"
            else:
                res["result"] = "planned"
        except ClassifyError as e:
            res.update(result="error", reason=str(e))
        except (OSError, yaml.YAMLError) as e:
            res.update(result="error", reason=f"{type(e).__name__}: {e}")
        results.append(res)
    return results


# ---------------------------------------------------------------- CLI
def _print_rows(rows, cols):
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) if rows else len(c) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


def main(argv=None):
    ap = argparse.ArgumentParser(description="AI-PLC Registry の分類情報（所属・種類・実行環境）")
    ap.add_argument("--db", type=Path, default=Path(os.environ.get("AIPLC_DB") or DEFAULT_DB))
    ap.add_argument("--root", type=Path, default=REPO)
    ap.add_argument("--state-dir", type=Path, default=None, help="承認ファイル・記録・バックアップの置き場所（既定: DB と同じフォルダの status_hygiene/）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("vocab"); v.add_argument("--check", action="store_true"); v.add_argument("--reveal", action="store_true")
    m = sub.add_parser("migrate"); m.add_argument("--yes", action="store_true")
    s = sub.add_parser("sync"); s.add_argument("--layer", action="append", default=[]); s.add_argument("--all", action="store_true"); s.add_argument("--yes", action="store_true")
    g = sub.add_parser("suggest"); g.add_argument("--scope", action="append", default=[]); g.add_argument("--out", type=Path)
    a = sub.add_parser("apply"); a.add_argument("file", type=Path); a.add_argument("--yes", action="store_true")
    w = sub.add_parser("show"); w.add_argument("--scope"); w.add_argument("--reveal", action="store_true")
    args = ap.parse_args(argv)
    state = args.state_dir or (args.db.parent / "status_hygiene")
    try:
        vocab = load_vocab()
        if args.cmd == "vocab":
            print(f"語彙: {vocab['_path'] or '（無し）'}")
            for axis in AXES:
                print(f"[{axis}]")
                for k, e in vocab[axis].items():
                    print(f"  {k}: {label(vocab, axis, k, args.reveal)}")
            print(f"[executor] {', '.join(EXECUTORS)}（固定）")
            if args.check:
                warn = [f"{axis}.{k}: label がありません" for axis in AXES for k, e in vocab[axis].items() if not e["has_label"]]
                for w_ in warn:
                    print(f"警告: {w_}")
                if not vocab["_path"]:
                    print("警告: 語彙ファイルがありません")
                    return 1
                print("検査: 形式・キーの重複は問題なし" + ("" if not warn else f"（警告 {len(warn)} 件）"))
                return 1 if warn else 0
            return 0
        if args.cmd == "migrate":
            conn = sqlite3.connect(str(args.db))
            try:
                if has_tables(conn):
                    print("分類の表はもうあります（変更なし）")
                    return 0
            finally:
                conn.close()
            if not args.yes:
                print(f"予定: {args.db} に project_classification / task_execution を作る（--yes で実行。先にバックアップを取ります）")
                return 0
            bk = backup_db(args.db, state)
            conn = sqlite3.connect(str(args.db))
            try:
                create_tables(conn)
            finally:
                conn.close()
            print(f"作りました（バックアップ: {bk}）")
            return 0
        if args.cmd == "sync":
            if not args.layer and not args.all:
                raise ClassifyError("--layer か --all を指定してください")
            if args.all:
                index, dups = layer_index(args.root, args.db)
                folders = [(sid, f) for sid, f in sorted(index.items()) if sid not in dups]
            else:
                folders = []
                for lp in args.layer:
                    f = (args.root / lp) if not Path(lp).is_absolute() else Path(lp)
                    intent = read_yaml(f / "intent.yaml")
                    sid = str(intent.get("scope_id") or "").strip()
                    if not sid:
                        raise ClassifyError(f"{lp}/intent.yaml に scope_id がありません")
                    folders.append((sid, f))
            plan = sync_rows(args.root, args.db, folders, args.yes, vocab)
            for p in plan:
                what = (f"project {p['project']}" if "project" in p else
                        f"task {p['task_id']} executed_by={p.get('executed_by')}" if "task_id" in p else "project")
                print(f"{p['scope_id']}: {what} — {p.get('result', 'planned')}{'（' + p['reason'] + '）' if p.get('reason') else ''}")
            if not plan:
                print("写すものはありません（intent.yaml に classification も、タスクに executed_by もありません）")
            return 0
        if args.cmd == "suggest":
            rep = suggest(args.root, args.db, vocab, set(args.scope) or None)
            out = args.out
            if out is None:
                base = state / "approvals" / f"classify_{date.today().strftime('%Y%m%d')}"
                out, n = Path(f"{base}.json"), 2
                while out.exists():  # 人が approve に直したファイルを上書きしない
                    out, n = Path(f"{base}_{n}.json"), n + 1
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"候補 {len(rep['rows'])} 件・対象外 {len(rep['out_of_scope'])} 件 → {out}")
            print("反映するなら、行の decision を approve にし（値は直してよい）、classify.py apply <ファイル> → --yes")
            return 0
        if args.cmd == "apply":
            try:
                approval = json.loads(args.file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                raise ClassifyError(f"承認ファイルを読めません（{e}）")
            res = apply(args.root, args.db, vocab, approval, args.yes, state / "classify_log.jsonl")
            for r in res:
                print(f"{r['scope_id']}: {r['result']}" + (f"（{r['reason']}）" if r.get("reason") else "")
                      + (f" {r.get('before')} → {r.get('after')}" if r.get("after") else ""))
            if not res:
                print("approve の行がありません")
            if not args.yes and any(r["result"] == "planned" for r in res):
                print("（予定だけです。--yes で反映します）")
            return 1 if any(r["result"] in ("error", "applied_intent_only") for r in res) else 0
        if args.cmd == "show":
            conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                if not has_tables(conn):
                    print("分類の表がありません（classify.py migrate --yes）")
                    return 0
                q = ("SELECT p.scope_id, p.name, c.affiliation, c.kind, c.executor, "
                     "(SELECT group_concat(DISTINCT e.executed_by) FROM task_execution e WHERE e.scope_id=p.scope_id) AS tasks "
                     "FROM projects p LEFT JOIN project_classification c ON c.scope_id=p.scope_id")
                rows = [dict(r) for r in conn.execute(q + (" WHERE p.scope_id=?" if args.scope else "") + " ORDER BY p.scope_id",
                                                        (args.scope,) if args.scope else ())]
            finally:
                conn.close()
            for r in rows:
                r["affiliation"] = label(vocab, "affiliation", r["affiliation"], args.reveal)
                r["kind"] = label(vocab, "kind", r["kind"], args.reveal)
                r["executor"] = r["executor"] or "—"
                r["tasks"] = r["tasks"] or "—"
            _print_rows(rows, ["scope_id", "affiliation", "kind", "executor", "tasks"])
            return 0
    except ClassifyError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
