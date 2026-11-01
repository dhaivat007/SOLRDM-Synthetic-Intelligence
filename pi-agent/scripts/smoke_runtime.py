#!/usr/bin/env python3
"""Real local inference test. Never substitutes fixtures for model weights."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from solrdm_pi.models import ModelManager
from solrdm_pi.agent import Agent
from solrdm_pi.memory import MemoryStore

MODELS = [
    {
        'id': 'qwen-language-1.5b',
        'name': 'Qwen2.5 1.5B Instruct Q4_K_M',
        'file': 'qwen2.5-1.5b-instruct-q4_k_m.gguf',
        'role': 'language',
        'url': 'https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/dd26da440ef0330c47919d1ecae0966d24022222/qwen2.5-1.5b-instruct-q4_k_m.gguf',
        'sha256': '6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e',
        'size_bytes': 1117320736,
        'license': 'Apache-2.0',
        'publisher': 'Qwen',
        'capability': 'Text conversation; small model, answers require checking.',
    },
    {
        'id': 'qwen-math-1.5b',
        'name': 'Qwen2.5 Math 1.5B Instruct Q4_K_M',
        'file': 'Qwen2.5-Math-1.5B-Instruct-Q4_K_M.gguf',
        'role': 'mathematics',
        'url': 'https://huggingface.co/second-state/Qwen2.5-Math-1.5B-Instruct-GGUF/resolve/14a9fbcfbd3bb7ad26297d7725b790dce07ee51a/Qwen2.5-Math-1.5B-Instruct-Q4_K_M.gguf',
        'sha256': '336d6f6973034fea14fae3164649dd8d81fb1df06dee3aa12de26cfb04715759',
        'size_bytes': 986048544,
        'license': 'Apache-2.0',
        'publisher': 'Qwen; GGUF conversion by Second State',
        'capability': 'Text mathematics assistance; calculations require verification.',
    },
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest-only', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'MODEL-MANIFEST.json').write_text(json.dumps(MODELS, indent=2) + '\n')
    if args.manifest_only:
        return
    results = []
    for model in MODELS:
        path = args.model_dir / model['file']
        with path.open('rb') as stream:
            actual_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual_hash != model['sha256'] or path.stat().st_size != model['size_bytes']:
            raise SystemExit(f'Model checksum or size mismatch: {path.name}')
        with tempfile.TemporaryDirectory(prefix='solrdm-real-inference-') as directory:
            manager = ModelManager(directory, runtime_path=str(args.runtime.resolve()), port=18081)
            record = manager.attach(str(path.resolve()), name=model['name'], role=model['role'])
            started = time.monotonic()
            try:
                manager.start(record['id'])
                while time.monotonic() - started < 240:
                    state = manager.status()
                    if state.get('ready'):
                        break
                    if state.get('state') == 'error':
                        raise AssertionError(state)
                    time.sleep(1)
                else:
                    raise AssertionError(f'Runtime readiness timeout: {manager.status()}')
                ready_after = round(time.monotonic() - started, 3)
                reply = manager.chat([
                    {'role': 'system', 'content': 'You are a helpful assistant. Answer concisely.'},
                    {'role': 'user', 'content': 'Compute 2 + 2. Reply with the answer only.'},
                ], max_tokens=96, temperature=0)
                if not isinstance(reply, str) or not re.search(r'(?<!\d)4(?!\d)', reply):
                    raise AssertionError(f'Actual arithmetic response did not contain 4: {reply!r}')
                agent = Agent(manager, MemoryStore(directory), lambda: {'preferred_backend': 'local'})
                conversation = agent.run({'mode': 'chat', 'text': 'Say hello in one short sentence.', 'messages': [], 'attachments': []})
                if not conversation.get('text') or conversation.get('incomplete'):
                    raise AssertionError(f'Application chat failed: {conversation!r}')
                task = agent.run({'mode': 'math', 'text': 'Use the calculate tool to evaluate 12345 * 6789, then report its result.', 'messages': [], 'attachments': []})
                receipts = task.get('receipts', [])
                if not any(r.get('tool') == 'calculate' and r.get('status') == 'completed' for r in receipts):
                    raise AssertionError(f'Real model did not execute the requested calculation tool: {task!r}')
                if task.get('incomplete') or not task.get('text'):
                    raise AssertionError(f'Application math task did not finish: {task!r}')
                results.append({
                    'model': model['id'], 'sha256': actual_hash, 'bytes': path.stat().st_size,
                    'prompt': 'Compute 2 + 2. Reply with the answer only.',
                    'response': reply, 'real_inference': True, 'ready_seconds': ready_after,
                    'application_chat': conversation, 'application_math_task': task,
                    'elapsed_seconds': round(time.monotonic() - started, 3),
                    'platform': 'GitHub-hosted ARM64 Linux; not a physical Raspberry Pi',
                })
                print(json.dumps(results[-1]), flush=True)
            finally:
                manager.stop()
                log = Path(directory) / 'llama-server.log'
                if log.is_file():
                    shutil.copy2(log, args.output / (model['id'] + '-llama-server.log'))
    (args.output / 'real-inference.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
