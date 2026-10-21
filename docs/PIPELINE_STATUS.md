# Pipeline status — which script to run, and which artifacts are frozen

Meridian's analysis chain is the astronomy pipeline in this repository. Two generations of the synthetic
ML pipeline coexist by design. They produce the **same dataset** and the **same test metrics**; they
differ only in protocol hygiene. This page says which is which so nobody has to infer it from filenames.

---

## 1. Two chains, one dataset

| | Historical chain | Corrected chain |
|---|---|---|
| Build dataset | `scripts/phase5_build_dataset.py` | `scripts/phase8_build_dataset.py` |
| Features | `scripts/phase5_features.py` | `scripts/phase8_features.py` |
| Split | computed inside the evaluator from a global RNG (`np.random.seed(42)`) | `scripts/phase8_split.py`, written into the feature CSV |
| Evaluation | `scripts/phase5_baseline.py` | `scripts/phase8_eval.py` |
| Outputs | `reports/phase5_dataset.json`, `phase5_features.csv`, `phase5_feature_config.json`, `phase5_results.json`, `phase5_results.md` | `reports/phase8_dataset.json`, `phase8_features.csv`, `phase8_feature_config.json`, `phase8_results.json`, `phase8_results.md` |
| Status | **frozen** — reproduces the audited Phase 5 results exactly | **maintained** — use for new work |

The two builders agree window-for-window: both select the same 26 segments, inject the same depths
(75/150/225/300 ppm) and compute the same seven features from the flux actually presented to the
classifier. `phase5_build_dataset.py` reproduces `reports/phase5_dataset.json` byte-for-byte.

Filenames were not renumbered because the frozen JSON records its generator in `generated_by`; renaming
would make the provenance inside the artifact false.

---

## 2. Protocol differences (both documented, neither changes a reported metric)

| # | Historical | Corrected | Effect |
|---|---|---|---|
| 1 | `matched_filter_corr` imputed with the median over **all 26 rows**, test included (`phase5_features.py`) | median fitted on **train rows only** (`phase8_features.py`) | median 0.843895 → 0.787757; threshold 0.4405 → 0.4399; **no test metric changes** |
| 2 | RandomForest admitted by comparing its **validation** F1 with the baseline's **test** F1 (`phase5_baseline.py:155`) | validation vs validation (`phase8_eval.py`) | RF not selected in either run; corrected rule no longer peeks at test |
| 3 | Split recomputed per run from the legacy global RNG | split stored per row by `phase8_split.py`; identical assignment (`RandomState(42)`, 50/25/25) | 13 / 6 / 7 windows, disjoint parent groups — verified identical |

The Phase 8 re-run reproduces precision 0.75, recall 0.75, F1 0.75, ROC-AUC 0.667, PR-AUC 0.771 and the
confusion matrix `[[2,1],[1,3]]` exactly. Full analysis: `reports/phase8_ml_pipeline_audit.md`.

---

## 3. Frozen artifacts (do not regenerate in place)

| Artifact | SHA-256 | Guarded by |
|---|---|---|
| `reports/phase5_dataset.json` | `f8ad47fb…1da5d4` | `test_saved_dataset_matches_repaired_builder` (regenerates in a temp copy, compares) |
| `reports/phase5_features.csv` | `a2886bf9…d4cdf3` | `test_features_csv_*` schema/alignment tests |
| `reports/phase5_results.json` | `a2273458…199c68` | `test_split_sizes_are_consistent_with_dataset`, `test_results_declare_no_discovery_claim` |
| `reports/phase5_results.md` | `8443a7b5…f8d3d04` | — (UTF-8 since Phase 7) |
| `reports/results/phase3_transit_analysis.json` | `045073e2…72ea22` | — (Phase 3 scientific result) |
| `reports/results/phase4_block_bootstrap.json` | `d4e2de41…591df9` | — |
| `reports/results/phase4_injection_recovery.json` | `57b67864…65540f` | — |
| `reports/results/phase4_model_comparison.json` | `a8183377…1fee813` | — |

The Phase 3/4 hashes have been verified unchanged in every phase since Phase 6.

---

## 4. What to run

Reproduce the historical chain (writes over the frozen files — copy `reports/` first if you want them
preserved):

```powershell
.\.venv\Scripts\python.exe scripts\phase5_build_dataset.py
.\.venv\Scripts\python.exe scripts\phase5_features.py
.\.venv\Scripts\python.exe scripts\phase5_baseline.py
```

Run the corrected chain (defaults write the Phase 8 files; `--out` redirects anywhere):

```powershell
.\.venv\Scripts\python.exe scripts\phase8_build_dataset.py
.\.venv\Scripts\python.exe scripts\phase8_features.py
.\.venv\Scripts\python.exe scripts\phase8_eval.py
```

Verify everything:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v      # 28 passed
```

---

## 5. Test coverage map

| File | Guards |
|---|---|
| `tests/test_phase5_leakage.py` | labels, one window per parent segment, class balance, feature config, CSV schema/alignment, NaN imputation, split sizes, no-discovery wording |
| `tests/test_phase5_builder.py` | builder parses, top-level indentation, features use the presented flux, seed/split declarations, byte-identical regeneration of the frozen dataset |
| `tests/test_phase8_pipeline.py` | features come from the presented flux, extractor cannot see labels/depth, single extraction path, parent groups never cross splits, train-only imputation, deterministic rebuild |

---

## 6. Data dependency

Both chains read `data/processed/kepler_all_quarters_quality_masked.csv` (45,514 rows), which is
gitignored. Without it the builders skip and the dataset tests fail loudly rather than silently passing.
Provenance and the publication manifest are in `reports/phase7_reliability_audit.md` §7.
