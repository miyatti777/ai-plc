"""Synthetic state fixtures; these are not actual human opt-ins or UI evidence."""
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parents[1] / 'recommendation.py'
# Staging has the same sibling module, prior to applying the approved write-set.
if not SCRIPT.exists():
    SCRIPT = Path(__file__).resolve().parent / 'recommendation.py'
spec = importlib.util.spec_from_file_location('collection_recommendation', SCRIPT)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
# <skills>/ai-plc/01-collection/tests: works in the source tree (core/skills) and the installed tree (.claude/skills).
AI_PLC = Path(__file__).resolve().parents[2]
CATALOG_VERSION = next(x['addon_version'] for x in yaml.safe_load((AI_PLC / 'references/addon-catalog.yaml').read_text())['addons'] if x['addon_id'] == 'aipm')


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / 'layer'
        self.root.mkdir()
        (self.root / 'Context').mkdir()
        self.intent({'scope_id': 'L-SYN', 'mode': 'direct', 'role': 'orchestrator',
                     'goal': {'description': 'Synthetic user discovery, not observed evidence'}})
        (self.root / 'Context/facts.md').write_text('Synthetic need and document value only.\n')

    def tearDown(self):
        self.temp.cleanup()

    def intent(self, obj):
        (self.root / 'intent.yaml').write_text(yaml.safe_dump(obj, allow_unicode=True, sort_keys=False))

    def current_intent(self):
        return yaml.safe_load((self.root / 'intent.yaml').read_text())

    def assessment(self, values=('yes', 'yes', 'yes')):
        ref = {'path': 'Context/facts.md', 'sha256': r.digest((self.root / 'Context/facts.md').read_bytes())}
        return {'version': 1, 'scope_id': 'L-SYN', 'conditions': {
            key: {'value': value, 'reason': 'Synthetic reason for ' + key, 'evidence_refs': [ref]}
            for key, value in zip(r.CONDITIONS, values)},
            'recommendation_reason': '利用者の課題と価値仮説を段階的に確かめたい'}

    def assessed(self, mode='normal'):
        return r.assess(self.root, self.assessment(), mode, apply=True)

    def receipt(self, answer='AIPM方式で進める', direct=False):
        state = r.Store(self.root).state
        obj = {'kind': 'user_reported', 'actor': 'actual_user', 'origin': 'actual_user_reply',
               'scope_id': 'L-SYN', 'source_thread_id': 'SYNTHETIC-ONLY', 'received_at': r.timestamp(),
               'question_id': None if direct else state['question']['id'],
               'target_path': state['snapshot'], 'target_sha256': state['snapshot_sha256'],
               'answer': answer, 'choice': r.answer_choice(answer)}
        if direct:
            obj['selection_source'] = 'actual_direct_selection'
        return obj

    def files(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_dry_run_assessment_and_status_write_nothing(self):
        before = self.files()
        result = r.assess(self.root, self.assessment())
        self.assertTrue(result['should_ask'])
        self.assertEqual(r.status(self.root)['route'], 'legacy_unselected')
        self.assertEqual(self.files(), before)

    def test_fit_question_single_source_no_repeat_no_project(self):
        before = (self.root / 'intent.yaml').read_bytes()
        result = self.assessed()
        self.assertEqual(result['question']['text'], r.QUESTION.format(reason=self.assessment()['recommendation_reason']))
        self.assertEqual(result['question']['options'], r.OPTIONS)
        repeat = r.assess(self.root, self.assessment(), apply=True)
        self.assertFalse(repeat['should_ask'])
        self.assertEqual(repeat['question'], result['question'])
        self.assertEqual((self.root / 'intent.yaml').read_bytes(), before)
        self.assertFalse((self.root / 'Documents').exists())

    def test_three_courses_use_shared_contract_without_auto_selection(self):
        for course in ['question_based/single_persona','solution_based/single_persona','document_based/single_persona']:
            with self.subTest(course=course):
                intent=self.current_intent();intent['aipm']={'course':course};self.intent(intent)
                before=self.files();result=r.assess(self.root,self.assessment())
                self.assertTrue(result['should_ask']);self.assertEqual(result['snapshot_content']['course'],course)
                self.assertEqual(self.files(),before)
                self.assertEqual(r.assess(self.root,self.assessment(('unknown','yes','yes')))['route'],'legacy_unknown')

    def test_explicit_selected_new_course_is_not_reasked(self):
        intent=self.current_intent();intent.update(work_style='aipm',aipm={'course':'document_based/single_persona'});self.intent(intent)
        before=self.files();result=r.assess(self.root)
        self.assertEqual(result['route'],'selected_existing');self.assertTrue(result['course_supported']);self.assertFalse(result['should_ask']);self.assertEqual(self.files(),before)

    def test_derived_conditions_and_unsupported_course(self):
        for value, route in [('no', 'legacy_not_fit'), ('unknown', 'legacy_unknown')]:
            data = self.assessment((value, 'yes', 'yes'))
            data['verdict'] = 'recommend'  # untrusted output must be derived
            result = r.assess(self.root, data)
            self.assertEqual(result['route'], route)
            self.assertFalse(result['should_ask'])
        intent = self.current_intent()
        intent['aipm'] = {'course': 'unsupported_multi_persona'}
        self.intent(intent)
        self.assertEqual(r.assess(self.root, self.assessment())['route'], 'legacy_not_fit')

    def test_label_only_does_not_override_missing_semantic_conditions(self):
        obj = self.current_intent()
        obj['goal']['description'] = 'PdM 開発 マーケティング PM'
        self.intent(obj)
        result = r.assess(self.root, self.assessment(('unknown', 'yes', 'unknown')))
        self.assertEqual(result['route'], 'legacy_unknown')
        bad = self.assessment()
        bad['conditions']['document_value']['reason'] = ''
        with self.assertRaises(ValueError):
            r.assess(self.root, bad)

    def test_equivalent_paths_cannot_reference_mutable_metadata_or_self(self):
        self.assessed()
        for alias in ('./intent.yaml', './context.yaml', './backlog.yaml',
                      'Context/./aipm_recommendation/state.json'):
            canonical = Path(alias).as_posix()
            target = self.root / canonical
            if not target.exists():
                target.write_text('synthetic: metadata\n')
            data = self.assessment()
            data['conditions']['discovery_needed']['evidence_refs'] = [
                {'path': alias, 'sha256': r.digest(target.read_bytes())}]
            before = self.files()
            with self.assertRaisesRegex(ValueError, 'avoid mutable metadata/self'):
                r.assess(self.root, data, apply=True)
            self.assertEqual(self.files(), before)

    def test_actual_input_alias_is_saved_as_canonical_relative_path(self):
        data = self.assessment()
        data['conditions']['discovery_needed']['evidence_refs'][0]['path'] = './Context/./facts.md'
        result = r.assess(self.root, data)
        snapshot = result['snapshot_content']
        self.assertEqual(snapshot['evidence'][0]['path'], 'Context/facts.md')
        self.assertEqual(snapshot['conditions']['discovery_needed']['evidence_refs'][0]['path'], 'Context/facts.md')

    def test_actual_selection_preserves_unrelated_intent_and_default_init_boundary(self):
        self.assessed()
        before = self.current_intent()
        result = r.respond(self.root, self.receipt(), apply=True)
        self.assertEqual(result['route'], 'aipm')
        after = self.current_intent()
        # Stage 2: only the bundled entry in addons; no work_style / work_style_source.
        entry, = after.pop('addons')
        self.assertEqual({k: entry[k] for k in ('addon_id', 'source', 'addon_version')},
                         {'addon_id': 'aipm', 'source': 'bundled', 'addon_version': CATALOG_VERSION})
        self.assertTrue(entry['selection_ref'].startswith(r.BASE + '/receipts/'))
        self.assertNotIn('work_style', after)
        self.assertNotIn('work_style_source', after)
        self.assertEqual(after, before)
        self.assertEqual(r.assess(self.root, apply=True)['route'], 'selected_existing')
        self.assertFalse((self.root / 'Documents').exists())

    def test_decline_is_stored_in_context_without_standard_style(self):
        self.assessed()
        r.respond(self.root, self.receipt('通常方式で進める'), apply=True)
        self.assertNotIn('work_style', self.current_intent())
        self.assertEqual(r.assess(self.root, apply=True)['route'], 'legacy_declined')

    def test_existing_selection_without_state_or_with_pending_cache_is_authoritative(self):
        for pending_cache in (False, True):
            if pending_cache:
                obj = self.current_intent()
                obj.pop('work_style', None)
                self.intent(obj)
                self.assessed()
            obj = self.current_intent()
            obj['work_style'] = 'aipm'
            obj['work_style_source'] = 'synthetic legacy source preserved'
            self.intent(obj)
            before = self.files()
            for result in (r.status(self.root), r.assess(self.root, apply=True)):
                self.assertEqual(result['route'], 'selected_existing')
                self.assertEqual(result['selection'], 'selected')
                self.assertEqual(result['status'], 'selected')
                self.assertFalse(result['should_ask'])
            self.assertEqual(self.files(), before)

    def test_blank_quote_accepted_and_ambiguous_do_not_select(self):
        self.assessed()
        before = (self.root / 'intent.yaml').read_bytes()
        for answer in ['', '「AIPM方式で進める」', 'accepted', 'A', 'たぶん', 'キャンセル']:
            reply = self.receipt(answer)
            result = r.respond(self.root, reply, apply=True)
            self.assertEqual(result['selection'], 'unselected')
            self.assertEqual((self.root / 'intent.yaml').read_bytes(), before)
        reply = self.receipt()
        reply['origin'] = 'ui_accepted'
        with self.assertRaises(ValueError):
            r.respond(self.root, reply, apply=True)

    def test_dry_run_response_does_not_mutate(self):
        self.assessed()
        before = self.files()
        self.assertEqual(r.respond(self.root, self.receipt())['route'], 'aipm')
        self.assertEqual(self.files(), before)

    def test_cancel_keeps_unselected_and_rejects_old_reply(self):
        self.assessed()
        reply = self.receipt()
        r.cancel(self.root, apply=True)
        with self.assertRaises(ValueError):
            r.respond(self.root, reply, apply=True)
        self.assertFalse(r.assess(self.root, self.assessment(), apply=True)['should_ask'])
        self.assertNotIn('work_style', self.current_intent())

    def test_auto_force_conservative_and_normal_resume(self):
        for mode in ('auto', 'force'):
            result = r.assess(self.root, self.assessment(), mode, apply=True)
            self.assertEqual(result['route'], 'legacy_' + mode)
            self.assertFalse(result['should_ask'])
            self.assertIsNone(result['question'])
            self.assertNotIn('work_style', self.current_intent())
        result = self.assessed()
        self.assertTrue(result['should_ask'])
        self.assertFalse(r.assess(self.root, self.assessment(), 'force')['should_ask'])

    def test_stale_goal_or_evidence_refuses_reply_and_status_marks_stale(self):
        self.assessed()
        reply = self.receipt()
        (self.root / 'Context/facts.md').write_text('Changed evidence')
        with self.assertRaises(ValueError):
            r.respond(self.root, reply, apply=True)
        self.assertEqual(r.status(self.root)['route'], 'stale')
        result = self.assessed()
        self.assertNotEqual(result['snapshot_sha256'], reply['target_sha256'])
        with self.assertRaises(ValueError):
            r.respond(self.root, reply, apply=True)
        obj = self.current_intent()
        obj['goal']['description'] = 'Changed goal'
        self.intent(obj)
        with self.assertRaises(ValueError):
            r.respond(self.root, self.receipt(), apply=True)

    def test_receipt_identity_target_time_and_raw_answer_mismatch_all_refused(self):
        self.assessed()
        for key, value in [('scope_id', 'L-OTHER'), ('question_id', 'old'), ('target_sha256', '0'*64),
                           ('actor', 'ai'), ('source_thread_id', ''), ('choice', 'standard'),
                           ('received_at', '2020-01-01T00:00:00+00:00'),
                           ('received_at', (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())]:
            before = self.files()
            reply = self.receipt()
            reply[key] = value
            with self.assertRaises(ValueError):
                r.respond(self.root, reply, apply=True)
            self.assertEqual(self.files(), before)

    def test_direct_selection_without_question_and_explicit_release(self):
        # Save the actual-direct-shaped utterance BEFORE its bound assessment.
        # This fixture remains synthetic and cannot prove external authorship.
        source_rel = 'Context/direct.yaml'
        for answer in ('AIPM方式で進める', '通常方式で進める'):
            source = {'kind': 'user_reported', 'actor': 'actual_user', 'origin': 'actual_user_reply',
                      'scope_id': 'L-SYN', 'answer': answer, 'source_thread_id': 'SYNTHETIC-ONLY',
                      'received_at': r.timestamp()}
            (self.root / source_rel).write_text(yaml.safe_dump(source, allow_unicode=True))
            data = self.assessment()
            data['conditions']['discovery_needed']['evidence_refs'].append(
                {'path': source_rel, 'sha256': r.digest((self.root / source_rel).read_bytes())})
            r.assess(self.root, data, 'force', apply=True)
            reply = self.receipt(answer, direct=True)
            reply.update(source, direct_source_path=source_rel)
            r.respond(self.root, reply, direct=True, apply=True)
            self.assertNotIn('work_style', self.current_intent())
            self.assertEqual(r.pm_selected(self.current_intent()), answer.startswith('AIPM'))
        self.assertFalse((self.root / 'Documents').exists())

    def test_direct_without_bound_source_refused(self):
        self.assessed('force')
        with self.assertRaises(ValueError):
            r.respond(self.root, self.receipt(direct=True), direct=True, apply=True)

    def test_invalid_style_and_cross_layer_scope_are_not_silently_fixed(self):
        obj = self.current_intent()
        obj['work_style'] = True
        self.intent(obj)
        before = self.files()
        with self.assertRaises(ValueError):
            r.assess(self.root, self.assessment(), apply=True)
        self.assertEqual(self.files(), before)
        obj.pop('work_style')
        self.intent(obj)
        data = self.assessment()
        data['scope_id'] = 'L-OTHER'
        with self.assertRaises(ValueError):
            r.assess(self.root, data, apply=True)

    def test_traversal_symlink_external_and_duplicate_inputs_refused(self):
        outside = self.root.parent / 'outside.json'
        outside.write_text('{}')
        (self.root / 'Context/link.json').symlink_to(outside)
        for input_path in ('../outside.json', str(outside), 'Context/link.json'):
            with self.assertRaises(ValueError):
                r.assess(self.root, input_path, apply=True)
        duplicate = self.root / 'Context/duplicate.json'
        duplicate.write_text('{"version":1,"version":1}')
        with self.assertRaises(ValueError):
            r.assess(self.root, 'Context/duplicate.json', apply=True)
        with self.assertRaises(ValueError):
            r.parse(b'key: one\nkey: two\n', '.yaml')

    def test_cas_detects_concurrent_evidence_before_any_state_write(self):
        store = r.Store(self.root)
        store.read('Context/facts.md')
        (self.root / 'Context/facts.md').write_text('Other writer')
        with self.assertRaises(ValueError):
            store.commit({r.BASE + '/state.json': r.encoded({})})
        self.assertFalse((self.root / r.BASE).exists())

    def test_transaction_failure_restores_exact_intent_and_new_files(self):
        store = r.Store(self.root)
        original = (self.root / 'intent.yaml').read_bytes()
        obj = copy.deepcopy(store.intent)
        obj['work_style'] = 'aipm'
        with self.assertRaises(OSError):
            store.commit({'intent.yaml': yaml.safe_dump(obj).encode(),
                          r.BASE + '/state.json': r.encoded({'scope_id': 'L-SYN', 'layer_root': str(self.root)})}, fail_after=1)
        self.assertEqual((self.root / 'intent.yaml').read_bytes(), original)
        self.assertFalse((self.root / r.BASE / 'state.json').exists())
        self.assertEqual(r.Store(self.root).load(r.BASE+'/journal.json')['status'], 'reverted')

    def test_final_commit_write_failure_does_not_leave_false_committed_archive(self):
        self.assessed()
        before = (self.root / 'intent.yaml').read_bytes()
        previous_id = r.Store(self.root).load(r.BASE + '/journal.json')['id']
        actual_atomic = r.atomic

        def fail_final(path, raw):
            if path.name == 'journal.json' and r.parse(raw).get('status') == 'committed':
                raise OSError('synthetic final journal failure')
            return actual_atomic(path, raw)

        with patch.object(r, 'atomic', side_effect=fail_final):
            with self.assertRaises(OSError):
                r.respond(self.root, self.receipt(), apply=True)
        self.assertEqual((self.root / 'intent.yaml').read_bytes(), before)
        self.assertEqual(r.Store(self.root).state['status'], 'pending')
        journal = r.Store(self.root).load(r.BASE + '/journal.json')
        self.assertEqual(journal['status'], 'reverted')
        archive_dir = self.root / r.BASE / 'transactions'
        archives = list(archive_dir.glob('*.json'))
        self.assertEqual([p.stem for p in archives], [previous_id])
        self.assertTrue(all(r.parse(p.read_bytes())['status'] == 'committed' for p in archives))

    def test_previous_committed_journal_is_archived_on_next_successful_change(self):
        self.assessed()
        previous = r.Store(self.root).read(r.BASE + '/journal.json')
        previous_id = r.parse(previous)['id']
        r.respond(self.root, self.receipt(), apply=True)
        archived = self.root / r.BASE / 'transactions' / (previous_id + '.json')
        self.assertEqual(archived.read_bytes(), previous)
        self.assertEqual(r.Store(self.root).load(r.BASE + '/journal.json')['status'], 'committed')

    def test_recovery_other_writer_conflict_refuses_all_targets(self):
        store = r.Store(self.root)
        original = (self.root / 'intent.yaml').read_bytes()
        obj = copy.deepcopy(store.intent)
        obj['work_style'] = 'aipm'
        with patch.object(r, 'recover_layer', side_effect=ValueError('fixture crash before recovery')):
            with self.assertRaises(ValueError):
                store.commit({'intent.yaml': yaml.safe_dump(obj).encode(),
                              r.BASE + '/new.json': b'{}'}, fail_after=1)
        (self.root / r.BASE / 'new.json').write_bytes(b'OTHER WRITER')
        changed = (self.root / 'intent.yaml').read_bytes()
        with self.assertRaises(ValueError):
            r.recover_layer(self.root, apply=True)
        self.assertEqual((self.root / 'intent.yaml').read_bytes(), changed)
        self.assertNotEqual(changed, original)
        self.assertEqual((self.root / r.BASE / 'new.json').read_bytes(), b'OTHER WRITER')

    def test_cli_status_and_irrelevant_flags(self):
        result = subprocess.run([sys.executable, '-B', str(SCRIPT), 'status', '--layer', str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['route'], 'legacy_unselected')
        for flags in (['status', '--apply'], ['cancel', '--assessment', 'x'], ['respond']):
            result = subprocess.run([sys.executable, '-B', str(SCRIPT), *flags, '--layer', str(self.root)], capture_output=True)
            self.assertEqual(result.returncode, 2)


def load_selector():
    sel_spec = importlib.util.spec_from_file_location('t002_selector', AI_PLC / 'scripts/plc_addon_select.py')
    module = importlib.util.module_from_spec(sel_spec)
    saved = list(sys.path)
    try:
        sel_spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


CASE = {'addon_id': 'synthetic-case', 'addon_version': '0.1', 'selection_ref': 'Context/selection.md'}


class BundledAddonWriteTests(RecommendationTests):
    """The choice is written as the bundled entry in intent.addons (synthetic fixtures only)."""

    def test_selection_reads_as_selected_by_the_selector(self):
        self.assessed()
        r.respond(self.root, self.receipt(), apply=True)
        result = load_selector().selected_addons(self.root, read_roots=[str(self.root)])
        self.assertEqual(result['route'], 'selected')
        self.assertEqual([s['addon_id'] for s in result['selected']], ['aipm'])
        self.assertEqual(result['selected'][0]['via'], 'addons')
        self.assertTrue(result['selected'][0]['selection_verified'])
        self.assertEqual(result['work_style_value'], 'aipm')

    def test_after_selection_status_and_assess_are_selected_existing(self):
        self.assessed()
        r.respond(self.root, self.receipt(), apply=True)
        before = self.files()
        for result in (r.status(self.root), r.assess(self.root, apply=True)):
            self.assertEqual(result['route'], 'selected_existing')
            self.assertEqual(result['selection'], 'selected')
        self.assertEqual(self.files(), before)

    def test_decline_removes_pm_from_both_fields_and_keeps_case_entries(self):
        obj = self.current_intent()
        obj['work_style'] = None
        obj['addons'] = [dict(CASE)]
        self.intent(obj)
        self.assessed()
        r.respond(self.root, self.receipt('通常方式で進める'), apply=True)
        after = self.current_intent()
        self.assertNotIn('work_style', after)
        self.assertNotIn('work_style_source', after)
        self.assertEqual(after['addons'], [CASE])
        self.assertEqual(r.assess(self.root, apply=True)['route'], 'legacy_declined')

    def test_decline_without_case_entries_drops_the_addons_field(self):
        self.assessed()
        r.respond(self.root, self.receipt('通常方式で進める'), apply=True)
        self.assertNotIn('addons', self.current_intent())

    def test_without_pm_drops_stale_bundled_entry(self):
        obj = {'scope_id': 'L-SYN', 'addons': [dict(CASE), {'addon_id': 'aipm', 'source': 'bundled',
                                                          'addon_version': '2.0'}], 'work_style': 'aipm'}
        self.assertEqual(r.without_pm(obj), {'scope_id': 'L-SYN', 'addons': [CASE]})
        self.assertTrue(r.pm_selected({'addons': obj['addons']}))
        self.assertFalse(r.pm_selected({'addons': [dict(CASE)]}))
        self.assertFalse(r.pm_selected({'addons': 'aipm'}))

    def test_case_entries_keep_order_and_bundled_is_appended(self):
        second = dict(CASE, addon_id='synthetic-case-2')
        obj = self.current_intent()
        obj['addons'] = [dict(CASE), second]
        self.intent(obj)
        self.assessed()
        r.respond(self.root, self.receipt(), apply=True)
        addons = self.current_intent()['addons']
        self.assertEqual(addons[:2], [CASE, second])
        self.assertEqual((addons[2]['addon_id'], addons[2]['source']), ('aipm', 'bundled'))

    def test_failed_selection_restores_intent_and_recovery_accepts_the_addons_change(self):
        self.assessed()
        before = (self.root / 'intent.yaml').read_bytes()
        actual_atomic = r.atomic

        def fail_final(path, raw):
            if path.name == 'journal.json' and r.parse(raw).get('status') == 'committed':
                raise OSError('synthetic final journal failure')
            return actual_atomic(path, raw)

        with patch.object(r, 'atomic', side_effect=fail_final):
            with self.assertRaises(OSError):
                r.respond(self.root, self.receipt(), apply=True)
        self.assertEqual((self.root / 'intent.yaml').read_bytes(), before)
        self.assertEqual(r.Store(self.root).load(r.BASE + '/journal.json')['status'], 'reverted')

    def test_recovery_refuses_a_journal_that_changes_case_entries(self):
        obj = self.current_intent()
        obj['addons'] = [dict(CASE)]
        self.intent(obj)
        store = r.Store(self.root)
        changed = copy.deepcopy(store.intent)
        changed['addons'] = [dict(CASE, addon_version='0.2'),
                             {'addon_id': 'aipm', 'source': 'bundled', 'addon_version': CATALOG_VERSION}]
        with patch.object(r, 'recover_layer', side_effect=ValueError('fixture crash before recovery')):
            with self.assertRaises(ValueError):
                store.commit({'intent.yaml': yaml.safe_dump(changed).encode(),
                              r.BASE + '/new.json': b'{}'}, fail_after=1)
        with self.assertRaisesRegex(ValueError, 'unrelated intent fields'):
            r.recover_layer(self.root, apply=True)

    def test_existing_legacy_work_style_is_not_rewritten(self):
        obj = self.current_intent()
        obj['work_style'] = 'aipm'
        obj['work_style_source'] = 'synthetic legacy source preserved'
        self.intent(obj)
        before = self.files()
        self.assertEqual(r.assess(self.root, self.assessment(), apply=False)['route'], 'selected_existing')
        self.assertEqual(r.status(self.root)['route'], 'selected_existing')
        self.assertEqual(self.files(), before)

    def test_legacy_work_style_source_is_removed_on_selection_and_decline(self):
        # A Layer that kept work_style_source from an earlier decline (old writer) answers again
        for answer in ('AIPM方式で進める', '通常方式で進める'):
            with self.subTest(answer=answer):
                self.tearDown(); self.setUp()
                obj = self.current_intent()
                obj['work_style_source'] = r.BASE + '/receipts/old-decline.json'
                self.intent(obj)
                self.assessed()
                r.respond(self.root, self.receipt(answer), apply=True)
                after = self.current_intent()
                self.assertNotIn('work_style_source', after)
                self.assertNotIn('work_style', after)
                self.assertEqual(r.pm_selected(after), answer.startswith('AIPM'))
                if answer.startswith('AIPM'):
                    self.assertTrue(after['addons'][0]['selection_ref'].startswith(r.BASE + '/receipts/'))
                    self.assertNotEqual(after['addons'][0]['selection_ref'], r.BASE + '/receipts/old-decline.json')
                else:
                    self.assertNotIn('addons', after)

    def test_null_addons_failure_restores_and_recovery_accepts(self):
        # addons: null before, the bundled entry after; the automatic recovery must accept it
        obj = self.current_intent()
        obj['addons'] = None
        self.intent(obj)
        self.assessed()
        before = (self.root / 'intent.yaml').read_bytes()
        actual_atomic = r.atomic

        def fail_final(path, raw):
            if path.name == 'journal.json' and r.parse(raw).get('status') == 'committed':
                raise OSError('synthetic final journal failure')
            return actual_atomic(path, raw)

        with patch.object(r, 'atomic', side_effect=fail_final):
            with self.assertRaises(OSError):
                r.respond(self.root, self.receipt(), apply=True)
        self.assertEqual((self.root / 'intent.yaml').read_bytes(), before)
        self.assertEqual(r.Store(self.root).load(r.BASE + '/journal.json')['status'], 'reverted')
        self.assertEqual(r.without_pm({'scope_id': 'L-SYN', 'addons': None}), {'scope_id': 'L-SYN'})
        r.respond(self.root, self.receipt(), apply=True)
        self.assertEqual(self.current_intent()['addons'][0]['addon_id'], 'aipm')

    def test_selector_unavailable_writes_nothing(self):
        self.assessed()
        before = self.files()
        with patch.object(r, 'selector', side_effect=ValueError('selector unavailable: synthetic')):
            with self.assertRaisesRegex(ValueError, 'selector unavailable'):
                r.respond(self.root, self.receipt(), apply=True)
        self.assertEqual(self.files(), before)


# Reuse the fixtures only; the inherited RecommendationTests cases are not collected twice.
for _name in [n for n in vars(RecommendationTests) if n.startswith('test_')]:
    setattr(BundledAddonWriteTests, _name, None)
del _name

if __name__ == '__main__':
    unittest.main()
