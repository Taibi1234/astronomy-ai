# Phase 11b implementation — stages 0, 1 and 2

**Date:** 2026-10-22 · **HEAD:** `5ef9df6` · **Scope:** protocol and offset freeze (stage 0), gated runner
(stage 1), execution-readiness verification with a smoke CLI (stage 2), and the first authorized smoke
attempt. **No test row was read and nothing was staged, committed or pushed.**

**Verdict:** stages 0–2 implemented and tested (149 passed, Ruff clean). The first authorized smoke execution
**was stopped on a scope violation**: the CLI planned 168 trials across Q00/Q01/Q04 but executed 1,852
trials across all ten train/val quarters, because the campaign ignored the smoke window subset (§9). The
run read no test rows and created no test-access record; frozen artifacts are unchanged. The defect and a
second one (a role value that pandas reads as missing) are fixed and covered by tests, but **the smoke run
has not been retried** and needs fresh approval. The frozen protocol is still insufficient for the physics
reporting spec (§8.4) and needs a v2 amendment before any ML-versus-physics comparison.

---

## 1. Files changed

| Path | Status | Note |
|---|---|---|
| `webapp/backend/research/phase11.py` | **new** | protocol/offsets builders, trial plan, gates, freeze/evaluate, campaign code (not run) |
| `webapp/backend/tests/test_phase11_runner.py` | **new** | 30 tests: protocol/offset integrity, split/feature/threshold gates, freeze/one-read guards |
| `reports/phase11_generalization/protocol.json` | **new** | frozen protocol |
| `reports/phase11_generalization/protocol.sha256` | **new** | raw-byte digest sidecar |
| `reports/phase11_generalization/offsets.json` | **new** | 207 + 345 materialized windows × 2 offsets |
| `reports/phase11_generalization/offsets.sha256` | **new** | raw-byte digest sidecar |
| `reports/phase11_research_plan.md` | updated | §13 points to this report and records the hashes |
| `reports/phase11b_implementation.md` | **new** | this report |

Unchanged: the five Phase 11a manifests, `research/generalization.py`, `core.py`, `experiment.py`,
`app.py`, the frontend, every source CSV, and all Phase 4/5/10 artifacts (hashes re-verified in §5).

---

## 2. Stage 0 — protocol

### 2.1 Artifact

`reports/phase11_generalization/protocol.json`, 7 836 bytes,
SHA-256 `ded2bd5eea3cfb3cbd5af0b67e439a767584b9bf508f02afe2a4b5d56a75319f`
(sidecar verified with `sha256sum -c`).

### 2.2 Schema

| Key | Content |
|---|---|
| `version`, `schema_version`, `status` | `phase11b-protocol-v1`, 1, "frozen before campaign" |
| `manifests` | SHA-256 of the five Phase 11a manifests the protocol is bound to |
| `seeds` | split `20261022`, offsets `20261023`, model `20261025`, bootstrap `20261024` |
| `features.detector_outputs` | `snr`, `depth_est_ppm`, `sigma_ppm` |
| `features.flux_features` | `min_depth_ppm`, `std_ppm`, `mad_ppm`, `gap_fraction`, `mean_flux`, `n_points` |
| `features.definitions` | one-line definition per feature |
| `features.sets` | L0–L7 feature lists (bound to `experiment_config.json` by test) |
| `features.forbidden` | the 15 ground-truth / bookkeeping columns |
| `preprocessing` | train-only median imputation, constant-feature drop, pipeline scaling, no selection, no tuning |
| `models` | LR `C=1.0, max_iter=1000, lbfgs`; RF `200/6`; Dummy stratified; `selection: none` |
| `thresholds` | detector `max(3.0, p95)` on train+val nulls; models p95 on validation nulls; `linear` percentile; strict `>`; explicit tie rule |
| `metrics` | primary ROC-AUC + recall@FPR; secondary PR-AUC, MCC, balanced accuracy, Brier, precision/recall; no-skill F1 |
| `bootstrap` | BCa, 10 000 resamples, cluster = quarter, percentile fallback |
| `test_access` | one read; requires protocol + fitted + manifest hashes; ledger `test_access.json` |
| `campaign` | smoke/full/sensitivity definitions and the enforced order (fit → freeze → test → evaluate) |
| `environment` | Python 3.14.3, NumPy, pandas, scikit-learn versions at freeze time |

### 2.3 Content review (hash alone is not validity)

- Feature sets and `forbidden` are asserted **equal** to `experiment_config.json` by
  `test_protocol_feature_sets_match_the_frozen_config`, so the protocol restates rather than drifts.
