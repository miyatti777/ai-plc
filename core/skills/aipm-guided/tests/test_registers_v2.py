"""Registers contract v2 and version binding. Synthetic fixtures only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import hashlib, tempfile, unittest, yaml
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_integration as base
import test_registers as reg
package=base.package;validate_package=base.validate_package;METHOD=base.METHOD

V1_SHA256='7fe836a1b0eeb5baa0ae2b42acea7460c64db950ff123ac89447d9af963ecddf'        # registers_contract.yaml version 1
COURSE_SHA256='699d5851f2b8fd74c9d1cddb5d60375fd9b2c6c9ffca0c5574c96a1b9060aa29'    # course_contracts.yaml is not changed by version 2
C8_WORDS=('outside the period','before the forecast.start','falls in no WBS forecast range')

def v1_registers_fixture(layer,rows=None):
    """A package bound to version 1: build it while the latest registers contract is stood in by the frozen version 1."""
    real=package.registers_contract_path
    package.registers_contract_path=lambda v=None:real(1 if v is None else v)
    try:return reg.registers_fixture(layer,rows)
    finally:package.registers_contract_path=real

class Base(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def result(self,root,layer):return validate_package.validate(root,layer=layer)
    def errors(self,root,layer):return [e for e in self.result(root,layer)['errors'] if e['code']=='E_REGISTERS']
    def warnings(self,root,layer):return [w for w in self.result(root,layer)['warnings'] if w['code']=='W_REGISTERS']
    def issues(self,root,rows):base.write_yaml(root/'registers/issues.yaml',{'charter':{'change_conditions':['c'],'exit_conditions':['e']},'issues':rows})
    def hyps(self,root,rows):base.write_yaml(root/'registers/hypotheses.yaml',{'hypotheses':rows})

class Version(Base):
    def test_v1_frozen_bytes_equal_the_contract_before_t005(self):
        self.assertEqual(hashlib.sha256((METHOD/'registers_contract.v1.yaml').read_bytes()).hexdigest(),V1_SHA256)
        self.assertEqual(package.registers_contract_path(1),METHOD/'registers_contract.v1.yaml')
        latest=package.load(METHOD/'registers_contract.yaml');self.assertEqual((latest['version'],latest['contract_suffix']),(2,'+registers.2'))

    def test_v1_package_still_validates_after_the_change(self):
        layer=self.base/'v1';root,c=v1_registers_fixture(layer)
        saved=package.load(root/'format_contract.yaml')
        self.assertEqual(saved['registers_contract_version'],1);self.assertTrue(saved['version'].endswith('+registers.1'));self.assertEqual(saved['registers_contract_sha256'],V1_SHA256)
        rebuilt=package.build_contract(layer);self.assertEqual(rebuilt,saved)   # the saved version is used, not the latest
        r=self.result(root,layer);self.assertTrue(r['pass'],r['errors'])
        again=package.init(layer);self.assertFalse(again['created'])           # init re-run is not refused as "another contract"

    def test_v1_package_keeps_v1_rules(self):
        layer=self.base/'v1rules';root,c=v1_registers_fixture(layer)
        row={'id':'I1','question':'q','status':'open','priority':'[unknown]','owner':'PM','due':'undecided'}
        self.issues(root,[row]);r=self.result(root,layer);self.assertTrue(r['pass'],r['errors'])
        self.assertFalse(any('priority is still' in w['message'] for w in r['warnings']))      # v1 warns for owner only
        self.issues(root,[dict(row,owner='[unknown]')]);self.assertTrue(any(w['message']=='owner is still [unknown]' for w in self.warnings(root,layer)))
        self.issues(root,[dict(row,sources=['Context/case.yaml'])]);self.assertTrue(any('unknown key: sources' in e['message'] for e in self.errors(root,layer)))

    def test_new_init_is_v2(self):
        layer=self.base/'init';layer.mkdir();(layer/'Context').mkdir()
        base.write_yaml(layer/'intent.yaml',{'scope_id':'L-V2','scope_name':'v2','work_style':'aipm','aipm':{'date':'2026-10-22','registers':True},'goal':{'description':'synthetic'}})
        r=package.init(layer);c=package.load(Path(r['package'])/'format_contract.yaml')
        self.assertTrue(c['version'].endswith('+registers.2'));self.assertEqual(c['registers_contract_version'],2)
        self.assertEqual(c['registers_contract_sha256'],base.sha(METHOD/'registers_contract.yaml'))

    def test_unknown_saved_version_is_refused(self):
        with self.assertRaises(ValueError):package.registers_contract_path(9)
        with self.assertRaises(ValueError):package.registers_contract_path('1')

class Sources(Base):
    def make(self):
        repo=self.base/'repo';(repo/'Stock').mkdir(parents=True);(repo/'Stock/known.md').write_text('x')
        (repo/'Flow/202610/2026-10-22').mkdir(parents=True)
        layer=repo/'Flow/202610/2026-10-22/src';root,c=reg.registers_fixture(layer);return layer,root

    def test_contract_has_formats_and_kind_rule(self):
        rc=package.load(METHOD/'registers_contract.yaml')
        self.assertEqual(set(rc['files']['hypotheses']['kind_rule']),set(rc['files']['hypotheses']['kind']))
        self.assertIn('sources',rc['files']['issues']['optional']);self.assertIn('sources',rc['files']['hypotheses']['optional'])
        self.assertEqual([f['format'] for f in rc['sources']['source_formats']][:2],['layer_relative','repo_relative'])

    def test_sources_checks(self):
        layer,root=self.make()
        row={'id':'I1','question':'q','status':'open','priority':'high','owner':'PM','due':'undecided'}
        hyp=[{'id':'H1','kind':'validation','claim':'x','status':'unknown'},{'id':'H2','kind':'opportunity','claim':'y','status':'unknown','sources':['Context/case.yaml']}]
        self.hyps(root,hyp)
        def run(srcs):
            self.issues(root,[dict(row,sources=srcs)]);r=self.result(root,layer)
            return r,[e for e in r['errors'] if e['code']=='E_REGISTERS'],[w for w in r['warnings'] if w['code']=='W_REGISTERS' and 'source' in w['message']]
        r,e,w=run(['Context/case.yaml','Flow@abc1234:202610/x.md','Stock/known.md']);self.assertTrue(r['pass'],r['errors']);self.assertEqual((e,w),([],[]))
        r,e,w=run(['Context/missing.md']);self.assertEqual(len(e),1);self.assertIn('source missing in the Layer',e[0]['message'])
        r,e,w=run(['origin/main:Flow/202610/x.md']);self.assertEqual(e,[]);self.assertEqual(len(w),1);self.assertTrue(r['pass'])
        r,e,w=run(['Stock/absent.md']);self.assertEqual(e,[]);self.assertEqual(len(w),1);self.assertIn('repo-relative source not found',w[0]['message'])
        r,e,w=run(['Flow@xyz:202610/x.md']);self.assertEqual(len(w),1)                               # not hex: not the Flow@ form
        for v in ('nowhere/x.md','notes.md','Agents/x.md'):                                         # Layer-relative by default
            r,e,w=run([v]);self.assertEqual(len(e),1,v);self.assertIn('source missing in the Layer: '+v,e[0]['message']);self.assertEqual(w,[]);self.assertFalse(r['pass'])
        (layer/'notes.md').write_text('n');(layer/'Agents').mkdir(exist_ok=True);(layer/'Agents/x.md').write_text('a')
        r,e,w=run(['notes.md','Agents/x.md']);self.assertEqual((e,w),([],[]));self.assertTrue(r['pass'],r['errors'])
        for v in ('.','./'):                                                                            # no IndexError
            r,e,w=run([v]);self.assertEqual(e,[]);self.assertEqual(len(w),1,v);self.assertIn('is not a Layer-relative',w[0]['message'])
        (self.base/'elsewhere').mkdir();outside=self.base/'elsewhere/src';oroot,_=reg.registers_fixture(outside)                         # no Flow parent: repository root unknown
        self.issues(oroot,[dict(row,sources=['nowhere/x.md'])]);ro=self.result(oroot,outside)
        self.assertEqual([x for x in ro['errors'] if 'source' in x['message']],[]);self.assertTrue(any('nowhere/x.md' in x['message'] for x in ro['warnings']))
        r,e,w=run('Context/case.yaml');self.assertTrue(any('non-empty list' in x['message'] for x in e))
        r,e,w=run([]);self.assertTrue(any('non-empty list' in x['message'] for x in e))
        self.issues(root,[row]);self.hyps(root,[hyp[0],dict(hyp[1],sources=['Context/missing.md'])])
        self.assertTrue(any('hypotheses.yaml#H2' in x['path'] and 'source missing' in x['message'] for x in self.errors(root,layer)))

class Schedule(Base):
    def setup_rows(self,root,w1=None,w2=None,period='2026-11-01〜2026-11-30',due='2026-11-15'):
        fc=lambda s,e:{'baseline':None,'forecast':{'start':s,'end':e},'actual':None,'history':[]}
        w={'deliverable':'d','exit_criteria':'e','owner':'o','status':'draft','milestone_id':'MS1'}
        base.write_yaml(root/'registers/wbs.yaml',{'wbs':[dict(w,id='W1',schedule=fc(*(w1 or ('2026-11-01','2026-11-10')))),dict(w,id='W2',depends=['W1'],schedule=fc(*(w2 or ('2026-11-05','2026-11-20'))))]})
        base.write_yaml(root/'registers/roadmap.yaml',{'roadmap':[{'id':'MS1','milestone':'m','period':period,'status':'draft','wbs_ids':['W1','W2']}]})
        self.issues(root,[{'id':'I1','question':'q','status':'open','priority':'high','owner':'PM','due':due}])
    def c8(self,root,layer):
        r=self.result(root,layer);self.assertTrue(r['pass'],r['errors'])   # warnings never change pass
        return [w for w in r['warnings'] if w['code']=='W_REGISTERS' and any(x in w['message'] for x in C8_WORDS)]

    def test_each_broken_case_warns_once(self):
        layer=self.base/'c8';root,c=reg.registers_fixture(layer)
        self.setup_rows(root);self.assertEqual(self.c8(root,layer),[])
        self.setup_rows(root,w2=('2026-11-05','2026-12-05'));w=self.c8(root,layer);self.assertEqual(len(w),1);self.assertIn('outside the period of MS1',w[0]['message']);self.assertTrue(w[0]['path'].endswith('#W2'))
        self.setup_rows(root,w2=('2026-10-30','2026-11-20'));w=self.c8(root,layer);self.assertEqual(len(w),1);self.assertIn('before the forecast.start of W1',w[0]['message'])
        self.setup_rows(root,w2=('2026-11-01','2026-11-20'));self.assertEqual(self.c8(root,layer),[])     # same start as the dependency is fine (start rule)
        self.setup_rows(root,due='2026-12-20');w=self.c8(root,layer);self.assertEqual(len(w),1);self.assertTrue(w[0]['path'].endswith('issues.yaml#I1'))

    def test_undecided_or_unreadable_is_silent(self):
        layer=self.base/'c8u';root,c=reg.registers_fixture(layer)
        for kw in [dict(period='undecided',w2=('2026-11-05','2026-12-05')),dict(period='Nov',w2=('2026-11-05','2026-12-05')),
                   dict(w2=('undecided','2026-11-20'),w1=('2026-11-03','2026-11-10')),dict(w1=('2026-11-01','undecided'),w2=('2026-11-05','undecided'),due='2026-12-20'),
                   dict(due='undecided')]:
            with self.subTest(**{k:str(v) for k,v in kw.items()}):self.setup_rows(root,**kw);self.assertEqual(self.c8(root,layer),[])

    def test_init_drafts_have_no_c8_warning(self):
        layer=self.base/'c8i';root,c=reg.registers_fixture(layer)
        self.assertEqual(self.c8(root,layer),[])
        rm=package.load(root/'registers/roadmap.yaml')['roadmap'];self.assertEqual(rm[0]['period'],'undecided')

    def test_contract_period_meaning(self):
        rc=package.load(METHOD/'registers_contract.yaml');self.assertIn('作業の期間ではない',rc['files']['roadmap']['period_meaning'])
        self.assertIn('forecast.start of a WBS it depends on',rc['schedule_warnings']['before_dependency'])

class UnknownFields(Base):
    def test_priority_unknown_warns_and_owner_is_unchanged(self):
        layer=self.base/'i3';root,c=reg.registers_fixture(layer)
        row={'id':'I1','question':'q','status':'open','priority':'[unknown]','owner':'PM','due':'2026-11-01'}
        self.issues(root,[row]);r=self.result(root,layer);self.assertTrue(r['pass'],r['errors'])
        w=[x for x in r['warnings'] if 'is still [unknown]' in x['message']];self.assertEqual([x['message'] for x in w],['priority is still [unknown]'])
        self.issues(root,[dict(row,priority='high',owner='[unknown]')]);w=[x['message'] for x in self.warnings(root,layer) if 'is still [unknown]' in x['message']]
        self.assertEqual(w,['owner is still [unknown]'])
        self.issues(root,[dict(row,priority='high')]);self.assertFalse(any('is still [unknown]' in x['message'] for x in self.warnings(root,layer)))

class PriorAnswer(Base):
    """gap.prior_answer {answer, source, asked_at}; course_contracts.yaml untouched."""
    def prepare(self,name,**kw):return base.CourseIntegration.prepare(self,name,**kw)
    def packet(self,layer,packet,gap):
        (layer/'Context/prior_answer.md').write_text('# synthetic prior answer record\n')
        packet['gaps']=[gap];base.write_yaml(layer/'Context/course_input.yaml',packet)
    def gap(self,**pa):
        g={'kind':'unknown','reason':'Synthetic: asked before drafting','requires_user':False,'prior_answer':{'answer':'synthetic answer','source':'Context/prior_answer.md','asked_at':'2026-10-22T10:00:00+09:00'}}
        g['prior_answer'].update(pa);return g

    def test_plan_and_draft_pass_with_prior_answer(self):
        layer,c,packet=self.prepare('ok');self.packet(layer,packet,self.gap())
        plan=package.course_plan(layer,'Context/course_input.yaml');self.assertEqual(plan['gaps'][0]['prior_answer']['answer'],'synthetic answer')
        root=Path(package.batch_draft(layer,'Context/course_input.yaml')['package'])
        r=validate_package.validate(root,phase='prearchive',layer=layer);self.assertTrue(r['pass'],r['errors'])
        self.assertEqual(package.load(root/'format_contract.yaml')['course_contract_sha256'],COURSE_SHA256)
        self.assertEqual(base.sha(METHOD/'course_contracts.yaml'),COURSE_SHA256)
        (layer/'Context/prior_answer.md').unlink()
        r=validate_package.validate(root,phase='prearchive',layer=layer);self.assertTrue(any(e['code']=='E_COURSE' and 'prior_answer source missing' in e['message'] for e in r['errors']))

    def test_plan_refuses_bad_prior_answer(self):
        for n,pa in enumerate([dict(source='Context/none.md'),dict(source=None),dict(source='../outside.md'),dict(answer='  '),dict(extra='x')]):
            with self.subTest(pa=pa):
                layer,c,packet=self.prepare('bad'+str(n));self.packet(layer,packet,self.gap(**pa))
                with self.assertRaises(ValueError):package.course_plan(layer,'Context/course_input.yaml')
        layer,c,packet=self.prepare('notmap');g=self.gap();g['prior_answer']='synthetic';self.packet(layer,packet,g)
        with self.assertRaises(ValueError):package.course_plan(layer,'Context/course_input.yaml')

    def test_prior_answer_alone_is_not_confirmed_actual(self):
        layer,c,packet=self.prepare('notconf')
        g=dict(self.gap(),requires_user=True,question='Which actual persona should be used?',decision_key='persona')
        packet['decisions']['persona'].update(state='confirmed_actual');self.packet(layer,packet,g)
        root=Path(package.batch_draft(layer,'Context/course_input.yaml')['package'])
        r=validate_package.validate(root,phase='prearchive',layer=layer);self.assertFalse(r['pass'])
        self.assertTrue(any(e['code']=='E_CHECKPOINT' and e['path']=='persona' for e in r['errors']))
        self.assertTrue(any(e['code']=='E_CHECKPOINT' and e['path']=='gaps' for e in r['errors']))

if __name__=='__main__':unittest.main()
