"""Phase 4 — Residual diagnostics (step 2 of Decision B).
Uses original time ordering; examines autocorrelation, segment scatter,
stationarity checks for block-bootstrap design.
"""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
RESULTS = ROOT / "reports" / "results"

df_all = pd.read_csv(DATA / "kepler_all_quarters_quality_masked.csv")
time = df_all["time"].to_numpy(float)
flux = df_all["normalized_flux"].to_numpy(float)

# Residuals: approximate by subtracting the phase-3 fitted model (approximate for diagnostic only)
# For diagnostics we don't need perfect model reconstruction — we examine scatter patterns.
# We split by >1 d gaps (same policy as detrending) to assess stationarity.
splits = np.where(np.diff(time) > 1.0)[0] + 1
segments = np.split(np.arange(len(time)), splits)
print(f"Segments (gap >1d): {len(segments)}")
for i, seg in enumerate(segments):
    if len(seg) < 10:
        continue
    fseg = flux[seg]
    print(
        f"  Seg {i:2d}: n={len(seg):6d} mean={fseg.mean():.4f} std={fseg.std():.5f} "
        f"min={fseg.min():.4f} max={fseg.max():.4f}"
    )

# Autocorrelation on full series (no phase folding)
resid_approx = flux - np.median(flux)  # rough centered residual for AC check
for lag in [1, 5, 10, 29, 58, 100]:
    if lag < len(resid_approx):
        r = np.corrcoef(resid_approx[:-lag], resid_approx[lag:])[0, 1]
        print(f"  AC lag {lag:3d} ({lag * 29.4 / 60:.2f}h): r={r:.4f}")
print(
    "Note: residuals not fully reconstructed; AC is on centered flux as proxy. Full bootstrap "
    "uses fitted-model residuals."
)
