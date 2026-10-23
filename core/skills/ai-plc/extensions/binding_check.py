"""Generic validator. No dispatch, source writes, or private imports.
The caller supplies current facts independently from canonical sources.
Installed generic helper; style activation and dispatch remain caller responsibilities.
"""
import datetime as dt
import hashlib
import json
from pathlib import PurePath, Path

class BindingError(ValueError):
    pass

def _require(condition, reason):
    if not condition:
        raise BindingError(reason)

def _text(value):
    return isinstance(value, str) and bool(value.strip())

def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)

def _time(value):
    _require(_text(value), "missing_time")
    try:
        result = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise BindingError("invalid_time") from exc
    _require(result.utcoffset() is not None, "timezone_required")
    return result

def instructions(binding):
    """Exact carried block; surrounding Task prose may differ."""
    body = json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return ("DEVELOPMENT_BINDING_BEGIN\n" + body + "\nDEVELOPMENT_BINDING_END\n"
            "既存入口と規約/Skill版を読む。実操作許可・有限枠・writerを各境界で照合する。\n"
            "上流未完・未知・不一致・期限終了は停止し、別方式へfallbackしない。\n"
            "技術計画の同版本人承認前に開発担当/技術reviewerを起動しない。\n"
            "同Task/request/runの入力を使用し、結果または停止理由を同じ返却先へ返す。\n")

def _single_block(text, expected):
    return (isinstance(text, str) and text.count("DEVELOPMENT_BINDING_BEGIN") == 1 and
            text.count("DEVELOPMENT_BINDING_END") == 1 and text.count(expected) == 1)

_SELECTOR = None


def _selector():
    """.claude/skills/ai-plc/scripts/plc_addon_select.py (a common read-only helper, not a private entry), loaded once
    by file path. sys.path and the bytecode setting are restored afterwards."""
    global _SELECTOR
    if _SELECTOR is None:
        import importlib.util
        import sys
        path = Path(__file__).resolve().parents[1] / "scripts" / "plc_addon_select.py"   # .claude/skills/ai-plc/scripts
        saved, bytecode = list(sys.path), sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec = importlib.util.spec_from_file_location("_aiplc_addon_select", path)
            if spec is None or not path.is_file():
                raise ImportError("missing " + str(path))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:
            raise BindingError("selector_unavailable") from exc
        finally:
            sys.path[:] = saved
            sys.dont_write_bytecode = bytecode
        _SELECTOR = module
    return _SELECTOR


def canonical_pm(root, intent):
    """PM selection as the binding work_style value: "aipm" or None.
    Bundled aipm in intent.addons or the legacy work_style: aipm, read by the selector; the value set is unchanged.
    Neither field -> None without loading the selector. A held selection stops."""
    if intent.get("work_style") is None and not intent.get("addons"):
        return None
    result = _selector().selected_addons(root, read_roots=[str(root)])
    _require(result["route"] != "held", "addon_selection_held")
    return "aipm" if any(s["addon_id"] == "aipm" for s in result["selected"]) else None


