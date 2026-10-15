from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
FIGURES = ROOT / "reports" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

# NASA Exoplanet Archive: Kepler-10 b, Q1-Q17 DR25 solution.
PERIOD_DAYS = 0.837491225
TRANSIT_EPOCH_BJD = 2454964.575

# FITS BJD reference offsets verified in the local metadata.
MISSION_BJDREF = {
    "kepler": 2454833.0,
    "tess": 2457000.0,
}

for mission, bjdref in MISSION_BJDREF.items():
    path = DATA / f"{mission}_kepler_10.csv"

    if not path.exists():
        print(f"Missing input: {path}")
        continue

    df = pd.read_csv(path)
    time = df["time"].to_numpy(dtype=float)
    flux = df["normalized_flux"].to_numpy(dtype=float)

    valid = np.isfinite(time) & np.isfinite(flux)
    time, flux = time[valid], flux[valid]

    if len(time) == 0:
        print(f"No valid observations in {path.name}")
        continue

    # Convert the published BJD epoch to the mission-relative time system.
    epoch_relative = TRANSIT_EPOCH_BJD - bjdref

    # Phase centered on the predicted transit: [-P/2, P/2).
    phase = ((time - epoch_relative + PERIOD_DAYS / 2) % PERIOD_DAYS) - PERIOD_DAYS / 2

    order = np.argsort(phase)

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.scatter(phase[order] * 24, flux[order], s=5, alpha=0.55)
    ax.axvline(0, color="red", linestyle="--", linewidth=1, label="Predicted transit center")
    ax.set_xlim(-6, 6)
    ax.set_title(f"{mission.upper()} — Kepler-10 b transit-aligned fold")
    ax.set_xlabel("Hours from predicted transit center")
    ax.set_ylabel("Normalized flux")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()

    output = FIGURES / f"{mission}_kepler_10_ephemeris_folded.png"
    fig.savefig(output, dpi=160)
    plt.close(fig)

    print(f"\nMission: {mission.upper()}")
    print(f"Valid observations: {len(time)}")
    print(f"Observed time range: {time.min():.6f} to {time.max():.6f}")
    print(f"Predicted epoch in mission-relative days: {epoch_relative:.6f}")
    print(f"Saved plot: {output}")

print("\nEphemeris-based phase folding finished.")
