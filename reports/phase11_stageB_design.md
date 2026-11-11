# Phase 11 — Stage B: Design and Synthetic-Only Readiness Validation

Status: planning and synthetic validation only. **No real campaign was executed, no model was
fitted on scientific data, no real trial was generated, no sealed-test data was read, and
nothing was staged or committed.**

Authoritative interpreter: `webapp/backend/.venv/Scripts/python.exe` (Python 3.14.3).

Inputs reviewed: `reports/phase11_stageA_runner_report.md`,
`reports/phase11_runner_integration_design.md`,
`reports/phase11_task2_protocol_input_audit.md`,
`reports/phase11_protocol_v2_3_repin.md`.

---

## 1. Documentation correction applied

`reports/phase11_stageA_runner_report.md` §10 is now explicitly marked **HISTORICAL —
superseded by §11**: a note above the section states that A.1 removed the `manifest_dir` /
`repo_root` parameters and replaced the seven tests, the superseded parameter sentence is
struck through with a pointer to §11.1, the "7 functions / 8 collected" count is marked
historical with a pointer to §11.4, and the old test names are labelled historical. No code
or protocol was touched by this correction.

---

## 2. Synthetic validation vs real execution readiness

These are different claims and must not be conflated.

| Aspect | Synthetic validation — **available today** | Real execution readiness — **not available** |
|---|---|---|
| Data | Generated rows (`SYN-###`, `source="synthetic-fixture"`) in a temp directory | Kepler quarter flux, read through the frozen manifests |
| Model | None instantiated | Train on train windows, calibrate on validation nulls |
| Trial generation | One synthetic CSV exercising the marker/integrity contract | 720 injected + 152 null trials for the 5-day campaign |
| Access markers | Temp directories only | Real campaign directory, one-shot |
| Evaluation | None | Recall/FPR/comparison over sealed trials |
| Statistics | Unit-tested functions, no data | Wired to test results |
| Readiness flags | `campaign_ready: false`, `execution_ready: false` | Requires a decision that cannot be made by code |
| CLI modes | `preflight`, `synthetic` | No execution mode exists; `execute_real` always refuses |

The synthetic path proves the **gates and state machine**. It says nothing about scientific
validity, statistical power, or that a real run would succeed.

---

## 3. Gate-by-gate matrix

| ID | Prerequisite | Code location | Current evidence | Failure behaviour | Test coverage | Unresolved gap |
|---|---|---|---|---|---|---|
| G1 | Exact protocol identity | `phase11_v2.py:132` `load_protocol_v21`; pin `:55-57` | v2.3 hash `e1dc5cc9…`, sidecar, version, schema, 16 sections, 9 operative invariants | `GateError` before any read | repin suite (12), Stage A (pin mismatch) | none |
| G2 | Readiness declaration | `phase11_runner.py:78` `execution_blockers`; `:164` `execute_real` | frozen v2.3 yields 4 blockers; `execute_real` refuses unconditionally | `ReadinessError` | Stage A + Stage B (4 params + 3) | **No mechanism to declare readiness**; needs v2.4 or an explicit decision |
| G3 | Preconditions (output ≠ manifest dir, no markers, no fitted artifact, manifests/offsets hashes, provenance, clean tree) | `phase11_v2.py:594` `campaign_preconditions` | called by `preflight` (`phase11_runner.py:125`) and the v2 CLI | `GateError` before any trial read | repin, review, Stage A | none for preflight |
| G4 | Output isolation | `phase11_runner.py:94` `resolve_output_dir`; `safeguards.py:92/109/130` | protected dirs, frozen tree, v1 stage-0, campaign state, non-directory | `OutputIsolationError` | Stage A (32 incl. replicas/symlinks/aliases) | TOCTOU narrowed, not eliminated |
| G5 | Generation claim | `test_access.py:161` `claim_generation` | two consumers: the legacy `phase11.py:1084` path and the Stage A synthetic walkthrough (`phase11_runner.py:292`). **No v2 generator exists** — nothing yet produces a real `trials_test.csv` under the v2 protocol | `GateError` on any existing marker | access-closure (19) + Stage A | **v2 generator missing** |
| G6 | Access claim | `test_access.py:140` `claim_access` | consumed by legacy `phase11.py:996` and the synthetic walkthrough | `GateError`; requires completed generation | access-closure, Stage A | **No v2 evaluator exists** |
| G7 | Fitted state freeze/load | `phase11_v2.py:525` `freeze_fitted_v21`; `:565` `load_fitted_v21` | implemented; called by `phase11_b1.fit_synthetic`; payload is **nine keys** incl. `detector_thresholds` (**B4 amendment**) | `GateError`/`IntegrityError` | v2 stage-2 suite | **No campaign caller**; schema version stays 2, so an artifact without the detector table still loads but is refused at evaluation (fail-closed) |
| G8 | Threshold calibration | `phase11_v2.py` `calibrate_thresholds_v21` / `choose_threshold_v21`; `phase11.py:560` `calibrate_detector_thresholds` | implemented; called by `phase11_b1.fit_synthetic` for both the L7 table and the comparator table | | `GateError` (min n 30, missing/extra strata, test rows, degenerate) | v2 stage-2 suite + B1/B3 | B1 freezes the comparator table as the ninth key; a stratum below the minimum is reported as inconclusive, never pooled or relaxed |
| G9 | Generated-file integrity | `phase11_runner.py:187` `verify_generated_trials`; `:218` `load_authorized_trials` | completed marker + 64-hex hash + file hash + row count | `IntegrityError` | Stage A + B3 | consumed by `phase11_b3.evaluate_test`; the hash is re-verified after the access claim; hash→read TOCTOU |
| G10 | Provenance capture | `phase11_v2.py:488` `capture_provenance`; `:513` `require_clean_tree` | recorded by preflight (commit, dirty paths, input hashes, env); **B2a/B1 must pass it into `freeze_fitted_v21` unchanged and assert it after reload (§5.2)** | `GateError` on dirty tree or missing source | repin, Stage A | Not yet persisted into a v2 fitted artifact — a B1 requirement, not a follow-up |
| G11 | FPR and comparison statistics | `phase11_v2.py:639` `fpr_report`; `:814` `paired_comparison`; `:913` `combine_confirmatory` | implemented; MMD overrides refused; inconclusive gates | `GateError` / `inconclusive` | stage-2/3/4 suites | **Not wired to test results** |
| G12 | Refusal audit trail | none | stderr only | — | — | Persisted refusal record outside the protected tree; **implemented in B3, independently verified in B4 (§5.4)** |
| G13 | CLI surface | `phase11_runner.py:38` `MODES`; `:364` `main` | `preflight`, `synthetic`; other modes exit 2 | exit 2 / 3 | Stage A | No execution mode (intentional) |
| G14 | Source baseline | — | sources untracked at HEAD `230c5ae8…` | — | — | Commit needed for commit-anchored provenance |
| G15 | Test isolation | `tests/test_phase11_stageA_runner.py` | replicas for all write-capable cases | a failing test cannot write into the frozen tree | Stage A | none |
| G16 | Effective protocol view | to be implemented as **B0** (§5.6) | **absent**: v2.3 carries no `features`/`models`/`preprocessing`/`injection`/`seeds` and no code resolves `inherits_from_v1`; `injection` comes from the separately bound `experiment_config.json`, whose hash is read from the authenticated v2.3 `frozen_inputs` (documented evidence `43fbddc1…`) | `GateError` on v2.3 digest mismatch or unauthenticated payload, v1 hash mismatch, missing v1 file, missing inherited key, unknown inherited key, invalid manifest entry, or missing/malformed/hash-mismatched experiment config | B0 tests (to be added) | **Blocks B1**: `feature_columns`, `fit_models` and `calibrate_thresholds_v21` raise `KeyError` on the pinned payload |

