# Interactive Transit-Injection Visualizer

**Status:** implemented and tested. No research artifact, source CSV, or saved Phase 5 result was
modified. Backups of every edited file are timestamped in
`%TEMP%/webapp-backup-20261022-072423/`.

---

## 1. What was added

A new **Transit-injection explorer** panel at the bottom of the existing *AI Laboratory* page. It injects
a synthetic Kepler-10 b transit of the published geometry into a real observation window and shows the
original flux, the injected flux, and the residual — with measured diagnostics.

Existing Overview, Light Curves, Methodology, navigation, styling, and all five pre-existing API
endpoints are unchanged (verified: all still return HTTP 200).

---

## 2. Verified scientific inputs

Everything below was read from the repository, not assumed.

| Quantity | Value | Source |
|---|---|---|
| Orbital period | 0.837491225 d | `scripts/transit_analysis.py:58` |
| Transit epoch | 2454964.575 BJD_TDB | `scripts/transit_analysis.py:59` |
| Kepler time reference | BKJD = BJD_TDB − 2454833.0 | `scripts/transit_analysis.py:63` |
| TESS time reference | TJD = BJD_TDB − 2457000.0 | `scripts/transit_analysis.py:63` |
| a/R★ | 3.4 | `scripts/transit_analysis.py:66` |
| Inclination | 84.5° | `scripts/transit_analysis.py:67` |
| Limb darkening | quadratic, u = [0.30, 0.20] | `scripts/transit_analysis.py:68` |
| batman params | t0 = 0, ecc = 0, w = 90°, `limb_dark="quadratic"` | `transit_analysis.batman_curve` |
| Radius ratio | `rp = sqrt(depth_ppm × 1e-6)` | `scripts/phase5_build_dataset.py:89–90` |
| Injection formula | `injected = flux + median(flux) × (model − 1)` | `scripts/phase5_build_dataset.py:101–102` |

### Why the code is mirrored rather than imported

`scripts/transit_analysis.py` switches matplotlib to Agg and creates report directories **at import
time**; `scripts/phase5_build_dataset.py` has no `__main__` guard, so importing it re-runs the entire
dataset build and overwrites `reports/phase5_dataset.json`. Neither may run inside a request handler.
The two formulas are therefore mirrored in `webapp/backend/transit_injection.py`, with every constant
annotated by source line.

### Equivalence verified, not assumed

The same batman probe (depths 75/150/225/300 ppm, 2001-point grid) was run in both environments:

| Environment | batman dist | Python | numpy | Max abs difference vs research |
|---|---|---:|---|---:|
| Research venv | 2.5.3 | 3.11.17 | 2.4.6 | reference |
| Backend venv | 2.5.2 | 3.14.3 | 2.5.4 | **0.0e+00** |

Model minima were bit-identical for all four depths, so the backend reproduces the research physics
exactly. A golden value (`min(model) = 0.999829865082` at 150 ppm) is pinned in the tests as a regression
guard.

---

## 3. Algorithm

For one request:

1. Load the processed CSV (`time`, `normalized_flux`), coerce to numeric, drop non-finite rows, sort by
   time. Cached per file-version (`mtime_ns`) with read-only arrays; the source file is only ever read.
2. Enumerate ephemeris-predicted transit centres `t_k = (T0 − BJDREF) + k·P` that have ≥ 3 observations
   within ±0.1 d (±2.4 h).
3. Select the requested centre (or the first available one).
4. Build `dt = t_window − t_centre` and a batman model with the fixed geometry above, at
   `rp = sqrt(depth × 1e-6)`. Depth 0 short-circuits to an all-ones model.
5. `injected = flux_window + median(flux_window) × (model − 1)` on a **copy**.
6. Diagnostics from the arrays:
   - measured depth = `max(original − injected) × 1e6`
   - max |change| = `max|injected − original| × 1e6`

Because the injection only removes flux, those two numbers are equal by construction; the API returns both
and says so rather than implying two independent measurements.

