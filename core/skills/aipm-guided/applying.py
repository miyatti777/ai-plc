"""apply: the adopted proposals into the box as a new version (stage 6), the version into the Stock (stage 7, push) and back
to the base when not pushed.

Every write checks every condition first (the dry-run gives the same answer), writes, runs validate final and puts back all
it wrote when final is worse than before, also on an exception or Ctrl-C. Earlier receipts, human_responses, checkpoint_targets
and evidence rows are never rewritten; a new version's receipt is made from the person's judgement (judge-change) and bound to
that version only. The Stock repository is never committed or pushed with git here (the person decides).
"""
import contextlib, os, shutil
from datetime import datetime, timezone
from pathlib import Path
import yaml
import changes
from package import load, safe_path, sha, slug, apply_box, apply_log_text, APPLY_LOG, LOG_KEYS

def _now():return datetime.now(timezone.utc).isoformat()
def _dump(data):return yaml.safe_dump(data,allow_unicode=True,sort_keys=False)
def _need(approval_ref):
    if not isinstance(approval_ref,str) or not approval_ref.strip():raise ValueError('--apply needs --approval-ref (the person\'s approval of this apply; nothing written)')
def _errors(res):return {(e['code'],e['path'],e['message']) for e in res['errors']}
def _replace(q,data):
    """Write bytes through a temporary file in the same folder and a rename (never half a file)."""
    tmp=q.with_name('.'+q.name+'.apply_tmp')
    try:
        with open(tmp,'wb') as f:f.write(data)
        os.replace(tmp,q)
    finally:tmp.unlink(missing_ok=True)   # never left behind, also on Ctrl-C between the write and the rename

def latest_list(layer):
    d=safe_path(layer,changes.CHANGES)
    lists=[load(q)|{'_path':q} for q in d.glob('list_*.yaml')] if d.is_dir() else []
    if not lists:raise ValueError('no list shown to the person yet; run change-list and judge-change first (nothing written)')
    return max(lists,key=lambda x:datetime.fromisoformat(x['created_at']))