---

## 4. Blockers that need a protocol revision or scientific authorization

| ID | Blocker | Why code cannot resolve it | What is required |
|---|---|---|---|
| B1 | Readiness declaration (`campaign_ready` / `execution_ready` false) | Flipping flags in the frozen v2.3 would change its hash and silently reinterpret a proposal | A **v2.4 protocol** (new artifact + sidecar + repin + independent review) or an explicit, documented decision that readiness is external to the protocol — which still needs a code change and review |
| B2 | Minimum meaningful difference unset | A scientific judgement about what difference matters | Explicit MMD decision; if non-null, a protocol revision, then a repin |
| B3 | Sealed-test access | One-shot and scientifically consequential | Explicit campaign authorization naming the operator, date, and single-run condition |
| B4 | Fitting on scientific data | Requires the real dataset and a reviewed fitting path | Code (**B0 + B2a + B1** of the sequence) plus authorization to run it |
| B5 | Timing tolerance 0.0377 rounding | Frozen choice affecting boundary trials | Protocol revision if it is ever to change; otherwise no action |

B1–B3 and B5 are **not** resolvable inside Stage B. B4 is implementable as code but not
runnable without B3.

---

## 5. Recommended safe sequence (no real execution)

The requirements in §5.1–§5.7 are **prerequisites for B0, B2a and B1–B3, not optional
follow-ups**. The order is **B0 → B2a → B1 → B2 → B3 → B4**, with the decisions in B5/B6 and
the authorization in B7. No step may use test-split or sealed-test rows for training, feature
selection, imputation, scaling or threshold calibration.

### 5.1 Feature-extraction ownership — DECIDED (neutral module)

Two feature builders exist today, each with its own callers:

| Function | Definition | Callers |
|---|---|---|
| `phase11.time_domain_features` | `phase11.py:1156` | `phase11.run_campaign` (`phase11.py:1128`) |
| `experiment.time_domain_features` | `experiment.py:72` | the Phase 10 pipeline (`experiment.py:271`) |

Their bodies are **AST-identical** apart from the docstring, so unification is
behaviour-preserving — but extraction must cover **both** copies, not just the `phase11` one.

`core.detect` (`core.py:102`) and `ti.inject_transit` (`transit_injection.py`) already live in
dependency-light modules and need **no extraction**; v2 imports them directly. The only code
that must move is the duplicated feature builder.

| Option | Advantages | Costs / risks |
|---|---|---|
| (a) import `phase11.time_domain_features` directly from the v2 fitter/generator | no duplicated science | creates a v2 → v1 dependency; `phase11.py` also hosts the legacy campaign/evaluation entry points |
| (b) move the feature builder into a neutral module and re-export it from both `phase11.py` and `experiment.py` | preserves isolation; one implementation with two compatible names | a mechanical move needing bit-identity evidence |

**Decision (frozen, not deferred to B1): adopt (b).** B2a performs the extraction as its first
task: move the feature builder into a neutral, dependency-light module; re-export it as
`phase11.time_domain_features` **and** `experiment.time_domain_features` so both existing
callers keep working unchanged; and prove **bit-identical output on synthetic arrays** for
both the feature vector and the detector result before any consumer uses it.

**Pre-decided fallback:** if, and only if, the bit-identity check fails in a way that cannot be
resolved without a behavioural edit, adopt (a) and record the v2 → v1 coupling in G7/G8 of the
matrix. The branch taken must be written into the B2a report before B1 starts; it may not be
chosen silently during B1.

### 5.2 Provenance is part of B2a/B1

`freeze_fitted_v21` (`phase11_v2.py:525`) requires a `provenance` argument, and
`capture_provenance` (`phase11_v2.py:488-511`) takes exactly:

