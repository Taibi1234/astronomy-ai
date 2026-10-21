# Reproducibility guide

How to verify and re-run the astronomy-ai analyses on Windows PowerShell, and what each command
actually writes. Every command here was executed during Phase 6 unless marked otherwise.

See [`PIPELINE_STATUS.md`](PIPELINE_STATUS.md) for the two ML pipeline generations: the **historical**
chain (`scripts/phase5_*`), frozen because it produced the audited artifacts, and the **maintained** chain
(`scripts/phase8_*`) for new work. That page also lists which artifacts must not be regenerated in place.

- Environment verified: **Python 3.11.17** in `.venv`, `uv 0.12.23`, 80 packages installed.
- Working directory matters: `tests/` and the Phase 5 scripts resolve `reports/...` **relative to the
  current directory**, so run everything from the repository root.
  (`transit_analysis.py` and the Phase 4 scripts use paths resolved from `__file__` and are safe
  anywhere, but the recommended convention is the repo root.)

---

## 1. One-time setup

```powershell
cd C:\path\to\astronomy-ai

# Option A — uv (how this environment was created)
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

---

## 2. Test invocation (and why `pytest` alone fails)

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v
```

Actually observed (Phase 8, after the builder correction and the Phase 8 pipeline tests):

```
collected 28 items
28 passed in 7.06s        (exit code 0)
```

In a fresh clone the two data-dependent tests are skipped rather than failed (measured: `26 passed,
2 skipped`), because the analysis-ready CSV is gitignored. Both skip reasons name the missing file.

The suite runs from any working directory. `tests/test_phase5_leakage.py` holds the dataset invariants
(labels, segment separation, schema, NaN imputation, split sizes); `tests/test_phase5_builder.py` holds
the builder guards plus an integration test that regenerates the dataset in an isolated copy and compares
it to the frozen artifact; `tests/test_phase8_pipeline.py` holds the presented-flux, no-label, single-path,
split-separation, train-only-imputation and determinism checks.

`test_saved_dataset_matches_repaired_builder` now passes: since the Phase 8 correction,
`scripts/phase5_build_dataset.py` computes features from the presented flux and reproduces
`reports/phase5_dataset.json` byte-for-byte (`f8ad47fb…`). It is a regression guard against the script and
the artifact drifting apart again.

```powershell
# Fails — do not run at the repository root:
# .\.venv\Scripts\python.exe -m pytest
```

Why it fails (observed):

```
ERROR scripts/transit_control_test.py - FileNotFoundError:
  ...\data\processed\kepler_kepler_10_-q.csv
```

pytest's default patterns include `*_test.py`, so `scripts/transit_control_test.py` is imported as a
test module. That script reads `sys.argv[1]` at import time and appends it to a filename (here `-q`),
so collection dies. Fixing this requires a `testpaths = ["tests"]` entry in `pyproject.toml` — **still
not applied**: that file is protected tooling config in this harness, so the two-line change is left to
the repository owner.

---

## 3. Offline reproduction — verified byte-identical

These commands need no network and no FITS files, only committed artifacts. Verified in Phase 6 by
running them in a throwaway copy of the repository and comparing SHA-256 hashes against the committed
outputs: **all five outputs matched byte-for-byte.**

```powershell
.\.venv\Scripts\python.exe scripts\phase5_features.py
#   reads  reports/phase5_dataset.json
#   writes reports/phase5_features.csv, reports/phase5_feature_config.json
#   expected: "Features extracted: 26 rows", "Positive: 13 / Negative: 13"

.\.venv\Scripts\python.exe scripts\phase5_baseline.py
#   reads  reports/phase5_features.csv, reports/phase5_feature_config.json
#   writes reports/phase5_results.md, reports/phase5_results.json
#   expected: train=13 val=6 test=7; threshold 0.441; Baseline F1=0.750 (dummy=0.571);
#             "RandomForest NOT selected"; rf_selected=False

.\.venv\Scripts\python.exe scripts\phase4_model_comparison.py
#   reads  reports/results/phase3_transit_analysis.json, phase4_block_bootstrap.json,
#          phase4_injection_recovery.json
#   writes reports/results/phase4_model_comparison.json
#   expected: reference depth 153.8 ppm; naive delta BIC -2195.58; AC=0.936 warning printed
```

