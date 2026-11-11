# Phase 10 Audit — Injection Recovery & Detection Benchmark

**Date:** 2026-10-22 · **Scope:** verification of the Phase 10 implementation, saved outputs, tests, API,
and UI. Historical Phase 4/5 results and source CSVs were not modified.
**Backups:** `%TEMP%/reports_before_audit.py` (pre-audit report generator);
earlier edit backups in `.../phase10-backup-20261022-080939/`.

## Verdict

The experiment, detector, splits, thresholds and saved metrics are **correct as implemented**: every
number in the saved summary was recomputed independently from `trial_results.csv` and matches exactly.
Three **reporting** defects were found and corrected (one of them material — the generated report omitted
the no-skill baseline that changes how the ML results must be read). The scientific interpretation in the
Phase 10 write-up stands, with one statistical qualification added: the reported confidence intervals are
trial-level and too narrow given that trials within a chunk share cadences.

Nothing in the scientific results changed. Browser interaction remains **unverified** (no automation
available).

---

## 1. Injection, subtraction, time, and no-leakage

| Check | Method | Result |
|---|---|---|
| Detector cannot see truth | AST of `core.detect`: args `(times, flux, mission)`; body references none of `depth_ppm`, `delta_true`, `injected`, `label`, `recovered`; single call site `core.detect(t, presented, m)` | **pass** |
| Injection formula | `inject_transit` = `flux + median(flux) × (model − 1)`, the Phase 5 formula; depth 0 returns an exact copy | **pass** (unit tests + code) |
| Published-transit subtraction | On one chunk per dataset: depth at δ=0 before vs after cleaning | Kepler **193.8 → 8.5 ppm**, TESS **160.4 → 4.3 ppm** (≈96–97% removed) |
| Subtraction cannot use injection truth | `remove_published_transit(times, flux, mission)` — amplitude fitted at the published ephemeris only; applied to the pre-injection chunk, before noise conditioning and injection | **pass** |
| Time conversion | `phase_offsets(epoch+δ, δ) == 0` exactly; BKJD/TJD round-trip to BJD_TDB exact | **pass** |
| Centre handling | Hidden δ ∈ ±0.10 d; detector scans ±0.20 d at 0.0025 d (161 candidates), so the truth is always inside the search range but never supplied | **pass** |

**Potential mismatch between claim and implementation:** none found. The one nuance worth stating is that
the subtraction is an *estimate*: it leaves 4–9 ppm of the real transit in the data, which contributes to
control noise but cannot create a false recovery at another phase.

**Label leakage:** none. Labels are `injected = depth > 0`, defined before detection; the physics decision
uses only `snr`, which is computed from flux. The ML features are six time-domain statistics of the
presented flux — they contain the injected signal (legitimate, as the classifier is shown the light curve)
but no depth, offset, or label.

---

## 2. Split independence

Saved mapping (`trial_results.csv` → `chunk_id` → `split`), verified to be one split per chunk:

| dataset | chunk | split | transits (approx.) |
|---|---|---|---|
| kepler | k-c0 | train | ~4 |
| kepler | k-c1 | val | ~4 |
| kepler | k-c2 | test | ~4 |
| tess | t-c0 | val | ~8 |
| tess | t-c1 | train | ~8 |
| tess | t-c2 | test | ~8 |
| tess | t-c3 | train | ~8 |

Chunks are contiguous index ranges of the light curve and are non-overlapping by construction
(`make_chunks` uses `linspace(0, n, k+1)`). No cadence appears in two chunks, no window crosses a split,
and no derived feature is computed across chunks.

**What the seven groups permit:** a descriptive recovery curve, a paired comparison of noise conditions
within chunk, and a grouped benchmark where test chunks were untouched during threshold/imputation/model
selection.

**What they do not permit:** trial-level binomial precision. The 20 trials inside one chunk reuse the same
cadences and the same noise realisation; they are repeated perturbations, not independent observations.
A cluster bootstrap over chunks (4 000 resamples, same seed) gives:

| Depth | Trial-level Wilson | Cluster bootstrap 95% |
|---|---|---|
| 150 ppm | [0.18, 0.50] | **[0.07, 0.64]** |
| 300 ppm | [0.46, 0.79] | **[0.36, 0.86]** |

The Phase 10 report already cautions that intervals describe *this experiment's trials*, but it does not say
the binomial assumption is violated by clustering. **This audit adds that qualification**; the intervals
were not recomputed in the saved artifacts (that would change reported numbers).

