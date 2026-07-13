#!/usr/bin/env python3
"""Safe planner/executor used by AI-PLC repository-local installers.

The module intentionally uses only the Python standard library. Target writes are
rooted at a pinned directory descriptor, reject symlink traversal, and are
journaled so a failed process can roll back without deleting unknown files.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
from typing import Any, Iterable


MANIFEST = ".ai-plc-install-manifest"
VERSION_MARKER = ".ai-plc-version"
LOCK = ".ai-plc-install.lock"
JOURNAL_PREFIX = ".ai-plc-install-journal."
TMP_PREFIX = ".ai-plc-tmp."
TOMBSTONE = ".ai-plc-uninstall-tombstone"
CODEX_START = "<!-- AI-PLC CODEX START -->"
CODEX_END = "<!-- AI-PLC CODEX END -->"
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class InstallError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def boot_identity() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        result = subprocess.run(
            ["sysctl", "-n", "kern.boottime"], text=True, capture_output=True, check=False,
        )
        return result.stdout.strip() or "unknown"


def process_start_identity(pid: int) -> str:
    if Path(f"/proc/{pid}/stat").is_file():
        try:
            return Path(f"/proc/{pid}/stat").read_text().split()[21]
        except (OSError, IndexError):
            return ""
    result = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)], text=True, capture_output=True, check=False,
    )
    return result.stdout.strip()


def canonical_rel(value: str) -> str:
    p = PurePosixPath(value)
    if p.is_absolute() or not p.parts or any(x in ("", ".", "..") for x in p.parts):
        raise InstallError(f"unsafe relative path: {value!r}")
    return p.as_posix()


def open_absolute_directory(path: Path) -> tuple[int, tuple[int, int]]:
    """Open every absolute path component from trusted `/` without following links."""
    absolute = Path(os.path.abspath(path))
    if not absolute.is_absolute():
        raise InstallError(f"not absolute: {path}")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open("/", flags)
    try:
        for part in absolute.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            raise InstallError(f"not a directory: {absolute}")
        return fd, (st.st_dev, st.st_ino)
    except Exception:
        os.close(fd)
        raise


class SafeRoot:
    def __init__(self, path: Path):
        self.path = Path(os.path.abspath(path))
        self.fd, self.identity = open_absolute_directory(self.path)

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> "SafeRoot":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _open_parent(self, rel: str, create: bool = False, tx: "Transaction | None" = None) -> tuple[int, str]:
        rel = canonical_rel(rel)
        parts = list(PurePosixPath(rel).parts)
        name = parts.pop()
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.dup(self.fd)
        walked: list[str] = []
        try:
            for part in parts:
                walked.append(part)
                try:
                    nxt = os.open(part, flags, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        raise
                    tmp_part = f"{TMP_PREFIX}{tx.transaction_id}.dir.{secrets.token_hex(4)}" if tx else part
                    intended = "/".join(walked)
                    temp_rel = "/".join(walked[:-1] + [tmp_part])
                    if tx is not None:
                        tx.plan_new_dir(intended, temp_rel)
                    os.mkdir(tmp_part, 0o755, dir_fd=fd)
                    os.fsync(fd)
                    nxt = os.open(tmp_part, flags, dir_fd=fd)
                    if tx is not None:
                        st = os.fstat(nxt)
                        tx.record_new_dir_created(intended, temp_rel, st)
                        os.fsync(nxt)
                        os.rename(tmp_part, part, src_dir_fd=fd, dst_dir_fd=fd)
                        os.fsync(fd)
                        tx.record_new_dir_published(intended)
                    os.close(nxt)
                    nxt = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = nxt
            return fd, name
        except Exception:
            os.close(fd)
            raise

    def lstat(self, rel: str) -> os.stat_result | None:
        try:
            fd, name = self._open_parent(rel)
        except FileNotFoundError:
            return None
        try:
            return os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        finally:
            os.close(fd)

    def exists(self, rel: str) -> bool:
        return self.lstat(rel) is not None

    def read_bytes(self, rel: str) -> bytes:
        fd, name = self._open_parent(rel)
        try:
            file_fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
            try:
                st = os.fstat(file_fd)
                if not stat.S_ISREG(st.st_mode):
                    raise InstallError(f"not a regular file: {rel}")
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(file_fd, 1024 * 1024)
                    if not chunk:
                        return b"".join(chunks)
                    chunks.append(chunk)
            finally:
                os.close(file_fd)
        finally:
            os.close(fd)

    def walk_regular_files(self, rel: str) -> list[str]:
        base = canonical_rel(rel)
        start_fd, _ = self._open_parent(base)
        name = PurePosixPath(base).name
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            directory_fd = os.open(name, flags, dir_fd=start_fd)
        finally:
            os.close(start_fd)
        found: list[str] = []
        def visit(fd: int, prefix: str) -> None:
            for child in sorted(os.listdir(fd)):
                st = os.stat(child, dir_fd=fd, follow_symlinks=False)
                path = f"{prefix}/{child}"
                if stat.S_ISREG(st.st_mode):
                    found.append(path)
                elif stat.S_ISDIR(st.st_mode):
                    child_fd = os.open(child, flags, dir_fd=fd)
                    try:
                        visit(child_fd, path)
                    finally:
                        os.close(child_fd)
                elif stat.S_ISLNK(st.st_mode):
                    raise InstallError(f"source symlink refused: {path}")
        try:
            visit(directory_fd, base)
        finally:
            os.close(directory_fd)
        return found

    def _write_new(self, rel: str, data: bytes, mode: int = 0o644, tx: "Transaction | None" = None) -> None:
        fd, name = self._open_parent(rel, create=True, tx=tx)
        try:
            out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode, dir_fd=fd)
            try:
                view = memoryview(data)
                while view:
                    written = os.write(out, view)
                    view = view[written:]
                os.fsync(out)
            finally:
                os.close(out)
            os.fsync(fd)
        finally:
            os.close(fd)

    def write_atomic(self, rel: str, data: bytes, tx: "Transaction", mode: int = 0o644) -> bool:
        rel = canonical_rel(rel)
        current = self.read_bytes(rel) if self.exists(rel) else None
        if current == data:
            return False
        fd, name = self._open_parent(rel, create=True, tx=tx)
        token = secrets.token_hex(8)
        tmp_name = f"{TMP_PREFIX}{tx.transaction_id}.{token}"
        try:
            if current is None:
                tx.record_new_file(rel, sha256(data), mode)
            else:
                before = os.stat(name, dir_fd=fd, follow_symlinks=False)
                while True:
                    backup = tx.next_backup_name(rel)
                    if self.exists(backup):
                        continue
                    tx.record_backup(rel, backup, sha256(current), sha256(data), before)
                    try:
                        self._write_new(backup, current, stat.S_IMODE(before.st_mode), tx)
                        tx.record_backup_created(rel, backup, self.lstat(backup))
                        break
                    except FileExistsError:
                        tx.cancel_backup(rel, backup)
            parent = PurePosixPath(rel).parent.as_posix()
            tmp_rel = tmp_name if parent == "." else f"{parent}/{tmp_name}"
            tx.record_temp(tmp_rel, sha256(data), mode)
            out = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode, dir_fd=fd)
            try:
                view = memoryview(data)
                while view:
                    written = os.write(out, view)
                    view = view[written:]
                os.fsync(out)
            finally:
                os.close(out)
            tx.record_temp_created(tmp_rel, os.stat(tmp_name, dir_fd=fd, follow_symlinks=False))
            if current is None:
                tx.record_new_file_identity(rel, os.stat(tmp_name, dir_fd=fd, follow_symlinks=False))
            os.replace(tmp_name, name, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
            published = os.stat(name, dir_fd=fd, follow_symlinks=False)
            tx.record_published(rel, published)
            tx.clear_temp(tmp_rel)
            return True
        finally:
            os.close(fd)

    def unlink(self, rel: str) -> None:
        fd, name = self._open_parent(rel)
        try:
            os.unlink(name, dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(fd)

    def rename(self, source: str, target: str) -> None:
        source_fd, source_name = self._open_parent(source)
        target_fd, target_name = self._open_parent(target, create=False)
        try:
            os.rename(source_name, target_name, src_dir_fd=source_fd, dst_dir_fd=target_fd)
            os.fsync(source_fd)
            if target_fd != source_fd:
                os.fsync(target_fd)
        finally:
            os.close(source_fd)
            os.close(target_fd)

    def delete_transactional(self, rel: str, tx: "Transaction") -> bool:
        rel = canonical_rel(rel)
        if not self.exists(rel):
            return False
        data = self.read_bytes(rel)
        fd, name = self._open_parent(rel)
        try:
            before = os.stat(name, dir_fd=fd, follow_symlinks=False)
            while True:
                backup = tx.next_backup_name(rel)
                if self.exists(backup):
                    continue
                tx.record_backup(rel, backup, sha256(data), None, before)
                try:
                    self._write_new(backup, data, stat.S_IMODE(before.st_mode), tx)
                    tx.record_backup_created(rel, backup, self.lstat(backup))
                    break
                except FileExistsError:
                    tx.cancel_backup(rel, backup)
            os.unlink(name, dir_fd=fd)
            os.fsync(fd)
            return True
        finally:
            os.close(fd)

    def prune_empty_dir(self, rel: str, identity: tuple[int, int] | None = None) -> None:
        fd, name = self._open_parent(rel)
        try:
            st = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if identity and (st.st_dev, st.st_ino) != identity:
                raise InstallError(f"directory identity changed during rollback: {rel}")
            os.rmdir(name, dir_fd=fd)
            os.fsync(fd)
        except OSError as exc:
            if exc.errno not in (errno.ENOENT, errno.ENOTEMPTY):
                raise
        finally:
            os.close(fd)


class Transaction:
    def __init__(self, root: SafeRoot):
        self.root = root
        self.transaction_id = f"{os.getpid()}-{secrets.token_hex(8)}"
        self.journal_name = f"{JOURNAL_PREFIX}{self.transaction_id}"
        self.lock_nonce = secrets.token_hex(16)
        self.state: dict[str, Any] = {
            "schema_version": 1,
            "transaction_id": self.transaction_id,
            "phase": "prepared",
            "backups": [],
            "new_files": [],
            "new_dirs": [],
            "temps": [],
        }
        self.locked = False
        self.lock_name = LOCK
        self.backup_seq = 0

    def acquire(self) -> None:
        if self.root.exists(LOCK):
            raise InstallError(f"target is busy or needs recovery: {LOCK}")
        candidate = f"{LOCK}.candidate.{os.getpid()}.{self.lock_nonce}"
        metadata = json.dumps({
            "pid": os.getpid(), "host": socket.gethostname(), "nonce": self.lock_nonce,
            "boot_id": boot_identity(), "process_start": process_start_identity(os.getpid()),
            "transaction_id": self.transaction_id, "journal_name": self.journal_name,
            "recovery_of": [], "started_at": utc_stamp(),
        }, sort_keys=True).encode() + b"\n"
        self.root._write_new(candidate, metadata)
        try:
            os.link(candidate, LOCK, src_dir_fd=self.root.fd, dst_dir_fd=self.root.fd, follow_symlinks=False)
            os.fsync(self.root.fd)
            self.root.unlink(candidate)
            self.locked = True
            self.save()
        except Exception:
            if self.root.exists(candidate):
                self.root.unlink(candidate)
            raise

    def save(self) -> None:
        data = json.dumps(self.state, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
        if self.root.exists(self.journal_name):
            current = self.root.read_bytes(self.journal_name)
            if current == data:
                return
            fd = os.dup(self.root.fd)
            tmp = f"{TMP_PREFIX}{self.transaction_id}.journal"
            try:
                if self.root.exists(tmp):
                    self.root.unlink(tmp)
                self.root._write_new(tmp, data)
                os.replace(tmp, self.journal_name, src_dir_fd=fd, dst_dir_fd=fd)
                os.fsync(fd)
            finally:
                os.close(fd)
        else:
            self.root._write_new(self.journal_name, data)

    def record_backup(self, path: str, backup: str, expected: str, post_sha256: str | None,
                      before: os.stat_result) -> None:
        self.state["backups"].append({
            "path": path, "backup": backup, "sha256": expected,
            "pre_device": before.st_dev, "pre_inode": before.st_ino,
            "pre_mode": stat.S_IMODE(before.st_mode),
            "backup_device": None, "backup_inode": None,
            "post_sha256": post_sha256, "post_device": None, "post_inode": None,
        })
        self.save()

    def record_backup_created(self, path: str, backup: str, st: os.stat_result) -> None:
        item = next(x for x in self.state["backups"] if x["path"] == path and x["backup"] == backup)
        item["backup_device"] = st.st_dev
        item["backup_inode"] = st.st_ino
        self.save()

    def cancel_backup(self, path: str, backup: str) -> None:
        item = next(x for x in self.state["backups"] if x["path"] == path and x["backup"] == backup)
        self.state["backups"].remove(item)
        self.save()

    def record_published(self, path: str, published: os.stat_result) -> None:
        for item in reversed(self.state["backups"]):
            if item["path"] == path:
                item["post_device"] = published.st_dev
                item["post_inode"] = published.st_ino
                self.save()
                return

    def record_new_file(self, path: str, expected: str, mode: int) -> None:
        if not any(x["path"] == path for x in self.state["new_files"]):
            self.state["new_files"].append({
                "path": path, "sha256": expected, "mode": mode,
                "device": None, "inode": None,
            })
            self.save()

    def record_new_file_identity(self, path: str, st: os.stat_result) -> None:
        item = next(x for x in self.state["new_files"] if x["path"] == path)
        item["device"] = st.st_dev
        item["inode"] = st.st_ino
        self.save()

    def plan_new_dir(self, path: str, temp: str) -> None:
        if not any(x["path"] == path for x in self.state["new_dirs"]):
            self.state["new_dirs"].append({
                "path": path, "temp": temp, "device": None, "inode": None, "published": False,
            })
            self.save()

    def record_new_dir_created(self, path: str, temp: str, st: os.stat_result) -> None:
        item = next(x for x in self.state["new_dirs"] if x["path"] == path)
        item.update({"temp": temp, "device": st.st_dev, "inode": st.st_ino})
        self.save()

    def record_new_dir_published(self, path: str) -> None:
        item = next(x for x in self.state["new_dirs"] if x["path"] == path)
        item["published"] = True
        self.save()

    def record_temp(self, name: str, expected_sha256: str, mode: int) -> None:
        self.state["temps"].append({
            "path": name, "sha256": expected_sha256, "mode": mode,
            "device": None, "inode": None,
        })
        self.save()

    def record_temp_created(self, name: str, st: os.stat_result) -> None:
        item = next(x for x in self.state["temps"] if x["path"] == name)
        item["device"] = st.st_dev
        item["inode"] = st.st_ino
        self.save()

    def clear_temp(self, name: str) -> None:
        matches = [x for x in self.state["temps"] if x["path"] == name]
        if matches:
            self.state["temps"].remove(matches[0])
            self.save()

    def next_backup_name(self, rel: str) -> str:
        self.backup_seq += 1
        return f"{rel}.bak.{utc_stamp()}.{self.backup_seq}"

    def commit(self) -> None:
        self.state["phase"] = "committed"
        self.save()
        if self.root.exists(self.journal_name):
            self.root.unlink(self.journal_name)
        if self.locked and self.root.exists(self.lock_name):
            self.root.unlink(self.lock_name)
        self.locked = False

    def rollback(self) -> None:
        errors: list[str] = []
        for item in reversed(self.state.get("temps", [])):
            try:
                path = item["path"] if isinstance(item, dict) else item
                if not self.root.exists(path):
                    continue
                data = self.root.read_bytes(path)
                st = self.root.lstat(path)
                if isinstance(item, dict):
                    if sha256(data) != item.get("sha256"):
                        raise InstallError(f"transaction temp changed; refusing cleanup: {path}")
                    if stat.S_IMODE(st.st_mode) != item.get("mode"):
                        raise InstallError(f"transaction temp mode changed; refusing cleanup: {path}")
                    if item.get("inode") is not None and (st.st_dev, st.st_ino) != (item["device"], item["inode"]):
                        raise InstallError(f"transaction temp identity changed; refusing cleanup: {path}")
                self.root.unlink(path)
            except Exception as exc:
                errors.append(str(exc))
        for item in reversed(self.state.get("backups", [])):
            try:
                if not self.root.exists(item["backup"]):
                    current = self.root.read_bytes(item["path"]) if self.root.exists(item["path"]) else None
                    if current is not None and sha256(current) == item["sha256"]:
                        continue
                    raise InstallError(f"backup missing after target publication: {item['backup']}")
                data = self.root.read_bytes(item["backup"])
                if sha256(data) != item["sha256"]:
                    raise InstallError(f"backup hash mismatch: {item['backup']}")
                backup_stat = self.root.lstat(item["backup"])
                if item.get("backup_inode") is not None and (
                    backup_stat.st_dev, backup_stat.st_ino
                ) != (item["backup_device"], item["backup_inode"]):
                    raise InstallError(f"backup identity mismatch: {item['backup']}")
                current_stat = self.root.lstat(item["path"])
                expected_post = item.get("post_sha256")
                if expected_post is None:
                    if current_stat is not None:
                        current = self.root.read_bytes(item["path"])
                        if sha256(current) == item["sha256"]:
                            self.root.unlink(item["backup"])
                            continue
                        raise InstallError(f"deleted target was recreated; refusing rollback: {item['path']}")
                else:
                    if current_stat is None:
                        raise InstallError(f"published target disappeared; refusing rollback: {item['path']}")
                    current = self.root.read_bytes(item["path"])
                    current_hash = sha256(current)
                    if current_hash == item["sha256"]:
                        self.root.unlink(item["backup"])
                        continue
                    if current_hash != expected_post:
                        raise InstallError(f"published target changed; refusing rollback: {item['path']}")
                    if item.get("post_inode") is not None and (
                        current_stat.st_dev, current_stat.st_ino
                    ) != (item["post_device"], item["post_inode"]):
                        raise InstallError(f"published target identity changed; refusing rollback: {item['path']}")
                self._restore(item["path"], data, int(item.get("pre_mode", 0o644)))
                self.root.unlink(item["backup"])
            except Exception as exc:  # best-effort recovery records every failure
                errors.append(str(exc))
        for item in reversed(self.state.get("new_files", [])):
            try:
                if self.root.exists(item["path"]):
                    data = self.root.read_bytes(item["path"])
                    st = self.root.lstat(item["path"])
                    identity_matches = item.get("inode") is not None and (
                        st.st_dev, st.st_ino
                    ) == (item["device"], item["inode"])
                    mode_matches = stat.S_IMODE(st.st_mode) == item.get("mode", 0o644)
                    if sha256(data) == item["sha256"] and identity_matches and mode_matches:
                        self.root.unlink(item["path"])
                    else:
                        raise InstallError(f"new file changed during rollback: {item['path']}")
            except Exception as exc:
                errors.append(str(exc))
        for item in reversed(self.state.get("new_dirs", [])):
            try:
                identity = None if item.get("inode") is None else (item["device"], item["inode"])
                candidate = item["path"] if self.root.exists(item["path"]) else item.get("temp")
                if candidate and self.root.exists(candidate):
                    self.root.prune_empty_dir(candidate, identity)
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            self.state["phase"] = "rollback-failed"
            self.state["errors"] = errors
            self.save()
            raise InstallError("rollback failed: " + "; ".join(errors))
        if self.root.exists(self.journal_name):
            self.root.unlink(self.journal_name)
        if self.locked and self.root.exists(self.lock_name):
            self.root.unlink(self.lock_name)
        self.locked = False

    def _restore(self, rel: str, data: bytes, mode: int = 0o644) -> None:
        fd, name = self.root._open_parent(rel, create=True)
        tmp = f"{TMP_PREFIX}{self.transaction_id}.restore.{secrets.token_hex(4)}"
        try:
            parent = PurePosixPath(rel).parent.as_posix()
            tmp_rel = tmp if parent == "." else f"{parent}/{tmp}"
            self.record_temp(tmp_rel, sha256(data), mode)
            out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode, dir_fd=fd)
            try:
                os.write(out, data)
                os.fsync(out)
            finally:
                os.close(out)
            self.record_temp_created(tmp_rel, os.stat(tmp, dir_fd=fd, follow_symlinks=False))
            os.replace(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
            self.clear_temp(tmp_rel)
        finally:
            os.close(fd)


def process_alive(pid: int, host: str, boot_id: str, process_start: str) -> bool:
    if host != socket.gethostname() or pid <= 0:
        return False
    if boot_id != boot_identity():
        return False
    try:
        os.kill(pid, 0)
        return process_start_identity(pid) == process_start
    except ProcessLookupError:
        return False
    except PermissionError:
        return process_start_identity(pid) == process_start


def control_artifacts(root: SafeRoot) -> list[str]:
    names = os.listdir(root.fd)
    return sorted(
        name for name in names
        if name == LOCK or name.startswith(LOCK + ".candidate.")
        or name.startswith(LOCK + ".stale.") or name.startswith(JOURNAL_PREFIX)
        or name.startswith(TMP_PREFIX)
    )


def validate_or_consume_tombstone(root: SafeRoot, mutate: bool) -> bool:
    if not root.exists(TOMBSTONE):
        return False
    try:
        data = json.loads(root.read_bytes(TOMBSTONE))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InstallError(f"invalid uninstall tombstone: {exc}") from exc
    if root.exists(MANIFEST):
        raise InstallError("uninstall tombstone unexpectedly coexists with install manifest")
    required = (
        data.get("schema_version") == 1 and data.get("state") == "deleted"
        and isinstance(data.get("transaction_id"), str) and data["transaction_id"]
        and isinstance(data.get("old_manifest_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", data["old_manifest_sha256"])
        and isinstance(data.get("completed_at"), str) and data["completed_at"]
    )
    if not required:
        raise InstallError("invalid uninstall tombstone schema")
    if mutate:
        root.unlink(TOMBSTONE)
    return True


def assert_fresh_transaction_artifacts(root: SafeRoot, tx: Transaction) -> None:
    actual = control_artifacts(root)
    expected = sorted([LOCK, tx.journal_name])
    if actual != expected:
        raise InstallError(f"transaction artifact set changed: expected {expected}, found {actual}")
    metadata = json.loads(root.read_bytes(LOCK))
    journal = json.loads(root.read_bytes(tx.journal_name))
    if metadata.get("transaction_id") != tx.transaction_id or metadata.get("nonce") != tx.lock_nonce:
        raise InstallError("transaction lock ownership mismatch")
    if metadata.get("recovery_of") != [] or journal.get("transaction_id") != tx.transaction_id:
        raise InstallError("transaction recovery/journal ownership mismatch")


def recover_if_needed(root: SafeRoot) -> None:
    """Recover a dead same-host transaction before planning a new install."""
    artifacts = control_artifacts(root)
    if not artifacts:
        return
    if not root.exists(LOCK):
        raise InstallError("orphan transaction artifact requires manual inspection: " + ", ".join(artifacts))
    try:
        lock_bytes = root.read_bytes(LOCK)
        lock_stat = root.lstat(LOCK)
        metadata = json.loads(lock_bytes)
    except Exception as exc:
        raise InstallError(f"invalid transaction lock requires manual recovery: {exc}") from exc
    transaction_id = str(metadata.get("transaction_id", ""))
    journal_name = str(metadata.get("journal_name", ""))
    required = (
        transaction_id and journal_name == f"{JOURNAL_PREFIX}{transaction_id}"
        and isinstance(metadata.get("nonce"), str) and metadata["nonce"]
        and isinstance(metadata.get("recovery_of"), list)
        and metadata.get("boot_id") and metadata.get("process_start")
    )
    if not required:
        raise InstallError("invalid transaction lock metadata requires manual recovery")
    if str(metadata.get("host", "")) != socket.gethostname():
        raise InstallError("installer lock belongs to another host; manual recovery required")
    current_boot_id = boot_identity()
    lock_boot_id = str(metadata.get("boot_id", ""))
    if current_boot_id == "unknown" or lock_boot_id != current_boot_id:
        raise InstallError("installer lock belongs to another boot/session; manual recovery required")
    if process_alive(
        int(metadata.get("pid", 0)), str(metadata.get("host", "")),
        str(metadata.get("boot_id", "")), str(metadata.get("process_start", "")),
    ):
        raise InstallError("target is busy: live installer lock")
    unexpected = [name for name in artifacts if (
        name.startswith(JOURNAL_PREFIX) and name != journal_name
    ) or name.startswith(LOCK + ".stale.") or (
        name.startswith(TMP_PREFIX) and not name.startswith(TMP_PREFIX + transaction_id)
    )]
    if metadata["recovery_of"]:
        raise InstallError("nested recovery ownership requires manual recovery")
    if unexpected:
        raise InstallError("multiple or stale transactions require manual recovery: " + ", ".join(unexpected))
    candidates = [name for name in artifacts if name.startswith(LOCK + ".candidate.")]
    for name in candidates:
        if sha256(root.read_bytes(name)) != sha256(lock_bytes):
            raise InstallError(f"candidate lock identity mismatch: {name}")
    current_stat = root.lstat(LOCK)
    if current_stat is None or (current_stat.st_dev, current_stat.st_ino) != (lock_stat.st_dev, lock_stat.st_ino):
        raise InstallError("canonical lock identity changed during recovery")
    if sha256(root.read_bytes(LOCK)) != sha256(lock_bytes):
        raise InstallError("canonical lock content changed during recovery")
    state = None
    if root.exists(journal_name):
        try:
            state = json.loads(root.read_bytes(journal_name))
        except Exception as exc:
            raise InstallError(f"invalid transaction journal requires manual recovery: {exc}") from exc
        if state.get("transaction_id") != transaction_id:
            raise InstallError("journal transaction identity mismatch")
    stale_name = f"{LOCK}.stale.{metadata['nonce']}"
    root.rename(LOCK, stale_name)
    stale_stat = root.lstat(stale_name)
    if stale_stat is None or (stale_stat.st_dev, stale_stat.st_ino) != (lock_stat.st_dev, lock_stat.st_ino):
        raise InstallError("stale lock publication identity mismatch")
    if state is None:
        for name in candidates:
            if root.exists(name):
                root.unlink(name)
        root.unlink(stale_name)
        return
    tx = Transaction(root)
    tx.transaction_id = transaction_id
    tx.journal_name = journal_name
    tx.state = state
    tx.locked = True
    tx.lock_name = stale_name
    if state.get("phase") == "committed":
        root.unlink(journal_name)
        for item in state.get("temps", []):
            name = item.get("path") if isinstance(item, dict) else item
            if name and root.exists(name):
                data = root.read_bytes(name)
                st = root.lstat(name)
                if isinstance(item, dict) and (
                    sha256(data) != item.get("sha256") or stat.S_IMODE(st.st_mode) != item.get("mode")
                    or (item.get("inode") is not None and (st.st_dev, st.st_ino) != (item["device"], item["inode"]))
                ):
                    raise InstallError(f"committed temp changed; manual recovery required: {name}")
                root.unlink(name)
        root.unlink(stale_name)
        return
    tx.rollback()


def source_files(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, bytes]]:
    entries: dict[str, dict[str, Any]] = {}
    payloads: dict[str, bytes] = {}

    source_root = SafeRoot(root)

    def add(source: str, target: str, component: str) -> None:
        data = source_root.read_bytes(source)
        target = canonical_rel(target)
        payloads[target] = data
        entries[target] = {"component": component, "source_sha256": sha256(data), "owners": ["codex"], "protection": None}

    try:
        for source in source_root.walk_regular_files("core/skills"):
            add(source, f".claude/{source.removeprefix('core/')}", "shared_claude_runtime")
        for name in ("ai-plc-system.md", "ai-plc-session.md", "ai-plc-adaptive.md"):
            add(f"core/rules/{name}", f".claude/rules/{name}", "shared_claude_runtime")
        for name in ("init_db.py", "plc_query.py", "sync.py", "README.md"):
            add(f"core/db/{name}", f".claude/db/{name}", "shared_claude_runtime")
        for source in source_root.walk_regular_files("codex/skills/ai-plc"):
            add(source, f".agents/skills/ai-plc/{source.removeprefix('codex/skills/ai-plc/')}", "codex_adapter")
        for source in source_root.walk_regular_files("core/skills/utility"):
            add(source, f".agents/skills/utility/{source.removeprefix('core/skills/utility/')}", "codex_adapter")
        return entries, payloads
    finally:
        source_root.close()


def extract_region(text: bytes, start: str, end: str) -> bytes:
    decoded = text.decode("utf-8")
    if decoded.count(start) != 1 or decoded.count(end) != 1:
        raise InstallError("managed region markers are missing or duplicated")
    before, rest = decoded.split(start, 1)
    middle, after = rest.split(end, 1)
    if before is None or after is None:
        raise InstallError("invalid managed region")
    return (start + middle + end).encode()


def merge_region(existing: bytes | None, template: bytes) -> bytes:
    template_text = template.decode("utf-8")
    if template_text.count(CODEX_START) != 1 or template_text.count(CODEX_END) != 1:
        raise InstallError("Codex AGENTS template must have exactly one marker pair")
    if existing is None:
        return template
    text = existing.decode("utf-8")
    starts, ends = text.count(CODEX_START), text.count(CODEX_END)
    if starts == 0 and ends == 0:
        separator = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        return (text + separator + template_text).encode()
    if starts != 1 or ends != 1:
        raise InstallError("existing AGENTS.md has invalid Codex marker count")
    prefix, rest = text.split(CODEX_START, 1)
    _, suffix = rest.split(CODEX_END, 1)
    template_region = extract_region(template, CODEX_START, CODEX_END).decode("utf-8")
    return (prefix + template_region + suffix).encode()


def secure_source_read(distribution: Path, rel: str) -> bytes:
    with SafeRoot(distribution) as source_root:
        return source_root.read_bytes(rel)


def create_db_bytes(init_script: bytes) -> bytes:
    """Run the canonical schema builder in memory; never write outside target."""
    namespace: dict[str, Any] = {"__name__": "ai_plc_init_db", "__file__": "<verified core/db/init_db.py>"}
    exec(compile(init_script, namespace["__file__"], "exec"), namespace)
    connection = sqlite3.connect(":memory:")
    try:
        namespace["create_schema"](connection)
        return connection.serialize()
    finally:
        connection.close()


def semver(value: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(value.strip())
    if not match:
        raise InstallError(f"invalid SemVer: {value!r}")
    return tuple(int(x) for x in match.groups())  # type: ignore[return-value]


def load_manifest(root: SafeRoot) -> dict[str, Any] | None:
    if not root.exists(MANIFEST):
        return None
    try:
        data = json.loads(root.read_bytes(MANIFEST))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InstallError(f"invalid {MANIFEST}: {exc}") from exc
    if data.get("schema_version") != 1 or data.get("status") not in ("active", "detached"):
        raise InstallError(f"unsupported {MANIFEST} schema/state")
    return data


def component_fingerprint(entries: dict[str, dict[str, Any]], component: str) -> str:
    lines = [f"file:{path}:{item['source_sha256']}" for path, item in entries.items() if item["component"] == component]
    return sha256(("\n".join(sorted(lines)) + "\n").encode())


def parse_legacy_catalog(content: bytes) -> dict[str, dict[str, Any]]:
    """Parse the deliberately restricted catalog schema without a YAML dependency."""
    result: dict[str, dict[str, Any]] = {}
    environment: str | None = None
    section: str | None = None
    current: str | None = None
    for raw in content.decode().splitlines():
        if re.fullmatch(r"  (cc|cursor):", raw):
            environment = raw.strip()[:-1]
            result[environment] = {"managed_files": {}, "managed_regions": {}}
            section = current = None
            continue
        if environment is None:
            continue
        if re.fullmatch(r"    (managed_files|managed_regions):.*", raw):
            section = raw.strip().split(":", 1)[0]
            current = None
            continue
        match = re.fullmatch(r'      "([^"]+)":', raw)
        if match and section:
            current = match.group(1)
            result[environment][section][current] = {}
            continue
        field = re.fullmatch(r'        ([a-z0-9_]+): "([^"]*)"', raw)
        if field and section and current:
            result[environment][section][current][field.group(1)] = field.group(2)
    return result


def legacy_state(root: SafeRoot, catalog_content: bytes) -> dict[str, Any]:
    catalog = parse_legacy_catalog(catalog_content)
    detected: list[str] = []
    if root.exists(".claude/commands/01-collection.md") and root.exists("CLAUDE.md") and root.exists("AGENTS.md"):
        detected.append("cc")
    if root.exists(".cursor/skills/ai-plc/01-collection/SKILL.md") and root.exists(".cursor/rules/ai-plc-system.mdc"):
        detected.append("cursor")
    if not detected:
        raise InstallError("legacy markers do not identify CC or Cursor")
    files: dict[str, dict[str, Any]] = {}
    regions: dict[str, dict[str, Any]] = {}
    for env in detected:
        inventory = catalog.get(env)
        if not inventory:
            raise InstallError(f"legacy catalog has no {env} inventory")
        for target, item in inventory["managed_files"].items():
            if not root.exists(target):
                raise InstallError(f"legacy {env} file missing: {target}")
            actual = sha256(root.read_bytes(target))
            expected = item.get("source_sha256")
            if actual != expected:
                raise InstallError(f"legacy {env} file changed: {target}")
            files[target] = {"source_sha256": expected, "owner": env}
        for region_id, item in inventory["managed_regions"].items():
            target = item.get("path")
            if not target or not root.exists(target):
                raise InstallError(f"legacy {env} region file missing: {region_id}")
            actual = sha256(extract_region(root.read_bytes(target), item["start_marker"], item["end_marker"]))
            expected = item.get("content_sha256")
            if actual != expected:
                raise InstallError(f"legacy {env} region changed: {region_id}")
            regions[region_id] = {**item, "owner": env}
    return {"environments": detected, "managed_files": files, "managed_regions": regions}


def plan_install(distribution: Path, root: SafeRoot, migrate_legacy: str | None,
                 lock_held: bool = False) -> dict[str, Any]:
    version = secure_source_read(distribution, VERSION_MARKER).decode().strip()
    semver(version)
    entries, payloads = source_files(distribution)
    manifest = load_manifest(root)
    conflicts: list[str] = []
    writes: list[str] = []
    preserved: list[str] = []
    legacy: dict[str, Any] | None = None

    artifacts = control_artifacts(root)
    if artifacts and not lock_held:
        conflicts.append("target is busy or needs recovery: " + ", ".join(artifacts))

    if manifest and manifest.get("status") == "detached":
        conflicts.append("manifest is detached; resolve residuals before install")
    if migrate_legacy:
        catalog_rel = f"migration/legacy-releases/{migrate_legacy}.yaml"
        try:
            catalog_content = secure_source_read(distribution, catalog_rel)
        except (FileNotFoundError, InstallError):
            conflicts.append(f"legacy catalog not found: {migrate_legacy}")
            catalog_content = None
        if catalog_content is not None and migrate_legacy == version:
            conflicts.append("legacy migration requires a newer distribution version; update .ai-plc-version first")
        elif catalog_content is not None and manifest:
            conflicts.append("legacy migration requires a target without an install manifest")
        elif catalog_content is not None:
            try:
                legacy = legacy_state(root, catalog_content)
            except InstallError as exc:
                conflicts.append(str(exc))
    old_files = (manifest or {}).get("managed_files", {})
    for path, item in entries.items():
        if not root.exists(path):
            writes.append(path)
            continue
        current = sha256(root.read_bytes(path))
        old = old_files.get(path)
        if old:
            if current != old.get("source_sha256"):
                conflicts.append(f"user-modified managed file: {path}")
            elif current != item["source_sha256"]:
                writes.append(path)
        elif legacy and path in legacy["managed_files"] and current == legacy["managed_files"][path]["source_sha256"]:
            writes.append(path)
        elif current == item["source_sha256"]:
            preserved.append(path)
        else:
            conflicts.append(f"unmanaged file collision: {path}")

    template = secure_source_read(distribution, "codex/AGENTS.md.template")
    agents_existing = root.read_bytes("AGENTS.md") if root.exists("AGENTS.md") else None
    try:
        if agents_existing and CODEX_START.encode() in agents_existing:
            current_region_hash = sha256(extract_region(agents_existing, CODEX_START, CODEX_END))
            old_region = (manifest or {}).get("managed_regions", {}).get("AGENTS.md#ai-plc-codex")
            if old_region and current_region_hash != old_region.get("content_sha256"):
                raise InstallError("user-modified managed Codex region")
            if not old_region and current_region_hash != sha256(extract_region(template, CODEX_START, CODEX_END)):
                raise InstallError("unmanaged Codex marker region; use verified legacy migration")
        agents_result = merge_region(agents_existing, template)
        if agents_existing != agents_result:
            writes.append("AGENTS.md#ai-plc-codex")
    except InstallError as exc:
        conflicts.append(f"AGENTS.md: {exc}")
        agents_result = b""

    seed_refs = {
        ".claude/wiki/wiki.md": "templates/wiki/wiki.md",
        ".claude/wiki/index.md": "templates/wiki/index.md",
        ".claude/wiki/log.md": "templates/wiki/log.md",
        ".claude/wiki/queries/README.md": "templates/wiki/queries/README.md",
        ".claude/wiki/sources/README.md": "templates/wiki/sources/README.md",
    }
    seeds: dict[str, bytes] = {}
    for target, source in seed_refs.items():
        try:
            seeds[target] = secure_source_read(distribution, source)
        except (FileNotFoundError, InstallError):
            conflicts.append(f"missing source seed: {source}")
        if root.exists(target):
            preserved.append(target)
        else:
            writes.append(target)
    if root.exists(".claude/db/ai_plc.db"):
        preserved.append(".claude/db/ai_plc.db")
    else:
        writes.append(".claude/db/ai_plc.db")

    if root.exists(VERSION_MARKER):
        marker_data = root.read_bytes(VERSION_MARKER)
        expected_marker = (manifest or {}).get("version_marker", {}).get("expected_sha256")
        if expected_marker and sha256(marker_data) != expected_marker:
            conflicts.append(f"user-modified managed file: {VERSION_MARKER}")
        current_version = marker_data.decode().strip()
        try:
            if semver(current_version) > semver(version):
                conflicts.append(f"downgrade refused: installed {current_version} > source {version}")
        except InstallError as exc:
            conflicts.append(str(exc))
    else:
        writes.append(VERSION_MARKER)

    components = {
        "shared_claude_runtime": {
            "version": version, "owners": ["codex"],
            "inventory_sha256": component_fingerprint(entries, "shared_claude_runtime"),
        },
        "codex_adapter": {
            "version": version, "owners": ["codex"],
            "inventory_sha256": component_fingerprint(entries, "codex_adapter"),
        },
    }
    if manifest:
        for name, component in components.items():
            old = manifest.get("components", {}).get(name)
            if not old:
                continue
            old_version = old.get("version", "")
            try:
                if semver(version) < semver(old_version):
                    conflicts.append(f"component downgrade refused: {name} {old_version} -> {version}")
                if version == old_version and old.get("inventory_sha256") != component["inventory_sha256"]:
                    conflicts.append(f"mutable release refused: {name} {version}")
            except InstallError as exc:
                conflicts.append(str(exc))

    stale_files: list[str] = []
    for path, old in old_files.items():
        owners = set(old.get("owners", []))
        if "codex" not in owners or path in entries:
            continue
        if root.exists(path) and sha256(root.read_bytes(path)) != old.get("source_sha256"):
            conflicts.append(f"user-modified stale managed file: {path}")
        else:
            stale_files.append(path)
            writes.append(f"DELETE:{path}")

    region_hash = sha256(extract_region(template, CODEX_START, CODEX_END))
    new_manifest = manifest or {"schema_version": 1, "environments": {}, "components": {}, "managed_files": {}, "managed_regions": {}, "residuals": []}
    new_manifest = json.loads(json.dumps(new_manifest))
    new_manifest["status"] = "active"
    if legacy:
        for env in legacy["environments"]:
            new_manifest["environments"][env] = {"version": migrate_legacy}
        for path, item in legacy["managed_files"].items():
            if path == VERSION_MARKER:
                continue
            owner = item["owner"]
            component = "cursor_runtime" if owner == "cursor" else (
                "shared_claude_runtime" if path.startswith((".claude/skills/", ".claude/rules/", ".claude/db/")) else "cc_runtime"
            )
            new_manifest["managed_files"][path] = {
                "component": component, "source_sha256": item["source_sha256"],
                "owners": [owner], "protection": None,
            }
        for region_id, item in legacy["managed_regions"].items():
            new_manifest["managed_regions"][region_id] = {
                "path": item["path"], "component": "cc_runtime",
                "start_marker": item["start_marker"], "end_marker": item["end_marker"],
                "content_sha256": item["content_sha256"], "owners": [item["owner"]], "protection": None,
            }
    new_manifest["environments"]["codex"] = {"version": version}
    for name, component in components.items():
        old_owners = new_manifest.get("components", {}).get(name, {}).get("owners", [])
        component["owners"] = sorted(set(old_owners) | {"codex"})
        new_manifest["components"][name] = component
    for path, item in entries.items():
        old_owners = new_manifest.get("managed_files", {}).get(path, {}).get("owners", [])
        item = dict(item)
        item["owners"] = sorted(set(old_owners) | {"codex"})
        new_manifest["managed_files"][path] = item
    for path in list(new_manifest["managed_files"]):
        if path in entries:
            continue
        item = new_manifest["managed_files"][path]
        owners = set(item.get("owners", []))
        if "codex" in owners:
            del new_manifest["managed_files"][path]
    new_manifest["managed_regions"]["AGENTS.md#ai-plc-codex"] = {
        "path": "AGENTS.md", "component": "codex_adapter", "start_marker": CODEX_START,
        "end_marker": CODEX_END, "content_sha256": region_hash, "owners": ["codex"], "protection": None,
    }
    if legacy:
        for component_name in ("cc_runtime", "cursor_runtime"):
            component_entries = [
                f"file:{path}:{item['source_sha256']}"
                for path, item in new_manifest["managed_files"].items()
                if item.get("component") == component_name
            ] + [
                f"region:{region_id}:{item['content_sha256']}"
                for region_id, item in new_manifest["managed_regions"].items()
                if item.get("component") == component_name
            ]
            if component_entries:
                owners = sorted({
                    owner for item in new_manifest["managed_files"].values()
                    if item.get("component") == component_name for owner in item.get("owners", [])
                } | {
                    owner for item in new_manifest["managed_regions"].values()
                    if item.get("component") == component_name for owner in item.get("owners", [])
                })
                new_manifest["components"][component_name] = {
                    "version": migrate_legacy, "owners": owners,
                    "inventory_sha256": sha256(("\n".join(sorted(component_entries)) + "\n").encode()),
                }
    new_manifest["version_marker"] = {"path": VERSION_MARKER, "expected_sha256": sha256((version + "\n").encode())}

    return {
        "version": version, "entries": entries, "payloads": payloads, "manifest": new_manifest,
        "writes": sorted(set(writes)), "stale_files": sorted(stale_files),
        "preserved": sorted(set(preserved)), "conflicts": sorted(set(conflicts)),
        "agents": agents_result, "seeds": seeds,
    }


def execute_plan(distribution: Path, root: SafeRoot, migrate_legacy: str | None) -> int:
    tx = Transaction(root)
    tx.acquire()
    try:
        validate_or_consume_tombstone(root, mutate=True)
        assert_fresh_transaction_artifacts(root, tx)
        plan = plan_install(distribution, root, migrate_legacy, lock_held=True)
    except Exception:
        tx.rollback()
        raise
    if plan["conflicts"]:
        for conflict in plan["conflicts"]:
            print(f"[CONFLICT] {conflict}", file=sys.stderr)
        tx.rollback()
        raise InstallError(f"preflight failed with {len(plan['conflicts'])} conflict(s); target unchanged")
    changed = 0
    try:
        for path in plan["stale_files"]:
            if root.delete_transactional(path, tx):
                changed += 1
        for path, data in plan["payloads"].items():
            if root.write_atomic(path, data, tx):
                changed += 1
        if root.write_atomic("AGENTS.md", plan["agents"], tx):
            changed += 1
        for path, data in plan["seeds"].items():
            if not root.exists(path):
                if root.write_atomic(path, data, tx):
                    changed += 1
        if not root.exists(".claude/db/ai_plc.db"):
            db = create_db_bytes(secure_source_read(distribution, "core/db/init_db.py"))
            if root.write_atomic(".claude/db/ai_plc.db", db, tx):
                changed += 1
        version_data = (plan["version"] + "\n").encode()
        if root.write_atomic(VERSION_MARKER, version_data, tx):
            changed += 1
        manifest_data = json.dumps(plan["manifest"], ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
        if root.write_atomic(MANIFEST, manifest_data, tx):
            changed += 1
        tx.commit()
    except Exception:
        tx.rollback()
        raise
    print(f"[OK] Codex install committed: {changed} changed file(s)")
    return changed


def determine_target(raw: str | None) -> Path:
    if raw:
        target = Path(raw)
    else:
        try:
            import subprocess
            value = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL).strip()
            target = Path(value)
        except Exception:
            target = Path.cwd()
    if not target.exists() or not target.is_dir():
        raise InstallError(f"target directory does not exist: {target}")
    return Path(os.path.abspath(target))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="install-codex.sh", description="Install AI-PLC for Codex")
    p.add_argument("--target", metavar="PATH", help="installation root (defaults to git root or cwd)")
    p.add_argument("--dry-run", action="store_true", help="show the plan without changing target")
    p.add_argument("--plan-only", action="store_true", help="emit the machine-readable plan without changing target")
    p.add_argument("--migrate-legacy", metavar="VERSION", help="explicitly adopt a verified legacy release")
    p.add_argument("--yes", action="store_true", help="confirm a non-interactive legacy migration")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    distribution = Path(__file__).resolve().parent.parent
    target = determine_target(args.target)
    is_git = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "--is-inside-work-tree"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0
    if not is_git and not (args.dry_run or args.plan_only):
        print(f"[WARN] target is not a git worktree: {target}", file=sys.stderr)
        if not args.yes and not sys.stdin.isatty():
            raise InstallError("non-git target requires --yes or interactive confirmation")
        if not args.yes:
            answer = input("Continue without initializing git? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                raise InstallError("non-git installation was not confirmed")
    if args.migrate_legacy and not args.yes and not sys.stdin.isatty():
        raise InstallError("--migrate-legacy in non-interactive mode also requires --yes")
    if args.migrate_legacy and not args.yes and sys.stdin.isatty():
        answer = input(f"Migrate verified legacy release {args.migrate_legacy}? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            raise InstallError("legacy migration was not confirmed")
    with SafeRoot(target) as root:
        if not (args.dry_run or args.plan_only):
            recover_if_needed(root)
        else:
            validate_or_consume_tombstone(root, mutate=False)
        plan = plan_install(distribution, root, args.migrate_legacy)
        summary = {k: plan[k] for k in ("version", "writes", "preserved", "conflicts")}
        if args.dry_run or args.plan_only:
            print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
            return 1 if plan["conflicts"] else 0
        execute_plan(distribution, root, args.migrate_legacy)
    print("Next: restart Codex if needed, then run $01-collection")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2)
    except OSError as exc:
        print(f"[ERROR] filesystem safety check failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
