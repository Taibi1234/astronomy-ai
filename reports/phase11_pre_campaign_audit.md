# Phase 11 pre-campaign audit

**Date:** 2026-10-22 · **HEAD:** `5ef9df6` · **Scope:** focused review of the frozen Phase 11a design before
Phase 11b. No campaign run, no model trained.

**Verdict: audit passed after the R1 correction (applied 2026-10-22).** The original review found one
blocking defect — the alternating injection/null role assignment was systematically associated with
position in time (injection windows earlier in 12 of 15 quarters, sign test p = 0.003 on non-tied
quarters; Cohen's d ≈ −0.21), which would have measured recovery and false positives under
systematically different within-quarter systematics. R1 replaced it with a paired deterministic SHA-256
allocation; the manifests were regenerated and the association is gone (5 d: d = −0.09, p = 0.56;
3 d: d = 0.00, p = 0.99). Everything else in the audit passed unchanged. Resolution record: §13.

Manifest hashes **after** the correction: `split.json 5931f5b4fc7450bb`,
`windows_primary.json 6d8eb4b4efad96ab`, `windows_sensitivity.json b89c6bded0c0b22a`,
`null_library.json 767ff9408c70a9c9`, `experiment_config.json 43fbddc15c74c626`.
They supersede the pre-correction hashes quoted in §3 (`f22213ca…`, `36e6adb1…`, `a7693993…`,
`fb295e24…`, `71f2ed9c…`). Backend suite: **78 passed**, Ruff clean.

---

## 1. What was audited

| Item | Check |
|---|---|
| `reports/phase11_research_plan.md` §12 | implementation record vs actual artifacts |
| `reports/phase11_generalization/{split,windows_primary,windows_sensitivity,null_library,experiment_config}.json` | content, counts, scoping, hashes |
| `webapp/backend/research/generalization.py` | window generation, role assignment, feasibility, no fitting code |
| `webapp/backend/tests/test_generalization.py` | what is already guaranteed by test |
| `data/processed/kepler_q*_quality_masked.csv` | per-window times, gaps, transits, transit centres (read-only) |

Method for the distribution audit: every window was re-expanded against its quarter's cadences to compute
its position inside its piece (`rel_piece`), inside its quarter (`rel_quarter`), its cadence count, its
transits, and the number of ephemeris transit centres it contains. Roles were compared with Cohen's d,
Mann–Whitney U, and a per-quarter sign test; the alternative allocation was evaluated on the same basis
without writing any file.

---

## 2. Summary of findings

| Area | Result | Action |
|---|---|---|
| Role ↔ time allocation | **FAIL** — systematic, small | **R1: regenerate with a paired deterministic rule (approval required)** |
| Role ↔ noise / offset | pass — fully crossed within every window | none |
| Role ↔ transit coverage | pass — d ≤ 0.15, p ≥ 0.20 | none |
| Role ↔ quarter balance | pass — counts differ by ≤ 1 per quarter | none |
| Role ↔ split balance | pass — 52.7/47.3 (test), 51.6/48.4 (train), 50/50 (val) | none |
| FPR calibration design | pass with two protocol gaps | R4 (per-method threshold scope), R5 (gates) |
| Test isolation | pass structurally; gates not yet implemented | R5 |
| L7 pre-registration | pass | none |
| Frozen constants | partial — hyperparameters/bootstrap/tie-break absent | R2 (`protocol.json`) |
| Hidden offsets materialized | no — seed only | R3 (`offsets.json`) |

---

## 3. Role allocation audit

### 3.1 Current assignment (even window index → injection)

Pooled distributions (207 windows: 107 injection, 100 null):

| Quantity | Injection | Null | Difference | Cohen's d | Mann–Whitney p |
|---|---:|---:|---:|---:|---:|
| Position in piece (`rel_piece`) | 0.400 | 0.460 | **−0.059** | **−0.21** | 0.123 |
| Position in quarter (`rel_quarter`) | 0.452 | 0.488 | −0.036 | −0.13 | 0.364 |
| Cadences per window | 212.7 | 210.4 | +2.3 | +0.15 | 0.197 |
| Transits per window | 5.926 | 5.921 | +0.005 | +0.05 | 0.451 |
| Transit centres inside window | 5.916 | 5.930 | −0.014 | −0.05 | 0.707 |

Per-quarter distribution (`rel_piece` means; negative = injection windows earlier in the piece):

| Quarter | Span (d) | Inj | Null | Inj mean | Null mean | Diff |
|---|---:|---:|---:|---:|---:|---:|
| Q00 | 9.7 | 1 | 1 | 0.00 | 0.52 | −0.52 |
| Q01 | 33.5 | 3 | 3 | 0.32 | 0.48 | −0.16 |
| Q02 | 88.7 | 8 | 8 | 0.36 | 0.41 | −0.05 |
| Q03 | 89.3 | 9 | 8 | 0.40 | 0.46 | −0.06 |
| Q04 | 20.8 | 2 | 2 | 0.24 | 0.48 | −0.24 |
| Q05 | 93.7 | 9 | 9 | 0.38 | 0.49 | −0.11 |
| Q06 | 89.8 | 9 | 9 | 0.45 | 0.50 | −0.05 |
| Q07 | 89.4 | 9 | 8 | 0.47 | 0.47 | 0.00 |
| Q09 | 97.4 | 10 | 9 | 0.46 | 0.46 | 0.00 |
| Q10 | 93.4 | 9 | 9 | 0.42 | 0.47 | −0.05 |
| Q11 | 97.1 | 8 | 8 | 0.37 | 0.49 | −0.12 |
| Q13 | 90.3 | 9 | 8 | 0.47 | 0.47 | 0.00 |
| Q14 | 97.2 | 9 | 8 | 0.43 | 0.39 | +0.05 |
| Q15 | 97.6 | 9 | 8 | 0.37 | 0.42 | −0.05 |
| Q17 | 31.8 | 3 | 2 | 0.15 | 0.45 | −0.30 |

Sign test: injection earlier in **12 of 15** quarters (p = 0.035); excluding the three tied quarters,
**12 of 13** (p = 0.0034). Split balance: test 39 inj / 35 null (52.7 %), train 47 / 44 (51.6 %), val 21 / 21.
Per-quarter role counts differ by at most one, so quarter *membership* is balanced — the bias is purely
within-quarter position in time.

### 3.2 Is it material?

The effect is small (d ≈ −0.21; mean shift 6 % of a piece, ≈ 5 d in a 90 d quarter) but it is not random:
the sign is consistent, and its direction is structural — with parity starting at "injection", every piece
begins with an injection window and alternates, so injections occupy the earlier slots everywhere.

Why it matters for this design specifically: recovery is estimated on injection windows and the false-positive
rate on null windows. A fixed within-quarter time offset means the two headline quantities are measured
under systematically different systematics (Kepler focus/roll/starspot drift within a quarter), which is
precisely the kind of contamination the quarter-clustered design was built to avoid. It would be reported
as a caveat forever; removing it costs one regeneration.

**Classified as a concrete flaw requiring a manifest change.** Per the review instructions, the manifests
are left untouched and approval is requested.

### 3.3 Proposed replacement: paired deterministic allocation

Within each quarter, sort windows by start time and pair them consecutively: `(0,1), (2,3), …`. For each
pair, take a deterministic coin `SHA-256(quarter | pair index)` and assign one member to injection; the
leftover window (odd counts) gets `SHA-256(quarter | "tail")`. Properties:

- **Exactly one injection per pair**, so per-quarter counts stay balanced (≤ 1 difference).
- **No time trend**: within a pair the assignment is random, not "first = injection".
- **Deterministic**: no PRNG state, no dependence on iteration order; the rule is auditable from the hash.
- Applied independently per window length.

Simulated on the current window lists (no files written):

| Quantity | Current | Proposed |
|---|---:|---:|
| Injection / null windows (5 d) | 107 / 100 | 104 / 103 |
| `rel_piece` diff (inj − null) | −0.059 (d = −0.21, p = 0.12) | +0.036 (d = +0.12, p = 0.38) |
| `rel_quarter` diff | −0.036 (p = 0.36) | +0.014 (p = 0.71) |
| Quarters with injection earlier | 12 / 15 (p = 0.035) | 7 / 15 (p = 1.00) |
| Cadences / transits / centres | d ≤ 0.15 | d ≤ 0.11 |
| Test split injection / null | 39 / 35 | 36 / 38 |
| Train / val injection / null | 47/44, 21/21 | 47/44, 21/21 |
| 3-day: injection / null | 176 / 169 | 174 / 171 (test 63/61, train 76/75, val 35/35) |

Feasibility under the frozen minimums still passes for both lengths and for the short-quarter-excluded
sensitivity analysis (test nulls 38 ≥ 20, per-depth balance ≈ 0.5). The 3-day numbers move by ≤ 2 windows.

If approved, the work is: change `_assign_roles()` in `generalization.py` to the paired rule, re-run the
21 tests, regenerate the five manifests, record new hashes in §12 of the plan, and add a regression test
that the role–time association is not systematic (sign test p > 0.10 or |d| < 0.15 on the frozen lists).

---

## 4. Noise, offset, and transit-coverage balance

- **Noise condition:** every window runs both `observed` and `amplified_x2` at every depth, so role × noise
  is perfectly crossed by construction. There is no per-window noise assignment to confound.
- **Hidden offsets:** every window draws two offsets; roles cannot be confounded by offset at the window
  level. However, the offsets are **not materialized** — only `OFFSET_SEED` is frozen, and the realisation
  depends on draw order. Recommendation **R3**: at 11b stage 0 write `offsets.json` (window → two deltas),
  hash it, and verify the role-wise offset distribution (mean ≈ 0, |δ| ≤ 0.10) before any trial runs.
- **Transit coverage:** cadences, transits and transit centres per window are statistically indistinguishable
  between roles (§3.1). The current injection/null split does not favour windows with more or fewer transits.

---

## 5. FPR calibration audit

### 5.1 How thresholds are selected

Declared rule (`experiment_config.json → null_library.calibration_rule`):
`threshold = max(3.0, p95 of calibration null S/N)`, per noise condition, mission = Kepler. S/N is the
matched-filter output of `core.detect` on a depth-0 window.

Pools, from the manifest (primary, 5 d):

| Pool | Windows | Trials per noise condition | Total trials | Use |
|---|---:|---:|---:|---|
| Calibration (train + val nulls) | 65 | 65 × 2 offsets = 130 | 260 | threshold only |
| Test nulls (test quarters) | 35 | 70 | 140 | reported FPR only |
| Paired controls (injection windows) | 107 | 214 | 428 | paired comparisons — excluded from calibration and FPR |

### 5.2 How the 5 % target is implemented

The target is an **empirical quantile**, not a guarantee: the threshold is the 95th percentile of the
calibration null distribution, so ≈ 5 % of calibration nulls are expected above it (≈ 6.5 of 130 per noise
condition). The reported number is not the target but the **achieved test FPR**, with its denominator,
interval and cluster count. If the 3.0 floor binds (p95 < 3.0), the effective FPR can be *lower* than 5 %;
the report must state whether the floor bound and what FPR the floor implies on calibration data.

### 5.3 Within-window and within-quarter dependence

- Two offsets per window are two realisations on the **same cadences** → correlated null S/N values. A
  trial-level p95 over 130 values therefore behaves like fewer than 130 independent draws.
- Windows within a quarter share systematics → the effective sample for calibration is closer to 10
  quarters than 65 windows.
- Handling: keep the trial-level point rule (it is the operating point actually applied per trial), but
  (a) report the **window-level exceedance fraction** (fraction of the 65 windows with ≥ 1 false positive)
  alongside the trial-level rate; (b) report a **quarter-cluster bootstrap interval for the threshold**
  (resample the 10 calibration quarters, recompute p95); (c) quantify the threshold's sampling noise:
  for 130 draws the quantile standard error is ≈ **0.19 σ** (asymptotic `sqrt(p(1−p)/n)/φ(1.645)`), which
  becomes ≈ **0.26 σ** under the design effect of 2 measured in Phase 10. A threshold quoted without that
  range overstates precision.

### 5.4 Uncertainty reported for the FPR itself

Test pool: 140 null trials from 35 windows in 5 quarters. At a true 5 % rate the expected count is 7/140,
with Wilson 95 % ≈ **[0.024, 0.100]**. Illustrative bounds from the same denominator:

| Observed | Rate | Wilson 95 % |
|---|---:|---|
| 0/140 | 0.000 | [0.000, 0.027] |
| 3/140 | 0.021 | [0.007, 0.061] |
| 7/140 | 0.050 | [0.024, 0.100] |
| 12/140 | 0.086 | [0.050, 0.144] |

The Wilson interval ignores clustering; the report will also carry a quarter-cluster bootstrap interval
(resampling the 5 test quarters) and state `k = 5 clusters`. With 5 clusters the cluster interval will be
wider than Wilson, and that is the interval that should be quoted.

### 5.5 Can test controls influence threshold selection?

**Not structurally.** The null library lists calibration quarters = the 10 train+val quarters and test
quarters = the 5 test quarters; they are disjoint sets in the manifest (`null_library.json`), and no
calibration quantity is derived from test windows. A test asserts that calibration and test quarter sets
are disjoint and that test nulls are a subset of test quarters.

**Not yet enforceable in code**, because no Phase 11 fitting code exists. Recommendation **R5**: the
calibration function must take only rows from `calibration_splits`, raise `ValueError` if any row has
`split == "test"` (or `role != "null"`), and be covered by a test that passes a test row and expects the
error. Until that gate exists, the guarantee is documentary, not mechanical — this should be stated in the
Phase 11b report.

---

## 6. Fit / evaluate isolation

No Phase 11 preprocessing, feature, model or calibration code exists yet; only the manifests and the
ladder declaration. The isolation that can be confirmed today is therefore structural, plus what the
ladder declaration forbids. Pre-registered sequence for 11b:

1. Fit preprocessing on **train rows only**: median imputation (NaN → train median), constant-feature drop
   computed on train.
2. Fit scaling inside the model pipeline on **train rows only** (`StandardScaler` in `Pipeline`).
3. Fit models on **train rows only** (L1, L3–L7). No feature selection, no hyperparameter search, no
   cross-split peeking: feature sets are frozen in the config, hyperparameters in the protocol (§8).
4. Select the operating threshold on **validation nulls only** for models that were fit (they never saw
   validation rows during fitting). For the physics detector and the S/N-only baseline, which fit nothing,
   calibrate on the pooled train+val nulls for a tighter estimate, and report the scope per method.
5. Write `fitted.json` (thresholds, imputation medians, scaler parameters, model coefficients where
   applicable) and hash it **before** any test row is read.
6. Evaluate test **once**, from the frozen fitted artifact; `test` rows are refused by the fitting entry
   point.

Gates to implement and test in 11b (R5): (a) `fit_*` refuses any frame containing `split == "test"`;
(b) `evaluate_test()` requires a `fitted.json` whose hash is recorded in the run manifest; (c) an
integration test flips a test row into the training frame and expects failure; (d) no metric is computed
on test before stage 5.

**L7 is the provisional primary model**, so there is no model-selection step at all — which removes the
most common way validation data leaks into test.

---

## 7. L7 pre-registration and comparisons

L7 = `snr`, `depth_est_ppm`, `sigma_ppm` (detector outputs) + `std_ppm`, `mad_ppm`, `mean_flux`
(clean flux features). It contains no truth column, no `min_depth_ppm`, no `n_points`/`gap_fraction`.

| Comparison | Purpose | Pre-registered role |
|---|---|---|
| L7 vs L3 (detector outputs only) | does clean flux add anything? | primary contrast |
| L7 vs L6 (clean flux only) | does the detector add anything? | primary contrast |
| L7 vs L2 (S/N only) | is the combination better than the matched filter? | primary contrast |
| L7 vs L0/L1 (no-skill) | is there any signal at all? | floor |
| L4 vs L5 | `min_depth_ppm` ablation | **diagnostic only, never primary** |
| L4 vs L6 | group identifiers (`n_points`, `gap_fraction`) | diagnostic only |

All comparisons are reported on the same test windows with the same FPR target, with cluster intervals and
prevalence stated. "Better" is not tested by F1; the pre-registered ordering is ROC-AUC, then
recall at the calibrated FPR, then MCC/balanced accuracy.

---

## 8. Constants to freeze before any test evaluation (R2)

These are not yet in the frozen config (adding them as a new `protocol.json` avoids touching the frozen
manifests). Values proposed here, to be written and hashed at 11b stage 0:

| Constant | Value |
|---|---|
| Split seed | `20261022` (frozen) |
| Offset seed | `20261023` (frozen) |
| Model seed | `20261025` (LR `random_state`, RF `random_state`, Dummy) |
| Bootstrap seed / resamples | `20261024` / 10 000, BCa; percentile method `linear` |
| LR | `C=1.0`, `max_iter=1000`, `solver=lbfgs`, `class_weight=None` |
| RF | `n_estimators=200`, `max_depth=6`, `n_jobs=1`, `class_weight=None` |
| Dummy | `strategy="stratified"` |
| Detector threshold | `max(3.0, p95)`; `numpy.percentile(..., method="linear")`; comparison strict `>` (Phase 10 parity) |
| Threshold ties | if the p95 value is tied, use the **smallest** threshold whose calibration exceedance ≤ 5 % |
| ML threshold | p95 of **validation** null scores, same percentile/tie rule |
| FPR target | 0.05; no 1 % target; report achieved rate and bound |
| Metrics | ROC-AUC (`roc_auc_score`), PR-AUC (`average_precision_score`, prevalence stated), recall@FPR, MCC, balanced accuracy, Brier, analytic no-skill F1 |
| Hyperparameter search | none |
| Test reads | exactly one, after `fitted.json` hash is recorded |

---

## 9. Risks

1. **Role–time confounding (§3)** — the one blocking item; fix is cheap, but it invalidates current hashes.
2. **Threshold quantile noise (§5.3)** — p95 from 130 correlated values carries ≈ 0.2–0.3 σ uncertainty;
   a single threshold per noise condition can land 5–10 % off in FPR terms. Report the range.
3. **Floor dominance** — if p95 < 3.0 the floor sets the operating point and the "5 % target" is nominal.
   Must be reported explicitly.
4. **Small test cluster count** — 5 quarters; cluster intervals will be wide and should be quoted over
   Wilson.
5. **Pooled prevalence 0.83–0.85** — pooled F1 is meaningless; the per-depth balanced contrast is the
   evaluation that carries information.
6. **Short quarters (Q00, Q01, Q04, Q17)** — retained by decision; the excluded sensitivity analysis is
   feasible but the primary result will be pulled by Q00/Q17 having 1–2 injection windows.
7. **Hidden offsets not materialized (§4, R3)** — reproducibility depends on draw order until frozen.
8. **TESS is a single cluster** — descriptive only; do not let it enter any interval or comparison table
   without the `k = 1` label.
9. **UI** — no Phase 11 UI exists; do not add run buttons before the analysis is settled (Phase 10 lesson).

---

## 10. Recommended corrections

| # | Correction | Requires manifest change? | Status |
|---|---|---|---|
| R1 | Replace alternating roles with paired deterministic allocation (§3.3) | **yes — hashes change** | **applied 2026-10-22 (§13)** |
| R2 | Add `protocol.json` freezing seeds, hyperparameters, thresholds, tie-breaking, metrics | no (additive) | stage 0 |
| R3 | Materialize `offsets.json` and verify role-wise offset balance | no (additive) | stage 0 |
| R4 | State per-method threshold scope (detector/S-N on train+val; fitted models on validation) | no (protocol text) | stage 0 |
| R5 | Implement fit/evaluate gates and tests (refuse test rows; frozen `fitted.json` before test) | no (code) | stage 1 |

R1 has been applied (§13): the role rule was replaced, six role-allocation tests were added (26 in the
module), the five manifests were regenerated, and the new hashes are recorded. Phase 11b may proceed once
R2–R5 are done at stages 0–1.

---

## 11. Conditional smoke test and Phase 11b sequence

**The runner does not exist yet** — `research/generalization.py` only builds manifests, and Phase 11b has
not been implemented. The command below is the exact interface to be created at stage 1; it is not runnable
today and no smoke run has been performed.

### 11.1 Exact smoke command (after stage 1, R1 decision applied)

```powershell
cd %USERPROFILE%\astronomy-ai\webapp\backend
.\.venv\Scripts\python.exe -m research.run_phase11 --mode smoke `
  --window-days 5 --quarters Q00,Q01,Q04 `
  --out ..\..\reports\phase11_generalization\smoke
```

Smoke is **train+val only by design** (Q04/Q00 = train, Q01 = val) so it exercises injection, detection,
threshold calibration, model fitting and metric computation without reading a test quarter.

| Expected | Value |
|---|---|
| Quarters / windows | 3 / 12 (6 injection, 6 null) |
| Trials | 6 × 24 + 6 × 4 = **168** |
| Runtime | ≈ 4 s (cost model) |
| Outputs | `trials.csv`, `thresholds.json`, `fitted.json`, `metrics_val.json`, `smoke_summary.json` |
| Acceptance | 168 rows; splits ⊂ {train, val}; **zero test rows**; thresholds per noise recorded with floor status; models fitted on train only; rerun byte-identical `trials.csv` |

### 11.2 Proposed Phase 11b sequence

1. **Stage 0 — freeze protocol (R2–R4).** Write `protocol.json` and `offsets.json`; record hashes; verify
   role-wise offset balance. No detector call.
2. **Stage 1 — runner + gates (R5).** Implement `research/phase11.py` (campaign, calibration, fit,
   evaluate) and its tests, including the "test row in training set raises" test. No campaign.
3. **Stage 2 — smoke.** Run §11.1; verify the acceptance table; discard the output directory from inference.
4. **Stage 3 — primary campaign (5 d).** `--mode full --window-days 5 --out .../primary`
   (≈ 2 968 trials, ≈ 67 s). Re-run once to confirm determinism. No test analysis yet.
5. **Stage 4 — sensitivity campaign (3 d).** Same command with `--window-days 3 --out .../sensitivity`
   (≈ 4 900 trials, ≈ 104 s). Reported separately; never used to choose the primary window length.
6. **Stage 5 — fit, freeze, evaluate once.** Fit on train, thresholds on validation (detector on train+val),
   write and hash `fitted.json`, then a single test pass with cluster bootstrap; TESS descriptive only.
7. **Stage 6 — report + acceptance table.** Update the research plan, record all hashes, and state the
   non-claims (one star, synthetic injection, no discovery).

---

## 12. Status

- **R1 applied.** `windows_primary.json`, `windows_sensitivity.json`, `null_library.json`,
  `split.json` and `experiment_config.json` were regenerated (hash changes recorded in §13).
- **No campaign was run, no model was trained, no historical artifact touched.** Phase 11b has not started.
- **Next:** R2–R5 at stages 0–1, then the smoke command in §11.1, then the campaign sequence §11.2.

## 13. R1 applied — paired deterministic allocation (2026-10-22)

Approved by the reviewer and implemented. Nothing else in the design changed: gap threshold, window
lengths, split assignment, depths, offsets, noise conditions, target FPR and the ML ladder are exactly as
frozen in Phase 11a.

### 13.1 What changed

| File | Change |
|---|---|
| `webapp/backend/research/generalization.py` | new `role_coin()` + `assign_roles()`; `generate_windows()` now delegates role assignment; manifest rule text updated; module docstring updated |
| `webapp/backend/tests/test_generalization.py` | +6 role tests (21 → 26 in the module; backend total 73 → 78) |
| `reports/phase11_generalization/{split,windows_primary,windows_sensitivity,null_library,experiment_config}.json` | regenerated |

The rule: sort the quarter's windows, pair consecutive ones `(0,1), (2,3), …`, and use
`SHA-256("phase11-role-v2" | quarter | "pair-<k>" | window_days)` to decide which member of the pair is
injected. An odd leftover window is decided by `SHA-256(… | "tail" | …)`. The window length is in the key,
so the 5 d and 3 d allocations are independent draws over their own inventories.

**Assignment inputs are identifiers only.** No flux, noise realisation, detector score, recovery label,
split outcome or test performance enters the coin. Tests enforce this: roles are unchanged when flux is
rescaled ×3 + 0.5, and unchanged when `OFFSET_SEED` is changed.

### 13.2 What did not change

Quarter→split assignment (train 7 / val 3 / test 5), gap threshold 1.0 d, window geometry, depths
{50, 75, 100, 150, 300} + control 0, two hidden offsets, two noise conditions, target FPR 5 %, L7 as
provisional primary, forbidden-feature list. No historical artifact, source CSV, or Phase 4/5/10 output
was touched.

### 13.3 New counts

Primary (5 d, 207 windows): **102 injection / 105 null** (was 107/100).

| Quarter | Inj | Null | Diff | Quarter | Inj | Null | Diff |
|---|---:|---:|---:|---|---:|---:|---:|
| Q00 | 1 | 1 | 0 | Q09 | 9 | 10 | −1 |
| Q01 | 3 | 3 | 0 | Q10 | 9 | 9 | 0 |
| Q02 | 8 | 8 | 0 | Q11 | 8 | 8 | 0 |
| Q03 | 8 | 9 | −1 | Q13 | 8 | 9 | −1 |
| Q04 | 2 | 2 | 0 | Q14 | 8 | 9 | −1 |
| Q05 | 9 | 9 | 0 | Q15 | 9 | 8 | +1 |
| Q06 | 9 | 9 | 0 | Q17 | 3 | 2 | +1 |
| Q07 | 8 | 9 | −1 | **total** | **102** | **105** | |

By split: train 45/46, val 21/21, test 36/38. Sensitivity (3 d, 345 windows): 173/172 overall
(train 75/76, val 35/35, test 63/61), per-quarter difference ≤ 1 everywhere.

Null library (5 d): calibration 67 windows / 268 trials; test 38 windows / 152 trials; paired controls
102 windows / 408 trials. Projected campaign: **2 868 trials / 65 s** (was 2 968 / 67 s); 3 d:
**4 840 trials / 103 s** (was 4 900 / 104 s). Feasibility still passes all frozen minimums at both
lengths and under short-quarter exclusion.

### 13.4 Balance before vs after

| Diagnostic (5 d) | Before (alternating) | After (paired coin) |
|---|---:|---:|
| Position in piece, Cohen's d | −0.21 (p = 0.12) | **−0.09 (p = 0.56)** |
| Position in quarter, d | −0.13 (p = 0.36) | **−0.07 (p = 0.63)** |
| Quarters with injection earlier | 12/15 (p = 0.035; 12/13 p = 0.0034) | **10/15 (p = 0.30)** |
| Cadences per window, d | +0.15 | **0.00** |
| Transits per window, d | +0.05 | −0.14 (p = 0.34) |

3 d after correction: position in piece d = 0.00 (p = 0.99), position in quarter d = 0.00 (p = 1.00),
sign test 7/15 (p = 1.00). The correction removes the systematic direction; it does **not** produce perfect
balance, and the residual differences are reported above rather than claimed away. The 5 d transit-count
difference (d = −0.14) is the largest remaining imbalance and is not statistically distinguishable from
zero at this sample size.

The prototype simulated in §3.3 predicted 104/103; the implemented coin key yields 102/105. The simulation
was illustrative; the implemented allocation is the authoritative one.

### 13.5 New artifact hashes

| Artifact | SHA-256 (first 16) | Bytes | Supersedes |
|---|---|---:|---|
| `split.json` | `5931f5b4fc7450bb` | 8 576 | `f22213caa28babfd` |
| `windows_primary.json` | `6d8eb4b4efad96ab` | 67 098 | `36e6adb172c971ec` |
| `windows_sensitivity.json` | `b89c6bded0c0b22a` | 111 608 | `a7693993ba537569` |
| `null_library.json` | `767ff9408c70a9c9` | 3 480 | `fb295e24b6eba62f` |
| `experiment_config.json` | `43fbddc15c74c626` | 5 967 | `71f2ed9c2648ddc5` |

`split.json` changed as well because it embeds per-quarter injection/null counts. All five are
byte-reproducible: the determinism test writes them twice into temporary directories and compares bytes.

### 13.6 Verification run

```
webapp/backend>  python -m pytest -q                     78 passed, 1 warning
webapp/backend>  python -m pytest tests/test_generalization.py -q   26 passed
webapp/backend>  python -m ruff check .                  All checks passed!
```

Growth is +5 net tests over Phase 11a (one alternating-role assertion replaced by six role tests):
valid roles and per-quarter balance, deterministic reproducibility, odd-tail coin, flux invariance, offset-seed
invariance, and a temporal-balance guard (|d| < 0.25 and sign-test p > 0.10 on the frozen lists).

Historical artifact hashes (Phase 4/5/10 inputs and outputs) are unchanged; `git diff --check` is clean;
nothing is staged or committed.

### 13.7 Protocol and hidden offsets — separation confirmed

- **Roles** depend only on `version | quarter | pair/tail index | window length` (tested invariant to flux
  and to `OFFSET_SEED`). No test-quarter outcome existed at allocation time: no campaign has run.
- **Hidden offsets** are still a separate draw (`OFFSET_SEED`), are not stored in any manifest, and are not
  read by the role rule. Stage 0 will materialize them as `offsets.json`, hashed independently, and verify
  role-wise offset balance.
- **Protocol constants** (R2) are likewise a separate artifact to be created and hashed at stage 0; changing
  them cannot change roles, because roles depend only on manifest identifiers.

### 13.8 Remaining risks

1. Residual transit-count imbalance (5 d, d = −0.14, p = 0.34) — small, non-significant, but not zero.
2. Tail coins are single draws, so per-quarter counts differ by one by construction; with 2–5 window
   quarters (Q00, Q17, Q04, Q01) this is proportionally larger.
3. Threshold p95 uncertainty (§5.3) is unchanged: ≈ 0.19 σ (0.26 σ with the measured design effect), and the
   floor may bind.
4. Test FPR denominator is now 152 null trials (was 140); expected ≈ 7.6 false positives at 5 %.
   For 8/152 the Wilson 95 % interval is [0.027, 0.100] — still wide but usable.
5. Offsets and protocol are still unfrozen (R2/R3 at stage 0).
6. Any future change to `MAJOR_GAP_DAYS` or window geometry reshuffles roles by design and requires a new
   role-coin version plus regenerated manifests.

*R1 complete. Phase 11b has not started; awaiting approval of this correction and of stages 0–1.*
## 14. Protocol v2.2 and Stage 2 hardening audit (2026-10-22)

Read-only audit of the code and protocol review. No campaign, fitting, test-trial
generation or sealed-test access was performed to produce this section.

### 14.1 Artifacts audited

| Artifact | SHA-256 | Note |
|---|---|---|
| `protocol_v2.json` | `7d69d461…23bec` | unchanged, superseded |
| `protocol_v2_1.json` | `bae1cc58…21a80` | unchanged, superseded |
| `protocol_v2_2.json` | `61f67198…24814a` | new, authorized correction |
| `research/phase11_v2.py` | `dd6d79b1…cbc8b` | 1044 lines, new |
| `research/run_phase11_v2.py` | `74d44c57…498185` | 130 lines, new |
| `tests/test_phase11_v2_stage2.py` | `b66cca88…7b563d` | 72 tests |
| `tests/test_phase11_v2_review.py` | `19ddf043…fef0b` | 19 tests |

### 14.2 v2.2 correction

Authorized scope was the false `thresholds.existence_argument` sentence only. Verification:

- The generator performed a recursive field-by-field comparison of v2.1 and v2.2 and
  aborted on any difference outside an allow-list. The recorded changed paths are exactly:
  `version`, `status`, `frozen_at`, `immediate_predecessor.*`, `thresholds.existence_argument`,
  `thresholds.tie_lift_note`, `changelog_vs_v1[len]`, `input_verification.verified_at`.
- Every other threshold field and all ten operative top-level blocks (`detection`,
  `comparison`, `fpr`, `reporting`, `data_roles`, `test_access`, `provenance`,
  `frozen_inputs`, `insufficient_data`, `bootstrap`, `approval_decisions`) compare equal.
- Predecessor hash is bound and matches the v2.1 bytes (`bae1cc58…`).
- The corrected arithmetic was re-derived independently: `e(q) = ceil((n-1)a)/n` reproduces
  n = 30 → 2/30 = 0.0667, n = 42 → 3/42 = 0.0714, n = 76 → 4/76 = 0.0526, n = 134 →
  7/134 = 0.0522, with post-lift values 0.0333, 0.0476, 0.0395, 0.0448. The claim that
  lifting is the normal path at the frozen sizes is therefore correct, and the L7 pool of 42
  will lift on every run.
- No scientific rule changed, so the authorized stop condition was not triggered.

### 14.3 Stage 2 implementation review

Defects found and fixed in this stage, each with a regression test:

| # | Defect | Effect before the fix | Fix |
|---|---|---|---|
| 1 | `_git` let `OSError` escape | missing git/repo raised `FileNotFoundError`, not a gate refusal | wrapped, raises `GateError` |
| 2 | `source_manifest_hash` hashed missing paths | `FileNotFoundError` instead of a refusal | existence check → `GateError` |
| 3 | `load_protocol_v21` indexed `frozen_inputs["files"]` | `KeyError` on a malformed protocol | mapping check → `GateError` |
| 4 | non-finite `floor` silently ignored | `NaN` floor disabled the floor instead of refusing | finite check → `GateError` |
| 5 | `mmd <= 0` accepted | a zero or negative MMD would license trivial "superiority" | must be positive or `None` |
| 6 | `resamples < 2` accepted | degenerate bootstrap with no useful interval | minimum 2 enforced |
| 7 | `fitted.json` without `model_sha256` | `KeyError` instead of a refusal | explicit check |
| 8 | unknown comparison status mapped to `not_superior` | a typo could silently become a verdict | `GateError` |

Reviewed and judged sound:

- **Threshold edge cases.** Candidate set includes `t0`; `e(max) = 0` guarantees existence;
  floor binding is strict; `floor == q` labels `quantile`; tie-lift is reachable and
  correct; saturation at the score supremum sets `threshold_degenerate`; the exceedance
  bound is re-asserted after selection; 20 randomised seeds confirm `e <= 0.05`.
- **Atomic markers.** Creation is `O_CREAT|O_EXCL`, so a concurrent second start fails
  closed; the only transition is `started → completed` via atomic replace; an interrupted
  run leaves `started` and every retry refuses; an unreadable marker is `invalid`, never
  absent; no code path deletes or resets a marker (asserted against the source text).
- **Protocol/hash binding.** Four independent checks: sidecar, exact pin, header, sections,
  then operative invariants. The pin now resolves at call time, so the CLI test can prove
  the pin is enforced rather than bypassed.
- **Comparison gates.** Percentile primary with BCa diagnostic on the same draws; FPR
  mismatch, heterogeneity, degenerate interval, cluster count and status validation all
  force `inconclusive`; `practical_superiority_claim` is hard-wired `False`.

### 14.4 Residual risks carried forward

1. `complete_marker` reads then atomically replaces without a lock. A concurrent double
   completion can produce a last-writer-wins record. It cannot cause a second test read,
   because every gate tests marker **existence**, not status; documented rather than
   locked, to avoid introducing a lock file that could itself go stale.
2. `write_json_with_sidecar` writes the JSON and the sidecar as two operations. A crash
   between them leaves a JSON without a valid sidecar, which `load_fitted_v21` refuses.
   Partial state fails closed but is not removed automatically.
3. Five-cluster bootstrap remains weakly identified; the module states the limitation in
   every result.
4. L7 saturation at 1.0 remains a live possibility at 42 calibration nulls and is only
   discoverable at calibration time.
5. The frozen `environment` block in v2.2 records the repo-root interpreter (Python 3.11.17)
   and is superseded by `reports/phase11_environment.md`. Correcting it needs v2.3.
6. The Phase 11 sources are still untracked at the baseline commit; provenance relies on the
   source-manifest hash rather than a commit id.

### 14.5 CLI

`research/run_phase11_v2.py` supports `preflight` only. It has no `--execute` flag and imports
nothing from the v1 runner (asserted by test). Exit codes: 0 success, 2 CLI refusal, 3 gate
refusal. Refusal paths covered by tests: every campaign mode, missing `--out`, gate failure,
and an unpinned protocol hash.

### 14.6 Test evidence

```
cd webapp/backend
.venv/Scripts/python.exe -m pytest tests/test_phase11_v2_stage2.py tests/test_phase11_v2_review.py -q
→ 91 passed
```

72 Stage 2 tests plus 19 review/CLI tests, all synthetic-only; collection across the whole
suite is 275 tests (184 previously verified + 91 new). `ruff check` and `ruff format --check`
are clean on all four files.

### 14.7 Preservation evidence

All 21 protected paths are byte-identical to the pre-stage snapshot: the nine v1 frozen
inputs, the four v2/v2.1 artifacts, and the eight files in the two historical smoke
directories. `git diff --stat` is empty; nothing is staged; HEAD is still `230c5ae8…`.

### 14.8 Status

The protocol and code are internally consistent and fail closed on the paths that were
audited. This section does **not** authorize a campaign: the minimum meaningful difference
remains unset (descriptive-only outcomes), no execution path exists by design, and the
saturation risk at 42 calibration nulls is still unresolved until calibration actually runs.
