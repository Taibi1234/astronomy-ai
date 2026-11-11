# Phase 11 — Scientific Generalization Audit and Experiment Design

**Date:** 2026-10-22 · **HEAD:** `5ef9df6` · **Status:** design + **Phase 11a implemented** (R1
role-allocation correction applied) + **Phase 11b stages 0–2 implemented** (frozen protocol, materialized
offsets, gated runner, synthetic-fixture numerical tests, physics operating-point spec, smoke CLI;
144 tests). No campaign run, no test row read, no scientific code changed, nothing staged or committed.
Records: §12/§13, [`phase11_pre_campaign_audit.md`](phase11_pre_campaign_audit.md),
[`phase11b_implementation.md`](phase11b_implementation.md).

**Purpose.** Phase 10 measured injection recovery on Phase 9/10's small inputs and benchmarked three
classifiers. This document establishes what may be concluded from it, what may not, and what a
defensible generalization study would require. The audit's answer is uncomfortable and useful: **Phase
10's "seven independent groups" are slices of two observing segments, not seven independent
observations**, and its Kepler arm uses one 9.7-day quarter rather than the 4-year dataset the README
describes. A valid study is possible, but only by changing the unit of analysis to the observing
quarter and by giving up any cross-mission claim.

---

## 1. Files inspected

| File | Why |
|---|---|
| `webapp/backend/research/core.py` | chunking, detector, subtraction, Wilson CI, noise condition |
| `webapp/backend/research/experiment.py` | config, trial construction, splits, thresholds, benchmark, metrics |
| `webapp/backend/research/jobs.py` | job lifecycle / artifact reconciliation (context only) |
| `webapp/backend/research/run_experiment.py` | CLI surface and output directory |
| `webapp/backend/research/reports.py` | regenerable figures/Markdown surface (function list) |
| `webapp/backend/app.py` | artifact allowlist, API contracts, dataset paths |
| `webapp/backend/transit_injection.py` | loader, injection, ephemeris, checksums |
| `webapp/backend/tests/test_research_experiment.py` | what is already asserted about splits and thresholds |
| `reports/phase10_audit.md`, `reports/phase10_injection_recovery_benchmark.md`, `reports/phase10_browser_acceptance.md` | claims to verify |
| `reports/injection_recovery/{summary.json, config.json, provenance.json, trial_results.csv, plot_data.json, recovery_report.md}` | saved facts, recomputed below |
| `reports/phase8_dataset.json` | how the Phase 5/8 windows are grouped |
| `docs/PIPELINE_STATUS.md`, `docs/reproducibility.md`, `README.md` | frozen-artifact and data-provenance policy |
| `data/processed/kepler_kepler_10.csv`, `tess_kepler_10.csv`, `kepler_all_quarters_quality_masked.csv`, `kepler_q*_quality_masked.csv` (15 files) | actual data extent and segment inventory |

Not inspected in depth: `scripts/*` analysis code (out of scope; untouched), frontend sources beyond
the Phase 10 panel already reviewed during browser acceptance.

---

## 2. Verified facts

### 2.1 The data Phase 10 actually used is one quarter and one sector

| Dataset | File | Rows | Span | Cadence | Contiguous segments |
|---|---|---:|---:|---:|---:|
| Kepler (Phase 10) | `kepler_kepler_10.csv` | **469** | **9.71 d** | 29.43 min | **1** (Q0 only) |
| TESS (Phase 10) | `tess_kepler_10.csv` | 17 722 | 26.85 d | 2.0 min | **1** (S14 only) |
| Kepler (available, unused) | `kepler_all_quarters_quality_masked.csv` | **45 514** | **1 470.5 d** | 29.42 min | 29 at gap > 1 d |

`core.load_curve()` reads `kepler_kepler_10.csv`, which `docs/reproducibility.md:187` identifies as
**Q0** (469 rows, 120.5–130.2 BKJD). The Phase 10 report's "Kepler" results therefore describe ~11
transits of one 9.7-day quarter, not the 4-year curve. This is not a bug — the file is what the Phase
9 visualizer needed — but it is a material scope limit that Phase 10's prose does not state.

### 2.2 Chunks are arbitrary slices of one continuous segment

`core.make_chunks()` (`core.py:67`) cuts by index: `np.linspace(0, n, k+1)`. Verified in the saved
trials:

| chunk | points | duration | split | injected recovered |
|---|---:|---:|---|---:|
| kepler-c0 | 156 | 3.2 d | train | 0.875 |
| kepler-c1 | 157 | 3.2 d | val | 0.750 |
| kepler-c2 | 156 | 3.2 d | test | 0.625 |
| tess-c0 | 4 430 | 6.2 d | val | 0.125 |
| tess-c1 | 4 431 | 6.2 d | train | 0.000 |
| tess-c2 | 4 431 | 6.2 d | test | 0.188 |
| tess-c3 | 4 430 | 6.2 d | train | 0.250 |

### 2.3 Trial structure: the chunk *is* the window

Each trial runs `core.detect()` over the whole chunk (`experiment.py:229-295`). Trials per chunk = 2
hidden offsets × 5 depths × 2 noise conditions = 20; 140 trials total, all valid. `n_points` and
`gap_fraction` have exactly **one distinct value per chunk** (verified `nunique() == 1` for all seven),
i.e. they are chunk identifiers, not observations.

