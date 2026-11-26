"""pm- operations on single items inside the AIPM boxes.

The AI-PLC Stages are the outer commands (they build the boxes); pm-issue / pm-hypothesis / pm-todo act on one item
inside the registers (registers/ of box_root_v1 / nested_v1, directly in Sheets/ for sheets_v1). Every write is tried in place: the target file's bytes and times are kept, the registers check of
validate (E_REGISTERS) is taken before and after as a set of (code, path, message), and the file is put back when a new
item appears or apply is not given (so the trial sees the same repo root and sources as the real Layer). Human decisions (resolved, owner/decider judgements, acceptance) are never made here:
resolve/close need a receipt or decision record given by the caller, and owner/decider judgements stay with judge.
"""
import os, re
from datetime import date, datetime
from pathlib import Path
import yaml
from package import build_contract, load, registers_contract, safe_path, select
from package import addon_selector as _addon_selector, LEGACY_COURSE, FLAT_LAYOUTS
import light   # imported at load time (another tool may load ops with this folder on sys.path only while loading)

READS={'init.status','issue.map','hypothesis.impact','todo.overdue','capture.context','capture.check','persona.revise','story.revise','today.pick'}   # capture/persona/story/today never write
STOP_IN_SAVED={'issue.add','issue.split','issue.propose','hypothesis.add','hypothesis.propose','todo.add','todo.link'}   # (resolve, close, todo.move stay)
WRITES={'issue.add','issue.split','issue.propose','issue.close','issue.resolve','hypothesis.add','hypothesis.propose','todo.add','todo.move','todo.link'}
UNKNOWN='[unknown]'

def check(layer):
    """Whether pm- may act on this Layer. selected / unselected (no write, reason) / held (selection held or broken)."""
    layer=Path(layer).absolute()
    try:chosen=select(layer);kind=_light_kind(layer)
    except ValueError as ex:return {'route':'held','pass':False,'reason':str(ex)}
    if kind is not None and (not chosen or 'registers_contract_version' not in build_contract(layer)):
        return _light_check(layer,kind)   # AIPM ライトモード, or the two sheets added to an aipm Layer
    if not chosen:return {'route':'unselected','reason':'AIPM is not selected in this Layer (pm- acts only on Layers that selected AIPM; to switch midway see pm-init)'}
    c=build_contract(layer)
    if 'registers_contract_version' not in c:return {'route':'unselected','reason':'aipm.registers is not selected'}
    root=safe_path(layer,c['package_root']);rc=registers_contract(c)
    missing=[s['path'] for s in rc['files'].values() if not safe_path(root,s['path']).is_file()]
    if missing:return {'route':'held','pass':False,'reason':'registers files missing (run package.py init first): '+', '.join(missing)}
    return {'route':'selected','scope_id':c.get('scope_id')}

LIGHT_OPS={'check','todo.add','todo.move','todo.link','todo.overdue'}   # the light sheets hold todo and wbs only

def _light_kind(layer):
    """kind of the light sheets in the Layer (light.LIGHT_KIND / light.SHEETS_KIND) or None. A held selection raises."""
    try:kind=light.record(layer)[0]
    except (OSError,yaml.YAMLError) as ex:raise ValueError('light box record unreadable: '+str(ex)) from ex   # held, not a traceback
    m=light.method(layer)[0]
    if kind is None:return light.LIGHT_KIND+'_missing' if m==light.LIGHT else None
    if kind==light.LIGHT_KIND and m!=light.LIGHT:return None   # a leftover record does not make a Layer light
    if kind==light.SHEETS_KIND and m!='aipm':return None
    return kind

def _light_check(layer,kind):
    if kind.endswith('_missing'):return {'route':'held','pass':False,'reason':'AIPM ライトモード is selected but its box is missing (run package.py init --light)'}
    try:_,rc,files=light.contract(layer)
    except ValueError as ex:return {'route':'held','pass':False,'reason':str(ex)}
    missing=[str(q.relative_to(layer)) for q in files.values() if not q.is_file()]
    if missing:return {'route':'held','pass':False,'reason':'light sheets missing: '+', '.join(missing)}
    return {'route':'selected','scope_id':load(safe_path(layer,'intent.yaml')).get('scope_id'),'light':kind}

def _text(v):
    if isinstance(v,(date,datetime)):return v.isoformat()
    return v

def _input(layer,path,allowed,required=()):
    if path is None:
        if required:raise ValueError('--input is required')
        return {}
    d=load(safe_path(layer,path))
    if d is None:d={}
    if not isinstance(d,dict):raise ValueError('input must be a map')
    extra=[k for k in d if k not in allowed]
    if extra:raise ValueError('unknown input key: '+', '.join(map(str,extra)))
    for k in required:
        if d.get(k) in (None,'',[]):raise ValueError('input '+k+' is required')
    return {k:_text(v) for k,v in d.items()}

def _next_id(rows,prefix):
    n=[int(m.group(1)) for r in rows if isinstance(r,dict) for m in [re.fullmatch(prefix+r'(\d+)',str(r.get('id','')))] if m]
    return prefix+str(max(n,default=0)+1)

def _row(rows,rid,kind):
    hit=[r for r in rows if isinstance(r,dict) and r.get('id')==rid]
    if len(hit)!=1:raise ValueError(kind+' not found: '+str(rid))
    return hit[0]

def _registers_problems(layer):
    from validate_package import validate
    if _light_kind(layer)==light.LIGHT_KIND and not select(layer):r=light.validate(layer)
    else:
        c=build_contract(layer);r=validate(safe_path(layer,c['package_root']),phase='prearchive',layer=layer)
        if _light_kind(layer)==light.SHEETS_KIND and 'registers_contract_version' not in c:
            return {(e['code'],e['path'],e['message']) for e in r['errors'] if e['code'] in ('E_REGISTERS','E_LIGHT')}
    return {(e['code'],e['path'],e['message']) for e in r['errors'] if e['code'] in ('E_REGISTERS','E_LIGHT')}

