"""pm- operations on single items inside the AIPM boxes.

The AI-PLC Stages are the outer commands (they build the boxes); pm-issue / pm-hypothesis / pm-todo act on one item
inside registers/. Every write is tried in place: the target file's bytes and times are kept, the registers check of
validate (E_REGISTERS) is taken before and after as a set of (code, path, message), and the file is put back when a new
item appears or apply is not given (so the trial sees the same repo root and sources as the real Layer). Human decisions (resolved, owner/decider judgements, acceptance) are never made here:
resolve/close need a receipt or decision record given by the caller, and owner/decider judgements stay with judge.
"""
import os, re
from datetime import date, datetime
from pathlib import Path
import yaml
from package import build_contract, load, registers_contract, safe_path, select
from package import addon_selector as _addon_selector, LEGACY_COURSE

READS={'init.status','issue.map','hypothesis.impact','todo.overdue','capture.context','capture.check','persona.revise','story.revise','today.pick'}   # capture/persona/story/today never write
WRITES={'issue.add','issue.split','issue.propose','issue.close','issue.resolve','hypothesis.add','hypothesis.propose','todo.add','todo.move','todo.link'}
UNKNOWN='[unknown]'

def check(layer):
    """Whether pm- may act on this Layer. selected / unselected (no write, reason) / held (selection held or broken)."""
    layer=Path(layer).absolute()
    try:chosen=select(layer)
    except ValueError as ex:return {'route':'held','pass':False,'reason':str(ex)}
    if not chosen:return {'route':'unselected','reason':'AIPM is not selected in this Layer (pm- acts only on Layers that selected AIPM; to switch midway see pm-init)'}
    c=build_contract(layer)
    if 'registers_contract_version' not in c:return {'route':'unselected','reason':'aipm.registers is not selected'}
    root=safe_path(layer,c['package_root']);rc=registers_contract(c)
    missing=[s['path'] for s in rc['files'].values() if not safe_path(root,s['path']).is_file()]
    if missing:return {'route':'held','pass':False,'reason':'registers files missing (run package.py init first): '+', '.join(missing)}
    return {'route':'selected','scope_id':c.get('scope_id')}

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
    c=build_contract(layer);r=validate(safe_path(layer,c['package_root']),phase='prearchive',layer=layer)
    return {(e['code'],e['path'],e['message']) for e in r['errors'] if e['code']=='E_REGISTERS'}

def _files(layer):
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
    root=files['issues'].parent.parent;docs={}
    for p in sorted(root.rglob('*')):
        if p.is_file() and p.suffix in ('.md','.yaml','.yml','.mmd') and 'registers' not in p.relative_to(root).parts:
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

def todo_write(verb,layer,data,inp,c,rc,hyps):
    rows=data['todo'];spec=rc['files']['todo']
    if verb=='add':
        row={'id':_next_id(rows,'D'),'title':str(inp['title']).strip(),'status':'todo','owner':inp.get('owner') or UNKNOWN}
        for k in TODO_NEW[2:]:
            if inp.get(k) not in (None,''):row[k]=inp[k]
        rows.append(row);return [row['id']]
    r=_row(rows,inp['id'],'todo')
    if verb=='move':
        if inp['status'] not in spec['status']:raise ValueError('status must be one of '+'/'.join(spec['status']))
        r['status']=inp['status']
    elif verb=='link':
        if not ({'wbs_id','source'}&set(inp)):raise ValueError('wbs_id or source is required')
        for k in ('wbs_id','source'):
            if k in inp:r[k]=inp[k]
    return [r['id']]

TODO_INPUT={'add':(TODO_NEW,('title',)),'move':(('id','status'),('id','status')),'link':(('id','wbs_id','source'),('id',))}

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
    rows=lambda f,k:[r for r in load(files[f]).get(k) or [] if isinstance(r,dict) and r.get('id')]   # rows without an id are left to validate
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
    if saved:return {'route':'held','pass':False,'reason':'保存済み（archived）の文書はその場で改訂しない。改訂は Stage で工程をやり直す','saved':saved}
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
            'how_to_revise':'19文書はその場で書き換えない（manifest の hash・工程の時刻・本人の確認の対象が壊れる）。改訂は Re-Inception で改訂の Task を足し、/04-operation でその工程をやり直す。この一覧は改訂の範囲の案で、直すかは本人が決める'}

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
            return {'state':'declined','next':'前に通常方式を選んでいる。考えを変えるなら '+recollect}
        return {'state':'unselected','next':recollect,'note':'方式の選択は本人の回答（受領記録）でだけ intent に書かれる。pm-init は書かない'}
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
    allowed,required=KIND[item][2][verb]
    return _write(layer,name,_input(layer,input_path,allowed,required),apply,c,rc,files)

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
    return {'route':'pm','op':name,'applied':True,'changed_ids':changed,'file':str(target.relative_to(layer)),'new_problems':[]}
