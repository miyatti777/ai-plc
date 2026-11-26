#!/usr/bin/env python3
"""Opt-in routing and bounded AIPM Project initialization. No external commands."""
from pathlib import Path
from datetime import date, datetime, timezone
import argparse, contextlib, copy, hashlib, json, os, re, shutil, sqlite3, unicodedata, urllib.request
import yaml

METHOD=Path(__file__).resolve().parent
COMMIT='2a7cdb8a77cb1b20e1325649faac0d7f177afb62'
LEGACY_COURSE='question_based/single_persona'

class UniqueLoader(yaml.SafeLoader):
    pass
def unique_map(loader,node,deep=False):
    result={}
    for key,value in node.value:
        k=loader.construct_object(key,deep=deep)
        if k in result: raise ValueError('duplicate YAML key: '+str(k))
        result[k]=loader.construct_object(value,deep=deep)
    return result
UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,unique_map)
def load(path): return yaml.load(Path(path).read_text(),Loader=UniqueLoader)
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def safe_path(root,relative):
    root=Path(root).absolute()
    if not isinstance(relative,str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('unsafe relative path')
    q=root/relative
    if any(x.is_symlink() for x in [q,*q.parents] if x==root or root in x.parents): raise ValueError('symlink path refused')
    if not q.resolve().is_relative_to(root.resolve()): raise ValueError('path outside root')
    return q

def intent(layer):
    d=load(safe_path(layer,'intent.yaml'))
    if not isinstance(d,dict): raise ValueError('intent must be map')
    return d

_SELECTOR=None
def addon_selector():
    """.claude/skills/ai-plc/scripts/plc_addon_select.py, loaded once by file path. sys.path and the
    bytecode setting are restored afterwards, so `from package import` stays on this folder."""
    global _SELECTOR
    if _SELECTOR is None:
        import importlib.util, sys
        here=Path(__file__).resolve()   # the repository scripts/ (here), else the ai-plc skill's scripts/ (the public copy)
        path=next((q for q in (here.parents[3]/'scripts/plc_addon_select.py',here.parents[1]/'ai-plc/scripts/plc_addon_select.py') if q.is_file()),here.parents[3]/'scripts/plc_addon_select.py')
        saved,bytecode=list(sys.path),sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode=True
            spec=importlib.util.spec_from_file_location('_aiplc_addon_select',path)
            if spec is None or not path.is_file():raise ImportError('missing '+str(path))
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        except Exception as e:
            raise ValueError('selector unavailable: '+type(e).__name__+': '+str(e)) from e
        finally:
            sys.path[:]=saved;sys.dont_write_bytecode=bytecode
        _SELECTOR=module
    return _SELECTOR

def _light():
    """light.py of this folder. The module imports this one by the name package; when another tool loaded
    this file under a different name or without its folder on sys.path, the folder is put on sys.path for the import only."""
    import sys
    mod=sys.modules.get('light')
    if mod is not None and Path(getattr(mod,'__file__','')).resolve()==METHOD/'light.py':return mod
    saved=list(sys.path)
    try:
        sys.path.insert(0,str(METHOD))
        if sys.modules.get('package') is None:sys.modules['package']=sys.modules[__name__]
        import importlib;return importlib.import_module('light')
    finally:sys.path[:]=saved

def select(layer):
    """True when the bundled PM addon (aipm) is selected: addons [{addon_id: aipm, source: bundled, ...}] or the legacy
    work_style: aipm (read by the selector, never rewritten). Neither field -> False without loading the selector.
    A held selection raises ValueError (stop, as the Stage SKILLs do)."""
    d=intent(layer)
    if d.get('work_style') is None and not d.get('addons'): return False
    result=addon_selector().selected_addons(Path(layer).absolute(),read_roots=[str(Path(layer).absolute())])
    if result['route']=='held':
        raise ValueError('addon selection held: '+', '.join(result['hold_reasons'])+('; '+result['detail'] if result.get('detail') else '')+'; do not silently change intent')
    return any(s['addon_id']=='aipm' for s in result['selected'])

def slug(value,label):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*',value):
        raise ValueError(label+' must be an explicit ASCII identifier without paths')
    return value

def registers_contract_path(version=None):
    """The registers contract file of one version (version 1 is frozen byte-for-byte in registers_contract.v1.yaml).
    None means the latest (registers_contract.yaml). Older versions are never rebuilt from the latest file."""
    latest=METHOD/'registers_contract.yaml'
    if version is None or version==load(latest)['version']:return latest
    if type(version) is not int or version<1:raise ValueError('unknown registers contract version: '+str(version))
    q=METHOD/('registers_contract.v'+str(version)+'.yaml')
    if not q.is_file() or load(q).get('version')!=version:raise ValueError('unknown registers contract version: '+str(version))
    return q
def registers_contract(c):
    """The registers contract bound in a built contract c (the saved version for existing packages). In a sheets_v1 package
    the registers sit directly in Sheets/ (no registers/ folder): the paths lose their 'registers/' prefix."""
    return registers_layout(c,load(registers_contract_path(c['registers_contract_version'])))
def registers_layout(c,rc):
    """rc (a loaded registers contract) with its file paths as they are in the package of c."""
    if c.get('layout')!=SHEETS_LAYOUT:return rc
    rc=copy.deepcopy(rc);pre=rc.get('root','registers')+'/'
    for spec in rc['files'].values():
        if not spec['path'].startswith(pre):raise ValueError('registers contract path outside its root: '+spec['path'])
        spec['path']=spec['path'][len(pre):]
    rc['root']='';return rc

def course_registry():
    data=load(METHOD/'course_contracts.yaml')
    expected={LEGACY_COURSE,'solution_based/single_persona','document_based/single_persona'}
    if not isinstance(data,dict) or data.get('version')!=1 or set(data.get('courses',{}))!=expected:
        raise ValueError('unknown local course contract/version')
    return data

def course_id(layer):
    selected=intent(layer).get('aipm',{}).get('course',LEGACY_COURSE)
    if not isinstance(selected,str) or selected not in course_registry()['courses']:
        raise ValueError('unsupported AIPM course')
    return selected

def source_path(layer, domain, relative):
    if domain=='layer': return safe_path(layer,relative)
    if domain=='method_source':
        source=json.loads((METHOD/'source/source_manifest.json').read_text())
        allowed={'source/'+entry['path'] for entry in source['files']}
        if relative not in allowed: raise ValueError('not a fixed method source')
        return safe_path(METHOD,relative)
    raise ValueError('unknown source domain')

def input_path(layer, value):
    if isinstance(value,str) and value.startswith('method_source:'):
        return source_path(layer,'method_source',value[len('method_source:'):])
    return safe_path(layer,value)

def document_stage(entry):
    return 'init' if entry.get('side') else {'01':'persona','02':'problem','03':'solution','04':'story'}[entry['path'][:2]]

def shape_ok(data,spec):
    typ=spec['type']
    if typ=='string': return isinstance(data,str) and (not spec.get('nonempty') or bool(data.strip()))
    if typ=='integer': return isinstance(data,int) and not isinstance(data,bool)
    if typ=='list': return isinstance(data,list) and len(data)>=spec.get('min_items',0) and all(shape_ok(x,spec['items']) for x in data)
    if typ=='map':
        return isinstance(data,dict) and len(data)>=spec.get('min_items',0) and all(k in data and shape_ok(data[k],v) for k,v in spec.get('fields',{}).items()) and ('values' not in spec or all(shape_ok(v,spec['values']) for v in data.values()))
    return False

def document_ok(raw,entry):
    if entry['kind']=='yaml':
        try: return shape_ok(yaml.load(raw,Loader=UniqueLoader),entry['schema'])
        except (ValueError,yaml.YAMLError): return False
    headings=re.findall(r'^#{2,3} (.+)$',raw,re.M)
    return all(h in headings for h in entry.get('required_headings',[])) and (entry['kind']!='mermaid' or len(re.findall(r'```mermaid\s*\n(.*?)\n```',raw,re.S))==1)

PRIOR_ANSWER_KEYS=('answer','source','asked_at')
def prior_answer_problem(layer,gap):
    """An optional gap.prior_answer {answer, source, asked_at} records what the user answered before drafting.
    Only the shape, a non-empty answer and an existing Layer-relative source are checked. It is not a receipt and never confirms a decision."""
    if 'prior_answer' not in gap:return None
    pa=gap['prior_answer']
    if not isinstance(pa,dict) or set(pa)-set(PRIOR_ANSWER_KEYS):return 'prior_answer must be a map of '+'/'.join(PRIOR_ANSWER_KEYS)
    if not isinstance(pa.get('answer'),str) or not pa['answer'].strip():return 'prior_answer needs a non-empty answer'
    try:q=safe_path(layer,pa.get('source'))
    except ValueError:return 'prior_answer source must be a Layer-relative path'
    if not q.is_file():return 'prior_answer source missing: '+str(pa.get('source'))
    return None

def course_plan(layer,packet_path):
    """Read actual inputs once; map compatible documents, missing drafts and material questions."""
    layer=Path(layer).absolute();c=build_contract(layer)
    if c.get('course_id',LEGACY_COURSE)==LEGACY_COURSE: raise ValueError('batch API is for explicitly selected new courses only')
    packet=load(safe_path(layer,packet_path))
    if not isinstance(packet,dict) or packet.get('version')!=1 or packet.get('scope_id')!=c['scope_id']:
        raise ValueError('course input version/scope mismatch')
    if c['course_id']=='solution_based/single_persona':
        sol=packet.get('solution',{})
        if not isinstance(sol,dict) or sol.get('kind')!='hypothesis' or not isinstance(sol.get('value'),str) or not sol['value'].strip():
            raise ValueError('solution must be an explicitly labelled hypothesis')
    sources=packet.get('sources');reads=[];texts={}
    if not isinstance(sources,list) or not sources: raise ValueError('actual sources required')
    for item in sources:
        if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not item['id'] or item['id'] in texts: raise ValueError('unique source ID required')
        q=source_path(layer,item.get('domain'),item.get('path'));before=q.stat();raw=q.read_bytes();after=q.stat()
        digest=hashlib.sha256(raw).hexdigest()
        if before.st_mtime_ns!=after.st_mtime_ns or before.st_size!=after.st_size or digest!=item.get('sha256'):
            raise ValueError('source changed or source hash mismatch')
        texts[item['id']]=raw.decode('utf-8')
        reads.append({'id':item['id'],'domain':item['domain'],'path':item['path'],'sha256':digest,'source_mtime_ns':after.st_mtime_ns,'read_at':datetime.now(timezone.utc).isoformat()})
    drafts=packet.get('drafts',{});reuse=packet.get('reuse',{})
    if not isinstance(drafts,dict) or not isinstance(reuse,dict): raise ValueError('drafts/reuse must be maps by source step')
    steps={e['step']:e for e in c['documents']}
    if (set(drafts)|set(reuse))-set(steps): raise ValueError('unknown output source step')
    if set(drafts)&set(reuse): raise ValueError('one output cannot be both draft and reuse')
    mapped={}
    for step,source_id in reuse.items():
        if step not in steps or source_id not in texts or not document_ok(texts[source_id],steps[step]): raise ValueError('reuse source is not format-compatible')
        mapped[step]=source_id
    gaps=packet.get('gaps',[])
    if not isinstance(gaps,list): raise ValueError('gaps must be list')
    for gap in gaps:
        if not isinstance(gap,dict) or gap.get('kind')!='unknown' or type(gap.get('requires_user')) is not bool or not gap.get('reason'):
            raise ValueError('gap needs unknown label, reason and materiality')
        if gap['requires_user'] and (not gap.get('question') or gap.get('decision_key') not in ['persona','validation']): raise ValueError('material gap needs a question and existing decision key')
        problem=prior_answer_problem(layer,gap)
        if problem: raise ValueError(problem)
    decisions=packet.get('decisions')
    if not isinstance(decisions,dict) or set(decisions)!=set(course_registry()['human_decisions']): raise ValueError('persona/validation decisions required')
    for key,d in decisions.items():
        if not isinstance(d,dict) or d.get('state') not in ['not_required','pending','confirmed_actual'] or not d.get('reason') or not isinstance(d.get('source_ids'),list) or not d['source_ids'] or not set(d['source_ids'])<=set(texts): raise ValueError('decision needs state, reason and actual source references')
        if d['state']=='not_required' and d.get('scope')!='reversible_draft_only': raise ValueError('no-question decision must stay reversible draft only')
        if d['state']=='pending' and not d.get('question'): raise ValueError('pending decision needs a question')
    claims=packet.get('claims',[])
    if not isinstance(claims,list): raise ValueError('claims must be list')
    for claim in claims:
        if not isinstance(claim,dict) or claim.get('kind') not in ['observed','user_reported','hypothesis','inference','unknown'] or not isinstance(claim.get('source_ids'),list) or not set(claim['source_ids'])<=set(texts): raise ValueError('claim kind/source references required')
        if claim['kind'] in ['observed','user_reported'] and not claim['source_ids']: raise ValueError('factual claim needs a source')
        if claim['kind']=='user_reported': raise ValueError('batch drafting cannot fabricate a human response; use the actual checkpoint receipt after drafting')
    missing=sorted(set(steps)-set(drafts)-set(mapped))
    questions=[x['question'] for x in gaps if x['requires_user']]+[d['question'] for d in decisions.values() if d['state']=='pending']
    return {'course':c['course_id'],'contract':c,'source_reads':reads,'mapping':mapped,'missing_steps':missing,'gaps':gaps,'decisions':decisions,'claims':claims,'questions':list(dict.fromkeys(questions)),'packet':packet,'texts':texts,'packet_path':packet_path,'packet_sha256':sha(safe_path(layer,packet_path))}

def package_folder_bases(c):
    """Package-relative bases that hold the contract folders: nested_v1 has Flow and Stock/documents (shared Stock: Flow only),
    box_root_v1 only the package itself."""
    if c.get('layout') in FLAT_LAYOUTS or c.get('storage')=='registry_stock_v1':return [c['flow_rel']]
    return [c['flow_rel'],c['stock_project_rel']+'/documents']

def mode_init_package(layer,root,c):
    """mode_init when the existing package holds only the Collection Phase 7.5 init outputs; else None.
    format_contract and registers are kept; the init drafts project_init/README must be unedited because the batch replaces them as two of the 19 documents."""
    mi=intent(layer).get('mode_init')
    if not isinstance(mi,dict) or mi.get('state')!='done' or not isinstance(mi.get('outputs'),list):return None
    try:
        done=datetime.fromisoformat(str(mi.get('done_at')))
        if done.tzinfo is None or done>datetime.now(timezone.utc):return None
    except ValueError:return None
    if any((root/n).exists() for n in ('manifest.yaml','validation_record.yaml','validation_checkpoint.yaml')):return None
    outs={o.get('path'):o.get('sha256') for o in mi['outputs'] if isinstance(o,dict)}
    pre=c['package_root']+'/'
    fc=root/'format_contract.yaml'
    if not fc.is_file() or outs.get(pre+'format_contract.yaml')!=sha(fc):return None
    for e in c['documents']:
        if not e.get('side'):continue
        rel=doc_rel(c,e);q=root/rel
        if not q.is_file() or outs.get(pre+rel)!=sha(q):return None       # init draft missing or edited by hand
    registers=[f['path'] for f in registers_contract(c)['files'].values()] if 'registers_contract_version' in c else []
    if any(not (root/r).is_file() for r in registers):return None          # registers were selected but a file is gone
    allowed={'format_contract.yaml',pkg_rel(c['flow_rel'],'project_init.yaml'),pkg_rel(c['stock_project_rel'],'README.md')}|set(registers)   # the fixed init paths, not whatever intent lists
    for q in root.rglob('*'):                                             # allow-list: only the init outputs (registers may be edited) and empty folders
        if q.is_symlink() or (q.is_file() and q.relative_to(root).as_posix() not in allowed):return None
    return mi

def source_snapshots(layer,c,reads):
    """Copy sources that live inside the package (e.g. registers, which later meetings keep updating) to
    source_snapshots/ with the same bytes and mtime; validate checks the copy. Returns {source id: copy path}."""
    pre=c['package_root']+'/';out={}
    todo=[r for r in reads if r['domain']=='layer' and r['path'].startswith(pre)]
    for r in todo:   # check every source first so a failure leaves no partial copies
        src=safe_path(layer,r['path'])
        if sha(src)!=r['sha256'] or src.stat().st_mtime_ns!=r['source_mtime_ns']:raise ValueError('source changed before snapshot')
    for r in todo:
        rel=pre+'source_snapshots/'+r['path'][len(pre):];q=safe_path(layer,rel);q.parent.mkdir(parents=True,exist_ok=True)
        src=safe_path(layer,r['path'])
        shutil.copy2(src,q)
        if sha(q)!=r['sha256'] or q.stat().st_mtime_ns!=r['source_mtime_ns']:raise ValueError('snapshot changed source identity')
        out[r['id']]=rel
    return out

def batch_draft(layer,packet_path,*,stock_runtime=None):
    """Write all 19 prepared documents in one batch, keeping reused source bytes/mtime."""
    layer=Path(layer).absolute();started=datetime.now(timezone.utc).isoformat();plan=course_plan(layer,packet_path);c=plan['contract']
    if plan['missing_steps']: raise ValueError('prepare missing drafts before generation: '+', '.join(plan['missing_steps']))
    root=safe_path(layer,c['package_root']);after_init=None
    if root.exists():
        after_init=mode_init_package(layer,root,c)
        if after_init is None: raise ValueError('batch requires a new package; existing packages are never regenerated/migrated (only a package holding just the unedited mode_init outputs is continued)')
    packet=plan['packet'];prepared={}
    for e in c['documents']:
        step=e['step']
        raw=plan['texts'][plan['mapping'][step]] if step in plan['mapping'] else (yaml.safe_dump(packet['drafts'][step],allow_unicode=True,sort_keys=False) if e['kind']=='yaml' else packet['drafts'][step])
        if not isinstance(raw,str) or not document_ok(raw,e): raise ValueError('invalid prepared document '+step)
        prepared[step]=raw
    validation=packet.get('validation_record')
    if not isinstance(validation,dict) or validation.get('scope_id')!=c['scope_id'] or validation.get('actual_new_user_response') is not None: raise ValueError('explicit scoped validation draft required; no automatic human response')
    if validation.get('before_solution') is not False: raise ValueError('batch validation must not pretend to precede the given/generated solution')
    # Verify sources and packet again before ANY package write.
    for r in plan['source_reads']:
        q=source_path(layer,r['domain'],r['path'])
        if sha(q)!=r['sha256'] or q.stat().st_mtime_ns!=r['source_mtime_ns']: raise ValueError('source changed before batch')
    if sha(safe_path(layer,packet_path))!=plan['packet_sha256']: raise ValueError('input changed before batch')
    init_start=datetime.now(timezone.utc).isoformat();initial=init(layer,stock_runtime=stock_runtime);init_end=datetime.now(timezone.utc).isoformat();batch_start=datetime.now(timezone.utc).isoformat()
    snapshots=source_snapshots(layer,c,plan['source_reads'])   # fix the read versions before writing any of the 19 documents
    records=[];ids=[r['id'] for r in plan['source_reads']];byid={r['id']:r for r in plan['source_reads']}
    inputs=[packet_path]+[('method_source:' if r['domain']=='method_source' else '')+r['path'] for r in plan['source_reads']]
    for e in c['documents']:
        rel=doc_rel(c,e);q=safe_path(root,rel);q.parent.mkdir(parents=True,exist_ok=True);step=e['step'];source_id=plan['mapping'].get(step)
        if source_id:
            r=byid[source_id];shutil.copy2(source_path(layer,r['domain'],r['path']),q)
            if sha(q)!=r['sha256'] or q.stat().st_mtime_ns!=r['source_mtime_ns']: raise ValueError('reuse copy changed source identity')
        else:q.write_text(prepared[step])
        records.append({'path':rel,'source_step':step,'template_sha256':e['template_sha256'],'version':'local-courses-v1','branch':c['course_id'],'stage':document_stage(e),'status':'validated_local_final' if e.get('side') else 'generated','requires_human':False,'human_state':'not_required','inputs':inputs,'evidence_refs':ids,'decision':'reversible local draft; actual human outcomes unknown','sha256':sha(q),'generated_mtime_ns':q.stat().st_mtime_ns,'archive_path':None,'archive_sha256':None,'generation_kind':'reused' if source_id else 'generated','generation_event':'batch','source_ids':[source_id] if source_id else ids,'reused_from':source_id})
    (root/'validation_record.yaml').write_text(yaml.safe_dump(validation,allow_unicode=True,sort_keys=False))
    batch_end=datetime.now(timezone.utc).isoformat();gap_start=datetime.now(timezone.utc).isoformat()
    evidence=[{'id':r['id'],'kind':'observed','source':('method_source:' if r['domain']=='method_source' else '')+r['path'],'source_sha256':r['sha256'],'scope':'document contents only; not evidence of actual user attributes or effectiveness'} for r in plan['source_reads']]
    def event(name,start,end):return {'name':name,'started_at':start,'finished_at':end,'checkpoint_actor':'auto_decision','checkpoint_status':'accepted_local','evidence_refs':ids}
    if after_init is not None:   # init ran earlier in Collection Phase 7.5: record that time and order as they happened (start time was not recorded)
        done=str(after_init['done_at']);init_event=dict(event('init',done,done),evidence_refs=[],origin='mode_init',time_source='mode_init.done_at (start time not recorded)',mode_init_outputs=after_init['outputs'])
        stages=[init_event,event('ingest',started,batch_start),event('batch',batch_start,batch_end),event('gaps',gap_start,datetime.now(timezone.utc).isoformat())]
    manifest={'scope_id':c['scope_id'],'source_commit':c['reviewed_commit'],'contract_version':c['version'],'branch':c['course_id'],'flow_rel':c['flow_rel'],'stock_project_rel':c['stock_project_rel'],'id_mapping':c['id_mapping'],'completion_claim':'local_trial_only; new human readability/effectiveness unknown','stages':[event('init',init_start,init_end),event('ingest',started,init_start),event('batch',batch_start,batch_end),event('gaps',gap_start,datetime.now(timezone.utc).isoformat())],'evidence':evidence,'records':records,'course_contract_version':c['course_contract_version'],'course_contract_sha256':c['course_contract_sha256'],'source_reads':plan['source_reads'],'input_packet':{'path':packet_path,'sha256':plan['packet_sha256']},'gaps':plan['gaps'],'decisions':plan['decisions'],'claims':plan['claims']}
    # Ingestion actually preceded initialization; record that order, never invent timestamps.
    manifest['stages']=stages if after_init is not None else [manifest['stages'][1],manifest['stages'][0],*manifest['stages'][2:]]
    if snapshots:manifest['source_snapshots']=snapshots
    (root/'manifest.yaml').write_text(yaml.safe_dump(manifest,allow_unicode=True,sort_keys=False))
    return {'route':'aipm','course':c['course_id'],'package':str(root),'state':'batch_draft','required_documents':19,'questions':plan['questions'],'pending_human_decisions':any(d['state']=='pending' for d in plan['decisions'].values()),'source_reads':plan['source_reads']}

def archive_course(layer,*,stock_runtime=None,stock_root=None,registry_db=None):
    """Archive only validated new-course artifacts; shared Stock uses its unchanged runtime."""
    from validate_package import validate
    layer=Path(layer).absolute();c=build_contract(layer);root=safe_path(layer,c['package_root'])
    if c.get('course_id',LEGACY_COURSE)==LEGACY_COURSE:raise ValueError('legacy archive stays on the existing route')
    if c.get('storage')=='registry_stock_v1':raise ValueError('use the existing explicit shared Stock prepare/apply runtime')
    result=validate(root,phase='prearchive',layer=layer)
    if not result['pass']:return result
    m=load(root/'manifest.yaml');start=datetime.now(timezone.utc).isoformat()
    if any(r.get('archive_path') is not None for r in m['records']): raise ValueError('already archived; archive is the first apply only. Revise an archived box with register (once) → clone → change → judge-change → apply')
    if c.get('layout') in FLAT_LAYOUTS:
        # box_root_v1 / sheets_v1: copy to the real repository Stock/programs/<program>/projects/<business>/<project>/documents/, where
        # <business> is the display name of the Layer's primary business project, read (never written) from the Registry
        # at archive time. Every check runs before the first copy; the program folder must already exist (no new program
        # is made here, nothing is committed).
        # where (.ai-plc/config.yaml aipm_archive) — stock (the above; business: none skips the Registry) or layer
        # (Documents/aipm_archive/<project> in the Layer: no program folder, no Registry).
        settings=archive_settings(layer,stock_root);name=c['bindings']['program_id']
        if settings['where']=='stock':
            if not c.get('stock_target_rel'):raise ValueError('archive needs aipm.program_id: an existing Stock/programs/<program> folder (nothing written)')
            base=stock_root_of(layer,stock_root)
            if base is None:raise ValueError('repository root holding Stock/programs not found; pass --stock-root (nothing written)')
            program=base/STOCK_PROGRAMS/name
            # the exact spelling (a case-insensitive file system would also open Sample for sample)
            if program.is_symlink() or not program.is_dir() or name not in {x.name for x in (base/STOCK_PROGRAMS).iterdir()}:raise ValueError('Stock/programs/'+name+' does not exist under '+str(base)+' (nothing written)')
        else:base=layer
        target=archive_target_of(layer,base,name,settings,registry_db)
        plan=[]
        for r in m['records']:
            e=next(e for e in c['documents'] if e['step']==r['source_step'])
            if e.get('side'):continue
            dest=target['target_rel']+'/documents/'+e['path'];q=safe_path(base,dest)
            if q.exists():raise ValueError('archive counterpart already exists: '+dest+' (nothing written)')
            plan.append((r,dest,q))
        log=safe_path(base,target['target_rel']+'/'+APPLY_LOG)
        if log.exists():raise ValueError('apply log already exists: '+target['target_rel']+'/'+APPLY_LOG+' (nothing written)')
        # the first archive is the first apply (v1, kind first). The apply_log is written before the copies
        # (only a new file) and removed again when the copies stop, so a failure leaves the Stock as before.
        m['applies']=[{**apply_entry(m,'first',None,target['target_rel']),'docs':{r['path']:r['sha256'] for r,dest,q in plan}}]
        made_dirs=[d for d in (log.parent,*log.parent.parents) if base in d.parents and not d.exists()]
        for d in reversed(made_dirs):d.mkdir()
        write_apply_log(layer,root,c,m,base,target['target_rel'])
        try:archive_to_stock(layer,root,plan)
        except BaseException:
            log.unlink(missing_ok=True)
            for d in made_dirs:
                with contextlib.suppress(OSError):d.rmdir()
            raise
        m['archive_target']=target
        if settings['where']=='stock':stock_root=base
    for r in m['records'] if c.get('layout') not in FLAT_LAYOUTS else []:
        e=next(e for e in c['documents'] if e['step']==r['source_step'])
        if e.get('side'):continue
        dest=c['stock_project_rel']+'/documents/'+e['path'];q=safe_path(root,dest)
        if q.exists():raise ValueError('archive counterpart already exists')
        q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(safe_path(root,r['path']),q);r.update(status='archived_local_final',archive_path=dest,archive_sha256=sha(q))
    m['stages'].append({'name':'archive','started_at':start,'finished_at':datetime.now(timezone.utc).isoformat(),'checkpoint_actor':'auto_decision','checkpoint_status':'accepted_local','evidence_refs':[r['id'] for r in m['source_reads']]})
    (root/'manifest.yaml').write_text(yaml.safe_dump(m,allow_unicode=True,sort_keys=False))
    return validate(root,phase='final',layer=layer,stock_root=stock_root)

# ---- apply (the version records, register and clone) ----
APPLY_LOG='apply_log.yaml'   # beside documents/ in the Stock project folder: the pushed versions, readable from the Stock alone
APPLY_KINDS=('register','first','apply')
LOG_KEYS=('version','kind','at','approval_ref','base_version','changed','docs')   # an apply_log version = these keys of a pushed applies[] entry
def apply_docs(m):
    """{package-relative path: sha256} of every document that has an archive copy (init drafts are not in a version)."""
    return {r['path']:r['sha256'] for r in m.get('records',[]) if isinstance(r,dict) and r.get('archive_path')}
def apply_entry(m,kind,approval_ref,target_rel,*,base_version=None,changed=None):
    return {'version':len(m.get('applies') or [])+1,'kind':kind,'at':datetime.now(timezone.utc).isoformat(),'approval_ref':approval_ref,
            'base_version':base_version,'docs':apply_docs(m),'changed':changed or [],'receipts':{},'event':None,'pushed':True,'stock_target_rel':target_rel}
def flow_layer_rel(layer):
    """Flow/<YYYYMM>/<date>/<layer> of the Layer, also from a worktree or a sparse Flow worktree (the last three parts)."""
    layer=Path(layer).absolute();flow=next((x for x in layer.parents if x.name=='Flow'),None)
    if flow is not None:return 'Flow/'+layer.relative_to(flow).as_posix()
    parts=layer.parts;i=next((n for n in range(len(parts)-1) if re.fullmatch(r'\d{6}',parts[n]) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',parts[n+1])),None)
    return 'Flow/'+'/'.join(parts[i:] if i is not None else parts[-3:])   # a SubLayer keeps its sublayers/... tail
def apply_log_text(layer,c,m):
    pushed=[{k:a.get(k) for k in LOG_KEYS} for a in m['applies'] if a.get('pushed')]
    return yaml.safe_dump({'project':c['bindings']['project_id'],'box':{'layer':flow_layer_rel(layer),'scope_id':c['scope_id'],'package_root':c['package_root']},'versions':pushed},allow_unicode=True,sort_keys=False)
def write_apply_log(layer,root,c,m,base,target_rel,*,create=True):
    """Write the Stock apply_log.yaml (create=True: only a new file, never over another one)."""
    q=safe_path(base,target_rel+'/'+APPLY_LOG)
    with open(q,'x' if create else 'w') as f:f.write(apply_log_text(layer,c,m))
    return q
def apply_target(c,m):
    """The Stock project folder of an archived box_root_v1 / sheets_v1 package (archive_target, else the earlier projects/<project>)."""
    return (m.get('archive_target') or {}).get('target_rel') or c.get('stock_target_rel')
def apply_box(layer,stock_root=None):
    """(layer, contract, package root, manifest, Stock base, target_rel) of a box that can carry versions; stops otherwise."""
    layer=Path(layer).absolute();c=build_contract(layer);root=safe_path(layer,c['package_root'])
    if c.get('storage')=='registry_stock_v1':raise ValueError('a shared Stock (registry_stock_v1) box has no apply (nothing written)')
    if c.get('layout') not in FLAT_LAYOUTS:raise ValueError('a nested_v1 box has no apply; move it with migrate-sheets first (nothing written)')
    m=load(root/'manifest.yaml');target=apply_target(c,m);base=archive_base_for(layer,target,stock_root)   # the Layer for a where: layer box
    if base is None:raise ValueError('repository root holding Stock/programs not found; pass --stock-root (nothing written)')
    if not target or not any(isinstance(r,dict) and r.get('archive_path') for r in m.get('records',[])):raise ValueError('the box is not archived yet; archive it first (nothing written)')
    return layer,c,root,m,base,target

def register(layer,*,apply=False,approval_ref=None,stock_root=None):
    """(stage 1): record the Stock copy of an archived box as version 1 (kind register): one applies[] entry in
    the manifest and a new apply_log.yaml in the Stock project folder. Nothing else changes (documents, records, sha256,
    receipts, evidence). Dry-run unless apply; apply needs approval_ref. Stops (nothing written) unless final passes, every
    Stock copy has its recorded archive_sha256, the box has no applies yet and the Stock has no apply_log. On a failure the
    manifest bytes come back and the new apply_log is removed."""
    from validate_package import validate
    layer,c,root,m,base,target=apply_box(layer,stock_root)
    if 'applies' in m:raise ValueError('the box already has versions (applies); register is only for a box archived before them (nothing written)')
    before=validate(root,phase='final',layer=layer,stock_root=base)
    if not before['pass']:raise ValueError('final does not pass before register; fix that first (nothing written): '+'; '.join(e['code']+' '+e['path'] for e in before['errors'][:3]))
    for r in m['records']:
        rel=r.get('archive_path')
        if not rel:continue
        if not rel.startswith(target+'/documents/'):raise ValueError('archive_path outside '+target+': '+rel+' (nothing written)')
        q=safe_path(base,rel)
        if not q.is_file() or sha(q)!=r.get('archive_sha256') or r.get('archive_sha256')!=r.get('sha256'):raise ValueError('Stock copy missing or different from the record: '+rel+' (nothing written)')
    log=safe_path(base,target+'/'+APPLY_LOG)
    if log.exists():raise ValueError('the Stock already has '+target+'/'+APPLY_LOG+' but the box has no versions; they disagree, check by hand (nothing written)')
    entry=apply_entry(m,'register',approval_ref,target)
    out={'route':'aipm','apply':bool(apply),'version':1,'kind':'register','documents':len(entry['docs']),'apply_log':target+'/'+APPLY_LOG,'stock_target_rel':target}
    if not apply:return out
    if not isinstance(approval_ref,str) or not approval_ref.strip():raise ValueError('--apply needs --approval-ref (the person\'s approval of registering this box; nothing written)')
    manifest_bytes=(root/'manifest.yaml').read_bytes();m['applies']=[entry];made=False
    try:
        write_apply_log(layer,root,c,m,base,target);made=True
        (root/'manifest.yaml').write_text(yaml.safe_dump(m,allow_unicode=True,sort_keys=False))
        after=validate(root,phase='final',layer=layer,stock_root=base)
        if not after['pass']:raise ValueError('final fails after register: '+'; '.join(e['code']+' '+e['path']+' '+e['message'] for e in after['errors'][:3]))
    except BaseException as ex:
        (root/'manifest.yaml').write_bytes(manifest_bytes)
        if made:log.unlink(missing_ok=True)
        raise ValueError('register stopped ('+type(ex).__name__+': '+str(ex)+'); the manifest and the Stock are as before') from ex
    out['final']=after
    return out

def outside_sources(c,m):
    """the sources outside the package a final check binds by sha256: layer source reads (new courses) and
    the evidence rows on Layer files (also the legacy course; receipts and method sources are not snapshotted).
    {id: {path, sha256, mtime_ns}}."""
    pre=c['package_root']+'/';out={}
    for r in m.get('source_reads') or []:
        if isinstance(r,dict) and r.get('domain')=='layer' and isinstance(r.get('path'),str) and not r['path'].startswith(pre):
            out[r['id']]={'path':r['path'],'sha256':r.get('sha256'),'mtime_ns':r.get('source_mtime_ns')}
    for e in m.get('evidence') or []:
        src=e.get('source') if isinstance(e,dict) else None
        if isinstance(src,str) and e.get('id') not in out and e.get('kind')!='user_reported' and not src.startswith((pre,'method_source:')):
            out[e['id']]={'path':src,'sha256':e.get('source_sha256'),'mtime_ns':None}
    return out
def snapshot_sources(layer,input_path=None,*,apply=False,approval_ref=None,stock_root=None):
    """a source outside the box that changed after archive (e.g. a Layer memo edited later with the
    person's approval) breaks final, so register / apply stop. Without input: list those sources (read only). With input
    (sources: [{id, bytes: <path of the archive-time bytes>, from: <where they came from, e.g. a git commit>}]): place each as
    <package>/source_snapshots/external/<path> with the same bytes, only when they have the recorded sha256, and record
    source_snapshots[id] and source_snapshot_log. Dry-run unless apply (needs approval_ref). The current source files are
    never changed. On a worse final, an exception or Ctrl-C, everything written is put back."""
    from validate_package import validate
    layer,c,root,m,base,target=apply_box(layer,stock_root)
    pre=c['package_root']+'/';log={x.get('id'):x for x in m.get('source_snapshot_log') or [] if isinstance(x,dict)}
    srcs=outside_sources(c,m);drift=[]
    for sid,x in srcs.items():
        try:q=safe_path(layer,x['path'])
        except ValueError as ex:drift.append({'id':sid,'path':x['path'],'recorded_sha256':x['sha256'],'now_sha256':None,'unsafe':str(ex)});continue   # listed, never copied
        now=sha(q) if q.is_file() else None
        if now!=x['sha256'] and sid not in log:drift.append({'id':sid,'path':x['path'],'recorded_sha256':x['sha256'],'now_sha256':now})
    archived_at=next((st.get('finished_at') for st in m.get('stages') or [] if isinstance(st,dict) and st.get('name')=='archive'),None)
    out={'route':'aipm','changed_sources':drift,'archived_at':archived_at}
    if input_path is None:return out
    data=load(safe_path(layer,input_path))
    if not isinstance(data,dict) or not isinstance(data.get('sources'),list) or not data['sources']:raise ValueError('the input needs a sources list (nothing written)')
    want={d['id']:d for d in drift};plan=[]
    for n,x in enumerate(data['sources'],1):
        if not isinstance(x,dict) or x.get('id') not in srcs:raise ValueError('source '+str(n)+': '+repr(x.get('id') if isinstance(x,dict) else x)+' is not a source outside the box (nothing written)')
        sid=x['id']
        if any(pl[0]==sid for pl in plan):raise ValueError(sid+' is given twice (nothing written)')
        if sid not in want:raise ValueError(sid+' has not changed since archive or already has a copy (nothing written)')
        if 'unsafe' in want[sid]:raise ValueError(sid+': its recorded path is unsafe ('+want[sid]['unsafe']+'); nothing written')
        b=x.get('bytes')
        if not isinstance(b,str) or not b:raise ValueError(sid+': bytes (the path of the archive-time bytes) is required (nothing written)')
        bq=Path(b) if Path(b).is_absolute() else safe_path(layer,b)
        if not bq.is_file() or bq.is_symlink():raise ValueError(sid+': bytes file not found: '+b+' (nothing written)')
        if sha(bq)!=srcs[sid]['sha256']:raise ValueError(sid+': the bytes do not have the recorded sha256 (not the archive-time version; nothing written)')
        rel=pre+'source_snapshots/external/'+srcs[sid]['path'];dq=safe_path(layer,rel)
        same=[pl for pl in plan if pl[2]==rel]
        if same and srcs[same[0][0]]['sha256']!=srcs[sid]['sha256']:raise ValueError(sid+' and '+same[0][0]+' read '+srcs[sid]['path']+' with different recorded sha256; one copy cannot serve both (nothing written)')
        if dq.exists() and (dq.is_symlink() or not dq.is_file() or sha(dq)!=srcs[sid]['sha256']):raise ValueError(rel+' already exists with other bytes (nothing written)')
        plan.append((sid,bq,rel,dq,x.get('from')))   # several ids (evidence rows) on one file share one copy
    out['copies']=[{'id':sid,'to':rel} for sid,bq,rel,dq,frm in plan]
    out['apply']=bool(apply)
    if not apply:return out
    if not isinstance(approval_ref,str) or not approval_ref.strip():raise ValueError('--apply needs --approval-ref (the person\'s approval of these copies; nothing written)')
    before=validate(root,phase='final',layer=layer,stock_root=base)
    mp=root/'manifest.yaml';saved=(mp.read_bytes(),mp.stat().st_mtime_ns);made=[];dirs=[]
    try:
        for sid,bq,rel,dq,frm in plan:
            if not dq.exists():   # a copy already there with the recorded bytes (another id on the same file) is reused
                for d in reversed([x for x in (dq.parent,*dq.parent.parents) if root in x.parents and not x.exists()]):d.mkdir();dirs.append(d)
                with open(dq,'xb') as f:made.append(dq);f.write(bq.read_bytes())
                t=srcs[sid]['mtime_ns']
                if type(t) is int:os.utime(dq,ns=(t,t))
            if sha(dq)!=srcs[sid]['sha256']:raise ValueError('the copy of '+sid+' changed while writing')
            m.setdefault('source_snapshots',{})[sid]=rel
            m.setdefault('source_snapshot_log',[]).append({'id':sid,'path':srcs[sid]['path'],'sha256':srcs[sid]['sha256'],'at':datetime.now(timezone.utc).isoformat(),'approval_ref':approval_ref,**({'from':frm} if frm else {})})
        mp.write_text(yaml.safe_dump(m,allow_unicode=True,sort_keys=False))
        after=validate(root,phase='final',layer=layer,stock_root=base)
        key=lambda e:(e['code'],e['path'],e['message'])
        worse={key(e) for e in after['errors']}-{key(e) for e in before['errors']}
        if worse:raise ValueError('final is worse after the copies: '+'; '.join(' '.join(e) for e in sorted(worse)[:3]))
    except BaseException as ex:
        mp.write_bytes(saved[0]);os.utime(mp,ns=(saved[1],saved[1]))
        for q in made:q.unlink(missing_ok=True)
        for d in reversed(dirs):
            with contextlib.suppress(OSError):d.rmdir()
        raise ValueError('snapshot-sources stopped ('+type(ex).__name__+': '+str(ex)+'); the box is as before') from ex
    out['final']=after
    return out

def clone(layer,*,stock_root=None):
    """(stage 2): check that the box and the Stock hold the same last pushed version and write the work base
    Context/aipm_changes/base_<project>.yaml (that version and the Stock sha256 of each document, checked again before push).
    Documents are never copied into the box: a Stock newer than the box means another checkout applied and pushed, so the
    Flow of the owner Layer is pulled with git instead. Stops (nothing written) when the box has no versions, an unpushed
    version, documents changed since the last version, a Stock apply_log that differs, a Stock document that differs, or
    another base already. The same base again writes nothing."""
    layer,c,root,m,base,target=apply_box(layer,stock_root)
    applies=m.get('applies')
    if not isinstance(applies,list) or not applies:raise ValueError('the box has no versions; run register first (nothing written)')
    if any(not a.get('pushed') for a in applies):raise ValueError('the box has a version not pushed yet; push it or revert it first (nothing written)')
    last=applies[-1];docs=last.get('docs') or {}
    box_now={r['path']:sha(safe_path(root,r['path'])) if safe_path(root,r['path']).is_file() else None for r in m['records'] if r.get('archive_path')}
    if box_now!=docs or apply_docs(m)!=docs:raise ValueError('the box documents differ from version '+str(last['version'])+' (changes not applied: '+', '.join(sorted(k for k in set(box_now)|set(docs) if box_now.get(k)!=docs.get(k)))[:300]+'); apply or undo them first (nothing written)')
    q=safe_path(base,target+'/'+APPLY_LOG)
    if not q.is_file():raise ValueError('the Stock has no '+target+'/'+APPLY_LOG+'; the box and the Stock disagree (nothing written)')
    log_data=load(q) or {}
    if log_data.get('project')!=c['bindings']['project_id'] or (log_data.get('box') or {}).get('scope_id')!=c['scope_id']:raise ValueError('the Stock apply_log belongs to another box (project / scope_id); check by hand (nothing written)')
    stock_versions=log_data.get('versions') or []
    box_versions=[{k:a.get(k) for k in LOG_KEYS} for a in applies]
    if stock_versions!=box_versions:
        newer=bool(stock_versions) and isinstance(stock_versions[-1],dict) and isinstance(stock_versions[-1].get('version'),int) and stock_versions[-1]['version']>last['version'] and stock_versions[:len(box_versions)]==box_versions
        if newer:raise ValueError('the Stock holds version '+str(stock_versions[-1]['version'])+', newer than the box (version '+str(last['version'])+'): another checkout applied and pushed it; pull the Flow of the owner Layer with git first (nothing written)')
        raise ValueError('the Stock apply_log and the box versions disagree (one was edited by hand?); check by hand (nothing written)')
    by_path={r['path']:r['archive_path'] for r in m['records'] if r.get('archive_path')}
    stock_docs={}
    for rel,h in docs.items():
        sq=safe_path(base,by_path[rel])
        stock_docs[rel]=sha(sq) if sq.is_file() else None
        if stock_docs[rel]!=h:raise ValueError('the Stock document differs from version '+str(last['version'])+': '+by_path[rel]+' (changed outside apply?; nothing written)')
    project=c['bindings']['project_id'];bq=safe_path(layer,'Context/aipm_changes/base_'+slug(project,'project')+'.yaml')
    data={'project':project,'version':last['version'],'stock_target_rel':target,'docs':stock_docs}
    out={'route':'aipm','base':str(bq.relative_to(layer)),'version':last['version'],'documents':len(stock_docs),'written':False}
    if bq.exists():
        old=load(bq) or {}
        if {k:old.get(k) for k in data}==data:return out   # the same base again: nothing to write
        raise ValueError('another base is open: '+out['base']+' (version '+str(old.get('version'))+'); finish or revert that apply first (nothing written)')
    bq.parent.mkdir(parents=True,exist_ok=True)
    with open(bq,'x') as f:f.write(yaml.safe_dump({**data,'cloned_at':datetime.now(timezone.utc).isoformat()},allow_unicode=True,sort_keys=False))
    out['written']=True
    return out

REGISTRY_DB_REL='.claude/db/ai_plc.db'   # the Registry of the repository that holds Stock/programs (read only here)
def business_folder(name):
    """The Stock folder of a business project: its Registry display name in NFC (macOS file names come back in NFD), with
    each ':' replaced by the full-width '：' (U+FF1A): only ':' is replaced (A:B →
    A：B; Windows/OneDrive, where the Stock may be backed up, cannot hold it; the other such characters are left as they are),
    and each '/' by the full-width '／' (U+FF0F: 「FAQ/RAG」→「FAQ／RAG」). Refused (nothing written) when the name still cannot be one
    folder name: '\\', control and invisible characters, a leading '.', a leading/trailing space or trailing '.'."""
    if not isinstance(name,str):raise ValueError('business project display name must be a string (nothing written)')
    n=unicodedata.normalize('NFC',name).replace(':','\uff1a').replace('/','\uff0f')
    bad=(not n.strip() or n in ('.','..') or n.startswith('.') or n!=n.strip() or n.endswith('.') or len(n.encode())>255
         or any(ch in '/\\' or unicodedata.category(ch) in ('Cc','Cf','Zl','Zp') for ch in n))
    if bad:raise ValueError('business project display name cannot be a folder name: '+repr(name)+' (rename it in the Registry; nothing written)')
    return n
def folder_key(name):
    """What two folder names share on a case-insensitive file system (None when the name cannot be a folder)."""
    try:return business_folder(name).casefold()
    except ValueError:return None
def archive_business(layer,base,program,registry_db=None):
    """box_root_v1 archive target: the Layer's primary (confirmed) business project in the Registry of base (or the
    explicit registry_db), opened read only. Stops (nothing written) when the Layer has no Registry row or no primary,
    the business is not active, its Program is not stock:<program>, another active business of that Program has the same
    folder name, or the intent membership names another business/Program."""
    d=intent(Path(layer).absolute());scope=d.get('scope_id')
    if not isinstance(scope,str) or not scope or scope.startswith('pending:'):raise ValueError('archive needs a Registry scope_id in intent.yaml (now '+repr(scope)+'); register the Layer and decide its business project first (nothing written)')
    db=Path(registry_db).absolute() if registry_db is not None else base/REGISTRY_DB_REL
    if not db.is_file():raise ValueError('Registry not found: '+str(db)+' (pass --registry-db; nothing written)')
    con=sqlite3.connect('file:'+urllib.request.pathname2url(str(db.resolve()))+'?mode=ro',uri=True)
    try:
        con.execute('PRAGMA query_only=ON')
        rows=con.execute('SELECT id FROM projects WHERE scope_id=?',(scope,)).fetchall()
        if len(rows)!=1:raise ValueError('Registry has '+str(len(rows))+' projects rows for '+scope+' (nothing written)')
        links=con.execute("SELECT workspace_id,business_uid FROM business_project_links WHERE project_id=? AND relation_type='primary' AND state='confirmed'",(rows[0][0],)).fetchall()
        if len(links)!=1:raise ValueError(scope+' has no primary business project in the Registry; decide and reflect its membership first (nothing written)')
        ws,uid=links[0]
        biz=con.execute('SELECT display_name,state FROM business_projects WHERE workspace_id=? AND business_uid=?',(ws,uid)).fetchone()
        if biz is None or biz[1]!='active':raise ValueError('primary business project '+uid+' is not active (nothing written)')
        progs=con.execute("SELECT p.program_uid,p.definition_key,p.state FROM program_memberships m JOIN programs p ON p.workspace_id=m.workspace_id AND p.program_uid=m.program_uid WHERE m.workspace_id=? AND m.business_uid=? AND m.target_kind='business_project' AND m.state='confirmed'",(ws,uid)).fetchall()
        if len(progs)!=1 or progs[0][2]!='active' or progs[0][1]!='stock:'+program:raise ValueError('business project '+uid+' does not belong to the Program stock:'+program+' (nothing written)')
        folder=business_folder(biz[0])
        same=con.execute("SELECT b.display_name FROM program_memberships m JOIN business_projects b ON b.workspace_id=m.workspace_id AND b.business_uid=m.business_uid WHERE m.workspace_id=? AND m.program_uid=? AND m.target_kind='business_project' AND m.state='confirmed' AND b.state='active' AND b.business_uid<>?",(ws,progs[0][0],uid)).fetchall()
        if any(folder_key(x[0])==folder.casefold() for x in same):raise ValueError(   # one folder after NFC, '：' and casefold
'another active business project of '+program+' has the folder name '+folder+' (nothing written)')
    finally:con.close()
    mem=d.get('membership')
    if mem is not None and not isinstance(mem,dict):raise ValueError('intent membership must be a map (nothing written)')
    if isinstance(mem,dict) and any(mem.get(k) not in (None,v) for k,v in (('business_uid',uid),('program_uid',progs[0][0]),('workspace_id',ws))):
        raise ValueError('intent membership differs from the Registry primary '+uid+' (nothing written)')
    project=build_contract(layer)['bindings']['project_id']
    return {'scope_id':scope,'workspace_id':ws,'program_uid':progs[0][0],'business_uid':uid,'business_display_name':unicodedata.normalize('NFC',biz[0]),'business_name':folder,
            'target_rel':STOCK_PROGRAMS+'/'+program+'/projects/'+folder+'/'+project,'resolved_at':datetime.now(timezone.utc).isoformat(),'source':'registry_read_only'}

def move_archive(layer,*,apply=False,stock_root=None,registry_db=None,approval_ref=None):
    """move the Stock copies of an archived box_root_v1 package to where archive would put
    them now (Stock/programs/<program>/projects/<business>/<project>/documents/, the primary read only from the Registry),
    e.g. a copy made before the business project path, or a copy left under an old business name. Dry-run unless apply; apply
    needs approval_ref (the person's approval of this box). Every file keeps its bytes and mtime (rename), its sha256 is
    checked against the record before and after, nothing is overwritten, and on a failure every moved file goes back.
    The manifest gets the new archive_path, a fresh archive_target and one archive_moves entry; final runs at the end.
    Nothing is committed (the Program repository and the Flow Layer are committed by the person)."""
    from validate_package import validate
    layer=Path(layer).absolute();c=build_contract(layer);root=safe_path(layer,c['package_root'])
    if c.get('layout') not in FLAT_LAYOUTS or c.get('storage')=='registry_stock_v1':raise ValueError('move-archive is for box_root_v1 / sheets_v1 packages archived to the repository Stock (nothing written)')
    before=validate(root,phase='final',layer=layer,stock_root=stock_root)
    if not before['pass']:raise ValueError('final does not pass before the move; fix that first (nothing written): '+'; '.join(e['code']+' '+e['path'] for e in before['errors'][:3]))
    settings=archive_settings(layer,stock_root)
    if settings['where']!='stock':raise ValueError('move-archive moves copies in the repository Stock; aipm_archive.where is layer (nothing written)')
    base=stock_root_of(layer,stock_root)
    if base is None:raise ValueError('repository root holding Stock/programs not found; pass --stock-root (nothing written)')
    m=load(root/'manifest.yaml');old=(m.get('archive_target') or {}).get('target_rel') or c['stock_target_rel']
    if str(old or '').startswith(LAYER_ARCHIVE+'/'):raise ValueError('the copies are in the Layer ('+old+'); move-archive moves Stock copies only (nothing written)')
    if 'applies' in m:raise ValueError('the box has versions (applies); move-archive does not move the apply_log, so it stops (nothing written)')
    target=archive_target_of(layer,base,c['bindings']['program_id'],settings,registry_db)
    if target['target_rel']==old:raise ValueError('the copies are already at '+old+' (nothing written)')
    moves=[]
    for r in m['records']:
        rel=r.get('archive_path')
        if not rel:continue
        if not rel.startswith(old+'/documents/'):raise ValueError('archive_path outside '+old+': '+rel+' (nothing written)')
        new=target['target_rel']+rel[len(old):];src=safe_path(base,rel);dst=safe_path(base,new)
        if not src.is_file() or sha(src)!=r.get('archive_sha256'):raise ValueError('copy missing or changed: '+rel+' (nothing written)')
        if dst.exists():raise ValueError('destination already exists: '+new+' (nothing written)')
        moves.append((r,rel,new,src,dst))
    out={'route':'aipm','apply':bool(apply),'from':old,'to':target['target_rel'],'business_uid':target['business_uid'],'business_display_name':target['business_display_name'],
         'moves':[{'from':rel,'to':new,'sha256':r['archive_sha256']} for r,rel,new,src,dst in moves]}
    if not apply:return out
    if not isinstance(approval_ref,str) or not approval_ref.strip():raise ValueError('--apply needs --approval-ref (the person\'s approval of this box; nothing written)')
    manifest_bytes=(root/'manifest.yaml').read_bytes();done=[];made=[]
    try:
        for r,rel,new,src,dst in moves:
            for d in reversed([p for p in (dst.parent,*dst.parent.parents) if not p.exists()]):d.mkdir();made.append(d)
            os.rename(src,dst);done.append((src,dst))
            if sha(dst)!=r['archive_sha256']:raise ValueError('hash changed while moving '+rel)
        for r,rel,new,src,dst in moves:r['archive_path']=new
        m['archive_target']=target
        m.setdefault('archive_moves',[]).append({'from':old,'to':target['target_rel'],'moved_at':datetime.now(timezone.utc).isoformat(),'approval_ref':approval_ref,'files':len(moves)})
        (root/'manifest.yaml').write_text(yaml.safe_dump(m,allow_unicode=True,sort_keys=False))
    except BaseException as ex:   # Ctrl-C too: put everything back before stopping
        stuck=[]
        for src,dst in reversed(done):
            try:os.rename(dst,src)
            except OSError:stuck.append(str(dst)+' -> '+str(src))
        for d in reversed(made):
            with contextlib.suppress(OSError):d.rmdir()
        try:(root/'manifest.yaml').write_bytes(manifest_bytes);manifest_ok=True
        except OSError:manifest_ok=False
        if stuck or not manifest_ok:
            raise ValueError('move stopped ('+type(ex).__name__+': '+str(ex)+'); NOT all put back: '+str(len(stuck))+' files still at the new place (new -> where it belongs: '+'; '.join(stuck)+')'+('' if manifest_ok else '; manifest not restored')+'; nothing is lost, fix by hand') from ex
        raise ValueError('move stopped ('+type(ex).__name__+': '+str(ex)+'); every moved file was put back') from ex
    stop=base/STOCK_PROGRAMS/c['bindings']['program_id']/'projects'   # remove the old folders left empty, never above projects/
    for src,dst in done:
        d=src.parent
        while d!=stop and stop in d.parents:
            try:d.rmdir()
            except OSError:break
            d=d.parent
    out['final']=validate(root,phase='final',layer=layer,stock_root=base)
    return out

def archive_to_stock(layer,root,plan):
    """Copy each (record, dest, path) of plan into the real Stock. A file is only created, never overwritten (another
    writer that made it first stops the copy). On any failure the files this call made are moved, not deleted, to
    Documents/aipm_retired/<time>_archive_failed/ of the Layer and the folders it made (left empty) are removed, so the
    Stock is as before; the records are updated only when every copy is done."""
    made=[];dirs=[]
    try:
        for r,dest,q in plan:
            for d in reversed([p for p in (q.parent,*q.parent.parents) if not p.exists()]):d.mkdir();dirs.append(d)
            src=safe_path(root,r['path'])
            with open(q,'xb') as f:made.append((dest,q));f.write(src.read_bytes())
            shutil.copystat(src,q)
    except Exception as ex:
        stamp='Documents/aipm_retired/'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'_archive_failed';retired=stamp;n=1
        while safe_path(layer,retired).exists():n+=1;retired=stamp+'_'+str(n)   # never move onto an earlier retired copy
        for dest,q in made:
            t=safe_path(layer,retired+'/'+dest);t.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(q),str(t))
        for d in reversed(dirs):
            with contextlib.suppress(OSError):d.rmdir()
        raise ValueError('archive stopped while copying ('+type(ex).__name__+': '+str(ex)+'); '+(str(len(made))+' partial copies moved to '+retired if made else 'nothing written'))
    for r,dest,q in plan:r.update(status='archived_local_final',archive_path=dest,archive_sha256=sha(q))

def build_contract(layer,*,layout_override=None,program_override=None,program_wins=False):
    """layout_override/program_override: migrate-layout builds the box_root_v1 contract of a saved nested_v1 package
    (nothing else passes them). program_wins: migrate-sheets of a nested_v1 package, where the program the person chose
    replaces an intent program_id (the move rewrites intent to it)."""
    layer=Path(layer).absolute();d=intent(layer)
    if not select(layer): raise ValueError('AIPM not explicitly selected')
    a=d.get('aipm',{})
    if not isinstance(a,dict): raise ValueError('aipm must be map')
    chosen=course_id(layer)
    scope=slug(d.get('scope_id'),'scope_id');project=slug(a.get('project_id',d.get('scope_name',scope)),'project_id')
    day=a.get('date')
    saved=saved_contract(layer)
    saved_c=load(saved) if saved.is_file() else None
    if not isinstance(saved_c,dict):saved_c={}
    if day is None and saved_c: day=saved_c.get('bindings',{}).get('date')
    if day is None:
        day=next((x.name for x in layer.parents if re.fullmatch(r'\d{4}-\d{2}-\d{2}',x.name)),date.today().isoformat())
    day=date.fromisoformat(str(day)).isoformat()
    layout=layout_override or package_layout(a,saved_c if saved.is_file() else None)
    if saved.is_file() and layout_override is None and (saved.parent.name==SHEETS_ROOT)!=(layout==SHEETS_LAYOUT):raise ValueError('saved format_contract.yaml at '+str(saved.relative_to(layer))+' does not match its layout '+layout+' (nothing written)')
    if program_wins and program_override is not None:program=slug(program_override,'program_id')
    elif layout==NESTED_LAYOUT or 'program_id' in a:program=slug(a.get('program_id',scope.replace('-','_')),'program_id')
    elif program_override is not None:program=slug(program_override,'program_id')
    elif saved.is_file() and isinstance(saved_c.get('bindings'),dict) and saved_c.get('layout') in FLAT_LAYOUTS:program=saved_c['bindings'].get('program_id','[unknown]');program=program if program=='[unknown]' else slug(program,'program_id')   # the saved program wins, like the layout
    else:program='[unknown]'   # box_root: no L_xxxx default (archive needs an explicit program)
    bindings={'program_id':program,'project_id':project,'participant_name':str(d.get('owner') or '[unknown]'),'flow_dir':project,'date':day,'persona_id':slug(a.get('persona_id','P001'),'persona_id'),'name_slug':slug(a.get('name_slug','user'),'name_slug'),'type':'user'}
    if not re.fullmatch(r'P\d+',bindings['persona_id']): raise ValueError('persona_id must be P plus digits')
    c=copy.deepcopy(load(METHOD/'format_schema.yaml'))
    c.pop('local_courses',None)  # Legacy contract bytes/values remain unchanged.
    if chosen!=LEGACY_COURSE:
        registry=course_registry();c.update(course_id=chosen,course=registry['courses'][chosen]['stages'],version=c['version']+'+courses.1',course_contract_version=registry['version'],course_contract_sha256=sha(METHOD/'course_contracts.yaml'))
    registers=a.get('registers',False)
    if not isinstance(registers,bool): raise ValueError('aipm.registers must be true or false')
    if registers:
        rq=registers_contract_path(saved_c.get('registers_contract_version'))   # a saved package keeps its version; a new Layer gets the latest
        rc=load(rq);c.update(version=c['version']+rc['contract_suffix'],registers_contract_version=rc['version'],registers_contract_sha256=sha(rq))
    if c['reviewed_commit']!=COMMIT or load(METHOD/'canonical.yaml')['reviewed_commit']!=COMMIT: raise ValueError('fixed commit mismatch')
    c.update(scope_id=scope,bindings=bindings,package_root=SHEETS_ROOT if layout==SHEETS_LAYOUT else LEGACY_ROOT,flow_rel='Flow/'+day[:7].replace('-','')+'/'+day+'/'+project,stock_project_rel=STOCK_PROGRAMS+'/'+bindings['program_id']+'/projects/'+project)
    if layout in FLAT_LAYOUTS:
        # The 19 documents, project_init.yaml and README.md sit directly in the package (sheets_v1: in Sheets/ with the registers too); nothing is written to Stock until
        # archive, which copies to the real repository Stock/programs/<program>/projects/<business>/<project> (stock_target_rel stays
        # projects/<project>: the business folder is read from the Registry at archive time and recorded in manifest.archive_target).
        c.update(layout=layout,version=c['version']+('+box_root.1' if layout==BOX_ROOT_LAYOUT else '+sheets.1'),flow_rel='',stock_project_rel='',stock_target_rel=None if program=='[unknown]' else STOCK_PROGRAMS+'/'+program+'/projects/'+project)
    for e in c['documents']:e['path']=e['path'].format(**bindings)
    c['id_mapping']['persona']=bindings['persona_id']
    storage=a.get('storage','legacy_internal')
    if storage not in ('legacy_internal','registry_stock_v1'):
        raise ValueError('unknown AIPM storage choice')
    if storage=='registry_stock_v1':
        selector=a.get('stock_selector')
        if not isinstance(selector,dict) or set(selector)!={'workspace_id','read_domain','program_uid','business_uid'} or any(not isinstance(v,str) or not v for v in selector.values()):
            raise ValueError('explicit Registry stable Stock selector required')
        uid=a.get('aiplc_uid')
        if not isinstance(uid,str) or not uid:raise ValueError('explicit AI-PLC sync UID required')
        c.update(storage=storage,stock_selector=selector,aiplc_uid=uid)
        # Charter remains a Flow draft until archive. This is NOT a Stock folder (box_root_v1: <package>/_charter).
        c['stock_project_rel']=pkg_rel(c['flow_rel'],'_charter')
        if layout in FLAT_LAYOUTS:c['stock_target_rel']=None   # the Registry binding is the shared destination, not a Stock path
    return c

NESTED_LAYOUT='nested_v1'      # the package holds Flow/<YYYYMM>/<date>/<project>/ and Stock/programs/<program>/projects/<project>/ inside it
BOX_ROOT_LAYOUT='box_root_v1'  # the documents sit directly in Documents/aipm_project/; Stock is the real repository Stock, at archive only
SHEETS_LAYOUT='sheets_v1'      # like box_root_v1, but the package is <Layer>/Sheets/ (beside Context/ and Documents/) and the
                               # registers sit directly in it, no registers/ folder
FLAT_LAYOUTS=(BOX_ROOT_LAYOUT,SHEETS_LAYOUT)   # the documents sit directly in the package; Stock only at archive
DEFAULT_LAYOUT=SHEETS_LAYOUT   # new packages, shared Stock (registry_stock_v1) included (before: box_root_v1)
LEGACY_ROOT='Documents/aipm_project'   # the package of nested_v1 and box_root_v1
SHEETS_ROOT='Sheets'                   # the package of sheets_v1 (exact case: Context/, Documents/, Agents/ are capitalised too)
def saved_contract(layer):
    """The saved format_contract.yaml of the Layer's package: Sheets/ (sheets_v1) or Documents/aipm_project/ (the earlier
    layouts). The path is returned even when it does not exist (the one a new package of the default layout would use).
    Stops when both exist, or when a folder like sheets/ differs from Sheets/ only in case (a case-insensitive file
    system would open it as Sheets/)."""
    layer=Path(layer).absolute()
    if layer.is_dir() and any(x.name!=SHEETS_ROOT and x.name.casefold()==SHEETS_ROOT.casefold() and (x/'format_contract.yaml').is_file() for x in layer.iterdir()):
        raise ValueError('a package named like '+SHEETS_ROOT+'/ but in another case is in the Layer; rename it to '+SHEETS_ROOT+'/ (nothing written)')
    new=safe_path(layer,SHEETS_ROOT+'/format_contract.yaml');old=safe_path(layer,LEGACY_ROOT+'/format_contract.yaml')
    if new.is_file() and old.is_file():raise ValueError('both '+SHEETS_ROOT+'/ and '+LEGACY_ROOT+'/ hold a format_contract.yaml; keep one package (nothing written)')
    return old if old.is_file() else new
def package_layout(a,saved_c):
    """The folder layout of the package. A saved format_contract keeps its own (no layout key = nested_v1, the packages
    made before box_root_v1; an empty or non-map saved file also reads as nested_v1, the side that changes nothing);
    a new package gets aipm.layout or DEFAULT_LAYOUT.
    A saved and an explicit layout that differ stop."""
    want=a.get('layout')
    if want is not None and want not in (NESTED_LAYOUT,BOX_ROOT_LAYOUT,SHEETS_LAYOUT):raise ValueError('aipm.layout must be '+NESTED_LAYOUT+', '+BOX_ROOT_LAYOUT+' or '+SHEETS_LAYOUT)
    if saved_c is not None:
        have=saved_c.get('layout',NESTED_LAYOUT) if isinstance(saved_c,dict) else NESTED_LAYOUT
        if want is not None and want!=have:raise ValueError('aipm.layout '+want+' differs from the saved package layout '+have+'; keep the saved layout (moving a package is a separate, approved step), do not rewrite intent')
        return have
    return want or DEFAULT_LAYOUT
def pkg_rel(base,path):
    """Package-relative path of path under base ('' = the package itself, box_root_v1)."""
    return base+'/'+path if base else path
# ---- where the archive copies go: .ai-plc/config.yaml, section aipm_archive ----
STOCK_PROGRAMS='Stock/programs'          # the programs folder of a repository Stock (the one place this path is built from)
LAYER_ARCHIVE='Documents/aipm_archive'   # where: layer — the archive copies inside the Layer (no Stock, no Registry)
ARCHIVE_WHERE=('auto','stock','layer');ARCHIVE_BUSINESS=('registry','none')
def repo_candidates(layer,explicit=None):
    """The folders that may be the repository root of the Layer, in order: the explicit one (--stock-root) alone, else the
    parent of the Flow folder that holds the Layer, then the superproject named by the .git file of the Flow checkout or
    worktree the Layer is in. Read from files only (no git command)."""
    if explicit is not None:return [Path(explicit).absolute()]
    layer=Path(layer).absolute();found=[]
    flow=next((x for x in layer.parents if x.name=='Flow'),None)
    if flow is not None:found.append(flow.parent)
    for x in (layer,*layer.parents):
        g=x/'.git'
        if g.is_dir():found.append(x);break
        if g.is_file():
            text=g.read_text(errors='replace').strip()
            if text.startswith('gitdir:'):
                gitdir=(x/text[len('gitdir:'):].strip()).resolve().as_posix()
                if '/.git/' in gitdir:found.append(Path(gitdir.split('/.git/')[0]))
            break
    return found
def stock_root_of(layer,explicit=None):
    """The repository root that holds Stock/programs for a box_root_v1 archive: the explicit one (--stock-root), else the
    parent of the Flow folder that holds the Layer, else the superproject named by the .git file of the Flow checkout or
    worktree the Layer is in (a worktree of a Flow submodule points into <repository>/.git/modules/Flow/...).
    Read from files only (no git command). A candidate counts only when it has a Stock/programs folder. None when not found."""
    if explicit is not None:return Path(explicit).absolute()
    return next((q for q in repo_candidates(layer) if (q/STOCK_PROGRAMS).is_dir() and not (q/'Stock').is_symlink()),None)
def archive_settings(layer,stock_root=None):
    """{where, business} from the aipm_archive section of the first .ai-plc/config.yaml among repo_candidates.
    where: auto (default: stock when a repository with Stock/programs is found or a config file exists, else layer) | stock | layer.
    business: registry (default: the Layer's primary business project read only from the Registry, as before) | none
    (no Registry: Stock/programs/<program>/projects/<project>). where: layer never reads the Registry, whatever business says.
    No file or no section = the defaults."""
    sec={};configured=False
    for q in repo_candidates(layer,stock_root):
        f=q/'.ai-plc/config.yaml'
        if f.is_file():
            configured=True
            data=yaml.safe_load(f.read_text()) or {}
            if not isinstance(data,dict):raise ValueError(str(f)+' must be a map (nothing written)')
            sec=data.get('aipm_archive') or {}
            break
    if not isinstance(sec,dict):raise ValueError('aipm_archive in .ai-plc/config.yaml must be a map (nothing written)')
    where=sec.get('where','auto');business=sec.get('business','registry')
    if where not in ARCHIVE_WHERE:raise ValueError('aipm_archive.where must be one of '+', '.join(ARCHIVE_WHERE)+' (nothing written)')
    if business not in ARCHIVE_BUSINESS:raise ValueError('aipm_archive.business must be one of '+', '.join(ARCHIVE_BUSINESS)+' (nothing written)')
    # auto: the Stock when one is found; the Layer only for a repository without .ai-plc/config.yaml (a public copy without a
    # Stock). A configured repository (this one) keeps stopping when its Stock is not found, as before.
    if where=='auto':where='stock' if stock_root_of(layer,stock_root) is not None or configured else 'layer'
    return {'where':where,'business':business}
def archive_base(layer,stock_root=None,settings=None):
    """The folder an archive target_rel is relative to: the Layer for where: layer, else the repository holding the Stock."""
    s=settings or archive_settings(layer,stock_root)
    return Path(layer).absolute() if s['where']=='layer' else stock_root_of(layer,stock_root)
def archive_base_for(layer,target_rel,stock_root=None):
    """The base of a recorded target_rel: the Layer for a Documents/aipm_archive/ copy, else the repository Stock root
    (so a box keeps the place it was archived to, whatever the settings say now)."""
    return Path(layer).absolute() if str(target_rel or '').startswith(LAYER_ARCHIVE+'/') else stock_root_of(layer,stock_root)
def archive_plain(layer,program,settings):
    """An archive target without the Registry (business: none, or where: layer): source config, no business fields."""
    c=build_contract(layer);project=c['bindings']['project_id']
    rel=LAYER_ARCHIVE+'/'+project if settings['where']=='layer' else STOCK_PROGRAMS+'/'+program+'/projects/'+project
    return {'scope_id':str(c.get('scope_id') or ''),'workspace_id':'','program_uid':'','business_uid':'','business_display_name':'','business_name':'',
            'target_rel':rel,'resolved_at':datetime.now(timezone.utc).isoformat(),'source':'config'}
def archive_target_of(layer,base,program,settings,registry_db=None):
    """Where archive puts the copies now: the Registry business project (where: stock, business: registry), else archive_plain."""
    if settings['where']=='stock' and settings['business']=='registry':return archive_business(layer,base,program,registry_db)
    return archive_plain(layer,program,settings)
def init_roots(c):
    """(flow_base, stock_base) that project_init.yaml names: nested_v1 the two inner roots, box_root_v1 the package itself
    and the real Stock target (or [unknown] until a program is given)."""
    if c.get('layout') in FLAT_LAYOUTS:return c['package_root'],(c['package_root']+'/'+c['stock_project_rel'] if c.get('storage')=='registry_stock_v1' else (c['stock_target_rel'] or '[unknown]'))   # shared Stock: the charter staging, Layer-relative like flow_base
    return c['flow_rel'],c['stock_project_rel']
def doc_rel(c,e):
    """Package-relative path of one contract document."""
    return pkg_rel(c['stock_project_rel'] if e.get('side')=='stock_project' else c['flow_rel'],e['path'])

INIT_NOTE='Init 直後の validate は 19文書と manifest が無いので E_MISSING で不合格になるのが正常。registers だけ見るなら E_REGISTERS の件数を見る'
RESET_NOTE='残った受領記録は古い対象を指すので、聞き直すときは新しい question_id を使う'
DRAFT_ITEM_KEYS={'wbs':('deliverable','exit_criteria'),'issues':('question',),'hypotheses':('claim',)}   # plus source_refs (required for wbs)
FLOW_REF=r'^Flow@[0-9a-fA-F]{7,40}:.+$'

def init_documents(layer,c):
    """project_init.yaml and README.md exactly as init writes them; reset-to-init rebuilds them the same way.
    Returns {package-relative path: text} in the order init writes them."""
    b=c['bindings'];initial={k:'[unknown]' for k in c['documents'][-2]['schema']['fields']}
    initial.update(program_id=b['program_id'],project_id=b['project_id'],participant_name=b['participant_name'],flow_dir=b['flow_dir'],flow_base=init_roots(c)[0],stock_base=init_roots(c)[1],period=b['date'],purpose=intent(layer).get('goal',{}).get('description','[unknown]'),share_repo='disabled',share_local_dir='disabled')
    readme='# '+b['project_id']+'\n\n'+''.join('## '+h+'\n\n[unknown] 初期下書き。実根拠を読んで更新する。\n\n' for h in c['documents'][-1]['required_headings'])
    return {pkg_rel(c['flow_rel'],'project_init.yaml'):yaml.safe_dump(initial,allow_unicode=True,sort_keys=False),pkg_rel(c['stock_project_rel'],'README.md'):readme}

def init_drafts_input(layer,c,drafts_path):
    """The optional --drafts YAML that Collection writes from the Goal and Context before init.
    wbs: [{deliverable, exit_criteria, source_refs}] (one or more); optional issues: [{question, source_refs?}] and
    hypotheses: [{claim, source_refs?}]. Any other key (owner, priority, due, schedule, baseline ...) is refused: those stay
    [unknown]/undecided until a person confirms them. Every check runs before init writes anything. No LLM call here."""
    if 'registers_contract_version' not in c:raise ValueError('--drafts needs aipm.registers: true (it only fills the registers drafts)')
    q=safe_path(layer,drafts_path)
    if not q.is_file():raise ValueError('drafts file missing: '+str(drafts_path))
    d=load(q)
    if not isinstance(d,dict) or 'wbs' not in d or set(d)-set(DRAFT_ITEM_KEYS):raise ValueError('drafts must be a map with wbs (required) and optional issues/hypotheses only')
    out={}
    for name,keys in DRAFT_ITEM_KEYS.items():
        if name not in d:continue
        items=d[name]
        if not isinstance(items,list) or not items:raise ValueError('drafts.'+name+' must be a non-empty list')
        rows=[]
        for n,it in enumerate(items,1):
            loc='drafts.'+name+'['+str(n)+']'
            if not isinstance(it,dict):raise ValueError(loc+' must be a map')
            extra=sorted(map(str,set(it)-set(keys)-{'source_refs'}))
            if extra:raise ValueError(loc+' has keys init does not write (owner/priority/due/schedule stay [unknown]/undecided): '+','.join(extra))
            for k in keys:
                if not isinstance(it.get(k),str) or not it[k].strip():raise ValueError(loc+'.'+k+' must be a non-empty string')
            refs=it.get('source_refs')
            if refs is None and name=='wbs':raise ValueError(loc+'.source_refs is required (where the draft came from)')
            if refs is not None:
                if not isinstance(refs,list) or not refs or any(not isinstance(v,str) or not v.strip() for v in refs):raise ValueError(loc+'.source_refs must be a non-empty list of paths')
                for v in refs:
                    if re.fullmatch(FLOW_REF,v):continue
                    try:p=safe_path(layer,v)
                    except ValueError:raise ValueError(loc+'.source_refs must be Layer-relative paths (or Flow@<commit>:<path>): '+v)
                    if not p.exists():raise ValueError(loc+'.source_refs missing: '+v)
            rows.append({**{k:it[k] for k in keys},**({'source_refs':list(refs)} if refs is not None else {})})
        out[name]=rows
    return out

def init(layer, *, stock_runtime=None, drafts=None):
    """drafts: an optional Layer-relative YAML for the registers drafts (see init_drafts_input). Without it the
    registers drafts are byte-for-byte the generic ones from the registers contract."""
    layer=Path(layer).absolute()
    if not select(layer):
        light=_light()   # AIPM ライトモード (aipm-light) is one form of this skill
        if light.is_light(layer):
            if drafts is not None:raise ValueError('--drafts needs aipm.registers (AIPM ライトモード starts with empty sheets)')
            return light.init_light(layer)
        if drafts is not None:raise ValueError('--drafts needs the bundled PM addon (aipm)')
        return {'route':'legacy','created':False}
    c=build_contract(layer);root=safe_path(layer,c['package_root'])
    if 'registers_contract_version' in c and _light().record(layer)[0]==_light().SHEETS_KIND:   # not designed yet
        raise ValueError('Sheets/ holds the two sheets added to this aipm Layer (light_sheets.yaml); turning on aipm.registers over them is not supported yet. Ask before moving their rows (nothing written)')
    adopted=_adopt_light_sheets(layer,c,root,check_only=True)   # aipm-light -> aipm: the two sheets stay as part of the registers; moved only after every check below
    if adopted and drafts is not None:raise ValueError('--drafts is not used when switching from AIPM ライトモード (the two sheets are kept as they are; nothing written)')
    if c.get('layout')==SHEETS_LAYOUT and not root.exists() and safe_path(layer,LEGACY_ROOT).exists():   # never start a Sheets/ box beside an earlier package folder
        raise ValueError(LEGACY_ROOT+'/ is already in the Layer (an earlier package without its contract); move or finish it before a '+SHEETS_ROOT+'/ package (nothing written)')
    if drafts is not None:
        if root.exists():raise ValueError('package already exists; --drafts is only used by the first init (nothing written)')
        parsed=init_drafts_input(layer,c,drafts)
    shared=c.get('storage')=='registry_stock_v1'
    if shared:
        from shared_stock import require_runtime
        require_runtime(stock_runtime,layer).bind(c['stock_selector'])
    if root.exists() and not adopted:
        if not (root/'format_contract.yaml').is_file() or load(root/'format_contract.yaml')!=c:
            raise ValueError('existing Project has another contract; do not overwrite')
        return {'route':'aipm','created':False,'package':str(root),'contract':c,'outputs':existing_outputs(root,c),'note':INIT_NOTE}
    source=json.loads((METHOD/'source/source_manifest.json').read_text())
    for e in source['files']:
        if sha(METHOD/'source'/e['path'])!=e['sha256']: raise ValueError('fixed source changed')
    for e in c['documents']:
        if sha(METHOD/e['raw_template'])!=e['template_sha256']: raise ValueError('fixed template changed')
    if adopted:_adopt_light_sheets(layer,c,root)   # every check passed: move the light record out now
    root.mkdir(parents=True,exist_ok=bool(adopted))
    for base in package_folder_bases(c):
        for folder in c['folders']:safe_path(root,pkg_rel(base,folder)).mkdir(parents=True,exist_ok=True)
    if shared:safe_path(root,c['stock_project_rel']).mkdir(parents=True,exist_ok=True)
    (root/'format_contract.yaml').write_text(yaml.safe_dump(c,allow_unicode=True,sort_keys=False))
    docs=init_documents(layer,c)
    for rel,text in docs.items():(root/rel).write_text(text)
    written=registers_drafts(root,c,parsed if drafts is not None else None) if 'registers_contract_version' in c else []
    made=['format_contract.yaml',*docs]+written
    outputs=[{'path':c['package_root']+'/'+rel,'sha256':sha(root/rel)} for rel in made]  # for intent.mode_init.outputs (01-collection Phase 7.5)
    result={'route':'aipm','created':True,'package':str(root),'state':'initialized_draft','required_documents':19,'contract':c,'registers':written,'outputs':outputs,'note':INIT_NOTE}
    if adopted:
        result['adopted_light_sheets']=adopted   # the kept sheets belong to the registers in mode_init.outputs too
        have={o['path'] for o in outputs}
        result['outputs']=outputs+[{'path':p,'sha256':sha(safe_path(layer,p))} for p in adopted if p not in have]
    if drafts is not None:   # wbs.yaml has no field for where a row came from (registers contract unchanged); keep these in the Collection record
        result.update(drafts=drafts,wbs_source_refs={'W'+str(n):r['source_refs'] for n,r in enumerate(parsed['wbs'],1)})
    return result

def _adopt_light_sheets(layer,c,root,check_only=False):
    """aipm-light -> aipm. When the Layer now selects aipm with aipm.registers and sheets_v1 and
    Sheets/ holds the AIPM ライトモード box (its record and the two sheets only), the light record moves to
    Context/aipm_light_retired/ and init continues in the same folder: the two sheets become part of the registers
    (registers_drafts never overwrites them), the rest of the registers and the init documents are added.
    Returns the kept sheet paths, or None when this is not a switch."""
    light=_light()
    if c.get('layout')!=SHEETS_LAYOUT or 'registers_contract_version' not in c or not light.switch_ready(layer):return None
    kind,q,saved=light.record(layer)
    keep={q.name,*saved['files'].values()}
    other=[x.name for x in root.iterdir() if x.name not in keep and x.name not in light.OS_METAFILES]
    if other:raise ValueError('Sheets/ has more than the AIPM ライトモード box: '+', '.join(sorted(other))+' (nothing written)')
    rc=registers_contract(c)
    for n in light.SHEETS:
        if rc['files'][n]['path']!=saved['files'][n]:raise ValueError('the light sheet '+saved['files'][n]+' is not where the registers keep '+n+' (nothing written)')
    retired=safe_path(layer,'Context/aipm_light_retired/'+q.name)
    if retired.exists():raise ValueError('Context/aipm_light_retired/'+q.name+' already exists; move it first (nothing written)')
    if not check_only:retired.parent.mkdir(parents=True,exist_ok=True);q.rename(retired)
    return [SHEETS_ROOT+'/'+saved['files'][n] for n in light.SHEETS]

def brief_init(result):
    """The init result without the full contract, for the CLI --brief. The function result is unchanged."""
    out={k:result[k] for k in ('route','created','package','state','required_documents','registers','outputs','drafts','wbs_source_refs','note') if k in result}
    if 'contract' in result:
        out['contract_version']=result['contract']['version']
        if 'registers_contract_version' in result['contract']:out['registers_contract_version']=result['contract']['registers_contract_version']
    return out

def existing_outputs(root,c):
    """path/sha256 of the init outputs that already exist (for mode_init.outputs on re-run)."""
    rels=['format_contract.yaml',pkg_rel(c['flow_rel'],'project_init.yaml'),pkg_rel(c['stock_project_rel'],'README.md')]
    if 'registers_contract_version' in c:rels+=[f['path'] for f in registers_contract(c)['files'].values()]
    return [{'path':c['package_root']+'/'+r,'sha256':sha(root/r)} for r in rels if (root/r).is_file()]

def registers_drafts(root,c,given=None):
    """Minimal required-key drafts for aipm.registers. Never overwrite.
    given: checked init_drafts_input; its wbs replaces the generic deliverables and its issues/hypotheses
    (when present) replace I1/H1. owner/priority stay [unknown], due/period undecided, status draft/open/unknown."""
    rc=registers_contract(c);unk='[unknown]'
    base=given['wbs'] if given else rc['init_drafts']['wbs_initial_deliverables']
    wbs=[{'id':'W'+str(n),'deliverable':x['deliverable'],'exit_criteria':x['exit_criteria'],'owner':unk,'status':'draft','schedule':{'baseline':None,'forecast':None,'actual':None,'history':[]},'source_of_truth':'local'} for n,x in enumerate(base,1)]
    issues=[{'id':'I1','question':unk+' 決めるべき問い（Goal と Context から下書きする）','status':'open','priority':unk,'owner':unk,'due':'undecided'}]
    hyps=[{'id':'H1','kind':'opportunity','claim':'[hypothesis] '+unk+' 調査前の Opportunity 仮説（Goal と Context から下書きする）','status':'unknown'}]
    def src(name,x):return {'sources':x['source_refs']} if 'source_refs' in x and 'sources' in rc['files'][name].get('optional',[]) else {}
    if given and 'issues' in given:issues=[{'id':'I'+str(n),'question':x['question'],'status':'open','priority':unk,'owner':unk,'due':'undecided',**src('issues',x)} for n,x in enumerate(given['issues'],1)]
    if given and 'hypotheses' in given:hyps=[{'id':'H'+str(n),'kind':'opportunity','claim':x['claim'],'status':'unknown',**src('hypotheses',x)} for n,x in enumerate(given['hypotheses'],1)]
    drafts={'issues':{'charter':{'change_conditions':[unk],'exit_conditions':[unk]},'issues':issues},
            'hypotheses':{'hypotheses':hyps},
            'todo':{'todo':[]},'wbs':{'wbs':wbs},
            'roadmap':{'roadmap':[{'id':'MS1','milestone':unk+' 最初の関係者提示','period':'undecided','status':'draft'}]}}
    out=[]
    for name,data in drafts.items():
        q=safe_path(root,rc['files'][name]['path'])
        if q.exists():continue
        q.parent.mkdir(parents=True,exist_ok=True);q.write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False));out.append(rc['files'][name]['path'])
    return out

