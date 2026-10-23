#!/usr/bin/env python3
"""Local Project cancellation/reopening and lossless status-schema migration.

No Notion calls, Task writes, deletion of artifacts or native Goal operations.
Commands preview by default; --yes applies. Layer/DB writes use a recoverable
journal because SQLite and filesystem cannot share a physical transaction.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / '.claude/db/ai_plc.db'
STATUSES = ('planned', 'active', 'completed', 'paused', 'cancelled')
STATUS_CHECK = re.compile(r"CHECK\s*\(\s*status\s+IN\s*\(([^)]*)\)\s*\)", re.I)
EVENT_SQL = '''CREATE TABLE IF NOT EXISTS project_lifecycle_events (
    event_uid TEXT PRIMARY KEY, project_id INTEGER NOT NULL,
    scope_id TEXT NOT NULL, from_status TEXT NOT NULL, to_status TEXT NOT NULL,
    decision_json TEXT NOT NULL, recorded_at TEXT NOT NULL)'''


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@contextlib.contextmanager
def layer_write_lock(layer):
    """Shared advisory lock used by lifecycle and status-audit writers (Viewer is read-only).
    Editors/agents writing raw files must be quiescent for a lifecycle change.
    """
    with (Path(layer)/'.project-lifecycle.lock').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f,fcntl.LOCK_UN)


def snapshot(conn):
    """All rows, schema objects and AUTOINCREMENT sequence; no secret output."""
    schema = conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    tables = [r[1] for r in schema if r[0] == 'table']
    return {'schema': [tuple(r) for r in schema], 'rows': {
        t: sorted([tuple(r) for r in conn.execute('SELECT * FROM "'+t.replace('"','""')+'"')], key=repr)
        for t in tables}}


def status_schema(conn):
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name='projects' AND type='table'").fetchone()
    if not row:
        raise ValueError('PROJECT_TABLE_MISSING')
    match = STATUS_CHECK.search(row[0])
    if not match:
        raise ValueError('PROJECT_STATUS_CHECK_UNSUPPORTED')
    values = tuple(re.findall(r"'([^']*)'", match[1]))
    if values not in (STATUSES[:-1], STATUSES):
        raise ValueError('PROJECT_STATUS_CHECK_UNSUPPORTED')
    return row[0], match, values


def migrate(db, backup=None, *, apply=False, fail_at=None):
    db = Path(db).resolve()
    conn = sqlite3.connect(f'file:{db}?mode=rw', uri=True, timeout=10)
    try:
        sql, match, values = status_schema(conn)
        result = {'already_migrated': values == STATUSES, 'projects': conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0]}
        if not apply:
            return dict(result, preview=True, write_set=['projects CHECK', 'project_lifecycle_events'])
        if backup is None:
            raise ValueError('MIGRATION_BACKUP_REQUIRED')
        backup = Path(backup).resolve()
        if backup.exists() or not backup.parent.is_dir() or backup == db:
            raise ValueError('MIGRATION_BACKUP_PATH_INVALID')
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            if any(r[2] == 'projects' for r in conn.execute('PRAGMA foreign_key_list("'+table.replace('"','""')+'")')):
                raise ValueError('MIGRATION_PROJECT_FOREIGN_KEY_REQUIRES_REVIEW')
        # Reserve the only writer before taking the backup; a separate read
        # connection can back up the stable WAL snapshot without self-deadlock.
        conn.execute('BEGIN IMMEDIATE')
        # A schema writer may have won the lock since the preview read.
        # Only the locked snapshot is authoritative for the reconstruction.
        sql, match, values = status_schema(conn)
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            if any(r[2] == 'projects' for r in conn.execute('PRAGMA foreign_key_list("'+table.replace('"','""')+'")')):
                raise ValueError('MIGRATION_PROJECT_FOREIGN_KEY_REQUIRES_REVIEW')
        source = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        try:
            with sqlite3.connect(str(backup)) as target:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('MIGRATION_BACKUP_INTEGRITY_FAILED')
        finally:
            source.close()
        before = snapshot(conn)
        try:
            if values != STATUSES:
                new_sql = sql[:match.start()] + "CHECK(status IN ('planned','active','completed','paused','cancelled'))" + sql[match.end():]
                # The new table has the original name when recreating views and
                # triggers; no ALTER rename can rewrite their references.
                new_sql = re.sub(r'^(CREATE\s+TABLE\s+)(?:IF\s+NOT\s+EXISTS\s+)?["`\[]?projects["`\]]?', r'\1_projects_lifecycle_new', new_sql, count=1, flags=re.I)
                objects = [r[3] for r in before['schema'] if r[2] == 'projects' and r[0] in ('index','trigger') and r[3]]
                views = [(r[1], r[3]) for r in before['schema'] if r[0]=='view']
                cols = [r[1] for r in conn.execute('PRAGMA table_info(projects)')]
                quoted = ','.join('"'+c.replace('"','""')+'"' for c in cols)
                conn.execute(new_sql)
                conn.execute(f'INSERT INTO _projects_lifecycle_new ({quoted}) SELECT {quoted} FROM projects')
                if fail_at == 'after_copy':
                    raise RuntimeError('injected failure: after_copy')
                for name,_ in views:
                    conn.execute('DROP VIEW "'+name.replace('"','""')+'"')
                conn.execute('DROP TABLE projects')
                conn.execute('ALTER TABLE _projects_lifecycle_new RENAME TO projects')
                for statement in objects:
                    conn.execute(statement)
                for _,statement in views:
                    conn.execute(statement)
                seq = dict(before['rows'].get('sqlite_sequence', []))
                if 'projects' in seq:
                    conn.execute("UPDATE sqlite_sequence SET seq=? WHERE name='projects'", (seq['projects'],))
            after = snapshot(conn)
            if before['rows'] != after['rows']:
                raise ValueError('MIGRATION_ROW_PRESERVATION_FAILED')
            old_objects = [r for r in before['schema'] if not (r[0]=='table' and r[1]=='projects')]
            new_objects = [r for r in after['schema'] if not (r[0]=='table' and r[1]=='projects')]
            if old_objects != new_objects:
                raise ValueError('MIGRATION_OBJECT_PRESERVATION_FAILED')
            if fail_at == 'after_swap':
                raise RuntimeError('injected failure: after_swap')
            conn.execute(EVENT_SQL)
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('MIGRATION_INTEGRITY_FAILED')
            conn.commit()
        except BaseException:
            conn.rollback()
            if snapshot(conn) != before:
                raise RuntimeError('MIGRATION_ROLLBACK_MISMATCH')
            raise
        return dict(result, backup=str(backup), preserved=True)
    finally:
        conn.close()


def validate_decision(decision, *, reopening=False):
    if not isinstance(decision, dict):
        raise ValueError('DECISION_MAPPING_REQUIRED')
    keys = ['reason','decided_at','approved_by','approval_ref'] + (['replan_ref'] if reopening else ['retained_artifacts'])
    if any(not decision.get(k) for k in keys):
        raise ValueError('DECISION_REQUIRED: '+','.join(keys))
    for k in ['reason','decided_at','approved_by','approval_ref'] + (['replan_ref'] if reopening else []):
        if not isinstance(decision[k], str) or not decision[k].strip():
            raise ValueError('DECISION_TEXT_REQUIRED: '+k)
    try:
        when = datetime.fromisoformat(decision['decided_at'].replace('Z','+00:00'))
        if when.tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('DECISION_TIMEZONE_REQUIRED') from None
    if not reopening and (not isinstance(decision['retained_artifacts'], list) or
                          any(not isinstance(p,str) or not p.strip() for p in decision['retained_artifacts'])):
        raise ValueError('RETAINED_ARTIFACTS_LIST_REQUIRED')
    if decision.get('replacement_scope_id') is not None and not isinstance(decision['replacement_scope_id'], str):
        raise ValueError('REPLACEMENT_SCOPE_ID_INVALID')
    if decision.get('reconsider_when') is not None and not isinstance(decision['reconsider_when'], str):
        raise ValueError('RECONSIDER_CONDITION_INVALID')


def atomic_write(path, text, *, expected=None):
    temp = path.with_name(path.name+'.lifecycle-tmp')
    with temp.open('w', encoding='utf-8') as f:
        f.write(text); f.flush(); os.fsync(f.fileno())
    try:
        if expected is not None and path.read_text() != expected:
            raise ValueError('LIFECYCLE_CONCURRENT_FILE_CHANGE')
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def recover(db, layer, *, apply=False):
    with layer_write_lock(Path(layer).resolve()):
        return _recover_locked(db,layer,apply=apply)


def _recover_locked(db, layer, *, apply=False):
    layer = Path(layer).resolve()
    journal_path = layer / '.project-lifecycle-journal.json'
    if not journal_path.is_file():
        return {'recovery': 'not_needed'}
    journal = json.loads(journal_path.read_text())
    if journal['db'] != str(Path(db).resolve()):
        raise ValueError('RECOVERY_DATABASE_MISMATCH')
    with sqlite3.connect(f'file:{Path(db).resolve()}?mode=rw', uri=True) as conn:
        conn.execute('BEGIN IMMEDIATE')
        event = conn.execute('SELECT to_status FROM project_lifecycle_events WHERE event_uid=?',(journal['event_uid'],)).fetchone()
        side = 'after' if event else 'before'
        current = conn.execute('SELECT status FROM projects WHERE id=?',(journal['project_id'],)).fetchone()
        if not current or current[0] != (journal['to_status'] if event else journal['from_status']):
            raise ValueError('RECOVERY_REGISTRY_CONCURRENT_CHANGE')
        for name, pair in journal['files'].items():
            if name not in ('intent.yaml','backlog.yaml'):
                raise ValueError('RECOVERY_FILE_INVALID')
            if (layer/name).read_text() not in pair.values():
                raise ValueError('RECOVERY_CONCURRENT_FILE_CHANGE')
        if apply:
            for name, pair in journal['files'].items():
                original = (layer/name).read_text()
                if original not in pair.values():
                    raise ValueError('RECOVERY_CONCURRENT_FILE_CHANGE')
                atomic_write(layer/name, pair[side],expected=original)
            journal_path.unlink()
        return {'recovery': side, 'preview': not apply}


def transition(db, layer, to, decision, *, apply=False, expected=None, fail_at=None):
    with layer_write_lock(Path(layer).resolve()):
        return _transition_locked(db,layer,to,decision,apply=apply,expected=expected,fail_at=fail_at)


def _transition_locked(db, layer, to, decision, *, apply=False, expected=None, fail_at=None):
    layer = Path(layer).resolve(); db = Path(db).resolve()
    if to not in ('cancelled','active'):
        raise ValueError('TRANSITION_ONLY_CANCEL_OR_REOPEN')
    journal_path = layer/'.project-lifecycle-journal.json'
    if journal_path.exists():
        raise ValueError('LIFECYCLE_RECOVERY_REQUIRED')
    files = {n: {'before': (layer/n).read_text()} for n in ('intent.yaml','backlog.yaml')}
    intent, backlog = [yaml.safe_load(files[n]['before']) for n in files]
    if not isinstance(intent,dict) or not isinstance(backlog,dict):
        raise ValueError('LAYER_MAPPING_REQUIRED')
    sid = intent.get('scope_id')
    reopening = to == 'active'
    validate_decision(decision, reopening=reopening)
    conn = sqlite3.connect(f'file:{db}?mode=rw', uri=True, timeout=10)
    try:
        if status_schema(conn)[2] != STATUSES or not conn.execute("SELECT 1 FROM sqlite_master WHERE name='project_lifecycle_events'").fetchone():
            raise ValueError('PROJECT_LIFECYCLE_MIGRATION_REQUIRED')
        conn.execute('BEGIN IMMEDIATE')
        rows = conn.execute('SELECT id,status FROM projects WHERE scope_id=?',(sid,)).fetchall()
        if len(rows) != 1:
            raise ValueError('PROJECT_IDENTITY_AMBIGUOUS_OR_MISSING')
        project_id, current = rows[0]
        if expected and expected != {'intent': intent.get('status'), 'registry': current}:
            raise ValueError('PROJECT_STATUS_CONCURRENT_CHANGE')
        if (reopening and (current != 'cancelled' or intent.get('status') != 'cancelled')) or (not reopening and (current not in ('planned','active','paused') or intent.get('status') in ('completed','done','cancelled'))):
            raise ValueError('PROJECT_TRANSITION_INVALID')
        for artifact in ([decision['replan_ref']] if reopening else decision['retained_artifacts']):
            if not isinstance(artifact,str) or not artifact.strip():
                raise ValueError('DECISION_ARTIFACT_MISSING')
            artifact_path = (layer/artifact).resolve()
            if Path(artifact).is_absolute() or not artifact_path.is_relative_to(layer):
                raise ValueError('DECISION_ARTIFACT_OUTSIDE_LAYER')
            if not artifact_path.exists() or (reopening and not artifact_path.is_file()):
                raise ValueError('DECISION_REPLAN_FILE_REQUIRED' if reopening else 'DECISION_ARTIFACT_MISSING')
        replacement = decision.get('replacement_scope_id')
        if replacement and (replacement == sid or conn.execute('SELECT COUNT(*) FROM projects WHERE scope_id=?',(replacement,)).fetchone()[0] != 1):
            raise ValueError('REPLACEMENT_SCOPE_INVALID')
        event_uid = str(uuid.uuid4())
        record = dict(decision, event_uid=event_uid, from_status=current, to_status=to,
                      recorded_at=utc_now(), previous_intent_status=intent.get('status'),
                      goal_snapshot=intent.get('goal'), task_status_snapshot=[{'id':t.get('id'), 'status':t.get('status')} for t in backlog.get('tasks',[])])
        intent['status'] = to
        intent.setdefault('project_lifecycle_history', []).append(record)
        if not reopening:
            intent['cancellation'] = record
        summary = backlog.setdefault('summary',{})
        summary['status'] = to
        backlog.setdefault('refactoring_log',[]).append({'date':record['recorded_at'][:10], 'entry':f'Project {current} → {to}: {decision["reason"]}', 'event_uid':event_uid})
        for name,data in [('intent.yaml',intent),('backlog.yaml',backlog)]:
            files[name]['after'] = yaml.safe_dump(data,allow_unicode=True,sort_keys=False)
        if not apply:
            conn.rollback()
            return {'scope_id':sid,'from':current,'to':to,'preview':True,'task_mutations':0}
        # Re-read the entire files, not just status, before any mutation.
        if any((layer/n).read_text() != pair['before'] for n,pair in files.items()):
            raise ValueError('LIFECYCLE_CONCURRENT_FILE_CHANGE')
        atomic_write(journal_path,json.dumps({'db':str(db),'event_uid':event_uid,'project_id':project_id,
                    'from_status':current,'to_status':to,'files':files},ensure_ascii=False))
        try:
            written = []
            conn.execute('INSERT INTO project_lifecycle_events VALUES (?,?,?,?,?,?,?)',
                         (event_uid,project_id,sid,current,to,json.dumps(record,ensure_ascii=False),record['recorded_at']))
            conn.execute('UPDATE projects SET status=? WHERE id=? AND status=?',(to,project_id,current))
            if conn.execute('SELECT status FROM projects WHERE id=?',(project_id,)).fetchone() != (to,):
                raise ValueError('LIFECYCLE_REGISTRY_READBACK_MISMATCH')
            for name,pair in files.items():
                atomic_write(layer/name,pair['after'],expected=pair['before'])
                written.append(name)
                if fail_at == name:
                    raise RuntimeError('injected failure: '+name)
            if any((layer/n).read_text() != pair['after'] for n,pair in files.items()):
                raise ValueError('LIFECYCLE_CONCURRENT_FILE_CHANGE')
            conn.commit()
        except BaseException as exc:
            conn.rollback()
            # An asynchronous interruption can arrive *after* replace/commit
            # actually succeeded. Keep the durable journal until recover reads
            # the event, rather than guessing an outcome and deleting evidence.
            if not isinstance(exc, Exception) or conn.execute('SELECT 1 FROM project_lifecycle_events WHERE event_uid=?',(event_uid,)).fetchone():
                raise RuntimeError('LIFECYCLE_RECOVERY_REQUIRED: '+type(exc).__name__) from exc
            for name in written:
                pair = files[name]
                atomic_write(layer/name,pair['before'],expected=pair['after'])
            journal_path.unlink()
            raise
        journal_path.unlink()
        return {'scope_id':sid,'from':current,'to':to,'event_uid':event_uid,'task_mutations':0}
    finally:
        conn.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,default=DEFAULT_DB)
    sub = p.add_subparsers(dest='command',required=True)
    m = sub.add_parser('migrate'); m.add_argument('--backup',type=Path); m.add_argument('--yes',action='store_true')
    for cmd in ('cancel','reopen'):
        s = sub.add_parser(cmd); s.add_argument('--layer',type=Path,required=True); s.add_argument('--decision',type=Path,required=True); s.add_argument('--yes',action='store_true')
    r = sub.add_parser('recover'); r.add_argument('--layer',type=Path,required=True); r.add_argument('--yes',action='store_true')
    args = p.parse_args()
    try:
        if args.command == 'migrate':
            out = migrate(args.db,args.backup,apply=args.yes)
        elif args.command == 'recover':
            out = recover(args.db,args.layer,apply=args.yes)
        else:
            out = transition(args.db,args.layer,'cancelled' if args.command=='cancel' else 'active',yaml.safe_load(args.decision.read_text()),apply=args.yes)
        print(json.dumps(out,ensure_ascii=False)); return 0
    except (ValueError,RuntimeError,OSError,sqlite3.Error,yaml.YAMLError) as e:
        print('[BLOCKED] '+str(e),file=sys.stderr); return 3


if __name__ == '__main__':
    sys.exit(main())
