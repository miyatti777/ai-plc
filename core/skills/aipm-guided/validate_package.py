#!/usr/bin/env python3
"""Read-only common AIPM validator; dynamically bound to explicitly selected Layers."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import argparse, hashlib, json, re
from datetime import date, datetime, timezone
import yaml

METHOD = Path(__file__).resolve().parent
from package import build_contract, select, safe_path, input_path, source_path, course_registry, LEGACY_COURSE, registers_contract_path, prior_answer_problem, BOX_ROOT_LAYOUT, NESTED_LAYOUT, FLAT_LAYOUTS, SHEETS_LAYOUT, SHEETS_ROOT, LEGACY_ROOT, SHEETS_MIGRATION_BY, registers_layout, pkg_rel, doc_rel, init_roots, stock_root_of, business_folder, APPLY_KINDS, STOCK_PROGRAMS, LAYER_ARCHIVE, archive_base_for, archive_settings
import light   # loaded with the package, while this folder is on sys.path

class UniqueLoader(yaml.SafeLoader):
    pass

def unique_map(loader, node, deep=False):
    result = {}
    for key, val in node.value:
        k = loader.construct_object(key, deep=deep)
        if k in result:
            raise ValueError('duplicate YAML key: ' + str(k))
        result[k] = loader.construct_object(val, deep=deep)
    return result
UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_map)

def load(path):
    return yaml.load(path.read_text(), Loader=UniqueLoader)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate(package, phase="final", layer=None, stock_runtime=None, stock_root=None):
    """stock_root: the repository root that holds Stock/ for a box_root_v1 archive (default: the parent of the Flow folder
    that holds the Layer). nested_v1 packages keep their Stock copy inside the package and ignore it."""
    if layer is None: raise ValueError("explicit layer required")
    LAYER = Path(layer).absolute()
    # validate learns AIPM ライトモード
    try: light_kind = light.record(LAYER)[0]
    except (OSError, ValueError, yaml.YAMLError): light_kind = None   # an unreadable Sheets/ does not stop a Layer without a method
    if not select(LAYER):
        if light.is_light(LAYER):
            if Path(package).absolute() != safe_path(LAYER, SHEETS_ROOT): raise ValueError("package must be the selected Layer " + SHEETS_ROOT)
            if light_kind != light.LIGHT_KIND: return {"pass": False, "route": light.LIGHT, "errors": [{"code": "E_LIGHT", "path": SHEETS_ROOT, "message": "AIPM ライトモード is selected but its box is missing (run package.py init --light)"}], "warnings": [], "checked_documents": 0}
            return light.validate(LAYER)
        return {"pass": True, "route": "legacy", "errors": [], "warnings": [], "checked_documents": 0}
    if phase not in ("prearchive", "final"): raise ValueError("unknown validation phase")
    contract = build_contract(LAYER)
    PKG = contract['package_root']   # Sheets (sheets_v1) or Documents/aipm_project (nested_v1, box_root_v1)
    wanted = safe_path(LAYER, PKG)
    if Path(package).absolute() != wanted: raise ValueError("package must be the selected Layer "+PKG)
    shared = contract.get('storage') == 'registry_stock_v1'
    branch = contract.get('course_id',LEGACY_COURSE)
    batch = branch != LEGACY_COURSE
    if load(Path(package)/'format_contract.yaml') != contract: raise ValueError('package contract differs from fixed source schema/bindings')
    root = Path(package).absolute()
    errors = []
    def err(code, path, message):
        errors.append({'code': code, 'path': str(path), 'message': message})
    warnings = []
    def warn(code, path, message):
        warnings.append({'code': code, 'path': str(path), 'message': message})
    mtime_drift = []   # files whose mtime differs from the recorded one: one W_MTIME per package
    def safe(rel):
        q = root / rel
        if Path(rel).is_absolute() or '..' in Path(rel).parts:
            err('E_BOUNDARY', rel, 'absolute or parent-relative path'); return None
        if root.is_symlink() or any(x.is_symlink() for x in [q, *q.parents] if x == root or root in x.parents):
            err('E_BOUNDARY', rel, 'symlink not accepted'); return None
        if not q.resolve().is_relative_to(root.resolve()):
            err('E_BOUNDARY', rel, 'outside package'); return None
        return q
    def stock_safe(rel):
        """A box_root_v1 archive copy: repository-relative under the real Stock root (or, where: layer, Layer-relative
        under Documents/aipm_archive/), no symlinks, never outside it."""
        in_layer = str(rel).startswith(LAYER_ARCHIVE + '/')
        base = archive_base_for(LAYER, rel, stock_root)
        if base is None: err('E_ARCHIVE', rel, 'repository root holding Stock/programs not found; pass stock_root (--stock-root)'); return None
        q = base / rel
        if Path(rel).is_absolute() or '..' in Path(rel).parts or not (in_layer or rel.startswith(STOCK_PROGRAMS + '/')):
            err('E_BOUNDARY', rel, 'Stock copy must be Stock/programs/... under the repository root (or Documents/aipm_archive/... in the Layer)'); return None
        if any(x.is_symlink() for x in [q, *q.parents] if x == base or base in x.parents):
            err('E_BOUNDARY', rel, 'symlink not accepted'); return None
        if not q.resolve().is_relative_to(base.resolve()):
            err('E_BOUNDARY', rel, 'outside repository root'); return None
        return q
    def schema(data, spec, loc):
        typ = spec['type']
        good = {'map': isinstance(data, dict), 'list': isinstance(data, list),
                'string': isinstance(data, str), 'integer': isinstance(data, int) and not isinstance(data, bool)}[typ]
        if not good:
            err('E_SCHEMA', loc, 'expected ' + typ); return
        if typ in ('map','list') and len(data) < spec.get('min_items', 0):
            err('E_SCHEMA', loc, 'too few items')
        if typ == 'map':
            for k, sub in spec.get('fields', {}).items():
                if k not in data: err('E_SCHEMA', loc + '.' + k, 'required key missing')
                else: schema(data[k], sub, loc + '.' + k)
            if 'values' in spec:
                for k,v in data.items(): schema(v, spec['values'], loc + '.' + str(k))
        elif typ == 'list':
            for n,v in enumerate(data): schema(v, spec['items'], loc + '['+str(n)+']')
        elif typ == 'string' and spec.get('nonempty') and not data.strip():
            err('E_SCHEMA', loc, 'empty string')
    if not root.is_dir():
        err('E_MISSING', '.', 'package directory missing')
        return {'pass': False, 'errors': errors, 'warnings': warnings}
    flow, stock = contract['flow_rel'], contract['stock_project_rel']
    box_root = contract.get('layout') in FLAT_LAYOUTS   # box_root_v1 and sheets_v1: the documents sit directly in the package
    if box_root:   # a box_root_v1 package never holds the nested_v1 inner roots (a package of one layout read as the other)
        for inner in ('Flow','Stock'):
            if (root/inner).exists(): err('E_BOUNDARY', inner, contract['layout']+' package must not hold an inner '+inner+'/ folder')
    # The contract folders are not checked on their own: init makes them, but git keeps no empty folder, and a folder
    # proves nothing. Each required document below has its own E_MISSING.
    docs = {}; expected = {}; actual = {}
    for e in contract['documents']:
        rel=doc_rel(contract,e)
        expected[rel]=e; q=safe(rel)
        if q is None: continue
        if not q.is_file(): err('E_MISSING', rel, 'required document missing'); continue
        actual[rel]=q
        text=q.read_text()
        if re.search(r'\{\{|\}\}|\bTODO_PLACEHOLDER\b',text): err('E_PLACEHOLDER',rel,'unrendered template')
        if e['kind']=='yaml':
            try:
                data=load(q); docs[e['step']]=data; schema(data,e['schema'],rel)
            except Exception as ex: err('E_SCHEMA',rel,str(ex))
        else:
            headings=re.findall(r'^#{2,3} (.+)$',text,re.M)
            for h in e.get('required_headings',[]):
                if h not in headings: err('E_HEADING',rel,'missing section '+h)
                elif not re.search(r'^#{2,3} '+re.escape(h)+r'\s*\n(?!\s*#)(?=\s*\S)',text,re.M):
                    err('E_HEADING',rel,'empty section '+h)
            if e['kind']=='mermaid':
                blocks=re.findall(r'```mermaid\s*\n(.*?)\n```',text,re.S)
                if len(blocks)!=1 or not re.search(r'\b(flowchart|graph) (TD|LR|TB|RL|BT)\b',blocks[0] if blocks else ''):
                    err('E_DIAGRAM',rel,'one closed Mermaid flowchart required')
    # Source/template binding is checked independently of package claims.
    source=METHOD/'source'; manifest_source=load(METHOD/'canonical.yaml')
    if manifest_source['reviewed_commit']!=contract['reviewed_commit']: err('E_SOURCE','contract','commit mismatch')
    sm=json.loads((source/'source_manifest.json').read_text()); by_source={x['path']:x for x in sm['files']}
    for e in contract['documents']:
        q=METHOD/e['raw_template']; src=source/e['source']
        if not q.is_file() or digest(q)!=e['template_sha256']:err('E_TEMPLATE',e['raw_template'],'raw template missing or changed')
        if digest(src)!=by_source[e['source']]['sha256']:err('E_SOURCE',e['source'],'fixed source changed')
    mpath=safe('manifest.yaml'); vpath=safe('validation_record.yaml'); manifest={}; validation={}
    for q,what in [(mpath,'manifest'),(vpath,'validation')]:
        if q is None:continue
        if not q.is_file():err('E_MISSING',what,'record missing');continue
        try:
            dat=load(q)
            if not isinstance(dat,dict):raise ValueError('record must be map')
            if what=='manifest':manifest=dat
            else:validation=dat
        except Exception as ex:err('E_SCHEMA',what,str(ex))
    for k in contract['additional_records']['manifest_schema']['required']:
        if k not in manifest:err('E_MANIFEST','manifest.'+k,'required key missing')
    for k in contract['additional_records']['validation_schema']['required']:
        if k not in validation:err('E_VALIDATION','validation.'+k,'required key missing')
    if manifest.get('scope_id')!=contract['scope_id'] or validation.get('scope_id')!=contract['scope_id']:err('E_MANIFEST','scope_id','wrong Scope')
    if manifest.get('source_commit')!=contract['reviewed_commit'] or manifest.get('contract_version')!=contract['version']:err('E_MANIFEST','version','source/contract version mismatch')
    if manifest.get('branch')!=branch:err('E_MANIFEST','branch','wrong selected branch')
    for k in ['flow_rel','stock_project_rel','id_mapping']:
        if manifest.get(k)!=contract[k]:err('E_MANIFEST',k,'binding mismatch')
    if manifest.get('completion_claim')!='local_trial_only; new human readability/effectiveness unknown':err('E_MANIFEST','completion_claim','unsupported completion claim')
    responses=manifest.get('human_responses',{})
    if not isinstance(responses,dict): err('E_CHECKPOINT','human_responses','expected map'); responses={}
    init_rewrites=[]   # (time, Sheets-relative path, sha256 before, sha256 after) of a project_init.yaml rewritten by a recorded nested_v1 move
    migrations=[]   # (time, nested_v1 or not) of each recorded move to sheets_v1 by migrate-sheets
    b_=contract.get('bindings') or {}
    old_flow='Flow/'+str(b_.get('date',''))[:7].replace('-','')+'/'+str(b_.get('date',''))+'/'+str(b_.get('flow_dir',''))   # the nested_v1 flow_rel this contract's bindings give
    if contract.get('layout')==SHEETS_LAYOUT:
        for x in manifest.get('layout_migrations') or []:
            if not (isinstance(x,dict) and x.get('to')==SHEETS_LAYOUT and x.get('by')==SHEETS_MIGRATION_BY and x.get('package')=={'from':LEGACY_ROOT,'to':SHEETS_ROOT}):continue
            if x.get('from')==BOX_ROOT_LAYOUT:nested=False
            elif x.get('from')==NESTED_LAYOUT and isinstance(x.get('flow_rel'),dict) and x['flow_rel'].get('from')==old_flow:nested=True
            else:continue
            try:at=datetime.fromisoformat(x['at'])
            except (KeyError,TypeError,ValueError):continue
            if at.tzinfo is None:continue
            migrations.append((at,nested))
            w=x.get('rewritten')   # project_init.yaml rewritten by the nested_v1 move (program_id, roots)
            if nested and isinstance(w,dict) and all(isinstance(w.get(k),str) for k in ('path','sha256_before','sha256_after')) and isinstance(w.get('fields'),list) and set(w['fields'])<={'program_id','flow_base','stock_base'}:init_rewrites.append((at,w['path'],w['sha256_before'],w['sha256_after']))
    def moved_receipt(receipt,target_path):
        """A receipt written before the recorded move names the old place of the same file (the receipt itself is never
        rewritten): Documents/aipm_project/<rest> for Sheets/<rest> (box_root_v1); for nested_v1, Documents/aipm_project/<name>
        for a package-level file Sheets/<name>, or Documents/aipm_project/<flow_rel>/<rest> (the flow_rel the bindings give)."""
        if not migrations or not target_path.startswith(SHEETS_ROOT+'/'):return False
        try:received=datetime.fromisoformat(receipt['received_at'])
        except (KeyError,TypeError,ValueError):return False
        rest=target_path[len(SHEETS_ROOT)+1:];old=receipt.get('target_path')
        def names(nested):
            if not nested:return {LEGACY_ROOT+'/'+rest}
            return {LEGACY_ROOT+'/'+old_flow+'/'+rest}|({LEGACY_ROOT+'/'+rest} if '/' not in rest else set())
        return received.tzinfo is not None and any(received<at and old in names(nested) for at,nested in migrations)
    def version_of(target_rel):
        """The last apply version that changed target_rel (None: no applies, or the document was never changed by apply)."""
        ap=manifest.get('applies')
        if not isinstance(ap,list):return None
        return next((a for a in reversed(ap) if isinstance(a,dict) and a.get('kind')=='apply' and any(isinstance(x,dict) and x.get('path')==target_rel for x in a.get('changed') or [])),None)
    def confirmed_version(key,r,a,target_rel,target):
        """the answer to a document an apply version changed is that version's receipt (the person's
        judgement of the list): ① the receipt file bytes ② received in the apply_v<N> event ③ a user_reported evidence row
        ④ target = the document now = the version docs ⑤ the list adopted every change of that document in the version."""
        v=(a.get('receipts') or {}).get(key)
        if not isinstance(v,dict) or not isinstance(v.get('source'),str) or not v['source'].startswith('Context/') or v.get('target_path')!=r.get('target_path'):return False
        q=safe_path(LAYER,v['source'])
        if not q.is_file() or digest(q)!=v.get('source_sha256'):return False
        receipt=load(q)
        if not isinstance(receipt,dict) or receipt.get('kind')!='user_reported' or receipt.get('actor')!='actual_user' or receipt.get('origin')!='actual_user_reply':return False
        for field,value in [('scope_id',contract['scope_id']),('stage',key),('answer',v.get('answer')),('target_sha256',v.get('target_sha256')),('target_path',v.get('target_path')),('question_id',v.get('list_digest')),('received_at',v.get('received_at'))]:
            if receipt.get(field)!=value:return False
        if not isinstance(v.get('answer'),str) or not v['answer'].strip() or not isinstance(receipt.get('source_thread_id'),str) or not receipt['source_thread_id'].strip():return False
        received=datetime.fromisoformat(receipt['received_at'])   # the event is read here: confirmed() is also called while the stages are being checked
        ev=next(x for x in manifest.get('stages',[]) if isinstance(x,dict) and x.get('name')==a.get('event'))
        if received.tzinfo is None or not datetime.fromisoformat(ev['started_at'])<=received<=datetime.fromisoformat(ev['finished_at']):return False
        if not any(e.get('kind')=='user_reported' and e.get('source')==v['source'] and e.get('source_sha256')==v['source_sha256'] for e in manifest.get('evidence',[])):return False
        if not (digest(target)==v['target_sha256']==a['docs'].get(target_rel)):return False
        lq=safe_path(LAYER,'Context/aipm_changes/list_'+str(v.get('list_digest'))+'.yaml')
        if not lq.is_file():return False
        listed={x.get('id') for x in (load(lq) or {}).get('entries') or [] if isinstance(x,dict)}
        ids=next(x.get('change_ids') for x in a['changed'] if isinstance(x,dict) and x.get('path')==target_rel)
        if not ids or not set(ids)<=listed:return False
        for i in ids:
            pq=safe_path(LAYER,'Context/aipm_changes/'+str(i)+'.yaml')
            if not pq.is_file() or ((load(pq) or {}).get('judgment') or {}).get('state')!='adopted':return False
        return True
    def confirmed(key):
        r=responses.get(key,{})
        if not isinstance(r,dict): return False
        try:
            a=version_of(r['target_path'][len(PKG)+1:]) if isinstance(r.get('target_path'),str) and r['target_path'].startswith(PKG+'/') else None
            if a is not None:return confirmed_version(key,r,a,r['target_path'][len(PKG)+1:],safe_path(LAYER,r['target_path']))
        except (KeyError,TypeError,ValueError,StopIteration,AttributeError): return False
        try:
            q=safe_path(LAYER,r['source'])
            target=safe_path(LAYER,r['target_path'])
            prefix=PKG+'/'
            if not r['source'].startswith('Context/') or not r['target_path'].startswith(prefix) or not q.is_file() or not target.is_file():return False
            target_rel=r['target_path'][len(prefix):]
            entry=expected.get(target_rel)
            target_stage='init' if entry and entry.get('side') else ({'01':'persona','02':'problem','03':'solution','04':'story'}.get(entry['path'][:2]) if entry else None)
            if key=='validation' and target_rel=='validation_checkpoint.yaml':
                question={k:v for k,v in validation.items() if k!='actual_new_user_response'}
                if load(target)!=question:return False
                target_stage='validation'
            if target_stage!=key:return False
            receipt=load(q)
            if not isinstance(receipt,dict) or receipt.get('kind')!='user_reported' or receipt.get('actor')!='actual_user' or receipt.get('origin')!='actual_user_reply':return False
            for field,value in [('scope_id',contract['scope_id']),('stage',key),('answer',r.get('answer')),('target_sha256',r.get('target_sha256'))]:
                if receipt.get(field)!=value:return False
            if receipt.get('target_path')!=r['target_path'] and not moved_receipt(receipt,r['target_path']):return False
            if not isinstance(receipt.get('question_id'),str) or not receipt['question_id'].strip() or not isinstance(receipt.get('source_thread_id'),str) or not receipt['source_thread_id'].strip():return False
            received=datetime.fromisoformat(receipt['received_at'])
            event=next(s for s in manifest.get('stages',[]) if s.get('name')==('gaps' if batch else key))
            # the reply must come after the target was written, by the RECORDED write time
            # (git keeps no mtime): the later of the bind's target_written_ns and the target record's generated_mtime_ns, else only the
            # stage time and the target_sha256 binding below (older receipts on validation_checkpoint.yaml)
            rec=next((x for x in manifest.get('records',[]) if isinstance(x,dict) and x.get('path')==target_rel),{})
            if 'target_written_ns' in r and type(r['target_written_ns']) is not int:return False
            written=[t for t in (r.get('target_written_ns'),rec.get('generated_mtime_ns')) if type(t) is int]
            if received.tzinfo is None or (written and received.timestamp()*1e9<max(written)) or received>datetime.fromisoformat(event['finished_at']):return False
            if not any(e.get('kind')=='user_reported' and e.get('source')==r['source'] and e.get('source_sha256')==r.get('source_sha256') for e in manifest.get('evidence',[])):return False
            now_sha=digest(target)
            # an init reply was given on project_init.yaml before a recorded nested_v1 move rewrote it (program_id, roots);
            # the receipt, the manifest and checkpoint_targets keep the bytes before, and the file must be exactly the bytes after
            rewritten=key=='init' and any(received<at and path==target_rel and before==r.get('target_sha256') and after==now_sha for at,path,before,after in init_rewrites)
            return digest(q)==r.get('source_sha256') and isinstance(r.get('answer'),str) and bool(r['answer'].strip()) and (now_sha==r.get('target_sha256') or rewritten) and r.get('target_sha256')==manifest.get('checkpoint_targets',{}).get(key)
        except (KeyError,TypeError,ValueError,StopIteration,AttributeError): return False
    if validation.get('actual_new_user_response') is not None and (not confirmed('validation') or validation.get('actual_new_user_response')!=responses.get('validation',{}).get('answer')):
        err('E_CHECKPOINT','validation.actual_new_user_response','actual response artifact/target binding missing')
    stages=manifest.get('stages',[])
    if not isinstance(stages,list):err('E_ORDER','stages','not list');stages=[]
    want=list(contract['course'][:-1] if phase=='prearchive' else contract['course'])
    first=stages[0] if stages and isinstance(stages[0],dict) else {}
    if batch and first.get('name')=='init' and first.get('origin')=='mode_init' and want[:2]==['ingest','init']:
        # init ran in Collection Phase 7.5 before ingestion; accept that true order only when it matches the Layer's mode_init
        mi=load(safe_path(LAYER,'intent.yaml')).get('mode_init') or {}
        if not isinstance(mi,dict) or mi.get('state')!='done' or str(mi.get('done_at'))!=str(first.get('finished_at')) or str(first.get('started_at'))!=str(first.get('finished_at')) or first.get('mode_init_outputs')!=mi.get('outputs'):err('E_ORDER','stages.init','origin mode_init does not match intent mode_init (done_at, no invented start time, outputs)')
        want=['init','ingest']+want[2:]
    applies=manifest.get('applies')   # a box with versions; each apply version adds the event apply_v<N> at the end
    apply_events=['apply_v'+str(a.get('version')) for a in applies if isinstance(a,dict) and a.get('kind')=='apply'] if isinstance(applies,list) and phase=='final' else []
    want+=apply_events
    if [s.get('name') for s in stages if isinstance(s,dict)]!=want:err('E_ORDER','stages','incorrect required stage order')
    for s in stages:
        if isinstance(s,dict) and s.get('name') in apply_events and (s.get('checkpoint_actor'),s.get('checkpoint_status'))!=('auto_decision','accepted_local'):
            err('E_APPLY','stages.'+str(s.get('name')),'an apply event is auto_decision / accepted_local (the person\'s answer is bound to the version receipts)')
    intervals={};previous=None
    for event in stages:
        if not isinstance(event,dict):err('E_ORDER','stages','invalid event');continue
        try:
            start=datetime.fromisoformat(event['started_at']);end=datetime.fromisoformat(event['finished_at'])
            if start.tzinfo is None or end.tzinfo is None or start>end or (previous is not None and start<previous) or (batch and end>datetime.now(timezone.utc)):raise ValueError('non-monotonic/naive/future event')
            previous=end;intervals[event['name']]=(int(start.timestamp()*1e9),int(end.timestamp()*1e9))
            if event.get('checkpoint_actor') not in ['auto_decision','actual_user'] or event.get('checkpoint_status') not in ['accepted_local','confirmed_actual']:raise ValueError('missing checkpoint classification')
            if not isinstance(event.get('evidence_refs'),list):raise ValueError('missing evidence refs')
            if not ((event.get('checkpoint_actor')=='auto_decision' and event.get('checkpoint_status')=='accepted_local') or (event.get('checkpoint_actor')=='actual_user' and event.get('checkpoint_status')=='confirmed_actual' and confirmed(event['name']))):
                err('E_CHECKPOINT', 'stages.'+event['name'], 'actual user checkpoint lacks actual response')
        except Exception as ex:err('E_ORDER','stages',str(ex))
    snaps=manifest.get('source_snapshots',{})   # sources inside the package are checked against their copy
    if not isinstance(snaps,dict):err('E_COURSE','source_snapshots','expected map');snaps={}
    snap_pre=PKG+'/source_snapshots/'
    reads_by_id={r['id']:r for r in (manifest.get('source_reads') or []) if isinstance(r,dict) and isinstance(r.get('id'),str)}
    valid_snaps={}
    ext_log={x['id']:x for x in (manifest.get('source_snapshot_log') or []) if isinstance(x,dict) and isinstance(x.get('id'),str)}
    ev_by_id={x['id']:x for x in (manifest.get('evidence') or []) if isinstance(x,dict) and isinstance(x.get('id'),str)}
    def external_snapshot(sid,rel):
        """the archive-time bytes of a source outside the package (a layer source read, or the evidence of
        that id) that changed after archive, placed by snapshot-sources: <PKG>/source_snapshots/external/<path>, recorded in
        source_snapshot_log with the same path and the recorded sha256. The copy's bytes are checked like the source."""
        x=ext_log.get(sid)
        r=reads_by_id.get(sid);e=ev_by_id.get(sid)
        if r is not None:path,want=(r.get('path') if r.get('domain')=='layer' else None),r.get('sha256')
        elif e is not None and e.get('kind')!='user_reported':path,want=e.get('source'),e.get('source_sha256')   # receipts are never copied
        else:return False
        return (isinstance(x,dict) and isinstance(path,str) and not path.startswith((PKG+'/','method_source:')) and rel==snap_pre+'external/'+path
                and x.get('path')==path and x.get('sha256')==want and isinstance(want,str))
    for sid,rel in snaps.items():   # a copy is honoured only for a read package-internal source that it mirrors
        r=reads_by_id.get(sid,{});path=str(r.get('path',''))
        if r.get('domain')=='layer' and path.startswith(PKG+'/') and rel==snap_pre+path[len(PKG+'/'):]:valid_snaps[sid]=rel
        elif r.get('domain')=='layer' and any(nested for _,nested in migrations) and path.startswith(LEGACY_ROOT+'/') and rel==snap_pre+path[len(LEGACY_ROOT)+1:]:valid_snaps[sid]=rel   # a source read from inside a nested_v1 box keeps its old path (bound by the input packet) and is read from its moved copy
        elif external_snapshot(sid,rel):valid_snaps[sid]=rel
        else:err('E_COURSE','source_snapshots.'+str(sid),'snapshot does not mirror a package-internal source read')
    def checked(src,sid):
        return valid_snaps.get(sid,src)
    evidence=manifest.get('evidence',[]); evidence_ids=set()
    if not isinstance(evidence,list):err('E_EVIDENCE','evidence','not list');evidence=[]
    for e in evidence:
        if not isinstance(e,dict):err('E_EVIDENCE','evidence','invalid entry');continue
        eid=e.get('id')
        if not isinstance(eid,str) or not eid or eid in evidence_ids:err('E_EVIDENCE','evidence','missing/duplicate evidence ID')
        evidence_ids.add(eid)
        if e.get('kind') not in contract['additional_records']['required_evidence_labels'] or not e.get('scope'):err('E_EVIDENCE',str(eid),'missing label/scope')
        src=e.get('source','')
        try: q=input_path(LAYER,checked(src,eid)) if batch else safe_path(LAYER,checked(src,eid))   # the legacy course has only external copies in valid_snaps
        except (TypeError,ValueError): err('E_EVIDENCE',str(eid),'unsafe source'); continue
        if Path(src).is_absolute() or '..' in Path(src).parts or (not batch and not q.resolve().is_relative_to(LAYER.resolve())) or not q.is_file():err('E_EVIDENCE',str(eid),'unresolved allowed source')
        elif digest(q)!=e.get('source_sha256') and not (not batch and any(src==PKG+'/'+path and e.get('source_sha256')==before and digest(q)==after for _,path,before,after in init_rewrites)):err('E_EVIDENCE',str(eid),'source hash mismatch')   # an evidence on project_init.yaml rewritten by a recorded nested_v1 move
    def refs(xs,known,loc):
        if not isinstance(xs,list):err('E_REF',loc,'references must be list');return
        for x in xs:
            if x not in known:err('E_REF',loc,'unresolved '+str(x))
    for s in stages:
        if isinstance(s,dict):refs(s.get('evidence_refs'),evidence_ids,'stages.'+str(s.get('name')))
    records=manifest.get('records',[]);seen=set()
    shared_archive = None
    if shared and phase=='final':
        try:
            from shared_stock import verify_archive
            shared_archive=verify_archive(LAYER,stock_runtime)
        except Exception as ex:err('E_ARCHIVE','shared Stock',str(ex))
    if not isinstance(records,list):err('E_MANIFEST','records','not list');records=[]
    business_target=None   # box_root_v1 archived under a business project: Stock/programs/<program>/projects/<business>/<project>
    # Offline: archive_target is checked against this package (program, project, folder name), not against the Registry.
    # Which business project it names is guaranteed by archive (read from the Registry at that time), not by final.
    if box_root and 'archive_target' in manifest:
        at=manifest['archive_target'];b=contract['bindings']
        keys=('scope_id','workspace_id','program_uid','business_uid','business_display_name','business_name','target_rel','resolved_at','source')
        plain=isinstance(at,dict) and at.get('source')=='config'   # business none / where layer (no Registry, no business fields)
        if plain:
            empty=('workspace_id','program_uid','business_uid','business_display_name','business_name')
            want={LAYER_ARCHIVE+'/'+b['project_id'],STOCK_PROGRAMS+'/'+b['program_id']+'/projects/'+b['project_id']}
            if set(at)!=set(keys) or any(not isinstance(at[k],str) for k in keys) or any(at[k] for k in empty) or not at['resolved_at'] or at['scope_id']!=str(contract.get('scope_id') or '') or at['target_rel'] not in want:
                err('E_ARCHIVE','archive_target','archive_target (source config) must name Documents/aipm_archive/<project> or Stock/programs/<program>/projects/<project> of this package, with empty business fields')
            elif at['target_rel'].startswith(STOCK_PROGRAMS+'/') and archive_settings(LAYER,stock_root)['business']!='none':
                # a Stock copy without its business project is valid only while aipm_archive.business is none
                err('E_ARCHIVE','archive_target','archive_target (source config) skips the business project, but aipm_archive.business is registry; set aipm_archive.business back to none for this box (move-archive cannot move a box with versions)')
            else:business_target=at['target_rel']
        elif not isinstance(at,dict) or set(at)!=set(keys) or any(not isinstance(at[k],str) or not at[k] for k in keys):err('E_ARCHIVE','archive_target','archive_target must hold exactly '+', '.join(keys))
        else:
            try:folder=business_folder(at['business_display_name'])   # the folder name follows from the recorded display name
            except ValueError as ex:folder=None;err('E_ARCHIVE','archive_target',str(ex))
            if folder is not None and (folder!=at['business_name'] or at['target_rel']!=STOCK_PROGRAMS+'/'+b['program_id']+'/projects/'+folder+'/'+b['project_id'] or at['scope_id']!=contract['scope_id'] or at['source']!='registry_read_only'):
                err('E_ARCHIVE','archive_target','archive_target does not name Stock/programs/<program>/projects/<business>/<project> of this package')
            elif folder is not None:business_target=at['target_rel']
    ap_=manifest.get('applies') if isinstance(manifest.get('applies'),list) else []
    unpushed=ap_[-1] if ap_ and isinstance(ap_[-1],dict) and ap_[-1].get('pushed') is False else None
    pushed_docs=next((a.get('docs') or {} for a in reversed(ap_) if isinstance(a,dict) and a.get('pushed') is True),{})
    unpushed_diff=[]
    fields=['path','source_step','template_sha256','version','branch','stage','status','requires_human','human_state','inputs','evidence_refs','decision','sha256','generated_mtime_ns','archive_path','archive_sha256']
    for r in records:
        if not isinstance(r,dict):err('E_MANIFEST','records','invalid entry');continue
        rel=r.get('path','');q=safe(rel)
        if any(k not in r for k in fields):err('E_MANIFEST',rel,'required record key missing')
        if rel in seen or rel not in expected:err('E_MANIFEST',rel,'duplicate/unknown record path')
        seen.add(rel)
        e=expected.get(rel)
        if e and (r.get('source_step')!=e['step'] or r.get('template_sha256')!=e['template_sha256']):err('E_TEMPLATE',rel,'incorrect source step/template')
        if not isinstance(r.get('version'),str) or not r['version'].strip() or r.get('branch')!=manifest.get('branch') or not isinstance(r.get('decision'),str) or not r.get('decision'):err('E_MANIFEST',rel,'invalid version/branch/decision')
        refs(r.get('evidence_refs'),evidence_ids,rel+'.evidence_refs')
        inputs=r.get('inputs')
        if not isinstance(inputs,list) or not inputs:err('E_MANIFEST',rel,'missing used inputs')
        else:
            for inp in inputs:
                try: z=input_path(LAYER,inp) if batch else safe_path(LAYER,inp)
                except (TypeError,ValueError): err('E_MANIFEST',rel,'unsafe input'); continue
                if Path(inp).is_absolute() or '..' in Path(inp).parts or (not batch and not z.resolve().is_relative_to(LAYER.resolve())) or not z.is_file():err('E_MANIFEST',rel,'unresolved input '+str(inp))
        human=r.get('requires_human');hstate=r.get('human_state')
        if not ((human is False and hstate=='not_required') or (human is True and hstate=='confirmed_actual' and confirmed(r.get('stage')))):
            err('E_CHECKPOINT',rel,'required actual response unresolved or state invalid')
        required_status='validated_local_final' if e and e.get('side') in ['flow','stock_project'] else ('generated' if phase=='prearchive' else 'archived_local_final')
        if r.get('status')!=required_status:err('E_STATE',rel,'not a locally final document')
        wanted_stage='init' if e and e.get('side') else ({'01':'persona','02':'problem','03':'solution','04':'story'}.get(e['path'][:2]) if e else None)
        if r.get('stage')!=wanted_stage or (not batch and r.get('stage') not in intervals):
            err('E_ORDER',rel,'source step not bound to its required stage interval')
        if q and q.is_file() and rel in actual:
            if digest(q)!=r.get('sha256'):err('E_HASH',rel,'content hash mismatch')
            if q.stat().st_mtime_ns!=r.get('applied_mtime_ns' if 'applied_in' in r else 'generated_mtime_ns'):mtime_drift.append(rel)   # git keeps no mtime; the bytes are bound by sha256 (C2)
        if 'applied_in' in r:   # a document changed by apply version N was written in its apply_v<N> event
            w=intervals.get('apply_v'+str(r.get('applied_in')))
            if type(r.get('applied_mtime_ns')) is not int or not w or not w[0]<=r['applied_mtime_ns']<=w[1]:err('E_APPLY',rel,'applied time not in its apply_v event')
        recorded=r.get('generated_mtime_ns')   # C3: the RECORDED generation time lies in its stage (legacy course); the file mtime is not used
        if not batch and (type(recorded) is not int or (r.get('stage') in intervals and not intervals[r['stage']][0]<=recorded<=intervals[r['stage']][1])):err('E_ORDER',rel,'file not generated within declared stage')
        archive=r.get('archive_path')
        if e and e.get('side') not in ['flow','stock_project'] and phase=='final':
            if shared:
                if shared_archive:
                    receipt=shared_archive['receipt']
                    if archive!='originals/'+receipt['source_id']+'/'+rel or r.get('archive_sha256')!=shared_archive['original_hashes'].get(rel):err('E_ARCHIVE',rel,'shared original counterpart mismatch')
                continue
            if box_root:
                target=business_target or contract.get('stock_target_rel')   # a where: layer box has no program, only its archive_target
                if not target:err('E_ARCHIVE',rel,'no Stock target; give aipm.program_id (an existing Stock/programs folder)');continue
                if business_target is not None:target=business_target   # archived under its business project (no archive_target = the earlier projects/<project>/ copies)
                elif 'archive_target' in manifest:continue   # a broken archive_target was already reported once
                expected_archive=target+'/documents/'+e['path']
                if archive!=expected_archive:err('E_ARCHIVE',rel,'incorrect Stock counterpart')
                aq=stock_safe(archive) if archive==expected_archive else None
            else:
                expected_archive=stock+'/documents/'+e['path']
                if archive!=expected_archive:err('E_ARCHIVE',rel,'incorrect Stock counterpart')
                aq=safe(archive or '')
            if aq and not aq.is_file():err('E_ARCHIVE',rel,'archive missing')
            elif aq and q and rel in actual and unpushed is not None:   # applied but not pushed: the Stock holds the last pushed version
                if digest(aq)!=r.get('archive_sha256') or r.get('archive_sha256')!=pushed_docs.get(rel):err('E_ARCHIVE',rel,'Stock differs from the last pushed version')
                elif aq.read_bytes()!=q.read_bytes():unpushed_diff.append(rel)
            elif aq and q and rel in actual and (aq.read_bytes()!=q.read_bytes() or digest(aq)!=r.get('archive_sha256')):err('E_ARCHIVE',rel,'Stock/Flow bytes or hash mismatch')
        elif archive is not None:err('E_ARCHIVE',rel,'Init/README should not have a second archive')
    if set(expected)!=seen:err('E_MANIFEST','records','required document records missing')
    if 'applies' in manifest:
        log_dir=business_target or (contract.get('stock_target_rel') if box_root else None)
        def read_log():
            q=stock_safe(log_dir+'/apply_log.yaml') if log_dir else None
            return load(q) if q is not None and q.is_file() else None
        check_applies(manifest,records,phase,err,read_log)
    if unpushed is not None and unpushed_diff:warn('W_UNPUSHED','applies','version '+str(unpushed.get('version'))+' is applied to the box but not pushed to the Stock ('+str(len(unpushed_diff))+' document(s)); push it (apply --push) or revert it (apply --revert-unpushed)')
    if batch:
        try:
            extension=course_registry()['manifest_extension']
            for key in extension['required']:
                if key not in manifest:err('E_COURSE',key,'local course field missing')
            if manifest.get('course_contract_version')!=contract['course_contract_version'] or manifest.get('course_contract_sha256')!=contract['course_contract_sha256']:
                err('E_COURSE','version','local course version/hash mismatch')
            packet=manifest.get('input_packet',{})
            if digest(safe_path(LAYER,packet.get('path')))!=packet.get('sha256'):err('E_COURSE','input_packet','input packet changed or missing hash')
            origin=load(safe_path(LAYER,packet.get('path')))
            if not isinstance(origin,dict) or origin.get('version')!=1 or origin.get('scope_id')!=contract['scope_id']:raise ValueError('input packet scope/version mismatch')
            if manifest.get('gaps')!=origin.get('gaps',[]) or manifest.get('claims')!=origin.get('claims',[]):err('E_COURSE','input_packet','original gaps/claims must be preserved; actual replies belong to checkpoint receipts')
            original_sources=origin.get('sources',[])
            original_ids={x['id']:x for x in original_sources}
            if len(original_ids)!=len(original_sources):raise ValueError('duplicate original source ID')
            reads=manifest.get('source_reads');byid={}
            if not isinstance(reads,list) or not reads:raise ValueError('actual source reads required')
            for read in reads:
                if not isinstance(read,dict) or not isinstance(read.get('id'),str) or not read['id'] or read['id'] in byid:raise ValueError('unique source read ID required')
                byid[read['id']]=read
                src=source_path(LAYER,read.get('domain'),checked(read.get('path'),read['id']))
                observed=datetime.fromisoformat(read['read_at']);window=intervals.get('ingest')
                if observed.tzinfo is None or observed>datetime.now(timezone.utc) or not window or not window[0]<=int(observed.timestamp()*1e9)<=window[1]:
                    err('E_COURSE',read['id'],'read time not in actual ingestion interval')
                if type(read.get('source_mtime_ns')) is not int or digest(src)!=read.get('sha256'):
                    err('E_COURSE',read['id'],'source mtime/hash changed or fabricated')
                elif src.stat().st_mtime_ns!=read['source_mtime_ns']:mtime_drift.append(read['id'])   # sha256 binds the source (C5)
                ev=next((e for e in evidence if e.get('id')==read['id']),{})
                wanted=('method_source:' if read['domain']=='method_source' else '')+read['path']
                if ev.get('source')!=wanted or ev.get('source_sha256')!=read.get('sha256'):err('E_COURSE',read['id'],'source/evidence binding mismatch')
            if set(byid)!=set(original_ids):err('E_COURSE','source_reads','source set differs from original packet')
            for key,read in byid.items():
                src=original_ids.get(key,{})
                if any(read.get(field)!=src.get(field) for field in ['domain','path','sha256']):err('E_COURSE',key,'source declaration differs from original packet')
            for r in records:
                if not isinstance(r,dict):continue
                originally_reused=origin.get('reuse',{}).get(r.get('source_step'))
                if r.get('reused_from')!=originally_reused or r.get('generation_kind')!=('reused' if originally_reused else 'generated'):err('E_COURSE',r.get('path'),'generation/reuse differs from original packet')
                if any(k not in r for k in extension['record_required']):err('E_COURSE',r.get('path'),'generation record missing')
                refs(r.get('source_ids'),set(byid),str(r.get('path'))+'.source_ids')
                if not r.get('source_ids'):err('E_COURSE',r.get('path'),'used source IDs required')
                interval=intervals.get(r.get('generation_event'));q=safe(r.get('path',''))
                if r.get('generation_event')!='batch' or not interval:err('E_COURSE',r.get('path'),'generation event missing')
                if r.get('generation_kind')=='generated':
                    recorded=r.get('generated_mtime_ns')   # the recorded generation time must lie in the batch (C4); the file mtime is not used
                    if r.get('reused_from') is not None or (interval and (type(recorded) is not int or not interval[0]<=recorded<=interval[1])):err('E_COURSE',r.get('path'),'generated time/reuse declaration mismatch')
                elif r.get('generation_kind')=='reused':
                    source=byid.get(r.get('reused_from'))
                    if not source or r.get('source_ids')!=[r.get('reused_from')]:err('E_COURSE',r.get('path'),'reuse needs its actual source binding')
                    elif q and q.is_file() and ((ap_[0].get('docs') or {}).get(r.get('path')) if 'applied_in' in r and ap_ and isinstance(ap_[0],dict) else digest(q))!=source['sha256']:err('E_COURSE',r.get('path'),'reuse bytes/mtime do not match source')   # the bytes decide reuse (C6); a document changed by apply: its first version's bytes
                else:err('E_COURSE',r.get('path'),'unknown generation kind')
            decisions=manifest.get('decisions')
            if not isinstance(decisions,dict) or set(decisions)!=set(course_registry()['human_decisions']):raise ValueError('required decisions missing')
            original_decisions=origin.get('decisions',{})
            if set(original_decisions)!=set(decisions):err('E_COURSE','decisions','decision keys differ from original packet')
            for key,d in decisions.items():
                original=original_decisions.get(key,{})
                if not isinstance(d,dict) or not d.get('reason') or not d.get('source_ids'):raise ValueError('decision reason/source required')
                refs(d['source_ids'],set(byid),'decisions.'+key)
                if {k:v for k,v in d.items() if k!='state'}!={k:v for k,v in original.items() if k!='state'}:err('E_COURSE',key,'original decision reason/sources/question must be preserved')
                if d.get('state')!=original.get('state') and d.get('state')!='confirmed_actual':err('E_COURSE',key,'original pending/material decision cannot be downgraded')
                if d.get('state')=='confirmed_actual':
                    if not confirmed(key):err('E_CHECKPOINT',key,'actual decision lacks actual response receipt')
                elif d.get('state')!='not_required' or d.get('scope')!='reversible_draft_only':err('E_CHECKPOINT',key,'material decision pending or unsupported no-question scope')
            gaps=manifest.get('gaps')
            if not isinstance(gaps,list):raise ValueError('gaps must be list')
            for gap in gaps:
                if not isinstance(gap,dict) or gap.get('kind')!='unknown' or type(gap.get('requires_user')) is not bool or not gap.get('reason'):raise ValueError('unknown gap classification required')
                if gap['requires_user'] and not confirmed(gap.get('decision_key')):err('E_CHECKPOINT','gaps','material question unresolved')
                problem=prior_answer_problem(LAYER,gap)   # shape/answer/source only; never a receipt
                if problem:err('E_COURSE','gaps',problem)
            claims=manifest.get('claims')
            if not isinstance(claims,list):raise ValueError('claims must be list')
            for item in claims:
                if not isinstance(item,dict) or item.get('kind') not in ['observed','user_reported','hypothesis','inference','unknown']:raise ValueError('claim classification missing')
                refs(item.get('source_ids'),set(byid),'claims')
                if item['kind'] in ['observed','user_reported'] and not item.get('source_ids'):err('E_EVIDENCE','claims','factual claim needs actual source')
                if item['kind']=='user_reported' and not confirmed(item.get('decision_key')):err('E_CHECKPOINT','claims','unverified actual human claim')
        except (KeyError,ValueError,TypeError,AttributeError,OSError) as ex:err('E_COURSE','manifest',str(ex))
    def get(step,key):
        data=docs.get(step,{})
        return data.get(key,{}) if isinstance(data,dict) else {}
    # Semantic references, safe even when a schema fixture is malformed.
    try:
        exp=get('generate_experience_yaml','experience_map');persona=get('generate_experience_yaml','persona');pid=persona['id']
        if pid!=contract['bindings']['persona_id']:err('E_REF','persona_id','document persona differs from selected binding')
        phases=exp['phases'];phids=[x['id'] for x in phases];actions=[a['id'] for x in phases for a in x['actions']]
        prob=get('export_problem_map_yaml','problem_map');cp=get('export_customer_problem_map_yaml','customer_problem_map');sol=get('export_solution_map_yaml','solution_map');st=get('export_story_map_yaml','story_map')
        prids=[x['id'] for x in prob['problems']];slids=[x['id'] for x in sol['phases'] for x in x['solutions']];stids=[x['id'] for x in st['stories']]
        for kind,ids in [('P',[pid]),('PH',phids),('A',actions),('PR',prids),('SL',slids),('ST',stids)]:
            if len(set(ids))!=len(ids) or any(not re.fullmatch(kind+r'\d+',x) for x in ids):err('E_ID',kind,'duplicate/noncanonical IDs')
        for item in [prob,cp,sol,st]:
            if item['persona_ref']!=pid:err('E_REF','persona_ref','unresolved '+item['persona_ref'])
        if cp['problems']!=prob['problems']:err('E_REF','customer_problem_map','problem maps disagree')
        for x in prob['problems']:refs(x['linked_actions'],actions,x['id']);refs(x['occurs_in_phases'],phids,x['id'])
        for x in cp['phases']:
            refs([x['id']],phids,'customer phases')
            for a in x['actions']:refs([a['id']],actions,'customer action');refs(a['issues'],prids,'customer issues')
        refs(sol['problems'],prids,'solution problems')
        for ph in sol['phases']:
            refs([ph['id']],phids,'solution phase')
            for x in ph['solutions']:
                refs(x['links'],actions+prids,x['id'])
                if not set(x['links'])&set(actions) or not set(x['links'])&set(prids):err('E_REF',x['id'],'action/problem links required')
        refs(st['problem_refs'],prids,'story problems')
        for x in st['stories']:
            refs(x['links'],actions+prids+slids,x['id'])
            if not re.search(r'As .+I want .+So that .+',x['summary']):err('E_SCHEMA',x['id'],'As/I want/So that required')
        for link in st['links']:
            chain=link['chain']
            if len(chain)!=4:err('E_REF','chain','must contain A PR SL ST')
            else:
                for value,known in zip(chain,[actions,prids,slids,stids]):refs([value],known,'chain')
                bystory={x['id']:x for x in st['stories']};bysol={x['id']:x for ph in sol['phases'] for x in ph['solutions']};bypr={x['id']:x for x in prob['problems']}
                if chain[3] in bystory and not set(chain[:3])<=set(bystory[chain[3]]['links']):err('E_REF','chain','story links disagree')
                if chain[2] in bysol and not {chain[0],chain[1]}<=set(bysol[chain[2]]['links']):err('E_REF','chain','solution links disagree')
                if chain[1] in bypr and chain[0] not in bypr[chain[1]]['linked_actions']:err('E_REF','chain','problem/action disagree')
        releases={x['name']:x['includes'] for x in st['releases']}
        for x in st['releases']:refs(x['includes'],stids,'release')
        for x in st['stories']:
            if x['id'] not in releases.get(x['release'],[]):err('E_REF',x['id'],'release mapping mismatch')
        integrated=get('generate_integrated_experience_map','integrated_experience_map')
        for x in integrated['personas'].values():refs([x['id']],[pid],'integrated persona')
        for x in integrated['integrated_phases']:
            if set(x['persona_mapping'])!={pid}:err('E_REF','integrated phases','persona mapping mismatch')
            for ref in x['persona_mapping'].values():
                match=re.fullmatch(r'(PH\d+): (.+)',ref)
                if match is None:err('E_REF','integrated phases','invalid phase mapping '+ref)
                else:
                    refs([match.group(1)],phids,'integrated phases')
                    names={ph['id']:ph['name'] for ph in phases}
                    if names.get(match.group(1))!=match.group(2):err('E_REF','integrated phases','phase name disagrees')
        viewer=get('export_viewer_integrated_yaml_final','integrated_story_map');activities=[x['id'] for x in viewer['story_map_structure']['activities']];backs=[x['id'] for x in viewer['story_map_structure']['backbones']]
        for x in viewer['story_map_structure']['backbones']:refs([x['activity_id']],activities,'backbone')
        refs(viewer['display_order']['backbones'],backs,'display backbones')
        vstories=[x for value in viewer['personas_stories'].values() for x in value['stories']]+viewer['cross_persona_stories'];vids=[x['id'] for x in vstories]
        refs(list(viewer['personas_stories']),[pid],'viewer personas')
        if len(set(vids))!=len(vids):err('E_ID','viewer stories','duplicate IDs')
        for x in vstories:
            refs([x['backbone_id']],backs,x['id']);refs([x['version']],viewer['version_definitions']['order'],x['id'])
            if viewer['story_mapping'].get(x['id'],{}).get('backbone_id')!=x['backbone_id']:err('E_REF',x['id'],'Viewer mapping inconsistent')
        if contract['id_mapping']['trace_story'] not in stids or contract['id_mapping']['viewer_story'] not in vids:err('E_REF','id_mapping','trace/Viewer target missing')
        # Diagram IDs cannot introduce a persona/phase/action/problem/solution/story outside YAML.
        known=[pid]+phids+actions+prids+slids+stids
        for rel,q in actual.items():
            if expected[rel]['kind']=='mermaid':
                blocks=re.findall(r'```mermaid\s*\n(.*?)\n```',q.read_text(),re.S)
                graph=blocks[0] if len(blocks)==1 else ''
                graph='\n'.join(line for line in graph.splitlines() if not re.match(r'\s*(?:%%|class\b|classDef\b|style\b)',line))
                graph=re.sub(r'"(?:[^"\\]|\\.)*"','',graph)
                graph=re.sub(r'\[[^\]]*\]|\([^)]*\)|\{[^}]*\}','',graph)
                graph=re.sub(r'\|[^|]*\|','',graph)
                graph=re.sub(r'--\s+[^\n]*?\s+-->', '-->', graph)
                graph=re.sub(r'-\.\s+[^\n]*?\s+\.->', '-.->', graph)
                graph=re.sub(r'==\s+[^\n]*?\s+==>', '==>', graph)
                graph=re.sub(r':::[A-Za-z_][A-Za-z0-9_-]*','',graph)
                present=set(re.findall(r'\b((?:PH|PR|SL|ST|A|P)\d+)\b(?=\s*(?:[;\n]|$|--|==|-\.|~~~|<))',graph));refs(sorted(present),known,rel)
                need={'generate_experience_mermaid':[pid]+phids+actions,'export_customer_problem_map_mermaid':phids+actions+prids,'export_problem_map_mermaid':phids+actions+prids,'export_solution_map_mermaid':actions+prids+slids,'export_story_map_mermaid':actions+prids+slids+stids}[expected[rel]['step']]
                if not set(need)<=present:err('E_DIAGRAM',rel,'required graph IDs missing')
        init=docs.get('write_init_yaml',{})
        for field in ['program_id','project_id','participant_name','flow_dir']:
            if init.get(field)!=contract['bindings'][field]:err('E_REF','project_init.'+field,'does not match selected Project binding')
        if (init.get('flow_base'),init.get('stock_base'))!=init_roots(contract) or init.get('share_repo')!='disabled' or init.get('share_local_dir')!='disabled':err('E_BOUNDARY','project_init','wrong roots or enabled sharing')
        if not batch and validation.get('before_solution') is not True:err('E_ORDER','validation','must precede solution')
        if batch and validation.get('before_solution') is not False:err('E_ORDER','validation','batch must not fabricate before-solution validation')
        solutions=[q for rel,q in actual.items() if expected[rel]['source'].endswith('03_ソリューションマップ.md')]
        # C7: the validation stage ends before the first RECORDED solution document (legacy course); the file mtimes are not used
        solution_times=[x.get('generated_mtime_ns') for x in records if isinstance(x,dict) and x.get('path') in actual and expected.get(x.get('path'),{}).get('source','').endswith('03_ソリューションマップ.md')]
        if not batch and vpath and vpath.is_file() and solution_times and 'validation' in intervals and (not all(type(s) is int for s in solution_times) or intervals['validation'][1]>=min(solution_times)):err('E_ORDER','validation','written after solution')
        refs(validation.get('evidence_refs'),evidence_ids,'validation evidence')
        if not isinstance(validation.get('hypotheses'),list) or not validation['hypotheses']:err('E_VALIDATION','hypotheses','missing hypotheses')
        else:
            for h in validation['hypotheses']:
                if any(k not in h for k in ['id','kind','claim','method','success','falsification','result','scope']) or h.get('kind')!='hypothesis' or h.get('result') not in ['unknown','not_supported','structurally_supported']:err('E_VALIDATION','hypotheses','invalid statement/result/scope')
    except (KeyError,TypeError,AttributeError,ValueError) as ex:
        err('E_REF','semantic', 'malformed or incomplete semantic data: '+str(ex))
    if mtime_drift:warn('W_MTIME','package',str(len(mtime_drift))+' file(s) differ from the recorded mtime (a git checkout keeps none; contents are checked by sha256): '+', '.join(mtime_drift[:5]))
    issues_summary=None;reg_out={}
    if 'registers_contract_version' in contract:issues_summary=check_registers(contract,safe,validation,err,LAYER,warn,reg_out)
    if 'register_edits' in manifest:check_register_edits(manifest,contract,safe,err,warn)
    if light_kind == light.SHEETS_KIND and 'registers_contract_version' not in contract:reg_out['light_sheets_summary']=light.check(LAYER,err,warn)   # the two sheets added to an aipm Layer
    return {'pass':not errors,'scope_id':contract['scope_id'],'source_commit':contract['reviewed_commit'],'validation_phase':phase,'checked_documents':len(actual),'errors':errors,'warnings':warnings,**({'issues_summary':issues_summary} if issues_summary is not None else {}),**reg_out,'limits':['Static Markdown/Mermaid structure and references; no Viewer rendering E2E','Human understanding/new usability/general productivity not measured']}

