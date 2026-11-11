# Phase 10 Browser Acceptance Test

**Date:** 2026-10-22 · **HEAD:** `5ef9df6` · **Scope:** manual browser acceptance of the Phase 10
injection-recovery job UI and the Phase 9 transit-injection explorer, following the seven-step
checklist in [`phase10_audit.md`](phase10_audit.md) §6.

**Verdict:** the checklist is **7/7 exercised**, but only **5/7 passed unmodified**. Two genuine
integration defects that every API-level check had missed were found and fixed:

- **D4 (blocking):** the browser could not start an experiment at all — the CORS allowlist permitted
  only `GET`, so the `POST /run` preflight was rejected and the UI showed "Failed to fetch".
- **D5 (data correctness):** download links could serve the **previous run's** artifact from Chrome's
  heuristic cache, because artifact responses carried no `Cache-Control`.

Both are fixed, covered by regression tests, and re-verified in the same browser session. No
scientific code, threshold, source CSV, or saved result was modified; `reports/injection_recovery/`
was backed up before testing and restored byte-identically afterwards.

---

## 1. What was actually tested

| Item | Value |
|---|---|
| Frontend URL opened | **http://localhost:5173/** (Vite 8.3.5, bound to `[::1]:5173`) |
| API endpoint used by the page | **http://127.0.0.1:8000** (hard-coded at `webapp/frontend/src/App.tsx:238`) |
| Origin → API relationship | cross-origin (`localhost:5173` → `127.0.0.1:8000`), so CORS applies |
| API calls observed from the page | 10 GET requests across 7 endpoints on first load (health, project, artifacts, ml-results, transit-injection, recovery status, recovery results), 0 network failures |
| Browser | installed Google Chrome, `HeadlessChrome/155.0.0.0`, 1440×1000, DPR 1 |
| Driving mechanism | Chrome DevTools Protocol over a ~180-line Node script using only Node 24 built-ins (`WebSocket`, `fetch`); **no packages installed, no downloads** |
| Backend | `webapp/backend/.venv/Scripts/python.exe -m uvicorn app:app --reload --port 8000` (documented command) |
| Frontend | `npm run dev` (documented command) |
| Evidence | 5 screenshots in [`phase10_browser_acceptance_figures/`](phase10_browser_acceptance_figures/) |

This was a genuine browser test: the page's own React code issued every request, and every assertion
below was read from the live DOM or the page's own `fetch` calls — not from `curl`.

---

## 2. Checklist results

| # | Checklist step | Result | Observed |
|---|---|---|---|
| 1 | Start backend + frontend | **pass** | Both documented commands served normally; `GET /api/health` 200, page mounted React root |
| 2 | Status badge = `completed`, mode full, runtime, finish time | **pass** | `COMPLETED` + `mode full · 8.35 s · 2026-10-22T00:19:29+00:00` (screenshot `02b_recovery_panel.png`) |
| 3 | Click **Run smoke** → badge `running`, progress increments from real trials | **FAIL → pass after D4 fix** | Before fix: banner "Failed to fetch", nothing ran. After fix: `completed → running 9/18 trials · 50% → running 18/18 · 100% → completed · mode smoke · 2.08 s` |
| 4 | Click **Run smoke** again while running → 409 surfaces as "An experiment is already running." | **pass** (via timed second click) | Second click at +130 ms produced the banner **"An experiment is already running."**; the first run continued (`7/140 trials · 5%`), i.e. the duplicate was refused, not restarted |
| 5 | On completion: four charts, table, download links | **FAIL → pass after D5 fix** | 4 charts with expected titles, 4-row table, 11 artifact links. Before D5: links returned the *stale* full-run `summary.json` (10 896 B, `mode full`) after a smoke run; after D5: every link byte-matched disk |
| 6 | Stop backend → Refresh shows error banner; existing charts remain | **pass** | Red banner "Failed to fetch"; all 4 charts, 4 table rows, 11 links and metric cards still rendered; console showed `net::ERR_CONNECTION_REFUSED` (screenshot `06_backend_down_error.png`). After restarting the backend and pressing Refresh the banner cleared and the badge returned to `completed` |
| 7 | Existing Phase 5 panels and Phase 9 explorer still work | **pass** | Phase 5: F1 0.750, ROC-AUC 0.667, P/R 0.750, confusion `[[2,1],[1,3]]`, PR-AUC 0.771, feature table present. Explorer: mission `kepler`→`tess` (checksum `ac582c1c…`, TJD−2457000, 17 722 obs), depth 150→300 (measured 169.5→340.3 ppm), centre cycle −13→−5 (BJD 2454960.38754, matches API), view mode `injected` (legend correctly hidden), **Reset controls** restores `kepler / 150 / −13 / comparison`. Overview and Light Curves pages also load without errors |

Numbers displayed by the UI on the restored full run matched the audited values exactly — e.g.
physics `0.578 / 0.844 / no-skill 0.889`, LR `0.889 / 0.680`, RF `0.555`, dummy `0.469`, splits
`train 60/3 · val 40/2 · test 40/2`, all four thresholds `3.00`
(screenshot `03c_full_table_downloads.png`).

