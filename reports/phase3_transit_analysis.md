# Phase 3 — Transit-Analysis Pipeline

**Date:** 2025-10-15
**Status:** complete — awaiting user review before Phase 4
**Framing:** Kepler-10 b is a known planet; this is a re-detection / pipeline-validation exercise.
All RSS-improvement numbers below are **descriptive fit-quality metrics, not detection significances**.

---

## 1. What was done

1. Committed Phase 2 (`21bf6e2`) after re-running ruff + a regression command (both green).
2. Downloaded the full available Kepler long-cadence coverage (Decision B) with explicit selection criteria.
3. Built per-quarter quality-masked CSVs + a validated combined file (Decision B requirements).
4. Produced the TESS candidate inventory and a recommended selection (Decision C) — **nothing TESS downloaded**.
5. Kept the historical orphan figures untouched; `scripts/plot_full_phase_fold.py` remains their
   reproducible generator (content-equivalent output, not a byte-identical clone — the original
   generating code no longer exists). Relationship documented here and in Phase 2 report §6.
6. Implemented the Phase 3 analysis in a new script `scripts/transit_analysis.py`
   (existing scripts untouched) with machine-readable results in
   `reports/results/phase3_transit_analysis.json`.

## 2. Data acquisition

### Kepler (Decision B) — downloaded

`scripts/download_kepler_quarters.py` — selection criteria, asserted in code:
target "Kepler-10" (KIC 11904151), mission=Kepler, author=Kepler, exptime=long (1800 s),
exactly one product per quarter, KIC-filename assertion, expected-count assertion (15).

- Scope checked against MAST metadata first: **5.9 MB total** (per-file 0.08–0.51 MB) — inside the approved envelope.
- After download: all 15 FITS verified present in `data/raw/mast_cache`.
- Quarters available and downloaded: **Q0–Q7, Q9–Q11, Q13–Q15, Q17** (no Q8/Q12/Q16 products exist for this target).

`scripts/prepare_kepler_quarters.py` — same quality policy as Phase 2 (`SAP_QUALITY == 0`,
finite TIME/PDCSAP_FLUX, median-normalized **per quarter**). Per-quarter CSVs
(`kepler_q{qq}_quality_masked.csv`, individually identifiable) plus combined
`kepler_all_quarters_quality_masked.csv`:

| Quantity | Value |
|---|---|
| Combined rows | **45,514** (Q0 alone: 439) |
| Time span | 120.54–1591.00 d BKJD (**~4.0 years**, Q0 alone: 9.7 d) |
| Cadence | 29.4 min everywhere |
| Duplicate/overlap check | combined timestamps strictly increasing — **no overlaps, no duplicates** |
| Inter-quarter gaps | 4,877 (expected: month-long downlinks + masked safe modes) |
| Rows removed by masking (all quarters) | 7,839 quality-flagged + 1,566 non-finite |

Provenance: `reports/kepler_quarters_metadata.json` (per-quarter rows, time ranges, gap counts,
observed quality bits, pipeline versions). Quality bits observed on flagged rows are recorded per quarter
(e.g. Q2 bits {1,3,5,6,7,12,13,15}); bit *names* remain referenced to the Kepler Archive Manual, not transcribed.

### TESS (Decision C) — inventory only, no download

Candidate SPOC light-curve products for Kepler-10 (from the Phase 2/3 MAST searches):

| Sector | Cadence | Products | Size |
|---|---|---|---|
| 14 | 120 s | 1 (held since Phase 1) | 1.96 MB |
| 40 | 20 s / 120 s | fast-lc + lc | 12.22 / 2.06 MB |
| 41 | 20 s / 120 s | fast-lc + lc | 11.52 / 1.94 MB |
| 53 | 20 s / 120 s | fast-lc + lc | 10.83 / 1.83 MB |
| 54 | 20 s / 120 s | fast-lc + lc | 11.36 / 1.92 MB |
| 55 | 20 s / 120 s | fast-lc + lc | 11.77 / 1.99 MB |
| 74 | 120 s | 1 | 1.95 MB |
| 75 | 120 s | 1 | 2.02 MB |
| 80 | 120 s | 1 | 1.94 MB |
| 81 | 120 s | 1 | 1.95 MB |
| 82 | 120 s | 1 | 1.89 MB |

