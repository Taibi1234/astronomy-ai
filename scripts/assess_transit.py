from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("data/processed")
PERIOD = 0.837491225
T0_BJD = 2454964.575
BJDREF = {"kepler": 2454833.0, "tess": 2457000.0}

DURATION_HOURS = 1.8
HALF_DURATION_DAYS = DURATION_HOURS / 48.0

for mission, offset in BJDREF.items():
    df = pd.read_csv(DATA / f"{mission}_kepler_10.csv")
    t = df["time"].to_numpy(float)
    y = df["normalized_flux"].to_numpy(float)

    good = np.isfinite(t) & np.isfinite(y)
    t, y = t[good], y[good]

    epoch = T0_BJD - offset
    phase_days = ((t - epoch + PERIOD / 2) % PERIOD) - PERIOD / 2

    # Fit baseline and depth using the central region and nearby baseline.
    use = np.abs(phase_days) <= 6 / 24
    x = phase_days[use]
    flux = y[use]

    # Transit-shaped box approximation; depth constrained to be nonnegative.
    inside = np.abs(x) < HALF_DURATION_DAYS
    outside = ~inside

    baseline = np.median(flux[outside])
    depth = max(0.0, baseline - np.median(flux[inside]))

    predicted_null = np.full_like(flux, baseline)
    predicted_transit = baseline - depth * inside.astype(float)

    rss_null = np.sum((flux - predicted_null) ** 2)
    rss_transit = np.sum((flux - predicted_transit) ** 2)

    print(f"\n===== {mission.upper()} =====")
    print(f"Points in +/-6h window: {len(flux)}")
    print(f"Fitted baseline: {baseline:.8f}")
    print(f"Box-model depth: {depth:.8f} ({depth * 1e6:.1f} ppm)")
    print(f"Null-model RSS: {rss_null:.8g}")
    print(f"Transit-model RSS: {rss_transit:.8g}")
    if rss_null > 0:
        print(f"RSS reduction: {100 * (rss_null - rss_transit) / rss_null:.2f}%")

    print("Caution: RSS improvement alone is not detection significance.")
    print("Phase-folded samples are not necessarily independent.")
