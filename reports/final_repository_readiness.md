# Final Repository Readiness Audit

**Date:** 2026-10-22 · **Scope:** pre-publication audit only — no scientific change, no commit, no push.
**Verdict:** **conditional GO.** The code, reports and artifacts are publishable. Three repository-hygiene
items must be settled first, one of which is a genuine accident risk (`HOME/`).

Everything below was measured in this session; where a check could not be completed, that is stated rather
than assumed.

---

## 1. Git state and proposed commit scope

```
branch: main
HEAD:   21bf6e2  feat: Phase 2 data integrity - quality-masked CSVs, provenance metadata, dataset variant support
parent: 1b00fa1  chore: initial baseline (Phase 1 audit state)
```

Tracked: **26 files**. Untracked: **50 status entries / 656 files**. One tracked file is modified
(`requirements-lock.txt`, the Phase 6 `batman-package` pin).

### 1.1 What a commit would contain

| Area | Files | Size | Contents |
|---|---:|---:|---|
| modified (tracked) | 1 | — | `requirements-lock.txt` (+1 line) |
| `README.md` | 1 | 25.8 KB | portfolio entry point |
| `docs/` | 2 | 17.1 KB | `reproducibility.md`, `PIPELINE_STATUS.md` |
| `scripts/` | 17 | 121.8 KB | Phase 3–8 scripts (incl. 4 Phase 8 files) |
| `tests/` | 3 | 16.0 KB | 28 tests |
| `reports/` (text/JSON/CSV) | 22 | 207.9 KB | Phase 3–8 reports, results, datasets, metadata |
| `reports/figures/` | 10 | 2,014.7 KB | Phase 3 figures |
| **total** | **56 changes** | **2.35 MB** | |

Complete list is reproducible with:

```bash
git ls-files --others --exclude-standard | grep -v '^HOME/' | sort
```

### 1.2 Blocker: `HOME/` must not be committed

`HOME/` is untracked, **not gitignored**, and contains **601 files / 22 MB**, including
`HOME/.claude-omniroute/.claude.json` (54 KB), `history.jsonl`, `paste-cache/*.txt`, a plugin marketplace
and a file-history directory. This is local agent-tooling state, not project content, and it can contain
conversation text. `git add -A` or `git add .` would commit all of it.

Required before any commit:

```gitignore
# local agent tooling state — never commit
HOME/
```

Nobody has changed `.gitignore` in this audit (repository policy: no unrequested edits). Until it is added,
stage explicit paths only, never `-A`/`.`.

---

## 2. Test results

### 2.1 Requested configuration change — blocked

`pyproject.toml` holds the project's ruff configuration and is protected by this environment. The edit was
refused:

> Blocked: pyproject.toml holds this project's ruff (linter) configuration and is protected. …
> If a config change is genuinely needed, ask the user to make it manually.

No workaround was attempted (no `pytest.ini`, no shell write). To apply manually:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

### 2.2 Actual results

| Command | Result | Exit |
|---|---|---|
| `python -m pytest -v` (repo root, no `testpaths`) | **fails during collection**: `scripts/transit_control_test.py` parses `sys.argv` at import → `FileNotFoundError: …kepler_kepler_10_-v.csv`; 0 tests run | **2** |
| `python -m pytest tests -v` | **28 passed**, 0 failed, 0 xfail, 0 skipped, 4 numpy RuntimeWarnings | **0** |
| same, from `/tmp` (absolute path) | 28 passed | 0 |
| clean clone (no CSVs) | 26 passed, 2 skipped | 0 |

Until `testpaths` exists, the command a reviewer types first — `pytest` at the root — fails. This is the
single most visible defect left.

---

## 3. Publication data set — hash and provenance audit

All five files were re-hashed against the Phase 7 manifest. **Every size and SHA-256 matches.**

| File | Size (B) | SHA-256 | Match |
|---|---:|---|---|
| `kepler_all_quarters_quality_masked.csv` | 1,737,194 | `9a457cf9c59866a578ba6c9ebf30364f29ea5852dd51152cdf94112605194d82` | yes |
| `kepler_kepler_10.csv` | 18,129 | `7dd1cb33d3dea7109db42c0277cae8f4bd3dfd1f9cf9d44e4b4c613521657854` | yes |
| `kepler_kepler_10_quality_masked.csv` | 16,961 | `47c4d04d630910b4be2a34e8ff28f33f778beaaf2c8f3a5904959f1215e290ab` | yes |
| `tess_kepler_10_quality_masked.csv` | 683,388 | `dfae1213d60c66ae5af25099637853dd793c7aa8183d0268ccfcc9c0a1150867` | yes |
| `tess_kepler_10.csv` (optional) | 683,479 | `ac582c1cf89996ff54d3d9f9035512f8ae6adb582a8ed5feeb5517cd13838f1f` | yes |

