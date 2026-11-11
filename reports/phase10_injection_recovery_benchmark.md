# Phase 10 — Injection Recovery, Detection Benchmark, and Reproducible Reports

**Status:** implemented, executed, and verified. No historical artifact or source CSV was modified.
**Backups:** `%TEMP%/phase10-backup-20261022-080939/` (`app.py`, `App.tsx`, `App.css`).

---

## 1. What was built

| Workstream | Deliverable |
|---|---|
| A — recovery experiment | `webapp/backend/research/` — fold-and-scan matched filter, hidden phase offsets, control-derived thresholds, Wilson intervals, full trial ledger |
| B — detection benchmark | Physics baseline vs logistic regression vs Random Forest vs dummy on identical grouped windows, with no-skill reference |
| C — report generator | `research/reports.py` — Markdown, `plot_data.json`, five PNG figures, and artifact-only regeneration |
| D — web app | New **Injection Recovery & Detection Benchmark** section in AI Laboratory; six API routes; process-local job manager |

---

## 2. Scientific design, and why it looks like this

A single Kepler-10 b transit in these data gives a matched-filter S/N of only **~1.3 (150 ppm, TESS) to
~2.6 (300 ppm, Kepler)**, measured from the actual per-point scatter (TESS 1346 ppm @ 2 min, Kepler
183 ppm @ 29.4 min). A per-transit detection experiment would therefore report "nothing detected" at every
depth — honest but uninformative.

The experiment uses the method real searches use: **fold the chunk at the published period and stack**.
S/N grows as √N with the number of transits in a chunk, which is what makes a recovery curve measurable.

Design decisions, all documented in code and in `config.json`:

1. **Period-known search.** Injections are placed coherently at `epoch + delta` for every orbit in a
   **contiguous chunk**, with `delta` drawn uniformly from ±0.10 d and never revealed to the detector.
2. **Folding detector.** For each of 161 candidate offsets (±0.20 d, 0.0025 d step) it folds the chunk,
   computes a matched-filter amplitude against the **same batman shape** used for injection, and keeps the
   most significant dip. Threshold = max(3σ, 95th percentile of non-test controls) per dataset/noise.
3. **Real transit removed first.** The published Kepler-10 b signal is present in the archive data. Left
   in, the detector locks onto the real planet at `delta ≈ 0` instead of the injection, and zero-depth
   controls are not nulls. `remove_published_transit()` estimates that amplitude at the published ephemeris
   (no injection truth) and subtracts it. This was found empirically: the first smoke run produced 0%
   recovery at every depth for exactly this reason.
4. **Independent units are chunks**, not cadences. 3 chunks (Kepler) and 4 (TESS) → 7 groups total.
   Split is grouped 50/25/25, so no chunk crosses splits.
5. **Paired trials.** The same hidden offset is reused across depths and noise conditions.

### Differences from Phase 5 and the Phase 9 explorer

| | Phase 5 | Phase 9 explorer | Phase 10 |
|---|---|---|---|
| Injection target | detrended flux | stored flux | stored flux, with the published transit subtracted |
| Window | randomly centred ±6 h | transit-centred ±2.4 h | whole contiguous chunks (multi-transit) |
| Centre | phase 0 (ephemeris) | user-selected ephemeris transit | hidden phase offset ±0.1 d |
| Purpose | ML dataset | visualisation | recovery measurement |

Phase 5 and Phase 9 are untouched.

---

## 3. Results — full mode (140 trials, 8.35 s, seed 20261022)

### Recovery by injected depth (all splits, Wilson 95%)

| Requested | Recovered | Trials | Fraction | 95% CI | Median recovered depth |
|---:|---:|---:|---:|---|---:|
| 75 ppm | 4 | 28 | 0.143 | [0.06, 0.30] | 135 ppm |
| 150 ppm | 9 | 28 | 0.321 | [0.18, 0.50] | 202 ppm |
| 225 ppm | 14 | 28 | 0.500 | [0.33, 0.67] | 287 ppm |
| 300 ppm | 18 | 28 | 0.643 | [0.46, 0.79] | 360 ppm |

**Test split only** (locked evaluation): 0/8, 2/8, 5/8, 6/8 for 75 → 300 ppm.

### By dataset and noise condition

| Dataset | Noise | Recovered | Trials | Fraction |
|---|---|---|---:|---:|
| Kepler | observed | 21 | 24 | 0.88 |
| Kepler | amplified ×2 | 15 | 24 | 0.62 |
| TESS | observed | 9 | 32 | 0.28 |
| TESS | amplified ×2 | 0 | 32 | 0.00 |

