import sys
sys.dont_write_bytecode=True
from pathlib import Path
import copy, hashlib, importlib.util, json, tempfile, unittest, yaml
from datetime import datetime, timezone
METHOD=Path(__file__).resolve().parents[1]
ROOT=METHOD.parents[2]
sys.path.insert(0,str(METHOD))
import package, validate_package, rollback
def now(): return datetime.now(timezone.utc).isoformat()
def write_yaml(p,d): p.write_text(yaml.safe_dump(d,allow_unicode=True,sort_keys=False))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def models(c):
    """Manually authored, synthetic, source-shaped minimum; no user observations."""
    problem = {'id': 'PR1', 'summary': '[hypothesis] synthetic problem', 'causes': ['[hypothesis] synthetic cause'], 'impact': '[unknown] synthetic impact', 'linked_actions': ['A101'], 'occurs_in_phases': ['PH1']}
    story = 'As a synthetic user, I want a synthetic result, So that the fixture can test references'
    init = {k: '[hypothesis] synthetic' for k in c['documents'][-2]['schema']['fields']}
    init.update(program_id='synthetic_pilot', project_id='aipm_guided', participant_name='Synthetic fixture', flow_dir='aipm_guided', flow_base=c['flow_rel'], stock_base=c['stock_project_rel'], share_repo='disabled', share_local_dir='disabled')
    return {'write_init_yaml': init, 'generate_experience_yaml': {'persona': {'id': 'P001', 'name': 'Synthetic fixture', 'profile': {'age_gender': '[unknown]', 'occupation': '[unknown]', 'company_context': '[unknown]'}, 'behaviors': ['[hypothesis] synthetic activity'], 'values': ['[hypothesis] synthetic value']}, 'experience_map': {'phases': [{'id': 'PH1', 'name': 'Synthetic phase', 'description': '[hypothesis] synthetic context', 'actions': [{'id': 'A101', 'label': 'Synthetic action', 'notes': ['[hypothesis] synthetic only']}]}]}, 'opportunity_hypotheses_mapping': {}, 'numbering_policy': ['prefix: P=Persona, PH=Phase, A=Action']}, 'generate_integrated_experience_map': {'integrated_experience_map': {'meta': {'created_date': '2026-10-07', 'project': 'aipm_guided', 'phase': 'Discovery - ペルソナ作成', 'description': 'Synthetic fixture'}, 'personas': {'user': {'id': 'P001', 'name': 'Synthetic fixture', 'role': '[unknown]', 'focus': '[hypothesis] synthetic'}}, 'integrated_phases': [{'id': 'IPH1', 'name': 'Synthetic phase', 'description': '[hypothesis] synthetic', 'persona_mapping': {'P001': 'PH1: Synthetic phase'}, 'opportunity_hypotheses': []}], 'validation_priorities': {'critical': [], 'high': []}}}, 'export_customer_problem_map_yaml': {'customer_problem_map': {'persona_ref': 'P001', 'phases': [{'id': 'PH1', 'actions': [{'id': 'A101', 'thoughts': ['[hypothesis] synthetic'], 'emotions': ['[unknown]'], 'issues': ['PR1']}]}], 'problems': [copy.deepcopy(problem)], 'numbering_policy': [{'prefix': 'PH=Phase, A=Action, PR=Problem'}]}}, 'export_problem_map_yaml': {'problem_map': {'persona_ref': 'P001', 'problems': [problem], 'numbering_policy': [{'prefix': 'PR=Problem, A=Action'}]}}, 'export_solution_map_yaml': {'solution_map': {'persona_ref': 'P001', 'problems': ['PR1'], 'phases': [{'id': 'PH1', 'name': 'Synthetic phase', 'solutions': [{'id': 'SL1', 'label': '[hypothesis] synthetic solution', 'links': ['PR1', 'A101']}]}], 'numbering_policy': [{'prefix': 'SL=Solution, PH=Phase'}]}}, 'export_story_map_yaml': {'story_map': {'persona_ref': 'P001', 'problem_refs': ['PR1'], 'links': [{'chain': ['A101', 'PR1', 'SL1', 'ST1']}], 'stories': [{'id': 'ST1', 'summary': story, 'acceptance': ['[hypothesis] synthetic acceptance'], 'release': 'MVP', 'links': ['PR1', 'SL1', 'A101']}], 'releases': [{'name': 'MVP', 'includes': ['ST1']}], 'numbering_policy': [{'prefix': 'ST=Story'}]}}, 'export_viewer_integrated_yaml_final': {'integrated_story_map': {'meta': {'project_name': 'Synthetic fixture'}, 'version_definitions': {'order': ['MVP']}, 'story_map_structure': {'activities': [{'id': 'ACT-CASE', 'name': 'Synthetic activity'}], 'backbones': [{'id': 'BB-CASE', 'name': 'Synthetic backbone', 'sequence': 1, 'activity_id': 'ACT-CASE'}]}, 'display_order': {'backbones': ['BB-CASE']}, 'personas_stories': {'P001': {'name': 'Synthetic fixture', 'stories': [{'id': 'ST-001', 'story': story, 'backbone_id': 'BB-CASE', 'version': 'MVP', 'status': 'TODO', 'backbone_x_version_sort': 1}]}}, 'cross_persona_stories': [], 'story_mapping': {'ST-001': {'backbone_id': 'BB-CASE', 'sequence': 1}}}}}