```
repo_root, source_paths=[...], protocol_sha256=<pin>,
manifest_hashes={<five manifest names>: <hash>}, offsets_sha256=<hash>
```

(the five manifests are `split`, `windows_primary`, `windows_sensitivity`, `null_library`,
`experiment_config`; the protocol separately binds nine *files*, which is a different count).

B1 must:

1. call `capture_provenance` with those exact arguments (repo root, enumerated runner sources,
   the v2.3 protocol hash, the five manifest hashes and the offsets hash) and require a clean
   tracked tree first;
2. pass that block **unchanged** into `freeze_fitted_v21` — no trimming, no substitution, no
   stub;
3. test that `fitted.json` contains the block and that `protocol_sha256` equals the active pin;
4. test that the block is **still present and equal after `load_fitted_v21` reload**, i.e. the
   loaded payload's `provenance` deep-equals what was captured;
5. test two failure paths: a dirty tracked tree aborts the freeze, and a missing source entry
   aborts capture (`GateError` in both cases).

A stub or empty provenance dict is a gate failure, not a shortcut (G10).

### 5.3 The no-execution invariant for B0–B3

B0–B3 add capability, never authority:

- no new CLI mode; `MODES` stays `("preflight", "synthetic")` (`phase11_runner.py:38`);
- `execute_real` keeps its unconditional `NoReturn` refusal (`:164-181`); it is not edited,
  parameterised, feature-flagged or bypassed;
- no new entry point reaches fitting, generation or evaluation without the same gates;
- protocol resolution (B0) produces a configuration view only; it grants no execution right and
  does not touch readiness flags;
- **B4 must verify all four** by test and by inspection, and must fail the review if any
  changed.

### 5.4 G12 refusal audit trail — implemented in B3, verified in B4

**B3 implements it** (a review step cannot). Persist refusal records outside the protected
tree, naming the failing gate, protocol hash, configuration hash and timestamp; a refused
attempt must leave a durable trace.

**B4 verifies it** by inspection and by a synthetic refusal test, and records the artifact
path and hash. If B3 and B4 jointly decide the debt is acceptable instead, B4 must record that
decision and its risk explicitly: a refused attempt would leave no durable trace beyond
stderr, weakening post-hoc provenance for near-miss events.

### 5.5 Synthetic-only guard test (entry criterion for B0, B2a, B1, B2 and B3)

The guard must prove that no synthetic code path opens real source data, **without** blocking
the authorized reader of the generated trial file.

**Real-data paths to intercept (enumerated from the current source):**

| Path | Location | Role |
|---|---|---|
| `generalization.load_quarter` | `generalization.py:219` (`pd.read_csv` at `:221`) | the funnel that reads a quarter CSV |
| `generalization.quarter_files` | `generalization.py:201` | builds the quarter-id → path map |
| `generalization.build_manifests` | `generalization.py:359-369` | calls `quarter_files`/`load_quarter` while building manifests |
| `phase11._load_window_series` | `phase11.py:1044-1047` | loads a quarter and slices a window |
| `core.load_curve` | `core.py:57-66` | builds `data/processed/…` directly and calls the transit-injection loader |
| `transit_injection.load_light_curve` / `_load_cached` | `transit_injection.py:161-175` (`pd.read_csv` at `:165`) | the CSV reader behind `core.load_curve` |

**Allowed read:** `phase11_runner.load_authorized_trials` (`phase11_runner.py:225`) reading
the generated `trials_test.csv` under a temporary campaign directory.

**Required guard shape:** monkeypatch the six paths above to raise, and additionally make any
`pandas.read_csv` whose target resolves under `data/processed` raise. Run the B0/B2a/B1/B2/B3
entry points on synthetic fixtures and require success; then assert that
`load_authorized_trials` still reads the generated file successfully. A path that needs
`data/processed` fails the test; a blanket block of all CSV reads would fail the second half
and is therefore explicitly rejected.

**Out of scope:** `app.py:333` / `app.py:595` and the Phase 10 reader `reports.py:419` also read
data, but neither module is on the B0–B3 import graph, so they are excluded from this inventory
and are not modified.

### 5.6 Protocol resolution — `effective_protocol(v2_3)` (step B0, before B2a)

**Why it is required.** The pinned v2.3 artifact is deliberately partial: it carries no
`features`, `models`, `preprocessing`, `injection` or `seeds` block and instead references v1
through `inherits_from_v1` (`rule`, `features`, `preprocessing`, `models`, `seeds`,
`campaign_modes`, `campaign_order`, `note`). Nothing in the code resolves that reference
today, so the functions B1 must call fail on the pinned payload:

- `phase11.feature_columns` → `KeyError: 'features'` (`phase11.py:491-499`);
- `phase11.fit_models` → dereferences `protocol["preprocessing"]["fit_splits"]` (`:511`),
  `protocol["thresholds"]["fitted_models"]["floor_snr"]` (`:633`), `protocol["models"]`
  (`:651`) and `protocol["features"]["sets"]` (`:656`);
- `phase11_v2.calibrate_thresholds_v21` → `protocol["injection"]["noise_conditions"]`
  (`phase11_v2.py:386`);
- the legacy detector calibration also reads `protocol["thresholds"]["detector"]["floor_snr"]`
  (`phase11.py:581`).

**Where `injection` comes from.** `injection` is not supplied by either protocol: it is absent
from v2.3, absent from v1, and is not named in `inherits_from_v1`. The only frozen artifact
that carries it is `reports/phase11_generalization/experiment_config.json`, whose bytes are
already bound in v2.3's `frozen_inputs.files["experiment_config.json"]` (recorded value
`43fbddc15c74c6262db9b56652ed393aca0ea4849d6b2f2df072d28079e7b4ce`, verified to match the
file). B0 therefore takes `injection.noise_conditions` from that verified config — a
separately bound frozen input, **not** an inherited v1 block — and the six-block v1 whitelist
below is unchanged.

