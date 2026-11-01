#!/usr/bin/env python3
"""Real local inference test. Never substitutes fixtures for model weights."""
import argparse
import ast
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


def verify_calculation_task(task):
    """Require the requested multiplication to have actually run correctly."""
    if task.get('incomplete') or not isinstance(task.get('text'), str) or not task['text'].strip():
        raise AssertionError(f'Application math task did not finish: {task!r}')
    if not re.search(r'(?<!\d)83810205(?!\d)', task['text'].replace(',', '')):
        raise AssertionError(f'Application answer did not report the verified multiplication result: {task!r}')
    for receipt in task.get('receipts', []):
        if receipt.get('tool') != 'calculate' or receipt.get('status') != 'completed':
            continue
        data = receipt.get('data', {})
        if data.get('result') != 12345 * 6789:
            continue
        try:
            expression = ast.parse(data.get('expression', ''), mode='eval').body
        except (SyntaxError, TypeError, ValueError):
            continue
        if (isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.Mult)
                and isinstance(expression.left, ast.Constant)
                and isinstance(expression.right, ast.Constant)
                and type(expression.left.value) in (int, float)
                and type(expression.right.value) in (int, float)
                and sorted((expression.left.value, expression.right.value)) == [6789, 12345]):
            return
    raise AssertionError(f'Real model did not execute 12345 * 6789 with result 83810205: {task!r}')


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
    def save_progress():
        temporary = args.output / 'real-inference.json.tmp'
        temporary.write_text(json.dumps(results, indent=2) + '\n')
        temporary.replace(args.output / 'real-inference.json')

    save_progress()
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
            evidence = {
                'model': model['id'], 'sha256': actual_hash, 'bytes': path.stat().st_size,
                'status': 'running', 'model_sha256_verified': True,
                'platform': 'GitHub-hosted ARM64 Linux; not a physical Raspberry Pi',
            }
            results.append(evidence)
            save_progress()
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
                evidence['ready_seconds'] = ready_after
                save_progress()
                reply = manager.chat([
                    {'role': 'system', 'content': 'You are a helpful assistant. Answer concisely.'},
                    {'role': 'user', 'content': 'Compute 2 + 2. Reply with the answer only.'},
                ], max_tokens=96, temperature=0)
                evidence.update(prompt='Compute 2 + 2. Reply with the answer only.', response=str(reply),
                                response_incomplete=bool(getattr(reply, 'incomplete', False)), real_inference=True)
                save_progress()
                if not isinstance(reply, str) or not re.search(r'(?<!\d)4(?!\d)', reply):
                    raise AssertionError(f'Actual arithmetic response did not contain 4: {reply!r}')
                if getattr(reply, 'incomplete', False):
                    raise AssertionError(f'Direct arithmetic output was reported incomplete: {reply!r}')
                agent = Agent(manager, MemoryStore(directory), lambda: {'preferred_backend': 'local'})
                conversation = agent.run({'mode': 'chat', 'text': 'Say hello in one short sentence.', 'messages': [], 'attachments': []})
                evidence['application_chat'] = conversation
                save_progress()
                if not conversation.get('text') or conversation.get('incomplete'):
                    raise AssertionError(f'Application chat failed: {conversation!r}')
                task = agent.run({'mode': 'math', 'text': 'Use the calculate tool to evaluate 12345 * 6789, then report its result.', 'messages': [], 'attachments': []})
                evidence['application_math_task'] = task
                save_progress()
                verify_calculation_task(task)
                evidence['status'] = 'passed'
                print(json.dumps(evidence), flush=True)
            except Exception as error:
                evidence['status'] = 'failed'
                evidence['error'] = type(error).__name__ + ': ' + str(error)[:2000]
                raise
            finally:
                evidence['elapsed_seconds'] = round(time.monotonic() - started, 3)
                save_progress()
                manager.stop()
                log = Path(directory) / 'llama-server.log'
                if log.is_file():
                    shutil.copy2(log, args.output / (model['id'] + '-llama-server.log'))


if __name__ == '__main__':
    main()