def check_register_edits(manifest,contract,safe,err,warn):
    """E_REDIT: ① edits 1..N ② each judgement has quote, at, thread, list_digest ③ base_version is a
    version of applies (or null). W_REDIT: the registers differ from what the last edit wrote (judge / resolve / todo.move or by
    hand after it); a warning only."""
    from package import registers_contract
    edits=manifest.get('register_edits')
    if not isinstance(edits,list) or not edits:err('E_REDIT','register_edits','expected a non-empty list');return
    versions={a.get('version') for a in manifest.get('applies') or [] if isinstance(a,dict)}
    for n,x in enumerate(edits,1):
        loc='register_edits['+str(n-1)+']'
        if not isinstance(x,dict):err('E_REDIT',loc,'expected map');continue
        if x.get('edit')!=n or isinstance(x.get('edit'),bool):err('E_REDIT',loc,'edits must run 1..N without a gap')
        js=x.get('judgments')
        if not isinstance(js,list) or not js or any(not isinstance(j,dict) or any(not isinstance(j.get(k),str) or not j[k].strip() for k in ('quote','at','thread','list_digest')) for j in js):err('E_REDIT',loc,'each judgement needs quote, at, thread and list_digest')
        if not isinstance(x.get('approval_ref'),str) or not x['approval_ref'].strip():err('E_REDIT',loc,'approval_ref missing')
        if x.get('base_version') is not None and x.get('base_version') not in versions:err('E_REDIT',loc,'base_version is not a version of applies')
    last=edits[-1]
    if 'registers_contract_version' in contract and isinstance(last,dict) and isinstance(last.get('registers_sha256'),dict):
        rc=registers_contract(contract);now={}
        for k,spec in rc['files'].items():
            q=safe(spec['path'])
            now[k]=digest(q) if q is not None and q.is_file() else None
        diff=[k for k in now if last['registers_sha256'].get(k)!=now[k]]
        if diff:warn('W_REDIT','register_edits','the registers changed after edit '+str(last.get('edit'))+' outside redit (judge / resolve / todo.move or by hand): '+', '.join(diff))

