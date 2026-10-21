# Phase 6 — Portfolio Readiness and Reproducibility

**Date:** 2026-10-21 (session date) · **Scope:** documentation, dependency documentation, verification
**Status:** complete — awaiting review. No commit, no push, no scientific change.

Phase 5 passed its audit and is frozen. Phase 6 makes the existing project legible to an admissions
committee or technical reviewer, and verifies — rather than assumes — what can be reproduced. Every
number in this report was measured during the phase.

---

## 1. Constraints observed

| Constraint | How it was respected |
|---|---|
| No change to analysis, algorithm, parameters, labels, splits, thresholds, results | No file under `scripts/` was modified; Phase 3/4/5 outputs hash-identical before/after (§5) |
| Do not overwrite Phase 3/4/5 outputs | Full re-fits were run in a throwaway copy at `/tmp/phase6_check`, never in the repository |
| No new datasets, no network dependencies | No download script was executed; no package installed or upgraded |
| No commit or push | `git add`/`commit`/`push` never invoked |
| Defects documented, not fixed | Three runnable-code defects recorded in §9 and left untouched pending approval |

---

## 2. Audit findings

### 2.1 Repository state

- **No `README.md`, no `docs/`** existed. `requirements-lock.txt` had 76 pins. `pyproject.toml` holds
  only `[tool.ruff]` configuration — it has **no `[project]`, no build system, no pytest section**.
  `src/astronomy_ai/` is an empty directory; nothing is installable. Scripts are executed as files and
  rely on `sys.path` insertion or `__file__`-relative roots.
- **Git tracks Phase 1–2 only** (29 files). Everything from Phase 3 onward — 12 scripts, `tests/`,
  12 reports, 4 result JSONs, 10 figures — is **untracked**. The working tree is complete; the history
  is not. Committing is a decision for the owner, not part of this phase.
- `HOME/` (an untracked Claude/omniroute tooling cache) sits in the project root and is not covered by
  `.gitignore`.
- `.gitignore` excludes `data/raw/*` and `data/processed/*`. Consequence: **a public clone contains no
  science data** and cannot run the pipeline end to end.

### 2.2 Dependencies — one real gap

Installed packages were diffed against the lock file programmatically
(`pip list --format=freeze` vs. `requirements-lock.txt`):

```
installed packages: 80 | locked: 76
MISSING FROM LOCK: ['batman-package', 'pip', 'setuptools', 'wheel']
IN LOCK NOT INSTALLED: []
```

- **`batman-package==2.5.3` was genuinely missing**, yet `batman` is imported by
  `fit_transit_model.py`, `statistical_validation.py`, `transit_analysis.py`, and used indirectly by all
  Phase 4/5 scripts. A fresh environment built from the lock file could not run the transit fit — i.e.
  could not reproduce any Phase 3–5 result. **Corrected** by adding the exact installed version pin
  (see §4). This is a documentation correction, not an upgrade: no version changed, nothing installed.
- `pip`, `setuptools`, `wheel` are environment tooling, not analysis dependencies. **Deliberately not
  added.**
- Verified `requires_python` for the pinned stack: `numpy`, `astropy`, `scipy`, `scikit-learn` all
  require `>=3.11`, so the documented target is **Python 3.11** (verified 3.11.17). `batman-package`
  declares no `requires_python`; the installed build came from a `cp311-cp311-win_amd64` wheel, so
  Windows + 3.11 needs no local C compiler.

### 2.3 Scripts — three defects found

| Script | Defect | Impact |
|---|---|---|
| `phase5_build_dataset.py` | `IndentationError: unexpected indent` at line 51. Lines 51–104 are over-indented by 4 spaces, so the module body never parses. Confirmed with `python -m py_compile scripts/*.py` and `ruff` (`invalid-syntax`). | The Phase 5 dataset **cannot be regenerated** from the committed script, although the JSON records `"generated_by": "scripts/phase5_build_dataset.py"`. Saved dataset is intact and was audited in Phase 5. |
| `statistical_validation.py` | 4 × `F821 undefined name`: `moving_block_resid`, `stratified_block_resid` are called but never defined. Imports fine; would raise `NameError` on use. | Superseded by the `phase4_*.py` scripts. Its intended outputs (`reports/results/phase4_statistical_validation.json`, `phase4_residual_diagnostics.png`, `phase4_bootstrap.png`, `phase4_model_comparison.png`) are absent — consistent with it never having completed. |
| `transit_control_test.py` | Reads `sys.argv` at import time; filename matches pytest's `*_test.py` pattern. | `pytest` at the repository root aborts collection (`FileNotFoundError: ...kepler_kepler_10_-q.csv`). `pytest tests\` is unaffected. |

