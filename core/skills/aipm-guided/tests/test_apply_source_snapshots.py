"""a source outside the box (a Layer memo read by the batch, an evidence file of the legacy course) that is
edited after archive breaks final; snapshot-sources places its archive-time bytes in the box (only the recorded sha256) and
final, register, clone, apply and push pass again. The current source file is never changed. Synthetic repository, Stock and
Registry only; the archive-time bytes are kept by the test (a real box takes them from the git history, read only)."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
from datetime import datetime, timezone
from unittest import mock
import re, shutil, unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent));sys.path.insert(0,str(HERE))
import package, validate_package, changes, applying
import test_integration as ti, test_init_and_reset as tr
import test_apply_register_clone as arc, test_apply_change_judgment as acj, test_apply_reflect_push as arp
import test_migrate_layout as tml, test_migrate_sheets_nested as tmsn
import registry_fixture as rf
write_yaml,sha=ti.write_yaml,ti.sha
MEMO='Documents/T001_memo.md'
def now():return datetime.now(timezone.utc).isoformat()

def errs(layer,root):
    r=validate_package.validate(root,phase='final',layer=layer);return r['pass'],sorted({(e['code'],e['path']) for e in r['errors']})

class Batch(arc.Base):
    persona_doc=acj.Changes.persona_doc;candidate=acj.Changes.candidate
    def memo_box(self,name):
        """A document_based box that read a Layer memo (a memo), archived (v1 kind first). Returns the archive-time
        bytes of the memo kept aside (a real box takes them from git)."""
        layer,c,packet=self.prepare(name);(layer/'Documents').mkdir(exist_ok=True);(layer/MEMO).write_text('# memo\n\n7 decision factors\n')
        packet['sources'].append({'id':'L1','domain':'layer','path':MEMO,'sha256':sha(layer/MEMO)});write_yaml(layer/'Context/course_input.yaml',packet)
        root=self.draft(layer);rf.register(self.repo,package.load(layer/'intent.yaml')['scope_id'])
        res=package.archive_course(layer);self.assertTrue(res['pass'],res['errors'])
        keep=self.repo/('kept_'+name+'.md');shutil.copy2(layer/MEMO,keep);return layer,root,keep
    def edit_memo(self,layer):(layer/MEMO).write_text('# memo\n\n8 decision factors (edited after archive with the person\'s approval)\n')
    def input(self,layer,keep,sid='L1'):write_yaml(layer/'Context/snap.yaml',{'sources':[{'id':sid,'bytes':str(keep),'from':'synthetic: git show <commit>:'+MEMO}]});return 'Context/snap.yaml'

    def test_an_edited_memo_breaks_final_and_its_copy_mends_it(self):
        layer,root,keep=self.memo_box('mm');self.edit_memo(layer);edited=sha(layer/MEMO)
        ok,e=errs(layer,root);self.assertFalse(ok);self.assertIn(('E_COURSE','L1'),e);self.assertIn(('E_EVIDENCE','L1'),e)
        out=package.snapshot_sources(layer);self.assertEqual([(x['id'],x['path']) for x in out['changed_sources']],[('L1',MEMO)])
        box=tr.state(root);out=package.snapshot_sources(layer,self.input(layer,keep));self.assertFalse(out['apply']);self.assertEqual(tr.state(root),box)   # dry-run
        with self.assertRaisesRegex(ValueError,'approval-ref'):package.snapshot_sources(layer,self.input(layer,keep),apply=True)
        out=package.snapshot_sources(layer,self.input(layer,keep),apply=True,approval_ref='chat:synthetic');self.assertTrue(out['final']['pass'],out['final']['errors'])
        self.assertEqual(sha(layer/MEMO),edited)   # the current memo is not touched
        m=package.load(root/'manifest.yaml');rel='Documents/aipm_project/source_snapshots/external/'+MEMO
        self.assertEqual(m['source_snapshots']['L1'],rel);self.assertEqual(m['source_snapshot_log'][0]['approval_ref'],'chat:synthetic');self.assertEqual(sha(layer/rel),sha(keep))
        self.assertEqual(package.snapshot_sources(layer)['changed_sources'],[])
        # the apply flow passes now: clone, a change, the judgement, apply, push
        package.clone(layer);changes.change(layer,self.candidate(layer,root,drafts=False),apply=True);lst=changes.change_list(layer);changes.judge_change(layer,lst['digest'],'OK',now(),'t')
        self.assertTrue(applying.apply(layer,apply=True,approval_ref='s')['final']['pass']);self.assertTrue(applying.push(layer,apply=True,approval_ref='s')['final']['pass'])
    def test_register_of_an_old_box_after_the_copy(self):
        layer,root,keep=self.memo_box('rg');m=package.load(root/'manifest.yaml');m.pop('applies');write_yaml(root/'manifest.yaml',m);(self.repo/m['archive_target']['target_rel']/package.APPLY_LOG).unlink()
        self.edit_memo(layer)
        with self.assertRaisesRegex(ValueError,'final does not pass'):package.register(layer,apply=True,approval_ref='s')   # the snapshot case
        package.snapshot_sources(layer,self.input(layer,keep),apply=True,approval_ref='s')
        self.assertTrue(package.register(layer,apply=True,approval_ref='s')['final']['pass']);self.assertTrue(package.clone(layer)['written'])
    def test_refusals_write_nothing(self):
        def wrong_bytes(case):
            layer,root,keep=case.memo_box('wb');case.edit_memo(layer);(case.repo/'other.md').write_text('not the archive-time bytes');return layer,case.input(layer,case.repo/'other.md'),'recorded sha256'
        def not_changed(case):
            layer,root,keep=case.memo_box('nc');return layer,case.input(layer,keep),'has not changed'
        def unknown_id(case):
            layer,root,keep=case.memo_box('ui');case.edit_memo(layer);return layer,case.input(layer,keep,'M1'),'not a source outside'
        def missing_bytes(case):
            layer,root,keep=case.memo_box('mb');case.edit_memo(layer);return layer,case.input(layer,case.repo/'nothing.md'),'not found'
        def not_archived(case):
            layer,c,packet=case.prepare('na');case.draft(layer);return layer,'Context/x.yaml','not archived'
        for build in (wrong_bytes,not_changed,unknown_id,missing_bytes,not_archived):
            with self.subTest(case=build.__name__):
                layer,inp,pattern=build(self);root=layer/ti.pkg_of(layer) if hasattr(ti,'pkg_of') else layer/'Documents/aipm_project';before=tr.state(layer);stock=tr.state(self.repo/'Stock')
                for apply in (False,True):
                    with self.assertRaisesRegex(ValueError,pattern):package.snapshot_sources(layer,inp,apply=apply,approval_ref='s')
                self.assertEqual({k:v for k,v in tr.state(layer).items() if k!='Context/snap.yaml'},{k:v for k,v in before.items() if k!='Context/snap.yaml'});self.assertEqual(tr.state(self.repo/'Stock'),stock)
    def test_a_copy_without_its_log_or_in_another_place_stays_an_error(self):
        layer,root,keep=self.memo_box('nl');self.edit_memo(layer);package.snapshot_sources(layer,self.input(layer,keep),apply=True,approval_ref='s')
        m=package.load(root/'manifest.yaml')
        for name,edit in (('no log',lambda d:d.pop('source_snapshot_log')),('other place',lambda d:d['source_snapshots'].update(L1='Documents/aipm_project/source_snapshots/'+MEMO)),('other sha in log',lambda d:d['source_snapshot_log'][0].update(sha256='0'*64))):
            with self.subTest(case=name):
                d=package.load(root/'manifest.yaml');edit(d);write_yaml(root/'manifest.yaml',d);ok,e=errs(layer,root);self.assertFalse(ok)
                self.assertTrue(any(c in ('E_COURSE','E_EVIDENCE') for c,p in e),e);write_yaml(root/'manifest.yaml',m)
        q=root/'source_snapshots/external'/MEMO;q.write_text('changed copy');ok,e=errs(layer,root);self.assertFalse(ok)   # the copy's bytes are checked like the source
    def test_a_worse_final_puts_everything_back(self):
        layer,root,keep=self.memo_box('wf');self.edit_memo(layer);box=tr.state(root)
        real=validate_package.validate;calls=[]
        def f(*a,**k):
            calls.append(1);r=real(*a,**k)
            return r if len(calls)==1 else {**r,'pass':False,'errors':r['errors']+[{'code':'E_SYNTH','path':'.','message':'s'}]}
        with mock.patch.object(validate_package,'validate',side_effect=f),self.assertRaisesRegex(ValueError,'as before'):package.snapshot_sources(layer,self.input(layer,keep),apply=True,approval_ref='s')
        self.assertEqual(tr.state(root),box)

class Legacy(unittest.TestCase):
    """The legacy course binds its sources by evidence only (Context/case.yaml here)."""
    setUp=tml.in_repository
    def tearDown(self):self.temp.cleanup()
    legacy_box=tmsn.MigrateSheetsNested.legacy_box
    def test_legacy_evidence_copy(self):
        layer,root0,c=self.legacy_box('le',internal=False);db=rf.db_path(self.registry)
        self.assertTrue(package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=db)['applied'])
        root=layer/'Sheets';keep=self.repo/'kept_case.yaml';shutil.copy2(layer/'Context/case.yaml',keep)
        (layer/'Context/case.yaml').write_text('kind: hypothesis\nclaim: edited after archive\n')
        ok,e=errs(layer,root);self.assertFalse(ok);sid=next(p for c,p in e if c=='E_EVIDENCE')
        self.assertIn(sid,[x['id'] for x in package.snapshot_sources(layer)['changed_sources']])
        write_yaml(layer/'Context/snap.yaml',{'sources':[{'id':sid,'bytes':str(keep)}]})
        out=package.snapshot_sources(layer,'Context/snap.yaml',apply=True,approval_ref='s');self.assertTrue(out['final']['pass'],out['final']['errors'])
        self.assertTrue(package.register(layer,apply=True,approval_ref='s')['final']['pass'])

class LegacyShared(unittest.TestCase):
    """Several evidence rows on one Layer file (one Context file read as several evidence rows) share one copy."""
    setUp=tml.in_repository
    def tearDown(self):self.temp.cleanup()
    legacy_box=tmsn.MigrateSheetsNested.legacy_box
    def box(self,name):
        layer,root0,c=self.legacy_box(name,internal=False);db=rf.db_path(self.registry)
        m=package.load(root0/'manifest.yaml');e=next(x for x in m['evidence'] if x.get('source')=='Context/case.yaml');m['evidence'].append({**e,'id':e['id']+'B'});write_yaml(root0/'manifest.yaml',m)
        self.assertTrue(package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=db)['applied'])
        keep=self.repo/('kept_'+name+'.yaml');shutil.copy2(layer/'Context/case.yaml',keep);(layer/'Context/case.yaml').write_text('kind: hypothesis\nclaim: edited\n')
        ids=sorted(x['id'] for x in package.snapshot_sources(layer)['changed_sources']);self.assertEqual(len(ids),2);return layer,layer/'Sheets',keep,ids
    def test_two_ids_in_one_input(self):
        layer,root,keep,ids=self.box('two');write_yaml(layer/'Context/snap.yaml',{'sources':[{'id':i,'bytes':str(keep)} for i in ids]})
        out=package.snapshot_sources(layer,'Context/snap.yaml',apply=True,approval_ref='s');self.assertTrue(out['final']['pass'],out['final']['errors'])
        m=package.load(root/'manifest.yaml');self.assertEqual(len({m['source_snapshots'][i] for i in ids}),1)
    def test_one_id_then_the_other(self):
        layer,root,keep,ids=self.box('one')
        for i in ids:
            write_yaml(layer/'Context/snap.yaml',{'sources':[{'id':i,'bytes':str(keep)}]});out=package.snapshot_sources(layer,'Context/snap.yaml',apply=True,approval_ref='s')
        self.assertTrue(out['final']['pass'],out['final']['errors'])

if __name__=='__main__':unittest.main()