- `test_protocol_has_every_required_section` checks the presence and exact values of the load-bearing
  fields (FPR 0.05, strict `>`, one test read, train-only fit, L7 primary).
- The detector rule and the model rule differ deliberately: the detector fits nothing, so it may pool
  train+val nulls; fitted models use validation nulls only. This is stated in the protocol, not implied.
- The protocol contains no performance numbers and no per-quarter results — nothing in it could have been
  tuned by outcome.

### 2.4 Determinism and provenance

`build_stage0()` is a pure function of the manifests; two builds are byte-identical
(`test_protocol_is_deterministic`, and `test_sidecar_hashes_match_raw_file_bytes`). The protocol pins the
manifest hashes, so a manifest change invalidates it by construction
(`assert_protocol_manifests`).

---

## 3. Stage 0 — offsets

### 3.1 Artifact

`reports/phase11_generalization/offsets.json`, 91 363 bytes,
SHA-256 `79e8d00eeef88c4e05cb571a64cc871dd5549d1c5e7ef5fd11d32021741b5be6`.

### 3.2 Rule

```
derived_seed = int(sha256(f"{20261023}|window_days={L:.2f}")[:8], 16)
rng          = numpy.random.default_rng(derived_seed)
offsets      = round(uniform(-0.10, 0.10), 6)   # two draws per window
```

Order is canonical `(quarter, window_index)`; roles, splits, flux and outcomes are absent from the key.
The per-length derived seed keeps the 5 d and 3 d draws independent.

### 3.3 Content

| Window | Windows | Values | Min | Max | Derived seed |
|---|---:|---:|---:|---:|---:|
| 5.0 d | 207 | 414 | −0.099588 | 0.099745 | 262 186 256 |
| 3.0 d | 345 | 690 | −0.099621 | 0.099945 | 3 494 546 397 |

### 3.4 Non-interference (verified, not assumed)

| Claim | Check |
|---|---|
| Roles did not change | manifest hashes re-verified after stage 0 (§5); `split.json 5931f5b4…` unchanged |
| Offsets do not depend on roles or splits | `test_offsets_do_not_depend_on_roles_or_splits` flips every role and reassigns splits; the offsets are identical |
| Offsets do not depend on flux or outcomes | key contains identifiers only; no flux argument exists in `build_offsets` |
| The two lengths are independent | `test_offsets_are_independent_per_window_length` |
| Bounds respected | `test_offsets_are_deterministic_and_bounded` (|δ| ≤ 0.10) |

### 3.5 Why materialize offsets at all

Phase 10 drew hidden offsets from a seeded RNG inside the campaign, so the realisation depended on
implementation order. Stage 0 fixes the actual values before any detector call, which makes the smoke and
full runs reproducible even if the runner's iteration order changes.

### 3.6 Bug found during implementation

`Path.write_text` on Windows translates `\n` to CRLF, so a digest computed over the in-memory string did
not match the file's bytes and `sha256sum -c` failed. Both writers now emit UTF-8 bytes and hash those
bytes (`write_json_with_sidecar`). A regression test asserts the raw file contains no CRLF and that the
sidecar equals the raw-byte digest. The corrected artifacts pass `sha256sum -c`.

---

## 4. Stage 1 — runner and gates

### 4.1 Requirements → enforcement → test

| Requirement | Enforcement (code) | Test |
|---|---|---|
| Training-only fitting | `assert_fit_splits` refuses any row outside `train`/`val`; `fit_models` selects `split=="train"` | `test_fit_refuses_test_rows` |
| Validation-only model/threshold selection | `fit_models` calibrates on `val` + `role=="null"`; scope string records it | `test_fit_uses_train_only_and_calibrates_on_validation_nulls` |
| Detector threshold provenance | `calibrate_detector_thresholds` refuses test rows; returns scope, n, quantile, floor, exceedance, tie rule | `test_detector_calibration_refuses_test_rows`, `test_threshold_tie_rule_respects_target_and_records_provenance` |
| Forbidden-feature checks | `feature_columns` rejects forbidden and undeclared columns | `test_forbidden_ground_truth_features_are_rejected`, `test_undeclared_features_are_rejected` |
| Test access only after freeze | `evaluate_test` requires protocol + manifest + fitted hashes; `assert_test_generation_allowed` gates test trial generation | `test_evaluate_requires_frozen_artifacts`, `test_test_generation_requires_frozen_fitted` |
| Fitted state persisted and hashed | `freeze_fitted` writes `fitted.json`, `model.pkl`, `fitted.sha256`; `load_fitted` re-verifies all three | `test_freeze_writes_hash_state_and_model`, `test_evaluate_rejects_tampered_fitted_state` |
| Test read once | ledger `test_access.json`; second call raises; refreeze after a read is refused | `test_evaluate_allows_exactly_one_test_read`, `test_freeze_is_refused_after_test_access` |
| Protocol integrity | sidecar hash + manifest hash binding | `test_protocol_mismatch_blocks_evaluation`, `test_protocol_frozen_against_other_manifests_is_refused` |
| Split isolation of trial plans | `plan_trials(split_group="fit"|"test")` | `test_plan_trials_fit_group_never_contains_test_rows`, count test |
| Smoke/full/sensitivity modes | `MODES` + `describe_mode()`; smoke is train+val only | `test_modes_resolve_to_pre_registered_trials`, `test_unknown_mode_is_rejected` |