def check_applies(manifest,records,phase,err,read_log=None):
    """E_APPLY (①-④) on a box with versions. ① versions 1..N without a gap, v1 register/first
    and the later ones apply ② each version's docs hold every document with an archive copy ③ the last docs = the records
    sha256 ④ changed before/after = the previous/this docs, and a document not in changed keeps its previous sha256."""
    applies=manifest.get('applies')
    if phase!='final':err('E_APPLY','applies','versions exist only after archive');return
    if not isinstance(applies,list) or not applies:err('E_APPLY','applies','expected a non-empty list');return
    archived={r['path']:r.get('sha256') for r in records if isinstance(r,dict) and r.get('archive_path') and isinstance(r.get('path'),str)}
    hexa=re.compile(r'[0-9a-f]{64}');prev=None
    for n,a in enumerate(applies,1):
        loc='applies['+str(n-1)+']'
        if not isinstance(a,dict):err('E_APPLY',loc,'expected map');prev=None;continue
        if a.get('version')!=n or isinstance(a.get('version'),bool):err('E_APPLY',loc,'versions must run 1..N without a gap')   # ①
        if a.get('kind') not in APPLY_KINDS or (n==1)!=(a.get('kind') in ('register','first')):err('E_APPLY',loc,'v1 is register/first, later versions are apply')
        if not isinstance(a.get('pushed'),bool):err('E_APPLY',loc,'pushed must be true/false')
        elif a['pushed'] is False and n!=len(applies):err('E_APPLY',loc,'only the last version may be unpushed')   # ⑤
        if a.get('kind') in ('register','first') and a.get('pushed') is not True:err('E_APPLY',loc,'a register/first version is pushed')
        if a.get('kind') in ('register','apply') and (not isinstance(a.get('approval_ref'),str) or not a['approval_ref'].strip()):err('E_APPLY',loc,'approval_ref missing')
        docs=a.get('docs')
        if not isinstance(docs,dict) or set(docs)!=set(archived) or any(not isinstance(v,str) or not hexa.fullmatch(v) for v in docs.values()):   # ②
            err('E_APPLY',loc+'.docs','docs must hold the sha256 of every document with an archive copy');prev=None;continue
        changed=a.get('changed')
        if not isinstance(changed,list):err('E_APPLY',loc+'.changed','expected list');prev=docs;continue
        if n==1:
            if changed or a.get('base_version') is not None:err('E_APPLY',loc,'v1 has no base_version and no changed documents')
        elif prev is not None:   # ④
            if a.get('base_version')!=n-1:err('E_APPLY',loc,'base_version must be the previous version')
            paths=set()
            for x in changed:
                if not isinstance(x,dict) or x.get('path') not in docs or x['path'] in paths or not isinstance(x.get('change_ids'),list) or not x['change_ids']:err('E_APPLY',loc+'.changed','each entry names one document of docs once, with its change_ids');continue
                paths.add(x['path'])
                if x.get('before')!=prev[x['path']] or x.get('after')!=docs[x['path']] or x['before']==x['after']:err('E_APPLY',loc+'.changed.'+x['path'],'before/after must be the previous/this version and differ')
            for k in set(docs)-paths:
                if docs[k]!=prev[k]:err('E_APPLY',loc+'.docs.'+k,'a document not in changed must keep its previous sha256')
        prev=docs
    last=applies[-1]
    if isinstance(last,dict) and isinstance(last.get('docs'),dict) and last['docs']!=archived:err('E_APPLY','applies','the last version docs must equal the records sha256')   # ③
    if read_log is not None:   # ⑥ the Stock apply_log holds exactly the pushed versions
        from package import LOG_KEYS
        log=read_log();want=[{k:a.get(k) for k in LOG_KEYS} for a in applies if isinstance(a,dict) and a.get('pushed') is True]
        if not isinstance(log,dict) or log.get('versions')!=want:err('E_APPLY','apply_log','the Stock apply_log must hold exactly the pushed versions')