def check(binding, current, task_text, agt_text, now, phase="read"):
    """Return a route decision only. It does not grant authorization.
    current must come from actual intent/Task/source/permission/budget/writer
    observations, never from a copy of the submitted binding itself.
    """
    _require(isinstance(binding, dict) and isinstance(current, dict), "object_required")
    _require(isinstance(now, dt.datetime) and now.utcoffset() is not None, "current_time_required")
    kind = current.get("kind")
    _require(kind in ("development", "non_development"), "classification_unknown")
    _require(binding.get("kind") == kind, "classification_mismatch")
    _require(binding.get("work_style") == current.get("work_style"), "work_style_mismatch")
    _require(binding.get("dev_style") == current.get("dev_style"), "dev_style_mismatch")
    _require(current.get("legacy_selector_conflict") is False, "legacy_selector_conflict_unknown_or_true")
    if kind == "non_development" or current.get("dev_style") is None:
        _require(binding.get("entry") is None and binding.get("private_binding") is None,
                 "stale_or_non_development_private_binding")
        return {"route": "ordinary", "private_reads": 0, "dispatch": False}
    _require(_text(current.get("dev_style")), "invalid_selector")
    _require(current.get("read_only_target") is False, "target_readonly_or_unknown")
    keys = ("schema_version", "task_id", "request_id", "run_id", "kind", "work_style", "dev_style",
            "repo", "profile", "selection_ref", "goal_sha256", "source_hashes", "entry",
            "private_binding", "candidate", "rules_refs", "skill_refs", "upstream_required_refs", "upstream_evidence", "permissions",
            "budget", "writer", "input_ref", "return_ref", "agt_required")
    for key in keys:
        _require(key in binding and key in current, "missing_" + key)
        _require(binding[key] == current[key], "mismatch_" + key)
    _require(binding["schema_version"] == "1.0", "schema_incompatible")
    for key in ("task_id", "request_id", "run_id", "repo", "profile", "selection_ref", "input_ref", "return_ref", "private_binding"):
        _require(_text(binding[key]), "unknown_" + key)
    _require(_digest(binding["goal_sha256"]), "goal_hash_invalid")
    hashes = binding["source_hashes"]
    _require(isinstance(hashes, dict) and bool(hashes), "source_hashes_unknown")
    _require(all(_text(p) and _digest(h) for p, h in hashes.items()), "source_hash_invalid")
    entry = binding["entry"]
    _require(isinstance(entry, dict) and _text(entry.get("path")) and _digest(entry.get("sha256")), "entry_unknown")
    _require(PurePath(entry["path"]).is_absolute(), "entry_not_absolute")
    _require(current.get("entry_realpath_and_hash_verified") is True, "entry_observation_missing")
    _require(current.get("selector_known") is True, "selector_unknown")
    for key in ("rules_refs", "skill_refs"):
        refs = binding[key]
        _require(isinstance(refs, list) and bool(refs), "unknown_" + key)
        for ref in refs:
            _require(isinstance(ref, dict) and _text(ref.get("ref")) and _digest(ref.get("sha256")), "bad_" + key)
        _require(current.get(key + "_verified") is True, "unverified_" + key)
    required = binding["upstream_required_refs"]
    upstream = binding["upstream_evidence"]
    _require(isinstance(required, list) and all(_text(ref) for ref in required) and
             len(set(required)) == len(required), "upstream_requirements_unknown")
    _require(isinstance(upstream, list), "upstream_evidence_unknown")
    _require(current.get("upstream_evidence_verified") is True and
             current.get("upstream_conditions_satisfied") is True, "upstream_conditions_unmet_or_unknown")
    seen_required = set()
    seen = set()
    for ref in upstream:
        _require(isinstance(ref, dict) and _text(ref.get("ref")) and _digest(ref.get("sha256")) and
                 type(ref.get("required")) is bool, "upstream_evidence_invalid")
        _require(ref["ref"] not in seen, "upstream_evidence_duplicate")
        seen.add(ref["ref"])
        _require(ref.get("state") in ("completed", "incomplete", "unknown") and
                 ref.get("decision") in ("satisfied", "unsatisfied", "unknown"), "upstream_state_unknown")
        if ref["required"]:
            seen_required.add(ref["ref"])
            _require(ref["state"] == "completed" and ref["decision"] == "satisfied" and
                     _text(ref.get("decision_ref")) and _digest(ref.get("decision_sha256")), "upstream_required_not_satisfied")
    _require(seen_required == set(required), "upstream_required_evidence_missing")
    if binding["work_style"] == "aipm":
        _require(current.get("inception_task_registered") is True, "inception_task_unregistered")
        ids = current.get("aipm_upstream_task_ids")
        _require(isinstance(ids, list) and bool(ids) and all(_text(x) for x in ids),
                 "aipm_upstream_tasks_missing")
        refs = current.get("canonical_upstream_required_refs")
        _require(isinstance(refs, list) and bool(refs) and set(required) == set(refs),
                 "aipm_canonical_upstream_mismatch")
        hashes = current.get("canonical_upstream_hashes")
        _require(isinstance(hashes, dict) and set(hashes) == set(required),
                 "aipm_canonical_hashes_missing")
        _require(all(ref["sha256"] == hashes.get(ref["ref"]) for ref in upstream if ref["required"]),
                 "aipm_upstream_version_changed")
    permission = binding["permissions"]
    _require(isinstance(permission, dict) and _text(permission.get("ref")), "permission_unknown")
    _require(current.get("permissions_verified") is True, "permission_observation_missing")
    _require(permission.get(phase) is True, "phase_permission_missing")
    if phase in ("implement", "review"):
        _require(current.get("same_version_plan_approved") is True, "plan_unapproved")
        _require(isinstance(binding["candidate"], dict) and bool(binding["candidate"]), "candidate_unknown")
    budget = binding["budget"]
    _require(isinstance(budget, dict) and _text(budget.get("budget_id")), "budget_unknown")
    start, deadline = _time(budget.get("started_at")), _time(budget.get("deadline_at"))
    spent = budget.get("consumed_minutes")
    _require(type(spent) in (int, float) and spent >= 0, "consumption_unknown")
    _require(start <= now < deadline and spent < (deadline - start).total_seconds() / 60, "deadline_or_consumption_exhausted")
    _require(current.get("budget_history_verified") is True, "budget_history_unverified")
    writer = binding["writer"]
    _require(isinstance(writer, dict) and _text(writer.get("owner")) and _text(writer.get("receipt")), "writer_unknown")
    _require(isinstance(writer.get("paths"), list) and bool(writer["paths"]), "writer_paths_unknown")
    _require(_time(writer.get("valid_until")) > now, "writer_expired")
    _require(current.get("writer_verified") is True, "writer_observation_missing")
    block = instructions(binding)
    _require(_single_block(task_text, block), "Task_instructions_missing_mixed_or_duplicate")
    _require(type(binding["agt_required"]) is bool, "agt_requirement_unknown")
    if binding["agt_required"]:
        _require(_single_block(agt_text, block), "AGT_instructions_missing_mixed_or_duplicate")
    return {"route": "selected_development", "entry": entry.copy(), "dispatch": False,
            "binding_sha256": hashlib.sha256(json.dumps(binding, sort_keys=True, ensure_ascii=False,
                separators=(",", ":")).encode()).hexdigest()}