Sizes are MAST-reported file sizes (exact, not estimates). Quality-flag policy would be identical to
Phase 2 (`QUALITY == 0`); all sectors are SPOC pipeline products on the same TIC 377780790 target.

**Recommendation:** download the three spread-out 120 s sectors **S40, S53, S74** (2021, 2022, 2024 —
baseline diversity for a TTV-style timing check), ≈ **5.8 MB total**, keeping S14. The 20 s fast-lc
products (~11–12 MB each) are not recommended: 6× the volume for marginal gain at this noise level.
**Awaiting your approval before any TESS download.**

## 3. Methods (implemented in `scripts/transit_analysis.py`)

- **Time conversion:** phase = ((t − (T0−BJDREF)) + P/2) mod P − P/2, TDB, BJDREF 2454833 (Kepler) /
  2457000 (TESS) — validated in Phase 2.
- **Models:** null = baseline + slope·Δt (2 params); transit = baseline·batman(rp, t0; fixed geometry)
  + slope·Δt (4 free params: rp, t0, baseline, slope). Fixed: a/R*=3.4, i=84.5°, u1=0.30, u2=0.20.
- **Detrending (optional, mild):** per contiguous segment (split at >1 d gaps), degree-2 polynomial on
  **out-of-transit points only (|phase| ≥ 3 h)**; only the zero-mean wiggle is removed so the continuum
  stays near unity. Transit-region data never enters the fit.
- **Binning:** 30-min bins over ±6 h; error bars = std/√n (noted in outputs as underestimating
  correlated noise).
- **Robustness grids** on the two primary detrended configs:
  - ephemeris: ΔP ∈ {−1, 0, +1}×10⁻⁶ d (measured scatter of published solutions), ΔT0 ∈ {−1, 0, +1}×2.82×10⁻⁴ d (archive 1σ)
  - window half-width ∈ {3, 6, 12} h
  - fixed geometry: a/R* ∈ {3.2, 3.4, 3.6} × i ∈ {83.5, 84.5, 85.5}°

## 4. Results (measured this phase)

### Primary fits (±6 h window)

| Config | n pts | rp | depth | t0 offset | RSS impr. | RMS resid in/out (ppm) |
|---|---|---|---|---|---|---|
| Kepler Q0 original / raw | 288 | 0.01363 | 185.7 ppm | −1.73 min | 16.89% | — |
| Kepler Q0 masked / raw | 272 | 0.01352 | 182.8 ppm | −1.75 min | 17.28% | — |
| Kepler Q0 masked / **detrended** | 272 | 0.01289 | **166.3 ppm** | −1.61 min | 45.80% | — |
| Kepler all-quarter masked / raw | 27,111 | 0.01239 | **153.6 ppm** | **+0.01 min** | 7.50% | — |
| Kepler all-quarter masked / **detrended** | 27,111 | 0.01240 | **153.8 ppm** | **+0.03 min** | 7.85% | ~1,200 / ~1,000 ppm (per-point) |
| TESS S14 masked / raw | 10,520 | 0.01405 | 197.4 ppm | −0.21 min | 0.29% | — |

Exact reproduction of the legacy numbers for Q0-original (185.7 ppm / 16.893%) and of the Phase 2
masked numbers confirms the new implementation is consistent with the old scripts.

### Q0-only vs full-coverage comparison (the headline result)

- **Fitted depth drops ~17%**: 183–186 ppm (Q0) → **~154 ppm** (all quarters).
- **Timing offset collapses to zero**: −1.7 min (Q0) → **≈ 0.0 min** (all quarters) — the Q0 offset was a
  sparse-sampling/trend artifact, not a real TTV signal.
- Explanation consistent with the data: Q0 has 439 points over 9.7 d with a ±5×10⁻⁴ instrumental/stellar
  trend; the fit there is prior- and trend-dominated. The full baseline dilutes both effects.

