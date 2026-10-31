#!/usr/bin/env bash
# Minimal no-code APKs model the old package with two different signing keys.
# Private fixture keys exist only in this job's temporary directory and are deleted.
set -euo pipefail
output_dir=${1:?Usage: build-installation-fixtures.sh OUTPUT_DIR}
build_tools="${ANDROID_HOME:?}/build-tools/35.0.0"
fixture_tmp=$(mktemp -d)
trap 'rm -rf "$fixture_tmp"' EXIT
mkdir -p "$output_dir"
cat > "$fixture_tmp/AndroidManifest.xml" <<'XML'
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.solrdm.app" android:versionCode="9" android:versionName="0.7.2-fixture">
    <uses-sdk android:minSdkVersion="26" android:targetSdkVersion="35" />
    <application android:label="SOLRDM legacy install fixture" android:debuggable="true" android:hasCode="false" />
</manifest>
XML
"$build_tools/aapt" package -f -M "$fixture_tmp/AndroidManifest.xml" \
  -I "$ANDROID_HOME/platforms/android-35/android.jar" -F "$fixture_tmp/unsigned.apk"
"$build_tools/zipalign" -f 4 "$fixture_tmp/unsigned.apk" "$fixture_tmp/aligned.apk"
for fixture_key in old replacement; do
  keytool -genkeypair -noprompt -keystore "$fixture_tmp/$fixture_key.keystore" \
    -storepass android -keypass android -alias fixture -keyalg RSA -keysize 2048 \
    -validity 365 -dname "CN=SOLRDM CI $fixture_key fixture" > /dev/null 2>&1
  "$build_tools/apksigner" sign --ks "$fixture_tmp/$fixture_key.keystore" \
    --ks-key-alias fixture --ks-pass pass:android --key-pass pass:android \
    --out "$output_dir/legacy-$fixture_key.apk" "$fixture_tmp/aligned.apk"
  "$build_tools/apksigner" verify "$output_dir/legacy-$fixture_key.apk"
done
