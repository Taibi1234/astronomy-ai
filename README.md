# astronomy-ai — Kepler-10 b transit re-detection and validation pipeline

A reproducible analysis of the **known** transiting planet **Kepler-10 b**, built to answer a
methodological question rather than a discovery question:

> Can a light-curve pipeline recover a published transit signal, quantify how much of the
> measurement is conditional on preprocessing and model assumptions, and honestly separate
> statistical noise from correlated systematics?

**Kepler-10 b is a confirmed planet.** Nothing here is a discovery. The project is a
pipeline-validation and uncertainty-budgeting exercise: a known answer exists, so every stage
can be checked against it instead of being asserted.

---

## 1. Why Kepler-10 b is the validation target

Kepler-10 b orbits a bright, quiet, well-studied G-type star at **P = 0.837491225 d**
(transit epoch **T₀ = 2454964.575 BJD_TDB**) with a transit depth of roughly **150 ppm**.
It is a good validation target for five concrete reasons:

1. **Ground truth exists.** The planet's transit is independently confirmed (radial velocity,
   not just photometry), so a pipeline that "finds" something at the published ephemeris can be
   scored against reality rather than against itself.
2. **The ephemeris is published and precise.** Phase folding on an external ephemeris means the
   fitting code cannot drift into a self-consistent but wrong solution.
3. **The signal is shallow.** ~150 ppm is comparable to the correlated noise of a single Kepler
   quarter, so the exercise forces an explicit noise model instead of a naive signal-to-noise claim.
4. **Two independent missions exist.** Kepler long-cadence data (29.4 min) and TESS (120 s) sample
   the same transit, allowing a cross-dataset sanity check.
5. **Repeat coverage is long.** ~4 years of Kepler data (~1,290 orbits) turn a one-off fit into a
   test of stability: a depth that moves when the baseline changes is a preprocessing artefact,
   not a planet.

Because the answer is known, the honest metric of success is *"is the recovered signal stable and
consistent with the published value, and are the uncertainties defensible"* — not *"is p < 0.05"*.

---

## 2. Scientific workflow

```
data acquisition            quality masking            phase folding & detrending
(MAST FITS / cached)  ──▶   (quality bitmask == 0)  ──▶  (published ephemeris; poly on
                                                            out-of-transit points only)
                                                                     │
      synthetic-only ML  ◀──  statistical validation  ◀──          transit model fit
      (inject → classify)     (block bootstrap,              (batman; 4 free params,
                               injection/recovery,            fixed geometry)
                               naive ΔBIC w/ warning)
```

**Stage 1 — Light-curve preparation.** Kepler long-cadence products for 15 quarters
(Q0–Q7, Q9–Q11, Q13–Q15, Q17; no Q8/Q12/Q16 products exist for this target) are reduced to
`SAP_QUALITY == 0` cadences with finite `TIME`/`PDCSAP_FLUX`, median-normalized **per quarter**, and
concatenated into a strictly increasing 45,514-row series spanning 120.54–1591.00 BKJD (~4.0 years).
7,839 quality-flagged and 1,566 non-finite cadences were removed. TESS Sector 14 (120 s,
17,722 rows after masking) is kept as an independent cross-check.

**Stage 2 — Phase folding and detrending.** Phase is computed as
`((t − (T₀ − BJDREF)) + P/2) mod P − P/2` in TDB with BJDREF 2454833 (Kepler) / 2457000 (TESS).
Detrending is deliberately mild: a degree-2 polynomial per contiguous segment (split at >1 d gaps)
fitted to **out-of-transit points only** (`|phase| ≥ 3 h`), so the transit region never enters the
trend fit and the continuum stays near unity.

**Stage 3 — Transit modeling.** `batman` model with four free parameters (radius ratio `rp`, timing
offset `t₀`, baseline, slope) against a baseline+slope null model. Fixed, explicitly labelled
assumptions: `a/R★ = 3.4`, `i = 84.5°`, quadratic limb darkening `u₁ = 0.30, u₂ = 0.20`. Robustness
grids sweep the ephemeris, transit-window half-width, and fixed geometry.

**Stage 4 — Statistical validation.** Residual diagnostics (lag-1 autocorrelation ≈0.93,
non-stationary scatter with a max/min segment ratio of 7.2) establish that independent resampling is
invalid. Primary method: a **segment-aware residual block bootstrap** (block lengths 10–500 cadences,
200 replicates each, seed 42). Independent cross-check: **injection/recovery** of synthetic transits
into real detrended data with noise drawn by residual replacement (50 replicates per depth, including a
0 ppm control). A naive ΔBIC is computed and explicitly flagged as invalid under correlated noise.