`phase5_features.py` prints a NaN notice: 9 of 26 windows have an undefined `matched_filter_corr`
(degenerate window flux) and the CSV substitutes the median (0.843895). The dataset JSON keeps the
raw NaN. This is documented behaviour, not a failure. (The Phase 5 audit reported 5; the measured count
is 9 — corrected in Phase 7.)

---

## 4. Offline re-fits — slow, and they overwrite committed outputs

```powershell
Copy-Item reports reports_backup -Recurse     # optional but recommended

.\.venv\Scripts\python.exe scripts\transit_analysis.py            # Phase 3
.\.venv\Scripts\python.exe scripts\phase4_residual_diagnostics.py # Phase 4 diagnostics (stdout only)
.\.venv\Scripts\python.exe scripts\phase4_block_bootstrap.py      # Phase 4 bootstrap
.\.venv\Scripts\python.exe scripts\phase4_injection_recovery.py   # Phase 4 injection/recovery
```

These read `data/processed/*.csv` and write `reports/results/*.json` plus `reports/figures/phase3_*.png`.
Measured on this machine (Python 3.11.17, CPU): `transit_analysis.py` ~17 s,
`phase4_block_bootstrap.py` ~3.6 min (1000 refits), `phase4_injection_recovery.py` ~1.5 min (350 refits).

All three were run in an isolated copy during Phase 6: the 10 Phase 3 figures and both Phase 4 JSONs came
out **byte-identical**, and `phase3_transit_analysis.json` matched in every value except its embedded
`generated_at_utc`. Expected headline values, unchanged by re-running:

| Output | Value |
|---|---|
| `phase3_transit_analysis.json` — kepler_all_masked/detrended depth | 153.8 ppm |
| — timing offset | +0.03 min |
| — points in ±6 h window | 27,111 |
| `phase4_block_bootstrap.json` — block 200, 95% interval | [151.2, 158.2] ppm |
| — block 500, 95% interval | [150.4, 157.7] ppm |
| `phase4_injection_recovery.json` — 154 ppm recovered | 154.8 ± 3.2 ppm |
| — 0 ppm control | +2.7 ± 2.0 ppm |

If a regenerated JSON differs from `reports/results/` beyond an embedded timestamp, treat that as a
finding, not noise.

---

## 5. Not reproducible offline

### Requires the raw FITS cache (gitignored)

```powershell
.\.venv\Scripts\python.exe scripts\apply_quality_mask.py          # -> Phase 2 CSVs
.\.venv\Scripts\python.exe scripts\prepare_kepler_quarters.py     # -> 15 quarter CSVs + combined
```

Both read `data/raw/mast_cache/*.fits`. That directory is gitignored, so a clean clone cannot run them.

### Requires network access to MAST

```powershell
.\.venv\Scripts\python.exe scripts\download_kepler_quarters.py    # 15 Kepler quarters, ~5.9 MB
.\.venv\Scripts\python.exe scripts\download_tess_sectors.py       # TESS S40/S53/S74 (~5.8 MB)
.\.venv\Scripts\python.exe scripts\prepare_lightcurves.py         # original Phase 1 download path
.\.venv\Scripts\python.exe scripts\smoke_test_data.py             # MAST availability probe
```

Not executed in Phase 6: the phase explicitly forbids new downloads and network dependencies. Whether
MAST is reachable today is unverified. `download_tess_sectors.py` is expected to fail for S40/S53/S74
(they were unavailable in Phase 4 as well); it does not substitute other sectors.

### Requires the analysis-ready CSVs (gitignored)

Everything else in `scripts/` reads `data/processed/*.csv`:

