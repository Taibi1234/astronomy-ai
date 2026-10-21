"""Phase 4 — Residual time-block bootstrap (Decision B, step 3).

Design choices (documented for review):
- Residuals come from the detrended transit-model fit on the full Kepler dataset
  (same config as Phase 3 headline: kepler_all_masked / detrended, ±6 h window).
- Block length sensitivity: tested at 10, 50, 100, 200, 500 cadences.
  Justification: AC remains high at ~50 h (r~0.44); blocks must exceed that.
- Residual resampling strategy: preserve time correlations by resampling
  CONTIGUOUS blocks of fitted-model residuals (not independent points), then
  add back to fitted model and re-fit.
- Stationarity evaluation: residual scatter differs across quarters (confirmed
  in diagnostics); we use a SEGMENT-AWARE approach: blocks drawn within
  contiguous segments (split at >1 d gaps) rather than across quarter
  boundaries, preventing nonstationary mixing.
- Reproducible: fixed random seed (numpy Generator with seed 42), block
  selection with replacement within each segment proportionally.
- Model re-fit for each replicate: same least_squares bounds/initial conditions.
- Uncertainty intervals reported for depth (rp^2) and t0 offset.
- Convergence: each replicate must have fit.success == True; failures reported.

Limitations reported in output (required):
- Residual resampling assumes fitted-model structure is correct; misspecified
  trends will propagate.
- Adding resampled residuals back to fitted model preserves mean but may not
  reproduce long-range correlation structure exactly.
- Block bootstrap does not account for parameter-dependence in model form.
"""

import json
import time
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
RESULTS = ROOT / "reports" / "results"
FIGURES = ROOT / "reports" / "figures"

# Import from Phase 3 script (same code path, preserved unchanged)
import importlib.util  # noqa: E402 - imported after path setup by design
import sys  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "transit_analysis", ROOT / "scripts" / "transit_analysis.py"
)
mod = importlib.util.module_from_spec(spec)
# Need minimal setup without running main()
sys.path.insert(0, str(ROOT))
# Instead, replicate the key functions inline to avoid importing and running
from scripts.transit_analysis import (  # noqa: E402 - requires sys.path setup above
    A_OVER_RSTAR,
    BJDREF,
    INCLINATION_DEG,
    PERIOD,
    TRANSIT_EPOCH_BJD,
    U1,
    U2,
    WINDOW_HOURS_DEFAULT,
    batman_curve,
    detrend_poly,
    fit_transit,
    fold_phase,
    load_dataset,
)

# Load dataset
spec_all = {
    "path": DATA / "kepler_all_quarters_quality_masked.csv",
    "mission": "kepler",
    "variants": ["raw", "detrended"],
}
time_all, flux_all = load_dataset(spec_all)
bjdref = BJDREF["kepler"]
phase_all = fold_phase(time_all, PERIOD, TRANSIT_EPOCH_BJD, bjdref)

# Detrend (same as headline config) and fit once for reference
flux_dt, trend = detrend_poly(time_all, phase_all, flux_all)
window = np.abs(phase_all) <= WINDOW_HOURS_DEFAULT / 24
ref_fit = fit_transit(phase_all[window], flux_dt[window])

# Full-series fitted model for residual computation
model_all = ref_fit["baseline"] * batman_curve(
    phase_all,
    ref_fit["rp"],
    ref_fit["t0_offset_minutes"] / (24 * 60),
    A_OVER_RSTAR,
    INCLINATION_DEG,
)
# Note: slope component omitted for simplicity in full-series; residual is approximate
resid_all = flux_dt - model_all

# Block-bootstrap design parameters
SEED = 42
BLOCK_LENGTHS = [10, 50, 100, 200, 500]  # cadences; ~4.9 min to ~10.2 days
N_REPLICATES = 200  # defensible for sensitivity

# Split at >1 d gaps for segment-aware resampling
split_points = np.where(np.diff(time_all) > 1.0)[0] + 1
segments_time_idx = np.split(np.arange(len(time_all)), split_points)
segments_resid = np.split(resid_all, split_points)

results_by_blocklen = {}
print(
    f"Reference depth: {ref_fit['depth_ppm']:.2f} ppm  t0_offset: "
    f"{ref_fit['t0_offset_minutes']:+.2f} min"
)
print(f"Segments for resampling: {len(segments_resid)}")
print(f"Block lengths (cadences): {BLOCK_LENGTHS}")
print(f"Replicates: {N_REPLICATES}")

