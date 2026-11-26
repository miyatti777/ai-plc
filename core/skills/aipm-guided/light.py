#!/usr/bin/env python3
"""AIPM ライトモード (addon_id aipm-light): the WBS and TODO sheets only, as one form of aipm-guided.

Two shapes share these two sheets (Sheets/todo.yaml and Sheets/wbs.yaml, the same rows as the registers contract):
- kind aipm_light: a Layer whose method is aipm-light. Its box record is Sheets/format_contract.yaml (the light contract).
- kind aipm_sheets: an aipm Layer without aipm.registers that got the two sheets (package.py add-sheets). Its box record
  is Sheets/light_sheets.yaml, beside (never instead of) the aipm package and its own format_contract.yaml.

The reference fields are not used in either shape (decision 7): wbs issue_ids / milestone_id, and I/H ids in todo source.
Nothing here calls an external command, writes outside the Layer, or overwrites an existing file.
"""
from pathlib import Path
import copy, re
import yaml

import package as _package   # addon_selector through the module, so a patched selector is seen (review P1-2)
from package import (load, sha, safe_path, intent, registers_contract_path, registers_layout,
                     SHEETS_ROOT, SHEETS_LAYOUT, LEGACY_ROOT, saved_contract)

LIGHT = 'aipm-light'
LIGHT_KIND, SHEETS_KIND = 'aipm_light', 'aipm_sheets'
LIGHT_VERSION = 1
LIGHT_RECORD = 'format_contract.yaml'     # kind aipm_light: the box record of an aipm-light Layer
SHEETS_RECORD = 'light_sheets.yaml'       # kind aipm_sheets: the record of the sheets added to an aipm Layer
SHEETS = ('todo', 'wbs')
UNUSED_REFS = {'wbs': ('issue_ids', 'milestone_id')}
SOURCE_ID = re.compile(r'[IH]\d+')
OS_METAFILES = {'.DS_Store'}


def method(layer):
    """(addon_id of the work method or None, selector result). A held selection raises ValueError."""
    layer = Path(layer).absolute()
    d = intent(layer)
    if d.get('work_style') is None and not d.get('addons'):
        return None, None
    result = _package.addon_selector().selected_addons(layer, read_roots=[str(layer)])
    if result['route'] == 'held':
        raise ValueError('addon selection held: ' + ', '.join(result['hold_reasons']) +
                         ('; ' + result['detail'] if result.get('detail') else '') + '; do not silently change intent')
    return result.get('method'), result


def is_light(layer):
    return method(layer)[0] == LIGHT


def _registers(version=None):
    q = registers_contract_path(version)
    rc = load(q)
    return q, rc


def expected_record(layer, kind, saved=None):
    """The light contract (kind aipm_light) or the sheets record (kind aipm_sheets) for this Layer. A saved record keeps
    its registers contract version (like an AIPM package keeps its own)."""
    d = intent(layer)
    version = saved.get('registers_contract_version') if isinstance(saved, dict) else None
    q, rc = _registers(version)
    rl = registers_layout({'layout': SHEETS_LAYOUT}, rc)
    return {'kind': kind, 'light_version': LIGHT_VERSION, 'scope_id': d.get('scope_id'),
            'layout': SHEETS_LAYOUT, 'package_root': SHEETS_ROOT,
            'registers_contract_version': rc['version'], 'registers_contract_sha256': sha(q),
            'files': {n: rl['files'][n]['path'] for n in SHEETS},
            'reference_fields_unused': {'wbs': list(UNUSED_REFS['wbs']), 'todo_source_ids': ['I', 'H']},
            'version': 'aipm-light.' + str(LIGHT_VERSION) + rc['contract_suffix']}


def record(layer):
    """(kind, record path, saved record) of the light sheets in this Layer, or (None, None, None)."""
    layer = Path(layer).absolute()
    root = safe_path(layer, SHEETS_ROOT)
    for name, kind in ((LIGHT_RECORD, LIGHT_KIND), (SHEETS_RECORD, SHEETS_KIND)):
        q = safe_path(root, name)
        if q.is_file():
            data = load(q)
            if isinstance(data, dict) and data.get('kind') == kind:
                return kind, q, data
    return None, None, None


