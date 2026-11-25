"""Exercise Collection -> normal package init -> prearchive -> apply -> next use.
Only source-shaped synthetic contents; no claim of human acceptance/product QA.
"""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import importlib.util
import json
import os
import unittest
import yaml
from datetime import datetime,timezone
METHOD=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(METHOD))
import package,validate_package,shared_stock
from test_integration import models,write_yaml,sha,now
SEED=next((q for q in (METHOD.parents[2]/'tests/db/test_shared_stock.py',METHOD.parents[1]/'db/tests/test_shared_stock.py') if q.is_file()),None)   # the repository's tests/db (the seed is not installed)
seeds=None
if SEED is not None:
    spec=importlib.util.spec_from_file_location('registry_fixture_seed',SEED)
    seeds=importlib.util.module_from_spec(spec);spec.loader.exec_module(seeds)
NO_SEED='tests/db/test_shared_stock.py is not here (an installed copy); run from the repository'


def layer_intent(store,selector,n,layout='nested_v1'):
    layer=store.root/('layer-'+str(n));layer.mkdir();(layer/'Context').mkdir()
    write_yaml(layer/'intent.yaml',{'scope_id':'L-SYN-'+str(n),'scope_name':'project'+str(n),'owner':'Synthetic fixture','mode':'direct','work_style':'aipm','aipm':{'layout':layout,'project_id':'project'+str(n),'persona_id':'P001','name_slug':'synthetic','date':'2026-10-13','storage':'registry_stock_v1','stock_selector':selector,'aiplc_uid':'aiplc-'+str(n)},'goal':{'description':'Synthetic only'}})
    (layer/'Context/case.yaml').write_text('kind: hypothesis\nclaim: synthetic only\n')
    return layer


def generated_documents(layer,store):
    # This calls the production package entry; no legacy package transplantation.
    result=package.init(layer,stock_runtime=store);c=result['contract'];root=Path(result['package']);data=models(c)
    b=c['bindings'];flow_base,stock_base=package.init_roots(c);data['write_init_yaml'].update(program_id=b['program_id'],project_id=b['project_id'],participant_name=b['participant_name'],flow_dir=b['flow_dir'],flow_base=flow_base,stock_base=stock_base)
    evidence=[{'id':'F1','kind':'hypothesis','source':'Context/case.yaml','source_sha256':sha(layer/'Context/case.yaml'),'scope':'synthetic only'}]
    records=[];stages=[]
    for name in c['course']:
        if name=='archive':break
        start=now()
        if name=='validation':
            write_yaml(root/'validation_record.yaml',{'scope_id':c['scope_id'],'before_solution':True,'hypotheses':[{'id':'H1','kind':'hypothesis','claim':'synthetic structure','method':'validator','success':'pass','falsification':'fail','result':'unknown','scope':'synthetic'}],'evidence_refs':['F1'],'actual_new_user_response':None,'limits':['No human result']})
        for e in c['documents']:
            stage='init' if e.get('side') else {'01':'persona','02':'problem','03':'solution','04':'story'}[e['path'][:2]]
            if stage!=name:continue
            rel=package.doc_rel(c,e);q=root/rel
            q.parent.mkdir(parents=True,exist_ok=True)
            if e['kind']=='yaml':write_yaml(q,data[e['step']])
            else:
                graph='flowchart TD\n P001 --> PH1\n PH1 --> A101\n A101 --> PR1\n PR1 --> SL1\n SL1 --> ST1'
                body='# Synthetic fixture\n\n'
                for idx,h in enumerate(e['required_headings']):body+='## '+h+'\n\n'+('```mermaid\n'+graph+'\n```\n' if e['kind']=='mermaid' and idx==0 else '[hypothesis] synthetic only\n')+'\n'
                if e['kind']=='mermaid' and not e['required_headings']:body+='```mermaid\n'+graph+'\n```\n'
                q.write_text(body)
            records.append({'path':rel,'source_step':e['step'],'template_sha256':e['template_sha256'],'version':'v1','branch':'question_based/single_persona','stage':name,'status':'validated_local_final' if e.get('side') else 'generated','requires_human':False,'human_state':'not_required','inputs':['Context/case.yaml'],'evidence_refs':['F1'],'decision':'synthetic structural fixture','sha256':sha(q),'generated_mtime_ns':q.stat().st_mtime_ns,'archive_path':None,'archive_sha256':None})
        stages.append({'name':name,'started_at':start,'finished_at':now(),'checkpoint_actor':'auto_decision','checkpoint_status':'accepted_local','evidence_refs':['F1']})
    manifest={'scope_id':c['scope_id'],'source_commit':c['reviewed_commit'],'contract_version':c['version'],'branch':'question_based/single_persona','flow_rel':c['flow_rel'],'stock_project_rel':c['stock_project_rel'],'id_mapping':c['id_mapping'],'completion_claim':'local_trial_only; new human readability/effectiveness unknown','stages':stages,'evidence':evidence,'records':records}
    write_yaml(root/'manifest.yaml',manifest)
    return root,c