def reset_to_init(layer,*,apply=False,retire=None):
    """Move the 19 documents and the batch records out of the package and put it back to just after
    the Collection Phase 7.5 init, so that draft can run again. New courses only, never after archive. Dry-run unless apply.
    Every check runs before any write; files are only moved (never deleted) to retire, a new Layer folder outside the package.
    format_contract, registers, intent, backlog and Context receipts are not changed."""
    import os
    layer=Path(layer).absolute()
    if not select(layer):raise ValueError('the bundled PM addon (aipm) is not selected')
    c=build_contract(layer)
    if c.get('course_id',LEGACY_COURSE)==LEGACY_COURSE:raise ValueError('reset-to-init is for the new courses only; the legacy course stays on its own route')
    root=safe_path(layer,c['package_root']);pre=c['package_root']+'/'
    if not root.is_dir():raise ValueError('package missing: '+c['package_root'])
    mi=intent(layer).get('mode_init')
    if not isinstance(mi,dict) or mi.get('state')!='done' or not isinstance(mi.get('outputs'),list):raise ValueError('mode_init is not done; only a package started by the Collection Phase 7.5 init can be reset')
    outs={o.get('path'):o.get('sha256') for o in mi['outputs'] if isinstance(o,dict)}
    fc=root/'format_contract.yaml'
    if not fc.is_file() or load(fc)!=c or outs.get(pre+'format_contract.yaml')!=sha(fc):raise ValueError('format_contract.yaml differs from the contract or from mode_init.outputs')
    m=load(root/'manifest.yaml') if (root/'manifest.yaml').is_file() else {}
    if not isinstance(m,dict):raise ValueError('manifest.yaml must be a map')
    stages=[s.get('name') for s in m.get('stages') or [] if isinstance(s,dict)]
    if 'archive' in stages or any(isinstance(r,dict) and r.get('archive_path') is not None for r in m.get('records') or []):raise ValueError('package already archived; reset-to-init is refused')
    recorded={r.get('path'):r.get('sha256') for r in m.get('records') or [] if isinstance(r,dict)}
    registers=[f['path'] for f in registers_contract(c)['files'].values()] if 'registers_contract_version' in c else []
    missing=[r for r in registers if not (root/r).is_file()]
    if missing:raise ValueError('registers file missing: '+', '.join(missing))
    docs=init_documents(layer,c);moves=[];restores=[]
    for rel,text in docs.items():
        if outs.get(pre+rel)!=hashlib.sha256(text.encode('utf-8')).hexdigest():raise ValueError('the rebuilt init draft differs from mode_init.outputs (intent changed after init?): '+rel)
        q=root/rel
        if q.is_symlink():raise ValueError('symlink path refused: '+rel)
        if not q.exists():restores.append(rel);continue
        now=sha(q)
        if now==outs[pre+rel]:continue
        if now!=recorded.get(rel):raise ValueError('edited by hand after init/draft (neither the init nor the recorded batch version): '+rel)
        moves.append(rel);restores.append(rel)
    for n in ('manifest.yaml','validation_record.yaml','validation_checkpoint.yaml'):
        if (root/n).exists():moves.append(n)
    for e in c['documents']:
        if e.get('side'):continue
        rel=pkg_rel(c['flow_rel'],e['path'])
        if (root/rel).exists():moves.append(rel)
    snap=root/'source_snapshots'
    if snap.exists():moves.append('source_snapshots')
    keep={'format_contract.yaml',*docs,*registers}
    for q in root.rglob('*'):
        rel=q.relative_to(root).as_posix()
        if q.is_symlink():raise ValueError('symlink path refused: '+rel)
        if q.is_file() and rel not in keep and rel not in moves and not rel.startswith('source_snapshots/'):raise ValueError('unexpected file in the package (not moved by reset; move or keep it by hand first): '+rel)
    retired={pre+x for x in moves}
    def retired_ref(v):
        if not isinstance(v,str) or re.fullmatch(r'[IH]\d+',v):return False
        v=v.rstrip('/')
        return v in retired or any(v.startswith(x+'/') for x in retired)
    reg_root=root
    for name,key in (('wbs','evidence_refs'),('issues','evidence_refs'),('issues','sources'),('hypotheses','sources')):
        if not registers:break
        spec=registers_contract(c)['files'][name];data=load(reg_root/spec['path']);rows=(data or {}).get(spec.get('list_key',name)) if isinstance(data,dict) else None
        for r in rows if isinstance(rows,list) else []:
            if not isinstance(r,dict):continue
            vals=r.get(key);vals=vals if isinstance(vals,list) else ([vals] if vals is not None else [])
            bad=[v for v in vals if retired_ref(v)]
            if bad:raise ValueError(spec['path']+'#'+str(r.get('id'))+' '+key+' points to a document reset would move: '+', '.join(bad))
    rel=retire if retire is not None else 'Documents/aipm_retired/'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dest=safe_path(layer,rel)
    if dest.exists():raise ValueError('retire folder already exists; give a new folder: '+rel)
    if dest.absolute().is_relative_to(root.absolute()) or root.absolute().is_relative_to(dest.absolute()):raise ValueError('retire folder must be outside the package '+c['package_root'])
    # Case-insensitive file systems: compare existing ancestors by identity, not by spelling.
    near=next((p for p in (dest,*dest.parents) if p.exists()),None)
    if near is not None and root.exists() and any(os.path.samefile(p,root) for p in (near,*near.parents) if p.exists()):raise ValueError('retire folder must be outside the package '+c['package_root'])
    for parent in dest.parents:
        if parent.exists() and not parent.is_dir():raise ValueError('retire path crosses a file: '+str(parent))
        if parent==layer:break
    plan_moves=[{'from':pre+x,'to':rel+'/'+x} for x in moves]
    receipts=sorted(q.relative_to(layer).as_posix() for q in (layer/'Context').glob('receipt_*.yaml')) if (layer/'Context').is_dir() else []
    result={'route':'aipm','applied':False,'retire':rel,'moves':plan_moves,'restores':[pre+x for x in restores],'kept':sorted(pre+x for x in keep-set(docs)),'receipts':receipts,'note':RESET_NOTE}
    if not apply:
        result['dry_run']='予定の表示だけで、何も書いていない。本人の承認の後に --apply --retire <退避先> で動かす'
        return result
    before={}
    for x in moves:
        q=root/x
        before[x]={f.relative_to(q).as_posix():sha(f) for f in q.rglob('*') if f.is_file()} if q.is_dir() else sha(q)
    done=[];written=[];made=[p for p in (dest,*dest.parents) if not p.exists()]   # folders this call creates (removed again on failure)
    try:
        for x in moves:
            t=dest/x;t.parent.mkdir(parents=True,exist_ok=True);(root/x).rename(t);done.append(x)
        for x in restores:
            q=root/x;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(docs[x]);written.append(x)
        for x in moves:
            t=dest/x;got={f.relative_to(t).as_posix():sha(f) for f in t.rglob('*') if f.is_file()} if t.is_dir() else sha(t)
            if got!=before[x]:raise ValueError('moved file changed: '+x)
        for x in restores:
            if sha(root/x)!=outs[pre+x]:raise ValueError('restored init draft differs from mode_init.outputs: '+x)
    except Exception:
        for x in written:(root/x).unlink(missing_ok=True)
        for x in reversed(done):os.replace(dest/x,root/x)
        if dest.exists():   # remove only empty folders left under the new retire folder, then the ones this call made
            for q in sorted((q for q in dest.rglob('*') if q.is_dir()),key=lambda q:len(q.parts),reverse=True):
                with contextlib.suppress(OSError):q.rmdir()
        for q in made:
            with contextlib.suppress(OSError):q.rmdir()
        raise
    result.update(applied=True,continuable=mode_init_package(layer,root,c) is not None)
    result.pop('dry_run',None)
    return result

