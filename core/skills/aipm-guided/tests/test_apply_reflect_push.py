"""apply (stage 6: the adopted proposals into the box as an unpushed version, a new receipt from the
person's judgement), push (stage 7: into the Stock after the conflict check) and --revert-unpushed. Every refusal and
every failure (an exception or Ctrl-C) leaves what that stage would write as it was. The earlier receipts stay as they are.
The person's words here are synthetic. Synthetic repository, Stock and Registry only; no real box is touched."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
from datetime import datetime, timezone
from unittest import mock
import os, unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent));sys.path.insert(0,str(HERE))
import package, validate_package, changes, applying
import test_integration as ti, test_init_and_reset as tr
import test_apply_register_clone as arc, test_apply_change_judgment as acj
import registry_fixture as rf
write_yaml,sha=ti.write_yaml,ti.sha
def now():return datetime.now(timezone.utc).isoformat()

class Apply(arc.Base):
    persona_doc=acj.Changes.persona_doc;candidate=acj.Changes.candidate
    def confirmed_box(self,name):
        """A document_based box whose persona answer is bound (decisions.persona confirmed_actual, a gap on it), archived
        (version 1, kind first) and cloned."""
        layer,c,packet=self.prepare(name,pending=True)
        packet['gaps'].append({'kind':'unknown','reason':'needs the user','requires_user':True,'decision_key':'persona','question':'?'});write_yaml(layer/'Context/course_input.yaml',packet)
        root=self.draft(layer)
        write_yaml(layer/'Context/ask.yaml',{'stage':'persona','question':'Which actual persona should be used?','answer':'Synthetic reply only','question_id':'SYN-Q1','source_thread_id':'SYNTHETIC-THREAD','answered_at':now()})
        package.receipt(layer,'Context/ask.yaml')
        rf.register(self.repo,package.load(layer/'intent.yaml')['scope_id'])
        res=package.archive_course(layer);self.assertTrue(res['pass'],res['errors'])
        package.clone(layer);m=package.load(root/'manifest.yaml');return layer,root,m['archive_target']['target_rel']
    def judged(self,layer,root,quote='OK',thread='thread-synthetic',drafts=False):
        changes.change(layer,self.candidate(layer,root,drafts=drafts),apply=True);lst=changes.change_list(layer)
        changes.judge_change(layer,lst['digest'],quote,now(),thread);return lst
    def final(self,layer,root):
        res=validate_package.validate(root,phase='final',layer=layer);return res['pass'],sorted({(e['code'],e['path'],e['message']) for e in res['errors']}),[w['code'] for w in res['warnings']]
    def stock(self):return tr.state(self.repo/'Stock')

    def test_v1_to_v2_then_push(self):
        layer,root,target=self.confirmed_box('fl');m0=package.load(root/'manifest.yaml');persona=self.persona_doc(root)
        receipt0=sha(layer/m0['human_responses']['persona']['source']);hr0=m0['human_responses'];ct0=m0['checkpoint_targets']
        self.judged(layer,root);stock=self.stock()
        out=applying.apply(layer);self.assertFalse(out['apply']);self.assertEqual(out['version'],2);self.assertEqual(out['receipts'],['persona'])
        with self.assertRaisesRegex(ValueError,'approval-ref'):applying.apply(layer,apply=True)
        out=applying.apply(layer,apply=True,approval_ref='chat:synthetic apply');self.assertTrue(out['final']['pass'],out['final']['errors'])
        self.assertIn('W_UNPUSHED',[w['code'] for w in out['final']['warnings']]);self.assertEqual(self.stock(),stock)   # stage 6 never writes the Stock
        m=package.load(root/'manifest.yaml');v2=m['applies'][-1]
        self.assertEqual((v2['version'],v2['kind'],v2['pushed'],v2['base_version'],v2['event']),(2,'apply',False,1,'apply_v2'))
        self.assertEqual({x['path'] for x in v2['changed']},{persona});self.assertIn('家族との時間',(root/persona).read_text())
        self.assertEqual(m['human_responses'],hr0);self.assertEqual(m['checkpoint_targets'],ct0);self.assertEqual(sha(layer/hr0['persona']['source']),receipt0)   # the earlier answer stays
        rec=v2['receipts']['persona'];r=package.load(layer/rec['source']);self.assertEqual((r['answer'],r['source_thread_id'],r['question_id'],r['target_sha256']),('OK','thread-synthetic',rec['list_digest'],sha(root/persona)))
        self.assertTrue(all(p['merge']['state']=='merged' for p in changes.proposals(layer)))
        out=applying.push(layer);self.assertFalse(out['apply']);self.assertEqual(self.stock(),stock)
        out=applying.push(layer,apply=True,approval_ref='chat:synthetic push');self.assertTrue(out['final']['pass'],out['final']['errors'])
        self.assertNotIn('W_UNPUSHED',[w['code'] for w in out['final']['warnings']])
        m=package.load(root/'manifest.yaml');log=package.load(self.repo/target/package.APPLY_LOG)
        self.assertEqual([v['version'] for v in log['versions']],[1,2]);self.assertTrue(m['applies'][-1]['pushed'])
        for r in m['records']:
            if r['archive_path']:self.assertEqual((self.repo/r['archive_path']).read_bytes(),(root/r['path']).read_bytes())
        b=package.load(layer/'Context/aipm_changes/base_course_fl.yaml');self.assertEqual(b['version'],2)   # the next work starts from version 2
        self.assertEqual(package.clone(layer)['version'],2)
    def test_confirmed_persona_and_the_batch_gap_need_the_version_receipt(self):
        layer,root,target=self.confirmed_box('cp');self.judged(layer,root);applying.apply(layer,apply=True,approval_ref='s')
        self.assertEqual(self.final(layer,root)[:2],(True,[]))
        m=package.load(root/'manifest.yaml');rec=m['applies'][-1]['receipts']['persona']
        for name,edit in (('receipt bytes',lambda:(layer/rec['source']).write_text((layer/rec['source']).read_text()+'# x\n')),
                          ('not adopted',lambda:[write_yaml(layer/'Context/aipm_changes'/(p['id']+'.yaml'),{**p,'judgment':{'state':'held'}}) for p in changes.proposals(layer)])):
            with self.subTest(case=name):
                saved={q:q.read_bytes() for q in (layer/'Context').rglob('*.yaml')}
                edit();ok,errs,w=self.final(layer,root);self.assertFalse(ok);self.assertTrue(any(c=='E_CHECKPOINT' for c,p,msg in errs),errs)
                for q,b in saved.items():q.write_bytes(b)
        self.assertEqual(self.final(layer,root)[:2],(True,[]))
    def test_apply_refusals_write_nothing(self):
        def no_judgement(case):
            layer,root,t=case.confirmed_box('nj');changes.change(layer,case.candidate(layer,root),apply=True);changes.change_list(layer);return layer,root,'no adopted proposal'
        def list_outdated(case):
            layer,root,t=case.confirmed_box('lo');case.judged(layer,root);changes.change(layer,case.candidate(layer,root,drafts=False,after='[owner] other'),apply=True);return layer,root,'changed after the last list'
        def before_gone(case):
            layer,root,t=case.confirmed_box('bg');case.judged(layer,root)
            q=root/case.persona_doc(root);m=package.load(root/'manifest.yaml')   # a proposal made on text that is no longer there: the document changed outside apply
            q.write_text(q.read_text().replace(acj.HYP,'[edited]',1));return layer,root,'differs from version'
        def no_thread(case):
            layer,root,t=case.confirmed_box('nt');case.judged(layer,root,thread=None);return layer,root,'no conversation id'
        def evidence_inside(case):
            layer,root,t=case.confirmed_box('ei');m=package.load(root/'manifest.yaml');p=case.persona_doc(root)
            m['evidence'].append({'id':'IN','kind':'hypothesis','source':'Documents/aipm_project/'+p,'source_sha256':sha(root/p),'scope':'synthetic'});write_yaml(root/'manifest.yaml',m)
            case.judged(layer,root);return layer,root,'points into a document'
        def base_not_last(case):
            layer,root,t=case.confirmed_box('bn');case.judged(layer,root);q=layer/'Context/aipm_changes/base_course_bn.yaml';b=package.load(q);b['version']=9;write_yaml(q,b);return layer,root,'not the last pushed version'
        def held_only(case):
            layer,root,t=case.confirmed_box('ho');case.judged(layer,root,quote='今回はレポートのみ');return layer,root,'no adopted proposal'
        for build in (no_judgement,list_outdated,before_gone,no_thread,evidence_inside,base_not_last,held_only):
            with self.subTest(case=build.__name__):
                layer,root,pattern=build(self);box=tr.state(root);ctx=tr.state(layer/'Context');stock=self.stock()
                for apply in (False,True):
                    with self.assertRaisesRegex(ValueError,pattern):applying.apply(layer,apply=apply,approval_ref='s')
                self.assertEqual(tr.state(root),box);self.assertEqual(tr.state(layer/'Context'),ctx);self.assertEqual(self.stock(),stock)
    def test_a_worse_final_or_an_interrupt_puts_everything_back(self):
        for name,patch in (('worse',lambda:mock.patch.object(validate_package,'validate',side_effect=self.worse_second())),('interrupt',lambda:mock.patch.object(applying,'_replace',side_effect=self.nth(1,KeyboardInterrupt)))):
            with self.subTest(case=name):
                layer,root,t=self.confirmed_box('w'+name[:2]);self.judged(layer,root);box=tr.state(root);ctx=tr.state(layer/'Context')
                with patch(),self.assertRaisesRegex(ValueError,'as before'):applying.apply(layer,apply=True,approval_ref='s')   # interrupt: Ctrl-C on writing the document
                self.assertEqual(tr.state(root),box);self.assertEqual(tr.state(layer/'Context'),ctx)
                self.assertTrue(applying.apply(layer,apply=True,approval_ref='s')['final']['pass'])   # and it can run again
    def test_a_revise_reply_reaches_the_version(self):
        layer,root,t=self.confirmed_box('rs');changes.change(layer,self.candidate(layer,root,drafts=False),apply=True);a=changes.change_list(layer)
        changes.judge_change(layer,a['digest'],'修正: 1 は「[owner] 修正した価値観」に直す',now(),'thread-synthetic')   # 修正 saves a newer list
        out=applying.apply(layer,apply=True,approval_ref='s');self.assertTrue(out['final']['pass'],out['final']['errors'])
        m=package.load(root/'manifest.yaml');rec=m['applies'][-1]['receipts']['persona'];r=package.load(layer/rec['source'])
        self.assertEqual((rec['list_digest'],r['question_id']),(a['digest'],a['digest']));self.assertIn('修正した価値観',(root/self.persona_doc(root)).read_text())
        self.assertEqual(m['stages'][-1]['started_at'],package.load(layer/a['list'])['created_at'])   # the event starts at the list the person answered
    def test_an_adoption_carried_to_a_later_list_reaches_the_version(self):
        layer,root,t=self.confirmed_box('ca');changes.change(layer,self.candidate(layer,root,drafts=False),apply=True);a=changes.change_list(layer)
        changes.judge_change(layer,a['digest'],'採用: 1',now(),'thread-synthetic')
        changes.change(layer,self.candidate(layer,root,drafts=False,target={'path':self.persona_doc(root),'locator':'基本情報'}),apply=True);b=changes.change_list(layer)
        changes.judge_change(layer,b['digest'],'今回はレポートのみ',now(),'thread-synthetic')   # the new one is held; the first stays adopted
        out=applying.apply(layer,apply=True,approval_ref='s');self.assertTrue(out['final']['pass'],out['final']['errors'])
        self.assertEqual(package.load(root/'manifest.yaml')['stages'][-1]['started_at'],package.load(layer/a['list'])['created_at'])
    def test_a_draft_that_breaks_a_cross_check_is_put_back(self):
        layer,root,t=self.confirmed_box('xc');self.judged(layer,root,drafts=True);box=tr.state(root);ctx=tr.state(layer/'Context')   # problem_map.yaml alone: customer_problem_map disagrees
        with self.assertRaisesRegex(ValueError,'problem maps disagree'):applying.apply(layer,apply=True,approval_ref='s')
        self.assertEqual(tr.state(root),box);self.assertEqual(tr.state(layer/'Context'),ctx)
    def worse_second(self):
        real=validate_package.validate;calls=[]
        def f(*a,**k):
            calls.append(1);res=real(*a,**k)
            return res if len(calls)==1 else {**res,'pass':False,'errors':res['errors']+[{'code':'E_SYNTH','path':'.','message':'synthetic'}]}
        return f
    def nth(self,n,exc):
        real=applying._replace.__wrapped__ if hasattr(applying._replace,'__wrapped__') else applying._replace;calls=[]
        def f(*a,**k):
            calls.append(1)
            if len(calls)==n:raise exc
            return real(*a,**k)
        return f

    # ---- push ----
    def applied(self,name):
        layer,root,target=self.confirmed_box(name);self.judged(layer,root);applying.apply(layer,apply=True,approval_ref='s');return layer,root,target
    def test_push_refusals_write_nothing(self):
        def stock_changed(case):
            layer,root,t=case.applied('sc');m=package.load(root/'manifest.yaml');r=next(r for r in m['records'] if r['archive_path'] and r['stage']=='story')
            q=case.repo/r['archive_path'];q.write_text(q.read_text()+'\nother checkout\n');return layer,root,'Stock changed after clone'
        def log_changed(case):
            layer,root,t=case.applied('lc');q=case.repo/t/package.APPLY_LOG;log=package.load(q);log['versions'][0]['approval_ref']='edited';write_yaml(q,log);return layer,root,'apply_log differs'
        def box_edited(case):
            layer,root,t=case.applied('be');q=root/case.persona_doc(root);q.write_text(q.read_text()+'\nlater\n');return layer,root,'changed after apply'
        def nothing(case):
            layer,root,t=case.confirmed_box('no');return layer,root,'no version to push'
        for build in (stock_changed,log_changed,box_edited,nothing):
            with self.subTest(case=build.__name__):
                layer,root,pattern=build(self);box=tr.state(root);stock=self.stock();ctx=tr.state(layer/'Context')
                for apply in (False,True):
                    with self.assertRaisesRegex(ValueError,pattern):applying.push(layer,apply=apply,approval_ref='s')
                self.assertEqual(tr.state(root),box);self.assertEqual(self.stock(),stock);self.assertEqual(tr.state(layer/'Context'),ctx)
    def test_a_failed_push_puts_the_stock_back(self):
        for name,patch in (('worse',lambda:mock.patch.object(validate_package,'validate',side_effect=self.worse_second())),('interrupt',lambda:mock.patch.object(applying,'_replace',side_effect=self.nth(2,KeyboardInterrupt)))):
            with self.subTest(case=name):
                layer,root,t=self.applied('p'+name[:2]);box=tr.state(root);stock=self.stock();ctx=tr.state(layer/'Context')
                with patch(),self.assertRaisesRegex(ValueError,'as before'):applying.push(layer,apply=True,approval_ref='s')
                self.assertEqual(self.stock(),stock);self.assertEqual(tr.state(root),box);self.assertEqual(tr.state(layer/'Context'),ctx)
                self.assertTrue(applying.push(layer,apply=True,approval_ref='s')['final']['pass'])   # the push can be done again
    def test_e_apply_five_and_six(self):
        layer,root,t=self.applied('e5');m=package.load(root/'manifest.yaml')
        m['applies'][0]['pushed']=False;write_yaml(root/'manifest.yaml',m);ok,errs,w=self.final(layer,root)
        self.assertTrue(any(c=='E_APPLY' and 'only the last version' in msg for c,p,msg in errs),errs)
        m['applies'][0]['pushed']=True;write_yaml(root/'manifest.yaml',m);self.assertEqual(self.final(layer,root)[:2],(True,[]))
        q=self.repo/t/package.APPLY_LOG;log=package.load(q);log['versions'][0]['approval_ref']='edited by hand';write_yaml(q,log)   # ⑥
        ok,errs,w=self.final(layer,root);self.assertIn(('E_APPLY','apply_log','the Stock apply_log must hold exactly the pushed versions'),errs)

    # ---- revert ----
    def test_revert_unpushed_goes_back_to_the_base_and_keeps_the_receipt(self):
        layer,root,t=self.confirmed_box('rv');box=tr.state(root);self.judged(layer,root)
        applying.apply(layer,apply=True,approval_ref='s');m=package.load(root/'manifest.yaml');rec=m['applies'][-1]['receipts']['persona']['source']
        with self.assertRaisesRegex(ValueError,'approval-ref'):applying.revert_unpushed(layer,apply=True)
        out=applying.revert_unpushed(layer,apply=True,approval_ref='chat:synthetic revert');self.assertTrue(out['reverted'])
        self.assertEqual({k:v[0] if isinstance(v,tuple) else v for k,v in tr.state(root).items()},{k:v[0] if isinstance(v,tuple) else v for k,v in box.items()})   # bytes as before the apply
        self.assertTrue((layer/rec).is_file())   # the receipt file stays (bound to no version)
        self.assertTrue(all(p['merge']['state']=='not_merged' for p in changes.proposals(layer)))
        self.assertEqual(self.final(layer,root)[:2],(True,[]))
        again=applying.apply(layer,apply=True,approval_ref='s');self.assertTrue(again['final']['pass'],again['final']['errors'])   # the same list again: other names
        m=package.load(root/'manifest.yaml');self.assertNotEqual(m['applies'][-1]['receipts']['persona']['source'],rec);self.assertTrue(m['applies'][-1]['backup'].endswith('_2'))
        with self.assertRaisesRegex(ValueError,'no unpushed'):(applying.push(layer,apply=True,approval_ref='s'),applying.revert_unpushed(layer,apply=True,approval_ref='s'))
    def test_revert_refuses_when_the_manifest_changed_after_apply(self):
        layer,root,t=self.confirmed_box('rm');self.judged(layer,root);applying.apply(layer,apply=True,approval_ref='s')
        m=package.load(root/'manifest.yaml');m['evidence'].append({'id':'LATER','kind':'hypothesis','source':'Context/course_input.yaml','source_sha256':sha(layer/'Context/course_input.yaml'),'scope':'added after apply'});write_yaml(root/'manifest.yaml',m)
        box=tr.state(root)
        with self.assertRaisesRegex(ValueError,'manifest changed after apply'):applying.revert_unpushed(layer,apply=True,approval_ref='s')
        self.assertEqual(tr.state(root),box)

import re
import test_migrate_layout as tml, test_migrate_sheets_nested as tmsn
class LegacyApply(unittest.TestCase):
    """The legacy (question_based) course: an archived nested_v1 box moved to sheets_v1 by migrate-sheets (its stage events
    and the init reply stay), registered as version 1, then a change of its persona document goes through apply and push."""
    setUp=tml.in_repository
    def tearDown(self):self.temp.cleanup()
    legacy_box=tmsn.MigrateSheetsNested.legacy_box
    def test_legacy_box_v1_to_v2(self):
        layer,root0,c=self.legacy_box('lg',internal=False);db=rf.db_path(self.registry)
        self.assertTrue(package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=db)['applied'])
        root=layer/'Sheets';package.register(layer,apply=True,approval_ref='chat:synthetic register');package.clone(layer)
        m=package.load(root/'manifest.yaml');persona=next(r['path'] for r in m['records'] if r.get('archive_path') and r['stage']=='persona' and r['path'].endswith('.md'))
        text=(root/persona).read_text();h=re.search(r'^## (.+)$',text,re.M);line=next(l for l in text[h.end():].splitlines() if l.strip() and not l.startswith('#'))
        write_yaml(layer/'Context/cand.yaml',{'source':{'kind':'conversation','ref':'synthetic'},'changes':[{'target':{'path':persona,'locator':h.group(1).strip()},'before':line,'after':line+'（v2 で直した）','reason':'synthetic'}]})
        changes.change(layer,'Context/cand.yaml',apply=True);lst=changes.change_list(layer);changes.judge_change(layer,lst['digest'],'OK',now(),'thread-synthetic')
        out=applying.apply(layer,apply=True,approval_ref='s');self.assertTrue(out['final']['pass'],out['final']['errors'])
        out=applying.push(layer,apply=True,approval_ref='s');self.assertTrue(out['final']['pass'],out['final']['errors'])
        m=package.load(root/'manifest.yaml');self.assertEqual(m['stages'][-1]['name'],'apply_v2');self.assertEqual([a['version'] for a in m['applies']],[1,2])
        r=next(r for r in m['records'] if r['path']==persona);self.assertEqual(r['applied_in'],2)
        self.assertEqual((self.registry/r['archive_path']).read_bytes() if (self.registry/r['archive_path']).is_file() else (self.repo/r['archive_path']).read_bytes(),(root/persona).read_bytes())

class CLI(arc.Base):
    def test_apply_push_from_the_command_line(self):
        layer,root,t=Apply.confirmed_box(self,'cli');Apply.judged(self,layer,root)
        code,out=tr.run_cli('apply','--layer',str(layer));self.assertEqual(code,0,out);self.assertFalse(out['apply'])
        code,out=tr.run_cli('apply','--layer',str(layer),'--apply','--approval-ref','s');self.assertEqual(code,0,out)
        code,out=tr.run_cli('apply','--layer',str(layer),'--push','--apply','--approval-ref','s');self.assertEqual(code,0,out);self.assertTrue(out['final']['pass'])
    persona_doc=Apply.persona_doc;candidate=Apply.candidate;prepare=Apply.prepare

if __name__=='__main__':unittest.main()
