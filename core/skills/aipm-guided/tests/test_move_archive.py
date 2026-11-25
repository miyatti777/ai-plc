"""move-archive moves the Stock copies of an archived box_root_v1 package to where archive
would put them now. The case is made synthetically: a box archived to the earlier Stock/programs/<program>/projects/
<project>/documents/ (no archive_target). Dry-run by default; every file keeps bytes, sha256 and mtime; a failure puts every
file back. Synthetic repository and Registry only; the real Registry is never touched."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import os, sqlite3, unittest
from unittest import mock
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent));sys.path.insert(0,str(HERE))
import package, validate_package
import test_init_and_reset as tr
import test_archive_business as ab
import test_integration as ti
import registry_fixture as rf
write_yaml,sha=ab.write_yaml,ab.sha

class MoveArchive(ab.ArchiveUnderBusiness):
    def l0819_like(self,name='l0819'):
        """A box archived before the move: copies under projects/<project>/documents/, manifest without archive_target."""
        layer,root,scope=self.layer(name);self.assertTrue(package.archive_course(layer)['pass'])
        m=package.load(root/'manifest.yaml');t=m.pop('archive_target');legacy='Stock/programs/Sample/projects/course_'+name
        m.pop('applies');(self.repo/t['target_rel']/package.APPLY_LOG).unlink()   # archived before the versions
        for r in m['records']:
            if r['archive_path']:
                new=r['archive_path'].replace(t['target_rel'],legacy,1);q=self.repo/new;q.parent.mkdir(parents=True,exist_ok=True)
                os.rename(self.repo/r['archive_path'],q);r['archive_path']=new
        for d in sorted((self.repo/t['target_rel']).rglob('*'),reverse=True):d.rmdir()
        (self.repo/t['target_rel']).rmdir()
        write_yaml(root/'manifest.yaml',m);self.assertTrue(validate_package.validate(root,phase='final',layer=layer)['pass'])
        return layer,root,legacy
    def files(self,folder):
        base=self.repo/folder;return {str(q.relative_to(base)):(sha(q),q.stat().st_mtime_ns) for q in base.rglob('*') if q.is_file()}

    def test_dry_run_lists_the_17_moves_and_writes_nothing(self):
        layer,root,legacy=self.l0819_like();stock=tr.state(self.repo/'Stock');manifest=sha(root/'manifest.yaml');db=sha(rf.db_path(self.repo))
        out=package.move_archive(layer)
        self.assertFalse(out['apply']);self.assertEqual(len(out['moves']),17)
        self.assertEqual((out['from'],out['to']),(legacy,'Stock/programs/Sample/projects/'+rf.BUSINESS+'/course_l0819'))
        self.assertEqual(tr.state(self.repo/'Stock'),stock);self.assertEqual(sha(root/'manifest.yaml'),manifest);self.assertEqual(sha(rf.db_path(self.repo)),db)

    def test_apply_keeps_every_file_and_rewrites_only_the_archive_records(self):
        layer,root,legacy=self.l0819_like();before=self.files(legacy);m0=package.load(root/'manifest.yaml');db=sha(rf.db_path(self.repo))
        with self.assertRaisesRegex(ValueError,'approval-ref'):package.move_archive(layer,apply=True)
        self.assertEqual(self.files(legacy),before)
        out=package.move_archive(layer,apply=True,approval_ref='synthetic approval')
        self.assertTrue(out['final']['pass'],out['final']['errors'])
        new='Stock/programs/Sample/projects/'+rf.BUSINESS+'/course_l0819'
        self.assertEqual(self.files(new),before)   # same files, bytes, sha256 and mtime
        self.assertFalse((self.repo/legacy).exists())   # the old folder, left empty, is gone
        self.assertEqual(sha(rf.db_path(self.repo)),db)
        m1=package.load(root/'manifest.yaml')
        self.assertEqual(set(m1)-set(m0),{'archive_target','archive_moves'})
        for k in m0:
            if k!='records':self.assertEqual(m1[k],m0[k],k)
        for a,b in zip(m0['records'],m1['records']):
            changed={k for k in a if a[k]!=b[k]}
            self.assertEqual(changed,{'archive_path'} if a['archive_path'] else set())
            if a['archive_path']:self.assertEqual(b['archive_path'],a['archive_path'].replace(legacy,new,1));self.assertEqual(a['archive_sha256'],b['archive_sha256'])
        mv=m1['archive_moves'];self.assertEqual(len(mv),1);self.assertEqual((mv[0]['from'],mv[0]['to'],mv[0]['files'],mv[0]['approval_ref']),(legacy,new,17,'synthetic approval'))
        self.assertEqual(m1['archive_target']['source'],'registry_read_only')
        with self.assertRaisesRegex(ValueError,'already at'):package.move_archive(layer)   # once moved, nothing more to move

    def test_move_refusals_write_nothing(self):
        def destination_exists(case):
            layer,root,legacy=case.l0819_like('de');q=case.repo/'Stock/programs/Sample/projects'/rf.BUSINESS/'course_de/documents/02_課題定義/problem_map.yaml';q.parent.mkdir(parents=True);q.write_text('x');return layer
        def copy_changed(case):
            layer,root,legacy=case.l0819_like('cc');q=next((case.repo/legacy).rglob('*.yaml'));q.write_text(q.read_text()+'# edited\n');return layer
        def no_primary(case):
            layer,root,legacy=case.l0819_like('np')
            con=sqlite3.connect(rf.db_path(case.repo));con.execute("UPDATE business_project_links SET state='retired'");con.commit();con.close();return layer
        for build,pattern in ((destination_exists,'already exists'),(copy_changed,'final does not pass'),(no_primary,'no primary')):
            with self.subTest(case=build.__name__):
                rf.db_path(self.repo).unlink(missing_ok=True);rf.standard(self.repo)
                layer=build(self);root=layer/ti.pkg_of(layer);stock=tr.state(self.repo/'Stock');manifest=sha(root/'manifest.yaml')
                for apply in (False,True):
                    with self.assertRaisesRegex(ValueError,pattern):package.move_archive(layer,apply=apply,approval_ref='synthetic')
                self.assertEqual(tr.state(self.repo/'Stock'),stock);self.assertEqual(sha(root/'manifest.yaml'),manifest)

    def test_a_failure_while_moving_puts_every_file_back(self):
        layer,root,legacy=self.l0819_like('pf');stock=tr.state(self.repo/'Stock');manifest=sha(root/'manifest.yaml')
        real=os.rename;calls=[]
        def failing(a,b):
            calls.append(1)
            if len(calls)==4:raise OSError('synthetic failure')
            return real(a,b)
        with mock.patch.object(package.os,'rename',failing),self.assertRaisesRegex(ValueError,'put back'):package.move_archive(layer,apply=True,approval_ref='synthetic')
        self.assertEqual(tr.state(self.repo/'Stock'),stock);self.assertEqual(sha(root/'manifest.yaml'),manifest)
        self.assertTrue(package.move_archive(layer,apply=True,approval_ref='synthetic')['final']['pass'])   # and it can run again

    def test_other_files_in_the_old_folder_are_kept(self):
        layer,root,legacy=self.l0819_like('of');extra=self.repo/legacy/'documents/.DS_Store';extra.write_bytes(b'finder');note=self.repo/legacy/'memo.md';note.write_text('kept')
        out=package.move_archive(layer,apply=True,approval_ref='synthetic');self.assertTrue(out['final']['pass'],out['final']['errors'])
        self.assertEqual(extra.read_bytes(),b'finder');self.assertEqual(note.read_text(),'kept')   # only empty folders are removed
        self.assertEqual(sorted(str(q.relative_to(self.repo/legacy)) for q in (self.repo/legacy).rglob('*') if q.is_file()),['documents/.DS_Store','memo.md'])
    def test_a_symlink_on_the_way_is_refused(self):
        layer,root,legacy=self.l0819_like('sy');elsewhere=self.repo/'elsewhere';elsewhere.mkdir()
        biz=self.repo/'Stock/programs/Sample/projects'/rf.BUSINESS;biz.rmdir()   # left empty by l0819_like
        biz.symlink_to(elsewhere,target_is_directory=True)
        stock=tr.state(self.repo/'Stock');manifest=sha(root/'manifest.yaml')
        with self.assertRaises(ValueError):package.move_archive(layer,apply=True,approval_ref='synthetic')
        self.assertEqual(tr.state(self.repo/'Stock'),stock);self.assertEqual(sha(root/'manifest.yaml'),manifest);self.assertEqual(list(elsewhere.iterdir()),[])
    def test_interrupt_puts_every_file_back(self):
        layer,root,legacy=self.l0819_like('ki');stock=tr.state(self.repo/'Stock');manifest=sha(root/'manifest.yaml')
        real=os.rename;calls=[]
        def interrupted(a,b):
            calls.append(1)
            if len(calls)==5:raise KeyboardInterrupt
            return real(a,b)
        with mock.patch.object(package.os,'rename',interrupted),self.assertRaisesRegex(ValueError,'put back'):package.move_archive(layer,apply=True,approval_ref='synthetic')
        self.assertEqual(tr.state(self.repo/'Stock'),stock);self.assertEqual(sha(root/'manifest.yaml'),manifest)
    def test_a_failed_put_back_is_reported(self):
        layer,root,legacy=self.l0819_like('pb');real=os.rename;calls=[]
        def failing(a,b):
            calls.append(1)
            if len(calls) in (3,4):raise OSError('synthetic')   # the 3rd move fails, then putting back the 2nd fails
            return real(a,b)
        with mock.patch.object(package.os,'rename',failing),self.assertRaisesRegex(ValueError,'NOT all put back: 1 files'):package.move_archive(layer,apply=True,approval_ref='synthetic')
        moved=sum(1 for q in (self.repo/'Stock/programs/Sample/projects'/rf.BUSINESS).rglob('*') if q.is_file());self.assertEqual(moved,1)   # nothing lost: it is at the new place
    def test_after_a_rename_the_copies_move_to_the_new_name(self):
        layer,root,scope=self.layer('rn');self.assertTrue(package.archive_course(layer)['pass'])
        old='Stock/programs/Sample/projects/'+rf.BUSINESS+'/course_rn'
        m=package.load(root/'manifest.yaml');m.pop('applies');write_yaml(root/'manifest.yaml',m);(self.repo/old/package.APPLY_LOG).unlink()   # archived before the versions
        before=self.files(old)
        con=sqlite3.connect(rf.db_path(self.repo));con.execute("UPDATE business_projects SET display_name='改名した業務'");con.commit();con.close()
        out=package.move_archive(layer,apply=True,approval_ref='synthetic');self.assertTrue(out['final']['pass'],out['final']['errors'])
        self.assertEqual(self.files('Stock/programs/Sample/projects/改名した業務/course_rn'),before)
        self.assertFalse((self.repo/'Stock/programs/Sample/projects'/rf.BUSINESS).exists())   # its only box moved: the empty business folder goes too
        t=package.load(root/'manifest.yaml')['archive_target'];self.assertEqual(t['business_display_name'],'改名した業務')

    def test_cli_dry_run(self):
        layer,root,legacy=self.l0819_like('cli');stock=tr.state(self.repo/'Stock')
        code,out=tr.run_cli('move-archive','--layer',str(layer));self.assertEqual(code,0,out);self.assertFalse(out['apply']);self.assertEqual(len(out['moves']),17)
        self.assertEqual(tr.state(self.repo/'Stock'),stock)

for name in [n for n in dir(ab.ArchiveUnderBusiness) if n.startswith('test_')]:setattr(MoveArchive,name,None)

if __name__=='__main__':unittest.main()
