"""a synthetic Registry (only the columns archive_business reads) at
<repository>/.claude/db/ai_plc.db, so that a box_root_v1 archive finds the primary business project of its Layer.
Synthetic fixtures only; the real Registry is never opened by the tests."""
from pathlib import Path
import sqlite3

WS='ws-synthetic'
PROGRAM_UID='prg_synthetic_sample'
BUSINESS='合成業務'
DDL='''
CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, scope_id TEXT);
CREATE TABLE programs (program_uid TEXT, workspace_id TEXT, definition_key TEXT, state TEXT);
CREATE TABLE business_projects (business_uid TEXT, workspace_id TEXT, display_name TEXT, state TEXT);
CREATE TABLE program_memberships (workspace_id TEXT, program_uid TEXT, target_kind TEXT, business_uid TEXT, state TEXT);
CREATE TABLE business_project_links (workspace_id TEXT, business_uid TEXT, project_id INTEGER, relation_type TEXT, state TEXT);
'''

def db_path(repo):return Path(repo)/'.claude/db/ai_plc.db'

def make_registry(repo,program='Sample'):
    """An empty Registry with the Program stock:<program> (Sample: PROGRAM_UID)."""
    p=db_path(repo);p.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(p);con.executescript(DDL)
    con.execute('INSERT INTO programs VALUES (?,?,?,?)',(PROGRAM_UID,WS,'stock:'+program,'active'));con.commit();con.close()
    return p

def add_business(repo,uid,name,program_uid=PROGRAM_UID,state='active'):
    con=sqlite3.connect(db_path(repo))
    con.execute('INSERT INTO business_projects VALUES (?,?,?,?)',(uid,WS,name,state))
    con.execute("INSERT INTO program_memberships VALUES (?,?,'business_project',?,'confirmed')",(WS,program_uid,uid));con.commit();con.close()

def link(repo,scope,uid,relation='primary',state='confirmed'):
    """Register scope (once) and link it to the business uid."""
    con=sqlite3.connect(db_path(repo))
    row=con.execute('SELECT id FROM projects WHERE scope_id=?',(scope,)).fetchone()
    pid=row[0] if row else con.execute('INSERT INTO projects (scope_id) VALUES (?)',(scope,)).lastrowid
    con.execute('INSERT INTO business_project_links VALUES (?,?,?,?,?)',(WS,uid,pid,relation,state));con.commit();con.close()

def standard(repo):
    """make_registry + the business 合成業務 (bpr_synthetic_test). Layers are linked by register()."""
    make_registry(repo);add_business(repo,'bpr_synthetic_test',BUSINESS)

def register(repo,scope,uid='bpr_synthetic_test'):
    """Give scope the primary uid unless it already has one (prepare may run twice for one scope)."""
    con=sqlite3.connect(db_path(repo))
    has=con.execute("SELECT 1 FROM business_project_links l JOIN projects p ON p.id=l.project_id WHERE p.scope_id=? AND l.relation_type='primary'",(scope,)).fetchone()
    con.close()
    if not has:link(repo,scope,uid)

def auto_register(case,package):
    """setUp helper for the earlier box_root_v1 archive tests: a standard Registry outside case.repo (so the tests that
    compare the repository before and after see no fixture write), and archive_course that first gives the Layer's scope_id
    the primary 合成業務 (as the Collection membership would have) and reads that Registry (registry_db)."""
    import tempfile, yaml
    from unittest import mock
    reg=tempfile.TemporaryDirectory();case.addCleanup(reg.cleanup);case.registry=Path(reg.name)
    standard(case.registry);real=package.archive_course
    def archive(layer,*a,**k):
        scope=yaml.safe_load((Path(layer)/'intent.yaml').read_text()).get('scope_id')
        if isinstance(scope,str):register(case.registry,scope)
        k.setdefault('registry_db',db_path(case.registry))
        return real(layer,*a,**k)
    p=mock.patch.object(package,'archive_course',archive);p.start();case.addCleanup(p.stop)
