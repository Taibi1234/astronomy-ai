# Reproducibility guide

How to verify astronomy-ai on Windows PowerShell, reproduce its saved analyses, and identify commands
that overwrite artifacts. See [`PIPELINE_STATUS.md`](PIPELINE_STATUS.md) for the frozen historical
Phase 5 chain and the maintained Phase 8 chain.

The original core environment was Python 3.11.17 on Windows. The publication audit also ran the core
and backend suites on Python 3.12.12 (Linux). Backend dependency pins require Python 3.12 or newer;
the frontend requires Node 22 or newer.

Run core analysis commands from the repository root. Run backend commands from `webapp/backend` so its
neighbouring `research` package and `transit_injection.py` module resolve correctly.

---

## 1. Core setup

```powershell
cd C:\path\to\astronomy-ai

# Option A — uv
uv venv --python 3.11 .venv
uv pip install --python .\.venv\Scripts\python.exe -r requirements-lock.txt

# Option B — stdlib venv
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-lock.txt
```

Sanity check:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "import numpy, pandas, scipy, astropy, batman, lightkurve, sklearn; print('imports OK')"
```

`setuptools` is intentionally pinned: batman's OpenMP helper imports `distutils`, which is not in the
Python 3.12 standard library. `batman-package==2.5.3` supplies NumPy 2.x-compatible wheels.

---

## 2. Current verification commands

### Core scientific tests

```powershell
cd C:\path\to\astronomy-ai
.\.venv\Scripts\python.exe -m pytest -q
```

`pyproject.toml` sets `testpaths = ["tests"]`, so bare pytest does not collect the argument-parsing
script `scripts/transit_control_test.py`.

Expected results:

- Public clone: **26 passed, 2 skipped**. The skips require the full 15-quarter analysis CSV, which is
  not bundled.
- With `data/processed/kepler_all_quarters_quality_masked.csv` present: **28 passed**.

The suite covers dataset invariants, parent-segment split separation, presented-flux feature
construction, train-only imputation, deterministic rebuilding, and agreement with frozen artifacts.

### Backend and research safeguards

```powershell
cd C:\path\to\astronomy-ai\webapp\backend
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Audited public-clone result: **756 passed, 28 skipped**. The tests use synthetic fixtures and temporary
directories. One test reads a designated fit-quarter file only when it exists locally; it skips on the
public clone. No test campaign, sealed-test evaluation, or real authorization is required.

### Lint

```powershell
cd C:\path\to\astronomy-ai
python -m pip install ruff==0.17.4
python -m ruff check scripts tests webapp/backend
```

Expected: `All checks passed!`

### Frontend

```powershell
cd C:\path\to\astronomy-ai\webapp\frontend
npm ci
npm run lint
npm run build
```

Use Node 22 or newer. The audited build passed; oxlint reported no errors and one non-blocking
`react(set-state-in-effect)` warning. There is no frontend unit-test suite.

GitHub Actions runs the core, backend, lint, and frontend jobs from `.github/workflows/ci.yml`.

---

## 3. Offline report-level reproduction

These commands need committed report artifacts but no network or raw FITS cache:

```powershell
cd C:\path\to\astronomy-ai
.\.venv\Scripts\python.exe scripts\phase5_features.py
.\.venv\Scripts\python.exe scripts\phase5_baseline.py
.\.venv\Scripts\python.exe scripts\phase4_model_comparison.py
```

They write:

| Command | Outputs |
|---|---|
| `phase5_features.py` | `reports/phase5_features.csv`, `phase5_feature_config.json` |
| `phase5_baseline.py` | `reports/phase5_results.json`, `phase5_results.md` |
| `phase4_model_comparison.py` | `reports/results/phase4_model_comparison.json` |

The Phase 6 isolated-copy check reproduced all five outputs byte-identically. Back up `reports/` before
re-running if you want to preserve the current files.

`phase5_features.py` reports 9 undefined `matched_filter_corr` values among 26 windows. The historical
feature CSV substitutes the median (0.843895); the maintained Phase 8 pipeline fits imputation on the
training split only. This is documented behavior, not a test failure.

---

## 4. Full offline re-fits overwrite scientific outputs

These commands require the analysis-ready CSVs listed in §5 and write into `reports/results/` and
`reports/figures/`:

```powershell
Copy-Item reports reports_backup -Recurse

.\.venv\Scripts\python.exe scripts\transit_analysis.py
.\.venv\Scripts\python.exe scripts\phase4_residual_diagnostics.py
.\.venv\Scripts\python.exe scripts\phase4_block_bootstrap.py
.\.venv\Scripts\python.exe scripts\phase4_injection_recovery.py
```