def receipt_problem(ref,layer,contract):
    """The step 8 actual-user receipt: a Context YAML inside the Layer with the receipt labels."""
    if not isinstance(ref,str) or not ref.strip():return 'evidence_ref must be a path string'
    if layer is None:return 'layer unknown'
    try:q=safe_path(layer,ref)
    except Exception as ex:return str(ex)
    if not q.is_file():return 'receipt file missing'
    try:r=load(q)
    except Exception as ex:return 'receipt unreadable: '+str(ex)
    if not isinstance(r,dict):return 'receipt must be map'
    for k,v in (('kind','user_reported'),('actor','actual_user'),('origin','actual_user_reply')):
        if r.get(k)!=v:return 'receipt '+k+' must be '+v
    for k in ('question_id','received_at','answer'):
        if not r.get(k):return 'receipt '+k+' missing'
    if r.get('scope_id')!=contract.get('scope_id'):return 'receipt scope_id mismatch'
    return None

def list_ids(spec,safe,key):
    """ids in a registers file for reference checks; None when unreadable (the file's own check reports it)."""
    q=safe(spec['path'])
    try:data=load(q) if q is not None and q.is_file() else None
    except Exception:return None
    if not isinstance(data,dict) or not isinstance(data.get(key),list):return None
    return {r['id']:r.get('kind') for r in data[key] if isinstance(r,dict) and isinstance(r.get('id'),str)}