**Required design — two layers.** B0 is split so that authentication is explicit and the merge
is testable without touching repository paths:

- **`resolve_effective_protocol(manifest_dir, *, protocol_path=None, v1_path=None,
  experiment_config_path=None) -> tuple[dict, dict]`** — the file-level entry point. It performs
  every read and authentication: v2.3 through `phase11_v2.load_protocol_v21` against
  `AUTHORIZED_PROTOCOL_SHA256`, v1 through `phase11.load_frozen_json` against
  `ded2bd5e…75319f`, manifest-entry validation, and config byte hashing; the config is parsed
  only after its bytes match the authenticated manifest entry. Paths derive from `manifest_dir`
  (default names `protocol_v2_3.json`, `protocol.json`, `experiment_config.json`) or from
  explicitly supplied test-fixture paths. The repository config path is never hard-coded as an
  independent authority; the authenticated v2.3 manifest entry is the sole runtime authority for
  the config hash.
- **`effective_protocol(protocol_v2_3, protocol_v2_3_sha256, protocol_v1, protocol_v1_sha256,
  experiment_config, experiment_config_sha256) -> dict`** — the pure merge. It performs no file
  I/O, re-verifies the supplied digests against the two pins, and applies the copy, floor,
  validation and provenance rules below.

Together the two layers must:

1. **authenticate before reading.** The loader obtains v2.3 through
   `phase11_v2.load_protocol_v21` (`phase11_v2.py:132`) and requires its digest to equal
   `AUTHORIZED_PROTOCOL_SHA256` (`e1dc5cc9…`, `:55-57`); a caller-supplied `protocol_v2_3`
   mapping without that authenticated origin and matching digest is refused, so the manifest
   consulted in step 5 is always the authenticated one. It obtains v1 through
   `phase11.load_frozen_json` (`expected_phase="11b"`, `expected_schema=1`) and requires its
   digest to equal `ded2bd5eea3cfb3cbd5af0b67e439a767584b9bf508f02afe2a4b5d56a75319f`. The
   pure merge re-checks both supplied digests against the same pins and refuses any mismatch;
2. copies **only** the six designated inherited blocks into a new dict — `features`,
   `preprocessing`, `models`, `seeds`, `campaign_modes` → `campaign.modes`, and
   `campaign_order` → `campaign.order` — leaving every v2.3 block untouched. The accepted key
   set is a **hard-coded whitelist**; it is never derived by iterating `inherits_from_v1`.
   `inherits_from_v1.rule` and `inherits_from_v1.note` are **prose metadata**, not
   configuration blocks and not JSON pointers, and are never copied. v1's `thresholds` block is
   deliberately outside the whitelist because v2.3 supersedes it;
3. **fails closed on unknown inherited configuration:** if `inherits_from_v1` contains any key
   outside that six-key whitelist (other than the prose keys `rule` and `note`), resolution
   raises `GateError` naming the key. An entry that appears to request inheritance is never
   silently discarded;
4. builds the two compatibility views the v1 functions expect **from v2.3's own fields**, not
   from v1: `thresholds.detector.floor_snr` from `thresholds.floor_snr_detector` (currently
   `3.0`), and `thresholds.fitted_models.floor_snr` from `thresholds.floor_snr_l7`. The v2.3
   value is `floor_snr_l7: null`, so the resolved value is **`None`**; B1 must preserve `None`
   and must not substitute `3.0`, inherit a v1 floor, or invent any fallback. v1's own
   `thresholds.fitted_models` rule is superseded and must not be inherited;
5. validates the manifest entry, then loads the config:
   - `frozen_inputs` must be a mapping whose `files` is a mapping; any other shape raises
     `GateError`;
   - `files["experiment_config.json"]` must exist, be a `str`, and be exactly 64 lowercase
     hexadecimal characters (`^[0-9a-f]{64}$`). Missing, wrong-type, malformed or otherwise
     invalid entries raise `GateError`;
   - **the runtime authority is that authenticated manifest entry.** The value
     `43fbddc15c74c6262db9b56652ed393aca0ea4849d6b2f2df072d28079e7b4ce` is recorded here as
     documented verification evidence only — never a fallback constant or a second source of
     truth;
   - a duplicate JSON manifest key cannot survive this gate undetected: any byte-level change
     to the pinned v2.3 payload changes its hash and fails step 1 before the manifest is read.

   The loader then reads the config file named by `experiment_config_path` (default
   `manifest_dir / "experiment_config.json"`), hashes the **exact bytes** and compares them with
   the manifest entry **before parsing**; a mismatch raises
   `GateError`. This is a separately bound frozen input, not an inherited block. From the
   parsed config copy **only** `injection.noise_conditions`, producing
   `effective["injection"] = {"noise_conditions": [...]}`; nothing else is copied, so it cannot
   override protocol blocks, thresholds, features, models or preprocessing. Unreadable bytes,
   malformed JSON or structurally invalid content — not an object, no `injection` mapping,
   absent/empty `noise_conditions`, or non-string entries — also raises `GateError`. There is
   no fallback to v1, to v2.3 or to any other file;
6. validates the merged view for **every configuration key consumed downstream** —
   `features.sets`, `features.forbidden`, `features.detector_outputs` and
   `features.flux_features` (`feature_columns`, `_default_factory`),
   `preprocessing.fit_splits` (`assert_fit_splits`), `injection.noise_conditions`
   (`calibrate_thresholds_v21` and the detector calibration), `models.*`,
   `thresholds.target_fpr`, `thresholds.min_calibration_n_per_stratum`
   (`calibrate_thresholds_v21`), `thresholds.detector.floor_snr` and
   `thresholds.fitted_models.floor_snr` — and raises `GateError` naming the first missing key;
