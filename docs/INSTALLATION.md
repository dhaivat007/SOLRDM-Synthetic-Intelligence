# Installing SOLRDM Debug 0.7.3

Download the `SOLRDM-Android-v0.7.3-debug-APK` artifact ZIP from the intended
successful workflow run, extract it, and open `SOLRDM-0.7.3-debug.apk`. Do not try
to install the ZIP or the separate instrumentation/test APK.

This build's package is `org.solrdm.app.debug` and its launcher label is
**SOLRDM Debug**. It installs alongside the older `org.solrdm.app` package. Each
app has its own private data. The new app does not automatically import the old
app's database, and the old app should remain installed to retain access to it.
The package requires Android 8/API 26+ on ARM64 or x86_64 Android. A Samsung S23
has the required ARM64 architecture; execution on that physical phone is not
established by emulator tests.

## Why the previous update could fail

The previously published APKs share `org.solrdm.app` but were generated on fresh
CI runners with different debug signing certificates. Android refuses to replace
an installed package with a differently signed APK. The detailed installer error
is `INSTALL_FAILED_UPDATE_INCOMPATIBLE`; a phone's installer may only display
“App not installed.” The original installed signing key is needed for a direct
update. Uninstalling removes private data and is not used as the fix here.

The regression workflow installs an old-package fixture and writes a private
sentinel. It proves a second APK with the same ID and another key is rejected,
then installs SOLRDM Debug and verifies both packages and the sentinel still
exist. It also reinstalls the identical Debug APK and verifies the new database
and neural state survive the compatible update.

## Persistent debug signing for future updates

To maintain one debug identity across CI runs, a repository administrator can set
these Actions secrets to an existing development keystore and its credentials:

- `SOLRDM_DEBUG_KEYSTORE_BASE64`
- `SOLRDM_DEBUG_STORE_PASSWORD`
- `SOLRDM_DEBUG_KEY_ALIAS`
- `SOLRDM_DEBUG_KEY_PASSWORD`

CI decodes a configured keystore only into the runner's temporary directory and
fails if its required credentials are absent. Gradle uses that keystore; no key
or password is printed, committed, or included in artifacts. Without these
secrets, Android's generated development key is used, and subsequent CI builds
may still be incompatible updates to an existing `org.solrdm.app.debug` install.
`build-info.json` records whether persistent signing was configured.

Configuring a new key cannot recover the key of an already installed APK. Keep
and reuse the same private keystore before distributing builds intended as
in-place updates. This workflow builds development APKs, not production releases.
