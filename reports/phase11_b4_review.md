# Phase 11 Stage B4 — Independent Review Report

Repository: `%USERPROFILE%\astronomy-ai`
Design authority: `reports/phase11_stageB_design.md` §5.3, §5.4, §5.8 (B4 row), gate matrix G1–G16
Status: review complete; one payload amendment recorded, three concrete G12 defects fixed.
No campaign, real trial, sealed-test access, protocol/manifest change, staging or commit.

## 1. Gate-matrix re-check

All fifteen gates were re-read against the current source. The matrix rows now reflect the
implemented state:

| Gate | State at B4 | Evidence |
|---|---|---|
| G5 generation claim | implemented, one consumer per stage: `phase11.run_campaign` (legacy), Stage A walkthrough, and now `phase11_b2.generate_test_trials` | B2 tests (duplicate/interrupted claims) |
| G7 fitted state | implemented; called by `phase11_b1.fit_synthetic`; payload is **nine keys** | B1/B4 tests, `freeze_fitted_v21` |
| G8 threshold calibration | implemented; B1 calls both `calibrate_thresholds_v21` (L7) and `phase11.calibrate_detector_thresholds` (comparator) | B1/B3 tests |
| G9 generated-file integrity | consumed by `phase11_b3.evaluate_test`; the hash is re-verified after the access claim | B3 tests |
| G12 refusal audit | implemented in B3, inspected here | §3 below |
| G16 effective protocol view | implemented (B0) | B0 suite |

No gate is claimed as verified from a report alone; each row names a test file that exercises it.

## 2. Nine-key payload amendment (recorded)

The B3 confirmatory contrast is L7 minus the physics detector **at its calibrated per-stratum
threshold**. No frozen artifact carried that table: the v2 and v1 fitted payloads each persist
only the L7 table, the historical smoke `fitted.json` confirms it, and
`phase11.calibrate_detector_thresholds` had no production caller. B3 could not obtain the
comparator without reading test data, which `thresholds.test_controls_excluded` forbids.

Amendment, now recorded in the design matrix (§5.7 hand-off, the B1 row of §5.8, G7/G8, and the
"Seventh pass" correction-log entry):

- the payload is **nine keys**: `model_id, features, dropped_features, imputation_medians,
  thresholds, detector_thresholds, train_rows, val_rows, train_injected`;
- B1 calibrates `detector_thresholds` on the same train+val nulls via
  `phase11.calibrate_detector_thresholds`;
- `freeze_fitted_v21` **requires** the key (`GateError`, and nothing is written — the check runs
  before the model file or `fitted.json`), and persists it through `phase11_v2.detector_table`
  inside `fitted.json`, so the existing `fitted.sha256` sidecar covers it;
- `FITTED_SCHEMA_VERSION` stays **2**. Recorded risk: a pre-amendment schema-2 artifact that
  lacks the key still loads, but `phase11_b3.require_detector_table` refuses it, so the absence
  fails closed at evaluation instead of silently recalibrating from test data.

## 3. G12 refusal audit — inspection and fixes

Inspected: `phase11_b3.record_refusal`, `_resolve_audit_dir`, `_recorded_fitted_hash`,
`evaluate_test`, and the B3 refusal tests.

Verified: records carry `stage`, `evaluator`, `gate`, `message`, the pinned protocol hash, a
deterministic configuration hash (sorted-key JSON of the resolved view), the campaign directory,
the timestamp and a schema version; the audit directory is refused when it resolves inside the
frozen manifest tree or to a protected directory; a refusal whose audit cannot be written is
re-raised as a `GateError` naming both failures rather than being swallowed; a refusal with no
fitted state records `fitted_sha256: null`.

Three concrete defects were found and fixed:

1. **`fitted_sha256` was never populated.** `evaluate_test` did not pass it, so every refusal
   record — including refusals raised *after* the frozen state was validated — carried `null`,
   weakening campaign identification. Fixed with `_recorded_fitted_hash`, a non-raising read of
   the `fitted.sha256` sidecar; a valid campaign's refusal now records the digest.
2. **An unwritable audit path raised `OSError` instead of `GateError`.** `record_refusal` created
   the directory outside its error handling, so a path whose parent is a file propagated a raw
   `OSError`. Fixed: creation and the exclusive write are wrapped, raising
   `GateError("could not write the refusal record …")`.
3. **Malformed frozen state could escape the audit contract.** A `fitted.json` without
   `thresholds`/`features`/`imputation_medians`, or a corrupt `model.pkl`, raised `KeyError` or
   `UnpicklingError` — neither is audited, and neither is a refusal. Fixed with
   `require_score_table` (validates the shape B3 consumes and the L7 table) and `_load_model`
   (missing/corrupt model file → `GateError`), so malformed frozen state is refused and audited.

## 4. Confirmatory decision logic against the frozen protocol

