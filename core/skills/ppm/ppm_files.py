#!/usr/bin/env python3
"""日次の入口（ppm-plan・ppm-status・ppm-todo・ppm-capture・ppm-update・ppm-close）が共通で使う、設定とファイルを読む部品。

読むだけで、ファイルを書き換える関数は持たない（書く側は各スキルが承認の手順と一緒に持つ）。
標準ライブラリと PyYAML（設定ファイルがあるときだけ）を使う。

設定: リポジトリのルートの `.ai-plc/config.yaml` の `ppm:` の節。書かなかったキーは既定値で埋める
（ファイルや節が無ければ全部既定値）。既定値は DEFAULTS を見る。

設定の値の扱い（決まり）:
- 型が違う値（例: 文字列のはずの所に数、一覧のはずの所に文字列）は PpmConfigError で止める。
  黙って既定に戻すと、見出しを替えたつもりの設定が効かないまま件数がずれるため。
- `ppm:` が mapping でない、YAML が壊れている、設定ファイルがあるのに PyYAML が無い、も PpmConfigError。
- 知らないキーは無視し、警告を1行出す（load_config の warn。既定は標準エラー）。

ルートの見つけ方（ppm-collection/collect.py と同じ）:
- 導入先（<repo>/.claude/skills/ppm/ または <repo>/.cursor/skills/ppm/）に置かれていれば、そのリポジトリ
- そうでなければ今のフォルダ。どちらも引数 root で替えられる

パスの決まり（スキルはこのパスに書き込むため）:
- todo.path・first_task.path・daily_task.path・day_dir は、リポジトリのルートからの相対パスだけ。
  絶対パス・`~` で始まるもの・解決するとルートの外に出るもの（`../x` など）は PpmConfigError。
  `a/../b` のように途中に `..` があっても、解決した先がルートの中なら通す。
  `.git`・`.claude`・`.ai-plc` のフォルダの中（パスのどの段でも）を指すものも PpmConfigError。
  判定は字面（os.path.normpath）で行い、シンボリックリンクはたどらない（中のリンクが外を指していても止めない）。
- will_do.file・task_diary.file はファイル名だけ（`/`・`\\` を含まない。`.`・`..` でない）。
- 雛形の場所（templates_dir・will_do.template・task_diary.template）は読むだけなので、外を指してよい（`~` も展開する）。

WillDo・日記の行の扱いの印（/ppm-close が付ける。チェックは `[ ]` のまま＝完了ではない）:
  `- [ ] 題名 :60 → 繰り越し`・`→ 繰り越し: <書き直した行 :30>`・`→ TODO へ`・`→ やめた`
  読むと item に disposition（carryover・to_todo・dropped・None）と carry_title・carry_estimate_min が付き、
  title・estimate_min からは印を外す。/ppm-plan は carry_candidates で翌日の候補を集める。

見出しの照合（決まり）:
- 節（`## `）・小区分（`### `）の名前は、見出しの文字が設定の名前と同じか、名前のすぐ後に
  「（」「(」・空白・「:」「：」が続くときに当たる（例: 名前「未再計画」は「## 未再計画（旧案件）」に当たる）。
- 終わりの印（end_marker）は、`## ` の見出しの文字がその語で始まれば当たる。それより後の節は進行中として読まない
  （待ちの節・雑務の節は、終わりの印の前後に関係なく読む）。
- HTML コメントの中（`<!--` から `-->` まで）とコードブロック（```）の中の行は、案件の行として読まない。
  ただし案件の行の直下の字下げした1行のコメント（`<!-- layer: … -->` など）は注記として読む。

使い方（読み取りだけ）:
  python3 ppm_files.py config [--root <repo>]
  python3 ppm_files.py paths [--date YYYY-MM-DD] [--root <repo>]
  python3 ppm_files.py todo [--json] [--root <repo>]
  python3 ppm_files.py first [--root <repo>]
  python3 ppm_files.py daily [--date YYYY-MM-DD] [--root <repo>]
  python3 ppm_files.py willdo [--date YYYY-MM-DD] [--root <repo>]
  python3 ppm_files.py diary [--date YYYY-MM-DD] [--root <repo>]
  python3 ppm_files.py carry --date <対象日> [--with-target-urgent] [--root <repo>]
  （todo の JSON でない出力は、私生活の節の行の Layer のパスを出さない。出すときは --show-private）
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
CONFIG_REL = Path(".ai-plc") / "config.yaml"
BUNDLED_TEMPLATES = HERE / "templates"
TEMPLATE_NAMES = ("todo", "first_task", "daily_task", "will_do", "task_diary")
# 書く先に使えないフォルダの名前（パスのどの段にあっても断る）
RESERVED_DIRS = (".git", ".claude", ".ai-plc")

DEFAULTS: dict = {
    "todo": {
        "path": "todo/todo.md",
        "inflight_sections": ["進行中の仕事", "進行中の私生活"],
        "work_subgroups": ["主軸", "支援課題"],
        "private_sections": ["進行中の私生活"],
        "waiting_section": "待ち／要確認",
        "misc_section": "いつでもいい雑務",
        "end_marker": "未再計画",
    },
    "first_task": {"path": "todo/first_task.md", "heading": "⭐ 現在のFirst Task"},
    "daily_task": {"path": "todo/daily_task.md"},
    "day_dir": "Flow/{YYYYMM}/{YYYY-MM-DD}",
    "templates_dir": "todo/templates",
    "will_do": {"file": "will_do.md", "template": None},
    "task_diary": {"file": "task_diary.md", "template": None},
    "plan": {"capacity_hours": 6, "max_items": 10, "overflow_rule": "tomorrow_diary", "lookback_days": 14},
    "capture": {"urgent_criteria": "今日やらないと実害（他者ブロック・締切超過・信頼毀損）が出るか"},
    "owner_words": ["本人", "user", "human"],
    "sources": {"calendar": "auto", "mail": "off"},
    "inflight": {"recent_days": 21},
}

OVERFLOW_RULES = ("tomorrow_diary",)
SOURCE_MODES = ("auto", "off")

# キー → 型の決まり。str / opt_str（文字列か null）/ list_str / pos_num / pos_int / enum:<値,...>
SCHEMA: dict = {
    "todo": {
        "path": "str", "inflight_sections": "list_str_nonempty", "work_subgroups": "list_str",
        "private_sections": "list_str", "waiting_section": "opt_str", "misc_section": "opt_str",
        "end_marker": "opt_str",
    },
    "first_task": {"path": "str", "heading": "str"},
    "daily_task": {"path": "str"},
    "day_dir": "str",
    "templates_dir": "str",
    "will_do": {"file": "filename", "template": "opt_str"},
    "task_diary": {"file": "filename", "template": "opt_str"},
    "plan": {"capacity_hours": "pos_num", "max_items": "pos_int", "overflow_rule": "enum_overflow",
             "lookback_days": "pos_int"},
    "capture": {"urgent_criteria": "str"},
    "owner_words": "list_str",
    "sources": {"calendar": "enum_source", "mail": "enum_source"},
    "inflight": {"recent_days": "pos_int"},
}

# WillDo の5つの欄（名前ごとそのまま。設定では替えない）
WILLDO_SECTIONS = (
    ("first", "First Task"),
    ("inserted", "差し込み"),
    ("carryover", "繰り越し"),
    ("from_todo", "TODOから"),
    ("daily", "Daily Task"),
)
RETRO_HEADING = "振り返り"
RETRO_SUBSECTIONS = ("FUN", "DONE", "DONE（WillDo外）", "LEARN")
DIARY_SECTIONS = (("scheduled", "予定タスク"), ("urgent", "緊急"))
# 未完了の行の扱いの印（キー, 書く文字）。行の末尾に ` → <文字>`（繰り越しは `: <書き直した行>` を続けてよい）
DISPOSITIONS = (("carryover", "繰り越し"), ("to_todo", "TODO へ"), ("dropped", "やめた"))
DISPOSITION_RE = re.compile(r"^(.*?)\s*→\s*(繰り越し|TODO\s*へ|やめた)(?:\s*[:：]\s*(.*?))?\s*$")

WEEKDAYS = "月火水木金土日"  # date.weekday() の 0〜6

ITEM_RE = re.compile(r"^- \[([ xX])\]\s+(.*?)\s*$")
PLAIN_ITEM_RE = re.compile(r"^- (?!\[[ xX]\])(.*?)\s*$")
LAYER_RE = re.compile(r"<!--\s*layer:\s*(.+?)(?:\s+scope:\s*(\S+?))?\s*-->")
SOURCE_RE = re.compile(r"<!--\s*source:\s*(.+?)(?:\s+candidate:\s*(\S+?))?\s*-->")
NOTE_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b")
ESTIMATE_RE = re.compile(r"(?:(?<=\s)|^):(\d{1,4})(?=\s|$|（|\()")
REASON_RE = re.compile(r"[（(]\s*理由\s*[:：]\s*(.*?)\s*[）)]")
DAILY_TAG_RE = re.compile(r"\s*\[(daily|weekly:[月火水木金土日]+|monthly:\d{1,2})\]\s*$")
H1_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")


class PpmConfigError(ValueError):
    """設定の形・型が違う（キーの名前と、期待する型を文に含める）。"""


# --- ルートと設定 --------------------------------------------------------------

def find_root(start=None) -> Path:
    """導入先（<repo>/.claude/skills/ppm/ か .cursor/...）ならそのリポジトリ、そうでなければ今のフォルダ。
    start を渡せばそれを使う。"""
    if start is not None:
        return Path(start).expanduser().resolve()
    if HERE.parents[0].name == "skills" and HERE.parents[1].name in (".claude", ".cursor"):
        return HERE.parents[2]
    return Path.cwd().resolve()


def default_config() -> dict:
    """既定値の写し（書き換えても DEFAULTS は変わらない）。"""
    return copy.deepcopy(DEFAULTS)


def _warn_stderr(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def _check(key: str, kind: str, value):
    """値を型の決まりで確かめて返す（list_str は写しを返す）。違えば PpmConfigError。"""
    def bad(expect: str):
        return PpmConfigError(f"ppm.{key} は {expect} にしてください（今の値: {value!r}）")

    if kind == "str":
        if not isinstance(value, str) or not value.strip():
            raise bad("空でない文字列")
        return value
    if kind == "opt_str":
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise bad("空でない文字列か null")
        return value
    if kind in ("list_str", "list_str_nonempty"):
        if value is None and kind == "list_str":
            return []
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            raise bad("文字列の一覧（例: [\"進行中の仕事\"]）")
        if kind == "list_str_nonempty" and not value:
            raise bad("1つ以上の文字列の一覧")
        return list(value)
    if kind == "pos_num":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise bad("正の数")
        return value
    if kind == "pos_int":
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise bad("正の整数")
        return value
    if kind == "filename":
        if (not isinstance(value, str) or not value.strip() or "/" in value or "\\" in value
                or value.strip() in (".", "..")):
            raise bad("ファイル名だけ（区切りの / を含まない）")
        if value.strip().lower() in RESERVED_DIRS:
            raise bad("`.git`・`.claude`・`.ai-plc` 以外のファイル名")
        return value
    if kind == "enum_overflow":
        if value not in OVERFLOW_RULES:
            raise bad(" / ".join(OVERFLOW_RULES) + " のどれか")
        return value
    if kind == "enum_source":
        if value not in SOURCE_MODES:
            raise bad(" / ".join(SOURCE_MODES) + " のどれか")
        return value
    raise AssertionError(kind)


def _merge(base: dict, schema: dict, given: dict, prefix: str, warn) -> None:
    for k, v in given.items():
        key = f"{prefix}{k}"
        if k not in schema:
            warn(f".ai-plc/config.yaml: ppm.{key} は知らないキーなので無視します")
            continue
        kind = schema[k]
        if isinstance(kind, dict):
            if v is None:
                continue
            if not isinstance(v, dict):
                raise PpmConfigError(f"ppm.{key} は mapping にしてください（今の値: {v!r}）")
            _merge(base[k], kind, v, f"{key}.", warn)
        else:
            base[k] = _check(key, kind, v)


def load_config(root=None, warn=None) -> dict:
    """`<root>/.ai-plc/config.yaml` の `ppm:` を読み、既定値で埋めた dict を返す。
    ファイル・節が無ければ default_config()。型が違えば PpmConfigError。"""
    warn = warn or _warn_stderr
    root = find_root(root)
    cfg = default_config()
    path = root / CONFIG_REL
    if not path.is_file():
        return cfg
    try:
        import yaml
    except ImportError as exc:
        raise PpmConfigError(f"{path} を読むには PyYAML が要ります（pip install pyyaml）") from exc
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # 壊れた YAML
        raise PpmConfigError(f"{path} を YAML として読めません: {exc}") from exc
    if not isinstance(data, dict):
        raise PpmConfigError(f"{path} の一番上は mapping にしてください")
    given = data.get("ppm")
    if given is None:
        return cfg
    if not isinstance(given, dict):
        raise PpmConfigError(f"{path}: ppm は mapping にしてください（今の値: {given!r}）")
    _merge(cfg, SCHEMA, given, "", warn)
    for key, value in (("todo.path", cfg["todo"]["path"]), ("first_task.path", cfg["first_task"]["path"]),
                       ("daily_task.path", cfg["daily_task"]["path"]), ("day_dir", cfg["day_dir"])):
        check_inside_path(value, key)
    return cfg


def context(root=None, warn=None) -> tuple[Path, dict]:
    """(ルート, 設定) をまとめて返す（各スキルの入口用）。"""
    r = find_root(root)
    return r, load_config(r, warn)


# --- パス ---------------------------------------------------------------------

def _as_date(day) -> date:
    if isinstance(day, datetime):
        return day.date()
    if isinstance(day, date):
        return day
    if isinstance(day, str):
        try:
            return date.fromisoformat(day.strip())
        except ValueError as exc:
            raise ValueError(f"日付は YYYY-MM-DD で渡してください: {day!r}") from exc
    raise TypeError(f"日付は date か 'YYYY-MM-DD' で渡してください: {day!r}")


def check_inside_path(rel: str, key: str = "path") -> str:
    """書き込みに使う設定のパスが、ルートの中を指す相対パスかを字面で確かめる（違えば PpmConfigError）。
    絶対パス・`~` で始まるもの・ドライブ名つき・解決するとルートの外に出るもの（`..` で上がり切る）、
    `.git`・`.claude`・`.ai-plc` のフォルダの中を指すもの（RESERVED_DIRS）を断る。
    途中の `..` で上がっても中に収まれば通す。シンボリックリンクはたどらない（中のリンクが外を指していても止めない）。"""
    s = str(rel).strip()
    if (s.startswith("~") or s.startswith(("/", "\\")) or Path(s).is_absolute()
            or re.match(r"^[A-Za-z]:", s)):
        raise PpmConfigError(f"ppm.{key} はリポジトリのルートからの相対パスにしてください（今の値: {rel!r}）")
    norm = os.path.normpath(s.replace("\\", "/"))
    if norm == ".." or norm.startswith("../"):
        raise PpmConfigError(f"ppm.{key} がリポジトリの外を指しています（今の値: {rel!r}）")
    hit = [part for part in norm.split("/") if part.lower() in RESERVED_DIRS]
    if hit:
        raise PpmConfigError(f"ppm.{key} は {hit[0]}/ の中を指せません（git・道具の設定の置き場のため。今の値: {rel!r}）")
    return s


def resolve_path(root, rel: str, allow_outside: bool = False, key: str = "path") -> Path:
    """設定のパスをルートからのパスにする。
    既定（書き込みに使うパス）は check_inside_path を通し、外を指せば PpmConfigError。
    allow_outside=True（読むだけの雛形の場所）は、`~` を展開し、絶対パスや外もそのまま使う。"""
    if allow_outside:
        p = Path(rel).expanduser()
        return p if p.is_absolute() else Path(root) / p
    return Path(root) / check_inside_path(rel, key)


def todo_path(root, cfg) -> Path:
    return resolve_path(root, cfg["todo"]["path"], key="todo.path")


def first_task_path(root, cfg) -> Path:
    return resolve_path(root, cfg["first_task"]["path"], key="first_task.path")


def daily_task_path(root, cfg) -> Path:
    return resolve_path(root, cfg["daily_task"]["path"], key="daily_task.path")


def _day_file(root, cfg, day, name: str) -> Path:
    fname = _check(f"{name}.file", "filename", cfg[name]["file"])
    return day_dir(root, cfg, day) / fname


def day_dir(root, cfg, day) -> Path:
    """日のフォルダ。day_dir の {YYYYMM}・{YYYY-MM-DD}・{YYYY}・{MM}・{DD} を埋める。
    ほかの {…} が残れば PpmConfigError。"""
    d = _as_date(day)
    s = cfg["day_dir"]
    for k, v in (("{YYYYMM}", d.strftime("%Y%m")), ("{YYYY-MM-DD}", d.isoformat()),
                 ("{YYYY}", d.strftime("%Y")), ("{MM}", d.strftime("%m")), ("{DD}", d.strftime("%d"))):
        s = s.replace(k, v)
    left = PLACEHOLDER_RE.findall(s)
    if left:
        raise PpmConfigError(f"ppm.day_dir に知らない置き換え {left} があります"
                             "（使えるのは {YYYYMM}・{YYYY-MM-DD}・{YYYY}・{MM}・{DD}）")
    return resolve_path(root, s, key="day_dir")


def will_do_path(root, cfg, day) -> Path:
    return _day_file(root, cfg, day, "will_do")


def task_diary_path(root, cfg, day) -> Path:
    return _day_file(root, cfg, day, "task_diary")


def template_path(root, cfg, name: str) -> Path:
    """雛形の場所。順に: ①will_do・task_diary は設定の template（書いてあって無ければ PpmConfigError）
    ②プロジェクトの <templates_dir>/<name>_template.md ③このスキルに同梱の templates/<name>_template.md。
    雛形は読むだけなので、リポジトリの外（`~` を含む）を指してもよい。"""
    if name not in TEMPLATE_NAMES:
        raise ValueError(f"雛形の名前は {TEMPLATE_NAMES} のどれか: {name!r}")
    explicit = cfg.get(name, {}).get("template") if name in ("will_do", "task_diary") else None
    if explicit:
        p = resolve_path(root, explicit, allow_outside=True)
        if not p.is_file():
            raise PpmConfigError(f"ppm.{name}.template の雛形が見つかりません: {p}")
        return p
    project = resolve_path(root, cfg["templates_dir"], allow_outside=True) / f"{name}_template.md"
    if project.is_file():
        return project
    return BUNDLED_TEMPLATES / f"{name}_template.md"


def load_template(root, cfg, name: str, day=None) -> str:
    """雛形の本文。day を渡せば {{YYYY-MM-DD}} をその日に置き換える（ファイルは書かない）。"""
    text = template_path(root, cfg, name).read_text(encoding="utf-8")
    if day is not None:
        text = text.replace("{{YYYY-MM-DD}}", _as_date(day).isoformat())
    return text


def paths(root, cfg, day=None) -> dict:
    """主なパスの一覧（存在するかも添える）。"""
    d = _as_date(day) if day is not None else date.today()
    out = {
        "root": Path(root),
        "todo": todo_path(root, cfg),
        "first_task": first_task_path(root, cfg),
        "daily_task": daily_task_path(root, cfg),
        "day_dir": day_dir(root, cfg, d),
        "will_do": will_do_path(root, cfg, d),
        "task_diary": task_diary_path(root, cfg, d),
    }
    res = {k: {"path": str(v), "exists": v.exists()} for k, v in out.items()}
    res["date"] = d.isoformat()
    res["templates"] = {n: str(template_path(root, cfg, n)) for n in TEMPLATE_NAMES}
    return res


# --- 行の読み方（共通） -----------------------------------------------------------

def _read(path) -> str | None:
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.is_file() else None


def _lines(text: str):
    """(行番号 1 始まり, 行, 読む対象か) を返す。コードブロックと複数行の HTML コメントの中、
    行の頭（字下げなし）から始まる1行の HTML コメントは「読む対象でない」。"""
    in_comment = False
    in_fence = False
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r")
        s = line.strip()
        if in_fence:
            if s.startswith("```"):
                in_fence = False
            yield i, line, False
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
            yield i, line, False
            continue
        if s.startswith("```"):
            in_fence = True
            yield i, line, False
            continue
        if s.startswith("<!--"):
            if "-->" not in s[4:]:
                in_comment = True
                yield i, line, False
                continue
            # 1行のコメント: 字下げがあれば注記として読む側に渡す
            yield i, line, line[:1] in (" ", "\t")
            continue
        yield i, line, True


def _heading(line: str):
    """(深さ, 文字) か None。"""
    m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
    return (len(m.group(1)), m.group(2).strip()) if m else None


def heading_matches(text: str, name: str | None) -> bool:
    """見出しの文字が名前に当たるか（同じ、または名前の後に「（」「(」・空白・コロンが続く）。"""
    if not name:
        return False
    text, name = text.strip(), name.strip()
    if text == name:
        return True
    return text.startswith(name) and text[len(name)] in "（( 　:：\t"


def split_estimate(text: str) -> tuple[str, int | None]:
    """行の文から見積の分（空白の後の `:60`）を取り出す。返り値は (見積を外した文, 分 or None)。
    複数あれば最後のもの。「10:30」のような時刻（直前が空白でない）は見積とみなさない。"""
    matches = list(ESTIMATE_RE.finditer(text))
    if not matches:
        return text.strip(), None
    m = matches[-1]
    before, after = text[:m.start()].rstrip(), text[m.end():].strip()
    sep = "" if not after or after.startswith(("（", "(")) else " "
    return (before + sep + after).strip(), int(m.group(1))


def _task(line_no: int, title_raw: str, done: bool) -> dict:
    title, est = split_estimate(title_raw)
    r = REASON_RE.search(title_raw)
    return {"title": title, "raw": title_raw, "done": done, "estimate_min": est,
            "reason": r.group(1) if r else None, "line": line_no}


def _checkbox_items(lines) -> list[dict]:
    """`- [ ] …`・`- [x] …` の行だけ（字下げの無いもの）。"""
    out = []
    for no, line, ok in lines:
        if not ok:
            continue
        m = ITEM_RE.match(line)
        if m:
            out.append(_task(no, m.group(2), m.group(1) != " "))
    return out


# --- TODO の一覧 -----------------------------------------------------------------

def parse_todo(text: str, cfg: dict | None = None) -> dict:
    """TODO の一覧の本文を読む（ファイルは読まない。read_todo を使えばパスから読む）。

    返り値:
      sections: [{"name", "line", "kind": inflight|waiting|misc|other, "after_end": bool,
                  "subgroups": [{"name", "line"}], "items": [item…], "entries": [waiting の行…]}]
      inflight: 進行中の案件の行（下の item）。終わりの印より前の、inflight_sections に当たる節の分だけ。完了の行も含む
      waiting:  待ちの節の行 [{"text", "line", "lines": [続きの行…]}]（waiting_section が null なら []）
      misc:     雑務の節の案件の行（item。misc_section が null なら []）
      has_subgroups: 進行中の節のどれかに `###` の小区分があるか
      end_line: 終わりの印の見出しの行番号（無ければ None）
    item: {"title", "raw", "done", "estimate_min", "reason", "line", "section", "subgroup",
           "group": work|private, "layer", "scope", "source", "candidate", "notes": [{"date", "text", "line"}]}
      subgroup は `###` の名前（小区分が無い所は None）。work_subgroups に無い小区分の名前もそのまま入る
      （known_subgroup が False になる）。
    """
    cfg = cfg or default_config()
    t = cfg["todo"]
    sections: list[dict] = []
    sec = None
    sub = None
    item = None
    after_end = False
    end_line = None
    waiting_cur = None

    for no, line, ok in _lines(text):
        h = _heading(line) if ok else None
        if h and h[0] <= 2:
            item = waiting_cur = None
            sub = None
            if h[0] == 1:
                sec = None
                continue
            name = h[1]
            if t["end_marker"] and name.startswith(t["end_marker"].strip()) and not after_end:
                after_end = True
                end_line = no
            if heading_matches(name, t["waiting_section"]):
                kind = "waiting"
            elif heading_matches(name, t["misc_section"]):
                kind = "misc"
            elif not after_end and any(heading_matches(name, s) for s in t["inflight_sections"]):
                kind = "inflight"
            else:
                kind = "other"
            private = any(heading_matches(name, s) for s in t["private_sections"])
            sec = {"name": name, "line": no, "kind": kind, "after_end": after_end, "private": private,
                   "subgroups": [], "items": [], "entries": []}
            sections.append(sec)
            continue
        if sec is None:
            continue
        if h and h[0] >= 3:
            item = waiting_cur = None
            if h[0] == 3:
                sub = h[1]
                sec["subgroups"].append({"name": sub, "line": no})
            continue

        if sec["kind"] == "waiting":
            if not ok:
                waiting_cur = None
                continue
            if line.startswith("- "):
                waiting_cur = {"text": line[2:].strip(), "line": no, "lines": []}
                sec["entries"].append(waiting_cur)
            elif waiting_cur is not None and line[:1] in (" ", "\t") and line.strip():
                waiting_cur["lines"].append(line.strip())
            else:
                waiting_cur = None
            continue

        m = ITEM_RE.match(line) if ok else None
        if m:
            item = _task(no, m.group(2), m.group(1) != " ")
            known = sub is None or any(heading_matches(sub, g) for g in t["work_subgroups"])
            item.update({"section": sec["name"], "subgroup": sub, "known_subgroup": known,
                         "group": "private" if sec["private"] else "work",
                         "layer": None, "scope": None, "source": None, "candidate": None, "notes": []})
            sec["items"].append(item)
            continue
        if item is None or not ok:
            continue  # 複数行のコメント・コードブロックの中は読まない（行は閉じない）
        if not line.strip():
            continue  # 空行では行を閉じない（注記の前後に空行があってもよい）
        if line[:1] not in (" ", "\t"):
            item = None  # 字下げの無い文・コメントで行が終わる
            continue
        s = line.strip()
        lm = LAYER_RE.search(s)
        sm = SOURCE_RE.search(s)
        if lm or sm:
            if lm and item["layer"] is None:
                item["layer"], item["scope"] = lm.group(1).strip(), lm.group(2)
            if sm and item["source"] is None:
                item["source"], item["candidate"] = sm.group(1).strip(), sm.group(2)
            continue
        if s.startswith("<!--"):
            continue  # ほかの1行のコメントは読まない
        dm = NOTE_DATE_RE.match(s)
        item["notes"].append({"date": dm.group(1) if dm else None, "text": s, "line": no})

    inflight = [it for s in sections if s["kind"] == "inflight" for it in s["items"]]
    waiting = [e for s in sections if s["kind"] == "waiting" for e in s["entries"]] if t["waiting_section"] else []
    misc = [it for s in sections if s["kind"] == "misc" for it in s["items"]] if t["misc_section"] else []
    has_sub = any(s["subgroups"] for s in sections if s["kind"] == "inflight")
    return {"sections": sections, "inflight": inflight, "waiting": waiting, "misc": misc,
            "has_subgroups": has_sub, "end_line": end_line}


def read_todo(root, cfg) -> dict | None:
    """TODO の一覧を読む。ファイルが無ければ None。返り値は parse_todo に path を足したもの。"""
    p = todo_path(root, cfg)
    text = _read(p)
    if text is None:
        return None
    res = parse_todo(text, cfg)
    res["path"] = str(p)
    return res


def inflight_items(todo: dict, include_done: bool = False, group: str | None = None) -> list[dict]:
    """進行中の案件の行。既定は未完了だけ。group は work / private で絞る。"""
    return [it for it in todo["inflight"]
            if (include_done or not it["done"]) and (group is None or it["group"] == group)]


def inflight_layers(todo: dict, include_done: bool = False, group: str | None = None) -> dict:
    """進行中の行の layer の注記 → scope（注記に scope が無ければ layer のパス）。最初に出たものを採る。
    group は work / private で絞る（既定は両方）。"""
    out: dict = {}
    for it in inflight_items(todo, include_done, group):
        if it["layer"]:
            out.setdefault(it["layer"], it["scope"] or it["layer"])
    return out


# --- First・Daily ----------------------------------------------------------------

def parse_first_task(text: str, cfg: dict | None = None) -> dict:
    """First のファイルの本文を読む。返り値:
    {"heading_found": bool, "task": item or None, "open": [見出しの下の未完了の行…]}
    task は見出し（first_task.heading）の下の、最初の未完了の `- [ ]` の行。見出しの範囲は次の `#`・`##` の見出しまで。"""
    cfg = cfg or default_config()
    name = cfg["first_task"]["heading"]
    found = False
    inside = False
    rows = []
    for no, line, ok in _lines(text):
        h = _heading(line) if ok else None
        if h and h[0] <= 2:
            inside = heading_matches(h[1], name)
            found = found or inside
            continue
        if inside:
            rows.append((no, line, ok))
    items = [it for it in _checkbox_items(rows) if not it["done"]]
    return {"heading_found": found, "task": items[0] if items else None, "open": items}


def read_first_task(root, cfg) -> dict | None:
    p = first_task_path(root, cfg)
    text = _read(p)
    if text is None:
        return None
    res = parse_first_task(text, cfg)
    res["path"] = str(p)
    return res


def daily_applies(tag: str | None, day) -> bool:
    """Daily のタグがその日に当たるか。daily=毎日／weekly:月火=その曜日／monthly:N=その月の N 日
    （N 日が無い月は当たらない。月末への繰り上げはしない）。タグが無い・読めない行は当たらない。"""
    if not tag:
        return False
    d = _as_date(day)
    if tag == "daily":
        return True
    kind, _, val = tag.partition(":")
    if kind == "weekly":
        return WEEKDAYS[d.weekday()] in val
    if kind == "monthly":
        try:
            return int(val) == d.day
        except ValueError:
            return False
    return False


def parse_daily_tasks(text: str, day=None) -> list[dict]:
    """Daily のファイルの行（`- [ ] …`・`- …` の末尾に [daily]・[weekly:月火]・[monthly:N]）。
    返り値の各行: item ＋ {"tag", "section", "applies"}（applies は day を渡したときだけ bool、無ければ None）。
    タグの無い行も入る（tag=None・applies=False）。完了の印は読むが、当てはまりの判定には使わない。"""
    out = []
    sec = None
    for no, line, ok in _lines(text):
        if not ok:
            continue
        h = _heading(line)
        if h:
            sec = h[1] if h[0] >= 2 else sec
            continue
        m = ITEM_RE.match(line)
        if m:
            body, done = m.group(2), m.group(1) != " "
        else:
            pm = PLAIN_ITEM_RE.match(line)
            if not pm or not pm.group(1):
                continue
            body, done = pm.group(1), False
        tm = DAILY_TAG_RE.search(body)
        tag = tm.group(1) if tm else None
        if tm:
            body = body[:tm.start()].rstrip()
        it = _task(no, body, done)
        it.update({"tag": tag, "section": sec,
                   "applies": (daily_applies(tag, day) if day is not None else None)})
        out.append(it)
    return out


def read_daily_tasks(root, cfg, day=None) -> list[dict] | None:
    text = _read(daily_task_path(root, cfg))
    return None if text is None else parse_daily_tasks(text, day)


# --- WillDo・日記 -----------------------------------------------------------------

def split_disposition(text: str) -> tuple[str, str | None, str | None]:
    """行の末尾の扱いの印を外す。返り値は (印を外した文, disposition or None, 書き直した行 or None)。
    印は ` → 繰り越し`・` → 繰り越し: <書き直した行>`・` → TODO へ`・` → やめた`（→ の前後の空白は省けてよい）。"""
    m = DISPOSITION_RE.match(text)
    if not m:
        return text, None, None
    word = re.sub(r"\s+", " ", m.group(2)).replace("TODOへ", "TODO へ")
    key = next(k for k, label in DISPOSITIONS if label == word)
    carry = (m.group(3) or "").strip() or None
    if key != "carryover":
        carry = None
    return m.group(1).rstrip(), key, carry


def _marked_task(line_no: int, body: str, done: bool) -> dict:
    """WillDo・日記の行（扱いの印を読む）。raw は印を含む元の文、title・estimate_min は印を外した文から。"""
    rest, disp, carry = split_disposition(body)
    it = _task(line_no, rest, done)
    it["raw"] = body
    ct, ce = split_estimate(carry) if carry else (None, None)
    it.update({"disposition": disp, "carry_title": ct, "carry_estimate_min": ce})
    return it


def _willdo_key(name: str) -> str | None:
    stripped = re.sub(r"^\d+\s*[.．]\s*", "", name).strip()
    for key, label in WILLDO_SECTIONS:
        if heading_matches(stripped, label) or stripped.startswith(label):
            return key
    return None


def parse_will_do(text: str) -> dict:
    """WillDo の本文を読む。返り値:
    {"date": 見出しの日付 or None,
     "sections": {"first"|"inserted"|"carryover"|"from_todo"|"daily": [item…]},
     "retrospective": {"present": bool, "lines": [振り返りの直下の文の行],
                       "FUN"|"DONE"|"DONE（WillDo外）"|"LEARN"|<ほかの ### の名前>: [{"text","done","estimate_min","line","is_task"}]},
     "unknown_sections": [5つの欄にも振り返りにも当たらない `##` の名前]}
    `###` の小見出しは、どの `##` の下にあっても振り返りの小区分として読む（DONE（WillDo外）が後から足されることがあるため）。
    5つの欄の item には、扱いの印（split_disposition）の disposition・carry_title・carry_estimate_min も付く。"""
    res = {"date": None, "sections": {k: [] for k, _ in WILLDO_SECTIONS},
           "retrospective": {"present": False, "lines": [], **{k: [] for k in RETRO_SUBSECTIONS}},
           "unknown_sections": []}
    cur = None  # ("section", key) | ("retro", None) | ("retro_sub", name) | None
    for no, line, ok in _lines(text):
        if not ok:
            continue
        h = _heading(line)
        if h:
            depth, name = h
            if depth == 1:
                m = H1_DATE_RE.search(name)
                res["date"] = m.group(1) if m else res["date"]
                cur = None
            elif depth == 2:
                key = _willdo_key(name)
                if key:
                    cur = ("section", key)
                elif RETRO_HEADING in name:
                    res["retrospective"]["present"] = True
                    cur = ("retro", None)
                else:
                    res["unknown_sections"].append(name)
                    cur = None
            else:
                res["retrospective"].setdefault(name, [])
                cur = ("retro_sub", name)
            continue
        if cur is None or not line.strip() or line.strip() == "---":
            continue
        m = ITEM_RE.match(line)
        if cur[0] == "section":
            if m:
                res["sections"][cur[1]].append(_marked_task(no, m.group(2), m.group(1) != " "))
            continue
        if cur[0] == "retro":
            res["retrospective"]["lines"].append(line.strip())
            continue
        if m:
            t = _task(no, m.group(2), m.group(1) != " ")
            row = {"text": t["title"], "done": t["done"], "estimate_min": t["estimate_min"], "line": no, "is_task": True}
        else:
            s = line.strip()
            s = s[2:].strip() if s.startswith("- ") else s
            row = {"text": s, "done": None, "estimate_min": None, "line": no, "is_task": False}
        res["retrospective"][cur[1]].append(row)
    return res


def will_do_counts(willdo: dict, include_daily: bool = True) -> dict:
    """5つの欄の行の数・完了の数・見積の合計（分。見積の無い行は数えない）。"""
    keys = [k for k, _ in WILLDO_SECTIONS if include_daily or k != "daily"]
    rows = [it for k in keys for it in willdo["sections"][k]]
    return {"total": len(rows), "done": sum(1 for r in rows if r["done"]),
            "open": sum(1 for r in rows if not r["done"]),
            "estimate_min": sum(r["estimate_min"] or 0 for r in rows),
            "without_estimate": sum(1 for r in rows if r["estimate_min"] is None)}


def read_will_do(root, cfg, day) -> dict | None:
    p = will_do_path(root, cfg, day)
    text = _read(p)
    if text is None:
        return None
    res = parse_will_do(text)
    res["path"] = str(p)
    return res


def parse_task_diary(text: str) -> dict:
    """日記の本文を読む。返り値 {"date", "scheduled": [item…], "urgent": [item…]}。
    緊急の行の「（理由: …）」は item の reason に入る。扱いの印（/ppm-close が緊急の行に付ける）も読む。"""
    res = {"date": None, "scheduled": [], "urgent": []}
    cur = None
    for no, line, ok in _lines(text):
        if not ok:
            continue
        h = _heading(line)
        if h:
            if h[0] == 1:
                m = H1_DATE_RE.search(h[1])
                res["date"] = m.group(1) if m else res["date"]
                cur = None
            elif h[0] == 2:
                cur = next((k for k, label in DIARY_SECTIONS if h[1].startswith(label)), None)
            continue
        if cur is None:
            continue
        m = ITEM_RE.match(line)
        if m:
            res[cur].append(_marked_task(no, m.group(2), m.group(1) != " "))
    return res


def read_task_diary(root, cfg, day) -> dict | None:
    p = task_diary_path(root, cfg, day)
    text = _read(p)
    if text is None:
        return None
    res = parse_task_diary(text)
    res["path"] = str(p)
    return res


# --- 翌日の候補（繰り越し・差し込み）をさかのぼって集める --------------------------------

def find_last_will_do(root, cfg, before, lookback_days: int | None = None) -> date | None:
    """before より前で WillDo がある最も新しい日（before 自身は見ない）。lookback_days 日（既定は
    ppm.plan.lookback_days）さかのぼって無ければ None。読むだけ。"""
    d0 = _as_date(before)
    n = lookback_days or cfg["plan"]["lookback_days"]
    for i in range(1, n + 1):
        d = d0 - timedelta(days=i)
        if will_do_path(root, cfg, d).is_file():
            return d
    return None


def _norm_title(s: str | None) -> str:
    """同じ行かを比べる鍵（空白と「（理由: …）」を外す）。"""
    return re.sub(r"\s+", "", REASON_RE.sub("", s or ""))


def carry_candidates(root, cfg, target, lookback_days: int | None = None,
                     include_target_urgent: bool = False) -> dict:
    """/ppm-plan が対象日の WillDo の 2（差し込み）・3（繰り越し）の欄に入れる候補を集める。読むだけ。

    - last = find_last_will_do（対象日より前で WillDo がある最も新しい日）。since = last、無ければ 対象日 − lookback_days
    - carryover（3の欄）: last の WillDo の5つの欄の未完了のうち、印が「繰り越し」か印の無い行。
      Daily Task の欄は、印が「繰り越し」の行だけ（Daily は次に当たる日にまた入るため）。
      「TODO へ」「やめた」の行は set_aside に入れ、候補にしない
    - scheduled（2の欄）: since（last があれば last の日）から対象日までの日記の「予定タスク」の未完了。
      last の日の予定タスクは、last の WillDo に同じ題名の行が無いものだけ（WillDo を組んだ後に足された行。
      WillDo にある行は WillDo の側で扱う）
    - urgent（2の欄の候補）: since から対象日の前の日までの日記の「緊急」の未完了で、印が「繰り越し」か無いもの
      （include_target_urgent=True なら対象日の分も。朝に今日の分を組むとき）。last の WillDo に同じ題名の行が
      ある緊急の行は、WillDo の側で扱うので入れない
    - 「TODO へ」「やめた」の印の付いた日記の行も set_aside に入れる
    - 同じ題名（空白を無視）は1回だけ。carryover が先、日記は日付の順（同じ日は緊急 → 予定タスク）で先に出た方を残す
    各行は item ＋ {"date", "from": will_do|diary_scheduled|diary_urgent, "section"（WillDo の欄。日記は None）,
    "plan_title", "plan_estimate_min"}。plan_title は書き直した行（carry_title）があればそれ、無ければ title。"""
    t = _as_date(target)
    n = lookback_days or cfg["plan"]["lookback_days"]
    last = find_last_will_do(root, cfg, t, n)
    since = last if last else t - timedelta(days=n)
    seen: set = set()
    out = {"target": t.isoformat(), "lookback_days": n, "last_will_do": last.isoformat() if last else None,
           "last_will_do_path": str(will_do_path(root, cfg, last)) if last else None,
           "carryover": [], "urgent": [], "scheduled": [], "set_aside": [], "diary_days": []}

    def add(bucket: str, it: dict, day: date, origin: str, section=None) -> None:
        title = it["carry_title"] or it["title"]
        est = it["carry_estimate_min"] if it["carry_title"] else it["estimate_min"]
        row = dict(it, date=day.isoformat(), **{"from": origin}, section=section,
                   plan_title=title, plan_estimate_min=est)
        key = _norm_title(title)
        if bucket != "set_aside":
            if key in seen:
                return
            seen.add(key)
        out[bucket].append(row)

    wd_titles: set = set()
    if last:
        wd = read_will_do(root, cfg, last) or {"sections": {}}
        for key, _ in WILLDO_SECTIONS:
            for it in wd["sections"].get(key, []):
                wd_titles.add(_norm_title(it["title"]))
                if it["done"]:
                    continue
                if it["disposition"] in ("to_todo", "dropped"):
                    add("set_aside", it, last, "will_do", key)
                elif key == "daily" and it["disposition"] != "carryover":
                    continue
                else:
                    add("carryover", it, last, "will_do", key)

    day = since
    while day <= t:
        diary = read_task_diary(root, cfg, day)
        if diary is not None:
            out["diary_days"].append(day.isoformat())
            if day < t or include_target_urgent:
                for it in diary["urgent"]:
                    if it["done"] or (day == last and _norm_title(it["title"]) in wd_titles):
                        continue
                    if it["disposition"] in ("to_todo", "dropped"):
                        add("set_aside", it, day, "diary_urgent")
                    else:
                        add("urgent", it, day, "diary_urgent")
            for it in diary["scheduled"]:
                if it["done"] or (day == last and _norm_title(it["title"]) in wd_titles):
                    continue
                if it["disposition"] in ("to_todo", "dropped"):
                    add("set_aside", it, day, "diary_scheduled")
                else:
                    add("scheduled", it, day, "diary_scheduled")
        day += timedelta(days=1)
    return out


# --- CLI（読み取りだけ） ----------------------------------------------------------

def _dump(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _todo_text(todo: dict, show_private: bool = False) -> str:
    """todo の JSON でない出力。私生活の節の行は、show_private でなければ題名だけ（Layer のパスを出さない）。"""
    lines = [f"TODO: {todo['path']}",
             f"進行中（未完了）: {len(inflight_items(todo))}件 / 待ち: {len(todo['waiting'])}件 / "
             f"雑務（未完了）: {sum(1 for i in todo['misc'] if not i['done'])}件"]
    for it in inflight_items(todo):
        where = it["section"] + (f" > {it['subgroup']}" if it["subgroup"] else "")
        hide = it["group"] == "private" and not show_private
        lay = f" — layer: {it['layer']}" if it["layer"] and not hide else ""
        lines.append(f"- [{where}] {it['title']}{lay}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="日次の入口の設定とファイルを読む（読み取りだけ）")
    ap.add_argument("command", choices=["config", "paths", "todo", "first", "daily", "willdo", "diary", "carry"])
    ap.add_argument("--root", default=None)
    ap.add_argument("--date", default=None, help="YYYY-MM-DD（既定は今日。carry では対象日）")
    ap.add_argument("--json", action="store_true", help="todo を JSON で出す（ほかは常に JSON）")
    ap.add_argument("--show-private", action="store_true",
                    help="todo の JSON でない出力で、私生活の節の行の Layer のパスも出す")
    ap.add_argument("--with-target-urgent", action="store_true",
                    help="carry で対象日の日記の緊急も入れる（朝に今日の分を組むとき）")
    a = ap.parse_args(argv)
    try:
        root, cfg = context(a.root)
        day = _as_date(a.date) if a.date else date.today()
        return _run(a, root, cfg, day)
    except (PpmConfigError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


def _run(a, root, cfg, day) -> int:
    if a.command == "carry":
        _dump(carry_candidates(root, cfg, day, include_target_urgent=a.with_target_urgent))
    elif a.command == "config":
        _dump(cfg)
    elif a.command == "paths":
        _dump(paths(root, cfg, day))
    elif a.command == "todo":
        todo = read_todo(root, cfg)
        if todo is None:
            print(f"TODO の一覧がありません: {todo_path(root, cfg)}（雛形: {template_path(root, cfg, 'todo')}）",
                  file=sys.stderr)
            return 1
        if a.json:
            _dump(todo)
        else:
            print(_todo_text(todo, show_private=a.show_private))
    elif a.command == "first":
        r = read_first_task(root, cfg)
        if r is None:
            print(f"First のファイルがありません: {first_task_path(root, cfg)}", file=sys.stderr)
            return 1
        _dump(r)
    elif a.command == "daily":
        r = read_daily_tasks(root, cfg, day)
        if r is None:
            print(f"Daily のファイルがありません: {daily_task_path(root, cfg)}", file=sys.stderr)
            return 1
        _dump(r)
    elif a.command == "willdo":
        r = read_will_do(root, cfg, day)
        if r is None:
            print(f"WillDo がありません: {will_do_path(root, cfg, day)}", file=sys.stderr)
            return 1
        r["counts"] = will_do_counts(r)
        _dump(r)
    elif a.command == "diary":
        r = read_task_diary(root, cfg, day)
        if r is None:
            print(f"日記がありません: {task_diary_path(root, cfg, day)}", file=sys.stderr)
            return 1
        _dump(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
