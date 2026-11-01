#!/usr/bin/env python3
"""Exercise the installed app's authenticated HTTP API using real model weights."""
import argparse
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8787')
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with urllib.request.urlopen(args.url + '/', timeout=10) as response:
        html = response.read(1_000_000).decode()
    token = re.search(r'<meta name="solrdm-token" content="([^"]+)"', html).group(1)
    assert token != '__SOLRDM_TOKEN__'

    def call(path, data=None, timeout=240):
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(args.url + path, data=body, headers={
            'Content-Type': 'application/json', 'X-SOLRDM-Token': token,
            'Origin': args.url,
        }, method='POST' if data is not None else 'GET')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise AssertionError(f'{path}: HTTP {error.code}: {error.read(4096).decode(errors="replace")}') from None

    status = call('/api/status')
    assert status['app'] == 'SOLRDM Pi Agent', status
    assert status.get('engine', {}).get('available') is True, status
    record = call('/api/models/attach', {'path': str(args.model.resolve()), 'name': 'Installed HTTP test language model', 'role': 'language'})
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
        response = call('/api/chat', {'text': 'What is 2 + 2? Reply with the number only.', 'mode': 'chat', 'messages': [], 'attachments': []})
        assert re.search(r'(?<!\d)4(?!\d)', response.get('text', '')), response
        assert not response.get('incomplete'), response
        result = {'installed_application': True, 'real_http_chat': True,
                  'original_engine_available': True, 'response': response,
                  'model_file': args.model.name,
                  'platform': 'GitHub-hosted ARM64 Linux; not a physical Raspberry Pi'}
        args.output.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), flush=True)
    finally:
        call('/api/models/stop', {})


if __name__ == '__main__':
    main()
