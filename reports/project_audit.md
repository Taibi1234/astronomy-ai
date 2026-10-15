# Project Audit — astronomy-ai

**Date:** 2025-10-15
**Auditor:** Kimi Code (automated audit pass, Phase 1)
**Scope:** repository state, environment, scripts, data, figures, reproducibility
**Status:** Phase 1 complete — awaiting user review before Phase 2

---

## 1. Current project state

### Repository layout

```
astronomy-ai/
├── .git/                  # initialized, but ZERO commits; everything untracked
├── .venv/                 # Python 3.11.17 virtual environment (gitignored)
├── data/
│   ├── raw/mast_cache/    # 2 downloaded FITS light curves (~2 MB, gitignored)
│   └── processed/         # 2 derived CSVs (~692 KB, gitignored)
├── reports/figures/       # 8 PNG figures (untracked, NOT gitignored)
├── scripts/               # 6 Python scripts (see §3)
├── src/astronomy_ai/      # EMPTY — package skeleton never started
├── tests/                 # EMPTY — no test suite
├── .gitignore             # reasonable: venvs, caches, data, .env
├── pyproject.toml         # ruff linter config only (added during this audit session)
├── requirements-lock.txt  # 76 pinned packages
└── README.md              # MISSING
```

### Git state

- Branch `main`, **no commits exist yet**. All files are untracked.
- Nothing has been lost or overwritten during the audit. Figures were regenerated once
  (to test reproducibility) and came out **byte-identical** to the originals; a backup copy
  still exists in the system temp folder as a precaution.

### Environment (verified by running commands)

| Item | Value |
|---|---|
| Python | 3.11.17 (`.venv`) |
| Key packages | lightkurve 2.6.0, astropy 8.0.1, astroquery 0.4.11, batman-package 2.5.3, numpy 2.4.6, pandas 2.3.3, scipy 1.17.1, matplotlib 3.11.2, pytest 9.1.1 |
| pytest | **0 tests collected** — no test suite exists |
| ruff | 0.17.0 (installed globally during this session for code-quality gating) |

PowerShell equivalents used throughout this audit:

```powershell
.\.venv\Scripts\python.exe -m pip list --format=freeze
.\.venv\Scripts\python.exe -m pytest
```

---

## 2. Data inventory (verified against files, not filenames)

### Kepler — `data/processed/kepler_kepler_10.csv`

- 469 rows; `time` (float64) spans **120.539147–130.245395** days; strictly increasing; no NaN/inf; no duplicates.
- Median cadence **29.4 min** (long cadence ✓).
- Provenance (read from FITS header): `kplr011904151-2009131105131_llc.fits`, **OBJECT = KIC 11904151**,
  **QUARTER = 0** (commissioning, only 9.7 days — the script downloads only `products[0]`,
  so this is a *short commissioning segment*, not a full quarter), OBSMODE = long cadence,
  TIMESYS = TDB, **BJDREFI = 2454833**, 476 rows in FITS of which **37 have SAP_QUALITY ≠ 0**.
- ⚠️ The script drops only NaN rows (7 rows); it does **not** apply the SAP_QUALITY mask, so
  quality-flagged points with finite flux remain in the CSV.

### TESS — `data/processed/tess_kepler_10.csv`

- 17,722 rows; `time` spans **1683.355718–1710.205631** days; strictly increasing; no NaN/inf; no duplicates.
- Median cadence **2.0 min** ✓.
- Provenance: `tess2019198215352-s0014-..._lc.fits`, **OBJECT = TIC 377780790**, **SECTOR = 14**,
  SPOC pipeline 5.0.96, TIMESYS = TDB, **BJDREFI = 2457000**, 19,337 rows in FITS of which
  **1,615 have QUALITY ≠ 0** (not masked in the CSV either).
- Visual inspection of the raw figure shows orbit gaps and scattered outliers up to +0.8%.

### Target identity — VERIFIED ✓

