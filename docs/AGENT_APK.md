# SOLRDM Agent APK 0.8.0

This APK bundles the new responsive workspace, so startup and scientific calculations do not depend on the unpublished website. It installs as **SOLRDM Agent**, package `org.solrdm.agent.debug`, alongside previous `org.solrdm.app` and `org.solrdm.app.debug` installations. Those applications have separate private data. The debug signing key is still ephemeral unless persistent signing secrets are configured; future in-place updates must use the same key.

The scientific workbench runs bounded JavaScript tools locally. A native **Python engine** control opens the existing six-operation Android interface backed by all sixteen supplied v0.7 modules. These are separate workflows; this does not claim an LLM can call every Python module.

Conversation and multimodal interpretation remain explicitly unavailable until a real model service is configured. No API key is embedded, no fake assistant response is substituted, and the app does not load an unpublished Site. File selection supports Android's document picker; video preparation samples six frames without audio. Research search requires internet access to Crossref and returns metadata/available abstracts, not verified full-paper reviews. JSON/Markdown export uses Android's document-save dialog.

The bundled assets are generated from tracked web sources by `node scripts/package-agent-assets.mjs`, which Gradle invokes before building. Existing web behavior remains unchanged. APK verification checks the packaged assets against generated source bytes, verifies all sixteen Python modules, validates the Android signature and publishes SHA-256.

The Android CI workflow builds the signed debug APK, runs Python/web tests and lint, independently verifies the downloaded APK, installs it on an Android 35 x86_64 emulator, tests the native Python screen, exercises the real bundled WebView and verifies persisted history after a process restart. A CI success is not proof of installation on the user's physical Samsung phone. Device file-picker/export interactions, live research, actual model calls and video interpretation require separate verification.