def check_result(result, binding):
    _require(isinstance(result, dict), "result_object_required")
    for key in ("task_id", "request_id", "run_id", "work_style", "dev_style", "candidate"):
        _require(key in result and key in binding and result[key] == binding[key], "result_mismatch_" + key)
    expected = hashlib.sha256(json.dumps(binding, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    _require(result.get("binding_sha256") == expected, "result_binding_mismatch")
    _require(result.get("status") in ("result", "stop", "plan_approval_pending"), "result_status_invalid")
    _require(isinstance(result.get("evidence_refs"), list) and bool(result["evidence_refs"]), "result_evidence_missing")
    _require(isinstance(result.get("ac_judgments"), list) and bool(result["ac_judgments"]), "AC_judgments_missing")
    for judgment in result["ac_judgments"]:
        _require(isinstance(judgment, dict) and _text(judgment.get("ac")) and
                 judgment.get("judgment") in ("achieved", "partial", "unmet", "unknown") and
                 _text(judgment.get("evidence_ref")), "AC_judgment_invalid")
    if result["status"] == "stop":
        _require(_text(result.get("stop_reason")), "stop_reason_missing")
    if result["status"] == "plan_approval_pending":
        _require(result.get("candidate") is None and result.get("same_version_plan_approved") is False, "unapproved_candidate")
    return result


def observe_registered_upstream(layer, task_id):
    """Read actual Task prerequisites. This proves structure/version, not human approval.

    Operation still checks semantic completion, independent verification, permissions,
    and real decision sources. No private entry is read and nothing is dispatched.
    """
    import yaml
    root = Path(layer).resolve(strict=True)
    observed = {}

    def read(ref):
        _require(_text(ref) and not Path(ref).is_absolute(), "upstream_relative_path_required")
        path = (root / ref).resolve(strict=True)
        _require(path.is_relative_to(root) and path.is_file(), "upstream_outside_layer")
        data = path.read_bytes()
        observed[ref] = hashlib.sha256(data).hexdigest()
        return data

    try:
        intent = yaml.safe_load(read("intent.yaml"))
        backlog = yaml.safe_load(read("backlog.yaml"))
        _require(isinstance(intent, dict) and isinstance(backlog, dict), "canonical_metadata_invalid")
        tasks = backlog.get("tasks")
        _require(isinstance(tasks, list) and all(isinstance(t, dict) and _text(t.get("id")) for t in tasks),
                 "canonical_tasks_invalid")
        by_id = {t["id"]: t for t in tasks}
        _require(len(by_id) == len(tasks), "canonical_duplicate_task")
        task = by_id.get(task_id)
        _require(task is not None and task.get("id_status") == "registered", "inception_task_unregistered")
        pm = canonical_pm(root, intent)
        _require(pm == "aipm" and _text(intent.get("dev_style")), "canonical_styles_mismatch")
        _require((task.get("development_scope") or {}).get("kind") == "development", "canonical_not_development")
        ids = task.get("aipm_upstream_tasks")
        deps = task.get("dependencies")
        _require(isinstance(ids, list) and bool(ids) and all(_text(x) for x in ids) and len(set(ids)) == len(ids),
                 "aipm_upstream_tasks_missing")
        _require(isinstance(deps, list) and all(_text(x) for x in deps) and set(ids) <= set(deps),
                 "aipm_upstream_not_dependencies")
        visited = set()
        def completed(tid, visiting):
            _require(tid not in visiting and tid != task_id, "upstream_dependency_cycle")
            if tid in visited:
                return
            t = by_id.get(tid)
            _require(t is not None and t.get("status") == "completed", "upstream_task_incomplete_or_missing")
            nested = t.get("dependencies", [])
            _require(isinstance(nested, list) and all(_text(x) for x in nested), "upstream_dependencies_invalid")
            for dep in nested:
                completed(dep, visiting | {tid})
            visited.add(tid)
        for tid in deps:
            completed(tid, set())
        hashes = {}
        for tid in ids:
            outputs = by_id[tid].get("output")
            _require(isinstance(outputs, list) and bool(outputs) and all(_text(x) for x in outputs),
                     "upstream_actual_outputs_missing")
            for ref in outputs:
                data = read(ref)
                hashes[ref] = hashlib.sha256(data).hexdigest()
        # Refuse a mixed snapshot if metadata or any output changed during these reads.
        _require(all(hashlib.sha256((root / ref).read_bytes()).hexdigest() == sha
                     for ref, sha in observed.items()), "canonical_changed_during_read")
        return {"inception_task_registered": True, "aipm_upstream_task_ids": ids,
                "canonical_upstream_required_refs": sorted(hashes), "canonical_upstream_hashes": hashes,
                "canonical_work_style": pm, "canonical_dev_style": intent["dev_style"],
                "canonical_read_hashes": observed}
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        if isinstance(exc, BindingError):
            raise
        raise BindingError("canonical_read_failed") from exc


def check_registered(binding, current, task_text, agt_text, now, *, layer, phase="read"):
    """Operation caller: canonical AIPM prerequisites first, then existing check()."""
    _require(isinstance(binding, dict) and isinstance(current, dict), "object_required")
    # Route using actual common metadata too: a caller cannot hide AIPM by
    # submitting matching null selectors in binding/current. No private reads.
    import yaml
    try:
        root = Path(layer).resolve(strict=True)
        intent_path, backlog_path = root / "intent.yaml", root / "backlog.yaml"
        for path in (intent_path, backlog_path):
            _require(path.resolve(strict=True).is_relative_to(root), "canonical_metadata_outside_layer")
        intent_bytes, backlog_bytes = intent_path.read_bytes(), backlog_path.read_bytes()
        intent, backlog = yaml.safe_load(intent_bytes), yaml.safe_load(backlog_bytes)
        _require(isinstance(intent, dict) and isinstance(backlog, dict), "canonical_metadata_invalid")
        tasks = backlog.get("tasks")
        _require(isinstance(tasks, list) and all(isinstance(t, dict) and _text(t.get("id")) for t in tasks),
                 "canonical_tasks_invalid")
        _require(len({t["id"] for t in tasks}) == len(tasks), "canonical_duplicate_task")
        task = next((t for t in tasks if t["id"] == current.get("task_id")), None)
        _require(task is not None, "canonical_task_missing")
        classification = task.get("development_scope")
        _require(isinstance(classification, dict), "canonical_classification_missing")
        _require(current.get("kind") == classification.get("kind") and
                 current.get("work_style") == canonical_pm(root, intent) and
                 current.get("dev_style") == intent.get("dev_style"), "canonical_selector_mismatch")
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        if isinstance(exc, BindingError):
            raise
        raise BindingError("canonical_read_failed") from exc
    facts = dict(current)
    if (current.get("kind") == "development" and current.get("dev_style") is not None
            and current.get("work_style") == "aipm"):
        observed = observe_registered_upstream(layer, current.get("task_id"))
        _require(current.get("work_style") == observed["canonical_work_style"] and
                 current.get("dev_style") == observed["canonical_dev_style"], "canonical_style_mismatch")
        facts.update(observed)
    _require(intent_path.read_bytes() == intent_bytes and backlog_path.read_bytes() == backlog_bytes,
             "canonical_changed_during_read")
    result = check(binding, facts, task_text, agt_text, now, phase)
    if (result["route"] == "selected_development" and current.get("work_style") == "aipm"):
        # Hashing a decision proves its version, never its meaning or human origin.
        # Read the required decision sources even if an output list omitted them.
        try:
            decisions = {}
            for evidence in binding["upstream_evidence"]:
                if not evidence["required"]:
                    continue
                ref = evidence["decision_ref"]
                _require(not Path(ref).is_absolute(), "decision_relative_path_required")
                path = (root / ref).resolve(strict=True)
                _require(path.is_relative_to(root) and path.is_file(), "decision_outside_layer")
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
                _require(sha == evidence["decision_sha256"], "aipm_decision_version_changed")
                decisions[ref] = sha
            all_reads = {**observed["canonical_read_hashes"], **decisions}
            for ref, sha in all_reads.items():
                path = (root / ref).resolve(strict=True)
                _require(path.is_relative_to(root) and path.is_file(), "canonical_path_changed")
                _require(hashlib.sha256(path.read_bytes()).hexdigest() == sha,
                         "canonical_changed_during_read")
        except (OSError, ValueError, TypeError) as exc:
            if isinstance(exc, BindingError):
                raise
            raise BindingError("decision_read_failed") from exc
    return result