7. returns a new dict (never mutates any input) recording the v2.3 hash, the v1 hash, the
   experiment-config hash and the block list copied, so the effective view can be reproduced
   and audited;
8. reads no trial data and grants no execution authority.

**Runtime availability.** Three frozen artifacts must remain present and byte-identical at run
time: `reports/phase11_generalization/protocol_v2_3.json` (the pin),
`reports/phase11_generalization/protocol.json` (the inherited-configuration source) and
`reports/phase11_generalization/experiment_config.json` (the `injection` source). Resolution
fails closed if any is missing, unreadable or hash-mismatched. No artifact is edited: v2.3
stays the pin, v1 supplies only the six whitelisted blocks, and the experiment config supplies
only `injection.noise_conditions`.

**Tests (B0 exit criteria):** successful resolution of the pinned triple with every required
key present and all v2.3 blocks unchanged; **`GateError` when the v2.3 digest differs from
`AUTHORIZED_PROTOCOL_SHA256` or the payload was not obtained through `load_protocol_v21`**;
`GateError` on a v1 hash mismatch; `GateError` when an inherited key is removed (synthetic
mutation); `GateError` when an unknown key is added to `inherits_from_v1` (no silent discard);
`GateError` when the v1 file is absent; **`GateError` when the manifest entry is missing,
non-string, not 64 lowercase hex characters, or when `frozen_inputs`/`files` are not
mappings**; **`GateError` when the experiment config is missing, unreadable, hash-mismatched
against `frozen_inputs`, malformed JSON, or structurally invalid**; an assertion that the
experiment config's only contribution is `injection.noise_conditions` (no other key from it
appears in the effective view); an assertion that no input dict was mutated; and an assertion
that the resolved `thresholds.fitted_models.floor_snr` is `None` — the v2.3 `floor_snr_l7`
value — and is not `3.0`. **Resolution grants no execution authority**: `execute_real` still
refuses and no CLI mode changes.

### 5.7 B2a — synthetic fit-split trial builder (after B0, before B1)

**Why it exists.** B1 trains on train windows and calibrates on validation nulls, so it needs
per-window feature rows **with injected labels** for the *fit* split. The B2 generator writes
the *test* split and is not a substitute.

**Inputs (synthetic only):** a temporary output directory; a row count or a small synthetic
window specification; a deterministic seed; the **resolved** protocol view from B0; and a split
map restricted to `train` and `val`.

**Outputs:** an in-memory `DataFrame` (and optionally a temporary CSV) carrying the frozen
feature columns (`snr`, `depth_est_ppm`, `sigma_ppm`, `std_ppm`, `mad_ppm`, `mean_flux`), the
label `injected`, and the metadata columns (`split`, `quarter`, `role`, `trial_id`,
`requested_depth_ppm`, `noise_condition`, `source="synthetic-fixture"`), produced from
synthetic time/flux arrays through the shared detector decided in §5.1. No path under `data/`
is opened.

**Contract requirements (each with a test):**

- **null windows are mandatory** in both `train` and `val` (role `null_window`,
  `injected=False`, `requested_depth_ppm=0.0`). `fit_models` calibrates L7 on validation nulls
  and raises "validation nulls are required to calibrate the threshold" if there are none
  (`phase11.py:620-622`), and `calibrate_thresholds_v21` filters on `role`;
- **label invariant:** `injected == (requested_depth_ppm > 0)` for every row, and null windows
  are `injected=False`; asserted before returning;
- **split enforcement:** call `phase11.assert_fit_splits(frame, effective)` (`phase11.py:507-514`)
  on the finished frame — it refuses any split outside `preprocessing.fit_splits | {"val"}` —
  in addition to the pre-construction guard that refuses `test` before any row is built;
- **disjointness:** train, validation and test roles never share rows; `test` rows are refused
  before construction, and B1 asserts its frame contains only `train`/`val`;
- writes only under a temporary directory through `resolve_output_dir`; creates **no** markers
  (`test_generation.json` / `test_access.json` belong to B2/B3);
- runs behind the §5.5 guard.

**Hand-off to B1.** B2a produces rows; B1 produces the fitted payload. `freeze_fitted_v21`
dereferences exactly **nine** keys: `model_id`, `features`, `dropped_features`,
`imputation_medians`, `thresholds`, `detector_thresholds`, `train_rows`, `val_rows`,
`train_injected`. B1's tests must assert all nine are present, that `thresholds` is the
per-stratum table produced by `calibrate_thresholds_v21`, and that `detector_thresholds` is the
per-stratum table produced by `phase11.calibrate_detector_thresholds` on the same train+val
nulls. The ninth key is the B4 amendment (see the correction log): the physics comparator needs a
frozen operating point, and calibrating it from test data is forbidden by the protocol.

**Tests:** `test`-split input refused before construction; label invariant; `assert_fit_splits`
green and red on an injected `test` row; null windows present in both splits; fixed seed gives
identical output; the feature set matches the resolved L7 columns; §5.5 green; the frame flows
through B1's fit → calibrate → freeze round trip.

**Exit criteria:** split guard, label invariant, null-window presence, determinism, L7 columns,
§5.5 and the recorded "no test-split rows" statement all green. B1 does not start until these
pass.

### 5.8 Sequence

