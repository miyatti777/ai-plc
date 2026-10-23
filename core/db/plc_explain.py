"""Show or update a Layer's explanation preference; no Registry/network access."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import yaml

LEVELS = {"brief": "要点中心", "reasoned": "理由も説明", "guided": "前提・用語から説明"}
DEFAULT = "reasoned"
HEAD = re.compile(r"^(?:\ufeff)?(?:explanation|\"explanation\"|'explanation')[ \t]*:")


class PreferenceError(ValueError):
    pass


class StrictLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError:
            raise PreferenceError("YAMLのキーが不正です") from None
        if duplicate:
            raise PreferenceError("YAMLに重複キーがあります")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def parse(text):
    try:
        data = yaml.load(text.lstrip("\ufeff"), Loader=StrictLoader)
    except yaml.YAMLError:
        raise PreferenceError("intent.yamlをYAMLとして読めません") from None
    if not isinstance(data, dict) or not isinstance(data.get("scope_id"), str) or not data["scope_id"].strip():
        raise PreferenceError("intent.yamlに文字列のscope_idが必要です")
    return data


def read(layer):
    path = Path(layer).expanduser().resolve() / "intent.yaml"
    if path.is_symlink():
        raise PreferenceError("シンボリックリンクのintent.yamlは対象にできません")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise PreferenceError("intent.yamlはUTF-8で保存してください") from None
    return path, raw, text, parse(text)


def profile(data):
    cur = data.get("explanation")
    valid = isinstance(cur, dict) and set(cur) == {"level"} and isinstance(cur.get("level"), str) and cur["level"] in LEVELS
    if "explanation" not in data:
        return None, []
    if not valid:
        return None, ["explanationの設定が不正です。reasonedで説明し、保存値は変更しません。"]
    return cur["level"], []


def show(layer, once=None):
    if once is not None and once not in LEVELS:
        raise PreferenceError("一時設定の値が不正です")
    _, _, _, data = read(layer)
    stored, warnings = profile(data)
    effective = once or stored or DEFAULT
    return {"scope_id": data["scope_id"], "stored_level": stored,
            "effective_level": effective, "label": LEVELS[effective],
            "source": "once" if once else "stored" if stored else "default",
            "expires": "next_response_end" if once else None,
            "warnings": warnings}


def edit_text(text, level):
    """Change only the top-level block, preserving all other bytes/comments."""
    lines = text.splitlines(keepends=True)
    heads = [i for i, line in enumerate(lines) if HEAD.match(line)]
    if len(heads) > 1:
        raise PreferenceError("explanationの見出しが複数あります")
    eol = "\r\n" if "\r\n" in text else "\n"
    block = f"explanation:{eol}  level: {level}{eol}"
    if not heads:
        if "explanation" in parse(text):
            raise PreferenceError("explanationの見出しを特定できません。手で範囲を確認してください")
        return text + (eol if text and not text.endswith("\n") else "") + block
    start = heads[0]
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and not line.startswith((" ", "\t", "#")):
            break
        end += 1
    # Preserve trailing comments/blank lines rather than deleting their context.
    while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
        end -= 1
    if start == 0 and text.startswith("\ufeff"):
        block = "\ufeff" + block
    return "".join(lines[:start]) + block + "".join(lines[end:])


def atomic_write(path, before, after):
    """Atomic replacement, with optimistic conflict detection just before replace."""
    mode = path.stat().st_mode & 0o777
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".plc_explain_", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(after)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temp, mode)
        if path.is_symlink() or path.read_bytes() != before:
            raise PreferenceError("intent.yamlが変更されました。読み直してから再実行してください")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def set_level(layer, level, yes=False):
    if level not in LEVELS:
        raise PreferenceError("説明設定の値が不正です")
    path, raw, text, data = read(layer)
    _, warnings = profile(data)
    if warnings:
        raise PreferenceError("既存explanationが不正です。未知の項目を上書きしません")
    edited = edit_text(text, level)
    expected = copy.deepcopy(data)
    expected["explanation"] = {"level": level}
    if parse(edited) != expected:
        raise PreferenceError("explanation以外の項目が変わるため書き込みません")
    if yes and edited.encode("utf-8") != raw:
        atomic_write(path, raw, edited.encode("utf-8"))
    return {"scope_id": data["scope_id"], "action": "saved" if yes else "preview",
            "level": level, "label": LEVELS[level], "written": bool(yes and edited.encode("utf-8") != raw)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    get = subs.add_parser("show", help="有効値を読み取る（書き込みなし）")
    get.add_argument("--layer", required=True)
    get.add_argument("--once", choices=LEVELS, help="次の1応答だけの説明値。保存しない")
    put = subs.add_parser("set", help="継続設定を変更する（--yesで保存）")
    put.add_argument("--layer", required=True)
    put.add_argument("--level", required=True, choices=LEVELS)
    put.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = show(args.layer, args.once) if args.command == "show" else set_level(args.layer, args.level, args.yes)
    except (PreferenceError, OSError) as exc:
        # OSError/YAML parser diagnostics can include private paths or source text.
        message = str(exc) if isinstance(exc, PreferenceError) else f"ファイル操作に失敗しました（{type(exc).__name__}）"
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
