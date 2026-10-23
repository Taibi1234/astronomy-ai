"""Shared time-domain feature builder (Phase 11 Stage B2a, design §5.1).

Neutral, dependency-light module: numpy only. ``phase11`` and ``experiment`` re-export
:func:`time_domain_features`, so both historical callers keep their existing names while a
single implementation is shared, and the v2 fit path can use it without importing a legacy
campaign module.

The builder sees only the presented time and flux arrays. It receives no ground-truth depth,
offset or label, holds no reference to the detector, and reads no file.
"""

from __future__ import annotations

import numpy as np

FEATURE_NAMES = (
    "min_depth_ppm",
    "std_ppm",
    "mad_ppm",
    "gap_fraction",
    "mean_flux",
    "n_points",
)


def time_domain_features(times: np.ndarray, flux: np.ndarray) -> dict:
    """Six features computed from the presented chunk, without truth or detector output."""
    baseline = float(np.median(flux))
    resid = flux - baseline
    gaps = np.diff(times) > 0.05
    return {
        "min_depth_ppm": float((baseline - float(np.min(flux))) * 1e6),
        "std_ppm": float(np.std(flux) * 1e6),
        "mad_ppm": float(np.median(np.abs(resid)) * 1e6),
        "gap_fraction": float(np.sum(gaps) / max(1, len(times) - 1)),
        "mean_flux": float(np.mean(flux)),
        "n_points": int(len(times)),
    }
