# Phase 5 Audit — Synthetic Classification Pipeline

Status: verification complete; no changes made to Phase 3/4 artifacts; no GitHub push. All checks performed on saved artifacts (reports/phase5_dataset.json, phase5_features.csv, phase5_feature_config.json, phase5_results.json, phase5_results.md, scripts/phase5_*.py, tests/test_phase5_leakage.py).

---

## 1. Verify the split — PASS (with observations)

Source: `reports/phase5_dataset.json` + `scripts/phase5_baseline.py` (line split logic).

Actual split (reconstructed from dataset segment_ids and baseline code):
- Unique parent segments (contiguous blocks split at >1d gap): 26 (IDs: 0,1,3,4,5,6,7,8,9,10,11,12,13,14,16,17,19,20,21,22,23,24,25,26,27,28 — note gaps in numbering from segments skipped due to <100 points).
- Each segment produces exactly ONE window (either positive or negative, alternating by segment index parity: even=positive, odd=negative, per fixed script).
- Therefore no segment appears in both positive and negative classes. No segment can appear in both train and test since split is by segment group.
- Split groups: train=13 windows (segs 0,3,4,5,6,7,8,9,10,11,12,13,14 — approximately first half after shuffle with seed 42), val=6, test=7.
- Verification: `tests/test_phase5_leakage.py` asserts no inconsistent labels per segment; passes. Manual verification: `len(set(segment_ids)) == len(windows) == 26` — each window uses a unique parent segment.
- Observation: the dataset uses one window per segment (not multiple windows from same segment). This eliminates intra-segment leakage but reduces sample size (26 windows total). The split is defensible and clearly documented.
- PASS: split strategy documented (`"segment-level (contiguous blocks split at >1d gaps)"`), no overlapping segments across splits.

---

## 2. Audit feature construction — PASS (with one issue documented)

All 7 features documented in `reports/phase5_feature_config.json` and `scripts/phase5_features.py`:

1. `depth_rel_ppm`: `(median(flux) - min(flux)) * 1e6`. Uses only window flux array. No label/depth reference. PASS.
2. `contrast_ppm`: `mean(flux[|phase|>3h]) - mean(flux[|phase|<=1.8h]) * 1e6`. Purely geometric mask on phase; no label/depth reference. PASS.
3. `mad_scatter`: `median(|flux - median(flux)|)`. Robust scatter; no label/depth reference. PASS.
4. `gap_fraction`: `sum(np.diff(time) > 0.05) / max(1, len-1)`. Uses only time array from window. PASS.
5. `matched_filter_corr`: `np.corrcoef(window_flux, batman_curve(phase, rp_for_150ppm, 0))`. Uses a FIXED 150 ppm depth template (`np.sqrt(150*1e-6)`) — does NOT use the actual injected depth (`75/150/225/300`). This is defensible (template-based filter) but must be noted: the feature does not adapt to the actual synthetic signal depth. PASS with note.
6. `segment_std_ppm`: `np.std(window_flux) * 1e6`. Uses only the window's flux; captures variability from parent segment (as requested). Can be computed for unseen segment without knowing label/depth. PASS.
7. `mean_flux`: `mean(flux)`. PASS.

Defect / observation: `matched_filter_corr` produces `NaN` for 4 windows (dataset lines 160, 190, 235, 265, 369 — 5 windows actually: segment IDs 10, 12, 16, 19, 26). The feature extraction script (`scripts/phase5_features.py`) fills NaN with the median (`median_corr`). This is a defensible imputation but changes the feature values from the raw calculation. The dataset file (`phase5_dataset.json`) retains NaN; the CSV (`phase5_features.csv`) has them filled. The audit notes this discrepancy but does not alter files (per instruction: stop for approval before changing results). The feature is still independent of label/depth.

PASS (with documented NaN-handling note): no feature uses injected label or actual injected depth directly.

---

## 3. Independently verify metrics — PASS (values confirmed by independent computation)

Recomputed independently from `reports/phase5_features.csv` using the same split logic (segment-level) and same `LogisticRegression(C=1.0)` and `RandomForestClassifier(200, max_depth=6, random_state=42)` settings:

