#!/usr/bin/env python3
"""Fault-fixture helpers that never patch the checked-out distribution."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Iterator


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_snapshot(root: Path) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        info = path.lstat()
        item: dict[str, object] = {"mode": stat.S_IMODE(info.st_mode), "size": info.st_size}
        if path.is_symlink():
            item.update({"type": "symlink", "target": os.readlink(path)})
        elif path.is_file():
            item.update({"type": "file", "sha256": sha256(path)})
        elif path.is_dir():
            item["type"] = "directory"
        else:
            item["type"] = "special"
        result[rel] = item
    return result


def source_snapshot(root: Path) -> dict[str, str]:
    names = (
        "install.sh", "install-cc.sh", "install-cursor.sh", "install-codex.sh", "uninstall.sh",
        "lib/ai_plc_safe_fs.py", "lib/ai_plc_multi_env.py",
    )
    return {name: sha256(root / name) for name in names}


class IsolatedDistribution:
    def __init__(self, source: Path):
        self.source = source
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        self._temporary = tempfile.TemporaryDirectory(prefix="ai-plc-test-dist-", dir="/private/tmp")
        self.path = Path(self._temporary.name) / "distribution"
        shutil.copytree(self.source, self.path, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        return self.path

    def __exit__(self, *_: object) -> None:
        if self._temporary:
            self._temporary.cleanup()


def patch_copy(path: Path, needle: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    if needle not in text:
        raise AssertionError(f"fault injection anchor not found: {needle}")
    path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")


def write_dead_lock(root: Path, metadata: dict, state: dict | None = None) -> None:
    transaction_id = metadata["transaction_id"]
    (root / ".ai-plc-install.lock").write_text(json.dumps(metadata, sort_keys=True) + "\n")
    if state is not None:
        (root / f".ai-plc-install-journal.{transaction_id}").write_text(
            json.dumps(state, sort_keys=True) + "\n")