def _files(layer):
    kind=_light_kind(layer)
    if kind in (light.LIGHT_KIND,light.SHEETS_KIND) and (not select(layer) or 'registers_contract_version' not in build_contract(layer)):
        return light.contract(layer)
    c=build_contract(layer);root=safe_path(layer,c['package_root']);rc=registers_contract(c)
    return c,rc,{k:safe_path(root,s['path']) for k,s in rc['files'].items()}

def _dump(path,data):path.write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False))

# ---- issue -------------------------------------------------------------------------------------------------------------
ISSUE_NEW=('question','priority','owner','due','parent','sources')

def _new_issue(rows,inp,parent=None):
    q=inp.get('question')
    if not isinstance(q,str) or not q.strip():raise ValueError('question is required (one question per row)')
    row={'id':_next_id(rows,'I'),'question':q.strip(),'status':'open','priority':inp.get('priority') or UNKNOWN,
         'owner':inp.get('owner') or UNKNOWN,'due':inp.get('due') or 'undecided'}
    p=parent or inp.get('parent')
    if p:row['parent']=p
    if inp.get('sources'):row['sources']=inp['sources']
    rows.append(row);return row

def _confirmed(layer,c,ref,issue_id,decided_by=None):
    """A receipt or decision record that a person confirmed, and that is about this issue: a decision record names it
    in issue_id; a receipt mentions it in its question or answer. Records about another issue are not reused."""
    from validate_package import decision_problem
    problem=decision_problem(ref,layer,c,decided_by)
    if problem:raise ValueError('a person must confirm this: give a receipt or decision record path ('+str(problem)+')')
    r=load(safe_path(layer,ref))
    if r.get('kind')=='decision_record':
        ids=r.get('issue_id');ids=ids if isinstance(ids,list) else [ids]
        if issue_id not in ids:raise ValueError('the decision record is not about '+issue_id+' (write issue_id: '+issue_id+' in the record made from what the person said)')
    elif not any(re.search(r'(?<![A-Za-z0-9])'+re.escape(issue_id)+r'(?![0-9])',str(r.get(k) or '')) for k in ('question','answer')):
        raise ValueError('the receipt does not mention '+issue_id+' in its question or answer')

OPEN_STATES=('open','on_hold')   # close and resolve act only on an issue that is still undecided

def issue_write(verb,layer,data,inp,c,rc,hyps):
    rows=data['issues'];changes=[]
    if verb=='add':changes.append(_new_issue(rows,inp)['id'])
    elif verb=='split':
        _row(rows,inp['parent'],'issue')
        kids=inp.get('children')
        if not isinstance(kids,list) or not kids:raise ValueError('children list is required')
        for k in kids:
            if not isinstance(k,dict) or set(k)-set(ISSUE_NEW):raise ValueError('each child takes '+', '.join(ISSUE_NEW))
            changes.append(_new_issue(rows,{kk:_text(v) for kk,v in k.items()},inp['parent'])['id'])
    elif verb=='propose':
        r=_row(rows,inp['id'],'issue')
        if r.get('status')!='open':raise ValueError('propose only on an open issue (status stays open)')
        for k in ('answer','validation_plan'):
            if k in inp:r[k]=inp[k]
        if not ({'answer','validation_plan'}&set(inp)):raise ValueError('answer or validation_plan is required')
        changes.append(r['id'])
    elif verb=='close':
        r=_row(rows,inp['id'],'issue');res=rc['files']['issues']['resolution']
        if inp['status'] not in res['reason_required']:raise ValueError('close takes '+'/'.join(res['reason_required'])+' (resolved is resolve)')
        if r.get('status') not in OPEN_STATES:raise ValueError(r['id']+' is '+str(r.get('status'))+'; close acts only on '+'/'.join(OPEN_STATES))
        _confirmed(layer,c,inp['confirmed_ref'],r['id'])
        r['status']=inp['status'];r['reason']=inp['reason']
        if inp.get('review_at'):r['review_at']=inp['review_at']
        changes.append(r['id'])
    elif verb=='resolve':
        r=_row(rows,inp['id'],'issue');res=rc['files']['issues']['resolution']
        if r.get('status') not in OPEN_STATES:raise ValueError(r['id']+' is '+str(r.get('status'))+'; resolve acts only on '+'/'.join(OPEN_STATES))
        if inp['decided_by'] not in res['decided_by']:raise ValueError('decided_by must be owner or decider')
        refs=inp['evidence_refs'];refs=refs if isinstance(refs,list) else [refs]
        from validate_package import human_judged
        root=safe_path(layer,c['package_root']);judged=human_judged(rc['files']['hypotheses'],lambda rel:safe_path(root,rel),layer,c)
        for ref in refs:
            if isinstance(ref,str) and re.fullmatch(r'H\d+',ref):
                if ref not in judged:raise ValueError('evidence '+ref+' has no owner/decider judgement backed by a receipt (use package.py judge first)')
            else:_confirmed(layer,c,ref,r['id'],inp['decided_by'])
        r.update({'status':'resolved','answer':inp['answer'],'evidence_refs':refs,'decided_by':inp['decided_by']})
        changes.append(r['id'])
    return changes

ISSUE_INPUT={'add':(ISSUE_NEW,('question',)),'split':(('parent','children'),('parent','children')),
             'propose':(('id','answer','validation_plan'),('id',)),'close':(('id','status','reason','review_at','confirmed_ref'),('id','status','reason','confirmed_ref')),
             'resolve':(('id','answer','evidence_refs','decided_by'),('id','answer','evidence_refs','decided_by'))}