### Download verification detail

All 11 links were resolved in-page with `fetch()`:

```
summary.json 200 application/json · config.json · provenance.json · plot_data.json
trial_results.csv 200 text/csv · recovery_report.md 200 text/markdown
recovery_vs_depth.png, control_snr.png, recovered_vs_injected.png, timing_error.png,
benchmark_f1.png — all 200 image/png
```

After the D5 fix, the sizes returned to the browser equalled the sizes on disk
(`summary.json` 10 897 B for the new full run; `trial_results.csv` 46 865 B; figures 18–30 KB).

---

## 3. Defects found and fixed

### D4 — CORS allowlist blocked the only browser write path (blocking)

| Evidence | Value |
|---|---|
| Preflight `OPTIONS /api/injection-recovery/run` | `400 Bad Request`, body `Disallowed CORS method`, `access-control-allow-methods: GET` |
| Browser console | `Access to fetch at 'http://127.0.0.1:8000/api/injection-recovery/run' from origin 'http://localhost:5173' has been blocked by CORS policy: Response to preflight request doesn't pass access control check: It does not have HTTP ok status.` |
| DevTools network | `OPTIONS` 400 → `net::ERR_FAILED`, `corsError: PreflightInvalidStatus` |
| User-visible effect | "Run smoke" / "Run full" showed the red banner **"Failed to fetch"** and no experiment started |

`app.py` allowed `allow_methods=["GET"]`, but `startRecovery` posts JSON
(`webapp/frontend/src/App.tsx:536`). Every HTTP-level backend test goes through `TestClient`, which
never performs a preflight, so 49 passing tests coexisted with a UI whose primary action could not
work.

**Fix** (`webapp/backend/app.py`): `allow_methods=["GET", "POST"]` with a comment naming the single
write path. `OPTIONS` is handled by the middleware; origins stay restricted to the four local dev
origins, so this does not widen the exposure to any new origin.

**Regression tests** (`webapp/backend/tests/test_research_experiment.py`):
`test_cors_preflight_allows_the_browser_to_start_a_run` (preflight 200, `POST` advertised, origin
echoed) and `test_cors_preflight_still_rejects_unused_methods_and_origins` (`DELETE` from an allowed
origin still 400; unknown origin still 400 with no `access-control-allow-origin`).

### D5 — artifact downloads could return the previous run's file

| Evidence | Value |
|---|---|
| Sequence | `Run smoke` completed (`summary.json` on disk 8 404 B, `mode smoke`); the UI's own download link then fetched **10 896 B of the earlier full run** (`mode: "full"`) |
| Control | same URL with a cache-busting query returned 8 404 B / `mode smoke` |
| Cause | `FileResponse` sent `ETag` + `Last-Modified` but no `Cache-Control`, so Chrome applied heuristic freshness and reused the stored response |

Every run rewrites the same paths, so this silently hands a user the wrong file — the same class of
staleness the audit fixed as D3 on the server side.

**Fix** (`webapp/backend/app.py`): artifact responses now carry `Cache-Control: no-cache`, so browsers
revalidate against the ETag instead of guessing. Verified end-to-end: after a new 140-trial run the
same URLs returned 10 897 B matching disk, with `cache-control: no-cache` on all 11.

**Regression test:** `test_artifact_download_is_not_heuristically_cached`.

---

## 4. Observations (not fixed — no defect justified)

1. **The 409 message is only reachable in a race.** Both run buttons are disabled while
   `status === "running"`, so a user cannot normally produce a duplicate request; the banner appeared
   only because a second click landed in the ~100 ms window before the status refetch. It is also
   **transient**: the next successful poll calls `setRecError("")` and the message disappears after
   ~2 s. The protection itself (409 at the API, disabled buttons in the UI) works.
2. **Error text is the browser-generic "Failed to fetch"** for both the recovery panel and the
   explorer. It conveys failure but not the endpoint or the cause; a message naming the API origin
   would help when the backend is down.
3. **A smoke run can finish before it is ever seen running.** Smoke takes ~2.1 s and the status poll
   interval is 2 s, so on a fast machine the `running` badge may never paint. Progress was observed
   as two increments (9/18, 18/18); the full run showed three (7/140, 122/140, 140/140).
4. **`uvicorn --reload` did not pick up `app.py` edits** on this Windows host: WatchFiles logged
   `Reloading...` and then the old worker kept serving the old code (still `allow_methods: GET`).
   The server was restarted manually; the final serving instance ran the documented command without
   `--reload`. This is a dev-tooling quirk, not an application defect.
5. **Job status is in-memory.** After a backend restart the UI is reconciled from artifacts
   (`"source": "artifacts"`), which behaved correctly here (`completed`, `mode full`, original
   `finished_at` returned).

---

## 5. Remaining limitations of this acceptance test

1. **Headless Chrome only.** One engine, one viewport (1440×1000, DPR 1). Firefox, Safari, headed
   Chrome, mobile widths, and keyboard/tab navigation were **not tested**.
