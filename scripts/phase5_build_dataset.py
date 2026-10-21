"""Phase 5 — Build synthetic labeled dataset for ML classification.

Labels come ONLY from the injection process (simulated = positive, depth=0 = negative).
Split is by parent contiguous segment (split at >1 d gaps) to prevent leakage.
No real-planet labels used.

Status: historical pipeline, kept because `reports/phase5_dataset.json` records this
script in its `generated_by` field. It reproduces that frozen artifact byte-for-byte.
The features are computed from the flux presented to the classifier (transit included
for positives); see reports/phase8_ml_pipeline_audit.md for why that is the correct
order. For new work use scripts/phase8_build_dataset.py, which also records the split
per row and fits imputation on train only.
"""

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
RESULTS = ROOT / "reports"

import sys  # noqa: E402 - imported after ROOT is defined

sys.path.insert(0, str(ROOT))
from transit_analysis import (  # noqa: E402 - requires sys.path setup above
    A_OVER_RSTAR,
    BJDREF,
    INCLINATION_DEG,
    PERIOD,
    TRANSIT_EPOCH_BJD,
    batman_curve,
    detrend_poly,
    fold_phase,
    load_dataset,
)

# Load full dataset
spec_all = {
    "path": DATA / "kepler_all_quarters_quality_masked.csv",
    "mission": "kepler",
    "variants": ["raw", "detrended"],
}
time_all, flux_all = load_dataset(spec_all)
bjdref = BJDREF["kepler"]
phase_all = fold_phase(time_all, PERIOD, TRANSIT_EPOCH_BJD, bjdref)
flux_dt, trend = detrend_poly(time_all, phase_all, flux_all)

# Split by contiguous segments (>1d gap)
splits = np.where(np.diff(time_all) > 1.0)[0] + 1
segments_idx = np.split(np.arange(len(time_all)), splits)

# Window extraction: 6-hour windows around phase 0 (transit region) with randomized offsets
# For simplicity: extract fixed windows centered on phase 0 from each segment
# Positive: inject depth in [75,150,225,300] ppm; Negative: depth 0
SEED = 42
rng = np.random.default_rng(SEED)
window_hours = 6.0  # same as analysis window

windows = []
labels = []  # 1 = transit injected, 0 = no transit
segment_ids = []

