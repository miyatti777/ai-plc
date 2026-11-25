#!/usr/bin/env python3
"""Read-only cross-project analysis. Python 3 standard library only."""
import argparse
import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path
from fractions import Fraction


def require(ok, msg):
    if not ok:
        raise ValueError(msg)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def load(path):
    raw = Path(path).read_bytes()
    def bad(x):
        raise ValueError('non-finite JSON: ' + x)
    def pairs(items):
        obj = {}
        for k, v in items:
            require(k not in obj, 'duplicate JSON key: ' + k)
            obj[k] = v
        return obj
    return json.loads(raw, parse_constant=bad, object_pairs_hook=pairs), digest(raw)


def day(value, where, nullable=True):
    if value is None and nullable:
        return None
    require(isinstance(value, str), where + ': date required')
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise ValueError(where + ': invalid date')
    require(result.isoformat() == value, where + ': use YYYY-MM-DD')
    return result


def number(value, where):
    require(value is None or (type(value) in (int, float) and math.isfinite(value) and value >= 0), where + ': nonnegative finite number/null required')


def text(value, where):
    require(isinstance(value, str) and bool(value.strip()), where + ': nonempty string required')


def index(rows, where):
    require(isinstance(rows, list), where + ': array required')
    result = {}
    for i, row in enumerate(rows):
        require(isinstance(row, dict), where + ': object required')
        text(row.get('id'), where + '/id')
        require(row['id'] not in result, where + ': duplicate id ' + row['id'])
        result[row['id']] = row
    return result


def source_ok(obj):
    src = obj.get('source')
    return isinstance(src, dict) and all(isinstance(src.get(k), str) and src[k].strip() for k in ('path', 'locator', 'revision'))


