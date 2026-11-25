"""Normal AIPM Collection/archive/reuse entry over an explicit Stock runtime.

Runtime is either the isolated FixtureStore or a LiveStore issued for one adopted
tuple/Layer/writer. No side effects occur without the in-memory
capability; a YAML path/bool in intent is not authority and cannot pick a runtime.
"""
from pathlib import Path
from datetime import datetime, timezone
import copy
import fcntl
import importlib.util
import json
import os
import sys
import tempfile
import yaml
sys.dont_write_bytecode = True
from package import build_contract, safe_path, load, sha, input_path

spec = importlib.util.spec_from_file_location('_aiplc_shared_stock_core',Path(__file__).resolve().parents[2]/'db/shared_stock.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
FixtureStore = core.FixtureStore
LiveStore = core.LiveStore
Hold = core.Hold


def require_runtime(runtime, layer):
    if type(runtime) not in (FixtureStore, LiveStore):
        raise Hold('explicit Stock runtime required (isolated FixtureStore or issued LiveStore)')
    p = Path(layer).absolute()
    if not p.resolve().is_relative_to(runtime.root) or any(x.is_symlink() for x in (p,*p.parents)):
        raise Hold('runtime may only operate on Layers under its own root')
    return runtime


def collection(layer, runtime, *, adopted_folder=None):
    runtime = require_runtime(runtime,layer)
    c = build_contract(layer)
    if c.get('storage') != 'registry_stock_v1':raise Hold('shared storage not selected')
    runtime.check_contract(c)
    b = runtime.bind(c['stock_selector'],folder=adopted_folder)
    runtime.project_identity(b['binding_id'],c['scope_id'],c['aiplc_uid'])
    return {'binding':b,'current':runtime.read(b['binding_id'])['content'],'isolated_only':runtime.isolated}


def prepare_archive(layer, runtime, *, task_id, decision_ref, units, as_of=None):
    from validate_package import validate
    runtime = require_runtime(runtime,layer)
    c = build_contract(layer); root = safe_path(layer,c['package_root'])
    check = validate(root,phase='prearchive',layer=layer)
    if not check['pass']:raise Hold('prearchive validation failed: '+str(check['errors']))
    state = collection(layer,runtime); m = load(root/'manifest.yaml')
    originals = {r['path']:safe_path(root,r['path']).read_bytes().decode('utf-8') for r in m['records']}
    plan = runtime.prepare(state['binding']['binding_id'],{'scope_id':c['scope_id'],'aiplc_uid':c['aiplc_uid'],'task_id':task_id,'decision_ref':decision_ref,'as_of':as_of or datetime.now(timezone.utc).isoformat()},originals,units)
    dependencies = set()
    for r in m['records']:dependencies.update(r['inputs'])
    for e in m['evidence']:dependencies.add(e['source'])
    pins = {'intent.yaml':sha(Path(layer)/'intent.yaml')}
    for q in [root/'manifest.yaml',root/'validation_record.yaml',root/'format_contract.yaml']:
        pins[str(q.relative_to(layer))] = sha(q)
    for path in dependencies:pins[path]=sha(input_path(layer,path))   # method_source:<path> (the new courses' fixed sources) resolves in the method folder
    for path in originals:pins[str((root/path).relative_to(layer))]=sha(root/path)
    return {'plan':plan,'input_pins':pins,'scope_id':c['scope_id'],'package_root':c['package_root']}


def apply_archive(layer, runtime, proposal, *, approved_hash, request_id, writer, expires_at, fault=None):
    runtime=require_runtime(runtime,layer)
    root=safe_path(layer,build_contract(layer)['package_root'])
    with safe_path(root,'.archive.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:raise Hold('concurrent package writer')
        try:
            return _apply_archive(layer,runtime,proposal,approved_hash=approved_hash,request_id=request_id,writer=writer,expires_at=expires_at,fault=fault)
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


def _apply_archive(layer, runtime, proposal, *, approved_hash, request_id, writer, expires_at, fault=None):
    """Apply exact presented proposal after prearchive validation, no auto approval."""
    from validate_package import validate
    runtime = require_runtime(runtime,layer)
    core.future(expires_at)
    if core.digest(proposal) != approved_hash:raise Hold('archive proposal adoption mismatch')
    c = build_contract(layer); root = safe_path(layer,c['package_root'])
    receipt_path = root/'shared_archive_receipt.json'
    # A completed same-request retry is a readback, not another archive event.
    if receipt_path.exists():
        prior=json.loads(receipt_path.read_text())
        if prior['request_id'] != request_id or prior['proposal_hash'] != approved_hash:raise Hold('package already archived by another request')
        verify_archive(layer,runtime,prior)
        return prior
    journal_path=safe_path(root,'shared_archive_pending.json')
    for relative,expected in proposal['input_pins'].items():
        if relative!=str((root/'manifest.yaml').relative_to(layer)) and sha(input_path(layer,relative))!=expected:raise Hold('Flow/input changed after diff')
    if journal_path.exists():
        journal=json.loads(journal_path.read_text())
        if (journal['request_id'],journal['proposal_hash'],journal['writer'])!=(request_id,approved_hash,writer):raise Hold('different package archive pending')
        before=journal['manifest_before'].encode()
        manifest_relative=str((root/'manifest.yaml').relative_to(layer))
        if core.sha(before)!=proposal['input_pins'][manifest_relative]:raise Hold('recovery preimage hash mismatch')
        current=(root/'manifest.yaml').read_bytes()
        if current!=before:
            if core.sha(current)!=journal.get('manifest_post_sha256'):raise Hold('later manifest change; no self recovery')
            atomic_text(root/'manifest.yaml',journal['manifest_before'])
    for relative, expected in proposal['input_pins'].items():
        if sha(input_path(layer,relative)) != expected:raise Hold('Flow/input changed after diff')
    result=validate(root,phase='prearchive',layer=layer)
    if not result['pass']:raise Hold('prearchive no longer valid')
    if not journal_path.exists():
        journal={'request_id':request_id,'proposal_hash':approved_hash,'writer':writer,'manifest_before':(root/'manifest.yaml').read_bytes().decode('utf-8')}
        atomic_text(journal_path,json.dumps(journal,ensure_ascii=False))
    receipt=runtime.commit(proposal['plan'],approved_hash=core.digest(proposal['plan']),request_id=request_id,writer=writer,expires_at=expires_at,fault=fault)
    m=load(root/'manifest.yaml'); start=datetime.now(timezone.utc).isoformat()
    for r in m['records']:
        if r['stage']=='init':continue
        r.update(status='archived_local_final',archive_path='originals/'+receipt['source_id']+'/'+r['path'],archive_sha256=r['sha256'])
    m['stages'].append({'name':'archive','started_at':start,'finished_at':datetime.now(timezone.utc).isoformat(),'checkpoint_actor':'auto_decision','checkpoint_status':'accepted_local','evidence_refs':[e['id'] for e in m['evidence']]})
    saved={**receipt,'proposal_hash':approved_hash,'manifest_before_hash':proposal['input_pins'][str((root/'manifest.yaml').relative_to(layer))]}
    # Journal retains the exact preimage and own posthash. A same-request retry
    # may restore only that manifest, never unknown subsequent changes.
    after=yaml.safe_dump(m,allow_unicode=True,sort_keys=False)
    journal['manifest_post_sha256']=core.sha(after.encode())
    atomic_text(journal_path,json.dumps(journal,ensure_ascii=False))
    atomic_text(root/'manifest.yaml',after)
    if fault=='after_package_manifest':raise RuntimeError('injected after_package_manifest')
    atomic_text(receipt_path,json.dumps(saved,ensure_ascii=False,indent=2)+'\n')
    verify_archive(layer,runtime,saved)
    return saved


def atomic_text(path,text):
    path=Path(path)
    safe_path(path.parent,path.name)
    fd,temp=tempfile.mkstemp(prefix='.stock-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def verify_archive(layer, runtime, receipt=None):
    runtime=require_runtime(runtime,layer); c=build_contract(layer); root=safe_path(layer,c['package_root'])
    if receipt is None:receipt=json.loads((root/'shared_archive_receipt.json').read_text())
    b=runtime.bind(c['stock_selector'])
    if receipt['binding_id'] != b['binding_id']:raise Hold('wrong archive binding')
    with runtime.db() as db:
        op=db.execute('SELECT * FROM stock_operations WHERE request_id=?',(receipt['request_id'],)).fetchone()
    if not op or op['state']!='committed':raise Hold('archive operation not committed or compensated')
    trusted=json.loads(op['receipt_json'])
    if any(receipt.get(k)!=v for k,v in trusted.items()):raise Hold('archive receipt forged')
    plan=json.loads(op['plan_json'])
    if plan['source']['scope_id']!=c['scope_id'] or plan['source']['aiplc_uid']!=c['aiplc_uid']:raise Hold('wrong source Layer')
    runtime.project_identity(b['binding_id'],c['scope_id'],c['aiplc_uid'])
    runtime._read_revision(b,receipt['revision'])
    for path,text in plan['originals'].items():
        if safe_path(root,path).read_bytes()!=text.encode():raise Hold('Flow changed after archive')
    return {'pass':True,'receipt':receipt,'original_hashes':plan['source']['original_hashes']}
