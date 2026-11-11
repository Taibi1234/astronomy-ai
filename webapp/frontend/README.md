# Observatory frontend

React + TypeScript + Vite UI for the astronomy-ai demo. It renders processed light curves and
saved evaluation artifacts served by the FastAPI backend in `../backend`. It is a viewer only: it
does not compute, fit, or store scientific results.

## Commands

```powershell
npm install      # install dependencies
npm run dev      # dev server on http://localhost:5173
npm run build    # tsc -b && vite build -> dist/
npm run lint     # oxlint
npm run preview  # serve the production build
```

The backend is expected at `http://127.0.0.1:8000`; the base URL is hard-coded in `src/App.tsx`
(`const API`). The API allows CORS from `localhost:5173` and `localhost:5174`.

## Notes

- There are currently **no frontend unit tests**.
- `plotly.js` is imported as the full distribution, so the production bundle is about 4.96 MB
  (about 1.42 MB gzip) for three trace types. A partial bundle is a known follow-up, not a
  release blocker.
- The UI is read-only. The "Run smoke" / "Run full" controls appear only when the backend reports
  `runner_enabled: true` from `/api/health`; the public demo runs with the runner disabled.
- The Light Curves page needs the processed CSVs under `data/processed/`. They are excluded from
  Git, and the page shows an explicit message when they are missing.

See the repository root `README.md` §12 for setup, data prerequisites, and scientific scope.
