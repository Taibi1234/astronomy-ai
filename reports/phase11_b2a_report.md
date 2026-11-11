# Phase 11 Stage B2a — Extraction and Builder Report

Repository: `%USERPROFILE%\astronomy-ai`
Design authority: `reports/phase11_stageB_design.md` §5.1 and §5.7
Status: **complete**; no real data, no sealing, no campaign, nothing staged or committed.
HEAD during B2a: `230c5ae8c26b87abd719c09548a23beab8f37222`.

## 1. §5.1 decision recorded

**Decision (b) was adopted; fallback (a) was not used.**

The duplicated feature builder was moved into a neutral, dependency-light module
(`webapp/backend/research/features.py`, numpy only) and re-exported as
`phase11.time_domain_features` and `experiment.time_domain_features`. Both historical callers
therefore keep their existing names and behaviour, the v2 path gains no dependency on the
legacy campaign module for feature extraction, and there is exactly one implementation.

The bit-identity gate passed on every probed case, so the pre-decided fallback — importing
`phase11.time_domain_features` directly and recording the v2 → v1 coupling in G7/G8 — was
**not** taken.

## 2. Artifacts

| File | Role | SHA-256 | Lines |
|---|---|---|---|
| `webapp/backend/research/features.py` | neutral shared builder | `9c7e3ba51f1a936f173e763b06b602d6ae379f4719068d1b741b30c13d31e77f` | 38 |
| `webapp/backend/research/phase11_b2a.py` | synthetic fit-split builder | `85f9d148c13449dec631e0b5d2c9d906917fc6eb644293a21e3de44d5e1187e4` | 337 |
| `webapp/backend/tests/test_phase11_b2a_extraction.py` | extraction gate | `305232765fd3646a61fb435d9b6db1491f681f041f8b2c2927587465d21ed8a0` | 181 |
| `webapp/backend/tests/test_phase11_b2a_builder.py` | builder, isolation, §5.5 | `ac6dbf8c63db9f094eadefeeee33003bd0a1b91a08a4b9cb18034698e1f4e581` | 386 |

`phase11.py` gained exactly two hunks: `from .features import time_domain_features` and the
removal of its local 12-line body. `experiment.py` gained the same two hunks.

## 3. Bit-identity gate

Proven against a verbatim copy of the pre-extraction body, comparing **IEEE-754 bytes**, Python
types and key order (no tolerance):

- nine synthetic array cases: standard, intra-window gaps, coarse sampling, two points, single
  point, constant flux, integer flux, extreme scale, and arrays containing NaN;
- all three import names produce identical output, and
  `phase11.time_domain_features is experiment.time_domain_features is features.time_domain_features`;
- the detector result from the B2a wiring is bit-identical to a direct `core.detect` call;
- `features.py` holds no file access, no detector access and no pandas/sklearn import.

## 4. Builder contract

`build_fit_split_frame(effective, split_map, seed, ...)` reads feature columns, noise strata and
the split vocabulary from the authenticated B0 view; it invents no configuration authority.
Enforced and tested: test-split and unknown splits refused **before any row is constructed**;
`injected == (requested_depth_ppm > 0)`; null windows mandatory in `train` and `val`;
`phase11.assert_fit_splits` green (and red on an injected test row); fixed seed reproducible;
the detector receives only `(times, flux, mission)` and the feature builder only
`(times, flux)`; invalid numeric/textual inputs fail closed with `GateError`; writes go through
`resolve_output_dir` and protected destinations are refused; no campaign marker is created. The
output file is named `b2a_fit_split.csv` so a later campaign output directory is not
pre-poisoned with campaign state.

## 5. Verification actually run

| Command | Result |
|---|---|
| `pytest tests/test_phase11_b2a_extraction.py -q` | 21 passed (5.8 s) |
| `pytest tests/test_phase11_b2a_builder.py -q` | 43 passed (11.7 s) |
| 9-file Phase 11 regression set (hardening, integration, cli, v2_stage2, physics, b0_resolution, stage3_safeguards, stageB_readiness, research_experiment) | 243 passed |
| `ruff check` on all six touched files | clean |
| `ruff format --check` on `features.py`, `phase11_b2a.py`, `experiment.py`, both test files | clean |
| 21 protected artifacts | 21/21 byte-identical |
| `git diff --check` | clean; 0 staged; no commits; no markers or trial files created |

`phase11.py` retains **pre-existing** `ruff format` drift (e.g. `require_noise_strata`,
`MODES`, `evaluate_test`); the added import line is not part of that drift and the file was not
reformatted, so tracked user work stays untouched.

## 6. Limitations carried into B1

- No B1 round trip was run in B2a: the frame's compatibility with the fit and calibration
  contract is proven structurally (`split`/`role`/`noise_condition`, feature columns and
  `injected` present, nulls in both splits, `assert_fit_splits` green).
- A real `calibrate_thresholds_v21` call needs at least
  `thresholds.min_calibration_n_per_stratum` = 30 validation nulls per stratum, which B2a's
  default 12-row fixture does not reach; B1's round trip therefore builds a larger fixture
  rather than lowering the frozen minimum.
- `null_library.json` remains unused by B2a; it belongs to the B2/B3 campaign path.
