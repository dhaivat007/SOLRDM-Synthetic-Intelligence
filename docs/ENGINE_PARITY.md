# SOLRDM Android engine scope and verification

The bundled Python code is an observation subset. It is **not the full historical
SOLRDM v0.7 intelligence engine**. A successful APK build or bridge smoke test does
not establish full engine integration or general intelligence.

## Available source

The starting Android source contains one Python module:
`app/src/main/python/android_bridge.py`, Git blob
`83ad333836e462f8f2ee9dfe2d0f8bfdaa90c40a`. It imports only Python's standard-library
`os`, `sqlite3`, and `re` modules. `MainActivity` invokes its `observe` function
through Chaquopy. There are no pretrained LLM dependencies.

No historical v0.7 Python modules or source archive were present in the supplied
workspace or this repository's starting source tree. References to v0.7 research
capabilities in prose are not executable source and do not establish parity.
The original v0.7 archive, its dependency versions, and original tests are needed
before those components can be imported, executed, tested, or benchmarked.

## Feature inventory

| Capability | Status in this APK's source | Evidence and limits |
| --- | --- | --- |
| Android-to-Python bridge | Implemented | `MainActivity` calls `android_bridge.observe`; on-device execution must be confirmed by the matching CI emulator test report. |
| Structured observation memory | Partial | Recognizes one ASCII English sentence pattern, `X is part of Y`, normalizes case, and appends a `part_of` relation to SQLite. |
| Durable SQLite storage | Working in host tests | Separate Python processes reopen the same database and retain previous observations. Android app process restart requires the separate emulator evidence. |
| Input rejection | Working in host tests | Unsupported patterns and inputs over 2,000 characters do not write observations. This is not a source validation or fact-checking system. |
| Observation retrieval | Partial | Returns the newly stored fact and total row count. No query interface, deduplication, or knowledge graph traversal is implemented. |
| General symbolic reasoning | Unavailable | No v0.7 inference module or rule engine is bundled; regex extraction is not inference. |
| Learned English intent model | Unavailable | No training or inference module is bundled. |
| Rule induction | Unavailable | No induction module is bundled. |
| Neural component | Unavailable | No custom neural source, model, training loop, or benchmark is bundled. |
| Scientific discovery | Unavailable | No discovery module or evaluation dataset is bundled. |
| Autonomous internet ingestion | Absent | The bridge performs no network requests. |

## Tests and benchmark limits

Run the host regression suite from the repository root:

```sh
python3 -m unittest discover -s tests -v
```

All eight tests passed on host Python 3.12.14 during development. They cover
normalization and optional articles, duplicate append behavior, rejection without
database writes, storage isolation, and persistence across two independent Python
processes. Test databases use temporary directories and are not committed.

The Android package uses its configured Chaquopy Python runtime. Host tests do
not prove that runtime starts, that an APK installs, or that the UI calls Python.
Use the exact build's instrumentation report and restart-smoke log for those
claims. Physical-device installation and ARM64 runtime behavior require separate
verification even when an x86_64 emulator passes.

Independent neural and full symbolic engine benchmarks cannot be run because
those components are absent. Timing the regex/SQLite bridge would not measure
their performance, and no substitute benchmark is presented as v0.7 parity.
