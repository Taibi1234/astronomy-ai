from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("data/processed")
PERIOD = 0.837491225
T0_BJD = 2454964.575
BJDREF = {"kepler": 2454833.0, "tess": 2457000.0}

DURATION_HOURS = 1.8
HALF_DURATION_DAYS = DURATION_HOURS / 48
CENTER_OFFSETS_MIN = np.arange(-30, 30.1, 2)
CONTROL_OFFSETS_HOURS = np.arange(-5.0, 5.01, 0.25)


def fit_box(phase_days, flux, center_days):
    inside = np.abs(phase_days - center_days) < HALF_DURATION_DAYS
    if inside.sum() < 3 or (~inside).sum() < 10:
        return None

    baseline = np.median(flux[~inside])
    depth = max(0.0, baseline - np.median(flux[inside]))
    prediction = baseline - depth * inside
    rss = np.sum((flux - prediction) ** 2)

    return {
        "depth": depth,
        "rss": rss,
        "n_in": int(inside.sum()),
        "baseline": baseline,
    }


for mission, offset in BJDREF.items():
    df = pd.read_csv(DATA / f"{mission}_kepler_10.csv")
    t = df["time"].to_numpy(float)
    y = df["normalized_flux"].to_numpy(float)

    valid = np.isfinite(t) & np.isfinite(y)
    t, y = t[valid], y[valid]

    epoch = T0_BJD - offset
    phase = ((t - epoch + PERIOD / 2) % PERIOD) - PERIOD / 2

    # Use the same +/-6-hour region for every center comparison.
    window = np.abs(phase) <= 6 / 24
    x, flux = phase[window], y[window]

    null_baseline = np.median(flux)
    null_rss = np.sum((flux - null_baseline) ** 2)

    results = []
    for minutes in CENTER_OFFSETS_MIN:
        center = minutes / (60 * 24)
        result = fit_box(x, flux, center)
        if result is not None:
            results.append((minutes, result))

    best_minutes, best = min(results, key=lambda item: item[1]["rss"])
    predicted = fit_box(x, flux, 0.0)

    # Control centers must be outside the expected transit neighborhood.
    controls = []
    for hours in CONTROL_OFFSETS_HOURS:
        if abs(hours) < 2:
            continue
        result = fit_box(x, flux, hours / 24)
        if result is not None:
            controls.append((hours, result))

    control_improvements = [null_rss - result["rss"] for _, result in controls]
    observed_improvement = null_rss - predicted["rss"]
    control_fraction = (
        sum(v >= observed_improvement for v in control_improvements) / len(control_improvements)
        if control_improvements
        else float("nan")
    )

    print(f"\n===== {mission.upper()} =====")
    print(f"Predicted-center depth: {predicted['depth'] * 1e6:.1f} ppm")
    print(f"Best center offset: {best_minutes:+.1f} minutes")
    print(f"Best-center depth: {best['depth'] * 1e6:.1f} ppm")
    print(f"Predicted-center RSS improvement: {100 * observed_improvement / null_rss:.3f}%")
    print(f"Control phases tested: {len(controls)}")
    print(f"Control phases matching/exceeding improvement: {100 * control_fraction:.1f}%")
    print("This control fraction is descriptive, not a calibrated p-value.")
    print("The control phases and samples are correlated.")