Mode resolution (no execution):

| Mode | Window | Groups | Trials | Quarters / splits |
|---|---|---|---:|---|
| smoke | 5 d | fit | 168 | Q00/Q01/Q04, train+val only |
| full | 5 d | fit + test | 1 852 + 1 016 | all 15, 7/3/5 |
| sensitivity | 3 d | fit + test | 3 084 + 1 756 | all 15, 7/3/5 |

### 4.2 Freeze-then-evaluate order (enforced, not documented only)

```
campaign(split_group="fit")      -> refuses nothing; produces train+val trials
fit_models(train, val)           -> refuses test rows; imputes/scales on train; threshold on val nulls
freeze_fitted(...)               -> writes fitted.json + model.pkl + fitted.sha256
campaign(split_group="test")     -> refused unless fitted.sha256 exists
evaluate_test(...)               -> one read; writes test_access.json; second call refused
```

### 4.3 Fitted state (`fitted.json`)

Contains: model id, protocol hash, kept features, dropped constant features, imputation medians, threshold
block (value, quantile, floor status, scope, n, calibration exceedance, rule text), train/val counts,
`train_fingerprint` (SHA-256 of the train rows and features used), `model_file` and its SHA-256, and
library versions. The model object itself is `model.pkl`, hashed and referenced; it is not embedded in the
JSON because pickles are binary and version-coupled.

### 4.4 Trial plan (sizes verified, nothing executed)

| Group | Rows | Composition |
|---|---:|---|
| fit (train+val) | 1 852 | 66 injection windows × 24 + 67 null windows × 4 |
| test | 1 016 | 36 injection × 24 + 38 null × 4 |
| total | 2 868 | matches `experiment_config.json → projected_cost.primary.total_detector_trials` |

### 4.5 Explicit non-execution

`run_campaign`, `fit_models`, `freeze_fitted` and `evaluate_test` were **not called on real data**. Every
test uses synthetic frames and a `StubModel` that never trains. No `.pkl`, `fitted.json`, `test_access.json`
or campaign CSV exists in the repository.

### 4.6 Gate review (hash is not enforcement)

- `assert_fit_splits` runs before any fitting and inspects the `split` column values, not a metadata flag.
- `fit_models` builds the design matrix from `train` rows only; validation rows are used solely to score
  nulls for the threshold.
- `evaluate_test` re-verifies the protocol hash, the manifest binding, the fitted hash, the model-file
  hash, and that the supplied frame contains test rows only.
- The ledger is checked before evaluation and written only after metrics are computed; a failed evaluation
  leaves no ledger, so it must be retried rather than silently repeated.

---

## 5. Verification performed

```
webapp/backend>  python -m pytest -q                              110 passed, 1 warning
webapp/backend>  python -m pytest tests/test_phase11_runner.py -q  32 passed
webapp/backend>  python -m ruff check .                           All checks passed!
reports/phase11_generalization>  sha256sum -c protocol.sha256      protocol.json: OK
reports/phase11_generalization>  sha256sum -c offsets.sha256       offsets.json: OK
```

Stage 0 determinism: two consecutive `python -m research.phase11 --stage plan` runs produce the same two
digests. Manifest hashes before and after stage 0 are identical (roles untouched).

Historical artifacts (re-hashed): `phase5_dataset.json f8ad47fb…`, `phase5_results.json a2273458…`,
`phase5_features.csv a2886bf9…`, `phase4_block_bootstrap.json d4e2de41…`,
`injection_recovery/summary.json 6c4d2cd3…`, `trial_results.csv ce4e028c…` — all unchanged.
Frontend checks were not run because no frontend file changed.

