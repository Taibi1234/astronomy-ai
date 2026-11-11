# Phase 11 B7 — Safe Baseline Review and `fit_real` Report

Repository: `%USERPROFILE%\astronomy-ai`
Branch `main`, HEAD `230c5ae8c26b87abd719c09548a23beab8f37222`, tracking `origin/main`.
Nothing was staged, committed, reset, cleaned, stashed or pushed.

## 1. Git baseline inventory

| Group | Content | Action |
|---|---|---|
| Preserved tracked user changes | `webapp/backend/research/generalization.py`, `phase11.py`, `run_phase11.py` (modified, unstaged) | keep; commit with the Phase 11 work |
| Phase 11 implementation (untracked) | `research/{features,phase11_b2a,phase11_b1,phase11_b2,phase11_b3,phase11_b5,phase11_b6,phase11_b7,phase11_v2,phase11_runner,safeguards,test_access,errors,experiment,jobs,reports,run_experiment,run_phase11_v2}.py`, `app.py` | commit |
| Phase 11 tests (untracked) | `tests/test_phase11_{access_closure,b0_resolution,b1,b2,b2a_builder,b2a_extraction,b3,b4,b5,b6,b7,protocol_repin,stage3_safeguards,stage4_guards,stageA_runner,stageB_readiness,v2_review,v2_stage2}.py`, `test_research_experiment.py`, `test_transit_injection.py` | commit |
| Frozen inputs (untracked) | `reports/phase11_generalization/protocol_v2*.json` + `.sha256` (v2, v2_1, v2_2, v2_3), `smoke/`, `smoke_invalid_scope_20261022/` | commit (they are the pinned evidence) |
| Reports (untracked) | all `reports/phase10_*`, `reports/phase11_*`, `reports/phase9_*`, `reports/injection_recovery*/`, `reports/phase10_browser_acceptance_figures/` | commit; they are the audit trail |
| Frontend (untracked) | `webapp/frontend/` — 21 source/config files; **`node_modules/` and `dist/` are ignored** by `webapp/frontend/.gitignore` | commit the 21 source files only |
| Must not enter Git | `webapp/backend/app.py.*.bak`, `webapp/frontend/src/*.bak` (editor backups), `data/raw/*`, `data/processed/*` (ignored: 4.8 MB of Kepler CSVs), `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, caches | exclude |

Safety checks: no `.env` or key material present; a pattern scan (API key, secret, password,
token, private-key block, `AKIA…`, `sk-…`) over all untracked text files returned **no hits**;
the largest tracked files are ≤524 KB figures, and the largest untracked directories are
`phase10_browser_acceptance_figures/` (832 KB), `smoke_invalid_scope_20261022/` (485 KB),
`injection_recovery*/` (396 KB combined) — all report evidence, none large.

**Proposed minimal baseline commit (single commit, no staging performed):**
`webapp/backend/research/*.py` (19 files incl. the three tracked modifications), `webapp/backend/app.py`,
`webapp/backend/tests/*.py` (19 files), `webapp/frontend/` (21 source files, respecting its
`.gitignore`), `reports/phase9_*`, `reports/phase10_*`, `reports/phase11_*` (all reports and the
`phase11_generalization/` frozen tree including `smoke/` and `smoke_invalid_scope_20261022/`),
`reports/injection_recovery*/`, `reports/phase10_browser_acceptance_figures/`.
**Excluded:** `*.bak`, `data/`, `.venv/`, caches, `node_modules/`, `dist/`.
The commit is a prerequisite for any real run (`require_clean_tree` refuses the current tree).

## 2. Fitting contract (as read, not changed)

- Protocol v2.3 `e1dc5cc9…c154`: `data_roles.model_fitting = "train windows only"`,
  `data_roles.l7_calibration` validation-only, `thresholds.min_calibration_n_per_stratum = 30`,
  `fitted_models.floor_snr = null`, and `unresolved` U5 forbids reusing a historical fitted artifact.
- Fit quarters are the `split.json` quarters with `split ∈ {train, val}`: Q00, Q01, Q03, Q04, Q05,
  Q06, Q07, Q10, Q11, Q15 (10). Test quarters are Q02, Q09, Q13, Q14, Q17 (5).
- `windows_primary.json` holds 207 windows: 45 train-injection, 46 train-null, 21 val-injection,
  21 val-null, and 72 test windows. Offsets come from `offsets.json` (2 draws per window, ±0.1 d);
  depths `[50,75,100,150,300]`, control depth `0`, noise `[observed, amplified_x2]`, 2 offset draws.
- The fitted state is the nine-key payload (`model_id`, `features`, `dropped_features`,
  `imputation_medians`, `thresholds`, `detector_thresholds`, `train_rows`, `val_rows`,
  `train_injected`) persisted by `freeze_fitted_v21` with provenance and a SHA-256 sidecar.

## 3. Implementation — `research/phase11_b7.py` (new, 516 lines)

A dedicated `fit_real` entry point; B1 is unchanged and still refuses anything but synthetic rows.

Gate order (all fail-closed, each before the next step): protocol pin/version → frozen split
manifest → fitting authorization → test-artifact exposure check (output and its parent) → output
isolation (`resolve_output_dir`) → provenance protocol binding + `require_clean_tree` → fit-frame
construction → frame re-assertion → fit → L7 calibration on validation nulls → detector
calibration on train+val nulls → `freeze_fitted_v21` → `load_fitted_v21` verification.

Boundary safeguards:

| Safeguard | Mechanism |
|---|---|
| Authorization | eight required fields; the authorized quarter list must equal the frozen fit quarters exactly — a test quarter in the list is refused |
| Test-quarter exclusion | `_classify_window` excludes test windows and refuses a test quarter labelled as a fit split; `load_fit_series` refuses any quarter outside the fit set **before** building a path |
| Split/parent isolation | `assert_plan_fit_only` and `assert_fit_frame` run before features are computed and again before fitting: no test split, no non-fit quarter, fit splits only, unique ids |
| Source tag | real rows carry `real-campaign-fit-v2`; synthetic rows are refused here and real rows are refused by B1 |
| No test exposure | refuses to run when the output directory or its parent holds `trials_test.csv`, `test_access.json`, `test_generation.json` or `metrics_test.json` |
| No campaign artifacts | no marker call, no CSV write; the output directory holds exactly `fitted.json`, `fitted.sha256`, `model.pkl` |
| Integrity | `load_fitted_v21` re-verifies the JSON sidecar, the model hash and the protocol binding; a tampered model file is refused |
| Determinism | fixed protocol seeds and `random_state=20261025`; two runs give identical thresholds and identical `model.pkl` bytes |

The real row builder mirrors the campaign's fit construction (published-transit removal, noise
condition, coherent injection from the frozen offset draws, matched-filter detection, shared
feature builder), so the calibration pools reproduce the protocol exactly: the real plan yields
**133 fit windows → 1852 rows** (1584 injection, 268 null), i.e. **84 validation null trials =
42 per stratum** for L7 and **268 train+val nulls = 134 per stratum** for the detector — the
protocol's own numbers.

## 4. Validation

**Focused tests** — `pytest tests/test_phase11_b7.py -q` → **27 passed** (11.8 s). Coverage:
authorization (8 failure shapes), test-window exclusion and manifest inconsistency, plan guard,
test-quarter loader refusal, nine frame-guard mutations, synthetic-guard regression (B1 still
refuses real rows), test-artifact exposure (output, parent, three artifact names), dirty tree,
protected output, contaminated builder, nine-key freeze with provenance reload, no
marker/trial creation, determinism, tamper evidence, and no new execution entry point.

**Regression** — 13 files (B7, B1, B2, B2a ×2, B3, B4, B5, B6, Stage B readiness, Stage A runner,
protocol repin, hardening) → **323 passed** (67.8 s).
`ruff check` / `ruff format --check` on `phase11_b7.py` and `test_phase11_b7.py` → clean.

**Real-data path probe (fit quarters only, read-only, no fitting).** `load_fit_series` read Q00
(439 points) and Q15 (4034 points) and refused Q02 with `GateError`; `fit_windows` returned the
133 fit windows with no test quarter; two real windows through the row builder produced sensible
detections (Q00: S/N 3.01, Δt 0.0120 vs 0.0125 d; Q01: S/N 4.24, Δt −0.0655 vs −0.0650 d).
No model was fitted on scientific data: `require_clean_tree` refuses the current dirty tree, which
is precisely why the baseline commit is the first prerequisite.

## 5. Verification

| Check | Result |
|---|---|
| 21 protected artifacts | 21/21 byte-identical |
| `protocol_v2_3.json` | `e1dc5cc9…c154`; `campaign_ready = false`, `execution_ready = false` |
| Trials / metrics / markers / fitted artifacts in the repository | none (all run output went to pytest temp directories) |
| Git | HEAD `230c5ae8…`, 0 staged, no commits, `git diff --check` clean; the three tracked modifications and every earlier untracked file preserved |
| Files added by this task | `research/phase11_b7.py` (`88cd7ac1…`), `tests/test_phase11_b7.py` (`482c86f9…`), this report |

## 6. Unresolved blockers

1. **Baseline commit** — the tree is dirty, so `require_clean_tree` (and therefore `fit_real`)
   refuses to run on real data. The commit plan above is ready; committing needs authorization.
2. **Not validated on real data** — by design until (1); the numerical path is validated on two
   real windows and the full frame is validated on fixtures.
3. **Real test generator, denominator-literal enforcement and the authorization document** remain
   unimplemented (B7 design decisions D1, D3, D5); `fit_real` produces only the fitted state.
4. **MMD stays unset**, so a later campaign's best verdict remains `descriptive_only`.