### 2.4 Threshold calibration and false-positive accounting

- Four strata (`kepler|observed`, `kepler|amplified_x2`, `tess|observed`, `tess|amplified_x2`), each
  with `n_calibration_controls` = **4** (Kepler) / **6** (TESS), drawn from train+val controls only.
- All four thresholds are **3.00** — the `max(3.0, 95th percentile)` floor binds because the percentile
  of 4–6 samples is essentially their maximum.
- Test controls: **8** (2 chunks × 2 offsets × 2 noise); false positives **0**; Wilson 95 %
  **[0.00, 0.324]**.

### 2.5 The benchmark's effective sample size is 3 groups to train, 2 to test

| split | windows | **groups** | positive | negative |
|---|---:|---:|---:|---:|
| train | 60 | **3** | 48 | 12 |
| val | 40 | **2** | 32 | 8 |
| test | 40 | **2** | 32 | 8 |

Prevalence 0.80 everywhere. LR/RF F1 0.889 = no-skill F1 0.889; RF ROC-AUC 0.555; test n = 2 clusters.
Any AUC computed on two clusters is a two-draw statistic.

### 2.6 The pooled recovery numbers are a dataset mixture, not a rate

At 150 ppm, observed noise, **every Kepler chunk recovers 100 % and every TESS chunk recovers 0 %**
(per-chunk fractions 1.00/1.00/1.00 vs 0.00/0.00/0.00/0.00; between-chunk SD 0.53). The pooled "43 %"
is therefore the mission mix, not a per-observation rate. Pooling across chunks with different true
rates makes the Wilson interval not just too narrow but meaningless.

### 2.7 Cluster dependence is measurable in the saved data

Cluster bootstrap over the 7 chunks (4 000 resamples, seed 20261022), injected trials, observed noise:

| Depth | p | trial-level ±1.96·SE | cluster 95 % | variance inflation |
|---|---:|---:|---|---:|
| 75 ppm | 0.21 | 0.21 | [0.00, 0.50] | 1.59× |
| 150 ppm | 0.43 | 0.26 | [0.14, 0.86] | 2.06× |
| 225 ppm | 0.64 | 0.25 | [0.29, 0.93] | 1.66× |
| 300 ppm | 0.86 | 0.18 | [0.57, 1.00] | 1.99× |

This reproduces and extends the audit's 150/300 ppm result: trial-level intervals are ~1.3–1.4× too
narrow in SE terms.

### 2.8 Available independent segments

| Mission | Grouping unit | Count | Rows per group | Span per group | Transits per group |
|---|---|---:|---|---|---:|
| Kepler | quarter (`kepler_q*_quality_masked.csv`) | **15** | 439–4 059 | 9.7–97.6 d | 11.6–116.5 |
| TESS | sector | **1** | 17 722 | 26.9 d | ≈32 |

12 quarters are 88–98 d long; three are short (Q0 9.7 d, Q4 20.8 d, Q17 31.8 d). The combined 45 514-row
file is exactly the 15 quarter files concatenated (row sum matches), hash `9a457cf9c59866a5…`.

### 2.9 Detector cost (measured, not estimated)

One `core.detect()` call on a real 3 396-point Kepler slice: **0.079 s**; on a 156-point Phase 10 chunk:
**0.022 s**. Linear fit: **t ≈ 0.019 s + 1.76 × 10⁻⁵ · n_points**. Predicted Phase 10 full campaign
9.1 s vs the recorded 8.35 s (−8 %), so the model is usable for planning.

---

## 3. Unit of independence

**Current unit:** contiguous index chunk. **Can windows from the same continuous segment cross splits?**

*Cadence level — no.* Each trial is one whole chunk and chunks are disjoint index ranges, so no cadence
appears in two split groups. The audit's statement is correct as far as it goes.

*Segment level — yes, and this is the defect.* Because chunks are equal-count slices of **one**
continuous light curve, the three "Kepler groups" are three consecutive 3.2-day pieces of Q0 and the
four "TESS groups" are four consecutive 6.2-day pieces of S14. Train, validation and test chunks are
**temporal neighbours in the same segment**: they share the same star, the same instrument state, the
same systematics and adjacent noise realisations. Consequences:

1. **Effective n = 2 segments, not 7 groups.** No amount of bootstrap resampling over chunks creates
   information that was never observed.
2. **Test is not a held-out condition.** It is an adjacent time slice of the training series, which is
   the optimistic case for any autocorrelated time series.
3. **The reported intervals inherit this.** Trial-level Wilson intervals assume 20 independent trials
   per chunk; the design effect (1.6–2.1) shows they are wrong by a factor the audit already flagged.
4. **The ML benchmark cannot be rescued by more windows.** 60 train windows from 3 chunks is 3
   independent examples repeated 20×; the "all-positive" behaviour is what a model converges to when
   the effective sample cannot support a boundary.

**Required unit for Phase 11:** the *observing segment* — a Kepler quarter or a TESS sector. Windows may
be cut inside a segment, but a segment's windows must all land in the same split, and inference must
treat the segment as the sampling unit.