for bl in BLOCK_LENGTHS:
    bl_label = int(bl)
    rng = np.random.default_rng(SEED + bl_label)  # separate seed per block length
    depths = []
    t0s = []
    converged = 0
    failed = 0
    start = time.time()
    for _rep in range(N_REPLICATES):
        # Build synthetic series by resampling blocks WITHIN each segment
        synthetic = np.zeros_like(flux_dt)
        # We reconstruct by adding resampled residual blocks back to fitted model
        # For simplicity: synthetic = model + resampled residual (block-level)
        synthetic_resid_blocks = []
        for seg_res in segments_resid:
            seg_len = len(seg_res)
            if seg_len < bl:
                # If segment shorter than block, use whole segment (no resampling within)
                synthetic_resid_blocks.append(seg_res.copy())
                continue
            # Number of blocks needed to cover segment (with overlap/replacement)
            n_blocks = max(1, int(np.ceil(seg_len / bl)))
            # Resample blocks with replacement from this segment's residuals
            start_positions = rng.integers(0, max(1, seg_len - bl), size=n_blocks)
            block_parts = []
            for s in start_positions:
                end = min(s + bl, seg_len)
                block_parts.append(seg_res[s:end])
            # Concatenate and trim to original segment length
            concat = np.concatenate(block_parts)
            synthetic_resid_blocks.append(concat[:seg_len])
        synthetic_resid = np.concatenate(synthetic_resid_blocks)
        # Ensure same length as original
        synthetic_resid = synthetic_resid[: len(flux_dt)]
        synthetic_flux = model_all + synthetic_resid
        # Re-fit on same window
        phase_syn = phase_all  # time unchanged (same ordering preserved)
        window_syn = np.abs(phase_syn) <= WINDOW_HOURS_DEFAULT / 24
        try:
            fit_syn = fit_transit(phase_syn[window_syn], synthetic_flux[window_syn])
            if fit_syn["converged"]:
                converged += 1
                depths.append(fit_syn["depth_ppm"])
                t0s.append(fit_syn["t0_offset_minutes"])
            else:
                failed += 1
        except Exception:
            failed += 1
    elapsed = time.time() - start
    depths = np.array(depths)
    t0s = np.array(t0s)
    if len(depths) > 0:
        print(
            f"  BL={bl:4d}: n_conv={converged} n_fail={failed} depth_mean={depths.mean():.1f} ppm "
            f"std={depths.std():.1f} 95%=[{np.percentile(depths, 2.5):.1f}, "
            f"{np.percentile(depths, 97.5):.1f}] "
            f"t0_mean={t0s.mean():+.2f} min  ({elapsed:.1f}s)"
        )
    results_by_blocklen[bl_label] = {
        "n_replicates": N_REPLICATES,
        "n_converged": int(converged),
        "n_failed": int(failed),
        "block_length_cadence": int(bl),
        "block_length_hours": float(bl * 29.4 / 60),
        "depth_ppm_mean": float(np.mean(depths)) if len(depths) else None,
        "depth_ppm_std": float(np.std(depths)) if len(depths) else None,
        "depth_ppm_95_interval_ppm": [
            float(np.percentile(depths, 2.5)),
            float(np.percentile(depths, 97.5)),
        ]
        if len(depths)
        else [None, None],
        "t0_offset_mean_min": float(np.mean(t0s)) if len(t0s) else None,
        "t0_offset_std_min": float(np.std(t0s)) if len(t0s) else None,
        "seed": SEED,
    }

# Write results
out = RESULTS / "phase4_block_bootstrap.json"
out.write_text(
    json.dumps(
        {
            "method": "residual time-block bootstrap (segment-aware, replacement)",
            "limitations_documented": (
                "Residual resampling assumes fitted-model structure is correct; misspecified "
                "trends propagate. "
                "Adding resampled residuals back preserves mean but not full long-range "
                "correlation. "
                "Not calibrated as formal detection significance (re-detection exercise only)."
            ),
            "assumptions": [
                "Residuals approximated by fitted-model subtraction (detrended transit model).",
                "Blocks drawn WITHIN contiguous segments (split at >1d gaps), not across them.",
                "Segment-aware approach chosen due to nonstationary scatter (seg std varies "
                "0.00006-0.00047).",
            ],
            "reference_config": {
                "dataset": "kepler_all_quarters_quality_masked",
                "variant": "detrended",
                "window_hours": WINDOW_HOURS_DEFAULT,
                "fixed_geometry": {
                    "a_over_r": A_OVER_RSTAR,
                    "inc_deg": INCLINATION_DEG,
                    "u1": U1,
                    "u2": U2,
                },
            },
            "block_length_sensitivity": results_by_blocklen,
            "generated_by": "scripts/phase4_block_bootstrap.py",
        },
        indent=2,
    )
    + "\n"
)
print(f"\nResults: {out}")