KIC 11904151 = TIC 377780790, both at RA 285.6794°, Dec +50.2413° — consistent across missions and
consistent with Kepler-10. The FITS time-system keywords (BJDREFI/TIMESYS=TDB) **confirm the hardcoded
offsets** `2454833.0` (Kepler) and `2457000.0` (TESS) used by every script.

**Context fact:** Kepler-10 b is a *known, published* transiting planet (Batalha et al. 2011).
This project is therefore a **re-detection / pipeline-validation exercise, not a discovery** —
the README and reports must say this explicitly.

---

## 3. Scripts (all inspected in full)

| Script | Role | Writes files? | Runs offline? |
|---|---|---|---|
| `prepare_lightcurves.py` | lightkurve search+download, `remove_nans().normalize()`, CSV + raw figure | yes (CSV, figure) | no (network) |
| `phase_fold.py` | ephemeris fold, ±6 h figure | yes | yes |
| `assess_transit.py` | box-model depth vs median baseline, RSS reduction (stdout only) | no | yes |
| `transit_control_test.py` | box fits at 31 center offsets + 26 control phases, control fraction (stdout only) | no | yes |
| `fit_transit_model.py` | batman-package physical model fit, 4 free params, figure + stdout | yes | yes |
| `smoke_test_data.py` | network smoke test: downloads 1 product each for Kepler-10 / TOI-700 | cache only | no |

Common duplication: the ephemeris (`P = 0.837491225 d`, `T0 = 2454964.575 BJD`) and BJDREF table are
copy-pasted into 4 scripts. Comment cites "NASA Exoplanet Archive, Q1–Q17 DR25" — **not yet independently
verified** against the archive (flagged for Phase 2).

### Measured behavior this audit (actual command output)

```powershell
.\.venv\Scripts\python.exe scripts\assess_transit.py
```

```
KEPLER:  288 pts in ±6 h | box depth 209.1 ppm | RSS reduction 18.40%
TESS:    10,520 pts in ±6 h | box depth 205.0 ppm | RSS reduction 0.30%
```

```powershell
.\.venv\Scripts\python.exe scripts\transit_control_test.py
```

```
KEPLER:  predicted-center depth 209.1 ppm | best offset -2.0 min | RSS impr. 14.473%
         26 control phases, 0.0% matched/exceeded improvement
TESS:    predicted-center depth 205.0 ppm | best offset +0.0 min | RSS impr. 0.287%
         26 control phases, 0.0% matched/exceeded improvement
```

```powershell
.\.venv\Scripts\python.exe scripts\fit_transit_model.py
```

```
KEPLER:  Rp/R* = 0.013627 | depth ≈ 185.7 ppm | TTV offset -1.73 min | RSS improvement 16.893%
TESS:    Rp/R* = 0.014050 | depth ≈ 197.4 ppm | TTV offset -0.21 min | RSS improvement 0.294%
```

**The user's quoted preliminary numbers reproduce exactly** — they come from `fit_transit_model.py`
(linear-baseline null model), not from `assess_transit.py` (constant-baseline box model; note the
different Kepler RSS figure, 18.40% vs 16.893%). Both are descriptive fit-quality metrics, **not
detection significances**.

Also reproduced byte-identical: `phase_fold.py` and `fit_transit_model.py` figures (sha256 match).

### Cosmetic bug (not a correctness bug)

`phase_fold.py` prints "Predicted epoch in mission-relative days: **-2035.425000**" for TESS.
The value is *negative because TESS's BJDREF (2457000) is later than the epoch (2454964.575)*;
Python's modulo handles it and the fold itself is correct (confirmed by the control/fit results above).
Still worth clarifying the printout to avoid alarming readers.

---

## 4. Figure inspection (viewed, not assumed)

