# Phase 8 — Synthetic Dataset Pipeline Audit and Corrected Evaluation

**Status:** complete — awaiting review. No commit, no push, no Phase 3/4 artifact touched.
**Question:** does the Phase 7 mismatch between the saved Phase 5 dataset and the current builder mean the
historical ML metrics are contaminated?

**Answer: no.** The saved dataset was built the correct way round; the post-Phase-7 builder is the one
that deviated. One genuine (small) leakage path did exist in Phase 5 and is corrected here. Re-evaluated
under a clean protocol, every test metric reproduces the historical values exactly.

---

## 1. The data-generation path, traced

Two builders exist. They select and inject identically and differ in exactly one place: which array the
features are computed from.

### 1.1 Window selection and injection (both builders)

| Step | Phase 5 (`scripts/phase5_build_dataset.py`) | Phase 8 (`scripts/phase8_build_dataset.py`) |
|---|---|---|
| Load + fold + detrend | `load_dataset` / `fold_phase` / `detrend_poly` (imported from `transit_analysis.py`) | same |
| Split into contiguous segments (>1 d gaps) | L44–45 | L107 |
| One window per qualifying segment (≥100 pts) | L61–65 | L112–115 |
| Random centre, `default_rng(42).integers(...)` | L67 | L116 |
| ±6 h window mask; skip <10 points | L72–75 | L117–119 |
| Positive/negative by segment parity | L65 (`seg_idx % 2 == 0`) | L114 |
| Depth draw `rng.choice([75,150,225,300])` | L89 | L129 |
| `batman_curve(phase, rp, 0.0, ...)` at phase 0 | L92 | via `inject_transit` L92–97 |
| Injection arithmetic `flux + median(flux) * (model - 1)` | L101–102 | L97 |

The RNG call sequence is identical, so both builders produce the same 26 windows, the same 13/13 label
balance, and the same injected depth per segment. Verified: `segment_id`, `label`,
`injected_depth_ppm`, `n_points`, `window_start_bkjd` match for all 26 windows.

### 1.2 Where the features are computed — the only divergence

| | Phase 5 (current) | Phase 8 (corrected) |
|---|---|---|
| Array passed to the feature code | `win_flux_dt` — detrended flux **before** injection (L107, L110–111, L117, L121–127, L129–132) | `presented_flux` — the flux the classifier sees (L131 positives, L134 negatives), one call site at L137 |
| Fate of the injected series | `synthetic` is computed at L96–102 and **never read again** | *is* the presented flux |
| Positive example semantics | features describe a window from which the transit has been removed | features describe a window containing the transit |
| Negative example | `synthetic = win_flux_dt.copy()` (L104) → identical either way | identical either way |

Saved artifact (`reports/phase5_dataset.json`, frozen) matches the **presented-flux** order, not the
current script. Rebuilding with `scripts/phase8_build_dataset.py` reproduces it exactly:

```
windows: 26 | window keys equal: True | identity fields identical: True
window field mismatches across 26 windows × 13 fields: 0
```

So the frozen artifact was written by an earlier revision of the Phase 5 script that used `synthetic`;
the script was later edited to use `win_flux_dt` without regenerating the artifact. That edit is the
`win_flux_dt`/`synthetic` split the Phase 7 audit detected, and it points the opposite way from the
Phase 7 conclusion.

### 1.3 Label assignment and save

Label is structural (`1 if is_positive else 0`, Phase 5 L133 / Phase 8 L138), written alongside
`injected_depth_ppm` into the JSON (Phase 5 L143–161 / Phase 8 L141–160). No feature reads either field.

---

## 2. Signal versus leakage, feature by feature

The test is the one Phase 8 specifies: does the feature use the input the classifier has at inference
time (fine), or does it use labels/injection metadata, process the classes differently, or borrow
statistics from other windows or splits (leakage)?

| Feature | Computed from | Uses label/depth? | Class path | Verdict |
|---|---|---|---|---|
| `depth_rel_ppm` = (median − min)·1e6 | presented flux | no | same for both | **signal** — a transit lowers the minimum; a real transit would too |
| `contrast_ppm` = mean(out) − mean(in) | presented flux, phase mask | no | same | **signal** |
| `mad_scatter` | presented flux | no | same | **signal** (robust scatter) |
| `gap_fraction` | window timestamps | no | same | **signal** (observing-condition covariate, no transit content) |
| `matched_filter_corr` | presented flux vs fixed 150 ppm template | no — template depth is a constant, not the injected draw | same | **signal** |
| `segment_std_ppm` | presented flux | no | same | **signal** — rises when a transit is present, as it would for a real one |
| `mean_flux` | presented flux | no | same | **signal** (weak, level covariate) |

