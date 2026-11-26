#!/usr/bin/env python3
"""TODO の一覧の待ちの節（既定「待ち／要確認」。設定 `ppm.todo.waiting_section`）を見直す。

各行を3つに分けて直す案を出す（読むだけ）。本人が承認した行だけを書き換える機能もある（このスキルで
ファイルを書くのはこの道具だけ）。

    python3 .claude/skills/ppm-todo/todo_waiting.py                     # 直す案（本人向けの文）
    python3 .claude/skills/ppm-todo/todo_waiting.py --json              # 機械向け（key・分け方・根拠・案・todo_sha256）
    python3 .claude/skills/ppm-todo/todo_waiting.py --apply APPROVAL.json           # 書き換えの予定を見せるだけ
    python3 .claude/skills/ppm-todo/todo_waiting.py --apply APPROVAL.json --write   # 承認した行だけを書き換えて保存

分け方（根拠は手元の案件の状態だけ。予定表・メールは読まず、行の中のリンクも開かない）:
- resolved（解消したと分かる）: 行に書かれた案件の ID（Layer の intent の scope_id）がどれも閉じている
  （正は Layer の intent の status。Layer が見つからないときだけ Registry の projects の写しを使う）
- past（日付がどれも過ぎた）: 行の中の日付（M/D。年が無ければ今日から前後半年の内に入る年とみなす）がどれも今日より前
- unknown（判断できない）: 上のどちらでもない（日付が無い・「来週」など）。本人に聞く

書き換えの約束:
- 待ちの節の `- ` の1行1件の形と見出しを保つ。承認していない行・ほかの節は1文字も変えない
- 承認ファイルの todo_sha256 が今のファイルと違えば止まる（案を出した後に一覧が変わったら、案を出し直す）
- 保存の直前にもう一度読み、変わっていれば止まる。保存した後に読み戻して確かめる
- 元のファイルの権限（例 0600）を保つ。一覧がシンボリックリンクなら、リンクは残してリンク先の実体を書き換える。
  ただしリンク先がリポジトリの外なら書かずに止まる（TODO の一覧はリポジトリの中の実体に置く。外の実体には書かない）
- 一覧が UTF-8 で読めないとき、承認ファイルが読めないとき（入れ子が深すぎるものを含む）は [HOLD] で止まる

承認ファイル（JSON。置き場はリポジトリの外。リポジトリの中に置いたものは断る。commit しない）:
  {"todo_sha256": "<案を出したときの値>", "items": [{"key": "<案の key>", "action": "delete" | "rewrite", "text": "<rewrite の新しい本文>"}]}
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import stat
import sys
from datetime import date, timedelta
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
CLOSED = {"completed", "cancelled", "done", "dropped"}

LINK_RE = re.compile(r"\[[^\]]*\]\([^)]*\)|https?://\S+")
DATE_RE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/]|\s*(?:件|個|枚)(?![一-龥ぁ-んァ-ヶ]))"
                     r"(?:[〜~～](?:(\d{1,2})/)?(\d{1,2})(?![\d/:]))?")
LINE_BREAKS = ("\r", "\n", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", " ", " ")
RELATIVE = ("来週", "今週", "明日", "あした", "今日", "近日", "後日")
SCOPE_MIN_LEN = 3  # これより短い ID は、行の中の別の語に当たりやすいので照らさない


class ApplyError(Exception):
    pass


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


def ppm_files():
    return load_sibling("ppm", "ppm_files.py", "ppm_files")


def list_inflight():
    return load_sibling("ppm-inflight", "list_inflight.py", "ppm_list_inflight")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def item_key(body: str) -> str:
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:8]


# --- 待ちの節を読む ------------------------------------------------------------------

def _plain_newlines(text: str) -> bool:
    """改行が \\n（と \\r\\n）だけか。ほかの改行の文字があると行の番号がずれるので、書き換えを断る。"""
    return [l.rstrip("\r") for l in text.split("\n")] == [l.rstrip("\r") for l in text.splitlines()] + (
        [""] if text.endswith("\n") else [])


def parse_waiting(text: str, cfg: dict) -> list[dict]:
    """待ちの節の行（ppm_files の読み方）。各行に key・start・end（0 始まり、end は含まない）を足す。"""
    pf = ppm_files()
    if not cfg["todo"]["waiting_section"]:
        return []
    entries = pf.parse_todo(text, cfg)["waiting"]
    lines = text.split("\n")
    seen: dict = {}
    out = []
    for e in entries:
        start = e["line"] - 1
        end = start + 1 + len(e["lines"])
        n = seen.get(e["text"], 0)
        seen[e["text"]] = n + 1
        key = item_key(e["text"] if n == 0 else f"{e['text']}\x00{n}")  # 同じ本文の行も別の key
        crlf = start < len(lines) and lines[start].endswith("\r")
        out.append({"key": key, "body": e["text"], "start": start, "end": end, "crlf": crlf,
                    "lines": lines[start:end]})
    return out


# --- 日付と案件 --------------------------------------------------------------------

def find_dates(body: str, today: date) -> list[date]:
    plain = LINK_RE.sub(" ", body)
    out = []
    for m in DATE_RE.finditer(plain):
        month, day = int(m.group(1)), int(m.group(2))
        d = _place(month, day, today)
        if d is None:
            continue
        out.append(d)
        if m.group(4):  # 「10/24〜26」「11/13〜11/14」の終わりの日
            end = _place(int(m.group(3) or month), int(m.group(4)), today)
            if end is not None:
                out.append(end if end >= d else _place_after(end, d))
    return out


def _place(month: int, day: int, today: date) -> date | None:
    """年の無い M/D を、今日から前後半年の内に入る年に置く。"""
    try:
        d = date(today.year, month, day)
    except ValueError:
        return None
    try:
        if d - today > timedelta(days=183):
            d = date(today.year - 1, month, day)
        elif today - d > timedelta(days=183):
            d = date(today.year + 1, month, day)
    except ValueError:  # 2/29 を閏年でない年に移すとき。今年のまま
        pass
    return d


def _place_after(end: date, start: date) -> date:
    try:
        return date(start.year + 1, end.month, end.day)
    except ValueError:
        return end


def known_scopes(root: Path, db_path=None, today: date | None = None) -> tuple[dict, bool]:
    """scope_id → (status, 出どころ)。Layer の intent が正。Layer に無い ID だけ Registry（読み取り専用）から足す。
    返り値の2つ目は Registry を読めたか（DB が無いときは True＝確かめる物が無い）。"""
    out = {sid: (r["status"], "案件の intent") for sid, r in list_inflight().layer_index(root, today).items()}
    ok = True
    if db_path and Path(db_path).is_file():
        try:
            con = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
            con.execute("PRAGMA query_only=1")
            try:
                for sid, st in con.execute("SELECT scope_id, status FROM projects").fetchall():
                    if sid and sid not in out:
                        out[str(sid)] = (str(st or "").lower(), "Registry の写し")
            finally:
                con.close()
        except sqlite3.Error:
            ok = False
    return out, ok


def matchable_scope(sid: str) -> bool:
    """行の中で照らしてよい案件 ID か。短すぎるもの・文字を含まないもの（数字と記号だけ）は、
    日付や番号の一部に当たって誤って「解消した」と分けるので照らさない。"""
    return len(sid) >= SCOPE_MIN_LEN and re.search(r"[^\W\d_]", sid) is not None


def scopes_in(body: str, known: dict) -> list[str]:
    """行に書かれた既知の案件 ID。前後が英数字・「_」「-」「/」「.」でない所（語の境界）だけを当てる。
    ID の形は決め打ちしない。"""
    plain = LINK_RE.sub(" ", body)
    found = []
    for sid in known:
        if not matchable_scope(sid):
            continue
        if re.search(rf"(?<![0-9A-Za-z_\-/.]){re.escape(sid)}(?![0-9A-Za-z_\-/]|\.[0-9A-Za-z])", plain):
            found.append(sid)
    return sorted(found)


def classify(item: dict, today: date, known: dict) -> dict:
    body = item["body"]
    scopes = scopes_in(body, known)
    dates = find_dates(body, today)
    relative = [w for w in RELATIVE if w in body]
    if scopes and all(known[s][0] in CLOSED for s in scopes):
        kind, action = "resolved", "delete"
        reason = "書かれている案件がもう閉じている（" + "、".join(f"{s} は {known[s][0]}（{known[s][1]}）" for s in scopes) + "）"
    elif dates and not relative and max(dates) < today:
        kind, action = "past", "delete"
        reason = f"書かれている日付（{'・'.join(f'{d.month}/{d.day}' for d in dates)}）がどれも過ぎた"
    else:
        kind, action = "unknown", "ask"
        if relative:
            reason = f"「{relative[0]}」のように日付がはっきりしない"
        elif dates:
            reason = "これから先の日付がある"
        else:
            reason = "日付も、閉じた案件も書かれていない"
    return {"key": item["key"], "body": body, "kind": kind, "reason": reason, "action": action,
            "dates": [d.isoformat() for d in dates], "scopes": scopes}


def review(text: str, cfg: dict, root: Path, today: date, db_path=None) -> dict:
    items = parse_waiting(text, cfg)
    known, ok = known_scopes(root, db_path, today) if items else ({}, True)
    return {"todo_sha256": sha256(text), "today": today.isoformat(), "registry_ok": ok,
            "enabled": bool(cfg["todo"]["waiting_section"]), "section": cfg["todo"]["waiting_section"],
            "items": [classify(it, today, known) for it in items]}


KIND_TEXT = {"past": "日付が過ぎた", "resolved": "解消したと分かる", "unknown": "判断できない（あなたに聞く）"}
ACTION_TEXT = {"delete": "消す案（残っていることがあれば書き直す）", "ask": "残すか・書き直すか・消すかをあなたが決める"}


def _short(body: str, n: int = 60) -> str:
    plain = LINK_RE.sub("", body).strip()
    return plain if len(plain) <= n else plain[:n] + "…"


def format_review(r: dict) -> str:
    if not r["enabled"]:
        return "待ちの節は使わない設定（ppm.todo.waiting_section: null）なので、見直しはしない。\n"
    items = r["items"]
    lines = [f"## {r['section']}の見直し（TODO の一覧はまだ書き換えていない）", ""]
    if not items:
        return "\n".join(lines + [f"{r['section']}に行は無い。", ""])
    c = {k: sum(1 for i in items if i["kind"] == k) for k in KIND_TEXT}
    lines.append(f"{len(items)}行のうち、日付が過ぎた {c['past']}行・解消したと分かる {c['resolved']}行・"
                 f"判断できない {c['unknown']}行。根拠は行に書かれた案件の状態だけで、予定表・メールは見ていない。")
    if not r.get("registry_ok", True):
        lines.append("（Registry を読めなかったため、Layer の無い案件が閉じたかは確かめていない）")
    lines.append("")
    for n, it in enumerate(items, 1):
        lines += [f"{n}. {_short(it['body'])}", f"   - {KIND_TEXT[it['kind']]}：{it['reason']}",
                  f"   - 案：{ACTION_TEXT[it['action']]}（key {it['key']}）"]
    lines.append("")
    return "\n".join(lines)


# --- 承認した行だけを書き換える -----------------------------------------------------------

def check_approval_shape(approval) -> list[dict]:
    """承認ファイルの形を確かめ、items を返す。形が違えば、どこが違うかを書いた ApplyError。"""
    form = '{"todo_sha256": "...", "items": [{"key": "...", "action": "delete" | "rewrite", "text": "..."}]}'
    if not isinstance(approval, dict):
        raise ApplyError(f"承認ファイルの形が違う：全体は {form} の形（今は {type(approval).__name__}）")
    if not isinstance(approval.get("todo_sha256"), str):
        raise ApplyError("承認ファイルの形が違う：todo_sha256（案を出したときの値）が文字列で要る")
    items = approval.get("items")
    if not isinstance(items, list) or not items:
        raise ApplyError("承認ファイルの items が空か、一覧になっていない")
    for n, a in enumerate(items, 1):
        if not isinstance(a, dict):
            raise ApplyError(f"承認ファイルの形が違う：items の {n}件目が {{\"key\": …, \"action\": …}} の形でない")
        if not isinstance(a.get("key"), str) or not isinstance(a.get("action"), str):
            raise ApplyError(f"承認ファイルの形が違う：items の {n}件目の key と action は文字列で要る")
        if "text" in a and a["text"] is not None and not isinstance(a["text"], str):
            raise ApplyError(f"承認ファイルの形が違う：items の {n}件目の text は文字列で要る")
    return items


def apply(text: str, approval, cfg: dict) -> tuple[str, list[str]]:
    """承認した行だけを書き換えた全文と、変えた内容の説明。約束に合わなければ ApplyError。"""
    if not cfg["todo"]["waiting_section"]:
        raise ApplyError("待ちの節は使わない設定になっている")
    approved = check_approval_shape(approval)
    if approval["todo_sha256"] != sha256(text):
        raise ApplyError("TODO の一覧が案を出したときから変わっている。案を出し直す")
    if not _plain_newlines(text):
        raise ApplyError("TODO の一覧に \\n 以外の改行の文字がある。行の位置がずれるので書き換えない（手で直す）")
    items = {it["key"]: it for it in parse_waiting(text, cfg)}
    lines = text.split("\n")
    edits: dict[int, tuple[int, list[str]]] = {}
    notes, seen = [], set()
    for a in approved:
        key, action = a["key"], a["action"]
        if key in seen:
            raise ApplyError(f"key {key} が承認ファイルに2回ある")
        seen.add(key)
        if key not in items:
            raise ApplyError(f"key {key} の行が待ちの節に無い")
        it = items[key]
        if lines[it["start"]].rstrip("\r")[2:].strip() != it["body"] or not lines[it["start"]].startswith("- "):
            raise ApplyError(f"key {key} の行の位置が読めない。書き換えない")
        extra = len(it["lines"]) - 1
        tail = f"（続きの字下げ行 {extra}行も消える）" if extra else ""
        if action == "delete":
            edits[it["start"]] = (it["end"], [])
            notes.append(f"消す: {_short(it['body'])}{tail}")
        elif action == "rewrite":
            new = (a.get("text") or "").strip()
            if not new or any(ch in new for ch in LINE_BREAKS) or new.splitlines() != [new]:
                raise ApplyError(f"key {key} の新しい本文は1行で、空にしない（改行の文字を入れない）")
            edits[it["start"]] = (it["end"], [f"- {new}" + ("\r" if it["crlf"] else "")])
            notes.append(f"書き直す: {_short(it['body'])} → {_short(new)}{tail}")
        else:
            raise ApplyError(f"key {key} の action は delete か rewrite")
    out, kept, i = [], [], 0
    while i < len(lines):
        if i in edits:
            end, repl = edits[i]
            out.extend(repl)
            i = end
        else:
            out.append(lines[i])
            kept.append(len(out) - 1)
            i += 1
    new_text = "\n".join(out)
    _verify(lines, out, kept, edits)
    _verify_reparse(new_text, items, edits, cfg)
    return new_text, notes


def _verify(old: list[str], new: list[str], kept: list[int], edits: dict) -> None:
    """承認していない行が同じ順で1文字も変わっていないこと。"""
    touched = {n for start, (end, _) in edits.items() for n in range(start, end)}
    if [new[k] for k in kept] != [l for n, l in enumerate(old) if n not in touched]:
        raise ApplyError("承認していない行が変わった。保存しない")


def _verify_reparse(new_text: str, items: dict, edits: dict, cfg: dict) -> None:
    """書いた後の全文を読み直して、待ちの行が承認どおりで、見出しが残っていること。"""
    pf = ppm_files()
    parsed = pf.parse_todo(new_text, cfg)
    if not any(s["kind"] == "waiting" for s in parsed["sections"]):
        raise ApplyError("待ちの節の見出しが無くなった。保存しない")
    expected = []
    for it in sorted(items.values(), key=lambda x: x["start"]):
        if it["start"] in edits:
            expected += [r[2:].rstrip("\r").strip() for r in edits[it["start"]][1]]
        else:
            expected.append(it["body"])
    if [e["text"] for e in parsed["waiting"]] != expected:
        raise ApplyError("読み直した待ちの行が承認と合わない。保存しない")


def _read(path: Path) -> str:
    try:
        with open(path, encoding="utf-8", newline="") as f:  # 改行を変換しない
            return f.read()
    except UnicodeDecodeError:
        raise ApplyError("TODO の一覧が UTF-8 で読めない。文字コードを UTF-8 に直してから使う") from None


def _repo_dirs(root: Path) -> list[Path]:
    return [Path(os.path.abspath(root)), Path(root).resolve()]


def write_target(path: Path, root: Path) -> Path:
    """書き換える実体のパス。リンクなら解いた先。実体がリポジトリの外なら ApplyError。
    （設定の ppm.todo.path は ppm_files がリポジトリの中の相対パスしか認めないので、外に出るのはリンクのときだけ）"""
    real = path.resolve(strict=True)
    if not any(real.is_relative_to(r) for r in _repo_dirs(root)):
        raise ApplyError("TODO の一覧はリポジトリの外を指すリンクになっている。書かない"
                         "（TODO の一覧はリポジトリの中の実体に置く。外の実体には書かない）")
    if not real.is_file():
        raise ApplyError("TODO の一覧の実体が普通のファイルでない。書かない")
    return real


def _write_atomic(path: Path, text: str, root: Path) -> Path:
    """実体と同じフォルダに一時ファイルを作り、元の権限を付けてから置き換える。置き換えた実体のパスを返す。"""
    real = write_target(path, root)
    mode = stat.S_IMODE(os.stat(real).st_mode)
    tmp = real.with_name(f".{real.name}.tmp-{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # 書いている間は本人だけが読める
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fchmod(f.fileno(), mode)
            os.fsync(f.fileno())
        os.replace(tmp, real)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return real


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TODO の一覧の待ちの節を見直す（--apply --write のときだけ書く）")
    ap.add_argument("--root", default=None)
    ap.add_argument("--db", default=None, help="Registry（Layer の無い案件の状態を引くときだけ。読み取り専用）")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD（試験用）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--apply", default=None, help="承認ファイル（JSON）")
    ap.add_argument("--write", action="store_true", help="--apply と一緒に使い、承認した行だけを書き換えて保存する")
    a = ap.parse_args(argv)
    if a.write and not a.apply:
        print("[ERROR] --write は --apply と一緒に使う", file=sys.stderr)
        return 2
    try:
        pf = ppm_files()
        root, cfg = pf.context(a.root)
        today = date.fromisoformat(a.today) if a.today else date.today()
    except (ImportError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    todo = pf.todo_path(root, cfg)
    if not todo.is_file():
        print(f"TODO の一覧がありません: {todo}", file=sys.stderr)
        return 1
    try:
        text = _read(todo)
    except ApplyError as exc:
        print(f"[HOLD] {exc}", file=sys.stderr)
        return 2
    if a.apply:
        appr = Path(a.apply)
        if any(p.is_relative_to(r) for p in (Path(os.path.abspath(appr)), appr.resolve()) for r in _repo_dirs(root)):
            print("[HOLD] 承認ファイルがリポジトリの中にある。リポジトリの外（作業用の一時フォルダなど）に置き直す",
                  file=sys.stderr)
            return 2
        try:
            approval = json.loads(appr.read_text(encoding="utf-8"))
            new_text, notes = apply(text, approval, cfg)
        except RecursionError:
            print("[HOLD] 承認ファイルの入れ子が深すぎて読めない。決まった形で書き直す", file=sys.stderr)
            return 2
        except (ApplyError, ValueError, OSError) as exc:  # UnicodeDecodeError・JSON の誤りも ValueError の仲間
            print(f"[HOLD] {exc}", file=sys.stderr)
            return 2
        for n in notes:
            print(n)
        if not a.write:
            print("（予定を見せただけ。保存するには --write を付ける）")
            return 0
        try:
            if _read(todo) != text:
                print("[HOLD] 書き換えの途中で TODO の一覧が変わった。保存しない", file=sys.stderr)
                return 2
            _write_atomic(todo, new_text, root)
            back = _read(todo)
        except (ApplyError, OSError) as exc:
            print(f"[HOLD] {exc}", file=sys.stderr)
            return 2
        if back != new_text:
            print("[HOLD] 読み戻した中身が違う", file=sys.stderr)
            return 2
        print(f"保存した: {todo}（待ちの行 {len(parse_waiting(back, cfg))}件）")
        return 0
    db = a.db
    if db is None:
        db = load_sibling("ppm-todo", "inflight_programs.py", "ppm_inflight_programs").default_db(root)
    r = review(text, cfg, root, today, db)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(format_review(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