class SharedFlow(unittest.TestCase):
    LAYOUT='nested_v1'   # BoxRootSharedFlow runs every test on box_root_v1
    def setUp(self):
        if seeds is None:self.skipTest(NO_SEED)
        self.s=shared_stock.FixtureStore();self.selector=seeds.seed(self.s)
    def tearDown(self):self.s.close()
    def setup_layer(self,n=1):
        layer=layer_intent(self.s,self.selector,n,self.LAYOUT)
        shared_stock.collection(layer,self.s,adopted_folder='programs/p1/projects/b1' if n==1 else None)
        root,c=generated_documents(layer,self.s)
        self.assertTrue(validate_package.validate(root,phase='prearchive',layer=layer)['pass'])
        return layer,root,c
    def proposal(self,layer,root,c,key='problem'):
        source=package.pkg_rel(c['flow_rel'],'02_課題定義/problem_map.yaml')
        return shared_stock.prepare_archive(layer,self.s,task_id='T007',decision_ref='synthetic-adoption',as_of='2026-10-13T00:00:00+00:00',units={key:{'kind':'hypothesis','text':'Synthetic organized claim '+key,'source_paths':[source]}})
    def apply(self,layer,proposal,request='archive-1',**kw):
        return shared_stock.apply_archive(layer,self.s,proposal,approved_hash=shared_stock.core.digest(proposal),request_id=request,writer='synthetic-writer',expires_at=seeds.expiry(),**kw)
    def test_normal_two_archive_then_next_collection(self):
        ids=[]
        for n,key in [(1,'problem'),(2,'solution')]:
            layer,root,c=self.setup_layer(n);self.assertFalse((root/'Stock').exists())
            p=self.proposal(layer,root,c,key);r=self.apply(layer,p,'archive-'+str(n));ids.append(r['binding_id'])
            result=validate_package.validate(root,layer=layer,stock_runtime=self.s)
            self.assertTrue(result['pass'],result);self.assertEqual(result['checked_documents'],19)
            self.assertEqual(r,self.apply(layer,p,'archive-'+str(n)))
        third=layer_intent(self.s,self.selector,3,self.LAYOUT);current=shared_stock.collection(third,self.s)
        self.assertEqual(ids[0],ids[1]);self.assertEqual(set(current['current']['units']),{'problem','solution'})
        self.assertEqual(len(current['current']['sources']),2)
        self.assertFalse((third/'Documents').exists())
    def test_live_runtime_and_unknown_binding_stop_before_init(self):
        layer=layer_intent(self.s,self.selector,1,self.LAYOUT)
        with self.assertRaises(shared_stock.Hold):package.init(layer)
        with self.assertRaises(shared_stock.Hold):package.init(layer,stock_runtime=self.s)
        self.assertFalse((layer/'Documents').exists())
    def test_flow_changed_after_diff(self):
        layer,root,c=self.setup_layer();p=self.proposal(layer,root,c)
        (layer/'Context/case.yaml').write_text('changed evidence')
        with self.assertRaises(shared_stock.Hold):self.apply(layer,p)
        self.assertIsNone(self.s.bind(self.selector)['current_revision'])
    def test_required_human_checkpoint_not_bypassed(self):
        layer,root,c=self.setup_layer();m=package.load(root/'manifest.yaml');m['records'][0].update(requires_human=True,human_state='pending');write_yaml(root/'manifest.yaml',m)
        with self.assertRaises(shared_stock.Hold):self.proposal(layer,root,c)
    def test_core_commit_interrupted_before_package_completion(self):
        layer,root,c=self.setup_layer();p=self.proposal(layer,root,c)
        with self.assertRaises(RuntimeError):self.apply(layer,p,fault='after_commit')
        r=self.apply(layer,p);self.assertEqual(r['generation'],1)
        self.assertTrue(validate_package.validate(root,layer=layer,stock_runtime=self.s)['pass'])
    def test_package_manifest_interruption_recovered_without_new_stock_version(self):
        layer,root,c=self.setup_layer();p=self.proposal(layer,root,c)
        with self.assertRaises(RuntimeError):self.apply(layer,p,fault='after_package_manifest')
        r=self.apply(layer,p);self.assertEqual(r['generation'],1)
        self.assertTrue(validate_package.validate(root,layer=layer,stock_runtime=self.s)['pass'])
    def test_package_recovery_rejects_later_manifest_changes(self):
        layer,root,c=self.setup_layer();p=self.proposal(layer,root,c)
        with self.assertRaises(RuntimeError):self.apply(layer,p,fault='after_package_manifest')
        q=root/'manifest.yaml';q.write_text(q.read_text()+'\n# other writer\n');before=q.read_bytes()
        with self.assertRaises(shared_stock.Hold):self.apply(layer,p)
        self.assertEqual(before,q.read_bytes())
    def test_crlf_original_and_manifest_preserved_through_recovery(self):
        layer,root,c=self.setup_layer()
        source=package.pkg_rel(c['flow_rel'],'02_課題定義/problem_map.yaml');q=root/source
        stamp=q.stat().st_mtime_ns;q.write_bytes(q.read_bytes().replace(b'\n',b'\r\n'));os.utime(q,ns=(stamp,stamp))
        manifest=package.load(root/'manifest.yaml')
        for record in manifest['records']:
            if record['path']==source:record['sha256']=sha(q)
        write_yaml(root/'manifest.yaml',manifest)
        m=root/'manifest.yaml';m.write_bytes(m.read_bytes().replace(b'\n',b'\r\n'))
        self.assertTrue(validate_package.validate(root,phase='prearchive',layer=layer)['pass'])
        proposal=self.proposal(layer,root,c)
        self.assertEqual(proposal['plan']['source']['original_hashes'][source],sha(q))
        with self.assertRaises(RuntimeError):self.apply(layer,proposal,fault='after_commit')
        receipt=self.apply(layer,proposal)
        dest=self.s.stock/self.s.bind(self.selector)['folder']/'revisions'/receipt['revision']/'originals'/receipt['source_id']/source
        self.assertEqual(dest.read_bytes(),q.read_bytes())
        self.assertTrue(validate_package.validate(root,layer=layer,stock_runtime=self.s)['pass'])
    def test_final_rejects_receipt_tampering_and_compensation(self):
        layer,root,c=self.setup_layer();p=self.proposal(layer,root,c);self.apply(layer,p)
        q=root/'shared_archive_receipt.json';saved=q.read_text();d=json.loads(saved);d['binding_id']='wrong';q.write_text(json.dumps(d))
        self.assertFalse(validate_package.validate(root,layer=layer,stock_runtime=self.s)['pass'])
        q.write_text(saved);self.s.compensate('archive-1',writer='synthetic-writer',expires_at=seeds.expiry())
        self.assertFalse(validate_package.validate(root,layer=layer,stock_runtime=self.s)['pass'])

    def test_new_course_batch_draft_goes_to_the_shared_archive(self):
        """The production draft of a new course (sources include method_source:...) through prepare/apply to final."""
        import test_integration as ti
        class Case:pass
        case=Case();case.base=self.s.root
        layer,_,packet=ti.CourseIntegration.prepare(case,'course-shared')
        d=package.load(layer/'intent.yaml');d['scope_id']='L-SYN-1'   # the identity seeded in the fixture Registry
        d['aipm'].update(layout=self.LAYOUT,storage='registry_stock_v1',stock_selector=self.selector,aiplc_uid='aiplc-1')
        write_yaml(layer/'intent.yaml',d)
        shared_stock.collection(layer,self.s,adopted_folder='programs/p1/projects/b1')
        c=package.build_contract(layer);b=c['bindings'];flow_base,stock_base=package.init_roots(c)
        packet['drafts']['write_init_yaml'].update(program_id=b['program_id'],project_id=b['project_id'],flow_dir=b['flow_dir'],flow_base=flow_base,stock_base=stock_base)
        packet['scope_id']='L-SYN-1';packet['validation_record']['scope_id']='L-SYN-1'
        write_yaml(layer/'Context/course_input.yaml',packet)
        root=Path(package.batch_draft(layer,'Context/course_input.yaml',stock_runtime=self.s)['package'])
        self.assertTrue(validate_package.validate(root,phase='prearchive',layer=layer)['pass'])
        source=package.pkg_rel(c['flow_rel'],'02_課題定義/problem_map.yaml')
        p=shared_stock.prepare_archive(layer,self.s,task_id='T009',decision_ref='synthetic-adoption',as_of='2026-10-24T00:00:00+00:00',units={'problem':{'kind':'hypothesis','text':'Synthetic organized claim','source_paths':[source]}})
        self.assertTrue(any(k.startswith('method_source:') for k in p['input_pins']))
        self.apply(layer,p,'archive-course')
        result=validate_package.validate(root,layer=layer,stock_runtime=self.s);self.assertTrue(result['pass'],result['errors'])
        if self.LAYOUT in package.FLAT_LAYOUTS:self.assertFalse((root/'Flow').exists());self.assertFalse((root/'Stock').exists())

