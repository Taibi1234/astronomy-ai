# Phase 2 — Data Integrity, Provenance & Quality Masking

**Date:** 2025-10-15
**Status:** complete — awaiting user review before Phase 3
**All numbers below were measured by running the project's scripts and queries during this phase.**
PowerShell equivalents: replace `.venv/Scripts/python.exe` with `.\.venv\Scripts\python.exe`.

---

## 1. Git baseline (Decision 1)

- Inspected `git status --porcelain`, `.gitignore`, and a dry-run staging list before committing.
- Staged 19 files (scripts, figures, reports, configs). Excluded by `.gitignore` and verified
  excluded: `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`, downloaded data, `.env*`.
- **Commit `1b00fa1`** — `chore: initial baseline (Phase 1 audit state)`. Nothing pushed.
- Working tree after Phase 2 changes (see §8) contains only intended modifications/additions.

## 2. Quality-masked datasets (Decision 4)

New script: `scripts/apply_quality_mask.py` (offline; reads cached FITS only).

**Policy** (documented in the script docstring and `reports/dataset_metadata.json`):
keep only cadences with the mission quality bitmask == 0 (no flags). Normalization matches
`prepare_lightcurves.py` (`remove_nans()` then divide by median of `PDCSAP_FLUX`).
Original CSVs were not modified (mtimes unchanged: 15:04 / 15:05).

```powershell
.\.venv\Scripts\python.exe scripts\apply_quality_mask.py
```

Measured results:

| Dataset | FITS rows | removed non-finite | removed quality-flagged | final rows |
|---|---|---|---|---|
| Kepler (Q0, 1800 s) | 476 | 7 | **30** | **439** → `kepler_kepler_10_quality_masked.csv` |
| TESS (S14, 120 s) | 19,337 | 1,615 | **0** | **17,722** → `tess_kepler_10_quality_masked.csv` |

- **Quality bits observed on flagged rows (measured, not assumed):** Kepler bits {5, 6, 7, 12, 13, 15};
  TESS bits {2, 3, 5, 7, 12}. Bit *names* are deliberately not hardcoded here; definitions live in the
  Kepler Archive Manual (`SAP_QUALITY`) and TESS SPOC Data Products spec (`QUALITY`).
- **TESS finding:** every QUALITY≠0 cadence was already NaN in flux, so lightkurve's `remove_nans()`
  had already dropped all flagged TESS data. The masked TESS CSV equals the original to
  **max |Δflux| = 6.0×10⁻⁸** (times identical; medians identical) — pure floating-point-path noise,
  scientifically irrelevant at the 2×10⁻⁴ depth scale. Recorded honestly as a difference, not "identical".
- **Kepler finding:** masked CSV is a strict subset of the original (verified: all 439 times ∈ original times).

**Input/output validation** (implemented in the script, results in `dataset_metadata.json`):
columns exactly `[time, normalized_flux]`, float dtypes, all finite, strictly increasing time,
no duplicate times — original CSVs: valid; masked CSVs: valid.

## 3. Downstream comparison: original vs quality-masked

Same commands, with optional dataset-variant argument added to four scripts
(fully backward-compatible; defaults reproduce Phase 1 numbers exactly — verified):

```powershell
.\.venv\Scripts\python.exe scripts\assess_transit.py            # original
.\.venv\Scripts\python.exe scripts\assess_transit.py quality_masked
.\.venv\Scripts\python.exe scripts\fit_transit_model.py quality_masked
```

| Metric | Kepler orig | Kepler masked | TESS orig | TESS masked |
|---|---|---|---|---|
| points in ±6 h window | 288 | 272 | 10,520 | 10,520 |
| box depth (assess) | 209.1 ppm | 209.1 ppm | 205.0 ppm | 205.0 ppm |
| box RSS reduction | 18.40% | 19.38% | 0.30% | 0.30% |
| batman Rp/R\* | 0.013627 | 0.013519 | 0.014050 | 0.014050 |
| batman depth | 185.7 ppm | 182.8 ppm | 197.4 ppm | 197.4 ppm |
| timing offset | −1.73 min | −1.75 min | −0.21 min | −0.21 min |
| batman RSS improvement | 16.893% | 17.277% | 0.294% | 0.294% |

**Conclusion:** quality masking shifts Kepler numbers by ≲1% (Rp/R\* −0.8%) and leaves TESS unchanged.
All qualitative conclusions are stable; these remain descriptive fit metrics, not significances.

## 4. Timestamp & time-system validation (verified facts)

- FITS extension headers: `TIMESYS = TDB`, `TIMEUNIT = d`, `BJDREFI = 2454833` (Kepler) / `2457000` (TESS),
  `BJDREFF = 0.0` — confirms the scripts' hardcoded offsets.
- `time` column semantics: mission-relative BJD in days — **BKJD = BJD(TDB) − 2454833.0** (Kepler),
  **TJD = BJD(TDB) − 2457000.0** (TESS). Absolute BJD = `time + bjdref`.
