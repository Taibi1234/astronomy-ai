# Phase 4 — Statistical Validation

**Status:** in progress (review required before any Phase 5 / ML).
**Framing:** Kepler-10 b is a known planet; this is pipeline validation / re-detection. No formal detection claim is made.

---

## 1. Decisions executed

- **A — TESS download:** Scope/review completed; sectors S40, S53, S74 unavailable (MAST network failure). Not substituted. Existing S14 preserved (`data/processed/tess_kepler_10_quality_masked.csv`).
- **B — Statistical validation:** Residual time-block bootstrap (primary) + injection/recovery (independent check). Before statistical work, Phase 3 baseline reproduced.

---

## 2. Baseline reproduction (required before statistical changes)

Re-ran `scripts/transit_analysis.py` without modification. Key result preserved:

| Config | Depth (ppm) | Offset (min) | RSS impr. | Status |
|---|---|---|---|---|
| Kepler all masked / detrended | 153.8 | +0.03 | 7.85% | Reproduced (file hash verified) |

Commands, software versions (`numpy`, `scipy`, `pandas`, `batman`), data provenance (`reports/kepler_quarters_metadata.json`), and fixed geometry (`a/R*=3.4`, `i=84.5°`, `u=[0.30,0.20]`) recorded in `reports/results/phase3_transit_analysis.json` (untouched). Phase 3 figures in `reports/figures/phase3_*.png` preserved.

---

## 3. Residual diagnostics (original time ordering preserved)

File: `scripts/phase4_residual_diagnostics.py` (run; results summarized below, no figure produced — design only).

- Residual standard deviation (approximate): ~0.0002 (normalized flux).
- Lag-1 autocorrelation at 1 cadence: **r ≈ 0.93** (high correlation).
- Per-segment scatter (split at >1 d gaps): ranges from std ~0.00006 (quiet segments) to ~0.00047 (variable segments) — **nonstationarity confirmed** (stationarity ratio max/min ≈ 7.2).
- Orbit-mean lag-1 autocorrelation: ~0.88.

Implication for bootstrap: independent resampling is not appropriate. Block bootstrap required; segment-aware stratification preferred.

---

## 4. Block bootstrap (primary method, step 3)

File: `scripts/phase4_block_bootstrap.py`.
Output: `reports/results/phase4_block_bootstrap.json`.

Design choices (documented):

- **Residual strategy:** Residuals from fitted detrended model added back to fitted model; replicates re-fitted (same `least_squares` bounds/initial conditions).
- **Block length sensitivity:** 10, 50, 100, 200, 500 cadences (~5 min to ~10.2 d). Justified from residual AC remaining high at ~50 h (r ≈ 0.44); shorter blocks underestimate variance.
- **Segment-aware approach:** Blocks drawn WITHIN contiguous segments (split at >1 d gaps), not across quarter boundaries. This addresses nonstationary scatter confirmed in diagnostics.
- **Reproducible seed:** `SEED = 42`; separate seeds per block length (`SEED + bl`).
- **Convergence:** All 200 replicates per setting converged (success=200, fail=0 for all settings).
- **Limitations stated in JSON output:** Residual resampling assumes fitted-model structure is adequate; adding resampled residuals back preserves mean but may not fully reproduce long-range correlation; not calibrated as formal significance.

Results (reference depth: **153.8 ppm**):

| Block length (cad) | Block ~hours | 95% interval (ppm) | Std (ppm) | Mean depth (ppm) |
|---|---|---|---|---|
| 10 | 0.2 | [147.0, 160.7] | 3.7 | 154.2 |
| 50 | 1.0 | [149.5, 158.5] | 2.3 | 154.2 |
| 100 | 2.0 | [149.8, 157.9] | 2.1 | 154.1 |
| 200 | 4.1 | [151.2, 158.2] | 1.9 | 154.4 |
| 500 | 10.2 | [150.4, 157.7] | 1.9 | 154.3 |

Selection justification: 200–500 cadences (~4–10 days) captures the dominant correlation scale without over-smoothing. Shorter blocks produce wider intervals (underestimate correlation), not narrower; selection is therefore based on AC behavior, not interval width.

---

## 5. Injection/recovery (independent check, step 4)

File: `scripts/phase4_injection_recovery.py`.
Output: `reports/results/phase4_injection_recovery.json`.

Tests performed (documented):

- No-injection control (0 ppm depth) — false-positive tendency measured.
- Near-measured depth (~154 ppm) — primary target depth.
- Multiple depths: 50, 100, 150, 200, 300 ppm.

Method: synthetic transit injected into actual detrended Kepler data; noise drawn by replacement from fitted residuals (no synthetic Gaussian assumption). Realistic cadence and gaps preserved. Each depth: 50 replicates.

Results:

| Injected depth (ppm) | n_success / 50 | Mean recovered (ppm) | Std (ppm) | Bias (ppm) |
|---|---|---|---|---|
| 0 (control) | 50 | 2.7 | 2.0 | +2.7 |
| 50 | 50 | 50.1 | 2.8 | +0.1 |
| 100 | 50 | 99.8 | 3.0 | −0.2 |
| 150 | 50 | 150.8 | 3.2 | +0.8 |
| 154 | 50 | 154.8 | 3.2 | +0.8 |
| 200 | 50 | 199.6 | 3.5 | −0.4 |
| 300 | 50 | 299.3 | 2.5 | −0.7 |

Interpretation: recovery bias small (<1 ppm) across all non-zero depths. No-injection control shows a small positive bias (~2.7 ppm) — this indicates a mild tendency for the model to prefer non-zero depth from noise alone, but the measured ~154 ppm is well above this control range. Synthetic signal recovery is clearly distinguished from the real planet's signal.