OS_METAFILES=frozenset({'.DS_Store'})   # git-ignored OS files; they move with the emptied folders to retire
MIGRATE_NOTE='移したのはこの箱だけ。git の commit は人がその worktree で行う（rename として見える）。Stock の写しは archive のときに本番の Stock へ作る'

def load_text(text):
    """YAML text -> value (duplicate keys refused)."""
    return yaml.load(text,Loader=UniqueLoader)

def _strings(o):
    """Every string value in a loaded YAML (keys included), for finding old-layout paths."""
    if isinstance(o,dict):return [s for k,v in o.items() for s in (_strings(k)+_strings(v))]
    if isinstance(o,list):return [s for v in o for s in _strings(v)]
    return [o] if isinstance(o,str) else []

SHEETS_MIGRATION_BY='package.py migrate-sheets'
SHEETS_MIGRATE_NOTE='移したのはこの箱だけ。git の commit は人がその worktree で行う（rename として見える）。Context の受領記録は書き換えない（validate は manifest の layout_migrations で古いパスを読む）。intent の mode_init.outputs の sha256 は init 時の値のままなので、移した後は reset-to-init が止まる（migrate-layout と同じ）。outside_references に出た箱の外の参照（backlog の output など）は書き換えないので、人が直す'
def migrate_sheets(layer,*,apply=False,approval_ref=None,stock_root=None,program=None,retire=None,registry_db=None):
    """move one box_root_v1 package (Documents/aipm_project/) to sheets_v1 (<Layer>/Sheets/). Dry-run
    unless apply; apply needs approval_ref (the person's approval of this box). The folder is renamed (every file keeps its
    bytes and mtime) and the registers move up from registers/ to Sheets/. Rewritten: format_contract (the sheets_v1
    contract), project_init.yaml flow_base (its generation time is kept; the rewrite is recorded), manifest (paths under the
    package, contract_version, one layout_migrations entry), intent mode_init.outputs paths, and the path references in the
    registers. Not rewritten: the documents, validation_record / validation_checkpoint, the input packet and the Context
    receipts (validate reads a receipt's old target path through the recorded migration). Archived packages and bound
    replies are allowed. Every check runs before any write; validate (final when archived, else prearchive) must not get
    errors it did not have before, else everything is put back. Refused: not box_root_v1, the legacy course, shared Stock,
    Sheets/ already there (in any case), intent aipm.layout written, unexpected files in registers/, old paths in
    validation_record / validation_checkpoint, sources / snapshots / evidence inside the package (bound to the original
    packet or evidence as they are), no project_init.yaml record, and references the text rewrite cannot place.
    A nested_v1 package goes to sheets_v1 in one step (see _nested_to_sheets); program and retire are
    for that route only (and registry_db: an archived nested_v1 package)."""
    from validate_package import validate
    layer=Path(layer).absolute()
    if not select(layer):raise ValueError('the bundled PM addon (aipm) is not selected')
    pre=LEGACY_ROOT+'/';root=safe_path(layer,LEGACY_ROOT);dst_root=safe_path(layer,SHEETS_ROOT)
    if (dst_root/'format_contract.yaml').is_file() and not (root/'format_contract.yaml').is_file():raise ValueError('package is already '+SHEETS_LAYOUT+' ('+SHEETS_ROOT+'/); nothing to move')
    if not (root/'format_contract.yaml').is_file():raise ValueError('package missing: '+pre+'format_contract.yaml')
    if (root/'manifest.yaml').is_file() and 'applies' in (load(root/'manifest.yaml') or {}):raise ValueError('the box has versions (applies); migrate-sheets does not move the version records (receipts[].target_path, the apply_log), so it stops (nothing written)')
    if dst_root.exists() or dst_root.is_symlink() or any(x.name.casefold()==SHEETS_ROOT.casefold() for x in layer.iterdir()):raise ValueError(SHEETS_ROOT+'/ (in any case) already exists in the Layer; not migrated')
    old=build_contract(layer)
    if (intent(layer).get('aipm') or {}).get('layout') is not None:raise ValueError('intent aipm.layout is written; remove it first (the saved layout decides after the move)')
    if old.get('layout',NESTED_LAYOUT)==NESTED_LAYOUT:return _nested_to_sheets(layer,old,root,dst_root,apply=apply,approval_ref=approval_ref,stock_root=stock_root,program=program,retire=retire,registry_db=registry_db)
    if old.get('layout')!=BOX_ROOT_LAYOUT:raise ValueError('only box_root_v1 and nested_v1 packages are moved to sheets_v1 (this one is '+str(old.get('layout'))+')')
    if program is not None or retire is not None or registry_db is not None:raise ValueError('--program, --retire and --registry-db are for a nested_v1 package (a box_root_v1 package keeps its program and leaves nothing behind)')
    if load(root/'format_contract.yaml')!=old:raise ValueError('format_contract.yaml differs from the rebuilt box_root_v1 contract; not migrated')
    if old.get('course_id',LEGACY_COURSE)==LEGACY_COURSE:raise ValueError('the legacy course is not migrated (its stage times bind the documents)')
    if old.get('storage')=='registry_stock_v1':raise ValueError('shared Stock packages are not migrated here')
    if not (root/'manifest.yaml').is_file():raise ValueError('manifest.yaml missing: only drafted packages are migrated')
    m=load(root/'manifest.yaml')
    if not isinstance(m,dict):raise ValueError('manifest.yaml must be a map')
    new=build_contract(layer,layout_override=SHEETS_LAYOUT)
    changed={k for k in set(old)|set(new) if old.get(k)!=new.get(k)}
    if not changed<={'layout','version','package_root'}:raise ValueError('the sheets_v1 contract differs in more than the layout: '+', '.join(sorted(changed)))
    reg_old={n:f['path'] for n,f in registers_contract(old)['files'].items()} if 'registers_contract_version' in old else {}
    reg_new={n:f['path'] for n,f in registers_contract(new)['files'].items()} if 'registers_contract_version' in new else {}
    reg_map={reg_old[n]:reg_new[n] for n in reg_old}   # package-relative: registers/issues.yaml -> issues.yaml
    def mp(v):
        """Old path -> new path: Layer-relative under Documents/aipm_project/ and package-relative registers paths; else unchanged."""
        if not isinstance(v,str):return v
        if v==LEGACY_ROOT:return SHEETS_ROOT
        if v.startswith(pre):
            rest=v[len(pre):]
            if rest in ('registers','registers/'):return SHEETS_ROOT+'/'   # a reference to the registers folder: they sit in Sheets/ now
            return SHEETS_ROOT+'/'+reg_map.get(rest,rest)
        return reg_map.get(v,v)
    def is_old(v):return isinstance(v,str) and (v==LEGACY_ROOT or v.startswith(pre) or v in reg_map)
    moves=[]   # package-relative, inside the renamed folder
    regdir=root/'registers'
    if reg_map:
        for q in sorted(regdir.rglob('*')) if regdir.exists() else []:
            rel=q.relative_to(root).as_posix()
            if q.is_symlink():raise ValueError('symlink path refused: '+rel)
            if q.is_file() and rel not in reg_map and q.name not in OS_METAFILES:raise ValueError('unexpected file in registers/ (move it by hand first): '+rel)
            if q.is_dir():raise ValueError('unexpected folder in registers/: '+rel)
        for o,n in reg_map.items():
            if not (root/o).is_file():raise ValueError('registers file missing: '+o)
            if (root/n).exists() or (root/n).is_symlink():raise ValueError('a file with the registers name is already in the package: '+n)
            moves.append({'from':o,'to':n,'sha256':sha(root/o)})
    # sources read from inside the package are bound to the original input packet (hashed, never rewritten): such a box
    # cannot keep the packet and the moved paths in step, so it is refused here, before anything is written
    for x in m.get('source_reads') or []:
        if isinstance(x,dict) and x.get('domain')=='layer' and isinstance(x.get('path'),str) and (x['path'].startswith(pre) or x['path']==LEGACY_ROOT):raise ValueError('a source read lives inside the package ('+x['path']+'); its input packet binds the old path, not migrated')
    if any(isinstance(v,str) and (v.startswith(pre) or v==LEGACY_ROOT) for v in _strings(m.get('source_snapshots') or {})):raise ValueError('source snapshots point into the package; not migrated')
    if any(isinstance(e,dict) and isinstance(e.get('source'),str) and (e['source'].startswith(pre) or e['source']==LEGACY_ROOT) for e in m.get('evidence') or []):raise ValueError('an evidence source lives inside the package; it is bound as it is, not migrated')
    if not any(isinstance(r,dict) and r.get('path')=='project_init.yaml' for r in m.get('records') or []):raise ValueError('manifest has no project_init.yaml record; not migrated')
    for n in ('validation_record.yaml','validation_checkpoint.yaml'):
        if (root/n).is_file() and any(is_old(v) for v in _strings(load(root/n))):raise ValueError(n+' refers to the old paths and is bound as it is; not migrated')
    rewrites=[];texts={}   # new package-relative path -> new text
    def text_rewrite(q,label):
        """Replace the old prefixes by text (keeps comments and order); the reloaded values must be exactly the mapped ones."""
        text=q.read_text();out=text
        for o,n in reg_map.items():out=out.replace(pre+o,SHEETS_ROOT+'/'+n)
        out=re.sub(re.escape(pre+'registers')+r'/?(?=[\s\'",\]\}]|$)',SHEETS_ROOT+'/',out,flags=re.M)   # the registers folder itself: the registers sit in Sheets/ now
        out=out.replace(pre,SHEETS_ROOT+'/');out=re.sub(re.escape(LEGACY_ROOT)+r'(?![^\s\'",\]\}])',SHEETS_ROOT,out)
        data=load(q)
        def remap(o):
            if isinstance(o,dict):return {remap(k):remap(v) for k,v in o.items()}
            if isinstance(o,list):return [remap(v) for v in o]
            return mp(o) if isinstance(o,str) and (o==LEGACY_ROOT or o.startswith(pre)) else o
        if yaml.load(out,Loader=UniqueLoader)!=remap(data):raise ValueError('cannot rewrite '+label+' by text safely; fix its references by hand first')
        return out
    for o,n in reg_map.items():
        data=load(root/o);hits=[v for v in _strings(data) if isinstance(v,str) and (v==LEGACY_ROOT or v.startswith(pre))]
        if hits:texts[n]=text_rewrite(root/o,pre+o);rewrites+=[{'file':SHEETS_ROOT+'/'+n,'from':v,'to':mp(v)} for v in hits]
    pi=load(root/'project_init.yaml');flow_base,stock_base=init_roots(new)
    if yaml.safe_dump(pi,allow_unicode=True,sort_keys=False)!=(root/'project_init.yaml').read_text():raise ValueError('project_init.yaml is not as the tool wrote it (comments or hand formatting); fix it by hand first')
    want={'flow_base':flow_base,'stock_base':stock_base}
    pi_fields=sorted(k for k,v in want.items() if pi.get(k)!=v)
    rewrites+=[{'file':SHEETS_ROOT+'/project_init.yaml','field':k,'from':pi.get(k),'to':want[k]} for k in pi_fields]
    pi.update(want);pi_text=yaml.safe_dump(pi,allow_unicode=True,sort_keys=False)
    fc_text=yaml.safe_dump(new,allow_unicode=True,sort_keys=False)
    it=intent(layer);mi=it.get('mode_init') if isinstance(it.get('mode_init'),dict) else None;intent_text=None
    if mi and isinstance(mi.get('outputs'),list):
        outs=[dict(o,path=mp(o.get('path'))) for o in mi['outputs']];text=safe_path(layer,'intent.yaml').read_text();out=text
        for a_,b_ in zip(mi['outputs'],outs):
            if a_.get('path')!=b_.get('path'):
                if out.count(str(a_['path']))!=1:raise ValueError('intent.yaml mode_init.outputs path appears more than once; not rewritten by text: '+str(a_['path']))
                out=out.replace(str(a_['path']),str(b_['path']));rewrites.append({'file':'intent.yaml','field':'mode_init.outputs.path','from':a_['path'],'to':b_['path']})
        if yaml.load(out,Loader=UniqueLoader).get('mode_init',{}).get('outputs')!=outs:raise ValueError('cannot rewrite intent.yaml mode_init.outputs by text safely')
        intent_text=out
    m2=copy.deepcopy(m)
    KEEP=('input_packet','evidence','archive_target','archive_moves','layout_migrations','source_reads','source_snapshots','gaps','claims','decisions')   # kept as they are: bound to the packet / evidence, or outside the package
    def remap_all(o,key=None):
        if isinstance(o,dict):return {k:(v if k in KEEP else remap_all(v,k)) for k,v in o.items()}
        if isinstance(o,list):return [remap_all(v,key) for v in o]
        return mp(o) if is_old(o) and isinstance(o,str) and (o.startswith(pre) or o==LEGACY_ROOT) else o
    m2=remap_all(m2);m2['contract_version']=new['version']
    left=[v for v in _strings({k:v for k,v in m2.items() if k not in KEEP}) if isinstance(v,str) and (v.startswith(pre) or v==LEGACY_ROOT)]
    if left:raise ValueError('manifest still refers to the old place after the mapping: '+', '.join(sorted(set(left))[:5]))
    rewrites.append({'file':SHEETS_ROOT+'/manifest.yaml','field':'paths under the package, contract_version','from':m.get('contract_version'),'to':new['version']})
    rewrites.append({'file':SHEETS_ROOT+'/format_contract.yaml','field':'layout/version/package_root','from':{'layout':old['layout'],'version':old['version']},'to':{'layout':new['layout'],'version':new['version'],'package_root':new['package_root']}})
    outside=[]   # Layer files outside the package that still name the old place: shown, not rewritten (backlog outputs, notes...)
    for q in sorted(layer.rglob('*')):
        relq=q.relative_to(layer).as_posix()
        if not q.is_file() or q.is_symlink() or q.suffix not in ('.md','.yaml','.yml') or relq.startswith((pre,'Documents/aipm_retired/')):continue
        for n,line in enumerate(q.read_text(errors='replace').splitlines(),1):
            if LEGACY_ROOT in line:
                if relq=='intent.yaml' and any(isinstance(o,dict) and o.get('path') and o['path'] in line for o in (mi or {}).get('outputs') or []):continue
                outside.append(relq+':'+str(n))
    archived=any(isinstance(r,dict) and r.get('archive_path') for r in m.get('records') or [])
    phase='final' if archived else 'prearchive'
    def errs(res):return sorted({(e['code'],e['path']) for e in res['errors']})
    before=errs(validate(root,phase=phase,layer=layer,stock_root=stock_root))
    result={'route':'aipm','applied':False,'from_layout':BOX_ROOT_LAYOUT,'to_layout':SHEETS_LAYOUT,'rename':{'from':LEGACY_ROOT,'to':SHEETS_ROOT},
            'moves':moves,'rewrites':rewrites,'validate_phase':phase,'validate_before':before,'outside_references':outside,'note':SHEETS_MIGRATE_NOTE}
    if not apply:
        result['dry_run']='予定の表示だけで、何も書いていない。本人の承認の後に --apply --approval-ref <承認の出典> で動かす';return result
    if not isinstance(approval_ref,str) or not approval_ref.strip():raise ValueError("--apply needs --approval-ref (the person's approval of this box; nothing written)")
    keep={}   # Layer-relative old path -> (bytes, atime, mtime) of every file this rewrites
    for relp in [pre+'manifest.yaml',pre+'format_contract.yaml',pre+'project_init.yaml','intent.yaml',*[pre+o for o,n in reg_map.items() if n in texts]]:
        q=safe_path(layer,relp);st=q.stat();keep[relp]=(q.read_bytes(),st.st_atime_ns,st.st_mtime_ns)
    try:
        os.rename(root,dst_root)
        for x in moves:
            s_,t_=dst_root/x['from'],dst_root/x['to'];t_.parent.mkdir(parents=True,exist_ok=True);os.rename(s_,t_)
        for d in (dst_root/'registers',dst_root/'source_snapshots/registers'):   # the emptied folders go; one with only an OS metafile stays
            with contextlib.suppress(OSError):d.rmdir()
        for n,out in texts.items():
            q=dst_root/n;st=q.stat();q.write_text(out);os.utime(q,ns=(st.st_atime_ns,st.st_mtime_ns))
        (dst_root/'format_contract.yaml').write_text(fc_text)
        pr=next(r for r in m2['records'] if r['path']=='project_init.yaml')
        (dst_root/'project_init.yaml').write_text(pi_text);os.utime(dst_root/'project_init.yaml',ns=((dst_root/'project_init.yaml').stat().st_atime_ns,pr['generated_mtime_ns']))
        m2.setdefault('layout_migrations',[]).append({'at':datetime.now(timezone.utc).isoformat(),'from':BOX_ROOT_LAYOUT,'to':SHEETS_LAYOUT,'by':SHEETS_MIGRATION_BY,
            'package':{'from':LEGACY_ROOT,'to':SHEETS_ROOT},'registers':{'from':'registers/','to':''},'approval_ref':approval_ref,
            'rewritten':{'path':'project_init.yaml','fields':pi_fields,'sha256_before':pr['sha256'],'sha256_after':sha(dst_root/'project_init.yaml'),'generated_mtime_kept':pr['generated_mtime_ns']},
            'moved_registers':len(reg_map)})
        pr['sha256']=sha(dst_root/'project_init.yaml')
        (dst_root/'manifest.yaml').write_text(yaml.safe_dump(m2,allow_unicode=True,sort_keys=False))
        if intent_text is not None:safe_path(layer,'intent.yaml').write_text(intent_text)
        for x in moves:
            if x['to'] not in texts and sha(dst_root/x['to'])!=x['sha256']:raise ValueError('moved file changed: '+x['to'])
        after=errs(validate(dst_root,phase=phase,layer=layer,stock_root=stock_root))
        mapped={(c,mp(p) if isinstance(p,str) else p) for c,p in before}
        extra=[e for e in after if e not in mapped]
        if extra:raise ValueError(phase+' validate gets new errors after the move: '+str(extra[:5]))
    except BaseException:
        # by what is on disk (a stop between a rename and its record is possible): the folder first, then each planned move
        if dst_root.exists() and not root.exists():os.rename(dst_root,root)
        for x in reversed(moves):
            s_,t_=root/x['from'],root/x['to']
            if t_.exists() and not s_.exists():s_.parent.mkdir(parents=True,exist_ok=True);os.replace(t_,s_)
        for relp,(data,at,mt) in keep.items():
            q=safe_path(layer,relp);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(data);os.utime(q,ns=(at,mt))
        raise
    result.update(applied=True,validate_after=after,manifest_sha256=sha(dst_root/'manifest.yaml'))
    return result

