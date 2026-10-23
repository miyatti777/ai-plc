#!/usr/bin/env python3
"""Bounded Collection recommendation records. No LLM, UI, project generation or network.

Typed receipts cannot prove external authorship. The invoking agent must compare
the actual user utterance before constructing a receipt; fixtures are synthetic.
"""
from __future__ import annotations

import argparse
import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

import yaml

sys.dont_write_bytecode = True
BASE = 'Context/aipm_recommendation'
COURSE = 'question_based/single_persona'
CONDITIONS = ('discovery_needed', 'course_supported', 'document_value')
OPTIONS = ['AIPM方式で進める', '通常方式で進める']
QUESTION = ('{reason}のため、AIPM方式をおすすめします。現在対応する1人の利用者の課題から'
            'ストーリーまで、19の指定形式文書を段階的に残して進めますか？')


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key: ' + str(key))
        result[key] = value
    return result


class UniqueLoader(yaml.SafeLoader):
    pass


def yaml_map(loader, node, deep=False):
    return unique_pairs([(loader.construct_object(k, deep=deep), loader.construct_object(v, deep=deep))
                         for k, v in node.value])


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, yaml_map)


def parse(raw, suffix='.json'):
    return yaml.load(raw, Loader=UniqueLoader) if suffix in ('.yaml', '.yml') else json.loads(raw, object_pairs_hook=unique_pairs)


