# Injection Recovery & Detection Benchmark

**Mode:** `full` · **status:** completed · **runtime:** 8.35 s · **finished:** 2026-10-22T00:19:29+00:00

> Synthetic injections only. Recovery of simulated transits does **not** establish
> real-planet detection performance.

## Research question

How successfully does a period-known, phase-folded matched filter recover injected
Kepler-10 b transits of known depth, and how does it compare with the project's ML
baselines on identical windows?

## Data

- `kepler`: SHA-256 `7dd1cb33d3dea710…`, 3 contiguous chunks, split {'train': 1, 'val': 1, 'test': 1}
- `tess`: SHA-256 `ac582c1cf89996ff…`, 4 contiguous chunks, split {'train': 2, 'val': 1, 'test': 1}

Time systems follow the project convention: BKJD = BJD_TDB − 2454833.0 (Kepler),
TJD = BJD_TDB − 2457000.0 (TESS).

## Transit model and injection

- Ephemeris: P = 0.837491225 d, T0 = 2454964.575 BJD_TDB.
- Geometry: a/R* = 3.4, i = 84.5°, quadratic limb darkening u = [0.30, 0.20].
- Radius ratio: rp = sqrt(depth_ppm × 1e-6); injection formula `flux + median(flux) × (model − 1)` (the Phase 5 formula, reused).
- Hidden phase offset per chunk: uniform in ±0.10 d; the same offset is reused across
  depths and noise conditions for paired comparisons.
- Search grid: ±0.2 d in 0.0025 d steps.
- Timing tolerance: 0.0377 d (half the 1.81 h transit duration).

## Detector and thresholds

- Folds each chunk at the published period, scans the phase offset, and computes a
  matched-filter amplitude with the same batman template shape as the injection.
- Detection threshold = 95th percentile of **train-split zero-depth controls** per
  (dataset, noise condition). The detector never receives the injected depth or offset.

| dataset \| noise | threshold S/N | calibration controls | source |
|---|---:|---:|---|
| kepler / amplified_x2 | 3.00 | 4 | max(3 sigma, 95th percentile of non-test controls) |
| kepler / observed | 3.00 | 4 | max(3 sigma, 95th percentile of non-test controls) |
| tess / amplified_x2 | 3.00 | 6 | max(3 sigma, 95th percentile of non-test controls) |
| tess / observed | 3.00 | 6 | max(3 sigma, 95th percentile of non-test controls) |

## Recovery by injected depth (all splits)

| requested (ppm) | recovered | trials | fraction | Wilson 95% | median recovered depth (ppm) |
|---:|---:|---:|---:|---|---:|
| 75 | 4 | 28 | 14.3% | [5.7%, 31.5%] | 135.0 |
| 150 | 9 | 28 | 32.1% | [17.9%, 50.7%] | 201.6 |
| 225 | 14 | 28 | 50.0% | [32.6%, 67.4%] | 286.5 |
| 300 | 18 | 28 | 64.3% | [45.8%, 79.3%] | 360.0 |

### Test-split only (locked evaluation)

| requested (ppm) | recovered | trials | fraction | Wilson 95% |
|---:|---:|---:|---:|---|
| 75 | 0 | 8 | 0.0% | [0.0%, 32.4%] |
| 150 | 2 | 8 | 25.0% | [7.1%, 59.1%] |
| 225 | 5 | 8 | 62.5% | [30.6%, 86.3%] |
| 300 | 6 | 8 | 75.0% | [40.9%, 92.9%] |

## Zero-depth controls

- Controls used for the false-positive estimate: 8 (chunks not used for threshold calibration).
- False positives: 0 → rate 0.0% (Wilson [0.0%, 32.4%]).
- Definition: zero-depth trials in test-split chunks (never used for calibration).

## Recovery by dataset and noise condition

| dataset | noise | recovered | trials | fraction | Wilson 95% |
|---|---|---:|---:|---:|---|
| kepler | amplified_x2 | 15 | 24 | 62.5% | [42.7%, 78.8%] |
| kepler | observed | 21 | 24 | 87.5% | [69.0%, 95.7%] |
| tess | amplified_x2 | 0 | 32 | 0.0% | [0.0%, 10.7%] |
| tess | observed | 9 | 32 | 28.1% | [15.6%, 45.4%] |

## Detection benchmark

Status: **ok**

| split | windows | groups | positive | negative |
|---|---:|---:|---:|---:|
| train | 60 | 3 | 48 | 12 |
| val | 40 | 2 | 32 | 8 |
| test | 40 | 2 | 32 | 8 |

| method | n | prevalence | precision | recall | F1 | ROC-AUC | PR-AUC | no-skill F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| physics_matched_filter | 40 | 0.800 | 1.000 | 0.406 | 0.578 | 0.844 | 0.960 | 0.889 |
| logistic_regression | 40 | 0.800 | 0.800 | 1.000 | 0.889 | 0.680 | 0.910 | 0.889 |
| random_forest | 40 | 0.800 | 0.800 | 1.000 | 0.889 | 0.555 | 0.826 | 0.889 |
| dummy | 40 | 0.800 | 0.788 | 0.812 | 0.800 | 0.469 | 0.790 | 0.889 |

Test-set positive prevalence is **0.800**; the **no-skill F1**
column is the score from predicting positive for every window
(`2p/(1+p) = 0.889`). A method at or below that value has
demonstrated no skill. Under this class imbalance F1 alone is not
interpretable, so ROC-AUC and per-depth recovery are reported alongside it.

### Per-depth behaviour on the test split

| requested (ppm) | trials | physics recovered | logistic detected |
|---:|---:|---:|---:|
| 75 | 8 | 0 | 8 |
| 150 | 8 | 2 | 8 |
| 225 | 8 | 5 | 8 |
| 300 | 8 | 6 | 8 |

## Figures

- `figures/recovery_vs_depth.png`
- `figures/control_snr.png`
- `figures/recovered_vs_injected.png`
- `figures/timing_error.png`
- `figures/benchmark_f1.png`

## Failed and excluded trials

- Invalid trials: 0
- No trials were excluded.

## Reproducibility

- Command: `python -m research.run_experiment --mode full`
- Seed: 20261022 · Python 3.14.3 · git `5ef9df6`
- Packages: numpy 2.5.4, pandas 3.0.6, scikit-learn 1.9.1, batman 2.5.1
- Started 2026-10-22T00:19:21+00:00 · finished 2026-10-22T00:19:29+00:00 · 8.35 s
- Artifacts: `config.json`, `trial_results.csv`, `summary.json`, `plot_data.json`, `provenance.json`, `figures/`.

## Limitations

- Independent units are contiguous chunks (3-4 per dataset), not individual cadences.
- Injections are coherent across each chunk's transits, at a hidden phase offset from the published ephemeris.
- Synthetic injection recovery does not establish real-planet detection performance.
- The ML benchmark uses six time-domain features and very few independent groups; treat it as exploratory.
- Wilson intervals describe this experiment's trials, not all future observations.
- With 3–4 contiguous chunks per dataset, per-dataset comparisons are exploratory.

## Scientific statement

Synthetic injection recovery measures pipeline sensitivity to simulated signals. It is
not a planet detection, not a discovery claim, and not evidence of real-world performance.
