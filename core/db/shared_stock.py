"""Shared Stock protocol: isolated FixtureStore, plus a host-bound LiveStore.

FixtureStore owns a fresh temp tree only. LiveStore is issued from a reviewed
issuance file that names one adopted Program x business tuple, one AI-PLC, one
writer and a finite period; it never accepts another selector, Layer or writer.
A bare path/JSON flag is still not authority: the issuance must sit under the repo
root, match the current OS principal, and be unexpired. The business-project
identity tables (business_registry.py) remain authoritative and are never written here.
"""
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
import sqlite3
import tempfile


class Hold(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe(root, relative):
    root = Path(root).absolute()
    if not isinstance(relative, str) or not relative or relative=='.' or str(Path(relative))!=relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise Hold('unsafe relative path')
    p = root / relative
    if any(q.is_symlink() for q in (p, *p.parents)) or not p.resolve().is_relative_to(root.resolve()):
        raise Hold('symlink or escape')
    return p


def future(expiry):
    try:
        value = datetime.fromisoformat(expiry)
        if value.tzinfo is None or value <= datetime.now(timezone.utc):
            raise ValueError()
    except (ValueError, TypeError):
        raise Hold('writer period expired or unknown')


IDENTITY_KEYS = ('id', 'scope_id', 'workspace_id', 'sync_uid', 'ownership_epoch', 'identity_version', 'parent_scope', 'status')

STOCK_DDL = '''
  CREATE TABLE IF NOT EXISTS stock_bindings(
    binding_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
    read_domain TEXT NOT NULL, program_uid TEXT NOT NULL, business_uid TEXT NOT NULL,
    folder TEXT NOT NULL UNIQUE, generation INTEGER NOT NULL DEFAULT 0,
    current_revision TEXT, identity_json TEXT NOT NULL,
    UNIQUE(workspace_id,read_domain,program_uid,business_uid));
  CREATE TABLE IF NOT EXISTS stock_operations(
    request_id TEXT PRIMARY KEY, binding_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
    plan_json TEXT NOT NULL, writer TEXT NOT NULL, state TEXT NOT NULL,
    base_revision TEXT, post_generation INTEGER NOT NULL, receipt_json TEXT);
'''


class FixtureStore:
    """Owns a newly allocated temp tree. Not an adapter for any existing database."""
    db_rel = 'registry.sqlite'
    isolated = True

    def __init__(self):
        self._temp = tempfile.TemporaryDirectory(prefix='ai-plc-stock-isolated-')
        self.root = Path(self._temp.name).resolve()
        self.db_path = self.root / 'registry.sqlite'
        self.stock = self.root / 'Stock'
        self.stock.mkdir()
        self.lock_path = self.root / '.writer.lock'
        self.lock_path.touch()
        self.staging = self.root
        spec = importlib.util.spec_from_file_location('_stock_business_schema', Path(__file__).with_name('business_registry.py'))
        schema = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(schema)
        with self.db() as db:
            db.execute('CREATE TABLE projects(id INTEGER PRIMARY KEY, scope_id TEXT, workspace_id TEXT, sync_uid TEXT, ownership_epoch INTEGER, identity_version INTEGER, status TEXT)')
            for statement in schema.DDL:  # the four business tables and their indexes
                db.execute(statement)
            db.executescript(STOCK_DDL)

    def close(self):
        self._temp.cleanup()

    # Hooks: the isolated store accepts exactly what its synthetic seed wrote.
    # LiveStore narrows every hook to the single issued tuple/Layer/writer.
    def _visibility_ok(self, visibility, read_domain):
        return visibility == read_domain

    def _snapshot_ok(self, snapshot, project):
        # Fixture links store canonical JSON; business_registry.py links store the digest
        # of the fixed identity dict. Both are exact matches only.
        return snapshot == canonical(project) or snapshot == digest({k: project.get(k) for k in IDENTITY_KEYS})

    def _check_selector(self, selector):
        pass

    def _check_folder(self, folder):
        pass

    def _check_project(self, scope_id, aiplc_uid):
        pass

    def _check_writer(self, writer):
        pass

    def check_contract(self, contract):
        pass

    @contextmanager
    def db(self):
        # Recheck every connection; replacing the test DB with a link is not allowed.
        safe(self.root, self.db_rel)
        db = sqlite3.connect(self.db_path, timeout=0)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def writer_lock(self):
        with safe(self.lock_path.parent, self.lock_path.name).open('r+') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Hold('concurrent writer')
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def identity(self, selector):
        required = {'workspace_id', 'read_domain', 'program_uid', 'business_uid'}
        if set(selector) != required or any(not isinstance(x, str) or not x for x in selector.values()):
            raise Hold('explicit stable identity tuple required')
        self._check_selector(selector)
        with self.db() as db:
            p = db.execute('SELECT * FROM programs WHERE workspace_id=? AND program_uid=? AND state=\'active\'', (selector['workspace_id'], selector['program_uid'])).fetchone()
            b = db.execute('SELECT * FROM business_projects WHERE workspace_id=? AND business_uid=? AND state=\'active\'', (selector['workspace_id'], selector['business_uid'])).fetchone()
            m = db.execute('SELECT * FROM program_memberships WHERE workspace_id=? AND program_uid=? AND business_uid=? AND target_kind=\'business_project\' AND state=\'confirmed\'', (selector['workspace_id'], selector['program_uid'], selector['business_uid'])).fetchall()
        if not p or not b or len(m) != 1 or p['read_domain'] != selector['read_domain'] or not self._visibility_ok(b['visibility'], selector['read_domain']):
            raise Hold('Registry tuple or confirmed membership unresolved')
        return {'program': dict(p), 'business': dict(b), 'membership': dict(m[0])}

    def bind(self, selector, *, folder=None):
        """Collection route: lookup/reuse, or explicit adopted relative folder."""
        identity = self.identity(selector)
        self._check_folder(folder)
        bid = digest(selector)
        with self.writer_lock(), self.db() as db:
            row = db.execute('SELECT * FROM stock_bindings WHERE binding_id=?', (bid,)).fetchone()
            if row:
                if row['identity_json'] != canonical(identity) or (folder is not None and folder != row['folder']):
                    raise Hold('binding identity/path changed')
                safe(self.stock, row['folder'])
                return dict(row)
            if folder is None:
                raise Hold('new tuple needs concrete folder adoption')
            dest = safe(self.stock, folder)
            for existing in db.execute('SELECT folder FROM stock_bindings'):
                other=safe(self.stock,existing[0])
                if dest==other or dest in other.parents or other in dest.parents:
                    raise Hold('overlapping Stock destination')
            if dest.exists():
                raise Hold('unregistered existing folder; explicit import required')
            # Registry is the authority. Folder creation is lazy at commit; no FS
            # side effect is needed for binding, so a failed INSERT leaves no orphan.
            db.execute('INSERT INTO stock_bindings(binding_id,workspace_id,read_domain,program_uid,business_uid,folder,identity_json) VALUES (?,?,?,?,?,?,?)', (bid, selector['workspace_id'], selector['read_domain'], selector['program_uid'], selector['business_uid'], folder, canonical(identity)))
            return dict(db.execute('SELECT * FROM stock_bindings WHERE binding_id=?', (bid,)).fetchone())

    def binding(self, bid):
        with self.db() as db:
            r = db.execute('SELECT * FROM stock_bindings WHERE binding_id=?', (bid,)).fetchone()
        if not r:
            raise Hold('unknown binding')
        r = dict(r)
        selector = {k:r[k] for k in ('workspace_id','read_domain','program_uid','business_uid')}
        if r['identity_json'] != canonical(self.identity(selector)):
            raise Hold('Registry identity revision changed')
        safe(self.stock, r['folder'])
        return r

    def project_identity(self, bid, scope_id, aiplc_uid):
        self._check_project(scope_id, aiplc_uid)
        b = self.binding(bid)
        with self.db() as db:
            projects = db.execute('SELECT * FROM projects WHERE workspace_id=? AND scope_id=? AND sync_uid=?', (b['workspace_id'], scope_id, aiplc_uid)).fetchall()
            if len(projects) != 1:
                raise Hold('AI-PLC identity unresolved')
            p = dict(projects[0])
            links = db.execute('SELECT * FROM business_project_links WHERE workspace_id=? AND business_uid=? AND project_id=? AND aiplc_uid=? AND state=\'confirmed\'', (b['workspace_id'], b['business_uid'], p['id'], aiplc_uid)).fetchall()
        if p['status'] == 'cancelled' or len(links) != 1:
            raise Hold('confirmed business-to-AI-PLC link required')
        link = dict(links[0])
        if link['project_epoch'] != p['ownership_epoch'] or link['project_version'] != p['identity_version'] or not self._snapshot_ok(link['identity_snapshot'], p):
            raise Hold('stale AI-PLC ownership/identity snapshot')
        return {'project': p, 'link': link}

    def _read_revision(self, binding, revision):
        if revision is None:
            return {'units': {}, 'sources': {}}
        p = safe(self.stock, binding['folder'] + '/revisions/' + revision)
        manifest = json.loads(safe(p, 'manifest.json').read_text())
        if digest(manifest) != revision:
            raise Hold('revision manifest changed')
        files = manifest['files']
        actual = {str(q.relative_to(p)) for q in p.rglob('*') if q.is_file()}
        if actual != set(files) | {'manifest.json'}:
            raise Hold('revision contains missing/unknown files')
        for rel, expected in files.items():
            if sha(safe(p, rel).read_bytes()) != expected:
                raise Hold('revision content changed')
        if manifest['parent'] is not None:
            self._read_revision(binding,manifest['parent'])
        return json.loads(safe(p, 'organized.json').read_text())

    def read(self, bid):
        b = self.binding(bid)
        return {'binding': b, 'content': self._read_revision(b, b['current_revision'])}

    def prepare(self, bid, provenance, originals, units):
        """Read-only diff. Units are reviewed claims/sections, never auto truth."""
        b = self.binding(bid)
        needed = {'scope_id','aiplc_uid','task_id','as_of','decision_ref'}
        if set(provenance) != needed or any(not isinstance(v,str) or not v for v in provenance.values()):
            raise Hold('incomplete provenance')
        identity = self.project_identity(bid, provenance['scope_id'], provenance['aiplc_uid'])
        if not originals or not units:
            raise Hold('originals and organized units required')
        for path, text in originals.items():
            safe(self.root, path)
            if not isinstance(text, str): raise Hold('UTF-8 documents required')
        hashes = {p:sha(t.encode()) for p,t in originals.items()}
        source = {**provenance, 'identity':identity, 'original_hashes':hashes}
        sid = digest(source)
        current = self._read_revision(b, b['current_revision'])
        merged = copy.deepcopy(current)
        merged['sources'][sid] = source
        conflicts = []
        for key, unit in units.items():
            if not isinstance(key,str) or not key or set(unit) != {'kind','text','source_paths'} or unit['kind'] not in ('observed','user_reported','hypothesis','inference','unknown') or not isinstance(unit['text'],str) or not unit['text'].strip() or not isinstance(unit['source_paths'],list) or not unit['source_paths'] or not set(unit['source_paths']) <= set(originals):
                raise Hold('invalid organized unit/evidence classification')
            incoming = {'kind':unit['kind'],'text':unit['text']}
            old = merged['units'].get(key)
            if old and any(old[k] != incoming[k] for k in incoming):
                conflicts.append({'key':key,'current':old,'incoming':unit})
                continue
            target = merged['units'].setdefault(key, {**incoming,'provenance':{}})
            target['provenance'][sid] = sorted(set(unit['source_paths']))
        return {'binding_id':bid,'base_generation':b['generation'],'base_revision':b['current_revision'],'registry_identity':json.loads(b['identity_json']),'source':source,'source_id':sid,'originals':originals,'incoming_units':units,'organized':merged,'conflicts':conflicts,'diff':{'added':[k for k in merged['units'] if k not in current['units']],'unchanged':[k for k in units if k in current['units'] and k not in {c['key'] for c in conflicts}],'provenance_added':sid not in current['sources']}}

    def _files(self, plan):
        files = {'organized.json':canonical(plan['organized']).encode()}
        for path, text in plan['originals'].items():
            files['originals/'+plan['source_id']+'/'+path] = text.encode()
        # Earlier original snapshots remain in immutable prior revisions. Source
        # hashes/identity in organized.json and the parent revision preserve lineage.
        manifest = {'parent':plan['base_revision'],'source_id':plan['source_id'],'files':{p:sha(v) for p,v in files.items()}}
        return files, manifest, digest(manifest)

    def commit(self, plan, *, approved_hash, request_id, writer, expires_at, fault=None):
        future(expires_at)
        if not isinstance(writer,str) or not writer or not isinstance(request_id,str) or not request_id or digest(plan) != approved_hash:
            raise Hold('concrete diff/writer adoption mismatch')
        self._check_writer(writer)
        if plan['conflicts']:
            raise Hold('conflicting claims: keep current and revise the proposal')
        with self.writer_lock():
            b = self.binding(plan['binding_id'])
            with self.db() as db:
                old = db.execute('SELECT * FROM stock_operations WHERE request_id=?',(request_id,)).fetchone()
                if old and (old['payload_hash'] != approved_hash or old['writer'] != writer):
                    raise Hold('request ID reused with different plan/writer')
                if old and old['state'] == 'compensated': raise Hold('request already compensated')
                if old and old['state'] == 'committed':
                    receipt = json.loads(old['receipt_json'])
                    self._read_revision(b,receipt['revision'])
                    return receipt
                pending = db.execute("SELECT request_id FROM stock_operations WHERE binding_id=? AND state='prepared'",(b['binding_id'],)).fetchall()
                if any(row[0] != request_id for row in pending): raise Hold('recover pending request first')
            if b['generation'] != plan['base_generation'] or b['current_revision'] != plan['base_revision']:
                raise Hold('stale Stock diff')
            if json.loads(b['identity_json']) != plan['registry_identity'] or self.project_identity(b['binding_id'],plan['source']['scope_id'],plan['source']['aiplc_uid']) != plan['source']['identity']:
                raise Hold('source identity changed')
            # Recompute derived output rather than trusting editable plan fields.
            fresh = self.prepare(b['binding_id'],{k:plan['source'][k] for k in ('scope_id','aiplc_uid','task_id','as_of','decision_ref')},plan['originals'],plan['incoming_units'])
            if fresh != plan: raise Hold('prepared diff altered')
            if plan['organized']==self._read_revision(b,b['current_revision']):
                receipt={'request_id':request_id,'binding_id':b['binding_id'],'revision':b['current_revision'],'generation':b['generation'],'plan_hash':approved_hash,'writer':writer,'source_id':plan['source_id'],'base_revision':b['current_revision'],'isolated_only':self.isolated,'noop':True}
                with self.db() as db:
                    db.execute('INSERT INTO stock_operations VALUES (?,?,?,?,?,?,?,?,?)',(request_id,b['binding_id'],approved_hash,canonical(plan),writer,'committed',b['current_revision'],b['generation'],canonical(receipt)))
                return receipt
            if not old:
                with self.db() as db:
                    db.execute('INSERT INTO stock_operations VALUES (?,?,?,?,?,?,?,?,?)',(request_id,b['binding_id'],approved_hash,canonical(plan),writer,'prepared',b['current_revision'],b['generation']+1,None))
            if fault == 'after_prepare': raise RuntimeError('injected after_prepare')
            files, manifest, revision = self._files(plan)
            dest = safe(self.stock,b['folder']+'/revisions/'+revision)
            dest.mkdir(parents=True,exist_ok=True)
            for relative, data in {**files,'manifest.json':canonical(manifest).encode()}.items():
                path = safe(dest,relative); path.parent.mkdir(parents=True,exist_ok=True)
                if path.exists():
                    if path.read_bytes() != data: raise Hold('materialized file changed; no overwrite')
                else:
                    # Stage outside the immutable revision. A partial write must
                    # never look like an adopted completed file. The root-owned
                    # temporary file is expendable; finalized paths are not.
                    fd, temporary = tempfile.mkstemp(prefix='.stock-write-',dir=self.staging)
                    try:
                        with os.fdopen(fd,'wb') as stream:
                            if fault=='during_file_write':
                                stream.write(data[:10]);stream.flush()
                                raise OSError('injected interrupted write')
                            stream.write(data); stream.flush(); os.fsync(stream.fileno())
                        # link is exclusive (no replace): a racing existing path
                        # is rejected rather than overwritten by rename.
                        os.link(temporary,path)
                        directory_fd=os.open(path.parent,os.O_RDONLY)
                        try:os.fsync(directory_fd)
                        finally:os.close(directory_fd)
                    finally:
                        if os.path.exists(temporary):os.unlink(temporary)
            self._read_revision(b,revision)
            if fault == 'after_materialize': raise RuntimeError('injected after_materialize')
            future(expires_at)
            receipt = {'request_id':request_id,'binding_id':b['binding_id'],'revision':revision,'generation':b['generation']+1,'plan_hash':approved_hash,'writer':writer,'source_id':plan['source_id'],'base_revision':b['current_revision'],'isolated_only':self.isolated}
            with self.db() as db:
                changed = db.execute('UPDATE stock_bindings SET generation=?,current_revision=? WHERE binding_id=? AND generation=?',(receipt['generation'],revision,b['binding_id'],b['generation'])).rowcount
                if changed != 1: raise Hold('concurrent Registry change')
                db.execute("UPDATE stock_operations SET state='committed',receipt_json=? WHERE request_id=?",(canonical(receipt),request_id))
            if fault == 'after_commit': raise RuntimeError('injected after_commit')
            return receipt

    def compensate(self, request_id, *, writer, expires_at):
        future(expires_at)
        self._check_writer(writer)
        with self.writer_lock():
            with self.db() as db:
                op = db.execute('SELECT * FROM stock_operations WHERE request_id=?',(request_id,)).fetchone()
            if not op or op['state'] != 'committed' or op['writer'] != writer: raise Hold('only own committed request can be compensated')
            receipt = json.loads(op['receipt_json']); b = self.binding(op['binding_id'])
            if receipt.get('noop'):raise Hold('no-op has no own change to restore')
            with self.db() as db:
                if db.execute("SELECT 1 FROM stock_operations WHERE binding_id=? AND state='prepared'",(b['binding_id'],)).fetchone():raise Hold('recover pending operation before compensation')
            if b['generation'] != receipt['generation'] or b['current_revision'] != receipt['revision']: raise Hold('later writer/version; no restoration')
            self._read_revision(b,receipt['revision']); self._read_revision(b,receipt['base_revision'])
            future(expires_at)
            with self.db() as db:
                changed = db.execute('UPDATE stock_bindings SET current_revision=?,generation=generation+1 WHERE binding_id=? AND generation=?',(op['base_revision'],b['binding_id'],b['generation'])).rowcount
                if changed != 1: raise Hold('concurrent change')
                db.execute("UPDATE stock_operations SET state='compensated' WHERE request_id=?",(request_id,))
            return {'state':'compensated','originals_retained':True,'generation':b['generation']+1}


class LiveStore(FixtureStore):
    """Host-bound runtime for exactly one adopted tuple, Layer and writer.

    Issued from an issuance JSON under the repo root (reviewed and hash-recorded by
    the adopting Task). Issuance only touches the empty writer lock file and the
    staging directory named by the issuance; no Registry row or Stock file is
    written. Schema install is a separate explicit call gated by the issuance flag.
    Every Registry access (bind/identity/read as well as commit/compensate)
    re-checks the issued period.
    """
    REQUIRED = {'version', 'repo_root', 'db_rel', 'stock_rel', 'lock_rel', 'staging_rel', 'host_uid',
                'selector', 'scope_id', 'aiplc_uid', 'adopted_folder', 'writer', 'task_id',
                'issued_at', 'issued_by', 'approval_ref', 'expires_at', 'allow_schema_install'}
    isolated = False

    def __init__(self, issuance_path):
        path = Path(issuance_path)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise Hold('issuance must be an absolute regular file')
        raw = path.read_bytes()
        try:
            spec = json.loads(raw)
        except ValueError:
            raise Hold('issuance is not JSON')
        if not isinstance(spec, dict) or set(spec) != self.REQUIRED or spec['version'] != 'live-v1':
            raise Hold('unsupported issuance shape/version')
        for key in ('repo_root', 'db_rel', 'stock_rel', 'lock_rel', 'staging_rel', 'scope_id', 'aiplc_uid', 'adopted_folder', 'writer', 'task_id', 'issued_at', 'issued_by', 'approval_ref', 'expires_at'):
            if not isinstance(spec[key], str) or not spec[key]:
                raise Hold('issuance field missing: ' + key)
        if type(spec['allow_schema_install']) is not bool or type(spec['host_uid']) is not int:
            raise Hold('issuance flags must be typed')
        selector = spec['selector']
        if not isinstance(selector, dict) or set(selector) != {'workspace_id', 'read_domain', 'program_uid', 'business_uid'} or any(not isinstance(v, str) or not v for v in selector.values()):
            raise Hold('issuance needs the explicit stable identity tuple')
        if spec['host_uid'] != os.getuid():
            raise Hold('issuance bound to another OS principal')
        future(spec['expires_at'])
        root = Path(spec['repo_root'])
        if not root.is_absolute() or root.resolve() != root or not root.is_dir():
            raise Hold('repo_root must be an absolute resolved directory')
        if not path.resolve().is_relative_to(root):
            raise Hold('issuance must live under repo_root')
        self.root = root
        self.db_rel = spec['db_rel']
        self.db_path = safe(root, spec['db_rel'])
        if not self.db_path.is_file():
            raise Hold('live Registry database missing')
        self.stock = safe(root, spec['stock_rel'])
        if not self.stock.is_dir():
            raise Hold('live Stock root missing')
        self.lock_path = safe(root, spec['lock_rel'])
        if not self.lock_path.parent.is_dir():
            raise Hold('lock directory missing')
        self.lock_path.touch(exist_ok=True)
        self.staging = safe(root, spec['staging_rel'])
        if self.staging.exists() and not self.staging.is_dir():
            raise Hold('staging path is not a directory')
        self.staging.mkdir(exist_ok=True)
        self.spec = copy.deepcopy(spec)
        self.issuance_path = path
        self.issuance_sha256 = sha(raw)
        self._temp = None

    def close(self):
        pass

    @contextmanager
    def db(self):
        with super().db() as db:
            if not getattr(self, '_installing', False):
                present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('stock_bindings','stock_operations')")}
                if present != {'stock_bindings', 'stock_operations'}:
                    raise Hold('shared Stock schema not installed in live Registry')
            yield db

    def describe(self):
        return {'runtime': 'live', 'issuance_sha256': self.issuance_sha256, 'scope_id': self.spec['scope_id'],
                'writer': self.spec['writer'], 'task_id': self.spec['task_id'], 'expires_at': self.spec['expires_at'],
                'adopted_folder': self.spec['adopted_folder'], 'db_rel': self.db_rel}

    def install_schema(self):
        """Additive only: creates the two shared-Stock tables when absent."""
        if not self.spec['allow_schema_install']:
            raise Hold('schema install not allowed by this issuance')
        future(self.spec['expires_at'])
        self._installing = True
        try:
            with self.writer_lock(), self.db() as db:
                before = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('stock_bindings','stock_operations')")}
                db.executescript(STOCK_DDL)
                after = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('stock_bindings','stock_operations')")}
        finally:
            self._installing = False
        return {'installed': sorted(after - before), 'already_present': sorted(before)}

    def _check_selector(self, selector):
        future(self.spec['expires_at'])
        if selector != self.spec['selector']:
            raise Hold('live runtime issued for another Program/business tuple')

    def _check_folder(self, folder):
        if folder is not None and folder != self.spec['adopted_folder']:
            raise Hold('live runtime issued for another adopted folder')

    def _check_project(self, scope_id, aiplc_uid):
        future(self.spec['expires_at'])
        if (scope_id, aiplc_uid) != (self.spec['scope_id'], self.spec['aiplc_uid']):
            raise Hold('live runtime issued for another AI-PLC Layer')

    def _check_writer(self, writer):
        if writer != self.spec['writer']:
            raise Hold('live runtime issued for another writer')
        future(self.spec['expires_at'])

    def check_contract(self, contract):
        if contract.get('storage') != 'registry_stock_v1':
            raise Hold('shared storage not selected')
        self._check_selector(contract.get('stock_selector'))
        self._check_project(contract.get('scope_id'), contract.get('aiplc_uid'))