def fixture(layer,scope='L-SYN-1',project='alpha',pid='P001'):
    layer.mkdir();(layer/'Context').mkdir()
    write_yaml(layer/'intent.yaml',{'scope_id':scope,'scope_name':project,'owner':'Synthetic fixture','mode':'direct','work_style':'aipm','aipm':{'project_id':project,'persona_id':pid,'name_slug':'synthetic','date':'2026-10-07'},'goal':{'description':'Synthetic integration, not user evidence'}})
    (layer/'Context/case.yaml').write_text('kind: hypothesis\nclaim: synthetic only\n')
    result=package.init(layer);c=result['contract'];root=Path(result['package'])
    data=models(c)
    def change(x):
        if isinstance(x,str):return x.replace('P001',pid)
        if isinstance(x,list):return [change(v) for v in x]
        if isinstance(x,dict):return {change(k):change(v) for k,v in x.items()}
        return x
    data=change(data);b=c['bindings'];data['write_init_yaml'].update(program_id=b['program_id'],project_id=b['project_id'],flow_dir=b['flow_dir'])
    evidence=[{'id':'F1','kind':'hypothesis','source':'Context/case.yaml','source_sha256':sha(layer/'Context/case.yaml'),'scope':'synthetic only'}]
    records=[];stages=[]
    for name in c['course']:
        start=now()
        if name=='validation':
            write_yaml(root/'validation_record.yaml',{'scope_id':scope,'before_solution':True,'hypotheses':[{'id':'H1','kind':'hypothesis','claim':'synthetic structure','method':'validator','success':'pass','falsification':'fail','result':'unknown','scope':'synthetic'}],'evidence_refs':['F1'],'actual_new_user_response':None,'limits':['No human result']})
        for e in c['documents']:
            stage='init' if e.get('side') else {'01':'persona','02':'problem','03':'solution','04':'story'}[e['path'][:2]]
            if stage!=name:continue
            assert sha(METHOD/e['raw_template'])==e['template_sha256']
            relative=(c['stock_project_rel'] if e.get('side')=='stock_project' else c['flow_rel'])+'/'+e['path'];q=root/relative;q.parent.mkdir(parents=True,exist_ok=True)
            if e['kind']=='yaml':write_yaml(q,data[e['step']])
            else:
                graph='flowchart TD\n '+pid+' --> PH1\n PH1 --> A101\n A101 --> PR1\n PR1 --> SL1\n SL1 --> ST1'
                body='# Synthetic fixture\n\n'
                for n,h in enumerate(e['required_headings']):body+='## '+h+'\n\n'+('```mermaid\n'+graph+'\n```\n' if e['kind']=='mermaid' and n==0 else '[hypothesis] synthetic only\n')+'\n'
                if e['kind']=='mermaid' and not e['required_headings']:body+='```mermaid\n'+graph+'\n```\n'
                q.write_text(body)
            records.append({'path':relative,'source_step':e['step'],'template_sha256':e['template_sha256'],'version':'v1','branch':'question_based/single_persona','stage':name,'status':'validated_local_final' if e.get('side') else 'generated','requires_human':False,'human_state':'not_required','inputs':['Context/case.yaml'],'evidence_refs':['F1'],'decision':'synthetic structural fixture','sha256':sha(q),'generated_mtime_ns':q.stat().st_mtime_ns,'archive_path':None,'archive_sha256':None})
        manifest={'scope_id':scope,'source_commit':c['reviewed_commit'],'contract_version':c['version'],'branch':'question_based/single_persona','flow_rel':c['flow_rel'],'stock_project_rel':c['stock_project_rel'],'id_mapping':c['id_mapping'],'completion_claim':'local_trial_only; new human readability/effectiveness unknown','stages':stages,'evidence':evidence,'records':records}
        if name=='archive':
            write_yaml(root/'manifest.yaml',manifest)
            result=validate_package.validate(root,phase='prearchive',layer=layer)
            if not result['pass']:raise AssertionError(result['errors'])
            for r in records:
                if r['stage']=='init':continue
                rel=r['path'][len(c['flow_rel'])+1:];dest=c['stock_project_rel']+'/documents/'+rel;q=root/dest;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes((root/r['path']).read_bytes());r.update(status='archived_local_final',archive_path=dest,archive_sha256=sha(q))
        stages.append({'name':name,'started_at':start,'finished_at':now(),'checkpoint_actor':'auto_decision','checkpoint_status':'accepted_local','evidence_refs':['F1']})
    manifest['stages']=stages;manifest['records']=records;write_yaml(root/'manifest.yaml',manifest)
    return root,c

