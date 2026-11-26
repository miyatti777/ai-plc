"""Change proposals, ripple drafts and the person's judgement for a box with versions.

Nothing here writes the box: the 19 documents, the registers and the manifest keep their bytes. Proposals, the numbered lists
shown to the person and the work base live in the owner Layer's Context/aipm_changes/. A proposal is made from a candidate YAML
(the AI or the person writes the candidate; the tool checks it against the cloned version), the ripple of a change is listed
from three sources (inputs, stage_order, id_mention) and drafts are accepted only for the id_mention hits. The judgement is
never written by the AI: judge-change reads the person's words (one of five replies) against the saved list digest.
"""
import hashlib, json, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import yaml
from package import load, safe_path, sha, slug, apply_box

CHANGES='Context/aipm_changes'
STAGE_ORDER=['persona','problem','solution','story']   # the document stages (validation is the person's check, not a document)
JUDGEMENTS=('undecided','adopted','held','rejected')   # shown as 未判定・採用・保留・却下 (the pmo- words)
MERGES=('not_merged','merged','not_applicable')        # shown as 未・済・対象外
JUDGEMENT_KEYS={'result','status','verdict','priority','judgment','judgement','判定','優先','優先度','結果'}   # a draft does not change these (the person decides)
ID_RE=re.compile(r'(?<![A-Za-z0-9])[A-Z]{1,4}[0-9]{1,4}(?![0-9A-Za-z])')
SOURCE_KINDS=('conversation','document','meeting')

def _now():return datetime.now(timezone.utc).isoformat()
def _dump(data):return yaml.safe_dump(data,allow_unicode=True,sort_keys=False)
def _text(v,label):
    if not isinstance(v,str) or not v.strip():raise ValueError(label+' must be a non-empty string (nothing written)')
    return v

# ---- the box and the base ----
def box(layer):
    """(layer, contract, package root, manifest, docs of the last version, base) of a cloned box; stops otherwise."""
    layer,c,root,m,base_root,target=apply_box(layer)
    applies=m.get('applies')
    if not isinstance(applies,list) or not applies:raise ValueError('the box has no versions; run register and clone first (nothing written)')
    last=applies[-1]
    bq=safe_path(layer,CHANGES+'/base_'+slug(c['bindings']['project_id'],'project')+'.yaml')
    if not bq.is_file():raise ValueError('no work base; run clone first (nothing written)')
    base=load(bq) or {}
    if base.get('version')!=last.get('version') or not last.get('pushed'):raise ValueError('the work base (version '+str(base.get('version'))+') is not the last pushed version of the box (version '+str(last.get('version'))+'); finish that apply or clone again (nothing written)')
    return layer,c,root,m,last['docs'],base

# ---- where a change sits in a document ----
def _fenced(lines):
    out=set();inside=False
    for n,l in enumerate(lines):
        if l.lstrip().startswith(('```','~~~')):inside=not inside;out.add(n);continue
        if inside:out.add(n)
    return out
def _md_region(lines,locator):
    fence=_fenced(lines)
    heads=[(n,len(h.group(1)),h.group(2).strip()) for n,l in enumerate(lines) if n not in fence for h in [re.match(r'^(#{1,6})\s+(.*?)\s*#*\s*$',l)] if h]
    hit=[(n,lv) for n,lv,t in heads if t==locator.strip()]
    if len(hit)!=1:return None if not hit else 'ambiguous'
    n,lv=hit[0];end=next((k for k,l2,t in heads if k>n and l2<=lv),len(lines))
    return n,end
def _yaml_region(lines,locator):
    """(start, end) line range of a dotted YAML key. Each part is matched among the DIRECT children of the block above it
    only (a deeper key of the same name is not it); a key found more than once (e.g. the same key in every list item) is
    'ambiguous': the change is never placed on the first one by guessing."""
    def info(l):
        s=l.lstrip(' ');ind=len(l)-len(s)
        if s.startswith('- '):s=s[2:];ind+=2
        return s,ind
    def content(l):return bool(l.strip()) and not l.lstrip(' ').startswith('#')
    start,end,lo=0,len(lines),0
    for key in locator.split('.'):
        kids=[n for n in range(lo,end) if content(lines[n])]
        if not kids:return None
        child=min(info(lines[n])[1] for n in kids)
        found=[n for n in kids if info(lines[n])[1]==child and any(info(lines[n])[0].startswith(q+':') for q in (key,'"'+key+'"',"'"+key+"'"))]
        if not found:return None
        if len(found)>1:return 'ambiguous'
        n=found[0];ind=info(lines[n])[1]
        def ends(l):   # the next line at a lower indent, or at the same indent and not a list item of this key, ends the block
            k=len(l)-len(l.lstrip(' '));return content(l) and (k<ind or (k==ind and not l.lstrip(' ').startswith('- ')))
        stop=next((k for k in range(n+1,end) if ends(lines[k])),end)
        start,end,lo=n,stop,n+1
    return start,end