def contract(layer):
    """(record, registers contract limited to todo/wbs with Sheets/ paths, {name: file}) of the light sheets."""
    layer = Path(layer).absolute()
    kind, _, saved = record(layer)
    if kind is None:
        raise ValueError('no AIPM light sheets in this Layer (run package.py init --light, or add-sheets)')
    q, rc = _registers(saved.get('registers_contract_version'))
    if sha(q) != saved.get('registers_contract_sha256'):
        raise ValueError('registers contract changed or hash mismatch')
    rc = registers_layout({'layout': SHEETS_LAYOUT}, rc)
    rc['files'] = {n: rc['files'][n] for n in SHEETS}
    root = safe_path(layer, SHEETS_ROOT)
    return saved, rc, {n: safe_path(root, rc['files'][n]['path']) for n in SHEETS}


def _collision(layer, kind):
    """Why the light sheets cannot be placed here (None when they can). Same stop as the AIPM init: nothing written."""
    root = safe_path(layer, SHEETS_ROOT)
    if layer.is_dir() and any(x.name != SHEETS_ROOT and x.name.casefold() == SHEETS_ROOT.casefold() for x in layer.iterdir()):
        return 'a folder named like ' + SHEETS_ROOT + '/ but in another case is in the Layer'
    if kind == LIGHT_KIND and safe_path(layer, LEGACY_ROOT).exists():
        return LEGACY_ROOT + '/ is already in the Layer (an earlier AIPM package)'
    if root.is_symlink():
        return SHEETS_ROOT + '/ is a symlink'
    if root.exists() and not root.is_dir():
        return SHEETS_ROOT + ' is a file, not a folder'
    return None


def _write_new(path, data):
    if path.exists() or path.is_symlink():
        raise ValueError('already exists (not overwritten): ' + str(path))
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def init_light(layer, *, apply=True):
    """package.py init for an aipm-light Layer: the light contract and the two sheets (empty lists), nothing else."""
    layer = Path(layer).absolute()
    if method(layer)[0] != LIGHT:
        raise ValueError('AIPM ライトモード (aipm-light) is not the method of this Layer')
    root = safe_path(layer, SHEETS_ROOT)
    kind, q, saved = record(layer)
    if kind == LIGHT_KIND:
        if saved != expected_record(layer, LIGHT_KIND, saved):
            raise ValueError('existing light contract differs; do not overwrite')
        return {'route': LIGHT, 'created': False, 'package': str(root), 'outputs': outputs(layer)}
    if kind is not None or saved_contract(layer).is_file():
        raise ValueError(SHEETS_ROOT + '/ already holds another box; do not overwrite (nothing written)')
    why = _collision(layer, LIGHT_KIND)
    if why is None and root.is_dir():
        other = [x.name for x in root.iterdir() if x.name not in OS_METAFILES]
        if other:
            why = SHEETS_ROOT + '/ is used for something else: ' + ', '.join(sorted(other)[:5])
    if why:
        raise ValueError(why + ' (nothing written)')
    c = expected_record(layer, LIGHT_KIND)
    plan = [LIGHT_RECORD] + [c['files'][n] for n in SHEETS]
    if not apply:
        return {'route': LIGHT, 'created': False, 'planned': [SHEETS_ROOT + '/' + p for p in plan]}
    root.mkdir(parents=True, exist_ok=True)
    _write_new(root / LIGHT_RECORD, c)
    for n in SHEETS:
        _write_new(safe_path(root, c['files'][n]), {n: []})
    return {'route': LIGHT, 'created': True, 'package': str(root), 'contract': c, 'outputs': outputs(layer),
            'note': 'AIPM ライトモードの箱（WBS と TODO のシートだけ）。19文書・issues・hypotheses・roadmap は作らない'}


