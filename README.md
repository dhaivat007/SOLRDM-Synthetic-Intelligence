# SOLRDM — Synthetic Observational Learning, Reasoning & Discovery Model

The new [Raspberry Pi 5 application](pi-agent/README.md) targets 8 GB devices running
64-bit Raspberry Pi OS. It provides a local GGUF model library, pretrained language
and mathematics model downloads, chat, scientific tools, source-linked research,
and reviewed observation memory. Version 0.10 adds live capability reports,
persistent goals and bounded tool plans, actual execution receipts, and model
reflections. Plans require explicit Run; interrupted work is never silently retried.
These operational features do not establish subjective consciousness or retrain
model weights. Its [build workflow](.github/workflows/pi-agent.yml)
verifies native ARM64 inference, installed HTTP chat, model-generated plans and
data preservation when upgrading the published 0.9 app before
publishing a preview. See the exact run's evidence; physical Pi testing is separate.
The Pi app uses pretrained models as explicitly requested. The description below
refers to the earlier Android observation engine.

Android 0.7.3 embeds the 16 Python modules from the supplied SOLRDM v0.7 source
bundle through Chaquopy. It uses no pretrained LLM. The Android UI supports six
operations: structured observations, limited English interpretation, memory queries
with symbolic inference, unverified hypotheses, local neural training, and status.
**Bundling every supplied module does not mean complete Android feature parity.**
Advanced learning, science, and research workflows still lack Android controls.
See [the feature inventory](docs/ENGINE_PARITY.md) and
[source provenance](docs/source-provenance.json).

Python work runs on a serial background worker. Observations persist in SQLite;
neural parameters, training count, and random state persist beside that database.
An existing database within the same app sandbox migrates once with provenance;
original rows remain intact. The separately installed Debug app cannot access the
older app's private database. Interpret English only proposes candidates and does not save
them. Hypotheses and neural similarities are not verified truth.

## Build and download

[Build SOLRDM Android APK](https://github.com/dhaivat007/SOLRDM-Synthetic-Intelligence/actions/workflows/build-android.yml)
produces `SOLRDM-Android-v0.7.3-debug-APK`. Select a successful run for the intended
commit and download its ZIP. It contains `SOLRDM-0.7.3-debug.apk`, `SHA256SUMS`,
signature verification, package metadata, source hashes, and separate symbolic and
neural benchmark results. `build-info.json` identifies the exact commit and run.
Artifacts expire after 30 days and GitHub may require sign-in to download.

The workflow runs Python regression tests and synthetic benchmarks, builds both
APKs, runs Android lint, verifies the signature/checksum and packaged module list,
then installs the downloaded artifact on an Android 35 x86_64 emulator alongside
an existing package. CI reproduces a mismatched-key update rejection and checks
that the existing package's private data remains intact. Two
instrumentation phases exercise all six UI commands, migrate old data, and check
SQLite and neural state across a forced process restart. Read the exact run's logs
before claiming these checks passed; source documentation is not execution proof.

The APK supports Android 8.0+ (API 26), targets API 35, and packages ARM64 and
x86_64 libraries. Physical-device/ARM64 execution needs separate verification.
The Debug APK uses package `org.solrdm.app.debug` and launcher name **SOLRDM Debug**
so it can install alongside older `org.solrdm.app` builds without removing their
data. The two apps have separate storage. Android rejects updates signed with a
different key. CI can use a persistent debug keystore from repository secrets;
without that configuration, newly generated debug keys still differ across runs.
Do not uninstall an existing app to work around a signing error without backing up
its data. See [installation and signing](docs/INSTALLATION.md).
This is a development build, not a production-signed or Play Store release.

[CI diagnosis and reproduction](docs/CI_REPAIR.md) documents the repaired SDK setup.
Never commit signing keys, credentials, research databases, or trained user models.
The manifest has no Internet permission, and the app does not schedule autonomous
research. Research modules are tested with synthetic transports only.
