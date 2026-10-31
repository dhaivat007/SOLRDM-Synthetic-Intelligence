# SOLRDM — Synthetic Observational Learning, Reasoning & Discovery Model

Android 0.7.2 embeds the 16 Python modules from the supplied SOLRDM v0.7 source
bundle through Chaquopy. It uses no pretrained LLM. The Android UI supports six
operations: structured observations, limited English interpretation, memory queries
with symbolic inference, unverified hypotheses, local neural training, and status.
**Bundling every supplied module does not mean complete Android feature parity.**
Advanced learning, science, and research workflows still lack Android controls.
See [the feature inventory](docs/ENGINE_PARITY.md) and
[source provenance](docs/source-provenance.json).

Python work runs on a serial background worker. Observations persist in SQLite;
neural parameters, training count, and random state persist beside that database.
Existing observation-prototype rows migrate once with provenance; the original
rows remain intact. Interpret English only proposes candidates and does not save
them. Hypotheses and neural similarities are not verified truth.

## Build and download

[Build SOLRDM Android APK](https://github.com/dhaivat007/SOLRDM-Synthetic-Intelligence/actions/workflows/build-android.yml)
produces `SOLRDM-Android-v0.7.2-debug-APK`. Select a successful run for the intended
commit and download its ZIP. It contains `SOLRDM-0.7.2-debug.apk`, `SHA256SUMS`,
signature verification, package metadata, source hashes, and separate symbolic and
neural benchmark results. `build-info.json` identifies the exact commit and run.
Artifacts expire after 30 days and GitHub may require sign-in to download.

The workflow runs Python regression tests and synthetic benchmarks, builds both
APKs, runs Android lint, verifies the signature/checksum and packaged module list,
then installs the downloaded artifact on an Android 35 x86_64 emulator. Two
instrumentation phases exercise all six UI commands, migrate old data, and check
SQLite and neural state across a forced process restart. Read the exact run's logs
before claiming these checks passed; source documentation is not execution proof.

The APK supports Android 8.0+ (API 26), targets API 35, and packages ARM64 and
x86_64 libraries. Physical-device/ARM64 execution needs separate verification.
Android-generated debug keys can differ across CI runs, preventing installation as
an update over an APK signed with another key. Uninstalling deletes app data; the
migration checks do not establish upgrade compatibility between different keys.
This is a development build, not a production-signed or Play Store release.

[CI diagnosis and reproduction](docs/CI_REPAIR.md) documents the repaired SDK setup.
Never commit signing keys, credentials, research databases, or trained user models.
The manifest has no Internet permission, and the app does not schedule autonomous
research. Research modules are tested with synthetic transports only.
