"""AIPM ライトモード (aipm-light): the WBS and TODO sheets only, as one form of aipm-guided.
Synthetic fixtures only. Each test makes its own temporary Layer."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import hashlib, json, subprocess, tempfile, unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_integration as base
package=base.package;validate_package=base.validate_package;METHOD=base.METHOD
sys.path.insert(0,str(METHOD))
import light, ops

LIGHT_ENTRY={'addon_id':'aipm-light','source':'bundled','addon_version':'0.1','selection_ref':'Context/aipm_recommendation/default_method.json'}

def inventory(layer):
    return {str(p.relative_to(layer)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(layer).rglob('*')) if p.is_file()}

class Light(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def layer(self,name='L',addons=None,**extra):
        layer=self.base/name;(layer/'Context/aipm_recommendation').mkdir(parents=True);(layer/'Documents').mkdir()
        (layer/'Context/aipm_recommendation/default_method.json').write_text(json.dumps({'kind':'default_on_no_answer','choice':'aipm-light'}))
        base.write_yaml(layer/'intent.yaml',{'scope_id':'L-SYN-LIGHT','scope_name':'light','owner':'Synthetic fixture','goal':{'description':'synthetic'},'addons':addons if addons is not None else [dict(LIGHT_ENTRY)],**extra})
        base.write_yaml(layer/'backlog.yaml',{'tasks':[]})
        return layer
    def inp(self,layer,name,data):base.write_yaml(layer/'Context'/name,data);return 'Context/'+name

    def test_init_makes_the_record_and_two_sheets_only(self):
        layer=self.layer();r=package.init(layer)
        self.assertEqual((r['route'],r['created']),('aipm-light',True))
        files=sorted(p.name for p in (layer/'Sheets').iterdir())
        self.assertEqual(files,['format_contract.yaml','todo.yaml','wbs.yaml'])   # no 19 documents, issues, hypotheses, roadmap
        self.assertEqual(package.load(layer/'Sheets/todo.yaml'),{'todo':[]});self.assertEqual(package.load(layer/'Sheets/wbs.yaml'),{'wbs':[]})
        self.assertEqual([o['path'] for o in r['outputs']],['Sheets/format_contract.yaml','Sheets/todo.yaml','Sheets/wbs.yaml'])
        before=inventory(layer);again=package.init(layer)
        self.assertFalse(again['created']);self.assertEqual(before,inventory(layer))   # never overwrites
        v=validate_package.validate(layer/'Sheets',layer=layer);self.assertTrue(v['pass'],v);self.assertEqual(v['route'],'aipm-light')

    def test_cli_light_flag(self):
        layer=self.layer()
        out=subprocess.run([sys.executable,str(METHOD/'package.py'),'init','--layer',str(layer),'--light','--brief'],capture_output=True,text=True)
        self.assertEqual(out.returncode,0,out.stdout+out.stderr);self.assertTrue(json.loads(out.stdout)['created'])
        v=subprocess.run([sys.executable,str(METHOD/'validate_package.py'),'--layer',str(layer)],capture_output=True,text=True)
        self.assertEqual(v.returncode,0,v.stdout)
        other=self.base/'aipm';base.fixture(other)
        bad=subprocess.run([sys.executable,str(METHOD/'package.py'),'init','--layer',str(other),'--light'],capture_output=True,text=True)
        self.assertEqual(bad.returncode,1);self.assertIn('--light',json.loads(bad.stdout)['error'])

    def test_collisions_stop_and_write_nothing(self):
        for setup in ('legacy_package','other_use','case_folder'):
            with self.subTest(setup=setup):
                layer=self.layer(setup)
                if setup=='legacy_package':(layer/'Documents/aipm_project').mkdir()
                if setup=='other_use':(layer/'Sheets').mkdir();(layer/'Sheets/notes.md').write_text('x')
                if setup=='case_folder':(layer/'sheets').mkdir()
                before=inventory(layer)
                with self.assertRaises(ValueError):package.init(layer)
                self.assertEqual(before,inventory(layer))

    def test_validate_reference_fields_and_rows(self):
        layer=self.layer();package.init(layer)
        base.write_yaml(layer/'Sheets/wbs.yaml',{'wbs':[{'id':'W1','deliverable':'d','exit_criteria':'e','owner':'[unknown]','status':'draft','issue_ids':['I1'],'milestone_id':'MS1'}]})
        base.write_yaml(layer/'Sheets/todo.yaml',{'todo':[{'id':'D1','title':'t','status':'todo','owner':'[unknown]','source':'H2','wbs_id':'W9'},{'id':'D2','title':'t','status':'todo','owner':'[unknown]','source':'定例会議'}]})
        v=validate_package.validate(layer/'Sheets',layer=layer);codes=[(e['code'],e['message'].split(' ')[0]) for e in v['errors']]
        self.assertFalse(v['pass'])
        self.assertIn(('E_LIGHT','issue_ids'),codes);self.assertIn(('E_LIGHT','milestone_id'),codes);self.assertIn(('E_LIGHT','source'),codes)
        self.assertIn(('E_REGISTERS','wbs_id'),codes)
        self.assertNotIn('Sheets/todo.yaml#D2',[e['path'] for e in v['errors']])   # a meeting name is fine
        base.write_yaml(layer/'Sheets/wbs.yaml',{'wbs':[{'id':'W1','deliverable':'d','exit_criteria':'e','owner':'o','status':'accepted'}]})
        base.write_yaml(layer/'Sheets/todo.yaml',{'todo':[]})
        v=validate_package.validate(layer/'Sheets',layer=layer);self.assertIn('accepted needs evidence_refs',[e['message'] for e in v['errors']])

    def test_pm_todo_works_on_the_light_sheets(self):
        layer=self.layer();package.init(layer)
        base.write_yaml(layer/'Sheets/wbs.yaml',{'wbs':[{'id':'W1','deliverable':'d','exit_criteria':'e','owner':'[unknown]','status':'draft'}]})
        self.assertEqual(ops.run(layer,'check')['light'],'aipm_light')
        r=ops.run(layer,'todo.add',self.inp(layer,'t.yaml',{'title':'見積を送る','source':'定例会議','due':'2026-10-01'}),apply=True)
        self.assertTrue(r['applied'],r)
        ops.run(layer,'todo.link',self.inp(layer,'l.yaml',{'id':'D1','wbs_id':'W1'}),apply=True)
        row=package.load(layer/'Sheets/todo.yaml')['todo'][0];self.assertEqual((row['owner'],row['wbs_id']),('[unknown]','W1'))   # owner is not guessed
        bad=ops.run(layer,'todo.link',self.inp(layer,'b.yaml',{'id':'D1','source':'I1'}),apply=True)
        self.assertFalse(bad['applied']);self.assertTrue(bad['new_problems'])   # I/H ids are not used in the light sheets
        self.assertEqual([x['id'] for x in ops.run(layer,'todo.overdue',self.inp(layer,'d.yaml',{'today':'2026-10-30'}))['overdue']],['D1'])
        held=ops.run(layer,'issue.add',self.inp(layer,'i.yaml',{'question':'q','priority':'high'}))
        self.assertEqual(held['route'],'held')
        st=ops.init_status(layer);self.assertEqual(st['state'],'light')

    def test_wbs_candidate_on_the_light_sheets(self):
        layer=self.layer();package.init(layer)
        base.write_yaml(layer/'Sheets/wbs.yaml',{'wbs':[{'id':'W1','deliverable':'d','exit_criteria':'e','owner':'[unknown]','status':'draft'}]})
        (layer/'Documents/out.md').write_text('x')
        base.write_yaml(layer/'backlog.yaml',{'tasks':[{'id':'T1','status':'completed','wbs_id':'W1','output':['Documents/out.md']}]})
        r=package.wbs_candidate(layer,'T1')
        self.assertEqual((r['route'],r['status']),('aipm-light','pending_acceptance'))
        self.assertTrue(validate_package.validate(layer/'Sheets',layer=layer)['pass'])

    def test_add_sheets_to_an_aipm_layer_without_registers(self):
        layer=self.base/'A';root,c=base.fixture(layer);self.assertNotIn('registers_contract_version',c)   # nested_v1: the package is Documents/aipm_project, Sheets/ is new
        before=inventory(layer)
        plan=light.add_sheets(layer);self.assertEqual(before,inventory(layer));self.assertEqual(plan['planned'],['Sheets/light_sheets.yaml','Sheets/todo.yaml','Sheets/wbs.yaml'])
        done=light.add_sheets(layer,apply=True);self.assertTrue(done['changed'])
        after=inventory(layer)
        self.assertEqual({k:v for k,v in after.items() if k in before},before)   # the aipm package is unchanged
        self.assertEqual(sorted(set(after)-set(before)),['Sheets/light_sheets.yaml','Sheets/todo.yaml','Sheets/wbs.yaml'])
        v=validate_package.validate(root,layer=layer);self.assertTrue(v['pass'],v['errors']);self.assertIn('light_sheets_summary',v)
        self.assertEqual(ops.run(layer,'check')['light'],'aipm_sheets')
        self.assertTrue(ops.run(layer,'todo.add',self.inp(layer,'t.yaml',{'title':'合成'}),apply=True)['applied'])
        self.assertFalse(light.add_sheets(layer,apply=True)['changed'])   # second run writes nothing
        reg=self.base/'R';base.fixture(reg)
        intent=package.load(reg/'intent.yaml');intent['aipm']['registers']=True;base.write_yaml(reg/'intent.yaml',intent)
        self.assertFalse(light.add_sheets(reg)['changed'])   # registers already hold todo and wbs
        with self.assertRaises(ValueError):light.add_sheets(self.layer('X'))   # not an aipm Layer

    def test_switch_light_to_aipm_keeps_the_sheets(self):
        layer=self.layer(project_id='light');package.init(layer)
        rows={'todo':[{'id':'D1','title':'残す','status':'todo','owner':'[unknown]'}]}
        base.write_yaml(layer/'Sheets/todo.yaml',rows);kept=(layer/'Sheets/todo.yaml').read_bytes()
        it=package.load(layer/'intent.yaml');it['addons']=[]
        it['work_style']='aipm';it['aipm']={'registers':True,'layout':'sheets_v1','project_id':'light','program_id':'Sample','date':'2026-10-07'}
        base.write_yaml(layer/'intent.yaml',it)
        r=package.init(layer)
        self.assertTrue(r['created']);self.assertEqual(r['adopted_light_sheets'],['Sheets/todo.yaml','Sheets/wbs.yaml'])
        self.assertEqual((layer/'Sheets/todo.yaml').read_bytes(),kept)   # the sheet becomes part of the registers as it is
        for n in ('issues.yaml','hypotheses.yaml','roadmap.yaml','project_init.yaml','README.md'):self.assertTrue((layer/'Sheets'/n).is_file(),n)
        self.assertEqual(package.load(layer/'Sheets/format_contract.yaml')['registers_contract_version'],4)
        self.assertTrue((layer/'Context/aipm_light_retired/format_contract.yaml').is_file())

    def test_switch_failure_moves_nothing(self):
        """Every check runs before the light record moves; a refused switch leaves the Layer as it was."""
        layer=self.layer(project_id='light');package.init(layer)
        it=package.load(layer/'intent.yaml');it['addons']=[];it['work_style']='aipm'
        it['aipm']={'registers':True,'layout':'sheets_v1','project_id':'light','program_id':'Sample','date':'2026-10-07'}
        base.write_yaml(layer/'intent.yaml',it);base.write_yaml(layer/'Context/d.yaml',{'wbs':[{'deliverable':'d','exit_criteria':'e','source_refs':['Context/d.yaml']}]})
        before=inventory(layer)
        with self.assertRaises(ValueError):package.init(layer,drafts='Context/d.yaml')
        self.assertEqual(before,inventory(layer))
        r=package.init(layer);self.assertTrue(r['created'])
        self.assertTrue({'Sheets/todo.yaml','Sheets/wbs.yaml'}<={o['path'] for o in r['outputs']})

    def test_leftover_light_record_is_not_light(self):
        """Without aipm-light in intent, a leftover record does not let pm-todo or wbs-candidate write."""
        layer=self.layer();package.init(layer)
        it=package.load(layer/'intent.yaml');it.pop('addons');base.write_yaml(layer/'intent.yaml',it)
        self.assertEqual(ops.run(layer,'check')['route'],'unselected')
        before=inventory(layer)
        self.assertNotEqual(ops.run(layer,'todo.add',self.inp(layer,'t.yaml',{'title':'x'}),apply=True).get('applied'),True)
        self.assertEqual({k:v for k,v in inventory(layer).items() if k!='Context/t.yaml'},before)

    def test_add_sheets_on_sheets_v1_and_registers_turned_on(self):
        """A sheets_v1 aipm Layer gets the sheets beside its package; turning on registers over them stops."""
        repo=self.base/'repo';(repo/'Stock/programs/Sample').mkdir(parents=True)
        layer=repo/'Flow/202610/2026-10-07/S';layer.parent.mkdir(parents=True)
        root,c=base.fixture(layer,layout='sheets_v1');self.assertEqual(c['package_root'],'Sheets')
        before=inventory(layer)
        light.add_sheets(layer,apply=True)
        after=inventory(layer)
        self.assertEqual({k:v for k,v in after.items() if k in before},before)
        self.assertEqual(sorted(set(after)-set(before)),['Sheets/light_sheets.yaml','Sheets/todo.yaml','Sheets/wbs.yaml'])
        errs=[e for e in validate_package.validate(root,layer=layer,phase='prearchive')['errors'] if e['code'] in ('E_LIGHT','E_REGISTERS')]
        self.assertEqual(errs,[])
        it=package.load(layer/'intent.yaml');it['aipm']['registers']=True;base.write_yaml(layer/'intent.yaml',it)
        snap=inventory(layer)
        with self.assertRaises(ValueError):package.init(layer)
        self.assertEqual(snap,inventory(layer))

    def test_symlinked_sheets_are_refused(self):
        layer=self.layer();outside=self.base/'outside';outside.mkdir();(layer/'Sheets').symlink_to(outside)
        with self.assertRaises(ValueError):package.init(layer)
        self.assertEqual(list(outside.iterdir()),[])

    def test_aipm_regression_unchanged(self):
        layer=self.base/'N';root,c=base.fixture(layer)
        self.assertTrue(validate_package.validate(root,layer=layer)['pass'])
        self.assertIsNone(light.record(layer)[0])

if __name__=='__main__':unittest.main()