def knot_problems(spec,r):
    """Knot columns of one todo row (contract v3 only: the spec has a 'knot' section). Returns ([error messages],[warning messages]).
    v2 specs have no 'knot', so nothing is checked there (the 3 columns are unknown keys). Shapes are in registers_contract.yaml."""
    kn=spec.get('knot')
    if not isinstance(kn,dict):return [],[]
    errs,warns=[],[]
    if r.get('done_when') is not None and r['done_when'] not in kn['done_when']:errs.append('done_when must be one of '+', '.join(kn['done_when']))
    for col in ('updated_on','confirmed_on'):   # confirmed_on: contract v4 only (in v3 its knot section has no such key, and the column is an unknown key)
        u=r.get(col)
        if u is not None and col in kn:
            s_=u.date().isoformat() if isinstance(u,datetime) else u.isoformat() if isinstance(u,date) else u
            if not isinstance(s_,str) or not re.fullmatch(kn[col],s_) or _as_date(s_) is None or _as_date(s_).isoformat()!=s_:errs.append(col+' must be a real date YYYY-MM-DD')
    b=r.get('blocked_by')
    if b is not None:
        for v in (b if isinstance(b,list) else [b]):
            if not isinstance(v,str) or not re.fullmatch(kn['blocked_by'],v):errs.append('blocked_by must be <scope_id>/<Txxx> (e.g. L-1234/T003)')
    src=r.get('source')
    for v in (src if isinstance(src,list) else [src] if src is not None else []):
        if not isinstance(v,str):continue
        t=v.strip()
        if re.fullmatch(r'[IH]\d+',t) or any(re.fullmatch(p,t) for p in kn['source_recommended']):continue
        warns.append('source '+t+' is neither a backlog Txxx nor a Documents/ file of this Layer')
    return errs,warns