---

## 3. Metrics, recomputed independently from `trial_results.csv`

| Quantity | Recomputed | Saved | Match |
|---|---|---:|---|
| Thresholds (4 strata) | 3.00 each (calibration n = 4, 4, 6, 6) | 3.00 each | ✓ |
| `detected` flags | 140/140 | 140/140 | ✓ |
| `recovered` flags | 140/140 | 140/140 | ✓ |
| Recovery 75/150/225/300 (all) | 4/28, 9/28, 14/28, 18/28 | identical | ✓ |
| FPR (test controls) | 0/8 | 0/8 | ✓ |
| Physics confusion matrix | [[8,0],[19,13]] | same | ✓ |
| Physics precision/recall/F1 | 1.000 / 0.406 / 0.578 | same | ✓ |
| Physics ROC-AUC / PR-AUC | 0.844 / 0.960 | same | ✓ |
| LR confusion matrix | [[0,8],[0,32]] | same | ✓ |
| LR F1 / ROC-AUC | 0.889 / 0.680 | same | ✓ |
| RF ROC-AUC | 0.555 | 0.555 | ✓ |
| Dummy ROC-AUC | 0.469 | 0.469 | ✓ |

Denominators everywhere: 140 valid trials, 0 invalid; 112 injected (28 per depth), 28 controls
(8 test-split); test split 40 windows / 2 chunks / 32 positive / 8 negative; prevalence **0.800**.

### Why the physics filter has AUC 0.844 but F1 0.578

They answer different questions. F1 is computed at the fixed 3σ threshold, which yields **perfect
precision and 0.41 recall** (19 of 32 positives are missed at 150/75 ppm). AUC is threshold-free and
reflects the *ranking* quality of the SNR, which is good — PR-AUC 0.96 confirms it. The filter is
conservative, not weak.

### Why both ML models predict all positives

Recomputed LR: validation Youden threshold **0.8795**; test probabilities range **0.880–1.000**, so every
window is classified positive. Confusion matrix `[[0,8],[0,32]]` — zero true negatives. RF also predicts a
single class. Their F1 **0.889 equals the no-skill value `2p/(1+p) = 2(0.8)/1.8 = 0.889`** exactly.

The six time-domain features carry almost no discriminative signal at these depths (physics S/N is 1.3–2.6
per transit), so the classifier learns the prior. This is a property of the feature set and sample size, not
a coding bug.

---

## 4. Noise experiment

- **How doubling works:** `f' = median(f) + 2 × (f − median(f))` applied to the cleaned, pre-injection
  chunk. It doubles the residual scatter about the median while preserving structure; it is a documented,
  explicitly synthetic stress condition, not a physical noise model (no Poisson/Gaussian claim is made).
- **Support:** Kepler 24 injected trials per noise condition; TESS 32. TESS goes 9/32 (28%) →
  **0/32 (0%)**; the Wilson 95% interval on 0/32 is [0.00, 0.11], so "TESS loses sensitivity under doubled
  noise" is supported for this configuration, while the exact 28% vs 0% gap is **exploratory** (2 test
  chunks; clustered trials).

---

## 5. Report integrity

- Regeneration from `summary.json` + `trial_results.csv` is **byte-deterministic** (verified after every
  change, including after the audit fixes).
- `plot_data.json` recovery series == `summary.json` recovery series (exact).
- All five figures regenerate from plot data. PNG content was not visually inspected.

### Defects found and corrected

| # | Defect | Evidence | Correction |
|---|---|---|---|
| **D1** | Generated Markdown omitted the **no-skill F1** and prevalence, so LR/RF's 0.889 appeared to beat the physics filter's 0.578 with no context | table had columns method/n/P/R/F1/AUC/PR-AUC only | added `prevalence` and `no-skill F1` columns plus an explanatory paragraph; regenerated |
| **D2** | Control figure mixed **28** controls (calibration + test) while the false-positive rate uses **8** test controls, with no label saying so | `plot_data.controls.n=28` vs `summary.false_positive_rate.controls=8`; title said only "n=28" | `plot_data.controls` now carries `n_test`, `false_positives` (from the FPR block) and a `scope` string; figure title states both counts; frontend chart label updated |
| **D3** | `regenerate_from_artifacts()` trusted a stale `plot_data.json` instead of rebuilding it, so a generator change could silently not apply | regeneration crashed with `KeyError: 'n_test'` on the old file | regeneration now rebuilds plot data from `summary.json` + `trial_results.csv`, rewrites it, then renders |