---

## 6. Limitations

1. **The campaign/fit/evaluate paths are implemented but unexecuted.** Gates are tested with stubs and the
   three modes resolve to the pre-registered trial counts, but the numerical path (injection → detector →
   metrics) has not been exercised end to end, and no execution CLI (`research.run_phase11`) exists yet.
   That is stage 2.
2. **`model.pkl` is a pickle.** Its hash proves identity, not portability; the protocol and `fitted.json`
   record library versions so a stale environment is detectable later.
3. **Bootstrap is declared, not implemented.** BCa over quarters is a stage-5 deliverable; `metrics_test`
   currently reports point estimates only.
4. **`evaluate_test` covers the ML ladder only.** The detector/physics operating-point evaluation reuses
   `detection_metrics` but is not yet wired into a separate physics report.
5. **`run_campaign` reads `offsets.json` from the manifest directory.** Stage 0 writes both into
   `reports/phase11_generalization/`, so this holds; moving them would require a flag.
6. **No UI.** Phase 11 remains analysis-first; adding run buttons before results exist would repeat the
   Phase 10 "API verified / browser unverified" gap.
7. **Hash ≠ validity.** The protocol was reviewed field by field (§2.3); a future change must be reviewed
   the same way, not merely re-hashed.

---

## 7. Next step (not started)

Stage 2 is implemented (§8); its smoke run has **not** been executed and needs explicit approval.

---

## 8. Stage 2 — execution-readiness verification and smoke CLI

### 8.1 Files

| Path | Status | Note |
|---|---|---|
| `webapp/backend/research/run_phase11.py` | **new** | smoke-only CLI, dry-run by default |
| `webapp/backend/tests/test_phase11_integration.py` | **new** | 10 numerical tests on synthetic fixtures (real LR/RF) |
| `webapp/backend/tests/test_phase11_physics.py` | **new** | 9 detector operating-point and bootstrap tests |
| `webapp/backend/tests/test_phase11_cli.py` | **new** | 9 smoke-scope, dry-run and no-test-access tests |
| `webapp/backend/research/phase11.py` | changed | physics operating point + bootstrap CI; ledger written before metrics; corrupt JSON → `GateError`; `fit_models` returns the in-memory model |
| `webapp/backend/tests/test_phase11_runner.py` | changed | +6 fail-closed tests (38 total) |

Unchanged and re-verified: `protocol.json ded2bd5e…`, `offsets.json 79e8d00e…`, the five Phase 11a
manifests, every source CSV, and the Phase 4/5/10 artifacts. No `fitted.json`, `model.pkl`,
`test_access.json` or campaign CSV exists anywhere in the repository.

### 8.2 Numerical integration tests (synthetic fixtures, no campaign data)

These fit **real** scikit-learn models on synthetic rows; they do not touch light curves or test rows.

| Test | What it proves |
|---|---|
| `test_constant_feature_is_dropped_and_recorded` | train-constant features are dropped and listed |
| `test_imputation_medians_come_from_train_rows_only` | medians equal an independently computed train median |
| `test_scaler_is_fitted_on_train_rows_only` | scaler mean equals the train matrix mean even when validation is shifted +25 |
| `test_logistic_regression_fits_and_separates_the_synthetic_signal` | LR fits, probabilities are in [0,1], injected scores exceed nulls, threshold n = validation nulls |
| `test_random_forest_fits_and_serializes` | RF fits and round-trips through `freeze_fitted` → `load_fitted` |
| `test_threshold_is_the_validation_null_p95` | threshold quantile equals `percentile(val_null_scores, 95)`, exceedance ≤ target |
| `test_freeze_reload_predicts_identically` | reloaded pickle reproduces the in-memory probabilities exactly |
| `test_fit_refuses_test_rows_with_a_real_factory` | a test row in the frame raises before fitting |
| `test_feature_order_and_missingness_are_handled` | feature order preserved; all-NaN validation columns imputed |
| `test_fitted_state_binds_to_the_protocol_hash` | fitted state refuses a different protocol hash |

### 8.3 Fail-closed additions

| Test | Failure it proves |
|---|---|
| `test_corrupted_protocol_json_fails_closed` | unreadable protocol JSON → `GateError` |
| `test_corrupted_fitted_json_fails_closed` | unreadable fitted JSON → `GateError` |
| `test_corrupted_model_file_fails_closed` | model bytes disagreeing with `model_sha256` → `GateError` |
| `test_ledger_is_written_before_metrics_and_blocks_retry` | a crash mid-evaluation leaves `status: "started"`; retry is refused |
| `test_restart_cannot_bypass_the_one_read_policy` | the on-disk ledger blocks a fresh call after a completed read |
| `test_test_campaign_is_blocked_before_freeze` | `run_campaign(split_group="test")` raises before touching data |

