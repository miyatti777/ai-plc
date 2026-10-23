"""Registers (aipm.registers: true) — Synthetic fixtures only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import tempfile, unittest, yaml
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_integration as base
package=base.package;validate_package=base.validate_package;METHOD=base.METHOD

HYP=[{'id':'H1','kind':'validation','claim':'synthetic structure','status':'unknown'},
     {'id':'H2','kind':'opportunity','claim':'[hypothesis] synthetic opportunity','status':'unknown'}]

def registers_fixture(layer,rows=None):
    """Reuse the integration fixture; inject aipm.registers and the registers file."""
    original=base.write_yaml
    def patched(p,d):
        if p.name=='intent.yaml':d=dict(d);d['aipm']=dict(d['aipm'],registers=True)
        original(p,d)
        if p.name=='validation_record.yaml':
            q=p.parent/'registers/hypotheses.yaml';q.parent.mkdir(exist_ok=True)
            original(q,{'hypotheses':rows if rows is not None else HYP})
    base.write_yaml=patched
    try:return base.fixture(layer)
    finally:base.write_yaml=original

class Registers(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def errors(self,root,layer):return [e for e in validate_package.validate(root,layer=layer)['errors'] if e['code']=='E_REGISTERS']
    def rewrite(self,root,rows):base.write_yaml(root/'registers/hypotheses.yaml',{'hypotheses':rows})
    def receipt(self,layer,name='receipt_meeting1.yaml',**over):
        r={'kind':'user_reported','actor':'actual_user','origin':'actual_user_reply','scope_id':'L-SYN-1','question_id':'Q1','received_at':'2026-10-19T10:00:00+09:00','answer':'synthetic'};r.update(over)
        base.write_yaml(layer/'Context'/name,r);return 'Context/'+name

    def test_legacy_contract_unchanged_without_opt_in(self):
        layer=self.base/'legacy';root,c=base.fixture(layer)
        self.assertNotIn('+registers',c['version']);self.assertNotIn('registers_contract_version',c)
        self.assertTrue(validate_package.validate(root,layer=layer)['pass'])

    def test_opt_in_suffix_and_hash(self):
        layer=self.base/'on';root,c=registers_fixture(layer)
        self.assertTrue(c['version'].endswith('+registers.2'));self.assertEqual(c['registers_contract_sha256'],base.sha(METHOD/'registers_contract.yaml'))
        check=validate_package.validate(root,layer=layer);self.assertTrue(check['pass'],check)

    def test_non_bool_opt_in_rejected(self):
        layer=self.base/'bad';layer.mkdir();base.write_yaml(layer/'intent.yaml',{'scope_id':'X','scope_name':'x','work_style':'aipm','aipm':{'date':'2026-10-19','registers':'yes'}})
        with self.assertRaises(ValueError):package.build_contract(layer)

    def test_missing_file_and_collision_and_mismatch(self):
        layer=self.base/'chk';root,c=registers_fixture(layer)
        (root/'registers/hypotheses.yaml').unlink();self.assertTrue(any('missing' in e['message'] for e in self.errors(root,layer)))
        self.rewrite(root,[{'id':'H1','kind':'opportunity','claim':'collides','status':'unknown'}])
        self.assertTrue(any('collides' in e['message'] for e in self.errors(root,layer)))
        self.rewrite(root,[{'id':'H1','kind':'validation','claim':'x','status':'not_supported'}])
        self.assertTrue(any('differs' in e['message'] for e in self.errors(root,layer)))

    def test_human_judgement_rules(self):
        layer=self.base/'hum';root,c=registers_fixture(layer)
        proxy={'date':'2026-10-19','event':'meeting 1','verdict':'supported','judged_by':'ai_proxy'}
        self.rewrite(root,[{'id':'H1','kind':'validation','claim':'x','status':'supported','judgements':[proxy]}])
        self.assertTrue(any('supported requires' in e['message'] for e in self.errors(root,layer)))
        owner=dict(proxy,judged_by='owner')
        self.rewrite(root,[{'id':'H1','kind':'validation','claim':'x','status':'supported','judgements':[proxy,owner]}])
        self.assertTrue(any('evidence_ref' in e['message'] for e in self.errors(root,layer)))
        owner['evidence_ref']='Context/missing.yaml'
        self.rewrite(root,[{'id':'H1','kind':'validation','claim':'x','status':'not_supported','judgements':[proxy,dict(owner,verdict='not_supported')]}])
        self.assertTrue(any('receipt file missing' in e['message'] for e in self.errors(root,layer)))
        owner['evidence_ref']=self.receipt(layer,'bad.yaml',origin='synthetic_trial')
        self.rewrite(root,[{'id':'H1','kind':'validation','claim':'x','status':'not_supported','judgements':[proxy,dict(owner,verdict='not_supported')]}])
        self.assertTrue(any('origin' in e['message'] for e in self.errors(root,layer)))
        owner['evidence_ref']=self.receipt(layer)
        self.rewrite(root,[{'id':'H1','kind':'validation','claim':'x','status':'not_supported','judgements':[proxy,dict(owner,verdict='not_supported')]}])
        self.assertEqual(self.errors(root,layer),[])

    def test_status_follows_latest_human_verdict(self):
        layer=self.base/'follow';root,c=registers_fixture(layer)
        ref=self.receipt(layer);own=lambda v:{'date':'2026-10-19','event':'meeting','verdict':v,'judged_by':'owner','evidence_ref':ref}
        self.rewrite(root,[{'id':'H1','kind':'validation','claim':'x','status':'supported','judgements':[own('not_supported')]}])
        self.assertTrue(any('latest owner/decider verdict' in e['message'] for e in self.errors(root,layer)))
        self.rewrite(root,[{'id':'H1','kind':'validation','claim':'x','status':'unknown','judgements':[own('supported'),own('undetermined')]}])
        self.assertEqual(self.errors(root,layer),[])
        proxy={'date':'2026-10-19','event':'meeting','verdict':'not_supported','judged_by':'ai_proxy'}
        self.rewrite(root,[{'id':'H1','kind':'validation','claim':'x','status':'unknown'},{'id':'H2','kind':'opportunity','claim':'y','status':'not_supported','judgements':[proxy]}])
        self.assertTrue(any('only unknown' in e['message'] for e in self.errors(root,layer)))
        self.rewrite(root,[{'id':'H1','kind':'validation','claim':'x','status':'unknown'},{'id':'H6','kind':'validation','claim':'z','status':'not_supported'}])
        self.assertTrue(any('#H6' in e['path'] and 'only unknown' in e['message'] for e in self.errors(root,layer)))

    def test_judgement_shape_and_bad_validation_id(self):
        layer=self.base/'jshape';root,c=registers_fixture(layer)
        self.rewrite(root,[{'id':'H1','kind':'validation','claim':'x','status':'unknown','judgements':[{'date':'','event':'m','verdict':'supported','judged_by':'ai_proxy','extra':1}]}])
        msgs=' '.join(e['message'] for e in self.errors(root,layer))
        self.assertIn('unknown key',msgs);self.assertIn('non-empty',msgs)
        val=base.package.load(root/'validation_record.yaml');val['hypotheses'][0]['id']=['H1'];base.write_yaml(root/'validation_record.yaml',val)
        self.assertTrue(any('must be a string' in e['message'] for e in self.errors(root,layer)))

    def test_courses_and_registers_compose(self):
        layer=self.base/'both';layer.mkdir();base.write_yaml(layer/'intent.yaml',{'scope_id':'L-BOTH','scope_name':'both','work_style':'aipm','aipm':{'date':'2026-10-19','course':'document_based/single_persona','registers':True}})
        c=package.build_contract(layer);self.assertTrue(c['version'].endswith('+courses.1+registers.2'));self.assertIn('course_contract_sha256',c);self.assertIn('registers_contract_sha256',c)

    def test_shape_errors(self):
        layer=self.base/'shape';root,c=registers_fixture(layer)
        self.rewrite(root,[{'id':'H1','kind':'validation','claim':'x','status':'unknown'},{'id':'H1','kind':'problem','claim':'y','status':'unknown'},{'id':'X9','kind':'idea','claim':'','status':'maybe','extra':1}])
        msgs=' '.join(e['message'] for e in self.errors(root,layer))
        for word in ['duplicate id','id must match']:self.assertIn(word,msgs)

    def test_init_writes_five_minimal_drafts_once(self):
        layer=self.base/'init';layer.mkdir();(layer/'Context').mkdir()
        base.write_yaml(layer/'intent.yaml',{'scope_id':'L-INIT','scope_name':'init','work_style':'aipm','aipm':{'date':'2026-10-19','registers':True},'goal':{'description':'synthetic'}})
        r=package.init(layer);root=Path(r['package'])
        self.assertEqual(sorted(r['registers']),sorted('registers/'+n+'.yaml' for n in ['issues','hypotheses','todo','wbs','roadmap']))
        self.assertEqual(len(r['outputs']),8);self.assertTrue(all(o['path'].startswith('Documents/aipm_project/') and len(o['sha256'])==64 for o in r['outputs']))
        wbs=yaml.safe_load((root/'registers/wbs.yaml').read_text())['wbs'];self.assertEqual([w['id'] for w in wbs],['W1','W2','W3','W4','W5']);self.assertTrue(all(w['status']=='draft' for w in wbs))
        hyp=yaml.safe_load((root/'registers/hypotheses.yaml').read_text())['hypotheses'];self.assertEqual((hyp[0]['id'],hyp[0]['kind']),('H1','opportunity'))
        before={q.name:q.read_bytes() for q in (root/'registers').iterdir()}
        again=package.init(layer);self.assertFalse(again['created']);self.assertEqual(before,{q.name:q.read_bytes() for q in (root/'registers').iterdir()})
        self.assertEqual(sorted(o['path'] for o in again['outputs']),sorted(o['path'] for o in r['outputs']))

    def test_init_without_registers_writes_no_registers(self):
        layer=self.base/'noreg';layer.mkdir();(layer/'Context').mkdir()
        base.write_yaml(layer/'intent.yaml',{'scope_id':'L-NOREG','scope_name':'noreg','work_style':'aipm','aipm':{'date':'2026-10-19'},'goal':{'description':'synthetic'}})
        r=package.init(layer);self.assertEqual(r['registers'],[]);self.assertFalse((Path(r['package'])/'registers').exists())

    def test_minimal_list_checks(self):
        layer=self.base/'lists';root,c=registers_fixture(layer);self.assertEqual(self.errors(root,layer),[])
        base.write_yaml(root/'registers/issues.yaml',{'issues':[{'id':'I1','question':'q','status':'open','priority':'medium','owner':'x','due':'undecided'}]})
        self.assertTrue(any('charter' in e['message'] for e in self.errors(root,layer)))
        base.write_yaml(root/'registers/wbs.yaml',{'wbs':[{'id':'W1','deliverable':'d','exit_criteria':'e','owner':'o','status':'done'},{'id':'W1','deliverable':'d','exit_criteria':'e','owner':'o','status':'draft'}]})
        msgs=' '.join(e['message'] for e in self.errors(root,layer));self.assertIn('unknown status',msgs);self.assertIn('duplicate id',msgs)
        (root/'registers/roadmap.yaml').unlink();self.assertTrue(any(e['path']=='registers/roadmap.yaml' and 'missing' in e['message'] for e in self.errors(root,layer)))
        base.write_yaml(root/'registers/todo.yaml',{'todo':[{'id':'T1','title':'t','status':'todo','owner':'o'}]})
        self.assertTrue(any('todo.yaml' in e['path'] and 'id must match' in e['message'] for e in self.errors(root,layer)))
        base.write_yaml(root/'registers/issues.yaml',{'charter':{'change_conditions':['c'],'exit_conditions':['e']},'issues':[{'id':'I1','question':'q','status':'cancelled','priority':'medium','owner':'x'},{'id':'I2','question':'  ','status':'open','priority':'medium','owner':'x','due':'undecided'}]})
        iss=[e for e in self.errors(root,layer) if 'issues.yaml' in e['path']]
        self.assertFalse(any('#0' in e['path'] for e in iss));self.assertTrue(any('#1' in e['path'] and 'question' in e['message'] for e in iss))
        self.assertTrue(any('todo.yaml' in e['path'] and 'id must match' in e['message'] for e in self.errors(root,layer)))

    def issues(self,root,rows,charter=None):
        base.write_yaml(root/'registers/issues.yaml',{'charter':charter or {'change_conditions':['c'],'exit_conditions':['e']},'issues':rows})
    def warnings(self,root,layer):return [w for w in validate_package.validate(root,layer=layer)['warnings'] if w['code']=='W_REGISTERS']

    def test_issue_map_completion_and_warnings(self):
        layer=self.base/'imap';root,c=registers_fixture(layer)
        ok=[{'id':'I1','question':'q1','status':'open','priority':'high','owner':'PM','due':'2026-11-01','answer':'H2','validation_plan':['H1']},
            {'id':'I2','question':'q2','status':'open','priority':'medium','owner':'PM','due':'undecided','parent':'I1'},
            {'id':'I3','question':'q3','status':'not_needed','priority':'medium','reason':'out of scope'},
            {'id':'I4','question':'q4','status':'open','priority':'critical','owner':'Lead','due':'2026-12-01','parent':'I1'},
            {'id':'I5','question':'q5','status':'on_hold','priority':'medium','owner':'PM','due':'undecided','answer':['H1','H2'],'reason':'wait for budget','review_at':'2026-12-01'}]
        self.issues(root,ok);self.assertEqual(self.errors(root,layer),[])
        self.assertTrue(any('I2' in w['path'] and 'undecided' in w['message'] for w in self.warnings(root,layer)))
        r=validate_package.validate(root,layer=layer);self.assertTrue(r['pass'],r['errors']);self.assertTrue(r['warnings'])
        self.issues(root,ok+[{'id':'I6','question':'q6','status':'open','priority':'medium'}])
        self.assertTrue(any(e['path'].endswith('#I6') and 'not complete' in e['message'] for e in self.errors(root,layer)))
        self.issues(root,[{'id':'I1','question':'q','status':'open','priority':'medium','owner':'[unknown]','due':'undecided'}])
        self.assertEqual(self.errors(root,layer),[]);self.assertTrue(any('[unknown]' in w['message'] for w in self.warnings(root,layer)))
        self.issues(root,ok,charter={'change_conditions':['[unknown]'],'exit_conditions':['[unknown]']})
        self.assertEqual(self.errors(root,layer),[]);self.assertTrue(any('charter' in w['path'] for w in self.warnings(root,layer)))

    def test_issue_map_refs_and_unknown_keys(self):
        layer=self.base/'irefs';root,c=registers_fixture(layer)
        row={'id':'I1','question':'q','status':'open','priority':'medium','owner':'o','due':'undecided'}
        self.issues(root,[dict(row,answer='H9')]);self.assertTrue(any('unknown id H9' in e['message'] for e in self.errors(root,layer)))
        self.issues(root,[dict(row,parent='I7')]);self.assertTrue(any('unknown id I7' in e['message'] for e in self.errors(root,layer)))
        self.issues(root,[dict(row,validation_plan=[1])]);self.assertTrue(any('must reference ids' in e['message'] for e in self.errors(root,layer)))
        self.issues(root,[dict(row,hypothesis='H1')]);self.assertTrue(any('unknown key' in e['message'] for e in self.errors(root,layer)))
        self.issues(root,[row],charter={'change_conditions':[],'exit_conditions':['e']});self.assertTrue(any('charter' in e['message'] for e in self.errors(root,layer)))

    def test_issue_map_review_fixes(self):
        layer=self.base/'ifix';root,c=registers_fixture(layer)
        q=root/'registers/issues.yaml'
        q.write_text('charter: {change_conditions: [c], exit_conditions: [e]}\nissues:\n- {id: I1, question: q, status: open, priority: medium, owner: o, due: 2026-11-01}\n')
        self.assertEqual(self.errors(root,layer),[])
        row={'question':'q','status':'open','priority':'medium'}
        self.issues(root,[dict(row,id='I1',reason='r')]);self.assertTrue(any('not complete' in e['message'] for e in self.errors(root,layer)))
        self.issues(root,[dict(row,id='I1',status='on_hold',reason='r',review_at='2026-12-01')]);self.assertEqual(self.errors(root,layer),[])
        own={'owner':'o','due':'undecided'}
        self.issues(root,[dict(row,id='I1',parent='I1',**own)]);self.assertTrue(any('itself' in e['message'] for e in self.errors(root,layer)))
        self.issues(root,[dict(row,id='I1',parent='I2',**own),dict(row,id='I2',parent='I1',**own)]);self.assertTrue(any('cycle' in e['message'] for e in self.errors(root,layer)))
        self.issues(root,[dict(row,id='I1',parent=['I1'],**own)]);self.assertTrue(any('one id' in e['message'] for e in self.errors(root,layer)))
        self.issues(root,[dict(row,id='I1',validation_plan='H2',**own)]);self.assertTrue(any('validation hypothesis' in e['message'] for e in self.errors(root,layer)))
        self.issues(root,[dict(row,id='I1',validation_plan='H1',**own)]);self.assertEqual(self.errors(root,layer),[])

    def test_issue_resolution(self):
        layer=self.base/'res';root,c=registers_fixture(layer)
        ref=self.receipt(layer)
        hyp=[{'id':'H1','kind':'validation','claim':'synthetic structure','status':'unknown'},
             {'id':'H2','kind':'opportunity','claim':'o','status':'supported','judgements':[{'date':'2026-10-19','event':'m','verdict':'supported','judged_by':'owner','evidence_ref':ref}]},
             {'id':'H3','kind':'problem','claim':'p','status':'unknown','judgements':[{'date':'2026-10-19','event':'m','verdict':'supported','judged_by':'ai_proxy'}]}]
        self.rewrite(root,hyp)
        (layer/'Context/decision1.md').write_text('# synthetic decision\n')
        own={'owner':'o','due':'undecided'}
        base_rows=[{'id':'I1','question':'q1','status':'resolved','priority':'high','answer':'H2','evidence_refs':['H2'],'decided_by':'owner',**own},
                   {'id':'I2','question':'q2','status':'not_needed','priority':'medium','reason':'out of scope'},
                   {'id':'I3','question':'q3','status':'on_hold','priority':'medium','reason':'budget','review_at':'2026-12-01',**own},
                   {'id':'I4','question':'q4','status':'open','priority':'medium',**own},
                   {'id':'I5','question':'q5','status':'open','priority':'medium',**own}]
        self.issues(root,base_rows)
        base.write_yaml(root/'registers/todo.yaml',{'todo':[{'id':'D1','title':'t1','status':'done','owner':'o','source':'I4'},{'id':'D2','title':'t2','status':'done','owner':'o','source':['I4']},{'id':'D3','title':'t3','status':'todo','owner':'o','source':'I5'}]})
        r=validate_package.validate(root,layer=layer)
        self.assertEqual([e for e in r['errors'] if e['code']=='E_REGISTERS'],[])
        left=[w['path'] for w in r['warnings'] if 'work done but issue still open' in w['message']]
        self.assertEqual(left,['registers/issues.yaml#I4'])
        sm=r['issues_summary'];self.assertEqual((sm['resolved'],sm['open'],sm['countable']),(1,2,3));self.assertAlmostEqual(sm['resolved_ratio'],1/3)
        # backlog task issue_id also counts as linked work
        base.write_yaml(layer/'backlog.yaml',{'tasks':[{'id':'T001','status':'completed','issue_id':'I5'}]})
        base.write_yaml(root/'registers/todo.yaml',{'todo':[]})
        left=[w['path'] for w in validate_package.validate(root,layer=layer)['warnings'] if 'work done' in w['message']]
        self.assertEqual(left,['registers/issues.yaml#I5'])
        # An operation task (recurrence, in_progress) with issue_id is not work, so the done normal task still warns
        base.write_yaml(layer/'backlog.yaml',{'tasks':[{'id':'T001','status':'completed','issue_id':'I5'},{'id':'T002','status':'in_progress','recurrence':'weekly','issue_id':'I5'}]})
        left=[w['path'] for w in validate_package.validate(root,layer=layer)['warnings'] if 'work done' in w['message']]
        self.assertEqual(left,['registers/issues.yaml#I5'])
        (layer/'backlog.yaml').unlink()  # later checks use other issue lists
        bad=[dict(base_rows[0],evidence_refs=['H3']),dict(base_rows[0],id='I6',evidence_refs=['Context/missing.md']),dict(base_rows[0],id='I7',decided_by='ai_proxy'),
             {'id':'I8','question':'q','status':'resolved','priority':'medium',**own},dict(base_rows[1],id='I9',reason=None),dict(base_rows[2],id='I10',review_at=None)]
        self.issues(root,bad);msgs=' '.join(e['path']+' '+e['message'] for e in self.errors(root,layer))
        for want in ['#I1 evidence H3 has no owner/decider','#I6 evidence Context/missing.md is not a decision record or receipt: file missing','#I7 decided_by must be','#I8 resolved needs answer','#I9 not_needed needs reason','#I10 on_hold needs review_at']:self.assertIn(want,msgs)
        self.issues(root,[dict(base_rows[0],answer='decided in words',evidence_refs=['Context/decision1.md'])])
        self.assertTrue(any('not a decision record' in e['message'] for e in self.errors(root,layer)))
        self.issues(root,[dict(base_rows[0],evidence_refs=['intent.yaml'])]);self.assertTrue(any('not a decision record' in e['message'] for e in self.errors(root,layer)))
        base.write_yaml(layer/'Context/decision1.yaml',{'kind':'decision_record','scope_id':'L-SYN-1','decided_by':'owner','decided_at':'2026-10-19','decision':'synthetic'})
        self.issues(root,[dict(base_rows[0],answer='decided in words',evidence_refs=['Context/decision1.yaml'])]);self.assertEqual(self.errors(root,layer),[])
        self.issues(root,[dict(base_rows[0],evidence_refs=[ref])]);self.assertEqual(self.errors(root,layer),[])
        self.issues(root,[dict(base_rows[0],answer='decided in words',evidence_refs=['Context/decision1.yaml'],decided_by='decider')]);self.assertTrue(any('differs from the record' in e['message'] for e in self.errors(root,layer)))
        self.issues(root,[dict(base_rows[0],answer='H9')]);self.assertEqual(validate_package.validate(root,layer=layer)['issues_summary']['invalid_resolved'],1)
        for typo in ('h1','H-1'):
            self.issues(root,[dict(base_rows[0],answer=typo)]);self.assertTrue(any('looks like an id' in w['message'] for w in self.warnings(root,layer)))
        self.issues(root,[base_rows[0],dict(base_rows[0],id='I2',evidence_refs=['H3']),dict(base_rows[3]),dict(base_rows[3],id='I9',status='weird')])
        sm=validate_package.validate(root,layer=layer)['issues_summary'];self.assertEqual((sm['resolved'],sm['invalid_resolved'],sm['total']),(2,1,3));self.assertAlmostEqual(sm['resolved_ratio'],1/3);self.assertAlmostEqual(sm['resolved_ratio_all'],1/3)

    def test_malformed_registers_do_not_crash(self):
        layer=self.base/'crash';root,c=registers_fixture(layer)
        for name,data in [('todo.yaml',['x']),('hypotheses.yaml',['x'])]:
            p=root/'registers'/name;keep=p.read_text();p.write_text(yaml.safe_dump(data))
            r=validate_package.validate(root,layer=layer);self.assertFalse(r['pass']);self.assertTrue(any(e['code']=='E_REGISTERS' for e in r['errors']));p.write_text(keep)
        self.rewrite(root,[{'id':'H1','kind':'validation','claim':'x','status':'unknown','judgements':5}]);self.assertTrue(any(e['code']=='E_REGISTERS' for e in validate_package.validate(root,layer=layer)['errors']))
        self.rewrite(root,HYP);(layer/'backlog.yaml').write_text(yaml.safe_dump(['x']));self.assertIn('pass',validate_package.validate(root,layer=layer))

    def wbsrows(self,root,rows):base.write_yaml(root/'registers/wbs.yaml',{'wbs':rows})
    def test_plan_lists(self):
        layer=self.base/'plan';root,c=registers_fixture(layer)
        wbs=yaml.safe_load((root/'registers/wbs.yaml').read_text())['wbs'];self.assertTrue(all('schedule' in w and w['source_of_truth']=='local' for w in wbs))
        self.assertEqual(self.errors(root,layer),[])
        w={'id':'W1','deliverable':'d','exit_criteria':'e','owner':'o','status':'draft'}
        (layer/'Documents/out1.md').write_text('x')
        self.wbsrows(root,[dict(w,status='accepted')]);self.assertTrue(any('needs evidence_refs' in e['message'] for e in self.errors(root,layer)))
        self.wbsrows(root,[dict(w,status='accepted',evidence_refs=['Documents/out1.md'])]);self.assertEqual(self.errors(root,layer),[])
        self.wbsrows(root,[dict(w,status='accepted',evidence_refs=['Documents/none.md'])]);self.assertTrue(any('evidence missing' in e['message'] for e in self.errors(root,layer)))
        self.wbsrows(root,[dict(w,depends=['W2']),dict(w,id='W2',depends=['W1'])]);self.assertTrue(any('cycle' in e['message'] for e in self.errors(root,layer)))
        self.wbsrows(root,[dict(w,schedule={'baseline':{'start':'2026-12-01','end':'2026-11-01'}})]);self.assertTrue(any('ends before' in e['message'] for e in self.errors(root,layer)))
        self.wbsrows(root,[dict(w,schedule={'baseline':{'start':'2026-11-01','end':'2026-12-01'},'forecast':{'start':'2026-11-01','end':'2027-01-15'},'history':[]})])
        ws=' '.join(x['message'] for x in self.warnings(root,layer));self.assertIn('no agreement record',ws);self.assertIn('history is empty',ws)
        self.wbsrows(root,[dict(w,source_of_truth='external')]);self.assertTrue(any('not supported' in e['message'] for e in self.errors(root,layer)))
        self.wbsrows(root,[dict(w,milestone_id='MS1'),dict(w,id='W2')])
        base.write_yaml(root/'registers/roadmap.yaml',{'roadmap':[{'id':'MS1','milestone':'m','period':'undecided','status':'draft','wbs_ids':['W2']}]})
        msgs=' '.join(e['message'] for e in self.errors(root,layer));self.assertIn('does not list this WBS',msgs)
        base.write_yaml(root/'registers/roadmap.yaml',{'roadmap':[{'id':'MS1','milestone':'m','period':'undecided','status':'draft','wbs_ids':['W1']}]});self.assertEqual(self.errors(root,layer),[])
        self.wbsrows(root,[dict(w),dict(w,id='W2')]);self.assertTrue(any('but its milestone_id is None' in e['message'] for e in self.errors(root,layer)))   # roadmap lists W1, W1 has no milestone_id
        self.wbsrows(root,[dict(w,milestone_id='MS1'),dict(w,id='W2')]);base.write_yaml(root/'registers/roadmap.yaml',{'roadmap':[{'id':'MS1','milestone':'m','period':'undecided','status':'draft'}]})
        self.assertTrue(any('does not list this WBS' in e['message'] for e in self.errors(root,layer)))   # milestone without wbs_ids
        base.write_yaml(root/'registers/roadmap.yaml',{'roadmap':[{'id':'MS1','milestone':'m','period':'undecided','status':'draft'}]})
        self.wbsrows(root,[dict(w,depends=['W2']),dict(w,id='W2',depends=['W2'])]);cyc=[e['path'] for e in self.errors(root,layer) if 'cycle' in e['message']]
        self.assertNotIn('registers/wbs.yaml#W1',cyc)
        q=root/'registers/wbs.yaml';q.write_text("wbs:\n- {id: W1, deliverable: d, exit_criteria: e, owner: o, status: draft, schedule: {baseline: {start: 2026-11-01, end: 2026-12-01}, forecast: {start: '2026-11-01', end: '2026-12-01'}, history: []}}\n")
        self.assertFalse(any('history is empty' in x['message'] for x in self.warnings(root,layer)))
        base.write_yaml(root/'registers/todo.yaml',{'todo':[{'id':'D1','title':'t','status':'todo','owner':'o','source':'H9'},{'id':'D2','title':'t','status':'todo','owner':'o','wbs_id':'W7'},{'id':'D3','title':'t','status':'todo','owner':'o','source':'会議 10/20'}]})
        msgs=' '.join(e['message'] for e in self.errors(root,layer));self.assertIn('unknown id H9',msgs);self.assertIn('unknown id W7',msgs)
        self.assertTrue(any('no WBS number' in x['message'] and '#D3' in x['path'] for x in self.warnings(root,layer)))
        sm=validate_package.validate(root,layer=layer)['wbs_summary'];self.assertEqual((sm['draft'],sm['total']),(1,1))

    def test_candidate_waits_for_every_task_of_the_same_wbs(self):
        layer=self.base/'allwbs';root,c=registers_fixture(layer)
        for n in (1,2,3):(layer/f'Documents/o{n}.md').write_text('x')
        def tasks(s1,s2,s3):base.write_yaml(layer/'backlog.yaml',{'tasks':[{'id':'T1','status':s1,'output':'Documents/o1.md','wbs_id':'W1'},{'id':'T2','status':s2,'output':'Documents/o2.md','wbs_id':'W1'},{'id':'T3','status':s3,'output':'Documents/o3.md','wbs_id':'W1.1'}]})
        def row():return [w for w in yaml.safe_load((root/'registers/wbs.yaml').read_text())['wbs'] if w['id']=='W1'][0]
        tasks('completed','pending','completed')
        r=package.wbs_candidate(layer,'T1');self.assertEqual(r['status'],'draft');self.assertEqual(r['pending_tasks'],[{'id':'T2','status':'pending'}])
        self.assertEqual((row()['status'],row()['evidence_refs']),('draft',['Documents/o1.md']))   # W1.1 (T3) is a different row
        def set_row(status):
            d=yaml.safe_load((root/'registers/wbs.yaml').read_text())
            for w in d['wbs']:
                if w['id']=='W1':w['status']=status;w['evidence_refs']=['Documents/o3.md'] if status in ('partially_accepted','accepted') else []
            base.write_yaml(root/'registers/wbs.yaml',d)
        for st in ('deferred','blocked'):
            tasks('completed',st,'completed');r=package.wbs_candidate(layer,'T1');self.assertEqual((r['status'],r['pending_tasks']),('draft',[{'id':'T2','status':st}]))
        tasks('completed','cancelled','pending');r=package.wbs_candidate(layer,'T1');self.assertEqual((r['status'],r['pending_tasks']),('pending_acceptance',[]))
        set_row('draft');tasks('completed','completed','pending');r=package.wbs_candidate(layer,'T2');self.assertEqual((r['status_before'],r['status']),('draft','pending_acceptance'));self.assertEqual(row()['evidence_refs'],['Documents/o2.md'])
        # an existing candidate is not reverted, and the note says the remaining tasks must be checked
        tasks('completed','pending','completed');r=package.wbs_candidate(layer,'T1');self.assertEqual(r['status'],'pending_acceptance');self.assertIn('戻さない',r['note']);self.assertEqual(r['pending_tasks'],[{'id':'T2','status':'pending'}])
        # partially_accepted keeps its state with or without remaining tasks; cancelled rows are not changed
        for st in ('pending','completed'):
            set_row('partially_accepted');tasks('completed',st,'completed');r=package.wbs_candidate(layer,'T1');self.assertEqual(r['status'],'partially_accepted');self.assertEqual(row()['evidence_refs'],['Documents/o3.md','Documents/o1.md'])
        set_row('cancelled');r=package.wbs_candidate(layer,'T1');self.assertFalse(r['changed']);self.assertEqual(row()['status'],'cancelled')

    def test_judge_command(self):
        """package.py judge appends owner/decider judgements backed by a receipt and sets status."""
        layer=self.base/'judge';root,c=registers_fixture(layer);ref=self.receipt(layer)
        rows=[{'id':'H1','kind':'validation','claim':'x','status':'unknown'},{'id':'H2','kind':'opportunity','claim':'y','status':'unknown','judgements':[{'date':'2026-10-19','event':'meeting','verdict':'supported','judged_by':'ai_proxy'}]}]
        self.rewrite(root,rows);q=root/'registers/hypotheses.yaml'
        def inp(**over):
            d={'date':'2026-10-20','event':'meeting 2','judged_by':'owner','evidence_ref':ref,'judgements':[{'hypothesis_id':'H2','verdict':'supported'},{'hypothesis_id':'H1','verdict':'undetermined','note':'not enough evidence'}]};d.update(over)
            base.write_yaml(layer/'Context/judge.yaml',d);return 'Context/judge.yaml'
        for bad in ({'judged_by':'ai_proxy'},{'evidence_ref':'Context/missing.yaml'},{'evidence_ref':self.receipt(layer,'bad.yaml',origin='synthetic_trial')},{'judgements':[{'hypothesis_id':'H9','verdict':'supported'}]},{'judgements':[{'hypothesis_id':'H1','verdict':'maybe'}]},{'judgements':[{'hypothesis_id':'H1','verdict':'supported'},{'hypothesis_id':'H1','verdict':'supported'}]},{'judgements':[]}):
            before=q.read_bytes()
            with self.assertRaises(ValueError):package.judge(layer,inp(**bad))
            self.assertEqual(before,q.read_bytes())
        r=package.judge(layer,inp());self.assertEqual([(x['id'],x['status']) for x in r['changes']],[('H2','supported'),('H1','unknown')])
        d=yaml.safe_load(q.read_text());h2=[h for h in d['hypotheses'] if h['id']=='H2'][0]
        self.assertEqual([g['judged_by'] for g in h2['judgements']],['ai_proxy','owner'])   # appended, never reordered
        self.assertEqual(self.errors(root,layer),[])
        r=package.judge(layer,inp(judgements=[{'hypothesis_id':'H2','verdict':'not_supported'}]));self.assertEqual(r['changes'][0]['status'],'not_supported');self.assertEqual(self.errors(root,layer),[])
        plain=self.base/'plain';base.fixture(plain);self.assertEqual(package.judge(plain,'Context/case.yaml')['route'],'unselected')

    def test_retired_recurring_task_is_not_pending(self):
        """A recurring operation task closed with retired_at does not keep a WBS row from becoming a candidate."""
        layer=self.base/'retired';root,c=registers_fixture(layer);(layer/'Documents/o1.md').write_text('x')
        def tasks(extra):base.write_yaml(layer/'backlog.yaml',{'tasks':[{'id':'T1','status':'completed','output':'Documents/o1.md','wbs_id':'W1'},{'id':'T2','status':'in_progress','recurrence':'weekly','wbs_id':'W1',**extra}]})
        tasks({});r=package.wbs_candidate(layer,'T1');self.assertEqual((r['status'],[x['id'] for x in r['pending_tasks']]),('draft',['T2']))
        tasks({'retired_at':'2026-10-21','retired_reason':'Goal 達成'});r=package.wbs_candidate(layer,'T1');self.assertEqual((r['status'],r['pending_tasks']),('pending_acceptance',[]))

    def test_candidate_returns_schedule_actual_hint(self):
        """The actual date is a candidate only when no task with the same wbs_id remains
        (the only task here is completed); a remaining task keeps it back. wbs.yaml schedule is untouched."""
        layer=self.base/'sched';root,c=registers_fixture(layer);(layer/'Documents/o1.md').write_text('x')
        base.write_yaml(layer/'backlog.yaml',{'tasks':[{'id':'T1','status':'completed','output':'Documents/o1.md','wbs_id':'W1','scheduled_for':'2026-10-20','completed_at':'2026-10-21'}]})
        before=yaml.safe_load((root/'registers/wbs.yaml').read_text())['wbs'][0]['schedule']
        r=package.wbs_candidate(layer,'T1');self.assertEqual((r['schedule_actual_candidate'],r['schedule_actual_basis']),('2026-10-21',['T1']))
        self.assertEqual(yaml.safe_load((root/'registers/wbs.yaml').read_text())['wbs'][0]['schedule'],before)
        base.write_yaml(layer/'backlog.yaml',{'tasks':[{'id':'T1','status':'completed','output':'Documents/o1.md','wbs_id':'W1','scheduled_for':'2026-10-20','completed_at':'2026-10-21'},{'id':'T2','status':'pending','wbs_id':'W1'}]})
        self.assertNotIn('schedule_actual_candidate',package.wbs_candidate(layer,'T1'))   # a remaining task: no candidate
        base.write_yaml(layer/'backlog.yaml',{'tasks':[{'id':'T1','status':'completed','output':'Documents/o1.md','wbs_id':'W1','completed_at':'2026-10-21'}]})
        self.assertNotIn('schedule_actual_candidate',package.wbs_candidate(layer,'T1'))
        # A mixed row (one task without scheduled_for) gives a candidate when both have completed_at,
        # and a completed_at that is not a date is reported as missing instead of being compared as text
        (layer/'Documents/o2.md').write_text('y')
        rows=[{'id':'T1','status':'completed','output':'Documents/o1.md','wbs_id':'W1','scheduled_for':'2026-10-20','completed_at':'2026-10-21'},
              {'id':'T2','status':'completed','output':'Documents/o2.md','wbs_id':'W1','completed_at':'2026-10-23'}]
        base.write_yaml(layer/'backlog.yaml',{'tasks':rows});r=package.wbs_candidate(layer,'T2')
        self.assertEqual((r['schedule_actual_candidate'],r['schedule_actual_basis']),('2026-10-23',['T1','T2']))
        rows[1]['completed_at']='10/23';base.write_yaml(layer/'backlog.yaml',{'tasks':rows});r=package.wbs_candidate(layer,'T2')
        self.assertEqual(r.get('schedule_actual_missing'),['T2']);self.assertNotIn('schedule_actual_candidate',r)

    def test_schedule_actual_waits_for_every_task_of_the_wbs_row(self):
        """No candidate while a task of the same wbs_id remains; then the latest completed_at with every
        completed task as the basis; a completed task without completed_at is reported instead. scheduled_for on any task
        of the row is enough. wbs.yaml schedule is never written."""
        layer=self.base/'sched_all';root,c=registers_fixture(layer)
        for n in (1,2):(layer/f'Documents/o{n}.md').write_text('x')
        sched=lambda:yaml.safe_load((root/'registers/wbs.yaml').read_text())['wbs'][0]['schedule'];before=sched()
        t1={'id':'T1','status':'completed','output':'Documents/o1.md','wbs_id':'W1','scheduled_for':'2026-10-20','completed_at':'2026-10-21'}
        def tasks(t2):base.write_yaml(layer/'backlog.yaml',{'tasks':[t1,{'id':'T2','output':'Documents/o2.md','wbs_id':'W1',**t2}]})
        tasks({'status':'pending'});r=package.wbs_candidate(layer,'T1')
        self.assertNotIn('schedule_actual_candidate',r);self.assertNotIn('schedule_actual_missing',r)
        tasks({'status':'completed','completed_at':'2026-10-23'});r=package.wbs_candidate(layer,'T2')
        self.assertEqual((r['schedule_actual_candidate'],r['schedule_actual_basis']),('2026-10-23',['T1','T2']))
        tasks({'status':'completed'});r=package.wbs_candidate(layer,'T2')
        self.assertNotIn('schedule_actual_candidate',r);self.assertEqual(r['schedule_actual_missing'],['T2'])
        # scheduled_for only on the other task of the row is enough
        t1.pop('scheduled_for');tasks({'status':'completed','completed_at':'2026-10-23','scheduled_for':'2026-W43'})
        self.assertEqual(package.wbs_candidate(layer,'T1')['schedule_actual_candidate'],'2026-10-23')
        self.assertEqual(sched(),before)

    def test_init_issue_priority_is_unknown_and_valid(self):
        """init does not write an unconfirmed priority; [unknown] passes validate (warning only for owner)."""
        layer=self.base/'prio';root,c=registers_fixture(layer)
        self.issues(root,[{'id':'I1','question':'q','status':'open','priority':'[unknown]','owner':'[unknown]','due':'undecided'}])
        self.assertEqual(self.errors(root,layer),[])
        init=self.base/'prio-init';init.mkdir();(init/'Context').mkdir()
        base.write_yaml(init/'intent.yaml',{'scope_id':'L-PRIO','scope_name':'prio','work_style':'aipm','aipm':{'date':'2026-10-21','registers':True},'goal':{'description':'synthetic'}})
        r=package.init(init);iss=yaml.safe_load((Path(r['package'])/'registers/issues.yaml').read_text())['issues']
        self.assertEqual((iss[0]['priority'],iss[0]['owner']),('[unknown]','[unknown]'))

    def test_task_links_and_candidate(self):
        layer=self.base/'links';root,c=registers_fixture(layer)
        (layer/'Documents/out1.md').write_text('x')
        base.write_yaml(layer/'backlog.yaml',{'tasks':[{'id':'T001','status':'pending','output':'Documents/out1.md','wbs_id':'W1','issue_id':'I1'},
            {'id':'T002','status':'pending','output':'Documents/out2.md'},{'id':'T003','status':'pending','output':'x','type':'management'},
            {'id':'T004','status':'pending','output':'x','wbs_id':'none'},{'id':'T005','status':'pending','wbs_id':'W9','issue_id':'I9'}]})
        msgs=' '.join(e['path']+' '+e['message'] for e in self.errors(root,layer))
        self.assertIn('#T005 wbs_id points to unknown WBS W9',msgs);self.assertIn('#T005 issue_id points to unknown issue I9',msgs)
        warned=[x['path'] for x in self.warnings(root,layer) if 'has no wbs_id' in x['message']];self.assertEqual(warned,['backlog.yaml#T002'])
        with self.assertRaises(ValueError):package.wbs_candidate(layer,'T001')   # not completed yet
        bl=yaml.safe_load((layer/'backlog.yaml').read_text());bl['tasks'][0]['status']='completed';base.write_yaml(layer/'backlog.yaml',bl)
        r=package.wbs_candidate(layer,'T001');self.assertTrue(r['changed']);self.assertEqual(r['status'],'pending_acceptance')
        row=[w for w in yaml.safe_load((root/'registers/wbs.yaml').read_text())['wbs'] if w['id']=='W1'][0]
        self.assertEqual((row['status'],row['evidence_refs']),('pending_acceptance',['Documents/out1.md']))
        self.assertEqual(package.wbs_candidate(layer,'T001')['evidence_refs'],['Documents/out1.md'])   # idempotent
        row['status']='accepted';d=yaml.safe_load((root/'registers/wbs.yaml').read_text())
        for w in d['wbs']:
            if w['id']=='W1':w['status']='accepted'
        base.write_yaml(root/'registers/wbs.yaml',d);self.assertFalse(package.wbs_candidate(layer,'T001')['changed'])
        self.assertEqual(package.wbs_candidate(layer,'T004')['changed'],False)

    def test_warnings_do_not_change_pass_for_legacy(self):
        layer=self.base/'legw';root,c=base.fixture(layer);r=validate_package.validate(root,layer=layer)
        self.assertTrue(r['pass']);self.assertEqual(r['warnings'],[])

if __name__=='__main__':unittest.main()