- CSV time ranges match FITS `TSTART`/`TSTOP` exactly (Kepler 120.539–130.246; TESS 1683.356–1710.206).
- Ephemeris **verified against the NASA Exoplanet Archive** (`ps` table, queried this session):
  multiple published solutions for Kepler-10 b include **P = 0.837491225 ± 3.0×10⁻⁷ d** and
  **T0 = 2454964.574858 ± 0.000282 d** (BJD). Script values (0.837491225, 2454964.575) match within
  rounding; ΔT0 ≈ 0.00014 d ≈ 12 s, well inside the archive uncertainty. ✔
  - ⚠️ Note for Phase 3: solutions in the archive scatter by ~1×10⁻⁶ d in P; over the ~4400 orbits
    between the Kepler epoch and TESS S14 this could drift phase by up to ~6 min — ephemeris
    sensitivity must be tested before trusting the sub-minute TESS timing offset.

## 5. Coverage search (Decision 2 — search only, nothing downloaded)

Query: `lk.search_lightcurve("Kepler-10", mission=..., author=...)` (MAST metadata only).

- **Kepler long-cadence (1800 s): 15 quarters available** — Q0–Q7, Q9–Q11, Q13–Q15, Q17.
  Current data uses only **Q0 (9.7 d)**.
- **TESS SPOC: sectors 14, 40, 41, 53, 54, 55, 74, 75, 80, 81, 82** (several have both 120 s and
  20 s products). Current data uses only **Sector 14**.

Downloading all 15 Kepler long-cadence light curves is the single biggest cheap science win
(roughly 20–40 MB total, estimate to be confirmed at download time). **No download performed —
awaiting approval (see §9).**

## 6. Orphan figures (Decision 3)

- Evidence: PNG metadata shows only "Matplotlib 3.11.2" (no timestamps). File mtimes place the
  `*_phase_folded.png` pair (15:12) between the raw-light-curve figures (15:04–15:05) and the
  ephemeris-fold/fit figures (16:43) — consistent with an **earlier iteration of the fold step**
  (full-phase fold, no transit marker) that was later replaced by the ±6 h ephemeris fold.
  The generating code no longer exists in the repo, so exact pixel reproduction is not claimed.
- Determination: keep the originals (untouched — sha256-verified against the pre-Phase-2 state),
  and make the content reproducible going forward via new `scripts/plot_full_phase_fold.py`
  (verified: regenerates content-equivalent full-phase folds from the current CSVs; supports the
  `quality_masked` variant and an optional output dir).
- Full disclosure: while testing, one invocation wrote into `reports/figures/` and replaced the two
  orphan PNGs; they were **restored immediately from the byte-exact backup** and re-verified
  (sha256 OK). No other original figure was touched at any point (all 8 hash-verified at phase end).

## 7. Files changed in Phase 2

| File | Change |
|---|---|
| `scripts/apply_quality_mask.py` | NEW — offline quality-mask step + validation + metadata writer |
| `scripts/plot_full_phase_fold.py` | NEW — reproducible generator for the full-phase fold figures |
| `scripts/assess_transit.py`, `transit_control_test.py` | + optional dataset-variant arg; CWD-relative `data/` path fixed to repo-relative |
| `scripts/phase_fold.py`, `fit_transit_model.py` | + optional dataset-variant arg (CSV and figure names) |
| `data/processed/*_quality_masked.csv` | NEW derived datasets (originals untouched) |
| `reports/dataset_metadata.json` | NEW — machine-readable provenance, policy, row accounting, validation |
| `reports/phase2_data_integrity.md` | THIS report |
| `reports/figures/*_quality_masked_transit_fit.png` | NEW figures from the masked-data fit |

**Nothing deleted; no original data, figure, or script behavior changed by default.**

## 8. Verification at phase end

- `ruff format --check .` + `ruff check .` → green.
- All 8 pre-existing figures byte-identical to pre-Phase-2 hashes.
- Original CSVs unmodified (mtimes + content).
- Regression: default runs reproduce Phase 1 numbers exactly (§3).
- `pytest`: still 0 tests (suite is Phase 6 scope — no tests existed to break).

## 9. Open items / decisions needed

1. **Download approval:** all 15 Kepler long-cadence quarters (~20–40 MB estimated)? Add any TESS
   sectors beyond S14 (each 2-min SPOC sector is larger, order tens of MB)? Or stay offline-only for now?
2. Replace the orphan `*_phase_folded.png` originals with the reproducible generator's output
   (content-equivalent), or keep both side by side?
3. OK to commit the Phase 2 changes (the §7 list) as the next commit?

**Uncertainties carried forward:** archive P solutions scatter ~1×10⁻⁶ d (phase-drift test needed in
Phase 3); quality-bit names intentionally referenced to official manuals rather than transcribed;
TESS masked-vs-original flux epsilon (6×10⁻⁸) is a numerics artifact, documented in metadata.