The Phase 6 isolated-copy run reproduced the ten Phase 3 figures and both Phase 4 JSON files
byte-identically. `phase3_transit_analysis.json` differed only in its embedded `generated_at_utc`.
Expected headline values:

| Output | Value |
|---|---|
| Full-baseline detrended Kepler depth | 153.8 ppm |
| Timing offset | +0.03 min |
| Points in ±6 h window | 27,111 |
| Block 200 / 500 bootstrap 95% intervals | [151.2, 158.2] / [150.4, 157.7] ppm |
| 154 ppm injection recovery | 154.8 ± 3.2 ppm |
| Zero-depth control | +2.7 ± 2.0 ppm |

Treat any other scientific-value difference as a finding to investigate, not as random noise.

---

## 5. Data availability and network boundaries

### Bundled demo data

Two finite-filtered demo files are intentionally tracked and are sufficient for the web viewer:

| File | Rows | Coverage |
|---|---:|---|
| `data/processed/kepler_kepler_10.csv` | 469 | Kepler Q0, finite-filtered; not quality-masked |
| `data/processed/tess_kepler_10.csv` | 17,722 | TESS S14, finite-filtered |

Their provenance and SHA-256 values are in root README §12 and `reports/dataset_metadata.json`.

### Analysis data not bundled

The following remain gitignored:

```text
data/processed/kepler_all_quarters_quality_masked.csv       45,514 rows
data/processed/kepler_kepler_10_quality_masked.csv             439 rows
data/processed/tess_kepler_10_quality_masked.csv              local analysis variant
data/processed/kepler_q00..q17_quality_masked.csv          15 quarter files
```

A public clone can run the report-level commands in §3 and the viewer, but cannot re-fit the full
15-quarter analysis until these inputs are re-derived.

### Raw FITS cache required

```powershell
.\.venv\Scripts\python.exe scripts\apply_quality_mask.py
.\.venv\Scripts\python.exe scripts\prepare_kepler_quarters.py
```

These read `data/raw/mast_cache/*.fits`, which is gitignored.

### Live MAST access required

```powershell
.\.venv\Scripts\python.exe scripts\download_kepler_quarters.py
.\.venv\Scripts\python.exe scripts\download_tess_sectors.py
.\.venv\Scripts\python.exe scripts\prepare_lightcurves.py
.\.venv\Scripts\python.exe scripts\smoke_test_data.py
```

These are not CI steps. `prepare_lightcurves.py` overwrites the two bundled demo CSVs and their figures;
verify their documented hashes afterwards. Do not run downloads merely to make the test suite pass.

---

## 6. Maintained and superseded scripts

| Script | Current status |
|---|---|
| `scripts/phase5_build_dataset.py` | Frozen historical chain; corrected in Phase 8 and reproduces the frozen dataset byte-for-byte |
| `scripts/phase8_*.py` | Maintained synthetic-ML chain for new work |
| `scripts/statistical_validation.py` | Superseded prototype; unimplemented helpers fail fast with `NotImplementedError` |
| `scripts/injection_recovery.py` | Superseded by `phase4_injection_recovery.py`; retained for provenance |
| `scripts/transit_control_test.py` | Analysis script, not a pytest module; root `testpaths` prevents accidental collection |

No known documentation status changes the Phase 3/4 results or authorizes a real Phase 11 campaign.

---

## 7. Hash verification

```powershell
Get-ChildItem reports\results\*.json, reports\phase5_*.json, reports\phase5_*.csv |
  Get-FileHash -Algorithm SHA256 |
  Format-Table Hash, Path -AutoSize
```

Bash/Git-Bash equivalent:

```bash
sha256sum reports/results/*.json reports/phase5_dataset.json reports/phase5_features.csv
```

Some Phase 3/4 JSON files embed `generated_at_utc`; compare scientific values as well as file hashes.
Frozen Phase 11 JSON files are intentionally marked `-text -diff` in `.gitattributes` so line-ending
conversion cannot silently change their bytes. Do not reformat or regenerate them for a documentation
or CI change.

---

## 8. Phase 11 boundary

The repository contains guarded research code, frozen protocol inputs, and historical synthetic smoke
fixtures. The authoritative state remains `campaign_ready = false`, `execution_ready = false`, with a
`descriptive_only` scientific ceiling. Issuer authenticity (H3) is unresolved.

Reproduction work must not create authorization documents, generate real trials, fit real campaign
data, access sealed test quarters, or evaluate a real campaign. See
`reports/phase11_final_hardening_report.md` for the safeguards and owner decision.