| Protocol requirement | Implementation | Verdict |
|---|---|---|
| Per-stratum primary family, `observed` and `amplified_x2` | one report and one comparison per stratum; strata read from the artifact and required to have frozen thresholds | OK |
| FPR point estimate `k/n`, zero-count Clopper-Pearson, Wilson labelled trial-level and anti-conservative | `v2.fpr_report` for both L7 and the comparator; the label text comes from the function, not the caller | OK |
| Recall = trial-weighted recovered/injected, Wilson interval | `_recall` over injected trials; per-depth table kept descriptive | OK |
| Confirmation contrast = L7 minus physics at calibrated thresholds | `_paired_frame` pairs injected trials on `trial_id`; `v2.paired_comparison` | OK |
| Paired bootstrap on quarters, percentile primary, BCa diagnostic, 10 000 resamples | `paired_comparison` defaults; B3 records the resample count actually used | OK |
| Per-stratum FPR operating-point gate (`abs(l7-physics) > 0.02` ⇒ inconclusive for superiority) | point estimates of that stratum passed as `fpr=` | OK |
| Heterogeneity guard (≥2 of 5 quarters opposite sign) and zero-difference gate | inside `_gate_reasons`; B4 test asserts the zero-difference gate fires | OK |
| Intersection-union combination | `v2.combine_confirmatory`; B4 test pins every status mapping | OK |
| MMD unset ⇒ `descriptive_only` ceiling, no practical-superiority claim | `_final_status`; `practical_superiority_claim` is hard `False`; caller-supplied `mmd` refused | OK |
| `insufficient_data` minima reported as not evaluated with observed counts | `_insufficiency`, never pooled or relaxed | OK |

No defect was found in the decision logic itself. The one structural consequence of the
nine-key amendment — that the comparator now has a frozen operating point — is what made the
FPR gate meaningful at all.

## 5. Denominator rule (documented and verified)

- **Synthetic evaluation** uses its own declared counts: B3 reports the null and injection counts
  it actually observed per stratum, enforces the protocol's `insufficient_data` minima
  (`minimum_test_clusters = 3`, `minimum_test_nulls_per_stratum = 30`,
  `minimum_test_injections_per_depth_per_stratum = 20`, verified equal to the frozen constants by
  test), and records `denominator_policy` in `metrics_test.json`. It never substitutes, pools,
  reweights or relaxes a denominator.
- **A future authorized confirmatory run** must recompute and enforce the frozen literals from
  frozen inputs before evaluating: 76 nulls per stratum (152 pooled, secondary), 72 injections
  per depth per stratum, and 5 test clusters, with `GateError` on any mismatch
  (`reporting.denominator_derivation.consistency_requirement`). That check is deliberately not
  implemented in B3: a synthetic fixture cannot meet the literals, and enforcing them here would
  have made B3 untestable. It remains a prerequisite of B7.

## 6. Files changed

| File | Change | SHA-256 |
|---|---|---|
| `reports/phase11_stageB_design.md` | nine-key amendment in §5.7, the B1 row, G7/G8/G9; "Seventh pass" log entry | `e71328d8b7558d700d6fe1323026b097153d0de72dffeb7d183155c7c91c25d1` |
| `webapp/backend/research/phase11_b3.py` | `require_score_table`, `_load_model`, `_recorded_fitted_hash`, audit-write error handling (561 lines) | `94a51884e3da5334c4e98a605b1c6dbd1e9aa573f845cd4abbe2efdffc626437` |
| `webapp/backend/tests/test_phase11_b4.py` | new B4 verification tests (490 lines) | `af8b59fd9ff7295ab488a697d7bef5afd62fc076f82f5e712510cbe7485162c5` |

No protocol, manifest, sidecar, runner, readiness flag or historical artifact was modified.

## 7. Verification

| Command | Result |
|---|---|
| `pytest tests/test_phase11_b4.py -q` | 21 passed (30.8 s) |
| `pytest` on 11 directly related files (B3, B1, B2, B2a extraction + builder, B0, v2 stage-2, v2 review, Stage A runner, Stage B readiness, stage-3 safeguards) | 360 passed (78.8 s) |
| `ruff check` / `ruff format --check` on `phase11_b3.py`, `test_phase11_b4.py` | clean |
| 21 protected artifacts | 21/21 byte-identical |
| `protocol_v2_3.json` | `e1dc5cc9…c154`; `campaign_ready = False`, `execution_ready = False` |
| stray `trials_test.csv` / `metrics_test.json` / markers in the repository | none |
| Git | HEAD `230c5ae8…`, 0 staged, no commits, `git diff --check` clean |

## 8. Limitations carried forward

- Evaluation is synthetic-only; the real campaign additionally needs its own generator, the
  frozen denominator-literal gate, an explicit authorization document and a clean committed tree.
- Five or fewer clusters: intervals stay weakly identified and are never called cluster-adjusted.
- The G12 trail is a local artifact; a real campaign should also archive it with the run records.
- B5/B6 decisions (readiness revision, MMD) remain open and untouched.