`injection_recovery.py` is not broken but is not runnable: it reads
`reports/results/phase4_statistical_validation.json`, which does not exist. Superseded by
`phase4_injection_recovery.py`; kept for provenance.

### 2.4 Tests

`tests/test_phase5_leakage.py` is **not a pytest suite** — it has no `test_*` functions and performs its
seven checks as module-level asserts at import time. `pytest tests\` therefore reports
`collected 0 items` / `no tests ran`, exit code 0, while the assertions do execute during collection
(a failure would surface as a collection error). No test covers time conversion, phase folding, the
transit fit, or the statistics.

### 2.5 Figures and reports

- 19 figures present. Phase 3's 10 `phase3_*.png` files are current. The 9 Phase 1 figures remain as
  provenance; `reports/project_audit.md` §4 already records that some were produced by a script that no
  longer exists and are only content-reproducible via `plot_full_phase_fold.py`.
- Phase 4's report §7 correctly states the diagnostics figure was never produced.
- **`reports/phase5_results.md` is Windows-1252, not UTF-8** (`file` reports "Non-ISO extended-ASCII";
  the cause is a single em dash, byte `0x97`). It cannot be read by UTF-8-only tooling. Content was read
  via `iconv -f CP1252` for this audit and is restated in README §3. The file was **not** converted, to
  avoid touching a frozen Phase 5 artifact.
- All other reports and JSONs are UTF-8.

### 2.6 Lint

```
ruff check scripts tests   ->  Found 114 errors.
    65 E501 (line too long), 13 I001 (import order), 10 E401, 8 E402,
    6 F401 (unused import), 4 F821 (statistical_validation.py),
    3 E702, 2 F541, 1 invalid-syntax (phase5_build_dataset.py), PLC1802, B007
ruff check <8 tracked scripts>  ->  All checks passed!
```

`ruff` is not a project dependency (0.17.0 at `C:\Users\5CA\.local\bin\ruff.exe`). `ruff check .`
reports 3,190 findings because it walks the untracked `HOME/` cache — a misleading number; the scoped
figure above is the meaningful one.

---

## 3. Documentation delivered

### `README.md` (new, root)

Written for a reviewer who has not seen the prior phases. Sections:

1. **Why Kepler-10 b is the validation target** — five concrete reasons (ground truth from RV
   confirmation, published precise ephemeris, shallow 150 ppm signal, two missions, ~4-year baseline).
2. **Scientific workflow** — ASCII stage diagram plus a paragraph per stage: acquisition → quality
   masking → folding/detrending → `batman` fit with labelled fixed parameters → block bootstrap /
   injection-recovery / warned ΔBIC → synthetic-only ML.
3. **Results** — the actual measured tables: 153.8 ppm, bootstrap intervals, geometry range,
   injection recovery, control bias, ΔBIC, and all ML metrics including `n_test = 7`.
4. **Limitations** — eight numbered items covering correlated noise (AC ≈ 0.93, `std/√n` underestimation),
   fixed-geometry dominance (146–162 ppm > the bootstrap interval), conditional uncertainty,
   approximated long-range correlation, `n_test = 7` instability, synthetic-only labels plus the
   median-imputed `matched_filter_corr`, partial TESS coverage, and the absence of any significance claim.
5. **Re-detection vs. discovery** — an explicit two-column comparison of what each requires; states that
   this repo's useful outputs (a 17% baseline-driven depth shift, a +2.7 ppm noise-floor bias, an unusable
   ΔBIC) are exactly the numbers a discovery claim could not publish.
6. Repository layout, with the empty package skeleton and `pyproject.toml`'s true role called out.
7. **Windows PowerShell setup** — two verified options (uv, and stdlib `venv` pinned to 3.11), a
   verification block (`pip check`, import smoke test), and the `batman-package` wheel note.
8. **Tests and reproduction** — the correct test invocation, the expected `0 items` output and why, the
   explicit warning against root-level `pytest`, three offline commands, three slow re-fit commands with
   an overwrite warning, and a table of what needs FITS/CSVs/network.
9. **Known issues** — ten items, including all three code defects and the untracked-history fact.
10. **Reports and figures index** — links to Phase 3 analysis, Phase 4 validation, Phase 4 audit, Phase 5
    experiment, Phase 5 audit, plus the JSON and figure inventory.
11. **Provenance and status** — seeds, data provenance, hash verification, frozen-phase statement.

### `docs/reproducibility.md` (new)

Operational companion: verified setup, the exact test invocation with observed output, byte-identical
offline commands with the outputs each writes, expected headline values for the slow re-fits, the full
"requires data / requires network" matrix, the known-broken script table, lint status, and a hash-
verification recipe (including the caveat that `generated_at_utc` timestamps change file hashes without
changing values).

### `requirements-lock.txt` (modified — one line)

```diff
 backports.tarfile==1.2.0
