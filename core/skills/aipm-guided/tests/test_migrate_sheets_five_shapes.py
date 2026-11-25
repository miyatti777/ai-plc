"""migrate-sheets (nested_v1 route) for five more shapes of real boxes: a box holding only its Collection
init (1), a project_init.yaml with hand formatting (2), an evidence on project_init.yaml (3), sources read from inside the
box with their snapshots (4) and a shared Stock box before archive (5). Synthetic fixtures only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import re, tempfile, unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import test_integration as ti
import test_init_and_reset as tr
import test_migrate_layout as tml
import test_migrate_sheets_nested as tn
import registry_fixture as rf
package=ti.package;validate_package=ti.validate_package;write_yaml,sha=ti.write_yaml,ti.sha
NEST='Documents/aipm_project'

def drop_layout(layer):
    d=package.load(layer/'intent.yaml');d['aipm'].pop('layout',None);write_yaml(layer/'intent.yaml',d)

class FiveShapes(unittest.TestCase):
    setUp=tml.in_repository
    def tearDown(self):self.temp.cleanup()
    prepare=ti.CourseIntegration.prepare;mode_init_layer=ti.CourseIntegration.mode_init_layer;draft=ti.CourseIntegration.draft
    nested=tml.MigrateLayout.nested;legacy_box=tn.MigrateSheetsNested.legacy_box;registers_as_sources=ti.CourseIntegration.registers_as_sources
    def errors(self,layer,root,phase='prearchive'):return sorted({(e['code'],e['path']) for e in validate_package.validate(root,phase=phase,layer=layer)['errors']})

    # shape 1
    def init_only(self,name):
        layer,root,out=self.mode_init_layer(name,True,'solution_based/single_persona');drop_layout(layer)
        self.assertFalse((root/'manifest.yaml').exists());return layer,root
    def test_init_only_box_becomes_as_if_initialised_in_sheets(self):
        layer,root=self.init_only('i1');old_mi=package.load(layer/'intent.yaml')['mode_init']
        self.assertIsNotNone(package.mode_init_package(layer,root,package.build_contract(layer)))
        regs={q.name:sha(q) for q in (root/'registers').iterdir()}
        r=package.migrate_sheets(layer,apply=True,approval_ref='synthetic',program='Sample');self.assertTrue(r['applied'],r)
        sheets=layer/'Sheets';c=package.build_contract(layer);mi=package.load(layer/'intent.yaml')['mode_init']
        self.assertFalse((sheets/'manifest.yaml').exists());self.assertEqual(c['layout'],package.SHEETS_LAYOUT)
        self.assertEqual({q:sha(sheets/q) for q in regs},regs)   # the registers keep their bytes
        for o in mi['outputs']:
            if o['path'].endswith(('format_contract.yaml','project_init.yaml','README.md')):self.assertEqual(sha(layer/o['path']),o['sha256'],o['path'])   # init's files: the new bytes
        self.assertEqual(mi['done_at'],old_mi['done_at']);self.assertEqual(mi['migrations'][0]['outputs_before'],old_mi['outputs'])
        self.assertEqual(package.load(sheets/'project_init.yaml')['program_id'],'Sample')
        self.assertIsNotNone(package.mode_init_package(layer,sheets,c))   # the batch can continue it as a Sheets/ init
        # the course input written after the move carries the new roots (one written before keeps the old ones: rewrite it first)
        pk=package.load(layer/'Context/course_input.yaml');b=c['bindings'];fb,sb=package.init_roots(c)
        pk['drafts']['write_init_yaml'].update(program_id=b['program_id'],flow_base=fb,stock_base=sb);write_yaml(layer/'Context/course_input.yaml',pk)
        self.draft(layer);res=validate_package.validate(sheets,phase='prearchive',layer=layer);self.assertTrue(res['pass'],res['errors'])
    def test_init_only_box_edited_after_init_is_refused(self):
        layer,root=self.init_only('i2');c=package.build_contract(layer)
        q=root/c['flow_rel']/'project_init.yaml';q.write_text(q.read_text().replace('[unknown]','hand edit',1));before=tr.state(self.repo)
        with self.assertRaisesRegex(ValueError,'edited after init'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample')
        self.assertEqual(tr.state(self.repo),before)

    def test_init_only_box_with_an_intent_program_id_moves(self):
        layer,root=self.init_only('i3');q=layer/'intent.yaml';t=q.read_text()
        self.assertLess(t.index('aipm:'),t.index('mode_init:'))   # aipm comes first: the program_id rewrite shifts the text before mode_init
        q.write_text(t.replace('aipm:\n','aipm:\n  program_id: L_COURSE\n',1));self.assertEqual(package.load(q)['aipm']['program_id'],'L_COURSE')
        for prog in ('Sample','AnotherLongerProgramName'):
            (self.repo/'Stock/programs'/prog).mkdir(exist_ok=True)
        dry=package.migrate_sheets(layer,program='AnotherLongerProgramName');self.assertFalse(dry['applied'])
        r=package.migrate_sheets(layer,apply=True,approval_ref='s',program='AnotherLongerProgramName');self.assertTrue(r['applied'],r)
        it=package.load(q);self.assertEqual(it['aipm']['program_id'],'AnotherLongerProgramName');self.assertEqual(len(it['mode_init']['migrations']),1)

    # shape 2
    def test_hand_formatted_project_init_keeps_its_formatting(self):
        layer,root,c=self.nested('h2',pending=False);q=root/c['flow_rel']/'project_init.yaml'
        text='# hand note kept by the move\n'+q.read_text().replace('participant_name:','participant_name:  ',1)
        q.write_text(text);m=package.load(root/'manifest.yaml')
        for rec in m['records']:
            if rec['source_step']=='write_init_yaml':rec['sha256']=sha(q)
        write_yaml(root/'manifest.yaml',m);before=self.errors(layer,root)
        r=package.migrate_sheets(layer,apply=True,approval_ref='synthetic',program='Sample');self.assertTrue(r['applied'],r)
        new=(layer/'Sheets/project_init.yaml').read_text();self.assertTrue(new.startswith('# hand note kept by the move\n'))
        self.assertIn('participant_name:  ',new);d=package.load(layer/'Sheets/project_init.yaml')
        self.assertEqual((d['program_id'],d['flow_base']),('Sample','Sheets'))
        self.assertEqual(r['validate_after'],sorted({(k,p[len(c['flow_rel'])+1:] if p.startswith(c['flow_rel']+'/') else p) for k,p in before}))

    def test_hand_formatted_project_init_edited_after_its_record_is_refused(self):
        layer,root,c=self.nested('h3',pending=False);q=root/c['flow_rel']/'project_init.yaml'
        q.write_text('# hand note\n'+q.read_text().replace('[unknown]','SOMETHING ELSE',1));before=tr.state(self.repo)   # the record keeps the old sha256
        with self.assertRaisesRegex(ValueError,'differs from its manifest record'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample')
        self.assertEqual(tr.state(self.repo),before)

    # shape 3
    def test_evidence_on_project_init_is_read_through_the_recorded_rewrite(self):
        layer,root,c=self.legacy_box('e3',init_reply=False);m=package.load(root/'manifest.yaml')
        pi=next(r['path'] for r in m['records'] if r['source_step']=='write_init_yaml')
        m['evidence'].append({'id':'F3','kind':'hypothesis','source':NEST+'/'+pi,'source_sha256':sha(root/pi),'scope':'synthetic'});write_yaml(root/'manifest.yaml',m)
        self.assertTrue(validate_package.validate(root,phase='final',layer=layer)['pass'])
        r=package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=rf.db_path(self.registry));self.assertTrue(r['applied'],r)
        sheets=layer/'Sheets';res=validate_package.validate(sheets,phase='final',layer=layer);self.assertTrue(res['pass'],res['errors'])
        m2=package.load(sheets/'manifest.yaml');e=next(x for x in m2['evidence'] if x['id']=='F3')
        self.assertEqual(e['source'],'Sheets/project_init.yaml')
        self.assertNotEqual(sha(sheets/'project_init.yaml'),e['source_sha256'])   # bound to the bytes before the rewrite
        lm=m2['layout_migrations'][-1]
        for name,change in (('other bytes after',lambda x:x['rewritten'].update(sha256_after='0'*64)),('no record',lambda x:x.pop('rewritten')),('another path',lambda x:x['rewritten'].update(path='README.md'))):
            with self.subTest(case=name):
                x=dict(lm,rewritten=dict(lm['rewritten']));change(x);write_yaml(sheets/'manifest.yaml',dict(m2,layout_migrations=[x]))
                self.assertIn(('E_EVIDENCE','F3'),{(e_['code'],e_['path']) for e_ in validate_package.validate(sheets,phase='final',layer=layer)['errors']})
        write_yaml(sheets/'manifest.yaml',m2)

    # shape 4
    def snapshot_box(self,name):
        layer,root=self.registers_as_sources(name);self.draft(layer);drop_layout(layer)
        m=package.load(root/'manifest.yaml');self.assertTrue(m.get('source_snapshots'))
        w=package.load(root/'registers/wbs.yaml');w['wbs'][0]['evidence_refs']=[NEST+'/Flow/',NEST+'/Stock/'];write_yaml(root/'registers/wbs.yaml',w)   # the inner folders themselves
        return layer,root,m
    def test_sources_read_from_inside_the_box_are_read_from_their_moved_snapshots(self):
        layer,root,m=self.snapshot_box('s4');before=self.errors(layer,root)
        r=package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',retire='Documents/aipm_retired/s4');self.assertTrue(r['applied'],r)
        sheets=layer/'Sheets';m2=package.load(sheets/'manifest.yaml')
        self.assertTrue(all(v.startswith('Sheets/source_snapshots/') for v in m2['source_snapshots'].values()))
        self.assertEqual(m2['source_reads'],m['source_reads']);self.assertEqual(m2['input_packet'],m['input_packet'])   # the packet binds the old paths: kept
        self.assertEqual(package.load(sheets/'wbs.yaml')['wbs'][0]['evidence_refs'],['Sheets','Documents/aipm_retired/s4/aipm_project/Stock/'])
        flow=package.load(sheets/'format_contract.yaml')
        self.assertEqual(set(r['validate_after']),{(k,p_) for k,p_ in before})   # nothing new (the box keeps the errors it had, same paths: none of them are under the inner Flow/)
        lm=m2['layout_migrations'];write_yaml(sheets/'manifest.yaml',dict(m2,layout_migrations=[]))   # without the move record the snapshots are not read
        self.assertIn('E_COURSE',{e['code'] for e in validate_package.validate(sheets,phase='prearchive',layer=layer)['errors']})
        write_yaml(sheets/'manifest.yaml',dict(m2,layout_migrations=lm))
    def test_a_snapshot_moved_to_another_place_is_not_read(self):
        layer,root,m=self.snapshot_box('s6');r=package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',retire='Documents/aipm_retired/s6');self.assertTrue(r['applied'],r)
        sheets=layer/'Sheets';m2=package.load(sheets/'manifest.yaml');sid,v=next(iter(m2['source_snapshots'].items()))
        other=sheets/'source_snapshots/other.md';other.write_bytes((layer/v).read_bytes())   # the same bytes at another place
        write_yaml(sheets/'manifest.yaml',dict(m2,source_snapshots=dict(m2['source_snapshots'],**{sid:'Sheets/source_snapshots/other.md'})))
        self.assertIn('E_COURSE',{e['code'] for e in validate_package.validate(sheets,phase='prearchive',layer=layer)['errors']})
    def test_a_stray_file_in_source_snapshots_and_a_missing_retire_are_refused(self):
        layer,root,m=self.snapshot_box('s7');(root/'source_snapshots/stray.md').write_text('no snapshot names me');before=tr.state(self.repo)
        with self.assertRaisesRegex(ValueError,'unexpected file in source_snapshots'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',retire='Documents/aipm_retired/s7')
        (root/'source_snapshots/stray.md').unlink();before=tr.state(self.repo)
        with self.assertRaisesRegex(ValueError,'give --retire'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample')   # the registers name the retired folder
        self.assertEqual(tr.state(self.repo),before)
    def test_a_source_inside_the_box_without_its_snapshot_is_refused(self):
        layer,root,m=self.snapshot_box('s5');sid=next(iter(m['source_snapshots']));m['source_snapshots'].pop(sid);write_yaml(root/'manifest.yaml',m);before=tr.state(self.repo)
        with self.assertRaisesRegex(ValueError,'without its snapshot'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample')
        self.assertEqual(tr.state(self.repo),before)

    # shape 5
    def shared_box(self):
        import test_shared_stock_integration as ts
        if ts.seeds is None:self.skipTest(ts.NO_SEED)
        store=ts.shared_stock.FixtureStore();self.addCleanup(store.close);selector=ts.seeds.seed(store)
        layer=ts.layer_intent(store,selector,1);ts.shared_stock.collection(layer,store,adopted_folder='programs/p1/projects/b1')
        root,c=ts.generated_documents(layer,store);drop_layout(layer)
        repo=Path(tempfile.mkdtemp());self.addCleanup(lambda:__import__('shutil').rmtree(repo,ignore_errors=True));(repo/'Stock/programs/Sample').mkdir(parents=True)
        return layer,root,c,repo
    def test_shared_stock_box_before_archive_moves(self):
        layer,root,c,repo=self.shared_box();before=self.errors(layer,root)
        r=package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',stock_root=repo);self.assertTrue(r['applied'],r)
        nc=package.build_contract(layer);self.assertEqual((nc['layout'],nc['storage'],nc['stock_project_rel']),(package.SHEETS_LAYOUT,'registry_stock_v1','_charter'))
        flow=c['flow_rel']+'/'
        self.assertLessEqual(set(r['validate_after']),{(k,p_[len(flow):] if p_.startswith(flow) else p_) for k,p_ in before})   # no new error
    def test_shared_stock_box_after_archive_is_refused(self):
        layer,root,c,repo=self.shared_box();m=package.load(root/'manifest.yaml');m['stages'].append({'name':'archive'});write_yaml(root/'manifest.yaml',m);before=tr.state(layer)
        with self.assertRaisesRegex(ValueError,'shared Stock package is migrated only after its draft and before archive'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',stock_root=repo)
        self.assertEqual(tr.state(layer),before)

if __name__=='__main__':unittest.main()
