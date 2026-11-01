#!/usr/bin/env bash
# Disposable CI emulator only: resets the new debug app, never the old SOLRDM app.
set -euo pipefail

if [[ $# -lt 2 || $# -gt 4 ]]; then
  echo "Usage: bash scripts/smoke-test.sh APP.apk ANDROID_TEST.apk [PREVIOUS_APP.apk [CONFLICTING_APP.apk]]" >&2
  exit 2
fi
test -s "$1"
test -s "$2"
app_package=org.solrdm.agent.debug
old_package=org.solrdm.app
old_sentinel=SOLRDM_PREVIOUS_INSTALLATION_DATA
mkdir -p evidence
adb wait-for-device
adb shell getprop ro.build.version.sdk | tee evidence/emulator-api.txt
adb shell getprop ro.product.cpu.abi | tee evidence/emulator-abi.txt

assert_installed() {
  local package="$1"
  local log_file="$2"
  adb shell pm path "$package" | tr -d '\r' | tee "$log_file"
  grep -Eq '^package:.+\.apk$' "$log_file"
}

assert_old_installation_preserved() {
  assert_installed "$old_package" evidence/previous-package-after.txt
  adb shell run-as "$old_package" cat files/coinstall-sentinel.txt \
    | tr -d '\r' | tee evidence/previous-data-after.txt
  grep -Fxq "$old_sentinel" evidence/previous-data-after.txt
}

if [[ $# -ge 3 ]]; then
  test -s "$3"
  # Establish a real installation under the old ID before installing this build.
  adb install -r -t "$3" | tr -d '\r' | tee evidence/install-previous-app.txt
  grep -Fxq 'Success' evidence/install-previous-app.txt
  assert_installed "$old_package" evidence/previous-package-before.txt
  adb shell run-as "$old_package" mkdir -p files
  adb shell "run-as $old_package sh -c 'echo $old_sentinel > files/coinstall-sentinel.txt'"
  adb shell run-as "$old_package" cat files/coinstall-sentinel.txt \
    | tr -d '\r' | tee evidence/previous-data-before.txt
  grep -Fxq "$old_sentinel" evidence/previous-data-before.txt
fi

if [[ $# -eq 4 ]]; then
  test -s "$4"
  if adb install -r -t "$4" > evidence/expected-signature-conflict.txt 2>&1; then
    echo 'A differently signed replacement unexpectedly installed' >&2
    exit 1
  fi
  cat evidence/expected-signature-conflict.txt
  grep -Fq 'INSTALL_FAILED_UPDATE_INCOMPATIBLE' evidence/expected-signature-conflict.txt
  assert_old_installation_preserved
fi

adb install -r -t "$1" | tr -d '\r' | tee evidence/install-app.txt
adb install -r -t "$2" | tr -d '\r' | tee evidence/install-test.txt
grep -Fxq 'Success' evidence/install-app.txt
grep -Fxq 'Success' evidence/install-test.txt
assert_installed "$app_package" evidence/debug-package.txt
if [[ $# -ge 3 ]]; then assert_old_installation_preserved; fi
# Reset only the separately identified test build; the existing app is untouched.
adb shell pm clear "$app_package" | tr -d '\r' | tee evidence/clear-test-data.txt
grep -Fxq 'Success' evidence/clear-test-data.txt

run_phase() {
  local method="$1"
  local log_file="$2"
  adb shell am instrument -w -r \
    -e class "org.solrdm.app.BridgeSmokeTest#$method" \
    "$app_package.test/android.test.InstrumentationTestRunner" \
    | tr -d '\r' | tee "$log_file"
  # am instrument can exit 0 even if an assertion failed or the process crashed.
  grep -Fq 'OK (1 test)' "$log_file"
  grep -Fxq 'INSTRUMENTATION_CODE: -1' "$log_file"
  if grep -Eq 'FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed|shortMsg=' "$log_file"; then
    return 1
  fi
}

run_phase testFirstLaunchWritesObservation evidence/instrumentation-write.txt
adb shell am force-stop "$app_package"
if [[ -n "$(adb shell pidof "$app_package" | tr -d '\r' || true)" ]]; then
  echo 'SOLRDM Agent process remained alive after force-stop' >&2
  exit 1
fi
echo 'App process stopped between write and read phases.' | tee evidence/process-restart.txt
# A compatible same-key update must preserve the database and trained model.
adb install -r -t "$1" | tr -d '\r' | tee evidence/reinstall-same-debug-apk.txt
grep -Fxq 'Success' evidence/reinstall-same-debug-apk.txt
run_phase testRestartPreservesObservation evidence/instrumentation-restart.txt

run_agent_phase() {
  local method="$1"
  local log_file="$2"
  adb shell am instrument -w -r \
    -e class "org.solrdm.app.AgentSmokeTest#$method" \
    "$app_package.test/android.test.InstrumentationTestRunner" \
    | tr -d '\r' | tee "$log_file"
  grep -Fq 'OK (1 test)' "$log_file"
  grep -Fxq 'INSTRUMENTATION_CODE: -1' "$log_file"
  if grep -Eq 'FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed|shortMsg=' "$log_file"; then return 1; fi
}
run_agent_phase testAgentToolsAndPersistence evidence/agent-tools.txt
adb shell am force-stop "$app_package"
run_agent_phase testAgentRestartPreservesHistory evidence/agent-restart.txt
adb shell am start -W -n "$app_package/org.solrdm.app.AgentActivity"
# Activity launch completion precedes WebView's first rendered frame. Check the
# visible accessibility tree before capturing evidence, rather than a blank frame.
visible=false
for attempt in 1 2 3 4 5; do
  adb shell uiautomator dump /sdcard/solrdm-agent.xml > /dev/null
  adb pull /sdcard/solrdm-agent.xml evidence/solrdm-agent-ui.xml > /dev/null
  if grep -Fq 'Connect a model to start chatting' evidence/solrdm-agent-ui.xml; then
    visible=true
    break
  fi
  sleep 1
done
if [[ "$visible" != true ]]; then
  echo 'Agent UI was not visible after launch.' >&2
  adb logcat -d -v threadtime > evidence/agent-launch-logcat.txt
  exit 1
fi
adb shell screencap -p /sdcard/solrdm-agent.png
adb pull /sdcard/solrdm-agent.png evidence/solrdm-agent-emulator.png
if [[ $# -ge 3 ]]; then
  assert_old_installation_preserved
  echo 'PASS: previous SOLRDM and new SOLRDM Agent coexist; previous private data is retained.' \
    | tee evidence/coinstall-result.txt
fi
echo 'PASS: APK installation and same-key update, all 16 module imports, six UI commands, schema migration, and SQLite plus neural persistence after update and restart.' \
  | tee evidence/smoke-result.txt
echo 'PASS: bundled agent WebView, offline scientific tool, explicit model-pending state and app history after process restart.' \
  | tee evidence/agent-smoke-result.txt