def issue_map(data,rc):
    rows=[r for r in data.get('issues') or [] if isinstance(r,dict)]
    res=rc['files']['issues']['resolution'];counted=[r for r in rows if r.get('status') not in res['not_counted']]
    kids={}
    for r in rows:kids.setdefault(r.get('parent'),[]).append(r.get('id'))
    out=[{k:r.get(k) for k in ('id','question','status','priority','owner','due','parent','answer') if r.get(k) is not None}|{'children':kids.get(r.get('id'),[])} for r in rows]
    return {'issues':out,'roots':kids.get(None,[]),'resolved_ratio':(round(sum(r.get('status')=='resolved' for r in counted)/len(counted),3) if counted else None),
            'open':[r.get('id') for r in rows if r.get('status')=='open']}

# ---- hypothesis --------------------------------------------------------------------------------------------------------
HYP_NEW=('kind','claim','issue_id','priority','method','success','falsification','sources')

def hypothesis_write(verb,layer,data,inp,c,rc,hyps):
    rows=data['hypotheses'];spec=rc['files']['hypotheses']
    if verb=='add':
        if inp['kind'] not in spec['kind']:raise ValueError('kind must be one of '+'/'.join(spec['kind'])+' ('+'; '.join(k+'='+v for k,v in spec['kind_rule'].items())+')')
        row={'id':_next_id(rows,'H'),'kind':inp['kind'],'claim':str(inp['claim']).strip(),'status':'unknown'}
        for k in HYP_NEW[2:]:
            if inp.get(k) not in (None,''):row[k]=inp[k]
        rows.append(row);return [row['id']]
    if verb=='propose':
        items=inp['judgements']
        if not isinstance(items,list) or not items:raise ValueError('judgements list is required')
        changed=[]
        for it in items:
            if not isinstance(it,dict) or set(it)-{'hypothesis_id','verdict','note'}:raise ValueError('each judgement takes hypothesis_id, verdict and optional note (owner/decider judgements go to package.py judge)')
            if it.get('verdict') not in spec['judgement']['verdict']:raise ValueError('unknown verdict: '+str(it.get('verdict')))
            h=_row(rows,it['hypothesis_id'],'hypothesis')
            g={'date':inp['date'],'event':inp['event'],'verdict':it['verdict'],'judged_by':'ai_proxy'}
            if it.get('note'):g['note']=it['note']
            js=h.get('judgements') if isinstance(h.get('judgements'),list) else [];js.append(g);h['judgements']=js   # status is not changed by a proposal
            changed.append(h['id'])
        return changed
    raise ValueError('unknown verb')

HYP_INPUT={'add':(HYP_NEW,('kind','claim')),'propose':(('date','event','judgements'),('date','event','judgements'))}

def _latest(h,human_only=False):
    js=[g for g in h.get('judgements') or [] if isinstance(g,dict) and (not human_only or g.get('judged_by') in ('owner','decider'))]
    return js[-1] if js else {}

def hypothesis_impact(layer,files,data,inp):
    rows=[h for h in data.get('hypotheses') or [] if isinstance(h,dict)]
    want=inp.get('hypothesis_ids')
    targets=[h['id'] for h in rows if (h.get('id') in want if want else (h.get('status')=='not_supported' or _latest(h).get('verdict')=='not_supported'))]
    by={h['id']:h for h in rows if h.get('id') in targets}
    issues=load(files['issues']).get('issues') or [];todo=load(files['todo']).get('todo') or []
    root=safe_path(layer,build_contract(layer)['package_root']);docs={}   # the package (not the Layer): Sheets/ or Documents/aipm_project/
    lists={Path(q).absolute() for q in files.values()}   # the registers themselves are not documents (sheets_v1 has no registers/ folder)
    for p in sorted(root.rglob('*')):
        if p.is_file() and p.suffix in ('.md','.yaml','.yml','.mmd') and p.absolute() not in lists and 'registers' not in p.relative_to(root).parts:
            text=p.read_text(errors='ignore')
            for t in targets:
                if re.search(r'(?<![A-Za-z0-9])'+re.escape(t)+r'(?![0-9])',text):docs.setdefault(t,[]).append(str(p.relative_to(root)))
    def refs(r,keys):
        vals=[]
        for k in keys:
            v=r.get(k);vals+=v if isinstance(v,list) else [v]
        return vals
    return {'targets':targets,'impact':[{'hypothesis':t,'status':by[t].get('status'),'latest_judgement':{k:_latest(by[t]).get(k) for k in ('verdict','judged_by','date')},'human_confirmed':_latest(by[t]).get('judged_by') in ('owner','decider'),'issues':[r.get('id') for r in issues if isinstance(r,dict) and t in refs(r,('answer','validation_plan','evidence_refs'))],
            'todo':[r.get('id') for r in todo if isinstance(r,dict) and r.get('source')==t],'documents':docs.get(t,[])} for t in targets],
            'note':'見直す候補の一覧。直すかは人が決める（文書の改訂は pm-persona・pm-story）。human_confirmed が false の行は AI の判定の案だけに基づく'}

# ---- todo --------------------------------------------------------------------------------------------------------------
TODO_NEW=('title','owner','source','wbs_id','due','priority','note')
TODO_KNOT=('done_when','updated_on','blocked_by')   # contract v3 only (optional)

