"""Edits of the registers (issues, hypotheses, todo, wbs, roadmap) of an AIPM box in the apply way.

An edit proposal (R-*.yaml) appends material or a note to an existing row, or adds a new row; the person judges a numbered
list (rlist_<digest>.yaml) with the five replies; only adopted proposals are written, and each write leaves one entry in the
manifest's register_edits[] with the person's words, the time, the conversation id and the list digest. Judgement fields
(status, answer, resolved, judgements, ...) are never written here: the person uses judge / resolve. An unsettled row is held,
never written. A saved box is written only when it carries versions (applies) whose last one is pushed. Every write checks
first, compares the check after (E_REGISTERS; validate final for a saved box) and puts everything back when it is worse.
"""
import hashlib, json, os, re, shutil
from datetime import date, datetime, timezone
from pathlib import Path
import yaml
import changes
from package import load, safe_path, sha, slug, build_contract, FLAT_LAYOUTS
from ops import _next_id, _registers_problems, _files

CHANGES='Context/aipm_changes'
REGISTERS=('issues','hypotheses','todo','wbs','roadmap')
PREFIX={'issues':'I','hypotheses':'H','todo':'D','wbs':'W','roadmap':'MS'}
# what op: append may touch (design §2); anything else stops. issues.evidence_refs is resolution evidence, never material
APPEND={'issues':('sources',),'hypotheses':('sources','evidence'),'wbs':('evidence_refs','milestone_id'),'todo':('note',),'roadmap':('note','wbs_ids')}
PATH_FIELDS=('sources',)
NOTE_FIELDS=('note',)
NEW_STATUS={'issues':('open',),'hypotheses':('unknown',),'todo':('todo',),'wbs':('draft','planned'),'roadmap':('draft','planned')}
JUDGEMENT_FIELDS={'answer','resolved','decided_by','reason','judgements','validation_plan','evidence_refs','review_at'}   # a new row never carries these (issues / hypotheses)
WBS_REFS=('milestone_id','issue_ids','depends')
UNSETTLED={'','未定','未確定','tbd','TBD','[unknown]','undecided?'}
HYP_SETTLED=('kind','claim','method','success','falsification')
# what op: fill may set, only while the field is still unsettled (undecided / [unknown] / empty) — the person's later decision
# on a field left open at init (issue due dates). A settled value is never overwritten here.
FILL={'issues':('due','owner','priority'),'todo':('due','owner','priority','wbs_id')}
DATE_FIELDS=('due',)