SHEETS_KEEP=('input_packet','evidence','archive_target','archive_moves','layout_migrations','source_reads','source_snapshots','gaps','claims','decisions')   # manifest keys a move keeps as they are: bound to the packet / evidence, or outside the package

def _nested_to_sheets(layer,old,root,dst_root,*,apply,approval_ref,stock_root,program,retire,registry_db=None):
    """migrate-sheets for a nested_v1 package (archived or not, any course but shared Stock), in one step.
    Every file in the package gets a place in Sheets/ from one table: the contract documents go where the sheets_v1
    contract puts them, the registers move up from registers/, Flow/<flow_rel>/<rest> becomes Sheets/<rest> (files outside
    the records too), and the package-level files (manifest, validation_*, others) keep their names. Files in Stock/ that
    are not contract documents stay behind; the emptied package folder (with them) is moved to retire (not deleted).
    Every file keeps its bytes and mtime (rename). Rewritten: format_contract, project_init.yaml (program_id and the roots;
    its generation time is kept and the rewrite is recorded), manifest (paths, flow_rel, stock_project_rel, contract_version,
    one layout_migrations entry), intent mode_init.outputs and the path references in the registers. Not rewritten: the
    documents, validation_record / validation_checkpoint (a validation reply is bound to their bytes; their old paths are
    listed in kept_old_references), the input packet and the Context receipts (validate reads a receipt's old target
    path through the recorded migration). apply needs approval_ref and program (an existing Stock/programs/<program>); an
    intent aipm.program_id that names another program is rewritten to it (recorded), since the sheets_v1 contract follows it.
    An archived package: its Stock copies inside the package are copied (bytes and mtime kept, nothing overwritten)
    to the real Stock/programs/<program>/projects/<business>/<project>/documents/, the business being the Layer's primary
    read only from the Registry (as archive does); the manifest gets the new archive_path and archive_target, the inner
    copies leave with the retired folder, and final must not get errors it did not have before. Nothing is committed (the
    Program repository is committed by the person).
    The legacy course moves too: its stage times are the recorded ones and stay, its evidence paths follow the move
    (it has no input packet; an evidence on a rewritten file is refused), and a reply bound to project_init.yaml is read
    by validate through the recorded rewrite (sha256 before and after).
    Five more shapes: (1) a box holding only its Collection init (no manifest, mode_init done, the init
    drafts unedited) becomes as if initialised in sheets_v1: the init drafts are rebuilt for the new contract and intent
    mode_init.outputs get the new path/sha256 (the old ones in mode_init.migrations); (2) a hand-formatted project_init.yaml
    gets only program_id/flow_base/stock_base rewritten by text; (3) an evidence on project_init.yaml (legacy course) is read
    by validate through the recorded rewrite; (4) sources read from inside the box move with their snapshots
    (source_snapshots/) and validate reads them through the recorded move; the inner Flow/ folder maps to Sheets/ and the
    inner Stock/ folder to the retired folder; (5) a shared Stock box after its draft and before archive.
    Every check runs before any write; prearchive validate must not get errors it did not have before, else everything
    is put back. Refused: a shared Stock box archived or holding only its init, sources / snapshots / evidence without a snapshot (new courses)
    inside the package, unexpected files, two files for one place, and references the mapping cannot place. For an archived
    package also: no Registry primary, a copy missing or changed, and a destination that already exists."""
    from validate_package import validate
    pre=LEGACY_ROOT+'/'
    if load(root/'format_contract.yaml')!=old:raise ValueError('format_contract.yaml differs from the rebuilt nested_v1 contract; not migrated')
    legacy=old.get('course_id',LEGACY_COURSE)==LEGACY_COURSE   # its stage times are the RECORDED ones (validate C3/C7/C8), kept as they are
    keep_keys=tuple(k for k in SHEETS_KEEP if k!='evidence') if legacy else SHEETS_KEEP   # the legacy course has no input packet: its evidence paths follow the move
    shared=old.get('storage')=='registry_stock_v1'
    mi0=intent(layer).get('mode_init')
    init_only=not (root/'manifest.yaml').is_file() and isinstance(mi0,dict) and mi0.get('state')=='done' and isinstance(mi0.get('outputs'),list)   # shape 1
    if not (root/'manifest.yaml').is_file() and not init_only:raise ValueError('manifest.yaml missing: only drafted packages (or a box holding just its Collection init, mode_init done) are migrated')
    m=load(root/'manifest.yaml') if not init_only else {}
    if not isinstance(m,dict):raise ValueError('manifest.yaml must be a map')
    archived='archive' in [s.get('name') for s in m.get('stages') or [] if isinstance(s,dict)] or any(isinstance(r,dict) and r.get('archive_path') is not None for r in m.get('records') or [])
    if shared and (archived or init_only):raise ValueError('a shared Stock package is migrated only after its draft and before archive (its originals/ record binds the document paths); not migrated')
    written=(intent(layer).get('aipm') or {}).get('program_id')   # the saved nested_v1 contract carries it, so it stays until the move rewrites it
    pid_change=(written,slug(program,'program')) if written is not None and program is not None and slug(program,'program')!=slug(written,'program_id') else None
    settings=archive_settings(layer,stock_root)   # where: layer needs no program folder (the copies go into the Layer)
    if apply and program is None and settings['where']=='stock':raise ValueError('--apply needs --program: the existing Stock/programs/<program> the person chose for this package')
    base=archive_base(layer,stock_root,settings)
    if program is not None and settings['where']=='stock':
        if base is None or slug(program,'program') not in {x.name for x in (base/STOCK_PROGRAMS).iterdir() if x.is_dir() and not x.is_symlink()}:raise ValueError('Stock/programs/'+str(program)+' does not exist in the repository Stock; give an existing program')
    new=build_contract(layer,layout_override=SHEETS_LAYOUT,program_override=program,program_wins=True)
    if program is not None and new['bindings']['program_id']!=slug(program,'program'):raise ValueError('the sheets_v1 contract would not carry the chosen program; not migrated')
    target=None;stock_plan=[]   # archived: (record index, inner package-relative copy, real destination)
    if archived:
        steps={e['step']:e for e in new['documents']}
        for i,r in enumerate(m.get('records') or []):
            e=steps.get(r.get('source_step')) if isinstance(r,dict) else None
            if e is None:raise ValueError('a record has no contract document; not migrated')
            if e.get('side'):continue
            inner=r.get('archive_path')
            if not isinstance(inner,str) or not inner.startswith(old['stock_project_rel']+'/documents/'):raise ValueError('archived record without its Stock copy inside the package: '+str(r.get('path'))+' (not migrated)')
            q=root/inner
            if q.is_symlink() or not q.is_file() or sha(q)!=r.get('archive_sha256'):raise ValueError('Stock copy missing or changed: '+inner+' (not migrated)')
            stock_plan.append((i,inner,e['path']))
        if program is not None or settings['where']=='layer':
            if base is None:raise ValueError('repository root holding Stock/programs not found; pass --stock-root (nothing written)')
            target=archive_target_of(layer,base,new['bindings']['program_id'],settings,registry_db)
            stock_plan=[(i,inner,target['target_rel']+'/documents/'+path) for i,inner,path in stock_plan]
            for i,inner,sd in stock_plan:
                dq=safe_path(base,sd)
                if dq.exists() or dq.is_symlink():raise ValueError('destination already exists in the real Stock: '+sd+' (nothing written)')
    retire_rel=retire if retire is not None else 'Documents/aipm_retired/'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'_migrate-sheets'
    dest=safe_path(layer,retire_rel)
    if dest.exists() or dest.is_symlink():raise ValueError('retire folder already exists; give a new folder: '+retire_rel)
    if dest.absolute().is_relative_to(root.absolute()) or dest.absolute().is_relative_to(dst_root.absolute()):raise ValueError('retire folder must be outside the package and '+SHEETS_ROOT+'/')
    used_retire=[]   # a reference rewritten to the retired folder: its name must be fixed before the approval (--retire)
    flow_pkg=old['flow_rel']+'/';stock_pkg=old['stock_project_rel']+'/'
    old_docs={e['step']:doc_rel(old,e) for e in old['documents']}
    doc_map={old_docs[e['step']]:doc_rel(new,e) for e in new['documents']}
    reg_old={n:f['path'] for n,f in registers_contract(old)['files'].items()} if 'registers_contract_version' in old else {}
    reg_new={n:f['path'] for n,f in registers_contract(new)['files'].items()} if 'registers_contract_version' in new else {}
    reg_map={reg_old[n]:reg_new[n] for n in reg_old}
    # one table for every file in the package (package-relative old -> Sheets-relative new)
    plan={};left=[]
    for q in sorted(root.rglob('*')):
        rel=q.relative_to(root).as_posix()
        if q.is_symlink():raise ValueError('symlink path refused: '+rel)
        if q.is_dir() or q.name in OS_METAFILES:continue
        if rel in doc_map:plan[rel]=doc_map[rel]
        elif rel in reg_map:plan[rel]=reg_map[rel]
        elif rel.startswith(flow_pkg):plan[rel]=rel[len(flow_pkg):]
        elif rel.startswith('Stock/'):left.append(rel)   # not a contract document: stays with the retired folder
        elif rel.startswith('source_snapshots/'):plan[rel]=rel   # the copies of sources read from inside the package (shape 4); checked below
        elif rel.startswith(('Flow/','registers/')):raise ValueError('unexpected file (move or keep it by hand first): '+rel)
        else:plan[rel]=rel
    recorded={r.get('path') for r in m.get('records') or [] if isinstance(r,dict)}
    for o in doc_map:   # the legacy course goes stage by stage: a document without a record (a stage not reached yet) may be missing; validate before and after decides the rest
        if o not in plan and (not legacy or o in recorded) and (not init_only or o in (pkg_rel(old['flow_rel'],'project_init.yaml'),pkg_rel(old['stock_project_rel'],'README.md'))):raise ValueError('document missing (only complete drafted packages are migrated): '+o)
    for o in reg_map:
        if o not in plan:raise ValueError('registers file missing: '+o)
    seen={}
    for o,n in plan.items():
        if n.split('/')[0] in ('Flow','Stock'):raise ValueError('a file would land in an inner '+n.split('/')[0]+'/ folder of Sheets/: '+o)
        k=n.casefold()
        if k in seen:raise ValueError('two files for one place in '+SHEETS_ROOT+'/: '+seen[k]+' and '+o)
        seen[k]=o
    def mp_pkg(v):
        """Package-relative old path -> Sheets-relative new path (None when the table cannot place it)."""
        if v in plan:return plan[v]
        if v in (flow_pkg[:-1],'registers','registers/',''):return ''
        if v.startswith(flow_pkg):return v[len(flow_pkg):]
        if v.startswith(('Flow/','Stock/','registers/')):return None
        return v
    def mp(v):
        """Old path -> new path: Layer-relative under Documents/aipm_project/, and the package-relative Flow/... Stock/... registers/ forms."""
        if not isinstance(v,str):return v
        if v==LEGACY_ROOT:return SHEETS_ROOT
        if v in (pre+'Flow',pre+'Flow/'):return SHEETS_ROOT   # the inner Flow/ folder itself is now Sheets/ (shape 4)
        if v in (pre+'Stock',pre+'Stock/'):used_retire.append(v);return retire_rel+'/aipm_project/Stock/'   # the inner Stock/ folder itself stays with the retired folder (shape 4)
        if v.startswith(pre):
            n=mp_pkg(v[len(pre):])
            return None if n is None else (SHEETS_ROOT+'/'+n if n else SHEETS_ROOT)
        if v in plan or v.startswith((flow_pkg,stock_pkg,'Flow/','Stock/')) or v in reg_map:return mp_pkg(v)
        return v
    def is_old(v):return isinstance(v,str) and (v==LEGACY_ROOT or v.startswith(pre) or v.startswith(('Flow/','Stock/')) or v in reg_map)
    snaps=m.get('source_snapshots') or {}
    if not isinstance(snaps,dict):raise ValueError('manifest source_snapshots must be a map; not migrated')
    def mirrored(sid,path):
        """A source read from inside the package has its copy at source_snapshots/<rest> (validate reads the copy, shape 4)."""
        return isinstance(path,str) and path.startswith(pre) and snaps.get(sid)==pre+'source_snapshots/'+path[len(pre):] and (root/('source_snapshots/'+path[len(pre):])).is_file()
    for x in m.get('source_reads') or []:
        if isinstance(x,dict) and x.get('domain')=='layer' and is_old(x.get('path')) and not mirrored(x.get('id'),x.get('path')):raise ValueError('a source read lives inside the package without its snapshot ('+str(x.get('path'))+'); its input packet binds the old path, not migrated')
    reads_ids={x.get('id') for x in m.get('source_reads') or [] if isinstance(x,dict)}
    named={v[len(pre):] for v in snaps.values() if isinstance(v,str) and v.startswith(pre)}
    stray=[o for o in plan if o.startswith('source_snapshots/') and o not in named]
    if stray:raise ValueError('unexpected file in source_snapshots/ (no source snapshot names it; move or keep it by hand first): '+stray[0])
    for sid,v in snaps.items():
        if not (sid in reads_ids and isinstance(v,str) and v.startswith(pre+'source_snapshots/')):raise ValueError('a source snapshot does not mirror a source read inside the package ('+str(sid)+'); not migrated')
    if not legacy and any(isinstance(e,dict) and is_old(e.get('source')) and not mirrored(e.get('id'),e.get('source')) for e in m.get('evidence') or []):raise ValueError('an evidence source lives inside the package without its snapshot; it is bound as it is, not migrated')
    kept=[]   # validation_record / validation_checkpoint: a validation reply is bound to their bytes, so their old paths stay
    for n in ('validation_record.yaml','validation_checkpoint.yaml'):
        if (root/n).is_file():kept+=[{'file':SHEETS_ROOT+'/'+n,'value':v} for v in _strings(load(root/n)) if is_old(v)]
    rewrites=[];texts={}   # Sheets-relative new path -> new text
    def remap(o):
        if isinstance(o,dict):return {remap(k):remap(v) for k,v in o.items()}
        if isinstance(o,list):return [remap(v) for v in o]
        return mp(o) if isinstance(o,str) and (o==LEGACY_ROOT or o.startswith(pre)) else o
    for o,n in reg_map.items():
        data=load(root/o);hits=[v for v in _strings(data) if isinstance(v,str) and (v==LEGACY_ROOT or v.startswith(pre))]
        if not hits:continue
        if any(mp(v) is None for v in hits):raise ValueError('a registers reference cannot be placed in '+SHEETS_ROOT+'/: '+', '.join(sorted(v for v in hits if mp(v) is None))[:300])
        text=(root/o).read_text();out=text
        for full in sorted({v for v in hits if v!=LEGACY_ROOT},key=len,reverse=True):out=out.replace(full,mp(full))
        out=re.sub(re.escape(LEGACY_ROOT)+r'(?![^\s\'",\]\}])',SHEETS_ROOT,out)
        if yaml.load(out,Loader=UniqueLoader)!=remap(data):raise ValueError('cannot rewrite '+o+' by text safely; fix its references by hand first')
        texts[n]=out;rewrites+=[{'file':SHEETS_ROOT+'/'+n,'from':v,'to':mp(v)} for v in hits]
    pi_old=old_docs['write_init_yaml'];pi_new=doc_map[pi_old]
    rd_old=pkg_rel(old['stock_project_rel'],'README.md');rd_new=doc_map.get(rd_old)
    init_texts={}   # shape 1: Sheets-relative new path -> the text init writes for the sheets_v1 contract
    if init_only:
        outs0={o.get('path'):o.get('sha256') for o in mi0['outputs'] if isinstance(o,dict)}
        if sha(root/'format_contract.yaml')!=outs0.get(pre+'format_contract.yaml'):raise ValueError('format_contract.yaml differs from intent mode_init.outputs; not migrated')
        for orel,text in init_documents(layer,old).items():   # unedited since init: the file is what init wrote and what mode_init recorded
            q=root/orel
            if not q.is_file() or q.read_text()!=text or sha(q)!=outs0.get(pre+orel):raise ValueError('the init draft was edited after init (or differs from mode_init.outputs): '+orel+'; not migrated')
        init_texts={doc_map[o]:t for o,t in zip(init_documents(layer,old),init_documents(layer,new).values())}
        pr0=None;pi_fields=sorted(k for k in ('program_id','flow_base','stock_base') if load(root/pi_old).get(k)!=load_text(init_texts[pi_new]).get(k))
        rewrites+=[{'file':SHEETS_ROOT+'/'+n,'field':'init draft (rebuilt for sheets_v1)'} for n in init_texts]
        pi_text=init_texts[pi_new]
    else:
        pr0=next((r for r in m.get('records') or [] if isinstance(r,dict) and r.get('path')==pi_old),None)
        if pr0 is None or not isinstance(pr0.get('sha256'),str) or type(pr0.get('generated_mtime_ns')) is not int:raise ValueError('manifest has no complete project_init.yaml record (sha256, generated_mtime_ns); not migrated')
        if sha(root/pi_old)!=pr0['sha256']:raise ValueError('project_init.yaml differs from its manifest record (edited after it was recorded); the move would hide that, not migrated')
        pi=load(root/pi_old);flow_base,stock_base=init_roots(new);b=new['bindings']
        want={'program_id':b['program_id'],'flow_base':flow_base,'stock_base':stock_base}
        pi_fields=sorted(k for k,v in want.items() if pi.get(k)!=v)
        raw=(root/pi_old).read_text()
        if yaml.safe_dump(pi,allow_unicode=True,sort_keys=False)==raw:pi_text=yaml.safe_dump({**pi,**want},allow_unicode=True,sort_keys=False)
        else:   # shape 2: hand formatting kept; only the three fields are rewritten by text, each on its own top-level line
            pi_text=raw
            for k in pi_fields:
                pat=re.compile(r'^'+k+r':[ \t]*(["\']?)'+re.escape(str(pi.get(k)))+r'\1[ \t]*$',re.M)
                if len(pat.findall(pi_text))!=1 or not re.fullmatch(r'[A-Za-z0-9_./-]+',str(want[k])):raise ValueError('project_init.yaml is not as the tool wrote it and '+k+' cannot be rewritten by text safely; fix it by hand first')
                pi_text=pat.sub(k+': '+str(want[k]),pi_text)
            if yaml.load(pi_text,Loader=UniqueLoader)!={**pi,**want}:raise ValueError('project_init.yaml is not as the tool wrote it and cannot be rewritten by text safely; fix it by hand first')
        rewrites+=[{'file':SHEETS_ROOT+'/'+pi_new,'field':k,'from':pi.get(k),'to':want[k]} for k in pi_fields]
    fc_text=yaml.safe_dump(new,allow_unicode=True,sort_keys=False)
    it=intent(layer);mi=it.get('mode_init') if isinstance(it.get('mode_init'),dict) else None;intent_text=None
    if mi and isinstance(mi.get('outputs'),list):
        outs=[dict(o,path=mp(o.get('path'))) for o in mi['outputs']]
        if any(o.get('path') is None for o in outs):raise ValueError('intent.yaml mode_init.outputs has a path the mapping cannot place')
        out=safe_path(layer,'intent.yaml').read_text()
        for a_,b_ in zip(mi['outputs'],outs):
            if a_.get('path')!=b_.get('path'):
                if out.count(str(a_['path']))!=1:raise ValueError('intent.yaml mode_init.outputs path appears more than once; not rewritten by text: '+str(a_['path']))
                out=out.replace(str(a_['path']),str(b_['path']));rewrites.append({'file':'intent.yaml','field':'mode_init.outputs.path','from':a_['path'],'to':b_['path']})
        if yaml.load(out,Loader=UniqueLoader).get('mode_init',{}).get('outputs')!=outs:raise ValueError('cannot rewrite intent.yaml mode_init.outputs by text safely')
        intent_text=out
    if pid_change:   # the chosen program replaces the intent aipm.program_id (else the moved contract and intent would disagree)
        out=intent_text if intent_text is not None else safe_path(layer,'intent.yaml').read_text()
        pat=re.compile(r'^([ \t]+program_id:[ \t]*)(["\']?)'+re.escape(str(pid_change[0]))+r'\2([ \t]*(#.*)?)$',re.M)
        if len(pat.findall(out))!=1:raise ValueError('intent.yaml aipm.program_id cannot be rewritten by text safely; set it to the chosen program by hand first')
        out2=pat.sub(lambda m_:m_.group(1)+pid_change[1]+m_.group(3),out)
        want_it=copy.deepcopy(yaml.load(out,Loader=UniqueLoader));want_it['aipm']['program_id']=pid_change[1]
        if yaml.load(out2,Loader=UniqueLoader)!=want_it:raise ValueError('intent.yaml aipm.program_id cannot be rewritten by text safely; set it to the chosen program by hand first')
        intent_text=out2;rewrites.append({'file':'intent.yaml','field':'aipm.program_id','from':pid_change[0],'to':pid_change[1]})
    init_migration=None
    if init_only:   # shape 1: the outputs now name what init writes for sheets_v1; the old path/sha256 go to mode_init.migrations
        newsha={SHEETS_ROOT+'/'+n:hashlib.sha256(t.encode('utf-8')).hexdigest() for n,t in init_texts.items()}
        newsha[SHEETS_ROOT+'/format_contract.yaml']=hashlib.sha256(fc_text.encode('utf-8')).hexdigest()
        out=intent_text;want_outs=[]
        for a_ in yaml.load(out,Loader=UniqueLoader)['mode_init']['outputs']:
            ns=newsha.get(a_.get('path'))
            if ns and ns!=a_.get('sha256'):
                if out.count(str(a_['sha256']))!=1:raise ValueError('intent.yaml mode_init.outputs sha256 appears more than once; not rewritten by text')
                out=out.replace(str(a_['sha256']),ns)
            want_outs.append(dict(a_,sha256=ns) if ns else a_)
        init_migration={'at':None,'from':NESTED_LAYOUT,'to':SHEETS_LAYOUT,'by':SHEETS_MIGRATION_BY,'outputs_before':mi0['outputs']}
        mline=re.search(r'^([ \t]*)mode_init:[ \t]*(#.*)?$',out,re.M)   # a trailing comment is kept
        if not mline:raise ValueError('intent.yaml mode_init is not a block map; not rewritten by text')
        after_line=out[mline.end()+1:];child=re.match(r'([ \t]+)\S',after_line)
        if not child:raise ValueError('intent.yaml mode_init has no indented keys; not rewritten by text')
        init_slot=(mline.end()+1,child.group(1))   # filled at apply time with the time of the move
        trial=out[:init_slot[0]]+init_slot[1]+'migrations:\n'+init_slot[1]+'- '+json.dumps(dict(init_migration,at='plan'),ensure_ascii=False)+'\n'+out[init_slot[0]:]
        got=yaml.load(trial,Loader=UniqueLoader)
        if got.get('mode_init',{}).get('migrations')!=[dict(init_migration,at='plan')] or {k:v for k,v in got['mode_init'].items() if k!='migrations'}!={k:v for k,v in yaml.load(out,Loader=UniqueLoader)['mode_init'].items()}:raise ValueError('cannot add intent.yaml mode_init.migrations by text safely; not migrated')
        if yaml.load(out,Loader=UniqueLoader).get('mode_init',{}).get('outputs')!=want_outs:raise ValueError('cannot rewrite intent.yaml mode_init.outputs by text safely')
        intent_text=out
    fixed=('flow_rel','stock_project_rel','contract_version','archive_path')   # archive_path: the real Stock copy (archived), set below
    def remap_all(o):
        if isinstance(o,dict):   # keys too (a manifest may key a map by a document path, e.g. related_versions)
            out={}
            for k,v in o.items():
                nk=remap_all(k) if isinstance(k,str) else k
                if nk in out:raise ValueError('two manifest keys become one after the mapping: '+str(nk))
                out[nk]=v if k in keep_keys+fixed else remap_all(v)
            return out
        if isinstance(o,list):return [remap_all(v) for v in o]
        if not is_old(o):return o
        n=mp(o)
        if n is None:raise ValueError('manifest refers to a place the mapping cannot put in '+SHEETS_ROOT+'/: '+o)
        return n
    m2=remap_all(copy.deepcopy(m))
    for r in m2.get('records') or []:
        if isinstance(r,dict) and isinstance(r.get('path'),str) and r['path'] in plan.values():continue
        raise ValueError('a record path cannot be placed in '+SHEETS_ROOT+'/: '+str(r.get('path') if isinstance(r,dict) else r))
    def without_fixed(o):
        if isinstance(o,dict):return {k:without_fixed(v) for k,v in o.items() if k not in keep_keys+fixed}
        if isinstance(o,list):return [without_fixed(v) for v in o]
        return o
    bad=[v for v in _strings(without_fixed(m2)) if is_old(v)]
    if bad:raise ValueError('manifest still refers to the old place after the mapping: '+', '.join(sorted({str(v) for v in bad})[:5]))
    if legacy:   # evidence is bound by sha256: it may not name a file this move rewrites (project_init, the registers, the records)
        changed={SHEETS_ROOT+'/'+n for n in (pi_new,'manifest.yaml','format_contract.yaml',*texts)}|({'intent.yaml'} if intent_text is not None else set())
        def bound(e):   # the evidence still matches its file now (one already broken by a later edit is not made worse by the move)
            o=e.get('source');o=o[len(SHEETS_ROOT)+1:] if o.startswith(SHEETS_ROOT+'/') else None
            q=(root/{v:k for k,v in plan.items()}.get(o,'')) if o else safe_path(layer,e.get('source'))
            return q.is_file() and sha(q)==e.get('source_sha256')
        hit=sorted({e['source'] for e in m2.get('evidence') or [] if isinstance(e,dict) and e.get('source') in changed-{SHEETS_ROOT+'/'+pi_new} and bound(e)})   # project_init.yaml: read through the recorded rewrite (shape 3)
        if hit:raise ValueError('an evidence source is a file this move rewrites ('+', '.join(hit)+'); its sha256 would no longer match, not migrated')
        rewrites+=[{'file':SHEETS_ROOT+'/manifest.yaml','field':'evidence[].source','from':a_.get('source'),'to':b_.get('source')} for a_,b_ in zip(m.get('evidence') or [],m2.get('evidence') or []) if isinstance(a_,dict) and a_.get('source')!=b_.get('source')]
    m2.update(flow_rel=new['flow_rel'],stock_project_rel=new['stock_project_rel'],contract_version=new['version'])
    if snaps:m2['source_snapshots']={k:SHEETS_ROOT+'/'+v[len(pre):] for k,v in snaps.items()};rewrites.append({'file':SHEETS_ROOT+'/manifest.yaml','field':'source_snapshots','count':len(snaps)})
    rewrites+=[{'file':SHEETS_ROOT+'/manifest.yaml','field':k,'from':m.get(k),'to':m2.get(k)} for k in fixed if k!='archive_path']
    if target is not None:
        for i,inner,sd in stock_plan:m2['records'][i]['archive_path']=sd
        m2['archive_target']=target
        rewrites.append({'file':SHEETS_ROOT+'/manifest.yaml','field':'records[].archive_path, archive_target','count':len(stock_plan),'to':target['target_rel']})
    rewrites.append({'file':SHEETS_ROOT+'/format_contract.yaml','field':'layout/version/package_root/flow_rel/stock_project_rel/stock_target_rel','from':{'layout':NESTED_LAYOUT,'version':old['version']},'to':{'layout':new['layout'],'version':new['version'],'stock_target_rel':new['stock_target_rel']}})
    outside=[]   # Layer files outside the package that still name the old place: shown, not rewritten (backlog outputs, notes...)
    for q in sorted(layer.rglob('*')):
        relq=q.relative_to(layer).as_posix()
        if not q.is_file() or q.is_symlink() or q.suffix not in ('.md','.yaml','.yml') or relq.startswith((pre,'Documents/aipm_retired/')):continue
        for n,line in enumerate(q.read_text(errors='replace').splitlines(),1):
            if LEGACY_ROOT in line:
                if relq=='intent.yaml' and any(isinstance(o,dict) and o.get('path') and o['path'] in line for o in (mi or {}).get('outputs') or []):continue
                outside.append(relq+':'+str(n))
    def errs(res):return sorted({(e['code'],e['path']) for e in res['errors']})
    phase='final' if archived else 'prearchive'
    before=errs(validate(root,phase=phase,layer=layer,stock_root=stock_root))
    moves=[{'from':pre+o,'to':SHEETS_ROOT+'/'+n,'sha256':sha(root/o)} for o,n in plan.items()]
    result={'route':'aipm','applied':False,'from_layout':NESTED_LAYOUT,'to_layout':SHEETS_LAYOUT,'program':None if new['bindings']['program_id']=='[unknown]' else new['bindings']['program_id'],'moves':moves,'rewrites':rewrites,
            'kept_old_references':kept,'retire':{'folder':retire_rel,'from':LEGACY_ROOT,'to':retire_rel+'/aipm_project','left_files':[pre+x for x in left]},
            'archived':archived,'archive_target':target,'stock_copies':[{'from':pre+inner,'to':sd} for i,inner,sd in stock_plan] if (not archived or target is not None) else '--program を付けると、本番の Stock の写し先（Registry の primary の業務Project）を引いて示す',
            'validate_phase':phase,'validate_before':before,'outside_references':outside,'note':SHEETS_MIGRATE_NOTE}
    if not apply:
        result['dry_run']='予定の表示だけで、何も書いていない。本人の承認の後に --apply --approval-ref <承認の出典> --program <program> で動かす'
        if used_retire and retire is None:result['needs_retire']='一覧が退避先を指すようになる。dry-run と --apply に同じ --retire <退避先> を付ける（付けない --apply は止まる）'
        return result
    if not isinstance(approval_ref,str) or not approval_ref.strip():raise ValueError("--apply needs --approval-ref (the person's approval of this box; nothing written)")
    if used_retire and retire is None:raise ValueError('a registers reference is rewritten to the retired folder; give --retire <folder> (the same in the dry-run and the --apply) so the approved plan is what is written')
    keep={}   # package-relative old path -> (bytes, atime, mtime) of every package file this rewrites; intent.yaml apart
    for o in ['manifest.yaml','format_contract.yaml',pi_old,*([rd_old] if init_only and rd_old in plan else []),*[o for o,n in reg_map.items() if n in texts]]:
        if not (root/o).is_file():continue   # an init-only box has no manifest
        st=(root/o).stat();keep[o]=((root/o).read_bytes(),st.st_atime_ns,st.st_mtime_ns)
    iq=safe_path(layer,'intent.yaml');ist=iq.stat();intent_keep=(iq.read_bytes(),ist.st_atime_ns,ist.st_mtime_ns)
    made=[];retired=dest/'aipm_project'
    def mk(d):
        for p_ in reversed([p_ for p_ in (d,*d.parents) if not p_.exists()]):made.append(p_);p_.mkdir()   # recorded first: a stop right after mkdir still removes it
    try:
        for i,inner,sd in stock_plan if archived else []:   # the real Stock copies first, from the inner copies (still in place)
            dq=safe_path(base,sd);mk(dq.parent)
            with open(dq,'xb') as f_:made.append(dq);f_.write((root/inner).read_bytes())   # create only: a file someone made meanwhile stops it, never overwritten or removed
            shutil.copystat(root/inner,dq)
            if sha(dq)!=m['records'][i]['archive_sha256']:raise ValueError('Stock copy changed while copying: '+sd)
        mk(dst_root)
        for o,n in plan.items():
            t_=dst_root/n;mk(t_.parent);os.rename(root/o,t_)
        for n,out in texts.items():
            q=dst_root/n;st=q.stat();q.write_text(out);os.utime(q,ns=(st.st_atime_ns,st.st_mtime_ns))
        (dst_root/'format_contract.yaml').write_text(fc_text)
        if init_only:   # shape 1: no manifest yet; the init drafts are written as init writes them for sheets_v1
            for n,t in init_texts.items():(dst_root/n).write_text(t)
            init_migration['at']=datetime.now(timezone.utc).isoformat();init_migration.update(approval_ref=approval_ref,program=new['bindings']['program_id'],retire=retire_rel)
            at_,ind=init_slot;intent_text=intent_text[:at_]+ind+'migrations:\n'+ind+'- '+json.dumps(init_migration,ensure_ascii=False)+'\n'+intent_text[at_:]
            if yaml.load(intent_text,Loader=UniqueLoader)['mode_init'].get('migrations')!=[init_migration]:raise ValueError('cannot add intent.yaml mode_init.migrations by text safely')
        else:
            pr=next(r for r in m2['records'] if r['path']==pi_new)
            (dst_root/pi_new).write_text(pi_text);os.utime(dst_root/pi_new,ns=((dst_root/pi_new).stat().st_atime_ns,pr['generated_mtime_ns']))
            m2.setdefault('layout_migrations',[]).append({'at':datetime.now(timezone.utc).isoformat(),'from':NESTED_LAYOUT,'to':SHEETS_LAYOUT,'by':SHEETS_MIGRATION_BY,
                'package':{'from':LEGACY_ROOT,'to':SHEETS_ROOT},'flow_rel':{'from':old['flow_rel'],'to':new['flow_rel']},'stock_project_rel':{'from':old['stock_project_rel'],'to':new['stock_project_rel']},
                'program':new['bindings']['program_id'],'approval_ref':approval_ref,
                'rewritten':{'path':pi_new,'fields':pi_fields,'sha256_before':pr['sha256'],'sha256_after':sha(dst_root/pi_new),'generated_mtime_kept':pr['generated_mtime_ns']},
                'moved_files':len(plan),'retire':retire_rel,'course':old.get('course_id',LEGACY_COURSE),**({'intent_program_id':{'from':pid_change[0],'to':pid_change[1]}} if pid_change else {}),**({'stock_copies':len(stock_plan),'archive_target_rel':target['target_rel']} if archived else {}),**({'source_snapshots':len(snaps)} if snaps else {})})
            pr['sha256']=sha(dst_root/pi_new)
            (dst_root/'manifest.yaml').write_text(yaml.safe_dump(m2,allow_unicode=True,sort_keys=False))
        if intent_text is not None:iq.write_text(intent_text)
        mk(dest);os.rename(root,retired)
        for x in moves:
            n=x['to'][len(SHEETS_ROOT)+1:]
            if n not in texts and n not in init_texts and n not in ('format_contract.yaml','manifest.yaml',pi_new) and sha(dst_root/n)!=x['sha256']:raise ValueError('moved file changed: '+x['to'])
        after=errs(validate(dst_root,phase=phase,layer=layer,stock_root=base if archived else stock_root))
        mapped={(c_,mp_pkg(p_) if isinstance(p_,str) and mp_pkg(p_) is not None else p_) for c_,p_ in before}
        extra=[e for e in after if e not in mapped]
        if extra:raise ValueError(phase+' validate gets new errors after the move: '+str(extra[:5]))
    except BaseException:
        # by what is on disk (a stop between two steps is possible): the package folder first, then each planned file
        if retired.exists() and not root.exists():os.rename(retired,root)
        root.mkdir(exist_ok=True)
        for o,n in reversed(list(plan.items())):
            s_,t_=root/o,dst_root/n
            if t_.exists() and not s_.exists():s_.parent.mkdir(parents=True,exist_ok=True);os.replace(t_,s_)
        for o,(data,at,mt) in keep.items():
            q=root/o;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(data);os.utime(q,ns=(at,mt))
        iq.write_bytes(intent_keep[0]);os.utime(iq,ns=(intent_keep[1],intent_keep[2]))
        for d in sorted(made,key=lambda p_:len(p_.parts),reverse=True):   # the real Stock copies this made, then the folders
            with contextlib.suppress(OSError):d.unlink() if d.is_file() and not d.is_symlink() else d.rmdir()
        raise
    result.update(applied=True,validate_after=after,manifest_sha256=sha(dst_root/'manifest.yaml') if (dst_root/'manifest.yaml').is_file() else None)
    return result