class BoxRootSharedFlow(SharedFlow):
    """The same shared Stock flow on box_root_v1: no inner Flow/ or Stock/, the charter at <package>/_charter."""
    LAYOUT=package.BOX_ROOT_LAYOUT
    def test_box_root_shape_and_default(self):
        layer,root,c=self.setup_layer()
        self.assertEqual((c['layout'],c['flow_rel'],c['stock_project_rel'],c['stock_target_rel']),(package.BOX_ROOT_LAYOUT,'','_charter',None))
        self.assertFalse((root/'Flow').exists());self.assertFalse((root/'Stock').exists());self.assertTrue((root/'_charter/README.md').is_file())
        self.assertTrue((root/'02_課題定義/problem_map.yaml').is_file())
        p=self.proposal(layer,root,c);r=self.apply(layer,p)
        m=package.load(root/'manifest.yaml')
        for rec in m['records']:
            if rec['stage']!='init':self.assertEqual(rec['archive_path'],'originals/'+r['source_id']+'/'+rec['path']);self.assertFalse(rec['path'].startswith('Flow/'))
        self.assertTrue(validate_package.validate(root,layer=layer,stock_runtime=self.s)['pass'])
        d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d)
        self.assertEqual(package.build_contract(layer)['layout'],package.BOX_ROOT_LAYOUT)   # the saved layout
        fresh=layer_intent(self.s,self.selector,4,None);d=package.load(fresh/'intent.yaml');d['aipm'].pop('layout');write_yaml(fresh/'intent.yaml',d)
        self.assertEqual(package.build_contract(fresh)['layout'],package.SHEETS_LAYOUT)   # the default for a new shared Stock package

if __name__=='__main__':unittest.main()