Therefore: **a feature changing when a synthetic transit is injected is the intended detection signal,
not leakage.** If positives were described by transit-free flux, the label would be unpredictable from
the features — which is exactly what the current Phase 5 script produces. Measured on that variant (same
windows, same split, same model):

```
PRE-injection features (current scripts/phase5_build_dataset.py):
  test AUC = 0.5833   test F1@0.5 = 0.5714   (dummy F1 ≈ 0.57)
```

AUC 0.583 on seven windows is chance. The repaired-but-pre-injection pipeline would have destroyed the
task rather than fixed it.

### 2.1 The one real leakage found — imputation across splits

`scripts/phase5_features.py:33` computes
`median_corr = df["matched_filter_corr"].median()` over **all 26 rows** and then fills 9 undefined
correlations (`:34`). Those 26 rows include the test split, so a test-set value influences a test-set
feature. It is unsupervised and tiny, but it is cross-split preprocessing and violates the Phase 8 rule.

Magnitude: all-window median 0.843895 vs train-only median 0.787757; 9 of 26 values imputed; the decision
threshold moves by 0.00058; **no test metric changes** (§4).

### 2.2 Other Phase 5 protocol issues found (not leakage)

- `phase5_baseline.py:146–148` compared the RandomForest **validation** F1 (0.80) against the baseline
  **test** F1 (0.75). The test score influenced model selection. Corrected in Phase 8 to validation-vs-
  validation.
- The split was recomputed inside the evaluation script from a global RNG (`:51–55`) rather than being
  stored with the rows. Corrected: `scripts/phase8_split.py` is the single source of truth and the split
  is written into the feature file.

---

## 3. Corrected pipeline (new paths only)

| Script | Role | Output |
|---|---|---|
| `scripts/phase8_build_dataset.py` | window selection + injection (unchanged RNG) + features from `presented_flux` via a pure `extract_features(flux, phase, time)` | `reports/phase8_dataset.json` |
| `scripts/phase8_features.py` | split assignment recorded per row; `matched_filter_corr` imputed with the **train-only** median | `reports/phase8_features.csv`, `reports/phase8_feature_config.json` |
| `scripts/phase8_eval.py` | LR on train, Youden threshold on val, one test pass; RF compared on validation F1; experiment seed 4242 | `reports/phase8_results.json`, `.md` |
| `scripts/phase8_split.py` | `RandomState(42)` shuffle, 50/25/25 cut — the historical rule | (module) |

Nothing under `reports/phase5_*`, `reports/results/`, `data/`, or `scripts/phase3–5*` was modified.
`phase8_dataset.json` differs from `phase5_dataset.json` only in metadata (`generated_by`, an added
`feature_source` key) and key order; all 26 window payloads are identical.

---

## 4. Re-evaluation without test leakage

### 4.1 Protocol

- Split preserved exactly: segment-level, `RandomState(42)`, cut 50/25/25.
  **Verified** by re-running the Phase 8 evaluator on the *historical* feature file: it returns
  `threshold = 0.4405000426188111`, the Phase 5 value to 16 digits, with the identical confusion matrix.
  So the split and model code are unchanged; only the imputation statistic differs.
- LogisticRegression(C=1.0, max_iter=1000) fitted on train only.
- Threshold: Youden index on validation predictions only.
- Test set scored once, after the threshold was frozen.
- RandomForest(200, max_depth=6, `random_state=4242`) admitted only if its validation F1 beats the
  baseline **validation** F1 by >0.05.
- New experiment seed (4242) for stochastic estimators; split seed stays 42 for comparability.

### 4.2 Splits (exact counts)

| split | windows | parent groups | positive | negative |
|---|---:|---:|---:|---:|
| train | 13 | 13 | 6 | 7 |
| val | 6 | 6 | 3 | 3 |
| test | 7 | 7 | 4 | 3 |

Every parent segment contributes exactly one window and appears in exactly one split.

### 4.3 Test-set metrics — corrected vs historical