def migrate_layout(layer,*,apply=False,retire=None,program=None):
    """move one nested_v1 package to box_root_v1 in place. Dry-run unless apply.
    The 19 documents are renamed (bytes and mtime kept), so their sha256 stay; project_init.yaml gets the new roots
    (flow_base, stock_base, program_id), so it alone gets a new sha256 (its generation time is
    kept and the rewrite is recorded in manifest layout_migrations). format_contract, manifest (flow_rel,
    stock_project_rel, contract_version, records, stages.mode_init_outputs), intent mode_init.outputs and registers
    references are rewritten with the same mapping; the input packet and Context receipts are not changed. The emptied
    Flow/ and Stock/ folders are moved (not deleted) to retire, a new Layer folder outside the package. Every check runs
    before any write; on any failure everything is put back. Refused: box_root_v1 already, the legacy course, shared Stock,
    archived packages, packages with bound actual-user replies, sources or snapshots inside the moved folders, unexpected
    files, and a prearchive validate that gets errors it did not have before.
    program: the existing Stock/programs/<program> the person chose for this package; --apply needs it (a dry-run
    shows the plan without it). The program is saved in format_contract (it wins when intent has no aipm.program_id)."""
    from validate_package import validate
    layer=Path(layer).absolute()
    if not select(layer):raise ValueError('the bundled PM addon (aipm) is not selected')
    pre='Documents/aipm_project/';root=safe_path(layer,'Documents/aipm_project')
    if not (root/'format_contract.yaml').is_file():raise ValueError('package missing: '+pre+'format_contract.yaml')
    old=build_contract(layer)
    if old.get('layout') in FLAT_LAYOUTS:raise ValueError('package is already '+old['layout'])
    if (intent(layer).get('aipm') or {}).get('layout') is not None:raise ValueError('intent aipm.layout is written; the existing packages have none, and the saved layout decides after the move (remove it first)')
    if load(root/'format_contract.yaml')!=old:raise ValueError('format_contract.yaml differs from the rebuilt nested_v1 contract; not migrated')
    if old.get('course_id',LEGACY_COURSE)==LEGACY_COURSE:raise ValueError('the legacy course is not migrated (its stage times bind the documents)')
    if old.get('storage')=='registry_stock_v1':raise ValueError('shared Stock packages are not migrated here')
    if not (root/'manifest.yaml').is_file():raise ValueError('manifest.yaml missing: only drafted packages are migrated')
    m=load(root/'manifest.yaml')
    if not isinstance(m,dict):raise ValueError('manifest.yaml must be a map')
    if 'archive' in [s.get('name') for s in m.get('stages') or [] if isinstance(s,dict)] or any(isinstance(r,dict) and r.get('archive_path') is not None for r in m.get('records') or []):raise ValueError('package already archived; archived packages are not migrated')
    if m.get('human_responses') or m.get('checkpoint_targets'):raise ValueError('actual-user replies are bound to the old paths (Context receipts); not migrated so the receipts stay unchanged')
    where=archive_settings(layer)['where']   # where: layer needs no program folder
    if apply and program is None and where=='stock':raise ValueError('--apply needs --program: the existing Stock/programs/<program> the person chose for this package (a moved package without one could not archive)')
    if program is not None and where=='stock':
        base=stock_root_of(layer)
        if base is None or slug(program,'program') not in {x.name for x in (base/STOCK_PROGRAMS).iterdir() if x.is_dir() and not x.is_symlink()}:raise ValueError('Stock/programs/'+str(program)+' does not exist in the repository Stock; give an existing program')
    new=build_contract(layer,layout_override=BOX_ROOT_LAYOUT,program_override=program)
    flow_pkg=old['flow_rel']+'/';stock_pkg=old['stock_project_rel']+'/'
    def mp(s):
        """Old path -> new path, in the Layer-relative (Documents/aipm_project/...) and the package-relative forms; else unchanged."""
        for base,full in ((flow_pkg,pre+flow_pkg),(stock_pkg,pre+stock_pkg)):
            if s.startswith(full):return pre+s[len(full):]
            if s==full[:-1]:return pre[:-1]
            if s.startswith(base):return s[len(base):]
        return s
    def is_old(s):return mp(s)!=s or s.startswith((pre+'Flow/',pre+'Stock/','Flow/','Stock/'))
    for s in m.get('source_reads') or []:
        if isinstance(s,dict) and s.get('domain')=='layer' and isinstance(s.get('path'),str) and s['path'].startswith((pre+'Flow/',pre+'Stock/')):raise ValueError('a source read lives in the moved folders: '+s['path'])
    if any(is_old(v) for v in _strings(m.get('source_snapshots') or {})):raise ValueError('source snapshots point into the moved folders')
    moves=[]
    for e in new['documents']:
        o=doc_rel(old,e);n=doc_rel(new,e);src=root/o;dst=root/n
        if src.is_symlink() or not src.is_file():raise ValueError('document missing (only complete drafted packages are migrated): '+o)
        if dst.exists() or dst.is_symlink():raise ValueError('target already exists: '+n)
        moves.append({'from':o,'to':n,'sha256':sha(src)})
    moved={x['from'] for x in moves}
    for inner in ('Flow','Stock'):
        for q in (root/inner).rglob('*') if (root/inner).exists() else []:
            rel=q.relative_to(root).as_posix()
            if q.is_symlink():raise ValueError('symlink path refused: '+rel)
            if q.is_file() and rel not in moved and q.name not in OS_METAFILES:raise ValueError('unexpected file in '+inner+'/ (move or keep it by hand first): '+rel)
    # registers, validation records: rewrite references with the same mapping (registers) or refuse (the others)
    reg_files=[f['path'] for f in registers_contract(new)['files'].values()] if 'registers_contract_version' in new else []
    for n in ('validation_record.yaml','validation_checkpoint.yaml'):
        if (root/n).is_file() and any(is_old(v) for v in _strings(load(root/n))):raise ValueError(n+' refers to the old layout; not migrated')
    rewrites=[];texts={}
    def plan_text(rel_layer):
        """Text replacement of the old prefixes (keeps comments and order); the reloaded values must be exactly the mapped ones."""
        q=safe_path(layer,rel_layer);text=q.read_text();out=text
        for full in (pre+flow_pkg,pre+stock_pkg):out=out.replace(full,pre)
        for full in (pre+flow_pkg,pre+stock_pkg):out=re.sub(re.escape(full[:-1])+r'(?![^\s\'",\]\}])',pre[:-1],out)
        return text,out
    for r in reg_files:
        q=root/r
        if not q.is_file():continue
        data=load(q);hits=[v for v in _strings(data) if is_old(v)]
        if not hits:continue
        text,out=plan_text(pre+r)
        def remap(o):
            if isinstance(o,dict):return {remap(k):remap(v) for k,v in o.items()}
            if isinstance(o,list):return [remap(v) for v in o]
            return mp(o) if isinstance(o,str) else o
        if yaml.load(out,Loader=UniqueLoader)!=remap(data):raise ValueError('cannot rewrite '+r+' by text safely; fix its references by hand first')
        texts[pre+r]=out;rewrites+=[{'file':pre+r,'from':v,'to':mp(v)} for v in hits]
    # project_init.yaml: the new roots
    pi_old=doc_rel(old,next(e for e in old['documents'] if e['path']=='project_init.yaml'));pi_new='project_init.yaml'
    pi=load(root/pi_old);flow_base,stock_base=init_roots(new);b=new['bindings']
    if yaml.safe_dump(pi,allow_unicode=True,sort_keys=False)!=(root/pi_old).read_text():raise ValueError('project_init.yaml is not as the tool wrote it (comments or hand formatting); rewrite would lose them, fix it by hand first')
    want={'program_id':b['program_id'],'flow_base':flow_base,'stock_base':stock_base}
    rewrites+=[{'file':pre+pi_new,'field':k,'from':pi.get(k),'to':v} for k,v in want.items() if pi.get(k)!=v]
    pi.update(want);pi_text=yaml.safe_dump(pi,allow_unicode=True,sort_keys=False)
    fc_text=yaml.safe_dump(new,allow_unicode=True,sort_keys=False)
    # intent mode_init.outputs and the manifest stage that copies them
    it=intent(layer);mi=it.get('mode_init') if isinstance(it.get('mode_init'),dict) else None
    def new_outputs(outs):
        """Only the paths move; sha256 stay the init-time values (what init wrote then), so reset-to-init refuses afterwards."""
        return [dict(o,path=mp(o['path'])) for o in outs]
    intent_text=None
    if mi and isinstance(mi.get('outputs'),list):
        outs=new_outputs(mi['outputs']);text=safe_path(layer,'intent.yaml').read_text();out=text
        for a_,b_ in zip(mi['outputs'],outs):
            for k in ('path',):
                if a_.get(k)!=b_.get(k):
                    if out.count(str(a_[k]))!=1:raise ValueError('intent.yaml mode_init.outputs '+k+' appears more than once; not rewritten by text')
                    out=out.replace(str(a_[k]),str(b_[k]));rewrites.append({'file':'intent.yaml','field':'mode_init.outputs.'+k,'from':a_[k],'to':b_[k]})
        if yaml.load(out,Loader=UniqueLoader).get('mode_init',{}).get('outputs')!=outs:raise ValueError('cannot rewrite intent.yaml mode_init.outputs by text safely')
        intent_text=out
    m2=copy.deepcopy(m)
    m2.update(flow_rel=new['flow_rel'],stock_project_rel=new['stock_project_rel'],contract_version=new['version'])
    for r in m2.get('records') or []:r['path']=mp(r['path'])
    for s in m2.get('stages') or []:
        if isinstance(s,dict) and isinstance(s.get('mode_init_outputs'),list):s['mode_init_outputs']=new_outputs(s['mode_init_outputs'])
    left=[v for v in _strings({k:v for k,v in m2.items() if k not in ('input_packet',)}) if is_old(v)]
    if left:raise ValueError('manifest still refers to the old layout after the mapping: '+', '.join(sorted(set(left))[:5]))
    rewrites+=[{'file':pre+'manifest.yaml','field':k,'from':m.get(k),'to':m2.get(k)} for k in ('flow_rel','stock_project_rel','contract_version')]
    rewrites.append({'file':pre+'manifest.yaml','field':'records[].path','count':len(m2.get('records') or [])})
    rewrites.append({'file':pre+'format_contract.yaml','field':'layout/version/flow_rel/stock_project_rel/stock_target_rel','from':{'version':old['version']},'to':{'layout':new['layout'],'version':new['version'],'stock_target_rel':new['stock_target_rel']}})
    outside=[]   # Layer files outside the package that still name the old paths: shown, not rewritten (backlog outputs, notes...)
    for q in sorted(layer.rglob('*')):
        relq=q.relative_to(layer).as_posix()
        if not q.is_file() or q.is_symlink() or q.suffix not in ('.md','.yaml','.yml') or relq.startswith((pre,'Documents/aipm_retired/')):continue
        for n,line in enumerate(q.read_text(errors='replace').splitlines(),1):
            if (pre+flow_pkg[:-1]) in line or (pre+stock_pkg[:-1]) in line:
                if relq=='intent.yaml' and any(isinstance(o,dict) and o.get('path') and o['path'] in line for o in (mi or {}).get('outputs') or []):continue   # rewritten above
                outside.append(relq+':'+str(n))
    def errs(res):return sorted({(e['code'],e['path']) for e in res['errors']})
    before=errs(validate(root,phase='prearchive',layer=layer))
    rel=retire if retire is not None else 'Documents/aipm_retired/'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'_migrate'
    dest=safe_path(layer,rel)
    if dest.exists():raise ValueError('retire folder already exists; give a new folder: '+rel)
    if dest.absolute().is_relative_to(root.absolute()) or root.absolute().is_relative_to(dest.absolute()):raise ValueError('retire folder must be outside the package '+pre[:-1])
    inner=[x for x in ('Flow','Stock') if (root/x).exists()]
    result={'route':'aipm','applied':False,'from_layout':NESTED_LAYOUT,'to_layout':BOX_ROOT_LAYOUT,'moves':moves,'rewrites':rewrites,'retire':{'folder':rel,'moves':[{'from':pre+x,'to':rel+'/'+x} for x in inner]},
            'validate_before':before,'outside_references':outside,'note':MIGRATE_NOTE}
    if not apply:
        result['dry_run']='予定の表示だけで、何も書いていない。本人の承認の後に --apply（--retire <退避先>）で動かす';return result
    # apply: back up everything that is rewritten, then move/write; any failure puts it all back
    keep={}
    for relp in [pre+'manifest.yaml',pre+'format_contract.yaml',pre+pi_old,'intent.yaml',*texts]:
        q=safe_path(layer,relp);st=q.stat();keep[relp]=(q.read_bytes(),st.st_atime_ns,st.st_mtime_ns)
    done=[];made=[]
    def mk(d):
        for p in reversed([p for p in (d,*d.parents) if not p.exists()]):p.mkdir();made.append(p)
    try:
        for x in moves:
            s,t=root/x['from'],root/x['to'];mk(t.parent);os.rename(s,t);done.append((s,t))
        for f in new['folders']:mk(root/f)
        (root/pi_new).write_text(pi_text);(root/'format_contract.yaml').write_text(fc_text)
        for relp,out in texts.items():safe_path(layer,relp).write_text(out)
        if intent_text is not None:safe_path(layer,'intent.yaml').write_text(intent_text)
        # project_init keeps its generation time (validate binds it to the batch interval); the rewrite is recorded instead
        pr=next(r for r in m2['records'] if r['path']==pi_new);os.utime(root/pi_new,ns=((root/pi_new).stat().st_atime_ns,pr['generated_mtime_ns']))
        m2.setdefault('layout_migrations',[]).append({'at':datetime.now(timezone.utc).isoformat(),'from':NESTED_LAYOUT,'to':BOX_ROOT_LAYOUT,'by':'package.py migrate-layout',
            'rewritten':{'path':pi_new,'fields':sorted(want),'sha256_before':pr['sha256'],'sha256_after':sha(root/pi_new),'generated_mtime_kept':pr['generated_mtime_ns']},'moved_documents':len(moves),'retire':rel})
        pr['sha256']=sha(root/pi_new)
        (root/'manifest.yaml').write_text(yaml.safe_dump(m2,allow_unicode=True,sort_keys=False))
        mk(dest)
        for x in inner:os.rename(root/x,dest/x);done.append((root/x,dest/x))
        for x in moves:
            if x['to']!=pi_new and sha(root/x['to'])!=x['sha256']:raise ValueError('moved document changed: '+x['to'])
        after=errs(validate(root,phase='prearchive',layer=layer))
        mapped={(c,mp(p) if isinstance(p,str) else p) for c,p in before}
        extra=[e for e in after if e not in mapped]
        if extra:raise ValueError('prearchive validate gets new errors after the move: '+str(extra[:5]))
    except Exception:
        for s,t in reversed(done):os.replace(t,s)
        for relp,(data,at,mt) in keep.items():
            q=safe_path(layer,relp);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(data);os.utime(q,ns=(at,mt))
        for d in sorted(made,key=lambda p:len(p.parts),reverse=True):
            with contextlib.suppress(OSError):d.rmdir()
        raise
    result.update(applied=True,validate_after=after,manifest_sha256=sha(root/'manifest.yaml'))
    return result

