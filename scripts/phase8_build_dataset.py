
"""Phase 8 — corrected synthetic dataset builder (WINDOW-LEVEL INPUT SEMANTICS).

Features are calculated from the flux presented to the classifier:
the injected-transit flux for positive windows and unchanged flux for negatives.

The window selection, injection depths, RNG sequence, labels, and split metadata
are preserved. Undefined Pearson correlations are represented as NaN rather
than triggering NumPy divide-by-zero or invalid-value warnings.

This writes phase8_dataset.json and never modifies phase5_dataset.json.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from transit_analysis import (  # noqa: E402
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

DATA = ROOT / "data" / "processed"
SEED = 42
WINDOW_HOURS = 6.0
POSITIVE_DEPTHS_PPM = [75, 150, 225, 300]
NEGATIVE_DEPTH_PPM = 0


def _safe_correlation(x, y):
    """Return NaN if Pearson correlation is undefined; otherwise return r."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)

    if (
        x.ndim != 1
        or y.ndim != 1
        or x.size != y.size
        or x.size < 2
        or not np.all(np.isfinite(x))
        or not np.all(np.isfinite(y))
        or np.std(x) == 0
        or np.std(y) == 0
    ):
        return float("nan")

    return float(np.corrcoef(x, y)[0, 1])


def extract_features(flux, phase, time):
    """Extract the seven features from the presented window flux only.

    No label, injected depth, or split information enters this function.
    """
    flux = np.asarray(flux, dtype=float)
    phase = np.asarray(phase, dtype=float)
    time = np.asarray(time, dtype=float)

    has_out = bool(np.any(np.abs(phase) > 3 / 24))
    has_in = bool(np.any(np.abs(phase) <= 1.8 / 24))

    contrast = (
        float(
            (
                np.mean(flux[np.abs(phase) > 3 / 24])
                - np.mean(flux[np.abs(phase) <= 1.8 / 24])
            )
            * 1e6
        )
        if has_out and has_in
        else 0.0
    )

    template = batman_curve(
        phase,
        np.sqrt(150 * 1e-6),
        0.0,
        A_OVER_RSTAR,
        INCLINATION_DEG,
    )
    corr = _safe_correlation(flux, template)

    return {
        "depth_rel_ppm": float((np.median(flux) - np.min(flux)) * 1e6),
        "contrast_ppm": contrast,
        "mad_scatter": float(np.median(np.abs(flux - np.median(flux)))),
        "gap_fraction": float(
            np.sum(np.diff(time) > 0.05) / max(1, len(time) - 1)
        ),
        "matched_filter_corr": corr,
        "segment_std_ppm": float(np.std(flux) * 1e6),
        "mean_flux": float(np.mean(flux)),
    }


def inject_transit(flux, phase, depth_ppm):
    """Add a batman transit of the given depth, preserving mean level."""
    rp = np.sqrt(depth_ppm * 1e-6)
    signal_model = batman_curve(
        phase, rp, 0.0, A_OVER_RSTAR, INCLINATION_DEG
    )
    median_w = float(np.median(flux))
    return flux + median_w * (signal_model - 1.0)


def build(out_dir):
    spec = {
        "path": DATA / "kepler_all_quarters_quality_masked.csv",
        "mission": "kepler",
        "variants": [],
    }
    time_all, flux_all = load_dataset(spec)
    phase_all = fold_phase(
        time_all, PERIOD, TRANSIT_EPOCH_BJD, BJDREF["kepler"]
    )
    flux_dt, _ = detrend_poly(time_all, phase_all, flux_all)

    segments_idx = np.split(
        np.arange(len(time_all)),
        np.where(np.diff(time_all) > 1.0)[0] + 1,
    )
    rng = np.random.default_rng(SEED)
    windows = []

    for seg_idx in range(len(segments_idx)):
        seg = segments_idx[seg_idx]
        if len(seg) < 100:
            continue

        is_positive = seg_idx % 2 == 0
        center_idx_in_seg = rng.integers(0, max(1, len(seg) - 50))
        center_time = time_all[seg[center_idx_in_seg]]
        window_points_idx = seg[
            np.abs(time_all[seg] - center_time) <= (WINDOW_HOURS / 24)
        ]

        if len(window_points_idx) < 10:
            continue

        win_time = time_all[window_points_idx]
        win_phase = phase_all[window_points_idx]
        win_flux_dt = flux_dt[window_points_idx]

        if is_positive:
            depth_ppm = float(rng.choice(POSITIVE_DEPTHS_PPM))
            presented_flux = inject_transit(
                win_flux_dt, win_phase, depth_ppm
            )
        else:
            depth_ppm = float(NEGATIVE_DEPTH_PPM)
            presented_flux = win_flux_dt.copy()

        row = {
            **extract_features(presented_flux, win_phase, win_time),
            "label": 1 if is_positive else 0,
            "segment_id": int(seg_idx),
            "is_positive": bool(is_positive),
            "injected_depth_ppm": float(depth_ppm),
            "n_points": int(len(win_time)),
            "window_start_bkjd": float(win_time.min()),
        }
        windows.append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_by": "scripts/phase8_build_dataset.py",
        "feature_source": (
            "presented window flux (transit injected when label=1)"
        ),
        "seed": SEED,
        "window_hours": WINDOW_HOURS,
        "geometry": {
            "a_over_r": A_OVER_RSTAR,
            "inc_deg": INCLINATION_DEG,
        },
        "positive_depths_ppm": POSITIVE_DEPTHS_PPM,
        "negative_depth_ppm": NEGATIVE_DEPTH_PPM,
        "n_windows": len(windows),
        "label_source": "simulated injection only; not real-planet labels",
        "split_strategy": "segment-level (contiguous blocks split at >1d gaps)",
        "windows": windows,
    }

    output_path = out_dir / "phase8_dataset.json"
    output_path.write_text(
        json.dumps(payload, indent=2, allow_nan=True) + "\n",
        encoding="utf-8",
    )

    n_positive = sum(w["label"] for w in windows)
    n_negative = sum(1 for w in windows if w["label"] == 0)

    print(
        f"Phase 8 dataset: {len(windows)} windows "
        f"({n_positive} positive, {n_negative} negative)"
    )
    print(f"Output: {output_path}")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(ROOT / "reports"),
        help="output directory",
    )
    args = parser.parse_args()
    build(Path(args.out))
