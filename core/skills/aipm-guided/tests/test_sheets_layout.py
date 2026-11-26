"""the sheets_v1 layout. The package is <Layer>/Sheets/ (beside Context/ and Documents/), with the
step folders, the registers yaml (no registers/ folder) and the management files on one level. The course, reset and
archive tests of test_integration / test_init_and_reset run again on sheets_v1 packages in a synthetic repository, and
the earlier layouts keep working. Synthetic fixtures only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import unittest
METHOD=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(METHOD));sys.path.insert(0,str(Path(__file__).resolve().parent))
import package, validate_package
import test_integration as ti, test_init_and_reset as tr, test_box_root_compat as bc
import test_archive_business as tab, test_archive_business_changes as tabc, test_move_archive as tma, test_shared_stock_integration as tss
import test_registers as treg, test_registers_v2 as treg2, test_ops as tops
import registry_fixture as rf
write_yaml,sha=ti.write_yaml,ti.sha
REGISTERS=('issues','hypotheses','todo','wbs','roadmap')

def sheets_prepare(self,name='new',course='document_based/single_persona',pending=False,reuse=False,**aipm):
    """CourseIntegration.prepare with aipm.layout sheets_v1 and program Sample (and the project_init roots of that layout)."""
    layer,_,packet=ti.CourseIntegration.prepare(self,name,course,pending,reuse)
    aipm.setdefault('program_id','Sample');aipm.setdefault('project_id','course_'+name)
    d=package.load(layer/'intent.yaml');d['aipm'].update(layout=package.SHEETS_LAYOUT,**aipm)
    if d['aipm']['program_id'] is None:d['aipm'].pop('program_id')
    write_yaml(layer/'intent.yaml',d)
    c=package.build_contract(layer);flow_base,stock_base=package.init_roots(c)
    b=c['bindings'];packet['drafts']['write_init_yaml'].update(program_id=b['program_id'],project_id=b['project_id'],flow_dir=b['flow_dir'],flow_base=flow_base,stock_base=stock_base)
    write_yaml(layer/'Context/course_input.yaml',packet);return layer,c,packet

class SheetsCourse(ti.CourseIntegration):
    setUp=bc.in_repository;prepare=sheets_prepare
    test_contract_provenance_and_unknown_branch_refused=None   # checks the nested_v1 version string; sheets adds +sheets.1

class SheetsReset(tr.ResetToInit):
    setUp=bc.in_repository;prepare=sheets_prepare;mode_init_layer=ti.CourseIntegration.mode_init_layer

class SheetsShape(unittest.TestCase):
    setUp=bc.in_repository
    def tearDown(self):self.temp.cleanup()
    prepare=sheets_prepare;draft=ti.CourseIntegration.draft
    def registers_layer(self,name,**aipm):
        layer=tr.new_layer(self.base,name)   # registers: true, a document course
        d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');d['aipm'].update(**aipm);write_yaml(layer/'intent.yaml',d)   # no aipm.layout = the default
        return layer

    def test_default_package_is_sheets_on_one_level(self):
        layer=self.registers_layer('one');out=package.init(layer);root=Path(out['package']);c=out['contract']
        self.assertEqual((c['layout'],c['package_root'],c['flow_rel'],c['stock_project_rel']),(package.SHEETS_LAYOUT,'Sheets','',''))
        self.assertTrue(c['version'].endswith('+sheets.1'))
        self.assertEqual(root,layer/'Sheets');self.assertFalse((layer/'Documents/aipm_project').exists())
        for inner in ('Flow','Stock','registers'):self.assertFalse((root/inner).exists(),inner)
        for name in REGISTERS:self.assertTrue((root/(name+'.yaml')).is_file(),name)   # the registers beside the step folders
        for name in ('project_init.yaml','README.md','format_contract.yaml'):self.assertTrue((root/name).is_file(),name)
        for folder in c['folders']:self.assertTrue((root/folder).is_dir(),folder)
        self.assertEqual(package.load(root/'format_contract.yaml'),c)
        self.assertTrue(all(o['path'].startswith('Sheets/') for o in out['outputs']),out['outputs'])
        self.assertIn({'path':'Sheets/issues.yaml','sha256':sha(root/'issues.yaml')},out['outputs'])
        self.assertEqual(package.registers_contract(c)['files']['wbs']['path'],'wbs.yaml')

    def test_registers_contract_paths_only_change_for_sheets(self):
        for layout,want in ((package.SHEETS_LAYOUT,'issues.yaml'),(package.BOX_ROOT_LAYOUT,'registers/issues.yaml'),(package.NESTED_LAYOUT,'registers/issues.yaml')):
            with self.subTest(layout=layout):
                layer=self.registers_layer('r'+layout.replace('_',''),layout=layout,**({'program_id':'Sample'} if layout!=package.NESTED_LAYOUT else {}))
                c=package.build_contract(layer);self.assertEqual(package.registers_contract(c)['files']['issues']['path'],want)
                self.assertEqual(c['package_root'],'Sheets' if layout==package.SHEETS_LAYOUT else 'Documents/aipm_project')

    def test_earlier_layouts_are_still_made_when_asked_and_read_as_they_are(self):
        for layout in (package.BOX_ROOT_LAYOUT,package.NESTED_LAYOUT):
            with self.subTest(layout=layout):
                layer=self.registers_layer('e'+layout.replace('_',''),layout=layout,**({'program_id':'Sample'} if layout==package.BOX_ROOT_LAYOUT else {}))
                out=package.init(layer);root=Path(out['package'])
                self.assertEqual(root,layer/'Documents/aipm_project');self.assertFalse((layer/'Sheets').exists())
                self.assertTrue(ti.reg(root,'issues').is_file());self.assertIn('registers',ti.reg(root,'issues').relative_to(root).parts)
                d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d)   # the saved layout wins over the new default
                self.assertEqual(package.build_contract(layer).get('layout',package.NESTED_LAYOUT),layout)   # nested_v1 has no layout key

    def test_ambiguous_packages_stop_and_write_nothing(self):
        def both(case):
            layer=case.registers_layer('both');package.init(layer)
            q=layer/'Documents/aipm_project';q.mkdir(parents=True);(q/'format_contract.yaml').write_bytes((layer/'Sheets/format_contract.yaml').read_bytes());return layer
        def other_case(case):   # a package folder sheets/ (with its contract) that differs from Sheets/ only in case
            layer=case.registers_layer('case');(layer/'sheets').mkdir();(layer/'sheets/format_contract.yaml').write_text('layout: sheets_v1\n');return layer
        def earlier_folder(case):
            layer=case.registers_layer('early');(layer/'Documents/aipm_project').mkdir(parents=True);return layer
        def moved_contract(case):   # a saved contract in Sheets/ that says box_root_v1
            layer=case.registers_layer('moved',layout=package.BOX_ROOT_LAYOUT,program_id='Sample');package.init(layer)
            (layer/'Documents/aipm_project').rename(layer/'Sheets');return layer
        for build,pattern in ((both,'both'),(other_case,'another case'),(earlier_folder,'already in the Layer'),(moved_contract,'does not match its layout')):
            with self.subTest(case=build.__name__):
                layer=build(self);before=tr.state(layer)
                with self.assertRaisesRegex(ValueError,pattern):package.init(layer)
                self.assertEqual(tr.state(layer),before)

    def test_explicit_sheets_against_a_saved_earlier_package_stops(self):
        layer=self.registers_layer('x',layout=package.BOX_ROOT_LAYOUT,program_id='Sample');package.init(layer)
        d=package.load(layer/'intent.yaml');d['aipm']['layout']=package.SHEETS_LAYOUT;write_yaml(layer/'intent.yaml',d)
        with self.assertRaisesRegex(ValueError,'differs from the saved package layout'):package.build_contract(layer)

    def test_validate_cli_finds_the_sheets_package(self):
        layer,c,packet=self.prepare('cli');root=self.draft(layer)
        import subprocess,json
        p=subprocess.run([sys.executable,'-B',str(METHOD/'validate_package.py'),'--layer',str(layer),'--phase','prearchive'],capture_output=True,text=True)
        r=json.loads(p.stdout);self.assertTrue(r['pass'],r['errors']);self.assertEqual(root,layer/'Sheets')

class SheetsArchive(unittest.TestCase):
    setUp=bc.in_repository
    def tearDown(self):self.temp.cleanup()
    prepare=sheets_prepare;draft=ti.CourseIntegration.draft
    def test_archive_copies_the_documents_only_and_final_passes(self):
        layer,c,packet=self.prepare('a');root=self.draft(layer);self.assertEqual(root,layer/'Sheets')
        result=package.archive_course(layer);self.assertTrue(result['pass'],result['errors'])
        target=self.repo/'Stock/programs/Sample/projects'/rf.BUSINESS/'course_a/documents'
        m=package.load(root/'manifest.yaml')
        for r in m['records']:
            if r['stage']=='init':self.assertIsNone(r['archive_path']);continue
            q=self.repo/r['archive_path'];self.assertEqual(q.read_bytes(),(root/r['path']).read_bytes())
        self.assertEqual(sum(1 for q in target.rglob('*') if q.is_file()),17)   # the same Stock shape as box_root_v1
        self.assertFalse((root/'Stock').exists())
        self.assertTrue(validate_package.validate(root,phase='final',layer=layer)['pass'])

class SheetsReceipt(unittest.TestCase):
    """package.receipt binds the persona and validation answers to a sheets_v1 package (the target path is in Sheets/)."""
    def setUp(self):import tempfile;self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    prepare=sheets_prepare;draft=ti.CourseIntegration.draft
    def test_receipt_binds_persona_and_validation_on_sheets(self):
        layer,c,packet=self.prepare('rc',pending=True)
        packet['decisions']['validation']={'state':'pending','reason':'Choosing validation hypotheses is the user call','scope':'reversible_draft_only','source_ids':['M1','M2'],'question':'Use H1 for validation?'}
        for key in ('persona','validation'):packet['gaps'].append({'kind':'unknown','reason':'needs the user','requires_user':True,'decision_key':key,'question':'?'})
        write_yaml(layer/'Context/course_input.yaml',packet);root=self.draft(layer);self.assertEqual(root,layer/'Sheets')
        def ask(name,**over):
            d={'stage':'persona','question':'Which actual persona should be used?','answer':'Synthetic reply only','question_id':'SYN-'+name,'source_thread_id':'SYNTHETIC-THREAD','answered_at':ti.now()};d.update(over)
            write_yaml(layer/'Context'/(name+'.yaml'),d);return 'Context/'+name+'.yaml'
        r=package.receipt(layer,ask('p'));self.assertTrue(r['bound'])
        m=package.load(root/'manifest.yaml');persona=next(x for x in m['records'] if x['source_step']=='generate_persona_md')
        self.assertEqual(package.load(layer/r['receipt'])['target_path'],'Sheets/'+persona['path'])
        v=package.load(root/'validation_record.yaml');write_yaml(root/'validation_checkpoint.yaml',{k:x for k,x in v.items() if k!='actual_new_user_response'})
        r=package.receipt(layer,ask('v',stage='validation',question='Use H1 for validation?',answered_at=ti.now()));self.assertTrue(r['pass'],r)
        self.assertTrue(validate_package.validate(root,phase='prearchive',layer=layer)['pass'])

class SheetsImpact(unittest.TestCase):
    """pm- hypothesis.impact reads only the package (Sheets/), not the Layer around it, and does not list the registers."""
    setUp=bc.in_repository
    def tearDown(self):self.temp.cleanup()
    def test_impact_stays_inside_the_package(self):
        import ops
        layer=tr.new_layer(self.base,'imp');d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d)
        root=Path(package.init(layer)['package']);self.assertEqual(root,layer/'Sheets')
        (layer/'Documents').mkdir(exist_ok=True);(layer/'Documents/note.md').write_text('H1 outside the package\n');(layer/'Context/in.yaml').write_text('ref: H1\n')
        (root/'01_ペルソナ作成/memo.md').write_text('mentions H1\n')
        h=package.load(root/'hypotheses.yaml');h['hypotheses'][0]['status']='not_supported';write_yaml(root/'hypotheses.yaml',h)
        imp=ops.run(layer,'hypothesis.impact')
        docs=[x for i in imp['impact'] for x in i.get('documents',[])]
        self.assertIn('01_ペルソナ作成/memo.md',docs)
        self.assertFalse(any(x.startswith(('Context/','Documents/','../')) or x=='hypotheses.yaml' for x in docs),docs)

def sheets_archive_prepare(self,name='new',**kw):
    return sheets_prepare(self,name,**kw)
class SheetsArchiveUnderBusiness(tab.ArchiveUnderBusiness):prepare=sheets_archive_prepare
class SheetsArchiveAfterBusinessChanges(tabc.ArchiveAfterBusinessChanges):prepare=sheets_archive_prepare
class SheetsMoveArchive(tma.MoveArchive):prepare=sheets_archive_prepare
class SheetsSharedFlow(tss.SharedFlow):LAYOUT=package.SHEETS_LAYOUT

def sheets_registers_setup(case):
    """A synthetic repository, and registers_fixture making sheets_v1 packages (with program Sample) while the test runs."""
    bc.in_repository(case);old=treg.DEFAULT_LAYOUT;treg.DEFAULT_LAYOUT=package.SHEETS_LAYOUT
    case.addCleanup(setattr,treg,'DEFAULT_LAYOUT',old)
class SheetsRegisters(treg.Registers):setUp=sheets_registers_setup
class SheetsRegistersVersion(treg2.Version):setUp=sheets_registers_setup
# treg2.Sources is not run on sheets_v1: its 'outside the repository' case cannot be built for the flat layouts (they
# archive into the repository Stock). The registers it reads are found through the contract (registers_layout) like in
# every other check run here; the source paths themselves are Layer- or repository-relative.
class SheetsRegistersSchedule(treg2.Schedule):setUp=sheets_registers_setup
class SheetsRegistersUnknownFields(treg2.UnknownFields):setUp=sheets_registers_setup
# treg2.PriorAnswer is not run on sheets_v1: it builds its Layer with base.CourseIntegration.prepare, which writes
# nested_v1 into the intent (the prior-answer check reads the course decisions, not the registers' place).

def sheets_ops_layer(self,name='L'):
    layer=self.base/name;root,c=treg.registers_fixture(layer,layout=package.SHEETS_LAYOUT);return layer,root
def sheets_ops_setup(case):
    """sheets_registers_setup, with the stop of pm- writes on a saved box switched off: registers_fixture makes an
    archived box, and these tests are about the pm- write mechanics (the stop is tested in test_registers_edit)."""
    sheets_registers_setup(case)
    import register_edits
    from unittest import mock
    pt=mock.patch.object(register_edits,'saved_versionable',return_value=False);pt.start();case.addCleanup(pt.stop)
class SheetsOps(tops.Ops):
    setUp=sheets_ops_setup;layer=sheets_ops_layer;LAYOUT=package.SHEETS_LAYOUT
    def test_cli(self):
        """The CLI runs in another process, where registers_fixture's archived box is a saved box: since pm- writes
        stop there, and issue.resolve still goes on to its own checks."""
        import json, subprocess, sys
        layer,root=self.layer();ref=self.inp(layer,'i.yaml',{'question':'CLI の問い'})
        run=lambda *a:json.loads(subprocess.run([sys.executable,'-B',str(package.METHOD/'package.py'),'op','--layer',str(layer),*a],capture_output=True,text=True).stdout)
        self.assertEqual(run('--name','check')['route'],'selected')
        out=run('--name','issue.add','--input',ref,'--apply');self.assertEqual(out['route'],'held');self.assertIn('redit',out['reason'])
        bad=run('--name','issue.resolve','--input',self.inp(layer,'r.yaml',{'id':'I1','answer':'x','evidence_refs':['H1'],'decided_by':'owner'}))
        self.assertFalse(bad['pass']);self.assertIn('judge',bad['error'])
class SheetsOpsRest(tops.OpsRest):setUp=sheets_registers_setup;layer=sheets_ops_layer;LAYOUT=package.SHEETS_LAYOUT

class FixtureIsSheets(unittest.TestCase):
    setUp=bc.in_repository
    def tearDown(self):self.temp.cleanup()
    def test_fixture_is_a_sheets_package_that_passes_final(self):
        layer=self.base/'fx';root,c=treg.registers_fixture(layer,layout=package.SHEETS_LAYOUT)
        self.assertEqual((root,package.load(root/'format_contract.yaml')['layout']),(layer/'Sheets',package.SHEETS_LAYOUT))
        self.assertFalse((root/'registers').exists());self.assertTrue((root/'hypotheses.yaml').is_file())
        self.assertTrue(validate_package.validate(root,phase='final',layer=layer)['pass'])

if __name__=='__main__':unittest.main()
