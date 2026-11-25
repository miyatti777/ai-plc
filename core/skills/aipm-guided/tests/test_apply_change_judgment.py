"""change proposals, the ripple (inputs, stage_order, id_mention) with drafts on the id_mention hits only,
the numbered list (list_<digest>) and judge-change (the five replies, bound to the saved list). Nothing here writes the box:
the 19 documents, the registers and the manifest keep their bytes. The person's words in these tests are synthetic.
Synthetic repository, Stock and Registry only; no real box is touched."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import unittest
from unittest import mock
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent));sys.path.insert(0,str(HERE))
import package, changes, ops
import test_integration as ti, test_init_and_reset as tr
import test_apply_register_clone as arc
write_yaml,sha=ti.write_yaml,ti.sha
VALUE_HEAD='価値観・重視する要素'
HYP='[hypothesis] synthetic structure; actual user effect unknown'
PROBLEM='02_課題定義/problem_map.yaml'
from datetime import datetime, timedelta, timezone
def now():return datetime.now(timezone.utc).isoformat()   # a synthetic reply, said after the list was shown

class Changes(arc.Base):
    def cloned(self,name):
        layer,root,target=self.registered(name);package.clone(layer);return layer,root
    def persona_doc(self,root):
        m=package.load(root/'manifest.yaml')
        return next(r['path'] for r in m['records'] if r.get('archive_path') and r['stage']=='persona' and '## '+VALUE_HEAD in (root/r['path']).read_text())
    def candidate(self,layer,root,drafts=True,**over):
        main={'target':{'path':self.persona_doc(root),'locator':VALUE_HEAD},'before':HYP,'after':'[owner] 家族との時間を重視する（PR1 に関わる）','reason':'synthetic: 本人の言葉で価値観を直す'}
        main.update(over)
        items=[main]
        if drafts:items.append({'target':{'path':PROBLEM,'locator':'problem_map.problems'},'before':"summary: '[hypothesis] synthetic problem'",'after':"summary: '[hypothesis] synthetic problem（P001 の価値観の改訂に合わせる）'",'reason':'synthetic draft','ripple_of':1})
        write_yaml(layer/'Context/cand.yaml',{'source':{'kind':'conversation','ref':'synthetic: 本人の言葉'},'changes':items});return 'Context/cand.yaml'
    def unchanged(self,layer,root):
        return tr.state(root),tr.state(self.repo/'Stock'),{k:v for k,v in tr.state(layer/'Context').items() if not k.startswith('aipm_changes/')}

    # ---- change ----
    def test_dry_run_lists_the_ripple_and_writes_nothing(self):
        layer,root=self.cloned('dr');inp=self.candidate(layer,root);before=tr.state(layer/'Context');pkg=tr.state(root)
        out=changes.change(layer,inp);self.assertFalse(out['apply'])
        self.assertEqual(tr.state(layer/'Context'),before);self.assertEqual(tr.state(root),pkg)
        main,draft=out['proposals'];self.assertEqual((main['judgment'],main['merge'],main['base_version']),({'state':'undecided'},{'state':'not_merged'},1))
        imp={x['path']:x for x in main['impact']}
        stages={x['stage'] for x in main['impact'] if 'stage_order' in x['reason']};self.assertEqual(stages,{'problem','solution','story'})   # every later document stage
        self.assertTrue(all(x['reason']==['id_mention'] for x in main['impact'] if x['stage']=='persona'))   # the same stage only when it names the ID
        self.assertEqual(set(imp[PROBLEM]['reason']),{'stage_order','id_mention'});self.assertEqual(imp[PROBLEM]['ids'],['PR1']);self.assertEqual(imp[PROBLEM]['draft'],'drafted')
        self.assertEqual(imp['02_課題定義/problem_todo.md']['reason'],['stage_order']);self.assertEqual(imp['02_課題定義/problem_todo.md']['draft'],'to_check_stage')   # no ID: only listed
        self.assertEqual(imp['03_ソリューションマップ/solution_map.yaml']['draft'],'to_check')   # an id_mention hit with no draft yet
        self.assertEqual(draft['origin'],{'ripple_of':main['id']});self.assertEqual(main['drafts'],[draft['id']]);self.assertEqual(draft['impact'],[])
    def test_apply_writes_only_the_proposals_and_keeps_the_box(self):
        layer,root=self.cloned('ap');inp=self.candidate(layer,root);pkg,stock,ctx=self.unchanged(layer,root);m0=sha(root/'manifest.yaml')
        out=changes.change(layer,inp,apply=True)
        self.assertEqual(len(out['written']),2);self.assertTrue(all(w.startswith('Context/aipm_changes/C-') for w in out['written']))
        self.assertEqual(self.unchanged(layer,root),(pkg,stock,ctx));self.assertEqual(sha(root/'manifest.yaml'),m0)   # box, registers, manifest, Stock: same bytes
        p=package.load(layer/out['written'][0]);self.assertEqual(p['judgment'],{'state':'undecided'})   # the AI never judges
        again=changes.change(layer,inp,apply=True);self.assertNotEqual(again['written'],out['written'])   # new ids, never over an earlier proposal
    def test_inputs_ripple(self):
        layer,root=self.cloned('in');m=package.load(root/'manifest.yaml');persona=self.persona_doc(root)
        r=next(r for r in m['records'] if r['path']=='04_ストーリーマップ/story_map_todo.md');r['inputs'].append('Documents/aipm_project/'+persona);write_yaml(root/'manifest.yaml',m)
        out=changes.change(layer,self.candidate(layer,root,drafts=False))
        imp={x['path']:x for x in out['proposals'][0]['impact']};self.assertIn('inputs',imp['04_ストーリーマップ/story_map_todo.md']['reason'])
    def test_change_refusals_write_nothing(self):
        def not_cloned(case):
            layer,root,target=case.registered('nc');return layer,root,case.candidate(layer,root),'run clone first'
        def before_missing(case):
            layer,root=case.cloned('bm');return layer,root,case.candidate(layer,root,before='not in the document'),'before is not in'
        def locator_missing(case):
            layer,root=case.cloned('lm');return layer,root,case.candidate(layer,root,target={'path':case.persona_doc(root),'locator':'無い見出し'}),'not found'
        def twice_in_section(case):
            layer,root=case.cloned('tw');return layer,root,case.candidate(layer,root,target={'path':case.persona_doc(root),'locator':'Synthetic structural document'}),'occurs 6 times'
        def init_draft(case):
            layer,root=case.cloned('id');m=package.load(root/'manifest.yaml');init=next(r['path'] for r in m['records'] if not r.get('archive_path'))
            return layer,root,case.candidate(layer,root,drafts=False,target={'path':init,'locator':'x'}),'not a document of version'
        def same_after(case):
            layer,root=case.cloned('sa');return layer,root,case.candidate(layer,root,after=HYP),'differs from before'
        def box_changed(case):
            layer,root=case.cloned('bc');q=root/case.persona_doc(root);q.write_text(q.read_text()+'\nedited\n');return layer,root,case.candidate(layer,root),'differs from version'
        def draft_off_the_hits(case):
            layer,root=case.cloned('do');inp=case.candidate(layer,root);d=package.load(layer/inp);d['changes'][1]['target']={'path':'02_課題定義/problem_todo.md','locator':'フェーズ別の主要課題'};d['changes'][1]['before']=HYP;write_yaml(layer/inp,d);return layer,root,inp,'only made on an id_mention hit'
        def draft_on_a_judgement(case):
            layer,root=case.cloned('dj');inp=case.candidate(layer,root);d=package.load(layer/inp);d['changes'][1]['target']['locator']='problem_map.problems.summary';d['changes'][1]['before']="'[hypothesis] synthetic problem'";d['changes'][1]['after']="'x'";write_yaml(layer/inp,d)
            mock.patch.object(changes,'JUDGEMENT_KEYS',{'summary'}).start();case.addCleanup(mock.patch.stopall);return layer,root,inp,'a judgement the person decides'
        def no_source(case):
            layer,root=case.cloned('ns');inp=case.candidate(layer,root);d=package.load(layer/inp);d['source']={'kind':'rumour','ref':'x'};write_yaml(layer/inp,d);return layer,root,inp,'source.kind'
        for build in (not_cloned,before_missing,locator_missing,twice_in_section,init_draft,same_after,box_changed,draft_off_the_hits,draft_on_a_judgement,no_source):
            with self.subTest(case=build.__name__):
                layer,root,inp,pattern=build(self);ctx=tr.state(layer/'Context');pkg=tr.state(root)
                for apply in (False,True):
                    with self.assertRaisesRegex(ValueError,pattern):changes.change(layer,inp,apply=apply)
                self.assertEqual(tr.state(layer/'Context'),ctx);self.assertEqual(tr.state(root),pkg)
    def test_yaml_locator_reaches_a_nested_key(self):
        layer,root=self.cloned('yl');inp=self.candidate(layer,root,drafts=False,target={'path':PROBLEM,'locator':'problem_map.problems.summary'},before="'[hypothesis] synthetic problem'",after="'[owner] synthetic problem v2'")
        out=changes.change(layer,inp);self.assertEqual(out['proposals'][0]['target']['locator'],'problem_map.problems.summary')
        inp=self.candidate(layer,root,drafts=False,target={'path':PROBLEM,'locator':'problem_map.persona_ref'},before="'[hypothesis] synthetic problem'",after='x')
        with self.assertRaisesRegex(ValueError,'before is not in'):changes.change(layer,inp)   # the text is outside that key's block

    # ---- list and judge-change ----
    def listed(self,name):
        layer,root=self.cloned(name);changes.change(layer,self.candidate(layer,root),apply=True);out=changes.change_list(layer);return layer,root,out
    def judged(self,layer):return {p['id']:p['judgment'] for p in changes.proposals(layer)}
    def test_list_is_saved_once_and_shows_the_digest(self):
        layer,root,out=self.listed('ls');self.assertTrue(out['written']);self.assertEqual([r['n'] for r in out['rows']],[1,2]);self.assertEqual(out['digest_short'],out['digest'][:12])
        self.assertEqual(out['rows'][1]['ripple_of'],out['rows'][0]['id'])
        again=changes.change_list(layer);self.assertFalse(again['written']);self.assertEqual(again['digest'],out['digest'])
    def test_adopt_then_revise(self):
        layer,root,out=self.listed('ar');ids=[r['id'] for r in out['rows']];pkg=tr.state(root)
        res=changes.judge_change(layer,out['digest_short'],'採用: 1',now(),'thread-synthetic')
        j=self.judged(layer);self.assertEqual(j[ids[0]]['state'],'adopted');self.assertEqual(j[ids[0]]['quote'],'採用: 1');self.assertEqual(j[ids[1]],{'state':'undecided'})
        self.assertEqual(j[ids[0]]['list_digest'],out['digest']);self.assertEqual(j[ids[0]]['thread'],'thread-synthetic')
        res=changes.judge_change(layer,out['digest'],'修正: 2 は「P001 の価値観に合わせた課題」に直す',now())   # a second reply to the same list
        self.assertEqual(res['reply'],'revise');self.assertNotEqual(res['new_list']['digest'],out['digest'])
        p=next(p for p in changes.proposals(layer) if p['id']==ids[1]);self.assertEqual(p['after'],'P001 の価値観に合わせた課題')   # the words inside 「」;self.assertEqual(p['judgment']['state'],'adopted')
        self.assertTrue((layer/'Context/aipm_changes'/('list_'+out['digest']+'.yaml')).is_file())   # the earlier list stays
        with self.assertRaisesRegex(ValueError,'changed after this list'):changes.judge_change(layer,out['digest'],'採用: 1',now())   # the old list no longer judges
        self.assertEqual(tr.state(root),pkg)
        saved=package.load(layer/res['new_list']['list'].replace('\\','/'));self.assertEqual([e['id'] for e in saved['entries']],ids)
    def test_the_five_replies(self):
        for n,(quote,want) in enumerate((('OK（全件反映）',['adopted','adopted']),('OK',['adopted','adopted']),('採用: 2',['undecided','adopted']),('採用：１、２',['adopted','adopted']),('今回はレポートのみ',['held','held']),('差し戻し',['rejected','rejected']))):
            with self.subTest(quote=quote):
                layer,root,out=self.listed('r'+str(n));changes.judge_change(layer,out['digest'],quote,now())
                j=self.judged(layer);self.assertEqual([j[r['id']]['state'] for r in out['rows']],want)
    def test_send_back_leaves_the_list_and_ok_does_not_bring_it_back(self):
        layer,root,out=self.listed('sb');changes.judge_change(layer,out['digest'],'採用: 1',now());changes.judge_change(layer,out['digest'],'差し戻し',now())
        ids=[r['id'] for r in out['rows']];j=self.judged(layer);self.assertEqual([j[i]['state'] for i in ids],['adopted','rejected'])
        merge={p['id']:p['merge'] for p in changes.proposals(layer)};self.assertEqual(merge[ids[1]],{'state':'not_applicable'})
        new=changes.change_list(layer);self.assertEqual([r['id'] for r in new['rows']],[ids[0]])   # the rejected one is out of the list
        changes.judge_change(layer,new['digest'],'OK',now());self.assertEqual(self.judged(layer)[ids[1]]['state'],'rejected')
        with self.assertRaisesRegex(ValueError,'changed after this list'):changes.judge_change(layer,out['digest'],'OK',now())   # the old list no longer judges
    def test_revise_follows_the_new_text_in_the_ripple(self):
        layer,root,out=self.listed('rr');ids=[r['id'] for r in out['rows']]
        p0=next(p for p in changes.proposals(layer) if p['id']==ids[0]);self.assertNotIn('ST1',{i for h in p0['impact'] for i in h['ids']})
        changes.judge_change(layer,out['digest'],'修正: 1 は「[owner] 家族との時間を重視する（ST1 に関わる）」に直す',now())
        p1=next(p for p in changes.proposals(layer) if p['id']==ids[0]);self.assertEqual(p1['after'],'[owner] 家族との時間を重視する（ST1 に関わる）')
        self.assertIn('ST1',{i for h in p1['impact'] for i in h['ids']});self.assertEqual(p1['drafts'],[ids[1]]);self.assertEqual(p1['ids'],['PR1','ST1'])   # PR1 (before) stays
        self.assertEqual(changes.parse_reply('修正: 1 は「A」と「B」に直す',2)[2],'「A」と「B」に直す')   # two pairs: the words as they were said
    def test_yaml_locator_matches_direct_children_once(self):
        lines=['top:\n','  child:\n','    target: deep\n','  target: direct\n','items:\n','- name: a\n','  value: 1\n','- name: b\n','  value: 2\n']
        self.assertEqual(changes._yaml_region(lines,'top.target'),(3,4))   # the direct child, not the deeper key
        self.assertEqual(changes._yaml_region(lines,'items.value'),'ambiguous')   # the same key in every list item
        self.assertIsNone(changes._yaml_region(lines,'top.missing'))
        self.assertEqual(changes._md_region(['# A\n','```\n','# A\n','```\n'],'A'),(0,4))   # a heading in a code block is not one
    def test_report_only_keeps_earlier_decisions(self):
        layer,root,out=self.listed('ro');changes.judge_change(layer,out['digest'],'採用: 1',now());changes.judge_change(layer,out['digest'],'今回はレポートのみ',now())
        j=self.judged(layer);self.assertEqual([j[r['id']]['state'] for r in out['rows']],['adopted','held'])
    def test_judge_refusals_write_nothing(self):
        cases=(('いいね','not one of the five'),('それで','not one of the five'),('採用','not one of the five'),('採用: 3','not in the list'),('採用: 1,1','twice'),('修正: 1 は '+HYP,'equals before'))
        layer,root,out=self.listed('jr');ctx=tr.state(layer/'Context')
        for quote,pattern in cases:
            with self.subTest(quote=quote):
                with self.assertRaisesRegex(ValueError,pattern):changes.judge_change(layer,out['digest'],quote,now())
                self.assertEqual(tr.state(layer/'Context'),ctx)
        for args,pattern in (((out['digest'],'採用: 1','2000-01-01T00:00:00+09:00'),'older than the list'),((out['digest'],'採用: 1','2026-10-28T00:00:00'),'offset'),((out['digest'],'採用: 1',(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()),'future'),(('0'*12,'採用: 1',now()),'no single saved list'),((out['digest'],'  ',now()),'--quote')):
            with self.subTest(args=args):
                with self.assertRaisesRegex(ValueError,pattern):changes.judge_change(layer,*args)
                self.assertEqual(tr.state(layer/'Context'),ctx)
        changes.change(layer,self.candidate(layer,root,drafts=False),apply=True);ctx=tr.state(layer/'Context')   # a new proposal after the list
        with self.assertRaisesRegex(ValueError,'changed after this list'):changes.judge_change(layer,out['digest'],'採用: 1',now())
        self.assertEqual(tr.state(layer/'Context'),ctx)

    # ---- pm-persona / pm-story ----
    def test_revise_on_a_box_with_versions_points_to_change(self):
        layer,root=self.cloned('pv');out=ops.run(layer,'persona.revise')
        self.assertNotEqual(out.get('route'),'held');self.assertIn('package.py clone',out['how_to_revise'])
        layer2,root2,target=self.archived_before_versions('pn');out=ops.run(layer2,'persona.revise')
        self.assertEqual(out['route'],'held');self.assertIn('register',out['reason'])

class CLI(arc.Base):
    def test_change_list_and_judge_from_the_command_line(self):
        layer,root,target=self.registered('cli');package.clone(layer);inp=Changes.candidate(self,layer,root,drafts=False)
        code,out=tr.run_cli('change','--layer',str(layer),'--input',inp);self.assertEqual(code,0,out);self.assertFalse(out['apply'])
        code,out=tr.run_cli('change','--layer',str(layer),'--input',inp,'--apply');self.assertEqual(code,0,out)
        code,lst=tr.run_cli('change-list','--layer',str(layer));self.assertEqual(code,0,lst)
        code,out=tr.run_cli('judge-change','--layer',str(layer),'--list',lst['digest_short'],'--quote','いいね','--at',now());self.assertEqual(code,1)
        code,out=tr.run_cli('judge-change','--layer',str(layer),'--list',lst['digest_short'],'--quote','採用: 1','--at',now());self.assertEqual(code,0,out);self.assertEqual(out['state'],'adopted')
    persona_doc=Changes.persona_doc

if __name__=='__main__':unittest.main()