+batman-package==2.5.3
 beautifulsoup4==4.15.0
```

`git diff` is exactly one insertion. The file's UTF-8 BOM and CRLF endings were preserved deliberately
(the editing tool initially stripped the BOM; it was restored and verified byte-for-byte).

---

## 4. Dependency decision record

| Package | Action | Justification |
|---|---|---|
| `batman-package==2.5.3` | **Added** | Direct import in 3 scripts, indirect dependency of every Phase 3–5 result. Exact installed version. No upgrade. |
| `pip`, `setuptools`, `wheel` | Not added | Environment tooling; pinning them would misrepresent the analysis stack. |
| All other 76 pins | Untouched | Verified installed set is a subset of the lock; no version drift. |

Nothing was installed, upgraded, or removed. `pip check` result in §6.

---

## 5. Preservation verification

21 scientific artifacts were hashed **before** and **after** Phase 6 (SHA-256, `sha256sum`):

```
reports/results/phase3_transit_analysis.json
reports/results/phase4_block_bootstrap.json
reports/results/phase4_injection_recovery.json
reports/results/phase4_model_comparison.json
reports/phase3_transit_analysis.md, phase4_statistical_validation.md, phase5_audit.md
reports/phase5_dataset.json, phase5_features.csv, phase5_results.json, phase5_results.md
reports/figures/phase3_*.png  (10 files)
```

`diff` of the two hash lists: **no differences** — all 21 identical. No Phase 3/4/5 artifact, figure, or
result file was written, renamed, reformatted, or re-encoded. `data/processed/` and `data/raw/` were not
touched.

---

## 6. Checks run — actual results

### 6.1 Toolchain and integrity

| Check | Command | Actual result |
|---|---|---|
| Python | `.venv\Scripts\python.exe --version` | `Python 3.11.17` |
| Package consistency | `python -m pip check` | `No broken requirements found.` |
| Lock integrity | byte check after edit | BOM present, CRLF present, 77 unique pins, no duplicates |
| Syntax | `python -m py_compile scripts/*.py` | **FAILS** on `scripts/phase5_build_dataset.py`, line 51 `IndentationError: unexpected indent`; all other scripts compile |
| Lint (scoped) | `ruff check scripts tests` | 114 findings (see §2.6) |
| Lint (tracked) | `ruff check <git ls-files scripts>` | `All checks passed!` |

The `py_compile` failure is the pre-existing Phase 5 defect, reported not introduced: it is present in
the frozen artifact set, and fixing it requires an approved implementation change.

### 6.2 Test run

```
> .\.venv\Scripts\python.exe -m pytest tests\ -v
platform win32 -- Python 3.11.17, pytest-9.1.1, pluggy-1.6.0
configfile: pyproject.toml
collecting ... collected 0 items
============================ no tests ran in 0.75s ============================
exit code: 0
```

```
> .\.venv\Scripts\python.exe -m pytest          # repository root — DO NOT USE
ERROR scripts/transit_control_test.py - FileNotFoundError:
  [Errno 2] No such file or directory: '...\data\processed\kepler_kepler_10_-q.csv'
!!!! Interrupted: 1 error during collection !!!!
```

Both outcomes are documented in the README and the reproducibility guide, with the working invocation.

### 6.3 Offline reproduction — byte-identical

A throwaway copy of the repository (`/tmp/phase6_check`, 18 MB, scripts + reports + data + tests) was
used so that no committed artifact could be overwritten. Commands run there:

| Command | Result | Hash vs. committed file |
|---|---|---|
| `python scripts/phase5_features.py` | 26 rows, 13 positive / 13 negative, 5-window NaN notice printed | `phase5_features.csv` **IDENTICAL** |
| (same run) | config rewritten | `phase5_feature_config.json` **IDENTICAL** |
| `python scripts/phase5_baseline.py` | `train=13 val=6 test=7`; threshold 0.441; `Baseline F1=0.750 (dummy=0.571)`; `RandomForest NOT selected` | `phase5_results.json` **IDENTICAL**, `phase5_results.md` **IDENTICAL** |
| `python scripts/phase4_model_comparison.py` | reference depth 153.8 ppm; naive ΔBIC −2195.58; AC=0.936 warning printed | `phase4_model_comparison.json` **IDENTICAL** |
| `python -m pytest tests\` | `no tests ran`, exit 0 | — |

Five of five regenerated files matched byte-for-byte. This is the strongest reproducibility result
available without network access: the entire Phase 5 ML chain and the Phase 4 model comparison are
deterministic functions of committed inputs.

### 6.4 Full re-fit re-run (isolated copy)

`transit_analysis.py`, `phase4_block_bootstrap.py`, and `phase4_injection_recovery.py` were launched in
the isolated copy (1000 bootstrap refits plus 350 injection refits on a 27k-point series; CPU-bound).
**No repository artifact is at risk, because the run is confined to `/tmp/phase6_check`.**

**Phase 3 (`transit_analysis.py`) — completed, reproduced exactly.**

| Output | Result |
|---|---|
| `phase3_kepler_all_coverage.png` … `phase3_tess_s14_masked_raw.png` (10 figures) | **all 10 SHA-256 IDENTICAL** to the committed figures |
| `reports/results/phase3_transit_analysis.json` | **identical after dropping `generated_at_utc`** — every dataset entry, fit parameter, and robustness-grid cell matched (the file hash differs only because the timestamp is embedded) |

This confirms the Phase 3 pipeline is deterministic and that the committed figures are exactly what the
committed code produces from the committed data.

**Phase 4 bootstrap and injection/recovery — completed, reproduced exactly.** Wall time: 17 s (Phase 3),
3.6 min (bootstrap), 1.5 min (injection/recovery); total 5.5 min, all exit code 0.

| Output | Result |
|---|---|
| `reports/results/phase4_block_bootstrap.json` | **SHA-256 IDENTICAL** (`d4e2de41…91df9`) — all five block-length rows, intervals, and convergence counts matched |
| `reports/results/phase4_injection_recovery.json` | **SHA-256 IDENTICAL** — all seven depth rows including the 0 ppm control reproduced |

Bootstrap re-run output, verbatim:

```
BL=  10: n_conv=200 n_fail=0 depth_mean=154.2 ppm std=3.7 95%=[147.0, 160.7]  (38.6s)
BL=  50: n_conv=200 n_fail=0 depth_mean=154.2 ppm std=2.3 95%=[149.5, 158.5]  (38.2s)
BL= 100: n_conv=200 n_fail=0 depth_mean=154.1 ppm std=2.1 95%=[149.8, 157.9]  (52.7s)
BL= 200: n_conv=200 n_fail=0 depth_mean=154.4 ppm std=1.9 95%=[151.2, 158.2]  (45.9s)
BL= 500: n_conv=200 n_fail=0 depth_mean=154.3 ppm std=1.9 95%=[150.4, 157.7]  (37.5s)
```

Injection/recovery re-run output, verbatim:

```
Depth    0: n_success=50 mean_recov=2.7   std=2.0 bias=+2.7
Depth   50: n_success=50 mean_recov=50.1  std=2.8 bias=+0.1
Depth  100: n_success=50 mean_recov=99.8  std=3.0 bias=-0.2
Depth  150: n_success=50 mean_recov=150.8 std=3.2 bias=+0.8
Depth  154: n_success=50 mean_recov=154.8 std=3.2 bias=+0.8
Depth  200: n_success=50 mean_recov=199.6 std=3.5 bias=-0.4
Depth  300: n_success=50 mean_recov=299.3 std=2.5 bias=-0.7
```

**Overall reproduction tally: 17 of 17 outputs reproduced — 16 byte-identical files and 1 JSON
(`phase3_transit_analysis.json`) identical in every value but its embedded timestamp.** The committed
Phase 3 and Phase 4 artifacts are exactly what the committed code produces from the committed data;
the Phase 5 chain is likewise reproducible from its saved dataset. Data availability, not determinism,
is the remaining obstacle to a front-to-back re-run (§7).

### 6.5 Documentation checks

| Check | Result |
|---|---|
| Every numeric claim in `README.md` traced to a report/JSON | 153.8 ppm, [151.2, 158.2], [150.4, 157.7], 146–162 ppm, 154.8 ± 3.2, +2.7 ± 2.0, −2195.58, 0.4405, 0.75/0.75/0.75, 0.667, 0.771, 0.571, 0.800, 26/13/6/7, 45,514, 27,111, 17,722, 7,839, 1,566, 15 quarters — all matched their source |
| Markdown links resolve to existing paths | README links: all 9 report/report-dir targets exist; `docs/reproducibility.md` exists |
| Setup commands match the real environment | `.venv/pyvenv.cfg` confirms `uv`-created CPython 3.11.17; `py -0p` shows 3.11 available only via `Astral/CPython3.11.17`, so the uv path is documented as primary and `py -3.11` as the alternative with a fallback note |
| Commands copy-ready and shell-correct | PowerShell syntax (`.\.venv\Scripts\python.exe`), no bash-isms in the README |
| Claims about non-runnable scripts verified | each of the four was executed or statically compiled, not assumed |
| Encoding of every file reviewed | `phase5_results.md` identified as CP1252 and left untouched; all new files written UTF-8 |

---

## 7. What a reviewer can and cannot reproduce

**Can reproduce, offline, from the committed artifacts:**

- The entire Phase 5 ML chain (features → threshold → metrics) byte-identically.
- The Phase 4 model comparison (153.8 ppm reference, ΔBIC, correlation warning) byte-identically.
- The leakage/label assertions in `tests/test_phase5_leakage.py` (via `pytest tests\`, as collection).
- Every reported number by reading the JSONs, without running anything.

**Cannot reproduce without downloaded data (from a clean clone):**

- Phase 3 transit fits, robustness grids, and `phase3_*.png` — require `data/processed/*.csv`
  (gitignored). *With those CSVs present they reproduce exactly (§6.4); the blocker is data availability,
  not determinism.*
- Phase 4 block bootstrap and injection/recovery — same requirement, same caveat.
- TESS S14 results — same requirement.
- Regenerating the CSVs — requires FITS from MAST (network), via the download scripts.

**Cannot reproduce at all in the current tree:**

- `reports/phase5_dataset.json` from source — `phase5_build_dataset.py` does not parse.
- Any output of `statistical_validation.py` — undefined names.
- `phase4_statistical_validation.json`, `phase4_residual_diagnostics.png`, `phase4_bootstrap.png`,
  `phase4_model_comparison.png` — never produced by the script that was supposed to write them.

---

## 8. Known scientific limitations (unchanged, restated for reviewers)

Carried forward verbatim in substance from Phases 3–5; see `README.md` §4 for the full statement.

1. **Correlated noise dominates.** Lag-1 residual AC ≈ 0.93 (0.936 in the model comparison); the
   stationarity ratio across segments is 7.2. `std/√n` bin errors underestimate uncertainty; per-point
   RMS (1,000–1,200 ppm) is 5–6× the depth.
2. **Fixed geometry is the largest systematic.** 146–162 ppm from the geometry grid, versus a bootstrap
   interval of [151.2, 158.2] ppm. The interval is conditional on `a/R★=3.4`, `i=84.5°`, `u=[0.30,0.20]`,
   the detrending choice, and the model form — it is not a total uncertainty.
3. **Block bootstrap approximates correlation**; scales beyond ~10 days and block lengths longer than the
   shortest segments are untested.
4. **The ML test set is 7 windows.** F1 = 0.75 moves to 0.667 or 0.857 on a single classification change;
   ROC-AUC 0.667 on n=7 carries essentially no information.
5. **ML labels are synthetic only**, with a fixed 150 ppm template and median-imputed NaN correlations for
   5/26 windows; generalisation to real observations is unverified.
6. **Cross-dataset validation is partial** — TESS S14 only; S40/S53/S74 were never retrieved.
7. **No detection significance is claimed anywhere.** All statistical statements are descriptive.
8. **The Q0-only numbers (183–186 ppm, −1.7 min) are superseded** by the full-baseline values and should
   not be quoted.

---

## 9. Unresolved issues requiring approval

| # | Issue | Proposed fix | Why not done |
|---|---|---|---|
| U1 | `phase5_build_dataset.py` IndentationError blocks dataset regeneration | Remove 4 spaces from lines 51–104 | Implementation change to a frozen Phase 5 script |
| U2 | `statistical_validation.py` undefined names | Define/import the two block-resampling helpers, or mark the script deprecated | Implementation change; its role is already covered by `phase4_*.py` |
| U3 | Root-level `pytest` aborts collection | Add `testpaths = ["tests"]` (and optionally `norecursedirs`) to `pyproject.toml` | Config change beyond documentation; low risk, needs a yes/no |
| U4 | No pytest-style tests | Wrap the leakage assertions in `test_*` functions; add unit tests for folding/validation/metrics | New code |
| U5 | 114 lint findings in Phase 3–5 scripts | `ruff check --fix` plus manual E501/F821 | Touches analysis scripts |
| U6 | `phase5_results.md` is CP1252 | Convert to UTF-8 | Modifies a frozen Phase 5 artifact |
| U7 | Science data is gitignored; a clone has no CSVs | Commit `data/processed/*.csv` (~4.8 MB) or document regeneration only | Changes repository content policy |
| U8 | Phase 3–5 artifacts are untracked in git | Commit them | Explicitly out of scope ("do not commit") |
| U9 | `HOME/` tooling cache in project root | Add `HOME/` to `.gitignore` or relocate | Not documentation |
| U10 | `src/astronomy_ai/` empty, `pyproject.toml` has no `[project]` | Either populate the package or delete the skeleton and say "scripts, not a package" | Structural change; README currently describes the status quo accurately |

None of these affects the correctness of the committed results. U1, U3, and U7 are the ones that most
affect a reviewer's first ten minutes with the repository.

---

## 10. Portfolio readiness verdict

**Ready as a working tree; not yet ready as a public repository.**

What is strong:

- The scientific framing is unusually honest for a portfolio: a known planet used as a control, a
  baseline-driven depth correction that *retracts* an earlier result, a measured +2.7 ppm false-positive
  tendency, a ΔBIC explicitly declared unusable, and an ML metric presented with its `n = 7` caveat.
- Two audit reports (Phase 4, Phase 5) exist independently of the analysis reports, and their claims
  were re-verified in this phase wherever possible without recomputation.
- Deterministic reproduction of the whole Phase 3–5 chain is now demonstrated byte-for-byte, not asserted:
  17 of 17 outputs, including all 10 Phase 3 figures and both Phase 4 JSONs.

What a reviewer would trip over, in order of likelihood:

1. **`pytest` at the root fails** (U3) and **`pytest tests\` collects 0 tests** (U4).
2. **A clone has no data** (U7), so none of the headline Phase 3/4 results can be re-run.
3. **The Phase 5 dataset generator does not parse** (U1) — a reviewer who tries to regenerate will see an
   `IndentationError`, which reads as carelessness unless the README is consulted first (it now flags it).
4. **Git history stops at Phase 2** (U8), so there is no commit trail for the most interesting work.
5. `reports/phase5_results.md` opens as mojibake in UTF-8 tooling (U6).

Fixing 1, 3 and 5 is genuinely small — one pytest config line, a four-space dedent, one re-encode. Item 2 is
a repository-policy decision (commit ~4.8 MB of CSVs, or accept "regenerate from MAST"), and item 4 is a
commit the owner declined in this phase. With 1, 2, 3 and 5 resolved, the project would be defensible as
a public portfolio piece: the remaining weaknesses would be scientific limitations that are already
documented, rather than packaging accidents.

---

## 11. Files changed in Phase 6

| File | Status | Size |
|---|---|---|
| `README.md` | **new** | 23.6 KB (405 lines) |
| `docs/reproducibility.md` | **new** | 10.1 KB (242 lines) |
| `reports/phase6_portfolio_readiness.md` | **new** (this file) | 25.6 KB (436 lines) |
| `requirements-lock.txt` | **modified** — one inserted line (`batman-package==2.5.3`), BOM/CRLF preserved | +1 line |

**Not modified:** every `scripts/*.py`, every `tests/*`, `pyproject.toml`, `.gitignore`, `data/`, and all
Phase 1–5 reports, results, JSONs, and figures (§5). No commit, no push.

---

## 12. Phase 6 status

**Complete — stop for review.**

Verified: scientific artifacts unchanged (21/21 hashes), full Phase 3–5 reproduction check
**17/17 outputs** (16 byte-identical, 1 identical but for a timestamp), dependency gap closed with a
one-line documented pin, documentation written against measured outputs rather than assumed ones, three
pre-existing code defects documented instead of silently fixed.
