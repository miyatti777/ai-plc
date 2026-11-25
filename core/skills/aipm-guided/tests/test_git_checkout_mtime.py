"""file mtimes are not used for documents and sources (C2/C4/C5/C6). A box whose files all
got new mtimes (as a git checkout does) gives the same pass and errors plus one W_MTIME; forgeries bound by sha256 still
stop; the forgeries the owner accepted (choice 2: rewriting the manifest too) pass. Synthetic fixtures only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import os, tempfile, time, unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import test_integration as ti
package=ti.package;validate_package=ti.validate_package;write_yaml,sha=ti.write_yaml,ti.sha

def touch_all(top):
    """What a checkout does to mtimes: every file gets a new one."""
    now=time.time_ns()+5_000_000_000
    for q in top.rglob('*'):
        if q.is_file():os.utime(q,ns=(now,now))

def result(layer,root,phase='prearchive'):
    r=validate_package.validate(root,phase=phase,layer=layer)
    return r['pass'],sorted({(e['code'],e['path']) for e in r['errors']}),[w for w in r['warnings'] if w['code']=='W_MTIME']

class MtimeIsNotEvidence(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def course(self,name,layout,reuse=False):
        layer,_,packet=ti.CourseIntegration.prepare(self,name,reuse=reuse)
        d=package.load(layer/'intent.yaml');d['aipm']['layout']=layout;write_yaml(layer/'intent.yaml',d)
        c=package.build_contract(layer);flow_base,stock_base=package.init_roots(c);b=c['bindings']
        packet['drafts']['write_init_yaml'].update(program_id=b['program_id'],project_id=b['project_id'],flow_dir=b['flow_dir'],flow_base=flow_base,stock_base=stock_base)
        write_yaml(layer/'Context/course_input.yaml',packet)
        return layer,ti.CourseIntegration.draft(self,layer),c
    def layouts(self):return (package.NESTED_LAYOUT,package.BOX_ROOT_LAYOUT,package.SHEETS_LAYOUT)

    def test_new_mtimes_give_the_same_pass_and_errors_and_one_warning(self):
        for layout in self.layouts():
            with self.subTest(layout=layout):
                layer,root,c=self.course('t'+layout,layout,reuse=True)
                ok,errs,w=result(layer,root);self.assertTrue(ok,errs);self.assertEqual(w,[])
                touch_all(layer)
                ok2,errs2,w2=result(layer,root)
                self.assertEqual((ok2,errs2),(ok,errs));self.assertEqual(len(w2),1);self.assertIn('file(s) differ',w2[0]['message'])
    def test_forgeries_bound_by_sha256_still_stop_after_a_checkout(self):
        for layout in self.layouts():
            with self.subTest(layout=layout):
                layer,root,c=self.course('f'+layout,layout,reuse=True);touch_all(layer)
                m=package.load(root/'manifest.yaml')
                gen=next(r for r in m['records'] if r['generation_kind']=='generated' and r['stage']!='init')
                q=root/gen['path'];saved=q.read_bytes();q.write_text(q.read_text()+'\nforged\n')
                self.assertIn(('E_HASH',gen['path']),result(layer,root)[1]);q.write_bytes(saved)          # a document rewritten, manifest untouched
                src=layer/'Context/existing_problem.md';keep=src.read_bytes();src.write_text('replaced source')
                self.assertTrue(any(code=='E_COURSE' for code,_ in result(layer,root)[1]));src.write_bytes(keep)   # a source replaced
                reused=next(r for r in m['records'] if r['generation_kind']=='reused');q=root/reused['path'];saved=q.read_bytes();q.write_text('remade, called reuse')
                self.assertIn(('E_COURSE',reused['path']),result(layer,root)[1]);q.write_bytes(saved)    # a remade document recorded as reused
                gen['generated_mtime_ns']=10**18*5;write_yaml(root/'manifest.yaml',m)                  # a recorded generation time outside the batch
                self.assertIn(('E_COURSE',gen['path']),result(layer,root)[1])
    def test_accepted_forgeries_pass(self):
        """Owner choice 2 (2026-10-24): rewriting the manifest too is not stopped any more."""
        for layout in self.layouts():
            with self.subTest(layout=layout):
                layer,root,c=self.course('a'+layout,layout);touch_all(layer)
                m=package.load(root/'manifest.yaml');gen=next(r for r in m['records'] if r['generation_kind']=='generated' and r['stage']!='init')
                q=root/gen['path'];q.write_text(q.read_text()+'\nrewritten later\n');gen['sha256']=sha(q)
                m['source_reads'][0]['source_mtime_ns']=0;write_yaml(root/'manifest.yaml',m)
                ok,errs,w=result(layer,root);self.assertTrue(ok,errs);self.assertEqual(len(w),1)

if __name__=='__main__':unittest.main()
