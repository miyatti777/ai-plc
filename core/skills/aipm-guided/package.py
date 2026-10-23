#!/usr/bin/env python3
"""Opt-in routing and bounded AIPM Project initialization. No external commands."""
from pathlib import Path
from datetime import date, datetime, timezone
import argparse, contextlib, copy, hashlib, json, os, re, shutil
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
        path=Path(__file__).resolve().parents[1]/'ai-plc/scripts/plc_addon_select.py'   # .claude/skills/ai-plc/scripts
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
    """The registers contract bound in a built contract c (the saved version for existing packages)."""
    return load(registers_contract_path(c['registers_contract_version']))

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
        rel=(c['stock_project_rel'] if e.get('side')=='stock_project' else c['flow_rel'])+'/'+e['path'];q=root/rel
        if not q.is_file() or outs.get(pre+rel)!=sha(q):return None       # init draft missing or edited by hand
    registers=[f['path'] for f in registers_contract(c)['files'].values()] if 'registers_contract_version' in c else []
    if any(not (root/r).is_file() for r in registers):return None          # registers were selected but a file is gone
    allowed={'format_contract.yaml',c['flow_rel']+'/project_init.yaml',c['stock_project_rel']+'/README.md'}|set(registers)   # the fixed init paths, not whatever intent lists
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
        rel=(c['stock_project_rel'] if e.get('side')=='stock_project' else c['flow_rel'])+'/'+e['path'];q=safe_path(root,rel);q.parent.mkdir(parents=True,exist_ok=True);step=e['step'];source_id=plan['mapping'].get(step)
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

def archive_course(layer,*,stock_runtime=None):
    """Archive only validated new-course artifacts; shared Stock uses its unchanged runtime."""
    from validate_package import validate
    layer=Path(layer).absolute();c=build_contract(layer);root=safe_path(layer,c['package_root'])
    if c.get('course_id',LEGACY_COURSE)==LEGACY_COURSE:raise ValueError('legacy archive stays on the existing route')
    if c.get('storage')=='registry_stock_v1':raise ValueError('registry_stock_v1 (shared Stock) is not included in this package')
    result=validate(root,phase='prearchive',layer=layer)
    if not result['pass']:return result
    m=load(root/'manifest.yaml');start=datetime.now(timezone.utc).isoformat()
    if any(r.get('archive_path') is not None for r in m['records']): raise ValueError('already archived; do not overwrite')
    for r in m['records']:
        e=next(e for e in c['documents'] if e['step']==r['source_step'])
        if e.get('side'):continue
        dest=c['stock_project_rel']+'/documents/'+e['path'];q=safe_path(root,dest)
        if q.exists():raise ValueError('archive counterpart already exists')
        q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(safe_path(root,r['path']),q);r.update(status='archived_local_final',archive_path=dest,archive_sha256=sha(q))
    m['stages'].append({'name':'archive','started_at':start,'finished_at':datetime.now(timezone.utc).isoformat(),'checkpoint_actor':'auto_decision','checkpoint_status':'accepted_local','evidence_refs':[r['id'] for r in m['source_reads']]})
    (root/'manifest.yaml').write_text(yaml.safe_dump(m,allow_unicode=True,sort_keys=False))
    return validate(root,phase='final',layer=layer)

def build_contract(layer):
    layer=Path(layer).absolute();d=intent(layer)
    if not select(layer): raise ValueError('AIPM not explicitly selected')
    a=d.get('aipm',{})
    if not isinstance(a,dict): raise ValueError('aipm must be map')
    chosen=course_id(layer)
    scope=slug(d.get('scope_id'),'scope_id');project=slug(a.get('project_id',d.get('scope_name',scope)),'project_id')
    day=a.get('date')
    saved=safe_path(layer,'Documents/aipm_project/format_contract.yaml')
    saved_c=load(saved) if saved.is_file() else None
    if not isinstance(saved_c,dict):saved_c={}
    if day is None and saved_c: day=saved_c.get('bindings',{}).get('date')
    if day is None:
        day=next((x.name for x in layer.parents if re.fullmatch(r'\d{4}-\d{2}-\d{2}',x.name)),date.today().isoformat())
    day=date.fromisoformat(str(day)).isoformat()
    bindings={'program_id':slug(a.get('program_id',scope.replace('-','_')),'program_id'),'project_id':project,'participant_name':str(d.get('owner') or '[unknown]'),'flow_dir':project,'date':day,'persona_id':slug(a.get('persona_id','P001'),'persona_id'),'name_slug':slug(a.get('name_slug','user'),'name_slug'),'type':'user'}
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
    c.update(scope_id=scope,bindings=bindings,package_root='Documents/aipm_project',flow_rel='Flow/'+day[:7].replace('-','')+'/'+day+'/'+project,stock_project_rel='Stock/programs/'+bindings['program_id']+'/projects/'+project)
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
        # Charter remains a Flow draft until archive. This is NOT a Stock folder.
        c['stock_project_rel']=c['flow_rel']+'/_charter'
    return c

