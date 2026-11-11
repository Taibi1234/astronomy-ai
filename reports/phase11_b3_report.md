# Phase 11 Stage B3 — Test Evaluation Report

Repository: `%USERPROFILE%\astronomy-ai`
Design authority: `reports/phase11_stageB_design.md` §5.4, §5.5 and the B3 row of §5.8
Status: **complete** as a synthetic-only evaluation path. No real campaign, no real trial, no
sealed-test access, nothing staged or committed.

## 1. Decision taken before coding (authorization: resolution 1)

The B3 confirmatory contrast is "L7 minus the physics matched-filter detector **at its calibrated
per-stratum threshold**" (protocol `comparison` block). No frozen artifact carried that table:
`freeze_fitted_v21` persisted only the L7 table, the legacy `freeze_fitted` did the same, the
historical smoke `fitted.json` confirms it, and `phase11.calibrate_detector_thresholds` had no
production caller. B3 therefore could not calibrate the comparator without reading test data,
which `thresholds.test_controls_excluded` forbids.

The authorized resolution extends the frozen fitted payload with a **ninth key**:

- `phase11_b1.fit_synthetic` now calibrates the detector table on the same train+val nulls via
  `phase11.calibrate_detector_thresholds` and passes it in the payload;
- `phase11_v2.freeze_fitted_v21` requires that key (fail-closed `GateError` when absent) and
  persists it through the new `phase11_v2.detector_table` beside the L7 table, inside
  `fitted.json` and therefore inside its SHA-256 sidecar;
- `phase11_b1.FITTED_PAYLOAD_KEYS` is now the nine keys
  `model_id, features, dropped_features, imputation_medians, thresholds, detector_thresholds,
  train_rows, val_rows, train_injected`.

**Schema version:** `FITTED_SCHEMA_VERSION` stays `2`. It names the protocol-bound payload
family, and raising it would invalidate the reviewed B1 artifact contract without a protocol
revision. Recorded risk: a pre-amendment schema-2 artifact that lacks the key still loads, but
`phase11_b3.require_detector_table` refuses it, so the absence fails closed at evaluation.

## 2. Test-trial schema (confirmed, not redefined)

`delta_true_days` and `delta_est_days` are consistent across the four authorities: the protocol
rule `recovered := detected AND abs(timing_error_days) <= 0.0377`, `phase11.TIMING_TOLERANCE_DAYS
= 0.0377`, `physics_operating_point`'s `|delta_est_days - delta_true_days|`, and B2's per-row
writer. `delta_true_days` is in `features.forbidden`, so truth can never enter either model. B3
adds no column and changes no definition.

## 3. B3 behaviour

`phase11_b3.evaluate_test(effective, out_dir, audit_dir, manifest_dir, repo_root, mode,
resamples)` — the only entry point; it takes a directory, never a DataFrame, so there is no
argument through which unverified rows could be injected.

Order, all fail-closed before the next step:

1. approved-mode gate (reused from B1; `("synthetic",)` only);
2. authenticated-protocol gate on the B0 view and the v2.3 pin;
3. campaign-directory isolation (B2's `resolve_campaign_dir`: frozen tree, protected dirs, file
   collision);
4. generation precondition (`assert_test_generation_allowed`) and `load_fitted_v21` under the
   pin;
5. `require_detector_table` — the comparator's thresholds must be frozen;
6. **`claim_access` before any read** — one-shot, cross-process, never released;
7. `load_authorized_trials` (hash-verified) plus `verify_generated_trials`, so the recorded hash
   is re-checked after the read;
8. trial-frame gates: test split only, synthetic source only, unique `trial_id`, no null keys,
   every stratum has a frozen L7 threshold, all required columns present.

Scoring and reporting use only frozen operating points: L7 on the frozen score thresholds, the
physics comparator on the frozen detector thresholds, both with the strict `>` rule and
`|timing error| <= 0.0377`. Per stratum, B3 emits `fpr_report` (trial-level Wilson plus the
zero-count Clopper-Pearson bound, labelled anti-conservative), Wilson recall, a per-depth table,
and `paired_comparison` on the injected trials with the protocol FPR-match gate; the strata are
combined by `combine_confirmatory` (intersection-union). The protocol's `insufficient_data`
minima (3 clusters, 30 nulls, 20 injections per depth per stratum) mark a stratum as not
evaluated with its observed counts instead of substituting a denominator.