def check_list(spec,safe,err,warn=None,ids=None):
    """Minimal required-key check for issues/todo/wbs/roadmap."""
    q=safe(spec['path'])
    if q is None:return
    if not q.is_file():err('E_REGISTERS',spec['path'],'registers file missing');return
    try:data=load(q)
    except Exception as ex:err('E_REGISTERS',spec['path'],str(ex));return
    if not isinstance(data,dict) or any(k not in data for k in spec['top_required']) or not isinstance(data.get(spec['list_key']),list):err('E_REGISTERS',spec['path'],'map with '+','.join(spec['top_required'])+' required');return
    if 'charter_required' in spec:
        ch=data.get('charter')
        if not isinstance(ch,dict) or any(not isinstance(ch.get(k),list) or not ch.get(k) or any(x is None or (isinstance(x,str) and not x.strip()) for x in ch.get(k)) for k in spec['charter_required']):err('E_REGISTERS',spec['path']+'#charter','charter needs non-empty '+','.join(spec['charter_required']))
        elif warn is not None and 'completion' in spec:
            mark=spec['completion'].get('warn_unknown_owner') or spec['completion'].get('unknown_mark')   # v1 / v2
            for k in spec['charter_required']:
                if mark and all(isinstance(x,str) and mark in x for x in ch[k]):warn('W_REGISTERS',spec['path']+'#charter.'+k,'still [unknown]; not yet decided')
    seen=set()
    for i,r in enumerate(data[spec['list_key']]):
        loc=spec['path']+'#'+str(i)
        if not isinstance(r,dict):err('E_REGISTERS',loc,'row must be map');continue
        skip={k for k,sts in (spec.get('required_unless') or {}).items() if r.get('status') in sts}
        if isinstance(r.get('due'),(date,datetime)):r=dict(r,due=r['due'].isoformat())  # unquoted YAML dates are accepted
        filled=lambda k:k in r and r[k] is not None and not (isinstance(r[k],str) and not r[k].strip())
        missing=[k for k in spec['required'] if k not in skip and not filled(k)]
        if missing:err('E_REGISTERS',loc,'required key missing: '+','.join(missing));continue
        rid=r['id']
        if not isinstance(rid,str) or not re.fullmatch(spec['id_pattern'],rid):err('E_REGISTERS',loc,'id must match '+spec['id_pattern']);continue
        if rid in seen:err('E_REGISTERS',spec['path']+'#'+rid,'duplicate id')
        seen.add(rid)
        if r['status'] not in spec['status']:err('E_REGISTERS',spec['path']+'#'+rid,'unknown status')
        rl=spec['path']+'#'+rid
        if 'optional' in spec and 'completion' in spec:
            extra=[k for k in r if k not in spec['required'] and k not in spec['optional']]
            if extra:err('E_REGISTERS',rl,'unknown key: '+','.join(map(str,extra)))
            for k in ('owner','due','reason'):
                if k in r and r[k] is not None and not isinstance(r[k],str):err('E_REGISTERS',rl,k+' must be a string')
            by_reason=r.get('status') in spec['completion'].get('reason_statuses',[]) and filled('reason')
            if not ((filled('owner') and filled('due')) or by_reason):err('E_REGISTERS',rl,'not complete: needs owner and due (a date or undecided); reason is accepted only for '+'/'.join(spec['completion'].get('reason_statuses',[])))
            for k,target in (spec.get('refs') or {}).items():
                if k not in r or r[k] is None:continue
                vals=r[k] if isinstance(r[k],list) else [r[k]]
                if k in spec.get('single_refs',[]) and not isinstance(r[k],str):err('E_REGISTERS',rl,k+' must be one id');continue
                for v in vals:
                    if not isinstance(v,str):err('E_REGISTERS',rl,k+' must reference ids');continue
                    if k in spec.get('free_text_refs',[]):
                        if re.fullmatch(r'H\d+',v):pass
                        elif re.fullmatch(r'(?i)[A-Z]{1,3}-?\d+(\.\d+)*',v.strip()):
                            if warn is not None:warn('W_REGISTERS',rl,k+' looks like an id but is not one ('+v+'); write H<number> or the answer in words')
                            continue
                        else:continue
                    known=(ids or {}).get(target)
                    if known is not None and v not in known:err('E_REGISTERS',rl,k+' points to unknown id '+v);continue
                    want=(spec.get('ref_kinds') or {}).get(k)
                    if want and known is not None and known.get(v)!=want:err('E_REGISTERS',rl,k+' must point to a '+want+' hypothesis ('+v+')')
                    if k in spec.get('single_refs',[]) and v==rid:err('E_REGISTERS',rl,k+' points to itself')
            if warn is not None:
                if spec['completion'].get('warn_undecided_due') and r.get('due')=='undecided':warn('W_REGISTERS',rl,'due is undecided')
                comp=spec['completion']
                if 'warn_unknown_fields' in comp:   # v2: owner and priority (I3)
                    for f in comp['warn_unknown_fields']:
                        if r.get(f)==comp.get('unknown_mark'):warn('W_REGISTERS',rl,f+' is still [unknown]')
                elif r.get('owner')==comp.get('warn_unknown_owner'):warn('W_REGISTERS',rl,'owner is still [unknown]')
    if 'single_refs' in spec:
        parents={r['id']:r.get('parent') for r in data[spec['list_key']] if isinstance(r,dict) and isinstance(r.get('id'),str) and isinstance(r.get('parent'),str)}
        for start in parents:
            seen_p,cur=set(),start
            while cur in parents and cur not in seen_p:seen_p.add(cur);cur=parents[cur]
            if cur==start and len(seen_p)>1:err('E_REGISTERS',spec['path']+'#'+start,'parent forms a cycle')

def human_judged(spec,safe,layer,contract):
    """hypothesis ids that carry an owner/decider judgement backed by an actual-user receipt."""
    q=safe(spec['path'])
    try:data=load(q) if q is not None and q.is_file() else None
    except Exception:return set()
    out=set()
    rows=data.get('hypotheses') if isinstance(data,dict) else None
    for h in rows if isinstance(rows,list) else []:
        if not isinstance(h,dict) or not isinstance(h.get('judgements'),list):continue
        for g in h['judgements']:
            if isinstance(g,dict) and g.get('judged_by') in ('owner','decider') and receipt_problem(g.get('evidence_ref'),layer,contract) is None:out.add(h.get('id'))
    return out

def decision_problem(ref,layer,contract,decided_by=None):
    """A path given as resolution evidence must be the step 8 receipt or a labelled decision record."""
    if receipt_problem(ref,layer,contract) is None:return None
    if layer is None:return 'layer unknown'
    try:q=safe_path(layer,ref)
    except Exception as ex:return str(ex)
    if not q.is_file():return 'file missing'
    try:r=load(q)
    except Exception:return 'not a YAML record'
    if not isinstance(r,dict) or r.get('kind')!='decision_record':return 'kind must be decision_record (or an actual-user receipt)'
    if r.get('decided_by') not in ('owner','decider'):return 'decided_by must be owner or decider'
    for k in ('decided_at','decision'):
        if not r.get(k):return k+' missing'
    if r.get('scope_id')!=contract.get('scope_id'):return 'scope_id mismatch'
    if decided_by is not None and r.get('decided_by')!=decided_by:return 'decided_by differs from the record ('+str(r.get('decided_by'))+')'
    return None