def _knot_check(spec,vals):
    if not vals:return
    if 'done_when' not in spec.get('optional',[]):raise ValueError('この箱の一覧は結び目の列（'+', '.join(TODO_KNOT)+'）に対応しない古い版です。列を除いて頼んでください（何も書いていません）')
    from validate_package import knot_problems
    bad=knot_problems(spec,vals)[0]
    if bad:raise ValueError('; '.join(bad)+'（何も書いていません）')

CONFIRMATIONS='Context/todo_confirmations.yaml'   # the owner's answers behind confirmed_on (contract v4). A reader should trust confirmed_on only with a record here

def _confirm_check(layer,spec,row_id,inp):
    """confirmed_on needs the owner's answer for this Layer, this row and this day. An AI never fills it in by itself."""
    if 'confirmed_on' not in spec.get('optional',[]):raise ValueError('この箱の一覧は確認日の列（confirmed_on）に対応しない古い版です（何も書いていません）')
    _knot_check(spec,{'confirmed_on':inp['confirmed_on']})
    rec=inp.get('receipt')
    if not isinstance(rec,dict) or rec.get('kind')!='user_reported' or rec.get('actor')!='actual_user':raise ValueError('receipt must be kind user_reported / actor actual_user（何も書いていません）')
    if rec.get('decision')!='confirm_todo_row' or not str(rec.get('quote') or '').strip() or not rec.get('received_at'):raise ValueError('receipt needs decision confirm_todo_row, quote and received_at（何も書いていません）')
    if rec.get('scope_ids')!=[(load(safe_path(layer,'intent.yaml')) or {}).get('scope_id')]:raise ValueError('receipt scope_ids must be exactly this Layer（何も書いていません）')
    if rec.get('rows')!=[row_id]:raise ValueError('receipt rows must be exactly this row（何も書いていません）')
    if str(rec['received_at'])[:10]!=str(inp['confirmed_on']):raise ValueError('confirmed_on must be the day of received_at（何も書いていません）')
    if str(inp['confirmed_on'])>date.today().isoformat():raise ValueError('confirmed_on must not be in the future（何も書いていません）')
    q=safe_path(layer,CONFIRMATIONS)
    old=load(q) if q.is_file() else {'confirmations':[]}
    if not isinstance(old,dict) or not isinstance(old.get('confirmations'),list):raise ValueError(CONFIRMATIONS+' の形が違うので書きません（何も書いていません）')

def _record_confirmation(layer,row_id,inp):
    q=safe_path(layer,CONFIRMATIONS)
    data=load(q) if q.is_file() else {'confirmations':[]}
    rec=inp['receipt']
    data['confirmations'].append({'row':row_id,'confirmed_on':str(inp['confirmed_on']),'kind':rec['kind'],'actor':rec['actor'],'decision':rec['decision'],'quote':rec['quote'],'received_at':str(rec['received_at'])})
    q.parent.mkdir(parents=True,exist_ok=True);_dump(q,data)

NOTE_ADD_LIMIT=300

def _note_add(v):
    """todo.move note_add: one line appended to the row's note. Empty means nothing."""
    if v in (None,''):return ''
    if not isinstance(v,str):raise ValueError('note_add must be one line of text（何も書いていません）')
    v=v.strip()
    if not v or '\n' in v or '\r' in v:raise ValueError('note_add must be one line of text（何も書いていません）')
    if len(v)>NOTE_ADD_LIMIT:raise ValueError('note_add must be at most '+str(NOTE_ADD_LIMIT)+' characters（何も書いていません）')
    return v

def todo_write(verb,layer,data,inp,c,rc,hyps):
    rows=data['todo'];spec=rc['files']['todo']
    if verb=='add':
        row={'id':_next_id(rows,'D'),'title':str(inp['title']).strip(),'status':'todo','owner':inp.get('owner') or UNKNOWN}
        for k in TODO_NEW[2:]:
            if inp.get(k) not in (None,''):row[k]=inp[k]
        knot={k:inp[k] for k in TODO_KNOT if inp.get(k) not in (None,'')};_knot_check(spec,knot);row.update(knot)
        rows.append(row);return [row['id']]
    r=_row(rows,inp['id'],'todo')
    if verb=='move':
        if inp['status'] not in spec['status']:raise ValueError('status must be one of '+'/'.join(spec['status']))
        add=_note_add(inp.get('note_add'))
        if inp.get('updated_on') not in (None,''):   # the day the row was closed, written with the status
            _knot_check(spec,{'updated_on':inp['updated_on']})
            if str(inp['updated_on'])>date.today().isoformat():raise ValueError('updated_on must not be in the future（何も書いていません）')
            r['updated_on']=inp['updated_on']
        if add and add not in str(r.get('note') or ''):   # one sentence of where the decision came from; the old note is kept, a repeat is not added twice
            r['note']=(str(r['note']).rstrip()+' '+add) if str(r.get('note') or '').strip() else add
        r['status']=inp['status']
    elif verb=='link':
        knot={k:inp[k] for k in TODO_KNOT if inp.get(k) not in (None,'')}
        confirmed=inp.get('confirmed_on') not in (None,'')
        if not knot and not confirmed and not ({'wbs_id','source'}&set(inp)):raise ValueError('wbs_id, source or a knot column is required')
        _knot_check(spec,knot)
        if confirmed:_confirm_check(layer,spec,r['id'],inp)
        elif 'receipt' in inp:raise ValueError('receipt is only for confirmed_on（何も書いていません）')
        for k in ('wbs_id','source'):
            if k in inp:r[k]=inp[k]
        r.update(knot)
        if confirmed:r['confirmed_on']=inp['confirmed_on']
    return [r['id']]

TODO_INPUT={'add':(TODO_NEW+TODO_KNOT,('title',)),'move':(('id','status','updated_on','note_add'),('id','status')),'link':(('id','wbs_id','source','confirmed_on','receipt')+TODO_KNOT,('id',))}