def outputs(layer):
    """path/sha256 of the box record and the sheets that exist (for intent mode_init.outputs)."""
    layer = Path(layer).absolute()
    kind, q, saved = record(layer)
    if kind is None:
        return []
    rels = [q.name] + [saved['files'][n] for n in SHEETS]
    root = safe_path(layer, SHEETS_ROOT)
    return [{'path': SHEETS_ROOT + '/' + r, 'sha256': sha(root / r)} for r in rels if (root / r).is_file()]


def add_sheets(layer, *, apply=False):
    """Decision 6: give an aipm Layer without aipm.registers the two sheets (kind aipm_sheets). Never overwrites; the
    aipm package and its format_contract.yaml stay as they are. Dry run unless apply."""
    layer = Path(layer).absolute()
    m, _ = method(layer)
    if m != 'aipm':
        raise ValueError('add-sheets is for an aipm Layer (method is ' + str(m) + ')')
    a = intent(layer).get('aipm') or {}
    if not isinstance(a, dict):
        raise ValueError('aipm must be map')
    if a.get('registers') is True:
        return {'route': 'aipm', 'changed': False, 'reason': 'aipm.registers is selected; the registers already hold todo and wbs'}
    kind, q, saved = record(layer)
    if kind == SHEETS_KIND:
        return {'route': 'aipm', 'changed': False, 'reason': 'sheets already added', 'outputs': outputs(layer)}
    if kind is not None:
        raise ValueError('an AIPM light box is in ' + SHEETS_ROOT + '/ of an aipm Layer; check the method (nothing written)')
    why = _collision(layer, SHEETS_KIND)
    c = expected_record(layer, SHEETS_KIND)
    root = safe_path(layer, SHEETS_ROOT)
    taken = [p for p in [SHEETS_RECORD] + [c['files'][n] for n in SHEETS] if (root / p).exists() or (root / p).is_symlink()]
    if why is None and taken:
        why = SHEETS_ROOT + '/ already has ' + ', '.join(taken)
    if why:
        raise ValueError(why + ' (nothing written)')
    plan = [SHEETS_ROOT + '/' + p for p in [SHEETS_RECORD] + [c['files'][n] for n in SHEETS]]
    if not apply:
        return {'route': 'aipm', 'changed': False, 'planned': plan}
    root.mkdir(parents=True, exist_ok=True)
    _write_new(root / SHEETS_RECORD, c)
    for n in SHEETS:
        _write_new(safe_path(root, c['files'][n]), {n: []})
    return {'route': 'aipm', 'changed': True, 'written': plan, 'outputs': outputs(layer)}