2. **Downloads were verified by content, not by the OS save dialog.** Each link's `href` was fetched
   in the page context and byte-compared with disk; the browser's "save to Downloads folder"
   behaviour itself was not exercised.
3. **No automated test was added for the UI.** The browser session was scripted ad hoc from a temp
   directory (not committed). The two fixes are covered by backend tests; a committed Playwright-style
   suite would still be the durable guard, and Playwright is not installed.
4. **Timing-sensitive steps.** Step 4's duplicate click and step 3's progress sampling depend on
   timing; results above are what was observed on this machine, not a guarantee.
5. **Visual inspection is by screenshot** (`reports/phase10_browser_acceptance_figures/`), at
   downscaled-fidelity for the long full-page shot. Chart internals were confirmed through DOM titles
   and Plotly containers, not pixel assertions.

---

## 6. Environment, integrity, and regressions

### Commands executed

```
webapp/backend>  .venv/Scripts/python.exe -m uvicorn app:app --reload --port 8000     (port 8000)
webapp/frontend> npm run dev                                                          (bound [::1]:5173)
webapp/backend>  .venv/Scripts/python.exe -m pytest -q        52 passed, 1 warning      exit 0
webapp/backend>  .venv/Scripts/python.exe -m ruff check .     All checks passed!        exit 0
webapp/frontend> npx tsc -b                                   exit 0
webapp/frontend> npm run lint                                 0 errors, 1 pre-existing warning
webapp/frontend> npm run build                                built in 3.76 s           exit 0
```

### Runs triggered from the browser

| Mode | Trials | Runtime shown in UI | Outcome |
|---|---|---|---|
| smoke | 18 | 2.08 s | completed; 4 charts, 4-row table, 11 downloads |
| full | 140 | 12.62 s | completed; recovery@300 64%, FPs 0/8, physics ROC-AUC 0.844 |

(The 12.62 s run was slower than the audited 8.35 s because it shared the machine with the test
harness; the numbers it produced are unchanged.)

### Data integrity

| File | SHA-256 (first 16) | Status |
|---|---|---|
| `data/processed/kepler_kepler_10.csv` | `7dd1cb33d3dea710` | unchanged |
| `data/processed/tess_kepler_10.csv` | `ac582c1cf89996ff` | unchanged |
| `reports/phase5_dataset.json` | `f8ad47fb2a404b41` | unchanged |
| `reports/phase5_results.json` | `a22734583ecc36fc` | unchanged |
| `reports/phase5_features.csv` | `a2886bf9a47f2325` | unchanged |
| `reports/results/phase4_block_bootstrap.json` | `d4e2de41a674c7c8` | unchanged |

`reports/injection_recovery/` was copied to `%TEMP%/injection_recovery_backup_pretest` before any
UI-triggered run and restored afterwards; the UI then again reported `mode full · 8.35 s ·
2026-10-22T00:19:29+00:00`, i.e. the pre-test artifacts.

### Git

```
git status --porcelain   ?? reports/injection_recovery/            (pre-existing, untracked)
                         ?? reports/injection_recovery_smoke/      (pre-existing)
                         ?? reports/phase9_transit_injection_visualizer.md   (pre-existing)
                         ?? reports/phase10_audit.md               (pre-existing)
                         ?? reports/phase10_injection_recovery_benchmark.md (pre-existing)
                         ?? webapp/                                (untracked; contains this phase's fixes)
                         ?? reports/phase10_browser_acceptance.md  (this report)
                         ?? reports/phase10_browser_acceptance_figures/ (this report's evidence)
git diff --check         clean (exit 0)
```

`scripts/phase8_build_dataset.py` **was drifted again** at the start of this session (8 insertions /
28 deletions, line rewrapping only). `ast.dump(ast.parse(...))` was identical between `HEAD` and the
working copy, so it was restored with `git checkout --`; the file is clean at the end of this test.
Nothing was staged or committed.

### Files changed by this acceptance test

| File | Change |
|---|---|
| `webapp/backend/app.py` | D4: `allow_methods=["GET", "POST"]`; D5: `Cache-Control: no-cache` on artifact responses |
| `webapp/backend/app.py.20261022-174257.bak` | backup of `app.py` taken before the edits |
| `webapp/backend/tests/test_research_experiment.py` | 3 regression tests (POST preflight, method/origin rejection, no-cache headers) |
| `reports/phase10_browser_acceptance.md` | this report |
| `reports/phase10_browser_acceptance_figures/*.png` | 5 screenshots from the session |

No frontend source was modified; the two defects were both server-side and both invisible to
type-check, lint, build, and `TestClient`-based tests.

---

## 7. Recommendation

The Phase 10 UI is **accepted** on this browser and this machine, with the two fixed defects and the
limitations above. The blocking finding is worth recording beyond this report: the audit's earlier
"API verified, browser unverified" verdict hid a total failure of the UI's primary action, because
CORS is only exercised by a real browser. Any future endpoint that adds a non-`GET` method needs the
preflight path tested, and the committed test suite now covers the two cases that failed here.