def todo_overdue(data,inp):
    today=str(inp.get('today') or date.today().isoformat())
    rows=[r for r in data.get('todo') or [] if isinstance(r,dict) and r.get('status') not in ('done','cancelled')]
    late=[{'id':r['id'],'title':r.get('title'),'due':str(r['due']),'status':r.get('status')} for r in rows if r.get('due') and re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(r['due'])) and str(r['due'])<today]
    return {'today':today,'overdue':late,'no_wbs':[r['id'] for r in rows if not r.get('wbs_id')],'note':'WBS の番号なしは「番号なし」として扱う。番号の推測は候補として別に出す'}

# ---- capture / today / persona / story ---------------------------------------------------------------------
NOTES_LIMIT=20000

def capture_context(layer,files,inp):
    notes=None
    if inp.get('notes'):
        q=safe_path(layer,inp['notes'])
        if not q.is_file():raise ValueError('notes file missing: '+inp['notes'])
        text=q.read_text(errors='ignore');notes={'path':inp['notes'],'text':text[:NOTES_LIMIT],'truncated':len(text)>NOTES_LIMIT}
    iss=[r for r in load(files['issues']).get('issues') or [] if isinstance(r,dict)]
    hyp=[h for h in load(files['hypotheses']).get('hypotheses') or [] if isinstance(h,dict)]
    todo=[r for r in load(files['todo']).get('todo') or [] if isinstance(r,dict)]
    return {'notes':notes,
            'open_issues':[{k:r.get(k) for k in ('id','question','status','due')} for r in iss if r.get('status') in OPEN_STATES],
            'undecided_hypotheses':[{k:h.get(k) for k in ('id','kind','claim','status')} for h in hyp if h.get('status') in ('unknown','structurally_supported')],
            'open_todo':[{k:r.get(k) for k in ('id','title','status','due','source')} for r in todo if r.get('status') not in ('done','cancelled')],
            'shapes':{'judgements':{'date':'YYYY-MM-DD','event':'会議名','judgements':[{'hypothesis_id':'H<n>','verdict':'/'.join(['supported','not_supported','undetermined']),'note':'任意'}]},
                      'issues':[{k:'...' for k in ISSUE_NEW}],'todo':[{k:'...' for k in TODO_NEW}]},
            'note':'候補はメモに書かれたことだけから作る。capture.check で試し、本人が確定したものを pm-hypothesis（propose）・pm-issue（add）・pm-todo（add）の --apply で書く'}

def capture_check(layer,inp,c,rc,files):
    tries=[]
    if inp.get('judgements'):tries.append(('hypothesis.propose',inp['judgements']))
    for x in inp.get('issues') or []:tries.append(('issue.add',x))
    for x in inp.get('todo') or []:tries.append(('todo.add',x))
    if not tries:raise ValueError('give judgements, issues or todo candidates')
    out=[]
    for name,cand in tries:
        item,verb=name.split('.');allowed,required=KIND[item][2][verb]
        try:
            if not isinstance(cand,dict) or set(cand)-set(allowed):raise ValueError('candidate takes '+', '.join(allowed))
            for k in required:
                if cand.get(k) in (None,'',[]):raise ValueError('candidate '+k+' is required')
            r=_write(layer,name,{k:_text(v) for k,v in cand.items()},False,c,rc,files)
            out.append({'op':name,'ok':not r['new_problems'],'provisional_ids':r['changed_ids'],'new_problems':r['new_problems']})
        except ValueError as ex:out.append({'op':name,'ok':False,'error':str(ex)})
    return {'candidates':out,'note':'1件ずつ試しただけ（Layer は元のまま）。付く id は仮で、--apply した順に決まる'}

def _day(v):
    try:return date.fromisoformat(str(v)[:10])
    except ValueError:return None

def today_pick(files,inp):
    if inp.get('today') is not None and _day(inp['today']) is None:raise ValueError('today must be YYYY-MM-DD')
    today=_day(inp.get('today')) or date.today()
    rows=lambda f,k:[r for r in load(files[f]).get(k) or [] if isinstance(r,dict) and r.get('id')] if f in files else []   # rows without an id are left to validate; AIPM ライトモード has no issues/hypotheses
    iss=rows('issues','issues');hyp=rows('hypotheses','hypotheses');todo=rows('todo','todo');wbs=rows('wbs','wbs')
    live=[r for r in todo if r.get('status') not in ('done','cancelled')]
    buckets=[
        ('期限を過ぎた ToDo',[{'id':r['id'],'title':r.get('title'),'due':str(r.get('due'))} for r in live if _day(r.get('due')) and _day(r.get('due'))<today]),
        ('7日以内が期限の論点',[{'id':r['id'],'question':r.get('question'),'due':str(r.get('due'))} for r in iss if r.get('status') in OPEN_STATES and _day(r.get('due')) and (_day(r.get('due'))-today).days<=7]),
        ('受入の候補（受け入れるのは人）',[{'id':r['id'],'deliverable':r.get('deliverable')} for r in wbs if r.get('status')=='pending_acceptance']),
        ('優先度の高い未確定の仮説',[{'id':h['id'],'claim':h.get('claim'),'priority':h.get('priority')} for h in hyp if h.get('status')=='unknown' and h.get('priority') in ('critical','high')]),
        ('進行中の ToDo',[{'id':r['id'],'title':r.get('title')} for r in live if r.get('status')=='doing'])]
    first=next(((name,rows[0]) for name,rows in buckets if rows),None)
    return {'today':today.isoformat(),'pick':first[1] if first else None,'reason':first[0] if first else '候補なし（論点・仮説・ToDo・受入の候補に急ぐものが無い）',
            'candidates':[{'reason':name,'items':rows} for name,rows in buckets if rows],'note':'選ぶのは本人。1件を進めるのは Stage（/04-operation）か各 pm-'}

