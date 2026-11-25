"""一覧の並び順（更新順）の根拠: Layer の管理ファイルのローカル保存時刻だけを読む（DB の同期時刻は使わない）。

読み取りだけ。シンボリックリンクをたどらず、大きすぎるファイル・読む途中で変わったファイルは根拠にしない。
時刻の表示は日本時間（+09:00）。
"""
from __future__ import annotations

import os
import re
import stat
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import yaml

JST = timezone(timedelta(hours=9))
LIMIT = 2 * 1024 * 1024
SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
NOTICE = ("更新順はbacklog.yaml／context.yamlのローカル保存時刻の目安です。"
          "業務実行日時ではなく、checkout・touch・復元でも変わります。"
          "両方未配置のLayerはintent.yaml、Layerなしは作業更新未確認の作成日時を下位に表示。"
          "Registry更新・同期時刻は順位に使いません。親子は維持し、条件に合う子の更新もグループ順位に反映します。")


def parse_time(value, now):
    """Date-only and legacy offset-less values are JST; invalid/future => unknown."""
    try:
        text = str(value or "").strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            result = datetime.combine(date.fromisoformat(text), time(), JST)
            precision = "day"
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", text):
            offset = re.search(r"[+-](\d{2}):(\d{2})$", text)
            if offset and (int(offset[1]) > 23 or int(offset[2]) > 59):
                return None
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
            result = result.replace(tzinfo=JST) if result.tzinfo is None else result
            precision = "second"
        else:
            return None
        return (result, precision) if 0 < result.timestamp() <= now.timestamp() else None
    except (ValueError, OverflowError, OSError):
        return None


def _signature(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def _bounded_structure(data):
    """Bound depth and distinct nodes without recursively expanding aliases."""
    pending, seen = [(data, 0)], set()
    while pending:
        node, depth = pending.pop()
        if depth > 100 or len(seen) > 100000:
            return False
        if not isinstance(node, (dict, list)) or id(node) in seen:
            continue
        seen.add(id(node))
        children = node.values() if isinstance(node, dict) else node
        pending.extend((value, depth + 1) for value in children)
    return True


def _saved(root, rel, filename, sid):
    """Bounded stable YAML read through no-follow directory descriptors; no writes."""
    fds = []
    try:
        parts = Path(rel).parts
        if Path(rel).is_absolute() or not parts or any(x in ("..", ".") for x in parts):
            return None, "参照先不正"
        fds.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY))
        for part in parts:
            fds.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1]))
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fds[-1])
        fds.append(fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > LIMIT:
            return None, "通常YAMLファイルではない／上限超過"
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(LIMIT + 1)
        after = os.fstat(fd)
        current = os.stat(filename, dir_fd=fds[-2], follow_symlinks=False)
        if len(raw) > LIMIT or _signature(before) != _signature(after) or _signature(after) != _signature(current):
            return None, "読取中更新"
        data = yaml.load(raw.decode("utf-8"), Loader=SAFE_LOADER)
        if not isinstance(data, dict) or not data or not _bounded_structure(data) or (data.get("scope_id") and str(data["scope_id"]) != sid):
            return None, "YAML内容不正"
        return after.st_mtime, None
    except FileNotFoundError:
        return None, "未配置"
    except (OSError, ValueError, UnicodeError, yaml.YAMLError, RecursionError):
        return None, "読取不可／YAML不正"
    except (AttributeError, NotImplementedError):  # dir_fd・O_NOFOLLOW などが使えない OS（Windows など）
        return None, "この OS では保存時刻を安全に読めない"
    finally:
        for fd in reversed(fds):
            os.close(fd)


def evidence(root, rel, row, *, now=None):
    now = now or datetime.now(timezone.utc)
    warnings, candidates = [], []
    if rel:
        saved = [(name, *_saved(root, rel, name, row["scope_id"]))
                 for name in ("backlog.yaml", "context.yaml")]
        if all(error == "未配置" for _, _, error in saved):
            saved = [("intent.yaml", *_saved(root, rel, "intent.yaml", row["scope_id"]))]
        for name, stamp, error in saved:
            if error:
                if error != "未配置":
                    warnings.append(f"{name}: {error}")
                continue
            try:
                dt = datetime.fromtimestamp(stamp, timezone.utc)
                if not 0 < stamp <= now.timestamp():
                    raise ValueError("future/invalid")
            except (ValueError, OverflowError, OSError):
                warnings.append(f"{name}: 保存時刻不正／未来")
                continue
            candidates.append((dt, name))
        if candidates:
            dt, name = max(candidates, key=lambda pair: (pair[0], pair[1]))
            return _result(dt, "local_save", name, f"{rel}/{name}", "second", warnings)
    else:
        parsed = parse_time(row["created_at"] if "created_at" in row.keys() else None, now)
        if parsed:
            dt, precision = parsed
            return _result(dt, "created", "Registry.created_at（作業更新未確認）", None, precision, warnings)
        warnings.append("Registry作成日時なし／不正／未来")
    return _result(None, "unknown", "更新未確認", None, None, warnings)


def _result(dt, kind, source, path, precision, warnings):
    return {"at": dt.astimezone(JST).isoformat(timespec="seconds") if dt else None,
            "epoch_ms": int(dt.timestamp() * 1000) if dt else None,
            "kind": kind, "source": source, "path": path, "precision": precision, "warnings": warnings}


def order_key(project):
    a = project["activity"]
    rank = {"local_save": 0, "created": 1, "unknown": 2}[a["kind"]]
    # scope_id の数字の部分は数として比べる（…-2 が …-12 より前）
    sid = tuple((1, int(x)) if x.isdigit() else (0, x) for x in re.split(r"(\d+)", project["scope_id"]))
    return rank, -(a["epoch_ms"] or 0), sid
