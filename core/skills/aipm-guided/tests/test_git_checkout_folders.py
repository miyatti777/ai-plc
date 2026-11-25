"""a box taken out again from git (no empty folders) is not refused for its folders; a
missing document still is. Both layouts, the course and the legacy fixtures. Synthetic fixtures only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import tempfile, unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import test_integration as ti
package=ti.package;validate_package=ti.validate_package;write_yaml=ti.write_yaml

def drop_empty_folders(root):
    """What git does: an empty folder is not kept (deepest first)."""
    for q in sorted((q for q in root.rglob('*') if q.is_dir()),key=lambda q:len(q.parts),reverse=True):
        if not any(q.iterdir()):q.rmdir()

def codes(layer,root,phase):
    return {(e['code'],e['path']) for e in validate_package.validate(root,phase=phase,layer=layer)['errors']}

class FoldersAreNotRequired(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.repo=Path(self.temp.name)
        self.base=self.repo/'Flow/202610/2026-10-24';self.base.mkdir(parents=True);(self.repo/'Stock/programs/Sample').mkdir(parents=True)
    def tearDown(self):self.temp.cleanup()
    def boxes(self):
        """(name, layer, root, phase to compare) for the legacy fixture (archived, final) and the course draft (prearchive), both layouts."""
        out=[]
        for layout in (package.NESTED_LAYOUT,package.BOX_ROOT_LAYOUT,package.SHEETS_LAYOUT):
            layer=self.base/('legacy-'+layout);root,c=ti.fixture(layer,layout=layout);out.append(('legacy '+layout,layer,root,'final'))
            case=type('Case',(),{})();case.base=self.base
            layer,_,packet=ti.CourseIntegration.prepare(case,'course-'+layout)
            d=package.load(layer/'intent.yaml');d['aipm']['layout']=layout;write_yaml(layer/'intent.yaml',d)
            c=package.build_contract(layer);flow_base,stock_base=package.init_roots(c);b=c['bindings']
            packet['drafts']['write_init_yaml'].update(program_id=b['program_id'],project_id=b['project_id'],flow_dir=b['flow_dir'],flow_base=flow_base,stock_base=stock_base)
            write_yaml(layer/'Context/course_input.yaml',packet)
            root=ti.CourseIntegration.draft(case,layer);out.append(('course '+layout,layer,root,'prearchive'))
        return out
    def test_empty_folders_gone_gives_the_same_result(self):
        for name,layer,root,phase in self.boxes():
            with self.subTest(box=name):
                before=codes(layer,root,phase)
                self.assertFalse(any(code=='E_MISSING' for code,_ in before),before)
                drop_empty_folders(root)
                self.assertEqual(codes(layer,root,phase),before)
    def test_a_missing_document_is_still_refused(self):
        for name,layer,root,phase in self.boxes():
            with self.subTest(box=name):
                c=package.build_contract(layer)
                for e in c['documents']:   # each of the 19, one at a time (moved aside and back)
                    q=root/package.doc_rel(c,e);aside=q.with_name(q.name+'.aside');q.rename(aside)
                    try:self.assertIn(('E_MISSING',package.doc_rel(c,e)),codes(layer,root,'prearchive'),e['path'])
                    finally:aside.rename(q)

if __name__=='__main__':unittest.main()