Kepler recovers far better: 29.4-minute cadence with 183 ppm scatter beats TESS's 2-minute cadence at
1346 ppm per point, and doubling the noise removes TESS sensitivity entirely.

### Zero-depth controls

**0 false positives in 8 test-split controls** (Wilson 95% [0.00, 0.32]). The upper bound is wide — this is
a small control sample, not a precise false-alarm calibration.

### Detection benchmark (same 40 test windows, 2 groups, 32 positive / 8 negative)

| Method | n | Precision | Recall | F1 | ROC-AUC | No-skill F1 |
|---|---:|---:|---:|---:|---:|---:|
| Physics matched filter | 40 | 1.000 | 0.406 | 0.578 | **0.844** | 0.889 |
| Logistic regression | 40 | 0.800 | 1.000 | 0.889 | 0.680 | 0.889 |
| Random Forest | 40 | 0.800 | 1.000 | 0.889 | 0.555 | 0.889 |
| Dummy (stratified) | 40 | 0.788 | 0.813 | 0.800 | 0.469 | 0.889 |

**The honest reading:** both ML models score **exactly the no-skill F1 (0.889)** — the value obtained by
predicting "positive" for everything under an 80% positive base rate. Their recall is 1.0 and their
precision is the prevalence, which is the signature of a constant-positive classifier. The physics
detector has the *lower* F1 but perfect precision and ROC-AUC 0.844, and it is the only method whose
detections track injected depth (per-depth test recovery 0/2/5/6 vs 8/8/8/8 for logistic regression).

Per-depth behaviour is the metric that exposes this; aggregate F1 alone would have made the ML models look
better. This is reported, not tuned away.

---

## 4. Artifacts

`reports/injection_recovery/` (live), `reports/injection_recovery_smoke/` (preserved smoke snapshot):

```
config.json  trial_results.csv  summary.json  plot_data.json  provenance.json
recovery_report.md  figures/{recovery_vs_depth,control_snr,recovered_vs_injected,timing_error,benchmark_f1}.png
```

Provenance recorded: SHA-256 of both source CSVs, seed, Python/platform, numpy/pandas/scikit-learn/batman
versions, git commit, command, timestamps. The report is regenerable from saved artifacts alone:

```python
from research.reports import regenerate_from_artifacts

regenerate_from_artifacts(Path("../../reports/injection_recovery"))
```

Verified deterministic: regenerating produced a byte-identical `recovery_report.md`.

---

## 5. API and UI

| Route | Behaviour |
|---|---|
| `GET /api/injection-recovery/status` | `not_run` / `running` (progress from completed trials) / `completed` / `failed`, reconciled with on-disk artifacts |
| `POST /api/injection-recovery/run` | body `{"mode": "smoke"|"full"}`, Pydantic-validated, **409** if already running, 202 on start |
| `GET /api/injection-recovery/results` | summary, plot data, benchmark, first 200 trial rows (NaN-safe JSON) |
| `GET /api/injection-recovery/report` | Markdown |
| `GET /api/injection-recovery/artifacts/{name}` | exact allowlist of 11 names; traversal and unknown names → 404 |
| `GET /api/detection-benchmark/results` | benchmark slice |

Compute runs in a single-worker `ThreadPoolExecutor` (documented process-local manager), never at startup,
never blocking the event loop, one job at a time. Failures set `status=failed` and leave previous artifacts
intact.

The UI section shows status/progress, Run smoke / Run full / Refresh, four Plotly panels (recovery vs depth
with asymmetric Wilson error bars, control S/N histogram with threshold lines, recovered-vs-injected
scatter, test-F1 bars with no-skill markers), a results table, split counts, thresholds, seed/commit, and
allowlisted download links.

---

## 6. Files changed / created

**New**
- `webapp/backend/research/{__init__,core,experiment,reports,jobs,run_experiment}.py`
- `webapp/backend/tests/test_research_experiment.py` (20 tests)
- `reports/injection_recovery/` and `reports/injection_recovery_smoke/`
- this report

**Modified**
- `webapp/backend/app.py` — imports + six routes (existing endpoints untouched)
- `webapp/frontend/src/App.tsx` — types, state, effect, four plots, table, downloads
- `webapp/frontend/src/App.css` — `.rec-*` styles

