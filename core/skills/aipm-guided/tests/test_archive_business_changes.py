"""after a business project is renamed, reassigned (reprimary) or merged, a new archive
goes to the current primary under its current display name, and nothing already in the Stock moves: the earlier copies,
their manifest (archive_target, archive_path) and their final validation stay as they were.
Synthetic repository and Registry only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import sqlite3, unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent));sys.path.insert(0,str(HERE))
import package, validate_package
import test_init_and_reset as tr
import test_archive_business as ab
import registry_fixture as rf
sha=ab.sha

class ArchiveAfterBusinessChanges(ab.ArchiveUnderBusiness):
    """Two boxes of one Layer scope (the fixture Layers share it): A archived before the change, B after."""
    def run_sql(self,*statements):
        con=sqlite3.connect(rf.db_path(self.repo))
        for q,args in statements:con.execute(q,args)
        con.commit();con.close()
    def archived_first(self):
        layer,root,scope=self.layer('first');self.assertTrue(package.archive_course(layer)['pass'])
        stock=tr.state(self.repo/'Stock');manifest=sha(root/'manifest.yaml')
        return layer,root,scope,stock,manifest
    def assert_first_unchanged(self,layer,root,stock_before,manifest_before,old_target):
        """Every file of A's copy is where it was with the same bytes, and A's manifest and final are as before."""
        now=tr.state(self.repo/'Stock')
        for rel,v in stock_before.items():self.assertEqual(now.get(rel),v,rel)
        self.assertEqual(sha(root/'manifest.yaml'),manifest_before)
        self.assertEqual(package.load(root/'manifest.yaml')['archive_target']['target_rel'],old_target)
        r=validate_package.validate(root,phase='final',layer=layer);self.assertTrue(r['pass'],r['errors'])
    def second(self):
        layer,root,scope=self.layer('second',link=False)   # same scope: already linked by the first
        result=package.archive_course(layer);self.assertTrue(result['pass'],result['errors'])
        return package.load(root/'manifest.yaml')['archive_target']

    def test_rename_sends_the_next_archive_to_the_new_name(self):
        layer,root,scope,stock,manifest=self.archived_first();old='Stock/programs/Sample/projects/'+rf.BUSINESS+'/course_first'
        self.run_sql(("UPDATE business_projects SET display_name='改名した業務' WHERE business_uid='bpr_synthetic_test'",()))
        t=self.second()
        self.assertEqual((t['business_uid'],t['business_display_name'],t['target_rel']),('bpr_synthetic_test','改名した業務','Stock/programs/Sample/projects/改名した業務/course_second'))
        self.assert_first_unchanged(layer,root,stock,manifest,old)
        self.assertTrue((self.repo/old).is_dir())   # the old folder name stays; nothing is renamed in the Stock

    def test_reprimary_sends_the_next_archive_to_the_new_primary(self):
        layer,root,scope,stock,manifest=self.archived_first();old='Stock/programs/Sample/projects/'+rf.BUSINESS+'/course_first'
        rf.add_business(self.repo,'bpr_next','次の業務')
        self.run_sql(("UPDATE business_project_links SET state='retired' WHERE business_uid='bpr_synthetic_test'",()))
        rf.link(self.repo,scope,'bpr_next')
        t=self.second();self.assertEqual((t['business_uid'],t['target_rel']),('bpr_next','Stock/programs/Sample/projects/次の業務/course_second'))
        self.assert_first_unchanged(layer,root,stock,manifest,old)

    def test_merge_sends_the_next_archive_to_the_target_and_an_archived_source_stops(self):
        layer,root,scope,stock,manifest=self.archived_first();old='Stock/programs/Sample/projects/'+rf.BUSINESS+'/course_first'
        rf.add_business(self.repo,'bpr_target','統合先の業務')
        # merge, step 1: the source is archived while the Layer's link still points to it -> archive stops, writes nothing
        self.run_sql(("UPDATE business_projects SET state='archived' WHERE business_uid='bpr_synthetic_test'",()))
        mid,midroot,_=self.layer('mid',link=False);before=tr.state(self.repo/'Stock');m=sha(midroot/'manifest.yaml')
        with self.assertRaisesRegex(ValueError,'not active'):package.archive_course(mid)
        self.assertEqual(tr.state(self.repo/'Stock'),before);self.assertEqual(sha(midroot/'manifest.yaml'),m)
        # merge, step 2: the source link is retired and the Layer gets the target as its primary
        self.run_sql(("UPDATE business_project_links SET state='retired' WHERE business_uid='bpr_synthetic_test'",()))
        rf.link(self.repo,scope,'bpr_target')
        t=self.second();self.assertEqual((t['business_uid'],t['target_rel']),('bpr_target','Stock/programs/Sample/projects/統合先の業務/course_second'))
        self.assert_first_unchanged(layer,root,stock,manifest,old)

    def test_an_archived_box_is_not_archived_again_after_a_change(self):
        layer,root,scope,stock,manifest=self.archived_first()
        self.run_sql(("UPDATE business_projects SET display_name='改名した業務' WHERE business_uid='bpr_synthetic_test'",()))
        r=package.archive_course(layer);self.assertFalse(r['pass'])   # prearchive no longer passes: nothing is copied again
        self.assertIn('E_STATE',[e['code'] for e in r['errors']])   # the records are archived_local_final, not generated
        self.assertEqual(tr.state(self.repo/'Stock'),stock);self.assertEqual(sha(root/'manifest.yaml'),manifest)
        self.assertFalse((self.repo/'Stock/programs/Sample/projects/改名した業務').exists())

# the tests of the base class run in test_archive_business; here only the change tests
for name in [n for n in dir(ab.ArchiveUnderBusiness) if n.startswith('test_')]:setattr(ArchiveAfterBusinessChanges,name,None)

if __name__=='__main__':unittest.main()