**Residual bypass:** the ledger is a filesystem record. A deliberate actor can delete
`test_access.json` and re-run; that is tampering with evidence, not a bypass the code can prevent
without external append-only storage. The report recommends recording the ledger hash outside the
working directory when the real test pass is run.

### 8.4 Physics operating-point specification (task 4)

`DETECTOR_REPORT_SPEC` (in `phase11.py`) fixes: score = `snr`; detected = `snr > threshold[noise]`;
recovered = injected ∧ detected ∧ |Δest − Δtrue| ≤ **0.0377 d** (`core.TOLERANCE_DAYS`); strata =
noise condition plus pooled; FPR = false positives / null trials; recall = recovered / injected;
intervals = Wilson + quarter cluster bootstrap; comparison rule = same test trial ids, same FPR
target, paired by quarter.

`physics_operating_point()` returns per-noise and pooled blocks with threshold, FPR (count, rate,
Wilson, cluster), recall (count, rate, Wilson, cluster) and a per-depth recovery table. It refuses
any split other than the requested one and never recalibrates.

**Protocol v1 is insufficient for this spec in three fields, so it was not modified:** it does not
record (a) the recovery timing tolerance, (b) the stratification rule, or (c) the ML-versus-physics
comparison rule. The code uses `core.TOLERANCE_DAYS` and records it in every report, but pre-registration
requires the protocol to state it. **Approval is requested for a protocol v2 amendment (new hash)
before any ML-versus-physics comparison.** The smoke run does not depend on this: it only fits.

### 8.5 Smoke CLI and its guarantees

```powershell
cd %USERPROFILE%\astronomy-ai\webapp\backend
.\.venv\Scripts\python.exe -m research.run_phase11 --mode smoke `
  --out ..\..\reports\phase11_generalization\smoke --execute
```

Omitting `--execute` is a dry run and writes nothing (verified). The runner refuses `full` and
`sensitivity` with exit code 2 until separately approved.

| Guarantee | Mechanism |
|---|---|
| Only Q00/Q04 (train) and Q01 (validation) | `smoke_windows()` filters the frozen manifest; `assert_smoke_scope()` asserts quarter→split |
| Cannot read test rows | plan uses `split_group="fit"`; the frame is re-checked for `split ⊆ {train, val}` |
| Cannot write a test-access record | evaluation is never called; the directory is checked afterwards for `test_access.json` |
| Cannot overwrite the frozen manifests | output equal to the manifest directory is refused |
| No test ledger already present | preflight refuses a directory containing `test_access.json` |

Expected smoke result: 12 windows, **168 trials** (6 injection windows × 24 + 6 null windows × 4),
≈4 s, artifacts `trials_fit.csv`, `fitted.json`, `fitted.sha256`, `model.pkl`.

### 8.6 Verification

```
webapp/backend>  python -m pytest -q                              144 passed, 1 warning
webapp/backend>  python -m pytest tests/test_phase11_runner.py -q  38 passed
webapp/backend>  python -m pytest tests/test_phase11_integration.py -q  10 passed
webapp/backend>  python -m pytest tests/test_phase11_physics.py -q  9 passed
webapp/backend>  python -m pytest tests/test_phase11_cli.py -q      9 passed
webapp/backend>  python -m ruff check .                           All checks passed!
```

`python -m research.run_phase11 --mode smoke` resolves to 12 windows / 168 trials and writes nothing.
Frozen hashes unchanged; no frontend checks were run because no frontend file changed.

### 8.7 Remaining risks

1. **Protocol v1 gap (§8.4)** — timing tolerance, stratification and the comparison rule must be added
   as v2 before ML-versus-physics comparisons; until then the specification lives in code and this report.
2. **Campaign path has now run once, out of scope (§9).** The light-curve → injection → detection path
   works (1,852 trials produced), but it has never run the authorized 168-trial smoke.
3. **Ledger tampering** (§8.3) — a deleted `test_access.json` cannot be distinguished by the code alone.
4. **Pickle portability** — `model.pkl` is version-coupled; `fitted.json` records library versions.
5. **BCa fallback** — degenerate samples fall back to percentile; the method is recorded per interval.
6. **Smoke output must be excluded from inference** — it lives under `reports/phase11_generalization/smoke`
   and is labelled as a smoke artifact, never as a result.
7. **No UI** — Phase 11 remains analysis-first.

---

## 9. First smoke execution — scope violation (2026-10-22)

### 9.1 What was run

```
webapp/backend>  python -m research.run_phase11 --mode smoke `
                   --out ../../reports/phase11_generalization/smoke --execute
exit code: 0        runtime: 44.2 s (expected ≈ 4 s)
```