**Restored (not mine, formatting-only drift):** `scripts/phase8_build_dataset.py` was reverted to HEAD
after confirming `ast.dump` equality; the working tree now contains only intended changes.

---

## 7. Verification (actual)

```
webapp/backend>  python -m pytest tests -q          46 passed, 1 warning        exit 0
webapp/backend>  python -m ruff check .             All checks passed!          exit 0
webapp/frontend> npx tsc -b                         exit 0
webapp/frontend> npm run build                      exit 0 (2.68 s)
webapp/frontend> npm run lint                      0 errors, 1 pre-existing warning
```

Smoke experiment: 18 trials, 1.6 s, recovery 4/6 at 150 ppm and 6/6 at 300 ppm.
Full experiment: 140 trials, 8.35 s, results above.

API regression: all pre-existing routes still 200 (`/api/health`, `/api/project`, `/api/artifacts` 7/7,
`/api/ml-results`, both `/api/lightcurve/*`, `/api/transit-injection`), and the six new routes return 200
(artifact traversal 404).

Source integrity — unchanged against the pre-work baseline:

| File | SHA-256 (first 16) |
|---|---|
| `data/processed/kepler_kepler_10.csv` | `7dd1cb33d3dea710` |
| `data/processed/tess_kepler_10.csv` | `ac582c1cf89996ff` |
| `reports/phase5_dataset.json` | `f8ad47fb2a404b41` |
| `reports/phase5_features.csv` | `a2886bf9a47f2325` |
| `reports/phase5_results.json` | `a22734583ecc36fc` |
| `reports/results/phase4_block_bootstrap.json` | `d4e2de41a674c7c8` |

`git diff --check` exit 0. No commit, no push.

---

## 8. Commands

```powershell
# Backend deps used by the experiment (already in the project's root lockfile)
cd %USERPROFILE%\astronomy-ai\webapp\backend
.\.venv\Scripts\python.exe -m pip install scikit-learn matplotlib

# Run an experiment (writes reports/injection_recovery/)
.\.venv\Scripts\python.exe -m research.run_experiment --mode smoke
.\.venv\Scripts\python.exe -m research.run_experiment --mode full

# Tests / lint
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .

# Serve
.\.venv\Scripts\python.exe -m uvicorn app:app --reload --port 8000

# Frontend
cd %USERPROFILE%\astronomy-ai\webapp\frontend
npm run dev          # http://localhost:5173
npx tsc -b; npm run lint; npm run build
```

The UI can also trigger runs (`Run smoke` / `Run full`), which is the only path that writes artifacts from
the browser.

---

## 9. Limitations (read before quoting any number)

1. **Seven independent groups** (3 Kepler + 4 TESS chunks). Every percentage carries a wide Wilson interval;
   dataset/noise comparisons are exploratory.
2. **80% positive base rate** inflates F1. The no-skill column exists precisely so this cannot be mistaken
   for skill; ROC-AUC and per-depth recovery are the informative metrics.
3. **Threshold floor of 3σ** is partly a design choice; with 2–3 calibration controls the 95th percentile is
   itself noisy. Detection thresholds are identical (3.0) for all four dataset/noise strata.
4. **Recovered depth is biased high** among detections (135–360 ppm for 75–300 ppm requests): the threshold
   preferentially selects upward noise fluctuations, on top of the ~13% limb-darkening offset.
5. **Injection model is the project's fixed geometry** (a/R* = 3.4, i = 84.5°, u = [0.30, 0.20]), not fitted
   per chunk.
6. **The real transit is subtracted**, not masked; residual subtraction error contributes to noise.
7. **No browser automation is available.** Type-check, build, and API tests pass; the rendered UI was not
   clicked through. Manual checklist: AI Laboratory → status badge → Run smoke → watch progress → four
   plots render from artifacts → downloads work → Run full → existing Phase 5 panels and Phase 9 explorer
   still function.
8. **Synthetic only.** These results say nothing about real-planet detection performance.

## 10. Next research steps

- Raise chunk counts (more independent groups) and evaluate the physics detector at 25–75 ppm.
- Cross-validate thresholds per chunk (leave-one-chunk-out) instead of a single 3σ floor.
- Replace the 3σ floor with a calibrated false-alarm rate from a null distribution built by phase-scrambling.
- Feed the detector's S/N into the ML benchmark as a feature to test complementarity — separately, and only
  with nested selection to avoid the base-rate trap.
