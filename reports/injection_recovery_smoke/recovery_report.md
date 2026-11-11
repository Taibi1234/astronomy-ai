# Injection Recovery & Detection Benchmark

**Mode:** `smoke` · **status:** completed · **runtime:** 1.62 s · **finished:** 2026-10-22T00:13:57+00:00

> Synthetic injections only. Recovery of simulated transits does **not** establish
> real-planet detection performance.

## Research question

How successfully does a period-known, phase-folded matched filter recover injected
Kepler-10 b transits of known depth, and how does it compare with the project's ML
baselines on identical windows?

## Data

- `kepler`: SHA-256 `7dd1cb33d3dea710…`, 3 contiguous chunks, split {'train': 1, 'val': 1, 'test': 1}
- `tess`: SHA-256 `ac582c1cf89996ff…`, 3 contiguous chunks, split {'train': 1, 'val': 1, 'test': 1}

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
| kepler / observed | 3.00 | 2 | max(3 sigma, 95th percentile of non-test controls) |
| tess / observed | 3.00 | 2 | max(3 sigma, 95th percentile of non-test controls) |

## Recovery by injected depth (all splits)

| requested (ppm) | recovered | trials | fraction | Wilson 95% | median recovered depth (ppm) |
|---:|---:|---:|---:|---|---:|
| 150 | 4 | 6 | 66.7% | [30.0%, 90.3%] | 205.7 |
| 300 | 6 | 6 | 100.0% | [61.0%, 100.0%] | 358.4 |

### Test-split only (locked evaluation)

| requested (ppm) | recovered | trials | fraction | Wilson 95% |
|---:|---:|---:|---:|---|
| 150 | 1 | 2 | 50.0% | [9.5%, 90.5%] |
| 300 | 2 | 2 | 100.0% | [34.2%, 100.0%] |

## Zero-depth controls

- Controls used for the false-positive estimate: 2 (chunks not used for threshold calibration).
- False positives: 0 → rate 0.0% (Wilson [0.0%, 65.8%]).
- Definition: zero-depth trials in test-split chunks (never used for calibration).

## Recovery by dataset and noise condition

| dataset | noise | recovered | trials | fraction | Wilson 95% |
|---|---|---:|---:|---:|---|
| kepler | observed | 6 | 6 | 100.0% | [61.0%, 100.0%] |
| tess | observed | 4 | 6 | 66.7% | [30.0%, 90.3%] |

## Detection benchmark

Status: **ok**

| split | windows | groups | positive | negative |
|---|---:|---:|---:|---:|
| train | 6 | 2 | 4 | 2 |
| val | 6 | 2 | 4 | 2 |
| test | 6 | 2 | 4 | 2 |

| method | n | precision | recall | F1 | ROC-AUC | PR-AUC |
|---|---:|---:|---:|---:|---:|---:|
| physics_matched_filter | 6 | 1.000 | 0.750 | 0.857 | 1.000 | 1.000 |
| logistic_regression | 6 | 0.667 | 0.500 | 0.571 | 0.750 | 0.887 |
| random_forest | 6 | 0.750 | 0.750 | 0.750 | 0.625 | 0.721 |
| dummy | 6 | 0.500 | 0.500 | 0.500 | 0.250 | 0.583 |

### Per-depth behaviour on the test split

| requested (ppm) | trials | physics recovered | logistic detected |
|---:|---:|---:|---:|
| 150 | 2 | 1 | 1 |
| 300 | 2 | 2 | 1 |

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

- Command: `python -m research.run_experiment --mode smoke`
- Seed: 20261022 · Python 3.14.3 · git `5ef9df6`
- Packages: numpy 2.5.4, pandas 3.0.6, scikit-learn 1.9.1, batman 2.5.1
- Started 2026-10-22T00:13:55+00:00 · finished 2026-10-22T00:13:57+00:00 · 1.62 s
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