| Metric | Phase 5 historical | Phase 8 corrected | Δ |
|---|---:|---:|---|
| threshold | 0.440500 | 0.439923 | −0.00058 |
| precision | 0.7500 | 0.7500 | 0 |
| recall | 0.7500 | 0.7500 | 0 |
| F1 | 0.7500 | 0.7500 | 0 |
| accuracy | 0.7143 | 0.7143 | 0 |
| confusion matrix | [[2,1],[1,3]] | [[2,1],[1,3]] | 0 |
| ROC-AUC | 0.6667 | 0.6667 | 0 |
| PR-AUC | 0.7708 | 0.7708 | 0 |
| stratified dummy F1 | 0.5714 (`seed 42`) | 0.5000 (`seed 4242`) | seed change only |

Baseline validation F1 is 1.0 (perfect separation on 6 validation windows); RandomForest validation F1
is 0.80, so RF is not selected — now for the correct reason (underperforms the baseline on validation,
not "compares against a test number"). Both the historical and corrected runs reach the same decision;
the corrected rule simply no longer peeks at the test set.

**Caveats, stated plainly:** seven test windows; one different classification moves F1 by ±0.15; the
features are computed from simulated flux injected at the published ephemeris, so the task is
"recover an injected, correctly-phased transit", not "discover a planet"; and ROC-AUC 0.667 on n=7 is
essentially uninformative. No significance claim is made.

---

## 5. Tests

New: `tests/test_phase8_pipeline.py` — 8 tests, all passing.

| Requirement | Test |
|---|---|
| features come from the intended simulated input | `test_features_use_the_presented_flux`, `test_deeper_injection_produces_larger_depth_feature` |
| …and the frozen artifact is that same pipeline | `test_phase8_dataset_matches_the_frozen_phase5_dataset` |
| extractor cannot see labels/depth | `test_extractor_signature_and_body_exclude_labels` (AST: args are exactly `flux, phase, time`; no `label`/`injected_depth_ppm`/`is_positive`/`depth_ppm`/`segment_id`/`split`) |
| one processing path for both classes | `test_single_extraction_site_for_both_classes` (exactly one call site, on `presented_flux`) |
| parent groups never cross splits | `test_parent_groups_do_not_cross_splits` (disjoint sets, union complete, 13/6/7) |
| preprocessing fitted on train only | `test_imputation_median_is_fitted_on_train_rows_only` (recomputes the train-only median from the raw dataset and asserts it differs from the all-window median) |
| reproducible under a fixed seed | `test_rebuild_is_deterministic` (two independent builds, byte-identical JSON) |

Updated: `tests/test_phase5_builder.py`. Its former assertion that features *must* use `win_flux_dt` is now
labelled as the known Phase 5 defect it is, and the strict `xfail` reason now points at §2 of this report
instead of the retracted Phase 7 leakage claim.

Actual runs:

```
> .\.venv\Scripts\python.exe -m pytest tests/test_phase8_pipeline.py -v
8 passed in 8.37s

> .\.venv\Scripts\python.exe -m pytest tests -q
27 passed, 1 xfailed in 8.12s        (exit code 0)
```

The single `xfail` is the deliberate tripwire that the Phase 5 script's pre-injection features differ from
the frozen dataset.

---

## 6. Preservation

No pre-existing scientific artifact changed. Hashes match the values recorded in the Phase 6 and Phase 7
reports:

| Artifact | SHA-256 |
|---|---|
| `reports/results/phase3_transit_analysis.json` | `045073e2…b72ea22` |
| `reports/results/phase4_block_bootstrap.json` | `d4e2de41…2591df9` |
| `reports/results/phase4_injection_recovery.json` | `57b67864…d65540f` |
| `reports/results/phase4_model_comparison.json` | `a8183377…1fee813` |
| `data/processed/kepler_all_quarters_quality_masked.csv` | `9a457cf9…05194d82` |
| 10 × `reports/figures/phase3_*.png` | unchanged, all distinct |

`reports/phase5_dataset.json`, `phase5_features.csv`, `phase5_feature_config.json`,
`phase5_results.json`, `phase5_results.md` and `reports/phase7_reliability_audit.md` are byte-identical
to their Phase 7 close state. Full-tree comparison of the report/data artifact set: 0 pre-existing files
changed, 5 Phase 8 artifacts added (plus the Phase 8 scripts, tests and this report).

---

## 7. Recommendation

1. **The Phase 5 metrics are scientifically interpretable** and should be retained as the project's ML
   result — but only with the framing already in the Phase 5 report: synthetic labels, 26 windows,
   7 test windows, no real-planet claim. They are not inflated by label leakage. Re-evaluation under a
   stricter protocol reproduces every test metric to the digit.