def wbs_candidate(layer,task_id):
    """04-operation Phase 6: add a completed task's output to its WBS row as evidence. The row becomes
    pending_acceptance only when every task with the same wbs_id is completed (cancelled do not count).
    Never sets accepted; leaves accepted/cancelled rows unchanged; keeps partially_accepted and an existing pending_acceptance."""
    layer=Path(layer).absolute()
    light=_light()   # AIPM ライトモード and the sheets added to an aipm Layer keep wbs.yaml in Sheets/
    kind=light.record(layer)[0]
    if kind==light.LIGHT_KIND and not light.is_light(layer):kind=None   # a leftover record does not make a Layer light
    c=build_contract(layer) if kind!=light.LIGHT_KIND else None
    if c is not None and 'registers_contract_version' not in c and kind!=light.SHEETS_KIND:return {'route':'unselected','changed':False,'reason':'aipm.registers is not selected'}
    route=light.LIGHT if kind==light.LIGHT_KIND else 'aipm'
    bl=load(safe_path(layer,'backlog.yaml'));tasks=[t for t in (bl.get('tasks') or []) if isinstance(t,dict) and t.get('id')==task_id]
    if len(tasks)!=1:raise ValueError('task not found: '+str(task_id))
    t=tasks[0];w=t.get('wbs_id')
    if w in (None,'none'):return {'route':route,'changed':False,'reason':'task has no wbs_id'}
    if t.get('status')!='completed':raise ValueError('task is not completed; update backlog first')
    outs=t.get('output');outs=outs if isinstance(outs,list) else ([outs] if outs else [])
    if not outs:raise ValueError('completed task has no output to use as evidence')
    for o in outs:
        if not safe_path(layer,o).exists():raise ValueError('task output missing: '+o)
    if c is not None and 'registers_contract_version' in c:root=safe_path(layer,c['package_root']);q=safe_path(root,registers_contract(c)['files']['wbs']['path'])
    else:q=light.contract(layer)[2]['wbs']
    data=load(q);rows=[r for r in data.get('wbs') or [] if isinstance(r,dict) and r.get('id')==w]
    if len(rows)!=1:raise ValueError('WBS row not found: '+w)
    r=rows[0];before=r.get('status')
    if before in ('accepted','cancelled'):return {'route':route,'changed':False,'wbs_id':w,'status':before,'reason':'row is '+before+'; not changed'}
    ev=r.get('evidence_refs');ev=ev if isinstance(ev,list) else ([ev] if ev else [])
    for o in outs:
        if o not in ev:ev.append(o)
    r['evidence_refs']=ev
    # the row becomes a candidate only when every task with the same wbs_id is completed (cancelled ones do not count; deferred/blocked are not done)
    pending=[{'id':x.get('id'),'status':x.get('status')} for x in (bl.get('tasks') or []) if isinstance(x,dict) and x.get('wbs_id')==w and x.get('status') not in ('completed','cancelled') and not x.get('retired_at')]   # a retired recurring task is finished
    if before!='partially_accepted' and not pending:r['status']='pending_acceptance'
    q.write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False))
    if before=='partially_accepted':note='証拠を足した（一部受け入れのまま）。受け入れの判断は人'
    elif pending and before=='pending_acceptance':note='変更前から受入の候補（戻さない）。同じ wbs_id の Task が残っているので、受け入れる前に pending_tasks を確かめる'
    elif pending:note='証拠を足した。同じ wbs_id の Task が残っているので受入の候補にはしていない'
    else:note='accepted の候補。accepted にするのは人'
    out={'route':route,'changed':True,'wbs_id':w,'status_before':before,'status':r['status'],'evidence_refs':ev,'pending_tasks':pending,'note':note}
    # the actual date is a candidate only when no task with the same wbs_id remains and one of them has scheduled_for:
    # the latest completed_at of the completed ones, with their ids; a completed task without completed_at stops it.
    # wbs.yaml schedule stays for people
    same=[x for x in (bl.get('tasks') or []) if isinstance(x,dict) and x.get('wbs_id')==w]
    if not pending and any(x.get('scheduled_for') for x in same):
        done=[x for x in same if x.get('status')=='completed' and not x.get('recurrence')]
        def day(x):
            v=str(x.get('completed_at') or '').strip().strip('\'"')[:10]
            try:return date.fromisoformat(v)
            except ValueError:return None
        missing=[x.get('id') for x in done if day(x) is None]   # no completed_at, or one that is not a date
        if missing:out['schedule_actual_missing']=missing
        elif done:
            out['schedule_actual_candidate']=max(day(x) for x in done).isoformat();out['schedule_actual_basis']=[x.get('id') for x in done]
    return out

