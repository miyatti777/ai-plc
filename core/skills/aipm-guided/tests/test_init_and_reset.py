"""init --drafts, --brief and the Init note, reset-to-init. Synthetic fixtures only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import contextlib, io, json, tempfile, unittest, yaml
from datetime import datetime, timezone
METHOD=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(METHOD));sys.path.insert(0,str(Path(__file__).resolve().parent))
import package, validate_package
import test_integration as ti   # module import: its TestCase classes are not collected again here
fixture,write_yaml,sha=ti.fixture,ti.write_yaml,ti.sha

CONTRACTS=[METHOD/'registers_contract.yaml',METHOD/'registers_contract.v1.yaml']
def contract_hashes():return {str(q):sha(q) for q in CONTRACTS}
def state(top):
    """hash and mtime of every file plus the folder list (dry-run and refusals must leave all of it as it was)."""
    return {q.relative_to(top).as_posix():((sha(q),q.stat().st_mtime_ns) if q.is_file() else 'dir') for q in sorted(top.rglob('*'))}
def run_cli(*args):
    out=io.StringIO();argv=sys.argv
    try:
        sys.argv=['package.py',*args]
        with contextlib.redirect_stdout(out):code=package.main()
    finally:sys.argv=argv
    return code,json.loads(out.getvalue())
def old_generic_registers(c):
    """The registers drafts exactly as init wrote them before --drafts existed (no --drafts)."""
    rc=package.registers_contract(c);unk='[unknown]'
    wbs=[{'id':'W'+str(n),'deliverable':x['deliverable'],'exit_criteria':x['exit_criteria'],'owner':unk,'status':'draft','schedule':{'baseline':None,'forecast':None,'actual':None,'history':[]},'source_of_truth':'local'} for n,x in enumerate(rc['init_drafts']['wbs_initial_deliverables'],1)]
    drafts={'issues':{'charter':{'change_conditions':[unk],'exit_conditions':[unk]},'issues':[{'id':'I1','question':unk+' 決めるべき問い（Goal と Context から下書きする）','status':'open','priority':unk,'owner':unk,'due':'undecided'}]},
            'hypotheses':{'hypotheses':[{'id':'H1','kind':'opportunity','claim':'[hypothesis] '+unk+' 調査前の Opportunity 仮説（Goal と Context から下書きする）','status':'unknown'}]},
            'todo':{'todo':[]},'wbs':{'wbs':wbs},
            'roadmap':{'roadmap':[{'id':'MS1','milestone':unk+' 最初の関係者提示','period':'undecided','status':'draft'}]}}
    return {rc['files'][k]['path']:yaml.safe_dump(v,allow_unicode=True,sort_keys=False) for k,v in drafts.items()}

def new_layer(base,name,registers=True,course='document_based/single_persona'):
    layer=base/name;layer.mkdir();(layer/'Context').mkdir()
    write_yaml(layer/'intent.yaml',{'scope_id':'L-SYN-INIT','scope_name':'synthetic_init','owner':'Synthetic fixture','work_style':'aipm','goal':{'description':'架空の Goal（試験用）'},'aipm':{'project_id':'synthetic_t006','date':'2026-10-22','course':course,'registers':registers}})
    (layer/'Context/goal_notes.md').write_text('# 架空の Context\n\n試験用の資料。\n')
    return layer
DRAFTS={'wbs':[{'deliverable':'架空の調査報告','exit_criteria':'問いごとに証拠と不足が書かれている','source_refs':['Context/goal_notes.md']},
               {'deliverable':'架空の試作','exit_criteria':'試作を1回動かした記録がある','source_refs':['Context/goal_notes.md','Flow@abcdef1:202610/x.md']}],
        'issues':[{'question':'架空の対象者を誰にするか？','source_refs':['Context/goal_notes.md']}],
        'hypotheses':[{'claim':'[hypothesis] 架空の機会がある'}]}

class InitDrafts(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.contracts=contract_hashes()
    def tearDown(self):
        self.assertEqual(contract_hashes(),self.contracts);self.temp.cleanup()
    def with_drafts(self,name,drafts=DRAFTS,**kw):
        layer=new_layer(self.base,name,**kw);write_yaml(layer/'Context/wbs_drafts.yaml',drafts);return layer
    def test_drafts_fill_wbs_and_keep_human_fields_unknown(self):
        layer=self.with_drafts('a');out=package.init(layer,drafts='Context/wbs_drafts.yaml');root=Path(out['package'])
        wbs=package.load(root/'registers/wbs.yaml')['wbs']
        self.assertEqual([(r['id'],r['deliverable'],r['exit_criteria']) for r in wbs],[('W'+str(n),d['deliverable'],d['exit_criteria']) for n,d in enumerate(DRAFTS['wbs'],1)])
        for r in wbs:
            self.assertEqual((r['owner'],r['status'],r['schedule']['baseline'],r['schedule']['forecast']),('[unknown]','draft',None,None))
            self.assertNotIn('evidence_refs',r)
        issues=package.load(root/'registers/issues.yaml')['issues']
        self.assertEqual(issues,[{'id':'I1','question':'架空の対象者を誰にするか？','status':'open','priority':'[unknown]','owner':'[unknown]','due':'undecided','sources':['Context/goal_notes.md']}])
        self.assertEqual(package.load(root/'registers/hypotheses.yaml')['hypotheses'],[{'id':'H1','kind':'opportunity','claim':'[hypothesis] 架空の機会がある','status':'unknown'}])
        self.assertEqual(out['wbs_source_refs'],{'W1':['Context/goal_notes.md'],'W2':['Context/goal_notes.md','Flow@abcdef1:202610/x.md']})
        self.assertEqual({o['path'] for o in out['outputs']},{o['path'] for o in package.existing_outputs(root,out['contract'])})
        result=validate_package.validate(root,phase='prearchive',layer=layer)
        self.assertEqual([e for e in result['errors'] if e['code']=='E_REGISTERS'],[])
    def test_wbs_only_keeps_generic_issue_and_hypothesis(self):
        layer=self.with_drafts('w',{'wbs':DRAFTS['wbs'][:1]});root=Path(package.init(layer,drafts='Context/wbs_drafts.yaml')['package'])
        generic=old_generic_registers(package.build_contract(layer))
        for rel in ('registers/issues.yaml','registers/hypotheses.yaml','registers/todo.yaml','registers/roadmap.yaml'):self.assertEqual((root/rel).read_text(),generic[rel],rel)
        self.assertEqual(len(package.load(root/'registers/wbs.yaml')['wbs']),1)
    def test_without_drafts_bytes_are_the_generic_ones(self):
        for n,(registers,course) in enumerate([(True,'document_based/single_persona'),(True,'question_based/single_persona'),(False,'document_based/single_persona')]):
            with self.subTest(registers=registers,course=course):
                layer=new_layer(self.base,'g'+str(n),registers,course);out=package.init(layer);root=Path(out['package']);c=out['contract']
                if registers:
                    for rel,text in old_generic_registers(c).items():self.assertEqual((root/rel).read_bytes(),text.encode('utf-8'),rel)
                self.assertEqual(out['registers'],list(old_generic_registers(c)) if registers else [])
                for rel,text in package.init_documents(layer,c).items():self.assertEqual((root/rel).read_bytes(),text.encode('utf-8'))
                self.assertNotIn('wbs_source_refs',out)
    def test_human_fields_and_invalid_inputs_write_nothing(self):
        def item(**kw):return {'wbs':[{**DRAFTS['wbs'][0],**kw}]}
        cases={'owner':item(owner='someone'),'priority':item(priority='high'),'schedule':item(schedule={'baseline':{'start':'2026-11-01'}}),'baseline':item(baseline='2026-11-01'),
               'issue_due':{'wbs':DRAFTS['wbs'],'issues':[{'question':'q?','due':'2026-11-01'}]},'issue_owner':{'wbs':DRAFTS['wbs'],'issues':[{'question':'q?','owner':'x'}]},
               'empty_wbs':{'wbs':[]},'no_wbs':{'issues':DRAFTS['issues']},'missing_exit':{'wbs':[{'deliverable':'x','source_refs':['Context/goal_notes.md']}]},
               'blank_deliverable':item(deliverable='  '),'missing_source_refs':{'wbs':[{'deliverable':'x','exit_criteria':'y'}]},'empty_source_refs':item(source_refs=[]),
               'source_outside':item(source_refs=['../outside.md']),'source_absolute':item(source_refs=['/etc/hosts']),'source_missing':item(source_refs=['Context/nothing.md']),
               'unknown_top':{'wbs':DRAFTS['wbs'],'roadmap':[{'milestone':'x'}]},'not_map':['x']}
        for name,d in cases.items():
            with self.subTest(case=name):
                layer=self.with_drafts(name,d);before=state(layer)
                with self.assertRaises(ValueError):package.init(layer,drafts='Context/wbs_drafts.yaml')
                self.assertEqual(state(layer),before);self.assertFalse((layer/'Documents').exists())
        for name,path in {'outside_layer':'../wbs_drafts.yaml','absolute':str(self.base/'x.yaml'),'missing':'Context/none.yaml'}.items():
            with self.subTest(path=name):
                layer=self.with_drafts('p_'+name);(self.base/'wbs_drafts.yaml').write_text(yaml.safe_dump(DRAFTS,allow_unicode=True));before=state(layer)
                with self.assertRaises(ValueError):package.init(layer,drafts=path)
                self.assertEqual(state(layer),before)
    def test_drafts_need_registers_and_a_new_package(self):
        layer=self.with_drafts('nr',registers=False);before=state(layer)
        with self.assertRaises(ValueError):package.init(layer,drafts='Context/wbs_drafts.yaml')
        self.assertEqual(state(layer),before)
        layer=self.with_drafts('ex');package.init(layer);before=state(layer)
        with self.assertRaises(ValueError):package.init(layer,drafts='Context/wbs_drafts.yaml')
        self.assertEqual(state(layer),before)

class BriefAndNote(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_brief_drops_contract_and_keeps_outputs(self):
        full_layer=new_layer(self.base,'full');brief_layer=new_layer(self.base,'brief')
        code,full=run_cli('init','--layer',str(full_layer));self.assertEqual(code,0)
        code,brief=run_cli('init','--layer',str(brief_layer),'--brief');self.assertEqual(code,0)
        self.assertIn('contract',full);self.assertNotIn('contract',brief)
        self.assertEqual(brief['outputs'],full['outputs']);self.assertEqual(brief['registers'],full['registers'])
        self.assertEqual(brief['contract_version'],full['contract']['version']);self.assertEqual(brief['registers_contract_version'],2)
        self.assertEqual(set(brief),{'route','created','package','state','required_documents','registers','outputs','note','contract_version','registers_contract_version'})
        same=new_layer(self.base,'same');self.assertEqual(json.loads(json.dumps(package.init(same),ensure_ascii=False)),{**full,'package':str(same/'Documents/aipm_project')})
        code,again=run_cli('init','--layer',str(brief_layer),'--brief');self.assertEqual((again['created'],sorted(again['outputs'],key=str)),(False,sorted(brief['outputs'],key=str)));self.assertNotIn('contract',again)
    def test_note_says_init_e_missing_is_normal_and_validate_is_unchanged(self):
        layer=new_layer(self.base,'n');out=package.init(layer);self.assertEqual(out['note'],package.INIT_NOTE);self.assertIn('E_MISSING',out['note']);self.assertIn('E_REGISTERS',out['note'])
        self.assertEqual(package.init(layer)['note'],package.INIT_NOTE)
        root=Path(out['package']);first=validate_package.validate(root,phase='prearchive',layer=layer)
        self.assertFalse(first['pass']);self.assertTrue(any(e['code']=='E_MISSING' for e in first['errors']));self.assertFalse(any(e['code']=='E_REGISTERS' for e in first['errors']))
        package.init(layer);self.assertEqual(validate_package.validate(root,phase='prearchive',layer=layer),first)

class ResetToInit(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    prepare=ti.CourseIntegration.prepare;mode_init_layer=ti.CourseIntegration.mode_init_layer;draft=ti.CourseIntegration.draft
    def drafted(self,name,course='document_based/single_persona'):
        layer,root,out=self.mode_init_layer(name,True,course);self.draft(layer);return layer,root,out
    def kept_hashes(self,layer,root):
        return {q:sha(q) for q in [root/'format_contract.yaml',layer/'intent.yaml',layer/'Context/course_input.yaml',*sorted((root/'registers').glob('*.yaml'))]}
    def test_draft_reset_draft_rebuilds_19_and_passes(self):
        def snapshots(name):   # course input reads the registers, so draft writes source_snapshots/
            layer,root=ti.CourseIntegration.registers_as_sources(self,name);self.draft(layer);return layer,root,None
        cases=[('document_based/single_persona',None),('solution_based/single_persona',None),('document_based/single_persona',snapshots)]
        for n,(course,build) in enumerate(cases):
            with self.subTest(course=course,snapshots=bool(build)):
                layer,root,out=build('r'+str(n)) if build else self.drafted('r'+str(n),course)
                (layer/'Context/receipt_old_q.yaml').write_text('kind: user_reported\n')   # an earlier receipt stays as it was
                kept=self.kept_hashes(layer,root);receipt=sha(layer/'Context/receipt_old_q.yaml')
                originals={q.relative_to(root).as_posix():q.read_bytes() for q in root.rglob('*') if q.is_file()}
                result=package.reset_to_init(layer,apply=True,retire='Documents/aipm_retired/t1')
                self.assertTrue(result['applied']);self.assertTrue(result['continuable']);self.assertEqual(result['note'],package.RESET_NOTE);self.assertEqual(result['receipts'],['Context/receipt_old_q.yaml'])
                retired=layer/'Documents/aipm_retired/t1'
                for mv in result['moves']:
                    src=mv['from'][len('Documents/aipm_project/'):]
                    t=layer/mv['to']
                    files={src:t} if t.is_file() else {src+'/'+f.relative_to(t).as_posix():f for f in t.rglob('*') if f.is_file()}
                    for rel,f in files.items():self.assertEqual(f.read_bytes(),originals[rel],rel)
                self.assertTrue((retired/'manifest.yaml').is_file());self.assertTrue((retired/'validation_record.yaml').is_file())
                self.assertEqual((retired/'source_snapshots').is_dir(),bool(build));self.assertFalse((root/'source_snapshots').exists())
                self.assertEqual(sum(1 for m in result['moves'] if m['from'].endswith(('.yaml','.md'))),21)   # 17 documents + project_init/README batch versions + manifest + validation_record
                for q,h in kept.items():self.assertEqual(sha(q),h,q)
                self.assertEqual(sha(layer/'Context/receipt_old_q.yaml'),receipt)
                mi={o['path']:o['sha256'] for o in package.load(layer/'intent.yaml')['mode_init']['outputs']}
                for rel in package.init_documents(layer,package.build_contract(layer)):self.assertEqual(sha(root/rel),mi['Documents/aipm_project/'+rel])
                self.assertIsNotNone(package.mode_init_package(layer,root,package.build_contract(layer)))
                self.draft(layer)
                v=validate_package.validate(root,phase='prearchive',layer=layer);self.assertTrue(v['pass'],v['errors']);self.assertEqual(v['checked_documents'],19)
                final=package.archive_course(layer);self.assertTrue(final['pass'],final['errors'])
    def test_reset_right_after_init_and_default_retire(self):
        layer,root,out=self.mode_init_layer('fresh');result=package.reset_to_init(layer)
        self.assertFalse(result['applied']);self.assertEqual(result['moves'],[]);self.assertTrue(result['retire'].startswith('Documents/aipm_retired/'))
        self.assertTrue(package.reset_to_init(layer,apply=True)['continuable'])
    def test_dry_run_writes_nothing(self):
        layer,root,out=self.drafted('dry');before=state(layer)
        result=package.reset_to_init(layer);self.assertFalse(result['applied']);self.assertIn('dry_run',result);self.assertTrue(result['moves'])
        code,cli=run_cli('reset-to-init','--layer',str(layer),'--retire','Documents/aipm_retired/x');self.assertEqual(code,0);self.assertFalse(cli['applied'])
        self.assertEqual(state(layer),before);self.assertFalse((layer/'Documents/aipm_retired').exists())
    def test_case_variant_retire_inside_package_is_refused(self):   # case-insensitive file systems
        layer,root,out=self.drafted('case');before=state(layer)
        probe=layer/'DOCUMENTS'
        if not probe.exists():self.skipTest('case-sensitive file system')
        with self.assertRaises(ValueError):package.reset_to_init(layer,apply=True,retire='documents/AIPM_PROJECT/retired')
        self.assertEqual(state(layer),before)
    def test_failed_apply_leaves_no_new_folders(self):
        layer,root,out=self.drafted('fail');before=state(layer)
        real=package.sha;calls=[0]
        def broken(q):
            calls[0]+=1
            if calls[0]>3 and 'aipm_retired' in str(q):raise OSError('synthetic failure while checking moved files')
            return real(q)
        package.sha=broken
        try:
            with self.assertRaises(OSError):package.reset_to_init(layer,apply=True,retire='Documents/aipm_retired/try')
        finally:package.sha=real
        self.assertEqual(state(layer),before);self.assertFalse((layer/'Documents/aipm_retired').exists())
    def test_refusals_write_nothing(self):
        def archived(layer,root):self.assertTrue(package.archive_course(layer)['pass'])
        def edited_init(layer,root):p=root/package.build_contract(layer)['flow_rel']/'project_init.yaml';p.write_text(p.read_text()+'# hand edit\n')
        def edited_readme(layer,root):p=root/package.build_contract(layer)['stock_project_rel']/'README.md';p.write_text(p.read_text()+'hand edit\n')
        def no_mode_init(layer,root):i=package.load(layer/'intent.yaml');i.pop('mode_init');write_yaml(layer/'intent.yaml',i)
        def pending(layer,root):i=package.load(layer/'intent.yaml');i['mode_init']={'state':'pending'};write_yaml(layer/'intent.yaml',i)
        def goal_changed(layer,root):i=package.load(layer/'intent.yaml');i['goal']['description']='changed after init';write_yaml(layer/'intent.yaml',i)
        def retire_exists(layer,root):(layer/'Documents/aipm_retired/t').mkdir(parents=True)
        def evidence_retired(layer,root):
            c=package.build_contract(layer);e=next(e for e in c['documents'] if not e.get('side'))
            w=package.load(root/'registers/wbs.yaml');w['wbs'][0]['evidence_refs']=['Documents/aipm_project/'+c['flow_rel']+'/'+e['path']];write_yaml(root/'registers/wbs.yaml',w)
        def stray(layer,root):(root/package.build_contract(layer)['flow_rel']/'memo.md').write_text('hand note')
        cases=[(archived,None),(edited_init,None),(edited_readme,None),(no_mode_init,None),(pending,None),(goal_changed,None),(retire_exists,'Documents/aipm_retired/t'),
               (lambda l,r:None,'Documents/aipm_project/retired'),(lambda l,r:None,'Documents/aipm_project'),(lambda l,r:None,'../outside'),(evidence_retired,None),(stray,None)]
        for n,(change,retire) in enumerate(cases):
            with self.subTest(case=getattr(change,'__name__','retire '+str(retire))):
                layer,root,out=self.drafted('x'+str(n));change(layer,root);before=state(layer)
                with self.assertRaises(ValueError):package.reset_to_init(layer,apply=True,retire=retire or 'Documents/aipm_retired/t')
                self.assertEqual(state(layer),before)
    def test_legacy_course_is_refused(self):
        layer=self.base/'legacy';fixture(layer)
        i=package.load(layer/'intent.yaml');c=package.build_contract(layer);root=layer/'Documents/aipm_project'
        i['mode_init']={'state':'done','done_at':datetime.now(timezone.utc).isoformat(),'outputs':package.existing_outputs(root,c)};write_yaml(layer/'intent.yaml',i)
        before=state(layer)
        with self.assertRaises(ValueError):package.reset_to_init(layer,apply=True,retire='Documents/aipm_retired/t')
        self.assertEqual(state(layer),before)

# A Layer that selects the PM only as the bundled entry in intent.addons (no work_style). Synthetic only.
from unittest import mock
CATALOG_VERSION=next(x['addon_version'] for x in package.load(METHOD.parent/'ai-plc/references/addon-catalog.yaml')['addons'] if x['addon_id']=='aipm')
RECEIPT='Context/aipm_recommendation/receipts/synthetic.json'
def to_bundled(layer):
    """Replace work_style: aipm with the bundled entry that recommendation.py writes (selection_ref = the receipt)."""
    d=package.load(layer/'intent.yaml');d.pop('work_style',None)
    d['addons']=[{'addon_id':'aipm','source':'bundled','addon_version':CATALOG_VERSION,'selection_ref':RECEIPT}]
    write_yaml(layer/'intent.yaml',d)
    r=layer/RECEIPT;r.parent.mkdir(parents=True,exist_ok=True);r.write_text(json.dumps({'kind':'user_reported','choice':'aipm'}))
    return layer

class BundledOnly(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def prepare(self,*a,**kw):
        layer,c,packet=ti.CourseIntegration.prepare(self,*a,**kw);to_bundled(layer);return layer,c,packet
    mode_init_layer=ti.CourseIntegration.mode_init_layer;draft=ti.CourseIntegration.draft
    def test_init_brief_and_validate_match_the_legacy_field(self):
        legacy=new_layer(self.base,'legacy');bundled=to_bundled(new_layer(self.base,'bundled'))
        self.assertTrue(package.select(bundled));self.assertEqual(run_cli('route','--layer',str(bundled)),(0,{'route':'aipm'}))
        self.assertNotIn('work_style',package.load(bundled/'intent.yaml'))
        a,b=package.init(legacy),package.init(bundled)
        self.assertEqual({**b,'package':None},{**a,'package':None})
        va=validate_package.validate(Path(a['package']),phase='prearchive',layer=legacy);vb=validate_package.validate(Path(b['package']),phase='prearchive',layer=bundled)
        self.assertEqual(vb,va)
        code,brief=run_cli('init','--layer',str(bundled),'--brief');self.assertEqual((code,brief['created']),(0,False))
    def test_mode_init_draft_reset_draft_archive(self):
        layer,root,out=self.mode_init_layer('pipe');self.draft(layer)
        self.assertNotIn('work_style',package.load(layer/'intent.yaml'))
        v=validate_package.validate(root,phase='prearchive',layer=layer);self.assertTrue(v['pass'],v['errors']);self.assertEqual(v['checked_documents'],19)
        dry=package.reset_to_init(layer);self.assertFalse(dry['applied']);self.assertTrue(dry['moves'])
        self.assertTrue(package.reset_to_init(layer,apply=True,retire='Documents/aipm_retired/t1')['continuable'])
        self.draft(layer)
        v=validate_package.validate(root,phase='prearchive',layer=layer);self.assertTrue(v['pass'],v['errors'])
        final=package.archive_course(layer);self.assertTrue(final['pass'],final['errors'])
    def test_neither_field_does_not_load_the_selector(self):
        layer=self.base/'plain';layer.mkdir();write_yaml(layer/'intent.yaml',{'scope_id':'L-P','scope_name':'p','work_style':None,'addons':[]})
        with mock.patch.object(package,'addon_selector',side_effect=AssertionError('selector read')):
            self.assertFalse(package.select(layer));self.assertEqual(package.init(layer),{'route':'legacy','created':False})
        self.assertEqual(sorted(q.name for q in layer.iterdir()),['intent.yaml'])
    def test_case_addons_without_pm_are_legacy(self):
        layer=self.base/'case';layer.mkdir();write_yaml(layer/'intent.yaml',{'scope_id':'L-C','scope_name':'c','addons':[{'addon_id':'synthetic-case'}]})
        fake=mock.Mock();fake.selected_addons.return_value={'route':'selected','selected':[],'case_addons':[{'addon_id':'synthetic-case'}],'hold_reasons':[]}
        with mock.patch.object(package,'addon_selector',return_value=fake):
            self.assertFalse(package.select(layer));self.assertEqual(package.init(layer),{'route':'legacy','created':False})
        fake.selected_addons.assert_called_with(layer.absolute(),read_roots=[str(layer.absolute())])
    def test_valid_case_addon_through_the_real_selector_is_legacy(self):
        # one correct synthetic case binding (built by scripts/plc_addon_binding.py), no PM -> not held, False
        import importlib.util
        saved=list(sys.path)
        try:
            spec=importlib.util.spec_from_file_location('_t002_binding_builder',METHOD.parent/'ai-plc/scripts/plc_addon_binding.py')
            builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        finally:sys.path[:]=saved
        layer=self.base/'realcase';(layer/'Context').mkdir(parents=True);base=layer/'Documents/synthetic-addon';(base/'forms').mkdir(parents=True)
        (base/'guide.md').write_text('# 合成の案内\n');(base/'common.md').write_text('# 合成の共通の約束\n');(base/'forms/weekly.md').write_text('週次の型（合成）\n')
        write_yaml(base/'manifest.yaml',{'addon_id':'synthetic-addon','addon_version':'0.1','guide':{'path':'guide.md','version':'0.1'},'common':{'path':'common.md','version':'0.1'},
                   'forms':[{'form_id':'weekly','path':'forms/weekly.md','version':'0.1'}],'read_limits':{'max_guide_items':1,'max_form_items':1}})
        (layer/'Context/synthetic-addon-selection.md').write_text('addon_id `synthetic-addon`、addon_version `0.1`\n')
        write_yaml(layer/'intent.yaml',{'scope_id':'L-RC','scope_name':'rc'})
        built=builder.build(layer,addon_dir='Documents/synthetic-addon',selection_ref='Context/synthetic-addon-selection.md');self.assertEqual(built['route'],'binding',built)
        write_yaml(layer/'intent.yaml',{'scope_id':'L-RC','scope_name':'rc','addons':[built['addon_entry']]})
        sel=package.addon_selector().selected_addons(layer.absolute(),read_roots=[str(layer.absolute())])
        self.assertEqual((sel['route'],sel['selected'],sel['has_case_addons']),('selected',[],True),sel)
        before=state(layer)
        self.assertFalse(package.select(layer));self.assertEqual(package.init(layer),{'route':'legacy','created':False})
        self.assertEqual(state(layer),before)
    def test_held_selection_stops_and_writes_nothing(self):
        bad=[{'addons':[{'addon_id':'not-in-catalog','source':'bundled','addon_version':'1'}]},
             {'addons':[{'addon_id':'aipm','source':'bundled','addon_version':CATALOG_VERSION,'guide_ref':'x'}]},
             {'addons':[{'addon_id':'aipm','source':'bundled','addon_version':CATALOG_VERSION}]*2},
             {'work_style':'other','addons':[{'addon_id':'aipm','source':'bundled','addon_version':CATALOG_VERSION}]},
             {'work_style':'other'}]
        for n,extra in enumerate(bad):
            with self.subTest(case=n):
                layer=new_layer(self.base,'held'+str(n));d=package.load(layer/'intent.yaml');d.pop('work_style');d.update(extra);write_yaml(layer/'intent.yaml',d)
                before=state(layer)
                with self.assertRaisesRegex(ValueError,'addon selection held'):package.select(layer)
                with self.assertRaises(ValueError):package.init(layer)
                with self.assertRaises(ValueError):package.reset_to_init(layer,apply=True)
                code,out=run_cli('init','--layer',str(layer));self.assertEqual(code,1);self.assertIn('addon selection held',out['error'])
                self.assertEqual(state(layer),before)
    def test_selector_unavailable_stops_and_restores_sys_path(self):
        layer=to_bundled(new_layer(self.base,'nosel'));saved=package._SELECTOR
        try:
            package._SELECTOR=None;before=list(sys.path)
            with mock.patch('importlib.util.spec_from_file_location',return_value=None):
                with self.assertRaisesRegex(ValueError,'selector unavailable'):package.select(layer)
            self.assertEqual(sys.path,before)
            package._SELECTOR=None;self.assertTrue(package.select(layer));self.assertEqual(sys.path,before)
        finally:package._SELECTOR=saved
        self.assertFalse((layer/'Documents/aipm_project').exists())

if __name__=='__main__':unittest.main()
