#!/usr/bin/env python3
"""Exercise the application's real cloud-import path for both release models."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from solrdm_pi.models import ModelManager
from smoke_runtime import MODELS


def download_models(output, evidence):
    output = Path(output).resolve()
    evidence = Path(evidence).resolve()
    output.mkdir(parents=True, exist_ok=True)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    results = []
    try:
        for model in MODELS:
            if Path(model['file']).name != model['file']:
                raise ValueError('The model manifest contains an invalid filename.')
            destination = output / model['file']
            if destination.exists():
                raise ValueError(f'Refusing to overwrite existing model: {destination.name}')
            result = {'model': model['id'], 'file': model['file'], 'url': model['url'],
                      'status': 'downloading', 'method': 'ModelManager.import_url',
                      'expected_sha256': model['sha256'], 'expected_size_bytes': model['size_bytes']}
            results.append(result)
            started = time.monotonic()
            # The managed download and final asset share a filesystem; rename
            # transfers ownership without copying another gigabyte of weights.
            with tempfile.TemporaryDirectory(prefix='.model-import-', dir=output) as directory:
                manager = ModelManager(directory)
                try:
                    transfer = manager.import_url(model['url'], model['name'], model['sha256'], model['role'])
                    last_progress = -10.0
                    while time.monotonic() - started < 1800:
                        transfer = manager.job(transfer['id'])
                        elapsed = time.monotonic() - started
                        if elapsed - last_progress >= 10 or transfer['state'] in ('completed', 'failed'):
                            print(json.dumps({'model': model['id'], 'state': transfer['state'],
                                              'received': transfer['received'], 'total': transfer['total'],
                                              'elapsed_seconds': round(elapsed, 1)}), flush=True)
                            last_progress = elapsed
                        if transfer['state'] == 'failed':
                            raise RuntimeError(transfer['error'] or 'Application cloud import failed.')
                        if transfer['state'] == 'completed':
                            break
                        time.sleep(1)
                    else:
                        manager.cancel_transfer(transfer['id'])
                        raise TimeoutError('Application cloud import exceeded 30 minutes.')
                    registered = next(item for item in manager.list_models() if item['id'] == transfer['model_id'])
                    source = Path(registered['path'])
                    with source.open('rb') as stream:
                        actual_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
                    actual_size = source.stat().st_size
                    if actual_sha != model['sha256'] or actual_size != model['size_bytes']:
                        raise AssertionError('Downloaded model bytes do not match the pinned manifest.')
                    if registered['sha256'] != actual_sha or transfer['sha256'] != actual_sha:
                        raise AssertionError('Application transfer/registry checksum differs from the saved file.')
                    source.replace(destination)
                    result.update(status='completed', sha256=actual_sha, size_bytes=actual_size,
                                  transfer_status=transfer['state'], elapsed_seconds=round(time.monotonic() - started, 3))
                except Exception as exc:
                    result.update(status='failed', error=str(exc))
                    raise
                finally:
                    manager.close()
                    evidence.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    finally:
        evidence.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    download_models(args.output, args.evidence or args.output / 'download-evidence.json')


if __name__ == '__main__':
    main()