def check(layer, err, warn=None):
    """Errors of the light sheets (E_REGISTERS for the rows, E_LIGHT for the light rules). Returns the wbs summary."""
    import validate_package as vp
    layer = Path(layer).absolute()
    kind, q, saved = record(layer)
    expected = expected_record(layer, kind, saved)
    if saved != expected:
        err('E_LIGHT', SHEETS_ROOT + '/' + q.name, 'light box record differs from the expected one (version, scope or files)')
        return None
    try:
        _, rc, files = contract(layer)
    except ValueError as ex:
        err('E_REGISTERS', 'registers_contract', str(ex))
        return None
    root = safe_path(layer, SHEETS_ROOT)

    def safe(rel):
        p = root / rel
        if Path(rel).is_absolute() or '..' in Path(rel).parts or p.is_symlink():
            err('E_BOUNDARY', rel, 'path not accepted')
            return None
        return p

    for n in SHEETS:
        vp.check_list(rc['files'][n], safe, err, warn, {})
    rows = {}
    for n in SHEETS:
        try:
            data = load(files[n]) if files[n].is_file() else None
        except Exception:
            data = None
        rows[n] = [r for r in (data or {}).get(n) or [] if isinstance(r, dict) and isinstance(r.get('id'), str)] \
            if isinstance(data, dict) else []
    wbs_ids = {r['id'] for r in rows['wbs']}
    summary = {'rows': len(rows['wbs']), 'by_status': {}}
    for n in SHEETS:
        spec = rc['files'][n]
        for r in rows[n]:
            rl = spec['path'] + '#' + r['id']
            extra = [k for k in r if k not in spec['required'] and k not in spec.get('optional', [])]
            if extra:
                err('E_REGISTERS', rl, 'unknown key: ' + ','.join(map(str, extra)))
            for k in UNUSED_REFS.get(n, ()):
                if r.get(k) not in (None, [], ''):
                    err('E_LIGHT', rl, k + ' is not used in AIPM ライトモード (no ' + ('issues' if k == 'issue_ids' else 'roadmap') + ' sheet)')
            if n == 'todo':
                src = r.get('source')
                for v in (src if isinstance(src, list) else [src] if src is not None else []):
                    if isinstance(v, str) and SOURCE_ID.fullmatch(v.strip()):
                        err('E_LIGHT', rl, 'source ' + v + ' is an issue/hypothesis id; write a meeting name or similar (no issues/hypotheses sheet)')
                ke, kw = vp.knot_problems(spec, r)
                for m_ in ke:
                    err('E_REGISTERS', rl, m_)
                for m_ in kw:
                    if warn is not None:
                        warn('W_REGISTERS', rl, m_)
                if r.get('wbs_id') not in (None, '') and r['wbs_id'] not in wbs_ids:
                    err('E_REGISTERS', rl, 'wbs_id points to unknown id ' + str(r['wbs_id']))
                if warn is not None and not r.get('wbs_id') and r.get('status') != 'cancelled':
                    warn('W_REGISTERS', rl, 'no WBS number (wbs_id is empty)')
            if n == 'wbs':
                summary['by_status'][str(r.get('status'))] = summary['by_status'].get(str(r.get('status')), 0) + 1
                for v in (r.get('depends') if isinstance(r.get('depends'), list) else [r.get('depends')] if r.get('depends') else []):
                    if v not in wbs_ids:
                        err('E_REGISTERS', rl, 'depends points to unknown id ' + str(v))
                    elif v == r['id']:
                        err('E_REGISTERS', rl, 'depends points to itself')
                acc = spec['acceptance']
                ev = r.get('evidence_refs')
                ev = ev if isinstance(ev, list) else ([ev] if ev else [])
                if r.get('status') in acc['needs_evidence'] and not ev:
                    err('E_REGISTERS', rl, str(r.get('status')) + ' needs evidence_refs')
                for v in ev:
                    try:
                        p = safe_path(layer, v) if isinstance(v, str) else None
                    except Exception:
                        p = None
                    if p is None or not p.exists():
                        err('E_REGISTERS', rl, 'evidence missing: ' + str(v))
    return summary


def validate(layer):
    """validate_package for an aipm-light Layer (kind aipm_light)."""
    errors, warnings = [], []
    summary = check(layer, lambda c, p, m: errors.append({'code': c, 'path': str(p), 'message': m}),
                    lambda c, p, m: warnings.append({'code': c, 'path': str(p), 'message': m}))
    return {'pass': not errors, 'route': LIGHT, 'scope_id': intent(layer).get('scope_id'), 'checked_documents': 0,
            'errors': errors, 'warnings': warnings, 'wbs_summary': summary,
            'limits': ['AIPM ライトモード: only Sheets/todo.yaml and Sheets/wbs.yaml are checked (no 19 documents)']}


def switch_ready(layer):
    """aipm-light -> aipm (decision 6): True when the intent now selects aipm with aipm.registers and Sheets/ holds the
    light box. package.init adopts the two sheets as part of the registers and adds the rest."""
    kind, q, saved = record(layer)
    if kind != LIGHT_KIND or method(layer)[0] != 'aipm':
        return False
    a = intent(layer).get('aipm') or {}
    return isinstance(a, dict) and a.get('registers') is True and a.get('layout', SHEETS_LAYOUT) == SHEETS_LAYOUT
