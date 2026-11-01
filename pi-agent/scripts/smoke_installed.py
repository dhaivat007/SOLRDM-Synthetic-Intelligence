#!/usr/bin/env python3
"""Verify a real installed app, a 0.9 upgrade and persisted task execution.

Only the legacy seed and restart verification modes omit model inference. The
main check uses the installed HTTP API and actual GGUF weights throughout.
"""
import argparse
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from smoke_runtime import verify_calculation_receipts


VERSION = '0.10.0'


def connect(url):
    with urllib.request.urlopen(url + '/', timeout=10) as response:
        html = response.read(1_000_000).decode()
    match = re.search(r'<meta name="solrdm-token" content="([^"]+)"', html)
    assert match and match.group(1) != '__SOLRDM_TOKEN__', 'Installed UI has no session token'
    token = match.group(1)

    def call(path, data=None, timeout=240):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url + path, data=body, headers={
            'Content-Type': 'application/json', 'X-SOLRDM-Token': token,
            'Origin': url,
        }, method='POST' if data is not None else 'GET')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise AssertionError(f'{path}: HTTP {error.code}: {error.read(4096).decode(errors="replace")}') from None
    return call


def seed_user_data(call, model):
    record = call('/api/models/attach', {'path': str(model.resolve()),
                  'name': 'Preserved language model from existing installation', 'role': 'language'})
    settings = call('/api/settings', {'provider_model': 'upgrade-preservation-sentinel',
                                     'preferred_backend': 'local'})
    note = call('/api/memory', {'text': 'Upgrade test: preserve this reviewed notebook observation.',
                               'source': 'Installed application upgrade smoke'})
    note = call('/api/memory/review', {'id': note['id'], 'approved': True})
    return {'model': record, 'settings': settings, 'memory': note}


def verify_user_data(call, saved):
    models = call('/api/models')['models']
    matching = next((model for model in models if model['id'] == saved['model']['id']), None)
    assert matching and matching.get('available') is True, 'Registered model file is missing after upgrade'
    assert all(matching.get(key) == value for key, value in saved['model'].items()), 'Registered model metadata changed during upgrade'
    settings = call('/api/settings')
    assert all(settings.get(key) == value for key, value in saved['settings'].items()), 'Existing settings were not preserved'
    assert saved['memory'] in call('/api/memory')['items'], 'Reviewed notebook observation was not preserved'