class Integration(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_legacy_modes_no_write(self):
        for mode in ['direct','platform_builder']:
            for flag in [None,'absent']:
                layer=self.base/(mode+str(flag));layer.mkdir();d={'scope_id':'L-TEST','scope_name':'test','mode':mode}
                if flag is None:d['work_style']=None
                write_yaml(layer/'intent.yaml',d);before=(layer/'intent.yaml').read_bytes();self.assertEqual(package.init(layer),{'route':'legacy','created':False});self.assertEqual((layer/'intent.yaml').read_bytes(),before);self.assertEqual(list(layer.iterdir()),[layer/'intent.yaml'])
    def test_quote_does_not_activate_and_invalid_rejected(self):
        layer=self.base/'q';layer.mkdir();write_yaml(layer/'intent.yaml',{'goal':{'description':'work_style: aipm mentioned as historical quote'},'mode':'direct'})
        self.assertFalse(package.select(layer));write_yaml(layer/'intent.yaml',{'work_style':True})
        with self.assertRaises(ValueError):package.init(layer)
    def test_two_layers_generalized_full_pipeline(self):
        for n in [1,2]:
            layer=self.base/str(n);root,c=fixture(layer,'L-SYN-'+str(n),'project'+str(n),'P00'+str(n))
            check=validate_package.validate(root,layer=layer);self.assertTrue(check['pass'],check);self.assertEqual(check['checked_documents'],19)
            self.assertEqual(len([x for x in package.load(root/'manifest.yaml')['records'] if x['archive_path']]),17)
            self.assertFalse(package.init(layer)['created'])
    def test_default_hook_bytes_and_stage_bindings(self):
        # Portable bindings; dirty-byte preservation is checked against the fresh
        # implementation manifest, outside this distributable regression test.
        # Activation markers are gone; each Stage keeps one activation paragraph.
        for stage in ('01-collection', '02-inception', '03-construction', '04-operation'):
            current=(METHOD.parent/'ai-plc'/stage/'SKILL.md').read_text()
            optins=[p for p in current.split('\n\n') if p.startswith('**選択した方式だけ読む')]
            self.assertEqual(len(optins),1,stage);optin=optins[0]
            self.assertIn('`work_style: aipm`',optin);self.assertIn('../../aipm-guided/SKILL.md',optin)
        collection=METHOD.parent/'ai-plc/01-collection'
        text=(collection/'SKILL.md').read_text()
        self.assertIn('references/aipm-recommendation.md',text)
        self.assertTrue((collection/'recommendation.py').is_file())
        self.assertTrue((collection/'references/aipm-recommendation.md').is_file())
    def test_actual_checkpoint_target_bound_and_changed_target_rejected(self):
        layer=self.base/'response';root,c=fixture(layer);m=package.load(root/'manifest.yaml');record=next(x for x in m['records'] if x['stage']=='persona');target=root/record['path'];target_rel=str(target.relative_to(layer));response=layer/'Context/answer.yaml'
        write_yaml(response,{'kind':'user_reported','actor':'actual_user','origin':'actual_user_reply','scope_id':c['scope_id'],'stage':'persona','answer':'agree','target_path':target_rel,'target_sha256':sha(target),'question_id':'synthetic-question-only','source_thread_id':'synthetic-thread-only','received_at':m['stages'][1]['finished_at']})
        m['evidence'].append({'id':'FA','kind':'user_reported','source':'Context/answer.yaml','source_sha256':sha(response),'scope':'synthetic typed response only'})
        m['human_responses']={'persona':{'source':'Context/answer.yaml','source_sha256':sha(response),'answer':'agree','target_path':target_rel,'target_sha256':sha(target)}};m['checkpoint_targets']={'persona':sha(target)};m['stages'][1].update(checkpoint_actor='actual_user',checkpoint_status='confirmed_actual')
        r=next(x for x in m['records'] if x['stage']=='persona');r.update(requires_human=True,human_state='confirmed_actual');write_yaml(root/'manifest.yaml',m)
        result=validate_package.validate(root,layer=layer);self.assertTrue(result['pass'],result)
        target.write_text('Synthetic checkpoint target v2');result=validate_package.validate(root,layer=layer);self.assertFalse(result['pass']);self.assertIn('E_CHECKPOINT',[e['code'] for e in result['errors']])
    def test_hypothesis_note_cannot_be_actual_response(self):
        layer=self.base/'false-person';root,c=fixture(layer);m=package.load(root/'manifest.yaml');note=layer/'Context/case.yaml';m['human_responses']={'persona':{'source':'Context/case.yaml','source_sha256':sha(note),'answer':'synthetic only','target_path':'Context/case.yaml','target_sha256':sha(note)}};m['checkpoint_targets']={'persona':sha(note)};m['stages'][1].update(checkpoint_actor='actual_user',checkpoint_status='confirmed_actual');m['records'][0].update(requires_human=True,human_state='confirmed_actual');write_yaml(root/'manifest.yaml',m)
        result=validate_package.validate(root,layer=layer);self.assertFalse(result['pass']);self.assertIn('E_CHECKPOINT',[e['code'] for e in result['errors']])
    def test_validation_checkpoint_immutable_question_snapshot(self):
        import os
        layer=self.base/'validation-reply';root,c=fixture(layer);m=package.load(root/'manifest.yaml');v=package.load(root/'validation_record.yaml');q=root/'validation_checkpoint.yaml';write_yaml(q,{k:value for k,value in v.items() if k!='actual_new_user_response'})
        event=next(e for e in m['stages'] if e['name']=='validation');time_ns=int(datetime.fromisoformat(event['started_at']).timestamp()*1e9);os.utime(q,ns=(time_ns,time_ns))
        rel=str(q.relative_to(layer));receipt=layer/'Context/validation_reply.yaml';write_yaml(receipt,{'kind':'user_reported','actor':'actual_user','origin':'actual_user_reply','scope_id':c['scope_id'],'stage':'validation','answer':'agree','target_path':rel,'target_sha256':sha(q),'question_id':'synthetic-validation-question','source_thread_id':'synthetic-thread','received_at':event['finished_at']})
        m['human_responses']={'validation':{'source':'Context/validation_reply.yaml','source_sha256':sha(receipt),'answer':'agree','target_path':rel,'target_sha256':sha(q)}};m['checkpoint_targets']={'validation':sha(q)};m['evidence'].append({'id':'FVR','kind':'user_reported','source':'Context/validation_reply.yaml','source_sha256':sha(receipt),'scope':'synthetic only'});event.update(checkpoint_actor='actual_user',checkpoint_status='confirmed_actual');write_yaml(root/'manifest.yaml',m)
        v['actual_new_user_response']='agree';old=(root/'validation_record.yaml').stat().st_mtime_ns;write_yaml(root/'validation_record.yaml',v);os.utime(root/'validation_record.yaml',ns=(old,old))
        result=validate_package.validate(root,layer=layer);self.assertTrue(result['pass'],result)
        v['hypotheses'][0]['claim']='new question';write_yaml(root/'validation_record.yaml',v);os.utime(root/'validation_record.yaml',ns=(old,old));result=validate_package.validate(root,layer=layer);self.assertFalse(result['pass'])
    def test_reject_missing_format_reference_order_checkpoint_archive_boundary(self):
        mutations=['missing','format','reference','order','checkpoint','archive','boundary','evidence_symlink','contract_tamper','fake_response','diagram_prose']
        for case in mutations:
            with self.subTest(case=case):
                layer=self.base/case;root,c=fixture(layer);flow=root/c['flow_rel'];story=flow/'04_ストーリーマップ/story_map.yaml';m=root/'manifest.yaml'
                if case=='missing':story.unlink()
                elif case=='format':d=package.load(story);d['story_map']['stories'][0]['acceptance']='bad';write_yaml(story,d)
                elif case=='reference':d=package.load(story);d['story_map']['stories'][0]['links'].append('PR999');write_yaml(story,d)
                elif case=='order':d=package.load(m);d['stages'][3],d['stages'][4]=d['stages'][4],d['stages'][3];write_yaml(m,d)
                elif case=='checkpoint':d=package.load(m);d['records'][0].update(requires_human=True,human_state='pending');write_yaml(m,d)
                elif case=='archive':q=root/c['stock_project_rel']/'documents/04_ストーリーマップ/story_map.yaml';q.write_text('changed')
                elif case=='boundary':story.unlink();story.symlink_to(layer/'Context/case.yaml')
                elif case=='evidence_symlink':q=layer/'Context/case.yaml';text=q.read_text();q.unlink();outside=self.base/'outside';outside.write_text(text);q.symlink_to(outside)
                elif case=='contract_tamper':d=package.load(root/'format_contract.yaml');d['documents']=[];write_yaml(root/'format_contract.yaml',d)
                elif case=='fake_response':d=package.load(root/'validation_record.yaml');d['actual_new_user_response']='invented';write_yaml(root/'validation_record.yaml',d)
                elif case=='diagram_prose':q=flow/'04_ストーリーマップ/story_map_mermaid.md';q.write_text('P001 PH1 A101 PR1 SL1 ST1\n```mermaid\nflowchart TD\n X --> Y\n```\n')
                try:result=validate_package.validate(root,layer=layer)
                except ValueError:result={'pass':False}
                self.assertFalse(result['pass'])
    def test_traversal_symlink_duplicate_keys_and_existing_project(self):
        layer=self.base/'bad';layer.mkdir();write_yaml(layer/'intent.yaml',{'scope_id':'L-X','scope_name':'x','work_style':'aipm','aipm':{'project_id':'../bad'}})
        with self.assertRaises(ValueError):package.init(layer)
        write_yaml(layer/'intent.yaml',{'scope_id':'L-X','scope_name':'x','work_style':'aipm'});(layer/'Documents').symlink_to(self.base)
        with self.assertRaises(ValueError):package.init(layer)
        (layer/'Documents').unlink();(layer/'Documents/aipm_project').mkdir(parents=True)
        with self.assertRaises(ValueError):package.init(layer)
        (layer/'intent.yaml').write_text('work_style: aipm\nwork_style: null\n')
        with self.assertRaises(ValueError):package.select(layer)
    def rollback_fixture(self):
        root=self.base/'repo';root.mkdir();(root/'.claude/skills/ai-plc/01-collection').mkdir(parents=True);(root/'.claude/skills/aipm-guided').mkdir();p=root/'.claude/skills/ai-plc/01-collection/SKILL.md';before='existing dirty writer data\n';p.write_text(before+'our marker\n');n=root/'.claude/skills/aipm-guided/SKILL.md';n.write_text('new skill\n');entries=[{'path':str(p.relative_to(root)),'before_text':before,'before_sha256':hashlib.sha256(before.encode()).hexdigest(),'after_sha256':sha(p)},{'path':str(n.relative_to(root)),'before_text':None,'after_sha256':sha(n)}];return root,p,n,{'files':entries}
    def test_rollback_exact_dirty_baseline(self):
        root,p,n,m=self.rollback_fixture();self.assertTrue(rollback.rollback(root,m,root/'retired')['dry_run']);self.assertTrue(rollback.rollback(root,m,root/'retired',True)['pass']);self.assertEqual(p.read_text(),'existing dirty writer data\n');self.assertFalse(n.exists());self.assertEqual((root/'retired'/n.relative_to(root)).read_text(),'new skill\n')
    def test_rollback_other_writer_refuses_all_writes(self):
        root,p,n,m=self.rollback_fixture();p.write_text(p.read_text()+'other writer\n');before=p.read_bytes()
        with self.assertRaises(ValueError):rollback.rollback(root,m,root/'retired',True)
        self.assertEqual(p.read_bytes(),before);self.assertTrue(n.exists());self.assertFalse((root/'retired').exists())
    def test_rollback_unknown_new_file_refuses(self):
        root,p,n,m=self.rollback_fixture();(n.parent/'unknown.txt').write_text('another writer')
        with self.assertRaises(ValueError):rollback.rollback(root,m,root/'retired',True)
        self.assertTrue(n.exists());self.assertIn('our marker',p.read_text())

class LegacyReceipt(unittest.TestCase):
    """Receipt binds a legacy (question-based) stage when it is closed, before the next stage starts."""
    ORDER=['init','persona','problem','validation','solution','story']
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def cut(self,name,upto,human=True):
        layer=self.base/name;root,c=fixture(layer);m=package.load(root/'manifest.yaml');keep=self.ORDER[:self.ORDER.index(upto)+1]
        for r in list(m['records']):
            if r['stage'] not in keep:(root/r['path']).unlink(missing_ok=True);m['records'].remove(r);continue
            if r['stage']=='init':continue
            r.update(status='generated',archive_path=None,archive_sha256=None)
            if r['stage']==upto and human:r.update(requires_human=True,human_state='pending')
        for q in (root/c['stock_project_rel']/'documents').rglob('*'):   # the archive copies go; the init folders stay
            if q.is_file():q.unlink()
        m['stages']=[e for e in m['stages'] if e['name'] in keep]
        if 'validation' not in keep:(root/'validation_record.yaml').unlink(missing_ok=True)
        write_yaml(root/'manifest.yaml',m);return layer,root,c
    def ask(self,layer,name,stage,**over):
        d={'stage':stage,'question':'Synthetic question about '+stage,'answer':'Synthetic reply only','question_id':'LEG-'+name,'source_thread_id':'SYNTHETIC-THREAD','answered_at':now()};d.update(over)
        d={k:v for k,v in d.items() if v is not None};write_yaml(layer/'Context'/(name+'.yaml'),d);return 'Context/'+name+'.yaml'
    def stage_errors(self,root,layer,stage,own):
        errs=validate_package.validate(root,phase='prearchive',layer=layer)['errors']
        return [e for e in errs if e['code']=='E_CHECKPOINT' and (e['path'] in (stage,'stages.'+stage) or e['path'] in own)]
    def test_solution_is_bound_and_its_checkpoint_errors_clear(self):
        layer,root,c=self.cut('sol','solution');m=package.load(root/'manifest.yaml');own={r['path'] for r in m['records'] if r['stage']=='solution'}
        self.assertTrue(self.stage_errors(root,layer,'solution',own))   # pending records are unresolved before the reply
        r=package.receipt(layer,self.ask(layer,'s1','solution'));self.assertTrue(r['bound']);self.assertIsNone(r.get('errors'))
        m=package.load(root/'manifest.yaml');rec=package.load(layer/r['receipt'])
        self.assertEqual(m['human_responses']['solution']['target_sha256'],rec['target_sha256']);self.assertEqual(m['checkpoint_targets']['solution'],rec['target_sha256'])
        self.assertIn('USR-solution',[e['id'] for e in m['evidence']]);self.assertTrue(rec['target_path'].endswith('solution_map_todo.md'))
        self.assertEqual((m['stages'][-1]['checkpoint_actor'],m['stages'][-1]['checkpoint_status']),('actual_user','confirmed_actual'))
        self.assertTrue(all(x['human_state']=='confirmed_actual' for x in m['records'] if x['stage']=='solution'))
        self.assertEqual(self.stage_errors(root,layer,'solution',own),[])
    def test_persona_and_validation_are_bound(self):
        layer,root,c=self.cut('per','persona');r=package.receipt(layer,self.ask(layer,'p1','persona'));self.assertTrue(r['bound']);self.assertIsNone(r.get('errors'))
        self.assertIn('persona',package.load(root/'manifest.yaml')['human_responses'])
        layer,root,c=self.cut('val','validation',human=False);v=package.load(root/'validation_record.yaml')
        untouched=lambda:untouched_files(root)
        before=untouched()
        with self.assertRaises(ValueError):package.receipt(layer,self.ask(layer,'v0','validation'))   # no checkpoint snapshot yet
        self.assertEqual(before,untouched())
        write_yaml(root/'validation_checkpoint.yaml',{k:x for k,x in v.items() if k!='actual_new_user_response'})
        r=package.receipt(layer,self.ask(layer,'v1','validation',answered_at=now()));self.assertTrue(r['bound']);self.assertIsNone(r.get('errors'))
        self.assertEqual(package.load(root/'validation_record.yaml')['actual_new_user_response'],'Synthetic reply only')
        self.assertEqual(self.stage_errors(root,layer,'validation',set()),[])
        self.assertFalse(any(e['path']=='validation.actual_new_user_response' for e in validate_package.validate(root,phase='prearchive',layer=layer)['errors']))
    def test_refusals_write_nothing(self):
        layer,root,c=self.cut('ref','story');m=package.load(root/'manifest.yaml')
        cases=[self.ask(layer,'a','solution'),   # the next stage (story) has already started
               self.ask(layer,'b','story',target_path=c['package_root']+'/'+[x['path'] for x in m['records'] if x['stage']=='solution'][0]),   # another stage's document
               self.ask(layer,'c','story',answered_at=None),self.ask(layer,'d','story',answered_at='2000-01-01T00:00:00+00:00')]
        for inp in cases:
            before=untouched_files(root)
            with self.assertRaises(ValueError):package.receipt(layer,inp)
            self.assertEqual(before,untouched_files(root));self.assertFalse(any(q.name.startswith('receipt_') for q in (layer/'Context').iterdir()))
        r=package.receipt(layer,self.ask(layer,'e','story',target_path=c['package_root']+'/'+[x['path'] for x in m['records'] if x['stage']=='story' and x['source_step']=='export_story_map_yaml'][0]))
        self.assertTrue(r['bound']);self.assertTrue(r['target_path'].endswith('story_map.yaml'))
        before=untouched_files(root)
        with self.assertRaises(ValueError):package.receipt(layer,self.ask(layer,'f','story'))   # already answered
        self.assertEqual(before,untouched_files(root))

    def test_unrelated_errors_and_rollback(self):
        """Only errors caused by the missing later stages are allowed; a failed binding is rolled back."""
        import os
        from unittest import mock
        def refused(layer,root,inp):
            before=untouched_files(root)
            with self.assertRaises(ValueError):package.receipt(layer,inp)
            self.assertEqual(before,untouched_files(root))
        layer,root,c=self.cut('gap','solution');m=package.load(root/'manifest.yaml');m['stages']=[e for e in m['stages'] if e['name']!='validation'];write_yaml(root/'manifest.yaml',m)
        refused(layer,root,self.ask(layer,'g','solution'))   # a missing earlier stage is not "later"
        layer,root,c=self.cut('rec','solution');m=package.load(root/'manifest.yaml')
        for r in [r for r in m['records'] if r['stage']=='problem']:m['records'].remove(r)
        write_yaml(root/'manifest.yaml',m);refused(layer,root,self.ask(layer,'r','solution'))   # an earlier stage's records are missing
        layer,root,c=self.cut('anr','solution');v=package.load(root/'validation_record.yaml');v['actual_new_user_response']='written by AI';write_yaml(root/'validation_record.yaml',v)
        refused(layer,root,self.ask(layer,'n','solution'))   # an unbound reply in validation_record is not this stage's error
        layer,root,c=self.cut('scope','persona');m=package.load(root/'manifest.yaml');m['scope_id']='L-OTHER';write_yaml(root/'manifest.yaml',m)
        refused(layer,root,self.ask(layer,'sc','persona'))   # a wrong manifest scope is not "validation not yet"
        layer,root,c=self.cut('rb','solution');mp=root/'manifest.yaml';vp=root/'validation_record.yaml'
        before={q:(q.read_bytes(),q.stat().st_mtime_ns) for q in (mp,vp)}
        real=validate_package.validate;calls=[]
        def broken(*a,**k):
            calls.append(1);res=real(*a,**k)
            return {**res,'pass':False,'errors':res['errors']+[{'code':'E_SYNTH','path':'x','message':'injected'}]} if len(calls)==2 else res
        with mock.patch.object(validate_package,'validate',broken):r=package.receipt(layer,self.ask(layer,'rb','solution'))
        self.assertFalse(r['pass']);self.assertIn('E_SYNTH',[e['code'] for e in r['errors']])
        self.assertEqual(before,{q:(q.read_bytes(),q.stat().st_mtime_ns) for q in (mp,vp)});self.assertFalse((layer/r['receipt']).exists())

def untouched_files(root):
    return {str(q):q.read_bytes() for q in [root/'manifest.yaml',root/'validation_record.yaml'] if q.is_file()}

class CourseIntegration(unittest.TestCase):
    """Local structural fixtures, with real fixed method docs as source inputs; no human evidence."""
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def prepare(self,name='new',course='document_based/single_persona',pending=False,reuse=False):
        layer=self.base/name;layer.mkdir();(layer/'Context').mkdir()
        write_yaml(layer/'intent.yaml',{'scope_id':'L-COURSE','scope_name':'course_fixture','work_style':'aipm','owner':'Synthetic fixture','goal':{'description':'Synthetic structural case, no user evidence'},'aipm':{'project_id':'course_fixture','persona_id':'P001','name_slug':'synthetic','date':'2026-10-13','course':course}})
        c=package.build_contract(layer);data=models(c)
        graph='flowchart TD\n P001 --> PH1\n PH1 --> A101\n A101 --> PR1\n PR1 --> SL1\n SL1 --> ST1'
        for e in c['documents']:
            if e['kind']!='yaml':
                text='# Synthetic structural document\n\n'
                for n,h in enumerate(e['required_headings']):text+='## '+h+'\n\n'+('```mermaid\n'+graph+'\n```\n' if e['kind']=='mermaid' and n==0 else '[hypothesis] synthetic structure; actual user effect unknown\n')+'\n'
                if e['kind']=='mermaid' and not e['required_headings']:text+='```mermaid\n'+graph+'\n```\n'
                data[e['step']]=text
        data['write_init_yaml'].update(program_id=c['bindings']['program_id'],project_id=c['bindings']['project_id'],participant_name=c['bindings']['participant_name'],flow_dir=c['bindings']['flow_dir'],flow_base=c['flow_rel'],stock_base=c['stock_project_rel'])
        sources=[{'id':'M'+str(n),'domain':'method_source','path':p,'sha256':sha(METHOD/p)} for n,p in enumerate(['source/3_discovery/03_ソリューションマップ.md','source/3_discovery/04_ストーリーマップ.md'],1)]
        packet={'version':1,'scope_id':'L-COURSE','solution':{'kind':'hypothesis','value':'[hypothesis] synthetic solution'},'sources':sources,'drafts':data,'reuse':{},'gaps':[{'kind':'unknown','reason':'Human effectiveness has not been measured','requires_user':False}],'decisions':{key:{'state':'pending' if pending and key=='persona' else 'not_required','reason':'Only reversible structural drafts; no factual/human decision claimed','scope':'reversible_draft_only','source_ids':['M1','M2'],**({'question':'Which actual persona should be used?'} if pending and key=='persona' else {})} for key in ['persona','validation']},'claims':[{'kind':'observed','source_ids':['M1','M2'],'claim':'fixed method documents were read, not actual user observations'}],'validation_record':{'scope_id':'L-COURSE','before_solution':False,'hypotheses':[{'id':'H1','kind':'hypothesis','claim':'Synthetic structure','method':'local validator','success':'valid references','falsification':'invalid references','result':'unknown','scope':'structural only'}],'evidence_refs':['M1','M2'],'actual_new_user_response':None,'limits':['No actual human evidence']}}
        if reuse:
            doc=layer/'Context/existing_problem.md';doc.write_text(data['generate_problem_statement']);packet['sources'].append({'id':'D1','domain':'layer','path':'Context/existing_problem.md','sha256':sha(doc)});packet['reuse']={'generate_problem_statement':'D1'};packet['drafts'].pop('generate_problem_statement')
        write_yaml(layer/'Context/course_input.yaml',packet)
        return layer,c,packet
    def draft(self,layer):
        result=package.batch_draft(layer,'Context/course_input.yaml');return Path(result['package'])
    def mutate(self,root,fn):
        m=package.load(root/'manifest.yaml');fn(m);write_yaml(root/'manifest.yaml',m)
        self.assertFalse(validate_package.validate(root,phase='prearchive',layer=root.parents[1])['pass'])
    def test_both_new_courses_generate_19_and_archive(self):
        for n,course in enumerate(['solution_based/single_persona','document_based/single_persona']):
            with self.subTest(course=course):
                layer,c,packet=self.prepare(str(n),course);root=self.draft(layer)
                result=validate_package.validate(root,phase='prearchive',layer=layer);self.assertTrue(result['pass'],result['errors']);self.assertEqual(result['checked_documents'],19)
                final=package.archive_course(layer);self.assertTrue(final['pass'],final['errors']);m=package.load(root/'manifest.yaml');self.assertEqual(m['branch'],course)
                self.assertEqual([e['name'] for e in m['stages']],['ingest','init','batch','gaps','archive'])
                self.assertIsNone(package.load(root/'validation_record.yaml')['actual_new_user_response'])
    def test_real_source_read_and_compatible_file_reuse_preserve_bytes_and_time(self):
        layer,c,packet=self.prepare(reuse=True);doc=layer/'Context/existing_problem.md';before=(doc.read_bytes(),doc.stat().st_mtime_ns);root=self.draft(layer);m=package.load(root/'manifest.yaml');r=next(r for r in m['records'] if r['source_step']=='generate_problem_statement');target=root/r['path']
        self.assertEqual((target.read_bytes(),target.stat().st_mtime_ns),before);self.assertEqual((doc.read_bytes(),doc.stat().st_mtime_ns),before);self.assertEqual(r['generation_kind'],'reused')
        for src in m['source_reads']:
            q=package.source_path(layer,src['domain'],src['path']);self.assertEqual(src['sha256'],sha(q));self.assertEqual(src['source_mtime_ns'],q.stat().st_mtime_ns)
        result=package.archive_course(layer);self.assertTrue(result['pass'],result['errors'])
    def test_pending_material_question_blocks_archive(self):
        layer,c,packet=self.prepare(pending=True);plan=package.course_plan(layer,'Context/course_input.yaml');self.assertEqual(plan['questions'],['Which actual persona should be used?']);root=self.draft(layer);result=package.archive_course(layer);self.assertFalse(result['pass']);self.assertTrue(any(e['code']=='E_CHECKPOINT' for e in result['errors']));self.assertEqual(package.load(root/'manifest.yaml')['decisions']['persona']['state'],'pending')
    def test_plan_missing_drafts_writes_nothing_and_batch_refuses(self):
        layer,c,packet=self.prepare();packet['drafts'].pop('generate_persona_md');write_yaml(layer/'Context/course_input.yaml',packet);before={str(q):q.read_bytes() for q in layer.rglob('*') if q.is_file()};plan=package.course_plan(layer,'Context/course_input.yaml');self.assertIn('generate_persona_md',plan['missing_steps'])
        with self.assertRaises(ValueError):self.draft(layer)
        self.assertEqual({str(q):q.read_bytes() for q in layer.rglob('*') if q.is_file()},before)
    def test_invalid_input_scope_source_and_human_claim_refused_before_write(self):
        for n,change in enumerate([lambda p:p.update(scope_id='WRONG'),lambda p:p['sources'][0].update(sha256='bad'),lambda p:p['sources'][0].update(path='../outside'),lambda p:p['claims'][0].update(kind='user_reported'),lambda p:p['validation_record'].update(actual_new_user_response='fiction'),lambda p:p['validation_record'].update(before_solution=True),lambda p:p['solution'].update(kind='observed')]):
            layer,c,packet=self.prepare(str(n),'solution_based/single_persona');change(packet);write_yaml(layer/'Context/course_input.yaml',packet)
            with self.assertRaises((ValueError,OSError)):self.draft(layer)
            self.assertFalse((layer/'Documents').exists())
    def test_contract_provenance_and_unknown_branch_refused(self):
        layer,c,packet=self.prepare();self.assertEqual(c['reviewed_commit'],package.COMMIT);self.assertEqual(c['version'],'2.0+courses.1');self.assertEqual(c['course_contract_sha256'],sha(METHOD/'course_contracts.yaml'))
        intent=package.load(layer/'intent.yaml');intent['aipm']['course']='multi_persona';write_yaml(layer/'intent.yaml',intent)
        with self.assertRaises(ValueError):package.build_contract(layer)
    def mode_init_layer(self,name,registers=True,course='document_based/single_persona'):
        """Collection Phase 7.5: init first, record mode_init in intent, then prepare the batch input."""
        layer,c,packet=self.prepare(name,course)
        intent=package.load(layer/'intent.yaml');intent['aipm']['registers']=registers;write_yaml(layer/'intent.yaml',intent)
        out=package.init(layer);self.assertTrue(out['created'])
        intent=package.load(layer/'intent.yaml');intent['mode_init']={'state':'done','done_at':datetime.now(timezone.utc).isoformat(),'outputs':out['outputs']};write_yaml(layer/'intent.yaml',intent)
        if registers:   # the validation hypothesis takes the next free id with kind validation (H1 is the Init opportunity)
            root=Path(out['package']);h=package.load(root/'registers/hypotheses.yaml');h['hypotheses'].append({'id':'H2','kind':'validation','claim':'Synthetic structure','status':'unknown'});write_yaml(root/'registers/hypotheses.yaml',h)
            packet['validation_record']['hypotheses'][0]['id']='H2';write_yaml(layer/'Context/course_input.yaml',packet)
        return layer,Path(out['package']),out
    def test_batch_continues_a_package_made_only_by_mode_init(self):
        cases=[(True,'document_based/single_persona'),(False,'document_based/single_persona'),(True,'solution_based/single_persona')]
        for n,(registers,course) in enumerate(cases):
            with self.subTest(registers=registers,course=course):
                layer,root,out=self.mode_init_layer('mi'+str(n),registers,course)
                kept={o['path']:(layer/o['path']).read_bytes() for o in out['outputs'] if o['path'].endswith('format_contract.yaml') or '/registers/' in o['path']}
                if registers:
                    issues=root/'registers/issues.yaml';issues.write_text(issues.read_text()+'# edited by later work\n');kept['Documents/aipm_project/registers/issues.yaml']=issues.read_bytes()
                self.draft(layer)
                for path,data in kept.items():self.assertEqual((layer/path).read_bytes(),data,path)
                m=package.load(root/'manifest.yaml');self.assertEqual([e['name'] for e in m['stages']],['init','ingest','batch','gaps'])
                mi=package.load(layer/'intent.yaml')['mode_init'];first=m['stages'][0]
                self.assertEqual((first['origin'],first['started_at'],first['finished_at']),('mode_init',mi['done_at'],mi['done_at']))
                self.assertIn('start time not recorded',first['time_source']);self.assertEqual(first['mode_init_outputs'],mi['outputs']);self.assertEqual(first['evidence_refs'],[])
                result=validate_package.validate(root,phase='prearchive',layer=layer);self.assertTrue(result['pass'],result['errors']);self.assertEqual(result['checked_documents'],19)
                final=package.archive_course(layer);self.assertTrue(final['pass'],final['errors'])
                self.assertEqual([e['name'] for e in package.load(root/'manifest.yaml')['stages']],['init','ingest','batch','gaps','archive'])
    def test_batch_still_refuses_packages_beyond_mode_init(self):
        def edited_init(layer,root):p=root/package.build_contract(layer)['flow_rel']/'project_init.yaml';p.write_text(p.read_text()+'# hand edit\n')
        def has_document(layer,root):c=package.build_contract(layer);e=next(e for e in c['documents'] if not e.get('side'));q=root/c['flow_rel']/e['path'];q.parent.mkdir(parents=True,exist_ok=True);q.write_text('existing')
        def has_manifest(layer,root):(root/'manifest.yaml').write_text('{}')
        def no_mode_init(layer,root):i=package.load(layer/'intent.yaml');i.pop('mode_init');write_yaml(layer/'intent.yaml',i)
        def pending(layer,root):i=package.load(layer/'intent.yaml');i['mode_init']={'state':'pending'};write_yaml(layer/'intent.yaml',i)
        def stock_doc(layer,root):c=package.build_contract(layer);e=next(e for e in c['documents'] if not e.get('side'));q=root/c['stock_project_rel']/'documents'/e['path'];q.parent.mkdir(parents=True,exist_ok=True);q.write_text('archived copy')
        def stray_file(layer,root):(root/package.build_contract(layer)['flow_rel']/'memo.md').write_text('hand note')
        def registers_gone(layer,root):(root/'registers/issues.yaml').unlink()
        for n,change in enumerate([edited_init,has_document,has_manifest,no_mode_init,pending,stock_doc,stray_file,registers_gone]):
            with self.subTest(case=change.__name__):
                layer,root,out=self.mode_init_layer('ref'+str(n));change(layer,root)
                before={str(q):q.read_bytes() for q in root.rglob('*') if q.is_file()}
                with self.assertRaises(ValueError):self.draft(layer)
                self.assertEqual({str(q):q.read_bytes() for q in root.rglob('*') if q.is_file()},before)
    def test_mode_init_order_needs_matching_intent(self):
        layer,root,out=self.mode_init_layer('order')
        self.draft(layer)
        i=package.load(layer/'intent.yaml');i['mode_init']['done_at']='2020-01-01T00:00:00+00:00';write_yaml(layer/'intent.yaml',i)
        result=validate_package.validate(root,phase='prearchive',layer=layer);self.assertFalse(result['pass']);self.assertTrue(any(e['code']=='E_ORDER' and 'mode_init' in e['message'] for e in result['errors']))
        for n,change in enumerate([lambda f:f.update(started_at='2020-01-01T00:00:00+00:00'),lambda f:f.update(mode_init_outputs=[])]):
            with self.subTest(case=n):
                layer,root,out=self.mode_init_layer('order'+str(n));self.draft(layer);m=package.load(root/'manifest.yaml');change(m['stages'][0]);write_yaml(root/'manifest.yaml',m)
                result=validate_package.validate(root,phase='prearchive',layer=layer);self.assertTrue(any(e['code']=='E_ORDER' and 'mode_init' in e['message'] for e in result['errors']),result['errors'])
    def test_batch_without_mode_init_keeps_legacy_order(self):
        layer,c,packet=self.prepare('plain');root=self.draft(layer);m=package.load(root/'manifest.yaml')
        self.assertEqual([e['name'] for e in m['stages']],['ingest','init','batch','gaps']);self.assertNotIn('origin',m['stages'][1])
    def registers_as_sources(self,name):
        """mode_init package whose course input reads the registers themselves."""
        layer,root,out=self.mode_init_layer(name)
        packet=package.load(layer/'Context/course_input.yaml')
        for n,f in enumerate(['issues','hypotheses','roadmap'],1):
            rel='Documents/aipm_project/registers/'+f+'.yaml';packet['sources'].append({'id':'R'+str(n),'domain':'layer','path':rel,'sha256':sha(layer/rel)})
        write_yaml(layer/'Context/course_input.yaml',packet);return layer,root
    def test_registers_can_change_after_archive_when_they_were_sources(self):
        layer,root=self.registers_as_sources('snap');self.draft(layer)
        m=package.load(root/'manifest.yaml');self.assertEqual(sorted(m['source_snapshots']),['R1','R2','R3'])
        for sid,rel in m['source_snapshots'].items():
            read=next(r for r in m['source_reads'] if r['id']==sid);q=layer/rel
            self.assertEqual((sha(q),q.stat().st_mtime_ns),(read['sha256'],read['source_mtime_ns']))
        final=package.archive_course(layer);self.assertTrue(final['pass'],final['errors'])
        h=package.load(root/'registers/hypotheses.yaml');h['hypotheses'][0].setdefault('judgements',[]).append({'date':'2026-10-20','event':'meeting','verdict':'undetermined','judged_by':'ai_proxy'});write_yaml(root/'registers/hypotheses.yaml',h)
        i=package.load(root/'registers/issues.yaml');i['issues'][0].update(status='on_hold',reason='later',review_at='2026-11-01');write_yaml(root/'registers/issues.yaml',i)
        r=package.load(root/'registers/roadmap.yaml');r['roadmap'][0]['period']='2026-11';write_yaml(root/'registers/roadmap.yaml',r)
        result=validate_package.validate(root,phase='final',layer=layer);self.assertTrue(result['pass'],result['errors'])
        snap=layer/m['source_snapshots']['R2'];snap.write_text(snap.read_text()+'# tampered\n')
        result=validate_package.validate(root,phase='final',layer=layer);self.assertFalse(result['pass']);self.assertTrue(any(e['code']=='E_COURSE' for e in result['errors']))
    def test_snapshot_must_mirror_a_package_source(self):
        layer,root=self.registers_as_sources('mirror');self.draft(layer)
        base=package.load(root/'manifest.yaml');issues_copy='Documents/aipm_project/source_snapshots/registers/issues.yaml'
        def outside(m):m['source_snapshots']['M1']=issues_copy
        def swapped(m):m['source_snapshots']['R2']=issues_copy
        def evidence_only(m):m['evidence'].append({'id':'X1','kind':'observed','source':'Context/does_not_exist.md','source_sha256':sha(layer/issues_copy),'scope':'probe'});m['source_snapshots']['X1']=issues_copy
        for change in [outside,swapped,evidence_only]:
            with self.subTest(case=change.__name__):
                m=copy.deepcopy(base);change(m);write_yaml(root/'manifest.yaml',m)
                result=validate_package.validate(root,phase='prearchive',layer=layer);self.assertTrue(any(e['code']=='E_COURSE' and 'snapshot' in e['message'] for e in result['errors']),result['errors'])
    def test_package_source_overwritten_by_the_batch_is_kept_as_read(self):
        layer,root,out=self.mode_init_layer('overwrite');c=package.build_contract(layer)
        rel='Documents/aipm_project/'+c['flow_rel']+'/project_init.yaml';packet=package.load(layer/'Context/course_input.yaml')
        packet['sources'].append({'id':'PI','domain':'layer','path':rel,'sha256':sha(layer/rel)});write_yaml(layer/'Context/course_input.yaml',packet);read=sha(layer/rel)
        self.draft(layer);m=package.load(root/'manifest.yaml')
        self.assertNotEqual(sha(layer/rel),read);self.assertEqual(sha(layer/m['source_snapshots']['PI']),read)
        result=validate_package.validate(root,phase='prearchive',layer=layer);self.assertTrue(result['pass'],result['errors'])
    def test_no_snapshots_when_sources_are_outside_the_package(self):
        layer,root,out=self.mode_init_layer('nosnap');self.draft(layer)
        self.assertNotIn('source_snapshots',package.load(root/'manifest.yaml'))
    def test_saved_legacy_contract_value_is_identical(self):
        layer=self.base/'old';layer.mkdir();write_yaml(layer/'intent.yaml',{'scope_id':'OLD','scope_name':'old','work_style':'aipm','aipm':{'date':'2026-10-13'}})
        c=package.build_contract(layer);schema=package.load(METHOD/'format_schema.yaml');schema.pop('local_courses');expected=copy.deepcopy(schema);b=c['bindings'];expected.update(scope_id='OLD',bindings=b,package_root=c['package_root'],flow_rel=c['flow_rel'],stock_project_rel=c['stock_project_rel'])
        for e in expected['documents']:e['path']=e['path'].format(**b)
        expected['id_mapping']['persona']='P001';self.assertEqual(c,expected);self.assertNotIn('course_id',c)
    def test_existing_package_never_regenerated_or_migrated(self):
        layer,c,packet=self.prepare();root=self.draft(layer);before={str(q):q.read_bytes() for q in root.rglob('*') if q.is_file()}
        with self.assertRaises(ValueError):self.draft(layer)
        self.assertEqual(before,{str(q):q.read_bytes() for q in root.rglob('*') if q.is_file()})
    def test_fake_metadata_and_no_question_scope_rejected(self):
        mutations=[lambda m:m.update(course_contract_sha256='fake'),lambda m:m['source_reads'][0].update(read_at='2999-01-01T00:00:00+00:00'),lambda m:m['source_reads'][0].update(source_mtime_ns=0),lambda m:m['decisions']['persona'].update(state='confirmed_actual'),lambda m:m['decisions']['persona'].update(reason=''),lambda m:m['decisions']['persona'].update(scope='actual_effect'),lambda m:m['records'][0].update(generation_kind='reused',reused_from='M1'),lambda m:m['records'][0].update(generated_mtime_ns=0),lambda m:m['stages'][0].update(finished_at='2999-01-01T00:00:00+00:00'),lambda m:m['claims'][0].update(kind='user_reported')]
        for n,mut in enumerate(mutations):
            layer,c,packet=self.prepare(str(n));root=self.draft(layer);self.mutate(root,mut)
    def test_original_pending_and_material_gaps_cannot_be_erased_in_manifest(self):
        for n,change in enumerate([lambda m:m['decisions']['persona'].update(state='not_required'),lambda m:m.update(gaps=[]),lambda m:m['decisions']['persona'].update(reason='fabricated no-question reasoning'),lambda m:m.update(claims=[])]):
            layer,c,packet=self.prepare('erase'+str(n),pending=True)
            packet['gaps'].append({'kind':'unknown','reason':'Actual persona must be chosen','requires_user':True,'decision_key':'persona','question':'Which persona?'})
            write_yaml(layer/'Context/course_input.yaml',packet);root=self.draft(layer);before=sha(layer/'Context/course_input.yaml');m=package.load(root/'manifest.yaml');change(m);write_yaml(root/'manifest.yaml',m)
            result=package.archive_course(layer);self.assertFalse(result['pass']);self.assertTrue(any(e['code']=='E_COURSE' for e in result['errors']));self.assertEqual(before,sha(layer/'Context/course_input.yaml'))
            self.assertTrue(all(r['archive_path'] is None for r in package.load(root/'manifest.yaml')['records']))
    def test_pending_decision_resolves_only_via_target_bound_receipt(self):
        layer,c,packet=self.prepare('answer',pending=True);packet['gaps'].append({'kind':'unknown','reason':'Actual persona must be chosen','requires_user':True,'decision_key':'persona','question':'Which persona?'})
        write_yaml(layer/'Context/course_input.yaml',packet);root=self.draft(layer);m=package.load(root/'manifest.yaml');record=next(r for r in m['records'] if r['source_step']=='generate_persona_md');target_path='Documents/aipm_project/'+record['path'];answer='Synthetic structural reply only; no real user observation'
        receipt={'kind':'user_reported','actor':'actual_user','origin':'actual_user_reply','scope_id':c['scope_id'],'stage':'persona','answer':answer,'question_id':'SYNTHETIC-QUESTION','source_thread_id':'SYNTHETIC-ONLY','received_at':now(),'target_path':target_path,'target_sha256':sha(root/record['path'])}
        source=layer/'Context/answer.yaml';write_yaml(source,receipt);m['human_responses']={'persona':{k:receipt[k] for k in ['answer','target_path','target_sha256']}};m['human_responses']['persona'].update(source='Context/answer.yaml',source_sha256=sha(source));m['checkpoint_targets']={'persona':receipt['target_sha256']};m['evidence'].append({'id':'USR','kind':'user_reported','source':'Context/answer.yaml','source_sha256':sha(source),'scope':'synthetic receipt fixture only'});m['decisions']['persona']['state']='confirmed_actual';m['stages'][-1]['finished_at']=now();write_yaml(root/'manifest.yaml',m)
        result=package.archive_course(layer);self.assertTrue(result['pass'],result['errors'])
        # A changed answer source cannot retain a false confirmation.
        receipt['target_sha256']='fake';write_yaml(source,receipt);result=validate_package.validate(root,phase='final',layer=layer);self.assertFalse(result['pass']);self.assertTrue(any(e['code']=='E_CHECKPOINT' for e in result['errors']))

    def test_receipt_command_binds_both_checkpoints(self):
        """package.py receipt writes the receipt from the input reply and binds manifest; refusals write nothing."""
        layer,c,packet=self.prepare('receipt',pending=True)
        packet['decisions']['validation']={'state':'pending','reason':'Choosing validation hypotheses is the user call','scope':'reversible_draft_only','source_ids':['M1','M2'],'question':'Use H1 for validation?'}
        for key in ('persona','validation'):packet['gaps'].append({'kind':'unknown','reason':'needs the user','requires_user':True,'decision_key':key,'question':'?'})
        write_yaml(layer/'Context/course_input.yaml',packet);root=self.draft(layer)
        def ask(name,**over):
            d={'stage':'persona','question':'Which actual persona should be used?','answer':'Synthetic reply only','question_id':'SYN-Q1','source_thread_id':'SYNTHETIC-THREAD','answered_at':now()};d.update(over)
            d={k:v for k,v in d.items() if v is not None};write_yaml(layer/'Context'/name,d);return 'Context/'+name
        def untouched(fn,*args):
            before=sha(root/'manifest.yaml');files=sorted(x.name for x in (layer/'Context').iterdir() if x.name.startswith('receipt_'))
            with self.assertRaises(ValueError):fn(*args)
            self.assertEqual(before,sha(root/'manifest.yaml'));self.assertEqual(files,sorted(x.name for x in (layer/'Context').iterdir() if x.name.startswith('receipt_')))
        untouched(package.receipt,layer,ask('a.yaml',question='A different question'))
        untouched(package.receipt,layer,ask('a2.yaml',question='Which persona should be used?'))   # the recorded question was edited
        untouched(package.receipt,layer,ask('b.yaml',answered_at=None))
        untouched(package.receipt,layer,ask('c.yaml',answered_at='2026-10-19T10:00:00'))   # no timezone
        untouched(package.receipt,layer,ask('d.yaml',answered_at='2000-01-01T00:00:00+00:00'))   # before the target version
        untouched(package.receipt,layer,ask('d2.yaml',answered_at='2999-01-01T00:00:00+00:00'))   # in the future
        from unittest import mock
        real=validate_package.validate
        def broken_after(n):
            calls=[]
            def v(*a,**k):
                calls.append(1);res=real(*a,**k)
                if len(calls)==n:res={**res,'pass':False,'errors':res['errors']+[{'code':'E_SYNTH','path':'x','message':'injected'}]}
                return res
            return v
        with mock.patch.object(validate_package,'validate',broken_after(1)):untouched(package.receipt,layer,ask('d3.yaml'))   # other errors before binding
        before=(sha(root/'manifest.yaml'),(root/'manifest.yaml').stat().st_mtime_ns)
        with mock.patch.object(validate_package,'validate',broken_after(2)):r=package.receipt(layer,ask('d4.yaml'))   # the binding breaks validate
        self.assertFalse(r['pass']);self.assertEqual([e['code'] for e in r['errors']],['E_SYNTH']);self.assertEqual(before,(sha(root/'manifest.yaml'),(root/'manifest.yaml').stat().st_mtime_ns));self.assertFalse((layer/'Context/receipt_SYN-Q1.yaml').exists())
        m=package.load(root/'manifest.yaml');saved=m['stages'][-1]['finished_at'];m['stages'][-1]['finished_at']='2026-10-19T10:00:00';write_yaml(root/'manifest.yaml',m)
        untouched(package.receipt,layer,ask('d5.yaml'))   # unreadable gaps time is found before any write
        m['stages'][-1]['finished_at']=saved;write_yaml(root/'manifest.yaml',m)
        untouched(package.receipt,layer,ask('e.yaml',stage='validation',question='Use H1 for validation?',question_id='SYN-Q2'))   # no checkpoint snapshot yet
        r=package.receipt(layer,ask('f.yaml',question='Which actual persona should be used? (the draft uses P001)'));self.assertTrue(r['bound']);self.assertEqual(r.get('errors'),None);self.assertFalse(r['pass'])   # validation still pending
        rec=package.load(layer/r['receipt']);self.assertEqual((rec['answered_at'],rec['answer']),(package.load(layer/'Context/f.yaml')['answered_at'],'Synthetic reply only'));self.assertNotEqual(rec['received_at'],rec['answered_at'])
        m=package.load(root/'manifest.yaml');self.assertEqual(m['decisions']['persona']['state'],'confirmed_actual');self.assertEqual(m['checkpoint_targets']['persona'],rec['target_sha256']);self.assertEqual(m['stages'][-1]['finished_at'],rec['received_at'])
        self.assertFalse(any(e['path']=='persona' for e in r['remaining_errors']))
        untouched(package.receipt,layer,ask('g.yaml',question_id='SYN-Q3'))   # persona already answered
        untouched(package.receipt,layer,ask('h.yaml',stage='note'))   # the same question_id file already exists
        v=package.load(root/'validation_record.yaml');write_yaml(root/'validation_checkpoint.yaml',{k:x for k,x in v.items() if k!='actual_new_user_response'})
        r=package.receipt(layer,ask('i.yaml',stage='validation',question='Use H1 for validation?',question_id='SYN-Q2',answered_at=now()));self.assertTrue(r['pass'],r)
        m=package.load(root/'manifest.yaml');self.assertEqual([e['id'] for e in m['evidence'] if e['kind']=='user_reported'],['USR-persona','USR-validation'])
        final=package.archive_course(layer);self.assertTrue(final['pass'],final['errors'])
        untouched(package.receipt,layer,ask('j.yaml',stage='validation',question='Use H1 for validation?',question_id='SYN-Q4'))   # after archive
        # a stage outside the checkpoints only writes the receipt (e.g. a judgement after a meeting)
        r=package.receipt(layer,ask('k.yaml',stage='meeting_1',question='Judge H1?',question_id='SYN-Q5'));self.assertFalse(r['bound']);self.assertNotIn('target_path',package.load(layer/r['receipt']))

    def test_external_layer_escape_and_symlink_cannot_be_source(self):
        layer,c,packet=self.prepare();outside=self.base/'outside';outside.write_text('not authorized');(layer/'Context/link').symlink_to(outside);packet['sources']=[{'id':'X','domain':'layer','path':'Context/link','sha256':sha(outside)}];write_yaml(layer/'Context/course_input.yaml',packet)
        with self.assertRaises(ValueError):self.draft(layer)
        self.assertFalse((layer/'Documents').exists())

if __name__=='__main__':unittest.main()
