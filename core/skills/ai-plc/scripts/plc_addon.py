"""Bounded, read-only addon consultation. Caller verifies current human authority.

Selection arguments are caller attestations, not authentication or permission grants.
No dispatch, journal, cache, network or persistent status operations are performed.
Explicit trials are held: A3 is not implemented by this module.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import stat

import yaml


MAX_INPUT_BYTES = 262144
MAX_RESOURCE_BYTES = 65536
MAX_BINDINGS = 16
CONTRACT = Path(__file__).resolve().parents[1] / "references/addon-seam-contract_v0.1.yaml"  # .claude/skills/ai-plc/scripts -> ../references
TASK_CONTRACT = CONTRACT.with_name("addon-seam-contract_v0.2.yaml")


class Held(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for k, v in node.value:
        key = loader.construct_object(k, deep=deep)
        if not isinstance(key, str) or key in result:
            raise Held("non-string or duplicate YAML key")
        result[key] = loader.construct_object(v, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _yaml(raw):
    text = raw.decode("utf-8")
    if any(isinstance(t, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for t in yaml.scan(text)):
        raise Held("YAML anchors/aliases are unsupported")
    value = yaml.load(text, Loader=UniqueLoader)
    if not isinstance(value, dict):
        raise Held("YAML root must be a mapping")
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise Held(name + " must be a nonempty string")
    return value


def _positive(value, name, maximum):
    if type(value) is not int or not 0 < value <= maximum:
        raise Held(name + " requires a positive finite supported limit")
    return value


def _bytes(path, roots, limit):
    """Read with no symlink traversal beneath an explicitly allowed physical root."""
    path = Path(path)
    options = [r for r in roots if path.is_relative_to(r)]
    if not options:
        raise Held("read outside explicit permitted roots")
    root = max(options, key=lambda r: len(r.parts))
    parts = path.relative_to(root).parts
    if not parts or any(x in ("", ".", "..") for x in parts):
        raise Held("invalid file reference")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise Held("nonregular or oversized input")
            chunks, total = [], 0
            while total <= limit:
                chunk = os.read(file_fd, min(65536, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            if total > limit:
                raise Held("input grew past finite limit")
            return b"".join(chunks)
        finally:
            os.close(file_fd)
    finally:
        os.close(fd)


def _reference(ref):
    if not isinstance(ref, dict):
        raise Held("resource reference must be a mapping")
    for key in ("kind", "scope", "version", "sha256"):
        _text(ref.get(key), key)
    if ref["scope"] not in ("common", "case"):
        raise Held("unknown reference scope")
    if len(ref["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in ref["sha256"]):
        raise Held("invalid pinned hash")
    if ref["kind"] == "page":
        _text(ref.get("resource_ref"), "resource_ref")
        return
    if ref["kind"] != "file":
        raise Held("unknown reference kind")
    name = _text(ref.get("relative_name"), "relative_name")
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise Held("absolute, parent or ambiguous path reference")


def _binding(binding, types):
    if not isinstance(binding, dict):
        raise Held("addon binding must be a mapping")
    fields = types["AddonBinding"]["field_contracts"]
    if any(k not in fields and k != "schema_version" for k in binding):
        raise Held("unknown addon binding field")
    if binding.get("schema_version", "0.1") != "0.1":
        raise Held("unknown binding schema version")
    for key, field in fields.items():
        if field["required"] and key not in binding:
            raise Held("missing addon field: " + key)
    for name in ("addon_id", "addon_version", "selection_ref"):
        _text(binding[name], name)
    for name in ("guide_ref", "common_contract_ref"):
        _reference(binding[name])
    forms = binding["forms"]
    if not isinstance(forms, list) or len(forms) > 128:
        raise Held("invalid bounded forms list")
    ids = []
    for form in forms:
        if not isinstance(form, dict) or set(form) != {"form_id", "form_ref"}:
            raise Held("invalid form declaration")
        ids.append(_text(form["form_id"], "form_id"))
        _reference(form["form_ref"])
    if len(ids) != len(set(ids)):
        raise Held("duplicate form_id")
    limits = binding["read_limits"]
    if not isinstance(limits, dict):
        raise Held("read_limits must be a mapping")
    _positive(limits.get("max_guide_items"), "max_guide_items", MAX_BINDINGS)
    _positive(limits.get("max_form_items"), "max_form_items", 128)


def _held(reason, coverage):
    coverage["coverage_state"] = "partial" if coverage["retrieved_count"] else "unknown"
    coverage["unknown_items"].append(reason)
    return {"route": "held", "reason": reason, "next_actions": [], "read_coverage": coverage,
            "execution_note": "実施：案内保留（Task未実行・試行未実施）", "source_refs": []}


def _next(layer, backlog, approved_ids, now, roots, executor="codex"):
    """Only currently caller-authorized, pending, unblocked tasks may be offered."""
    tasks = backlog.get("tasks", [])
    if not isinstance(tasks, list) or any(not isinstance(t, dict) for t in tasks):
        raise Held("invalid tasks")
    ids = [t.get("id") for t in tasks]
    if any(not isinstance(x, str) for x in ids) or len(ids) != len(set(ids)):
        raise Held("unknown/duplicate task identities")
    contract = backlog.get("execution_contract") or {}
    budget = backlog.get("execution_budget") or {}
    actions = []
    usable = False
    if (contract.get("status") == "running" and contract.get("authorization_scope") == "end_to_end"
            and budget.get("status") == "running" and not contract.get("runner")):
        try:
            deadline = dt.datetime.fromisoformat(budget["deadline"].replace("Z", "+00:00"))
            started = dt.datetime.fromisoformat(budget["started_at"].replace("Z", "+00:00"))
            usable = (deadline.tzinfo is not None and started.tzinfo is not None
                      and started <= now < deadline and contract.get("budget_id") == budget.get("budget_id"))
            reserve = budget.get("recording_reserved_from")
            if reserve and now >= dt.datetime.fromisoformat(reserve.replace("Z", "+00:00")):
                usable = False
        except (KeyError, ValueError, TypeError):
            usable = False
    states = {t["id"]: t.get("status") for t in tasks}
    for task in tasks:
        if (not usable or task["id"] not in approved_ids or task.get("status") != "pending"
                or task["id"] not in contract.get("scope_tasks", [])
                or not task.get("task_version")
                or task.get("task_version") != (contract.get("task_versions") or {}).get(task["id"])):
            continue
        deps = task.get("dependencies", [])
        if not isinstance(deps, list) or any(states.get(dep) != "completed" for dep in deps):
            continue
        required = (backlog.get("construction") or {}).get("tasks", [])
        needs_agent = task["id"] in required
        agent = task.get("command_template_ref")
        if needs_agent and isinstance(agent, str) and agent:
            relative = Path(agent)
            if relative.is_absolute() or ".." in relative.parts:
                raise Held("agent reference outside Layer")
            try:
                _bytes(layer / relative, roots, MAX_INPUT_BYTES)
                needs_agent = False
            except OSError:
                pass
        prefix = "$" if executor == "codex" else "/"
        entry = prefix + ("03-construction" if needs_agent else "04-operation")
        actions.append({"entry": entry, "layer": str(layer), "task_id": task["id"],
                        "outcome": "必要担当指示を作る" if needs_agent else task.get("name", task["id"]),
                        "authority": "caller current approval plus canonical version/budget/dependencies; suggestion only"})
    if not actions:
        actions = [{"entry": ("$" if executor == "codex" else "/") + "plc-brief", "layer": str(layer), "task_id": None,
                    "outcome": "現在の成立済み成果・保留理由・必要判断を確認する"}]
    return actions[:3]


def _case_bindings(bindings, shape_reason="invalid bounded addon bindings"):
    """The case (brought-in) bindings of intent.addons, bundled entries removed.

    Bundled entries (source: bundled) are checked with the selector's rules (plc_addon_select.split_addons:
    catalog row, no case fields, no duplicates) and then dropped; this helper never reads them further.
    Without any source field the list is returned as is and the catalog is not read.
    The bound MAX_BINDINGS applies to the remaining case list (shape_reason keeps each caller's former
    Held text). Empty result means unselected (task_inputs keeps its Held for a selected form).
    """
    if bindings is None or bindings == []:
        return []
    if not isinstance(bindings, list):
        raise Held(shape_reason)
    if any(isinstance(b, dict) and "source" in b for b in bindings):
        import importlib
        import sys
        try:
            if __package__:
                select = importlib.import_module(__package__ + ".plc_addon_select")
            else:
                here = str(Path(__file__).resolve().parent)
                if here not in sys.path:
                    sys.path.insert(0, here)
                select = importlib.import_module("plc_addon_select")
        except ImportError as exc:
            raise Held("selector unavailable: " + type(exc).__name__ + ": " + str(exc))
        try:
            _bundled, bindings = select.split_addons(bindings, select.load_catalog()["rows"])
        except select.Hold as exc:
            raise Held(str(exc))
    if len(bindings) > MAX_BINDINGS:
        raise Held(shape_reason)
    return bindings


def consult(layer, *, allowed_roots, common_root=None, verified_selections=(),
            request_kind="operational_guidance", requested_addon=None,
            trial_requested=False, no_write_requested=False, approved_task_ids=(), now=None,
            executor="codex"):
    """Caller checks actual selection/read/execution authority before supplying data.

    File metadata, Boolean flags and saved selection refs alone are not proof of it.
    Return guide text as bounded task data, never as executable instructions.
    """
    instant = now or dt.datetime.now(dt.timezone.utc)
    coverage = {"source_ref": "explicit addon consultation", "attempted_scope": [],
                "retrieved_count": 0, "coverage_state": "unknown", "missing_fields": [],
                "unreadable_items": [], "unknown_items": [], "as_of": instant.isoformat(), "evidence_ref": None}
    if trial_requested is not False or no_write_requested is not False:
        return _held("explicit/unknown no-write trial is unsupported; hold before private/claim/Backfill", coverage)
    if executor not in ("codex", "claude-code"):
        return _held("current executor unresolved; use actual runtime, not source data", coverage)
    try:
        if not allowed_roots or instant.tzinfo is None:
            raise Held("explicit permitted roots and aware current time required")
        roots = [Path(r).resolve(strict=True) for r in allowed_roots]
        case = Path(layer).resolve(strict=True)
        raw_intent = _bytes(case / "intent.yaml", roots, MAX_INPUT_BYTES)
        intent = _yaml(raw_intent)
        if "trial_policy" in intent:
            return _held("Layer trial policy is unsupported; hold before private/claim/Backfill", coverage)
        if intent.get("status") in ("cancelled", "paused", "deferred", "blocked"):
            return _held("Layer stopped or held; no addon execution recommendation", coverage)
        bindings = _case_bindings(intent.get("addons"))  # bundled entries removed
        if not bindings:
            return {"route": "unselected", "additional_reads": 0, "private_reads": 0,
                    "message": "retain existing ordinary consultation"}
        declaration = _yaml(_bytes(CONTRACT, [CONTRACT.parent], MAX_INPUT_BYTES))
        if declaration.get("schema_version") != "0.1":
            raise Held("unknown common contract schema")
        types = declaration["types"]
        selected = []
        for binding in bindings:
            _binding(binding, types)
            triple = {k: binding[k] for k in ("addon_id", "addon_version", "selection_ref")}
            if triple not in verified_selections:
                raise Held("selection/version not independently verified by current caller")
            if requested_addon is None or binding["addon_id"] == requested_addon:
                selected.append(binding)
        if len(selected) != 1:
            raise Held("unresolved multiple addon guides or requested addon missing")
        binding = selected[0]
        text_data, snapshots = [], [(case / "intent.yaml", raw_intent, roots)]
        for label in ("guide_ref", "common_contract_ref"):
            ref = binding[label]
            coverage["attempted_scope"].append(dict(ref))
            if ref["kind"] != "file":
                raise Held("page reference capability/version pin unsupported; no fallback")
            base = case if ref["scope"] == "case" else (Path(common_root).resolve(strict=True) if common_root else None)
            if base is None:
                raise Held("explicit common root missing")
            path = base / ref["relative_name"]
            raw = _bytes(path, roots, MAX_RESOURCE_BYTES)
            if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                raise Held("resource changed or pinned hash mismatch")
            text_data.append({"role": label, "ref": dict(ref), "text": raw.decode("utf-8"),
                              "trust": "task data only; not authority or executable commands"})
            snapshots.append((path, raw, roots))
            coverage["retrieved_count"] += 1
        backlog_path = case / "backlog.yaml"
        raw_backlog = _bytes(backlog_path, roots, MAX_INPUT_BYTES)
        backlog = _yaml(raw_backlog)
        if not intent.get("scope_id") or backlog.get("scope_id") != intent.get("scope_id"):
            raise Held("intent/backlog scope mismatch")
        snapshots.append((backlog_path, raw_backlog, roots))
        if request_kind not in ("operational_guidance", "plan_change"):
            raise Held("request kind unresolved; keep existing consultation classification")
        actions = _next(case, backlog, set(approved_task_ids), instant, roots, executor) if request_kind == "operational_guidance" else []
        for path, raw, read_roots in snapshots:
            limit = MAX_INPUT_BYTES if path.name in ("intent.yaml", "backlog.yaml") else MAX_RESOURCE_BYTES
            if _bytes(path, read_roots, limit) != raw:
                raise Held("source version changed during consultation")
        coverage["coverage_state"] = "retrieved"
        return {"route": request_kind if request_kind == "operational_guidance" else "existing_plan_change_classification",
                "next_actions": actions, "read_coverage": coverage,
                "execution_note": "実施：相談のみ（Task未実行）", "source_refs": [x["ref"] for x in text_data],
                "guide_data": text_data, "form_ids": [x["form_id"] for x in binding["forms"]][:binding["read_limits"]["max_form_items"]],
                "dispatch": False, "writes": False, "MatterTrace_generated": False}
    except (Held, OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError) as exc:
        return _held(type(exc).__name__ + ": " + str(exc), coverage)


# ADDON-INIT:BEGIN
ADDON_INIT_FIELDS = {"addon_id", "addon_version", "form_id", "declared_in", "manifest_sha256"}


def _addon_init_flag(intent, binding, form_id, read_case_file):
    """Validate optional intent.addon_init and return whether form_id is the declared initialization form.

    Absent addon_init keeps the previous behavior (False). A present but inconsistent declaration Holds;
    it never selects an addon, registers a Task, or grants a write.
    """
    init = intent.get("addon_init", None)
    if init is None:
        return False
    if not isinstance(init, dict) or set(init) - ADDON_INIT_FIELDS or not {"addon_id", "addon_version", "form_id"} <= set(init):
        raise Held("invalid addon_init declaration")
    for key in ("addon_id", "addon_version", "form_id"):
        _text(init[key], "addon_init." + key)
    if init["addon_id"] != binding["addon_id"]:
        return False  # the declaration belongs to another addon; this form is simply not the init form
    if init["addon_version"] != binding["addon_version"]:
        raise Held("addon_init does not match the current addon binding version")
    if init["form_id"] not in [f["form_id"] for f in binding["forms"]]:
        raise Held("addon_init form is not declared in the current addon binding")
    if ("declared_in" in init) != ("manifest_sha256" in init):
        raise Held("addon_init declared_in and manifest_sha256 must appear together")
    if "declared_in" in init:
        name = _text(init["declared_in"], "addon_init.declared_in")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise Held("addon_init manifest outside Layer")
        if hashlib.sha256(read_case_file(relative)).hexdigest() != init["manifest_sha256"]:
            raise Held("addon_init manifest hash mismatch")
    return init["form_id"] == form_id
# ADDON-INIT:END


# ADDON-NORMAL:BEGIN
def _normal_single_task(backlog, task_id, approved_task_ids):
    """Return "normal_single_task" only when no bulk execution record is active and exactly one Task was approved.

    The caller must derive approved_task_ids from the current human instruction for this one Task;
    this function cannot verify that. Any other contract/budget state falls back to the bulk check (and Holds there).
    Old completed records are ignored, never read as approval.
    """
    contract = backlog.get("execution_contract", None)
    budget = backlog.get("execution_budget", None)
    def finished_or_absent(record):
        return record is None or (isinstance(record, dict) and record.get("status") == "completed")
    approved = list(approved_task_ids or [])
    if (finished_or_absent(contract) and finished_or_absent(budget)
            and len(approved) == 1 and approved[0] == task_id):
        return "normal_single_task"
    return None
# ADDON-NORMAL:END


def task_inputs(layer, *, allowed_roots, verified_selections=(), common_root=None,
                stage="operation", form_selected=False, form_id=None, requested_addon=None,
                task_id=None, task_version=None, approved_task_ids=(),
                trial_requested=False, no_write_requested=False, now=None):
    """Read-only generation/transport/consumption of one explicitly selected form.

    The caller supplies current selection and operation authority independently.
    Data returned here never authorizes registration, dispatch, or writes.
    """
    instant = now or dt.datetime.now(dt.timezone.utc)
    coverage = {"source_ref": "Task addon inputs", "attempted_scope": [],
                "retrieved_count": 0, "coverage_state": "unknown", "missing_fields": [],
                "unreadable_items": [], "unknown_items": [], "as_of": instant.isoformat(),
                "evidence_ref": None}
    if trial_requested is not False or no_write_requested is not False:
        return _held("explicit/unknown trial unsupported before registration/AGT/private/claim", coverage)
    try:
        if stage not in ("inception", "construction", "operation", "collection_init"):
            raise Held("unknown Task input stage")
        if type(form_selected) is not bool or not allowed_roots or instant.tzinfo is None:
            raise Held("current form decision, finite roots and aware time required")
        case = Path(layer).resolve(strict=True)
        roots = [Path(p).resolve(strict=True) for p in allowed_roots]
        snapshots = []

        def read(path, read_roots=roots, limit=MAX_INPUT_BYTES):
            raw = _bytes(path, read_roots, limit)
            snapshots.append((path, raw, read_roots, limit))
            return raw

        intent = _yaml(read(case / "intent.yaml"))
        if "trial_policy" in intent or intent.get("status") in ("cancelled", "paused", "deferred", "blocked"):
            raise Held("Layer trial/stopped policy; hold before side effects")
        task = None
        if stage not in ("inception", "collection_init"):
            backlog = _yaml(read(case / "backlog.yaml"))
            if not intent.get("scope_id") or backlog.get("scope_id") != intent["scope_id"]:
                raise Held("intent/backlog scope mismatch")
            tasks = backlog.get("tasks")
            if not isinstance(tasks, list) or any(not isinstance(t, dict) for t in tasks):
                raise Held("invalid task list")
            ids = [t.get("id") for t in tasks]
            if any(not isinstance(x, str) for x in ids) or len(ids) != len(set(ids)):
                raise Held("duplicate/unknown task identities")
            matches = [t for t in tasks if t.get("id") == task_id]
            if len(matches) != 1 or not task_version or matches[0].get("task_version") != task_version:
                raise Held("current Task/version mismatch")
            task = matches[0]
            if task.get("status") not in ("pending", "in_progress"):
                raise Held("Task is stopped or terminal")
            if "addon_refs" in task:
                if not form_selected:
                    raise Held("current form selection removed while registered refs remain; no fallback")
                refs = task["addon_refs"]
                if not isinstance(refs, list) or len(refs) != 1:
                    raise Held("present addon_refs requires exactly one form; no fallback")
            elif form_selected:
                raise Held("selected form has no registered addon_refs")
            else:
                return {"route": "unselected", "additional_reads": 0, "private_reads": 0}
        elif not form_selected:
            return {"route": "unselected", "additional_reads": 0, "private_reads": 0}
        declaration = _yaml(read(TASK_CONTRACT, [TASK_CONTRACT.parent]))
        if declaration.get("schema_version") != "0.2" or declaration["types"]["TaskAddonRef"]["required_fields"] != ["addon_id", "addon_version", "form_id", "form_ref"]:
            raise Held("unsupported Task input contract")
        bindings = _case_bindings(intent.get("addons"), "selected form without current addon binding")
        if not bindings:
            raise Held("selected form without current addon binding")
        expected = None
        if task is not None:
            expected = refs[0]
            if not isinstance(expected, dict) or set(expected) != {"addon_id", "addon_version", "form_id", "form_ref"}:
                raise Held("TaskAddonRef requires exact four fields")
            for key in ("addon_id", "addon_version", "form_id"):
                _text(expected[key], key)
            _reference(expected["form_ref"])
            if form_id is not None and form_id != expected["form_id"]:
                raise Held("current form decision differs from registered Task")
            if requested_addon is not None and requested_addon != expected["addon_id"]:
                raise Held("current addon decision differs from registered Task")
            form_id, requested_addon = expected["form_id"], expected["addon_id"]
        _text(form_id, "explicit selected form_id")
        selected = []
        for binding in bindings:
            _binding(binding, declaration["types"])
            triple = {k: binding[k] for k in ("addon_id", "addon_version", "selection_ref")}
            if triple not in verified_selections:
                raise Held("current caller selection/version not independently verified")
            if requested_addon is None or requested_addon == binding["addon_id"]:
                selected.append(binding)
        if len(selected) != 1:
            raise Held("unresolved multiple addon bindings")
        binding = selected[0]
        forms = [f for f in binding["forms"] if f["form_id"] == form_id]
        if len(forms) != 1:
            raise Held("selected form missing from current binding")
        ref = {"addon_id": binding["addon_id"], "addon_version": binding["addon_version"],
               "form_id": form_id, "form_ref": forms[0]["form_ref"]}
        if expected is not None and expected != ref:
            raise Held("registered Task/form/version/hash changed; no automatic update")
        # ADDON-INIT:BEGIN 初期化タスクの宣言（intent.addon_init。無ければ従来どおり）
        is_init_form = _addon_init_flag(intent, binding, form_id, lambda rel: read(case / rel))
        # ADDON-INIT:END
        # COLLECTION-INIT:BEGIN Collection の最後の初期化の段（addon-seam.md の初期化の宣言）。宣言どおりの初期化の型だけを Task 無しで読む
        if stage == "collection_init" and is_init_form is not True:
            raise Held("collection_init reads only the declared initialization form (intent.addon_init)")
        # COLLECTION-INIT:END
        authorization_mode = None
        if stage == "operation":
            # ADDON-NORMAL:BEGIN 通常の1件の照合（実行の記録が無い又は終わっているときだけ。条件は addon-seam.md の同じ印の節）
            authorization_mode = _normal_single_task(backlog, task_id, approved_task_ids)
            # ADDON-NORMAL:END
        if stage == "operation" and authorization_mode is None:
            authorization_mode = "bulk_execution"
            contract, budget = backlog.get("execution_contract") or {}, backlog.get("execution_budget") or {}
            if (task_id not in approved_task_ids or contract.get("current_task") != task_id
                    or task_id not in contract.get("scope_tasks", [])
                    or (contract.get("task_versions") or {}).get(task_id) != task_version
                    or contract.get("status") != "running" or contract.get("authorization_scope") != "end_to_end"
                    or budget.get("status") != "running" or not budget.get("budget_id")
                    or contract.get("budget_id") != budget["budget_id"]):
                raise Held("current Task approval/contract mismatch")
            start = dt.datetime.fromisoformat(budget["started_at"].replace("Z", "+00:00"))
            stop = dt.datetime.fromisoformat(budget["deadline"].replace("Z", "+00:00"))
            if not start <= instant < stop:
                raise Held("current finite allocation unavailable")
            if budget.get("recording_reserved_from") and instant >= dt.datetime.fromisoformat(budget["recording_reserved_from"].replace("Z", "+00:00")):
                raise Held("recording-only reserve reached")
        if stage == "operation":
            states = {t["id"]: t.get("status") for t in tasks}
            deps = task.get("dependencies", [])
            if not isinstance(deps, list) or any(states.get(d) != "completed" for d in deps):
                raise Held("upstream Task completion unavailable; actual evidence checked by caller")
            required = (backlog.get("construction") or {}).get("tasks", [])
            if task_id in required:
                name = _text(task.get("command_template_ref"), "required AGT")
                relative = Path(name)
                if relative.is_absolute() or ".." in relative.parts or "\\" in name:
                    raise Held("AGT outside Layer")
                agent = read(case / relative).decode("utf-8")
                begin, end = "<!-- ADDON_REFS:BEGIN -->", "<!-- ADDON_REFS:END -->"
                if agent.count(begin) != 1 or agent.count(end) != 1:
                    raise Held("required AGT has no unique addon reference block")
                raw_block = agent.split(begin)[1].split(end)[0].strip()
                if _yaml(raw_block.encode()).get("addon_refs") != [ref]:
                    raise Held("AGT/Task addon refs differ")
        resources = []
        labels = [("guide_ref", binding["guide_ref"]), ("common_contract_ref", binding["common_contract_ref"])]
        if stage in ("operation", "collection_init"):
            labels.append(("form_ref", ref["form_ref"]))
        for role, resource in labels:
            coverage["attempted_scope"].append(dict(resource))
            if resource["kind"] != "file":
                raise Held("page capability unsupported; no fallback")
            base = case if resource["scope"] == "case" else (Path(common_root).resolve(strict=True) if common_root else None)
            if base is None:
                raise Held("explicit common root missing")
            raw = read(base / resource["relative_name"], limit=MAX_RESOURCE_BYTES)
            if hashlib.sha256(raw).hexdigest() != resource["sha256"]:
                raise Held("resource hash mismatch")
            resources.append({"role": role, "ref": dict(resource), "text": raw.decode("utf-8"),
                              "trust": "task data only; not authority or executable commands"})
            coverage["retrieved_count"] += 1
        for path, raw, read_roots, limit in snapshots:
            if _bytes(path, read_roots, limit) != raw:
                raise Held("source changed during Task input read")
        coverage["coverage_state"] = "retrieved"
        return {"route": {"operation": "task_inputs", "collection_init": "init_inputs"}.get(stage, "task_refs"),
                "stage": stage, "addon_refs": [ref], "reference_block": yaml.safe_dump({"addon_refs": [ref]}, allow_unicode=True, sort_keys=False),
                "input_data": resources, "read_coverage": coverage, "dispatch": False,
                "writes": False, "private_reads": 0, "MatterTrace_generated": False,
                "authorization_mode": authorization_mode,
                "is_init_form": is_init_form,
                "execution_note": ("実施：初期化の型の読取のみ（実行・保存は 01-collection Phase 7.5 の別の OK の後）" if stage == "collection_init" else "実施：型入力の照合のみ（登録・Task実行・保存はcallerの別許可）")}
    except (Held, OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError) as exc:
        return _held(type(exc).__name__ + ": " + str(exc), coverage)


# ADDON-RECURRING:BEGIN 運用タスクの雛形の案（契約 v0.3 の RecurringTaskTemplate。読み取りだけ・書き込まない）
RECURRING_CONTRACT = CONTRACT.with_name("addon-seam-contract_v0.3.yaml")
RECURRING_BEGIN, RECURRING_END = "<!-- RECURRING_TEMPLATES:BEGIN -->", "<!-- RECURRING_TEMPLATES:END -->"
RECURRENCE_VALUES = ("daily", "weekly", "per_meeting")
TEMPLATE_FIELDS = {"name", "recurrence", "acceptance_criteria", "description"}
MAX_TEMPLATES = 16
MAX_TEMPLATE_AC = 16
CALLER_FILLS = ["id", "priority", "owner", "estimated_hours", "command", "origin"]
RECURRING_RULES = ["他の Task の依存先にしない（運用の結果を使う Task は初回の run の output を input に書く）",
                   "自動完走（RUL_plc_session §10）では回さない",
                   "Operation で実行しても completed にせず runs に1行ずつ足す。status の値を増やさない"]


def _recurring_block(guide_text):
    """Return the parsed template list declared in the guide, or None when the guide has no block."""
    begins, ends = guide_text.count(RECURRING_BEGIN), guide_text.count(RECURRING_END)
    if begins == 0 and ends == 0:
        return None
    if begins != 1 or ends != 1 or guide_text.index(RECURRING_BEGIN) > guide_text.index(RECURRING_END):
        raise Held("recurring_templates block markers must appear exactly once in order")
    raw = guide_text.split(RECURRING_BEGIN)[1].split(RECURRING_END)[0].strip()
    block = _yaml(raw.encode("utf-8")) if raw else {}
    if set(block) != {"recurring_templates"}:
        raise Held("recurring_templates block must contain only recurring_templates")
    templates = block["recurring_templates"]
    if not isinstance(templates, list) or len(templates) > MAX_TEMPLATES:
        raise Held("recurring_templates must be a bounded list")
    names = []
    for item in templates:
        if not isinstance(item, dict) or set(item) - TEMPLATE_FIELDS:
            raise Held("unknown recurring template field")
        names.append(_text(item.get("name"), "recurring template name").strip())
        if item.get("recurrence") not in RECURRENCE_VALUES:
            raise Held("unknown recurring template recurrence: " + str(item.get("recurrence")))
        ac = item.get("acceptance_criteria")
        if not isinstance(ac, list) or not 0 < len(ac) <= MAX_TEMPLATE_AC:
            raise Held("recurring template acceptance_criteria must be a nonempty bounded list")
        for line in ac:
            _text(line, "recurring template acceptance criterion")
        if "description" in item:
            _text(item["description"], "recurring template description")
    if len(names) != len(set(names)):
        raise Held("duplicate recurring template name")
    return templates


def recurring_templates(layer, *, allowed_roots, verified_selections=(), common_root=None,
                        requested_addon=None, trial_requested=False, no_write_requested=False, now=None):
    """Inception proposals for recurring operation Tasks declared by the selected addon guide.

    Read-only: nothing is written to backlog/intent. The proposals need the human's approval of the
    Inception breakdown before the caller writes them. No declaration means zero proposals.
    """
    instant = now or dt.datetime.now(dt.timezone.utc)
    coverage = {"source_ref": "addon recurring task templates", "attempted_scope": [],
                "retrieved_count": 0, "coverage_state": "unknown", "missing_fields": [],
                "unreadable_items": [], "unknown_items": [], "as_of": instant.isoformat(),
                "evidence_ref": None}
    if trial_requested is not False or no_write_requested is not False:
        return {**_held("explicit/unknown trial unsupported before Inception proposals", coverage), "proposals": []}
    try:
        if not allowed_roots or instant.tzinfo is None:
            raise Held("explicit permitted roots and aware current time required")
        case = Path(layer).resolve(strict=True)
        roots = [Path(p).resolve(strict=True) for p in allowed_roots]
        snapshots = []

        def read(path, read_roots=roots, limit=MAX_INPUT_BYTES):
            raw = _bytes(path, read_roots, limit)
            snapshots.append((path, raw, read_roots, limit))
            return raw

        intent = _yaml(read(case / "intent.yaml"))
        if "trial_policy" in intent or intent.get("status") in ("cancelled", "paused", "deferred", "blocked"):
            raise Held("Layer trial/stopped policy; hold before proposals")
        bindings = _case_bindings(intent.get("addons"))  # bundled entries removed
        if not bindings:
            return {"route": "unselected", "proposals": [], "additional_reads": 0, "private_reads": 0,
                    "reason": "no addon binding; no recurring task templates", "writes": False}
        declaration = _yaml(read(RECURRING_CONTRACT, [RECURRING_CONTRACT.parent]))
        types = declaration.get("types") or {}
        if (declaration.get("schema_version") != "0.3" or "RecurringTaskTemplate" not in types
                or list(types["RecurringTaskTemplate"]["fields"]["recurrence"]["values"]) != list(RECURRENCE_VALUES)):
            raise Held("unsupported recurring template contract")
        selected = []
        for binding in bindings:
            _binding(binding, types)
            triple = {k: binding[k] for k in ("addon_id", "addon_version", "selection_ref")}
            if triple not in verified_selections:
                raise Held("current caller selection/version not independently verified")
            if requested_addon is None or requested_addon == binding["addon_id"]:
                selected.append(binding)
        if len(selected) != 1:
            raise Held("unresolved multiple addon bindings or requested addon missing")
        binding = selected[0]
        ref = binding["guide_ref"]
        coverage["attempted_scope"].append(dict(ref))
        if ref["kind"] != "file":
            raise Held("page capability unsupported; no fallback")
        base = case if ref["scope"] == "case" else (Path(common_root).resolve(strict=True) if common_root else None)
        if base is None:
            raise Held("explicit common root missing")
        raw_guide = read(base / ref["relative_name"], limit=MAX_RESOURCE_BYTES)
        if hashlib.sha256(raw_guide).hexdigest() != ref["sha256"]:
            raise Held("resource hash mismatch")
        coverage["retrieved_count"] += 1
        templates = _recurring_block(raw_guide.decode("utf-8"))
        existing = set()
        try:
            backlog = _yaml(read(case / "backlog.yaml"))
        except FileNotFoundError:
            backlog = None
        if backlog is not None:
            if backlog.get("scope_id") != intent.get("scope_id"):
                raise Held("intent/backlog scope mismatch")
            tasks = backlog.get("tasks") or []
            if not isinstance(tasks, list) or any(not isinstance(t, dict) for t in tasks):
                raise Held("invalid task list")
            existing = {(str(t.get("name", "")).strip(), t.get("recurrence")) for t in tasks}
        source = {"addon_id": binding["addon_id"], "addon_version": binding["addon_version"],
                  "guide_ref": dict(ref)}
        proposals, already = [], []
        for index, item in enumerate(templates or []):
            name = item["name"].strip()
            if (name, item["recurrence"]) in existing:
                already.append({"name": name, "recurrence": item["recurrence"]})
                continue
            task = {"id": "R?", "name": name}
            if "description" in item:
                task["description"] = item["description"]
            task.update({"type": "operation", "recurrence": item["recurrence"], "runs": [], "status": "pending",
                         "dependencies": [], "acceptance_criteria": list(item["acceptance_criteria"])})
            proposals.append({"task": task, "source": {**source, "template_index": index}})
        for path, raw, read_roots, limit in snapshots:
            if _bytes(path, read_roots, limit) != raw:
                raise Held("source changed during recurring template read")
        coverage["coverage_state"] = "retrieved"
        if templates is None:
            reason = "guide declares no recurring_templates; zero proposals"
        elif not templates:
            reason = "guide declares an empty recurring_templates list; zero proposals"
        else:
            reason = "%d proposal(s) from the selected addon guide" % len(proposals)
        return {"route": "recurring_proposals", "stage": "inception_recurring", "proposals": proposals,
                "already_in_backlog": already, "reason": reason, "caller_fills": CALLER_FILLS,
                "recurring_task_rules": RECURRING_RULES,
                "registration": "Inception の分解表に入れて本人の承認を取り、承認の後に backlog に書く（この返却は承認・登録ではない）",
                "read_coverage": coverage, "dispatch": False, "writes": False, "private_reads": 0,
                "MatterTrace_generated": False, "execution_note": "実施：雛形の案の読取のみ（backlog・intent へ書いていない）"}
    except (Held, OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError) as exc:
        return {**_held(type(exc).__name__ + ": " + str(exc), coverage), "proposals": []}
# ADDON-RECURRING:END


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", required=True)
    parser.add_argument("--read-root", action="append", required=True, help="actual caller-permitted finite read roots")
    parser.add_argument("--common-root")
    parser.add_argument("--selection", action="append", default=[], help="JSON current-verified addon_id/addon_version/selection_ref; not authentication")
    parser.add_argument("--request-kind", choices=["operational_guidance", "plan_change"], default="operational_guidance")
    parser.add_argument("--requested-addon")
    parser.add_argument("--approved-task", action="append", default=[])
    parser.add_argument("--trial-requested", action="store_true")
    parser.add_argument("--no-write-requested", action="store_true")
    parser.add_argument("--stage", choices=["consult", "inception", "construction", "operation", "collection_init", "inception_recurring"], default="consult")
    parser.add_argument("--form-selected", action="store_true")
    parser.add_argument("--form-id")
    parser.add_argument("--task-id")
    parser.add_argument("--task-version")
    parser.add_argument("--executor", choices=["codex", "claude-code"], default="codex",
                        help="current caller runtime; legacy API/CLI default remains Codex, not runtime proof")
    args = parser.parse_args()
    try:
        selection = [json.loads(value) for value in args.selection]
    except ValueError:
        parser.error("selection must be JSON data")
    if args.stage == "consult":
        result = consult(args.layer, allowed_roots=args.read_root, common_root=args.common_root,
                     verified_selections=selection, request_kind=args.request_kind,
                     requested_addon=args.requested_addon, approved_task_ids=args.approved_task,
                     trial_requested=args.trial_requested, no_write_requested=args.no_write_requested,
                     executor=args.executor)
    elif args.stage == "inception_recurring":  # ADDON-RECURRING 案を返すだけ（書き込まない）
        result = recurring_templates(args.layer, allowed_roots=args.read_root, common_root=args.common_root,
                                     verified_selections=selection, requested_addon=args.requested_addon,
                                     trial_requested=args.trial_requested, no_write_requested=args.no_write_requested)
    else:
        result = task_inputs(args.layer, allowed_roots=args.read_root, common_root=args.common_root,
                             verified_selections=selection, stage=args.stage, form_selected=args.form_selected,
                             form_id=args.form_id, requested_addon=args.requested_addon,
                             task_id=args.task_id, task_version=args.task_version, approved_task_ids=args.approved_task,
                             trial_requested=args.trial_requested, no_write_requested=args.no_write_requested)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["route"] != "held" else 1


if __name__ == "__main__":
    raise SystemExit(main())
