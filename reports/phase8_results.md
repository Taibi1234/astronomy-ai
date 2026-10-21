# Phase 8 — Corrected Evaluation (presented-flux features)

**Synthetic labels only; 26 windows total, 7 in test. Not a discovery claim.**

## Protocol

- Split: segment-level, shuffle `RandomState(42)`, cut 50/25/25 — unchanged from Phase 5.
- Model: LogisticRegression(C=1.0, max_iter=1000) fitted on train only.
- Threshold: Youden index on validation predictions only.
- Test set: scored once, after all choices were fixed.
- RandomForest(n=200, max_depth=6, random_state=4242) compared on **validation** F1.
- Imputation median fitted on train rows only.

## Splits

| split | windows | parent groups | positive | negative |
|---|---:|---:|---:|---:|
| train | 13 | 13 | 6 | 7 |
| val | 6 | 6 | 3 | 3 |
| test | 7 | 7 | 4 | 3 |

## Test metrics

- threshold: 0.4399
- precision: 0.7500
- recall: 0.7500
- F1: 0.7500
- accuracy: 0.7143
- ROC-AUC: 0.6667
- PR-AUC: 0.7708
- confusion matrix (rows=true 0/1): [[2, 1], [1, 3]]
- stratified dummy F1 (test): 0.5000
- RandomForest validation F1: 0.8000 (baseline validation F1 1.0000) → selected: False

## Caveats

- Seven test windows: one different classification moves F1 by ±0.1 or more.
- Features are computed from simulated flux; real-observation performance is unknown.
- No formal significance claim is made.