def plan(layer,approval_ref=None):
    """Everything stage 6 would write, checked: the adopted proposals of the last list, the new bytes of each document, the
    receipts to make, the event, the version entry. Stops (raises) on any condition that is not met."""
    from validate_package import validate
    layer,c,root,m,docs,base=changes.box(layer)
    applies=m['applies'];n=len(applies)+1;pkg=c['package_root']
    lst=latest_list(layer)
    if changes._digest(changes._entries(layer))!=lst['digest']:raise ValueError('the proposals changed after the last list; show the list again and judge it (nothing written)')
    props={p['id']:p for p in changes.proposals(layer)}
    adopted=[props[e['id']] for e in lst['entries'] if props[e['id']]['judgment'].get('state')=='adopted' and props[e['id']]['merge'].get('state')=='not_merged']
    if not adopted:raise ValueError('no adopted proposal in the last list (nothing written)')
    for p in adopted:
        if p.get('base_version')!=base['version']:raise ValueError(p['id']+' was made on version '+str(p.get('base_version'))+', not the cloned version '+str(base['version'])+' (nothing written)')
    new={};texts={}
    for p in sorted(adopted,key=lambda p:p['id']):
        path=p['target']['path']
        if path not in docs:raise ValueError(p['id']+': '+path+' is not a document of the version (nothing written)')
        if path not in texts:
            q=safe_path(root,path)
            if sha(q)!=docs[path]:raise ValueError(path+' differs from version '+str(base['version'])+' (changed outside apply; nothing written)')
            texts[path]=q.read_text()
        text=texts[path];a,b=changes.region(text,path,p['target']['locator']);k=text[a:b].count(p['before'])
        if k!=1:raise ValueError(p['id']+': before is '+('not' if k==0 else str(k)+' times')+' in '+path+' / '+p['target']['locator']+' now (an old proposal; nothing written)')
        i=text.index(p['before'],a);texts[path]=text[:i]+p['after']+text[i+len(p['before']):]
        new.setdefault(path,[]).append(p)
    # an evidence row on a document this version changes would lose its source_sha256
    on=[e.get('id') for e in m.get('evidence') or [] if isinstance(e,dict) and e.get('source') in {pkg+'/'+x for x in new}]
    if on:raise ValueError('evidence '+', '.join(map(str,on))+' points into a document this version changes; that is out of apply (nothing written)')
    after={path:texts[path].encode() for path in new}
    import hashlib
    new_docs={**docs,**{path:hashlib.sha256(b).hexdigest() for path,b in after.items()}}
    for path in new:
        if new_docs[path]==docs[path]:raise ValueError(path+' would not change (nothing written)')
    # the person's answers bound to a changed document: a new receipt from the judgement
    # each adopted judgement answered one saved list (judge_change keeps its digest even when 修正 saves a newer list): the
    # apply_v<N> event starts when the earliest of those lists was made, so every judgement time lies in the event
    lists={}
    for v in new.values():
        for p in v:
            dg=p['judgment'].get('list_digest');q=safe_path(layer,changes.CHANGES+'/list_'+str(dg)+'.yaml')
            if not q.is_file():raise ValueError(p['id']+': the list it was judged on ('+str(dg)+') is missing (nothing written)')
            lists[dg]=load(q)
    start=min((x['created_at'] for x in lists.values()),key=datetime.fromisoformat)
    for v in new.values():
        for p in v:
            t=datetime.fromisoformat(p['judgment']['at'])
            if not datetime.fromisoformat(start)<=t<=datetime.now(timezone.utc):raise ValueError(p['id']+': the judgement time is outside the apply event (nothing written)')
    hr=m.get('human_responses') if isinstance(m.get('human_responses'),dict) else {}
    # the same list applied again after --revert-unpushed: the next attempt number (backups and receipts are never overwritten)
    stem='Context/aipm_changes/backup_v'+str(n)+'_'+lst['digest'][:12];k=1
    while safe_path(layer,stem+('' if k==1 else '_'+str(k))).exists():k+=1
    suffix='' if k==1 else '_'+str(k)
    receipts={}
    for key,r in hr.items():
        if not isinstance(r,dict) or not isinstance(r.get('target_path'),str) or not r['target_path'].startswith(pkg+'/'):continue
        path=r['target_path'][len(pkg)+1:]
        if path not in new:continue
        js=sorted((p['judgment'] for p in new[path]),key=lambda j:datetime.fromisoformat(j['at']));j=js[-1]   # the last reply on this document is the answer; every reply is kept in the receipt
        if not j.get('thread'):raise ValueError('the judgement of '+path+' (the target of the '+key+' answer) has no conversation id; judge it again with --thread (nothing written)')
        name='Context/receipt_apply_v'+str(n)+'_'+slug(key,'answer key')+'_'+lst['digest'][:12]+suffix+'.yaml'
        if safe_path(layer,name).exists():raise ValueError(name+' already exists; a receipt is never overwritten (nothing written)')
        receipts[key]={'file':name,'body':{'kind':'user_reported','actor':'actual_user','origin':'actual_user_reply','scope_id':c['scope_id'],'stage':key,'question':'apply v'+str(n)+' の変更案の一覧（'+lst['digest'][:12]+'）','answer':j['quote'],
            'question_id':j['list_digest'],'source_thread_id':j['thread'],'answered_at':j['at'],'received_at':j['at'],'target_path':r['target_path'],'target_sha256':new_docs[path],
            'judgments':[{'quote':x['quote'],'at':x['at'],'list_digest':x['list_digest'],**({'thread':x['thread']} if x.get('thread') else {})} for x in js]}}
    prev=(m.get('stages') or [{}])[-1].get('finished_at')
    if prev and datetime.fromisoformat(start)<datetime.fromisoformat(prev):raise ValueError('the list was made before the last stage ended ('+str(prev)+'); make the list again (nothing written)')
    backup=stem+suffix
    before=validate(root,phase='final',layer=layer)
    if not before['pass']:raise ValueError('final does not pass before apply; fix that first (nothing written): '+'; '.join(e['code']+' '+e['path'] for e in before['errors'][:3]))
    return {'layer':layer,'c':c,'root':root,'m':m,'docs':docs,'base':base,'n':n,'list':lst,'new':new,'after':after,'new_docs':new_docs,'receipts':receipts,'start':start,'backup':backup,'before':before}