def region(text,path,locator):
    """(start, end) character offsets of the section (Markdown heading) or the key block (YAML dotted key); stops when it is
    not found or a heading is not unique (a change is never placed by guessing)."""
    lines=text.splitlines(keepends=True)
    r=_yaml_region(lines,locator) if path.endswith(('.yaml','.yml')) else _md_region(lines,locator)
    if r=='ambiguous':raise ValueError('locator '+repr(locator)+' names more than one heading or key in '+path+' (nothing written)')
    if r is None:raise ValueError('locator '+repr(locator)+' not found in '+path+' (nothing written)')
    a=sum(len(l) for l in lines[:r[0]]);b=sum(len(l) for l in lines[:r[1]])
    return a,b
def place(root,path,locator,before):
    """Check that before occurs exactly once in the located part of the document as it is now."""
    q=safe_path(root,path);text=q.read_text()
    a,b=region(text,path,locator);n=text[a:b].count(before)
    if n!=1:raise ValueError(('before is not in ' if n==0 else 'before occurs '+str(n)+' times in ')+path+' / '+locator+' (an old or wrong proposal; nothing written)')
    return text
def last_key(locator):return locator.split('.')[-1].strip()

# ---- ripple ----
def ids_of(*texts):return sorted({x for t in texts if isinstance(t,str) for x in ID_RE.findall(t)})
def hits(text,ids,path):
    """The lines of a document that mention any of ids, each with the locator around it (heading or top-level key)."""
    out=[];head=None;yml=path.endswith(('.yaml','.yml'))
    for n,l in enumerate(text.splitlines(),1):
        if not yml and (h:=re.match(r'^#{1,6}\s+(.*?)\s*#*\s*$',l)):head=h.group(1).strip()
        if yml and l and not l[0].isspace() and ':' in l and not l.startswith(('#','-')):head=l.split(':',1)[0].strip().strip('"\'')
        found=[i for i in ids if re.search(r'(?<![A-Za-z0-9])'+re.escape(i)+r'(?![0-9A-Za-z])',l)]
        if found:out.append({'line':n,'locator':head,'ids':found,'text':l.strip()})
    return out
def ripple(layer,c,root,m,docs,path,ids):
    """Affected documents of a change of path: inputs (a record reads path), stage_order (a later document stage) and
    id_mention (another document names one of ids). Only documents of the version (archive copies) are listed."""
    recs={r['path']:r for r in m['records'] if isinstance(r,dict) and r.get('path') in docs}
    stage=recs[path].get('stage');idx=STAGE_ORDER.index(stage) if stage in STAGE_ORDER else len(STAGE_ORDER)
    pkg=c['package_root']+'/'+path;out=[]
    for p,r in recs.items():
        if p==path:continue
        why=[]
        if any(isinstance(x,str) and (x==pkg or x.endswith('/'+pkg)) for x in r.get('inputs') or []):why.append('inputs')
        if r.get('stage') in STAGE_ORDER and STAGE_ORDER.index(r['stage'])>idx:why.append('stage_order')
        h=hits(safe_path(root,p).read_text(),ids,p) if ids else []
        if h:why.append('id_mention')
        if why:out.append({'path':p,'stage':r.get('stage'),'reason':why,'ids':sorted({i for x in h for i in x['ids']}),'hits':h})
    return out

def mark(p,others):
    """The id_mention hits no draft covers are documents to check; a later-stage document without the ID is only listed."""
    drafted={d['target']['path'] for d in others if (d.get('origin') or {}).get('ripple_of')==p['id']}
    for h in p['impact']:h['draft']='drafted' if h['path'] in drafted else ('to_check' if 'id_mention' in h['reason'] else 'to_check_stage')

# ---- proposals ----
def _files(layer):
    d=safe_path(layer,CHANGES)
    return sorted(d.glob('C-*.yaml')) if d.is_dir() else []