---

## 4. Leakage audit

| Item | Where | Verdict |
|---|---|---|
| `FEATURE_NAMES` = `min_depth_ppm, std_ppm, mad_ppm, gap_fraction, mean_flux, n_points` | `experiment.py:62` | **no label leakage** — computed from `times` and the *presented* flux only (`experiment.py:271`) |
| Injected depth used in features? | `time_domain_features` | No direct use; `min_depth_ppm` is a **depth proxy** by construction (it measures the dip). Legitimate for a "given the light curve, is a transit present" task, but it makes the benchmark a depth-discrimination problem, not a detection pipeline |
| Hidden offset in features? | `delta_true_days` | Recorded in `trial_results.csv`, **never** used as a feature (verified against `FEATURE_NAMES` and the benchmark's `X`) |
| `n_points`, `gap_fraction` | `experiment.py:83-84` | **chunk identifiers** — one distinct value per chunk (verified). They cannot leak the label, but they let a model index groups; must be dropped or declared as nuisance in Phase 11 |
| Threshold fitted on test? | `_thresholds` (`experiment.py:103`) | **No** — `split != "test"`, asserted by `test_thresholds_use_non_test_controls_only` |
| ML imputation / scaling on test? | `_benchmark` (`experiment.py:506`) | **No** — median imputation on `X[train]`, `StandardScaler` inside the train-fit pipeline |
| LR threshold / RF selection on test? | `experiment.py:520-535` | **No** — both use validation only |
| Physics `detected` flag | `experiment.py:312` | Uses the non-test-calibrated threshold ✓ |
| `trial_results.csv` as a feature table | artifact | **Unsafe by itself**: it carries `delta_true_days`, `injected`, `depth_est_ppm`, `snr`, `recovered`. The benchmark only reads `FEATURE_NAMES` ✓, but any future model must not read the CSV naively |
| Split/segment dependence | §3 | **Not leakage in the label sense, but the dominant validity problem** |

**Additional structural issue:** `_split_map` (`experiment.py:87`) shuffles chunk IDs with no
stratification. With 3–4 chunks this can — and here did — put a short chunk in test, and makes the
split non-reproducible across config changes (the same RNG also draws the hidden offsets). Phase 11
must freeze the split as an artifact before any run.

---

## 5. Is there enough data for a valid generalization study?

**Kepler: yes, at the group level, with caveats.** 15 quarters × 11–116 transits gives 15 clusters. That
supports a blocked split (e.g. 7 train / 3 val / 5 test) or leave-one-quarter-out evaluation of the
detector, with cluster-robust intervals. It does **not** support statements about stars in general:
all 15 quarters are the same star, the same instrument, different epochs.

**TESS: no.** One sector (26.9 d, ≈32 transits, 1 contiguous segment) cannot be split. Any TESS number
is a single-cluster case study — which is exactly what Phase 10's TESS arm already was, except it
pretended to have four groups.

**Cross-mission: not supportable.** With one TESS cluster, a Kepler→TESS transfer claim has n = 1.
Report it as a case study, never with a confidence interval.

**Power.** Simulating a cluster bootstrap with 4–5 clusters and a between-cluster SD of 0.30 gives an
expected 95 % CI **width ≈ 0.39–0.41**. Phase 11 can distinguish 0.5 from 0.9; it cannot resolve
0.60 from 0.70. This must be stated up front, not discovered in the discussion.

**Verdict:** feasible and honest if the study is Kepler-quarter-blocked with TESS as a descriptive
external check; not feasible as a multi-mission generalization claim.

---

## 6. Proposed Phase 11 design

No scientific algorithm changes. `core.detect`, `core.remove_published_transit`,
`core.apply_noise_condition`, `transit_injection.inject_transit` are reused unchanged; Phase 11 adds
**windowing, grouping, splits, calibration and clustered inference** around them.

### E1 — Unit of analysis

- **Cluster (inference unit):** Kepler quarter (`kepler_qXX_quality_masked.csv`), 15 total.
- **Window (analysis unit):** 5.0 d contiguous, **non-overlapping**, wholly inside one quarter
  (≈245 Kepler cadences, ≈6 transits). Windows never cross a quarter boundary.
- Windows with < 40 points are dropped and logged.
- Expected window count: 215 (1–19 per quarter).

Justification for 5 d: a full quarter (≈100 transits) folds to S/N ≈ 15 at 150 ppm, so every depth
saturates and the recovery curve stops being informative. Six transits keeps the task comparable to
Phase 10's ~4-transit chunks while providing ~215 independent-in-time replicate windows.

### E2 — Frozen, stratified split

- Assign **quarters** (not windows) to train / validation / test = **7 / 3 / 5**, stratified by quarter
  span so no split is only short quarters; e.g. test = {Q02, Q09, Q13, Q14, Q17}.
- Write the assignment to `reports/phase11_generalization/split.json` **before** any run, including the
  seed, the quarter file names and their SHA-256. Windows inherit their quarter's split.
- Supplement the split with **leave-one-quarter-out** evaluation of the detector (no training needed),
  which uses all 15 clusters and removes any dependence on one split draw.
- `test` is read once, at analysis time, by a separate script.

### E3 — Controls

- **Paired controls:** each injected window also runs at depth 0 (same window, same noise realisation)
  — this is the current Phase 10 behaviour and is kept for paired comparisons.
- **Separate null library:** additional non-overlapping null windows in non-test quarters
  (≈8 per non-test quarter, ≈88 total) used only for **threshold calibration**. Paired controls are
  *not* used for calibration, so calibration and recovery are not computed on the same windows.
- **Achieved-FPR check:** independent null windows inside test quarters (≈5 per test quarter, 25 total)
  yield the reported FPR with a cluster interval. Target **5 %**, not 1 %: with 25 nulls, 0 observed
  false positives bounds FPR at ≈11 %, so a 1 % target would be unmeasurable. Report the bound, not just
  the point estimate.

### E4 — Detector operating point

- Threshold per (mission, noise) = `max(3.0, 95th percentile of validation-quarter null S/N)`, fitted on
  validation quarters only, with ≈24 null windows per stratum instead of 4–6 — enough for the 95th
  percentile to mean something.
- Report for each stratum: calibration n, the empirical percentile, whether the 3σ floor binds, and the
  achieved test FPR.
- Keep the 3σ floor for continuity with Phase 10 but label it explicitly as a design choice; also report
  the unfloored empirical threshold so the effect is visible.

### E5 — Metrics and inference

Primary (threshold-free): **ROC-AUC** and **PR-AUC** (with prevalence stated).
Operating point: **recall at the calibrated FPR**, plus **MCC** and **balanced accuracy**.
Recovery: per-depth recovery fraction, per-quarter table (15 rows), and the pooled value only as a
mix-adjusted summary.
No-skill baselines for every metric (all-positive F1, prevalence, random AUC 0.5).
Intervals: **cluster bootstrap over quarters** (BCa, 10 000 resamples), reporting the number of clusters
beside every interval. Wilson intervals may appear only for orientation, explicitly labelled
"trial-level, anti-conservative, design effect ≈ 2".

### E6 — ML baseline ladder (one grouped CV, no tuning of test)

1. no-skill (all positive)
2. `DummyClassifier`
3. **matched-filter S/N alone** (1 feature) — is the ML adding anything?
4. the six Phase 10 time-domain features
5. six features + S/N
6. six features minus `n_points`/`gap_fraction` (drop the group identifiers)

Fit only on train quarters, threshold on validation quarters, report on test quarters once. Add a
**label-permutation test at the cluster level** (shuffle labels across quarters) to show whether any AUC
exceeds what between-cluster permutation produces. Class balance is fixed by construction (paired
controls), so F1 is reported alongside prevalence and never alone.

### E7 — TESS

One sector, one cluster. Descriptive only: per-depth recovery with the same calibrated threshold,
labelled `n = 1 cluster — no interval`. No half-split is allowed (51/49 temporal split of one sector is
the same mistake Phase 10 made).

### E8 — Outputs and provenance

New directory `reports/phase11_generalization/` (`summary.json`, `trials.csv`, `split.json`,
`plot_data.json`, `generalization_report.md`, `figures/`). Provenance records SHA-256 of every quarter
file, the combined file and the TESS file, the seed, git commit, package versions. Phase 10 outputs,
Phase 4/5 artifacts and all source CSVs remain untouched.

---

## 7. Acceptance criteria

| # | Criterion | How it is checked |
|---|---|---|
| A1 | Every trial's split equals its quarter's frozen split | assertion over `trials.csv` vs `split.json`; test in suite |
| A2 | No window spans two quarters; no window overlaps another in the same quarter | interval arithmetic test |
| A3 | Calibration uses validation quarters only; paired controls excluded from calibration | provenance fields + test |
| A4 | Test quarters are read once, by the analysis script, after the campaign is frozen | artifact timestamps + code path |
| A5 | Achieved test FPR reported with a cluster interval and an explicit upper bound | report table |
| A6 | Every reported metric carries its method, prevalence and **number of clusters** | report lint: no metric row without `k` |
| A7 | Trial-level intervals, if shown, are labelled anti-conservative with the measured design effect | report text check |
| A8 | Determinism: same seed → identical `trials.csv` numerics (timestamps excluded) | rerun diff in temp dir |
| A9 | Phase 4/5/8/9/10 artifact hashes unchanged | hash gate before/after |
| A10 | The report states that synthetic injection on one star is not detection performance and not discovery | text check |
| A11 | Campaign runtime within the projected budget (±50 %) | recorded `runtime_seconds` |

---

## 8. Computational cost

Measured model (§2.9): `t ≈ 0.019 + 1.76e-5·n_points` seconds per detector call.

Design-time projection (superseded by §12, which corrected the window/null partition):

| Component | Trials | Points/trial | Projected |
|---|---:|---:|---:|
| Kepler windows, 6 depths × 2 offsets × 2 noise | 215 × 24 = 5 160 | ≈245 | ≈120 s |
| Separate null library (calibration + test) | ≈113 × 2 noise = 226 | ≈245 | ≈5 s |
| TESS windows, same design | 5 × 24 = 120 | ≈3 600 | ≈10 s |
| Analysis + figures | — | — | ≈20–40 s |
| **Total, full** | **≈5 500** | | **≈2.5–3 min** |

That projection assumed every window would carry injections *and* that additional disjoint null
windows existed; they do not. The implemented partition (§12.3) yields **2 868 primary trials / 65 s**
and **4 840 sensitivity trials / 103 s**. Memory ≈3 MB CSV. Nothing requires a sweep, GPU, or network.

---

## 9. Risks and unresolved questions

1. **Cluster definition.** Quarters are instrument-defined, but within-quarter gaps reach 6.97 d (Q14)
   and 5.66 d (Q15). Is a quarter one segment or two? Proposal: quarter is the cluster, with intra-quarter
   gaps recorded and a sensitivity check treating each gap-delimited piece as its own cluster.
2. **Short quarters.** Q0 (9.7 d), Q4 (20.8 d), Q17 (31.8 d) contribute one window each and are
   structurally different (Q0 is the quarter Phase 3 showed to be trend-dominated). Option: keep all 15
   (n = 15 clusters) or drop to 12 long quarters. Needs a decision before the split is frozen.
3. **Window length.** 3 d (≈3.6 transits, more windows) vs 5 d (≈6 transits) vs 10 d (≈12 transits,
   saturation). Proposal: 5 d primary, 3 d as a pre-registered sensitivity check — but only if the user
   accepts two campaign sizes.
4. **Target FPR.** 5 % is measurable with ~25 test nulls; 1 % is not, without ≈300 test nulls (which
   would need more null windows than the data comfortably supports without overlap).
5. **Null realism.** `remove_published_transit` leaves 4–9 ppm of the real transit (§Phase 10 audit).
   On 6-transit windows this is a larger fraction of a 50 ppm injection than on 4-transit chunks. A
   diagnostic is needed: detector S/N distribution of nulls vs a matched pure-noise simulation.
6. **Depth-proxy feature.** `min_depth_ppm` is nearly a depth estimator. Including it makes the ML task
   easier than detection; excluding it may leave no signal at all. The ablation in E6 answers this
   empirically either way.
7. **One star.** Every group is Kepler-10. Even a perfect 15-quarter study generalizes to *this star's
   epochs*, not to planets or pipelines in general. This should be in the abstract, not the limitations.
8. **Data provenance.** `data/processed/` is gitignored, so Phase 11's inputs are local-only. Hashes in
   provenance mitigate but do not make the study reproducible from a clean clone.
9. **UI.** Phase 11 is analysis-first. A UI panel is out of scope until the results exist and are
   approved; adding run buttons now would repeat Phase 10's "API verified / browser unverified" gap.

---

## 10. Recommended next experiment

**Phase 11a — pre-registration (no compute):**
1. Approve cluster = Kepler quarter, window = 5 d, depths {0, 50, 75, 100, 150, 300} ppm, 2 hidden
   offsets, noise {observed, ×2}, target FPR 5 %.
2. Write `split.json` + input hashes; commit nothing, but freeze the file (hash it into the plan).
3. Add `webapp/backend/research/generalization.py` (windowing, grouped splits, clustered metrics) and
   tests A1–A4 **before** any campaign runs. No change to `core.py` science.

**Phase 11b — smoke (≈3 s):** 2 quarters, 96 trials; verify window integrity, split assertions,
threshold provenance, and that the analysis script refuses to run if `test` was touched during
calibration.

**Phase 11c — full campaign (≈2.5–3 min):** the table in §8. Run twice to confirm determinism (A8).

**Phase 11d — analysis and report:** cluster bootstrap, metric ladder, per-quarter table, TESS case
study, limitations. Written to `reports/phase11_generalization/` plus a synthesis report.

**What Phase 11 must not do:** pool trials across clusters without saying so; report a single test AUC
without `k`; call a 51/49 split of one sector "validation"; compare ML to physics at a threshold tuned on
test; or describe any of it as real-planet performance.

---

## 11. What this audit changes about Phase 10's claims

Nothing in Phase 10's saved numbers; they are reproduced here and remain what they are. What changes is
the interpretation that may be attached to them:

| Phase 10 statement | Status after this audit |
|---|---|
| "Independent units are contiguous chunks (3–4 per dataset)" | **Not supported.** Chunks are slices of one Q0 segment and one S14 segment; effective n = 2. |
| "Recovery 150 ppm = 43 %" | Mixture of 100 % (Kepler) and 0 % (TESS); not a per-observation rate. |
| "Physics ROC-AUC 0.844" | Computed on 2 test clusters; reportable only with k = 2 and a cluster interval. |
| "FPR 0 of 8 test controls" | True but weak: 95 % upper bound 0.324, calibration n = 4–6. |
| "ML F1 equals no-skill F1" | Confirmed and structural: 3 training clusters, 80 % prevalence, features that are group identifiers. |
| "No leakage" | Correct for labels; the threat here is dependence, not leakage. |

---

*Prepared as design input. Phase 11a is implemented and frozen (§12); Phase 11b has not started.
Awaiting review and approval.*

---

## 12. Phase 11a — implementation record (frozen)

Implemented 2026-10-22. **No campaign, no detector call over the campaign, no model fit.** The only
computation is reading the 15 quarter CSVs and laying out windows.

### 12.1 Code and artifacts

| Path | Role |
|---|---|
| `webapp/backend/research/generalization.py` | frozen split, window generation, null-library manifest, experiment config, feasibility checks (CLI: `python -m research.generalization`) |
| `webapp/backend/tests/test_generalization.py` | 26 tests (quarter isolation, gap handling, determinism, role-allocation balance, leakage guards, feasibility) |
| `reports/phase11_generalization/split.json` | quarter → split, per-quarter metadata, input SHA-256 |
| `reports/phase11_generalization/windows_primary.json` | 207 five-day windows |
| `reports/phase11_generalization/windows_sensitivity.json` | 345 three-day windows |
| `reports/phase11_generalization/null_library.json` | calibration/test null windows, paired-control exclusion |
| `reports/phase11_generalization/experiment_config.json` | frozen config, ML ladder, metrics, projected cost |

No existing module was modified: `core.py`, `experiment.py`, `jobs.py`, `app.py`, the frontend, the
Phase 4/5/8/9/10 artifacts and every source CSV are byte-unchanged.

Manifest hashes (no timestamps, byte-reproducible — verified by regenerating twice and diffing):

| Artifact | SHA-256 (first 16) | Bytes |
|---|---|---:|
| `split.json` | `5931f5b4fc7450bb` | 8 576 |
| `windows_primary.json` | `6d8eb4b4efad96ab` | 67 098 |
| `windows_sensitivity.json` | `b89c6bded0c0b22a` | 111 608 |
| `null_library.json` | `767ff9408c70a9c9` | 3 480 |
| `experiment_config.json` | `43fbddc15c74c626` | 5 967 |

These supersede the pre-correction hashes (`f22213ca…`, `36e6adb1…`, `a7693993…`, `fb295e24…`,
`71f2ed9c…`) after the R1 role-allocation correction documented in
[`phase11_pre_campaign_audit.md`](phase11_pre_campaign_audit.md) §13.

### 12.2 Frozen split (7 / 3 / 5, all 15 quarters)

| Split | Quarters | Quarters (long/short) | Primary 5 d windows | Injection | Null |
|---|---|---|---:|---:|---:|
| train | Q00, Q03, Q04, Q05, Q07, Q11, Q15 | 5 / 2 | 91 | 45 | 46 |
| val | Q01, Q06, Q10 | 2 / 1 | 42 | 21 | 21 |
| test | Q02, Q09, Q13, Q14, Q17 | 4 / 1 | 74 | 36 | 38 |

The test set is the one named in §E2 of this plan. Validation was chosen to hold ~20 % of the windows
(the alternative `{Q01, Q04, Q06}` held 14 %) while keeping both span bands represented; training is the
remainder. Every split contains at least one long and one short quarter. Short quarters (< 60 d) are
Q00, Q01, Q04, Q17; they are retained and flagged in `split.json`.

### 12.3 Window rules (implemented exactly)

- Cluster = quarter; every window inherits its quarter's split. **A quarter can never appear in two
  splits, and no window can straddle two quarters.**
- A quarter is cut into contiguous pieces at data gaps **> 1.0 d**; a window never spans such a gap.
- Windows are laid consecutively from each piece start, length 5.0 d (primary) or 3.0 d (sensitivity),
  **never overlapping**.
- A window is kept only if it has **≥ 40 points**, duration **≥ 0.8 × window length**, and **≥ 2
  transits** (P = 0.837491225 d). Tails failing this are dropped; a 4.9 d tail is kept for a 5 d window,
  a 3.9 d tail is not.
- Roles are assigned **in consecutive pairs inside each quarter**: one deterministic
  `SHA-256(version | quarter | pair index | window length)` coin per pair decides which member is
  injected; an odd leftover window is decided by its own `tail` coin. Inputs are identifiers and the
  window length only — never flux, noise, labels, detector scores or test outcomes. The two roles
  therefore never share cadences, per-quarter counts differ by at most one, and there is no systematic
  "earlier window is injected" bias (measured: d = −0.09, p = 0.56 at 5 d; d = 0.00, p = 0.99 at 3 d).

**Correction to the design (§E3).** The plan assumed all ~215 windows would carry injections *and* that
≈113 additional disjoint null windows existed. They do not — there are only 207 windows. The
implemented design partitions them: **102 injection windows + 105 null windows** (primary), 173 + 172
(sensitivity). Consequences, stated rather than hidden: the campaign shrinks from ~5 160 to **2 868
trials**, and the null library is a genuine disjoint set rather than an afterthought. Paired zero-depth
controls still exist on every injection window (102 × 4 = 408 trials) but are excluded from both
calibration and the false-positive rate, exactly as the plan required.

### 12.4 Null library and operating point

| Pool | Primary windows | Trials | Used for |
|---|---:|---:|---|
| Calibration (train + val nulls) | 67 | 268 | threshold: `max(3.0, p95 of null S/N)` per noise condition |
| Test nulls (test quarters only) | 38 | 152 | reported FPR: count, denominator, Wilson + cluster interval |
| Paired controls (all splits) | 102 | 408 | paired comparisons only — **excluded** from calibration and FPR |

Target FPR is **5 %**; the config states "no 1 % target" and a test asserts that no 0.01 FPR value
appears in the null-library block. With 152 test null trials, a 5 % FPR is measurable (expected ≈7.6
false positives); a 1 % target would not be.

### 12.5 ML ablation ladder (declared, not fitted)

| ID | Features | Purpose |
|---|---|---|
| L0_no_skill_all_positive | — | analytic no-skill F1 |
| L1_dummy_stratified | — | random baseline at train prevalence |
| L2_snr_only | `snr` | is ML needed at all? |
| L3_detector_outputs | `snr`, `depth_est_ppm`, `sigma_ppm` | detector measurements only |
| L4_flux_full | 6 Phase 10 features | includes `min_depth_ppm` **and** group identifiers |
| L5_flux_without_depth_proxy | L4 − `min_depth_ppm` | the pre-registered proxy contrast |
| L6_flux_clean | L4 − proxy − `n_points` − `gap_fraction` | removes chunk identifiers |
| L7_detector_plus_clean_flux | L3 + L6 | **primary realistic-detection model** |

Ground truth is banned from every feature set by `forbidden_feature_columns` (`delta_true_days`,
`requested_depth_ppm`, `injected`, `recovered`, `timing_error_days`, ids, split/threshold bookkeeping).
`min_depth_ppm`, `n_points` and `gap_fraction` are measured from flux/times — legitimate but flagged —
and L4 vs L5 vs L6/L7 isolates their contribution. No model is trained in Phase 11a.

### 12.6 Feasibility check (run before coding; re-run from the manifests)

Command: `python -m research.generalization`. Both window lengths pass every pre-registered rule.

| Window | Split | Quarters | Inj windows | Null windows | Positives | Null negatives | Pos/depth | Prevalence | Per-depth balance |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 d | train | 7 | 45 | 46 | 900 | 184 | 180 | 0.83 | 0.49 |
| 5 d | val | 3 | 21 | 21 | 420 | 84 | 84 | 0.83 | 0.50 |
| 5 d | test | 5 | 36 | 38 | 720 | 152 | 144 | 0.83 | 0.49 |
| 3 d | train | 7 | 75 | 76 | 1 500 | 304 | 300 | 0.83 | 0.50 |
| 3 d | val | 3 | 35 | 35 | 700 | 140 | 140 | 0.83 | 0.50 |
| 3 d | test | 5 | 63 | 61 | 1 260 | 244 | 252 | 0.84 | 0.51 |

Pooled prevalence is 0.83–0.84 because there are five depths to one control, so **the balanced
per-depth contrast (each depth vs the nulls, balance 0.49–0.51) is the pre-registered evaluation**, and
pooled numbers are always reported with their prevalence and no-skill value. Excluding the four short
quarters still passes every split minimum (checked by test), so the sensitivity analysis in decision 2
is feasible.

### 12.7 Projected cost (from the measured model)

| Window | Injection trials | Paired controls | Null trials | Total | Mean points | Projected |
|---|---:|---:|---:|---:|---:|---:|
| 5 d (primary) | 2 040 | 408 | 420 | **2 868** | 211.6 | **65 s** |
| 3 d (sensitivity) | 3 460 | 692 | 688 | **4 840** | 127.2 | **103 s** |
| TESS case study (descriptive) | — | — | — | ≈100 | ≈3 600 | ≈8 s |

### 12.8 Tests and checks

```
webapp/backend>  python -m pytest -q            78 passed, 1 warning   (52 existing + 26 new)
webapp/backend>  python -m ruff check .         All checks passed!
webapp/backend>  python -m pytest tests/test_generalization.py -q     26 passed
```

The 26 new tests cover the required guarantees:

- **Quarter-level isolation** — every window inherits its quarter's split; quotas 7/3/5; each split has a
  long and a short quarter; injection and null windows never share cadences.
- **Temporal-gap handling** — no window spans a gap > 1 d; windows within a quarter never overlap;
  geometry matches the 5 d/3 d rules; tail handling verified on synthetic 8 d, 4.9 d and 3.9 d curves.
- **Deterministic reproducibility** — manifests written twice are byte-identical, and the written files
  match a fresh regeneration.
- **Ground-truth leakage prevention** — every ladder entry is disjoint from `forbidden_feature_columns`;
  all features are measured quantities; L5 differs from L4 by exactly `min_depth_ppm`; L7 carries no
  proxy and no group identifiers; the 5 % FPR target is declared and no 1 % value appears.

Plus feasibility (both lengths, short-quarter exclusion) and projected-cost assertions.

**Role-allocation tests added with the R1 correction (6):** valid roles and per-quarter balance
(|injection − null| ≤ 1), deterministic reproducibility across rebuilds, odd-tail handled by its own coin,
roles unchanged when flux is rescaled, roles unchanged when `OFFSET_SEED` changes, and a temporal-balance
guard (|Cohen's d| < 0.25 and sign-test p > 0.10, computed on the frozen lists).

Measured balance after the correction (5 d): injection/null counts 102/105 overall (test 36/38,
train 45/46, val 21/21); position-in-piece difference **d = −0.09 (p = 0.56)**, position-in-quarter
**d = −0.07 (p = 0.63)**, per-quarter injection-earlier in **10 of 15 (p = 0.30)**; cadences d = 0.00 and
transits d = −0.14 (p = 0.34). At 3 d: counts 173/172, position d = 0.00 (p = 0.99), sign test 7/15
(p = 1.00). Residual differences are reported, not claimed as perfect balance.

### 12.9 What has *not* happened

No injection, no detection, no threshold fitting, no model fitting, no campaign artifacts, no UI change,
no modification of Phase 4/5/8/9/10 outputs or source CSVs, no staging or commit. The `test` quarters have
not been read by any analysis code — only by the manifest builder that lays out windows.

### 12.10 Open decisions for review before Phase 11b

1. Bump `MAJOR_GAP_DAYS` from 1.0 d to 3.0 d? Fewer pieces → more windows (earlier estimate 215 vs 207),
   but windows could then span a 2 d outage. Current choice is the conservative one.
2. Keep both window lengths as reported, or run primary only and treat 3 d as a later sensitivity run?
   (Budget: 65 s vs 103 s — not a constraint, so both is preferable.)
3. Confirm the val set `{Q01, Q06, Q10}` (20 % of windows, both span bands) or swap in Q04 for Q01.
4. Confirm `L7_detector_plus_clean_flux` as "the primary realistic-detection model" for the report, with
   L2/L3 as ablations.
5. Fix the ML protocol constants now (regularisation C, RF depth, CV folds) or leave them to Phase 11c and
   record them in the config before touching test.

## 13. Phase 11b stages 0–1 — protocol, offsets, and the gated runner

Implemented 2026-10-22. Full record: [`phase11b_implementation.md`](phase11b_implementation.md).

| Artifact | SHA-256 | Bytes |
|---|---|---:|
| `reports/phase11_generalization/protocol.json` | `ded2bd5eea3cfb3cbd5af0b67e439a767584b9bf508f02afe2a4b5d56a75319f` | 7 836 |
| `reports/phase11_generalization/offsets.json` | `79e8d00eeef88c4e05cb571a64cc871dd5549d1c5e7ef5fd11d32021741b5be6` | 91 363 |

Both carry `.sha256` sidecars over raw file bytes (`sha256sum -c` passes). The five Phase 11a manifests are
byte-unchanged (`split.json 5931f5b4fc7450bb`), so the protocol/offset freeze did not alter the split,
windows or roles.

- **Protocol** freezes seeds, feature definitions and sets (asserted equal to `experiment_config.json`),
  the forbidden-column list, train-only preprocessing, model parameters, both threshold rules
  (detector: train+val nulls; fitted models: validation nulls only), the strict `>` comparison and tie
  rule, metrics, BCa bootstrap configuration, and the one-read test-access policy. It pins the manifest
  hashes, so a manifest change invalidates it.
- **Offsets** materialize both hidden draws for all 207 (5 d) and 345 (3 d) windows from a per-length
  derived seed; order is `(quarter, window_index)`, and roles/splits/flux are absent from the key
  (verified by test).
- **Runner** (`research/phase11.py`) implements the trial plan, campaign code, fitting, freeze and
  evaluation behind gates: fitting refuses non-train/val rows, features are checked against the forbidden
  list, thresholds record their provenance, `fitted.json` + `model.pkl` + `fitted.sha256` must exist before
  test trials may be generated, and evaluation is allowed exactly once (ledger `test_access.json`).
- **Modes:** `describe_mode()` resolves smoke (168 trials, Q00/Q01/Q04, train+val only), full
  (1 852 fit + 1 016 test) and sensitivity (3 084 fit + 1 756 test) without executing anything.
- **Tests:** 110 passed (32 new), Ruff clean. No campaign, model fit, test read or UI change.

**Stage 2 (execution readiness):** synthetic-fixture numerical tests with real LR/RF fitting, fail-closed
tests (corrupted artifacts, ledger-before-metrics, restart), a physics operating-point reporting spec
(`DETECTOR_REPORT_SPEC` + `physics_operating_point`), and a smoke-only CLI (`research/run_phase11.py`,
dry-run by default). **Protocol v1 does not record the detector recovery timing tolerance,
stratification, or the ML-versus-physics comparison rule — a v2 amendment is requested before any such
comparison.**

**First authorized smoke attempt stopped on a scope violation:** the CLI planned 168 trials over
Q00/Q01/Q04 but executed 1,852 trials over all ten train/val quarters, because `run_campaign` ignored the
smoke window subset. No test rows were read and no test-access record was created; frozen artifacts are
unchanged. The output was quarantined (`smoke_invalid_scope_20261022/`), the defect was fixed with
post-run scope assertions, and the run was **not retried**. A second defect (trial role `null` read as
pandas NA) was fixed by renaming the vocabulary to `null_window`. 149 tests pass. Details in
[`phase11b_implementation.md`](phase11b_implementation.md) §9.

*Phase 11b stages 0–2 complete. Awaiting approval for a corrected smoke re-run; no corrected run has
executed.*
