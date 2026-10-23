"""pm- operations: package.py op / ops.py. Synthetic fixtures only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import hashlib, json, subprocess, tempfile, unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_integration as base
import test_registers as reg
package=base.package;METHOD=base.METHOD
sys.path.insert(0,str(METHOD))
import ops

def inventory(layer):
    return {str(p.relative_to(layer)):(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in sorted(Path(layer).rglob('*')) if p.is_file()}

class Base(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def layer(self,name='L'):
        layer=self.base/name;root,c=reg.registers_fixture(layer);return layer,root
    def inp(self,layer,name,data):base.write_yaml(layer/'Context'/name,data);return 'Context/'+name
    def rows(self,root,key,file=None):return package.load(root/'registers'/((file or key)+'.yaml'))[key]
    def receipt(self,layer,name='receipt_q.yaml',**over):
        r={'kind':'user_reported','actor':'actual_user','origin':'actual_user_reply','scope_id':'L-SYN-1','question_id':'Q1','received_at':'2026-10-23T10:00:00+09:00','question':'I1 をどう決めるか','answer':'synthetic'};r.update(over)
        return self.inp(layer,name,r)
    def decision(self,layer,name='decision.yaml',**over):
        r={'kind':'decision_record','issue_id':'I1','decided_by':'owner','decided_at':'2026-10-23','decision':'synthetic','scope_id':'L-SYN-1'};r.update(over)
        return self.inp(layer,name,r)

class Ops(Base):
    def test_trial_without_apply_changes_nothing(self):
        layer,root=self.layer();ref=self.inp(layer,'i.yaml',{'question':'どの利用者から始めるか','priority':'high'})
        before=inventory(layer);r=ops.run(layer,'issue.add',ref)
        self.assertEqual(before,inventory(layer));self.assertFalse(r['applied']);self.assertEqual(r['changed_ids'],['I2']);self.assertEqual(r['new_problems'],[])

    def test_reads_change_nothing(self):
        layer,root=self.layer();before=inventory(layer)
        m=ops.run(layer,'issue.map');self.assertEqual(m['open'],['I1']);self.assertEqual(m['roots'],['I1'])
        self.assertEqual(ops.run(layer,'hypothesis.impact')['targets'],[])
        self.assertIn('no_wbs',ops.run(layer,'todo.overdue'))
        self.assertEqual(before,inventory(layer))

    def test_apply_writes_and_keeps_registers_clean(self):
        layer,root=self.layer()
        r=ops.run(layer,'issue.add',self.inp(layer,'i.yaml',{'question':'どの利用者から始めるか','priority':'high'}),apply=True)
        self.assertTrue(r['applied']);row=self.rows(root,'issues')[-1]
        self.assertEqual((row['id'],row['status'],row['owner'],row['due']),('I2','open','[unknown]','undecided'))   # no guessed owner or due
        ops.run(layer,'issue.split',self.inp(layer,'s.yaml',{'parent':'I2','children':[{'question':'法人か個人か'},{'question':'初回の接点はどこか'}]}),apply=True)
        kids=[x for x in self.rows(root,'issues') if x.get('parent')=='I2'];self.assertEqual([k['id'] for k in kids],['I3','I4'])
        ops.run(layer,'issue.propose',self.inp(layer,'p.yaml',{'id':'I2','answer':'H2','validation_plan':'H1'}),apply=True)
        self.assertEqual(self.rows(root,'issues')[1]['status'],'open')
        ops.run(layer,'hypothesis.add',self.inp(layer,'h.yaml',{'kind':'problem','claim':'[hypothesis] 合成の課題','issue_id':'I2'}),apply=True)
        self.assertEqual(self.rows(root,'hypotheses')[-1]['status'],'unknown')
        ops.run(layer,'todo.add',self.inp(layer,'t.yaml',{'title':'候補を3件挙げる','source':'I2'}),apply=True)
        ops.run(layer,'todo.move',self.inp(layer,'m.yaml',{'id':'D1','status':'done'}),apply=True)
        t=self.rows(root,'todo')[0];self.assertEqual((t['owner'],t['status']),('[unknown]','done'))
        errs=[e for e in base.validate_package.validate(root,layer=layer)['errors'] if e['code']=='E_REGISTERS'];self.assertEqual(errs,[])

    def test_new_problem_refuses_and_layer_is_unchanged(self):
        layer,root=self.layer();ref=self.inp(layer,'bad.yaml',{'title':'x','wbs_id':'W99'});before=inventory(layer)
        r=ops.run(layer,'todo.add',ref,apply=True)
        self.assertFalse(r['applied']);self.assertTrue(any('W99' in p['message'] for p in r['new_problems']));self.assertEqual(before,inventory(layer))

    def test_one_fixed_one_new_is_still_refused(self):
        layer,root=self.layer()
        base.write_yaml(root/'registers/todo.yaml',{'todo':[{'id':'D1','title':'x','status':'todo','owner':'PM','wbs_id':'W98'}]})
        ref=self.inp(layer,'l.yaml',{'id':'D1','wbs_id':'W99'});before=inventory(layer);r=ops.run(layer,'todo.link',ref,apply=True)
        self.assertFalse(r['applied']);self.assertEqual(len(r['new_problems']),1);self.assertEqual(before,inventory(layer))   # W98 goes away, W99 appears: same count, still refused

    def test_writes_on_a_layer_right_after_init(self):
        layer=self.base/'init';layer.mkdir();(layer/'Context').mkdir()
        base.write_yaml(layer/'intent.yaml',{'scope_id':'L-OPS','scope_name':'ops','work_style':'aipm','aipm':{'date':'2026-10-23','registers':True},'goal':{'description':'synthetic'}})
        root=Path(package.init(layer)['package'])
        whole=base.validate_package.validate(root,layer=layer);self.assertFalse(whole['pass'])   # E_MISSING is normal right after init
        r=ops.run(layer,'issue.add',self.inp(layer,'i.yaml',{'question':'合成の問い'}),apply=True)
        self.assertTrue(r['applied'],r);self.assertEqual(self.rows(root,'issues')[-1]['question'],'合成の問い')

    def test_human_line(self):
        layer,root=self.layer()
        with self.assertRaises(ValueError):ops.run(layer,'issue.resolve',self.inp(layer,'r0.yaml',{'id':'I1','answer':'x','decided_by':'owner'}))   # evidence required
        with self.assertRaises(ValueError):ops.run(layer,'issue.resolve',self.inp(layer,'r1.yaml',{'id':'I1','answer':'x','evidence_refs':['H1'],'decided_by':'owner'}))   # H1 has no human judgement
        with self.assertRaises(ValueError):ops.run(layer,'issue.resolve',self.inp(layer,'r2.yaml',{'id':'I1','answer':'x','evidence_refs':['Context/none.yaml'],'decided_by':'owner'}))
        with self.assertRaises(ValueError):ops.run(layer,'issue.resolve',self.inp(layer,'r3.yaml',{'id':'I1','answer':'x','evidence_refs':[self.receipt(layer)],'decided_by':'ai_proxy'}))
        with self.assertRaises(ValueError):ops.run(layer,'issue.resolve',self.inp(layer,'r4.yaml',{'id':'I1','answer':'x','evidence_refs':[self.decision(layer,decided_by='decider')],'decided_by':'owner'}))   # record differs
        row=lambda i:{'id':i,'question':'q','status':'open','priority':'high','owner':'PM','due':'undecided'}
        base.write_yaml(root/'registers/issues.yaml',{'charter':{'change_conditions':['c'],'exit_conditions':['e']},'issues':[row('I1'),row('I2')]})
        with self.assertRaises(ValueError):ops.run(layer,'issue.resolve',self.inp(layer,'r6.yaml',{'id':'I2','answer':'x','evidence_refs':[self.receipt(layer)],'decided_by':'owner'}))   # the receipt is about I1
        with self.assertRaises(ValueError):ops.run(layer,'issue.resolve',self.inp(layer,'r7.yaml',{'id':'I2','answer':'x','evidence_refs':[self.decision(layer)],'decided_by':'owner'}))   # the record is about I1
        r=ops.run(layer,'issue.resolve',self.inp(layer,'r5.yaml',{'id':'I1','answer':'B 案','evidence_refs':[self.receipt(layer)],'decided_by':'owner'}),apply=True)
        self.assertTrue(r['applied'],r);self.assertEqual(self.rows(root,'issues')[0]['status'],'resolved')
        with self.assertRaises(ValueError):ops.run(layer,'issue.close',self.inp(layer,'c0.yaml',{'id':'I1','status':'not_needed','reason':'x'}))   # confirmed_ref required
        with self.assertRaises(ValueError):ops.run(layer,'issue.close',self.inp(layer,'c1.yaml',{'id':'I1','status':'not_needed','reason':'x','confirmed_ref':'Context/i.yaml'}))
        with self.assertRaises(ValueError):ops.run(layer,'issue.close',self.inp(layer,'c2.yaml',{'id':'I1','status':'resolved','reason':'x','confirmed_ref':self.decision(layer)}))
        with self.assertRaises(ValueError):ops.run(layer,'issue.close',self.inp(layer,'c4.yaml',{'id':'I1','status':'on_hold','reason':'x','review_at':'2026-11-01','confirmed_ref':self.decision(layer)}))   # I1 is resolved already
        with self.assertRaises(ValueError):ops.run(layer,'issue.resolve',self.inp(layer,'r8.yaml',{'id':'I1','answer':'x','evidence_refs':[self.receipt(layer)],'decided_by':'owner'}))
        r=ops.run(layer,'issue.close',self.inp(layer,'c3.yaml',{'id':'I2','status':'on_hold','reason':'先に予算','review_at':'2026-11-01','confirmed_ref':self.decision(layer,'d2.yaml',issue_id='I2')}),apply=True)
        row=self.rows(root,'issues')[1];self.assertTrue(r['applied']);self.assertEqual(row['status'],'on_hold');self.assertNotIn('confirmed_ref',row)   # evidence is input only
        with self.assertRaises(ValueError):ops.run(layer,'hypothesis.propose',self.inp(layer,'j.yaml',{'date':'2026-10-23','event':'m','judgements':[{'hypothesis_id':'H1','verdict':'supported','judged_by':'owner'}]}))
        with self.assertRaises(ValueError):ops.run(layer,'hypothesis.propose',self.inp(layer,'j2.yaml',{'date':'2026-10-23','event':'m','judged_by':'owner','judgements':[{'hypothesis_id':'H1','verdict':'supported'}]}))
        r=ops.run(layer,'hypothesis.propose',self.inp(layer,'j3.yaml',{'date':'2026-10-23','event':'m','judgements':[{'hypothesis_id':'H2','verdict':'not_supported'}]}),apply=True)
        h=self.rows(root,'hypotheses')[1];self.assertEqual((h['status'],h['judgements'][-1]['judged_by']),('unknown','ai_proxy'))
        imp=ops.run(layer,'hypothesis.impact');self.assertEqual(imp['targets'],['H2']);self.assertFalse(imp['impact'][0]['human_confirmed'])
        with self.assertRaises(ValueError):ops.run(layer,'hypothesis.add',self.inp(layer,'k.yaml',{'kind':'idea','claim':'x'}))
        with self.assertRaises(ValueError):ops.run(layer,'todo.add',self.inp(layer,'u.yaml',{'title':'x','assignee':'誰か'}))   # unknown key

    def test_trial_sees_the_same_sources_as_the_real_layer(self):
        layer=self.base/'repo/Flow/202610/2026-10-23/L';layer.parent.mkdir(parents=True);root,c=reg.registers_fixture(layer)   # under Flow: repo-relative sources are checked
        ref=self.inp(layer,'s.yaml',{'question':'出典の無い問い','sources':['nope/x.md']});before=inventory(layer)
        r=ops.run(layer,'issue.add',ref,apply=True)
        self.assertFalse(r['applied'],r);self.assertTrue(any('nope/x.md' in p['message'] for p in r['new_problems']));self.assertEqual(before,inventory(layer))

    def test_interrupted_trial_puts_the_file_back(self):
        layer,root=self.layer();ref=self.inp(layer,'i.yaml',{'question':'中断される問い'});before=inventory(layer)
        real=ops._registers_problems;calls=[]
        def stop(l):
            calls.append(1)
            if len(calls)==2:raise KeyboardInterrupt
            return real(l)
        ops._registers_problems=stop
        try:
            with self.assertRaises(KeyboardInterrupt):ops.run(layer,'issue.add',ref,apply=True)
        finally:ops._registers_problems=real
        self.assertEqual(before,inventory(layer))

    def test_stops(self):
        legacy=self.base/'legacy';root,c=base.fixture(legacy)   # AIPM without registers
        self.assertEqual(ops.run(legacy,'issue.map')['route'],'unselected')
        plain=self.base/'plain';plain.mkdir();base.write_yaml(plain/'intent.yaml',{'scope_id':'L-PLAIN','goal':{'description':'x'}})
        before=inventory(plain);r=ops.run(plain,'todo.add','Context/none.yaml',apply=True)
        self.assertEqual(r['route'],'unselected');self.assertEqual(before,inventory(plain))
        held=self.base/'held';held.mkdir();base.write_yaml(held/'intent.yaml',{'scope_id':'L-HELD','work_style':'other','goal':{'description':'x'}})
        r=ops.run(held,'issue.add',None,apply=True);self.assertEqual((r['route'],r['pass']),('held',False))
        layer,root=self.layer('missing');(root/'registers/todo.yaml').unlink()
        r=ops.run(layer,'todo.add',None,apply=True);self.assertEqual(r['route'],'held');self.assertIn('registers files missing',r['reason'])
        with self.assertRaises(ValueError):ops.run(self.layer('unknown')[0],'issue.delete')

    def test_cli(self):
        layer,root=self.layer();ref=self.inp(layer,'i.yaml',{'question':'CLI の問い'})
        run=lambda *a:json.loads(subprocess.run([sys.executable,'-B',str(METHOD/'package.py'),'op','--layer',str(layer),*a],capture_output=True,text=True).stdout)
        self.assertEqual(run('--name','check')['route'],'selected')
        self.assertFalse(run('--name','issue.add','--input',ref)['applied'])
        self.assertTrue(run('--name','issue.add','--input',ref,'--apply')['applied'])
        self.assertFalse(run()['pass'])   # --name is required
        bad=run('--name','issue.resolve','--input',self.inp(layer,'r.yaml',{'id':'I1','answer':'x','evidence_refs':['H1'],'decided_by':'owner'}))
        self.assertFalse(bad['pass']);self.assertIn('judge',bad['error'])

class OpsRest(Base):
    """pm-capture / pm-today / pm-persona / pm-story never write."""
    def unsave(self,root):
        m=package.load(root/'manifest.yaml')
        for r in m['records']:
            if r.get('stage') in ('persona','problem','solution','story'):r['status']='generated';r['archive_path']=None
        base.write_yaml(root/'manifest.yaml',m)

    def test_capture(self):
        layer,root=self.layer();(layer/'Context/notes.md').write_text('合成の会議メモ。H2 は当てはまらなかった。')
        n=self.inp(layer,'n.yaml',{'notes':'Context/notes.md'})
        b=self.inp(layer,'b.yaml',{'judgements':{'date':'2026-10-23','event':'m','judgements':[{'hypothesis_id':'H2','verdict':'not_supported'}]},
                                   'issues':[{'question':'次にだれに聞くか'}],'todo':[{'title':'x','wbs_id':'W99'},{'title':'y','assignee':'誰か'}]})
        before=inventory(layer)
        ctx=ops.run(layer,'capture.context',n);self.assertIn('H2',ctx['notes']['text']);self.assertEqual([h['id'] for h in ctx['undecided_hypotheses']],['H1','H2'])
        chk=ops.run(layer,'capture.check',b)['candidates']
        self.assertEqual([c['ok'] for c in chk],[True,True,False,False]);self.assertIn('W99',chk[2]['new_problems'][0]['message']);self.assertIn('error',chk[3])
        self.assertEqual(before,inventory(layer))
        with self.assertRaises(ValueError):ops.run(layer,'capture.context',self.inp(layer,'m.yaml',{'notes':'Context/none.md'}))

    def test_today_order(self):
        layer,root=self.layer();before_empty=ops.run(layer,'today.pick')
        self.assertIsNone(before_empty['pick'])
        base.write_yaml(root/'registers/todo.yaml',{'todo':[{'id':'D1','title':'進行中','status':'doing','owner':'PM'},{'id':'D2','title':'遅れ','status':'todo','owner':'PM','due':'2026-10-01'}]})
        base.write_yaml(root/'registers/issues.yaml',{'charter':{'change_conditions':['c'],'exit_conditions':['e']},'issues':[{'id':'I1','question':'q','status':'open','priority':'high','owner':'PM','due':'2026-10-25'}]})
        ref=self.inp(layer,'d.yaml',{'today':'2026-10-23'});before=inventory(layer);r=ops.run(layer,'today.pick',ref)
        self.assertEqual((r['pick']['id'],r['reason']),('D2','期限を過ぎた ToDo'))
        self.assertEqual([c['reason'] for c in r['candidates']],['期限を過ぎた ToDo','7日以内が期限の論点','進行中の ToDo'])
        self.assertEqual(before,inventory(layer))

    def test_revise_returns_scope_and_never_writes(self):
        layer,root=self.layer();held=ops.run(layer,'persona.revise')
        self.assertEqual(held['route'],'held');self.assertTrue(held['saved'])   # saved documents are not revised in place
        self.unsave(root);ref=self.inp(layer,'r.yaml',{'hypothesis_ids':['H1'],'reason':'合成の観測'});before=inventory(layer)
        r=ops.run(layer,'persona.revise',ref)
        self.assertEqual({t['stage'] for t in r['targets']},{'persona','problem'});self.assertEqual({t['stage'] for t in r['downstream']},{'solution','story'})
        self.assertIn('その場で書き換えない',r['how_to_revise'])
        s=ops.run(layer,'story.revise');self.assertEqual({t['stage'] for t in s['targets']},{'solution','story'});self.assertEqual(s['downstream'],[])
        self.assertEqual(before,inventory(layer))

    def test_revise_lists_the_persons_checks_to_redo(self):
        layer,root=self.layer();self.unsave(root)
        m=package.load(root/'manifest.yaml')
        m['human_responses']={'persona':{'source':'Context/receipt.yaml','target_path':'x.md'},'story':{'source':'Context/r2.yaml','target_path':'y.md'}}
        for st in m['stages']:
            if st.get('name')=='problem':st['checkpoint_actor']='actual_user'
        base.write_yaml(root/'manifest.yaml',m)
        p=ops.run(layer,'persona.revise');self.assertEqual({c['stage'] for c in p['human_checks_to_redo']},{'persona','story','problem'})
        s=ops.run(layer,'story.revise');self.assertEqual({c['stage'] for c in s['human_checks_to_redo']},{'story'})

    def test_today_input_and_rows_without_id(self):
        layer,root=self.layer()
        with self.assertRaises(ValueError):ops.run(layer,'today.pick',self.inp(layer,'bad.yaml',{'today':'tomorrow'}))
        base.write_yaml(root/'registers/todo.yaml',{'todo':[{'title':'id なし','status':'doing','owner':'PM'}]})
        self.assertIsNone(ops.run(layer,'today.pick')['pick'])

    def test_revise_stops(self):
        plain=self.base/'plain';plain.mkdir();base.write_yaml(plain/'intent.yaml',{'scope_id':'L-PLAIN','goal':{'description':'x'}})
        self.assertEqual(ops.run(plain,'story.revise')['route'],'unselected')
        layer=self.base/'init';layer.mkdir();(layer/'Context').mkdir()
        base.write_yaml(layer/'intent.yaml',{'scope_id':'L-OPS','scope_name':'ops','work_style':'aipm','aipm':{'date':'2026-10-23','registers':True},'goal':{'description':'synthetic'}})
        package.init(layer);r=ops.run(layer,'persona.revise')
        self.assertEqual(r['route'],'held');self.assertIn('manifest',r['reason'])
        self.assertEqual(ops.run(plain,'today.pick')['route'],'unselected')

class PmInit(Base):
    """init.status only guides a midway Layer; it never writes."""
    def midway(self,name='mid',**extra):
        L=self.base.resolve()/name;(L/'Context').mkdir(parents=True);(L/'Documents').mkdir()
        base.write_yaml(L/'intent.yaml',dict({'scope_id':'L-MID','scope_name':'mid','goal':{'description':'synthetic midway'}},**extra))
        base.write_yaml(L/'backlog.yaml',{'tasks':[{'id':'T001','status':'completed','output':'Documents/T001.md'},{'id':'T002','status':'pending'}]})
        (L/'Documents/T001.md').write_text('# synthetic research\n');(L/'Context/facts.md').write_text('synthetic\n')
        return L
    def status(self,L):
        before=inventory(L);r=ops.run(L,'init.status');self.assertEqual(before,inventory(L));return r

    def test_states(self):
        rec=ops._recommendation()
        L=self.midway();r=self.status(L);self.assertEqual(r['state'],'unselected');self.assertIn('/01-collection',r['next'])
        ref={'path':'Context/facts.md','sha256':rec.digest((L/'Context/facts.md').read_bytes())}
        rec.assess(L,{'version':1,'scope_id':'L-MID','conditions':{k:{'value':'yes','reason':'synthetic','evidence_refs':[ref]} for k in rec.CONDITIONS},'recommendation_reason':'synthetic'},'normal',apply=True)
        r=self.status(L);self.assertEqual(r['state'],'question_pending');self.assertTrue(r['question'])
        st=rec.Store(L).state
        reply=lambda ans:{'kind':'user_reported','actor':'actual_user','origin':'actual_user_reply','scope_id':'L-MID','source_thread_id':'SYNTHETIC-ONLY','received_at':rec.timestamp(),'question_id':st['question']['id'],'target_path':st['snapshot'],'target_sha256':st['snapshot_sha256'],'answer':ans,'choice':rec.answer_choice(ans)}
        D=self.midway('declined');rec.assess(D,{'version':1,'scope_id':'L-MID','conditions':{k:{'value':'yes','reason':'synthetic','evidence_refs':[{'path':'Context/facts.md','sha256':ref['sha256']}]} for k in rec.CONDITIONS},'recommendation_reason':'synthetic'},'normal',apply=True)
        sd=rec.Store(D).state
        rec.respond(D,dict(reply('通常方式で進める'),question_id=sd['question']['id'],target_path=sd['snapshot'],target_sha256=sd['snapshot_sha256']),apply=True)
        self.assertEqual(self.status(D)['state'],'declined')
        rec.respond(L,reply('AIPM方式で進める'),apply=True)
        r=self.status(L);self.assertEqual(r['state'],'selected_not_initialized')
        it=package.load(L/'intent.yaml');it['aipm']={'date':'2026-10-23','course':'document_based/single_persona','registers':True};base.write_yaml(L/'intent.yaml',it)
        package.init(L);r=self.status(L)
        self.assertEqual((r['state'],r['course'],r['import_candidates']),('initialized_no_tasks','document_based/single_persona',['Documents/T001.md']));self.assertIn('/02-inception',r['next'])
        bl=package.load(L/'backlog.yaml');bl['tasks'].append({'id':'T003','status':'pending','wbs_id':'W1'});base.write_yaml(L/'backlog.yaml',bl)
        self.assertEqual(self.status(L)['state'],'running')

    def test_legacy_course_name(self):
        S=self.midway('legacy',addons=[{'addon_id':'aipm','source':'bundled','addon_version':'2.0'}],aipm={'date':'2026-10-23','registers':True});package.init(S)
        r=self.status(S);self.assertEqual(r['course'],package.LEGACY_COURSE);self.assertNotIn('None',r['next'])

    def test_stops(self):
        H=self.midway('held',work_style='other');self.assertEqual(self.status(H)['state'],'held')
        sys.path[:0]=[str(METHOD.parent/'ai-plc/scripts'),str(METHOD.parent/'ai-plc/scripts/tests')]   # .claude/skills/ai-plc/scripts
        from test_plc_addon import make_case
        d=self.base.resolve()/'cases';d.mkdir();C=make_case(d)[0]   # a real case binding that declares no exclusive group
        r=self.status(C);self.assertEqual(r['state'],'other_addon',r);self.assertIn('宣言なし',r['reason'])

    def test_stale_corrupt_and_paths(self):
        rec=ops._recommendation();L=self.midway('stale')
        ref={'path':'Context/facts.md','sha256':rec.digest((L/'Context/facts.md').read_bytes())}
        rec.assess(L,{'version':1,'scope_id':'L-MID','conditions':{k:{'value':'yes','reason':'synthetic','evidence_refs':[ref]} for k in rec.CONDITIONS},'recommendation_reason':'synthetic'},'normal',apply=True)
        (L/'Context/facts.md').write_text('changed\n');self.assertEqual(self.status(L)['state'],'stale_recommendation')
        S=self.midway('sel',addons=[{'addon_id':'aipm','source':'bundled','addon_version':'2.0'}],aipm={'date':'2026-10-23','registers':True});package.init(S)
        base.write_yaml(S/'backlog.yaml',{'tasks':[{'id':'T1','status':'completed','output':['../outside.md','/abs/x.md','Documents/T001.md']},
                                                  {'id':'T2','status':'completed','output':'Documents/aipm_project_old/x.md'}]})
        r=self.status(S);self.assertEqual(r['state'],'initialized_no_tasks');self.assertEqual(r['import_candidates'],['Documents/T001.md'])   # prefix-only names are not the package
        base.write_yaml(S/'backlog.yaml',{'tasks':[{'id':'T3','status':'pending','output':'./Documents/aipm_project/x.md'}]})
        self.assertEqual(self.status(S)['state'],'running')
        (S/'backlog.yaml').write_text('tasks: [unclosed');self.assertEqual(self.status(S)['state'],'held')
        base.write_yaml(S/'backlog.yaml',['not','a','map']);self.assertEqual(self.status(S)['state'],'held')

if __name__=='__main__':unittest.main()
