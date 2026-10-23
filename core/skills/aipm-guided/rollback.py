#!/usr/bin/env python3
"""Preflight every owned file before restoring this change only. No Git/DB resets."""
from pathlib import Path
import argparse, hashlib, json, shutil

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def safe(root,rel):
    if not isinstance(rel,str) or not rel or Path(rel).is_absolute() or '..' in Path(rel).parts: raise ValueError('unsafe manifest path')
    q=root/rel
    if any(x.is_symlink() for x in [q,*q.parents] if x==root or root in x.parents):raise ValueError('symlink refused')
    if not q.resolve().is_relative_to(root.resolve()):raise ValueError('outside root')
    return q

def rollback(root,manifest,retire,apply=False):
    root=Path(root).absolute();retire=Path(retire).absolute();entries=manifest['files']
    if retire.exists() or not retire.is_relative_to(root):raise ValueError('retirement must be a new directory inside root')
    safe(root,str(retire.relative_to(root)))
    if not isinstance(entries,list) or not entries:raise ValueError('empty patch manifest')
    seen=set()
    for e in entries:
        rel=e['path']
        if rel in seen:raise ValueError('duplicate path')
        seen.add(rel)
        if not (rel.startswith('.claude/skills/ai-plc/') or rel.startswith('.claude/skills/aipm-guided/')):raise ValueError('outside exact shared scope')
        q=safe(root,rel)
        if not q.is_file() or digest(q)!=e['after_sha256']:raise ValueError('another writer changed '+rel+'; no rollback writes')
        if e.get('before_text') is not None and hashlib.sha256(e['before_text'].encode()).hexdigest()!=e['before_sha256']:raise ValueError('corrupt backup')
    added_root=root/'.claude/skills/aipm-guided'
    actual={str(p.relative_to(root)) for p in added_root.rglob('*') if p.is_file() or p.is_symlink()} if added_root.exists() else set()
    if actual!={e['path'] for e in entries if e.get('before_text') is None}:raise ValueError('unknown new file; refuse retirement')
    if not apply:return {'pass':True,'dry_run':True,'files':len(entries)}
    # All preflight checks precede writes. Files are retained rather than discarded.
    retire.mkdir(parents=True)
    for e in entries:
        q=root/e['path']
        if e.get('before_text') is None:
            dest=retire/e['path'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(q),str(dest))
        else:q.write_text(e['before_text'])
    return {'pass':True,'dry_run':False,'files':len(entries),'retirement':str(retire)}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--manifest',required=True);p.add_argument('--retire',required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
    try:result=rollback(a.root,json.loads(Path(a.manifest).read_text()),a.retire,a.apply)
    except Exception as e:result={'pass':False,'error':str(e)}
    print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result['pass'] else 1)