REVISE={'persona':(('persona','problem'),('validation','solution','story')),'story':(('solution','story'),())}

def check_docs(layer):
    """persona/story need AIPM and a 19-document manifest (registers are not required)."""
    layer=Path(layer).absolute()
    try:chosen=select(layer)
    except ValueError as ex:return {'route':'held','pass':False,'reason':str(ex)}
    if not chosen:return {'route':'unselected','reason':'AIPM is not selected in this Layer (to switch midway see pm-init)'}
    c=build_contract(layer)
    if not safe_path(safe_path(layer,c['package_root']),'manifest.yaml').is_file():return {'route':'held','pass':False,'reason':'no manifest of the 19 documents yet; make them through the Stages first'}
    return {'route':'selected','scope_id':c.get('scope_id')}

def revise(layer,kind,inp):
    c=build_contract(layer);root=safe_path(layer,c['package_root']);m=load(root/'manifest.yaml')
    own,down=REVISE[kind];recs=[r for r in m.get('records') or [] if isinstance(r,dict)]
    def doc(r):return {'path':r.get('path'),'stage':r.get('stage'),'status':r.get('status'),'saved':r.get('status')=='archived_local_final' or bool(r.get('archive_path'))}
    targets=[doc(r) for r in recs if r.get('stage') in own]
    saved=[t['path'] for t in targets if t['saved']]
    versioned=isinstance(m.get('applies'),list) and bool(m['applies'])   # a box with versions is revised by apply
    if saved and not versioned:return {'route':'held','pass':False,'reason':'保存済み（archived）の文書はその場で改訂しない。改訂は Stage で工程をやり直す（版の登録〔package.py register〕をした箱は、変更案〔package.py change〕から apply で改訂できる）','saved':saved}
    ids=inp.get('hypothesis_ids') or []
    mentions=[]
    for r in recs:
        try:q=safe_path(root,str(r.get('path')))
        except ValueError:continue
        if ids and q.is_file() and any(re.search(r'(?<![A-Za-z0-9])'+re.escape(h)+r'(?![0-9])',q.read_text(errors='ignore')) for h in ids):mentions.append(r.get('path'))
    # the person's confirmations bound to these stages: human_responses (stage -> receipt; batch courses may bind them to gaps)
    # and stage events checked by the actual user. Stage events carry their stage name in 'name'.
    hr=m.get('human_responses') if isinstance(m.get('human_responses'),dict) else {}
    scope=set(own+down)|({'gaps'} if hr.get('gaps') else set())
    checks=[{'stage':k,'source':(v or {}).get('source'),'target_path':(v or {}).get('target_path')} for k,v in hr.items() if k in scope and isinstance(v,dict)]
    seen={c['stage'] for c in checks}
    checks+=[{'stage':s.get('name'),'checkpoint_actor':s.get('checkpoint_actor'),'checkpoint_status':s.get('checkpoint_status')} for s in m.get('stages') or [] if isinstance(s,dict) and s.get('name') in scope and s.get('name') not in seen and s.get('checkpoint_actor')=='actual_user']
    return {'kind':kind,'targets':targets,'downstream':[doc(r) for r in recs if r.get('stage') in down],'mentions':mentions,'human_checks_to_redo':checks,
            'reason_given':inp.get('reason'),
            'how_to_revise':('19文書はその場で書き換えない。この箱は版を持つので、改訂は変更案から: package.py clone → change（候補の YAML。dry-run で影響の一覧を見てから --apply）→ change-list で番号つきの一覧を本人に見せる → 本人の返事を judge-change で記録 → apply（反映は本人が採用した変更案だけ）。この一覧は改訂の範囲の案で、直すかは本人が決める' if saved else
                             '19文書はその場で書き換えない（manifest の hash・工程の時刻・本人の確認の対象が壊れる）。改訂は Re-Inception で改訂の Task を足し、/04-operation でその工程をやり直す。この一覧は改訂の範囲の案で、直すかは本人が決める')}

# ---- init: switching a midway Layer to AIPM -----------------------------------------------------------------
# Only a guide: it reads where the Layer stands and returns the next command. Choosing (recommendation + receipt), building the
# boxes (Collection Phase 7.5 init) and adding the 19-document Tasks (Re-Inception) stay with the Stages.

def _recommendation():
    import importlib.util
    q=Path(__file__).resolve().parent.parent/'ai-plc'/'01-collection'/'recommendation.py'
    spec=importlib.util.spec_from_file_location('collection_recommendation',q);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

def _shown(layer):
    for x in layer.parents:
        if x.name=='Flow':return str(layer.relative_to(x.parent))
    return str(layer)

def _under(path,root):
    """True when a Layer-relative output path lies inside root (normalised; never prefix-only)."""
    p=os.path.normpath(str(path));r=os.path.normpath(str(root))
    return p==r or p.startswith(r+os.sep)