### Requested vs measured depth — a real distinction worth showing

`depth_ppm` parameterises `rp²`. Limb darkening makes the central flux decrement larger:

| Requested | Measured (TESS, 2-min cadence) | Measured (Kepler, 29.4-min cadence) |
|---:|---:|---:|
| 0 | 0.00 ppm | 0.00 ppm |
| 75 | 85.07 ppm | — |
| 150 | 170.13 ppm | 169.51 ppm |
| 225 | 255.20 ppm | — |
| 300 | 340.26 ppm | — |

The ~13% excess is the limb-darkening weighting. The small Kepler deficit is cadence sampling: the
transit centre can fall between 29.4-minute exposures, so its measured depth is a lower bound. Both effects
are stated in the UI's limitations list.

---

## 4. API

`GET /api/transit-injection?mission=kepler|tess&depth_ppm=0|75|150|225|300&center_index=<int>`

- `depth_ppm` outside the five supported values → **422**
- unknown mission → **404** (matches the existing `/api/lightcurve` convention)
- `center_index` not in the returned `available_centers` → **422**
- returns only the ~10 (Kepler) to ~138 (TESS) window points, chronological, plus metadata

Response: `mission`, `target`, `dataset` (path, **sha256**, counts, window width), `time` (system,
definition, `axis_label`, BJD offset), `flux` (unit, axis label), `ephemeris`, `model` (all geometry and the
formula string), `center`, `available_centers`, `points` (`time`, `bjd_tdb`, `original`, `injected`,
`difference_ppm`), `diagnostics` (requested/measured depth, definition, limitations), and a
`scientific_notice`. All API strings are ASCII for safe logging.

---

## 5. UI

Inside *AI Laboratory*, below the saved Phase 5 metrics and independent of their loading state:

- **Controls:** dataset (Kepler Q0 / TESS S14), depth (0/75/150/225/300 ppm), transit centre (populated from
  `available_centers`, showing system time and point count), display mode (original / injected /
  comparison), and **Reset controls**.