2. **Do not regenerate `reports/phase5_dataset.json`.** It is the correct artifact. Phase 7's proposal to
   regenerate it from the repaired builder would have replaced valid features with chance-level ones
   (AUC 0.583).
3. **Retract Phase 7 finding R1.** Its "metrics are inflated, quote only with this caveat" conclusion is
   wrong on the evidence in §1–§2. The correct statement is: *the frozen dataset uses presented-flux
   features, which is the intended order; the builder was edited after the artifact was written.*
4. **Fix `scripts/phase5_build_dataset.py`** (one-line class of change: features from `synthetic`) or mark
   it superseded by `scripts/phase8_build_dataset.py`. Not done here, to avoid touching a Phase 5 script
   without approval.
5. **Keep the Phase 8 imputation fix.** It is the only real leakage repair, and it changes no metric.
6. Treat the ML section as a pipeline demonstration, not a result: with 26 windows the honest headline is
   "the pipeline recovers injected transits", not a performance number.

### 7.1 Items requiring approval before proceeding

| # | Item | Why it waits |
|---|---|---|
| A1 | Correct README §4 item 6 and §9 items 1–2, which currently assert the retracted leakage claim | Explicitly out of scope ("stop before changing the root README's headline ML results") |
| A2 | Correct or deprecate `scripts/phase5_build_dataset.py` | Changes a Phase 5 script |
| A3 | Annotate `reports/phase7_reliability_audit.md` §1 as retracted | Preserves the historical record until you approve an erratum |
| A4 | Whether `reports/phase5_results.md` should gain a pointer to this audit | Frozen Phase 5 artifact |

---

## 8. Files in this phase

**New:** `scripts/phase8_build_dataset.py`, `scripts/phase8_split.py`, `scripts/phase8_features.py`,
`scripts/phase8_eval.py`, `tests/test_phase8_pipeline.py`, `reports/phase8_dataset.json`,
`reports/phase8_features.csv`, `reports/phase8_feature_config.json`, `reports/phase8_results.json`,
`reports/phase8_results.md`, this report.

**Modified:** `tests/test_phase5_builder.py` (assertion relabelled from "requirement" to "known defect";
xfail reason corrected). No scientific artifact modified.

**Not committed, not pushed.**

---

## 9. Post-review actions (applied after the user authorized continuation)

The §7.1 items were approved and executed. Recorded here so the audit trail closes.

| Item | Action | Verification |
|---|---|---|
| A2 | `scripts/phase5_build_dataset.py`: the seven features are now computed from `synthetic` (the presented flux) instead of `win_flux_dt`. Comment added explaining why. | Running the corrected script in an isolated copy reproduces `reports/phase5_dataset.json` **byte-for-byte**: `f8ad47fb2a404b41…1da5d4`. The frozen artifact was not touched. |
| A2-tests | `test_phase5_builder_uses_the_presented_flux` (was: the defect pin) now asserts features reference `synthetic` and never `win_flux_dt`. The strict `xfail` on `test_saved_dataset_matches_repaired_builder` was removed; it is now a passing regression guard. | `28 passed` (was 27 passed + 1 xfailed). |
| A1 | README corrected: §3 ML table now states the Phase 8 re-derivation and cites the audit; §4 limitations 6 and 9 replaced the retracted leakage caveat with the correct signal/leakage distinction; §8 test counts updated to 28; §9 known issues 1–2 replaced with the retraction and the imputation fix; §10 index and §11 provenance updated. | `grep` for "not leakage-free"/"8 of 26"/"1 xfailed" in README returns nothing. |
| A3 | `reports/phase7_reliability_audit.md` gained a dated ERRATUM block at the top retracting R1 and naming the superseded sections. Original text preserved unchanged below it. | Original §1–§12 text intact; only the header block added. |
| A4 | Not applied — `reports/phase5_results.md` is a frozen Phase 5 artifact; a pointer would alter its bytes. The Phase 8 audit is linked from README instead. | — |

**Still unchanged and verified after these edits:** `reports/phase5_dataset.json`
(`f8ad47fb…`), `phase5_features.csv`, `phase5_results.{json,md}`, all four `reports/results/phase4_*.json`,
`reports/results/phase3_transit_analysis.json` (`045073e2…`) and the ten `phase3_*.png` figures.

**Remaining decision:** whether to fold the Phase 8 scripts into the Phase 5 numbering (renumber, deprecate
the Phase 5 builder) or keep both chains side by side. Both currently agree byte-for-byte, so this is
housekeeping, not a scientific choice.