def init_status(layer):
    layer=Path(layer).absolute();where=_shown(layer)
    recollect='/01-collection を実行してください / Layer: '+where+' / Re-Collection: 途中から AIPM にしたい（Phase 4.5 の方式の推薦と本人の選択 → Phase 7.5 の初期化）'
    fix='/01-collection を実行してください / Layer: '+where+' / Re-Collection: 方式の選択の食い違いを直したい'
    try:it=load(safe_path(layer,'intent.yaml'))
    except Exception as ex:return {'state':'held','reason':'intent.yaml unreadable: '+str(ex),'next':fix}
    if not isinstance(it,dict):return {'state':'held','reason':'intent must be a map','next':fix}
    try:sel=_addon_selector().selected_addons(layer,read_roots=[str(layer)])
    except Exception as ex:return {'state':'held','reason':'addon selection unreadable: '+str(ex),'next':fix}
    if sel['route']=='held':return {'state':'held','reason':', '.join(sel.get('hold_reasons') or [])+('; '+sel['detail'] if sel.get('detail') else ''),'next':fix}
    chosen=any(x.get('addon_id')=='aipm' for x in sel.get('selected') or [])
    # a case addon that is a work method, or that declares nothing, cannot sit with AIPM (catalog: undeclared_case_with_member: hold)
    blocking=[c for c in sel.get('case_addons') or [] if c.get('exclusive_group')!='none']
    if blocking and not chosen:
        return {'state':'other_addon','reason':'持ち込みのアドオン（'+', '.join(str(c.get('addon_id'))+'：'+str(c.get('exclusive_group') or '宣言なし') for c in blocking)+'）があり、AIPM と一緒には選べない（方式どうしは重ねない・宣言の無いものは方式と並べない）','next':'方式の組み合わせを確かめる：'+recollect}
    if not chosen and any(x.get('addon_id')=='aipm-light' for x in sel.get('selected') or []):
        return {'state':'light','next':'AIPM ライトモード（WBS と TODO のシートだけ）で動いている。AIPM に切り替えるなら '+recollect,'note':'方式は答えが無いと AIPM ライトモードが記録される（Collection Phase 7）。AIPM への切り替えでは2つのシートを registers の一部として引き継ぐ'}
    if not chosen:
        try:
            mod=_recommendation();rec=mod.status(layer)
            q=mod.Store(layer).state.get('question') if rec.get('status')=='pending' else None
        except Exception as ex:return {'state':'held','reason':'recommendation state unreadable: '+str(ex),'next':fix}
        if rec.get('route')=='stale':return {'state':'stale_recommendation','reason':'推薦の根拠が変わり、保存してある質問は古い','next':recollect+'（推薦を出し直す）'}
        if rec.get('route')=='legacy_selection_changed_externally':return {'state':'held','reason':'推薦の記録では AIPM を選んだが、intent では選ばれていない（外で変わった）','next':fix}
        if rec.get('status')=='pending' and isinstance(q,dict):
            return {'state':'question_pending','question':q.get('text'),'next':'保存してある推薦の質問に本人が答える（回答の受領記録で intent が変わる。Collection Phase 4.5 の手順）'}
        if rec.get('route')=='legacy_declined' or rec.get('status')=='declined':
            return {'state':'declined','next':'前に AIPM を選ばなかった。考えを変えるなら '+recollect}
        return {'state':'unselected','next':recollect,'note':'方式は本人の回答（受領記録）か、答えが無いときの既定（AIPM ライトモード）で intent に書かれる。pm-init は書かない'}
    c=build_contract(layer);root=safe_path(layer,c['package_root'])
    if not (root/'format_contract.yaml').is_file():
        return {'state':'selected_not_initialized','next':recollect+'（AIPM は選択済み。Phase 7.5 の初期化の段から）'}
    try:bl=load(safe_path(layer,'backlog.yaml'))
    except Exception as ex:return {'state':'held','reason':'backlog.yaml unreadable: '+str(ex),'next':'backlog を直してから pm-init を呼び直す'}
    if bl is None:bl={}
    if not isinstance(bl,dict) or not isinstance(bl.get('tasks',[]) or [],list):return {'state':'held','reason':'backlog must be a map with a tasks list','next':'backlog を直してから pm-init を呼び直す'}
    tasks=[t for t in bl.get('tasks') or [] if isinstance(t,dict)]
    outs=lambda t:[o for o in (t.get('output') if isinstance(t.get('output'),list) else [t.get('output')]) if isinstance(o,str) and o.strip()]
    pkg=c['package_root']
    aipm=[t.get('id') for t in tasks if (t.get('wbs_id') not in (None,'','none')) or any(_under(o,pkg) for o in outs(t))]
    if not aipm:
        cands=[]
        for t in tasks:
            if t.get('status')!='completed':continue
            for o in outs(t):
                if _under(o,pkg):continue
                try:
                    if safe_path(layer,o).is_file():cands.append(o)
                except ValueError:continue   # outputs outside the Layer are not import candidates
        course=c.get('course_id',LEGACY_COURSE)   # the legacy question-based course has no course_id in the contract
        return {'state':'initialized_no_tasks','course':course,'import_candidates':cands,
                'next':'/02-inception を実行してください / Layer: '+where+' / Re-Inception: AIPM の19文書（コース '+str(course)+'）を作る Task を足す'+('。今までの成果 '+', '.join(cands)+' を document_based の取り込みの候補にする' if cands else ''),
                'note':'取り込み（document_based）には persona・validation の本人の決定が要る（コースの決まり）。既存の Task・成果は変えない'}
    return {'state':'running','aipm_tasks':aipm,'next':'もう AIPM で動いている。箱の中の操作は pm-today・pm-issue など'}

# ---- entry -------------------------------------------------------------------------------------------------------------
KIND={'issue':('issues',issue_write,ISSUE_INPUT),'hypothesis':('hypotheses',hypothesis_write,HYP_INPUT),'todo':('todo',todo_write,TODO_INPUT)}

