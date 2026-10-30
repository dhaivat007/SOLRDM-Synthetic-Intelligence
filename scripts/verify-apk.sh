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
import json
import os
from pathlib import Path
import sys
import zipfile

apk = Path(sys.argv[1])
badging = (apk.parent / 'apk-badging.txt').read_text()
assert "package: name='org.solrdm.app' versionCode='8' versionName='0.7.1'" in badging, badging
assert "sdkVersion:'26'" in badging, badging
assert "targetSdkVersion:'28'" in badging, badging
with zipfile.ZipFile(apk) as archive:
    abis = sorted({p.split('/')[1] for p in archive.namelist() if p.startswith('lib/') and p.endswith('.so')})
assert abis == ['arm64-v8a', 'x86_64'], abis
sha256 = hashlib.sha256(apk.read_bytes()).hexdigest()
(apk.parent / 'SHA256SUMS').write_text(f'{sha256}  {apk.name}\n')
run_url = f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}" if 'GITHUB_RUN_ID' in os.environ else None
metadata = dict(apk=apk.name, sha256=sha256, size_bytes=apk.stat().st_size,
                package='org.solrdm.app', version_name='0.7.1', version_code=8,
                min_sdk=26, target_sdk=28, abis=abis, signing='development debug certificate',
                commit=os.environ.get('GITHUB_SHA'), build_url=run_url,
                engine='limited observation bridge; full v0.7 source unavailable')
(apk.parent / 'build-info.json').write_text(json.dumps(metadata, indent=2) + '\n')
print(json.dumps(metadata, indent=2))
if 'GITHUB_STEP_SUMMARY' in os.environ:
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write(f'APK: `{apk.name}`\n\nSHA-256: `{sha256}`\n\nSize: {apk.stat().st_size:,} bytes\n\nBuild: {run_url}\n\nDebug signature verified. See emulator job for installation and runtime test result.\n')
PY
(cd "$output_dir" && sha256sum --check SHA256SUMS)
