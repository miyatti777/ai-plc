"""package.py migrate-sheets moves one box_root_v1 package (Documents/aipm_project/) to sheets_v1
(<Layer>/Sheets/). Dry-run by default; --apply needs an approval reference; files keep bytes and mtime; the registers move
up from registers/; bound replies (Context receipts, never rewritten) and archived packages keep validating; any failure
puts everything back. Synthetic repository, Registry and boxes only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import os, unittest
from unittest import mock
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent));sys.path.insert(0,str(HERE))
import package, validate_package
import test_integration as ti, test_init_and_reset as tr, test_box_root_compat as bc
write_yaml,sha=ti.write_yaml,ti.sha
REGISTERS=('issues','hypotheses','todo','wbs','roadmap')

def no_intent_layout(layer):
    """Like the real boxes: the saved format_contract decides the layout, intent has no aipm.layout."""
    d=package.load(layer/'intent.yaml');d['aipm'].pop('layout',None);write_yaml(layer/'intent.yaml',d)

def files(root):
    """package-relative path -> (sha256, mtime_ns) of every file under root."""
    return {q.relative_to(root).as_posix():(sha(q),q.stat().st_mtime_ns) for q in root.rglob('*') if q.is_file()}

class MigrateSheets(unittest.TestCase):
    setUp=bc.in_repository
    def tearDown(self):self.temp.cleanup()
    prepare=bc.box_root_prepare;mode_init_layer=ti.CourseIntegration.mode_init_layer;draft=ti.CourseIntegration.draft
    def drafted(self,name):
        """A drafted box_root_v1 package with registers and mode_init (like a real box before archive)."""
        layer,root,out=self.mode_init_layer(name,True);self.draft(layer)
        self.assertEqual(root,layer/'Documents/aipm_project');self.assertTrue((root/'registers/issues.yaml').is_file())
        w=package.load(root/'registers/wbs.yaml');w['wbs'][0]['evidence_refs']=['Documents/aipm_project/'];write_yaml(root/'registers/wbs.yaml',w)
        no_intent_layout(layer);return layer,root
    def bound(self,name):
        """A box_root_v1 package whose persona and validation replies are bound by Context receipts."""
        layer,c,packet=self.prepare(name,pending=True)
        packet['decisions']['validation']={'state':'pending','reason':'Choosing validation hypotheses is the user call','scope':'reversible_draft_only','source_ids':['M1','M2'],'question':'Use H1 for validation?'}
        for key in ('persona','validation'):packet['gaps'].append({'kind':'unknown','reason':'needs the user','requires_user':True,'decision_key':key,'question':'?'})
        write_yaml(layer/'Context/course_input.yaml',packet);root=self.draft(layer)
        def ask(n,**over):
            d={'stage':'persona','question':'Which actual persona should be used?','answer':'Synthetic reply only','question_id':'SYN-'+n,'source_thread_id':'SYNTHETIC-THREAD','answered_at':ti.now()};d.update(over)
            write_yaml(layer/'Context'/(n+'.yaml'),d);return 'Context/'+n+'.yaml'
        self.assertTrue(package.receipt(layer,ask('p'))['bound'])
        v=package.load(root/'validation_record.yaml');write_yaml(root/'validation_checkpoint.yaml',{k:x for k,x in v.items() if k!='actual_new_user_response'})
        self.assertTrue(package.receipt(layer,ask('v',stage='validation',question='Use H1 for validation?',answered_at=ti.now()))['pass'])
        self.assertTrue(validate_package.validate(root,phase='prearchive',layer=layer)['pass'])
        no_intent_layout(layer);return layer,root

    def test_dry_run_shows_the_plan_and_writes_nothing(self):
        layer,root=self.drafted('dry');before=tr.state(layer)
        out=package.migrate_sheets(layer)
        self.assertFalse(out['applied']);self.assertEqual(out['rename'],{'from':'Documents/aipm_project','to':'Sheets'})
        self.assertEqual({(x['from'],x['to']) for x in out['moves']},{('registers/'+n+'.yaml',n+'.yaml') for n in REGISTERS})
        self.assertIn({'file':'Sheets/wbs.yaml','from':'Documents/aipm_project/','to':'Sheets/'},out['rewrites'])
        self.assertEqual(out['validate_phase'],'prearchive');self.assertEqual(tr.state(layer),before)

    def test_apply_moves_the_box_and_keeps_every_document(self):
        layer,root=self.drafted('app');before=files(root);intent_before=package.load(layer/'intent.yaml')
        with self.assertRaisesRegex(ValueError,'approval-ref'):package.migrate_sheets(layer,apply=True)
        self.assertEqual(files(root),before)
        out=package.migrate_sheets(layer,apply=True,approval_ref='synthetic approval');self.assertTrue(out['applied'])
        new=layer/'Sheets';self.assertFalse(root.exists());self.assertFalse((new/'registers').exists())
        after=files(new);rewritten={'format_contract.yaml','manifest.yaml','project_init.yaml','wbs.yaml'}
        for rel,(h,mt) in before.items():
            moved=rel[len('registers/'):] if rel.startswith('registers/') else rel
            self.assertIn(moved,after,rel)
            if moved not in rewritten:self.assertEqual(after[moved],(h,mt),rel)   # bytes and mtime kept
        c=package.load(new/'format_contract.yaml');self.assertEqual((c['layout'],c['package_root']),(package.SHEETS_LAYOUT,'Sheets'))
        self.assertEqual(package.build_contract(layer),c)
        self.assertEqual(package.load(new/'project_init.yaml')['flow_base'],'Sheets')
        self.assertEqual(after['project_init.yaml'][1],before['project_init.yaml'][1])   # its generation time is kept
        self.assertEqual(package.load(new/'wbs.yaml')['wbs'][0]['evidence_refs'],['Sheets/'])
        m=package.load(new/'manifest.yaml');mig=m['layout_migrations'][-1]
        self.assertEqual((mig['from'],mig['to'],mig['package'],mig['approval_ref']),(package.BOX_ROOT_LAYOUT,package.SHEETS_LAYOUT,{'from':'Documents/aipm_project','to':'Sheets'},'synthetic approval'))
        self.assertEqual(next(r for r in m['records'] if r['path']=='project_init.yaml')['sha256'],sha(new/'project_init.yaml'))
        outs=package.load(layer/'intent.yaml')['mode_init']['outputs']
        self.assertEqual([o['path'] for o in outs],[o['path'].replace('Documents/aipm_project/registers/','Sheets/').replace('Documents/aipm_project/','Sheets/') for o in intent_before['mode_init']['outputs']])
        self.assertEqual([o['sha256'] for o in outs],[o['sha256'] for o in intent_before['mode_init']['outputs']])
        r=validate_package.validate(new,phase='prearchive',layer=layer);self.assertTrue(r['pass'],r['errors'])
        with self.assertRaisesRegex(ValueError,'already sheets_v1'):package.migrate_sheets(layer)   # once moved, nothing more to move

    def test_bound_replies_keep_validating_and_the_receipts_are_not_rewritten(self):
        layer,root=self.bound('rcpt');receipts={q.name:sha(q) for q in (layer/'Context').glob('*.yaml')}
        package.migrate_sheets(layer,apply=True,approval_ref='synthetic')
        new=layer/'Sheets';r=validate_package.validate(new,phase='prearchive',layer=layer);self.assertTrue(r['pass'],r['errors'])
        self.assertEqual({q.name:sha(q) for q in (layer/'Context').glob('*.yaml')},receipts)
        m=package.load(new/'manifest.yaml')
        self.assertTrue(all(h['target_path'].startswith('Sheets/') for h in m['human_responses'].values()))
        receipt=package.load(layer/m['human_responses']['persona']['source']);self.assertTrue(receipt['target_path'].startswith('Documents/aipm_project/'))
        # the old target path is only read through a recorded move (by migrate-sheets) that came after the reply
        import copy
        for name,change in (('move before the reply',lambda x:x.update(at='2000-01-01T00:00:00+00:00')),('not by the tool',lambda x:x.update(by='by hand')),
                            ('other prefixes',lambda x:x.update(package={'from':'Documents/other','to':'Sheets'})),('no record',None)):
            with self.subTest(case=name):
                t=copy.deepcopy(m)
                if change is None:t['layout_migrations'].pop()
                else:change(t['layout_migrations'][-1])
                write_yaml(new/'manifest.yaml',t)
                self.assertIn('E_CHECKPOINT',{e['code'] for e in validate_package.validate(new,phase='prearchive',layer=layer)['errors']})
        write_yaml(new/'manifest.yaml',m);self.assertTrue(validate_package.validate(new,phase='prearchive',layer=layer)['pass'])

    def test_an_archived_box_keeps_its_final(self):
        layer,root=self.drafted('arc');self.assertTrue(package.archive_course(layer)['pass'])
        m=package.load(root/'manifest.yaml');box=tr.state(layer)
        with self.assertRaisesRegex(ValueError,'has versions'):package.migrate_sheets(layer,apply=True,approval_ref='synthetic')   # a box with versions is not moved
        self.assertEqual(tr.state(layer),box)
        m.pop('applies');write_yaml(root/'manifest.yaml',m);(self.repo/m['archive_target']['target_rel']/package.APPLY_LOG).unlink()   # archived before the versions (like a real box)
        stock=tr.state(self.repo/'Stock')
        out=package.migrate_sheets(layer,apply=True,approval_ref='synthetic');self.assertEqual(out['validate_phase'],'final')
        r=validate_package.validate(layer/'Sheets',phase='final',layer=layer);self.assertTrue(r['pass'],r['errors'])
        self.assertEqual(tr.state(self.repo/'Stock'),stock)   # the Stock copies are not touched

    def test_refusals_write_nothing(self):
        def sheets_there(case):
            layer,root=case.drafted('st');(layer/'Sheets').mkdir();return layer
        def stray_register(case):
            layer,root=case.drafted('sr');(root/'registers/notes.md').write_text('hand note');return layer
        def intent_layout(case):
            layer,root=case.drafted('il');d=package.load(layer/'intent.yaml');d['aipm']['layout']=package.BOX_ROOT_LAYOUT;write_yaml(layer/'intent.yaml',d);return layer
        def bound_checkpoint(case):
            layer,root=case.drafted('bc');v=package.load(root/'validation_record.yaml');v['note']='Documents/aipm_project/x';write_yaml(root/'validation_record.yaml',v);return layer
        for build,pattern in ((sheets_there,'already exists'),(stray_register,'unexpected file'),(intent_layout,'intent aipm.layout'),(bound_checkpoint,'bound as it is')):
            with self.subTest(case=build.__name__):
                layer=build(self);before=tr.state(layer)
                for apply in (False,True):
                    with self.assertRaisesRegex(ValueError,pattern):package.migrate_sheets(layer,apply=apply,approval_ref='synthetic')
                self.assertEqual(tr.state(layer),before)

    def test_nested_v1_goes_to_its_own_route(self):
        layer=self.base/'nest';ti.fixture(layer)   # nested_v1 (legacy course, archived): the nested_v1 route plans it (tests in test_migrate_sheets_nested)
        d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d);before=tr.state(layer)
        r=package.migrate_sheets(layer);self.assertEqual((r['from_layout'],r['applied'],r['archived']),('nested_v1',False,True))
        self.assertEqual(tr.state(layer),before)

    def test_a_failure_puts_everything_back(self):
        for n in (1,3,6):   # the folder rename, a registers move, the last registers move
            with self.subTest(fail_at=n):
                layer,root=self.drafted('pf'+str(n));before=tr.state(layer)
                real=os.rename;calls=[]
                def failing(a,b):
                    calls.append(1)
                    if len(calls)==n:raise OSError('synthetic failure')
                    return real(a,b)
                with mock.patch.object(package.os,'rename',failing),self.assertRaises((OSError,ValueError)):package.migrate_sheets(layer,apply=True,approval_ref='synthetic')
                self.assertEqual(tr.state(layer),before);self.assertFalse((layer/'Sheets').exists())
                self.assertTrue(package.migrate_sheets(layer,apply=True,approval_ref='synthetic')['applied'])   # and it can run again

    def test_a_box_that_read_its_registers_as_sources_is_refused_before_writing(self):
        layer,root=ti.CourseIntegration.registers_as_sources(self,'src');self.draft(layer);no_intent_layout(layer)
        self.assertEqual(root,layer/'Documents/aipm_project');before=tr.state(layer)
        for apply in (False,True):
            with self.assertRaisesRegex(ValueError,'source read lives inside the package'):package.migrate_sheets(layer,apply=apply,approval_ref='synthetic')
        self.assertEqual(tr.state(layer),before)

    def test_new_errors_after_the_writes_put_everything_back(self):
        layer,root=self.drafted('late');before=tr.state(layer);real=validate_package.validate;calls=[]
        def worse(*a,**k):
            r=real(*a,**k);calls.append(1)
            if len(calls)==2:r=dict(r,errors=r['errors']+[{'code':'E_SYNTH','path':'x','message':'synthetic'}])   # the check after the move
            return r
        with mock.patch.object(validate_package,'validate',worse),self.assertRaisesRegex(ValueError,'new errors after the move'):package.migrate_sheets(layer,apply=True,approval_ref='synthetic')
        self.assertEqual(tr.state(layer),before);self.assertFalse((layer/'Sheets').exists())

    def test_an_interrupt_puts_everything_back(self):
        layer,root=self.drafted('int');before=tr.state(layer);real=os.rename;calls=[]
        def interrupted(a,b):
            calls.append(1)
            if len(calls)==4:real(a,b);raise KeyboardInterrupt   # stopped right after a registers move, before anything is recorded
            return real(a,b)
        with mock.patch.object(package.os,'rename',interrupted),self.assertRaises(KeyboardInterrupt):package.migrate_sheets(layer,apply=True,approval_ref='synthetic')
        self.assertEqual(tr.state(layer),before);self.assertFalse((layer/'Sheets').exists())

    def test_a_reference_to_the_registers_folder_points_to_sheets(self):
        layer,root=self.drafted('ref');w=package.load(root/'registers/wbs.yaml');w['wbs'][0]['evidence_refs']=['Documents/aipm_project/registers/'];write_yaml(root/'registers/wbs.yaml',w)
        package.migrate_sheets(layer,apply=True,approval_ref='synthetic')
        self.assertEqual(package.load(layer/'Sheets/wbs.yaml')['wbs'][0]['evidence_refs'],['Sheets/'])

    def test_cli_dry_run(self):
        layer,root=self.drafted('cli');before=tr.state(layer)
        code,out=tr.run_cli('migrate-sheets','--layer',str(layer));self.assertEqual(code,0,out);self.assertFalse(out['applied'])
        self.assertEqual(tr.state(layer),before)

if __name__=='__main__':unittest.main()
