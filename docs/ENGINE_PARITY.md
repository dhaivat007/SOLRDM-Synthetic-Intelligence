# Supplied v0.7 engine integration and limits

The user supplied `SOLRDM_Android_FullEngine_v0_7_Source.zip`, SHA-256
`03fe799e305671542961d7cb689da9d18c9fd166fac88a07815f1632d9329e8c`.
It contains 16 `solrdm` Python source files plus an Android bridge and UI. All 16
are included in this app. This is provenance from the supplied archive, not an
independent claim that it matches an otherwise unavailable historical repository.
The archive contained no original test suite or APK and explicitly disclaimed
complete Android UI parity. Per-file original and integrated hashes are recorded
in `source-provenance.json`.

## Feature inventory

| Module / capability | Android exposure | Verification and remaining limits |
| --- | --- | --- |
| `__init__` and all 15 submodules | Imported by status and bridge commands | APK verification asserts all 16 compiled modules are packaged; emulator status asserts all 16 import. Import alone does not exercise every feature. |
| `core`: observations, query, inference, hypotheses | Save, Query, Generate hypotheses | SQLite records retain source/confidence; derived facts are not stored as observations. Host tests and emulator UI assertions cover a two-hop inference. Confidence combination is heuristic, not calibrated truth. |
| `english`: interpretation | Interpret English without saving | Limited patterns and explicit abstention on negation/uncertainty. Parsed candidates require a separate explicit observation. This is not general language understanding. |
| `neural`: from-scratch pair representations | Train on local observations | Real supplied training code runs. Weights, count, and RNG state persist; host tests and emulator restart assertions cover persistence. Similarity is not factual confidence. |
| `learning`: supervised rule induction | Bundled, no UI workflow | Host tests cover train/holdout cases, pending approval, approve/revoke and persistence. Not general self-learning. |
| `self_learning`: feedback/cycle | Bundled, no UI workflow | Host tests exercise bounded candidate proposals and boolean labels; approval remains separate. |
| `science`: linear relationships | Bundled, no UI workflow | Host tests exercise synthetic grouped measurements and holdout fit; observational relationships remain unverified. |
| `discovery_v05`: numerical hypotheses | Bundled, no UI workflow | Host tests cover candidates on authored synthetic measurements. Selection on the same small holdout is exploratory, not independent validation. |
| `language_learning`: intent classification and gates | Bundled, no UI training workflow | Host tests and synthetic benchmark exercise fit/predict/evaluate and rollback. The hashed classifier is not an LLM. |
| `compositional`: intent features | Bundled, no UI workflow | Exercised by host tests and supplied synthetic evaluation; no claim of general comprehension. |
| `agent_v06`: bounded proposed plan | Bundled, no UI workflow | Host tests cover abstention and proposed next actions; it does not execute autonomous tasks. |
| `internet`, `research`, `autonomy` | Bundled; network unavailable to app | Tests use synthetic injected transport and explicit review. Manifest has no Internet permission; no scheduler runs on import. Live web research is unverified and not enabled. |
| `benchmark`, `independent_eval` | CI/host tools, no UI workflow | Both execute against tiny authored synthetic datasets. Despite the latter filename, this is not a third-party independent benchmark. |

Complete Android feature parity is **not** claimed: advanced workflows remain
Python library capabilities with host tests. Android runtime verification covers
all module imports and the six exposed commands on API 35 x86_64. Physical-device,
ARM64, older Android, 16 KB page-size, and prolonged-use behavior need separate
runtime validation. There are no standalone Java unit tests; that Gradle task
reports NO-SOURCE.

## Integration changes

The archive's build/workflow files were not allowed to undo the verified SDK
package selection, API 35 target, lint/signature gates, or artifact verification.
The supplied six-command bridge was adapted to close each SQLite connection,
serialize work, isolate database paths, validate bounded inputs, preserve neural
state atomically, and expose errors without claiming success. Java executes it on
a background worker and avoids updating a destroyed activity.

The old `observations` table migrates to `facts` in one transaction with distinct
legacy-row provenance. A migration marker prevents duplicate migration, original
rows are retained, and the app keeps the files-directory database filename within its own sandbox.
Android 0.7.3 Debug has a separate application ID, so it does not automatically
read data from the old installed app. This isolation avoids deleting that data.
New observations with the same triple and source update that source's confidence.
Migration does not overcome Android signing-key mismatch between CI builds.

Confirmed source defects were repaired with regressions: symbolic inference now
retains the strongest evidence and strongest path independently of insertion
order; supervised feedback rejects non-boolean labels; corroboration rejects
missing/mixed claims instead of pooling unrelated evidence. Other supplied module
algorithms remain research prototypes. A further review fixed article/case/spacing
matching, abstention for compound and conditional statements, truthy-string
approval/corroboration bypasses, and self/unverified evidence validation. The
Android adapter normalizes entity matching without rewriting historical rows.

The Android adapter currently allows 1,000 observations, 100 rows per response,
inference over at most 100 observations and two rounds, and neural training over
at most 200 distinct pairs for 15 epochs per request. Existing data is retained
when a limit is reached. These are UI operation limits, not benchmark claims.

## Reproduce tests and benchmarks

```sh
python3 -m unittest discover -s tests -v
python3 scripts/benchmark_engine.py
```

`SOLRDM-build-evidence` contains `python-tests.log`, Gradle/lint evidence and
`engine-benchmarks.json`. The APK artifact also includes the benchmark JSON.
Symbolic and neural components are measured separately, with seeded synthetic
data, correctness/score metrics and elapsed time. Timings are runner-specific;
the neural toy data is not a generalization or intelligence benchmark. The supplied
language benchmarks report synthetic split sizes and limitations separately.

Use the matching successful workflow and its emulator evidence to establish what
actually ran. A module's presence in an archive or this document is not proof of
successful installation or full integration.