def aware(value,label):
    try:t=datetime.fromisoformat(value) if isinstance(value,str) else None
    except ValueError:t=None
    if t is None or t.tzinfo is None:raise ValueError(label+' must be an ISO time with timezone')
    return t

def receipt(layer,input_path):
    """Step 8 helper: write the actual-user receipt from the user's real reply and, for the new-course
    checkpoints (persona/validation), bind it in manifest. The reply and its time come only from the input; received_at
    is when this command wrote the receipt. Every check runs before any write. For the legacy (question-based) course the
    stages persona/problem/validation/solution/story are bound when the stage is closed, before the next one starts."""
    from validate_package import validate
    layer=Path(layer).absolute()
    if not select(layer):raise ValueError('the bundled PM addon (aipm) is not selected')
    c=build_contract(layer);inp=load(safe_path(layer,input_path))
    if not isinstance(inp,dict):raise ValueError('input must be map')
    for k in ('stage','question','answer','question_id','source_thread_id','answered_at'):
        if isinstance(inp.get(k),(date,datetime)):raise ValueError('input '+k+' must be a quoted string (YAML read it as a date)')
        if not isinstance(inp.get(k),str) or not inp[k].strip():raise ValueError('input '+k+' is required (the actual reply; never filled in by AI)')
    extra=[k for k in inp if k not in ('stage','question','answer','question_id','source_thread_id','answered_at','target_path','question_full','note','evidence_scope')]
    if extra:raise ValueError('unknown input key: '+','.join(map(str,extra)))
    qid=slug(inp['question_id'],'question_id');stage=inp['stage']
    answered=aware(inp['answered_at'],'answered_at')
    if answered>datetime.now(timezone.utc):raise ValueError('answered_at is in the future')
    rel='Context/receipt_'+qid+'.yaml';out=safe_path(layer,rel)
    if out.exists():raise ValueError('receipt already exists; do not overwrite: '+rel)
    root=safe_path(layer,c['package_root']);m=None;gaps_end=None
    legacy=c.get('course_id',LEGACY_COURSE)==LEGACY_COURSE and stage in LEGACY_STAGES
    binding=legacy or stage in ('persona','validation')
    if legacy:target_rel,m,gaps_end=legacy_target(layer,c,root,stage,inp)
    elif binding:
        if c.get('course_id',LEGACY_COURSE)==LEGACY_COURSE:raise ValueError('legacy course checkpoints stay on the existing route')
        m=load(root/'manifest.yaml');d=(m.get('decisions') or {}).get(stage)
        if not isinstance(d,dict):raise ValueError('manifest has no decision for '+stage)
        if d.get('state')=='confirmed_actual' or stage in (m.get('human_responses') or {}):raise ValueError(stage+' already has an actual reply; do not overwrite')
        if not isinstance(d.get('question'),str) or not d['question'].strip() or d['question'] not in inp['question']:raise ValueError('the asked question must contain manifest decisions.'+stage+'.question unchanged (context may be added around it)')
        names=[s.get('name') for s in m.get('stages',[])]
        if 'archive' in names:raise ValueError('package already archived; a checkpoint reply cannot be bound afterwards')
        if not names or names[-1]!='gaps':raise ValueError('gaps must be the last stage before archive')
        gaps_end=aware(m['stages'][-1].get('finished_at'),'gaps.finished_at')
        if stage=='persona':
            recs=[r for r in m.get('records',[]) if r.get('source_step')=='generate_persona_md']
            if len(recs)!=1:raise ValueError('persona document record not found')
            target_rel=c['package_root']+'/'+recs[0]['path']
        else:
            target_rel=c['package_root']+'/validation_checkpoint.yaml';q=safe_path(layer,target_rel)
            if not q.is_file():raise ValueError('validation_checkpoint.yaml missing; fix the question snapshot before asking')
            v=load(root/'validation_record.yaml')
            if load(q)!={k:x for k,x in v.items() if k!='actual_new_user_response'}:raise ValueError('validation_checkpoint.yaml differs from validation_record; the question changed')
        if inp.get('target_path') not in (None,target_rel):raise ValueError('target_path differs from the '+stage+' checkpoint target '+target_rel)
    if binding:
        ev_id='USR-'+stage
        if any(e.get('id')==ev_id for e in m.get('evidence',[])):raise ValueError('evidence id already used: '+ev_id)
    else:target_rel=inp.get('target_path')
    target=None
    if target_rel is not None:
        target=safe_path(layer,target_rel)
        if not target.is_file():raise ValueError('target missing: '+target_rel)
        if answered.timestamp()*1e9<target.stat().st_mtime_ns:raise ValueError('answered_at is before the target was last written; the reply was about an older version')
    key=lambda e:(e['code'],e['path'],e['message'])
    pre=validate(root,phase='prearchive',layer=layer)['errors'] if binding else []
    if legacy:other=[e for e in pre if not legacy_allowed(e,c,m,stage,root)]
    else:other=[e for e in pre if not (e['code']=='E_CHECKPOINT' and e['path'] in ('persona','validation','gaps','validation.actual_new_user_response'))]
    if other:raise ValueError('the package has other validate errors; fix them before binding a reply: '+json.dumps(other[:3],ensure_ascii=False))
    baseline={key(e) for e in pre}
    received=datetime.now(timezone.utc).isoformat()
    r={'kind':'user_reported','actor':'actual_user','origin':'actual_user_reply','scope_id':c['scope_id'],'stage':stage,'question':inp['question'],'answer':inp['answer'],'question_id':qid,'source_thread_id':inp['source_thread_id'],'answered_at':inp['answered_at'],'received_at':received}
    if target is not None:r.update(target_path=target_rel,target_sha256=sha(target))
    for k in ('question_full','note'):
        if inp.get(k):r[k]=inp[k]
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(yaml.safe_dump(r,allow_unicode=True,sort_keys=False))
    result={'route':'aipm','receipt':rel,'stage':stage,'answered_at':inp['answered_at'],'received_at':received,'bound':binding}
    if not binding:return result
    mp=root/'manifest.yaml';vp=root/'validation_record.yaml'
    saved={q:(q.read_bytes(),q.stat().st_mtime_ns) for q in (mp,vp) if q.is_file()}
    def restore():
        import os
        for q,(data,ns) in saved.items():q.write_bytes(data);os.utime(q,ns=(ns,ns))
        out.unlink(missing_ok=True)
    try:
        if legacy:bound=bind_legacy(m,rel,out,r,inp,stage,target_rel,received,gaps_end,mp,vp,root,layer,validate,key,baseline)
        else:bound=bind(m,rel,out,r,inp,stage,target_rel,received,gaps_end,mp,root,layer,validate,key,baseline)
    except Exception:
        restore();raise
    if bound['errors']:   # the binding itself broke something: leave nothing half-bound
        restore();return {**result,'pass':False,'errors':bound['errors'],'note':'binding failed validate; manifest restored and the receipt removed'}
    # remaining errors existed before (e.g. the other checkpoint is still pending); they are returned, not hidden
    return {**result,'pass':bound['pass'],'remaining_errors':bound['remaining'],'gaps_finished_at_extended':bound['extended'],'target_path':target_rel}

