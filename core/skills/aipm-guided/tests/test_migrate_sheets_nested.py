"""package.py migrate-sheets moves one nested_v1 package (not archived, not the legacy course) to
sheets_v1 in one step. Fixtures: a box (document_based, registers, mode_init, a WBS reference into the inner
Flow folder, pending decisions) and a box whose persona and validation replies are bound by receipts. Synthetic only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
from datetime import datetime, timezone
from unittest import mock
import os, unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import test_integration as ti
import test_init_and_reset as tr
import test_migrate_layout as tml
import registry_fixture as rf

def bind_init(layer,root):
    """An init reply bound to project_init.yaml the way a box made by the receipt command has it (the receipt command of
    today does not bind init): receipt, human_responses, checkpoint_targets, evidence and the init stage."""
    m=package.load(root/'manifest.yaml');st=m['stages'][0];assert st['name']=='init'
    pi=next(r for r in m['records'] if r['source_step']=='write_init_yaml');tp=NEST+'/'+pi['path']
    rec={'kind':'user_reported','actor':'actual_user','origin':'actual_user_reply','scope_id':m['scope_id'],'stage':'init','answer':'Synthetic reply only','target_sha256':pi['sha256'],'target_path':tp,'question_id':'LEG-init','source_thread_id':'SYNTHETIC-THREAD','received_at':st['finished_at']}
    write_yaml(layer/'Context/init_reply.yaml',rec);ss=sha(layer/'Context/init_reply.yaml')
    m['human_responses']={'init':{'source':'Context/init_reply.yaml','target_path':tp,'answer':'Synthetic reply only','target_sha256':pi['sha256'],'source_sha256':ss}}
    m['checkpoint_targets']={'init':pi['sha256']}
    m['evidence'].append({'id':'USR-init','kind':'user_reported','source':'Context/init_reply.yaml','source_sha256':ss,'scope':'synthetic actual-user reply'})
    st.update(checkpoint_actor='actual_user',checkpoint_status='confirmed_actual');st['evidence_refs'].append('USR-init')
    for r in m['records']:
        if r['stage']=='init':r.update(requires_human=True,human_state='confirmed_actual')
    write_yaml(root/'manifest.yaml',m)
package=ti.package;validate_package=ti.validate_package;write_yaml,sha=ti.write_yaml,ti.sha
NEST='Documents/aipm_project'

class MigrateSheetsNested(unittest.TestCase):
    setUp=tml.in_repository
    def tearDown(self):self.temp.cleanup()
    prepare=ti.CourseIntegration.prepare;mode_init_layer=ti.CourseIntegration.mode_init_layer;draft=ti.CourseIntegration.draft
    nested=tml.MigrateLayout.nested
    def errors(self,layer,root):return sorted({(e['code'],e['path']) for e in validate_package.validate(root,phase='prearchive',layer=layer)['errors']})
    def receipt_box(self,name):
        """A nested_v1 new-course box whose persona and validation replies are bound by receipts (prearchive passes).
        validation_record (and so validation_checkpoint) also names an old path: it must stay as it is."""
        layer,c,packet=self.prepare(name,pending=True)
        packet['decisions']['validation']={'state':'pending','reason':'Choosing validation hypotheses is the user call','scope':'reversible_draft_only','source_ids':['M1','M2'],'question':'Use H1 for validation?'}
        for key in ('persona','validation'):packet['gaps'].append({'kind':'unknown','reason':'needs the user','requires_user':True,'decision_key':key,'question':'?'})
        packet['validation_record']['limits'].append(NEST+'/'+c['flow_rel']+'/02_課題定義/problem_map.yaml')
        write_yaml(layer/'Context/course_input.yaml',packet);root=self.draft(layer)
        def ask(qname,**over):
            r={'stage':'persona','question':'Which actual persona should be used?','answer':'Synthetic reply only','question_id':'SYN-'+qname,'source_thread_id':'SYNTHETIC-THREAD','answered_at':datetime.now(timezone.utc).isoformat()};r.update(over)
            write_yaml(layer/'Context'/(qname+'.yaml'),r);return 'Context/'+qname+'.yaml'
        self.assertTrue(package.receipt(layer,ask('p'))['bound'])
        v=package.load(root/'validation_record.yaml');write_yaml(root/'validation_checkpoint.yaml',{k:x for k,x in v.items() if k!='actual_new_user_response'})
        self.assertTrue(package.receipt(layer,ask('v',stage='validation',question='Use H1 for validation?'))['pass'])
        d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d)
        return layer,root,c

    def test_dry_run_writes_nothing_and_shows_one_table_for_every_file(self):
        layer,root,c=self.nested()
        (root/c['flow_rel']/'01_ペルソナ作成/memo.md').write_text('a note outside the records')       # Flow side, not a record
        (root/'validation_results.yaml').write_text('note: package-level file\n')                       # package level, not a record
        (root/c['stock_project_rel']/'README_extra.md').write_text('stays behind')                      # Stock side, not a document
        before=tr.state(self.repo)
        r=package.migrate_sheets(layer)
        self.assertFalse(r['applied']);self.assertIn('dry_run',r);self.assertEqual(tr.state(self.repo),before)
        to={x['from']:x['to'] for x in r['moves']}
        self.assertEqual(to[NEST+'/'+c['flow_rel']+'/01_ペルソナ作成/memo.md'],'Sheets/01_ペルソナ作成/memo.md')
        self.assertEqual(to[NEST+'/validation_results.yaml'],'Sheets/validation_results.yaml')
        self.assertEqual(to[NEST+'/registers/wbs.yaml'],'Sheets/wbs.yaml')
        self.assertTrue(all(not t.startswith(('Sheets/Flow/','Sheets/Stock/','Sheets/registers/')) for t in to.values()))
        self.assertEqual(r['retire']['left_files'],[NEST+'/'+c['stock_project_rel']+'/README_extra.md'])
        self.assertEqual((r['from_layout'],r['to_layout']),('nested_v1','sheets_v1'))
        files={w['file'] for w in r['rewrites']}
        self.assertTrue({'intent.yaml','Sheets/manifest.yaml','Sheets/format_contract.yaml','Sheets/wbs.yaml','Sheets/project_init.yaml'}<=files)

    def test_apply_moves_in_one_step_keeps_bytes_and_times_and_then_archives(self):
        layer,root,c=self.nested('one',pending=False)
        (root/c['flow_rel']/'01_ペルソナ作成/memo.md').write_text('a note outside the records')
        (root/c['flow_rel']/'01_ペルソナ作成/.DS_Store').write_bytes(b'os meta')
        before_errors=self.errors(layer,root);self.assertEqual(before_errors,[])
        old=package.load(root/'manifest.yaml');old_hash={x['source_step']:(x['sha256'],x['generated_mtime_ns']) for x in old['records']}
        memo=root/c['flow_rel']/'01_ペルソナ作成/memo.md';memo_state=(sha(memo),memo.stat().st_mtime_ns)
        old_outputs=package.load(layer/'intent.yaml')['mode_init']['outputs'];packet=sha(layer/'Context/course_input.yaml')
        with self.assertRaisesRegex(ValueError,'--program'):package.migrate_sheets(layer,apply=True,approval_ref='synthetic')
        with self.assertRaisesRegex(ValueError,'approval-ref'):package.migrate_sheets(layer,apply=True,program='Sample')
        r=package.migrate_sheets(layer,apply=True,approval_ref='synthetic approval',program='Sample',retire='Documents/aipm_retired/s1')
        self.assertTrue(r['applied']);self.assertEqual(r['validate_after'],[])
        sheets=layer/'Sheets'
        self.assertFalse((layer/NEST).exists());self.assertTrue((layer/'Documents/aipm_retired/s1/aipm_project').is_dir())
        self.assertEqual([q.name for q in (layer/'Documents/aipm_retired/s1').rglob('*') if q.is_file()],['.DS_Store'])   # only emptied folders and the OS file
        self.assertEqual((sha(sheets/'01_ペルソナ作成/memo.md'),(sheets/'01_ペルソナ作成/memo.md').stat().st_mtime_ns),memo_state)
        m=package.load(sheets/'manifest.yaml');fc=package.load(sheets/'format_contract.yaml')
        self.assertEqual((fc['layout'],fc['package_root'],m['flow_rel'],m['stock_project_rel'],m['contract_version']),(package.SHEETS_LAYOUT,'Sheets','','',fc['version']))
        for rec in m['records']:
            self.assertEqual(sha(sheets/rec['path']),rec['sha256'],rec['path']);self.assertEqual((sheets/rec['path']).stat().st_mtime_ns,rec['generated_mtime_ns'],rec['path'])
            if rec['source_step']!='write_init_yaml':self.assertEqual((rec['sha256'],rec['generated_mtime_ns']),old_hash[rec['source_step']],rec['path'])
        lm=m['layout_migrations'][-1]
        self.assertEqual((lm['from'],lm['to'],lm['by'],lm['program'],lm['approval_ref'],lm['flow_rel']['from']),('nested_v1','sheets_v1','package.py migrate-sheets','Sample','synthetic approval',c['flow_rel']))
        self.assertEqual(lm['rewritten']['sha256_before'],old_hash['write_init_yaml'][0]);self.assertEqual(lm['rewritten']['sha256_after'],sha(sheets/'project_init.yaml'))
        pi=package.load(sheets/'project_init.yaml');self.assertEqual((pi['program_id'],pi['flow_base']),('Sample','Sheets'))
        self.assertEqual(package.load(sheets/'wbs.yaml')['wbs'][0]['evidence_refs'],['Sheets'])
        it=package.load(layer/'intent.yaml');self.assertTrue((layer/'intent.yaml').read_text().startswith('# synthetic comment'))
        self.assertEqual(it['mode_init']['outputs'],m['stages'][0]['mode_init_outputs'])
        self.assertTrue(all(o['path'].startswith('Sheets/') for o in it['mode_init']['outputs']))
        self.assertEqual([o['sha256'] for o in it['mode_init']['outputs']],[o['sha256'] for o in old_outputs])
        self.assertEqual(sha(layer/'Context/course_input.yaml'),packet)
        self.assertEqual(package.build_contract(layer)['layout'],package.SHEETS_LAYOUT)
        with self.assertRaisesRegex(ValueError,'already sheets_v1'):package.migrate_sheets(layer)
        result=package.archive_course(layer);self.assertTrue(result['pass'],result['errors'])

    def test_stock_files_that_are_not_documents_stay_in_the_retired_folder(self):
        layer,root,c=self.nested('left',pending=False);extra=root/c['stock_project_rel']/'README_extra.md';extra.write_text('stays behind');state=(sha(extra),extra.stat().st_mtime_ns)
        r=package.migrate_sheets(layer,apply=True,approval_ref='synthetic',program='Sample',retire='Documents/aipm_retired/l1');self.assertTrue(r['applied'])
        kept=layer/'Documents/aipm_retired/l1/aipm_project'/c['stock_project_rel']/'README_extra.md'
        self.assertEqual((sha(kept),kept.stat().st_mtime_ns),state);self.assertFalse((layer/'Sheets/README_extra.md').exists())
        self.assertEqual(r['program'],'Sample');self.assertEqual(package.load(layer/'Sheets/manifest.yaml')['layout_migrations'][-1]['program'],'Sample')

    def test_pending_box_keeps_its_errors_only(self):
        layer,root,c=self.nested('pend');before=self.errors(layer,root);self.assertEqual({e[0] for e in before},{'E_CHECKPOINT'})
        r=package.migrate_sheets(layer,apply=True,approval_ref='synthetic',program='Sample');self.assertTrue(r['applied'])
        flow=c['flow_rel']+'/'
        self.assertEqual(r['validate_after'],sorted({(k,p[len(flow):] if p.startswith(flow) else p) for k,p in before}))

    def test_bound_replies_stay_bound_and_receipts_are_not_rewritten(self):
        layer,root,c=self.receipt_box('rc')
        self.assertTrue(validate_package.validate(root,phase='prearchive',layer=layer)['pass'])
        receipts={q.name:sha(q) for q in (layer/'Context').glob('receipt_*.yaml')};self.assertEqual(len(receipts),2)
        vr=sha(root/'validation_record.yaml');vc=sha(root/'validation_checkpoint.yaml')
        dry=package.migrate_sheets(layer)
        self.assertEqual({k['file'] for k in dry['kept_old_references']},{'Sheets/validation_record.yaml','Sheets/validation_checkpoint.yaml'})
        r=package.migrate_sheets(layer,apply=True,approval_ref='synthetic',program='Sample');self.assertTrue(r['applied'],r)
        sheets=layer/'Sheets';res=validate_package.validate(sheets,phase='prearchive',layer=layer)
        self.assertTrue(res['pass'],res['errors'])
        self.assertEqual({q.name:sha(q) for q in (layer/'Context').glob('receipt_*.yaml')},receipts)
        self.assertEqual((sha(sheets/'validation_record.yaml'),sha(sheets/'validation_checkpoint.yaml')),(vr,vc))
        m=package.load(sheets/'manifest.yaml');self.assertTrue(all(h['target_path'].startswith('Sheets/') for h in m['human_responses'].values()))
        # the reading of the old receipt path needs the recorded move: without it the replies are unbound
        m['layout_migrations']=[];write_yaml(sheets/'manifest.yaml',m)
        self.assertIn('E_CHECKPOINT',{e['code'] for e in validate_package.validate(sheets,phase='prearchive',layer=layer)['errors']})

    def test_receipt_after_the_move_or_a_forged_record_is_not_read(self):
        layer,root,c=self.receipt_box('fg')
        package.migrate_sheets(layer,apply=True,approval_ref='synthetic',program='Sample');sheets=layer/'Sheets'
        m=package.load(sheets/'manifest.yaml');lm=m['layout_migrations'][-1]
        for name,change in (('moved before the replies',lambda x:x.update(at='2000-01-01T00:00:00+00:00')),('box_root record for a nested box',lambda x:x.update({'from':'box_root_v1'})),('another flow_rel',lambda x:x['flow_rel'].update({'from':'Flow/202601/2026-01-01/other'})),('another tool',lambda x:x.update(by='hand'))):
            with self.subTest(case=name):
                x=dict(lm,flow_rel=dict(lm['flow_rel']));change(x);m2=dict(m,layout_migrations=[x]);write_yaml(sheets/'manifest.yaml',m2)
                self.assertIn('E_CHECKPOINT',{e['code'] for e in validate_package.validate(sheets,phase='prearchive',layer=layer)['errors']})

    def test_failure_puts_everything_back(self):
        layer,root,c=self.nested('fail')
        (root/c['flow_rel']/'01_ペルソナ作成/memo.md').write_text('a note outside the records')
        before=tr.state(layer)
        real=validate_package.validate;calls=[]
        def broken(*a,**k):
            calls.append(1);res=real(*a,**k)
            if len(calls)==2:res={**res,'errors':res['errors']+[{'code':'E_SYNTH','path':'x','message':'injected'}]}
            return res
        with mock.patch.object(validate_package,'validate',broken),self.assertRaisesRegex(ValueError,'new errors'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',retire='Documents/aipm_retired/f')
        self.assertEqual(tr.state(layer),before)
        last=len(package.migrate_sheets(layer)['moves'])+1   # every file, then the emptied folder to retire
        for n in (1,5,last):   # the first file, one in the middle, the folder to retire (after every write)
            with self.subTest(fail_at=n):
                real_rename=os.rename;count=[0]
                def flaky(a_,b_):
                    count[0]+=1
                    if count[0]==n:raise OSError('injected rename failure')
                    return real_rename(a_,b_)
                with mock.patch.object(package.os,'rename',flaky),self.assertRaises(OSError):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',retire='Documents/aipm_retired/f'+str(n))
                self.assertEqual(tr.state(layer),before)
        with mock.patch.object(package.os,'rename',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample')
        self.assertEqual(tr.state(layer),before)
        for n in (1,2):   # Ctrl-C while the rewritten files are written (the first registers text, then project_init.yaml)
            with self.subTest(interrupt_at_write=n):
                real_utime=os.utime;count=[0]
                def stop(*a_,**k_):
                    count[0]+=1
                    if count[0]==n:raise KeyboardInterrupt
                    return real_utime(*a_,**k_)
                with mock.patch.object(package.os,'utime',stop),self.assertRaises(KeyboardInterrupt):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample')
                self.assertEqual(tr.state(layer),before)

    def test_refusals_write_nothing(self):
        def archived(case):
            layer,root,c=case.nested('ar',pending=False);d=package.load(layer/'intent.yaml');d['aipm']['program_id']='Sample';write_yaml(layer/'intent.yaml',d)
            m=package.load(root/'manifest.yaml');m['stages'].append({'name':'archive'});write_yaml(root/'manifest.yaml',m);d['aipm'].pop('program_id');write_yaml(layer/'intent.yaml',d);return layer
        def stray_flow(case):
            layer,root,c=case.nested('sf');(root/'Flow/other.md').write_text('outside flow_rel');return layer
        def collision(case):
            layer,root,c=case.nested('co');(root/c['flow_rel']/'manifest.yaml').write_text('x: 1\n');return layer
        def evidence_inside(case):
            layer,root,c=case.nested('ev');m=package.load(root/'manifest.yaml');m['evidence'][0]['source']=NEST+'/'+c['flow_rel']+'/project_init.yaml';write_yaml(root/'manifest.yaml',m);return layer
        def unplaceable(case):
            layer,root,c=case.nested('un');m=package.load(root/'manifest.yaml');m['notes']=NEST+'/'+c['stock_project_rel']+'/nothing_here.md';write_yaml(root/'manifest.yaml',m);return layer
        def layout_written(case):
            layer,root,c=case.nested('lw');d=package.load(layer/'intent.yaml');d['aipm']['layout']='nested_v1';write_yaml(layer/'intent.yaml',d);return layer
        def hand_edited_init(case):
            layer,root,c=case.nested('he');q=root/c['flow_rel']/'project_init.yaml';import re as re_;q.write_text(re_.sub(r'^(program_id:.*)$',r'\1  # hand note',q.read_text(),count=1,flags=re_.M))   # a field the text rewrite cannot place (shape 2 keeps other hand formatting)
            m=package.load(root/'manifest.yaml')
            for r_ in m['records']:
                if r_['source_step']=='write_init_yaml':r_['sha256']=sha(q)   # recorded as it is now (an edit after the record is refused earlier)
            write_yaml(root/'manifest.yaml',m);return layer
        def unknown_program(case):
            layer,root,c=case.nested('up');return layer,None,'NoSuchProgram'
        def retire_inside(case):
            layer,root,c=case.nested('ri');return layer,'Sheets/retired','Sample'
        def intent_program_not_rewritable(case):   # the same program_id line twice (another map): which one is aipm's is not safe to tell by text
            layer,root,c=case.nested('op');q=layer/'intent.yaml';q.write_text(q.read_text().replace('aipm:\n','aipm:\n  program_id: L_COURSE\n',1)+'notes:\n  program_id: L_COURSE\n');return layer
        def no_init_record(case):
            layer,root,c=case.nested('ni');m=package.load(root/'manifest.yaml');m['records']=[r for r in m['records'] if r['source_step']!='write_init_yaml'];write_yaml(root/'manifest.yaml',m);return layer
        reasons={'archived':'without its Stock copy','stray_flow':'unexpected file','collision':'two files for one place','evidence_inside':'evidence source lives inside',
                 'unplaceable':'cannot put','layout_written':'aipm.layout is written','hand_edited_init':'not as the tool wrote it','unknown_program':'does not exist','retire_inside':'outside the package',
                 'intent_program_not_rewritable':'cannot be rewritten by text safely','no_init_record':'no complete project_init.yaml record'}
        for build in (archived,stray_flow,collision,evidence_inside,unplaceable,layout_written,hand_edited_init,unknown_program,retire_inside,intent_program_not_rewritable,no_init_record):
            with self.subTest(case=build.__name__):
                out=build(self);layer,retire,program=(out if isinstance(out,tuple) else (out,None,'Sample'));before=tr.state(self.repo)
                with self.assertRaisesRegex(ValueError,reasons[build.__name__]):package.migrate_sheets(layer,apply=True,approval_ref='synthetic',retire=retire,program=program)
                self.assertEqual(tr.state(self.repo),before)

    def archived_box(self,name):
        """A nested_v1 box archived the old way: the Stock copies sit inside the package (Stock/programs/<L_xxxx>/...)."""
        layer,root,c=self.nested(name,pending=False);res=package.archive_course(layer);self.assertTrue(res['pass'],res['errors'])
        m=package.load(root/'manifest.yaml');self.assertTrue(all(r['archive_path'].startswith(c['stock_project_rel']+'/documents/') for r in m['records'] if r['archive_path']))
        return layer,root,c,m

    def test_archived_box_goes_to_the_real_stock_under_its_business(self):
        layer,root,c,m=self.archived_box('arc');db=rf.db_path(self.registry)
        self.assertTrue(validate_package.validate(root,phase='final',layer=layer)['pass'])
        copies={r['source_step']:(r['archive_sha256'],(root/r['archive_path']).stat().st_mtime_ns) for r in m['records'] if r['archive_path']}
        dry=package.migrate_sheets(layer);self.assertTrue(dry['archived']);self.assertIsInstance(dry['stock_copies'],str)   # no program: the destination is not looked up
        before=tr.state(self.repo);dry=package.migrate_sheets(layer,program='Sample',registry_db=db);self.assertEqual(tr.state(self.repo),before)
        target='Stock/programs/Sample/projects/'+rf.BUSINESS+'/course_fixture'
        self.assertEqual(dry['archive_target']['target_rel'],target);self.assertEqual(len(dry['stock_copies']),len(copies))
        self.assertTrue(all(x['to'].startswith(target+'/documents/') for x in dry['stock_copies']))
        r=package.migrate_sheets(layer,apply=True,approval_ref='synthetic',program='Sample',registry_db=db,retire='Documents/aipm_retired/a1')
        self.assertTrue(r['applied'],r);self.assertEqual(r['validate_phase'],'final');self.assertEqual(r['validate_after'],[])
        sheets=layer/'Sheets';m2=package.load(sheets/'manifest.yaml')
        self.assertEqual(m2['archive_target']['target_rel'],target);self.assertEqual(m2['layout_migrations'][-1]['stock_copies'],len(copies))
        for rec in m2['records']:
            if not rec['archive_path']:continue
            q=self.repo/rec['archive_path'];self.assertTrue(rec['archive_path'].startswith(target+'/documents/'))
            self.assertEqual((sha(q),q.stat().st_mtime_ns),copies[rec['source_step']],rec['archive_path'])   # copied with bytes and mtime
        inner=layer/'Documents/aipm_retired/a1/aipm_project'/c['stock_project_rel']/'documents'
        self.assertEqual(len([q for q in inner.rglob('*') if q.is_file()]),len(copies))   # the inner copies are kept in the retired folder
        res=validate_package.validate(sheets,phase='final',layer=layer);self.assertTrue(res['pass'],res['errors'])

    def test_archived_box_refusals_and_failure_write_nothing(self):
        db=rf.db_path(self.registry)
        layer,root,c,m=self.archived_box('anp')
        import tempfile;tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);empty=Path(tmp.name);rf.make_registry(empty);before=tr.state(self.repo)   # outside the repository
        with self.assertRaisesRegex(ValueError,'projects rows for L-COURSE'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=rf.db_path(empty))
        self.assertEqual(tr.state(self.repo),before)
        with self.assertRaisesRegex(ValueError,'does not exist'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='NoSuchProgram',registry_db=db)
        self.assertEqual(tr.state(self.repo),before)
        import sqlite3
        con=sqlite3.connect(rf.db_path(empty));con.execute("INSERT INTO projects (scope_id) VALUES ('L-COURSE')");con.commit();con.close()   # registered, but no primary business project
        with self.assertRaisesRegex(ValueError,'no primary business project'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=rf.db_path(empty))
        self.assertEqual(tr.state(self.repo),before)
        dest=self.repo/'Stock/programs/Sample/projects'/rf.BUSINESS/'course_fixture/documents/02_課題定義/problem_map.yaml'
        dest.parent.mkdir(parents=True);dest.write_text('already here');before=tr.state(self.repo)
        with self.assertRaisesRegex(ValueError,'already exists in the real Stock'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=db)
        self.assertEqual(tr.state(self.repo),before)
        dest.unlink();[d.rmdir() for d in (dest.parent,dest.parent.parent,dest.parent.parent.parent,dest.parent.parent.parent.parent)]
        rec=next(r for r in m['records'] if r['archive_path']);q=root/rec['archive_path'];orig=q.read_bytes();q.write_text('changed');before=tr.state(self.repo)
        with self.assertRaisesRegex(ValueError,'missing or changed'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=db)
        self.assertEqual(tr.state(self.repo),before);q.write_bytes(orig)
        before=tr.state(self.repo);real_open=open;made_by_other=[]
        def racing(path,mode='r',*a_,**k_):   # another writer makes the destination between the plan and the copy
            if mode=='xb' and not made_by_other:Path(path).write_text('made by another writer');made_by_other.append(Path(path))
            return real_open(path,mode,*a_,**k_)
        with mock.patch('builtins.open',racing),self.assertRaises(FileExistsError):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=db)
        self.assertEqual(made_by_other[0].read_text(),'made by another writer')   # never overwritten, never removed
        made_by_other[0].unlink()
        for d in (made_by_other[0].parent,*made_by_other[0].parent.parents):
            if d==self.repo/'Stock/programs/Sample/projects':break
            d.rmdir()
        self.assertEqual(tr.state(self.repo),before)
        real=validate_package.validate;calls=[]
        def broken(*a,**k):
            calls.append(1);res=real(*a,**k)
            if len(calls)==2:res={**res,'errors':res['errors']+[{'code':'E_SYNTH','path':'x','message':'injected'}]}
            return res
        with mock.patch.object(validate_package,'validate',broken),self.assertRaisesRegex(ValueError,'new errors'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=db)
        self.assertEqual(tr.state(self.repo),before)   # the real Stock copies and their folders are gone again
        real_stat=package.shutil.copystat;count=[0]
        def stop(*a_,**k_):   # Ctrl-C after the third real Stock copy was written, before its times are set
            count[0]+=1
            if count[0]==3:raise KeyboardInterrupt
            return real_stat(*a_,**k_)
        with mock.patch.object(package.shutil,'copystat',stop),self.assertRaises(KeyboardInterrupt):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=db)
        self.assertEqual(tr.state(self.repo),before)

    def legacy_box(self,name,internal=True,init_reply=True):
        """An archived legacy (question_based) nested_v1 box like the real ones: records' inputs and one evidence point at a
        package document (case C1), and the init reply is bound to project_init.yaml."""
        layer=self.base/name;root,c=ti.fixture(layer,scope='L-LEG-'+name,project='leg_'+name)
        m=package.load(root/'manifest.yaml');first=next(r['path'] for r in m['records'] if r['stage']=='persona')
        if internal:
            m['evidence'].append({'id':'F2','kind':'hypothesis','source':NEST+'/'+first,'source_sha256':sha(root/first),'scope':'synthetic package source'})
            for r in m['records']:
                if r['stage'] in ('problem','solution','story'):r['inputs'].append(NEST+'/'+first);r['evidence_refs'].append('F2')
            write_yaml(root/'manifest.yaml',m)
        if init_reply:bind_init(layer,root)
        d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d)
        rf.register(self.registry,'L-LEG-'+name);return layer,root,c

    def test_legacy_archived_box_keeps_its_stage_times_and_init_reply(self):
        layer,root,c=self.legacy_box('a');db=rf.db_path(self.registry)
        res=validate_package.validate(root,phase='final',layer=layer);self.assertTrue(res['pass'],res['errors'])
        m=package.load(root/'manifest.yaml');receipt=sha(layer/'Context/init_reply.yaml')
        times={r['source_step']:r['generated_mtime_ns'] for r in m['records']};hashes={r['source_step']:r['sha256'] for r in m['records']}
        r=package.migrate_sheets(layer,apply=True,approval_ref='synthetic',program='Sample',registry_db=db)
        self.assertTrue(r['applied'],r);self.assertEqual(r['validate_after'],[])
        sheets=layer/'Sheets';m2=package.load(sheets/'manifest.yaml')
        self.assertEqual(m2['stages'],m['stages'])   # the recorded stage times are not touched
        self.assertEqual({x['source_step']:x['generated_mtime_ns'] for x in m2['records']},times)
        for x in m2['records']:
            self.assertEqual((sheets/x['path']).stat().st_mtime_ns,x['generated_mtime_ns'],x['path'])
            if x['source_step']!='write_init_yaml':self.assertEqual(sha(sheets/x['path']),hashes[x['source_step']],x['path'])   # the same bytes as before the move
        self.assertEqual(next(e for e in m2['evidence'] if e['id']=='F2')['source'],'Sheets/'+next(x['path'] for x in m2['records'] if x['stage']=='persona'))
        self.assertTrue(all(i.startswith(('Context/','Sheets/')) for x in m2['records'] for i in x['inputs']))
        self.assertEqual(sha(layer/'Context/init_reply.yaml'),receipt)   # the receipt is not rewritten
        h=m2['human_responses']['init'];lm=m2['layout_migrations'][-1]
        self.assertEqual((h['target_sha256'],m2['checkpoint_targets']['init']),(lm['rewritten']['sha256_before'],lm['rewritten']['sha256_before']))
        self.assertNotEqual(sha(sheets/'project_init.yaml'),lm['rewritten']['sha256_before']);self.assertEqual(lm['course'],package.LEGACY_COURSE)
        res=validate_package.validate(sheets,phase='final',layer=layer);self.assertTrue(res['pass'],res['errors'])
        for name,change in (('no rewrite record',lambda x:x.pop('rewritten')),('other bytes after',lambda x:x['rewritten'].update(sha256_after='0'*64)),('moved before the reply',lambda x:x.update(at='2000-01-01T00:00:00+00:00')),('another path',lambda x:x['rewritten'].update(path='README.md')),('other bytes before',lambda x:x['rewritten'].update(sha256_before='0'*64)),('another field rewritten',lambda x:x['rewritten'].update(fields=['program_id','participant_name']))):
            with self.subTest(case=name):
                x=dict(lm,rewritten=dict(lm['rewritten']));change(x);write_yaml(sheets/'manifest.yaml',dict(m2,layout_migrations=[x]))
                errs={(e['code'],e['path']) for e in validate_package.validate(sheets,phase='final',layer=layer)['errors']}
                self.assertIn(('E_CHECKPOINT','stages.init'),errs)
        write_yaml(sheets/'manifest.yaml',m2)

    def test_legacy_box_stopped_at_a_stage_keeps_its_errors_only(self):
        lr=ti.LegacyReceipt('test_solution_is_bound_and_its_checkpoint_errors_clear');lr.base=self.base
        layer,root,c=lr.cut('legB','solution');self.assertTrue(package.receipt(layer,lr.ask(layer,'s1','solution'))['bound'])
        d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d)
        before=self.errors(layer,root);self.assertTrue(before)
        r=package.migrate_sheets(layer,apply=True,approval_ref='synthetic',program='Sample');self.assertTrue(r['applied'],r)
        flow=c['flow_rel']+'/'
        self.assertEqual(r['validate_after'],sorted({(k,p[len(flow):] if p.startswith(flow) else p) for k,p in before}))   # the solution reply stays bound

    def test_manifest_keys_naming_old_paths_are_rewritten_or_refused(self):
        layer,root,c=self.legacy_box('k',internal=False,init_reply=False);m=package.load(root/'manifest.yaml')
        docs=[r['path'] for r in m['records'] if r['stage']=='solution']
        m['related_versions']={NEST+'/'+d:'v1' for d in docs};write_yaml(root/'manifest.yaml',m)
        r=package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=rf.db_path(self.registry));self.assertTrue(r['applied'],r)
        m2=package.load(layer/'Sheets/manifest.yaml');self.assertEqual(set(m2['related_versions']),{'Sheets/'+x['path'] for x in m2['records'] if x['stage']=='solution'})
        layer,root,c=self.legacy_box('k2',internal=False,init_reply=False);m=package.load(root/'manifest.yaml');d=next(r['path'] for r in m['records'] if r['stage']=='solution')
        m['related_versions']={NEST+'/'+d:'v1','Sheets/'+d[len(c['flow_rel'])+1:]:'v2'};write_yaml(root/'manifest.yaml',m);before=tr.state(self.repo)   # two keys for one place
        with self.assertRaisesRegex(ValueError,'two manifest keys become one'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=rf.db_path(self.registry))
        self.assertEqual(tr.state(self.repo),before)
        m['related_versions']={NEST+'/'+c['stock_project_rel']+'/nothing.md':'v1'};write_yaml(root/'manifest.yaml',m);before=tr.state(self.repo)   # a key the table cannot place
        with self.assertRaisesRegex(ValueError,'cannot put'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=rf.db_path(self.registry))
        self.assertEqual(tr.state(self.repo),before)

    def test_legacy_evidence_on_a_rewritten_file_is_refused(self):
        layer,root,c=self.legacy_box('ev',init_reply=False);m=package.load(root/'manifest.yaml')   # format_contract.yaml (project_init.yaml is read through the rewrite: shape 3)
        m['evidence'].append({'id':'F3','kind':'hypothesis','source':NEST+'/format_contract.yaml','source_sha256':sha(root/'format_contract.yaml'),'scope':'synthetic'});write_yaml(root/'manifest.yaml',m)
        before=tr.state(self.repo)
        with self.assertRaisesRegex(ValueError,'evidence source is a file this move rewrites'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=rf.db_path(self.registry))
        self.assertEqual(tr.state(self.repo),before)

    def test_intent_program_is_rewritten_to_the_chosen_program(self):
        layer,root,c,m=self.archived_box('ip');db=rf.db_path(self.registry)
        d=package.load(layer/'intent.yaml');self.assertNotIn('program_id',d['aipm'])
        q=layer/'intent.yaml';q.write_text(q.read_text().replace('aipm:\n','aipm:\n  program_id: L_COURSE  # the old nested_v1 program\n',1))
        before=tr.state(self.repo);real=validate_package.validate;calls=[]
        def broken(*a,**k):   # a failure after intent was rewritten puts intent back too
            calls.append(1);res=real(*a,**k)
            if len(calls)==2:res={**res,'errors':res['errors']+[{'code':'E_SYNTH','path':'x','message':'injected'}]}
            return res
        with mock.patch.object(validate_package,'validate',broken),self.assertRaisesRegex(ValueError,'new errors'):package.migrate_sheets(layer,apply=True,approval_ref='s',program='Sample',registry_db=db)
        self.assertEqual(tr.state(self.repo),before);self.assertEqual(package.load(q)['aipm']['program_id'],'L_COURSE')
        self.assertEqual(package.load(q)['aipm']['program_id'],'L_COURSE')   # the saved nested_v1 contract was built from the scope (L_COURSE) too
        self.assertTrue(validate_package.validate(root,phase='final',layer=layer)['pass'])
        r=package.migrate_sheets(layer,apply=True,approval_ref='synthetic',program='Sample',registry_db=db);self.assertTrue(r['applied'],r)
        self.assertIn({'file':'intent.yaml','field':'aipm.program_id','from':'L_COURSE','to':'Sample'},r['rewrites'])
        self.assertEqual(q.read_text().count('program_id: Sample  # the old nested_v1 program'),1)   # the comment is kept
        self.assertEqual(package.load(layer/'Sheets/manifest.yaml')['layout_migrations'][-1]['intent_program_id'],{'from':'L_COURSE','to':'Sample'})
        self.assertEqual(package.build_contract(layer)['bindings']['program_id'],'Sample')
        res=validate_package.validate(layer/'Sheets',phase='final',layer=layer);self.assertTrue(res['pass'],res['errors'])

    def test_box_root_route_refuses_nested_only_options(self):
        layer=self.base/'br';ti.fixture(layer,layout=package.BOX_ROOT_LAYOUT);d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d);before=tr.state(layer)
        with self.assertRaisesRegex(ValueError,'nested_v1 package'):package.migrate_sheets(layer,program='Sample')
        self.assertEqual(tr.state(layer),before)

    def test_cli_dry_run(self):
        layer,root,c=self.nested('cli');before=tr.state(layer)
        code,out=tr.run_cli('migrate-sheets','--layer',str(layer),'--program','Sample');self.assertEqual(code,0);self.assertFalse(out['applied']);self.assertEqual(out['program'],'Sample')
        self.assertEqual(tr.state(layer),before)

if __name__=='__main__':unittest.main()