# Each segment produces exactly ONE window: either positive OR negative (not both).
# This ensures segment-level split works cleanly (same segment never in both classes).
# For simplicity, alternate positive/negative across segments.
for seg_idx in range(len(segments_idx)):
    seg = segments_idx[seg_idx]
    if len(seg) < 100:
        continue
    is_positive = seg_idx % 2 == 0
    # Pick a random index within segment for window center
    center_idx_in_seg = rng.integers(0, max(1, len(seg) - 50))
    center_time = time_all[seg[center_idx_in_seg]]
    # Define window around published ephemeris position (phase ~0)
    # For simplicity: use a 6-hour region around the time that corresponds to phase 0
    # We approximate by taking points within ±6h of center_time in the segment
    mask_window = np.abs(time_all[seg] - center_time) <= (window_hours / 24)
    window_points_idx = seg[mask_window]
    if len(window_points_idx) < 10:
        continue  # skip too-short windows
    # Get time/flux for this window
    win_time = time_all[window_points_idx]
    win_flux_raw = flux_all[window_points_idx]
    win_phase = phase_all[window_points_idx]
    # Detrend same way (re-run polyfit on this sub-window's out-of-transit points)
    # For simplicity: apply same detrending function to sub-array
    # Note: detrend_poly expects full arrays; we call with sub-arrays
    # Actually reuse detrend logic by passing sub-time/sub-phase/sub-flux
    # But detrend_poly uses phase for out-of-transit selection. We'll use the sub-phase.
    # Simplified: use pre-detrended full-series flux_dt and take same indices
    win_flux_dt = flux_dt[window_points_idx]
    # Synthetic injection for positive windows
    if is_positive:
        depth_ppm = float(rng.choice([75, 150, 225, 300]))
        rp_inj = np.sqrt(depth_ppm * 1e-6)
        # Center injection at phase 0 (t0=0)
        signal_model = batman_curve(win_phase, rp_inj, 0.0, A_OVER_RSTAR, INCLINATION_DEG)
        # Add noise from actual detrended residual (resample from full-series residual)
        resid_full_approx = win_flux_dt - np.median(win_flux_dt)
        # For synthetic: inject signal into median-normalized window
        synthetic = win_flux_dt.copy()
        # Apply transit model on top of the window's median-normalized base
        # The simplest injection: synthetic = synthetic * (signal_model / median(signal_model))
        # But since signal_model ~1 outside transit, this approximates multiplicative injection
        # More precise: synthetic = synthetic + (signal_model - 1.0) * median_flux
        median_w = float(np.median(win_flux_dt))
        synthetic = synthetic + median_w * (signal_model - 1.0)
    else:
        synthetic = win_flux_dt.copy()
    # Compute the 7 features from the flux the classifier actually sees (`synthetic`):
    # for positives that flux contains the injected transit; for negatives it is an
    # exact copy of win_flux_dt. Computing them from win_flux_dt would describe a
    # positive window by flux that no longer contains its own signal
    # (see reports/phase8_ml_pipeline_audit.md).
    features = {
        "depth_rel_ppm": float((np.median(synthetic) - np.min(synthetic)) * 1e6),  # approximate
        "contrast_ppm": float(
            (
                np.mean(synthetic[np.abs(win_phase) > 3 / 24])
                - np.mean(synthetic[np.abs(win_phase) <= 1.8 / 24])
            )
            * 1e6
        )
        if np.any(np.abs(win_phase) > 3 / 24) and np.any(np.abs(win_phase) <= 1.8 / 24)
        else 0.0,
        "mad_scatter": float(np.median(np.abs(synthetic - np.median(synthetic)))),
        "gap_fraction": float(
            np.sum(np.diff(win_time) > 0.05) / max(1, len(win_time) - 1)
        ),  # rough gap measure
        "matched_filter_corr": float(
            np.corrcoef(
                synthetic,
                batman_curve(win_phase, np.sqrt(150 * 1e-6), 0.0, A_OVER_RSTAR, INCLINATION_DEG),
            )[0, 1]
        )
        if len(synthetic) > 1
        else 0.0,
        "segment_std_ppm": float(
            np.std(synthetic) * 1e6
        ),  # approximate; better version uses parent segment
        "mean_flux": float(np.mean(synthetic)),
        "label": 1 if is_positive else 0,
        "segment_id": int(seg_idx),
        "is_positive": bool(is_positive),
        "injected_depth_ppm": float(depth_ppm) if is_positive else 0.0,
        "n_points": int(len(win_time)),
        "window_start_bkjd": float(win_time.min()),
    }
    windows.append(features)

# Save dataset
out_data = RESULTS / "phase5_dataset.json"
out_data.write_text(
    json.dumps(
        {
            "generated_by": "scripts/phase5_build_dataset.py",
            "seed": SEED,
            "window_hours": window_hours,
            "geometry": {"a_over_r": A_OVER_RSTAR, "inc_deg": INCLINATION_DEG},
            "positive_depths_ppm": [75, 150, 225, 300],
            "negative_depth_ppm": 0,
            "n_windows": len(windows),
            "split_strategy": "segment-level (contiguous blocks split at >1d gaps); windows "
            "from same segment never split across sets",
            "label_source": "simulated injection only; not real-planet labels",
            "windows": windows,
        },
        indent=2,
    )
    + "\n"
)

print(
    f"Phase 5 dataset built: {len(windows)} windows ({sum(w['label'] for w in windows)} "
    f"positive, {sum(1 for w in windows if w['label'] == 0)} negative)"
)
print(f"Output: {out_data}")
