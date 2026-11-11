# Phase 11 B7 — Commit Plan and Security Review (`fit_real`)

Repository: `C:\Users\5CA\astronomy-ai`, branch `main`, HEAD `230c5ae8c26b87abd719c09548a23beab8f37222`,
0 staged. **Nothing was staged, committed or pushed, no model was fitted, no trial generated.**

## 1. Status recap

| Item | Value |
|---|---|
| `research/phase11_b7.py` | `88cd7ac1f0f1034af86f29ab5d0941458f94b5e75be75669f0e1e336d7cc4974`, 516 lines |
| `tests/test_phase11_b7.py` | `482c86f99074a0272ee5b230b03f212b5383c1ee899b63fc11393e901ed71e3b`, 433 lines |
| Focused tests (re-run for this review) | **27 passed** (12.9 s), synthetic fixtures only |
| Untouched by B7 | B1 `963550a0…`, B2 `683b800b…`, B3 `94a51884…` — synthetic guards byte-identical |
| Protected artifacts | 21/21 byte-identical |
| Readiness | `campaign_ready = false`, `execution_ready = false` |
| New fitted/campaign output | none; the only fitted artifacts are the two historical smoke directories, unchanged |

## 2. Proposed commit groups (exact)

A single baseline commit is recommended, because `fit_real` cannot run until the tree is clean and
the frozen inputs it verifies are committed. Groups below are for review ordering.

**G1 — `fit_real` implementation and its direct dependencies (essential).** 18 files under
`webapp/backend/research/`: `phase11_b7.py` (new), plus the modules it imports or that the harness
needs: `phase11_b1.py`, `phase11_b2.py`, `phase11_b2a.py`, `phase11_b3.py`, `phase11_b5.py`,
`phase11_b6.py`, `phase11_v2.py`, `phase11_runner.py`, `features.py`, `safeguards.py`,
`test_access.py`, `errors.py`, `experiment.py`, `jobs.py`, `reports.py`, `run_experiment.py`,
`run_phase11_v2.py`. Also `webapp/backend/app.py`.

**G2 — tests (essential to review the contract).** 20 files under `webapp/backend/tests/`:
`test_phase11_b7.py` (new) plus `test_phase11_{access_closure,b0_resolution,b1,b2,b2a_builder,b2a_extraction,b3,b4,b5,b6,protocol_repin,stage3_safeguards,stage4_guards,stageA_runner,stageB_readiness,v2_review,v2_stage2}.py`,
`test_research_experiment.py`, `test_transit_injection.py`.

**G3 — protocol and frozen inputs (essential).** The nine frozen inputs are already tracked; only the
protocol lineage and sidecars are new: `reports/phase11_generalization/protocol_v2.json`,
`protocol_v2.sha256`, `protocol_v2_1.json`, `protocol_v2_1.sha256`, `protocol_v2_2.json`,
`protocol_v2_2.sha256`, `protocol_v2_3.json`, `protocol_v2_3.sha256` (8 files). Do **not** re-add
`split.json`, `windows_primary.json`, `windows_sensitivity.json`, `null_library.json`,
`experiment_config.json`, `offsets.json`, `offsets.sha256`, `protocol.json`, `protocol.sha256`
(already tracked at HEAD).

**G4 — historical smoke and quarantine evidence (recommended, not required by `fit_real`).**
`reports/phase11_generalization/smoke/{fitted.json,fitted.sha256,model.pkl,trials_fit.csv}` and the
same four under `smoke_invalid_scope_20261022/`. These are 8 of the 21 protected artifacts; committing
them freezes the baseline the hash checks compare against. No new smoke artifact is created here.

**G5 — reports (recommended).** `reports/phase11_*.md` (16 files, including the four B7 records and
this plan), `reports/phase9_transit_injection_visualizer.md`, `reports/phase10_*` (3 markdown +
`phase10_browser_acceptance_figures/` 5 PNGs), `reports/injection_recovery/` (10 files) and
`reports/injection_recovery_smoke/` (10 files). They are the audit trail for every earlier stage.

**G6 — frontend (separate concern, same baseline).** 21 files under `webapp/frontend/`: `.gitignore`,
`.oxlintrc.json`, `README.md`, `index.html`, `package.json`, `package-lock.json`, `public/{favicon,icons}.svg`,
`src/{App.css,App.tsx,index.css,main.tsx}`, `src/assets/{hero.png,react.svg,vite.svg}`, `tsconfig{,.app,.node}.json`,
`vite.config.ts`. `node_modules/` and `dist/` are ignored by `webapp/frontend/.gitignore` (verified with
`git check-ignore`) and must stay out.

**G7 — pre-existing tracked user modifications (preserve, commit).**
`webapp/backend/research/generalization.py`, `phase11.py`, `run_phase11.py` (currently `M`).