def check_resolution(rc,safe,err,warn,layer,contract):
    """Issue resolution is judged apart from work completion. Returns issues_summary."""
    spec=rc['files']['issues'];res=spec['resolution'];q=safe(spec['path'])
    try:data=load(q) if q is not None and q.is_file() else None
    except Exception:return None
    if not isinstance(data,dict) or not isinstance(data.get('issues'),list):return None
    rows=[r for r in data['issues'] if isinstance(r,dict) and isinstance(r.get('id'),str)]
    judged=human_judged(rc['files']['hypotheses'],safe,layer,contract)
    known_h=list_ids(rc['files']['hypotheses'],safe,'hypotheses')
    filled=lambda r,k:k in r and r[k] is not None and not (isinstance(r[k],str) and not r[k].strip()) and r[k]!=[]
    invalid=set()
    def bad(rid):invalid.add(rid)
    for r in rows:
        rl=spec['path']+'#'+r['id'];st=r.get('status')
        e0=err
        def err(code,path,msg,_rid=r['id']):bad(_rid);e0(code,path,msg)
        if st=='resolved':
            ans=r.get('answer');ans=ans if isinstance(ans,list) else [ans]
            if known_h is not None and any(isinstance(a,str) and re.fullmatch(r'H\d+',a) and a not in known_h for a in ans):bad(r['id'])  # reported by check_list
            missing=[k for k in res['resolved_requires'] if not filled(r,k)]
            if missing:err('E_REGISTERS',rl,'resolved needs '+','.join(missing))
            if filled(r,'decided_by') and r['decided_by'] not in res['decided_by']:err('E_REGISTERS',rl,'decided_by must be owner or decider')
            refs=r.get('evidence_refs');refs=refs if isinstance(refs,list) else ([refs] if refs is not None else [])
            for ref in refs:
                if not isinstance(ref,str):err('E_REGISTERS',rl,'evidence_refs must be ids or paths');continue
                if re.fullmatch(r'H\d+',ref):
                    if ref not in judged:err('E_REGISTERS',rl,'evidence '+ref+' has no owner/decider judgement')
                else:
                    problem=decision_problem(ref,layer,contract,r.get('decided_by'))
                    if problem:err('E_REGISTERS',rl,'evidence '+ref+' is not a decision record or receipt: '+problem)
        if st in res['reason_required'] and not filled(r,'reason'):err('E_REGISTERS',rl,st+' needs reason')
        if st in res['review_at_required'] and not filled(r,'review_at'):err('E_REGISTERS',rl,st+' needs review_at')
        err=e0
    # work linked to each issue: todo.source and AI-PLC backlog task issue_id
    work={}
    tq=safe(rc['files']['todo']['path'])
    try:todo=load(tq) if tq is not None and tq.is_file() else {}
    except Exception:todo={}
    tl=todo.get('todo') if isinstance(todo,dict) else None
    for t in tl if isinstance(tl,list) else []:
        if not isinstance(t,dict):continue
        src=t.get('source');src=src if isinstance(src,list) else [src]
        for s_ in src:
            if isinstance(s_,str) and re.fullmatch(r'I\d+',s_):work.setdefault(s_,[]).append(t.get('status') in res['done_work']['todo'])
    if layer is not None:
        try:
            bq=safe_path(layer,'backlog.yaml');bl=load(bq) if bq.is_file() else {}
        except Exception:bl={}
        tasks=bl.get('tasks') if isinstance(bl,dict) else None
        for t in tasks if isinstance(tasks,list) else []:
            # 運用タスク（recurrence）は完了しないので work に入れない
            if isinstance(t,dict) and not t.get('recurrence') and isinstance(t.get('issue_id'),str):work.setdefault(t['issue_id'],[]).append(t.get('status') in res['done_work']['backlog'])
    for r in rows:
        w=work.get(r['id'])
        if warn is not None and r.get('status')=='open' and w and all(w):warn('W_REGISTERS',spec['path']+'#'+r['id'],'work done but issue still open ('+str(len(w))+' linked)')
    valid=[r for r in rows if r.get('status') in spec['status']]
    counts={k:sum(1 for r in valid if r.get('status')==k) for k in spec['status']}
    good_resolved=sum(1 for r in valid if r.get('status')=='resolved' and r['id'] not in invalid)
    countable=len(valid)-sum(counts.get(k,0) for k in res['not_counted'])
    return {**counts,'invalid_resolved':counts.get('resolved',0)-good_resolved,'total':len(valid),'countable':countable,
            'resolved_ratio':(good_resolved/countable if countable else None),'resolved_ratio_all':(good_resolved/len(valid) if valid else None)}

def _load_list(spec,safe):
    q=safe(spec['path'])
    try:data=load(q) if q is not None and q.is_file() else None
    except Exception:return None,None
    rows=data.get(spec['list_key']) if isinstance(data,dict) else None
    return data,([r for r in rows if isinstance(r,dict) and isinstance(r.get('id'),str)] if isinstance(rows,list) else None)

def _as_date(v):
    if isinstance(v,datetime):return v.date()
    if isinstance(v,date):return v
    if isinstance(v,str):
        try:return date.fromisoformat(v[:10])
        except ValueError:return None
    return None

def _period(v):
    """(start, end) of a roadmap period 'YYYY-MM-DD〜YYYY-MM-DD' (or ~); None when undecided or unreadable."""
    m=re.fullmatch(r'\s*(\d{4}-\d{2}-\d{2})\s*[〜~]\s*(\d{4}-\d{2}-\d{2})\s*',v) if isinstance(v,str) else None
    if not m:return None
    a,b=_as_date(m.group(1)),_as_date(m.group(2))
    return (a,b) if a and b and a<=b else None

