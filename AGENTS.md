# Codex development instructions — SOLRDM

## Mission
Build and verify a real installable Android APK for SOLRDM (Synthetic Observational Learning, Reasoning & Discovery Model). Preserve Option 1: no pretrained LLM as the intelligence engine.

## Repository status
The Android app now includes all 16 Python modules from the user-supplied v0.7 source archive. Six offline operations are exposed in the UI; advanced library workflows are not complete Android feature parity. Preserve the source hashes in docs/source-provenance.json. Do not claim full historical parity or successful Android execution without the matching tests and artifact evidence.

## Immediate steps
1. Inspect Gradle, Android Gradle Plugin, Chaquopy repositories, Android SDK, and workflow. Run the GitHub Actions equivalent build in a cloud development environment.
2. Fix actual compilation failures; retain error logs and document root causes.
3. Run Android unit/instrumentation tests where supported and Python tests for bundled modules.
4. Build `assembleDebug`; verify APK signature, package name, version, ABI, file size and SHA-256.
5. Publish the APK as a GitHub Actions artifact. Provide the exact successful run URL and artifact name. Never claim a build succeeded without logs/artifact.
6. Confirm Android UI calls Python engine successfully; verify SQLite persistence across app restarts.
7. For full engine parity, integrate all available SOLRDM v0.7 modules, provide an inventory of working/partial/unavailable features, and benchmark neural and symbolic components independently.

## Safety and engineering
Do not commit secrets, signing keys, credentials, or user databases. Debug signatures are for development only. No uncontrolled autonomous internet ingestion. Keep source provenance, validation gates, and approval controls. Do not represent intent classification or scripted rules as general intelligence.

## Acceptance criteria
- Successful reproducible CI APK build
- APK signature verified with apksigner
- SHA-256 published
- On-device Python bridge smoke test (emulator or physical device, identify which)
- Clear feature parity report and limitations

