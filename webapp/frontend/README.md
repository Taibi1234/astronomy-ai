# Observatory frontend

React + TypeScript + Vite UI for the astronomy-ai demo. It renders processed light curves and saved evaluation artifacts. The same source supports two modes:

- **Local full-stack mode:** reads the FastAPI backend in `../backend` at `http://127.0.0.1:8000`.
- **Static GitHub Pages mode:** reads pre-exported JSON and allowlisted artifacts from `public/api`; no backend or scientific execution is available.

Public demo: <https://taibi1234.github.io/astronomy-ai/>

## Requirements

- **Node.js 22 or newer** — required by the installed Plotly dependency chain.
- For local full-stack mode, the FastAPI backend running at `http://127.0.0.1:8000`.
- For regenerating the static export, Python with `../backend/requirements-web.txt` installed.

## Local full-stack commands

```powershell
npm ci           # reproduce the lockfile exactly
npm run dev      # dev server on http://localhost:5173
npm run lint     # oxlint
npm run build    # tsc -b && vite build -> dist/
npm run preview  # serve the production build
```

Use `npm install` only when intentionally updating dependencies; ordinary setup and CI use `npm ci`.

Set `VITE_API_BASE_URL` only when intentionally using a different local API address. The default remains `http://127.0.0.1:8000`. The backend allows CORS from ports 5173 and 5174 on localhost/127.0.0.1.

## Static GitHub Pages build

From the repository root, install the read-only export dependencies once:

```powershell
py -3.12 -m venv .venv-pages
.\.venv-pages\Scripts\python.exe -m pip install -r webapp\backend\requirements-web.txt
.\.venv-pages\Scripts\Activate.ps1
cd webapp\frontend
npm run build:pages
npm run preview -- --mode pages
```

`npm run build:pages` calls `scripts/export_static_webapp.py` before compiling the site. The exporter:

- calls only existing read-only backend handlers;
- reads the bundled demonstration CSVs and saved reports;
- exports every mission/depth/transit-centre combination used by the injection explorer;
- copies only the backend's allowlisted recovery downloads;
- never trains a model, runs a campaign, accesses sealed test quarters, or rewrites source data.

The Pages build uses relative assets and `VITE_STATIC_DATA=true`. Its data status reads **STATIC DATA**, all experiment runner controls remain hidden, and non-GET API requests are refused by the static adapter. The public deployment is handled by `.github/workflows/pages.yml`.

The production site also includes an installable web-app manifest and a network-first service worker for offline fallback after a successful visit.

## Verification and limitations

- The production build and lint pass under Node 22. Oxlint reports one non-blocking `react(set-state-in-effect)` warning in `App.tsx` and no errors.
- There are currently **no frontend unit tests**; browser behavior has a dated manual acceptance report in `reports/phase10_browser_acceptance.md`.
- The full Plotly distribution produces an approximately **4.96 MB** JavaScript bundle (**1.51 MB gzip** in the audited build). A partial bundle is a possible optimization, not a correctness fix.
- "Run smoke" / "Run full" controls appear only when the local `/api/health` reports `runner_enabled: true`. They never appear in the static Pages build.
- The Light Curves page uses the two bundled demo CSVs: `kepler_kepler_10.csv` and `tess_kepler_10.csv`. Other processed analysis CSVs remain gitignored.
- Static exports are copies of committed artifacts. After intentionally changing a source artifact, regenerate the static site with `npm run build:pages`; do not hand-edit generated JSON.

See the repository root `README.md` §12 for setup, provenance, and scientific scope.