```
data/processed/kepler_all_quarters_quality_masked.csv      45,514 rows  (~4.0 yr, 29.4 min cadence)
data/processed/kepler_kepler_10.csv                           469 rows  (Q0 original)
data/processed/kepler_kepler_10_quality_masked.csv            439 rows  (Q0 masked)
data/processed/tess_kepler_10.csv                          19,337 rows  (S14 original)
data/processed/tess_kepler_10_quality_masked.csv           17,722 rows  (S14 masked)
data/processed/kepler_q00..q17_quality_masked.csv      15 per-quarter files
```

Because `.gitignore` excludes `data/processed/*`, **a public clone contains no science data**. Two
options, both requiring a decision from the project owner:

1. Re-derive it: run the download scripts, then `apply_quality_mask.py` / `prepare_kepler_quarters.py`.
2. Ship the CSVs: remove the `data/processed/*` ignore rule (combined CSV is ~1.7 MB; the full directory
   is ~4.8 MB) and commit them.

Option 2 has not been applied — it changes repository content beyond documentation.

---

## 6. Scripts with known defects

| Script | Symptom | Status after Phase 7 |
|---|---|---|
| `scripts/phase5_build_dataset.py` | `IndentationError` at line 51 (fixed in Phase 7); features computed pre-injection (fixed in Phase 8) | **Corrected.** Dedented in Phase 7; feature source switched to the presented flux in Phase 8. It now reproduces `reports/phase5_dataset.json` byte-for-byte and is guarded by `test_saved_dataset_matches_repaired_builder`. |
| `scripts/statistical_validation.py` | `NameError` for `moving_block_resid`, `stratified_block_resid` (never defined) | **Unchanged.** Incomplete proto-Phase-4 prototype superseded by `phase4_*.py`; no outputs exist anywhere, so nothing depends on it. |
| `scripts/injection_recovery.py` | Reads `reports/results/phase4_statistical_validation.json`, which does not exist | Unchanged; superseded by `phase4_injection_recovery.py`; kept for provenance |
| `scripts/transit_control_test.py` | Parses `sys.argv` at import; breaks root-level pytest collection | Unchanged; harmless when pytest is scoped to `tests` |

None of these affect the committed Phase 3/4 results. Full detail in
`reports/phase7_reliability_audit.md`.

---

## 7. Lint

```powershell
ruff check scripts tests
```

Observed (ruff 0.17.0, installed outside `.venv` — it is **not** a dependency of this project; the
binary need not be on the default `PATH`):

```
All checks passed!
```

The 75 findings that existed at the end of the publication audit were fixed: 16 safe autofixes (import
splitting, sorting, removal of genuinely unused imports, one `len()` truthiness), 41 long lines wrapped by
splitting string literals into adjacent literals, 13 `# noqa: E402` where imports must follow `sys.path`
setup, and 4 `# noqa: F821` on the calls to the never-defined helpers in `statistical_validation.py`
(inventing those helpers would be a new statistical implementation, not a lint fix).

Every string value, and therefore every written artifact, was verified unchanged: `ast.dump` of each
edited module is identical to its pre-fix form apart from the removed unused imports, and re-running all
eight artifact-producing scripts reproduces the committed outputs byte-for-byte.

---

## 8. Hash verification recipe

To confirm that a re-run did not silently change the science:

```powershell
Get-ChildItem reports\results\*.json, reports\phase5_*.json, reports\phase5_*.csv |
  Get-FileHash -Algorithm SHA256 |
  Format-Table Hash, Path -AutoSize
```

Bash/Git-Bash equivalent:

```bash
sha256sum reports/results/*.json reports/phase5_dataset.json reports/phase5_features.csv
```

Note that `reports/phase3_transit_analysis.json` and the Phase 4 JSONs embed a `generated_at_utc`
timestamp, so a full re-run changes the file hash even when every scientific value is identical.
Compare the values, not only the hash, for those files.

`reports/phase5_results.md` is UTF-8 as of Phase 7 (it was Windows-1252; only the encoding changed —
CRLF, wording and numbers are byte-identical after decoding). Its SHA-256 therefore differs from the
Phase 5/6 record: `8443a7b5…d3d04` instead of `3387b8ee…aefd6`. That is the only intentional artifact
content change between Phase 6 and Phase 7.
