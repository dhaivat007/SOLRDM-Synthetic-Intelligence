#!/usr/bin/env python3
"""Create an installable Pi bundle and exact SHA-256 manifest; no user data."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile

VERSION = '0.10.0'
LLAMA_COMMIT = '8642541b255bfb5dc39cd351a178be09013a55d6'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('pi-output'))
    parser.add_argument('--require-runtime', action='store_true')
    args = parser.parse_args()
    app = Path(__file__).resolve().parents[1]
    repo = app.parent
    args.output.mkdir(parents=True, exist_ok=True)
    runtime = app / 'runtime/bin/llama-server'
    if args.require_runtime and not runtime.is_file():
        raise SystemExit('Missing ARM64 runtime')
    files = {}
    roots = [('solrdm_pi', app / 'solrdm_pi'), ('web', app / 'web'),
             ('runtime', app / 'runtime'), ('engine/solrdm', repo / 'app/src/main/python/solrdm')]
    for prefix, root in roots:
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                raise SystemExit(f'Refusing symlink: {path}')
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                files[str(Path(prefix) / path.relative_to(root))] = (path.read_bytes(), 0o755 if os.access(path, os.X_OK) else 0o644)
    for name in ['install.sh', 'launch.sh', 'README.md']:
        files[name] = ((app / name).read_bytes(), 0o755 if name.endswith('.sh') else 0o644)
    files['engine/android_bridge.py'] = ((repo / 'app/src/main/python/android_bridge.py').read_bytes(), 0o644)
    files['source-provenance.json'] = ((repo / 'docs/source-provenance.json').read_bytes(), 0o644)
    engine_count = sum(name.startswith('engine/solrdm/') and name.endswith('.py') for name in files)
    if engine_count != 16:
        raise SystemExit(f'Expected all 16 original engine modules; found {engine_count}')
    metadata = {
        'application': 'SOLRDM Pi Agent', 'version': VERSION, 'platform': 'linux-arm64',
        'minimum_python': '3.11', 'minimum_os': '64-bit Raspberry Pi OS Bookworm (Debian 12)',
        'source_commit': os.environ.get('GITHUB_SHA', 'local-unpublished'),
        'build_url': (f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
                      if os.environ.get('GITHUB_RUN_ID') else None),
        'llama_cpp_commit': LLAMA_COMMIT, 'runtime_bundled': runtime.is_file(),
        'engine_module_count': engine_count, 'model_weights_bundled': False,
        'physical_raspberry_pi_tested': False,
        'subjective_consciousness_verified': False,
        'model_weights_retrained': False,
        'upgrade_preserves': ['models', 'settings', 'observations', 'task_history'],
        'complete_models_release': 'solrdm-pi-v0.9.0-preview',
    }
    files['BUILD-INFO.json'] = (json.dumps(metadata, indent=2).encode() + b'\n', 0o644)
    manifest = ''.join(f'{hashlib.sha256(content).hexdigest()}  {name}\n' for name, (content, mode) in sorted(files.items()))
    files['MANIFEST.sha256'] = (manifest.encode(), 0o644)
    package = args.output / f'SOLRDM-Pi5-{VERSION}-linux-arm64.tar.gz'
    with package.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='') as zipped:
        with tarfile.open(fileobj=zipped, mode='w') as archive:
            for name, (content, mode) in sorted(files.items()):
                entry = tarfile.TarInfo(f'SOLRDM-Pi5-{VERSION}/{name}')
                entry.size, entry.mode, entry.mtime = len(content), mode, 0
                entry.uid = entry.gid = 0
                entry.uname = entry.gname = ''
                archive.addfile(entry, io.BytesIO(content))
    (args.output / 'BUILD-INFO.json').write_text(json.dumps(metadata, indent=2) + '\n')
    checksum = hashlib.file_digest(package.open('rb'), 'sha256').hexdigest()
    (args.output / 'SHA256SUMS').write_text(f'{checksum}  {package.name}\n')
    print(json.dumps({'package': str(package), 'bytes': package.stat().st_size, 'sha256': checksum, **metadata}, indent=2))


if __name__ == '__main__':
    main()
