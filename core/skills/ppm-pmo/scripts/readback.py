#!/usr/bin/env python3
"""Verify explicitly selected JSON masters; never apply changes."""
import argparse
from pathlib import Path
from portfolio import require, text, load, digest, encode, write_bundle


def json_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    return a == b


def request_hash(request):
    return digest(encode({k: v for k, v in request.items() if k not in ('confirmation', 'receipt')}))


def pointer_get(obj, pointer):
    require(isinstance(pointer, str) and (pointer == '' or pointer.startswith('/')), 'invalid JSON pointer')
    if pointer == '':
        return obj
    for part in pointer[1:].split('/'):
        # RFC6901 escapes only; reject malformed escape strings.
        i = 0
        while i < len(part):
            if part[i] == '~':
                require(i + 1 < len(part) and part[i + 1] in '01', 'invalid pointer escape')
                i += 2
            else:
                i += 1
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(obj, list):
            require(part.isdigit() and (part == '0' or not part.startswith('0')), 'invalid array index')
            obj = obj[int(part)]
        else:
            require(isinstance(obj, dict), 'pointer traverses scalar')
            obj = obj[part]
    return obj


def verify(data, base):
    require(isinstance(data, dict) and data.get('schema_version') == 'handoff-1', 'schema_version must be handoff-1')
    for k in ('portfolio_id', 'decision_id'):
        text(data.get(k), k)
    requests = data.get('requests')
    require(isinstance(requests, list) and bool(requests), 'requests required')
    seen, results, protected = {}, [], []
    for req in requests:
        require(isinstance(req, dict), 'request object required')
        for k in ('request_id', 'project_id', 'revision', 'target_path', 'before_sha256'):
            text(req.get(k), k)
        require(req.get('decision_id') == data['decision_id'] and req.get('portfolio_id') == data['portfolio_id'], 'request decision binding mismatch')
        require(not json_equal(req.get('expected_before'), req.get('expected_after')) and 'expected_before' in req and 'expected_after' in req, 'distinct before/after required')
        text(req.get('pointer'), 'pointer')
        rh = request_hash(req)
        key = (req['project_id'], req['request_id'], req['revision'])
        require(key not in seen, 'duplicate request identity; submit one content per revision')
        seen[key] = rh
        path = Path(req['target_path'])
        path = (base / path).resolve() if not path.is_absolute() else path.resolve()
        protected.append(path)
        row = {'project_id': req['project_id'], 'request_id': req['request_id'], 'revision': req['revision'], 'request_sha256': rh, 'target_path': str(path), 'pointer': req['pointer'], 'state': 'needs_review', 'reason': ''}
        confirmation, receipt = req.get('confirmation'), req.get('receipt')
        if not isinstance(confirmation, dict) or confirmation.get('request_sha256') != rh or not all(confirmation.get(k) for k in ('actor', 'authority', 'at')):
            row['reason'] = '対象内容版に結び付いた確認者/権限/日時が不足。人の明示確認が必要'
            results.append(row)
            continue
        try:
            master, actual_sha = load(path)
            actual = pointer_get(master, req['pointer'])
            row['actual_sha256'] = actual_sha
            row['actual_value'] = actual
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            row.update(state='evidence_missing', reason='正本/項目を取得できない: ' + str(exc))
            results.append(row)
            continue
        if json_equal(actual, req['expected_before']):
            row.update(state='unapplied' if actual_sha == req['before_sha256'] else 'conflict', reason='期待変更前の値。元版一致なら未反映、版違いなら再確認')
        elif not json_equal(actual, req['expected_after']):
            row.update(state='conflict', reason='期待する変更前/後の値と異なる')
        elif not isinstance(receipt, dict) or not all(receipt.get(k) for k in ('actor', 'at')):
            row.update(state='evidence_missing', reason='期待値は存在するが案件別実行記録が不足')
        elif receipt.get('request_sha256') != rh or receipt.get('after_sha256') != actual_sha:
            row.update(state='conflict', reason='実行記録と要求内容版/現在正本hashが一致しない')
        else:
            row.update(state='verified', reason='確認内容版、案件別実行記録、現在JSON正本の期待値が一致')
        results.append(row)
    count = sum(r['state'] == 'verified' for r in results)
    overall = 'verified' if count == len(results) else 'partial' if count else 'unapplied' if all(r['state'] == 'unapplied' for r in results) else 'needs_review'
    return {'schema_version': 'readback-1', 'portfolio_id': data['portfolio_id'], 'decision_id': data['decision_id'], 'state': overall, 'verified_count': count, 'request_count': len(results), 'requests': results, 'limits': '確認者/権限の実在性は人が確認。これは変更要求の読戻しであり案件の作業完了ではない。'}, protected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        data, sha = load(args.input)
        result, protected = verify(data, args.input.parent)
        result['input_sha256'] = sha
        write_bundle(args.output, {'readback.json': encode(result)}, [args.input, *protected])
        print(result['state'] + ': ' + str(result['verified_count']) + '/' + str(result['request_count']))
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(2, 'Input/output error: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
