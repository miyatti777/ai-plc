import sys
sys.dont_write_bytecode=True
from pathlib import Path
import copy
import importlib.util
import json
import unittest
from datetime import datetime,timezone,timedelta

spec=importlib.util.spec_from_file_location('stock_protocol_test',Path(__file__).resolve().parents[2]/'core'/'db'/'shared_stock.py')
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)


def expiry():return (datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()


def seed(store, count=3):
    """Only synthetic identities, in the business_registry.py schema."""
    selector={'workspace_id':'synthetic-workspace','read_domain':'work','program_uid':'program-1','business_uid':'business-1'}
    with store.db() as db:
        db.execute('INSERT INTO programs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',('program-1','synthetic-workspace','synthetic-program','Synthetic','work','work','fixture','fixture','synthetic',1,2,1,'active'))
        db.execute('INSERT INTO business_projects(business_uid,workspace_id,display_name,purpose,included_json,excluded_json,owner_ref,steward_ref,visibility,source_ref,source_hash,source_as_of,ownership_epoch,identity_version,row_revision,state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('business-1','synthetic-workspace','Synthetic business','test','[]','[]','fixture','fixture','work','synthetic','hash','2026-10-13',1,2,1,'active'))
        db.execute('INSERT INTO program_memberships(membership_uid,workspace_id,program_uid,target_kind,business_uid,source_ref,row_revision,state) VALUES (?,?,?,?,?,?,?,?)',('member-1','synthetic-workspace','program-1','business_project','business-1','synthetic',1,'confirmed'))
        for n in range(1,count+1):
            p={'id':n,'scope_id':'L-SYN-'+str(n),'workspace_id':'synthetic-workspace','sync_uid':'aiplc-'+str(n),'ownership_epoch':1,'identity_version':2,'status':'active'}
            db.execute('INSERT INTO projects VALUES (?,?,?,?,?,?,?)',tuple(p.values()))
            db.execute('INSERT INTO business_project_links(link_uid,workspace_id,business_uid,project_id,aiplc_uid,project_epoch,project_version,identity_snapshot,relation_type,source_ref,row_revision,state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',('link-'+str(n),'synthetic-workspace','business-1',n,p['sync_uid'],1,2,core.canonical(p),'primary','synthetic',1,'confirmed'))
    return selector


class Protocol(unittest.TestCase):
    def setUp(self):
        self.s=core.FixtureStore();self.selector=seed(self.s);self.b=self.s.bind(self.selector,folder='programs/p1/projects/b1')
    def tearDown(self):self.s.close()
    def prepare(self,n=1,key='problem',text='[unknown] real effect'):
        return self.s.prepare(self.b['binding_id'],{'scope_id':'L-SYN-'+str(n),'aiplc_uid':'aiplc-'+str(n),'task_id':'T001','as_of':'2026-10-13T00:00:00+00:00','decision_ref':'synthetic-decision'}, {'Flow/doc.md':'# Original\n'+text},{key:{'kind':'unknown','text':text,'source_paths':['Flow/doc.md']}})
    def commit(self,p,request='r1',**kw):return self.s.commit(p,approved_hash=core.digest(p),request_id=request,writer='fixture-writer',expires_at=expiry(),**kw)
    def test_same_pair_and_identity_separation(self):
        self.assertEqual(self.b,self.s.bind(self.selector))
        with self.assertRaises(core.Hold):self.s.bind({**self.selector,'business_uid':'missing'},folder='elsewhere')
        with self.assertRaises(core.Hold):self.s.bind(self.selector,folder='new-path')
        with self.assertRaises(core.Hold):self.s.project_identity(self.b['binding_id'],'L-SYN-1','aiplc-2')
    def test_new_pair_has_distinct_binding_and_overlapping_paths_refused(self):
        with self.s.db() as db:
            db.execute("INSERT INTO business_projects(business_uid,workspace_id,display_name,purpose,included_json,excluded_json,visibility,source_ref,source_hash,source_as_of,ownership_epoch,identity_version,row_revision,state) SELECT 'business-2',workspace_id,'second',purpose,included_json,excluded_json,visibility,source_ref,source_hash,source_as_of,ownership_epoch,identity_version,row_revision,state FROM business_projects WHERE business_uid='business-1'")
            db.execute("INSERT INTO program_memberships(membership_uid,workspace_id,program_uid,target_kind,business_uid,source_ref,row_revision,state) VALUES ('member-2','synthetic-workspace','program-1','business_project','business-2','synthetic',1,'confirmed')")
        second={**self.selector,'business_uid':'business-2'}
        with self.assertRaises(core.Hold):self.s.bind(second,folder='programs/p1/projects/b1/nested')
        b=self.s.bind(second,folder='programs/p1/projects/b2')
        self.assertNotEqual(b['binding_id'],self.b['binding_id'])
        self.commit(self.prepare());self.assertEqual(self.s.read(b['binding_id'])['content']['units'],{})
    def test_different_program_pair_does_not_mix_contents(self):
        with self.s.db() as db:
            program=dict(db.execute('SELECT * FROM programs').fetchone());program.update(program_uid='program-2',definition_key='synthetic-program-2')
            db.execute('INSERT INTO programs('+','.join(program)+') VALUES ('+','.join('?' for _ in program)+')',tuple(program.values()))
            business=dict(db.execute('SELECT * FROM business_projects').fetchone());business.pop('id');business.update(business_uid='business-2')
            db.execute('INSERT INTO business_projects('+','.join(business)+') VALUES ('+','.join('?' for _ in business)+')',tuple(business.values()))
            db.execute("INSERT INTO program_memberships(membership_uid,workspace_id,program_uid,target_kind,business_uid,source_ref,row_revision,state) VALUES ('member-2','synthetic-workspace','program-2','business_project','business-2','synthetic',1,'confirmed')")
        b=self.s.bind({**self.selector,'program_uid':'program-2','business_uid':'business-2'},folder='programs/p2/projects/b2')
        self.commit(self.prepare());self.assertEqual(self.s.read(b['binding_id'])['content']['units'],{})
    def test_two_sources_organized_and_originals(self):
        first=self.commit(self.prepare());second=self.commit(self.prepare(2,'solution','[hypothesis] a solution'),'r2')
        result=self.s.read(self.b['binding_id'])
        self.assertEqual(set(result['content']['units']),{'problem','solution'})
        self.assertEqual(len(result['content']['sources']),2)
        p=self.s.stock/self.b['folder']/'revisions'/first['revision']/'originals'/first['source_id']/'Flow/doc.md'
        self.assertEqual(p.read_text(),'# Original\n[unknown] real effect')
        self.assertNotEqual(first['revision'],second['revision'])
    def test_conflict_retained_and_tamper_rejected(self):
        self.commit(self.prepare());p=self.prepare(2,text='contradiction')
        self.assertEqual(len(p['conflicts']),1)
        with self.assertRaises(core.Hold):self.commit(p,'conflict')
        p=self.prepare(2,'solution');p['organized']['units']['problem']['text']='silently revised'
        with self.assertRaises(core.Hold):self.commit(p,'forged')
    def test_duplicate_request_is_noop(self):
        p=self.prepare();r=self.commit(p);self.assertEqual(r,self.commit(p));self.assertEqual(self.s.binding(self.b['binding_id'])['generation'],1)
        same=self.prepare();again=self.commit(same,'same-content-new-request');self.assertTrue(again['noop']);self.assertEqual(again['generation'],1)
        p['originals']['Flow/doc.md']='different'
        with self.assertRaises(core.Hold):self.commit(p)
    def test_stale_diff_and_ownership(self):
        p=self.prepare();stale=self.prepare(2,'solution');self.commit(p)
        with self.assertRaises(core.Hold):self.commit(stale,'stale')
        with self.s.db() as db:db.execute('UPDATE projects SET ownership_epoch=2 WHERE id=1')
        with self.assertRaises(core.Hold):self.prepare()
    def test_concurrent_writer(self):
        p=self.prepare()
        with self.s.writer_lock():
            with self.assertRaises(core.Hold):self.commit(p)
    def test_interruption_and_same_request_recovery(self):
        for failure in ['after_prepare','after_materialize','after_commit']:
            with self.subTest(failure=failure):
                s=core.FixtureStore();seed(s);b=s.bind(self.selector,folder='target');old=self.s;oldb=self.b;self.s=s;self.b=b
                try:
                    p=self.prepare()
                    with self.assertRaises(RuntimeError):self.commit(p,failure,fault=failure)
                    if failure!='after_commit':
                        with self.assertRaises(core.Hold):self.commit(p,'other')
                    r=self.commit(p,failure);self.assertEqual(r,self.commit(p,failure));self.assertEqual(s.binding(b['binding_id'])['generation'],1)
                finally:self.s=old;self.b=oldb;s.close()
    def test_changed_materialized_file_not_overwritten(self):
        p=self.prepare()
        with self.assertRaises(RuntimeError):self.commit(p,fault='after_materialize')
        q=next(self.s.stock.rglob('doc.md'));q.write_text('another writer')
        with self.assertRaises(core.Hold):self.commit(p)
        self.assertEqual(q.read_text(),'another writer')
    def test_partial_file_write_recovers_without_overwriting_unknown_files(self):
        p=self.prepare()
        with self.assertRaises(OSError):self.commit(p,fault='during_file_write')
        self.assertFalse(list(self.s.stock.rglob('organized.json')))
        receipt=self.commit(p);self.assertEqual(receipt['generation'],1)
        self.assertEqual(self.commit(p),receipt)
    def test_compensation_only_own_poststate(self):
        self.commit(self.prepare());self.commit(self.prepare(2,'solution'),'r2')
        with self.assertRaises(core.Hold):self.s.compensate('r1',writer='fixture-writer',expires_at=expiry())
        self.s.compensate('r2',writer='fixture-writer',expires_at=expiry())
        self.assertEqual(set(self.s.read(self.b['binding_id'])['content']['units']),{'problem'})
        self.assertEqual(len(list(self.s.stock.rglob('manifest.json'))),2)
    def test_changed_files_and_expired_writer(self):
        p=self.prepare();r=self.commit(p);q=next(self.s.stock.rglob('organized.json'));q.write_text('{}')
        with self.assertRaises(core.Hold):self.s.compensate('r1',writer='fixture-writer',expires_at=expiry())
        with self.assertRaises(core.Hold):self.s.commit(p,approved_hash=core.digest(p),request_id='late',writer='fixture-writer',expires_at='2000-01-01T00:00:00+00:00')
    def test_business_visibility_must_match_read_domain(self):
        # 業務Project の visibility が Program の read_domain と違う行は、Fixture でも Live でも止める
        with self.s.db() as db:
            db.execute("UPDATE business_projects SET visibility='other'")
        with self.assertRaises(core.Hold):self.s.bind(self.selector)
        with self.assertRaises(core.Hold):issue(self.s.root,self.selector).bind(self.selector)
    def test_path_escape_and_symlink(self):
        for path in ['../outside','/tmp/outside']:
            with self.assertRaises(core.Hold):core.safe(self.s.stock,path)
        (self.s.stock/'alias').symlink_to(self.s.root)
        with self.assertRaises(core.Hold):core.safe(self.s.stock,'alias/file')


def issue(root,selector,**overrides):
    """Write a live issuance under a synthetic repo root and return the LiveStore."""
    import os
    spec={'version':'live-v1','repo_root':str(root),'db_rel':'registry.sqlite','stock_rel':'Stock','lock_rel':'.live.lock','staging_rel':'.staging','host_uid':os.getuid(),
          'selector':selector,'scope_id':'L-SYN-1','aiplc_uid':'aiplc-1','adopted_folder':'programs/p1/projects/b1','writer':'issued-writer','task_id':'T001',
          'issued_at':'2026-10-14T00:00:00+00:00','issued_by':'synthetic','approval_ref':'synthetic','expires_at':expiry(),'allow_schema_install':True}
    spec.update(overrides);path=root/'issuance.json';path.write_text(json.dumps(spec))
    return core.LiveStore(path)


class LiveIssuance(unittest.TestCase):
    """LiveStore over a synthetic DB in the shape business_registry.py writes (digest
    snapshots, stock tables absent until installed)."""
    def setUp(self):
        self.s=core.FixtureStore();self.selector=seed(self.s)
        with self.s.db() as db:
            db.execute('DROP TABLE stock_bindings');db.execute('DROP TABLE stock_operations')
            p=dict(db.execute('SELECT * FROM projects WHERE id=1').fetchone())
            live={k:p.get(k) for k in core.IDENTITY_KEYS}
            db.execute('UPDATE business_project_links SET identity_snapshot=? WHERE project_id=1',(core.digest(live),))
        self.live=issue(self.s.root,self.selector)
    def tearDown(self):self.s.close()
    def test_schema_install_is_additive_and_gated(self):
        with self.assertRaises(core.Hold):self.live.bind(self.selector,folder='programs/p1/projects/b1')
        self.assertEqual(self.live.install_schema(),{'installed':['stock_bindings','stock_operations'],'already_present':[]})
        self.assertEqual(self.live.install_schema(),{'installed':[],'already_present':['stock_bindings','stock_operations']})
        with self.assertRaises(core.Hold):issue(self.s.root,self.selector,allow_schema_install=False).install_schema()
    def test_live_shape_identity_and_single_tuple(self):
        self.live.install_schema();b=self.live.bind(self.selector,folder='programs/p1/projects/b1')
        self.assertEqual(b,self.live.bind(self.selector))
        self.live.project_identity(b['binding_id'],'L-SYN-1','aiplc-1')
        with self.assertRaises(core.Hold):self.live.project_identity(b['binding_id'],'L-SYN-2','aiplc-2')
        with self.assertRaises(core.Hold):self.live.bind(self.selector,folder='programs/other')
        with self.assertRaises(core.Hold):self.live.bind({**self.selector,'business_uid':'business-2'},folder='programs/p1/projects/b2')
        with self.assertRaises(core.Hold):self.live.check_contract({'storage':'registry_stock_v1','stock_selector':self.selector,'scope_id':'L-SYN-2','aiplc_uid':'aiplc-2'})
        self.assertFalse(self.live.isolated)
    def test_writer_period_and_principal_bound(self):
        self.live.install_schema();b=self.live.bind(self.selector,folder='programs/p1/projects/b1')
        p=self.live.prepare(b['binding_id'],{'scope_id':'L-SYN-1','aiplc_uid':'aiplc-1','task_id':'T001','as_of':'2026-10-14T00:00:00+00:00','decision_ref':'synthetic'},{'Flow/doc.md':'# x'},{'k':{'kind':'unknown','text':'x','source_paths':['Flow/doc.md']}})
        with self.assertRaises(core.Hold):self.live.commit(p,approved_hash=core.digest(p),request_id='r',writer='other-writer',expires_at=expiry())
        r=self.live.commit(p,approved_hash=core.digest(p),request_id='r',writer='issued-writer',expires_at=expiry())
        self.assertFalse(r['isolated_only']);self.assertEqual(r['generation'],1)
        self.assertFalse(list((self.s.root/'.staging').iterdir()))
        with self.assertRaises(core.Hold):issue(self.s.root,self.selector,expires_at='2000-01-01T00:00:00+00:00')
        self.live.spec['expires_at']='2000-01-01T00:00:00+00:00'  # retained instance after expiry
        with self.assertRaises(core.Hold):self.live.bind(self.selector)
        with self.assertRaises(core.Hold):self.live.read(b['binding_id'])
        with self.assertRaises(core.Hold):issue(self.s.root,self.selector,host_uid=-1)
        with self.assertRaises(core.Hold):issue(self.s.root,self.selector,db_rel='../outside.sqlite')
        link=self.s.root/'issuance-link.json';link.symlink_to(self.s.root/'issuance.json')
        with self.assertRaises(core.Hold):core.LiveStore(link)


if __name__=='__main__':unittest.main()