def safe(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('unsafe relative path')
    path = root / relative
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError('symlink path refused')
    if not path.resolve().is_relative_to(root):
        raise ValueError('path outside Layer')
    if path.exists() and not path.is_file():
        raise ValueError('expected regular file: ' + relative)
    return path


def instant(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be text')
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError('timezone required')
    return dt


def atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


PM_ADDON = 'aipm'
_SELECTOR = None


def selector():
    """.claude/skills/ai-plc/scripts/plc_addon_select.py, loaded once by file path.
    Used only for the catalog version of the bundled PM addon. sys.path is restored afterwards."""
    global _SELECTOR
    if _SELECTOR is None:
        import importlib.util
        path = Path(__file__).resolve().parents[1] / 'scripts' / 'plc_addon_select.py'   # .claude/skills/ai-plc/scripts
        saved = list(sys.path)
        try:
            spec = importlib.util.spec_from_file_location('_aiplc_addon_select', path)
            if spec is None or not path.is_file():
                raise ImportError('missing ' + str(path))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:
            raise ValueError('selector unavailable: ' + type(exc).__name__ + ': ' + str(exc)) from exc
        finally:
            sys.path[:] = saved
        _SELECTOR = module
    return _SELECTOR


def is_pm_entry(item):
    return isinstance(item, dict) and item.get('source') == 'bundled' and item.get('addon_id') == PM_ADDON


def pm_selected(intent):
    """The bundled PM addon in intent.addons, or the legacy work_style: aipm. Not the Stage judgement (that is the
    selector, which also holds on case declarations); this only reads what this recommendation wrote."""
    addons = intent.get('addons')
    return intent.get('work_style') == 'aipm' or isinstance(addons, list) and any(is_pm_entry(x) for x in addons)


def without_pm(intent):
    """intent without the PM selection fields (both the new bundled entry and the legacy fields)."""
    obj = copy.deepcopy(intent)
    for key in ('work_style', 'work_style_source'):
        obj.pop(key, None)
    # Same shape as respond(): addons None/[] or only the PM entry -> no addons key.
    addons = obj.get('addons', None)
    if addons is None or isinstance(addons, list):
        rest = [x for x in (addons or []) if not is_pm_entry(x)]
        if rest:
            obj['addons'] = rest
        else:
            obj.pop('addons', None)
    return obj


class Store:
    def __init__(self, layer, allow_unfinished=False):
        original = Path(layer).absolute()
        if any(p.is_symlink() for p in [original, *original.parents]):
            raise ValueError('symlink Layer refused; use its canonical authorized path')
        self.root = original.resolve(strict=True)
        self.expected = {}
        self.intent_raw = self.read('intent.yaml')
        self.intent = parse(self.intent_raw, '.yaml')
        if not isinstance(self.intent, dict) or not isinstance(self.intent.get('scope_id'), str) or not self.intent['scope_id']:
            raise ValueError('intent.scope_id required')
        self.scope = self.intent['scope_id']
        if self.intent.get('work_style') not in (None, 'aipm'):
            raise ValueError('unsupported work_style; do not silently change intent')
        journal = self.load(BASE + '/journal.json')
        if journal and journal.get('status') == 'prepared' and not allow_unfinished:
            raise ValueError('unfinished transaction; inspect journal and recover_layer before another mutation')
        self.state = self.load(BASE + '/state.json') or {}
        if self.state and (self.state.get('scope_id') != self.scope or self.state.get('layer_root') != str(self.root)):
            raise ValueError('state scope/root mismatch')

    def read(self, rel, optional=False):
        path = safe(self.root, rel)
        raw = path.read_bytes() if path.exists() else None
        self.expected.setdefault(rel, digest(raw) if raw is not None else None)
        if raw is None and not optional:
            raise ValueError('missing file: ' + rel)
        return raw

    def load(self, rel):
        raw = self.read(rel, optional=True)
        return None if raw is None else parse(raw, Path(rel).suffix)

    def input(self, path):
        path = Path(path)
        if path.is_absolute():
            try:
                relative = path.relative_to(self.root).as_posix()
            except ValueError:
                raise ValueError('input outside Layer') from None
        else:
            relative = path.as_posix()
        return parse(self.read(relative), path.suffix)

    def verify_expected(self):
        for rel, expected in self.expected.items():
            path = safe(self.root, rel)
            current = digest(path.read_bytes()) if path.exists() else None
            if current != expected:
                raise ValueError('concurrent change: ' + rel)

    def commit(self, changes, fail_after=None):
        if not changes:
            return
        for rel in changes:
            if rel != 'intent.yaml' and not rel.startswith(BASE + '/'):
                raise ValueError('mutation outside recommendation write-set')
            self.read(rel, optional=True)
        self.verify_expected()
        # Archive the PREVIOUS proven commit before preparing this transaction.
        # The current journal remains authoritative until the final commit write;
        # a failed final write must never leave a false committed archive behind.
        previous_raw = self.read(BASE + '/journal.json', optional=True)
        previous = None if previous_raw is None else parse(previous_raw)
        if previous and previous.get('status') == 'committed':
            previous_id = previous.get('id')
            if (not isinstance(previous_id, str) or len(previous_id) != 32
                    or any(c not in '0123456789abcdef' for c in previous_id)
                    or previous.get('scope_id') != self.scope
                    or previous.get('layer_root') != str(self.root)):
                raise ValueError('invalid previous transaction journal')
            archive_rel = BASE + '/transactions/' + previous_id + '.json'
            archived = self.read(archive_rel, optional=True)
            if archived is not None and archived != previous_raw:
                raise ValueError('previous journal archive conflict')
            if archived is None:
                atomic(safe(self.root, archive_rel), previous_raw)
                self.expected[archive_rel] = digest(previous_raw)
        self.verify_expected()
        records = []
        for rel, after in changes.items():
            path = safe(self.root, rel)
            before = path.read_bytes() if path.exists() else None
            records.append({'path': rel, 'before': None if before is None else base64.b64encode(before).decode(),
                            'before_sha256': None if before is None else digest(before),
                            'after': base64.b64encode(after).decode(), 'after_sha256': digest(after)})
        journal = {'scope_id': self.scope, 'layer_root': str(self.root), 'id': uuid.uuid4().hex,
                   'created_at': timestamp(), 'status': 'prepared', 'entries': records}
        journal_path = safe(self.root, BASE + '/journal.json')
        atomic(journal_path, encoded(journal))
        try:
            for index, entry in enumerate(records):
                path = safe(self.root, entry['path'])
                before_hash = digest(path.read_bytes()) if path.exists() else None
                if before_hash != entry['before_sha256']:
                    raise ValueError('concurrent change during transaction: ' + entry['path'])
                atomic(path, base64.b64decode(entry['after'], validate=True))
                if fail_after == index:
                    raise OSError('injected transaction failure')
            journal['status'] = 'committed'
            atomic(journal_path, encoded(journal))
        except Exception:
            recover_layer(self.root, apply=True)
            raise


def recover_layer(layer, apply=False):
    """Explicit recovery, all-target preflight; never undo an unknown third-party edit."""
    store = Store(layer, allow_unfinished=True)
    journal = store.load(BASE + '/journal.json')
    if not journal or journal.get('status') != 'prepared':
        return {'recovery': 'not_needed'}
    if journal.get('scope_id') != store.scope or journal.get('layer_root') != str(store.root):
        raise ValueError('journal scope/root mismatch')
    seen = set()
    for entry in journal['entries']:
        rel = entry['path']
        if rel in seen or (rel != 'intent.yaml' and not rel.startswith(BASE + '/')):
            raise ValueError('invalid journal write-set')
        seen.add(rel)
        path = safe(store.root, rel)
        before = None if entry['before'] is None else base64.b64decode(entry['before'], validate=True)
        after = base64.b64decode(entry['after'], validate=True)
        if (None if before is None else digest(before)) != entry['before_sha256'] or digest(after) != entry['after_sha256']:
            raise ValueError('journal bytes/hash mismatch')
        if rel == 'intent.yaml':
            first, last = parse(before, '.yaml'), parse(after, '.yaml')
            for obj in (first, last):
                if obj.get('scope_id') != store.scope:
                    raise ValueError('journal intent scope mismatch')
            if without_pm(first) != without_pm(last):
                raise ValueError('journal changes unrelated intent fields')
        current = digest(path.read_bytes()) if path.exists() else None
        if current not in (entry['before_sha256'], entry['after_sha256']):
            raise ValueError('recovery conflict: ' + rel)
    if apply:
        for entry in reversed(journal['entries']):
            path = safe(store.root, entry['path'])
            if entry['before'] is None:
                if path.exists():
                    path.unlink()
            else:
                atomic(path, base64.b64decode(entry['before'], validate=True))
        journal['status'] = 'reverted'
        atomic(safe(store.root, BASE + '/journal.json'), encoded(journal))
    return {'recovery': 'reverted' if apply else 'ready', 'entries': len(journal['entries'])}


def goal_hash(store):
    return digest(encoded(store.intent.get('goal', {})))


def course(store):
    settings = store.intent.get('aipm', {})
    if not isinstance(settings, dict):
        raise ValueError('aipm must be a map')
    return settings.get('course', COURSE)


def existing(store):
    if pm_selected(store.intent):
        return 'selected_existing'
    if store.state.get('selection') == 'declined':
        return 'legacy_declined'
    if store.state.get('selection') == 'selected':
        return 'legacy_selection_changed_externally'
    return None


def result(route, state=None, should_ask=False, question=None):
    state = state or {}
    # The explicit existing intent flag is authoritative even when no legacy
    # recommendation state exists, or the cached state still says pending.
    selected_existing = route == 'selected_existing'
    return {'route': route, 'selection': 'selected' if selected_existing else state.get('selection', 'unselected'),
            'status': 'selected' if selected_existing else state.get('status', route), 'should_ask': should_ask,
            'question': question, 'snapshot': state.get('snapshot'),
            'snapshot_sha256': state.get('snapshot_sha256')}


def current_snapshot(store, state=None):
    state = state or store.state
    rel = state.get('snapshot')
    if not isinstance(rel, str) or not rel.startswith(BASE + '/snapshots/'):
        raise ValueError('missing recommendation snapshot')
    raw = store.read(rel)
    if digest(raw) != state.get('snapshot_sha256'):
        raise ValueError('snapshot hash mismatch')
    snap = parse(raw)
    if snap.get('scope_id') != store.scope or snap.get('goal_hash') != goal_hash(store) or snap.get('course') != course(store):
        raise ValueError('stale snapshot goal/scope/course')
    for ref in snap['evidence']:
        if digest(store.read(ref['path'])) != ref['sha256']:
            raise ValueError('stale snapshot evidence')
    return snap


def course_supported(store):
    contract_path=Path(__file__).resolve().parents[2]/'aipm-guided/course_contracts.yaml'
    registry=parse(contract_path.read_bytes(),'.yaml')
    if not isinstance(registry,dict) or registry.get('version')!=1 or set(registry.get('courses',{}))!={COURSE,'solution_based/single_persona','document_based/single_persona'}:
        raise ValueError('unknown local AIPM course contract/version')
    selected=course(store)
    return isinstance(selected,str) and selected in registry.get('courses',{})


def question_text(store, reason):
    if course(store)==COURSE:return QUESTION.format(reason=reason)
    label={'solution_based/single_persona':'ソリューションを仮説として整理する','document_based/single_persona':'既存資料を対応付け、不足を補完する'}[course(store)]
    return reason+'のため、AIPM方式をおすすめします。'+label+'コースで、19の指定形式文書を作り、必要な不足だけ確認して進めますか？'


def assessment_snapshot(store, assessment):
    if not isinstance(assessment, dict) or type(assessment.get('version')) is not int or assessment['version'] != 1:
        raise ValueError('assessment version=1 required')
    if assessment.get('scope_id') != store.scope:
        raise ValueError('assessment scope mismatch')
    conditions = assessment.get('conditions')
    if not isinstance(conditions, dict) or set(conditions) != set(CONDITIONS):
        raise ValueError('all three conditions required')
    conditions = copy.deepcopy(conditions)
    refs = {}
    for item in conditions.values():
        if not isinstance(item, dict) or item.get('value') not in ('yes', 'no', 'unknown'):
            raise ValueError('condition value must be yes/no/unknown')
        if not isinstance(item.get('reason'), str) or not item['reason'].strip():
            raise ValueError('condition reason required')
        if not isinstance(item.get('evidence_refs'), list):
            raise ValueError('evidence_refs must be a list; Goal is bound separately')
        for ref in item['evidence_refs']:
            if not isinstance(ref, dict) or not isinstance(ref.get('path'), str):
                raise ValueError('invalid evidence reference')
            rel = safe(store.root, ref['path']).relative_to(store.root).as_posix()
            ref['path'] = rel
            if rel in ('intent.yaml', 'context.yaml', 'backlog.yaml') or rel.startswith(BASE + '/'):
                raise ValueError('use goal_hash and actual input documents; avoid mutable metadata/self references')
            if digest(store.read(rel)) != ref.get('sha256'):
                raise ValueError('evidence hash mismatch')
            refs[rel] = ref['sha256']
    reason = assessment.get('recommendation_reason')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('recommendation_reason required')
    verdict = ('not_fit' if any(x['value'] == 'no' for x in conditions.values()) else
               'unknown' if any(x['value'] == 'unknown' for x in conditions.values()) else 'recommend')
    if not course_supported(store):
        verdict = 'not_fit'
    return {'version': 1, 'scope_id': store.scope, 'goal_hash': goal_hash(store),
            'course': course(store), 'conditions': conditions,
            'evidence': [{'path': path, 'sha256': sha} for path, sha in sorted(refs.items())],
            'recommendation_reason': reason, 'verdict': verdict, 'required_documents': 19}


def assess(layer, assessment=None, execution_mode='normal', apply=False):
    if execution_mode not in ('normal', 'auto', 'force'):
        raise ValueError('invalid execution_mode')
    store = Store(layer)
    prior = existing(store)
    if prior and assessment is None:
        output = result(prior, store.state)
        output['course_supported'] = course_supported(store)
        return output
    if assessment is None:
        raise ValueError('assessment required for unselected Layer')
    data = store.input(assessment) if isinstance(assessment, (str, Path)) else assessment
    snap = assessment_snapshot(store, data)
    basis_hash = digest(encoded(snap))
    state = copy.deepcopy(store.state)
    same = state.get('basis_sha256') == basis_hash
    if not prior and same and (state.get('status') in ('pending', 'cancelled') or state.get('status') == 'deferred' and execution_mode != 'normal'):
        current_snapshot(store)
        question = state.get('question') if execution_mode == 'normal' and state.get('status') == 'pending' else None
        return result('pending' if question else 'legacy_' + execution_mode if execution_mode != 'normal' else 'cancelled', state, False, question)
    changes = {}
    if same:
        current_snapshot(store)
        rel, snapshot_hash = state['snapshot'], state['snapshot_sha256']
    else:
        snap['created_at'] = timestamp()
        raw = encoded(snap)
        snapshot_hash = digest(raw)
        rel = BASE + '/snapshots/' + snapshot_hash + '.json'
        if store.read(rel, optional=True) is not None:
            raise ValueError('immutable snapshot already exists unexpectedly')
        changes[rel] = raw
    history = state.get('history', [])
    if state:
        history = history + [{key: state.get(key) for key in ('status', 'selection', 'snapshot', 'snapshot_sha256', 'question')}]
    state = {'version': 1, 'scope_id': store.scope, 'layer_root': str(store.root),
             'selection': 'unselected', 'basis_sha256': basis_hash, 'snapshot': rel,
             'snapshot_sha256': snapshot_hash, 'history': history, 'execution_mode': execution_mode}
    should_ask = not prior and snap['verdict'] == 'recommend' and execution_mode == 'normal'
    state['status'] = 'pending' if should_ask else 'deferred' if snap['verdict'] == 'recommend' else snap['verdict']
    if prior:
        state['selection'] = 'selected' if pm_selected(store.intent) else store.state.get('selection', 'unselected')
        state['status'] = prior
    question = None
    if should_ask:
        question = {'id': 'aipm-' + snapshot_hash[:20], 'scope_id': store.scope,
                    'text': question_text(store,snap['recommendation_reason']), 'options': OPTIONS.copy(),
                    'target_path': rel, 'target_sha256': snapshot_hash, 'created_at': timestamp()}
        state['question'] = question
    changes[BASE + '/state.json'] = encoded(state)
    if apply:
        store.commit(changes)
    output = result(prior if prior else 'pending' if should_ask else 'legacy_' + execution_mode if state['status'] == 'deferred' else 'legacy_' + state['status'], state, should_ask, question)
    output['verdict'] = snap['verdict']
    output['snapshot_content'] = snap
    return output


def answer_choice(answer):
    if not isinstance(answer, str):
        raise ValueError('answer must preserve the user text')
    value = answer.strip()
    if value in ('AIPM方式で進める', 'AIPM方式', 'aipm', 'AIPMで進める'):
        return 'aipm'
    if value in ('通常方式で進める', '通常方式', 'standard', '通常方式にする'):
        return 'standard'
    return 'pending'


def respond(layer, receipt, direct=False, apply=False):
    store = Store(layer)
    receipt = store.input(receipt) if isinstance(receipt, (str, Path)) else copy.deepcopy(receipt)
    snap = current_snapshot(store)
    state = copy.deepcopy(store.state)
    if not isinstance(receipt, dict) or receipt.get('kind') != 'user_reported' or receipt.get('actor') != 'actual_user' or receipt.get('origin') != 'actual_user_reply':
        raise ValueError('actual user receipt required; accepted/auto/quotation is not a reply')
    if receipt.get('scope_id') != store.scope or receipt.get('target_path') != state['snapshot'] or receipt.get('target_sha256') != state['snapshot_sha256']:
        raise ValueError('receipt scope/target mismatch')
    if not isinstance(receipt.get('source_thread_id'), str) or not receipt['source_thread_id'].strip():
        raise ValueError('actual utterance source required')
    observed = instant(receipt.get('received_at'))
    if observed > datetime.now(timezone.utc) or not direct and observed < instant(snap['created_at']):
        raise ValueError('receipt timestamp outside target lifetime')
    if direct:
        if receipt.get('selection_source') != 'actual_direct_selection' or receipt.get('question_id') is not None:
            raise ValueError('direct selection must be an explicit current instruction, without a question ID')
        # A direct instruction precedes its assessment. Bind its saved verbatim source
        # into that assessment rather than pretending it answered a later question.
        source_rel = receipt.get('direct_source_path')
        if source_rel not in [ref['path'] for ref in snap['evidence']]:
            raise ValueError('direct instruction source must be snapshot evidence')
        source = parse(store.read(source_rel), Path(source_rel).suffix)
        fields = ('kind', 'actor', 'origin', 'scope_id', 'answer', 'source_thread_id', 'received_at')
        if not isinstance(source, dict) or any(source.get(key) != receipt.get(key) for key in fields):
            raise ValueError('direct instruction source/receipt mismatch')
    else:
        question = state.get('question')
        if state.get('status') != 'pending' or not question or receipt.get('question_id') != question['id']:
            raise ValueError('question missing/cancelled/stale/already answered')
        if observed < instant(question['created_at']):
            raise ValueError('answer predates question')
    choice = answer_choice(receipt.get('answer'))
    if receipt.get('choice') != choice:
        raise ValueError('choice does not match clear original answer')
    if choice == 'aipm' and not course_supported(store):
        raise ValueError('unsupported course; request Re-Collection')
    state.setdefault('history', []).append({key: state.get(key) for key in ('status', 'selection', 'snapshot', 'question')})
    state['selection'] = 'selected' if choice == 'aipm' else 'declined' if choice == 'standard' else state.get('selection', 'unselected')
    state['status'] = 'selected' if choice == 'aipm' else 'declined' if choice == 'standard' else state.get('status', 'pending')
    receipt_raw = encoded(receipt)
    receipt_path = BASE + '/receipts/' + digest(receipt_raw) + '.json'
    changes = {receipt_path: receipt_raw}
    if store.read(receipt_path, optional=True) is not None:
        raise ValueError('receipt already processed')
    state['last_receipt'] = receipt_path
    changes[BASE + '/state.json'] = encoded(state)
    if choice != 'pending':
        # Stage 2: the choice is written only as the bundled entry in intent.addons; the legacy
        # work_style / work_style_source are not written. A decline removes the PM from both fields. Both legacy
        # fields are PM fields (as in without_pm) and are removed on a decline and on a new selection.
        intent = copy.deepcopy(store.intent)
        addons = intent.get('addons')
        if addons is not None and not isinstance(addons, list):
            raise ValueError('intent.addons must be a list; do not silently change intent')
        rest = [x for x in (addons or []) if not is_pm_entry(x)]
        intent.pop('work_style', None)
        intent.pop('work_style_source', None)
        if choice == 'aipm':
            module = selector()
            try:
                version = module.load_catalog()['rows'][PM_ADDON]['addon_version']
            except (module.Hold, KeyError) as exc:
                raise ValueError('bundled addon catalog unreadable: ' + str(exc)) from exc
            intent['addons'] = rest + [{'addon_id': PM_ADDON, 'source': 'bundled', 'addon_version': version,
                                        'selection_ref': receipt_path}]
        elif rest:
            intent['addons'] = rest
        else:
            intent.pop('addons', None)
        changes['intent.yaml'] = yaml.safe_dump(intent, allow_unicode=True, sort_keys=False).encode()
    if apply:
        store.commit(changes)
    return result('aipm' if choice == 'aipm' else 'legacy_declined' if choice == 'standard' else 'pending', state)


def cancel(layer, apply=False):
    store = Store(layer)
    current_snapshot(store)
    state = copy.deepcopy(store.state)
    if state.get('status') != 'pending':
        raise ValueError('only a current pending question can be cancelled')
    state['status'] = 'cancelled'
    state['cancelled_at'] = timestamp()
    if apply:
        store.commit({BASE + '/state.json': encoded(state)})
    return result('cancelled', state)


def status(layer):
    store = Store(layer)
    prior = existing(store)
    if prior:
        return result(prior, store.state)
    if not store.state:
        return result('legacy_unselected')
    try:
        current_snapshot(store)
    except ValueError as exc:
        return {**result('stale', store.state), 'error': str(exc)}
    return result(store.state.get('status', 'legacy_unselected'), store.state)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('assess', 'respond', 'cancel', 'status'))
    parser.add_argument('--layer', required=True)
    parser.add_argument('--assessment')
    parser.add_argument('--receipt')
    parser.add_argument('--execution-mode', choices=('normal', 'auto', 'force'))
    parser.add_argument('--direct', action='store_true')
    parser.add_argument('--apply', action='store_true', help='persist records; not an additional human approval')
    args = parser.parse_args(argv)
    if args.assessment and args.action != 'assess' or args.receipt and args.action != 'respond' or args.direct and args.action != 'respond' or args.execution_mode and args.action != 'assess' or args.apply and args.action == 'status':
        parser.error('argument does not apply to action')
    if args.action == 'respond' and not args.receipt:
        parser.error('respond requires --receipt')
    try:
        if args.action == 'assess':
            output = assess(args.layer, args.assessment, args.execution_mode or 'normal', args.apply)
        elif args.action == 'respond':
            output = respond(args.layer, args.receipt, args.direct, args.apply)
        elif args.action == 'cancel':
            output = cancel(args.layer, args.apply)
        else:
            output = status(args.layer)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, yaml.YAMLError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