| Figure | Observation |
|---|---|
| `kepler_kepler_10.png` | Raw Q0 light curve has a **smooth ±5×10⁻⁴ trend over 9.7 d — ~2.5× the ~2×10⁻⁴ transit depth**. Detrending choices will dominate the result. X-axis label "mission time units" is vague (should be "BKJD − 2454833, days"). |
| `tess_kepler_10.png` | Obvious orbit gaps; σ ≈ 10⁻³ per 2-min point; outliers to +8×10⁻³; slow baseline wander. |
| `kepler_kepler_10_ephemeris_folded.png` | A few points dip to −2…−4×10⁻⁴ near phase 0; very sparse in-transit sampling (29-min cadence ⇒ ~3–4 points per transit). Suggestive, not conclusive by eye. |
| `tess_kepler_10_ephemeris_folded.png` | No visible dip at phase 0 at plot scale. |
| `kepler_kepler_10_transit_fit.png` | batman model dip visible, centered ~−2 min from predicted center; data noise comparable to depth. |
| `tess_kepler_10_transit_fit.png` | Fitted model essentially flat (depth consistent with ~0). |
| `kepler_kepler_10_phase_folded.png`, `tess_kepler_10_phase_folded.png` | ⚠️ **ORPHANS** — no script in the repo currently generates `*_phase_folded.png` files. Stale artifacts from an earlier script version. Decide: delete or re-home a generator. |

---

## 5. Engineering issues found

1. **No tests at all** (`pytest` → 0 collected). Phase 6 must add them.
2. **`requirements-lock.txt` is incomplete**: `batman-package` (direct import in `fit_transit_model.py`)
   and `aiobotocore` (transitive via s3fs) are installed but missing from the lock. Fresh environment
   from the lock file **cannot run the transit fit**.
3. **No README**, no docs, no usage instructions.
4. **No git history** — everything untracked; an initial commit is needed before any further work
   (so changes become reviewable). *Requires user approval per rules.*
5. Duplicated ephemeris/BJDREF constants across 4 scripts (single-source-of-truth needed).
6. `prepare_lightcurves.py` silently takes `products[0]` — search-result ordering is not stable over
   time, so "re-run later" may fetch a *different* quarter/sector. Provenance (quarter/sector/cadence)
   is not recorded anywhere machine-readable.
7. Quality flags (SAP_QUALITY / QUALITY) never applied — flagged cadences remain in the CSVs.
8. `assess_transit.py` / `transit_control_test.py` compute phase with a duplicated formula but use
   `Path("data/processed")` **relative to the shell's CWD** (breaks if run from elsewhere); the other
   scripts use `Path(__file__).resolve().parents[1]` (robust). Inconsistent.
9. `src/astronomy_ai/` and `tests/` are empty skeletons — package conversion (Phase 7) has a place to land.
10. Orphan figures (§4). `.gitignore` last line has a stray trailing `\r` (cosmetic).
11. The Kepler CSV contains only **9.7 days of Q0 commissioning data** — chosen by `products[0]`, not
    by science criteria. Phase 2 should decide deliberately which quarters/sectors to use
    (e.g. full Kepler Q1–Q17 stack for a strong portfolio result, bandwidth permitting).

## 6. Scientific issues & risks

| # | Issue | Severity | Phase |
|---|---|---|---|
| S1 | Kepler Q0 raw trend (~±5×10⁻⁴) is larger than the transit depth (~2×10⁻⁴); no detrending anywhere in the pipeline. Folded "transit" could be partially trend leakage. | **High** | 3 |
| S2 | Per-point noise treated as independent; high-cadence TESS points and folded samples are **correlated**. RSS/BIC-style statistics computed naively will overstate significance. | **High** | 4 |
| S3 | Control test uses 26 correlated control phases — the script itself prints "descriptive, not a calibrated p-value". No injection/recovery or bootstrap yet. | High | 4 |
| S4 | Ephemeris quoted from NASA Exoplanet Archive (DR25) but not re-verified from the archive in-repo. | Medium | 2 |
| S5 | TESS per-point σ ≈ 10⁻³ ≫ depth ~2×10⁻⁴; a 26.8 d stack helps, but significance must be demonstrated, not assumed. | Medium | 4 |
| S6 | Kepler in-transit sampling is ~3–4 points per transit (29-min cadence, ~1.8 h duration). Parameter errors will be prior/geometry-dominated. | Medium | 4 |
| S7 | Quality-flagged data kept (see §5.7). | Medium | 2 |
| S8 | Fixed parameters (a/R*=3.4, i=84.5°, u1,u2) are asserted "diagnostic"; sensitivity to these is untested. | Medium | 3/4 |
| S9 | Known-planet target: must be framed as re-detection/validation, never as discovery. | (framing) | 8 |