def _forecast(r):
    sch=r.get('schedule');fc=sch.get('forecast') if isinstance(sch,dict) else None
    if not isinstance(fc,dict):return None,None
    read=lambda v:_as_date(v) if isinstance(v,(date,datetime)) or (isinstance(v,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',v.strip())) else None
    return read(fc.get('start')),read(fc.get('end'))

def check_schedule_warnings(rc,loaded,warn):
    """W_REGISTERS only, never changes pass; silent when a value is undecided or unreadable."""
    sw=rc.get('schedule_warnings')
    if not sw or warn is None:return
    files=rc['files'];wrows=loaded.get('wbs') or [];fc={r['id']:_forecast(r) for r in wrows}
    periods={m['id']:_period(m.get('period')) for m in loaded.get('roadmap') or []}
    for r in wrows:
        rl=files['wbs']['path']+'#'+r['id'];s,e=fc[r['id']]
        mid=r.get('milestone_id');p=periods.get(mid) if isinstance(mid,str) else None
        if 'outside_milestone' in sw and e and p and not (p[0]<=e<=p[1]):warn('W_REGISTERS',rl,'forecast.end '+e.isoformat()+' is outside the period of '+mid+' ('+p[0].isoformat()+'〜'+p[1].isoformat()+'); fix it or leave the reason in history/note')
        if 'before_dependency' in sw and s:
            deps=r.get('depends');deps=deps if isinstance(deps,list) else [deps]
            for d in deps:
                ds=fc.get(d,(None,None))[0] if isinstance(d,str) else None
                if ds and s<ds:warn('W_REGISTERS',rl,'forecast.start '+s.isoformat()+' is before the forecast.start of '+d+' ('+ds.isoformat()+'); fix it or leave the reason in history/note')
    if 'issue_due_outside_wbs' in sw:
        live=[fc[r['id']] for r in wrows if r.get('status')!='cancelled']
        ranges=[x for x in live if x[0] and x[1]] if all(x[0] and x[1] for x in live) else []   # any undecided/unreadable WBS range: say nothing
        for r in loaded.get('issues') or []:
            if r.get('status')!='open':continue
            due=r.get('due');due=_as_date(due) if isinstance(due,(date,datetime)) or (isinstance(due,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',due.strip())) else None
            if due and ranges and not any(a<=due<=b for a,b in ranges):warn('W_REGISTERS',files['issues']['path']+'#'+r['id'],'due '+due.isoformat()+' falls in no WBS forecast range')

def _repo_root(layer):
    """The repository root for repo-relative sources: the parent of the Flow folder that holds the Layer (None if not found)."""
    if layer is None:return None
    for x in Path(layer).absolute().parents:
        if x.name=='Flow':return x.parent
    return None

def check_sources(rc,safe,err,warn,layer):
    """Sources of issues/hypotheses rows. Layer-relative must exist (E), repo-relative missing warns,
    Flow@<commit>:<path> is checked for format only (no git call), absolute/../colon forms warn.
    A relative path whose first name is in neither the Layer nor the repository root is Layer-relative;
    when the repository root is not found (Layer outside Flow) it warns as before. A name that also exists at the repository root stays repo-relative."""
    spec=rc.get('sources')
    if not spec:return
    pat=next((f['pattern'] for f in spec.get('source_formats',[]) if isinstance(f,dict) and f.get('pattern')),None)
    repo=_repo_root(layer);lay=Path(layer).absolute() if layer is not None else None
    for name,key in (('issues','issues'),('hypotheses','hypotheses')):
        fs=rc['files'][name]
        if 'sources' not in fs.get('optional',[]):continue
        q=safe(fs['path'])
        try:data=load(q) if q is not None and q.is_file() else None
        except Exception:continue
        rows=data.get(key) if isinstance(data,dict) else None
        for r in rows if isinstance(rows,list) else []:
            if not isinstance(r,dict) or 'sources' not in r or not isinstance(r.get('id'),str):continue
            rl=fs['path']+'#'+r['id'];vals=r['sources']
            if not isinstance(vals,list) or not vals or any(not isinstance(v,str) or not v.strip() for v in vals):err('E_REGISTERS',rl,'sources must be a non-empty list of path strings');continue
            for v in vals:
                v=v.strip()
                if pat and re.fullmatch(pat,v):continue
                pv=Path(v)
                if not pv.parts or pv.is_absolute() or '..' in pv.parts or ':' in v or '\\' in v:   # '.' has no parts
                    if warn is not None:warn('W_REGISTERS',rl,'source '+v+' is not a Layer-relative, repo-relative or Flow@<commit>:<path> form')
                    continue
                first=pv.parts[0]
                if lay is not None and (lay/first).exists():
                    try:ok=safe_path(lay,v).exists()
                    except Exception:ok=False
                    if not ok:err('E_REGISTERS',rl,'source missing in the Layer: '+v)
                elif repo is not None and (repo/first).exists():
                    if not (repo/v).exists() and warn is not None:warn('W_REGISTERS',rl,'repo-relative source not found: '+v)
                elif lay is not None and repo is not None:err('E_REGISTERS',rl,'source missing in the Layer: '+v)   # not in the Layer, not a repo top-level name
                elif warn is not None:warn('W_REGISTERS',rl,'source '+v+' is not a Layer-relative, repo-relative or Flow@<commit>:<path> form')

def check_plan_lists(rc,safe,err,warn,layer):
    """todo/wbs/roadmap optional keys, references, acceptance, schedule and AI-PLC task links. Returns wbs_summary."""
    files=rc['files'];ids={}
    loaded={}
    for name in ('issues','hypotheses','todo','wbs','roadmap'):
        _,rows=_load_list(files[name],safe) if name!='hypotheses' else (None,None)
        if name=='hypotheses':
            hq=safe(files['hypotheses']['path'])
            try:hd=load(hq) if hq is not None and hq.is_file() else None
            except Exception:hd=None
            hr=hd.get('hypotheses') if isinstance(hd,dict) else None
            rows=[r for r in hr if isinstance(r,dict) and isinstance(r.get('id'),str)] if isinstance(hr,list) else None
        loaded[name]=rows;ids[name]=None if rows is None else {r['id'] for r in rows}
    sot=rc.get('source_of_truth',['local'])
    def refcheck(spec,r,rl):
        for k,target in (spec.get('refs') or {}).items():
            if k not in r or r[k] is None:continue
            vals=r[k] if isinstance(r[k],list) else [r[k]]
            for v in vals:
                if not isinstance(v,str):err('E_REGISTERS',rl,k+' must reference ids');continue
                if ids.get(target) is not None and v not in ids[target]:err('E_REGISTERS',rl,k+' points to unknown id '+v)
                if k=='depends' and v==r['id']:err('E_REGISTERS',rl,'depends points to itself')
    for name in ('todo','wbs','roadmap'):
        spec=files[name];rows=loaded[name]
        if rows is None:continue
        for r in rows:
            rl=spec['path']+'#'+r['id']
            extra=[k for k in r if k not in spec['required'] and k not in spec.get('optional',[])]
            if extra:err('E_REGISTERS',rl,'unknown key: '+','.join(map(str,extra)))
            refcheck(spec,r,rl)
            if 'source_of_truth' in r and r['source_of_truth'] not in sot:err('E_REGISTERS',rl,'source_of_truth '+str(r['source_of_truth'])+' is not supported yet (local only)')
            if name=='todo' and r.get('source') is not None:
                srcs=r['source'] if isinstance(r['source'],list) else [r['source']]
                for v in srcs:
                    if not isinstance(v,str):err('E_REGISTERS',rl,'source must be text or ids');continue
                    m=re.fullmatch(r'([IH])\d+',v)
                    if m:
                        target=spec['source_refs'][m.group(1)]
                        if ids.get(target) is not None and v not in ids[target]:err('E_REGISTERS',rl,'source points to unknown id '+v)
            if name=='todo':
                ke,kw=knot_problems(spec,r)
                for m_ in ke:err('E_REGISTERS',rl,m_)
                for m_ in kw:
                    if warn is not None:warn('W_REGISTERS',rl,m_)
            if name=='todo' and warn is not None and not r.get('wbs_id') and r.get('status')!='cancelled':warn('W_REGISTERS',rl,'no WBS number (wbs_id is empty); an AI guess must be shown separately as a candidate')
            if name=='wbs':
                acc=spec['acceptance'];ev=r.get('evidence_refs');ev=ev if isinstance(ev,list) else ([ev] if ev else [])
                if r.get('status') in acc['needs_evidence'] and not ev:err('E_REGISTERS',rl,str(r.get('status'))+' needs evidence_refs')
                for v in ev:
                    if not isinstance(v,str):err('E_REGISTERS',rl,'evidence_refs must be paths or H ids');continue
                    if re.fullmatch(r'H\d+',v):
                        if ids.get('hypotheses') is not None and v not in ids['hypotheses']:err('E_REGISTERS',rl,'evidence points to unknown id '+v)
                    else:
                        try:p=safe_path(layer,v) if layer is not None else None
                        except Exception:p=None
                        if p is None or not p.exists():err('E_REGISTERS',rl,'evidence missing: '+v)
                sch=r.get('schedule')
                if sch is not None:
                    sk=spec['schedule']
                    if not isinstance(sch,dict) or any(k not in sk['keys'] for k in sch):err('E_REGISTERS',rl,'schedule keys must be '+','.join(sk['keys']))
                    else:
                        for part in ('baseline','forecast','actual'):
                            seg=sch.get(part)
                            if seg is None:continue
                            if not isinstance(seg,dict):err('E_REGISTERS',rl,'schedule.'+part+' must be a map');continue
                            a,b=_as_date(seg.get('start')),_as_date(seg.get('end'))
                            if a and b and b<a:err('E_REGISTERS',rl,'schedule.'+part+' ends before it starts')
                        hist=sch.get('history',[])
                        if not isinstance(hist,list):err('E_REGISTERS',rl,'schedule.history must be a list');hist=[]
                        base=sch.get('baseline')
                        if warn is not None and isinstance(base,dict) and any(not base.get(k) for k in sk['baseline_agreement']):warn('W_REGISTERS',rl,'baseline has no agreement record (agreed_at/agreed_by/scope); treated as a forecast')
                        fc=sch.get('forecast')
                        if warn is not None and isinstance(base,dict) and isinstance(fc,dict) and any(((_as_date(fc.get(k)),_as_date(base.get(k)))!=(None,None) and _as_date(fc.get(k))!=_as_date(base.get(k))) or ((_as_date(fc.get(k)),_as_date(base.get(k)))==(None,None) and fc.get(k)!=base.get(k)) for k in sk['range']) and not hist:warn('W_REGISTERS',rl,'forecast differs from baseline but history is empty')
    # depends cycles and roadmap<->wbs consistency
    wrows=loaded['wbs'] or [];rrows=loaded['roadmap'] or []
    deps={r['id']:[d for d in (r.get('depends') if isinstance(r.get('depends'),list) else [r.get('depends')]) if isinstance(d,str)] for r in wrows}
    color={n:0 for n in deps};on_cycle=set()   # iterative three-colour DFS; report only nodes on a cycle
    for root in deps:
        if color[root]:continue
        stack=[(root,iter(deps[root]))];path=[root];color[root]=1
        while stack:
            node,it=stack[-1];nxt=next((d for d in it if d in deps),None)
            if nxt is None:color[node]=2;stack.pop();path.pop();continue
            if color[nxt]==1 and nxt!=node:on_cycle.update(path[path.index(nxt):])
            elif color[nxt]==0:color[nxt]=1;stack.append((nxt,iter(deps[nxt])));path.append(nxt)
    for n in sorted(on_cycle):err('E_REGISTERS',files['wbs']['path']+'#'+n,'depends forms a cycle')
    check_schedule_warnings(rc,loaded,warn)
    ms_of={r['id']:r.get('milestone_id') for r in wrows if isinstance(r.get('milestone_id'),str)}
    wl_of={m['id']:(m.get('wbs_ids') if isinstance(m.get('wbs_ids'),list) else ([m['wbs_ids']] if isinstance(m.get('wbs_ids'),str) else [])) for m in rrows}
    wbs_known={r['id'] for r in wrows}
    for mid,wl in wl_of.items():   # roadmap -> wbs: each listed WBS must point back to this milestone
        for w in wl:
            if w in wbs_known and ms_of.get(w)!=mid:err('E_REGISTERS',files['roadmap']['path']+'#'+mid,'wbs_ids includes '+w+' but its milestone_id is '+str(ms_of.get(w)))
    for w,mid in ms_of.items():   # wbs -> roadmap: the milestone must list this WBS
        if mid in wl_of and w not in wl_of[mid]:err('E_REGISTERS',files['wbs']['path']+'#'+w,'milestone_id '+mid+' does not list this WBS in wbs_ids')
    # AI-PLC backlog tasks
    tl=rc.get('task_links') or {}
    if layer is not None and tl:
        try:
            bq=safe_path(layer,'backlog.yaml');bl=load(bq) if bq.is_file() else {}
        except Exception:bl={}
        tasks=bl.get('tasks') if isinstance(bl,dict) else None
        for t in tasks if isinstance(tasks,list) else []:
            if not isinstance(t,dict) or not isinstance(t.get('id'),str):continue
            tloc='backlog.yaml#'+t['id']
            w=t.get('wbs_id');i=t.get('issue_id')
            if w is not None and w!='none':
                if not isinstance(w,str) or not re.fullmatch(tl['wbs_id'],w):err('E_REGISTERS',tloc,'wbs_id must look like W1 or W1.1 (or none)')
                elif ids.get('wbs') is not None and w not in ids['wbs']:err('E_REGISTERS',tloc,'wbs_id points to unknown WBS '+w)
            if i is not None:
                if not isinstance(i,str) or not re.fullmatch(tl['issue_id'],i):err('E_REGISTERS',tloc,'issue_id must look like I1')
                elif ids.get('issues') is not None and i not in ids['issues']:err('E_REGISTERS',tloc,'issue_id points to unknown issue '+i)
            if warn is not None and w is None and t.get('output') and t.get('status')!='cancelled' and t.get('type') not in ('management','coordination'):warn('W_REGISTERS',tloc,'task with output has no wbs_id (write the WBS row or wbs_id: none)')
    sts=files['wbs']['status'];valid=[r for r in wrows if r.get('status') in sts]
    counts={k:sum(1 for r in valid if r.get('status')==k) for k in sts}
    denom=len(valid)-counts.get('cancelled',0)
    return {**counts,'total':len(valid),'accepted_ratio':(counts.get('accepted',0)/denom if denom else None)}

def check_registers(contract,safe,validation,err,layer=None,warn=None,out=None):
    """Only for contracts that opted in with aipm.registers: true."""
    try:rc_path=registers_contract_path(contract.get('registers_contract_version'))   # the version the package was bound to
    except ValueError as ex:err('E_REGISTERS','registers_contract',str(ex));return
    if digest(rc_path)!=contract.get('registers_contract_sha256'):err('E_REGISTERS','registers_contract','registers contract changed or hash mismatch');return
    rc=registers_layout(contract,load(rc_path));spec=rc['files']['hypotheses'];js=spec['judgement']   # sheets_v1: no registers/ folder
    ids={'hypotheses':list_ids(rc['files']['hypotheses'],safe,'hypotheses'),'issues':list_ids(rc['files']['issues'],safe,'issues')}
    for name in ('issues','todo','wbs','roadmap'):check_list(rc['files'][name],safe,err,warn,ids)
    summary=check_resolution(rc,safe,err,warn,layer,contract)
    wsum=check_plan_lists(rc,safe,err,warn,layer)
    check_sources(rc,safe,err,warn,layer)
    if out is not None:out['wbs_summary']=wsum
    q=safe(spec['path'])
    if q is None:return summary
    if not q.is_file():err('E_REGISTERS',spec['path'],'registers file missing');return summary
    try:data=load(q)
    except Exception as ex:err('E_REGISTERS',spec['path'],str(ex));return summary
    if not isinstance(data,dict) or any(k not in data for k in spec['top_required']) or not isinstance(data.get('hypotheses'),list):err('E_REGISTERS',spec['path'],'map with hypotheses list required');return summary
    rows={};human=set()
    for i,h in enumerate(data['hypotheses']):
        loc=spec['path']+'#'+str(i)
        if not isinstance(h,dict):err('E_REGISTERS',loc,'row must be map');continue
        missing=[k for k in spec['required'] if k not in h]
        if missing:err('E_REGISTERS',loc,'required key missing: '+','.join(missing));continue
        unknown=[k for k in h if k not in spec['required'] and k not in spec['optional']]
        if unknown:err('E_REGISTERS',loc,'unknown key: '+','.join(map(str,unknown)))
        hid=h['id'];loc=spec['path']+'#'+str(hid)
        if not isinstance(hid,str) or not re.fullmatch(spec['id_pattern'],hid):err('E_REGISTERS',loc,'id must match '+spec['id_pattern']);continue
        if hid in rows:err('E_REGISTERS',loc,'duplicate id');continue
        rows[hid]=h
        if h['kind'] not in spec['kind']:err('E_REGISTERS',loc,'unknown kind')
        if h['status'] not in spec['status']:err('E_REGISTERS',loc,'unknown status')
        if not isinstance(h['claim'],str) or not h['claim'].strip():err('E_REGISTERS',loc,'empty claim')
        if 'priority' in h and h['priority'] not in spec['priority']:err('E_REGISTERS',loc,'unknown priority')
        js_rows=h.get('judgements',[])
        if not isinstance(js_rows,list):err('E_REGISTERS',loc,'judgements must be list');js_rows=[]
        last_human=None
        for j,g in enumerate(js_rows):
            gl=loc+'.judgements#'+str(j)
            if not isinstance(g,dict) or any(k not in g for k in js['required']):err('E_REGISTERS',gl,'judgement needs '+','.join(js['required']));continue
            extra=[k for k in g if k not in js['required'] and k not in js['optional']]
            if extra:err('E_REGISTERS',gl,'unknown key: '+','.join(map(str,extra)))
            if any(not isinstance(g[k],str) or not g[k].strip() for k in ('date','event')):err('E_REGISTERS',gl,'date/event must be non-empty strings')
            if g['verdict'] not in js['verdict']:err('E_REGISTERS',gl,'unknown verdict');continue
            if g['judged_by'] not in js['judged_by']:err('E_REGISTERS',gl,'unknown judged_by');continue
            if g['judged_by'] in ('owner','decider'):
                problem=receipt_problem(g.get('evidence_ref'),layer,contract)
                if problem:err('E_REGISTERS',gl,'human judgement needs an actual-user receipt: '+problem)
                else:human.add(hid);last_human=g['verdict']
        if last_human is not None:
            want={'supported':'supported','not_supported':'not_supported','undetermined':'unknown'}[last_human]
            if h['status']!=want:err('E_REGISTERS',loc,'status must follow the latest owner/decider verdict ('+want+')')
        elif h['status']=='supported':err('E_REGISTERS',loc,'supported requires an owner/decider judgement')
        elif h['kind']!='validation' and h['status']!='unknown':err('E_REGISTERS',loc,'without an owner/decider judgement only unknown is allowed (ai_proxy is a proposal)')
    for vh in validation.get('hypotheses') or []:
        if not isinstance(vh,dict):continue
        vid=vh.get('id')
        if not isinstance(vid,str):err('E_REGISTERS','validation.'+str(vid),'validation hypothesis id must be a string');continue
        row=rows.get(vid)
        if row is None:err('E_REGISTERS','validation.'+str(vid),'validation hypothesis id missing from registers');continue
        if row['kind']=='opportunity':err('E_REGISTERS','validation.'+str(vid),'id collides with an Init opportunity hypothesis; use the next free id with kind validation');continue
        if row['kind']!='validation':err('E_REGISTERS','validation.'+str(vid),'registers row must have kind validation');continue
        if vid not in human and row['status']!=vh.get('result'):err('E_REGISTERS','validation.'+str(vid),'status differs from validation_record result without an owner/decider judgement')
    listed={vh.get('id') for vh in validation.get('hypotheses') or [] if isinstance(vh,dict) and isinstance(vh.get('id'),str)}
    for hid,h in rows.items():
        if h['kind']=='validation' and hid not in listed and hid not in human and h['status']!='unknown':err('E_REGISTERS',spec['path']+'#'+hid,'without an owner/decider judgement only unknown is allowed (ai_proxy is a proposal)')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--layer',required=True);parser.add_argument('--phase',choices=['prearchive','final'],default='final')
    parser.add_argument('--stock-root',help='box_root_v1 final: the repository root that holds Stock/ (default: the parent of the Flow folder that holds the Layer; a Flow worktree outside the repository needs it)');args=parser.parse_args()
    try:
        L=Path(args.layer).absolute()
        pkg=L/SHEETS_ROOT if not select(L) and light.is_light(L) else L/build_contract(L)['package_root']
        result=validate(pkg,phase=args.phase,layer=args.layer,stock_root=args.stock_root)
    except Exception as ex: result={'pass':False,'errors':[{'code':'E_VALIDATOR','path':'.','message':str(ex)}],'warnings':[]}
    print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result['pass'] else 1)