LEGACY_STAGES=('persona','problem','validation','solution','story')
LEGACY_TARGET_STEP={'persona':'generate_persona_md','problem':'generate_problem_statement','solution':'generate_solution_map','story':'generate_story_map_md'}
STAGE_OF_PREFIX={'01':'persona','02':'problem','03':'solution','04':'story'}

def legacy_target(layer,c,root,stage,inp):
    """Checks for a legacy stage reply (before any write): the stage is the last one in manifest, not yet answered, and the
    target is the stage's default document (or another document of the same stage). Returns (target_rel, manifest, stage_end)."""
    m=load(root/'manifest.yaml')
    if stage in (m.get('human_responses') or {}):raise ValueError(stage+' already has an actual reply; do not overwrite')
    names=[s.get('name') for s in m.get('stages',[])]
    if 'archive' in names:raise ValueError('package already archived; a checkpoint reply cannot be bound afterwards')
    if not names or names[-1]!=stage:raise ValueError('close '+stage+' before the next stage starts: the last stage is '+str(names[-1] if names else None))
    order=c['course'];want=order[:order.index(stage)+1]
    if names!=want:raise ValueError('stages must be exactly '+','.join(want)+' before closing '+stage)
    stage_end=aware(m['stages'][-1].get('finished_at'),stage+'.finished_at')
    pre=c['package_root']+'/'
    if stage=='validation':
        target_rel=pre+'validation_checkpoint.yaml';q=safe_path(layer,target_rel)
        if not q.is_file():raise ValueError('validation_checkpoint.yaml missing; fix the question snapshot before asking')
        v=load(root/'validation_record.yaml')
        if load(q)!={k:x for k,x in v.items() if k!='actual_new_user_response'}:raise ValueError('validation_checkpoint.yaml differs from validation_record; the question changed')
        if v.get('actual_new_user_response') is not None:raise ValueError('validation_record already has actual_new_user_response; do not overwrite')
        if inp.get('target_path') not in (None,target_rel):raise ValueError('target_path differs from the validation checkpoint target '+target_rel)
        return target_rel,m,stage_end
    own=[r for r in m.get('records',[]) if r.get('stage')==stage]
    if inp.get('target_path') is not None:
        if inp['target_path'] not in [pre+r['path'] for r in own]:raise ValueError('target_path is not a document of the '+stage+' stage')
        return inp['target_path'],m,stage_end
    recs=[r for r in own if r.get('source_step')==LEGACY_TARGET_STEP[stage]]
    if len(recs)!=1:raise ValueError(stage+' document record not found')
    return pre+recs[0]['path'],m,stage_end

LATER_SEMANTIC_KEYS={'problem':'problems','solution':'phases','story':'stories'}   # the first key validate reads from each stage's documents

def legacy_allowed(e,c,m,stage,root):
    """validate errors that only mean "the later stages have not started yet" (each checked to be so), or that this reply resolves.
    legacy_target has already checked that stages are exactly init..stage."""
    later=LEGACY_STAGES[LEGACY_STAGES.index(stage)+1:]
    code,path,msg=e['code'],e['path'],e['message']
    own={r['path'] for r in m.get('records',[]) if r.get('stage')==stage}
    no_record=not (root/'validation_record.yaml').exists()
    if code=='E_CHECKPOINT':return path in (stage,'stages.'+stage) or path in own or (path=='validation.actual_new_user_response' and stage=='validation')
    if code=='E_ORDER':return path=='stages' and msg=='incorrect required stage order'
    if code=='E_MANIFEST' and path=='records' and msg=='required document records missing':
        done=[d['step'] for d in c['documents'] if d.get('side') or STAGE_OF_PREFIX.get(d['path'][:2]) not in later]
        have={r.get('source_step') for r in m.get('records',[])}
        return all(step in have for step in done)   # only later stages' records are missing
    if code=='E_MANIFEST' and path=='scope_id':return 'validation' in later and no_record and m.get('scope_id')==c['scope_id']
    if code=='E_VALIDATION' or (code=='E_MISSING' and path=='validation'):return 'validation' in later and no_record
    if code=='E_REF':return path=='semantic' and msg in {"malformed or incomplete semantic data: '"+LATER_SEMANTIC_KEYS[s]+"'" for s in later if s in LATER_SEMANTIC_KEYS}
    if code=='E_MISSING':
        doc=next((d for d in c['documents'] if path==pkg_rel(c['flow_rel'],d['path']) and not d.get('side')),None)
        return bool(doc) and STAGE_OF_PREFIX.get(doc['path'][:2]) in later
    return False

def bind_legacy(m,rel,out,r,inp,stage,target_rel,received,stage_end,mp,vp,root,layer,validate,key,baseline):
    """receipt's manifest step for a legacy stage (the caller restores manifest/validation_record and removes the receipt on failure)."""
    m.setdefault('human_responses',{})[stage]={'answer':inp['answer'],'source':rel,'source_sha256':sha(out),'target_path':target_rel,'target_sha256':r['target_sha256'],
        'target_written_ns':safe_path(layer,target_rel).stat().st_mtime_ns}   # the write time seen at the bind, kept for a later git checkout
    m.setdefault('checkpoint_targets',{})[stage]=r['target_sha256']
    m.setdefault('evidence',[]).append({'id':'USR-'+stage,'kind':'user_reported','source':rel,'source_sha256':sha(out),'scope':inp.get('evidence_scope') or '本人の実回答（'+stage+' の質問への回答）だけで、実ユーザーの観察ではない'})
    event=m['stages'][-1];event.update(checkpoint_actor='actual_user',checkpoint_status='confirmed_actual')
    for rec in m.get('records',[]):
        if rec.get('stage')==stage and rec.get('requires_human') is True:rec['human_state']='confirmed_actual'
    extended=stage_end<datetime.fromisoformat(received)
    if extended:event['finished_at']=received   # the stage was waiting for this reply
    if stage=='validation':   # SKILL step 8: the reply is appended to validation_record (comments are not kept); the checkpoint snapshot stays
        v=load(vp);v['actual_new_user_response']=inp['answer'];vp.write_text(yaml.safe_dump(v,allow_unicode=True,sort_keys=False))
    mp.write_text(yaml.safe_dump(m,allow_unicode=True,sort_keys=False))
    check=validate(root,phase='prearchive',layer=layer)
    own={x['path'] for x in m.get('records',[]) if x.get('stage')==stage}
    left=[e for e in check['errors'] if e['code']=='E_CHECKPOINT' and (e['path'] in (stage,'stages.'+stage) or e['path'] in own)]   # the reply must resolve this stage
    return {'errors':[e for e in check['errors'] if key(e) not in baseline]+left,'pass':check['pass'],'remaining':check['errors'],'extended':extended}

def bind(m,rel,out,r,inp,stage,target_rel,received,gaps_end,mp,root,layer,validate,key,baseline):
    """receipt's manifest step (the caller restores manifest and removes the receipt on any failure)."""
    m.setdefault('human_responses',{})[stage]={'answer':inp['answer'],'source':rel,'source_sha256':sha(out),'target_path':target_rel,'target_sha256':r['target_sha256'],
        'target_written_ns':safe_path(layer,target_rel).stat().st_mtime_ns}   # the write time seen at the bind, kept for a later git checkout
    m.setdefault('checkpoint_targets',{})[stage]=r['target_sha256']
    m.setdefault('evidence',[]).append({'id':'USR-'+stage,'kind':'user_reported','source':rel,'source_sha256':sha(out),'scope':inp.get('evidence_scope') or '本人の実回答（'+stage+' の質問への回答）だけで、実ユーザーの観察ではない'})
    m['decisions'][stage]['state']='confirmed_actual'
    gaps=m['stages'][-1];extended=gaps_end<datetime.fromisoformat(received)
    if extended:gaps['finished_at']=received   # the gaps stage was waiting for this reply (SKILL: record the real waiting time)
    mp.write_text(yaml.safe_dump(m,allow_unicode=True,sort_keys=False))
    check=validate(root,phase='prearchive',layer=layer)
    return {'errors':[e for e in check['errors'] if key(e) not in baseline],'pass':check['pass'],'remaining':check['errors'],'extended':extended}

def judge(layer,input_path):
    """Add owner/decider judgements backed by an actual-user receipt to registers/hypotheses.yaml.
    Appends to judgements and sets status from the latest human verdict (undetermined -> unknown), as validate requires.
    ai_proxy proposals are written by ops.py hypothesis.propose (pm-hypothesis); every check runs before the write."""
    from validate_package import receipt_problem
    layer=Path(layer).absolute();c=build_contract(layer)
    if 'registers_contract_version' not in c:return {'route':'unselected','changed':False,'reason':'aipm.registers is not selected'}
    inp=load(safe_path(layer,input_path))
    if not isinstance(inp,dict):raise ValueError('input must be map')
    extra=[k for k in inp if k not in ('date','event','judged_by','evidence_ref','note','judgements')]
    if extra:raise ValueError('unknown input key: '+','.join(map(str,extra)))
    for k in ('date','event','evidence_ref'):
        if isinstance(inp.get(k),(date,datetime)):raise ValueError('input '+k+' must be a quoted string (YAML read it as a date)')
        if not isinstance(inp.get(k),str) or not inp[k].strip():raise ValueError('input '+k+' is required')
    if inp.get('judged_by') not in ('owner','decider'):raise ValueError('judged_by must be owner or decider (ai_proxy proposals are written by hand)')
    problem=receipt_problem(inp['evidence_ref'],layer,c)
    if problem:raise ValueError('evidence_ref is not an actual-user receipt: '+problem)
    items=inp.get('judgements')
    if not isinstance(items,list) or not items:raise ValueError('judgements list is required')
    rc=registers_contract(c);q=safe_path(safe_path(layer,c['package_root']),rc['files']['hypotheses']['path'])
    data=load(q)
    if not isinstance(data,dict) or not isinstance(data.get('hypotheses'),list):raise ValueError('hypotheses.yaml must be a map with a hypotheses list')
    rows={h.get('id'):h for h in data.get('hypotheses') or [] if isinstance(h,dict)};seen=set()
    for it in items:
        if not isinstance(it,dict) or set(it)-{'hypothesis_id','verdict','note'}:raise ValueError('each judgement needs hypothesis_id, verdict and optional note')
        hid=it.get('hypothesis_id')
        if hid not in rows:raise ValueError('hypothesis not found: '+str(hid))
        if hid in seen:raise ValueError('hypothesis listed twice: '+hid)
        seen.add(hid)
        if it.get('verdict') not in rc['files']['hypotheses']['judgement']['verdict']:raise ValueError('unknown verdict for '+hid)
    want={'supported':'supported','not_supported':'not_supported','undetermined':'unknown'};changes=[]
    for it in items:
        h=rows[it['hypothesis_id']];g={'date':inp['date'],'event':inp['event'],'verdict':it['verdict'],'judged_by':inp['judged_by'],'evidence_ref':inp['evidence_ref']}
        note=it.get('note') or inp.get('note')
        if note:g['note']=note
        js=h.get('judgements');js=js if isinstance(js,list) else []
        js.append(g);h['judgements']=js;before=h['status'];h['status']=want[it['verdict']]
        changes.append({'id':h['id'],'verdict':it['verdict'],'status_before':before,'status':h['status']})
    q.write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False))
    return {'route':'aipm','changed':True,'evidence_ref':inp['evidence_ref'],'judged_by':inp['judged_by'],'changes':changes}

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['route','init','contract','plan','draft','archive','move-archive','register','clone','snapshot-sources','change','change-list','judge-change','apply','redit','redit-list','redit-judge','redit-apply','redit-revert','redit-extract','migrate-sheets','wbs-candidate','receipt','judge','reset-to-init','migrate-layout','op','add-sheets']);p.add_argument('--layer',required=True);p.add_argument('--input');p.add_argument('--task')
    p.add_argument('--program',help='migrate-layout / migrate-sheets (a nested_v1 package): the existing Stock/programs/<program> chosen for this package (required with --apply)')
    p.add_argument('--stock-root',help='archive (box_root_v1): the repository root that holds Stock/programs (default: found from the Layer path)')
    p.add_argument('--approval-ref',help='move-archive / migrate-sheets / register / snapshot-sources / apply (also --push, --revert-unpushed) --apply: the person\'s approval of this write (recorded in the manifest)')
    p.add_argument('--registry-db',help='archive / move-archive (box_root_v1, sheets_v1) / migrate-sheets (an archived nested_v1 package): the Registry to read the primary business project from (default: <stock root>/.claude/db/ai_plc.db; opened read only)')
    p.add_argument('--push',action='store_true',help='apply: write the unpushed version into the Stock (stage 7)');p.add_argument('--revert-unpushed',action='store_true',help='apply: put the box back to the base from the backup of the unpushed version')
    p.add_argument('--list',help='judge-change: the digest of the saved list the person answered (at least its first 12 characters)')
    p.add_argument('--quote',help='judge-change: the person\'s words as they were said (one of the five replies)');p.add_argument('--at',help='judge-change: when the person said them (ISO time with offset)')
    p.add_argument('--thread',help='judge-change: the id of the conversation the reply came in (optional)')
    p.add_argument('--name',help='op: <item>.<verb> of a pm- operation (issue.add, hypothesis.propose, todo.move, ...) or check')
    p.add_argument('--drafts',help='init: Layer-relative YAML of the WBS (and optional issues/hypotheses) drafts');p.add_argument('--brief',action='store_true',help='init: print without the full contract')
    p.add_argument('--light',action='store_true',help='init: the Layer must have AIPM ライトモード (aipm-light) as its method')
    p.add_argument('--apply',action='store_true',help='reset-to-init: move and restore / migrate-layout: move and rewrite / op: write after the trial / register / change / apply (also --push, --revert-unpushed): write (default is a dry-run for all; clone, change-list and judge-change write only the owner Layer Context and need no --apply)');p.add_argument('--retire',help='reset-to-init / migrate-layout / migrate-sheets (a nested_v1 package): new Layer-relative folder outside the package');a=p.parse_args()
    try:
        if a.action=='route': result={'route':'aipm' if select(a.layer) else 'legacy'}
        elif a.action=='init':
            if a.light:
                light=_light()
                if not light.is_light(a.layer):raise ValueError('--light: AIPM ライトモード (aipm-light) is not the method of this Layer')
            result=init(a.layer,drafts=a.drafts)
            if a.brief:result=brief_init(result)
        elif a.action=='add-sheets':
            light=_light()   # the two sheets for an aipm Layer without aipm.registers (dry run unless --apply)
            result=light.add_sheets(a.layer,apply=a.apply)
        elif a.action=='reset-to-init':result=reset_to_init(a.layer,apply=a.apply,retire=a.retire)
        elif a.action=='migrate-layout':result=migrate_layout(a.layer,apply=a.apply,retire=a.retire,program=a.program)
        elif a.action=='migrate-sheets':result=migrate_sheets(a.layer,apply=a.apply,approval_ref=a.approval_ref,stock_root=a.stock_root,program=a.program,retire=a.retire,registry_db=a.registry_db)
        elif a.action=='plan':
            plan=course_plan(a.layer,a.input);result={k:v for k,v in plan.items() if k not in ['packet','texts','contract']}
        elif a.action=='draft':result=batch_draft(a.layer,a.input)
        elif a.action=='archive':result=archive_course(a.layer,stock_root=a.stock_root,registry_db=a.registry_db)
        elif a.action=='register':result=register(a.layer,apply=a.apply,approval_ref=a.approval_ref,stock_root=a.stock_root)
        elif a.action=='clone':result=clone(a.layer,stock_root=a.stock_root)
        elif a.action=='snapshot-sources':result=snapshot_sources(a.layer,a.input,apply=a.apply,approval_ref=a.approval_ref,stock_root=a.stock_root)
        elif a.action=='apply':
            import applying   # stage 6 (into the box), stage 7 (--push, into the Stock), --revert-unpushed
            if a.push:result=applying.push(a.layer,apply=a.apply,approval_ref=a.approval_ref,stock_root=a.stock_root)
            elif a.revert_unpushed:result=applying.revert_unpushed(a.layer,apply=a.apply,approval_ref=a.approval_ref)
            else:result=applying.apply(a.layer,apply=a.apply,approval_ref=a.approval_ref)
        elif a.action.startswith('redit'):
            import register_edits as re_   # registers edits in the apply way
            if a.action=='redit':result=re_.redit(a.layer,a.input,apply=a.apply)
            elif a.action=='redit-list':result=re_.redit_list(a.layer)
            elif a.action=='redit-judge':result=re_.redit_judge(a.layer,a.list,a.quote,a.at,a.thread)
            elif a.action=='redit-apply':result=re_.redit_apply(a.layer,apply=a.apply,approval_ref=a.approval_ref)
            elif a.action=='redit-extract':result=re_.extract(a.layer,a.input,apply=a.apply)
            else:result=re_.redit_revert(a.layer,apply=a.apply,approval_ref=a.approval_ref)
        elif a.action in ('change','change-list','judge-change'):
            import changes   # proposals, the numbered list and the person's judgement (Context/aipm_changes/ only)
            if a.action=='change':result=changes.change(a.layer,a.input,apply=a.apply)
            elif a.action=='change-list':result=changes.change_list(a.layer)
            else:result=changes.judge_change(a.layer,a.list,a.quote,a.at,a.thread)
        elif a.action=='move-archive':result=move_archive(a.layer,apply=a.apply,stock_root=a.stock_root,registry_db=a.registry_db,approval_ref=a.approval_ref)
        elif a.action=='wbs-candidate':result=wbs_candidate(a.layer,a.task)
        elif a.action=='receipt':result=receipt(a.layer,a.input)
        elif a.action=='judge':result=judge(a.layer,a.input)
        elif a.action=='op':
            from ops import run   # pm- operations on single items
            if not a.name:raise ValueError('op needs --name')
            result=run(a.layer,a.name,a.input,a.apply)
        else: result=build_contract(a.layer) if select(a.layer) else {'route':'legacy'}
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except Exception as e:
        print(json.dumps({'pass':False,'error':str(e)},ensure_ascii=False));return 1
if __name__=='__main__':raise SystemExit(main())