**Excluded from the commit.**
`webapp/backend/app.py.20261022-075927.bak`, `app.py.20261022-174257.bak`,
`webapp/frontend/src/App.css.20261022-071618.bak`, `App.tsx.20261022-071618.bak` (editor backups);
`data/raw/*`, `data/processed/*` (ignored; 4.8 MB Kepler CSVs); `.venv/`, `__pycache__/`,
`.pytest_cache/`, `.ruff_cache/`; `webapp/frontend/node_modules/`, `webapp/frontend/dist/`.

**What reviewers need.** G1+G2+G3 are sufficient to reproduce and review `fit_real` (code, tests,
pinned protocol). G4 keeps the protected-artifact baseline meaningful; G5 is provenance; G6 is
unrelated to fitting and could be committed separately if the owner prefers a smaller first commit.
Nothing in the commit writes or reads test data.

## 3. Security review of `phase11_b7.py` and its tests

**Verified sound**

- *No test-data access.* No test quarter is ever turned into a path: `load_fit_series` validates the
  quarter against `^Q\d{2}$`, refuses anything outside the fit set **before** building a path, and the
  tests assert both the refusal (`Q02`) and the invalid-identifier refusal (`../Q00`). Test windows are
  classified out by `_classify_window`; the plan and frame guards reject `test` splits, non-fit
  quarters, foreign roles and the `real-campaign-v2` tag.
- *No traversal.* The filename is built from a validated quarter; `root` is only joined, never
  interpolated with caller text.
- *Test-artifact exposure.* `fit_real` refuses to run when the output directory or its parent holds
  `trials_test.csv`, `test_access.json`, `test_generation.json` or `metrics_test.json`; a test proves
  the fitter is never reached in those cases.
- *Authorization.* Eight fields plus an exact fit-quarter set and protocol pin; a test quarter in the
  list is refused. `single_run_ack` must be `True`.
- *No weakening of the synthetic path.* B1/B2/B3 are byte-identical to their reviewed hashes; a test
  proves `b1.assert_synthetic_frame` still refuses the real-tagged frame.
- *Tests use synthetic fixtures only* — the frame is `b2a.build_fit_split_frame` output re-tagged; the
  only real file reads are the frozen manifests and the two probes documented in the B7 report.

**Findings — status after the hardening patch**

Findings 1–3 below were closed by a focused patch: `phase11_b7.py` now verifies each fit-quarter
CSV against the SHA-256 (and row count where pinned) in the frozen split manifest, refuses symlinked
quarter files and data-root escapes, and resolves the output path and its parent before the
exposure check. `research/phase11_b7.py` is now `4f16076d…` and `tests/test_phase11_b7.py` is
`990062ec…` with 44 focused tests. Finding 4 (unsigned authorization) remains open as design debt.

**Original findings (record) for review**

1. **Quarter-file hash is not verified (high).** `split.json` already pins each quarter's `sha256`
   and `rows`, but `load_fit_series` parses whatever sits at
   `root/data/processed/kepler_qNN_quality_masked.csv`. A swapped, tampered or symlinked file would be
   silently fitted. Recommended fix (small): hash the file and compare with `split.json[quarter]["sha256"]`
   before `gen.load_quarter`, refusing on mismatch; add a test that a modified copy is refused.
2. **No resolved-path containment (medium).** `data/processed` itself could be a symlinked directory.
   Combined with (1) the hash check blocks substituted content; additionally resolve the path and
   require it to stay under `root/data/processed`. Add a temp-dir symlink test.
3. **Exposure check precedes path resolution (low).** `_assert_no_test_exposure` inspects the
   unresolved `out_dir` and its parent; `resolve_output_dir` then refuses campaign state, so the gap is
   narrow, but resolving first and checking the resolved path and its real parent would close it.
4. **Authorization is an unsigned dict (design debt, not a defect).** Anyone able to call the function
   can satisfy the fields; binding to the OD-2 hashed document and its `campaign_id` is still pending.

Items 1–2 should be closed before the commit is made; 3 can be closed in the same pass; 4 is the
known owner decision.

## 4. Verification performed

| Check | Result |
|---|---|
| `pytest tests/test_phase11_b7.py -q` | 27 passed (12.9 s) |
| 21 protected artifact hashes | 21/21 byte-identical |
| `protocol_v2_3.json` | `e1dc5cc9…c154`; `campaign_ready = false`, `execution_ready = false` |
| New fitted artifacts / campaign output | none (only the historical smoke directories hold fitted files) |
| `git diff --check` | clean; 0 staged; HEAD unchanged; every earlier modification and untracked file preserved |
| Secrets scan (untracked text files) | no hits; no `.env` present |

## 5. Unresolved concerns

1. Findings 1–2 above (quarter hash, path containment) are open until fixed; they are the only items I
   would consider blocking for a *baseline* commit that a real run will later rely on.
2. `fit_real` cannot be exercised on real quarters until the tree is committed and clean
   (`require_clean_tree`), so end-to-end validation remains pending.
3. Real test generator, denominator-literal enforcement and the authorization document (B7 D1/D3/D5)
   are still unimplemented; `fit_real` produces only the fitted state.