INIT_NOTE='Init 直後の validate は 19文書と manifest が無いので E_MISSING で不合格になるのが正常。registers だけ見るなら E_REGISTERS の件数を見る'
RESET_NOTE='残った受領記録は古い対象を指すので、聞き直すときは新しい question_id を使う'
DRAFT_ITEM_KEYS={'wbs':('deliverable','exit_criteria'),'issues':('question',),'hypotheses':('claim',)}   # plus source_refs (required for wbs)
FLOW_REF=r'^Flow@[0-9a-fA-F]{7,40}:.+$'

def init_documents(layer,c):
    """project_init.yaml and README.md exactly as init writes them; reset-to-init rebuilds them the same way.
    Returns {package-relative path: text} in the order init writes them."""
    b=c['bindings'];initial={k:'[unknown]' for k in c['documents'][-2]['schema']['fields']}
    initial.update(program_id=b['program_id'],project_id=b['project_id'],participant_name=b['participant_name'],flow_dir=b['flow_dir'],flow_base=c['flow_rel'],stock_base=c['stock_project_rel'],period=b['date'],purpose=intent(layer).get('goal',{}).get('description','[unknown]'),share_repo='disabled',share_local_dir='disabled')
    readme='# '+b['project_id']+'\n\n'+''.join('## '+h+'\n\n[unknown] 初期下書き。実根拠を読んで更新する。\n\n' for h in c['documents'][-1]['required_headings'])
    return {c['flow_rel']+'/project_init.yaml':yaml.safe_dump(initial,allow_unicode=True,sort_keys=False),c['stock_project_rel']+'/README.md':readme}

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
        if drafts is not None:raise ValueError('--drafts needs the bundled PM addon (aipm)')
        return {'route':'legacy','created':False}
    c=build_contract(layer);root=safe_path(layer,c['package_root'])
    if drafts is not None:
        if root.exists():raise ValueError('package already exists; --drafts is only used by the first init (nothing written)')
        parsed=init_drafts_input(layer,c,drafts)
    shared=c.get('storage')=='registry_stock_v1'
    if shared:
        try:
            from shared_stock import require_runtime
        except ImportError:
            raise ValueError('registry_stock_v1 (shared Stock) is not included in this package') from None
        require_runtime(stock_runtime,layer).bind(c['stock_selector'])
    if root.exists():
        if not (root/'format_contract.yaml').is_file() or load(root/'format_contract.yaml')!=c:
            raise ValueError('existing Project has another contract; do not overwrite')
        return {'route':'aipm','created':False,'package':str(root),'contract':c,'outputs':existing_outputs(root,c),'note':INIT_NOTE}
    source=json.loads((METHOD/'source/source_manifest.json').read_text())
    for e in source['files']:
        if sha(METHOD/'source'/e['path'])!=e['sha256']: raise ValueError('fixed source changed')
    for e in c['documents']:
        if sha(METHOD/e['raw_template'])!=e['template_sha256']: raise ValueError('fixed template changed')
    root.mkdir(parents=True)
    for base in ([c['flow_rel']] if shared else [c['flow_rel'],c['stock_project_rel']+'/documents']):
        for folder in c['folders']:safe_path(root,base+'/'+folder).mkdir(parents=True,exist_ok=True)
    if shared:safe_path(root,c['stock_project_rel']).mkdir(parents=True,exist_ok=True)
    (root/'format_contract.yaml').write_text(yaml.safe_dump(c,allow_unicode=True,sort_keys=False))
    docs=init_documents(layer,c)
    for rel,text in docs.items():(root/rel).write_text(text)
    written=registers_drafts(root,c,parsed if drafts is not None else None) if 'registers_contract_version' in c else []
    made=['format_contract.yaml',*docs]+written
    outputs=[{'path':'Documents/aipm_project/'+rel,'sha256':sha(root/rel)} for rel in made]  # for intent.mode_init.outputs (01-collection Phase 7.5)
    result={'route':'aipm','created':True,'package':str(root),'state':'initialized_draft','required_documents':19,'contract':c,'registers':written,'outputs':outputs,'note':INIT_NOTE}
    if drafts is not None:   # wbs.yaml has no field for where a row came from (registers contract unchanged); keep these in the Collection record
        result.update(drafts=drafts,wbs_source_refs={'W'+str(n):r['source_refs'] for n,r in enumerate(parsed['wbs'],1)})
    return result

def brief_init(result):
    """The init result without the full contract, for the CLI --brief. The function result is unchanged."""
    out={k:result[k] for k in ('route','created','package','state','required_documents','registers','outputs','drafts','wbs_source_refs','note') if k in result}
    if 'contract' in result:
        out['contract_version']=result['contract']['version']
        if 'registers_contract_version' in result['contract']:out['registers_contract_version']=result['contract']['registers_contract_version']
    return out