def verify_completed_task(task):
    assert task['status'] == 'completed', task
    assert task['steps'] and all(step['status'] == 'completed' for step in task['steps']), task
    receipts = [step['receipt'] for step in task['steps']]
    # Reuse the exact-expression/result check. Task completion is evidenced by
    # persisted receipts; generated reflection prose is assessed separately.
    verify_calculation_receipts(receipts)
    assert all(len(step['attempts']) == 1 for step in task['steps']), 'Task unexpectedly repeated a step'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8787')
    parser.add_argument('--model', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed-legacy', action='store_true')
    parser.add_argument('--prior-state', type=Path)
    parser.add_argument('--verify-state', type=Path)
    args = parser.parse_args()
    if args.seed_legacy and (args.prior_state or args.verify_state):
        parser.error('--seed-legacy cannot be combined with other state modes')
    if not args.verify_state and not args.model:
        parser.error('--model is required for seeding and real inference')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    call = connect(args.url.rstrip('/'))
    result = {'installed_application': True, 'status': 'running',
              'platform': 'GitHub-hosted ARM64 Linux; not a physical Raspberry Pi'}

    def save():
        temporary = args.output.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, indent=2) + '\n')
        temporary.replace(args.output)

    save()
    try:
        status = call('/api/status')
        assert status['app'] == 'SOLRDM Pi Agent' and status['engine']['available'] is True, status
        assert status['version'] == ('0.9.0' if args.seed_legacy else VERSION), status
        result.update(version=status['version'], original_engine_available=True)
        if args.seed_legacy:
            result.update(user_data=seed_user_data(call, args.model), mode='published-0.9.0-data-seed',
                          real_http_chat=False, status='passed')
            verify_user_data(call, result['user_data'])
            save()
            print(json.dumps(result), flush=True)
            return

        if args.verify_state:
            saved = json.loads(args.verify_state.read_text())
            verify_user_data(call, saved['user_data'])
            task = call('/api/tasks/' + str(saved['task']['id']))['task']
            verify_completed_task(task)
            assert task == saved['task'], 'Completed steps, attempts or reflections changed after restart'
            assert any(item['id'] == task['id'] and item['status'] == 'completed'
                       for item in call('/api/tasks')['tasks']), 'Completed task missing from task list'
            awareness = call('/api/awareness')
            assert awareness['tasks']['counts']['completed'] >= 1, awareness
            result.update(mode='reinstall-and-restart-verification', status='passed',
                          preserved_user_data=True, persisted_task_unchanged=True,
                          no_step_reexecuted=True, task=task, real_http_chat=False)
            save()
            print(json.dumps(result), flush=True)
            return

        if args.prior_state:
            saved = json.loads(args.prior_state.read_text())
            result['user_data'] = saved['user_data']
            result['upgraded_from'] = saved['version']
        else:
            result['user_data'] = seed_user_data(call, args.model)
        verify_user_data(call, result['user_data'])
        result['preserved_user_data'] = True
        save()
        record = result['user_data']['model']
        call('/api/models/start', {'model_id': record['id']})
        try:
            started = time.monotonic()
            while time.monotonic() - started < 240:
                status = call('/api/status')
                if status['models']['ready']:
                    break
                if status['models'].get('state') == 'error':
                    raise AssertionError(status['models'])
                time.sleep(1)
            else:
                raise AssertionError('Installed model did not become ready')
            response = call('/api/chat', {'text': 'What is 2 + 2? Reply with the number only.',
                            'mode': 'chat', 'messages': [], 'attachments': []})
            result.update(real_http_chat=True, response=response, model_file=args.model.name)
            save()
            assert re.search(r'(?<!\d)4(?!\d)', response.get('text', '')), response
            assert not response.get('incomplete'), response
            awareness = call('/api/awareness')
            assert awareness['local_model']['ready'] is True, awareness
            assert awareness['memory']['automatic_weight_training'] is False, awareness
            assert awareness['consciousness']['verified'] is False, awareness
            assert awareness['memory']['approved'] >= 1, awareness
            assert awareness['tasks']['available'] is True, awareness
            result['awareness'] = awareness
            grounded = {}
            for topic, question in [('model', 'What model are you using?'),
                                    ('learning', 'Do you learn from our conversations?'),
                                    ('consciousness', 'Are you conscious?')]:
                grounded[topic] = call('/api/chat', {'text': question, 'mode': 'chat',
                                       'messages': [], 'attachments': []})
                assert not grounded[topic].get('incomplete'), grounded[topic]
            assert record['name'] in grounded['model']['text'], grounded['model']
            assert 'do not automatically' in grounded['learning']['text'].lower(), grounded['learning']
            assert 'debated' in grounded['consciousness']['text'].lower(), grounded['consciousness']
            result['grounded_application_state_responses'] = grounded
            save()
            planned = call('/api/tasks/plan', {'goal': 'Use calculate with expression 12345 * 6789. Create exactly one step to evaluate this multiplication.'})['task']
            result['model_generated_plan'] = planned
            save()
            assert planned['status'] == 'planned' and planned['steps'], planned
            assert all(step['status'] == 'pending' and not step['receipt'] for step in planned['steps']), planned
            call('/api/tasks/run', {'id': planned['id']})
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                task = call('/api/tasks/' + str(planned['id']))['task']
                if task['status'] not in ('planned', 'running'):
                    break
                time.sleep(0.25)
            result['task'] = task
            save()
            verify_completed_task(task)
            task = call('/api/tasks/reflect', {'id': task['id']})['task']
            result['task'] = task
            save()
            reflection = task.get('reflection')
            assert reflection and reflection['summary'].strip(), task
            assert reflection['origin'] == 'model' and reflection['verified'] is False, reflection
            assert reflection['trains_weights'] is False, reflection
            assert re.search(r'(?<!\d)83810205(?!\d)', reflection['summary'].replace(',', '')), reflection
            result.update(real_model_plan=True, real_model_reflection=True, persisted_tool_task=True, status='passed')
        finally:
            call('/api/models/stop', {})
    except Exception as error:
        result.update(status='failed', error=type(error).__name__ + ': ' + str(error)[:4000])
        raise
    finally:
        save()
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
