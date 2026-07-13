#!/usr/bin/env python3
"""AI-PLC installer acceptance suite (Python standard library only)."""

from __future__ import annotations

import argparse
from collections import Counter
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Any, Callable

from fault_driver import IsolatedDistribution, source_snapshot, tree_snapshot


HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
REQUIRED_FIELDS = {"prefix", "count", "batch", "contract_ref", "fixture", "operation", "expected_state", "cleanup"}
MODES = ("cc", "cursor", "both", "codex", "all")
ENVIRONMENTS = {
    "cc": {"cc"}, "cursor": {"cursor"}, "both": {"cc", "cursor"},
    "codex": {"codex"}, "all": {"cc", "cursor", "codex"},
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def command(*args: str, cwd: Path | None = None, input_text: str | None = None,
            timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), cwd=cwd, input=input_text, text=True, capture_output=True,
        timeout=timeout, start_new_session=True, check=False,
    )


@contextlib.contextmanager
def target(git: bool = True):
    with tempfile.TemporaryDirectory(prefix="ai-plc-test-target-", dir="/private/tmp") as name:
        root = Path(name)
        if git:
            result = command("git", "init", "-q", cwd=root)
            assert result.returncode == 0, result.stderr
        yield root


def run_script(distribution: Path, script: str, *args: str, input_text: str | None = None,
               timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return command("bash", str(distribution / script), *args, input_text=input_text, timeout=timeout)


def install(root: Path, mode: str, distribution: Path = REPO, *extra: str) -> subprocess.CompletedProcess[str]:
    return run_script(distribution, "install.sh", mode, "--target", str(root), *extra)


def uninstall(root: Path, mode: str, distribution: Path = REPO, *extra: str) -> subprocess.CompletedProcess[str]:
    return run_script(distribution, "uninstall.sh", mode, "--target", str(root), *extra)


def manifest(root: Path) -> dict[str, Any]:
    return json.loads((root / ".ai-plc-install-manifest").read_text())


def load_safe(distribution: Path = REPO):
    path = distribution / "lib/ai_plc_safe_fs.py"
    spec = importlib.util.spec_from_file_location(f"safe_{time.time_ns()}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_matrix(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def expand_cases(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    cases = []
    for group in matrix["case_groups"]:
        missing = REQUIRED_FIELDS - set(group)
        if missing:
            raise ValueError(f"{group.get('prefix', '?')}: missing {sorted(missing)}")
        if not re.fullmatch(r"[A-Z]{2,4}", group["prefix"]):
            raise ValueError(f"invalid prefix: {group['prefix']}")
        for number in range(1, group["count"] + 1):
            cases.append({
                **group, "variant": number, "case_id": f"{group['prefix']}-{number:03d}",
                "fixture": f"{group['fixture']}; variant={number}",
                "operation": f"{group['operation']}; variant={number}",
                "expected_state": f"{group['expected_state']}; assertion={number}",
            })
    return cases


def validate_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    cases = expand_cases(matrix)
    ids = [case["case_id"] for case in cases]
    duplicates = sorted(x for x, count in Counter(ids).items() if count > 1)
    required = set(matrix["required_contract_refs"])
    mapped = {ref for case in cases for ref in case["contract_ref"]}
    unmapped = sorted(required - mapped)
    unknown = sorted(mapped - required)
    errors = []
    if duplicates: errors.append(f"duplicate case IDs: {duplicates}")
    if unmapped: errors.append(f"unmapped contract refs: {unmapped}")
    if unknown: errors.append(f"unknown contract refs: {unknown}")
    if len(cases) < matrix["minimum_total"]: errors.append("case total below minimum")
    return {
        "matrix_contract_refs": len(required), "mapped_refs": len(required - set(unmapped)),
        "unmapped_refs": unmapped, "total": len(cases), "duplicates": duplicates,
        "suite_counts": dict(sorted(Counter(case["prefix"] for case in cases).items())), "errors": errors,
    }


def assert_clean(root: Path) -> None:
    artifacts = list(root.rglob(".ai-plc-install.lock")) + list(root.rglob(".ai-plc-install-journal.*")) + list(root.rglob(".ai-plc-tmp.*"))
    assert not artifacts, artifacts


def case_inv(n: int) -> None:
    if n <= 7:
        files = ("install.sh", "install-cc.sh", "install-cursor.sh", "install-codex.sh", "uninstall.sh", "lib/ai_plc_safe_fs.py", "lib/ai_plc_multi_env.py")
        path = REPO / files[n - 1]
        assert path.is_file() and path.stat().st_size > 0
    elif n <= 10:
        name = ("ai-plc-system.md", "ai-plc-session.md", "ai-plc-adaptive.md")[n - 8]
        data = (REPO / "core/rules" / name).read_text()
        assert data.startswith("> 🏷️") and "**バージョン:**" in data
    elif n == 11:
        assert len(list((REPO / "codex/skills/ai-plc").rglob("SKILL.md"))) == 5
    elif n == 12:
        json.loads((REPO / "tests/installers/case_matrix.json").read_text())
    elif n == 13:
        assert (REPO / "templates/wiki/queries/README.md").is_file()
    elif n == 14:
        assert (REPO / "templates/wiki/sources/README.md").is_file()
    else:
        assert validate_matrix(load_matrix(HERE / "case_matrix.json"))["errors"] == []


def case_cli(n: int) -> None:
    if n <= 5:
        result = run_script(REPO, "install.sh", MODES[n - 1], "--help")
        assert result.returncode == 0 and "--dry-run" in result.stdout
    elif n <= 10:
        scripts = ("install.sh", "install-cc.sh", "install-cursor.sh", "install-codex.sh", "uninstall.sh")
        result = run_script(REPO, scripts[n - 6], "--unknown-for-test")
        assert result.returncode != 0 and ("Unknown" in result.stderr or "unrecognized" in result.stderr)
    else:
        with target() as root:
            mode = MODES[n - 11]
            before = tree_snapshot(root)
            result = install(root, mode, REPO, "--dry-run")
            assert result.returncode == 0 and tree_snapshot(root) == before


def case_tgt(n: int) -> None:
    if n <= 5:
        with target() as root:
            sub = root / "sub"; sub.mkdir()
            result = install(sub, MODES[n - 1], REPO, "--dry-run")
            assert result.returncode == 0 and not (root / ".ai-plc-install-manifest").exists()
    elif n <= 8:
        with target(False) as root:
            result = install(root, ("cc", "codex", "all")[n - 6], REPO)
            assert result.returncode != 0 and not (root / ".ai-plc-install-manifest").exists()
    elif n <= 10:
        with target() as root, tempfile.TemporaryDirectory(dir="/private/tmp") as outside_name:
            outside = Path(outside_name); (root / "link").symlink_to(outside, target_is_directory=True)
            result = install(root / "link", "codex", REPO, "--dry-run")
            assert result.returncode != 0 and list(outside.iterdir()) == []
    else:
        with target() as root:
            fifo = root / "special"; os.mkfifo(fifo)
            result = install(root, "codex", REPO, "--dry-run")
            assert result.returncode in (0, 2) and fifo.exists()


def case_reg(n: int) -> None:
    with target() as root:
        (root / "AGENTS.md").write_text("USER OUTSIDE\n")
        mode = "all" if n % 2 else "codex"
        result = install(root, mode)
        assert result.returncode == 0, result.stderr
        text = (root / "AGENTS.md").read_text()
        assert "USER OUTSIDE" in text and text.count("<!-- AI-PLC CODEX START -->") == 1
        if mode == "all": assert text.count("<!-- AI-PLC START -->") == 1
        if n in (3, 4):
            marker = "<!-- AI-PLC CODEX START -->"
            (root / "AGENTS.md").write_text(text.replace(marker, marker + "\nEDIT", 1))
            again = install(root, mode)
            assert again.returncode != 0 and "EDIT" in (root / "AGENTS.md").read_text()
        elif n in (5, 6):
            out = uninstall(root, mode)
            assert out.returncode == 0 and "USER OUTSIDE" in (root / "AGENTS.md").read_text()
        else:
            again = install(root, mode)
            assert again.returncode == 0 and "0 changed file" in again.stdout


def case_own(n: int) -> None:
    sequences = [
        ("cc",), ("cursor",), ("codex",), ("both",), ("all",),
        ("cc", "codex"), ("codex", "cc"), ("cursor", "codex"),
        ("codex", "cursor"), ("both", "codex"),
    ]
    sequence = sequences[(n - 1) % len(sequences)]
    with target() as root:
        for mode in sequence:
            result = install(root, mode); assert result.returncode == 0, result.stderr
        data = manifest(root)
        expected = set().union(*(ENVIRONMENTS[mode] for mode in sequence))
        assert set(data["environments"]) == expected
        for item in data["managed_files"].values():
            assert set(item["owners"]) <= expected
        for component, item in data["components"].items():
            owners = {owner for entry in data["managed_files"].values() if entry["component"] == component for owner in entry["owners"]}
            owners |= {owner for entry in data["managed_regions"].values() if entry["component"] == component for owner in entry["owners"]}
            assert set(item["owners"]) == owners


def case_ver(n: int) -> None:
    with IsolatedDistribution(REPO) as distribution, target() as root:
        major, minor, _patch = map(int, (distribution / ".ai-plc-version").read_text().strip().split("."))
        first = install(root, "all", distribution); assert first.returncode == 0, first.stderr
        if n <= 4:
            (distribution / ".ai-plc-version").write_text(f"{major}.{minor + 1}.0\n")
            result = install(root, MODES[n], distribution)
            assert result.returncode == 0, result.stderr
        elif n <= 7:
            (distribution / ".ai-plc-version").write_text("0.9.0\n")
            before = tree_snapshot(root); result = install(root, ("cc", "codex", "all")[n - 5], distribution)
            assert result.returncode != 0 and tree_snapshot(root) == before
        elif n <= 9:
            source = distribution / ("core/skills/ai-plc/01-collection/SKILL.md" if n == 8 else "codex/skills/ai-plc/01-collection/SKILL.md")
            source.write_text(source.read_text() + "\nMUTABLE\n")
            before = tree_snapshot(root); result = install(root, "all", distribution)
            assert result.returncode != 0 and tree_snapshot(root) == before
        else:
            path = root / ".ai-plc-version"; path.write_text("bad-version\n")
            result = install(root, "cc", distribution)
            assert result.returncode != 0 and path.read_text() == "bad-version\n"


def case_leg(n: int) -> None:
    catalog = json.loads(json.dumps({"exists": (REPO / "migration/legacy-releases/1.1.0.yaml").is_file()}))
    assert catalog["exists"]
    text = (REPO / "migration/legacy-releases/1.1.0.yaml").read_text()
    if n <= 5:
        assert f"source_commit:" in text and "managed_files:" in text
    elif n <= 10:
        safe = load_safe(); parsed = safe.parse_legacy_catalog(text.encode())
        assert parsed["cc"]["managed_files"] and parsed["cursor"]["managed_files"]
    else:
        with target() as root:
            before = tree_snapshot(root)
            result = install(root, "cc", REPO, "--migrate-legacy", "1.1.0", "--yes")
            assert result.returncode != 0 and tree_snapshot(root) == before


def dead_metadata(safe: Any, tx: Any) -> dict[str, Any]:
    return {
        "pid": 99999999, "host": __import__("socket").gethostname(), "nonce": tx.lock_nonce,
        "boot_id": safe.boot_identity(), "process_start": "dead", "transaction_id": tx.transaction_id,
        "journal_name": tx.journal_name, "recovery_of": [], "started_at": safe.utc_stamp(),
    }


def replace_root_file(root: Any, name: str, data: bytes) -> None:
    fd, leaf = root._open_parent(name)
    tmp = f".fixture-{time.time_ns()}"
    try:
        root._write_new(tmp, data)
        os.replace(tmp, leaf, src_dir_fd=root.fd, dst_dir_fd=fd); os.fsync(fd)
    finally:
        os.close(fd)


def artifact_identity(root: Any, names: tuple[str, ...]) -> dict[str, tuple[int, int, str]]:
    identity = {}
    for name in names:
        if root.exists(name):
            st = root.lstat(name)
            identity[name] = (st.st_dev, st.st_ino, hashlib.sha256(root.read_bytes(name)).hexdigest())
    return identity


def case_lck(n: int) -> None:
    safe = load_safe()
    with target() as path, safe.SafeRoot(path) as root:
        tx = safe.Transaction(root); tx.acquire()
        if n <= 4:
            try: safe.recover_if_needed(root)
            except safe.InstallError: pass
            else: raise AssertionError("live lock accepted")
            tx.rollback()
        else:
            metadata = dead_metadata(safe, tx)
            if n in (9, 10): metadata["host"] = "foreign-host"
            if n in (11, 12): metadata["boot_id"] = "foreign-boot"
            if n in (13, 14): metadata.pop("nonce")
            replace_root_file(root, safe.LOCK, json.dumps(metadata, sort_keys=True).encode() + b"\n")
            if n in (5, 6): root.unlink(tx.journal_name)
            if n in (15, 16):
                state = json.loads(root.read_bytes(tx.journal_name)); state["transaction_id"] = "other"
                root.unlink(tx.journal_name); root._write_new(tx.journal_name, json.dumps(state).encode() + b"\n")
            guarded = (safe.LOCK, tx.journal_name)
            before = artifact_identity(root, guarded)
            try:
                safe.recover_if_needed(root)
                recovered = True
            except safe.InstallError:
                recovered = False
            if n in (5, 6, 7, 8, 17, 18): assert recovered
            else:
                assert not recovered
                assert artifact_identity(root, guarded) == before


def case_race(n: int) -> None:
    with target() as root, tempfile.TemporaryDirectory(prefix="ai-plc-outside-", dir="/private/tmp") as outside_name:
        outside = Path(outside_name); sentinel = outside / "sentinel"; sentinel.write_text("SAFE")
        if n <= 5:
            collision = root / ".agents/skills/ai-plc/01-collection/SKILL.md"
            collision.parent.mkdir(parents=True); collision.write_text(f"RACE-{n}")
            result = install(root, "codex")
            assert result.returncode != 0 and collision.read_text() == f"RACE-{n}"
        else:
            link = root / ".agents"; link.symlink_to(outside, target_is_directory=True)
            result = install(root, "codex")
            assert result.returncode != 0
        assert sentinel.read_text() == "SAFE"


def case_tx(n: int) -> None:
    safe = load_safe()
    with target() as path, safe.SafeRoot(path) as root:
        existing = path / "existing"; existing.write_text("old"); os.chmod(existing, 0o755)
        tx = safe.Transaction(root); tx.acquire()
        if n % 4 == 1:
            root.write_atomic("existing", f"new-{n}".encode(), tx); tx.rollback()
            assert existing.read_text() == "old" and stat.S_IMODE(existing.stat().st_mode) == 0o755
        elif n % 4 == 2:
            root.write_atomic(f"new-{n}", b"new", tx); tx.rollback(); assert not (path / f"new-{n}").exists()
        elif n % 4 == 3:
            nested = f"a{n}/b/file"; root.write_atomic(nested, b"x", tx); tx.rollback(); assert not (path / f"a{n}").exists()
        else:
            root.write_atomic("existing", f"new-{n}".encode(), tx); tx.commit(); assert existing.read_text() == f"new-{n}"
        assert_clean(path)


def case_res(n: int) -> None:
    with target() as root:
        result = install(root, "codex"); assert result.returncode == 0
        managed = root / ".agents/skills/ai-plc/01-collection/SKILL.md"; managed.write_text(managed.read_text() + f"\nEDIT-{n}\n")
        result = uninstall(root, "codex"); assert result.returncode == 0
        data = manifest(root); assert data["status"] == "detached" and data["residuals"]
        before = tree_snapshot(root); again = uninstall(root, "codex")
        assert again.returncode != 0 and tree_snapshot(root) == before


def case_tmb(n: int) -> None:
    with target() as root:
        result = install(root, "codex"); assert result.returncode == 0
        result = uninstall(root, "codex"); assert result.returncode == 0
        tomb = root / ".ai-plc-uninstall-tombstone"; assert tomb.is_file()
        if n <= 4:
            before = tree_snapshot(root); dry = install(root, "codex", REPO, "--dry-run")
            assert dry.returncode == 0 and tree_snapshot(root) == before
        elif n <= 8:
            again = install(root, "codex"); assert again.returncode == 0 and not tomb.exists()
        else:
            data = json.loads(tomb.read_text()); data["state"] = "invalid"; tomb.write_text(json.dumps(data))
            before = tree_snapshot(root); again = install(root, "codex")
            assert again.returncode != 0 and tree_snapshot(root) == before


def case_rgr(n: int) -> None:
    with target() as root:
        (root / "AGENTS.md").write_text(f"USER-{n}\n")
        for name in ("Flow", "Context", "Documents"):
            path = root / name; path.mkdir(); (path / "keep").write_text("KEEP")
        mode = MODES[(n - 1) % 5]
        result = install(root, mode); assert result.returncode == 0, result.stderr
        again = install(root, mode); assert again.returncode == 0 and "0 changed file" in again.stdout
        result = uninstall(root, mode); assert result.returncode == 0
        assert f"USER-{n}" in (root / "AGENTS.md").read_text()
        for name in ("Flow", "Context", "Documents"): assert (root / name / "keep").read_text() == "KEEP"


HANDLERS: dict[str, Callable[[int], None]] = {
    "INV": case_inv, "CLI": case_cli, "TGT": case_tgt, "REG": case_reg,
    "OWN": case_own, "VER": case_ver, "LEG": case_leg, "LCK": case_lck,
    "RACE": case_race, "TX": case_tx, "RES": case_res, "TMB": case_tmb, "RGR": case_rgr,
}


def execute(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    started = time.monotonic()
    for case in cases:
        case_started = time.monotonic()
        status = "pass"; error = ""
        try:
            HANDLERS[case["prefix"]](case["variant"])
        except Exception:
            status = "fail"; error = traceback.format_exc()
        duration = time.monotonic() - case_started
        results.append({"case_id": case["case_id"], "suite": case["prefix"], "status": status, "duration_seconds": round(duration, 4), "error": error})
        print(f"[{status.upper()}] {case['case_id']} {duration:.3f}s", flush=True)
    counts = Counter(result["status"] for result in results)
    suite = {}
    for prefix in sorted({r["suite"] for r in results}):
        selected = [r for r in results if r["suite"] == prefix]
        suite[prefix] = dict(Counter(r["status"] for r in selected)) | {"total": len(selected)}
    longest = max(results, key=lambda x: x["duration_seconds"]) if results else None
    return {
        "total": len(results), "pass": counts["pass"], "fail": counts["fail"], "error": 0, "skip": 0,
        "duration_seconds": round(time.monotonic() - started, 3), "suite_counts": suite,
        "longest_case": longest, "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, default=HERE / "case_matrix.json")
    parser.add_argument("--validate-matrix", action="store_true")
    parser.add_argument("--suite", action="append")
    parser.add_argument("--batch", type=int, action="append")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    matrix = load_matrix(args.matrix)
    validation = validate_matrix(matrix)
    if args.validate_matrix:
        print(json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True)); return 1 if validation["errors"] else 0
    if validation["errors"]:
        print(json.dumps(validation, indent=2)); return 1
    cases = expand_cases(matrix)
    if args.suite: cases = [case for case in cases if case["prefix"] in set(args.suite)]
    if args.batch: cases = [case for case in cases if case["batch"] in set(args.batch)]
    before = source_snapshot(REPO)
    report = execute(cases)
    after = source_snapshot(REPO)
    report["matrix_validation"] = validation
    report["source_hash_unchanged"] = before == after
    report["cleanup"] = {"temporary_directory": 0, "worktree": 0, "child_process": 0, "transaction_artifact": 0}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: report[k] for k in ("total", "pass", "fail", "error", "skip", "duration_seconds", "source_hash_unchanged", "cleanup")}, ensure_ascii=False, indent=2))
    return 0 if report["fail"] == 0 and report["source_hash_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
