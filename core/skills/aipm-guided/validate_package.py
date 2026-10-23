#!/usr/bin/env python3
"""Read-only common AIPM validator; dynamically bound to explicitly selected Layers."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import argparse, hashlib, json, re
from datetime import date, datetime, timezone
import yaml

METHOD = Path(__file__).resolve().parent
from package import build_contract, select, safe_path, input_path, source_path, course_registry, LEGACY_COURSE, registers_contract_path, prior_answer_problem

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

def validate(package, phase="final", layer=None, stock_runtime=None):
    if layer is None: raise ValueError("explicit layer required")
    LAYER = Path(layer).absolute()
    if not select(LAYER): return {"pass": True, "route": "legacy", "errors": [], "warnings": [], "checked_documents": 0}
    wanted = safe_path(LAYER, "Documents/aipm_project")
    if Path(package).absolute() != wanted: raise ValueError("package must be the selected Layer Documents/aipm_project")
    if phase not in ("prearchive", "final"): raise ValueError("unknown validation phase")
    contract = build_contract(LAYER)
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
    def safe(rel):
        q = root / rel
        if Path(rel).is_absolute() or '..' in Path(rel).parts:
            err('E_BOUNDARY', rel, 'absolute or parent-relative path'); return None
        if root.is_symlink() or any(x.is_symlink() for x in [q, *q.parents] if x == root or root in x.parents):
            err('E_BOUNDARY', rel, 'symlink not accepted'); return None
        if not q.resolve().is_relative_to(root.resolve()):
            err('E_BOUNDARY', rel, 'outside package'); return None
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
    for folder in contract['folders']:
        for base in ((flow,) if shared else (flow, stock+'/documents')):
            q=safe(base+'/'+folder)
            if q and not q.is_dir(): err('E_MISSING', base+'/'+folder, 'required folder missing')
    docs = {}; expected = {}; actual = {}
    for e in contract['documents']:
        rel=(stock if e.get('side')=='stock_project' else flow)+'/'+e['path']
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
    def confirmed(key):
        r=responses.get(key,{})
        if not isinstance(r,dict): return False
        try:
            q=safe_path(LAYER,r['source'])
            target=safe_path(LAYER,r['target_path'])
            prefix='Documents/aipm_project/'
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
            for field,value in [('scope_id',contract['scope_id']),('stage',key),('answer',r.get('answer')),('target_path',r['target_path']),('target_sha256',r.get('target_sha256'))]:
                if receipt.get(field)!=value:return False
            if not isinstance(receipt.get('question_id'),str) or not receipt['question_id'].strip() or not isinstance(receipt.get('source_thread_id'),str) or not receipt['source_thread_id'].strip():return False
            received=datetime.fromisoformat(receipt['received_at'])
            event=next(s for s in manifest.get('stages',[]) if s.get('name')==('gaps' if batch else key))
            if received.tzinfo is None or received.timestamp()*1e9<target.stat().st_mtime_ns or received>datetime.fromisoformat(event['finished_at']):return False
            if not any(e.get('kind')=='user_reported' and e.get('source')==r['source'] and e.get('source_sha256')==r.get('source_sha256') for e in manifest.get('evidence',[])):return False
            return digest(q)==r.get('source_sha256') and isinstance(r.get('answer'),str) and bool(r['answer'].strip()) and digest(target)==r.get('target_sha256') and r.get('target_sha256')==manifest.get('checkpoint_targets',{}).get(key)
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
    if [s.get('name') for s in stages if isinstance(s,dict)]!=want:err('E_ORDER','stages','incorrect required stage order')
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
    snap_pre='Documents/aipm_project/source_snapshots/'
    reads_by_id={r['id']:r for r in (manifest.get('source_reads') or []) if isinstance(r,dict) and isinstance(r.get('id'),str)}
    valid_snaps={}
    for sid,rel in snaps.items():   # a copy is honoured only for a read package-internal source that it mirrors
        r=reads_by_id.get(sid,{});path=str(r.get('path',''))
        if r.get('domain')=='layer' and path.startswith('Documents/aipm_project/') and rel==snap_pre+path[len('Documents/aipm_project/'):]:valid_snaps[sid]=rel
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
        try: q=input_path(LAYER,checked(src,eid)) if batch else safe_path(LAYER,src)
        except (TypeError,ValueError): err('E_EVIDENCE',str(eid),'unsafe source'); continue
        if Path(src).is_absolute() or '..' in Path(src).parts or (not batch and not q.resolve().is_relative_to(LAYER.resolve())) or not q.is_file():err('E_EVIDENCE',str(eid),'unresolved allowed source')
        elif digest(q)!=e.get('source_sha256'):err('E_EVIDENCE',str(eid),'source hash mismatch')
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
            try:
                from shared_stock import verify_archive
            except ImportError:
                raise ValueError('registry_stock_v1 (shared Stock) is not included in this package') from None
            shared_archive=verify_archive(LAYER,stock_runtime)
        except Exception as ex:err('E_ARCHIVE','shared Stock',str(ex))
    if not isinstance(records,list):err('E_MANIFEST','records','not list');records=[]
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
            if q.stat().st_mtime_ns!=r.get('generated_mtime_ns'):err('E_ORDER',rel,'recorded generation mtime mismatch')
            interval=intervals.get(r.get('stage'))
            if not batch and interval and not interval[0]<=q.stat().st_mtime_ns<=interval[1]:err('E_ORDER',rel,'file not generated within declared stage')
        archive=r.get('archive_path')
        if e and e.get('side') not in ['flow','stock_project'] and phase=='final':
            if shared:
                if shared_archive:
                    receipt=shared_archive['receipt']
                    if archive!='originals/'+receipt['source_id']+'/'+rel or r.get('archive_sha256')!=shared_archive['original_hashes'].get(rel):err('E_ARCHIVE',rel,'shared original counterpart mismatch')
                continue
            expected_archive=stock+'/documents/'+e['path']
            if archive!=expected_archive:err('E_ARCHIVE',rel,'incorrect Stock counterpart')
            aq=safe(archive or '')
            if aq and not aq.is_file():err('E_ARCHIVE',rel,'archive missing')
            elif aq and q and rel in actual and (aq.read_bytes()!=q.read_bytes() or digest(aq)!=r.get('archive_sha256')):err('E_ARCHIVE',rel,'Stock/Flow bytes or hash mismatch')
        elif archive is not None:err('E_ARCHIVE',rel,'Init/README should not have a second archive')
    if set(expected)!=seen:err('E_MANIFEST','records','required document records missing')
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
                if type(read.get('source_mtime_ns')) is not int or src.stat().st_mtime_ns!=read['source_mtime_ns'] or digest(src)!=read.get('sha256'):
                    err('E_COURSE',read['id'],'source mtime/hash changed or fabricated')
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
                    if r.get('reused_from') is not None or (q and q.is_file() and interval and not interval[0]<=q.stat().st_mtime_ns<=interval[1]):err('E_COURSE',r.get('path'),'generated time/reuse declaration mismatch')
                elif r.get('generation_kind')=='reused':
                    source=byid.get(r.get('reused_from'))
                    if not source or r.get('source_ids')!=[r.get('reused_from')]:err('E_COURSE',r.get('path'),'reuse needs its actual source binding')
                    elif q and q.is_file() and (digest(q)!=source['sha256'] or q.stat().st_mtime_ns!=source['source_mtime_ns']):err('E_COURSE',r.get('path'),'reuse bytes/mtime do not match source')
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
        if init.get('flow_base')!=flow or init.get('stock_base')!=stock or init.get('share_repo')!='disabled' or init.get('share_local_dir')!='disabled':err('E_BOUNDARY','project_init','wrong roots or enabled sharing')
        if not batch and validation.get('before_solution') is not True:err('E_ORDER','validation','must precede solution')
        if batch and validation.get('before_solution') is not False:err('E_ORDER','validation','batch must not fabricate before-solution validation')
        solutions=[q for rel,q in actual.items() if expected[rel]['source'].endswith('03_ソリューションマップ.md')]
        if not batch and vpath and vpath.is_file() and solutions and vpath.stat().st_mtime_ns>=min(q.stat().st_mtime_ns for q in solutions):err('E_ORDER','validation','written after solution')
        refs(validation.get('evidence_refs'),evidence_ids,'validation evidence')
        if not isinstance(validation.get('hypotheses'),list) or not validation['hypotheses']:err('E_VALIDATION','hypotheses','missing hypotheses')
        else:
            for h in validation['hypotheses']:
                if any(k not in h for k in ['id','kind','claim','method','success','falsification','result','scope']) or h.get('kind')!='hypothesis' or h.get('result') not in ['unknown','not_supported','structurally_supported']:err('E_VALIDATION','hypotheses','invalid statement/result/scope')
    except (KeyError,TypeError,AttributeError,ValueError) as ex:
        err('E_REF','semantic', 'malformed or incomplete semantic data: '+str(ex))
    issues_summary=None;reg_out={}
    if 'registers_contract_version' in contract:issues_summary=check_registers(contract,safe,validation,err,LAYER,warn,reg_out)
    return {'pass':not errors,'scope_id':contract['scope_id'],'source_commit':contract['reviewed_commit'],'validation_phase':phase,'checked_documents':len(actual),'errors':errors,'warnings':warnings,**({'issues_summary':issues_summary} if issues_summary is not None else {}),**reg_out,'limits':['Static Markdown/Mermaid structure and references; no Viewer rendering E2E','Human understanding/new usability/general productivity not measured']}

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
    rc=load(rc_path);spec=rc['files']['hypotheses'];js=spec['judgement']
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
    parser=argparse.ArgumentParser();parser.add_argument('--layer',required=True);parser.add_argument('--phase',choices=['prearchive','final'],default='final');args=parser.parse_args()
    try: result=validate(Path(args.layer).absolute()/'Documents/aipm_project',phase=args.phase,layer=args.layer)
    except Exception as ex: result={'pass':False,'errors':[{'code':'E_VALIDATOR','path':'.','message':str(ex)}],'warnings':[]}
    print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result['pass'] else 1)
