"""Portable task routing and evidence normalization; no network or settings writes."""
import argparse
import json
from pathlib import Path

MODELS = {
    'claude-code': {'fast': ('haiku', 'low'), 'standard': ('sonnet', 'medium'), 'deep': ('opus', 'low')},
    'codex': {'fast': ('gpt-6-luna', 'high'), 'standard': ('gpt-6.1-sol', 'medium'), 'deep': ('gpt-6-astra', 'low')},
}


def recommend(task, environment, available_models=None):
    if environment not in MODELS:
        raise ValueError('Unsupported environment')
    for key in ('complexity', 'ambiguity', 'impact'):
        if task.get(key, 'medium') not in ('low', 'medium', 'high'):
            raise ValueError('Invalid ' + key)
    if 'verifiable' in task and not isinstance(task['verifiable'], bool):
        raise ValueError('verifiable must be a boolean')
    attempts = task.get('failed_attempts', 0)
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 0:
        raise ValueError('Invalid failed_attempts')
    if attempts >= 2:
        return {'status': 'stop', 'reason': 'Two failed attempts; existing escalation gate takes precedence'}
    simple = all(task.get(k) == 'low' for k in ('complexity', 'ambiguity', 'impact')) and task.get('verifiable') is True
    difficult = task.get('complexity') == 'high' or task.get('ambiguity') == 'high' or attempts > 0
    role = 'deep' if task.get('impact') == 'high' or task.get('verifiable') is False else ('fast' if simple else 'standard')
    model, effort = MODELS[environment][role]
    override = task.get('model_override')
    if override is not None:
        if not isinstance(override, str) or not override.strip():
            raise ValueError('Invalid model_override')
        model = override
        # An explicit model has no inferred supported effort unless supplied.
        effort = task.get('effort_override')
    elif 'effort_override' in task:
        effort = task['effort_override']
    supported = {'claude-code': {'low', 'medium', 'high', 'xhigh', 'max'},
                 'codex': {'low', 'medium', 'high', 'xhigh', 'max', 'ultra'}}
    if effort is not None and effort not in supported[environment]:
        raise ValueError('Unsupported effort; check selected model before execution')
    if available_models is not None and model not in available_models:
        return {'status': 'unavailable', 'recommended_role': role, 'recommended_model': model,
                'reason': 'Selected model unavailable; no silent fallback'}
    advisor = difficult and role != 'deep'
    advisor_model, advisor_effort = MODELS[environment]['deep']
    if advisor and available_models is not None and advisor_model not in available_models:
        return {'status': 'unavailable', 'recommended_model': model, 'reason': 'Advisor unavailable; choose an explicit alternative'}
    return {'status': 'ready', 'environment': environment, 'recommended_role': role,
            'recommended_model': model, 'recommended_effort': effort,
            'reason': 'User model override' if override else ('High impact or human-only verification' if role == 'deep' else ('Clear, low-risk, mechanically verifiable task' if simple else 'Standard task with targeted advice' if advisor else 'Standard task')),
            'advisor': {'required': advisor, 'model': advisor_model if advisor else None,
                        'effort': advisor_effort if advisor else None, 'kind': 'separate-model-consultation'},
            'actual_model': None, 'actual_model_evidence': None,
            'independent_review': '04-operation Phase 5.5 and BT checks remain separate'}


def normalize(record):
    """Read execution metadata, never a model's self-identification or requested config."""
    raw = record.get('stdout', '')
    result = {'actual_model': None, 'actual_models': [], 'actual_model_evidence': None,
              'actual_model_status': 'unverified', 'observed_effort': None,
              'usage': None, 'list_price_estimate_usd': None, 'answer': '',
              'execution_succeeded': False, 'tool_events': []}
    if record['environment'] == 'claude-code':
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return result
        if not isinstance(data, dict):
            return result
        usage = data.get('modelUsage')
        usage = usage if isinstance(usage, dict) else {}
        used = [k for k, v in usage.items() if isinstance(v, dict)
                and isinstance(v.get('inputTokens', 0), (int, float))
                and isinstance(v.get('outputTokens', 0), (int, float))
                and v.get('inputTokens', 0) + v.get('outputTokens', 0) > 0]
        result.update(answer=data.get('result', ''), usage=data.get('usage'),
                      list_price_estimate_usd=data.get('total_cost_usd'), actual_models=used,
                      execution_succeeded=record.get('exit_code') == 0 and not data.get('is_error', True))
        if len(used) == 1:
            result.update(actual_model=used[0], actual_model_evidence='CLI result.modelUsage with consumed tokens', actual_model_status='verified_runtime_usage')
    elif record['environment'] == 'codex':
        events=[]
        for line in raw.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        for e in events:
            if not isinstance(e, dict):
                continue
            if e.get('type') == 'turn.completed':
                result['usage'] = e.get('usage')
                result['execution_succeeded'] = record.get('exit_code') == 0
            if e.get('type') in ('turn.failed', 'error'):
                result['execution_succeeded'] = False
            item=e.get('item', {})
            if not isinstance(item, dict):
                continue
            if e.get('type') == 'item.completed' and item.get('type') == 'agent_message':
                result['answer'] += item.get('text', '')
            if item and item.get('type') not in ('agent_message', 'reasoning'):
                result['tool_events'].append(item.get('type'))
        # Current CLI event protocol has no response model ID; requested model is not proof.
    return result


def parse_answer(text):
    text=text.strip()
    if text.startswith('```') and text.endswith('```'):
        text='\n'.join(text.splitlines()[1:-1])
    return json.loads(text)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    inputs=p.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--task', type=Path, help='Task attributes as a JSON file')
    inputs.add_argument('--record', type=Path, help='Saved CLI record: environment, exit_code, stdout and request fields')
    p.add_argument('--environment', choices=list(MODELS))
    a=p.parse_args()
    try:
        data=json.loads((a.task or a.record).read_text())
        if not isinstance(data, dict):
            raise ValueError('Input must be a JSON object')
        if a.task:
            if not a.environment:
                raise ValueError('--environment is required with --task')
            output=recommend(data, a.environment)
        else:
            environment=data.get('environment')
            if environment not in MODELS:
                raise ValueError('Record must specify a supported environment')
            if a.environment and environment != a.environment:
                raise ValueError('Environment does not match record')
            output={k:data.get(k) for k in ('environment', 'requested_model', 'requested_effort', 'duration_seconds')}
            output.update(normalize(data))
    except (OSError, ValueError, TypeError) as error:
        p.error(str(error))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