Total for the four required files: **2.34 MB**.

**Provenance (verified from FITS headers in `data/raw/mast_cache/`):** Kepler long-cadence
`kplr011904151-{timestamp}_llc.fits`, 15 quarters, `ORIGIN = NASA/Ames`, `TELESCOP = Kepler`,
`OBJECT = KIC 11904151`; TESS SPOC `tess2019198215352-s0014-0000000377780790-0150-s_lc.fits`,
TIC 377780790. Processing policy and row accounting are recorded in `reports/dataset_metadata.json` and
`reports/kepler_quarters_metadata.json`.

**Redistribution terms: UNRESOLVED.** The archive's terms-of-use text could not be retrieved in this
session — the search backend returned HTTP 429 (quota) and a direct fetch of `archive.stsci.edu` failed at
the network layer. I did **not** infer permission from the data being publicly downloadable. What is
verified is narrower: the files are public NASA mission products, no credentials were used to obtain them,
and their processing is fully documented. Confirming MAST/STScI terms remains an owner action before the
CSVs enter Git. **Nothing was staged, added, or ignored.**

---

## 4. Clean-clone rehearsal

A disposable copy was built exactly as a commit would produce it: `git archive HEAD` plus the 55 proposed
files, no `.venv`, no `HOME/`, no CSVs (only `data/*/.gitkeep`). 81 files, 5.0 MB. The repository's own
interpreter was used, so this tests *content* availability, not installation.

### 4.1 Without the four CSVs

| Script | Result |
|---|---|
| `phase5_features.py` | **OK** — output byte-identical to the frozen CSV |
| `phase5_baseline.py` | **OK** — `phase5_results.json` and `.md` byte-identical |
| `phase4_model_comparison.py` | **OK** — byte-identical |
| `phase8_features.py`, `phase8_eval.py` | **OK** |
| `phase8_build_dataset.py` | fails — `FileNotFoundError: data/processed/kepler_all_quarters_quality_masked.csv` |
| `phase5_build_dataset.py` | fails — same |
| `transit_analysis.py` | fails — same |
| `phase4_block_bootstrap.py`, `phase4_injection_recovery.py` | fail — same |
| `apply_quality_mask.py`, `prepare_kepler_quarters.py` | fail — need the gitignored FITS cache |
| `download_*.py`, `prepare_lightcurves.py`, `smoke_test_data.py` | require network (not run) |

Tests: 26 passed, 2 skipped (both skips name the missing CSV).

### 4.2 With the four CSVs added (2.4 MB copied in)

| Check | Result |
|---|---|
| `phase5_build_dataset.py` | runs; output **byte-identical** to the frozen dataset (`f8ad47fb…`) |
| `phase8_build_dataset.py` | runs; output byte-identical to `reports/phase8_dataset.json` (`5707f58c…`) |
| `transit_analysis.py` | runs; headline `153.8 ppm`, offset `+0.03 min` |
| 10 × `phase3_*.png` | **byte-identical** to the repository figures |
| `phase3_transit_analysis.json` | identical in every value except `generated_at_utc` |

**Conclusion:** a clone can read and re-derive every *report-level* artifact with no data and no network.
Reproducing the *analysis* (Phase 3, Phase 4, dataset builds) requires the CSVs. Re-deriving the CSVs
requires MAST access.

---

## 5. Artifact hash verification

Ten protected artifacts, re-hashed against the values recorded in earlier phases:

| Artifact | SHA-256 (first 16) | Status |
|---|---|---|
| `reports/results/phase3_transit_analysis.json` | `045073e20b7dcbfc` | match |
| `reports/results/phase4_block_bootstrap.json` | `d4e2de41a674c7c8` | match |
| `reports/results/phase4_injection_recovery.json` | `57b67864f5fd5187` | match |
| `reports/results/phase4_model_comparison.json` | `a8183377dfe7443a` | match |
| `reports/phase5_dataset.json` | `f8ad47fb2a404b41` | match |
| `reports/phase5_features.csv` | `a2886bf9a47f2325` | match |
| `reports/phase5_feature_config.json` | `417d614c5609aef7` | match |
| `reports/phase5_results.json` | `a22734583ecc36fc` | match |
| `reports/phase5_results.md` | `8443a7b5cf1de2a2` | match |
| `reports/phase5_audit.md` | `b1b5e2cc467ed509` | match |

**10/10 identical; no differences to investigate.** Phase 3/4 results and figures, the Phase 5 dataset,
features, metrics and audit are all untouched.

---

## 6. Documentation consistency

Checked README, `docs/reproducibility.md`, `docs/PIPELINE_STATUS.md` and the Phase 7 erratum.