def run(layer,name,input_path=None,apply=False):
    layer=Path(layer).absolute()
    item=str(name).split('.')[0]
    if name=='init.status':return {'route':'pm','op':name,**init_status(layer)}   # works before AIPM is chosen; writes nothing
    st=check_docs(layer) if item in REVISE else check(layer)
    if name=='check' or st['route']!='selected':return st
    if st.get('light') and name not in LIGHT_OPS:return {'route':'held','pass':False,'op':name,'reason':'AIPM ライトモードのシートは todo と wbs だけ。使える操作: '+', '.join(sorted(LIGHT_OPS))}
    if name not in READS|WRITES:raise ValueError('unknown op: '+str(name)+' (reads: '+', '.join(sorted(READS))+'; writes: '+', '.join(sorted(WRITES))+')')
    verb=name.split('.')[1]
    if item in REVISE:
        r=revise(layer,item,_input(layer,input_path,('hypothesis_ids','reason')))
        return r if r.get('route')=='held' else {'route':'pm','op':name,**r}
    c,rc,files=_files(layer)
    if name=='issue.map':_input(layer,input_path,());return {'route':'pm','op':name,**issue_map(load(files['issues']),rc)}
    if name=='hypothesis.impact':return {'route':'pm','op':name,**hypothesis_impact(layer,files,load(files['hypotheses']),_input(layer,input_path,('hypothesis_ids',)))}
    if name=='todo.overdue':return {'route':'pm','op':name,**todo_overdue(load(files['todo']),_input(layer,input_path,('today',)))}
    if name=='today.pick':return {'route':'pm','op':name,**today_pick(files,_input(layer,input_path,('today',)))}
    if name=='capture.context':return {'route':'pm','op':name,**capture_context(layer,files,_input(layer,input_path,('notes',)))}
    if name=='capture.check':return {'route':'pm','op':name,**capture_check(layer,_input(layer,input_path,('judgements','issues','todo')),c,rc,files)}
    if name in STOP_IN_SAVED:   # a saved box that can carry versions is edited through redit
        import register_edits
        if register_edits.saved_versionable(layer):
            head='保存済み（archive 済み）の箱の registers は、記録なしでは書かない。'
            tail='（判定・状態の操作 issue.resolve・issue.close・todo.move・package.py judge は今までどおり使える）'
            how={'issue.propose':'答えの案・検証の仮説の案は一覧に書かない。案は redit の変更案の reason か、redit-extract の判定の下書き（judge_draft）の備考に残し、本人の判定は pm-issue の resolve・close で行う',
                 'hypothesis.propose':'AI の判定の案は一覧に書かない。案は redit の変更案の reason か、redit-extract の判定の下書き（judge_draft）の備考に残し、本人・判断者の判定は package.py judge で行う',
                 'todo.link':'wbs_id が空の ToDo は redit の fill（op: fill・field: wbs_id）で WBS につなぐ。付いている wbs_id の直しと source の付け直し、確認日 confirmed_on は、今は redit で足せない（要るかは本人に確かめる）',
                 'issue.split':'子の論点は redit の add_row（row_data に parent）で足す: package.py redit → redit-list → 本人の返事を redit-judge → redit-apply'
                 }.get(name,'変更案から書く: package.py redit → redit-list → 本人の返事を redit-judge → redit-apply')
            return {'route':'held','pass':False,'op':name,'reason':head+how+tail}
    allowed,required=KIND[item][2][verb]
    inp=_input(layer,input_path,allowed,required)
    if name=='todo.move' and ({'updated_on','note_add'}&{k for k,v in inp.items() if v not in (None,'')}):
        import register_edits
        if register_edits.saved_versionable(layer):return {'route':'held','pass':False,'op':name,'reason':'保存済み（archive 済み）の箱では todo.move は status だけを書く。updated_on・note_add を外して頼むか、redit の変更案から書く（何も書いていません）'}
    res=_write(layer,name,inp,apply,c,rc,files)
    if name in STOP_IN_SAVED and c.get('layout') not in FLAT_LAYOUTS and c.get('storage')!='registry_stock_v1':
        import register_edits
        if register_edits.state(layer)[4]:res['hint']='保存済みの nested_v1 の箱は記録なしで書いた。版と承認の出典を残すなら、先に migrate-sheets で sheets_v1 に移し、register の後に redit を使う'
    return res

def _write(layer,name,inp,apply,c,rc,files):
    item,verb=name.split('.');key,writer,table=KIND[item]
    target=files[key];raw=target.read_bytes();st=target.stat()
    before=_registers_problems(layer)
    data=load(target)
    changed=writer(verb,layer,data,inp,c,rc,None)   # every check runs before anything is written
    if target.read_bytes()!=raw:raise ValueError('the registers file changed while checking; run again')
    keep=False
    try:
        _dump(target,data);written=target.read_bytes()
        try:new=sorted(_registers_problems(layer)-before)
        except Exception:new=[('E_OPS',str(target.relative_to(layer)),'check failed after writing')]
        keep=apply and not new
    finally:
        if not keep:   # put the file back as it was, also when the check is interrupted
            if target.read_bytes()!=written:raise ValueError(str(target.relative_to(layer))+' was changed by someone else during the trial; it was left as it is now (not put back)')
            target.write_bytes(raw);os.utime(target,ns=(st.st_atime_ns,st.st_mtime_ns))
    if not keep:
        return {'route':'pm','op':name,'applied':False,'tried':True,'changed_ids':changed,
                'new_problems':[{'code':a,'path':b,'message':m} for a,b,m in new],
                'note':('新しい問題が出るので書いていない（Layer は元のまま）' if new else '試しただけ（Layer は元のまま）。書くなら同じ入力で --apply')}
    if name=='todo.link' and inp.get('confirmed_on') not in (None,''):_record_confirmation(layer,changed[0],inp)   # after the row: a failure here leaves a confirmed_on without a record (not to be trusted)
    return {'route':'pm','op':name,'applied':True,'changed_ids':changed,'file':str(target.relative_to(layer)),'new_problems':[]}
