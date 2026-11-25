"""the versions of an archived box (manifest applies[] and the Stock apply_log.yaml), register (an archived
box becomes version 1 without changing its documents, records, sha256 or other manifest values), the first archive as
version 1 (kind first), clone (the work base of the last pushed version) and E_APPLY ①-④ with the apply_v<N> events at the
end of the stages. Synthetic repository, Stock and Registry only; no real box is touched."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import copy, unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent));sys.path.insert(0,str(HERE))
import package, validate_package
import test_integration as ti, test_init_and_reset as tr
import test_archive_business as ab, test_sheets_layout as tsl, test_box_root_compat as bc
import registry_fixture as rf
write_yaml,sha=ti.write_yaml,ti.sha

def errors(layer,root):
    res=validate_package.validate(root,phase='final',layer=layer);return res['pass'],sorted({(e['code'],e['path'],e['message']) for e in res['errors']})

class Base(unittest.TestCase):
    setUp=ab.setup
    def tearDown(self):self.temp.cleanup()
    prepare=bc.box_root_prepare;draft=ti.CourseIntegration.draft
    def archived_before_versions(self,name,sheets=False,course='document_based/single_persona'):
        """A box archived the way it was before box versions (no applies, no apply_log): archive, then take the version records out."""
        if sheets:
            layer,c,packet=tsl.sheets_prepare(self,name,course);root=self.draft(layer);rf.register(self.repo,package.load(layer/'intent.yaml')['scope_id'])
        else:
            layer,c,packet=self.prepare(name,course);root=self.draft(layer);rf.register(self.repo,package.load(layer/'intent.yaml')['scope_id'])
        res=package.archive_course(layer);self.assertTrue(res['pass'],res['errors'])
        m=package.load(root/'manifest.yaml');m.pop('applies');write_yaml(root/'manifest.yaml',m)
        (self.repo/m['archive_target']['target_rel']/package.APPLY_LOG).unlink()
        self.assertEqual(errors(layer,root),(True,[]))
        return layer,root,m['archive_target']['target_rel']
    def log(self,target):return package.load(self.repo/target/package.APPLY_LOG)
    def registered(self,name,sheets=False):
        layer,root,target=self.archived_before_versions(name,sheets);package.register(layer,apply=True,approval_ref='synthetic');return layer,root,target

class Versions(Base):

    # ---- the first archive is version 1 (kind first) ----
    def test_first_archive_writes_version_1_and_the_apply_log(self):
        for n,(sheets,course) in enumerate(((False,'document_based/single_persona'),(True,'solution_based/single_persona'))):
            with self.subTest(sheets=sheets,course=course):
                if sheets:layer,c,packet=tsl.sheets_prepare(self,'f'+str(n),course)
                else:layer,c,packet=self.prepare('f'+str(n),course)
                root=self.draft(layer);rf.register(self.repo,package.load(layer/'intent.yaml')['scope_id'])
                res=package.archive_course(layer);self.assertTrue(res['pass'],res['errors'])
                m=package.load(root/'manifest.yaml');a=m['applies']
                self.assertEqual(len(a),1);self.assertEqual((a[0]['version'],a[0]['kind'],a[0]['pushed'],a[0]['base_version'],a[0]['changed']),(1,'first',True,None,[]))
                self.assertEqual(len(a[0]['docs']),17);self.assertEqual(a[0]['docs'],{r['path']:r['sha256'] for r in m['records'] if r['archive_path']})
                log=self.log(m['archive_target']['target_rel'])
                self.assertEqual([v['version'] for v in log['versions']],[1]);self.assertEqual(log['versions'][0]['docs'],a[0]['docs'])
                self.assertEqual(log['box']['layer'],'Flow/202610/2026-10-24/f'+str(n));self.assertEqual(log['project'],'course_f'+str(n))
    def test_first_archive_stops_when_the_stock_already_has_an_apply_log(self):
        layer,c,packet=self.prepare('fl');root=self.draft(layer);rf.register(self.repo,package.load(layer/'intent.yaml')['scope_id'])
        target=self.repo/'Stock/programs/Sample/projects'/rf.BUSINESS/'course_fl';target.mkdir(parents=True);(target/package.APPLY_LOG).write_text('versions: []\n')
        stock=tr.state(self.repo/'Stock');manifest=sha(root/'manifest.yaml')
        with self.assertRaisesRegex(ValueError,'apply log already exists'):package.archive_course(layer)
        self.assertEqual(tr.state(self.repo/'Stock'),stock);self.assertEqual(sha(root/'manifest.yaml'),manifest)

    def test_a_failed_first_archive_leaves_no_apply_log(self):
        layer,c,packet=self.prepare('fa');root=self.draft(layer);rf.register(self.repo,package.load(layer/'intent.yaml')['scope_id'])
        stock=tr.state(self.repo/'Stock');manifest=sha(root/'manifest.yaml')
        from unittest import mock
        with mock.patch.object(package.shutil,'copystat',side_effect=OSError('synthetic')),self.assertRaisesRegex(ValueError,'archive stopped'):package.archive_course(layer)
        self.assertEqual(tr.state(self.repo/'Stock'),stock);self.assertEqual(sha(root/'manifest.yaml'),manifest)
        self.assertTrue(package.archive_course(layer)['pass'])   # and it can run again
    def test_move_archive_stops_on_a_box_with_versions(self):
        layer,c,packet=self.prepare('mv');root=self.draft(layer);rf.register(self.repo,package.load(layer/'intent.yaml')['scope_id']);self.assertTrue(package.archive_course(layer)['pass'])
        stock=tr.state(self.repo/'Stock');manifest=sha(root/'manifest.yaml')
        with self.assertRaisesRegex(ValueError,'has versions'):package.move_archive(layer,apply=True,approval_ref='synthetic')
        self.assertEqual(tr.state(self.repo/'Stock'),stock);self.assertEqual(sha(root/'manifest.yaml'),manifest)
    def test_flow_layer_rel(self):
        self.assertEqual(package.flow_layer_rel(Path('/x/Flow/202610/2026-10-28/a/sublayers/b')),'Flow/202610/2026-10-28/a/sublayers/b')
        self.assertEqual(package.flow_layer_rel(Path('/wt/bot/work/202610/2026-10-28/a/sublayers/b')),'Flow/202610/2026-10-28/a/sublayers/b')   # a sparse Flow worktree
        self.assertEqual(package.flow_layer_rel(Path('/wt/bot/work/202610/2026-10-28/a')),'Flow/202610/2026-10-28/a')

    # ---- register ----
    def test_register_dry_run_writes_nothing(self):
        layer,root,target=self.archived_before_versions('rd');stock=tr.state(self.repo/'Stock');manifest=sha(root/'manifest.yaml')
        out=package.register(layer);self.assertFalse(out['apply']);self.assertEqual((out['version'],out['kind'],out['documents']),(1,'register',17))
        self.assertEqual(tr.state(self.repo/'Stock'),stock);self.assertEqual(sha(root/'manifest.yaml'),manifest)
    def test_register_keeps_every_document_and_value_and_adds_only_the_versions(self):
        for sheets,course in ((False,'document_based/single_persona'),(True,'solution_based/single_persona')):
            with self.subTest(sheets=sheets,course=course):
                name='r'+('s' if sheets else 'b');layer,root,target=self.archived_before_versions(name,sheets,course)
                pkg=tr.state(root);stock=tr.state(self.repo/'Stock');m0=package.load(root/'manifest.yaml');before=errors(layer,root)
                with self.assertRaisesRegex(ValueError,'approval-ref'):package.register(layer,apply=True)
                with self.assertRaisesRegex(ValueError,'approval-ref'):package.register(layer,apply=True,approval_ref='  ')
                self.assertEqual(tr.state(root),pkg);self.assertEqual(tr.state(self.repo/'Stock'),stock)
                out=package.register(layer,apply=True,approval_ref='chat:synthetic approval')
                self.assertTrue(out['final']['pass'],out['final']['errors']);self.assertEqual(errors(layer,root),before)   # validate final is not worse
                m1=package.load(root/'manifest.yaml')
                self.assertEqual(set(m1)-set(m0),{'applies'})
                for k in m0:self.assertEqual(m1[k],m0[k],k)   # records, stages, evidence, receipts: the same values
                self.assertEqual({k:v for k,v in tr.state(root).items() if k!='manifest.yaml'},{k:v for k,v in pkg.items() if k!='manifest.yaml'})   # documents: bytes and mtime
                a=m1['applies'];self.assertEqual((len(a),a[0]['kind'],a[0]['approval_ref'],a[0]['stock_target_rel']),(1,'register','chat:synthetic approval',target))
                new=set(tr.state(self.repo/'Stock'))-set(stock);self.assertEqual(new,{target.split('Stock/',1)[1]+'/'+package.APPLY_LOG})
                self.assertEqual({k:v for k,v in tr.state(self.repo/'Stock').items() if k in stock},stock)   # Stock documents untouched
                log=self.log(target);self.assertEqual(log['versions'],[{k:a[0][k] for k in package.LOG_KEYS}])
                with self.assertRaisesRegex(ValueError,'already has versions'):package.register(layer,apply=True,approval_ref='again')
    def test_register_refusals_write_nothing(self):
        def stock_changed(case):
            layer,root,target=case.archived_before_versions('sc');q=next((case.repo/target/'documents').rglob('*.md'));q.write_text(q.read_text()+'\nedited\n');return layer,root
        def stock_has_log(case):
            layer,root,target=case.archived_before_versions('sl');(case.repo/target/package.APPLY_LOG).write_text('versions: []\n');return layer,root
        def not_archived(case):
            layer,c,packet=case.prepare('na');root=case.draft(layer);return layer,root
        for build,pattern in ((stock_changed,'final does not pass'),(stock_has_log,'disagree'),(not_archived,'not archived')):
            with self.subTest(case=build.__name__):
                layer,root=build(self);stock=tr.state(self.repo/'Stock');manifest=sha(root/'manifest.yaml')
                for apply in (False,True):
                    with self.assertRaisesRegex(ValueError,pattern):package.register(layer,apply=apply,approval_ref='synthetic')
                self.assertEqual(tr.state(self.repo/'Stock'),stock);self.assertEqual(sha(root/'manifest.yaml'),manifest)
    def test_register_puts_everything_back_when_final_fails_after(self):
        layer,root,target=self.archived_before_versions('rb');stock=tr.state(self.repo/'Stock');manifest=sha(root/'manifest.yaml')
        real=validate_package.validate;calls=[]
        def second_fails(*a,**k):
            calls.append(1);res=real(*a,**k)
            return res if len(calls)==1 else {**res,'pass':False,'errors':[{'code':'E_SYNTH','path':'.','message':'synthetic'}]}
        from unittest import mock
        with mock.patch.object(validate_package,'validate',second_fails),self.assertRaisesRegex(ValueError,'as before'):package.register(layer,apply=True,approval_ref='synthetic')
        self.assertEqual(tr.state(self.repo/'Stock'),stock);self.assertEqual(sha(root/'manifest.yaml'),manifest)
    def test_register_refuses_nested_and_shared_boxes(self):
        layer,c,packet=ti.CourseIntegration.prepare(self,'nest');root=self.draft(layer);self.assertTrue(package.archive_course(layer)['pass'])
        manifest=sha(root/'manifest.yaml')
        self.assertNotIn('applies',package.load(root/'manifest.yaml'))   # nested_v1 archives stay without versions
        with self.assertRaisesRegex(ValueError,'nested_v1'):package.register(layer,apply=True,approval_ref='synthetic')
        with self.assertRaisesRegex(ValueError,'nested_v1'):package.clone(layer)
        self.assertEqual(sha(root/'manifest.yaml'),manifest)
        c=package.build_contract(layer);real=package.build_contract
        from unittest import mock
        with mock.patch.object(package,'build_contract',lambda l:{**real(l),'storage':'registry_stock_v1'}),self.assertRaisesRegex(ValueError,'shared Stock'):package.register(layer)

    # ---- clone ----
    def test_clone_writes_the_base_and_the_same_base_again_writes_nothing(self):
        for sheets in (False,True):
            with self.subTest(sheets=sheets):
                layer,root,target=self.registered('c'+str(int(sheets)),sheets);pkg=tr.state(root);stock=tr.state(self.repo/'Stock')
                out=package.clone(layer);self.assertTrue(out['written']);self.assertEqual((out['version'],out['documents']),(1,17))
                b=package.load(layer/out['base']);m=package.load(root/'manifest.yaml')
                self.assertEqual((b['version'],b['stock_target_rel'],b['docs']),(1,target,m['applies'][0]['docs']))
                self.assertEqual(out['base'],'Context/aipm_changes/base_course_c'+str(int(sheets))+'.yaml')
                self.assertEqual(tr.state(root),pkg);self.assertEqual(tr.state(self.repo/'Stock'),stock)   # box and Stock: nothing copied
                base=sha(layer/out['base']);again=package.clone(layer);self.assertFalse(again['written']);self.assertEqual(sha(layer/out['base']),base)
                self.assertEqual(errors(layer,root),(True,[]))
    def test_clone_refusals_write_nothing(self):
        def no_versions(case):layer,root,target=case.archived_before_versions('nv');return layer,root,'run register first'
        def stock_newer(case):
            layer,root,target=case.registered('sn');q=case.repo/target/package.APPLY_LOG;log=package.load(q)
            v2=copy.deepcopy(log['versions'][0]);v2.update(version=2,kind='apply',base_version=1);log['versions'].append(v2);write_yaml(q,log);return layer,root,'newer than the box'
        def log_edited(case):
            layer,root,target=case.registered('le');q=case.repo/target/package.APPLY_LOG;log=package.load(q);log['versions'][0]['approval_ref']='edited';write_yaml(q,log);return layer,root,'disagree'
        def other_box(case):
            layer,root,target=case.registered('ox');q=case.repo/target/package.APPLY_LOG;log=package.load(q);log['project']='course_other';write_yaml(q,log);return layer,root,'another box'
        def log_missing(case):
            layer,root,target=case.registered('lm');(case.repo/target/package.APPLY_LOG).unlink();return layer,root,'has no'
        def stock_doc_changed(case):
            layer,root,target=case.registered('sd');q=next((case.repo/target/'documents').rglob('*.md'));q.write_text(q.read_text()+'\nedited\n');return layer,root,'Stock document differs'
        def box_doc_changed(case):
            layer,root,target=case.registered('bd');m=package.load(root/'manifest.yaml');r=next(r for r in m['records'] if r['archive_path'] and r['path'].endswith('.md'))
            q=root/r['path'];q.write_text(q.read_text()+'\nnot applied\n');return layer,root,'changes not applied'
        def unpushed(case):
            layer,root,target=case.registered('up');m=package.load(root/'manifest.yaml');m['applies'][0]['pushed']=False;write_yaml(root/'manifest.yaml',m);return layer,root,'not pushed'
        def other_base(case):
            layer,root,target=case.registered('ob');q=layer/'Context/aipm_changes/base_course_ob.yaml';q.parent.mkdir(parents=True);write_yaml(q,{'project':'course_ob','version':7,'stock_target_rel':target,'docs':{}});return layer,root,'another base'
        for build in (no_versions,stock_newer,log_edited,other_box,log_missing,stock_doc_changed,box_doc_changed,unpushed,other_base):
            with self.subTest(case=build.__name__):
                layer,root,pattern=build(self);stock=tr.state(self.repo/'Stock');ctx=tr.state(layer/'Context');pkg=tr.state(root)
                with self.assertRaisesRegex(ValueError,pattern):package.clone(layer)
                self.assertEqual(tr.state(self.repo/'Stock'),stock);self.assertEqual(tr.state(layer/'Context'),ctx);self.assertEqual(tr.state(root),pkg)

    # ---- validate: E_APPLY ①-④ and the apply_v<N> events ----
    def tampered(self,name,edit):
        layer,root,target=self.registered(name);m=package.load(root/'manifest.yaml');edit(m);write_yaml(root/'manifest.yaml',m);return errors(layer,root)
    def test_e_apply_findings(self):
        def gap(m):m['applies'][0]['version']=2
        def missing_doc(m):m['applies'][0]['docs'].pop(next(iter(m['applies'][0]['docs'])))
        def last_differs(m):k=next(iter(m['applies'][0]['docs']));m['applies'][0]['docs'][k]='0'*64
        def no_approval(m):m['applies'][0]['approval_ref']=None
        def v1_apply(m):m['applies'][0]['kind']='apply'
        def v1_changed(m):m['applies'][0]['changed']=[{'path':'x','before':'a','after':'b','change_ids':['C-1']}]
        def bad_kind_v2(m):v2=copy.deepcopy(m['applies'][0]);v2.update(version=2,kind='register');m['applies'].append(v2)
        def not_list(m):m['applies']={}
        for edit,message in ((gap,'without a gap'),(missing_doc,'every document'),(last_differs,'last version docs'),(no_approval,'approval_ref'),(v1_apply,'v1 is register/first'),(v1_changed,'no base_version'),(bad_kind_v2,'v1 is register/first'),(not_list,'non-empty list')):
            with self.subTest(edit=edit.__name__):
                ok,errs=self.tampered(edit.__name__,edit);self.assertFalse(ok)
                self.assertTrue(any(c=='E_APPLY' and message in msg for c,p,msg in errs),errs)
    def with_v2(self,name,change_one=True,event=('auto_decision','accepted_local')):
        """A synthetic apply version 2 (apply writes these; here only the records the validator reads): one document edited."""
        layer,root,target=self.registered(name);m=package.load(root/'manifest.yaml');v1=m['applies'][0]
        v2=copy.deepcopy(v1);v2.update(version=2,kind='apply',base_version=1,approval_ref='synthetic v2',pushed=True,event='apply_v2')
        if change_one:
            r=next(r for r in m['records'] if r['archive_path'] and r['path'].endswith('.md'));q=root/r['path'];q.write_text(q.read_text()+'\nv2\n')
            new=sha(q);v2['changed']=[{'path':r['path'],'before':r['sha256'],'after':new,'change_ids':['C-20261101-01']}];v2['docs'][r['path']]=new;r['sha256']=new;r['applied_in']=2;r['applied_mtime_ns']=q.stat().st_mtime_ns
            a=self.repo/r['archive_path'];a.write_bytes(q.read_bytes());r['archive_sha256']=new
        last=m['stages'][-1]['finished_at']
        import datetime as _dt
        if event:m['stages'].append({'name':'apply_v2','started_at':last,'finished_at':_dt.datetime.now(_dt.timezone.utc).isoformat(),'checkpoint_actor':event[0],'checkpoint_status':event[1],'evidence_refs':[]})
        m['applies'].append(v2);write_yaml(root/'manifest.yaml',m)
        lq=self.repo/m['archive_target']['target_rel']/package.APPLY_LOG;log=package.load(lq);log['versions'].append({k:v2.get(k) for k in package.LOG_KEYS});write_yaml(lq,log)   # pushed: the Stock log has it too
        return layer,root,m
    def test_an_apply_version_with_its_event_at_the_end_passes(self):
        layer,root,m=self.with_v2('v2');self.assertEqual(errors(layer,root),(True,[]))
    def test_an_apply_version_needs_its_event_and_an_auto_checkpoint(self):
        layer,root,m=self.with_v2('ne',event=None);ok,errs=errors(layer,root);self.assertFalse(ok);self.assertIn(('E_ORDER','stages','incorrect required stage order'),errs)
        layer,root,m=self.with_v2('au',event=('actual_user','confirmed_actual'));ok,errs=errors(layer,root);self.assertFalse(ok)
        self.assertTrue(any(c=='E_APPLY' and p=='stages.apply_v2' for c,p,msg in errs),errs)
    def test_changed_must_match_the_versions(self):
        def wrong_before(m):m['applies'][1]['changed'][0]['before']='1'*64
        def unlisted_change(m):m['applies'][1]['changed']=[]
        def wrong_base(m):m['applies'][1]['base_version']=None
        for edit,message in ((wrong_before,'before/after'),(unlisted_change,'not in changed'),(wrong_base,'base_version')):
            with self.subTest(edit=edit.__name__):
                layer,root,m=self.with_v2(edit.__name__);edit(m);write_yaml(root/'manifest.yaml',m);ok,errs=errors(layer,root);self.assertFalse(ok)
                self.assertTrue(any(c=='E_APPLY' and message in msg for c,p,msg in errs),errs)
    def test_a_box_without_versions_is_checked_as_before(self):
        layer,root,target=self.archived_before_versions('nb');self.assertEqual(errors(layer,root),(True,[]))

class CLI(Base):
    def test_register_and_clone_from_the_command_line(self):
        layer,root,target=self.archived_before_versions('cli')
        code,out=tr.run_cli('register','--layer',str(layer));self.assertFalse(out['apply'])
        code,out=tr.run_cli('register','--layer',str(layer),'--apply');self.assertEqual(code,1);self.assertFalse(out['pass']);self.assertIn('approval-ref',out['error'])
        code,out=tr.run_cli('register','--layer',str(layer),'--apply','--approval-ref','chat:synthetic');self.assertTrue(out['final']['pass'])
        code,out=tr.run_cli('clone','--layer',str(layer));self.assertTrue(out['written'])

if __name__=='__main__':unittest.main()