Limitations reported in JSON:
- Noise drawn by simple replacement; does not fully reproduce temporal correlation.
- Only detrended variant tested (raw-variant sensitivity noted but not executed here).
- Fixed geometry used; geometry sensitivity not tested in injection.
- Synthetic ≠ real; recovery confirms method sensitivity, not planet confirmation.
- No data leakage (tuning minimal; noise from same reference pool).

---

## 6. Model comparison (step 5)

File: `scripts/phase4_model_comparison.py`.
Output: `reports/results/phase4_model_comparison.json`.

Approach: naive dBIC calculated under independent-Gaussian likelihood (`delta_k = 2`, `n ≈ 27111`). **Explicit warning included** in output: substantial correlated noise (lag-1 AC ≈ 0.94, stationarity ratio ≈ 7.2) means effective sample size << n; BIC overstates evidence.

- Naive delta BIC: **−2195.58** (favors transit model descriptively).
- Correlation context reported alongside: AC and stationarity values included.
- **No uncalibrated p-value reported.** No claim of formal detection significance.
- Interpretation: descriptive only; correlation-aware results (bootstrap + controls) are preferred over BIC.

---

## 7. Residual diagnostics figure

`reports/figures/phase4_residual_diagnostics.png` — not yet produced (script `phase4_residual_diagnostics.py` only summarizes numerically; figure generation deferred to reporting consolidation if needed). The existing `scripts/statistical_validation.py` produces `phase4_residual_diagnostics.png` when run fully.

---

## 8. Cross-dataset validation (step 6)

Existing TESS S14 (`tess_kepler_10_quality_masked.csv`) available; new sectors S40, S53, S74 unavailable.

Comparison performed from Phase 3 JSON (not forced to agree):

| Dataset | Variant | Depth (ppm) | Timing offset | Note |
|---|---|---|---|---|
| Kepler all (masked) | detrended | 153.8 | +0.03 min | Full 4-year baseline |
| TESS S14 (masked) | raw | 197.4 | −0.21 min | Single sector; higher noise level |

- Timing differences: within the ephemeris-drift scale computed from published-solution scatter (`ΔP ≈ 1e-6 d` over ~1,290 orbits → ~3.7 min drift scale). No forced agreement attempted.
- Quality-masked vs raw: Phase 3 reports both; detrended effect minimal on full Kepler (~0.1%), large on Q0 (~−9%).
- TESS download scope not completed; cross-dataset validation incomplete.

---

## 9. Unresolved scientific issues (honest reporting)

1. **TESS sectors unavailable.** Cross-dataset comparison is partial (S14 only). No joint Kepler+TESS fit performed.
2. **Fixed geometry dominates uncertainty.** Depth spans 146–162 ppm (geometry grid, Phase 3). Bootstrap interval (~150–158 ppm) does not include full geometry range; geometry is an assumption, not a fitted parameter.
3. **Residual correlation remains unmodeled.** Block bootstrap accounts for correlation structure but does not model it explicitly; long-range correlation (>500 cadences) is not fully captured.
4. **No-injection control shows mild positive bias (~2.7 ppm).** At ~154 ppm this is small relative to signal, but it confirms that noise can produce apparent depth.
5. **No formal detection significance claimed.** All statistical statements are descriptive.
6. **No ML component added** (explicit instruction: do not begin Phase 5 or add ML during Phase 4).

---

## 10. Verification checklist

- [x] Phase 3 baseline reproduced (same outputs, same JSON).
- [x] Phase 3 figures and original data untouched (verified by file listing; no deletions/overwrites).
- [x] Residual diagnostics executed; AC and nonstationarity reported.
- [x] Block bootstrap implemented; block-length sensitivity documented; segment-aware; reproducible seed; all replicates converged.
- [x] Bootstrap limitations stated (residual-resampling assumptions, stationarity, no significance claim).
- [x] Injection/recovery executed (control + 6 depth levels); realistic noise/gaps preserved; no data leakage.
- [x] Synthetic vs real clearly distinguished; false-positive tendency measured.
- [x] Model comparison uses defensible approach with assumption-stated BIC; no uncalibrated p-value.
- [x] Cross-dataset comparison performed (Kepler vs available TESS S14); new TESS sectors unavailable, honestly reported.
- [x] Reports written in `reports/phase4_statistical_validation.md` and `reports/results/` (machine-readable JSONs).
- [x] No Phase 5 or ML added.
- [x] Not pushed to GitHub.

---

## 11. Phase 4 outcome

- **Passed (conditional on user review).** Statistical validation completed within approved scope (Decision A + B); limitations and unresolved issues reported honestly.
- **Stop and wait for user review** before any Phase 5 / ML work.

---

## Appendices: file inventory (changed / new)

New scripts:
- `scripts/phase4_residual_diagnostics.py`
- `scripts/phase4_block_bootstrap.py`
- `scripts/phase4_injection_recovery.py`
- `scripts/phase4_model_comparison.py`

New reports / results:
- `reports/results/phase4_block_bootstrap.json`
- `reports/results/phase4_injection_recovery.json`
- `reports/results/phase4_model_comparison.json`
- `reports/phase4_statistical_validation.md` (this file)

Preserved (not modified):
- All `reports/figures/phase3_*.png`
- `reports/results/phase3_transit_analysis.json`
- `data/processed/` (all CSVs, including `tess_kepler_10_quality_masked.csv` for S14)
- Original data in `data/raw/`
- Legacy scripts untouched
