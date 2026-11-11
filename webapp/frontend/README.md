# Observatory frontend

React + TypeScript + Vite UI for the astronomy-ai demo. It renders processed light curves and
saved evaluation artifacts served by the FastAPI backend in `../backend`. Scientific execution is
disabled unless the backend operator explicitly enables the local runner.

## Requirements

- **Node.js 22 or newer** — required by the installed Plotly dependency chain.
- The FastAPI backend running at `http://127.0.0.1:8000`.

## Commands

```powershell
npm ci           # reproduce the lockfile exactly
npm run dev      # dev server on http://localhost:5173
npm run lint     # oxlint
npm run build    # tsc -b && vite build -> dist/
npm run preview  # serve the production build
```

Use `npm install` only when intentionally updating dependencies; ordinary setup and CI use `npm ci`.
The API base URL is `const API` in `src/App.tsx`. The backend allows CORS from ports 5173 and 5174 on
localhost/127.0.0.1.

## Verification and limitations

- The production build and lint pass under Node 22. Oxlint reports one non-blocking
  `react(set-state-in-effect)` warning in `App.tsx` and no errors.
- There are currently **no frontend unit tests**; browser behavior has a dated manual acceptance
  report in `reports/phase10_browser_acceptance.md`.
- The full Plotly distribution produces an approximately **4.96 MB** JavaScript bundle
  (**1.51 MB gzip** in the audited build). A partial bundle is a possible optimization, not a
  correctness fix.
- "Run smoke" / "Run full" controls appear only when `/api/health` reports `runner_enabled: true`.
  The default application is read-only, and the runner must not be exposed on a public network.
- The Light Curves page uses the two bundled demo CSVs: `kepler_kepler_10.csv` and
  `tess_kepler_10.csv`. Other processed analysis CSVs remain gitignored.

See the repository root `README.md` §12 for setup, provenance, and scientific scope.