def apply(layer,*,apply=False,approval_ref=None):
    """Stage 6: put the adopted proposals of the last list into the box as version n (pushed: false). Dry-run unless apply."""
    from validate_package import validate
    P=plan(layer)
    out={'route':'aipm','apply':bool(apply),'version':P['n'],'base_version':P['base']['version'],'list_digest':P['list']['digest'],
         'changed':[{'path':k,'change_ids':[p['id'] for p in v]} for k,v in P['new'].items()],'receipts':sorted(P['receipts']),'backup':P['backup']}
    if not apply:return out
    _need(approval_ref)
    layer,root,m,n=P['layer'],P['root'],P['m'],P['n'];mp=root/'manifest.yaml'
    saved_manifest=mp.read_bytes();manifest_ns=mp.stat().st_mtime_ns;saved_docs={};made=[];props_old={}
    bdir=safe_path(layer,P['backup'])
    try:
        bdir.mkdir(parents=True);made.append(bdir)
        shutil.copy2(mp,bdir/'manifest.yaml')
        for path in P['new']:
            q=safe_path(root,path);saved_docs[path]=(q.read_bytes(),q.stat().st_mtime_ns)
            t=bdir/'documents'/path;t.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(q,t)
        mtimes={}
        for path,b in P['after'].items():
            q=safe_path(root,path);_replace(q,b);mtimes[path]=q.stat().st_mtime_ns
        bound={}
        for key,x in P['receipts'].items():
            q=safe_path(layer,x['file'])
            with open(q,'x') as f:made.append(q);f.write(_dump(x['body']))
            bound[key]={'source':x['file'],'source_sha256':sha(q),'answer':x['body']['answer'],'target_path':x['body']['target_path'],'target_sha256':x['body']['target_sha256'],'received_at':x['body']['received_at'],'list_digest':x['body']['question_id']}
            m.setdefault('evidence',[]).append({'id':'USR-apply_v'+str(n)+'-'+key,'kind':'user_reported','source':x['file'],'source_sha256':bound[key]['source_sha256'],'scope':'本人の判定（apply v'+str(n)+' の変更案の一覧への返事）だけで、実ユーザーの観察ではない'})
        for r in m['records']:
            if isinstance(r,dict) and r.get('path') in P['after']:r.update(sha256=P['new_docs'][r['path']],applied_in=n,applied_mtime_ns=mtimes[r['path']])
        event='apply_v'+str(n)
        m['stages'].append({'name':event,'started_at':P['start'],'finished_at':_now(),'checkpoint_actor':'auto_decision','checkpoint_status':'accepted_local','evidence_refs':['USR-apply_v'+str(n)+'-'+k for k in bound]})
        m['applies'].append({'version':n,'kind':'apply','at':_now(),'approval_ref':approval_ref,'base_version':P['base']['version'],'docs':P['new_docs'],
            'changed':[{'path':k,'before':P['docs'][k],'after':P['new_docs'][k],'change_ids':[p['id'] for p in v]} for k,v in P['new'].items()],
            'receipts':bound,'event':event,'pushed':False,'stock_target_rel':P['m']['applies'][-1]['stock_target_rel'],'backup':P['backup'],'list_digest':P['list']['digest']})
        mp.write_text(_dump(m));(bdir/'applied_manifest.sha256').write_text(sha(mp)+'\n')   # revert refuses when the manifest changed after this
        for v in P['new'].values():
            for p in v:
                f=safe_path(layer,changes.CHANGES+'/'+p['id']+'.yaml');props_old[f]=(f.read_bytes(),f.stat().st_mtime_ns)
                p2=load(f);p2['merge']={'state':'merged','version':n,'at':_now()};f.write_text(_dump(p2))
        res=validate(root,phase='final',layer=layer)
        worse=_errors(res)-_errors(P['before'])
        if worse:raise ValueError('final is worse after apply: '+'; '.join(' '.join(e) for e in sorted(worse)[:3]))
    except BaseException as ex:
        for path,(b,t) in saved_docs.items():
            q=safe_path(root,path);_replace(q,b);os.utime(q,ns=(t,t))
        mp.write_bytes(saved_manifest);os.utime(mp,ns=(manifest_ns,manifest_ns))
        for f,(b,t) in props_old.items():f.write_bytes(b);os.utime(f,ns=(t,t))
        for q in reversed(made):
            if q.is_dir():shutil.rmtree(q,ignore_errors=True)
            else:q.unlink(missing_ok=True)
        raise ValueError('apply stopped ('+type(ex).__name__+': '+str(ex)+'); the box, the receipts and the proposals are as before') from ex
    out['final']=res
    return out