## 7. Verified baseline (what is TRUE as of this audit)

- ✔ Scripts run end-to-end offline on existing CSVs (assess, control, fold, fit).
- ✔ User's quoted fit numbers reproduce exactly from current code + data.
- ✔ Figures from `phase_fold.py` / `fit_transit_model.py` are byte-reproducible.
- ✔ Target identity and BJDREF time offsets verified against FITS headers.
- ✔ CSVs clean of NaN/inf/duplicates/monotonicity problems.
- ✘ No test suite. ✘ No README. ✘ No git history. ✘ No statistical validation beyond descriptive RSS.
- ✘ No quality masking. ✘ No detrending. ✘ No uncertainty estimates. ✘ No ML component.

## 8. Prioritized implementation plan

- **Phase 2 — Data integrity:** add validation module; apply quality masks (re-derive CSVs, keep originals);
  write machine-readable dataset metadata (JSON: mission, target, quarter/sector, cadence, BJDREF, time span,
  quality-filter counts, download command); verify ephemeris against NASA Exoplanet Archive; document
  `time` column = mission-relative days (BKJD/TJD, TDB) with FITS keywords.
- **Phase 3 — Pipeline:** single config for ephemeris/BJDREF; loaders with validation; raw/detrended/folded
  states distinguished; optional gentle detrending (documented); binned folded plots with error bars;
  residual plots; batman fit with fixed-vs-fitted parameters labeled; sensitivity grid
  (detrend on/off, window half-width, limb darkening, a/R*, inclination).
- **Phase 4 — Statistics:** null vs transit model comparison with parameter counts; BIC only with
  justification, otherwise residual/bootstrap-based assessment that respects time correlation
  (e.g., block/bootstrap over transit light curves, injection-recovery); honest significance statement;
  `reports/scientific_validation.md` from real outputs.
- **Phase 5 — ML:** genuine task is **transit injection/recovery classification** on simulated light curves
  (synthetic: inject known transits into real or simulated baselines) — defensible, lightweight, CPU-only;
  baseline = depth/SNR threshold classifier vs scikit-learn model; grouped train/test split by source
  light curve to prevent leakage; precision/recall/F1 + confusion matrix. (Curve fitting alone is NOT ML —
  the repo currently has no ML component; this extension is scientifically appropriate.)
- **Phase 6 — Quality:** move shared logic to `src/astronomy_ai/`; fix CWD-relative paths; type hints +
  docstrings; logging; deterministic seeds; unit tests (time conversion, phase fold, validation, metrics)
  + integration test on synthetic fixture; complete `requirements-lock.txt` (add batman-package);
  keep ruff gate green.
- **Phase 7 — Reproducibility:** `python -m astronomy_ai` CLI: `validate`, `analyze`, `figures`, `results`,
  `test`; separate explicit `download` step; documented output manifest.
- **Phase 8 — Docs/portfolio:** README (10 required sections), methodology doc, figure captions with units,
  results summary from measured outputs, limitations + future work, honest framing.
- **Phase 9 — Final gate:** full test run, lint, clean-shell reproduction, figure inspection, report-vs-output
  consistency, secret/path scan, `reports/final_quality_gate.md`.

## 9. Decisions needed from you before Phase 2

1. **Initial git commit** of the current state (strongly recommended — makes everything after reviewable). Approve?
2. Kepler data choice: keep the current short Q0 segment, or download a fuller Kepler data set
   (more quarters = much stronger result; needs network + disk)? Either way the raw FITS cache stays.
3. Orphan `*_phase_folded.png` figures: delete, or keep and give them a generator script?
4. Data policy: OK to regenerate the processed CSVs with quality masking (originals preserved under new names)?

---

*All numerical values above were produced by running the project's own scripts on the current data during
this audit. Nothing was estimated visually or invented.*
