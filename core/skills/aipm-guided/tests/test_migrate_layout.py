"""package.py migrate-layout moves one nested_v1 package to box_root_v1 in place. The fixture is
shaped like a real box (document_based course, registers, Collection Phase 7.5 init recorded in intent mode_init, a WBS
evidence reference into the inner Flow folder, pending human decisions). Synthetic fixtures only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
from datetime import datetime, timezone
import json, tempfile, unittest, yaml
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import test_integration as ti
import test_init_and_reset as tr
import registry_fixture as rf
package=ti.package;validate_package=ti.validate_package;write_yaml,sha=ti.write_yaml,ti.sha

def in_repository(case):
    case.temp=tempfile.TemporaryDirectory();case.repo=Path(case.temp.name)
    case.base=case.repo/'Flow/202608/2026-08-19';case.base.mkdir(parents=True);(case.repo/'Stock/programs/Sample').mkdir(parents=True)
    rf.auto_register(case,package)

class MigrateLayout(unittest.TestCase):
    setUp=in_repository
    def tearDown(self):self.temp.cleanup()
    prepare=ti.CourseIntegration.prepare;mode_init_layer=ti.CourseIntegration.mode_init_layer;draft=ti.CourseIntegration.draft
    def nested(self,name='l0819like',pending=True):
        """A nested_v1 package like a real box: mode_init, draft, a WBS reference into the inner Flow, a comment in intent."""
        layer,root,out=self.mode_init_layer(name,True,'document_based/single_persona')
        if pending:   # the decisions wait for the person (prearchive has only E_CHECKPOINT)
            p=package.load(layer/'Context/course_input.yaml');p['decisions']['persona'].update(state='pending',question='Which actual persona should be used?');write_yaml(layer/'Context/course_input.yaml',p)
        self.draft(layer);c=package.build_contract(layer)
        w=package.load(root/'registers/wbs.yaml');w['wbs'][0]['evidence_refs']=['Documents/aipm_project/'+c['flow_rel']+'/'];write_yaml(root/'registers/wbs.yaml',w)
        d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d)   # the real nested packages have no aipm.layout
        (layer/'intent.yaml').write_text('# synthetic comment kept by the migration\n'+(layer/'intent.yaml').read_text())
        return layer,root,c
    def errors(self,layer,root):return sorted({(e['code'],e['path']) for e in validate_package.validate(root,phase='prearchive',layer=layer)['errors']})

    def test_dry_run_writes_nothing_and_shows_the_plan(self):
        layer,root,c=self.nested();before=tr.state(self.repo)
        r=package.migrate_layout(layer)
        self.assertFalse(r['applied']);self.assertIn('dry_run',r);self.assertEqual(tr.state(self.repo),before)
        self.assertEqual(len(r['moves']),19)
        for x in r['moves']:self.assertTrue(x['from'].startswith(('Flow/','Stock/')));self.assertFalse(x['to'].startswith(('Flow/','Stock/')))
        files={w['file'] for w in r['rewrites']}
        self.assertTrue({'intent.yaml','Documents/aipm_project/manifest.yaml','Documents/aipm_project/format_contract.yaml','Documents/aipm_project/registers/wbs.yaml','Documents/aipm_project/project_init.yaml'}<=files)
        self.assertEqual([m['from'] for m in r['retire']['moves']],['Documents/aipm_project/Flow','Documents/aipm_project/Stock'])

    def test_apply_keeps_document_hashes_and_validate_and_then_archive_to_the_real_stock(self):
        layer,root,c=self.nested();before_errors=self.errors(layer,root)
        self.assertTrue(before_errors);self.assertEqual({e[0] for e in before_errors},{'E_CHECKPOINT'})
        packet=sha(layer/'Context/course_input.yaml');old=package.load(root/'manifest.yaml')
        old_hash={r['source_step']:(r['sha256'],r['generated_mtime_ns']) for r in old['records']}
        (root/c['flow_rel']/'01_ペルソナ作成/.DS_Store').write_bytes(b'os meta')   # an OS file moves with the emptied folders
        bl={'tasks':[{'id':'T1','output':'Documents/aipm_project/'+c['flow_rel']+'/01_ペルソナ作成/x.md'}]};write_yaml(layer/'backlog.yaml',bl)
        with self.assertRaises(ValueError):package.migrate_layout(layer,apply=True)   # --apply needs --program
        dry=package.migrate_layout(layer);self.assertEqual(dry['outside_references'],['backlog.yaml:3'])   # shown, not rewritten
        old_outputs=package.load(layer/'intent.yaml')['mode_init']['outputs']
        r=package.migrate_layout(layer,apply=True,retire='Documents/aipm_retired/m1',program='Sample')
        self.assertTrue(r['applied']);self.assertEqual(r['validate_after'],before_errors)
        self.assertFalse((root/'Flow').exists());self.assertFalse((root/'Stock').exists())
        self.assertTrue((layer/'Documents/aipm_retired/m1/Flow').is_dir())
        self.assertEqual([q.name for q in (layer/'Documents/aipm_retired/m1').rglob('*') if q.is_file()],['.DS_Store'])   # only emptied folders (and the OS file) were moved
        self.assertEqual(package.load(layer/'backlog.yaml'),bl)
        m=package.load(root/'manifest.yaml');fc=package.load(root/'format_contract.yaml')
        self.assertEqual((fc['layout'],m['flow_rel'],m['stock_project_rel'],m['contract_version']),(package.BOX_ROOT_LAYOUT,'','',fc['version']))
        for rec in m['records']:
            self.assertEqual(sha(root/rec['path']),rec['sha256'],rec['path'])
            if rec['source_step']!='write_init_yaml':self.assertEqual((rec['sha256'],rec['generated_mtime_ns']),old_hash[rec['source_step']],rec['path'])   # renamed, not rewritten
        lm=m['layout_migrations'];self.assertEqual((len(lm),lm[0]['from'],lm[0]['to'],lm[0]['moved_documents']),(1,'nested_v1','box_root_v1',19))
        self.assertEqual(lm[0]['rewritten']['sha256_before'],old_hash['write_init_yaml'][0]);self.assertEqual(lm[0]['rewritten']['sha256_after'],sha(root/'project_init.yaml'))
        pi=package.load(root/'project_init.yaml');self.assertEqual((pi['flow_base'],pi['stock_base'],pi['program_id']),('Documents/aipm_project','Stock/programs/Sample/projects/course_fixture','Sample'))
        self.assertEqual([o['sha256'] for o in package.load(layer/'intent.yaml')['mode_init']['outputs']],[o['sha256'] for o in old_outputs])   # init-time hashes kept, only paths move
        self.assertEqual(sha(layer/'Context/course_input.yaml'),packet)   # the input packet stays as it was
        it=package.load(layer/'intent.yaml');self.assertTrue((layer/'intent.yaml').read_text().startswith('# synthetic comment'))
        self.assertEqual(it['mode_init']['outputs'],m['stages'][0]['mode_init_outputs'])
        self.assertTrue(all(not o['path'].startswith(('Documents/aipm_project/Flow/','Documents/aipm_project/Stock/')) for o in it['mode_init']['outputs']))
        self.assertEqual(package.load(root/'registers/wbs.yaml')['wbs'][0]['evidence_refs'],['Documents/aipm_project/'])
        self.assertEqual(package.build_contract(layer)['layout'],package.BOX_ROOT_LAYOUT)   # the saved layout now wins
        with self.assertRaises(ValueError):package.migrate_layout(layer)                       # already box_root_v1
        before=tr.state(self.repo)
        self.assertFalse(package.archive_course(layer)['pass'])   # the decisions still wait for the person: archive stops at prearchive
        self.assertEqual(tr.state(self.repo),before)
        with self.assertRaises(ValueError):package.reset_to_init(layer)   # the init-time hashes no longer rebuild: reset-to-init refuses after a move
    def test_program_chosen_at_the_migration_goes_to_the_real_stock(self):
        layer,root,c=self.nested('prog',pending=False)
        with self.assertRaises(ValueError):package.migrate_layout(layer,program='NoSuchProgram')   # must exist in the repository Stock
        r=package.migrate_layout(layer,apply=True,program='Sample');self.assertTrue(r['applied']);self.assertEqual(r['validate_after'],[])
        fc=package.load(root/'format_contract.yaml');self.assertEqual(fc['stock_target_rel'],'Stock/programs/Sample/projects/course_fixture')
        self.assertEqual(package.load(root/'project_init.yaml')['program_id'],'Sample')
        self.assertNotIn('program_id',package.load(layer/'intent.yaml')['aipm'])   # the saved contract carries it
        result=package.archive_course(layer);self.assertTrue(result['pass'],result['errors'])
        self.assertTrue((self.repo/'Stock/programs/Sample/projects'/rf.BUSINESS/'course_fixture/documents/02_課題定義/problem_map.yaml').is_file())
        d=package.load(layer/'intent.yaml');d['aipm']['program_id']='Other';write_yaml(layer/'intent.yaml',d)
        with self.assertRaises(ValueError):validate_package.validate(root,phase='final',layer=layer)   # a different program in intent stops

    def test_failure_puts_everything_back(self):
        from unittest import mock
        layer,root,c=self.nested();before=tr.state(layer)
        real=validate_package.validate;calls=[]
        def broken(*a,**k):
            calls.append(1);res=real(*a,**k)
            if len(calls)==2:res={**res,'errors':res['errors']+[{'code':'E_SYNTH','path':'x','message':'injected'}]}
            return res
        with mock.patch.object(validate_package,'validate',broken),self.assertRaises(ValueError):package.migrate_layout(layer,apply=True,retire='Documents/aipm_retired/f',program='Sample')
        self.assertEqual(tr.state(layer),before)

    def test_refusals_write_nothing(self):
        def archived(case):
            layer,root,c=case.nested('ar',pending=False);package.archive_course(layer);return layer
        def receipts(case):
            layer,root,c=case.nested('rc');m=package.load(root/'manifest.yaml');m['human_responses']={'persona':{'source':'Context/x.yaml'}};write_yaml(root/'manifest.yaml',m);return layer
        def stray(case):
            layer,root,c=case.nested('st');(root/c['flow_rel']/'memo.md').write_text('hand note');return layer
        def legacy(case):
            layer=case.base/'lg';ti.fixture(layer);d=package.load(layer/'intent.yaml');d['aipm'].pop('layout');write_yaml(layer/'intent.yaml',d);return layer
        def box_root(case):
            layer=case.base/'br';ti.fixture(layer,layout=package.BOX_ROOT_LAYOUT);return layer
        def layout_written(case):
            layer,root,c=case.nested('lw');d=package.load(layer/'intent.yaml');d['aipm']['layout']='nested_v1';write_yaml(layer/'intent.yaml',d);return layer
        def contract_differs(case):
            layer,root,c=case.nested('cd');fc=package.load(root/'format_contract.yaml');fc['folders'].append('extra');write_yaml(root/'format_contract.yaml',fc);return layer
        def missing_document(case):
            layer,root,c=case.nested('md');(root/c['flow_rel']/'02_課題定義/problem_map.yaml').rename(layer/'Context/aside.yaml');return layer
        def target_exists(case):
            layer,root,c=case.nested('te');(root/'02_課題定義').mkdir();(root/'02_課題定義/problem_map.yaml').write_text('x');return layer
        def hand_edited_init(case):
            layer,root,c=case.nested('he');q=root/c['flow_rel']/'project_init.yaml';q.write_text('# hand note\n'+q.read_text());return layer
        def unknown_program(case):
            layer,root,c=case.nested('up');return layer,None,'NoSuchProgram'
        def retire_inside(case):
            layer,root,c=case.nested('ri');return layer,'Documents/aipm_project/retired','Sample'
        reasons={'archived':'already archived','receipts':'actual-user replies','stray':'unexpected file','legacy':'legacy course','box_root':'already box_root_v1',
                 'layout_written':'aipm.layout is written','contract_differs':'differs from the rebuilt','missing_document':'document missing','target_exists':'target already exists',
                 'hand_edited_init':'not as the tool wrote it','unknown_program':'does not exist','retire_inside':'outside the package'}
        for build in (archived,receipts,stray,legacy,box_root,layout_written,contract_differs,missing_document,target_exists,hand_edited_init,unknown_program,retire_inside):
            with self.subTest(case=build.__name__):
                out=build(self);layer,retire,program=(out if isinstance(out,tuple) else (out,None,'Sample'));before=tr.state(self.repo)
                with self.assertRaisesRegex(ValueError,reasons[build.__name__]):package.migrate_layout(layer,apply=True,retire=retire,program=program)
                self.assertEqual(tr.state(self.repo),before)

    def test_cli_dry_run(self):
        layer,root,c=self.nested('cli');before=tr.state(layer)
        code,out=tr.run_cli('migrate-layout','--layer',str(layer));self.assertEqual(code,0);self.assertFalse(out['applied'])
        self.assertEqual(tr.state(layer),before)

if __name__=='__main__':unittest.main()
