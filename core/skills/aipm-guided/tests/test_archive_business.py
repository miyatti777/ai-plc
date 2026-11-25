"""a box_root_v1 archive copies to
Stock/programs/<program>/projects/<business display name>/<project>/documents/, the business being the Layer's primary
(confirmed) business project read only from the Registry. Every refusal writes nothing (Stock, Registry, manifest).
Synthetic repository and Registry only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import sqlite3, tempfile, unicodedata, unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent));sys.path.insert(0,str(HERE))
import package, validate_package
import test_integration as ti, test_init_and_reset as tr
import test_box_root_compat as bc
import registry_fixture as rf
write_yaml,sha=ti.write_yaml,ti.sha

def setup(case):
    case.temp=tempfile.TemporaryDirectory();case.repo=Path(case.temp.name)
    case.base=case.repo/'Flow/202610/2026-10-24';case.base.mkdir(parents=True);(case.repo/'Stock/programs/Sample').mkdir(parents=True)
    rf.standard(case.repo)

class ArchiveUnderBusiness(unittest.TestCase):
    setUp=setup
    def tearDown(self):self.temp.cleanup()
    prepare=bc.box_root_prepare;draft=ti.CourseIntegration.draft
    def layer(self,name,link=True,**aipm):
        layer,c,packet=self.prepare(name,**aipm);root=self.draft(layer)
        scope=package.load(layer/'intent.yaml')['scope_id']
        if link:rf.register(self.repo,scope)
        return layer,root,scope
    def snapshot(self):return tr.state(self.repo/'Stock'),sha(rf.db_path(self.repo))

    def test_archive_goes_under_the_business_and_final_passes(self):
        layer,root,scope=self.layer('a');db=sha(rf.db_path(self.repo))
        result=package.archive_course(layer);self.assertTrue(result['pass'],result['errors'])
        self.assertEqual(sha(rf.db_path(self.repo)),db)   # the Registry is only read
        m=package.load(root/'manifest.yaml');t=m['archive_target']
        self.assertEqual(t['business_display_name'],rf.BUSINESS);self.assertEqual((t['business_uid'],t['business_name'],t['program_uid'],t['scope_id'],t['source']),('bpr_synthetic_test',rf.BUSINESS,rf.PROGRAM_UID,scope,'registry_read_only'))
        self.assertEqual(t['target_rel'],'Stock/programs/Sample/projects/'+rf.BUSINESS+'/course_a')
        copies=[r for r in m['records'] if r['archive_path']]
        self.assertEqual(len(copies),17)
        for r in copies:
            self.assertTrue(r['archive_path'].startswith(t['target_rel']+'/documents/'))
            self.assertEqual((self.repo/r['archive_path']).read_bytes(),(root/r['path']).read_bytes())
        self.assertFalse((self.repo/'Stock/programs/Sample/projects/course_a').exists())   # not the earlier projects/<project>/
        self.assertTrue(validate_package.validate(root,phase='final',layer=layer)['pass'])

    def test_explicit_registry_db(self):
        layer,root,scope=self.layer('x',link=False)
        other=Path(self.temp.name)/'elsewhere';other.mkdir();rf.db_path(self.repo).rename(other/'r.db')
        with self.assertRaises(ValueError):package.archive_course(layer)   # the default <stock root>/.claude/db/ai_plc.db is gone
        con=sqlite3.connect(other/'r.db');pid=con.execute('INSERT INTO projects (scope_id) VALUES (?)',(scope,)).lastrowid
        con.execute("INSERT INTO business_project_links VALUES (?,?,?,'primary','confirmed')",(rf.WS,'bpr_synthetic_test',pid));con.commit();con.close()
        result=package.archive_course(layer,registry_db=other/'r.db');self.assertTrue(result['pass'],result['errors'])

    def test_nfd_display_name_becomes_an_nfc_folder(self):
        nfd=unicodedata.normalize('NFD','合成の業務・ガイドブック');self.assertNotEqual(nfd,unicodedata.normalize('NFC',nfd))
        rf.add_business(self.repo,'bpr_nfd',nfd);layer,root,scope=self.layer('n',link=False);rf.link(self.repo,scope,'bpr_nfd')
        self.assertTrue(package.archive_course(layer)['pass'])
        t=package.load(root/'manifest.yaml')['archive_target'];self.assertEqual(t['business_name'],'合成の業務・ガイドブック')
        self.assertIn('合成の業務・ガイドブック',[x.name for x in (self.repo/'Stock/programs/Sample/projects').iterdir()])

    def test_refusals_write_nothing(self):
        def pending_scope(case):
            layer,root,scope=case.layer('ps',link=False);d=package.load(layer/'intent.yaml');d['scope_id']='pending:registry-untouched';write_yaml(layer/'intent.yaml',d);return layer
        def no_row(case):return case.layer('nr',link=False)[0]
        def related_only(case):
            layer,root,scope=case.layer('ro',link=False);rf.link(case.repo,scope,'bpr_synthetic_test',relation='related');return layer
        def retired_primary(case):
            layer,root,scope=case.layer('rp',link=False);rf.link(case.repo,scope,'bpr_synthetic_test',state='retired');return layer
        def inactive_business(case):
            rf.add_business(case.repo,'bpr_arch','終わった業務',state='archived');layer,root,scope=case.layer('ib',link=False);rf.link(case.repo,scope,'bpr_arch');return layer
        def other_program(case):
            con=sqlite3.connect(rf.db_path(case.repo));con.execute("INSERT INTO programs VALUES ('prg_customer',?,'customer:Client','active')",(rf.WS,));con.commit();con.close()
            rf.add_business(case.repo,'bpr_customer','顧客の業務',program_uid='prg_customer');layer,root,scope=case.layer('op',link=False);rf.link(case.repo,scope,'bpr_customer');return layer
        def same_name(case):
            rf.add_business(case.repo,'bpr_twin',rf.BUSINESS);return case.layer('sn')[0]
        def same_folder_after_colon(case):
            rf.add_business(case.repo,'bpr_half','AB:CD');rf.add_business(case.repo,'bpr_full','AB：CD');layer,root,scope=case.layer('sf',link=False);rf.link(case.repo,scope,'bpr_half');return layer
        def same_name_other_case(case):
            rf.add_business(case.repo,'bpr_lower','case');rf.add_business(case.repo,'bpr_upper','Case');layer,root,scope=case.layer('sc',link=False);rf.link(case.repo,scope,'bpr_upper');return layer
        def membership_not_a_map(case):
            layer,root,scope=case.layer('mn');d=package.load(layer/'intent.yaml');d['membership']=['bpr_synthetic_test'];write_yaml(layer/'intent.yaml',d);return layer
        def membership_other_workspace(case):
            layer,root,scope=case.layer('mw');d=package.load(layer/'intent.yaml');d['membership']={'business_uid':'bpr_synthetic_test','workspace_id':'ws-other'};write_yaml(layer/'intent.yaml',d);return layer
        def membership_differs(case):
            layer,root,scope=case.layer('md');d=package.load(layer/'intent.yaml');d['membership']={'program_uid':rf.PROGRAM_UID,'business_uid':'bpr_other'};write_yaml(layer/'intent.yaml',d);return layer
        def no_registry(case):
            layer=case.layer('nd')[0];rf.db_path(case.repo).unlink();return layer
        cases=[pending_scope,no_row,related_only,retired_primary,inactive_business,other_program,same_name,same_folder_after_colon,same_name_other_case,membership_differs,membership_other_workspace,membership_not_a_map]
        for n,bad in enumerate(('a\\b','.hidden',' lead','trail ','end.','\u200bzw','tab\tname','')):
            def bad_name(case,bad=bad,n=n):
                uid='bpr_bad_'+str(n);rf.add_business(case.repo,uid,bad);layer,root,scope=case.layer('bn'+str(n),link=False);rf.link(case.repo,scope,uid);return layer
            bad_name.__name__='bad_name_'+repr(bad);cases.append(bad_name)
        cases.append(no_registry)   # last: it removes the Registry
        expect={'pending_scope':'scope_id','no_row':'projects rows','related_only':'no primary','retired_primary':'no primary',
                'inactive_business':'not active','other_program':'does not belong','same_name':'has the folder name','same_name_other_case':'has the folder name','same_folder_after_colon':'has the folder name','membership_other_workspace':'membership differs','membership_not_a_map':'must be a map','membership_differs':'membership differs','no_registry':'Registry not found'}
        for build in cases:
            with self.subTest(case=build.__name__):
                rf.db_path(self.repo).unlink(missing_ok=True);rf.standard(self.repo)   # the fixture Layers share one scope_id: a fresh Registry per case
                layer=build(self);root=layer/ti.pkg_of(layer);manifest=sha(root/'manifest.yaml')
                stock=tr.state(self.repo/'Stock');db=sha(rf.db_path(self.repo)) if rf.db_path(self.repo).exists() else None
                with self.assertRaisesRegex(ValueError,expect.get(build.__name__,'cannot be a folder name')):package.archive_course(layer)
                self.assertEqual(tr.state(self.repo/'Stock'),stock);self.assertEqual(sha(root/'manifest.yaml'),manifest)
                if db:self.assertEqual(sha(rf.db_path(self.repo)),db)

    def test_colon_becomes_a_full_width_colon_in_the_folder_only(self):
        rf.add_business(self.repo,'bpr_colon','AB:CD');layer,root,scope=self.layer('rs',link=False);rf.link(self.repo,scope,'bpr_colon')
        result=package.archive_course(layer);self.assertTrue(result['pass'],result['errors'])
        t=package.load(root/'manifest.yaml')['archive_target']
        self.assertEqual((t['business_display_name'],t['business_name']),('AB:CD','AB\uff1aCD'))
        self.assertEqual(t['target_rel'],'Stock/programs/Sample/projects/AB\uff1aCD/course_rs')
        self.assertTrue((self.repo/t['target_rel']/'documents').is_dir());self.assertFalse((self.repo/'Stock/programs/Sample/projects/AB:CD').exists())

    def test_membership_that_agrees_passes(self):
        layer,root,scope=self.layer('ma');d=package.load(layer/'intent.yaml');d['membership']={'program_uid':rf.PROGRAM_UID,'business_uid':'bpr_synthetic_test','registry_state':'reflected'};write_yaml(layer/'intent.yaml',d)
        self.assertTrue(package.archive_course(layer)['pass'])

    def test_final_rejects_an_archive_target_that_does_not_name_this_package(self):
        layer,root,scope=self.layer('t');self.assertTrue(package.archive_course(layer)['pass'])
        m=package.load(root/'manifest.yaml');good=dict(m['archive_target'])
        for key,value in (('target_rel','Stock/programs/Sample/projects/別の業務/course_t'),('business_name','別の業務'),('business_display_name','別の業務'),('scope_id','L-OTHER'),('source','guess'),('business_name','a/b')):
            with self.subTest(key=key,value=value):
                m['archive_target']=dict(good,**{key:value});write_yaml(root/'manifest.yaml',m)
                r=validate_package.validate(root,phase='final',layer=layer);self.assertFalse(r['pass']);self.assertIn('E_ARCHIVE',[e['code'] for e in r['errors']])
        m['archive_target']=dict(good);m['archive_target'].pop('resolved_at');write_yaml(root/'manifest.yaml',m)
        self.assertFalse(validate_package.validate(root,phase='final',layer=layer)['pass'])
        m['archive_target']=good;write_yaml(root/'manifest.yaml',m)
        self.assertTrue(validate_package.validate(root,phase='final',layer=layer)['pass'])

    def test_an_earlier_copy_without_archive_target_still_passes_final(self):
        """Like a box archived earlier (archived to projects/<project>/documents/ before this change): no archive_target in the manifest."""
        layer,root,scope=self.layer('old');self.assertTrue(package.archive_course(layer)['pass'])
        m=package.load(root/'manifest.yaml');t=m.pop('archive_target');legacy='Stock/programs/Sample/projects/course_old'
        m.pop('applies');(self.repo/t['target_rel']/package.APPLY_LOG).unlink()   # archived before the versions
        for r in m['records']:
            if r['archive_path']:
                new=r['archive_path'].replace(t['target_rel'],legacy,1);q=self.repo/new;q.parent.mkdir(parents=True,exist_ok=True)
                (self.repo/r['archive_path']).rename(q);r['archive_path']=new
        write_yaml(root/'manifest.yaml',m)
        r=validate_package.validate(root,phase='final',layer=layer);self.assertTrue(r['pass'],r['errors'])

if __name__=='__main__':unittest.main()
