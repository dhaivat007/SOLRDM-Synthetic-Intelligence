# Android CI repair

The failing run https://github.com/dhaivat007/SOLRDM-Synthetic-Intelligence/actions/runs/41144623912 stopped in SDK setup, before Gradle compilation. The setup-android v3 default `packages` input was `tools platform-tools`; `sdkmanager tools` failed with `Warning: Failed to find package 'tools'`. The earlier run 41142363657 (attempt 4) failed at the same command. See the retained log excerpt in `ci-failure-41144623912.log`.

After fixing SDK setup, run https://github.com/dhaivat007/SOLRDM-Synthetic-Intelligence/actions/runs/41147214192 successfully compiled both APKs, but the newly enabled lint gate rejected `targetSdk 28` with `ExpiredTargetSdkVersion`. The app now targets API 35, matching compileSdk, and handles system-bar insets for Android 15 edge-to-edge layout. Lint is not suppressed. See `ci-failure-41147214192.log`.

The workflow overrides that default with `platform-tools platforms;android-35 build-tools;35.0.0`. It uses Java 17, Gradle 8.9, Android Gradle Plugin 8.7.3, Chaquopy 16.1.0 and Python 3.11. Both Gradle plugin and dependency resolution include the Chaquopy Maven repository. No native source is compiled, so the previously requested NDK installation is unnecessary.

The build runs Python regression tests, `assembleDebug`, `assembleDebugAndroidTest`, `testDebugUnitTest` and `lintDebug`. No standalone Java unit tests exist yet; the Gradle unit-test task must not be described as a passing Java test suite if it reports NO-SOURCE. The separate emulator job installs the downloaded, checksum-verified APK on Android API 35 x86_64, tests the UI/Python bridge, force-stops the app, and verifies committed observations in a new process. Instrumentation uses Android's legacy test runner, declared through optional SDK test libraries.

The APK artifact includes `SHA256SUMS`, `signature.txt`, `apk-badging.txt` and `build-info.json`. `apksigner verify --verbose --print-certs` must pass before upload. The emulator job downloads the exact artifact and verifies its signature and SHA-256 again. Build reports/logs and emulator evidence are uploaded separately, including on failure. Signing is Android's generated development debug certificate; keys and databases are never uploaded. A new runner may generate a different debug key and APK hash, so this is a reproducible build procedure, not a promise of byte-identical artifacts or upgrade-compatible signatures across runs.

To reproduce with Java 17, Python 3.11, Gradle 8.9 and an Android SDK configured as `ANDROID_HOME`:

```sh
sdkmanager 'platform-tools' 'platforms;android-35' 'build-tools;35.0.0'
python3 -m unittest discover -s tests -v
gradle --no-daemon --stacktrace assembleDebug assembleDebugAndroidTest testDebugUnitTest lintDebug
bash scripts/verify-apk.sh app/build/outputs/apk/debug/app-debug.apk
# With a running, disposable Android API 35 emulator:
bash scripts/smoke-test.sh app/build/outputs/apk/debug/app-debug.apk app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
```

The managed authoring workspace had Java 21 and Python but no Android SDK, Gradle or emulator; outbound commands failed connecting to its configured proxy. Android build and device verification therefore run on the GitHub-hosted cloud runners. Host Python testing is supplementary. Check the exact workflow run's conclusions and evidence before claiming installation or a successful build.