def analyze(data, sha):
    require(isinstance(data, dict) and data.get('schema_version') == 'portfolio-1', 'schema_version must be portfolio-1')
    text(data.get('portfolio_id'), 'portfolio_id')
    authority = data.get('decision_authority')
    require(authority is None or isinstance(authority, dict), 'decision_authority object/null required')
    if authority is not None:
        require(all(authority.get(k) is None or isinstance(authority.get(k), str) for k in ('role', 'scope', 'unconfirmed')), 'authority fields string/null required')
    asof = day(data.get('as_of'), 'as_of', False)
    threshold = data.get('staleness_days')
    require(threshold is None or (type(threshold) is int and threshold >= 0), 'staleness_days invalid')
    projects = index(data.get('projects'), 'projects')
    selected = data.get('selected_projects')
    require(isinstance(selected, list) and len(selected) > 0 and all(isinstance(x, str) for x in selected), 'selected_projects required')
    require(len(selected) == len(set(selected)), 'duplicate selected_projects')
    require(set(selected) <= projects.keys(), 'unknown selected project')
    resources = index(data.get('resources', []), 'resources')
    dependencies = index(data.get('dependencies', []), 'dependencies')
    allocations = index(data.get('allocations', []), 'allocations')
    warnings = []
    def warn(code, pointer, detail):
        warnings.append({'code': code, 'pointer': pointer, 'detail': detail})
    def freshness(obj, pointer):
        observed = day(obj.get('observed_at'), pointer + '/observed_at')
        age = (asof - observed).days if observed else None
        state = 'unknown' if age is None else 'future' if age < 0 else 'stale' if threshold is not None and age > threshold else 'age_only' if threshold is None else 'current'
        if state in ('unknown', 'future', 'stale'):
            warn('freshness_' + state, pointer, '情報時点を確認')
        if not source_ok(obj):
            warn('source_missing', pointer, 'path/locator/revisionの根拠不足')
        return {'observed_at': obj.get('observed_at'), 'age_days': age, 'state': state}
    def evidence(obj, pointer):
        return {'pointer': pointer, 'source': obj.get('source'), 'input_sha256': sha}
    if authority is not None and not source_ok(authority):
        warn('authority_source_missing', '/decision_authority', '判断権限の出典不足。申告範囲を確認済み権限と扱わない')
    itemmap, pmeta, pptr = {}, {}, {}
    project_output = []
    common = {}
    for i, (pid, p) in enumerate(projects.items()):
        ptr = '/projects/' + str(i)
        pptr[pid] = ptr
        items = index(p.get('items', []), ptr + '/items')
        issues = index(p.get('issues', []), ptr + '/issues')
        issues_status = p.get('issues_status', 'reported' if issues else 'not_provided')
        require(issues_status in ('reported', 'not_provided', 'confirmed_none'), ptr + ': invalid issues_status')
        require(not issues or issues_status == 'reported', ptr + ': issues_status contradicts issues')
        if pid in selected and issues_status == 'not_provided':
            warn('issues_not_provided', ptr, '課題の記載なし。課題がないと確認したわけではない')
        for j, (iid, item) in enumerate(items.items()):
            ip = ptr + '/items/' + str(j)
            day(item.get('forecast'), ip + '/forecast')
            require(type(item.get('confirmed_done', False)) is bool, ip + ': confirmed_done boolean')
            itemmap[(pid, iid)] = (item, ip)
            if pid in selected and not source_ok(item):
                warn('source_missing', ip, '項目の根拠不足')
        for j, issue in enumerate(issues.values()):
            require('project_id' not in issue or issue['project_id'] == pid, ptr + ': issue project_id contradicts parent')
            require(issue.get('kind') in ('issue', 'risk'), ptr + ': issue kind invalid')
            key = issue.get('common_key')
            require(key is None or isinstance(key, str) and bool(key.strip()), 'common_key string/null')
            if pid in selected and key:
                common.setdefault(key, []).append({**issue, 'project_id': pid, 'evidence': evidence(issue, ptr + '/issues/' + str(j))})
        if pid in selected:
            meta = freshness(p, ptr)
            pmeta[pid] = meta
            if not p.get('owner'):
                warn('owner_missing', ptr, '案件責任者が不明')
            project_output.append({'project_id': pid, 'name': p.get('name'), 'owner': p.get('owner'), 'freshness': meta, 'items': p.get('items', []), 'issues': p.get('issues', []), 'issues_status': issues_status, 'evidence': evidence(p, ptr)})
    depout, outside, graph = [], [], {}
    for i, dep in enumerate(dependencies.values()):
        ptr = '/dependencies/' + str(i)
        endpoints = []
        for field in ('from', 'to'):
            ref = dep.get(field)
            require(isinstance(ref, dict), ptr + ': endpoint object')
            key = (ref.get('project_id'), ref.get('item_id'))
            require(key in itemmap, ptr + ': nonexistent project/item reference')
            endpoints.append(key)
        a, b = endpoints
        needed = day(dep.get('needed_by'), ptr + '/needed_by')
        if not ({a[0], b[0]} <= set(selected)):
            if a[0] in selected or b[0] in selected:
                outside.append({'id': dep['id'], 'from': dep['from'], 'to': dep['to'], 'evidence': evidence(dep, ptr)})
                warn('outside_dependency', ptr, '選択範囲外の依存。全体状況は未判定')
            continue
        item, ip = itemmap[a]
        forecast = day(item.get('forecast'), ip + '/forecast')
        proof = source_ok(dep) and source_ok(item) and source_ok(projects[a[0]]) and source_ok(projects[b[0]])
        provisional = not proof or any(pmeta[p]['state'] in ('unknown', 'future', 'stale') for p in (a[0], b[0]))
        state = 'confirmed_done' if item.get('confirmed_done') and proof and not provisional else 'unknown' if not forecast or not needed else 'late' if forecast > needed else 'within_needed_date'
        if state == 'unknown':
            warn('dependency_unknown', ptr, '完了根拠または日付不足')
        depout.append({'id': dep['id'], 'from': dep['from'], 'to': dep['to'], 'state': state, 'provisional': provisional, 'late_days': max(0, (forecast-needed).days) if forecast and needed and state != 'confirmed_done' else None, 'forecast': item.get('forecast'), 'needed_by': dep.get('needed_by'), 'evidence': [evidence(dep, ptr), evidence(item, ip)]})
        graph.setdefault(a, []).append((b, dep['id']))
    # Per-edge reachability avoids recursion and handles shared subgraphs.
    cycles = []
    for a, edges in graph.items():
        for b, eid in edges:
            todo, seen = [b], set()
            while todo:
                node = todo.pop()
                if node == a:
                    cycles.append(eid)
                    break
                if node in seen:
                    continue
                seen.add(node)
                todo.extend(x for x, _ in graph.get(node, []))
    for dep in depout:
        todo = [(dep['to']['project_id'], dep['to']['item_id'])]
        seen = set()
        while todo:
            node = todo.pop()
            if node in seen:
                continue
            seen.add(node)
            todo.extend(x for x, _ in graph.get(node, []))
        dep['impact_confirmation_targets'] = [{'project_id': p, 'item_id': i} for p, i in sorted(seen)]
    rout = []
    for ri, (rid, res) in enumerate(resources.items()):
        ptr = '/resources/' + str(ri)
        number(res.get('capacity'), ptr + '/capacity')
        unit = res.get('unit')
        require(unit is None or isinstance(unit, str), ptr + ': unit string/null')
        meta = freshness(res, ptr)
        relevant, excluded, unknown = [], [], []
        for ai, alloc in enumerate(allocations.values()):
            ap = '/allocations/' + str(ai)
            require(alloc.get('resource_id') in resources, ap + ': unknown resource')
            require(alloc.get('project_id') in projects, ap + ': unknown project')
            number(alloc.get('load'), ap + '/load')
            start, end = day(alloc.get('start'), ap + '/start'), day(alloc.get('end'), ap + '/end')
            require(not (start and end) or start <= end, ap + ': reversed period')
            if alloc['resource_id'] != rid:
                continue
            entry = {**alloc, 'evidence': evidence(alloc, ap)}
            if alloc['project_id'] not in selected:
                excluded.append(entry)
                warn('outside_allocation', ap, '選択外負荷あり。資源全体の空きを断定できない')
            elif not start or not end or alloc.get('load') is None or not unit or alloc.get('unit') != unit or res.get('capacity') is None:
                unknown.append(entry)
                reasons = []
                if not start: reasons.append('開始日不明')
                if not end: reasons.append('終了日不明')
                if alloc.get('load') is None: reasons.append('負荷不明')
                if res.get('capacity') is None: reasons.append('資源上限不明')
                if not unit: reasons.append('資源単位不明')
                elif alloc.get('unit') != unit: reasons.append('割当と資源の単位不一致')
                entry['unknown_reasons'] = reasons
                warn('allocation_unknown', ap, '・'.join(reasons))
            else:
                relevant.append((start, end, entry))
        boundaries = sorted({d for start, end, _ in relevant for d in (start, end + timedelta(days=1))})
        intervals = []
        for start, nxt in zip(boundaries, boundaries[1:]):
            active = [a for s, e, a in relevant if s <= start <= e]
            if not active:
                continue
            total_exact = sum((Fraction(str(a['load'])) for a in active), Fraction(0))
            total = float(total_exact)
            over_capacity = total_exact > Fraction(str(res['capacity']))
            active_projects = sorted({a['project_id'] for a in active})
            provisional = meta['state'] in ('unknown', 'future', 'stale') or not source_ok(res) or any(pmeta[p]['state'] in ('unknown', 'future', 'stale') or not source_ok(projects[p]) for p in active_projects) or any(not source_ok(a) for a in active)
            intervals.append({'start': start.isoformat(), 'end': (nxt-timedelta(days=1)).isoformat(), 'load': total, 'capacity': res.get('capacity'), 'unit': unit, 'project_ids': active_projects, 'allocation_ids': [a['id'] for a in active], 'cross_project_conflict': len(active_projects) >= 2 and over_capacity, 'over_capacity': over_capacity, 'provisional': provisional, 'evidence': [a['evidence'] for a in active]})
        rout.append({'resource_id': rid, 'freshness': meta, 'evidence': evidence(res, ptr), 'intervals': intervals, 'unknown_allocations': unknown, 'outside_allocations': excluded, 'coverage': 'selected_projects_only; unknown/outside loads excluded from numeric sum'})
    # Validate references even when resources is empty.
    for alloc in allocations.values():
        require(alloc.get('resource_id') in resources and alloc.get('project_id') in projects, 'allocation reference invalid')
    return {'schema_version': 'analysis-1', 'portfolio_id': data['portfolio_id'], 'as_of': data['as_of'], 'input_sha256': sha, 'selected_projects': selected, 'selected_count': len(selected), 'decision_authority': data.get('decision_authority'), 'projects': project_output, 'dependencies': depout, 'outside_dependencies': outside, 'cycle_dependency_ids': sorted(set(cycles)), 'resources': rout, 'common_issues': [{'common_key': k, 'members': v} for k, v in sorted(common.items()) if len({x['project_id'] for x in v}) > 1], 'warnings': warnings, 'limits': ['申告資料の分析。正本の事実性・権限は人が確認', '資源上限は期間中一定、休日や役割代替は未考慮', '進捗率の平均・自動順位付け・自動変更は行わない']}


