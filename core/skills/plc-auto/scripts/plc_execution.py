"""Shared, bounded workflow decisions. Caller supplies current runtime evidence.

This module does not authenticate a person, grant permissions, run tools, or set
a native Goal. JSON inputs are data; current_authorization is a caller attestation,
never a fact inferred from saved prose. Only explicit record_version=2 opts in.
"""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import stat
import uuid

import yaml


INTERNAL = {"plan", "register_task", "instruct", "implement", "code_check",
            "test", "review", "repair", "save", "management_record", "resume"}
RESTRICTED = {"consult", "collection", "planning", "read_only"}
TERMINAL = {"completed", "cancelled", "deferred", "blocked"}


def approval_scope_sha256(contract, budget):
    """Version binding only, not human authentication. Excludes consumption/position."""
    scope = {k: contract.get(k) for k in (
        "run_id", "layer", "authorization_scope", "authorization_ref", "scope_revision",
        "approval_revision", "goal", "scope_tasks", "task_versions", "operations", "write_set", "budget_id")}
    scope["limits"] = {k: budget.get(k) for k in (
        "budget_id", "started_at", "deadline", "recording_reserved_from",
        "repairs_limit", "additional_spend_limit_yen")}
    return hashlib.sha256(json.dumps(scope, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed


def load_layer(layer):
    root = Path(layer).resolve(strict=True)
    intent = yaml.safe_load((root / "intent.yaml").read_text())
    backlog = yaml.safe_load((root / "backlog.yaml").read_text())
    if not isinstance(intent, dict) or not isinstance(backlog, dict):
        raise ValueError("Layer metadata must be mappings")
    return root, intent, backlog


def result(decision, reason, **extra):
    return {"decision": decision, "reason": reason,
            "requires_user_input": False, **extra}


def evaluate(layer, action, runtime, *, at=None):
    """Read-only decision for a currently observed execution, not a document hint."""
    if not isinstance(runtime, dict):
        return result("hold", "runtime evidence missing")
    if runtime.get("platform_denied") is True:
        return result("stop", "actual tool refusal; no fallback bypass")
    if action == "read":
        # A concurrent writer does not make permitted reading require owner input.
        if runtime.get("source_changed") is True:
            return result("hold", "source changed; inspect current version again")
        return result("read_only", "inspect available current source and compare versions",
                      requires_independent_review=False)
    if action not in INTERNAL:
        return result("hold", "new permission, external send, spend or scope needs owner decision")
    if any(runtime.get(k) for k in ("new_permission", "external_send", "new_spend", "scope_change")):
        return result("hold", "boundary outside approved bundle; report specific owner decision")
    if runtime.get("instruction_scope") in RESTRICTED:
        if action == "management_record":
            root = Path(layer).resolve()
            if any(not Path(p).resolve().is_relative_to(root) for p in runtime.get("write_paths", [])):
                return result("hold", "record-only scope cannot write outside its Layer")
            return result("record_only", "record only the authorized consultation/collection",
                          requires_independent_review=False)
        return result("scope_limited", "consultation/collection/planning is not execution permission")
    try:
        root, intent, backlog = load_layer(layer)
        contract = backlog.get("execution_contract") or {}
        budget = backlog.get("execution_budget") or {}
        if intent.get("status") in {"cancelled", "paused", "blocked"}:
            return result("stop", "Project cancellation or pause is preserved")
        if contract.get("record_version") != 2:
            return result("hold", "no bounded v2 execution; preserve existing ordinary workflow")
        if contract.get("status") != "running":
            return result("stop", "execution stopped or finished; history cannot restart it")
        if contract.get("authorization_scope") != "end_to_end":
            return result("scope_limited", "record authorizes no full execution")
        if runtime.get("current_authorization") is not True or runtime.get("runtime_active") is not True:
            return result("hold", "current trusted instruction/runtime must be checked; saved record alone is insufficient")
        for key in ("run_id", "authorization_ref", "scope_revision"):
            if not contract.get(key) or runtime.get(key) != contract[key]:
                return result("hold", "current execution/approval/version mismatch: " + key)
        if contract.get("approval_revision") != contract.get("scope_revision"):
            return result("hold", "approval does not cover current scope version")
        if Path(contract["layer"]).resolve() != root:
            return result("hold", "Layer mismatch")
        bound = contract.get("thread_id") or contract.get("session_id")
        owner = runtime.get("thread_id") or runtime.get("session_id")
        if not bound or owner != bound:
            return result("hold", "current thread/session mismatch; no inherited force")
        runner = contract.get("runner") or {}
        if runner and action != "management_record" and (
                runtime.get("claim_token") != runner.get("token") or runner.get("owner") != owner
                or runner.get("run_id") != contract["run_id"] or runner.get("action") != action
                or runner.get("task_id") != contract.get("current_task")
                or runner.get("task_version") != (contract.get("task_versions") or {}).get(contract.get("current_task"))):
            return result("busy", "approved operation still running; do not restart it")
        if not budget.get("budget_id") or contract.get("budget_id") != budget["budget_id"]:
            return result("hold", "budget does not belong to this execution")
        current = at or dt.datetime.now(dt.timezone.utc)
        started, deadline = timestamp(budget["started_at"]), timestamp(budget["deadline"])
        if deadline <= started or current < started:
            return result("hold", "invalid finite time window")
        if current >= deadline or budget.get("status") in {"blocked", "expired", "completed"}:
            return result("stop", "finite deadline/budget ended; do not reset")
        limit, used = budget["repairs_limit"], budget["repairs_used"]
        if type(limit) is not int or type(used) is not int or limit < 0 or used < 0:
            return result("hold", "invalid repair accounting")
        if used > limit or (action == "repair" and used >= limit):
            return result("stop", "repair ceiling reached")
        spent, ceiling = budget["additional_spend_yen"], budget["additional_spend_limit_yen"]
        if (type(spent) not in (int, float) or type(ceiling) not in (int, float)
                or not math.isfinite(spent) or not math.isfinite(ceiling) or not 0 <= spent <= ceiling):
            return result("stop", "spending ceiling or accounting invalid")
        reserve = budget.get("recording_reserved_from")
        if reserve and current >= timestamp(reserve) and action not in {"save", "management_record"}:
            return result("stop", "record-only time reserve; start no new work")
        if action not in contract.get("operations", []):
            return result("hold", "operation not covered by approval")
        if runtime.get("approved_scope_sha256") != approval_scope_sha256(contract, budget):
            return result("hold", "approved bundle/version/limits changed; do not infer new approval")
        tasks = backlog.get("tasks", [])
        ids = [t["id"] for t in tasks]
        if len(ids) != len(set(ids)):
            return result("hold", "duplicate Task identity")
        scope = contract.get("scope_tasks") or []
        if len(scope) != len(set(scope)):
            return result("hold", "duplicate approved Task identity")
        for approved_id in scope:
            approved_task = next((t for t in tasks if t["id"] == approved_id), None)
            approved_revision = (contract.get("task_versions") or {}).get(approved_id)
            if not approved_task or not approved_revision or approved_task.get("task_version") != approved_revision:
                return result("hold", "an approved Task/version is missing or changed")
        task_id = contract.get("current_task")
        if not task_id or task_id not in scope:
            return result("hold", "current Task must belong to approved bundle")
        if runtime.get("requested_task") not in (None, task_id):
            return result("hold", "explicit requested Task differs from active execution")
        task = next((t for t in tasks if t["id"] == task_id), None)
        approved_version = (contract.get("task_versions") or {}).get(task_id)
        if not task or not approved_version or task.get("task_version") != approved_version:
            return result("hold", "current Task/approved version mismatch")
        if runtime.get("task_version") != approved_version:
            return result("hold", "runtime Task version mismatch")
        if task.get("status") in TERMINAL and action != "management_record":
            return result("stop", "Task stopped or finished; no automatic restart")
        if any(next((t.get("status") for t in tasks if t["id"] == dep), None) != "completed"
               for dep in task.get("dependencies", [])):
            return result("hold", "dependency not complete")
        for value in runtime.get("write_paths", []):
            path = Path(value).resolve()
            explicit = {Path(p).resolve() for p in contract.get("write_set", [])}
            if path not in explicit:
                if not path.is_relative_to(root):
                    return result("hold", "write path outside fixed bundle")
                relative = path.relative_to(root)
                if any(part.startswith(".") for part in relative.parts):
                    return result("hold", "hidden/settings path not authorized")
                if path.exists() and path not in {root / name for name in ("backlog.yaml", "context.yaml", "intent.yaml")}:
                    return result("hold", "existing artifact requires explicit fixed write path")
        if runtime.get("final_delivery") is True:
            if (runtime.get("quality_passed") is not True or runtime.get("unresolved_p0_p2") != 0
                    or not runtime.get("artifact_sha256")
                    or runtime["artifact_sha256"] != runtime.get("reviewed_sha256")):
                return result("stop", "final quality/reviewed version not verified")
        return result("continue_internal", "same approved execution; no repeated A/start-text confirmation",
                      run_id=contract["run_id"], task_id=task_id, task_version=approved_version,
                      document_task_hint_ignored=runtime.get("document_task_hint") not in (None, task_id),
                      requires_new_plan=False, requires_independent_review=action == "review")
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return result("hold", "execution metadata unavailable or invalid: " + str(exc))


@contextlib.contextmanager
def layer_lock(layer):
    root = Path(layer).resolve(strict=True)
    with (root / ".project-lifecycle.lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield root
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_backlog(root, backlog):
    path = root / "backlog.yaml"
    descriptor, temp = tempfile.mkstemp(prefix=".execution-", dir=root)
    try:
        os.fchmod(descriptor, stat.S_IMODE(path.stat().st_mode))
        with os.fdopen(descriptor, "w") as stream:
            yaml.safe_dump(backlog, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def claim(layer, action, runtime):
    """Persist one operation owner under the existing Layer lock; never steal a slot."""
    try:
        with layer_lock(layer) as root:
            decision = evaluate(root, action, runtime)
            if decision["decision"] != "continue_internal":
                return decision
            _, _, backlog = load_layer(root)
            contract = backlog["execution_contract"]
            if contract.get("runner"):
                return result("busy", "operation already running; inspect/wait, do not start again")
            token = uuid.uuid4().hex
            contract["runner"] = {"token": token, "run_id": contract["run_id"],
                                  "owner": runtime.get("thread_id") or runtime.get("session_id"),
                                  "task_id": decision["task_id"], "task_version": decision["task_version"],
                                  "action": action, "claimed_at": dt.datetime.now(dt.timezone.utc).isoformat()}
            atomic_backlog(root, backlog)
            return {**decision, "claim_token": token}
    except BlockingIOError:
        return result("busy", "Layer writer currently holds lock; no duplicate start")


def release(layer, run_id, token, owner):
    """Release only the exact operation owner; permitted even after its deadline."""
    try:
        with layer_lock(layer) as root:
            _, _, backlog = load_layer(root)
            contract = backlog.get("execution_contract") or {}
            runner = contract.get("runner") or {}
            if (not token or contract.get("run_id") != run_id or runner.get("token") != token
                    or runner.get("run_id") != run_id or runner.get("owner") != owner):
                return result("hold", "claim token/run/owner mismatch; no state overwritten")
            del contract["runner"]
            atomic_backlog(root, backlog)
            return result("released", "same operation slot released; approval/budget unchanged")
    except BlockingIOError:
        return result("busy", "Layer writer holds lock; release not applied")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", required=True)
    parser.add_argument("--action", required=True, choices=sorted(INTERNAL | {"read"}))
    parser.add_argument("--runtime", required=True, help="JSON data of current caller-observed runtime")
    parser.add_argument("--claim", action="store_true", help="acquire exact operation slot; no tool execution")
    args = parser.parse_args()
    runtime = json.loads(Path(args.runtime).read_text())
    selected = claim(args.layer, args.action, runtime) if args.claim else evaluate(args.layer, args.action, runtime)
    print(json.dumps(selected, ensure_ascii=False))
    return 0 if selected["decision"] in {"continue_internal", "read_only", "record_only"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