def proposals(layer):return [load(q) for q in _files(layer)]
def _new_ids(layer,count):
    day=datetime.now(timezone.utc).astimezone().strftime('%Y%m%d');used=[int(x.group(1)) for q in _files(layer) for x in [re.fullmatch('C-'+day+r'-([0-9]+)',q.stem)] if x]
    n=max(used,default=0);return ['C-'+day+'-'+str(n+k).zfill(2) for k in range(1,count+1)]
def content_sha(p):
    """The proposal without judgment and merge: writing a judgement keeps the list digest."""
    return hashlib.sha256(json.dumps({k:v for k,v in p.items() if k not in ('judgment','merge')},ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def change(layer,input_path,*,apply=False):
    """Stage 4: make proposals (and their ripple drafts) from a candidate YAML (Layer-relative):
      source: {kind: conversation|document|meeting, ref: "<where it came from, or the person's words>"}
      created_by: ai | owner          (default ai)
      changes:
        - target: {path: <document path of the version>, locator: <heading or dotted YAML key>}
          before: <the exact text now in that part>   after: <the new text>   reason: <why>
          ids: [PR8, ...]             (optional; default: the IDs in before and after)
          ripple_of: 1                (a draft for change 1 of this file: an id_mention hit of that change)
    Dry-run unless apply: returns the proposals with their ripple (and the id_mention hits not yet drafted). Stops (nothing
    written) when the box is not cloned, a target is not a document of the version (an init draft), the locator or before
    is not found once, a draft is not on an id_mention hit or would change a judgement key."""
    layer,c,root,m,docs,base=box(layer)
    q=safe_path(layer,_text(input_path,'--input'));data=load(q)
    if not isinstance(data,dict) or not isinstance(data.get('changes'),list) or not data['changes']:raise ValueError('the input needs a changes list (nothing written)')
    src=data.get('source')
    if not isinstance(src,dict) or src.get('kind') not in SOURCE_KINDS:raise ValueError('source.kind must be one of '+', '.join(SOURCE_KINDS)+' (nothing written)')
    _text(src.get('ref'),'source.ref')
    by=data.get('created_by','ai')
    if by not in ('ai','owner'):raise ValueError('created_by must be ai or owner (nothing written)')
    items=data['changes'];ids_new=_new_ids(layer,len(items));made=[];at=_now()
    for n,x in enumerate(items,1):
        if not isinstance(x,dict):raise ValueError('change '+str(n)+' must be a map (nothing written)')
        t=x.get('target') or {};path=_text(t.get('path'),'change '+str(n)+' target.path');loc=_text(t.get('locator'),'change '+str(n)+' target.locator')
        if path not in docs:raise ValueError('change '+str(n)+': '+path+' is not a document of version '+str(base['version'])+' (init drafts and unknown paths are out of apply; nothing written)')
        if sha(safe_path(root,path))!=docs[path]:raise ValueError('change '+str(n)+': '+path+' differs from version '+str(base['version'])+' (nothing written)')
        before=_text(x.get('before'),'change '+str(n)+' before');after=x.get('after')
        if not isinstance(after,str) or after==before:raise ValueError('change '+str(n)+': after must be a string that differs from before (nothing written)')
        place(root,path,loc,before)
        ids=x.get('ids')
        if ids is None:ids=ids_of(before,after)
        if not isinstance(ids,list) or any(not isinstance(i,str) or not i for i in ids):raise ValueError('change '+str(n)+': ids must be a list of strings (nothing written)')
        p={'id':ids_new[n-1],'created_at':at,'created_by':by,'source':{'kind':src['kind'],'ref':src['ref']},'target':{'path':path,'locator':loc},
           'base_version':base['version'],'before':before,'after':after,'reason':_text(x.get('reason'),'change '+str(n)+' reason'),'ids':sorted(set(ids)),
           'origin':None,'impact':[],'drafts':[],'judgment':{'state':'undecided'},'merge':{'state':'not_merged'}}
        r=x.get('ripple_of')
        if r is not None:
            if not isinstance(r,int) or isinstance(r,bool) or not 1<=r<n or items[r-1].get('ripple_of') is not None:raise ValueError('change '+str(n)+': ripple_of names an earlier main change of this file (nothing written)')
            main=made[r-1];slots={h['path'] for h in main['impact'] if 'id_mention' in h['reason']}
            if path not in slots:raise ValueError('change '+str(n)+': a draft is only made on an id_mention hit of change '+str(r)+' ('+path+' is not one; nothing written)')
            if last_key(loc) in JUDGEMENT_KEYS:raise ValueError('change '+str(n)+': a draft does not change '+loc+' (a judgement the person decides; list it instead; nothing written)')
            p['origin']={'ripple_of':main['id']};main['drafts'].append(p['id'])
        else:
            p['impact']=ripple(layer,c,root,m,docs,path,ids)
        made.append(p)
    for p in made:
        if p['origin'] is None:mark(p,made)
    out={'route':'aipm','apply':bool(apply),'base_version':base['version'],'proposals':made}
    if not apply:return out
    d=safe_path(layer,CHANGES);written=[]
    try:
        for p in made:
            f=safe_path(layer,CHANGES+'/'+p['id']+'.yaml')
            with open(f,'x') as h:written.append(f);h.write(_dump(p))
    except BaseException as ex:
        for f in written:f.unlink(missing_ok=True)
        raise ValueError('change stopped ('+type(ex).__name__+': '+str(ex)+'); nothing written') from ex
    out['written']=[str(f.relative_to(layer)) for f in written]
    return out

# ---- the numbered list and the judgement (stage 5) ----
def _entries(layer):
    return [{'n':n,'id':p['id'],'content_sha256':content_sha(p)} for n,p in enumerate(sorted((p for p in proposals(layer) if (p.get('merge') or {}).get('state')=='not_merged'),key=lambda p:p['id']),1)]
def _digest(entries):return hashlib.sha256(json.dumps(entries,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def change_list(layer):
    """The numbered list of the proposals not merged yet, saved as list_<digest>.yaml (the same list again is not rewritten).
    The person answers against this list; its digest (first 12 shown) binds the answer to these numbers."""
    layer,c,root,m,docs,base=box(layer)
    entries=_entries(layer)
    if not entries:raise ValueError('no proposal to judge (nothing written)')
    dg=_digest(entries);q=safe_path(layer,CHANGES+'/list_'+dg+'.yaml');written=False
    if not q.exists():
        with open(q,'x') as f:f.write(_dump({'digest':dg,'created_at':_now(),'base_version':base['version'],'entries':entries,'replies':[]}))
        written=True
    by={p['id']:p for p in proposals(layer)}
    rows=[{'n':e['n'],'id':e['id'],'path':by[e['id']]['target']['path'],'locator':by[e['id']]['target']['locator'],'before':by[e['id']]['before'],'after':by[e['id']]['after'],
           'ripple_of':(by[e['id']].get('origin') or {}).get('ripple_of'),'judgment':by[e['id']]['judgment']['state']} for e in entries]
    return {'route':'aipm','list':str(q.relative_to(layer)),'digest':dg,'digest_short':dg[:12],'written':written,'rows':rows,
            'replies':'OK（全件反映）／採用: 1,3／修正: 2 は〜／今回はレポートのみ／差し戻し'}

def _aware(v):
    try:t=datetime.fromisoformat(v)
    except (TypeError,ValueError):raise ValueError('--at must be an ISO time with its offset (nothing written)')
    if t.tzinfo is None:raise ValueError('--at must carry its offset (nothing written)')
    if t>datetime.now(timezone.utc)+timedelta(minutes=10):raise ValueError('--at is in the future; give the time the person said it (nothing written)')
    return t
def parse_reply(quote,count):
    """(kind, numbers, text) of one of the five replies; anything else stops (「いいね」「それで」, no numbers, ...)."""
    s=quote.strip()
    if re.fullmatch(r'OK(\s*[（(]全件反映[）)])?',s):return 'all',list(range(1,count+1)),None
    if s=='今回はレポートのみ':return 'report_only',[],None
    if s=='差し戻し':return 'send_back',[],None
    m=re.fullmatch(r'採用\s*[:：]\s*([0-9０-９][0-9０-９\s,、，]*)',s)
    if m:
        nums=[int(x.translate(str.maketrans('０１２３４５６７８９','0123456789'))) for x in re.split(r'[\s,、，]+',m.group(1).strip()) if x]
        if not nums or len(set(nums))!=len(nums) or any(not 1<=x<=count for x in nums):raise ValueError('採用 names a number not in the list, or twice (nothing written)')
        return 'adopt',nums,None
    m=re.fullmatch(r'修正\s*[:：]\s*([0-9０-９]+)\s*は\s*(.+)',s,re.S)
    if m:
        k=int(m.group(1).translate(str.maketrans('０１２３４５６７８９','0123456789')))
        if not 1<=k<=count:raise ValueError('修正 names a number not in the list (nothing written)')
        text=m.group(2).strip();q=re.fullmatch(r'「([^「」]+)」\s*(に直す|にする|へ|で)?[。.]?',text,re.S)   # 「…」に直す: the words inside 「」 are the new text
        return 'revise',[k],(q.group(1) if q else text)
    raise ValueError('not one of the five replies (OK（全件反映）／採用: 1,3／修正: 2 は〜／今回はレポートのみ／差し戻し); nothing is judged')
def judge_change(layer,digest,quote,at,thread=None):
    """Record the person's reply to the saved list: the words as they were said, the time, the list digest. Stops (nothing
    written) when the list is not the current one (a proposal was added or changed after it), the time is before the list,
    or the words are not one of the five replies. 修正 changes the after of that proposal, adopts it and saves a new list."""
    layer,c,root,m,docs,base=box(layer)
    _text(quote,'--quote');t=_aware(at);_text(digest,'--list')
    if not re.fullmatch(r'[0-9a-f]{12,64}',digest):raise ValueError('--list is the list digest (at least its first 12 characters; nothing written)')
    found=[q for q in safe_path(layer,CHANGES).glob('list_'+digest+'*.yaml')] if safe_path(layer,CHANGES).is_dir() else []
    if len(found)!=1:raise ValueError('no single saved list for '+digest+' (nothing written)')
    lq=found[0];saved=load(lq)
    if _digest(_entries(layer))!=saved['digest']:raise ValueError('the proposals changed after this list (new or edited); show the list again and ask again (nothing written)')
    if t<datetime.fromisoformat(saved['created_at']):raise ValueError('the words are older than the list; only a reply to this list judges it (nothing written)')
    kind,nums,text=parse_reply(quote,len(saved['entries']))
    by={e['n']:e['id'] for e in saved['entries']}
    state={'all':'adopted','adopt':'adopted','revise':'adopted','report_only':'held','send_back':'rejected'}[kind]
    targets=[by[n] for n in nums] if kind in ('all','adopt','revise') else [e['id'] for e in saved['entries']]
    rec={'state':state,'quote':quote,'at':t.isoformat(),'list_digest':saved['digest'],'reply':kind,**({'thread':thread} if thread else {})}
    files={i:safe_path(layer,CHANGES+'/'+i+'.yaml') for i in targets};old={i:f.read_bytes() for i,f in files.items()}
    changed=[]
    for i,f in files.items():
        p=load(f)
        if kind in ('report_only','send_back') and p['judgment']['state']!='undecided':continue   # a reply to the whole list leaves earlier decisions
        if kind=='revise':
            if text==p['before']:raise ValueError('修正 text equals before (nothing written)')
            p['after']=text
            if p.get('origin') is None:   # the ripple follows the new text (new IDs may be named)
                p['ids']=sorted(set(p.get('ids') or [])|set(ids_of(text)))   # the given ids stay; the new text may name more
                p['impact']=ripple(layer,c,root,m,docs,p['target']['path'],p['ids']);mark(p,proposals(layer))
        if kind in ('all','adopt') and p['judgment'].get('state')=='rejected':continue   # never reached: a rejected proposal has left the list
        p['judgment']=rec
        if state=='rejected':p['merge']={'state':'not_applicable'}   # 差し戻し: out of every later list
        changed.append((f,p))
    lold=lq.read_bytes();new_list=None;before_lists=set(safe_path(layer,CHANGES).glob('list_*.yaml'))
    try:
        for f,p in changed:f.write_text(_dump(p))
        saved['replies'].append({'quote':quote,'at':t.isoformat(),'reply':kind,'numbers':nums,**({'thread':thread} if thread else {})});lq.write_text(_dump(saved))
        if kind=='revise':new_list=change_list(layer)
    except BaseException as ex:
        for i,f in files.items():f.write_bytes(old[i])
        lq.write_bytes(lold)
        for q in set(safe_path(layer,CHANGES).glob('list_*.yaml'))-before_lists:q.unlink(missing_ok=True)
        raise ValueError('judge-change stopped ('+type(ex).__name__+': '+str(ex)+'); nothing changed') from ex
    out={'route':'aipm','list_digest':saved['digest'],'reply':kind,'judged':[p['id'] for f,p in changed],'state':state}
    if new_list:out['new_list']={'digest':new_list['digest'],'digest_short':new_list['digest_short'],'list':new_list['list']}
    return out