def existing_outputs(root,c):
    """path/sha256 of the init outputs that already exist (for mode_init.outputs on re-run)."""
    rels=['format_contract.yaml',c['flow_rel']+'/project_init.yaml',c['stock_project_rel']+'/README.md']
    if 'registers_contract_version' in c:rels+=[f['path'] for f in registers_contract(c)['files'].values()]
    return [{'path':'Documents/aipm_project/'+r,'sha256':sha(root/r)} for r in rels if (root/r).is_file()]

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
        rel=c['flow_rel']+'/'+e['path']
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

def wbs_candidate(layer,task_id):
    """04-operation Phase 6: add a completed task's output to its WBS row as evidence. The row becomes
    pending_acceptance only when every task with the same wbs_id is completed (cancelled do not count).
    Never sets accepted; leaves accepted/cancelled rows unchanged; keeps partially_accepted and an existing pending_acceptance."""
    layer=Path(layer).absolute();c=build_contract(layer)
    if 'registers_contract_version' not in c:return {'route':'unselected','changed':False,'reason':'aipm.registers is not selected'}
    bl=load(safe_path(layer,'backlog.yaml'));tasks=[t for t in (bl.get('tasks') or []) if isinstance(t,dict) and t.get('id')==task_id]
    if len(tasks)!=1:raise ValueError('task not found: '+str(task_id))
    t=tasks[0];w=t.get('wbs_id')
    if w in (None,'none'):return {'route':'aipm','changed':False,'reason':'task has no wbs_id'}
    if t.get('status')!='completed':raise ValueError('task is not completed; update backlog first')
    outs=t.get('output');outs=outs if isinstance(outs,list) else ([outs] if outs else [])
    if not outs:raise ValueError('completed task has no output to use as evidence')
    for o in outs:
        if not safe_path(layer,o).exists():raise ValueError('task output missing: '+o)
    root=safe_path(layer,c['package_root']);q=safe_path(root,registers_contract(c)['files']['wbs']['path'])
    data=load(q);rows=[r for r in data.get('wbs') or [] if isinstance(r,dict) and r.get('id')==w]
    if len(rows)!=1:raise ValueError('WBS row not found: '+w)
    r=rows[0];before=r.get('status')
    if before in ('accepted','cancelled'):return {'route':'aipm','changed':False,'wbs_id':w,'status':before,'reason':'row is '+before+'; not changed'}
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
    out={'route':'aipm','changed':True,'wbs_id':w,'status_before':before,'status':r['status'],'evidence_refs':ev,'pending_tasks':pending,'note':note}
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
        doc=next((d for d in c['documents'] if path.endswith('/'+d['path']) and not d.get('side')),None)
        return bool(doc) and STAGE_OF_PREFIX.get(doc['path'][:2]) in later
    return False

def bind_legacy(m,rel,out,r,inp,stage,target_rel,received,stage_end,mp,vp,root,layer,validate,key,baseline):
    """receipt's manifest step for a legacy stage (the caller restores manifest/validation_record and removes the receipt on failure)."""
    m.setdefault('human_responses',{})[stage]={'answer':inp['answer'],'source':rel,'source_sha256':sha(out),'target_path':target_rel,'target_sha256':r['target_sha256']}
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
    m.setdefault('human_responses',{})[stage]={'answer':inp['answer'],'source':rel,'source_sha256':sha(out),'target_path':target_rel,'target_sha256':r['target_sha256']}
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
    p=argparse.ArgumentParser();p.add_argument('action',choices=['route','init','contract','plan','draft','archive','wbs-candidate','receipt','judge','reset-to-init','op']);p.add_argument('--layer',required=True);p.add_argument('--input');p.add_argument('--task')
    p.add_argument('--name',help='op: <item>.<verb> of a pm- operation (issue.add, hypothesis.propose, todo.move, ...) or check')
    p.add_argument('--drafts',help='init: Layer-relative YAML of the WBS (and optional issues/hypotheses) drafts');p.add_argument('--brief',action='store_true',help='init: print without the full contract')
    p.add_argument('--apply',action='store_true',help='reset-to-init: move and restore / op: write after the trial (default is a dry-run for both)');p.add_argument('--retire',help='reset-to-init: new Layer-relative folder outside the package');a=p.parse_args()
    try:
        if a.action=='route': result={'route':'aipm' if select(a.layer) else 'legacy'}
        elif a.action=='init':
            result=init(a.layer,drafts=a.drafts)
            if a.brief:result=brief_init(result)
        elif a.action=='reset-to-init':result=reset_to_init(a.layer,apply=a.apply,retire=a.retire)
        elif a.action=='plan':
            plan=course_plan(a.layer,a.input);result={k:v for k,v in plan.items() if k not in ['packet','texts','contract']}
        elif a.action=='draft':result=batch_draft(a.layer,a.input)
        elif a.action=='archive':result=archive_course(a.layer)
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