def report(result):
    def display(value):
        return '未確認' if value is None else str(value)
    fresh = {'unknown':'時点不明', 'future':'基準日より未来・要確認', 'stale':'古い情報・要確認', 'age_only':'経過日数のみ確認', 'current':'指定期間内の情報'}
    states = {'confirmed_done':'資料上の完了確認あり', 'unknown':'判定不能', 'late':'必要日より後の見通し', 'within_needed_date':'申告上は必要日以内'}
    issue_states = {'reported':'記載あり', 'not_provided':'記載なし・有無は未確認', 'confirmed_none':'資料上で課題なしを確認'}
    rows = ['# 複数案件PMOレポート', '', f"基準日: {result['as_of']} / 対象: {result['selected_count']}案件", '', '## 案件状況']
    for p in result['projects']:
        rows.append(f"- {p['project_id']} {display(p['name'])}：責任者 {display(p['owner'])}、情報時点 {display(p['freshness']['observed_at'])}（{fresh[p['freshness']['state']]}）。課題: {issue_states[p['issues_status']]}。根拠 {p['evidence']['pointer']}")
        for item in p['items']:
            rows.append(f"  - {item['id']} {display(item.get('title'))}：元状態 {display(item.get('status'))}、完成見通し {display(item.get('forecast'))}")
    rows.extend(['', '## 案件間依存'])
    for d in result['dependencies']:
        origin = d['from']['project_id'] + '/' + d['from']['item_id']
        target = d['to']['project_id'] + '/' + d['to']['item_id']
        caution = '最新資料・根拠の確認が必要な暫定判定' if d['provisional'] else '申告資料に基づく判定'
        rows.append(f"- {d['id']} {origin} → {target}：{states[d['state']]}。必要日 {display(d['needed_by'])}、見通し {display(d['forecast'])}、必要日からの超過日数 {display(d['late_days'])}。{caution}")
    if result['cycle_dependency_ids']:
        rows.append('循環の確認対象: ' + ', '.join(result['cycle_dependency_ids']))
    for d in result['outside_dependencies']:
        rows.append(f"- {d['id']}：対象外案件につながる依存あり。範囲を確認")
    rows.extend(['', '## 共有資源'])
    for r in result['resources']:
        for x in r['intervals']:
            condition = '複数案件で上限超過' if x['cross_project_conflict'] else '上限超過' if x['over_capacity'] else '計算対象の負荷は申告上限以内'
            caution = '／古い情報・根拠等を確認する暫定値' if x['provisional'] else ''
            rows.append(f"- {r['resource_id']} {x['start']}〜{x['end']}：{x['load']}/{x['capacity']} {x['unit']}、{condition}{caution}。案件={','.join(x['project_ids'])}")
        for alloc in r['unknown_allocations']:
            rows.append(f"- {r['resource_id']} / {alloc['id']}：{'・'.join(alloc['unknown_reasons'])}のため判定不能")
        if r['unknown_allocations'] or r['outside_allocations']:
            rows.append(f"- {r['resource_id']}：未判定/対象外の負荷あり。空き容量を断定しない。")
    rows.extend(['', '## 共通課題・リスク'])
    for c in result['common_issues']:
        rows.append('- ' + c['common_key'] + ': ' + ', '.join(x['project_id'] + '/' + x['id'] + '（' + ('課題' if x['kind']=='issue' else 'リスク') + '・' + display(x.get('status')) + '）' for x in c['members']))
    rows.extend(['', '## 判断権限'])
    authority = result.get('decision_authority')
    if isinstance(authority, dict):
        rows.append('判断者: ' + display(authority.get('role')) + '／資料上の申告範囲: ' + display(authority.get('scope')) + '／未確認: ' + display(authority.get('unconfirmed')))
        if source_ok(authority):
            src = authority['source']
            rows.append('権限の出典: ' + src['path'] + ' / ' + src['locator'] + ' / ' + src['revision'] + '（個別変更の承認は別途確認）')
        else:
            rows.append('権限の根拠は未確認。確認済みとして扱わない。')
    else:
        rows.append('判断者と権限範囲は未確認。AIが権限を推測しない。')
    rows.extend(['', '## 確認事項'])
    rows.extend(f"- {w['pointer']}：{w['detail']}" for w in result['warnings'])
    rows.extend(['', '## 次の判断準備', 'AIはanalysis.jsonの根拠を読み、decision_brief.mdに選択肢・影響・不明・判断者を整理する。現時点で優先順位や変更は未決定。', '', '詳細根拠: analysis.json / 入力SHA256: ' + result['input_sha256']])
    return '\n'.join(rows) + '\n'


