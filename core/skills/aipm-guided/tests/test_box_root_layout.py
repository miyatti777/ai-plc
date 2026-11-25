"""the box_root_v1 layout writes the 19 documents, project_init.yaml and README.md directly in
Documents/aipm_project/ (no Flow/ or Stock/ inside the package). A saved package keeps its own layout. Synthetic fixtures only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
from datetime import datetime, timezone
import tempfile, unittest
METHOD=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(METHOD));sys.path.insert(0,str(Path(__file__).resolve().parent))
import package
import test_integration as ti   # module import: its TestCase classes are not collected again here
write_yaml,sha=ti.write_yaml,ti.sha

def new_intent(layer,**aipm):
    write_yaml(layer/'intent.yaml',{'scope_id':'L-BOX','scope_name':'box_fixture','work_style':'aipm','owner':'Synthetic fixture','goal':{'description':'Synthetic layout case, no user evidence'},
                                    'aipm':{'layout':package.BOX_ROOT_LAYOUT,'project_id':'box_fixture','date':'2026-10-24','course':'document_based/single_persona','registers':True,**aipm}})

def box_root_course_layer(case,name,**aipm):
    """The course fixture of test_integration, rebuilt for the box_root_v1 layout."""
    layer,_,packet=ti.CourseIntegration.prepare(case,name)
    d=package.load(layer/'intent.yaml');d['aipm'].update(layout=package.BOX_ROOT_LAYOUT,**aipm);write_yaml(layer/'intent.yaml',d)
    c=package.build_contract(layer);b=c['bindings']
    packet['drafts']['write_init_yaml'].update(program_id=b['program_id'],flow_base=c['package_root'],stock_base=c['stock_target_rel'] or '[unknown]')
    write_yaml(layer/'Context/course_input.yaml',packet)
    return layer,c

class BoxRootLayout(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def layer(self,name,**aipm):
        layer=self.base/name;layer.mkdir();(layer/'Context').mkdir();new_intent(layer,**aipm);return layer
    def test_without_layout_a_new_package_is_sheets_also_with_shared_stock(self):
        layer=self.layer('d');d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d)
        c=package.build_contract(layer);self.assertEqual((c['layout'],c['flow_rel'],c['package_root']),(package.SHEETS_LAYOUT,'','Sheets'))   # the default
        d['aipm'].update(storage='registry_stock_v1',stock_selector={'workspace_id':'w','read_domain':'r','program_uid':'p','business_uid':'b'},aiplc_uid='u');write_yaml(layer/'intent.yaml',d)
        c=package.build_contract(layer);self.assertEqual((c['layout'],c['flow_rel'],c['stock_project_rel']),(package.SHEETS_LAYOUT,'','_charter'))   # shared Stock too
    def test_box_root_package_has_no_inner_flow_or_stock(self):
        out=package.init(self.layer('a'));root=Path(out['package']);c=out['contract']
        self.assertEqual((c['layout'],c['flow_rel'],c['stock_project_rel'],c['stock_target_rel']),(package.BOX_ROOT_LAYOUT,'','',None))
        self.assertTrue(c['version'].endswith('+box_root.1'))
        self.assertFalse((root/'Flow').exists());self.assertFalse((root/'Stock').exists())
        for name in ('project_init.yaml','README.md','registers/wbs.yaml','format_contract.yaml'):self.assertTrue((root/name).is_file(),name)
        for folder in c['folders']:self.assertTrue((root/folder).is_dir(),folder)
        self.assertEqual(package.load(root/'format_contract.yaml'),c)
        self.assertIn({'path':'Documents/aipm_project/project_init.yaml','sha256':sha(root/'project_init.yaml')},out['outputs'])
        self.assertIn({'path':'Documents/aipm_project/README.md','sha256':sha(root/'README.md')},out['outputs'])
        init_yaml=package.load(root/'project_init.yaml')
        self.assertEqual((init_yaml['program_id'],init_yaml['flow_base'],init_yaml['stock_base']),('[unknown]','Documents/aipm_project','[unknown]'))   # no L_xxxx default
        self.assertEqual({o['path'] for o in out['outputs']},{o['path'] for o in package.existing_outputs(root,c)})
    def test_explicit_program_names_the_real_stock_target(self):
        out=package.init(self.layer('p',program_id='Sample'));c=out['contract'];root=Path(out['package'])
        self.assertEqual(c['stock_target_rel'],'Stock/programs/Sample/projects/box_fixture')
        self.assertEqual(package.load(root/'project_init.yaml')['stock_base'],'Stock/programs/Sample/projects/box_fixture')
        self.assertFalse((root/'Stock').exists());self.assertFalse((self.base/'p/Stock').exists())   # init writes nothing outside the package
        for bad in ('../x','a/b'):
            with self.subTest(program=bad),self.assertRaises(ValueError):package.build_contract(self.layer('bad'+str(len(bad)),program_id=bad))
    def test_batch_draft_writes_19_documents_directly_in_the_package(self):
        layer,c=box_root_course_layer(self,'draft');root=ti.CourseIntegration.draft(self,layer)
        self.assertFalse((root/'Flow').exists());self.assertFalse((root/'Stock').exists())
        m=package.load(root/'manifest.yaml')
        self.assertEqual((m['flow_rel'],m['stock_project_rel'],m['contract_version']),('','',c['version']))
        self.assertEqual(len(m['records']),19)
        for r in m['records']:
            self.assertFalse(r['path'].startswith(('Flow/','Stock/','/')),r['path'])
            self.assertEqual(sha(root/r['path']),r['sha256'],r['path'])
        self.assertEqual({r['path'] for r in m['records']},{package.doc_rel(c,e) for e in c['documents']})
        self.assertIn('project_init.yaml',{r['path'] for r in m['records']});self.assertIn('README.md',{r['path'] for r in m['records']})
    def test_init_then_draft_continues_the_mode_init_package(self):
        """Collection Phase 7.5: init first, record mode_init, then draft continues the same package (box_root_v1)."""
        layer,c=box_root_course_layer(self,'mi');out=package.init(layer);root=Path(out['package'])
        d=package.load(layer/'intent.yaml');d['mode_init']={'state':'done','done_at':datetime.now(timezone.utc).isoformat(),'outputs':out['outputs']};write_yaml(layer/'intent.yaml',d)
        self.assertIsNotNone(package.mode_init_package(layer,root,c))
        ti.CourseIntegration.draft(self,layer)
        m=package.load(root/'manifest.yaml');self.assertEqual(m['stages'][0]['origin'],'mode_init')
        self.assertFalse((root/'Flow').exists());self.assertFalse((root/'Stock').exists())
        self.assertEqual({r['path'] for r in m['records']},{package.doc_rel(c,e) for e in c['documents']})
    def test_box_root_with_shared_stock_puts_the_charter_in_the_package(self):
        layer=self.layer('s',storage='registry_stock_v1',stock_selector={'workspace_id':'w','read_domain':'r','program_uid':'p','business_uid':'b'},aiplc_uid='u')
        c=package.build_contract(layer);self.assertEqual((c['flow_rel'],c['stock_project_rel'],c['stock_target_rel']),('','_charter',None))
        self.assertEqual(package.init_roots(c),('Documents/aipm_project','Documents/aipm_project/_charter'))
        self.assertFalse((layer/'Documents').exists())   # build_contract writes nothing

class SavedLayoutIsKept(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_saved_nested_package_stays_nested_without_layout_in_intent(self):
        layer=self.base/'old';layer.mkdir();new_intent(layer,layout=package.NESTED_LAYOUT);out=package.init(layer);root=Path(out['package'])
        fc=(root/'format_contract.yaml').read_bytes()
        self.assertNotIn('layout',out['contract']);self.assertTrue((root/out['contract']['flow_rel']).is_dir())
        new_intent(layer);d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d)   # the existing packages (and the others) have no aipm.layout
        self.assertEqual(package.build_contract(layer),out['contract'])
        again=package.init(layer);self.assertFalse(again['created']);self.assertEqual((root/'format_contract.yaml').read_bytes(),fc)
    def test_explicit_layout_differing_from_the_saved_one_stops(self):
        layer=self.base/'mix';layer.mkdir();new_intent(layer);package.init(layer)
        d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d)
        self.assertEqual(package.build_contract(layer)['layout'],package.BOX_ROOT_LAYOUT)   # the saved layout wins over the default
        new_intent(layer,layout=package.NESTED_LAYOUT)
        with self.assertRaises(ValueError):package.build_contract(layer)
        new_intent(layer,layout=package.BOX_ROOT_LAYOUT);self.assertEqual(package.build_contract(layer)['layout'],package.BOX_ROOT_LAYOUT)
    def test_unknown_layout_value_stops(self):
        layer=self.base/'bad';layer.mkdir();new_intent(layer,layout='flat')
        with self.assertRaises(ValueError):package.init(layer)
        self.assertFalse((layer/'Documents').exists())

if __name__=='__main__':unittest.main()