def _now():return datetime.now(timezone.utc).isoformat()
def _dump(data):return yaml.safe_dump(data,allow_unicode=True,sort_keys=False)
def _rowsha(row):return hashlib.sha256(json.dumps(row,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def _list_key(name):return name   # every register keeps its rows under its own name (issues: issues, ...)
def _plain(v):
    """A date or datetime that YAML read from an unquoted value becomes its ISO text (the registers keep dates as text)."""
    if isinstance(v,(datetime,date)):return v.isoformat()
    if isinstance(v,dict):return {k:_plain(x) for k,x in v.items()}
    if isinstance(v,list):return [_plain(x) for x in v]
    return v
def _unsettled(v):return v is None or (isinstance(v,str) and v.strip() in UNSETTLED) or (isinstance(v,list) and not v)

# ---- the box ----
def state(layer):
    """(layer, contract, package root, manifest or {}, saved, versionable, files) — and stops when a saved box cannot be written."""
    layer=Path(layer).absolute();c,rc,files=_files(layer);root=safe_path(layer,c['package_root'])
    mq=root/'manifest.yaml';m=load(mq) if mq.is_file() else {}
    saved=any(isinstance(r,dict) and r.get('archive_path') for r in m.get('records') or [])
    versionable=c.get('layout') in FLAT_LAYOUTS and c.get('storage')!='registry_stock_v1'
    return layer,c,root,m,saved,versionable,files
def writable(layer):
    """Design §5 condition 1: the box form, and for a saved box its versions."""
    layer,c,root,m,saved,versionable,files=state(layer)
    if not versionable:raise ValueError('this box cannot carry versions (nested_v1 or shared Stock); redit is for sheets_v1 / box_root_v1 boxes (migrate-sheets first; nothing written)')
    applies=m.get('applies')
    if saved:
        if not isinstance(applies,list) or not applies:raise ValueError('the box is saved but has no versions; run package.py register first (nothing written)')
        if applies[-1].get('pushed') is not True:raise ValueError('the box has a version not pushed yet; push or revert it first (nothing written)')
    return layer,c,root,m,saved,files
def saved_versionable(layer):
    """For ops: a saved box that can carry versions (its pm- writes go through redit — design §8)."""
    try:layer,c,root,m,saved,versionable,files=state(layer)
    except Exception:return False
    return saved and versionable

# ---- proposals ----
def _rfiles(layer):
    d=safe_path(layer,CHANGES);return sorted(d.glob('R-*.yaml')) if d.is_dir() else []
def proposals(layer):return [load(q) for q in _rfiles(layer)]
def _new_ids(layer,count):
    day=datetime.now(timezone.utc).astimezone().strftime('%Y%m%d')
    used=[int(x.group(1)) for q in _rfiles(layer) for x in [re.fullmatch('R-'+day+r'-([0-9]+)',q.stem)] if x]
    n=max(used,default=0);return ['R-'+day+'-'+str(n+k).zfill(2) for k in range(1,count+1)]
def _rows(data,register):
    rows=data.get(_list_key(register)) if isinstance(data,dict) else None
    if not isinstance(rows,list):raise ValueError(register+' has no row list (nothing written)')
    return rows
def _row(rows,rid,register):
    hit=[r for r in rows if isinstance(r,dict) and r.get('id')==rid]
    if len(hit)!=1:raise ValueError(register+' row not found: '+str(rid)+' (nothing written)')
    return hit[0]

def check_edit(n,x,data,rc,layer):
    """Checks one input edit against the registers now. Returns ('ok', proposal part) or ('held', reason); raises to stop."""
    if not isinstance(x,dict):raise ValueError('edit '+str(n)+' must be a map (nothing written)')
    reg=x.get('register');op=x.get('op')
    if reg not in REGISTERS:raise ValueError('edit '+str(n)+': register must be one of '+', '.join(REGISTERS)+' (nothing written)')
    spec=rc['files'][reg];rows=_rows(data[reg],reg)
    if op=='append':
        f=x.get('field')
        if f in ('status','answer','resolved','judgements','decided_by','reason','verdict'):raise ValueError('edit '+str(n)+': '+reg+'.'+str(f)+' is a judgement the person makes (judge / resolve); redit never writes it (nothing written)')
        if f not in APPEND[reg]:raise ValueError('edit '+str(n)+': '+reg+'.'+str(f)+' cannot be appended (allowed: '+', '.join(APPEND[reg])+'; nothing written)')
        if f not in spec['required'] and f not in (spec.get('optional') or []):raise ValueError('edit '+str(n)+': '+reg+'.'+str(f)+' is not in this box\'s registers contract (an older version; nothing written)')
        row=_row(rows,x.get('row'),reg)
        if f in NOTE_FIELDS:
            v=x.get('value')
            if not isinstance(v,str) or not v.strip():raise ValueError('edit '+str(n)+': a note needs value (a sentence; nothing written)')
            part={'field':f,'value':v.strip()}
        elif f=='milestone_id':
            v=x.get('value')
            if row.get('milestone_id') not in (None,''):raise ValueError('edit '+str(n)+': '+row['id']+' already has a milestone_id (nothing written)')
            if not isinstance(v,str) or v not in {r.get('id') for r in _rows(data['roadmap'],'roadmap') if isinstance(r,dict)}:raise ValueError('edit '+str(n)+': milestone_id must name a roadmap row (nothing written)')
            part={'field':f,'value':v}
        else:
            vs=x.get('values')
            if not isinstance(vs,list) or not vs or any(not isinstance(v,str) or not v.strip() for v in vs):raise ValueError('edit '+str(n)+': values must be a non-empty list of strings (nothing written)')
            if f in PATH_FIELDS:
                for v in vs:
                    if not re.match(r'^(Stock/|Flow@)',v) and not safe_path(layer,v).is_file():raise ValueError('edit '+str(n)+': source not found: '+v+' (nothing written)')
            if reg=='wbs' and f=='evidence_refs':   # as validate: an H id that exists, or a path in the Layer that exists
                hyps={r.get('id') for r in _rows(data['hypotheses'],'hypotheses') if isinstance(r,dict)}
                for v in vs:
                    if re.fullmatch(r'H\d+',v):
                        if v not in hyps:raise ValueError('edit '+str(n)+': evidence points to unknown id '+v+' (nothing written)')
                    else:
                        try:ok_=safe_path(layer,v).exists()
                        except Exception:ok_=False
                        if not ok_:raise ValueError('edit '+str(n)+': evidence missing: '+v+' (nothing written)')
            if f=='wbs_ids':
                known={r.get('id') for r in _rows(data['wbs'],'wbs') if isinstance(r,dict)}
                if any(v not in known for v in vs):raise ValueError('edit '+str(n)+': wbs_ids must name wbs rows (nothing written)')
            part={'field':f,'values':[v.strip() for v in vs]}
        return 'ok',{'op':'append','target':{'register':reg,'row':row['id']},'append':part,'row_data':None,'base_row':_rowsha(row)}
    if op=='add_row':
        rd=x.get('row_data')
        if not isinstance(rd,dict):raise ValueError('edit '+str(n)+': add_row needs row_data (nothing written)')
        if 'id' in rd:raise ValueError('edit '+str(n)+': a new row gets its id when written; do not give one (nothing written)')
        rd=_plain(rd)
        if 'sources' in rd and _unsettled(rd['sources']):rd={k:v for k,v in rd.items() if k!='sources'}   # an empty sources is left out (validate wants a non-empty list)
        if 'sources' in rd and rd['sources'] is not None and not isinstance(rd['sources'],list):raise ValueError('edit '+str(n)+': sources must be a list of paths (nothing written)')
        if reg=='todo' and rd.get('source') is not None and not isinstance(rd['source'],(str,list)):raise ValueError('edit '+str(n)+': todo.source is text or a list of ids (nothing written)')
        for k in {'issues':('owner','due','question'),'hypotheses':('claim',)}.get(reg,()):
            if k in rd and rd[k] is not None and not isinstance(rd[k],str):raise ValueError('edit '+str(n)+': '+reg+'.'+k+' must be text (nothing written)')
        if 'source_of_truth' in rd and rd['source_of_truth'] not in (rc.get('source_of_truth') or ['local']):raise ValueError('edit '+str(n)+': source_of_truth must be one of '+', '.join(rc.get('source_of_truth') or ['local'])+' (nothing written)')
        unknown=[k for k in rd if k not in spec['required'] and k not in spec.get('optional',[])]
        if unknown:raise ValueError('edit '+str(n)+': unknown keys '+', '.join(unknown)+(' （この箱の一覧は結び目の列に対応しない古い版です）' if reg=='todo' and set(unknown)&{'done_when','updated_on','blocked_by','confirmed_on'} else '')+' (nothing written)')
        if reg=='todo':
            if 'confirmed_on' in rd:raise ValueError('edit '+str(n)+': confirmed_on is the owner\'s confirmation; a new row never carries it (nothing written)')
            from validate_package import knot_problems
            ke=knot_problems(spec,rd)[0]
            if ke:raise ValueError('edit '+str(n)+': '+'; '.join(ke)+' (nothing written)')
        judge=[k for k in rd if k in JUDGEMENT_FIELDS and reg in ('issues','hypotheses')]
        if judge:raise ValueError('edit '+str(n)+': '+', '.join(judge)+' are judgement fields; a new row never carries them (nothing written)')
        if reg=='wbs' and any(k in rd for k in WBS_REFS):raise ValueError('edit '+str(n)+': a new wbs row carries no milestone_id / issue_ids / depends (link it later with a pair of appends; nothing written)')
        if reg=='roadmap' and 'wbs_ids' in rd:raise ValueError('edit '+str(n)+': a new roadmap row carries no wbs_ids (link it later with a pair of appends; nothing written)')
        if reg=='hypotheses' and 'priority' in rd and _unsettled(rd['priority']):rd={k:v for k,v in rd.items() if k!='priority'}   # optional: left out until the person decides
        if reg=='issues' and 'parent' in rd and not _unsettled(rd['parent']) and not isinstance(rd['parent'],str):raise ValueError('edit '+str(n)+': issues.parent is one id (nothing written)')
        if reg=='wbs' and isinstance(rd.get('schedule'),dict) and rd['schedule'].get('forecast') is not None:
            fc=rd['schedule']['forecast']
            if not isinstance(fc,dict):raise ValueError('edit '+str(n)+': schedule.forecast must be a map (nothing written)')
            from validate_package import _as_date
            a_,b_=_as_date(fc.get('start')),_as_date(fc.get('end'))
            if a_ and b_ and b_<a_:raise ValueError('edit '+str(n)+': schedule.forecast ends before it starts (nothing written)')
        refs={**(spec.get('refs') or {}),**({'issue_id':'issues'} if reg=='hypotheses' else {})}
        rd={k:v for k,v in rd.items() if not (k in refs and _unsettled(v))}   # an undecided optional reference is left out (written later with the person's answer)
        for k,target in refs.items():   # a reference names a row that exists now (otherwise the check after writing would put every adoption back)
            if k in rd:
                known={r.get('id') for r in _rows(data[target],target) if isinstance(r,dict)}
                vals=rd[k] if isinstance(rd[k],list) else [rd[k]]
                if any(not isinstance(v,str) for v in vals):raise ValueError('edit '+str(n)+': '+reg+'.'+k+' must reference ids (nothing written)')
                bad=[v for v in vals if v not in known]
                if bad:raise ValueError('edit '+str(n)+': '+reg+'.'+k+' points to unknown id '+', '.join(map(str,bad))+' (nothing written)')
        if reg=='todo':
            if isinstance(rd.get('source'),list) and any(not isinstance(s_,str) for s_ in rd['source']):raise ValueError('edit '+str(n)+': todo.source is text or a list of ids (nothing written)')
            for s_ in (rd.get('source') if isinstance(rd.get('source'),list) else [rd.get('source')]):
                if isinstance(s_,str) and re.fullmatch(r'[IH]\d+',s_.strip()):
                    target='issues' if s_.strip()[0]=='I' else 'hypotheses'
                    if s_.strip() not in {r.get('id') for r in _rows(data[target],target) if isinstance(r,dict)}:raise ValueError('edit '+str(n)+': todo.source points to unknown id '+s_+' (nothing written)')
        if reg=='hypotheses':
            for k in ('kind','priority'):
                if k in rd and not _unsettled(rd[k]) and rd[k] not in (spec.get(k) or []):raise ValueError('edit '+str(n)+': hypotheses.'+k+' must be one of '+', '.join(spec.get(k) or [])+' (nothing written)')
        if reg=='wbs' and any(k in rd for k in ('gate','evidence_refs')):raise ValueError('edit '+str(n)+': a new wbs row carries no gate / evidence_refs (acceptance is the person\'s; append evidence later; nothing written)')
        if reg=='wbs' and 'schedule' in rd:
            sc=rd['schedule']
            if not isinstance(sc,dict) or any(k not in ('baseline','forecast','actual','history') for k in sc) or sc.get('baseline') is not None or sc.get('actual') is not None or sc.get('history') not in (None,[]):
                raise ValueError('edit '+str(n)+': a new wbs row may carry schedule.forecast only (baseline is the person\'s agreement, actual and history are records; nothing written)')
        for v in rd.get('sources') or []:
            if not isinstance(v,str) or (not re.match(r'^(Stock/|Flow@)',v) and not safe_path(layer,v).is_file()):raise ValueError('edit '+str(n)+': source not found: '+str(v)+' (nothing written)')
        st=rd.get('status',NEW_STATUS[reg][0])
        if st not in NEW_STATUS[reg]:raise ValueError('edit '+str(n)+': a new '+reg+' row starts as '+' or '.join(NEW_STATUS[reg])+', not '+str(st)+' (nothing written)')
        rd={**rd,'status':st}
        need=[k for k in spec['required'] if k not in ('id','status')]+([k for k in HYP_SETTLED if k not in spec['required']] if reg=='hypotheses' else [])
        open_=[k for k in need if k!='owner' and _unsettled(rd.get(k))]
        if open_:return 'held','unsettled: '+', '.join(open_)
        if reg in ('todo','wbs','issues') and _unsettled(rd.get('owner')):rd['owner']='[unknown]'
        if reg=='issues' and _unsettled(rd.get('due')):rd['due']='undecided'   # as pm- issue.add (an issue row needs owner and due)
        return 'ok',{'op':'add_row','target':{'register':reg,'row':None},'append':None,'row_data':rd,'base_row':None}
    if op=='fill':
        f=x.get('field')
        if f not in FILL.get(reg,()):raise ValueError('edit '+str(n)+': '+reg+'.'+str(f)+' cannot be filled (allowed: '+'; '.join(k+': '+', '.join(v) for k,v in FILL.items())+'; nothing written)')
        if f not in spec['required'] and f not in (spec.get('optional') or []):raise ValueError('edit '+str(n)+': '+reg+'.'+str(f)+' is not in this box\'s registers contract (an older version; nothing written)')
        row=_row(rows,x.get('row'),reg)
        st=row.get('status')
        if (reg=='issues' and st not in ('open','on_hold')) or (reg=='todo' and st in ('done','cancelled')):raise ValueError('edit '+str(n)+': '+row['id']+' is '+str(st)+'; fill is for rows still in progress (nothing written)')
        if not (_unsettled(row.get(f)) or (isinstance(row.get(f),str) and row.get(f).strip()=='undecided')):raise ValueError('edit '+str(n)+': '+row['id']+'.'+f+' is already '+str(row.get(f))+'; fill sets an unsettled field only (nothing written)')
        v=_plain(x.get('value'))
        if not isinstance(v,str) or _unsettled(v) or v.strip()=='undecided':raise ValueError('edit '+str(n)+': fill needs a decided value (nothing written)')
        v=v.strip()
        if f in DATE_FIELDS:
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',v):raise ValueError(v)
                date.fromisoformat(v)
            except ValueError:raise ValueError('edit '+str(n)+': '+f+' must be a date YYYY-MM-DD (nothing written)')
        if f=='wbs_id' and v not in {r.get('id') for r in _rows(data['wbs'],'wbs') if isinstance(r,dict)}:raise ValueError('edit '+str(n)+': todo.wbs_id points to unknown id '+v+' (nothing written)')
        return 'ok',{'op':'fill','target':{'register':reg,'row':row['id']},'append':{'field':f,'value':v,'before':row.get(f)},'row_data':None,'base_row':_rowsha(row)}
    raise ValueError('edit '+str(n)+': op must be append, add_row or fill (nothing written)')

def redit(layer,input_path,*,apply=False):
    """Make edit proposals from an input YAML (Layer-relative): source {kind, ref}, created_by, edits [...]. Unsettled rows are
    held (never proposals). Dry-run unless apply."""
    layer,c,root,m,saved,files=writable(layer)
    if 'registers_contract_version' not in c:raise ValueError('aipm.registers is not selected (nothing written)')
    from package import registers_contract
    rc=registers_contract(c)
    d=load(safe_path(layer,changes._text(input_path,'--input')))
    if not isinstance(d,dict) or not isinstance(d.get('edits'),list) or not d['edits']:raise ValueError('the input needs an edits list (nothing written)')
    src=d.get('source')
    if not isinstance(src,dict) or src.get('kind') not in changes.SOURCE_KINDS:raise ValueError('source.kind must be one of '+', '.join(changes.SOURCE_KINDS)+' (nothing written)')
    changes._text(src.get('ref'),'source.ref')
    by=d.get('created_by','ai')
    if by not in ('ai','owner'):raise ValueError('created_by must be ai or owner (nothing written)')
    data={k:load(files[k]) for k in REGISTERS};fsha={k:sha(files[k]) for k in REGISTERS}
    made=[];held=[]
    seen_fill=set()
    for n,x in enumerate(d['edits'],1):
        kind,part=check_edit(n,x,data,rc,layer)
        if kind=='ok' and part['op']=='fill':
            key=(part['target']['register'],part['target']['row'],part['append']['field'])
            if key in seen_fill:raise ValueError('edit '+str(n)+': '+'.'.join(key)+' is filled twice in this input (nothing written)')
            seen_fill.add(key)
        if kind=='held':held.append({'n':n,'register':x.get('register'),'reason':part,'edit':x});continue
        made.append((x,part))
    ids=_new_ids(layer,len(made));at=_now();out_p=[]
    for i,(x,part) in zip(ids,made):
        reg=part['target']['register']
        out_p.append({'id':i,'created_at':at,'created_by':by,'source':{'kind':src['kind'],'ref':src['ref']},'op':part['op'],'target':part['target'],
                      'append':part['append'],'row':part['row_data'],'base':{'register_sha256':fsha[reg],'row_sha256':part['base_row']},
                      'reason':x['reason'].strip() if isinstance(x.get('reason'),str) and x['reason'].strip() else 'see source',
                      'judgment':{'state':'undecided'},'merge':{'state':'not_merged'}})
    out={'route':'aipm','apply':bool(apply),'proposals':out_p,'held':held}
    if not apply:return out
    dirp=safe_path(layer,CHANGES);dirp.mkdir(parents=True,exist_ok=True);written=[]
    try:
        for p_ in out_p:
            f=safe_path(layer,CHANGES+'/'+p_['id']+'.yaml')
            with open(f,'x') as h:written.append(f);h.write(_dump(p_))
        if held:
            hq=safe_path(layer,CHANGES+'/rheld_'+Path(input_path).stem+'.yaml')
            if hq.exists():raise ValueError(str(hq.relative_to(layer))+' already exists')
            with open(hq,'x') as h:written.append(hq);h.write(_dump({'input':input_path,'at':at,'held':held}))
    except BaseException as ex:
        for f in written:f.unlink(missing_ok=True)
        raise ValueError('redit stopped ('+type(ex).__name__+': '+str(ex)+'); nothing written') from ex
    out['written']=[str(f.relative_to(layer)) for f in written]
    return out

# ---- the numbered list and the judgement ----
def _entries(layer):
    ps=sorted((p for p in proposals(layer) if (p.get('merge') or {}).get('state')=='not_merged'),key=lambda p:p['id'])
    return [{'n':n,'id':p['id'],'content_sha256':changes.content_sha(p)} for n,p in enumerate(ps,1)]
def _lists(layer):
    d=safe_path(layer,CHANGES);return [load(q)|{'_path':q} for q in d.glob('rlist_*.yaml')] if d.is_dir() else []
def redit_list(layer):
    layer,c,root,m,saved,files=writable(layer)
    entries=_entries(layer)
    if not entries:raise ValueError('no registers proposal to judge (nothing written)')
    dg=changes._digest(entries);q=safe_path(layer,CHANGES+'/rlist_'+dg+'.yaml');written=False
    if not q.exists():
        with open(q,'x') as f:f.write(_dump({'digest':dg,'created_at':_now(),'entries':entries,'replies':[]}))
        written=True
    by={p['id']:p for p in proposals(layer)}
    def show(p):
        if p['op']=='add_row':return {'add_row':p['target']['register'],'row':p['row']}
        if p['op']=='fill':a=p['append'];return {'fill':p['target']['register']+'.'+p['target']['row']+'.'+a['field'],'value':a['value'],'before':a.get('before')}
        a=p['append'];return {'append':p['target']['register']+'.'+p['target']['row']+'.'+a['field'],'value':a.get('value',a.get('values'))}
    rows=[{'n':e['n'],'id':e['id'],**show(by[e['id']]),'judgment':by[e['id']]['judgment']['state']} for e in entries]
    return {'route':'aipm','list':str(q.relative_to(layer)),'digest':dg,'digest_short':dg[:12],'written':written,'rows':rows,'replies':'OK（全件反映）／採用: 1,3／修正: 2 は「…」に直す（note だけ）／今回はレポートのみ／差し戻し'}

def redit_judge(layer,digest,quote,at,thread):
    """The person's reply to the saved list (thread required — design §5 condition 3). 修正 changes the value of a note only."""
    layer,c,root,m,saved,files=writable(layer)
    changes._text(quote,'--quote');t=changes._aware(at);changes._text(digest,'--list');changes._text(thread,'--thread')
    if not re.fullmatch(r'[0-9a-f]{12,64}',digest):raise ValueError('--list is the list digest (at least its first 12 characters; nothing written)')
    found=[q for q in safe_path(layer,CHANGES).glob('rlist_'+digest+'*.yaml')] if safe_path(layer,CHANGES).is_dir() else []
    if len(found)!=1:raise ValueError('no single saved list for '+digest+' (nothing written)')
    lq=found[0];saved_l=load(lq)
    if changes._digest(_entries(layer))!=saved_l['digest']:raise ValueError('the proposals changed after this list; show the list again and ask again (nothing written)')
    if t<datetime.fromisoformat(saved_l['created_at']):raise ValueError('the words are older than the list (nothing written)')
    kind,nums,text=changes.parse_reply(quote,len(saved_l['entries']))
    by={e['n']:e['id'] for e in saved_l['entries']}
    state_={'all':'adopted','adopt':'adopted','revise':'adopted','report_only':'held','send_back':'rejected'}[kind]
    targets=[by[n] for n in nums] if kind in ('all','adopt','revise') else [e['id'] for e in saved_l['entries']]
    rec={'state':state_,'quote':quote,'at':t.isoformat(),'list_digest':saved_l['digest'],'reply':kind,'thread':thread}
    fs={i:safe_path(layer,CHANGES+'/'+i+'.yaml') for i in targets};old={i:(f.read_bytes(),f.stat().st_mtime_ns) for i,f in fs.items()};done=[]
    for i,f in fs.items():
        p=load(f)
        if kind in ('report_only','send_back') and (p.get('merge') or {}).get('state')!='not_merged':continue   # the latest words win over an earlier adoption not written yet (a revert, a changed proposal)
        if kind=='revise':
            if p['op']!='append' or p['append']['field'] not in NOTE_FIELDS:raise ValueError('修正 changes the text of a note only; send it back and make a new proposal (nothing written)')
            p['append']['value']=text
        p['judgment']={**rec,'content_sha256':changes.content_sha(p)} if state_=='adopted' else rec   # the content the person adopted (after 修正)
        if state_=='rejected':p['merge']={'state':'not_applicable'}
        done.append((f,p))
    lold=(lq.read_bytes(),lq.stat().st_mtime_ns);new_list=None;before=set(safe_path(layer,CHANGES).glob('rlist_*.yaml'))
    try:
        for f,p in done:f.write_text(_dump(p))
        saved_l['replies'].append({'quote':quote,'at':t.isoformat(),'reply':kind,'numbers':nums,'thread':thread});lq.write_text(_dump(saved_l))
        if kind=='revise':new_list=redit_list(layer)
    except BaseException as ex:
        for i,f in fs.items():f.write_bytes(old[i][0]);os.utime(f,ns=(old[i][1],old[i][1]))
        lq.write_bytes(lold[0]);os.utime(lq,ns=(lold[1],lold[1]))
        for q in set(safe_path(layer,CHANGES).glob('rlist_*.yaml'))-before:q.unlink(missing_ok=True)
        raise ValueError('redit-judge stopped ('+type(ex).__name__+': '+str(ex)+'); nothing changed') from ex
    out={'route':'aipm','list_digest':saved_l['digest'],'reply':kind,'judged':[p['id'] for f,p in done],'state':state_}
    if new_list:out['new_list']={'digest':new_list['digest'],'digest_short':new_list['digest_short'],'list':new_list['list']}
    return out

# ---- write (redit-apply) ----
def _check(layer,root,saved):
    from validate_package import validate
    if saved:
        r=validate(root,phase='final',layer=layer);return r['pass'],{(e['code'],e['path'],e['message']) for e in r['errors']}
    return True,_registers_problems(layer)
def plan(layer):
    layer,c,root,m,saved,files=writable(layer)
    lists=_lists(layer)
    if not lists:raise ValueError('no list shown to the person yet; run redit-list and redit-judge first (nothing written)')
    if not _entries(layer):raise ValueError('no proposal left to write (all written or sent back; nothing written)')
    match=[x for x in lists if x.get('digest')==changes._digest(_entries(layer))]   # the list of the proposals as they are now (not merely the newest file)
    if len(match)!=1:raise ValueError('the proposals changed after the last list; show the list again and judge it (nothing written)')
    last=match[0]
    props={p['id']:p for p in proposals(layer)}
    adopted=[props[e['id']] for e in last['entries'] if props[e['id']]['judgment'].get('state')=='adopted' and props[e['id']]['merge'].get('state')=='not_merged']
    if not adopted:raise ValueError('no adopted proposal in the last list (nothing written)')
    for p in adopted:
        j=p['judgment']
        if not all(isinstance(j.get(k),str) and j[k].strip() for k in ('quote','at','thread','list_digest')):raise ValueError(p['id']+': the judgement lacks the words, time, conversation id or list digest (nothing written)')
        judged=[x for x in lists if x.get('digest')==j['list_digest']]
        if len(judged)!=1 or p['id'] not in {e['id'] for e in judged[0].get('entries') or []}:raise ValueError(p['id']+': the list the person answered is missing or does not carry this proposal (nothing written)')
        if not any((r.get('quote'),r.get('at'),r.get('thread'))==(j['quote'],j['at'],j['thread']) for r in judged[0].get('replies') or []):raise ValueError(p['id']+': the reply is not in the list the person answered (nothing written)')
        if j.get('content_sha256')!=changes.content_sha(p):raise ValueError(p['id']+': the proposal changed after the person adopted it; send it back or judge it again (nothing written)')
    data={k:load(files[k]) for k in REGISTERS};now_sha={k:sha(files[k]) for k in REGISTERS}
    for p in adopted:   # design §5 condition 4: every proposal against the state before writing
        reg=p['target']['register']
        if p['base']['register_sha256']!=now_sha[reg]:raise ValueError(p['id']+': '+reg+' changed after the proposal (an old proposal; nothing written)')
        if p['op'] in ('append','fill') and _rowsha(_row(_rows(data[reg],reg),p['target']['row'],reg))!=p['base']['row_sha256']:raise ValueError(p['id']+': the row changed after the proposal (nothing written)')
    fills=[(p['target']['register'],p['target']['row'],p['append']['field']) for p in adopted if p['op']=='fill']
    if len(fills)!=len(set(fills)):raise ValueError('two adopted fills set the same field; send one back (nothing written)')
    changed=[]
    for p in sorted(adopted,key=lambda p:p['id']):
        reg=p['target']['register'];rows=_rows(data[reg],reg)
        if p['op']=='append':
            row=_row(rows,p['target']['row'],reg);a=p['append'];f=a['field'];before=_rowsha(row)
            if f in NOTE_FIELDS:
                line=datetime.fromisoformat(p['judgment']['at']).astimezone().strftime('%Y-%m-%d')+': '+a['value']
                row[f]=(row[f].rstrip('\n')+'\n'+line) if isinstance(row.get(f),str) and row[f].strip() else line
            elif f=='milestone_id':row[f]=a['value']
            elif f=='evidence' and isinstance(row.get(f),str) and row[f].strip():   # a string hypotheses.evidence keeps its form: one line per value
                lines=row[f].split('\n');row[f]='\n'.join(lines+[v for v in a['values'] if v not in lines])
            else:
                cur=row.get(f) if isinstance(row.get(f),list) else ([row[f]] if isinstance(row.get(f),str) and row[f].strip() else [])   # a single path becomes a list
                row[f]=cur+[v for v in a['values'] if v not in cur]
            changed.append({'id':p['id'],'register':reg,'row':row['id'],'op':'append','field':f,'before_sha256':before,'after_sha256':_rowsha(row)})
        elif p['op']=='fill':
            row=_row(rows,p['target']['row'],reg);a=p['append'];before=_rowsha(row);row[a['field']]=a['value']
            changed.append({'id':p['id'],'register':reg,'row':row['id'],'op':'fill','field':a['field'],'before_sha256':before,'after_sha256':_rowsha(row)})
        else:
            rid=_next_id(rows,PREFIX[reg]);row={'id':rid,**p['row']};rows.append(row)
            changed.append({'id':p['id'],'register':reg,'row':rid,'op':'add_row','before_sha256':None,'after_sha256':_rowsha(row)})
    # design §5 condition 7: the wbs.milestone_id <-> roadmap.wbs_ids pair is adopted together
    wbs={r['id']:r for r in _rows(data['wbs'],'wbs') if isinstance(r,dict)};rm={r['id']:r for r in _rows(data['roadmap'],'roadmap') if isinstance(r,dict)}
    for p in adopted:
        if p['op']!='append':continue
        a=p['append']
        if a['field']=='milestone_id' and p['target']['row'] not in (rm.get(a['value'],{}).get('wbs_ids') or []):raise ValueError(p['id']+': '+p['target']['row']+'.milestone_id '+a['value']+' needs '+a['value']+'.wbs_ids to include '+p['target']['row']+' adopted in the same list (nothing written)')
        if a['field']=='wbs_ids':
            for w in a['values']:
                if (wbs.get(w) or {}).get('milestone_id')!=p['target']['row']:raise ValueError(p['id']+': '+p['target']['row']+'.wbs_ids '+w+' needs '+w+'.milestone_id = '+p['target']['row']+' adopted in the same list (nothing written)')
    ok,before=_check(layer,root,saved)
    if saved and not ok:raise ValueError('final does not pass before writing; fix that first (nothing written)')
    n=len(m.get('register_edits') or [])+1
    return {'layer':layer,'c':c,'root':root,'m':m,'saved':saved,'files':files,'list':last,'adopted':adopted,'data':data,'changed':changed,'before':before,'n':n}

def redit_apply(layer,*,apply=False,approval_ref=None):
    P=plan(layer)
    out={'route':'aipm','apply':bool(apply),'edit':P['n'],'list_digest':P['list']['digest'],'changes':P['changed']}
    if not apply:return out
    if not isinstance(approval_ref,str) or not approval_ref.strip():raise ValueError('--apply needs --approval-ref (the person\'s approval of this write; nothing written)')
    layer,root,m,files,n=P['layer'],P['root'],P['m'],P['files'],P['n']
    mq=root/'manifest.yaml';touched=sorted({x['register'] for x in P['changed']})
    if not mq.is_file():raise ValueError('the box has no manifest.yaml yet (draft the 19 documents first; nothing written)')
    stem=CHANGES+'/rbackup_'+str(n)+'_'+P['list']['digest'][:12];k=1   # the same list again after redit-revert: _2, _3 (a backup is never overwritten)
    while safe_path(layer,stem+('' if k==1 else '_'+str(k))).exists():k+=1
    bdir=safe_path(layer,stem+('' if k==1 else '_'+str(k)))
    saved_f={q:(q.read_bytes(),q.stat().st_mtime_ns) for q in [*files.values(),mq]};props_old={};made=[]
    try:
        bdir.mkdir(parents=True);made.append(bdir)
        for k,q in files.items():shutil.copy2(q,bdir/q.name)
        shutil.copy2(mq,bdir/'manifest.yaml')
        for k in touched:files[k].write_text(_dump(P['data'][k]))
        judg=[]
        for p in P['adopted']:
            j={k:p['judgment'][k] for k in ('quote','at','thread','list_digest')}
            if j not in judg:judg.append(j)
        m.setdefault('register_edits',[]).append({'edit':n,'at':_now(),'approval_ref':approval_ref,
            'base_version':(m.get('applies') or [{}])[-1].get('version') if m.get('applies') else None,'list_digest':P['list']['digest'],
            'judgments':judg,'changes':P['changed'],'registers_sha256':{k:sha(files[k]) for k in REGISTERS},'backup':str(bdir.relative_to(layer))})
        mq.write_text(_dump(m));(bdir/'applied_manifest.sha256').write_text(sha(mq)+'\n')
        for p in P['adopted']:
            f=safe_path(layer,CHANGES+'/'+p['id']+'.yaml');props_old[f]=(f.read_bytes(),f.stat().st_mtime_ns)
            q=load(f);q['merge']={'state':'merged','edit':n,'at':_now()};f.write_text(_dump(q))
        ok,after=_check(layer,root,P['saved'])
        worse=after-P['before']
        if worse:raise ValueError('the check is worse after writing: '+'; '.join(' '.join(e) for e in sorted(worse)[:3]))
    except BaseException as ex:
        for q,(b,t) in saved_f.items():q.write_bytes(b);os.utime(q,ns=(t,t))
        for f,(b,t) in props_old.items():f.write_bytes(b);os.utime(f,ns=(t,t))
        for d in made:shutil.rmtree(d,ignore_errors=True)
        raise ValueError('redit-apply stopped ('+type(ex).__name__+': '+str(ex)+'); the registers, the manifest and the proposals are as before') from ex
    out['written']=touched
    return out

def redit_revert(layer,*,apply=False,approval_ref=None):
    """Put back the last edit from its backup (design §5): only when the registers are still what that edit wrote and the
    manifest is what it wrote right after. The proposals of that edit become not_merged."""
    layer,c,root,m,saved,versionable,files=state(layer)
    edits=m.get('register_edits') or []
    if not edits:raise ValueError('no registers edit to revert (nothing written)')
    last=edits[-1];bdir=safe_path(layer,last.get('backup') or '-');mq=root/'manifest.yaml'
    if not (bdir/'manifest.yaml').is_file():raise ValueError('the backup of edit '+str(last['edit'])+' is missing (nothing written)')
    if {k:sha(files[k]) for k in REGISTERS}!=last.get('registers_sha256'):raise ValueError('the registers changed after edit '+str(last['edit'])+' (judge / resolve / todo.move or by hand); revert would lose it (nothing written)')
    mark=bdir/'applied_manifest.sha256'
    if not mark.is_file() or mark.read_text().strip()!=sha(mq):raise ValueError('the manifest changed after edit '+str(last['edit'])+'; revert would drop it (nothing written)')
    ids=[x['id'] for x in last['changes']]
    out={'route':'aipm','apply':bool(apply),'edit':last['edit'],'proposals':ids}
    if not apply:return out
    if not isinstance(approval_ref,str) or not approval_ref.strip():raise ValueError('--apply needs --approval-ref (nothing written)')
    ok,before=_check(layer,root,saved)
    saved_f={q:(q.read_bytes(),q.stat().st_mtime_ns) for q in [*files.values(),mq]};props={}
    try:
        for k,q in files.items():
            src=bdir/q.name;q.write_bytes(src.read_bytes());shutil.copystat(src,q)
        mq.write_bytes((bdir/'manifest.yaml').read_bytes());shutil.copystat(bdir/'manifest.yaml',mq)
        for i in dict.fromkeys(ids):
            f=safe_path(layer,CHANGES+'/'+i+'.yaml');props[f]=(f.read_bytes(),f.stat().st_mtime_ns);p=load(f);p['merge']={'state':'not_merged'};f.write_text(_dump(p))
        rec_dir=safe_path(layer,CHANGES);k_=1
        while True:
            rq=rec_dir/('rrevert_'+str(last['edit'])+'_'+str(last.get('list_digest') or '')[:12]+('' if k_==1 else '_'+str(k_))+'.yaml')
            if not rq.exists():break
            k_+=1
        props[rq]=None   # removed if anything below stops (even half written)
        with open(rq,'x') as f_:f_.write(_dump({'reverted_at':_now(),'approval_ref':approval_ref,'edit':last}))   # the edit as written (its approval and judgements) and the revert's approval
        ok2,after=_check(layer,root,saved)
        worse=after-before
        if worse:raise ValueError('the check is worse after revert: '+'; '.join(' '.join(e) for e in sorted(worse)[:3]))
    except BaseException as ex:
        for q,(b,t) in saved_f.items():q.write_bytes(b);os.utime(q,ns=(t,t))
        for f,v_ in props.items():
            if v_ is None:f.unlink(missing_ok=True)
            else:f.write_bytes(v_[0]);os.utime(f,ns=(v_[1],v_[1]))
        raise ValueError('redit-revert stopped ('+type(ex).__name__+': '+str(ex)+'); the box is as before') from ex
    out['reverted']=True;out['record']=str(rq.relative_to(layer))
    return out

# ---- extraction drafts ----
SECTION_REGISTER=(('TODO','todo'),('WBS','wbs'),('論点','issues'),('仮説','hypotheses'))
DECISION_COLUMNS=('採否','本人の確定')
ROW_ID=re.compile(r'(?<![A-Za-z0-9])(MS\d+|[IHDW]\d+(?:\.\d+)*)(?![0-9])')
def _mark(cell):
    """(mark, note): the decision and the words added to it (e.g. 採用（材料の追記だけ、判定は変えない）). A note is never dropped."""
    c=cell.replace('*','').strip()
    for head,mark in (('採用しない','rejected'),('不採用','rejected'),('採用','adopted'),('足さない','not_proposed'),('案を出さない','not_proposed'),('保留','held')):
        if c.startswith(head):return mark,c[len(head):].strip(' 　（）()、。:：')
    return ('unmarked' if not c else 'unreadable'),''
def _kind(cell,register):
    c=cell.strip()
    if c.startswith(('重複','判定に使えない')):return 'skip'
    if '判定' in c:return 'needs_judgement'
    if c.startswith('新規'):return 'add_row'
    if '材料の追記' in c:return 'append'
    if c.startswith('既存の更新'):return 'update'
    return 'unreadable'
def read_extraction(text):
    """Rows of the tables of an extraction draft: sections TODO / WBS / 論点 / 仮説, header row starting with 案 and holding 区分,
    the decision in the last column (採否 or 本人の確定). Nothing is guessed: what cannot be read is returned as unreadable."""
    rows=[];register=None;header=None;lines=text.splitlines()
    for n,l in enumerate(lines,1):
        if l.startswith('## '):
            register=next((r for k,r in SECTION_REGISTER if k in l),None);header=None;continue
        if not l.startswith('|'):
            header=None;continue   # a table ends at the first non-table line
        cells=[c.strip() for c in l.strip().strip('|').split('|')]
        if set(''.join(cells))<=set('-: '):continue   # the separator row
        if cells and cells[0]=='案' and '区分' in cells:
            header=cells if cells[-1] in DECISION_COLUMNS else None
            if header is None:rows.append({'line':n,'register':register,'class':'unreadable','reason':'no decision column (採否 / 本人の確定)'})
            continue
        if header is None:continue
        if register is None:
            rows.append({'line':n,'register':None,'class':'unreadable','reason':'a table outside the sections TODO / WBS / 論点 / 仮説','case':cells[0] if cells else None});continue
        if len(cells)!=len(header):rows.append({'line':n,'register':register,'class':'unreadable','reason':'cell count differs from the header','case':cells[0] if cells else None});continue
        row=dict(zip(header,cells));kind=_kind(row['区分'],register);mark,note=_mark(row[header[-1]])
        ids=ROW_ID.findall(row['区分'])
        lead=ROW_ID.match(cells[2].replace('*','').strip()) if len(cells)>2 else None   # only the id at the head of the 3rd column (bold allowed; never one inside a sentence)
        target=(ids[0] if ids else (lead.group(1) if lead else None)) if kind in ('append','update','needs_judgement') else None
        reg=register
        if register=='wbs' and target and target.startswith('MS'):reg='roadmap'   # the WBS section also holds roadmap rows
        reason=None
        if target and not target.startswith(PREFIX[reg]):cls,reason='unreadable','row id '+target+' does not belong to '+reg
        elif kind=='unreadable' or mark=='unreadable':cls='unreadable'
        elif kind=='skip':cls='conflict' if mark=='adopted' else 'skip'   # a duplicate the person still adopted: ask, never drop silently
        elif mark!='adopted':cls=mark
        elif note:   # an adopted row with words added: the AI reads them; a judgement row whose note keeps the judgement becomes material
            cls='adopt_append' if kind=='needs_judgement' and '材料の追記' in note and '判定は変え' in note else 'adopted_with_note'
        else:cls={'append':'adopt_append','add_row':'adopt_add_row','needs_judgement':'needs_judgement','update':'adopt_update'}[kind]
        if cls in ('adopt_append','adopt_update','needs_judgement') and not target:cls,reason='unreadable','no row id to update'
        elif cls=='adopted_with_note' and kind in ('append','update','needs_judgement') and not target:reason='no row id to update (the AI must find it, never guess)'
        register_row=reg
        rows.append({'line':n,'register':register_row,'case':cells[0],'kind':kind,'mark':mark,'note':note,'class':cls,'target':target,'cells':row,**({'reason':reason} if reason else {})})
    return rows
def _judge_draft(r):
    ai=next((r['cells'][k] for k in ('AI の案','内容','論点','仮説') if r['cells'].get(k)),'')   # the AI's proposal, shown to the person; never written as the judgement
    if r['register']=='hypotheses':
        return {'for':'package.py judge --input <this input>（本人の受領がそろってから。道具は実行しない）','source':r['case'],'ai_proposal':ai,
                'input':{'date':None,'event':None,'judged_by':None,'evidence_ref':None,'judgements':[{'id':r['target'],'verdict':None}]}}
    if r['register']=='issues':
        return {'for':'package.py op --name issue.resolve --input <this input>（本人の決定の記録がそろってから。道具は実行しない）','source':r['case'],'ai_proposal':ai,
                'input':{'id':r['target'],'answer':None,'evidence_refs':[],'decided_by':None}}
    return {'for':'本人が決める（todo は todo.move、wbs の受け入れは本人）','source':r['case'],'ai_proposal':ai,'input':{'register':r['register'],'id':r['target']}}
def extract(layer,input_path,*,apply=False):
    """redit-extract: read an extraction draft (read only) and sort its rows: adopt_append / adopt_add_row / adopt_update (the AI
    writes the redit input for these), needs_judgement (judge / resolve drafts only), rejected, not_proposed, held, unmarked, skip,
    unreadable. With apply: save the sorting as Context/aipm_changes/rextract_<name>.yaml and one judge_draft_<case>.yaml per
    adopted judgement (never over an existing file). adopted_with_note: an adopted row with words added to the mark (the AI reads
    them); conflict: a duplicate row the person still adopted (ask). The decision record of the draft is the origin, not the
    approval (design §6)."""
    layer=Path(layer).absolute();q=safe_path(layer,changes._text(input_path,'--input'))
    if not q.is_file():raise ValueError('extraction draft not found: '+input_path+' (nothing written)')
    rows=read_extraction(q.read_text())
    if not any(r['class']!='unreadable' for r in rows):raise ValueError('no table of an extraction draft could be read (sections TODO / WBS / 論点 / 仮説, header 案・区分・…・採否; nothing written)')
    groups={}
    for r in rows:groups.setdefault(r['class'],[]).append(r)
    out={'route':'aipm','apply':bool(apply),'input':input_path,'counts':{k:len(v) for k,v in groups.items()},'groups':groups,
         'next':'adopt_append・adopt_add_row・adopt_update の行から redit の入力（rinput_*.yaml）を書き、redit で照らす。needs_judgement は judge_draft の下書きを本人の判定に回す'}
    if not apply:return out
    d=safe_path(layer,CHANGES);d.mkdir(parents=True,exist_ok=True);stem=Path(input_path).stem;written=[]
    files=[(safe_path(layer,CHANGES+'/rextract_'+stem+'.yaml'),{'input':input_path,'input_sha256':sha(q),'at':_now(),'counts':out['counts'],'rows':rows})]
    for r in groups.get('needs_judgement',[]):files.append((safe_path(layer,CHANGES+'/judge_draft_'+slug('case_'+re.sub(r'[^A-Za-z0-9_-]','_',r['case']),'case')+'.yaml'),_judge_draft(r)))
    for f,_ in files:
        if f.exists():raise ValueError(str(f.relative_to(layer))+' already exists (nothing written)')
    try:
        for f,data in files:
            with open(f,'x') as h:written.append(f);h.write(_dump(data))
    except BaseException as ex:
        for f in written:f.unlink(missing_ok=True)
        raise ValueError('redit-extract stopped ('+type(ex).__name__+': '+str(ex)+'); nothing written') from ex
    out['written']=[str(f.relative_to(layer)) for f in written]
    return out
