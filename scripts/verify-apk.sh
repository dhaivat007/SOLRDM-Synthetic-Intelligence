#!/usr/bin/env bash
set -euo pipefail
apk=${1:?Usage: verify-apk.sh APK}
output_dir=$(dirname "$apk")
build_tools="${ANDROID_HOME:?ANDROID_HOME is required}/build-tools/35.0.0"
test -s "$apk"
"$build_tools/apksigner" verify --verbose --print-certs "$apk" | tee "$output_dir/signature.txt"
"$build_tools/aapt" dump badging "$apk" > "$output_dir/apk-badging.txt"
python3 - "$apk" <<'PY'
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import zipfile

apk = Path(sys.argv[1])
provenance = json.loads(Path('docs/source-provenance.json').read_text())
for source in provenance['source_files']:
    assert hashlib.sha256(Path(source['path']).read_bytes()).hexdigest() == source['integrated_sha256'], source['path']
badging = (apk.parent / 'apk-badging.txt').read_text()
assert "package: name='org.solrdm.agent.debug' versionCode='11' versionName='0.8.0'" in badging, badging
assert "sdkVersion:'26'" in badging, badging
assert "targetSdkVersion:'35'" in badging, badging
with zipfile.ZipFile(apk) as archive:
    asset_hashes = {}
    for name in ['index.html', 'style.css', 'app.js', 'android-adapter.js']:
        packaged = archive.read('assets/agent/' + name)
        assert packaged == Path('app/src/main/assets/agent', name).read_bytes(), name
        asset_hashes[name] = hashlib.sha256(packaged).hexdigest()
    assert b'SolrdmAndroid' in archive.read('assets/agent/app.js')
    assert b'modelConfigured' in archive.read('assets/agent/android-adapter.js')
    abis = sorted({p.split('/')[1] for p in archive.namelist() if p.startswith('lib/') and p.endswith('.so')})
    with zipfile.ZipFile(io.BytesIO(archive.read('assets/chaquopy/app.imy'))) as python_archive:
        packaged_modules = sorted(p for p in python_archive.namelist() if p.startswith('solrdm/') and p.endswith('.pyc'))
        expected_modules = sorted('solrdm/' + p.stem + '.pyc' for p in Path('app/src/main/python/solrdm').glob('*.py'))
        assert len(expected_modules) == 16, expected_modules
        assert packaged_modules == expected_modules, packaged_modules
        assert 'android_bridge.pyc' in python_archive.namelist()
assert abis == ['arm64-v8a', 'x86_64'], abis
sha256 = hashlib.sha256(apk.read_bytes()).hexdigest()
(apk.parent / 'SHA256SUMS').write_text(f'{sha256}  {apk.name}\n')
run_url = f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}" if 'GITHUB_RUN_ID' in os.environ else None
metadata = dict(apk=apk.name, sha256=sha256, size_bytes=apk.stat().st_size,
                package='org.solrdm.agent.debug', version_name='0.8.0', version_code=11,
                min_sdk=26, target_sdk=35, abis=abis, signing='development debug certificate',
                commit=os.environ.get('GITHUB_SHA'), build_url=run_url,
                persistent_signing_configured=bool(os.environ.get('SOLRDM_DEBUG_KEYSTORE')),
                installation='Separate SOLRDM Agent package; does not replace org.solrdm.app or org.solrdm.app.debug or share their private data',
                packaged_engine_modules=packaged_modules,
                bundled_agent_assets=asset_hashes,
                conversation_model_configured=False,
                launcher='SOLRDM Agent: bundled offline workspace; Python engine available from native controls',
                engine='supplied v0.7 bundle: 16 modules; six Android commands; incomplete UI parity',
                source_archive_sha256='03fe799e305671542961d7cb689da9d18c9fd166fac88a07815f1632d9329e8c')
(apk.parent / 'build-info.json').write_text(json.dumps(metadata, indent=2) + '\n')
print(json.dumps(metadata, indent=2))
if 'GITHUB_STEP_SUMMARY' in os.environ:
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write(f'APK: `{apk.name}`\n\nSHA-256: `{sha256}`\n\nSize: {apk.stat().st_size:,} bytes\n\nBuild: {run_url}\n\nDebug signature verified. See emulator job for installation and runtime test result.\n')
PY
(cd "$output_dir" && sha256sum --check SHA256SUMS)