D1 is the material one: without it the auto-generated report could be read as "the ML model beats the
physics detector", which the data do not support.

Regression tests added (3): report contains the no-skill baseline and prevalence note; control scope
matches the FPR denominator; regeneration rebuilds plot data and is byte-deterministic.

---

## 6. Browser acceptance — **NOT VERIFIED**

No browser automation is installed (`npx playwright` refuses without installing; no Puppeteer; no Python
Playwright; no Chrome/Edge automation binary on PATH). No rendered page was inspected or clicked.

Manual checklist (to run before claiming UI acceptance):

1. Start backend (`uvicorn app:app --port 8000`) and frontend (`npm run dev`).
2. AI Laboratory → status badge shows `completed`, "mode full", runtime and finish time.
3. Click **Run smoke** → badge `running`, progress counter increments from real trial completions.
4. Click **Run smoke** again while running → 409 surfaces as "An experiment is already running."
5. On completion → four charts render, table populates, download links fetch `summary.json`,
   `trial_results.csv`, `recovery_report.md`, PNGs.
6. Stop the backend → Refresh shows an error banner; existing charts remain readable.
7. Existing Phase 5 panels and the Phase 9 transit explorer still work.

---

## 7. Data integrity and Git

| File | SHA-256 (first 16) | Status |
|---|---|---|
| `data/processed/kepler_kepler_10.csv` | `7dd1cb33d3dea710` | unchanged |
| `data/processed/tess_kepler_10.csv` | `ac582c1cf89996ff` | unchanged |
| `reports/phase5_dataset.json` | `f8ad47fb2a404b41` | unchanged |
| `reports/phase5_results.json` | `a22734583ecc36fc` | unchanged |
| `reports/phase5_features.csv` | `a2886bf9a47f2325` | unchanged |
| `reports/results/phase4_block_bootstrap.json` | `d4e2de41a674c7c8` | unchanged |

`git status` shows only intended Phase 9/10 additions (`webapp/`, `reports/injection_recovery*`,
Phase 9/10 reports). **Recurring environmental drift:** `scripts/phase8_build_dataset.py` keeps being
rewritten with formatting-only changes (8 insertions / 28 deletions, `ast.dump` identical). It was restored
to HEAD at the end of this audit; re-check `git status` before committing in case it reappears.

---

## 8. Checks executed (actual)

```
webapp/backend>  python -m pytest -q            49 passed, 1 warning        exit 0
webapp/backend>  python -m ruff check .         All checks passed!          exit 0
webapp/frontend> npx tsc -b                     exit 0
webapp/frontend> npm run lint                   0 errors, 1 pre-existing warning
webapp/frontend> npm run build                  built in 5.99 s             exit 0
```

API: status `completed`, results include `controls.n=28 / n_test=8`, report 200, artifact allowlist intact.
Smoke artifacts: 18 trials, 1.62 s. Full artifacts: 140 trials, 8.35 s (unchanged by this audit).

---

## 9. Classification of findings

**Confirmed defects (fixed):** D1 (missing no-skill baseline in generated report), D2 (control-scope
mislabelling), D3 (stale plot data on regeneration).

**Scientific limitations (documented, not defects):**
1. Trial-level Wilson intervals ignore clustering; cluster bootstrap is 1.3–1.8× wider.
2. 3σ threshold floor is a design choice; with 2–3 calibration controls per stratum the 95th percentile is
   noise, so the floor effectively sets every threshold.
3. Recovered depth is biased high among detections (selection on threshold).
4. Base rate 80% makes F1 uninformative; this is now stated in the generated report as well.
5. Seven chunks, two test chunks: dataset/noise comparisons are exploratory.
6. Subtraction leaves 4–9 ppm of the real transit.

**Optional future improvements (not applied):**
- Persist per-trial ML scores/predictions so benchmark metrics are auditable without re-running.
- Report cluster-robust intervals alongside trial-level Wilson intervals.
- Increase chunk count and calibrate thresholds per chunk (leave-one-chunk-out).
- Replace the 3σ floor with a phase-scrambled null distribution.

---

## 10. Recommendation

Publish the Phase 10 experiment as-is. The two report-level defects are fixed, the numbers are unchanged
and independently reproduced, and the honest framing (no-skill baseline, base rate, small group count) is
now present in the generated artifact rather than only in the hand-written report. Remaining gaps are
statistical caveats and UI acceptance, both documented above.