def push(layer,*,apply=False,approval_ref=None,stock_root=None):
    """Stage 7: write the unpushed version into the Stock. Before writing, every Stock document must still be what clone saw
    (base) and the Stock apply_log must hold the pushed versions of the box; otherwise nothing is written (a conflict)."""
    from validate_package import validate
    layer,c,root,m,base_root,target=apply_box(layer,stock_root)
    applies=m.get('applies') or []
    if not applies or applies[-1].get('pushed') is not False:raise ValueError('no version to push (nothing written)')
    last=applies[-1];pushed=[a for a in applies if a.get('pushed')]
    bq=safe_path(layer,changes.CHANGES+'/base_'+slug(c['bindings']['project_id'],'project')+'.yaml')
    if not bq.is_file():raise ValueError('no work base (nothing written)')
    base=load(bq)
    if base.get('version')!=last.get('base_version'):raise ValueError('the work base is version '+str(base.get('version'))+', the version to push was made on '+str(last.get('base_version'))+' (nothing written)')
    by_path={r['path']:r for r in m['records'] if isinstance(r,dict) and r.get('archive_path')}
    for path,h in last['docs'].items():
        if sha(safe_path(root,path))!=h:raise ValueError('the box document '+path+' changed after apply (nothing written)')
    for path,h in base['docs'].items():
        if path not in by_path:raise ValueError('the base names '+path+', which has no Stock copy in the records (nothing written)')
        q=safe_path(base_root,by_path[path]['archive_path'])
        if not q.is_file() or sha(q)!=h:raise ValueError('the Stock changed after clone: '+by_path[path]['archive_path']+' (a conflict; take in the newer Stock first; nothing written)')
    lq=safe_path(base_root,target+'/'+APPLY_LOG)
    if not lq.is_file() or (load(lq) or {}).get('versions')!=[{k:a.get(k) for k in LOG_KEYS} for a in pushed]:raise ValueError('the Stock apply_log differs from the pushed versions of the box (a conflict; nothing written)')
    before=validate(root,phase='final',layer=layer,stock_root=base_root)
    if not before['pass']:raise ValueError('final does not pass before push (nothing written): '+'; '.join(e['code']+' '+e['path'] for e in before['errors'][:3]))
    changed=[x['path'] for x in last['changed']]
    out={'route':'aipm','apply':bool(apply),'version':last['version'],'documents':[by_path[p]['archive_path'] for p in changed],'apply_log':target+'/'+APPLY_LOG}
    if not apply:return out
    _need(approval_ref)
    mp=root/'manifest.yaml';saved_manifest=mp.read_bytes();saved_log=lq.read_bytes();saved_base=bq.read_bytes();done={}
    times={q:q.stat().st_mtime_ns for q in (mp,bq)}
    try:
        for p in changed:
            q=safe_path(base_root,by_path[p]['archive_path']);done[q]=(q.read_bytes(),q.stat().st_mtime_ns)
            _replace(q,safe_path(root,p).read_bytes());shutil.copystat(safe_path(root,p),q)
        for p in changed:by_path[p]['archive_sha256']=last['docs'][p]
        last['pushed']=True;last['push_approval_ref']=approval_ref;last['pushed_at']=_now()
        done[lq]=(saved_log,lq.stat().st_mtime_ns);_replace(lq,apply_log_text(layer,c,m).encode())
        mp.write_text(_dump(m))
        bq.write_text(_dump({'project':base['project'],'version':last['version'],'stock_target_rel':target,'docs':dict(last['docs']),'cloned_at':_now(),'after_push':True}))
        res=validate(root,phase='final',layer=layer,stock_root=base_root)
        worse=_errors(res)-_errors(before)
        if worse:raise ValueError('final is worse after push: '+'; '.join(' '.join(e) for e in sorted(worse)[:3]))
    except BaseException as ex:
        for q,(b,t) in done.items():_replace(q,b);os.utime(q,ns=(t,t))
        mp.write_bytes(saved_manifest);bq.write_bytes(saved_base)
        for q,t in times.items():os.utime(q,ns=(t,t))
        raise ValueError('push stopped ('+type(ex).__name__+': '+str(ex)+'); the Stock and the box are as before') from ex
    out['final']=res
    return out