| Step | Work | Exit criterion | Real data? |
|---|---|---|---|
| **B0** | §5.6 two layers — `resolve_effective_protocol` (file-level: authenticate v2.3 through `load_protocol_v21` against `AUTHORIZED_PROTOCOL_SHA256`, hash-verify v1, validate the `experiment_config.json` manifest entry, hash-verify config bytes before parsing) and pure `effective_protocol` (six-block whitelist copy with unknown keys rejected, copy only `injection.noise_conditions`, derived floors, key validation) | pinned triple resolves from any manifest directory or fixture path with all v2.3 blocks unchanged and every required key present; L7 floor resolves to `None`; **v2.3 digest mismatch or unauthenticated payload**, v1 hash mismatch, missing inherited key, unknown inherited key, missing v1 file, invalid manifest entry, and missing/malformed/hash-mismatched experiment config all fail closed; inputs not mutated; no execution authority granted | no |
| **B2a** | §5.1 extraction with a bit-identity gate; §5.7 synthetic fit-split builder (train/val, null windows mandatory) | extraction bit-identical or the pre-decided fallback recorded; split guard, label invariant, null windows, determinism and §5.5 green; no markers created | no |
| **B1** | v2 fitting path on the B0 view: train on B2a's train rows, calibrate on validation nulls via `calibrate_thresholds_v21`, freeze the comparator's detector thresholds via `phase11.calibrate_detector_thresholds`, capture provenance (§5.2), persist the nine-key payload via `freeze_fitted_v21` | frame asserted train/val only; synthetic round trip fit → freeze → `load_fitted_v21` → hash; all nine keys present (incl. `detector_thresholds`); provenance present, hash-bound **and equal after reload**; dirty-tree and missing-source aborts green; forbidden-feature and split-isolation gates green; §5.5 green | no |
| **B2** | v2 **test-split** generator behind `claim_generation`, writing `trials_test.csv` and completing with its hash | duplicate/interrupted claims refused; `verify_generated_trials` green; integrity tamper test; no execution mode added (§5.3) | no (synthetic arrays) |
| **B3** | evaluator consuming `load_authorized_trials` only; claim access first; emit FPR/recall/comparison artifacts via `fpr_report` / `paired_comparison`; **implement G12 (§5.4)**; assert the trial file never reaches training | no caller-supplied DataFrame path; second evaluation refused; inconclusive gates proven on synthetic scores; G12 records written; §5.5 green | no |
| **B4** | Independent review of B0–B3 + full focused safety suite + gate-matrix re-check + §5.3 invariant verification + **G12 verification** (not implementation) + §5.4 debt decision if applicable | review PASS, §5.3 verified, G12 artifact inspected, 21/21 artifacts unchanged, hashes recorded | no |
| **B5** | Decide B1 (readiness), producing v2.4 or a documented external-readiness decision | protocol revision reviewed and repinned, or decision recorded | no |
| **B6** | Decide B2 (MMD) | explicit value or a recorded decision to stay descriptive-only | no |
| **B7** | Separate explicit authorization for the real campaign | authorization document + clean tree + committed source baseline | **yes** |

No step before B7 may read, generate or evaluate sealed trials. B0 resolves configuration only
and grants no execution authority.

---

## 6. Verification performed in the Stage B pass

(The figures below are from the Stage B implementation pass. The documentation corrections to
this file ran no tests.)

```
cd webapp/backend
.venv/Scripts/python.exe -m pytest tests/test_phase11_stageB_readiness.py -q
→ 7 passed              (4 parametrised readiness conditions + 3 separation tests)

.venv/Scripts/python.exe -m pytest \
  tests/test_phase11_stageB_readiness.py tests/test_phase11_stageA_runner.py \
  tests/test_phase11_protocol_repin.py tests/test_phase11_access_closure.py \
  tests/test_phase11_stage4_guards.py -q
→ 96 passed

ruff check tests/test_phase11_stageB_readiness.py        → All checks passed
ruff format --check (same file)                          → already formatted
git diff --check                                         → clean
```

New tests (`tests/test_phase11_stageB_readiness.py`):

| Test | Proves |
|---|---|
| `test_each_readiness_condition_is_required[×4]` | each of campaign_ready, execution_ready, status text and proposal_record independently produces a blocker |
| `test_no_blockers_when_every_readiness_condition_is_satisfied` | the blocker function is not trivially always-failing |
| `test_execute_real_refuses_even_when_the_protocol_claims_ready` | a fabricated all-ready protocol does **not** unlock execution; the Stage A hard gate is independent of flags |
| `test_preflight_may_report_authorized_but_execution_still_refuses` | `execution_authorized: true` is reporting only; execution still refuses, and preflight writes nothing |

### Artifact state

| Item | Value |
|---|---|
| `protocol_v2_3.json` | `e1dc5cc9ed4e6e2dc4645a82efc4f7638fb0f3128248b9810c67ba339f32c154` (sidecar OK) |
| `protocol.json` (v1, inherited-configuration source) | `ded2bd5eea3cfb3cbd5af0b67e439a767584b9bf508f02afe2a4b5d56a75319f` |
| 21 protected artifacts | 21/21 byte-identical to baseline |
| Campaign dirs / markers / trial files under `reports/` | 0 / 0 |
| `phase11_runner.py` | `331b983bde34cc465e7a0cf6e7e343c11491507db1b7a202b0645ab2d570ee35` (unchanged) |
| `tests/test_phase11_stageB_readiness.py` (new) | `41d05afa59071c55689c3b63affa7bec0207e8ecefbb42474e8c4e7b136886e3` |
| `reports/phase11_stageA_runner_report.md` (corrected) | `ebf2d300bdf6e11f56012054d5113631ee89c7fb91905fc9944d03ced3ee0b95` |
| Git | HEAD `230c5ae8…`, 0 staged, three earlier tracked modifications untouched, no new commits |

---

## 7. Residual risks

1. **TOCTOU** between output validation and directory creation is narrowed, not removed;
   eliminating it needs descriptor-relative operations.