| Check | Result |
|---|---|
| Historical vs maintained chain distinguished | **Yes** — README §8 now names both explicitly; `PIPELINE_STATUS.md` is the reference page; each Phase 5 script carries a status header |
| Retraction of the Phase 7 leakage claim | README §9 item 1, Phase 7 report erratum block, Phase 8 audit §2 — all consistent |
| Stale claims (`xfail`, "not leakage-free", "0 items", "19 passed", "8 of 26") | **none remain** in README or `docs/` |
| Historical metrics overstated? | No. README §3 states the Phase 8 re-derivation, labels the table a "pipeline demonstration, not a performance estimate", and §4.4 gives the 7-window caveat |
| Links resolve | README 15/15, reproducibility 1/1, PIPELINE_STATUS — none broken |

Two known inaccuracies remain inside **historical** reports, preserved rather than rewritten:
`reports/phase6_portfolio_readiness.md` says 5/26 windows had imputed correlations (measured: 9), and its
§3 describes an earlier test state. Phase 7 carries a dated erratum for the retracted finding; Phase 6 has
no erratum. This is recorded here rather than edited, to keep the audit trail intact.

---

## 7. Remaining blockers

| # | Severity | Issue | Exact fix | Owner |
|---|---|---|---|---|
| B1 | **P0** | `HOME/` (601 files, 22 MB, tool config + chat history) is untracked and not ignored; `git add -A` would commit it | add `HOME/` to `.gitignore` | you (policy edit) |
| B2 | **P1** | `pytest` at the repo root exits 2; reviewers hit this first | add the two-line `[tool.pytest.ini_options]` block | you (protected file) |
| B3 | **P1** | MAST/STScI redistribution terms unverified | confirm terms; then decide whether the 2.34 MB of CSVs enter Git | you |
| B4 | **P2** | Without CSVs, Phase 3/4 cannot be re-run and 2 tests skip | publish the CSVs (if B3 clears) or state "code-only clone" in README | you |
| B5 | **P3** | `scripts/statistical_validation.py` calls 4 undefined helpers and produced no committed output | deprecate with a header, or delete | you |
| B6 | — | `ruff check scripts tests`: 75 findings in Phase 3–5 scripts (line length, import order, undefined helpers) | **Resolved after this audit** — 0 findings. 16 safe autofixes, 41 wrapped literals, 13 `# noqa: E402` (imports after `sys.path` setup), 4 `# noqa: F821` (never-defined helpers in `statistical_validation.py`). All eight artifact outputs re-verified byte-identical. | done |
| B7 | **P3** | Git history has 2 commits; all Phase 3–8 work is uncommitted | commit in phase-sized chunks so the audit trail is readable | you |

No blocker requires changing a scientific result or deleting historical evidence.

---

## 8. Changes made during this audit

| File | Change | Reason |
|---|---|---|
| `tests/test_phase8_pipeline.py` | `skipif` guard on `test_rebuild_is_deterministic` (matching the existing guard on the sibling integration test); `INPUT_CSV` constant | a clean clone failed this test; now skips with an explicit reason. Repo run still 28 passed |
| `README.md` | §3 Stage 5 wording (validation-vs-validation selection); §8 names the historical and maintained chains | accuracy and consistency with Phase 8 |
| `docs/reproducibility.md` | chain naming; clean-clone test result (26 passed, 2 skipped) | accuracy |

No test was weakened to make it pass: the skip fires only when the gitignored CSV is genuinely absent, and
the four assertions it guards were verified separately in the repo and in the clone-with-data run.

**Not done:** `pyproject.toml` edit (blocked), `.gitignore` edit (policy), commit, push, staging, data
addition, formatter run.

---

## 9. Recommendation

**Publish the code, documentation and reports now. Do not publish the data yet.**

- The scientific record is self-consistent and hash-verified: Phase 3/4 untouched, Phase 5 frozen and
  byte-reproducible, Phase 8 retraction documented, all 28 tests green.
- A reviewer cloning today gets a working suite (`pytest tests`), every report, every figure, and exact
  reproduction of the report-level artifacts — but will hit two stumbles: `pytest` at the root (B2) and no
  data for the re-fits (B4).
- Fix B1 and B2 before the first commit; they are two- and one-line changes and they are what separates
  "careful repository" from "accident waiting to happen".
- Hold the CSVs until B3 is answered. Publishing without data is honest and already documented; publishing
  data without confirmed terms is not.

**Suggested commit sequence** once B1/B2 are in place (each independently reviewable):

1. `chore: ignore local agent tooling state` (`.gitignore`)
2. `chore: configure pytest testpaths` (`pyproject.toml`)
3. `feat: phase 3–4 analysis, reports and figures`
4. `feat: phase 5 dataset, features and historical ML results`
5. `test: phase 5 and phase 8 pipeline tests`
6. `docs: README, reproducibility guide, pipeline status, phase 6–8 audits`
7. *(separate, after B3)* `data: publish processed light-curve CSVs with provenance manifest`

**Stopped here for review.** Nothing staged, committed, or pushed.