Results match `reports/phase5_results.md`:
- Threshold: 0.4405 (validation Youden index)
- Test class balance: positive=4, negative=3 (n_test=7)
- Confusion matrix: [[2, 1], [1, 3]] (2 TN, 1 FP, 1 FN, 3 TP) — verified independently.
- Precision: 0.75 (3 TP / (3 TP + 1 FP) = 3/4)
- Recall: 0.75 (3 TP / (3 TP + 1 FN) = 3/4)
- F1: 0.75
- ROC-AUC: 0.6667 (verified independently)
- PR-AUC: 0.7708 (verified independently)
- Dummy classifier (stratified): F1 ≈ 0.5714 (matches report)

Model selection / threshold audit:
- Threshold selected using ONLY `X_val`, `y_val` (Youden index on validation predictions). PASS.
- Random Forest comparison uses validation F1 (`rf_f1_validation` = 0.8000 from independent run). Reported improvement over baseline F1 (~0.75): exactly 0.05 (not >0.05). The selection rule (`metrics["rf_selected"] = bool(rf_f1_val > metrics["f1"] + 0.05)`) evaluates `0.8000 > 0.750 + 0.05` → `0.80 > 0.80` = False. Therefore RF is correctly NOT selected. PASS.
- Note: the small test size (n=7) means the reported F1 has high variance; a single different classification would change F1 substantially (e.g., if 1 FP becomes TN, F1 would become 0.857; if 1 TP becomes FN, F1=0.667). The audit reports this limitation explicitly.

PASS: metrics independently verified; model selection uses only validation data.

---

## 4. Reproducibility and scientific claims — PASS (with limitations documented)

- Random seed: `SEED = 42` (in `scripts/phase5_build_dataset.py` and `tests/test_phase5_leakage.py`). PASS.
- Saved config (`reports/phase5_feature_config.json`) includes feature definitions, label source, split method, `no_real_planet_labels: True`. PASS.
- Phase 3/4 artifacts unchanged: `reports/results/phase3_transit_analysis.json` hash `d82b4e40d19a65f41dc97cb39a46621c` (verified from audit; unchanged from earlier session). `reports/phase4_statistical_validation.md`, `reports/phase4_audit.md`, `reports/results/phase4_*.json` all preserved (not overwritten by Phase 5 scripts). PASS.
- Report claims: `reports/phase5_results.md` contains:
  - "Synthetic-label classification only. ... Not a discovery claim."
  - "Synthetic injection only (positive=depth>0 [75,150,225,300 ppm], negative=depth=0). Not real-planet labels."
  - "Performance measured on simulated windows only. Generalization to real observations remains unverified."
- PASS: no claim implies real-observation performance; all scientific claims are synthetic-only.
- Window independence limitation: only 26 windows from ~29 contiguous segments (some skipped for length <100 points). Because each segment contributes exactly one window and split is segment-level, windows are independent by design. However, the total sample is very small (26 windows, 7 test). This is noted as a limitation in the evaluation: confidence intervals are wide (implied by small n) and point estimates are unstable. PASS (honestly reported).

---

## 5. Defects / issues found

No code defects found that affect correctness of the scientific claims. One feature-level issue noted (not corrected per instruction to stop before changing results):

- `matched_filter_corr`: 5 windows have NaN in the saved dataset (`reports/phase5_dataset.json`); the CSV fills with median. This is a minor data-handling artifact; the feature remains scientifically defensible (uses fixed 150 ppm template, not injected depth, no label reference). The audit notes it explicitly rather than silently correcting.
- Small sample size (26 windows, 7 test) limits metric reliability. This is reported honestly in the audit and does not constitute a scientific error.
- No material defects requiring changes to results files or pipeline.

---

## 6. Final recommendation

PASS — Phase 5 is ready to freeze as an audit-completed synthetic-classification exercise.

Conditions met:
- All split and leakage requirements verified (segment-level split, no overlap, consistent labels).
- Feature independence verified (no feature uses label/depth directly; segment_std_ppm uses only flux).
- Metrics independently reproduced from saved artifacts.
- Reproducibility verified (seed 42, saved config, preserved Phase 3/4 artifacts).
- Scientific claims limited to synthetic-only; no claim of real-observation performance.
- Reported limitations (small n, NaN handling, synthetic-only scope) are clearly documented.

No changes made to `reports/phase3_*.json`, `reports/phase4_*.json`, `reports/phase3_*.png`, `data/processed/*.csv`, or `scripts/transit_analysis.py`. No GitHub push. Audit artifacts saved as `reports/phase5_audit.md` only.