2. **The gate matrix is a snapshot.** Any Stage B implementation must re-derive it and prove
   each row again; this document is not evidence that future code keeps the gates.
3. **No evaluator exists**, so the integrity contract has a producer and unit tests but no
   consumer. Its value depends on B3 landing behind it.
4. **Readiness ambiguity**: if external readiness is chosen instead of v2.4, the protocol text
   would still say "proposal only", which is a documentation trap for future operators.
5. **Untracked sources** mean provenance is hash-based; a commit is a prerequisite for a
   defensible run record.
6. **Synthetic evidence is not scientific evidence.** Nothing here supports a claim about
   detection performance, and none is made.
7. **Feature ownership is decided but unproven** (§5.1): the extraction must pass the
   bit-identity gate before B1. If it does not, the pre-decided fallback applies and the
   v2 → v1 coupling becomes a recorded, reviewed risk rather than a silent dependency.
8. **G12 is assigned, not implemented** (§5.4). B3 must land refusal records and B4 must verify
   them; until then near-miss events leave no durable trace beyond stderr.
9. **B2a is a design only.** If its implementation diverges from the shared §5.1 module (for
   example a parallel feature calculation), B1's synthetic results would not represent the
   real path. B2a must call the shared module, and B4 must check that it does.
10. **Protocol resolution is unproven (B0).** A whitelist copy could still be too broad or too
    narrow: too broad would let v1 shadow a v2.3 rule, too narrow would leave a `KeyError` for
    B1. Mitigations: explicit block whitelist, a test that every v2.3 block is unchanged, and
    the derived-floor compatibility views built only from v2.3's own fields.
11. **The v1 protocol file becomes a runtime dependency** of B0. It is frozen and committed,
    but a future relocation or "cleanup" of `reports/phase11_generalization/protocol.json`
    would break resolution; the failure is a clear `GateError`, not a silent fallback.
12. **A second source is now bound into resolution.** `injection.noise_conditions` comes from
    `experiment_config.json`, so B0 depends on three frozen files instead of two. The hash is
    taken from v2.3's `frozen_inputs`, not hard-coded independently, so the two cannot drift
    silently — a mismatch is a `GateError`. Residual risk: the effective view is only as
    trustworthy as that manifest entry, and the copy rule (only
    `injection.noise_conditions`) must be tested so the config cannot leak unrelated keys into
    the protocol view.

Stage B planning is complete and carries the §5.1–§5.7 prerequisites, with §5.8 fixing the
order (B0 → B2a → B1 → B2 → B3 → B4 → B5/B6 → B7). No real execution is authorized, and B0,
B2a and B1 are not started.

---

## 8. Correction log (documentation passes)

### First pass

| Issue raised by the independent review | Correction |
|---|---|
| B1 had no source of fit-split trial rows; B2 (test split) is not a substitute | §5.7 and step **B2a** placed before B1; table, G-matrix references and risks updated |
| §5.1 left the feature decision conditional during B1 | decision **frozen** on the neutral module with a bit-identity gate; fallback pre-decided and required to be recorded in the B2a report |
| §5.2 said "nine manifest/offset hashes" and omitted the reload assertion | parameter structure corrected to five manifest hashes + protocol hash + offsets hash; unchanged propagation, persisted block, reload equality and the two failure tests added |
| §5.5 blocked "any CSV reader" and named only `load_quarter` | four source-data paths enumerated, scoped to `data/processed`, with the generated trial read explicitly allowed and required to keep working |
| G12 was assigned to a review step | implementation assigned to **B3**, independent verification to **B4**; debt path kept but only with an explicit recorded decision |
| Sequencing was incoherent (B1 before its builder; review implementing code) | order *at that time* became **B2a → B1 → B2 → B3 → B4 → B5/B6 → B7**, with the data-separation invariant at the head of §5. **Superseded by the second pass**, which places **B0** (protocol resolution) first; §5.8 is authoritative |

### Second pass (this correction)

| Issue raised by the independent review | Correction |
|---|---|
| v2.3 has no `features`/`models`/`preprocessing`/`injection`/`seeds`, and no code resolves `inherits_from_v1`; `feature_columns`, `fit_models` and `calibrate_thresholds_v21` raise `KeyError` | new §5.6 and step **B0**: `effective_protocol(v2_3)` with a v1 hash gate (`ded2bd5e…`), whitelist copy of the inherited blocks, derived `detector`/`fitted_models` floor views taken from v2.3's own fields, key validation, and four failure tests; G16 added to the matrix |
| B2a did not require null windows, so B1's calibration would fail (`phase11.py:620-622`) | null windows mandatory in train and val; label invariant `injected == (requested_depth_ppm > 0)`; `phase11.assert_fit_splits` named as the split enforcer; disjointness stated |
| The eight `freeze_fitted_v21` payload keys were unstated | listed explicitly in §5.7's hand-off and in B1's exit criterion |
| §5.1 named one feature implementation; a second AST-identical copy exists in `experiment.py` | both implementations and their callers tabulated; extraction must re-export both names; `core.detect` / `ti.inject_transit` stated as already neutral and not extracted |
| §5.5 omitted two real-data funnels | `core.load_curve` (`core.py:57-66`) and `transit_injection.load_light_curve` / `_load_cached` (`:161-175`, `:165`) added to the table and the guard test |
| Sequence omitted the resolution prerequisite | order is now **B0 → B2a → B1 → B2 → B3 → B4 → B5/B6 → B7**, with B0's exit criteria and two new risk entries (§7.10–7.11) |

### Third pass (this correction)