- **Charts:** Plotly (the project's existing dependency) — main chart with both traces in comparison mode
  (legend toggling, zoom, pan, scroll zoom, hover with time + BJD + flux), and a dedicated residual chart of
  injected − original in ppm with a zero line.
- **Diagnostics:** requested depth, measured depth, max |change|, observation count, plus dataset path,
  time system, transit centre with ephemeris cycle, model geometry, and the source SHA-256 prefix.
- **States:** loading message, error banner with **Retry**, empty-window message, disabled centre selector
  until data arrives.
- **Styling:** existing dark palette and `ml-*` classes; new `ti-*` classes are scoped to this panel so the
  other pages are visually untouched.

`comparison` plots two traces; the residual is a separate, always-visible series. The spec's phrase
"comparison and difference modes" was implemented as "three display modes + a dedicated difference panel"
rather than a fourth mode, since the required control list names three.

---

## 6. Files

| File | Change |
|---|---|
| `webapp/backend/app.py` | modified — imports; new `/api/transit-injection`; cached file SHA-256 helper |
| `webapp/backend/transit_injection.py` | **new** — shared model/injection/centres/loader (mirrors research code) |
| `webapp/backend/conftest.py` | **new** — puts the backend on `sys.path` for tests |
| `webapp/backend/tests/test_transit_injection.py` | **new** — 25 tests |
| `webapp/frontend/src/App.tsx` | modified — types, state, effect, traces, explorer JSX |
| `webapp/frontend/src/App.css` | modified — scoped `ti-*` styles |
| `reports/phase9_transit_injection_visualizer.md` | **new** — this report |

Backups (pre-edit): `app.py`, `App.tsx`, `App.css` in
`%TEMP%/webapp-backup-20261022-072423/`.

---

## 7. Test results (actual)

```
webapp/backend> python -m pytest tests -q
25 passed, 1 warning in 2.32s        exit 0
```

The single warning is Starlette's deprecation notice about `httpx` in `TestClient` — not from this feature.

Covered: zero-depth identity · nonzero injection changes only in-transit samples and never raises flux ·
model matches the research batman value · limb-darkening depth ratio · measured depth recomputed from the
returned arrays · difference series consistency · point/observation counts · unsupported depths (×5),
unknown mission, unknown centre → rejected · centre acceptance/echo · ephemeris centre times and BJD
conversion per mission · chronological bounded points · non-finite rows excluded · empty window ·
source CSV byte-identical after requests · reported checksum matches the file · full response contract.

```
webapp/frontend> npx tsc -b           exit 0
webapp/frontend> npm run build        exit 0   (built in 3.56s; pre-existing large-chunk warning)
webapp/frontend> npm run lint         exit 0   1 warning (pre-existing set-state-in-effect, line ~220)
```

Regression check — all endpoints still serve:

```
200 /api/health · 200 /api/project · 200 /api/artifacts (7/7 available)
200 /api/ml-results · 200 /api/lightcurve/kepler · 200 /api/lightcurve/tess
200 /api/transit-injection?mission=kepler&depth_ppm=225
```

Research data unchanged after all runs:

| File | SHA-256 (first 16) |
|---|---|
| `data/processed/kepler_kepler_10.csv` | `7dd1cb33d3dea710` |
| `data/processed/tess_kepler_10.csv` | `ac582c1cf89996ff` |
| `reports/phase5_dataset.json` | `f8ad47fb2a404b41` |
| `reports/phase5_features.csv` | `a2886bf9a47f2325` |
| `reports/phase5_results.json` | `a22734583ecc36fc` |

---

## 8. Limitations and unverified items

1. **No browser automation is available in this environment.** The UI was type-checked, built, and its API
   contract is tested, but no rendered screenshot or click-through was performed. Manual checklist:
   open AI Laboratory → change dataset/depth/centre/mode → confirm traces change, legend toggles, residual
   updates, Reset restores defaults, and the error banner appears when the backend is stopped.
2. **Injection target differs from Phase 5.** Phase 5 injected into *detrended* flux inside randomly
   centred 6-hour windows. This explorer injects into the *stored* processed flux inside transit-centred
   windows. The formula and geometry are identical; the baseline is not detrended, so the visual result is
   not a reproduction of the saved Phase 5 experiment (stated in the API and UI).
3. **No quality mask is applied** — these CSVs carry only `time` and `normalized_flux`, with no quality
   column. Non-finite rows are dropped instead; this is documented, not glossed over.
4. **Measured depth is a sampled quantity**, and the Kepler 29.4-minute cadence under-samples the transit
   centre. Values are reported as measured, not extrapolated.
5. **batman patch-level differs between venvs** (2.5.2 backend vs 2.5.3 research). Verified numerically
   identical for this configuration; the backend venv needed `setuptools` for batman's `distutils` import on
   Python 3.14.
6. **New backend dependencies** (no requirements file exists for the webapp):
   `batman-package==2.5.2`, `setuptools`; plus `pytest` and `httpx` for tests. `batman` is imported at
   module import, so the API fails fast at startup if it is missing.
7. **No model is trained, no performance is claimed, and the injected points are labelled "simulated"** in
   the legend, notice, and chart title.

---

## 9. Commands

Backend:

```powershell
cd %USERPROFILE%\astronomy-ai\webapp\backend
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install "batman-package==2.5.2" setuptools pytest httpx   # once
.\.venv\Scripts\python.exe -m uvicorn app:app --reload --port 8000
```

Frontend:

```powershell
cd %USERPROFILE%\astronomy-ai\webapp\frontend
npm install          # once
npm run dev          # http://localhost:5173
```

Checks:

```powershell
cd %USERPROFILE%\astronomy-ai\webapp\backend
.\.venv\Scripts\python.exe -m pytest tests -q

cd %USERPROFILE%\astronomy-ai\webapp\frontend
npx tsc -b
npm run lint
npm run build
```
