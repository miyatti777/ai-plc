"""boxes really committed to git and cloned elsewhere (no empty folders, new mtimes) give the
same validate pass and errors as where they were made (SC1). After the clone, forgeries bound by sha256 or by one-sided
record changes still stop, and the owner-accepted forgery (stages and records rewritten together) passes (SC2, choice 2).
validate and package never call git; only this test does. Synthetic fixtures only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
from datetime import datetime, timedelta, timezone
import shutil, subprocess, tempfile, unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import test_integration as ti
import registry_fixture as rf
package=ti.package;validate_package=ti.validate_package;write_yaml,sha=ti.write_yaml,ti.sha

def git(cwd,*args):
    subprocess.run(['git','-c','core.hooksPath=/dev/null','-c','user.name=synthetic','-c','user.email=synthetic@example.invalid',*args],cwd=cwd,check=True,capture_output=True)

def result(layer,phase):
    r=validate_package.validate(layer/ti.pkg_of(layer),phase=phase,layer=layer)
    return r['pass'],sorted({(e['code'],e['path']) for e in r['errors']})

class GitCheckout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which('git') is None:raise unittest.SkipTest('git not installed')
        cls.temp=tempfile.TemporaryDirectory();top=Path(cls.temp.name)
        cls.repo=top/'made';cls.base=cls.repo/'Flow/202610/2026-10-24';cls.base.mkdir(parents=True);(cls.repo/'Stock/programs/Sample').mkdir(parents=True)
        (cls.repo/'Stock/programs/Sample/.keep').write_text('')
        cls.registry=top/'registry';rf.standard(cls.registry)   # outside the repository: archive reads it
        cls.boxes={}
        for layout in (package.NESTED_LAYOUT,package.BOX_ROOT_LAYOUT,package.SHEETS_LAYOUT):
            layer=cls.base/('legacy-'+layout);ti.fixture(layer,layout=layout,project='alpha_'+layout);cls.boxes['legacy '+layout]=('legacy-'+layout,'final')   # one Stock project per box
        cls.receipt_box(package.NESTED_LAYOUT,archive=False)
        cls.receipt_box(package.BOX_ROOT_LAYOUT,archive=True)
        cls.receipt_box(package.SHEETS_LAYOUT,archive=True)
        cls.made={name:result(cls.base/rel,phase) for name,(rel,phase) in cls.boxes.items()}
        git(cls.repo,'init','-q');git(cls.repo,'add','-A');git(cls.repo,'commit','-q','-m','synthetic boxes')
        cls.clone=top/'clone';git(top,'clone','-q',str(cls.repo),str(cls.clone))
        cls.cbase=cls.clone/'Flow/202610/2026-10-24'
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    @classmethod
    def receipt_box(cls,layout,archive):
        """A new-course box whose persona and validation decisions were answered (receipts bound), then optionally archived."""
        case=type('Case',(),{})();case.base=cls.base;name='course-'+layout
        layer,_,packet=ti.CourseIntegration.prepare(case,name,pending=True)
        packet['decisions']['validation']={'state':'pending','reason':'Choosing validation hypotheses is the user call','scope':'reversible_draft_only','source_ids':['M1','M2'],'question':'Use H1 for validation?'}
        for key in ('persona','validation'):packet['gaps'].append({'kind':'unknown','reason':'needs the user','requires_user':True,'decision_key':key,'question':'?'})
        d=package.load(layer/'intent.yaml');d['aipm'].update(layout=layout,program_id='Sample',project_id='course_'+layout);write_yaml(layer/'intent.yaml',d)   # one Stock project per box
        c=package.build_contract(layer);flow_base,stock_base=package.init_roots(c);b=c['bindings']
        packet['drafts']['write_init_yaml'].update(program_id=b['program_id'],project_id=b['project_id'],flow_dir=b['flow_dir'],flow_base=flow_base,stock_base=stock_base)
        write_yaml(layer/'Context/course_input.yaml',packet);root=ti.CourseIntegration.draft(case,layer)
        def ask(qname,**over):
            r={'stage':'persona','question':'Which actual persona should be used?','answer':'Synthetic reply only','question_id':'SYN-'+qname,'source_thread_id':'SYNTHETIC-THREAD','answered_at':datetime.now(timezone.utc).isoformat()};r.update(over)
            write_yaml(layer/'Context'/(qname+'.yaml'),r);return 'Context/'+qname+'.yaml'
        assert package.receipt(layer,ask('p'))['bound']
        v=package.load(root/'validation_record.yaml');write_yaml(root/'validation_checkpoint.yaml',{k:x for k,x in v.items() if k!='actual_new_user_response'})
        assert package.receipt(layer,ask('v',stage='validation',question='Use H1 for validation?'))['pass']
        if archive:
            rf.register(cls.registry,package.load(layer/'intent.yaml')['scope_id'])
            assert package.archive_course(layer,registry_db=rf.db_path(cls.registry))['pass']
        cls.boxes['course '+layout]=(name,'final' if archive else 'prearchive')

    def test_cloned_boxes_give_the_same_pass_and_errors(self):
        for name,(rel,phase) in self.boxes.items():
            with self.subTest(box=name):
                self.assertTrue(self.made[name][0],self.made[name][1])
                self.assertEqual(result(self.cbase/rel,phase),self.made[name])
                root=self.cbase/rel/ti.pkg_of(self.cbase/rel)
                if package.load(root/'format_contract.yaml').get('layout') not in package.FLAT_LAYOUTS:continue
                self.assertFalse((root/'05_UIワイヤーフレーム').exists())   # git really dropped the empty folders
    def copy(self,name):
        GitCheckout.copies=getattr(GitCheckout,'copies',0)+1
        rel,phase=self.boxes[name];dst=self.cbase/('forge'+str(GitCheckout.copies)+'-'+rel);shutil.copytree(self.cbase/rel,dst,copy_function=shutil.copy2)
        return dst,dst/ti.pkg_of(dst),phase
    def edit(self,root,fn):
        m=package.load(root/'manifest.yaml');fn(m);write_yaml(root/'manifest.yaml',m)
    def test_one_sided_record_changes_still_stop(self):
        for layout in (package.NESTED_LAYOUT,package.BOX_ROOT_LAYOUT,package.SHEETS_LAYOUT):
            with self.subTest(layout=layout,check='C3 a record moved to another stage'):
                layer,root,phase=self.copy('legacy '+layout)
                def move(m):
                    late=next(s for s in m['stages'] if s['name']=='story');r=next(r for r in m['records'] if r['stage']=='persona')
                    r['generated_mtime_ns']=int(datetime.fromisoformat(late['finished_at']).timestamp()*1e9)+1
                self.edit(root,move);self.assertIn('E_ORDER',{c for c,_ in result(layer,phase)[1]})
            with self.subTest(layout=layout,check='C7 validation after solution'):
                layer,root,phase=self.copy('legacy '+layout)
                def late_validation(m):
                    sol=min(r['generated_mtime_ns'] for r in m['records'] if r['stage']=='solution')
                    s=next(s for s in m['stages'] if s['name']=='validation');s['finished_at']=datetime.fromtimestamp(sol/1e9+1,timezone.utc).isoformat()
                self.edit(root,late_validation);self.assertIn(('E_ORDER','validation'),result(layer,phase)[1])
            for bad in ('1700000000000000000',None,True):
                with self.subTest(layout=layout,check='C3 a recorded time that is not an int',value=bad):
                    layer,root,phase=self.copy('legacy '+layout)
                    self.edit(root,lambda m:next(r for r in m['records'] if r['stage']=='persona').update(generated_mtime_ns=bad))
                    self.assertIn('E_ORDER',{c for c,_ in result(layer,phase)[1]})
        with self.subTest(check='C8 the target rewritten after the reply'):
            layer,root,phase=self.copy('course '+package.NESTED_LAYOUT)
            m=package.load(root/'manifest.yaml');target=m['human_responses']['persona']['target_path'][len('Documents/aipm_project/'):]
            q=root/target;q.write_text(q.read_text()+'\nchanged after the reply\n')
            self.edit(root,lambda m:[r.update(sha256=sha(q)) for r in m['records'] if r['path']==target])
            self.assertIn('E_CHECKPOINT',{c for c,_ in result(layer,phase)[1]})
        with self.subTest(check='C8 the reply recorded before the target was written'):
            layer,root,phase=self.copy('course '+package.NESTED_LAYOUT)
            self.edit(root,lambda m:m['human_responses']['persona'].update(target_written_ns=int((datetime.now(timezone.utc)+timedelta(days=1)).timestamp()*1e9)))
            self.assertIn('E_CHECKPOINT',{c for c,_ in result(layer,phase)[1]})
        with self.subTest(check='C8 a recorded write time that is not an int'):
            layer,root,phase=self.copy('course '+package.NESTED_LAYOUT)
            self.edit(root,lambda m:m['human_responses']['persona'].update(target_written_ns='x'))
            self.assertIn('E_CHECKPOINT',{c for c,_ in result(layer,phase)[1]})
        with self.subTest(check='C8 only the target record moved after the reply'):
            layer,root,phase=self.copy('course '+package.NESTED_LAYOUT)
            def late_record(m):
                h=m['human_responses']['persona'];target=h['target_path'][len('Documents/aipm_project/'):]
                late=int((datetime.now(timezone.utc)+timedelta(days=1)).timestamp()*1e9)   # after any reply in this fixture
                next(r for r in m['records'] if r['path']==target).update(generated_mtime_ns=late)
            self.edit(root,late_record);self.assertIn('E_CHECKPOINT',{c for c,_ in result(layer,phase)[1]})
    def test_accepted_forgery_stages_and_records_together(self):
        """Owner choice 2: shifting stages and records together (a consistent manifest) is not stopped."""
        layer,root,phase=self.copy('legacy '+package.NESTED_LAYOUT)
        def shift(m):
            d=timedelta(hours=1);n=int(d.total_seconds()*1e9)
            for s in m['stages']:
                for k in ('started_at','finished_at'):s[k]=(datetime.fromisoformat(s[k])-d).isoformat()
            for r in m['records']:r['generated_mtime_ns']-=n
        self.edit(root,shift);self.assertTrue(result(layer,phase)[0])

if __name__=='__main__':unittest.main()
