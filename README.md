# SOLRDM — Synthetic Observational Learning, Reasoning & Discovery Model

This Android research prototype embeds Python through Chaquopy and stores a
limited `X is part of Y` observation pattern in SQLite. It contains no pretrained
LLM. **The full historical SOLRDM v0.7 intelligence engine is not included.**
See [the feature inventory](docs/ENGINE_PARITY.md) for source provenance and limits.

## Build and download

[Build SOLRDM Android APK](https://github.com/dhaivat007/SOLRDM-Synthetic-Intelligence/actions/workflows/build-android.yml)
produces the `SOLRDM-Android-debug-APK` artifact. Select a successful run for the
intended commit and download the artifact ZIP. It contains
`SOLRDM-0.7.1-debug.apk`, `SHA256SUMS`, certificate verification output, package
metadata, and the exact source commit and build URL in `build-info.json`.
Artifacts expire after 30 days and GitHub may require sign-in to download.

The workflow tests Python behavior, builds the signed debug APK, runs Android lint,
verifies the APK signature and checksum, and installs the downloaded artifact on
an API 35 x86_64 emulator. Its two instrumentation phases click the UI's Observe
button and check SQLite persistence after the app process is force-stopped.
Read the matching run's logs before claiming these checks passed. ARM64 is packaged
but physical-device execution is not established by an x86_64 emulator test.

This development APK supports Android 8.0+ (API 26), contains ARM64 and x86_64
native libraries, and targets API 35. Its generated debug signing key
may change between runs, preventing upgrades over a differently signed build.
It is not a production-signed or Play Store release.

[CI diagnosis and reproduction instructions](docs/CI_REPAIR.md) describe the SDK
setup failure and validation procedure. Never commit API keys, signing keys,
user data, or research databases. Internet learning must use approved sources and
validation gates; this bridge performs no internet ingestion.