**Stage 5 — Synthetic-only ML.** A 7-feature classifier (logistic regression baseline; RandomForest
considered only if its validation F1 beats the baseline's validation F1 by >0.05, as corrected in Phase 8)
is trained on **26 windows**: 13 with synthetic transits injected at 75/150/225/300 ppm and 13 uninjected.
The split is by parent contiguous segment, so no segment appears in more than one of
train/validation/test (13/6/7). Labels come only from the injection process — **no real-planet labels are
used anywhere**.

---

## 3. Results

### Transit recovery (Kepler, all 15 quarters, detrended)

| Quantity | Value |
|---|---|
| Fitted transit depth | **153.8 ppm** |
| Radius ratio `rp` | 0.01240 |
| Timing offset at published ephemeris | **+0.03 min** |
| Points in ±6 h window | 27,111 |
| Block-bootstrap 95% interval (block 200 cad) | **[151.2, 158.2] ppm** |
| Block-bootstrap 95% interval (block 500 cad) | [150.4, 157.7] ppm |
| Fixed-geometry sensitivity range | **146–162 ppm** |
| Injection/recovery at 154 ppm | 154.8 ± 3.2 ppm (bias +0.8) |
| No-injection control (0 ppm) | +2.7 ± 2.0 ppm |

The headline scientific result is a **baseline effect, not a detection**: fitting only Kepler Q0
(9.7 days, 439 points) gives 183–186 ppm and a −1.7 min timing offset, both of which collapse to
~154 ppm and ~0.0 min once the full 4-year baseline is used. The Q0 values were dominated by a
±5×10⁻⁴ instrumental/stellar trend; they are superseded and should not be quoted.

### Statistical validation

- The bootstrap interval is **stable across defensible block lengths** (0.2–10.2 d), which is the
  intended robustness check — the interval width moves by <2×, the central value does not move.
- Injection/recovery bias is **<1 ppm** at all non-zero depths (50–300 ppm).
- The 0 ppm control shows a small **+2.7 ppm false-positive tendency**: the model mildly prefers a
  non-zero depth from noise alone. At 154 ppm the signal is well separated, but this is exactly the
  kind of number that must be reported rather than hidden.
- Naive ΔBIC = **−2195.58** under an independent-Gaussian likelihood. This number is *not* evidence:
  with lag-1 AC ≈ 0.94, the effective sample size is far below n = 27,111 and BIC dramatically
  overstates support. It is reported as a descriptive fit comparison only.

### Synthetic-only ML (test set)

| Metric | Value |
|---|---|
| Windows / train / validation / test | 26 / 13 / 6 / 7 |
| Decision threshold (validation Youden index) | 0.4405 |
| Precision / recall / F1 | 0.75 / 0.75 / 0.75 |
| ROC-AUC / PR-AUC | 0.667 / 0.771 |
| Stratified dummy baseline F1 | 0.571 |
| Confusion matrix | `[[2, 1], [1, 3]]` (TN, FP, FN, TP) |
| RandomForest (200 trees, depth 6) | validation F1 0.800 → **not selected** (baseline validation F1 1.000) |

Phase 8 re-derived this table under a stricter protocol (train-only imputation, validation-only model
selection, one test pass) and reproduced every test metric exactly; only the threshold moved by 0.0006.
See [`reports/phase8_ml_pipeline_audit.md`](reports/phase8_ml_pipeline_audit.md). With 7 test windows these
numbers are a pipeline demonstration, not a performance estimate.

---

## 4. Limitations — read before quoting any number

1. **Correlated noise is the dominant statistical issue.** Lag-1 residual autocorrelation is ≈0.93;
   bin error bars of the form `std/√n` assume independent points and **underestimate** the true
   uncertainty. Per-point RMS residuals (~1,000–1,200 ppm) are 5–6× the transit depth — the phase
   fold, not individual points, does the work.
2. **Fixed geometry dominates the systematic budget.** The 146–162 ppm range from the geometry grid is
   *larger* than the bootstrap interval. The quoted interval is a statistical interval **conditional
   on** `a/R★ = 3.4`, `i = 84.5°`, the limb-darkening coefficients, the detrending choice, and the
   model form. It is not a total uncertainty.
3. **Correlation is approximated, not modeled.** The block bootstrap resamples contiguous residuals
   within segments; correlation on scales >~10 days is not fully captured, and block lengths longer
   than the shortest segments were not tested.
4. **The ML test set is 7 windows.** One different classification moves F1 from 0.75 to 0.667 or 0.857.
   ROC-AUC 0.667 on n=7 is essentially uninformative. Read the pipeline design, not the metric.
5. **The ML labels are synthetic only.** Positives are injected `batman` signals at a fixed 150 ppm
   template; the `matched_filter_corr` feature does not adapt to the actual injected depth, and 9 of 26
   windows had a NaN correlation that was median-imputed in the feature CSV. Performance says nothing
   about real-observation generalization.
6. **Feature values respond to the injected transit — that is the signal, not leakage.** The seven
   features are computed from the flux the classifier is given (transit included when present), which is
   the correct order; Phase 8 verified this by rebuilding `phase5_dataset.json` byte-for-byte. The one real
   protocol defect found in Phase 5 — a correlation-imputation median fitted over all 26 windows — was
   corrected in Phase 8 and changes no reported metric. See
   [`reports/phase8_ml_pipeline_audit.md`](reports/phase8_ml_pipeline_audit.md).
7. **Cross-dataset validation is partial.** Only TESS S14 is available; S40/S53/S74 could not be
   retrieved and were not substituted. No joint Kepler+TESS fit exists.
8. **No formal detection significance is claimed anywhere.** Every RSS improvement, ΔBIC, and interval
   in this repository is descriptive. The planet is known and independent confirmation does not rest on
   this work.
9. **The ML task is easier than real detection.** Positives are injected at the published ephemeris, so
   the pipeline is asked to recover a correctly-phased synthetic transit, not to search for one.

---

## 5. Re-detecting a known planet is not discovering one

This distinction is the point of the project, so it is stated explicitly:

| Reproducing a known signal (what this repo does) | Discovering a new planet (what this repo does not do) |
|---|---|
| Ephemeris is given; the fit is anchored to a known phase | Period must be searched over a blind frequency grid |
| One candidate, known to be real | Thousands to millions of candidates, almost all false |
| Success = recovered depth agrees with published value | Success = signal survives a calibrated false-alarm analysis |
| Noise model can be checked against a known answer | Noise model *is* the result; mistakes become "discoveries" |
| Metric: stability under preprocessing choices | Metric: statistical significance after trials correction |

Because the target is known, this repo can afford to report numbers that a discovery paper could not:
a 17% depth shift between baselines, a +2.7 ppm noise floor bias, a ΔBIC that is explicitly declared
unusable, and an ML F1 computed on 7 samples. Those are the useful outputs.

---

## 6. Repository layout

```
astronomy-ai/
├── scripts/                     # analysis scripts (see §8 for runnable/not)
│   ├── download_kepler_quarters.py     # network: MAST FITS for 15 Kepler quarters
│   ├── download_tess_sectors.py        # network: MAST FITS for TESS S40/S53/S74
│   ├── apply_quality_mask.py           # offline: needs raw FITS cache
│   ├── prepare_kepler_quarters.py      # offline: FITS cache -> per-quarter + combined CSVs
│   ├── transit_analysis.py             # Phase 3: fits + robustness grids + figures
│   ├── phase4_residual_diagnostics.py  # Phase 4: AC / non-stationarity diagnostics
│   ├── phase4_block_bootstrap.py       # Phase 4: segment-aware block bootstrap
│   ├── phase4_injection_recovery.py    # Phase 4: injection/recovery + control
│   ├── phase4_model_comparison.py      # Phase 4: naive ΔBIC with correlation warning
│   ├── phase5_build_dataset.py         # Phase 5: dataset generator (BROKEN, see §9)
│   ├── phase5_features.py              # Phase 5: 7-feature extraction
│   ├── phase5_baseline.py              # Phase 5: logistic regression + RF comparison
│   └── (earlier Phase 1–2 scripts: assess_transit, fit_transit_model, phase_fold, ...)
├── data/
│   ├── raw/mast_cache/          # downloaded FITS (gitignored)
│   └── processed/               # analysis-ready CSVs (gitignored)
├── reports/
│   ├── figures/                 # Phase 1–3 figures (PNG)
│   ├── results/                 # machine-readable JSON for Phase 3–4
│   ├── phase2_data_integrity.md
│   ├── phase3_transit_analysis.md
│   ├── phase4_statistical_validation.md
│   ├── phase4_audit.md
│   ├── phase5_results.md  /  phase5_audit.md
│   ├── phase6_portfolio_readiness.md
│   ├── phase7_reliability_audit.md
│   └── phase8_ml_pipeline_audit.md
├── tests/                        # 28 tests: phase 5 dataset, builder, phase 8 pipeline
├── docs/
│   ├── PIPELINE_STATUS.md        # which chain to run; frozen artifact hashes
│   └── reproducibility.md
├── pyproject.toml               # ruff config only — this is not an installable package
└── requirements-lock.txt        # 77 pinned packages (see §9)
```

`src/astronomy_ai/` is an empty package skeleton and `pyproject.toml` contains no build-system or
project metadata. **Nothing is installed** — scripts are executed as files, and cross-script imports
work because each script inserts its own directory into `sys.path`.

---

## 7. Setup on Windows (PowerShell)

Verified environment: **Python 3.11.17** in `.venv`, created with `uv 0.12.23`. All dependency pins in
`requirements-lock.txt` require Python ≥ 3.11 (`numpy`, `astropy`, `scipy`, `scikit-learn`), so use
**3.11**; do not assume a newer interpreter works with these exact pins.

### Option A — uv (matches how this environment was built)

```powershell
cd C:\path\to\astronomy-ai
uv venv --python 3.11 .venv
uv pip install --python .\.venv\Scripts\python.exe -r requirements-lock.txt
```

### Option B — standard library `venv`

```powershell
cd C:\path\to\astronomy-ai
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-lock.txt
```

If `py -3.11` reports no such version, install CPython 3.11 first (`winget install Python.Python.3.11`)
or use Option A. `py -0p` lists what the launcher can see.

### Verification

```powershell
.\.venv\Scripts\python.exe --version          # expect Python 3.11.x
.\.venv\Scripts\python.exe -m pip check       # expect "No broken requirements found."
.\.venv\Scripts\python.exe -c "import numpy, pandas, scipy, astropy, batman, lightkurve, sklearn; print('imports OK')"
```

`batman-package` is a C extension, but the installed build came from a `cp311-cp311-win_amd64` wheel,
so no local compiler is needed on Windows + Python 3.11. On other combinations pip may need MSVC build
tools; `conda install -c conda-forge batman-package` is the usual fallback.

---

## 8. Running tests and reproducing the analyses

Full details, including what each command overwrites and how to verify output hashes, are in
[`docs/reproducibility.md`](docs/reproducibility.md). Two ML pipeline generations coexist: a **historical**
chain (`scripts/phase5_*`) that is frozen because it produced the audited artifacts, and a **maintained**
chain (`scripts/phase8_*`) for new work. Which script to run for what, and which artifacts must not be
regenerated in place, is in [`docs/PIPELINE_STATUS.md`](docs/PIPELINE_STATUS.md). The short version:

### Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
```

**Measured output (Phase 8):** `28 passed` — 28 collected, exit code 0, ~7 s. The suite runs from any
working directory because paths resolve from the test file, not the shell.

Coverage: dataset invariants (labels, segment separation, schema, imputation, split sizes); builder
guards (parses, top-level indentation, features come from the presented flux, deterministic rebuild,
regeneration matches the frozen dataset); and the Phase 8 pipeline checks (extractor cannot see labels or
depth, one code path for both classes, parent groups never cross splits, imputation fitted on train only).

```powershell
# Still fails: pytest also collects scripts/*_test.py, which reads sys.argv at import time.
# The fix is `testpaths = ["tests"]` in pyproject.toml; that file is protected tooling config
# and has not been edited.
# .\.venv\Scripts\python.exe -m pytest
```

### Offline reproduction (no network, uses committed artifacts only)

```powershell
.\.venv\Scripts\python.exe scripts\phase5_features.py        # dataset JSON  -> feature CSV + config
.\.venv\Scripts\python.exe scripts\phase5_baseline.py        # feature CSV   -> results JSON + MD
.\.venv\Scripts\python.exe scripts\phase4_model_comparison.py
```

These three were verified during Phase 6 to reproduce their committed outputs **byte-identically**
(SHA-256 match).

```powershell
# Full pipeline re-fits. These OVERWRITE reports/figures and reports/results.
# Measured on this machine: ~17 s (Phase 3), ~3.6 min (bootstrap), ~1.5 min (injection).
.\.venv\Scripts\python.exe scripts\transit_analysis.py
.\.venv\Scripts\python.exe scripts\phase4_block_bootstrap.py
.\.venv\Scripts\python.exe scripts\phase4_injection_recovery.py
```

All three were also verified in Phase 6, in an isolated copy: the 10 Phase 3 figures and both Phase 4
JSONs reproduce **byte-identically**, and `phase3_transit_analysis.json` matches in every value except its
embedded `generated_at_utc` timestamp.

Back up `reports\` before running them if you want to keep the committed outputs:
`Copy-Item reports reports_backup -Recurse`.

### Requires downloaded data or network — **not** reproducible from a clean clone

| Script | Requirement |
|---|---|
| `download_kepler_quarters.py`, `download_tess_sectors.py`, `prepare_lightcurves.py`, `smoke_test_data.py` | live MAST access |
| `apply_quality_mask.py`, `prepare_kepler_quarters.py` | FITS files in `data/raw/mast_cache/` (gitignored) |
| **all other analysis scripts** (`transit_analysis.py`, `phase4_*.py`, `phase5_build_dataset.py`, and the Phase 1–2 fitters/folders) | analysis-ready CSVs in `data/processed/` (**gitignored**) |

Note that `data/processed/*.csv` is excluded by `.gitignore`. A fresh clone can run only the three
offline commands above (and only if `reports/phase5_dataset.json` and the `reports/results/*.json`
files are present). Re-deriving the CSVs requires a MAST download, which is a network dependency.

---

## 9. Known issues and unresolved defects

These are documented rather than fixed, because fixing them would modify analysis code or results
without review.

1. **Phase 7 finding R1 is retracted.** It claimed the frozen Phase 5 features were leakage-contaminated.
   Phase 8 rebuilt the dataset from the presented-flux pipeline and matched all 26 windows exactly, so the
   artifact was correct and the script was wrong. The script is now fixed and reproduces the artifact
   byte-for-byte (`f8ad47fb…`). See [`reports/phase8_ml_pipeline_audit.md`](reports/phase8_ml_pipeline_audit.md).
2. **Phase 5's imputation statistic was fitted across splits** (median over all 26 windows, 9 values).
   Corrected in the Phase 8 pipeline with a train-only median; it changes the threshold by 0.0006 and no
   reported test metric. The frozen Phase 5 CSV was left as-is.
3. **`scripts/statistical_validation.py` would raise `NameError`** — `moving_block_resid` and
   `stratified_block_resid` are called but never defined. It is an incomplete proto-Phase-4 prototype,
   superseded by `phase4_*.py`, and none of its outputs exist anywhere in the repo. Left untouched.
4. **`pytest` at the repository root still fails collection** in `scripts/transit_control_test.py` (parses
   `sys.argv` at import). The fix is `testpaths = ["tests"]` in `pyproject.toml`; that file is protected
   tooling config in this harness and was not edited. Use `pytest tests`.
5. **Lint is clean.** `ruff check scripts tests` reports **0 findings**. Two suppressions are deliberate and
   commented: `# noqa: E402` where imports must follow `sys.path` setup, and `# noqa: F821` on the four
   calls to the undefined helpers in `scripts/statistical_validation.py` (item 3) — the calls cannot be
   "fixed" without inventing a statistical implementation.
6. **`reports/phase5_results.md` is now UTF-8** (converted in Phase 7 from Windows-1252; CRLF preserved,
   no replacement characters, single em dash).
7. **Git history does not contain Phase 3–5 artifacts.** Only Phase 1–2 files are tracked. Everything
   from `reports/results/`, `reports/phase3_*`, `reports/phase4_*`, `reports/phase5_*`, the `tests/`
   directory, and the Phase 3–5 scripts is currently untracked. No commit was made in this phase.
8. **`HOME/` (untracked tooling cache) sits in the project root** and is not covered by `.gitignore`.
9. **Superceded artifacts remain for provenance.** Q0-only fits, the orphan Phase 1 figures, and
   `injection_recovery.py` (which reads a `phase4_statistical_validation.json` that does not exist)
   are kept intentionally; they are not part of the current result chain.
10. **`pip`, `setuptools`, `wheel` are installed but deliberately not in the lock file** — they are
    environment tooling, not analysis dependencies. `batman-package==2.5.3` **was** missing and has been
    added to `requirements-lock.txt` in Phase 6 (see `reports/phase6_portfolio_readiness.md`).

---

## 10. Reports and figures

| Artifact | Contents |
|---|---|
| [`reports/project_audit.md`](reports/project_audit.md) | Phase 1 audit: initial state, defects, plan |
| [`reports/phase2_data_integrity.md`](reports/phase2_data_integrity.md) | Quality masking policy, provenance, row accounting |
| [`reports/phase3_transit_analysis.md`](reports/phase3_transit_analysis.md) | **Phase 3 scientific analysis**: fits, robustness grids, Q0-vs-full-baseline |
| [`reports/phase4_statistical_validation.md`](reports/phase4_statistical_validation.md) | **Phase 4 validation**: bootstrap, injection/recovery, model comparison |
| [`reports/phase4_audit.md`](reports/phase4_audit.md) | Independent audit of the Phase 4 statistics |
| [`reports/phase5_results.md`](reports/phase5_results.md) | **Phase 5 ML experiment**: metrics, split, synthetic-only warning |
| [`reports/phase5_audit.md`](reports/phase5_audit.md) | **Phase 5 audit**: leakage, feature independence, metric reproduction |
| [`reports/phase6_portfolio_readiness.md`](reports/phase6_portfolio_readiness.md) | Phase 6: portfolio readiness checks, changed files |
| [`reports/phase7_reliability_audit.md`](reports/phase7_reliability_audit.md) | **Phase 7**: repairs, test suite, regeneration comparison, data-publication manifest (its R1 finding is retracted by Phase 8) |
| [`reports/phase8_ml_pipeline_audit.md`](reports/phase8_ml_pipeline_audit.md) | **Phase 8**: synthetic-pipeline audit, leakage analysis, corrected evaluation |
| `reports/results/phase3_transit_analysis.json` | Machine-readable fit results and full robustness grids |
| `reports/results/phase4_*.json` | Bootstrap intervals, injection/recovery table, ΔBIC |
| `reports/phase5_dataset.json`, `phase5_features.csv`, `phase5_results.json` | ML dataset, features, metrics |

Key figures (`reports/figures/`):

- `phase3_kepler_all_coverage.png` — 4-year quality-masked coverage and gaps.
- `phase3_kepler_all_masked_raw_vs_detrended.png` — detrending effect on the full baseline.
- `phase3_kepler_all_masked_detrended.png` — binned phase fold with model overlay and residuals
  (the headline 153.8 ppm fit).
- `phase3_kepler_q0_masked_detrended.png` — the superseded Q0-only fit, for comparison.
- `phase3_robustness_summary.png` — depth across ephemeris, window, and geometry grids.
- `phase3_tess_s14_masked_raw.png` — independent TESS S14 fold.
- Phase 1 figures (`kepler_kepler_10*.png`, `tess_kepler_10*.png`) — original Q0/S14 single-dataset fits.

---

## 11. Provenance and status

- Phases 1–5 are complete; Phase 5 passed audit and is frozen. Phase 6 was documentation and
  reproducibility only. Phase 7 repaired the Phase 5 dataset builder (indentation), converted the test
  module into a real pytest suite, and re-encoded one report. Phase 8 audited the synthetic-data pipeline,
  corrected the Phase 5 builder's feature source, corrected a cross-split imputation statistic, and
  reproduced every ML metric under a stricter protocol. **No Phase 3/4 scientific result, parameter,
  threshold, label, or split was changed.**
- Phase 3/4/5 report, result, and figure hashes are preserved across all phases; the only intentional
  content change to a frozen artifact is the UTF-8 re-encoding of `reports/phase5_results.md` (Phase 7).
- The Phase 5 dataset is byte-reproducible: `python scripts/phase5_build_dataset.py` regenerates
  `reports/phase5_dataset.json` exactly (`f8ad47fb…`), and Phase 8's independent builder agrees.
- Seeds: `SEED = 42` (block bootstrap, dataset build, ML), `SEED = 1234` (older `injection_recovery.py`).
- Data provenance: MAST (Kepler long-cadence `kplr011904151-*_llc.fits`, TESS SPOC S14 120 s); per-quarter
  row counts, time ranges, and observed quality bits in `reports/kepler_quarters_metadata.json`.
- Nothing is committed or pushed. The working tree is the deliverable.