Outputs: `metrics_test.json` + `metrics_test.sha256`, and the access marker completed with the
metrics hash, row count, cluster count and overall status. `practical_superiority_claim` is
always `False`; with the minimum meaningful difference unset the best status is
`descriptive_only`.

**G12 refusal audit (§5.4):** every refused gate writes a durable JSON record naming the stage,
gate, message, protocol hash, configuration hash, campaign directory and UTC timestamp. The
audit directory must be outside the frozen manifest tree and the protected directories; when it
cannot be written, the refusal is re-raised as a `GateError` naming both failures rather than
being swallowed.

**Denominator policy (recorded):** B3 enforces the protocol's `insufficient_data` minima and
reports observed denominators. The frozen campaign literals (76 nulls, 72 injections per depth
per stratum) are absolutes of the real campaign; a synthetic fixture cannot meet them, so
enforcing them here would make B3 untestable. The literal consistency check stays a
real-campaign requirement.

## 4. Files changed

| File | Change | SHA-256 |
|---|---|---|
| `webapp/backend/research/phase11_b3.py` | new evaluator (509 lines) | `c29b8f67da3d19706ff372bf76f5254a8e1d89b33f8f3dc672400c0d195cb0c2` |
| `webapp/backend/tests/test_phase11_b3.py` | new focused tests (537 lines) | `901934368b0ef22ff7dcb89ec11aadb6fd1066cc236945a9d216029a955478b7` |
| `webapp/backend/research/phase11_v2.py` | `detector_table`; freeze requires and persists the ninth key | `727f929e331fd5d711cea353e8af984a5b7179820cf652a7e1570b6acf7d78ce` |
| `webapp/backend/research/phase11_b1.py` | nine-key payload, detector calibration on train+val nulls | `963550a0639d0545943f9ceea01c8b0afb00f326b2d32159fe38e6dabfd14658` |
| `webapp/backend/tests/test_phase11_v2_stage2.py` | fixture carries the detector table | `0fe9006fb298d5e182b72a44346f108b9a763eabb7c3a7ccdb3ce0eb2d5d79bc` |
| `webapp/backend/tests/test_phase11_b1.py` | round-trip asserts the reloaded detector table | `f6f90b461b0b1a262fd9581bf2bcca41bdb5c0f909228e54a283930e0c47a52c` |

Protocols, manifests, sidecars, Stage A runner, readiness flags and historical artifacts are
untouched.

## 5. Verification

| Command | Result |
|---|---|
| `pytest tests/test_phase11_b3.py -q` | 28 passed (37.7 s) |
| `pytest tests/test_phase11_b1.py -q` (after the added reload assertion) | 32 passed (25.3 s) |
| `pytest` on 15 directly related files (B0, B2a extraction + builder, B1, B2, hardening, integration, cli, v2 stage-2, v2 review, physics, stage-3 safeguards, stage-B readiness, Stage A runner, Phase 10 experiment) | 427 passed (88.0 s), 1 pre-existing Starlette warning |
| `ruff check` / `ruff format --check` on the six touched files | clean |
| 21 protected artifacts | 21/21 byte-identical |
| stray `trials_test.csv` / `metrics_test.json` / markers in the repository | none |
| Git | HEAD `230c5ae8…`, 0 staged, no commits, `git diff --check` clean |

The B3 suite covers: the hash-bound metrics artifact and completed ledger; access claimed before
the read (marker observed as `started` at read time); no caller-supplied frame parameter;
second evaluation refused and audited; tampered trials refused with a terminal claim; a missing
detector table refused rather than recalibrated; mode/protocol/destination refusals; six
trial-frame gate cases; proof the test frame can never pass `assert_fit_splits` and that
evaluation never calls `fit_models`; the insufficiency and inconclusive gates (zero difference,
FPR mismatch, matched FPR giving `descriptive_only`); the G12 record fields and the protected
audit-directory refusal; unchanged execution safety; and the §5.5 synthetic-only guard with the
authorized trial read still permitted.

## 6. Limitations and next-stage requirements

- Evaluation is synthetic-only. A real campaign needs its own generator, the frozen denominator
  literal check, and separate authorization (B4/B7).
- Five or fewer clusters: intervals are reported as weakly identified, never as
  cluster-adjusted, and the achieved false-positive rate is never described as a target met.
- The fitted-payload amendment (nine keys) should be reflected in the design record at the B4
  review, which must also verify the G12 artifact by inspection.
- No B4 work, no campaign, no real trial, no sealed-test access, no staging or commit occurred.
