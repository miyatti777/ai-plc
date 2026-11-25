"""validate (prearchive/final), receipt, reset-to-init and archive read and write both layouts.
The course and reset tests of test_integration / test_init_and_reset run again on box_root_v1 packages, in a synthetic
repository (Flow/ and Stock/programs/Sample/) so that archive copies to its Stock. Synthetic fixtures only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
from datetime import datetime, timezone
import shutil, tempfile, unittest
METHOD=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(METHOD));sys.path.insert(0,str(Path(__file__).resolve().parent))
import package, validate_package
import test_integration as ti, test_init_and_reset as tr   # module import: their TestCase classes are not collected again here
import registry_fixture as rf
write_yaml,sha=ti.write_yaml,ti.sha

def in_repository(case):
    """setUp: a temporary repository whose Layers sit under Flow/ and whose Stock has the program Sample."""
    case.temp=tempfile.TemporaryDirectory();case.repo=Path(case.temp.name)
    case.base=case.repo/'Flow/202610/2026-10-24';case.base.mkdir(parents=True);(case.repo/'Stock/programs/Sample').mkdir(parents=True)
    rf.auto_register(case,package)   # archive goes under the primary business project 合成業務

def box_root_prepare(self,name='new',course='document_based/single_persona',pending=False,reuse=False,**aipm):
    """CourseIntegration.prepare with aipm.layout box_root_v1 and program Sample (and the project_init roots of that layout)."""
    layer,_,packet=ti.CourseIntegration.prepare(self,name,course,pending,reuse)
    aipm.setdefault('program_id','Sample');aipm.setdefault('project_id','course_'+name)   # one Stock project per Layer (the same program/project would collide)
    d=package.load(layer/'intent.yaml');d['aipm'].update(layout=package.BOX_ROOT_LAYOUT,**aipm)
    if d['aipm']['program_id'] is None:d['aipm'].pop('program_id')
    write_yaml(layer/'intent.yaml',d)
    c=package.build_contract(layer);flow_base,stock_base=package.init_roots(c)
    b=c['bindings'];packet['drafts']['write_init_yaml'].update(program_id=b['program_id'],project_id=b['project_id'],flow_dir=b['flow_dir'],flow_base=flow_base,stock_base=stock_base)
    write_yaml(layer/'Context/course_input.yaml',packet);return layer,c,packet

class BoxRootCourse(ti.CourseIntegration):
    setUp=in_repository;prepare=box_root_prepare
    test_contract_provenance_and_unknown_branch_refused=None   # checks the nested_v1 version string; box_root adds +box_root.1

class BoxRootReset(tr.ResetToInit):
    setUp=in_repository;prepare=box_root_prepare;mode_init_layer=ti.CourseIntegration.mode_init_layer
    def test_box_root_refusals_without_archive(self):
        """test_refusals_write_nothing without its archived case (archive): every refusal leaves the Layer as it was."""
        def edited_init(layer,root):p=root/'project_init.yaml';p.write_text(p.read_text()+'# hand edit\n')
        def evidence_retired(layer,root):
            c=package.build_contract(layer);e=next(e for e in c['documents'] if not e.get('side'))
            w=package.load(root/'registers/wbs.yaml');w['wbs'][0]['evidence_refs']=['Documents/aipm_project/'+e['path']];write_yaml(root/'registers/wbs.yaml',w)
        def stray(layer,root):(root/'memo.md').write_text('hand note')
        def edited_readme(layer,root):p=root/'README.md';p.write_text(p.read_text()+'hand edit\n')
        def no_mode_init(layer,root):i=package.load(layer/'intent.yaml');i.pop('mode_init');write_yaml(layer/'intent.yaml',i)
        def pending(layer,root):i=package.load(layer/'intent.yaml');i['mode_init']['state']='pending';write_yaml(layer/'intent.yaml',i)
        def goal_changed(layer,root):i=package.load(layer/'intent.yaml');i['goal']['description']='changed after init';write_yaml(layer/'intent.yaml',i)
        def retire_exists(layer,root):(layer/'Documents/aipm_retired/t').mkdir(parents=True)
        cases=[(edited_init,None),(edited_readme,None),(no_mode_init,None),(pending,None),(goal_changed,None),(retire_exists,'Documents/aipm_retired/t'),(evidence_retired,None),(stray,None),
               (lambda l,r:None,'Documents/aipm_project/retired'),(lambda l,r:None,'Documents/aipm_project'),(lambda l,r:None,'../outside')]
        for n,(change,retire) in enumerate(cases):
            with self.subTest(case=getattr(change,'__name__','retire '+str(retire))):
                layer,root,out=self.drafted('x'+str(n));change(layer,root);before=tr.state(layer)
                with self.assertRaises(ValueError):package.reset_to_init(layer,apply=True,retire=retire or 'Documents/aipm_retired/t')
                self.assertEqual(tr.state(layer),before)
    def test_box_root_reset_moves_the_documents_and_draft_again_passes_prearchive(self):
        layer,root,out=self.drafted('rr');c=package.build_contract(layer)
        result=package.reset_to_init(layer,apply=True,retire='Documents/aipm_retired/t1');self.assertTrue(result['applied']);self.assertTrue(result['continuable'])
        moved={m['from'] for m in result['moves']}
        for e in c['documents']:
            if not e.get('side'):self.assertIn('Documents/aipm_project/'+e['path'],moved)
        self.assertFalse((root/'Flow').exists());self.assertTrue((root/'project_init.yaml').is_file())
        self.draft(layer);r=validate_package.validate(root,phase='prearchive',layer=layer);self.assertTrue(r['pass'],r['errors'])

class BoxRootValidate(unittest.TestCase):
    setUp=in_repository
    def tearDown(self):self.temp.cleanup()
    prepare=box_root_prepare;draft=ti.CourseIntegration.draft
    def archived_by_hand(self,name,program='Sample'):
        """The box_root_v1 archive as archive will write it, made by hand: Stock/programs/<program>/projects/<project>/documents/."""
        layer,c,packet=self.prepare(name,program_id=program);root=self.draft(layer)
        self.assertTrue(validate_package.validate(root,phase='prearchive',layer=layer)['pass'])
        m=package.load(root/'manifest.yaml')
        for r in m['records']:
            e=next(e for e in c['documents'] if e['step']==r['source_step'])
            if e.get('side'):continue
            dest=c['stock_target_rel']+'/documents/'+e['path'];q=self.repo/dest;q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/r['path'],q)
            r.update(status='archived_local_final',archive_path=dest,archive_sha256=sha(q))
        m['stages'].append({'name':'archive','started_at':datetime.now(timezone.utc).isoformat(),'finished_at':datetime.now(timezone.utc).isoformat(),'checkpoint_actor':'auto_decision','checkpoint_status':'accepted_local','evidence_refs':[r['id'] for r in m['source_reads']]})
        write_yaml(root/'manifest.yaml',m);return layer,root,c,m
    def codes(self,layer,root,phase='final',**kw):
        r=validate_package.validate(root,phase=phase,layer=layer,**kw);return r['pass'],{e['code'] for e in r['errors']},r
    def test_prearchive_and_final_pass_with_the_copy_in_the_real_stock(self):
        layer,root,c,m=self.archived_by_hand('ok')
        ok,codes,r=self.codes(layer,root);self.assertTrue(ok,r['errors']);self.assertEqual(r['checked_documents'],19)
        self.assertFalse((root/'Stock').exists());self.assertTrue((self.repo/c['stock_target_rel']/'documents').is_dir())
    def test_final_in_a_flow_worktree_needs_the_stock_root(self):
        """A Flow worktree (<somewhere>/<work>/202610/...) has no parent named Flow: final asks for --stock-root."""
        layer,root,c,m=self.archived_by_hand('wt');wt=self.repo.parent/(self.repo.name+'_wt')/'202610/2026-10-24';wt.mkdir(parents=True)
        moved=wt/'wt';shutil.copytree(layer,moved,copy_function=shutil.copy2)
        ok,codes,r=self.codes(moved,moved/'Documents/aipm_project');self.assertFalse(ok);self.assertTrue(any('stock_root' in e['message'] for e in r['errors']))
        ok,codes,r=self.codes(moved,moved/'Documents/aipm_project',stock_root=self.repo);self.assertTrue(ok,r['errors'])
        import subprocess
        out=subprocess.run([sys.executable,'-B',str(METHOD/'validate_package.py'),'--layer',str(moved),'--phase','final','--stock-root',str(self.repo)],capture_output=True,text=True)
        self.assertEqual(out.returncode,0,out.stdout[-500:])
    def test_final_with_an_explicit_stock_root(self):
        layer,root,c,m=self.archived_by_hand('sr');other=self.repo.parent/(self.repo.name+'_other')
        ok,codes,_=self.codes(layer,root,stock_root=other);self.assertFalse(ok);self.assertIn('E_ARCHIVE',codes)   # the copy is not under that root
        ok,codes,r=self.codes(layer,root,stock_root=self.repo);self.assertTrue(ok,r['errors'])
    def test_final_stops_on_changed_missing_or_misplaced_copies(self):
        layer,root,c,m=self.archived_by_hand('bad');r0=next(r for r in m['records'] if r['archive_path'])
        q=self.repo/r0['archive_path'];q.write_text(q.read_text()+'\nchanged\n')
        self.assertIn('E_ARCHIVE',self.codes(layer,root)[1])
        q.unlink();self.assertIn('E_ARCHIVE',self.codes(layer,root)[1])
        r0['archive_path']='Stock/programs/Other/projects/box/documents/x.md';write_yaml(root/'manifest.yaml',m)
        self.assertIn('E_ARCHIVE',self.codes(layer,root)[1])
    def test_final_without_a_program_stops(self):
        layer,c,packet=self.prepare('np',program_id=None);root=self.draft(layer)
        self.assertTrue(validate_package.validate(root,phase='prearchive',layer=layer)['pass'])
        self.assertIsNone(c['stock_target_rel'])
        m=package.load(root/'manifest.yaml');m['stages'].append({'name':'archive','started_at':datetime.now(timezone.utc).isoformat(),'finished_at':datetime.now(timezone.utc).isoformat(),'checkpoint_actor':'auto_decision','checkpoint_status':'accepted_local','evidence_refs':[]})
        for r in m['records']:
            if r['stage']!='init':r['status']='archived_local_final'
        write_yaml(root/'manifest.yaml',m)
        ok,codes,r=self.codes(layer,root);self.assertFalse(ok);self.assertTrue(any(e['code']=='E_ARCHIVE' and 'program' in e['message'] for e in r['errors']))
    def test_nested_contract_with_documents_at_the_package_root_stops(self):
        """The other direction: a nested_v1 package whose documents sit directly in the package (not under its Flow/)."""
        layer,_,packet=ti.CourseIntegration.prepare(self,'rev');root=self.draft(layer);c=package.build_contract(layer)
        for e in c['documents']:
            src=root/package.doc_rel(c,e);dst=root/e['path'];dst.parent.mkdir(parents=True,exist_ok=True);src.rename(dst)
        ok,codes,r=self.codes(layer,root,phase='prearchive');self.assertFalse(ok);self.assertIn('E_MISSING',codes)
    def test_package_of_one_layout_read_as_the_other_stops(self):
        layer,c,packet=self.prepare('mix');root=self.draft(layer)
        (root/'Flow').mkdir();self.assertIn('E_BOUNDARY',self.codes(layer,root,phase='prearchive')[1])   # an inner Flow/ in a box_root package
        (root/'Flow').rmdir()
        fc=package.load(root/'format_contract.yaml');fc.pop('layout');write_yaml(root/'format_contract.yaml',fc)   # relabelled as nested_v1
        with self.assertRaises(ValueError):validate_package.validate(root,phase='prearchive',layer=layer)   # intent says box_root_v1
        d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d)
        with self.assertRaises(ValueError):validate_package.validate(root,phase='prearchive',layer=layer)   # the relabelled contract is not the fixed nested_v1 one

class BoxRootArchive(unittest.TestCase):
    """archive_course on box_root_v1: copies to the real Stock/programs/<program>/projects/<business>/<project>/documents/ only."""
    setUp=in_repository
    def tearDown(self):self.temp.cleanup()
    prepare=box_root_prepare;draft=ti.CourseIntegration.draft
    def test_archive_copies_to_the_repository_stock_and_final_passes(self):
        layer,c,packet=self.prepare('a');root=self.draft(layer)
        result=package.archive_course(layer);self.assertTrue(result['pass'],result['errors'])
        m=package.load(root/'manifest.yaml');self.assertEqual(m['stages'][-1]['name'],'archive')
        target=self.repo/'Stock/programs/Sample/projects'/rf.BUSINESS/'course_a/documents'
        for r in m['records']:
            if r['stage']=='init':self.assertIsNone(r['archive_path']);continue
            self.assertTrue(r['archive_path'].startswith('Stock/programs/Sample/projects/'+rf.BUSINESS+'/course_a/documents/'))
            q=self.repo/r['archive_path'];self.assertEqual(q.read_bytes(),(root/r['path']).read_bytes());self.assertEqual(sha(q),r['archive_sha256'])
        self.assertEqual(sum(1 for q in target.rglob('*') if q.is_file()),17)
        self.assertFalse((root/'Stock').exists());self.assertFalse((root/'Flow').exists())
        before=tr.state(self.repo);again=package.archive_course(layer)   # already archived: prearchive no longer passes, nothing is copied
        self.assertFalse(again['pass']);self.assertEqual(tr.state(self.repo),before)
    def test_refusals_write_nothing(self):
        def no_program(case):return case.prepare('np',program_id=None)
        def missing_program(case):return case.prepare('mp',program_id='NoSuchProgram')
        def counterpart_exists(case):
            out=case.prepare('ce');q=case.repo/'Stock/programs/Sample/projects'/rf.BUSINESS/'course_ce/documents/02_課題定義/problem_map.yaml';q.parent.mkdir(parents=True);q.write_text('existing');return out
        def symlinked_program(case):
            out=case.prepare('sl',program_id='Linked');(case.repo/'elsewhere').mkdir();(case.repo/'Stock/programs/Linked').symlink_to(case.repo/'elsewhere');return out
        for build in (no_program,missing_program,counterpart_exists,symlinked_program):
            with self.subTest(case=build.__name__):
                layer,c,packet=build(self);root=self.draft(layer);before=tr.state(self.repo)
                with self.assertRaises(ValueError):package.archive_course(layer)
                self.assertEqual(tr.state(self.repo),before)
    def test_wrong_case_program_is_refused(self):
        layer,c,packet=self.prepare('wc',program_id='sample');root=self.draft(layer);before=tr.state(self.repo)
        with self.assertRaises(ValueError):package.archive_course(layer)
        self.assertEqual(tr.state(self.repo),before)
    def test_a_failure_while_copying_moves_the_partial_copies_out_of_the_stock(self):
        from unittest import mock
        layer,c,packet=self.prepare('pf');root=self.draft(layer);stock=self.repo/'Stock';before=tr.state(stock);manifest=sha(root/'manifest.yaml')
        real=shutil.copystat;calls=[]
        def failing(*a,**k):
            calls.append(1)
            if len(calls)==3:raise OSError('synthetic disk full')
            return real(*a,**k)
        with mock.patch.object(package.shutil,'copystat',failing),self.assertRaises(ValueError) as cm:package.archive_course(layer)
        self.assertIn('3 partial copies moved to Documents/aipm_retired/',str(cm.exception))
        self.assertEqual(tr.state(stock),before);self.assertEqual(sha(root/'manifest.yaml'),manifest)   # Stock and records as before
        moved=[q for q in (layer/'Documents/aipm_retired').rglob('*') if q.is_file()];self.assertEqual(len(moved),3)
        result=package.archive_course(layer);self.assertTrue(result['pass'],result['errors'])   # and archive can run again
    def test_new_layer_without_layout_goes_init_draft_validate_archive(self):
        layer,c,packet=self.prepare('nl');d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d)
        c=package.build_contract(layer);self.assertEqual(c['layout'],package.SHEETS_LAYOUT)   # the default
        flow_base,stock_base=package.init_roots(c);packet['drafts']['write_init_yaml'].update(flow_base=flow_base,stock_base=stock_base);write_yaml(layer/'Context/course_input.yaml',packet)   # the project_init roots of the default layout
        out=package.init(layer);root=Path(out['package']);self.assertEqual(root,layer/'Sheets');self.assertFalse((root/'Flow').exists())
        d=package.load(layer/'intent.yaml');d['mode_init']={'state':'done','done_at':datetime.now(timezone.utc).isoformat(),'outputs':out['outputs']};write_yaml(layer/'intent.yaml',d)
        self.draft(layer);self.assertTrue(validate_package.validate(root,phase='prearchive',layer=layer)['pass'])
        result=package.archive_course(layer);self.assertTrue(result['pass'],result['errors'])
        self.assertFalse((root/'Stock').exists());self.assertTrue((self.repo/'Stock/programs/Sample/projects'/rf.BUSINESS/'course_nl/documents').is_dir())
    def test_archive_from_a_flow_worktree_finds_the_superproject_stock(self):
        """A Bot worktree: <wt>/.git is a file pointing into <repository>/.git/modules/Flow/worktrees/<name>."""
        wt=self.repo.parent/(self.repo.name+'_wt');(wt/'202610/2026-10-24').mkdir(parents=True)
        (self.repo/'.git/modules/Flow/worktrees/x').mkdir(parents=True);(wt/'.git').write_text('gitdir: '+str(self.repo/'.git/modules/Flow/worktrees/x')+'\n')
        self.assertEqual(package.stock_root_of(wt/'202610/2026-10-24/l').resolve(),self.repo.resolve())
        self.base=wt/'202610/2026-10-24';layer,c,packet=self.prepare('w');root=self.draft(layer)
        result=package.archive_course(layer);self.assertTrue(result['pass'],result['errors'])
        self.assertTrue((self.repo/'Stock/programs/Sample/projects'/rf.BUSINESS/'course_w/documents').is_dir())
        self.assertTrue(validate_package.validate(root,phase='final',layer=layer)['pass'])
    def test_archive_cli_with_stock_root(self):
        other=self.repo.parent/(self.repo.name+'_cli');(other/'202610').mkdir(parents=True);self.base=other/'202610'   # no Flow parent, no .git
        layer,c,packet=self.prepare('cli');root=self.draft(layer)
        # no Stock found and no .ai-plc/config.yaml: aipm_archive.where auto means the Layer
        self.assertEqual(package.archive_settings(layer),{'where':'layer','business':'registry'})
        rf.register(self.registry,package.load(layer/'intent.yaml')['scope_id'])   # the CLI runs in another process (no patched archive)
        code,out=tr.run_cli('archive','--layer',str(layer),'--stock-root',str(self.repo),'--registry-db',str(rf.db_path(self.registry)));self.assertEqual(code,0,out);self.assertTrue(out['pass'])
        self.assertTrue((self.repo/'Stock/programs/Sample/projects'/rf.BUSINESS/'course_cli/documents').is_dir())

class BoxRootReceipt(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    prepare=box_root_prepare;draft=ti.CourseIntegration.draft
    def test_receipt_binds_persona_and_validation_on_box_root(self):
        layer,c,packet=self.prepare('rc',pending=True)
        packet['decisions']['validation']={'state':'pending','reason':'Choosing validation hypotheses is the user call','scope':'reversible_draft_only','source_ids':['M1','M2'],'question':'Use H1 for validation?'}
        for key in ('persona','validation'):packet['gaps'].append({'kind':'unknown','reason':'needs the user','requires_user':True,'decision_key':key,'question':'?'})
        write_yaml(layer/'Context/course_input.yaml',packet);root=self.draft(layer)
        def ask(name,**over):
            d={'stage':'persona','question':'Which actual persona should be used?','answer':'Synthetic reply only','question_id':'SYN-'+name,'source_thread_id':'SYNTHETIC-THREAD','answered_at':ti.now()};d.update(over)
            write_yaml(layer/'Context'/(name+'.yaml'),d);return 'Context/'+name+'.yaml'
        r=package.receipt(layer,ask('p'));self.assertTrue(r['bound'])
        m=package.load(root/'manifest.yaml');persona=next(x for x in m['records'] if x['source_step']=='generate_persona_md')
        self.assertEqual(package.load(layer/r['receipt'])['target_path'],'Documents/aipm_project/'+persona['path'])
        self.assertFalse(persona['path'].startswith('Flow/'))
        v=package.load(root/'validation_record.yaml');write_yaml(root/'validation_checkpoint.yaml',{k:x for k,x in v.items() if k!='actual_new_user_response'})
        r=package.receipt(layer,ask('v',stage='validation',question='Use H1 for validation?',answered_at=ti.now()));self.assertTrue(r['pass'],r)
        self.assertTrue(validate_package.validate(root,phase='prearchive',layer=layer)['pass'])

class LegacyAllowedBothLayouts(unittest.TestCase):
    """receipt of a legacy (question-based) stage tolerates the later stages' missing documents in both layouts."""
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_later_stage_missing_documents_are_allowed_and_own_are_not(self):
        for layout in (package.NESTED_LAYOUT,package.BOX_ROOT_LAYOUT):
            with self.subTest(layout=layout):
                layer=self.base/layout;layer.mkdir()
                write_yaml(layer/'intent.yaml',{'scope_id':'L-LEG','scope_name':'leg','work_style':'aipm','aipm':{'layout':layout,'date':'2026-10-24'}})
                c=package.build_contract(layer);root=layer/'Documents/aipm_project'
                def doc(prefix):return next(d for d in c['documents'] if not d.get('side') and d['path'].startswith(prefix))
                def allowed(d):return package.legacy_allowed({'code':'E_MISSING','path':package.pkg_rel(c['flow_rel'],d['path']),'message':'required document missing'},c,{'records':[]},'persona',root)
                self.assertTrue(allowed(doc('02')));self.assertTrue(allowed(doc('04')))   # later stages
                self.assertFalse(allowed(doc('01')))                                       # the stage being answered
                self.assertFalse(package.legacy_allowed({'code':'E_MISSING','path':'x/'+doc('02')['path'],'message':'required document missing'},c,{'records':[]},'persona',root))

if __name__=='__main__':unittest.main()