Preflight passed immediately before the run: all seven hashes verified (`protocol ded2bd5e…`,
`offsets 79e8d00e…`, five manifests), output directory absent, not the manifest directory.

### 9.2 What actually happened — **scope violation**

| Expected (authorised) | Observed |
|---|---|
| 12 windows, **168 trials** | **1,852 trials** |
| Quarters Q00,Q04 (train) + Q01 (val) | **10 quarters**: Q00, Q01, Q03, Q04, Q05, Q06, Q07, Q10, Q11, Q15 |
| Train/val splits only | train 1,264 / val 588 (no test) |
| ≈ 4 s | 44.2 s |

The fitted artifact therefore came from the full train+val window set, not the smoke subset:
threshold 0.7561 calibrated on **84** validation nulls (expected 12), protocol hash `ded2bd5e…`.

**No test access occurred.** `split` values are only `train`/`val`; no `test_access.json` exists; the
CLI reported `evaluate_called: false`. Frozen artifacts and historical Phase 4/5/10 outputs were
re-hashed after the run and are unchanged.

### 9.3 Root cause

`run_smoke` validated a 12-window plan in `preflight()` but then called `run_campaign` without passing
that subset. `run_campaign` re-read the full `windows_primary.json` and planned `split_group="fit"` over
all 207 windows (66 injection + 67 null on train+val), producing 1,852 trials. The smoke scope check was
disconnected from execution.

### 9.4 Second defect found by the same run

The trial-level `role` was written as the literal string `null`, which pandas treats as a missing value:
reading `trials_fit.csv` back turned all 532 control rows into `NaN`. Any later analysis would silently
lose the control flag.

### 9.5 Handling

- The run was **not retried**. It was stopped and reported, per the authorization.
- The output directory was quarantined by renaming it to
  `reports/phase11_generalization/smoke_invalid_scope_20261022/`; `reports/phase11_generalization/smoke/`
  is absent so a corrected run cannot overwrite or inherit it.
- Quarantined artifact hashes: `trials_fit.csv b1691d293451921b…` (479,424 B),
  `fitted.json b4c35fa877a7ee61…` (1,333 B), `fitted.sha256 0b19982937f4b1ac…`,
  `model.pkl 577cd73234221f23…`. They are evidence, not results.

### 9.6 Remediation (implemented, not executed)

| Fix | Detail |
|---|---|
| Campaign honours an explicit window subset | `run_campaign(..., windows=...)`; `run_smoke` passes its 12 pre-registered windows |
| Post-run scope assertions | raises if the campaign returns any quarter outside Q00/Q01/Q04, or a trial count ≠ the preflight 168 |
| Trial vocabulary | `plan_trials` writes `null_window` instead of `null`; calibration and fitting updated; CSV round-trip preserves roles |
| Window indexing bug (found before execution) | `run_campaign` keyed windows by quarter only, so every trial used the quarter's last window; now keyed by `(quarter, window_index)` |

New tests (149 total, +5): window lookup keeps every window distinct, campaign honours explicit windows,
trial role survives a CSV round-trip, smoke rejects unauthorised quarters, smoke rejects a wrong trial
count. The execute-path test now asserts that exactly 12 windows are passed to the campaign.

### 9.7 State after remediation

```
webapp/backend>  python -m pytest -q        149 passed
webapp/backend>  python -m ruff check .     All checks passed!
dry run          smoke resolves to 168 trials / 12 windows / Q00,Q01,Q04 and writes nothing
hashes           protocol ded2bd5e…, offsets 79e8d00e…, five manifests unchanged; historical unchanged
git              nothing staged; diff --check clean
```

### 9.8 Request

Approval is requested for a **corrected smoke re-run** with the same authorization (Q00/Q04 train, Q01
validation, `split_group="fit"`, no evaluation), into `reports/phase11_generalization/smoke`. The
incorrect output remains quarantined and must not be used for any inference.

*Stages 0–2 complete. The smoke run stopped on a scope violation, was not retried, and awaits approval.*