def write_bundle(out, files, protected=()):
    out = Path(out).resolve()
    for name in files:
        dest = (out / name).resolve()
        require(dest not in {Path(p).resolve() for p in protected}, 'output would overwrite input/source')
        require(not dest.exists() or dest.read_bytes() == files[name], 'output differs; use a new run directory: ' + str(dest))
    out.mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        dest = out / name
        if not dest.exists():
            with dest.open('xb') as stream:
                stream.write(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        data, sha = load(args.input)
        result = analyze(data, sha)
        protected = [args.input]
        def visit(x):
            if isinstance(x, dict):
                src = x.get('source')
                if isinstance(src, dict) and isinstance(src.get('path'), str):
                    path = Path(src['path'])
                    protected.append(path if path.is_absolute() else args.input.parent / path)
                for v in x.values():
                    visit(v)
            elif isinstance(x, list):
                for v in x:
                    visit(v)
        visit(data)
        write_bundle(args.output, {'analysis.json': encode(result), 'portfolio_report.md': report(result).encode()}, protected)
        print(json.dumps({'output': str(args.output), 'selected_count': result['selected_count'], 'warnings': len(result['warnings']), 'input_sha256': sha}, ensure_ascii=False))
    except (ValueError, OSError, TypeError, KeyError, OverflowError) as exc:
        parser.exit(2, 'Input/output error: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
