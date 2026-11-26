"""registers edits in the apply way (register_edits.py). Proposals (R-*), the numbered list (rlist_*), the
person's reply (five replies, thread required), the write with the check before/after and the record register_edits[], the
revert of the last edit, the stop of pm- writes in a saved box that carries versions, and E_REDIT / W_REDIT. Judgement fields
are never written and unsettled rows are held. Synthetic boxes only (the person's words here are synthetic)."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
from datetime import datetime, timezone
from unittest import mock
import unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent));sys.path.insert(0,str(HERE))
import package, validate_package, ops, register_edits as rex
import test_integration as ti, test_init_and_reset as tr
import test_apply_register_clone as arc, test_sheets_layout as tsl
import registry_fixture as rf
write_yaml,sha=ti.write_yaml,ti.sha
def now():return datetime.now(timezone.utc).isoformat()
MEMO='Context/synthetic_memo.md'
REGS=('issues','hypotheses','todo','wbs','roadmap')

class Base(arc.Base):
    def box(self,name,saved=True):
        """A sheets_v1 document_based box with registers. saved: archived (version 1, kind first)."""
        layer,c,packet=tsl.sheets_prepare(self,name,'document_based/single_persona')
        d=package.load(layer/'intent.yaml');d['aipm']['registers']=True;write_yaml(layer/'intent.yaml',d)
        packet['validation_record']['hypotheses'][0]['id']='H2';write_yaml(layer/'Context/course_input.yaml',packet)   # H1 is the Init opportunity
        root=self.draft(layer);rf.register(self.repo,d['scope_id'])
        h=package.load(root/'hypotheses.yaml');h['hypotheses'].append({'id':'H2','kind':'validation','claim':'synthetic validation','status':'unknown'});write_yaml(root/'hypotheses.yaml',h)
        (layer/MEMO).write_text('# synthetic memo\n')
        if saved:
            res=package.archive_course(layer);self.assertTrue(res['pass'],res['errors'])
        return layer,root
    def inp(self,layer,edits,name='in.yaml'):
        write_yaml(layer/'Context'/name,{'source':{'kind':'document','ref':'synthetic extraction'},'edits':edits});return 'Context/'+name
    def adopt(self,layer,quote='OK',thread='thread-synthetic'):
        lst=rex.redit_list(layer);rex.redit_judge(layer,lst['digest'],quote,now(),thread);return lst
    def final(self,layer,root):
        r=validate_package.validate(root,phase='final',layer=layer);return r['pass'],sorted({(e['code'],e['path']) for e in r['errors']}),[w['code'] for w in r['warnings']]
    EDITS=[{'op':'append','register':'hypotheses','row':'H1','field':'sources','values':[MEMO],'reason':'material'},
           {'op':'append','register':'issues','row':'I1','field':'sources','values':[MEMO]},
           {'op':'append','register':'wbs','row':'W1','field':'evidence_refs','values':[MEMO]},
           {'op':'append','register':'roadmap','row':'MS1','field':'note','value':'synthetic note'},
           {'op':'add_row','register':'wbs','row_data':{'deliverable':'synthetic deliverable','exit_criteria':'synthetic exit','owner':'[unknown]','status':'draft'}},
           {'op':'add_row','register':'todo','row_data':{'title':'synthetic todo','owner':'[unknown]','note':'n'}}]

class Flow_(Base):
    def test_saved_box_flow(self):
        layer,root=self.box('fl');docs={k:v for k,v in tr.state(root).items() if not k.endswith('.yaml') or '/' in k};m0=package.load(root/'manifest.yaml');stock=tr.state(self.repo/'Stock')
        inp=self.inp(layer,self.EDITS);ctx=tr.state(layer/'Context');out=rex.redit(layer,inp)
        self.assertFalse(out['apply']);self.assertEqual(len(out['proposals']),6);self.assertEqual(tr.state(layer/'Context'),ctx)   # dry-run
        self.assertTrue(all(p['judgment']=={'state':'undecided'} for p in out['proposals']))   # the AI never judges
        rex.redit(layer,inp,apply=True);lst=self.adopt(layer)
        self.assertEqual(len(lst['rows']),6)
        out=rex.redit_apply(layer);self.assertFalse(out['apply']);self.assertEqual(len(out['changes']),6)
        with self.assertRaisesRegex(ValueError,'approval-ref'):rex.redit_apply(layer,apply=True)
        out=rex.redit_apply(layer,apply=True,approval_ref='chat:synthetic');self.assertEqual(out['written'],['hypotheses','issues','roadmap','todo','wbs'])
        m=package.load(root/'manifest.yaml');e=m['register_edits'][0]
        self.assertEqual((e['edit'],e['base_version'],e['list_digest']),(1,1,lst['digest']));self.assertEqual(e['judgments'][0]['thread'],'thread-synthetic')
        self.assertEqual(e['registers_sha256'],{k:sha(root/(k+'.yaml')) for k in REGS})
        for k in m0:self.assertEqual(m[k],m0[k],k)   # applies, records, receipts, evidence: the same
        self.assertEqual({k:v for k,v in tr.state(root).items() if not k.endswith('.yaml') or '/' in k},docs);self.assertEqual(tr.state(self.repo/'Stock'),stock)
        h=package.load(root/'hypotheses.yaml');self.assertIn(MEMO,next(r for r in h['hypotheses'] if r['id']=='H1')['sources'])
        w=package.load(root/'wbs.yaml')['wbs'];self.assertEqual(w[-1]['id'],'W6');self.assertEqual(w[-1]['status'],'draft')
        t=package.load(root/'todo.yaml')['todo'];self.assertEqual(t[-1]['id'],'D1')
        r=package.load(root/'roadmap.yaml')['roadmap'][0];self.assertTrue(r['note'].endswith(': synthetic note'))
        self.assertEqual(self.final(layer,root)[:2],(True,[]))
        with self.assertRaisesRegex(ValueError,'no registers proposal'):rex.redit_list(layer)   # all merged
    def test_unsaved_box_flow(self):
        layer,root=self.box('us',saved=False)
        rex.redit(layer,self.inp(layer,self.EDITS[:2]),apply=True);self.adopt(layer)
        out=rex.redit_apply(layer,apply=True,approval_ref='s');self.assertEqual(package.load(root/'manifest.yaml')['register_edits'][0]['base_version'],None)

class Refusals(Base):
    def test_proposal_refusals_write_nothing(self):
        layer,root=self.box('rf')
        cases=(({'op':'append','register':'hypotheses','row':'H1','field':'status','values':['supported']},'judgement the person makes'),
               ({'op':'append','register':'issues','row':'I1','field':'evidence_refs','values':[MEMO]},'cannot be appended'),
               ({'op':'append','register':'issues','row':'I9','field':'sources','values':[MEMO]},'row not found'),
               ({'op':'append','register':'issues','row':'I1','field':'sources','values':['Context/nothing.md']},'source not found'),
               ({'op':'append','register':'roadmap','row':'MS1','field':'note','value':'  '},'needs value'),
               ({'op':'add_row','register':'wbs','row_data':{'deliverable':'d','exit_criteria':'e','owner':'o','status':'accepted'}},'starts as'),
               ({'op':'add_row','register':'hypotheses','row_data':{'kind':'problem','claim':'c','method':'m','success':'s','falsification':'f','status':'supported'}},'starts as'),
               ({'op':'add_row','register':'wbs','row_data':{'deliverable':'d','exit_criteria':'e','owner':'o','milestone_id':'MS1'}},'no milestone_id'),
               ({'op':'add_row','register':'issues','row_data':{'question':'q','priority':'P1','answer':'H1'}},'judgement fields'),
               ({'op':'add_row','register':'todo','row_data':{'title':'t','owner':'o','foo':'x'}},'unknown keys'),
               ({'op':'add_row','register':'todo','row_data':{'id':'D9','title':'t','owner':'o'}},'gets its id'),
               ({'op':'append','register':'wbs','row':'W1','field':'milestone_id','value':'MS9'},'roadmap row'))
        for edit,pattern in cases:
            with self.subTest(pattern=pattern):
                inp=self.inp(layer,[edit],'bad.yaml');ctx=tr.state(layer/'Context');box=tr.state(root)
                for apply in (False,True):
                    with self.assertRaisesRegex(ValueError,pattern):rex.redit(layer,inp,apply=apply)
                self.assertEqual(tr.state(root),box);self.assertEqual(tr.state(layer/'Context'),ctx)
    def test_unsettled_rows_are_held(self):
        layer,root=self.box('ho')
        edits=[{'op':'add_row','register':'hypotheses','row_data':{'kind':'problem','claim':'synthetic H21','method':'未定','success':'s','falsification':'f'}},
               {'op':'add_row','register':'wbs','row_data':{'deliverable':'TBD','exit_criteria':'e','owner':'o'}},
               {'op':'append','register':'hypotheses','row':'H1','field':'sources','values':[MEMO]}]
        out=rex.redit(layer,self.inp(layer,edits,'h.yaml'),apply=True)
        self.assertEqual(len(out['proposals']),1);self.assertEqual([h['n'] for h in out['held']],[1,2]);self.assertIn('unsettled: method',out['held'][0]['reason'])
        self.assertTrue((layer/'Context/aipm_changes/rheld_h.yaml').is_file())
    def test_apply_refusals_write_nothing(self):
        def no_versions(case):
            layer,root=case.box('nv');m=package.load(root/'manifest.yaml');m.pop('applies');write_yaml(root/'manifest.yaml',m);return layer,root,'run package.py register'
        def unpushed(case):
            layer,root=case.box('up');rex.redit(layer,case.inp(layer,case.EDITS[:1]),apply=True);case.adopt(layer)
            m=package.load(root/'manifest.yaml');m['applies'][0]['pushed']=False;write_yaml(root/'manifest.yaml',m);return layer,root,'not pushed'
        def not_judged(case):
            layer,root=case.box('nj');rex.redit(layer,case.inp(layer,case.EDITS[:1]),apply=True);rex.redit_list(layer);return layer,root,'no adopted'
        def list_outdated(case):
            layer,root=case.box('lo');rex.redit(layer,case.inp(layer,case.EDITS[:1]),apply=True);case.adopt(layer);rex.redit(layer,case.inp(layer,case.EDITS[1:2],'b.yaml'),apply=True);return layer,root,'changed after the last list'
        def register_changed(case):
            layer,root=case.box('rc');rex.redit(layer,case.inp(layer,case.EDITS[:1]),apply=True);case.adopt(layer)
            h=package.load(root/'hypotheses.yaml');h['hypotheses'][0]['claim']+=' edited';write_yaml(root/'hypotheses.yaml',h);return layer,root,'changed after the proposal'
        def half_pair(case):
            layer,root=case.box('hp');rex.redit(layer,case.inp(layer,[{'op':'append','register':'wbs','row':'W1','field':'milestone_id','value':'MS1'}]),apply=True);case.adopt(layer);return layer,root,'adopted in the same list'
        for build in (no_versions,unpushed,not_judged,list_outdated,register_changed,half_pair):
            with self.subTest(case=build.__name__):
                layer,root,pattern=build(self);box=tr.state(root);ctx=tr.state(layer/'Context')
                for apply in (False,True):
                    with self.assertRaisesRegex(ValueError,pattern):rex.redit_apply(layer,apply=apply,approval_ref='s')
                self.assertEqual(tr.state(root),box);self.assertEqual(tr.state(layer/'Context'),ctx)
    def test_judge_needs_thread_and_one_of_the_five(self):
        layer,root=self.box('jt');rex.redit(layer,self.inp(layer,self.EDITS[:1]),apply=True);lst=rex.redit_list(layer);ctx=tr.state(layer/'Context')
        for args,pattern in (((lst['digest'],'OK',now(),''),'--thread'),((lst['digest'],'いいね',now(),'t'),'not one of the five'),((lst['digest'],'修正: 1 は「x」に直す',now(),'t'),'note only')):
            with self.subTest(args=args):
                with self.assertRaisesRegex(ValueError,pattern):rex.redit_judge(layer,*args)
                self.assertEqual(tr.state(layer/'Context'),ctx)
    def test_revise_a_note(self):
        layer,root=self.box('rv');rex.redit(layer,self.inp(layer,[self.EDITS[3]]),apply=True);lst=rex.redit_list(layer)
        out=rex.redit_judge(layer,lst['digest'],'修正: 1 は「直したメモ」に直す',now(),'t');self.assertIn('new_list',out)
        rex.redit_apply(layer,apply=True,approval_ref='s');self.assertTrue(package.load(root/'roadmap.yaml')['roadmap'][0]['note'].endswith(': 直したメモ'))

class More(Base):
    def test_todo_note_and_new_roadmap_row(self):
        layer,root=self.box('tn');rex.redit(layer,self.inp(layer,[self.EDITS[5]]),apply=True);self.adopt(layer);rex.redit_apply(layer,apply=True,approval_ref='s')   # D1
        rex.redit(layer,self.inp(layer,[{'op':'append','register':'todo','row':'D1','field':'note','value':'second line'},
            {'op':'add_row','register':'roadmap','row_data':{'milestone':'synthetic milestone','period':'undecided','status':'planned'}}],'b.yaml'),apply=True);self.adopt(layer)
        rex.redit_apply(layer,apply=True,approval_ref='s')
        d1=package.load(root/'todo.yaml')['todo'][0];self.assertEqual(d1['note'].split('\n')[0],'n');self.assertTrue(d1['note'].endswith(': second line'))
        self.assertEqual(package.load(root/'roadmap.yaml')['roadmap'][-1]['id'],'MS2')
        self.assertEqual([e['edit'] for e in package.load(root/'manifest.yaml')['register_edits']],[1,2]);self.assertEqual(self.final(layer,root)[:2],(True,[]))
    def test_reapply_after_revert(self):
        layer,root=self.box('ra');rex.redit(layer,self.inp(layer,self.EDITS[:1]),apply=True);self.adopt(layer)
        rex.redit_apply(layer,apply=True,approval_ref='s');rex.redit_revert(layer,apply=True,approval_ref='s')
        out=rex.redit_apply(layer,apply=True,approval_ref='s2');self.assertTrue(out['written'])
        self.assertTrue(package.load(root/'manifest.yaml')['register_edits'][0]['backup'].endswith('_2'))
    def test_new_wbs_row_carries_no_agreement_and_new_sources_are_checked(self):
        layer,root=self.box('ag');base={'deliverable':'d','exit_criteria':'e','owner':'o'}
        for extra,pattern in (({'schedule':{'baseline':{'agreed_by':'owner','agreed_at':'2026-10-28'},'forecast':None,'actual':None,'history':[]}},'forecast only'),({'gate':'g'},'no gate'),({'evidence_refs':[MEMO]},'no gate')):
            with self.subTest(extra=list(extra)):
                with self.assertRaisesRegex(ValueError,pattern):rex.redit(layer,self.inp(layer,[{'op':'add_row','register':'wbs','row_data':{**base,**extra}}],'w.yaml'))
        ok=rex.redit(layer,self.inp(layer,[{'op':'add_row','register':'wbs','row_data':{**base,'schedule':{'baseline':None,'forecast':{'start':'2026-11-01','end':'2026-11-30'},'actual':None,'history':[]}}}],'w2.yaml'));self.assertEqual(len(ok['proposals']),1)
        with self.assertRaisesRegex(ValueError,'source not found'):rex.redit(layer,self.inp(layer,[{'op':'add_row','register':'issues','row_data':{'question':'q','priority':'P1','sources':['Context/nothing.md']}}],'s.yaml'))
    def test_string_evidence_keeps_its_form(self):
        layer,root=self.box('es');h=package.load(root/'hypotheses.yaml');h['hypotheses'][0]['evidence']='first';write_yaml(root/'hypotheses.yaml',h)
        rex.redit(layer,self.inp(layer,[{'op':'append','register':'hypotheses','row':'H1','field':'evidence','values':['second']}]),apply=True);self.adopt(layer);rex.redit_apply(layer,apply=True,approval_ref='s')
        self.assertEqual(package.load(root/'hypotheses.yaml')['hypotheses'][0]['evidence'],'first\nsecond')

class Pairs_and_back(Base):
    def test_pair_adopted_together(self):
        layer,root=self.box('pa')
        rex.redit(layer,self.inp(layer,[{'op':'append','register':'wbs','row':'W1','field':'milestone_id','value':'MS1'},{'op':'append','register':'roadmap','row':'MS1','field':'wbs_ids','values':['W1']}]),apply=True);self.adopt(layer)
        rex.redit_apply(layer,apply=True,approval_ref='s');self.assertEqual(self.final(layer,root)[:2],(True,[]))
    def test_a_worse_check_or_an_interrupt_puts_everything_back(self):
        real=validate_package.validate
        def worse():
            calls=[]
            def f(*a,**k):
                calls.append(1);r=real(*a,**k)
                return r if len(calls)==1 else {**r,'pass':False,'errors':r['errors']+[{'code':'E_SYNTH','path':'.','message':'s'}]}
            return f
        for name,patch in (('worse',lambda:mock.patch.object(validate_package,'validate',side_effect=worse())),('interrupt',lambda:mock.patch.object(rex.shutil,'copy2',side_effect=KeyboardInterrupt))):
            with self.subTest(case=name):
                layer,root=self.box('w'+name[:2]);rex.redit(layer,self.inp(layer,self.EDITS),apply=True);self.adopt(layer);box=tr.state(root);ctx=tr.state(layer/'Context')
                with patch(),self.assertRaisesRegex(ValueError,'as before'):rex.redit_apply(layer,apply=True,approval_ref='s')
                self.assertEqual(tr.state(root),box);self.assertEqual(tr.state(layer/'Context'),ctx)
                self.assertTrue(rex.redit_apply(layer,apply=True,approval_ref='s')['written'])   # and it can run again
    def test_revert_the_last_edit(self):
        layer,root=self.box('rt');box=tr.state(root);rex.redit(layer,self.inp(layer,self.EDITS),apply=True);self.adopt(layer);rex.redit_apply(layer,apply=True,approval_ref='s')
        with self.assertRaisesRegex(ValueError,'approval-ref'):rex.redit_revert(layer,apply=True)
        out=rex.redit_revert(layer,apply=True,approval_ref='s');self.assertTrue(out['reverted'])
        self.assertEqual(tr.state(root),box)   # registers and manifest: bytes and times as before the edit
        self.assertTrue(all(p['merge']['state']=='not_merged' for p in rex.proposals(layer)))
        with self.assertRaisesRegex(ValueError,'no registers edit'):rex.redit_revert(layer)
    def test_revert_refuses_after_a_change_outside(self):
        layer,root=self.box('ro');rex.redit(layer,self.inp(layer,self.EDITS[:1]),apply=True);self.adopt(layer);rex.redit_apply(layer,apply=True,approval_ref='s')
        h=package.load(root/'hypotheses.yaml');h['hypotheses'][0]['claim']+=' later';write_yaml(root/'hypotheses.yaml',h);box=tr.state(root)
        with self.assertRaisesRegex(ValueError,'registers changed after edit'):rex.redit_revert(layer,apply=True,approval_ref='s')
        self.assertEqual(tr.state(root),box)
        ok,errs,w=self.final(layer,root);self.assertIn('W_REDIT',w)   # a change outside redit is a warning only

class Ops_and_validate(Base):
    def test_pm_writes_stop_in_a_saved_box_but_judgement_and_state_ops_stay(self):
        layer,root=self.box('op');write_yaml(layer/'Context/q.yaml',{'question':'synthetic question'})
        out=ops.run(layer,'issue.add','Context/q.yaml');self.assertEqual(out['route'],'held');self.assertIn('redit',out['reason'])
        rex.redit(layer,self.inp(layer,[self.EDITS[5]]),apply=True);self.adopt(layer);rex.redit_apply(layer,apply=True,approval_ref='s')   # D1
        write_yaml(layer/'Context/mv.yaml',{'id':'D1','status':'doing'});out=ops.run(layer,'todo.move','Context/mv.yaml')
        self.assertNotEqual(out.get('route'),'held')   # todo.move stays
        write_yaml(layer/'Context/mv2.yaml',{'id':'D1','status':'done','note_add':'synthetic: closed by the owner'});before=package.load(root/'todo.yaml')
        out=ops.run(layer,'todo.move','Context/mv2.yaml',apply=True);self.assertEqual(out['route'],'held');self.assertIn('status だけ',out['reason'])
        self.assertEqual(package.load(root/'todo.yaml'),before)
        layer2,root2=self.box('op2',saved=False);write_yaml(layer2/'Context/q.yaml',{'question':'synthetic question'})
        self.assertNotEqual(ops.run(layer2,'issue.add','Context/q.yaml').get('route'),'held')   # an unsaved box: as before
    def test_e_redit(self):
        layer,root=self.box('ev');rex.redit(layer,self.inp(layer,self.EDITS[:1]),apply=True);self.adopt(layer);rex.redit_apply(layer,apply=True,approval_ref='s')
        m=package.load(root/'manifest.yaml')
        for name,edit,msg in (('gap',lambda d:d['register_edits'][0].update(edit=2),'without a gap'),('no thread',lambda d:d['register_edits'][0]['judgments'][0].pop('thread'),'thread'),('base',lambda d:d['register_edits'][0].update(base_version=9),'base_version')):
            with self.subTest(case=name):
                d=package.load(root/'manifest.yaml');edit(d);write_yaml(root/'manifest.yaml',d)
                r=validate_package.validate(root,phase='final',layer=layer);self.assertTrue(any(e['code']=='E_REDIT' and msg in e['message'] for e in r['errors']),r['errors'])
                write_yaml(root/'manifest.yaml',m)

class CLI(Base):
    def test_cli(self):
        layer,root=self.box('cl');inp=self.inp(layer,self.EDITS[:2])
        code,out=tr.run_cli('redit','--layer',str(layer),'--input',inp,'--apply');self.assertEqual(code,0,out)
        code,lst=tr.run_cli('redit-list','--layer',str(layer));self.assertEqual(code,0,lst)
        code,out=tr.run_cli('redit-judge','--layer',str(layer),'--list',lst['digest_short'],'--quote','OK','--at',now(),'--thread','t');self.assertEqual(code,0,out)
        code,out=tr.run_cli('redit-apply','--layer',str(layer),'--apply','--approval-ref','s');self.assertEqual(code,0,out)
        code,out=tr.run_cli('redit-revert','--layer',str(layer));self.assertEqual(code,0,out);self.assertFalse(out['apply'])

class ReviewFixesT004(Base):
    """review: the write binds the content the person adopted; new rows that would fail the check after
    writing stop or get the same defaults as pm-; pm- stop reasons name what redit can and cannot do."""
    def test_a_proposal_changed_after_adoption_is_not_written(self):
        layer,root=self.box('cg');rex.redit(layer,self.inp(layer,[self.EDITS[3]]),apply=True);self.adopt(layer)
        q=next((layer/'Context/aipm_changes').glob('R-*.yaml'));d=package.load(q);d['append']['value']='not what the person saw';write_yaml(q,d)
        rex.redit_list(layer);box=tr.state(root)   # a new list alone is not a new reply
        with self.assertRaisesRegex(ValueError,'changed after the person adopted'):rex.redit_apply(layer,apply=True,approval_ref='s')
        self.assertEqual(tr.state(root),box)
    def test_a_revised_note_is_written_as_revised(self):
        layer,root=self.box('rv');rex.redit(layer,self.inp(layer,[self.EDITS[3]]),apply=True);self.adopt(layer,'修正: 1 は「直した文」に直す')
        rex.redit_apply(layer,apply=True,approval_ref='s');self.assertTrue(package.load(root/'roadmap.yaml')['roadmap'][0]['note'].endswith(': 直した文'))
    def test_new_issue_gets_owner_and_due_like_pm(self):
        layer,root=self.box('ni');rex.redit(layer,self.inp(layer,[{'op':'add_row','register':'issues','row_data':{'question':'synthetic question?','priority':'high','parent':'I1'}},self.EDITS[3]]),apply=True);self.adopt(layer)
        rex.redit_apply(layer,apply=True,approval_ref='s');row=package.load(root/'issues.yaml')['issues'][-1]
        self.assertEqual((row['owner'],row['due'],row['status'],row['parent']),('[unknown]','undecided','open','I1'));self.assertEqual(self.final(layer,root)[:2],(True,[]))
    def test_new_rows_that_cannot_pass_stop_at_the_proposal(self):
        layer,root=self.box('np');ctx=tr.state(layer/'Context')
        for e,msg in (({'op':'add_row','register':'hypotheses','row_data':{'kind':'guess','claim':'c','method':'m','success':'s','falsification':'f'}},'kind must be one of'),
                      ({'op':'add_row','register':'hypotheses','row_data':{'kind':'problem','claim':'c','method':'m','success':'s','falsification':'f','priority':'low'}},'priority must be one of'),
                      ({'op':'add_row','register':'roadmap','row_data':{'milestone':'m','period':'undecided','status':'planned','wbs_ids':['W1']}},'carries no wbs_ids')):
            with self.assertRaisesRegex(ValueError,msg):rex.redit(layer,self.inp(layer,[e]),apply=True)
        self.assertEqual({k:v for k,v in tr.state(layer/'Context').items() if not k.startswith('in.yaml')},{k:v for k,v in ctx.items() if not k.startswith('in.yaml')})
    def test_pm_stop_reasons_name_what_redit_can_do(self):
        layer,root=self.box('rs');write_yaml(layer/'Context/x.yaml',{'id':'I1'})
        r={n:ops.run(layer,n,'Context/x.yaml')['reason'] for n in ('issue.propose','hypothesis.propose','todo.link','issue.split','todo.add')}
        self.assertIn('一覧に書かない',r['issue.propose']);self.assertIn('package.py judge',r['hypothesis.propose'])
        self.assertIn('今は redit で足せない',r['todo.link']);self.assertIn('parent',r['issue.split']);self.assertIn('redit-apply',r['todo.add'])

class ReviewFixesT004b(Base):
    """A later 差し戻し stops an adopted proposal not written yet; references of a new row are checked."""
    def test_send_back_after_revert_is_not_written(self):
        layer,root=self.box('sb');rex.redit(layer,self.inp(layer,[self.EDITS[3]]),apply=True);self.adopt(layer)
        rex.redit_apply(layer,apply=True,approval_ref='s');rex.redit_revert(layer,apply=True,approval_ref='s')
        self.adopt(layer,'差し戻し');box=tr.state(root)
        with self.assertRaises(ValueError):rex.redit_apply(layer,apply=True,approval_ref='s')
        self.assertEqual(tr.state(root),box)
    def test_send_back_frees_a_changed_proposal(self):
        layer,root=self.box('sc');rex.redit(layer,self.inp(layer,[self.EDITS[3]]),apply=True);self.adopt(layer)
        q=next((layer/'Context/aipm_changes').glob('R-*.yaml'));d=package.load(q);d['append']['value']='changed';write_yaml(q,d)
        out=self.adopt(layer,'差し戻し');self.assertEqual(package.load(q)['judgment']['state'],'rejected')
    def test_new_row_references_are_checked(self):
        layer,root=self.box('rr')
        for e,msg in (({'op':'add_row','register':'issues','row_data':{'question':'q?','priority':'high','parent':'I99'}},'parent points to unknown'),
                      ({'op':'add_row','register':'todo','row_data':{'title':'t','owner':'[unknown]','wbs_id':'W99'}},'wbs_id points to unknown'),
                      ({'op':'add_row','register':'todo','row_data':{'title':'t','owner':'[unknown]','source':'I99'}},'source points to unknown'),
                      ({'op':'add_row','register':'hypotheses','row_data':{'kind':'problem','claim':'c','method':'m','success':'s','falsification':'f','issue_id':'I99'}},'issue_id points to unknown')):
            with self.assertRaisesRegex(ValueError,msg):rex.redit(layer,self.inp(layer,[e]))
    def test_an_undecided_hypothesis_priority_is_left_out(self):
        layer,root=self.box('hp');rex.redit(layer,self.inp(layer,[{'op':'add_row','register':'hypotheses','row_data':{'kind':'problem','claim':'c','method':'m','success':'s','falsification':'f','priority':'[unknown]'}}]),apply=True);self.adopt(layer)
        rex.redit_apply(layer,apply=True,approval_ref='s');h=package.load(root/'hypotheses.yaml')['hypotheses'][-1]
        self.assertNotIn('priority',h);self.assertEqual(self.final(layer,root)[:2],(True,[]))

class ReviewFixesT004c(Base):
    """The wbs evidence and the box's contract are checked at the proposal; a revert keeps a record of the
    write's approval and the revert's; malformed new rows stop; the list that matches the proposals now is the one judged."""
    def test_wbs_evidence_is_checked_at_the_proposal(self):
        layer,root=self.box('we')
        for v,msg in (('Context/none.md','evidence missing'),('H99','unknown id H99')):
            with self.assertRaisesRegex(ValueError,msg):rex.redit(layer,self.inp(layer,[{'op':'append','register':'wbs','row':'W1','field':'evidence_refs','values':[v]}]))
        self.assertEqual(rex.redit(layer,self.inp(layer,[{'op':'append','register':'wbs','row':'W1','field':'evidence_refs','values':['H2']}]))['proposals'][0]['op'],'append')
    def test_a_field_outside_the_box_contract_stops(self):
        layer,root=self.box('v1');rc=package.registers_contract(package.load(root/'format_contract.yaml'))
        rc['files']['issues']['optional']=[k for k in rc['files']['issues']['optional'] if k!='sources']
        with mock.patch.object(rex,'registers_contract',return_value=rc,create=True),mock.patch.object(package,'registers_contract',return_value=rc):
            with self.assertRaisesRegex(ValueError,'not in this box'):rex.redit(layer,self.inp(layer,[self.EDITS[1]]))
    def test_revert_keeps_a_record_of_both_approvals(self):
        layer,root=self.box('rk');rex.redit(layer,self.inp(layer,[self.EDITS[3]]),apply=True);self.adopt(layer)
        rex.redit_apply(layer,apply=True,approval_ref='chat:first');out=rex.redit_revert(layer,apply=True,approval_ref='chat:revert')
        r=package.load(layer/out['record']);self.assertEqual((r['approval_ref'],r['edit']['approval_ref'],r['edit']['judgments'][0]['thread']),('chat:revert','chat:first','thread-synthetic'))
        rex.redit_apply(layer,apply=True,approval_ref='chat:again');out2=rex.redit_revert(layer,apply=True,approval_ref='chat:revert2')
        self.assertNotEqual(out['record'],out2['record'])   # never over an earlier record
    def test_malformed_new_rows_stop(self):
        layer,root=self.box('mf')
        for e,msg in (({'op':'add_row','register':'issues','row_data':{'question':'q?','priority':'high','parent':['I1']}},'parent is one id'),
                      ({'op':'add_row','register':'todo','row_data':{'title':'t','owner':'[unknown]','source':['I99']}},'source points to unknown'),
                      ({'op':'add_row','register':'wbs','row_data':{'deliverable':'d','exit_criteria':'e','owner':'[unknown]','status':'draft','schedule':{'forecast':{'start':'2026-12-01','end':'2026-11-01'}}}},'ends before it starts'),
                      ({'op':'add_row','register':'wbs','row_data':{'deliverable':'d','exit_criteria':'e','owner':'[unknown]','status':'draft','schedule':{'forecast':'2026-12'}}},'must be a map')):
            with self.assertRaisesRegex(ValueError,msg):rex.redit(layer,self.inp(layer,[e]))

class ReviewFixesT004d(Base):
    """Unquoted YAML dates, undecided references, the list chosen by the proposals now."""
    def test_unquoted_dates_become_text(self):
        layer,root=self.box('ud');(layer/'Context/d.yaml').write_text('source: {kind: document, ref: synthetic}\nedits:\n- {op: add_row, register: issues, row_data: {question: "q?", priority: high, due: 2026-11-30}}\n- {op: add_row, register: wbs, row_data: {deliverable: d, exit_criteria: e, owner: "[unknown]", status: draft, schedule: {forecast: {start: 2026-11-01, end: 2026-11-30}}}}\n')
        rex.redit(layer,'Context/d.yaml',apply=True);self.adopt(layer);rex.redit_apply(layer,apply=True,approval_ref='s')
        self.assertEqual(package.load(root/'issues.yaml')['issues'][-1]['due'],'2026-11-30');self.assertEqual(self.final(layer,root)[:2],(True,[]))
    def test_undecided_references_are_left_out_and_bad_sources_stop(self):
        layer,root=self.box('ur')
        out=rex.redit(layer,self.inp(layer,[{'op':'add_row','register':'todo','row_data':{'title':'t','owner':'[unknown]','wbs_id':'未定'}}]))
        self.assertNotIn('wbs_id',out['proposals'][0]['row'])
        with self.assertRaisesRegex(ValueError,'text or a list of ids'):rex.redit(layer,self.inp(layer,[{'op':'add_row','register':'todo','row_data':{'title':'t','owner':'[unknown]','source':['I1',3]}}]))
    def test_the_list_that_matches_the_proposals_now_is_used(self):
        layer,root=self.box('lm');rex.redit(layer,self.inp(layer,[self.EDITS[3]]),apply=True);self.adopt(layer)   # L1
        rex.redit_apply(layer,apply=True,approval_ref='s')
        rex.redit(layer,self.inp(layer,[self.EDITS[1]],'b.yaml'),apply=True);self.adopt(layer,'差し戻し')   # L2 sent back
        with self.assertRaisesRegex(ValueError,'no proposal left'):rex.redit_apply(layer,apply=True,approval_ref='s')
        rex.redit_revert(layer,apply=True,approval_ref='s')
        rex.redit_apply(layer,apply=True,approval_ref='s2');self.assertEqual(len(package.load(root/'manifest.yaml')['register_edits']),1)   # L1 matches again

class ReviewFixesT004e(Base):
    """Value types that would fail the check after writing stop at the proposal; the reply is in the list."""
    def test_types_stop_at_the_proposal(self):
        layer,root=self.box('ty')
        for e,msg in (({'op':'add_row','register':'todo','row_data':{'title':'t','owner':'[unknown]','source':3}},'text or a list of ids'),
                      ({'op':'add_row','register':'issues','row_data':{'question':'q?','priority':'high','owner':5}},'must be text'),
                      ({'op':'add_row','register':'todo','row_data':{'title':'t','owner':'[unknown]','wbs_id':[{'a':1}]}},'must reference ids'),
                      ({'op':'add_row','register':'todo','row_data':{'title':'t','owner':'[unknown]','source_of_truth':'sheet'}},'source_of_truth must be'),
                      ({'op':'add_row','register':'issues','row_data':{'question':'q?','priority':'high','sources':MEMO}},'list of paths')):
            with self.assertRaisesRegex(ValueError,msg):rex.redit(layer,self.inp(layer,[e]))
        self.assertNotIn('sources',rex.redit(layer,self.inp(layer,[{'op':'add_row','register':'issues','row_data':{'question':'q?','priority':'high','sources':[]}}]))['proposals'][0]['row'])
    def test_a_judgement_without_the_reply_in_the_list_is_not_written(self):
        layer,root=self.box('jr');rex.redit(layer,self.inp(layer,[self.EDITS[3]]),apply=True);rex.redit_list(layer)
        q=next((layer/'Context/aipm_changes').glob('R-*.yaml'));d=package.load(q);lst=next((layer/'Context/aipm_changes').glob('rlist_*.yaml'))
        import changes as ch
        d['judgment']={'state':'adopted','quote':'OK','at':now(),'thread':'t','list_digest':package.load(lst)['digest'],'reply':'all','content_sha256':ch.content_sha(d)};write_yaml(q,d)
        with self.assertRaisesRegex(ValueError,'reply is not in the list'):rex.redit_apply(layer,apply=True,approval_ref='s')

class Fill(Base):
    """op: fill sets a field left unsettled at init (issue due / owner / priority, todo due / owner / priority / wbs_id) after the
    person decides it: same proposal → list → reply → write; a settled value is never overwritten (issue due dates)."""
    def undecided_issue(self,root):
        d=package.load(root/'issues.yaml');d['issues'][0]['due']='undecided';write_yaml(root/'issues.yaml',d)
    def test_fill_an_undecided_due_through_the_list(self):
        layer,root=self.box('fd',saved=False);self.undecided_issue(root)
        rex.redit(layer,self.inp(layer,[{'op':'fill','register':'issues','row':'I1','field':'due','value':'2026-11-15','reason':'本人の回答（合成）'}]),apply=True)
        lst=rex.redit_list(layer);self.assertEqual(lst['rows'][0]['fill'],'issues.I1.due');self.assertEqual(lst['rows'][0]['before'],'undecided')
        rex.redit_judge(layer,lst['digest'],'OK（全件反映）',now(),'thread-synthetic');rex.redit_apply(layer,apply=True,approval_ref='s')
        i1=package.load(root/'issues.yaml')['issues'][0];self.assertEqual((i1['due'],i1['status']),('2026-11-15','open'))
        self.assertEqual(package.load(root/'manifest.yaml')['register_edits'][0]['changes'][0]['op'],'fill')
        with self.assertRaisesRegex(ValueError,'already 2026-11-15'):rex.redit(layer,self.inp(layer,[{'op':'fill','register':'issues','row':'I1','field':'due','value':'2026-11-20'}],'again.yaml'))   # a settled value is never overwritten
    def test_fill_in_a_saved_box_and_unquoted_date(self):
        layer,root=self.box('fs')
        d=package.load(root/'issues.yaml');d['issues'][0]['due']='undecided';write_yaml(root/'issues.yaml',d)
        (layer/'Context/f.yaml').write_text('source: {kind: conversation, ref: synthetic}\nedits:\n- {op: fill, register: issues, row: I1, field: due, value: 2026-11-06}\n')
        rex.redit(layer,'Context/f.yaml',apply=True);self.adopt(layer);rex.redit_apply(layer,apply=True,approval_ref='s')
        self.assertEqual(package.load(root/'issues.yaml')['issues'][0]['due'],'2026-11-06')
    def test_fill_refusals(self):
        layer,root=self.box('fr',saved=False);self.undecided_issue(root)
        i1=package.load(root/'issues.yaml')['issues'][0]
        rex.redit(layer,self.inp(layer,[self.EDITS[5]],'d.yaml'),apply=True);self.adopt(layer);rex.redit_apply(layer,apply=True,approval_ref='s')   # D1 (owner [unknown], no due)
        for e,msg in (({'op':'fill','register':'issues','row':'I1','field':'status','value':'resolved'},'cannot be filled'),
                      ({'op':'fill','register':'issues','row':'I1','field':'answer','value':'x'},'cannot be filled'),
                      ({'op':'fill','register':'issues','row':'I1','field':'due','value':'11/15'},'YYYY-MM-DD'),
                      ({'op':'fill','register':'issues','row':'I1','field':'due','value':'undecided'},'decided value'),
                      ({'op':'fill','register':'issues','row':'I1','field':'question','value':'q?'},'cannot be filled'),
                      ({'op':'fill','register':'todo','row':'D1','field':'wbs_id','value':'W99'},'unknown id W99'),
                      ({'op':'fill','register':'hypotheses','row':'H1','field':'priority','value':'high'},'cannot be filled')):
            with self.assertRaisesRegex(ValueError,msg):rex.redit(layer,self.inp(layer,[e]))
        d=package.load(root/'issues.yaml');d['issues'][0]['owner']='owner-a';write_yaml(root/'issues.yaml',d)
        with self.assertRaisesRegex(ValueError,'already owner-a'):rex.redit(layer,self.inp(layer,[{'op':'fill','register':'issues','row':'I1','field':'owner','value':'someone'}]))
        for v in ('20261115','2026-W46-1'):
            with self.assertRaisesRegex(ValueError,'YYYY-MM-DD'):rex.redit(layer,self.inp(layer,[{'op':'fill','register':'issues','row':'I1','field':'due','value':v}]))
        with self.assertRaisesRegex(ValueError,'filled twice'):rex.redit(layer,self.inp(layer,[{'op':'fill','register':'issues','row':'I1','field':'due','value':'2026-11-15'},{'op':'fill','register':'issues','row':'I1','field':'due','value':'2026-11-20'}]))
        t_=package.load(root/'todo.yaml');t_['todo'][0]['status']='done';write_yaml(root/'todo.yaml',t_)
        with self.assertRaisesRegex(ValueError,'still in progress'):rex.redit(layer,self.inp(layer,[{'op':'fill','register':'todo','row':'D1','field':'due','value':'2026-12-01'}]))
        t_['todo'][0]['status']='todo';write_yaml(root/'todo.yaml',t_)
        out=rex.redit(layer,self.inp(layer,[{'op':'fill','register':'todo','row':'D1','field':'wbs_id','value':'W1'},{'op':'fill','register':'todo','row':'D1','field':'due','value':'2026-12-01'}]))
        self.assertEqual(len(out['proposals']),2)
    def test_two_fills_of_the_same_field_stop(self):
        layer,root=self.box('f2',saved=False);self.undecided_issue(root)
        rex.redit(layer,self.inp(layer,[{'op':'fill','register':'issues','row':'I1','field':'due','value':'2026-11-15'}]),apply=True)
        rex.redit(layer,self.inp(layer,[{'op':'fill','register':'issues','row':'I1','field':'due','value':'2026-11-20'}],'b.yaml'),apply=True);self.adopt(layer)   # two inputs, one list
        with self.assertRaisesRegex(ValueError,'same field'):rex.redit_apply(layer,apply=True,approval_ref='s')
    def test_fill_mixed_with_append_and_add_row_then_revert(self):
        layer,root=self.box('fm');self.undecided_issue(root)
        rex.redit(layer,self.inp(layer,[self.EDITS[5]],'d.yaml'),apply=True);self.adopt(layer);rex.redit_apply(layer,apply=True,approval_ref='s')   # D1
        before={k:sha(root/(k+'.yaml')) for k in REGS}
        rex.redit(layer,self.inp(layer,[{'op':'fill','register':'issues','row':'I1','field':'due','value':'2026-11-15'},self.EDITS[1],
            {'op':'fill','register':'todo','row':'D1','field':'wbs_id','value':'W1'},{'op':'fill','register':'todo','row':'D1','field':'due','value':'2026-12-01'},
            {'op':'fill','register':'todo','row':'D1','field':'priority','value':'high'},{'op':'fill','register':'todo','row':'D1','field':'owner','value':'owner-a'},
            {'op':'add_row','register':'todo','row_data':{'title':'synthetic todo 2','owner':'[unknown]'}}]),apply=True)
        lst=rex.redit_list(layer)
        with self.assertRaisesRegex(ValueError,'note only'):rex.redit_judge(layer,lst['digest'],'修正: 1 は「x」に直す',now(),'t')
        rex.redit_judge(layer,lst['digest'],'OK（全件反映）',now(),'t');rex.redit_apply(layer,apply=True,approval_ref='s')
        d1=package.load(root/'todo.yaml')['todo'][0];self.assertEqual((d1['wbs_id'],d1['due'],d1['priority'],d1['owner']),('W1','2026-12-01','high','owner-a'))
        self.assertEqual(package.load(root/'issues.yaml')['issues'][0]['due'],'2026-11-15');self.assertEqual(self.final(layer,root)[:2],(True,[]))
        rex.redit_revert(layer,apply=True,approval_ref='s');self.assertEqual({k:sha(root/(k+'.yaml')) for k in REGS},before)
        rex.redit_apply(layer,apply=True,approval_ref='s2');self.assertEqual(package.load(root/'issues.yaml')['issues'][0]['due'],'2026-11-15')

if __name__=='__main__':unittest.main()