### Detrending effect

- Q0: large — depth −9% (182.8→166.3 ppm), RSS improvement 17.3%→45.8% (the trend was inflating the
  null-model RSS; improvement remains descriptive only).
- All-quarters: negligible (153.6→153.8 ppm, +0.1%) — trends average out over ~1,290 orbits.

### Robustness (all measured; full grid in the JSON)

- **Ephemeris:** depth rock-stable — Q0: 166.3 ppm in all 9 combos; all-quarters: 153.6–153.9 ppm.
  Fitted t0 offset shifts by up to −1.6 min at ΔP=+1×10⁻⁶ d over the 4-year baseline (expected phase
  drift; the fit absorbs it), without affecting depth. Conclusions are **insensitive** to the
  published-solution scatter.
- **Window width:** depth 165–168 ppm (Q0), 151–155 ppm (all) — stable at the ±2% level. RSS improvement
  swings wildly (35.6%↔56.6% for Q0) confirming it is **not** a stable metric.
- **Fixed geometry:** the dominant uncertainty — depth spans **146–162 ppm** (all-quarters),
  ~±5% around 154 ppm; a/R* and inclination compensate each other (degenerate at this SNR).
  Timing offsets here vary up to ±9 min and are not constraining.

## 5. Figures (all phase3-*, originals untouched and hash-verified)

- `phase3_kepler_all_coverage.png` — 4-year quality-masked coverage.
- `phase3_kepler_all_masked_raw_vs_detrended.png`, `phase3_kepler_q0_masked_raw_vs_detrended.png` —
  raw vs detrended comparison.
- `phase3_<dataset>_<variant>.png` — binned phase-folded flux with std/√n error bars, model overlay,
  residual panel (per config).
- `phase3_robustness_summary.png` — depth across the three grids (x-axis is grid index; parameter
  mappings are in the JSON and §3).

## 6. Interpretation and limitations

- With full Kepler coverage the data show a **stable, reproducible ~154 ppm dip at the published
  ephemeris position**, robust to ephemeris and window choices at the percent level. This is consistent
  with re-detecting the known Kepler-10 b transit — **stated as consistency, not a claimed significance**.
- Dominant identified systematic: **fixed geometry choice** (±5% on depth). Fitting geometry would need
  better in-transit sampling than long cadence provides; documented as a fixed assumption.
- Bin error bars assume independent points and **underestimate** uncertainty under correlated noise;
  per-point RMS residuals (~1,000–1,200 ppm) are ~5–6× the depth — the fold does the heavy lifting.
- RSS improvement is demonstrably unstable against window/preprocessing choices (35–57% for the same
  Q0 data) and must not be quoted as evidence strength. Phase 4 must build a defensible noise model
  (correlation-aware) before any significance statement.
- Q0's earlier "−1.7 min offset" and 183–186 ppm depth should be retired in favor of the full-baseline
  values (the legacy scripts remain in the repo for provenance; their outputs are superseded for
  scientific interpretation).

## 7. Files changed in Phase 3

New scripts: `download_kepler_quarters.py`, `prepare_kepler_quarters.py`, `transit_analysis.py`.
New data (gitignored): 14 FITS (cache), 15 quarter CSVs + combined CSV (data/processed).
New reports: `reports/kepler_quarters_metadata.json`, `reports/results/phase3_transit_analysis.json`,
`reports/phase3_transit_analysis.md` (this file), 10 `phase3_*.png` figures.
**Modified: none. Deleted: none.** Original CSVs, original 8 figures, and legacy scripts all verified
byte-identical/untouched at phase end.

## 8. Decisions needed before Phase 4

1. Approve TESS download of S40 + S53 + S74 (≈5.8 MB) as recommended, another subset, or none for now?
2. Phase 4 will build the correlation-aware noise model (e.g. residual bootstrap over transit-separated
   blocks or injection-recovery). Any preference for the primary method? (Default proposal: time-block
   bootstrap of residuals + injection/recovery as a cross-check.)

**Phase 3 status: passed.**