def revert_unpushed(layer,*,apply=False,approval_ref=None):
    """Put the box back to the base from the backup of the unpushed version: documents and manifest (its evidence rows,
    receipts and version go with it). The proposals become not_merged again; receipt files stay (bound to no version)."""
    layer,c,root,m,base_root,target=apply_box(layer)
    applies=m.get('applies') or []
    if not applies or applies[-1].get('pushed') is not False:raise ValueError('no unpushed version to revert (nothing written)')
    last=applies[-1];bdir=safe_path(layer,last.get('backup') or '-')
    if not (bdir/'manifest.yaml').is_file():raise ValueError('the backup of version '+str(last['version'])+' is missing (nothing written)')
    for path,h in last['docs'].items():
        if sha(safe_path(root,path))!=h:raise ValueError('the box document '+path+' changed after apply; revert would lose it (nothing written)')
    mark=bdir/'applied_manifest.sha256'
    if not mark.is_file() or mark.read_text().strip()!=sha(root/'manifest.yaml'):raise ValueError('the manifest changed after apply (a receipt, evidence or another record was added?); revert would drop it, check by hand (nothing written)')
    changed=[x['path'] for x in last['changed']]
    for p in changed:
        if not (bdir/'documents'/p).is_file():raise ValueError('the backup lacks '+p+' (nothing written)')
    ids=[i for x in last['changed'] for i in x['change_ids']]
    out={'route':'aipm','apply':bool(apply),'version':last['version'],'documents':changed,'proposals':ids}
    if not apply:return out
    _need(approval_ref)
    from validate_package import validate
    before=validate(root,phase='final',layer=layer)
    mp=root/'manifest.yaml';saved={mp:(mp.read_bytes(),mp.stat().st_mtime_ns)};props={}
    try:
        for p in changed:
            q=safe_path(root,p);saved[q]=(q.read_bytes(),q.stat().st_mtime_ns);_replace(q,(bdir/'documents'/p).read_bytes());shutil.copystat(bdir/'documents'/p,q)
        _replace(mp,(bdir/'manifest.yaml').read_bytes());shutil.copystat(bdir/'manifest.yaml',mp)   # the bytes and the time before the apply
        for i in ids:
            f=safe_path(layer,changes.CHANGES+'/'+i+'.yaml');props[f]=(f.read_bytes(),f.stat().st_mtime_ns);p=load(f);p['merge']={'state':'not_merged'};f.write_text(_dump(p))
        res=validate(root,phase='final',layer=layer)
        worse=_errors(res)-_errors(before)
        if worse:raise ValueError('final is worse after revert: '+'; '.join(' '.join(e) for e in sorted(worse)[:3]))
    except BaseException as ex:
        for q,(b,t) in saved.items():_replace(q,b);os.utime(q,ns=(t,t))
        for f,(b,t) in props.items():f.write_bytes(b);os.utime(f,ns=(t,t))
        raise ValueError('revert stopped ('+type(ex).__name__+': '+str(ex)+'); the box is as before') from ex
    out['reverted']=True;out['final']=res
    return out
