#!/usr/bin/env bash
# CI emulator only: clears org.solrdm.app data before the first phase.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: bash scripts/smoke-test.sh APP.apk ANDROID_TEST.apk" >&2
  exit 2
fi
test -s "$1"
test -s "$2"
mkdir -p evidence
adb wait-for-device
adb shell getprop ro.build.version.sdk | tee evidence/emulator-api.txt
adb shell getprop ro.product.cpu.abi | tee evidence/emulator-abi.txt
adb install -r -t "$1" | tr -d '\r' | tee evidence/install-app.txt
adb install -r -t "$2" | tr -d '\r' | tee evidence/install-test.txt
grep -Fxq 'Success' evidence/install-app.txt
grep -Fxq 'Success' evidence/install-test.txt
adb shell pm clear org.solrdm.app | tr -d '\r' | tee evidence/clear-test-data.txt
grep -Fxq 'Success' evidence/clear-test-data.txt

run_phase() {
  local method="$1"
  local log_file="$2"
  adb shell am instrument -w -r \
    -e class "org.solrdm.app.BridgeSmokeTest#$method" \
    org.solrdm.app.test/android.test.InstrumentationTestRunner \
    | tr -d '\r' | tee "$log_file"
  # am instrument can exit 0 even if an assertion failed or the process crashed.
  grep -Fq 'OK (1 test)' "$log_file"
  grep -Fxq 'INSTRUMENTATION_CODE: -1' "$log_file"
  if grep -Eq 'FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed|shortMsg=' "$log_file"; then
    return 1
  fi
}

run_phase testFirstLaunchWritesObservation evidence/instrumentation-write.txt
adb shell am force-stop org.solrdm.app
if [[ -n "$(adb shell pidof org.solrdm.app | tr -d '\r' || true)" ]]; then
  echo 'SOLRDM process remained alive after force-stop' >&2
  exit 1
fi
echo 'App process stopped between write and read phases.' | tee evidence/process-restart.txt
run_phase testRestartPreservesObservation evidence/instrumentation-restart.txt
echo 'PASS: APK installation, UI → Python, rejected input, and SQLite persistence after process restart.' \
  | tee evidence/smoke-result.txt