| Issue raised by the final review | Correction |
|---|---|
| The validation list omitted `thresholds.min_calibration_n_per_stratum`, consumed by `calibrate_thresholds_v21` | §5.6 step 5 now lists every consumed key and states the list covers all downstream consumers |
| Unknown `inherits_from_v1` keys would be silently ignored | §5.6 step 3 adds a fail-closed rule: unknown keys raise `GateError`; the six-block whitelist is explicit and hard-coded |
| `inherits_from_v1.rule` / `.note` ambiguity | §5.6 step 2 states they are prose metadata, not blocks and not JSON pointers, and are never copied; the implementation is explicitly **not** key-driven |
| The derived L7 floor `None` was unstated | §5.6 step 4 and the B0 test/exit criteria state `floor_snr_l7: null` resolves to `None`, that B1 must preserve it, and that `3.0` or a v1 floor must not be substituted |
| `app.py` / `reports.py` readers not placed out of scope | §5.5 adds one sentence: neither module is on the B0–B3 import graph, so both are excluded and unmodified |

### Fourth pass (this correction)

| Issue found during B0 implementation | Correction |
|---|---|
| §5.6 step 5 required `injection.noise_conditions`, but `injection` exists in neither protocol and is not in `inherits_from_v1`, so a six-block resolution could not satisfy its own validation | §5.6 now sources that block from `experiment_config.json` — a separately bound frozen input, **not** an inherited block — with the hash taken from v2.3's `frozen_inputs.files["experiment_config.json"]` (verified to match the file); a new "Where `injection` comes from" paragraph states why the six-block whitelist is unchanged |
| No fail-closed rule existed for the config source | §5.6 step 5 requires verification of the config bytes against the manifest entry before parsing, and rejects missing, unreadable, hash-mismatched, malformed or structurally invalid configuration with `GateError`; there is no fallback |
| The config could have been copied wholesale into the protocol view | §5.6 step 5 copies **only** `injection.noise_conditions`, so the config cannot override protocol blocks, thresholds, features, models or preprocessing; a test asserts that no other config key appears in the effective view |
| Provenance did not name the third source | §5.6 step 7 records the v2.3, v1 and experiment-config hashes plus the copied block list; the runtime-availability paragraph now names all three frozen files |
| Matrix and exit criteria lagged the new source | G16 row and the B0 sequence row now include the config hash check and its failure modes; risk 12 records the two-source dependency and its residual risk |

### Fifth pass (this correction)

| Issue raised by the final review | Correction |
|---|---|
| The verification chain had no authenticated root: B0 never required the v2.3 payload itself to be the pinned, loader-authenticated one | §5.6 step 1 now requires v2.3 to come from `load_protocol_v21` with digest equal to `AUTHORIZED_PROTOCOL_SHA256`, and refuses a caller-supplied dict without that origin and digest; the signature carries the v2.3 digest; the B0 sequence row lists "authenticate v2.3" first and its exit criteria include v2.3 digest mismatch / unauthenticated payload |
| Manifest-entry validity was unspecified; fail-closure was only implied by comparison | §5.6 step 5 now requires `frozen_inputs` and `files` to be mappings, requires the entry to exist and be exactly 64 lowercase hex characters, and raises `GateError` otherwise; the config bytes are hashed and compared against that entry before parsing |
| The quoted `43fbddc1…` could be mistaken for the authority | §5.6 step 5 labels it **documented verification evidence only**, states that the authenticated manifest entry is the runtime authority, and forbids any fallback constant or second source of truth |
| Duplicate manifest keys were unaddressed | §5.6 step 5 adds one sentence: a duplicate key cannot survive the gate undetected because any byte-level change to the pinned v2.3 payload fails step 1 before the manifest is read |


### Sixth pass (pre-implementation)

| Issue raised by the final review | Correction |
|---|---|
| §5.6 described a "pure function" that also read the config file from a hard-coded repository path, which is contradictory and made synthetic-fixture testing impossible | §5.6 now defines two layers: `resolve_effective_protocol(manifest_dir, *, protocol_path=None, v1_path=None, experiment_config_path=None)` performs every read and authentication (v2.3 pin, v1 pin, manifest entry, config bytes before parsing) with paths derived from `manifest_dir` or explicit fixture paths, and the pure `effective_protocol(...)` receives the authenticated payloads, the parsed config and all digests, performs no I/O, and re-checks the digests |
| Step 1 narrated authentication as part of the merge | Step 1 now attributes authentication to the loader and digest re-checking to the pure merge; step 5 attributes the config read to the loader with a parameterised path |

### Seventh pass (B4 review — payload amendment recorded)

| Item found in the B4 review | Record |
|---|---|
| `freeze_fitted_v21` dereferenced eight keys, but B3's confirmatory contrast is L7 minus the physics detector **at its calibrated per-stratum threshold**, and no frozen artifact carried that table: the v2 and v1 fitted payloads each persist only the L7 table, and `phase11.calibrate_detector_thresholds` had no production caller. B3 could not obtain the comparator without reading test data, which `thresholds.test_controls_excluded` forbids | the payload is amended to **nine keys**: `detector_thresholds` is calibrated by B1 on the same train+val nulls via `phase11.calibrate_detector_thresholds`, required by `freeze_fitted_v21` (`GateError` when absent), compacted by the new `phase11_v2.detector_table` and persisted inside `fitted.json`, so it is covered by the existing `fitted.sha256` sidecar; §5.7's hand-off and the B1 row above now say nine |
| Whether the payload amendment needs a schema-version bump | `FITTED_SCHEMA_VERSION` stays **2**: it names the protocol-bound payload family, and raising it would invalidate the reviewed B1 contract without a protocol revision. Recorded risk: a pre-amendment schema-2 artifact that lacks the key still loads, but `phase11_b3.require_detector_table` refuses it, so the absence fails closed at evaluation rather than silently recalibrating |
| B4 scope | the amendment is code plus tests only; no protocol, manifest, sidecar or readiness flag changed, and no campaign, real trial or sealed-test read occurred |
