"""Generate full-phase ephemeris-folded light-curve figures.

Reproducible generator for `reports/figures/<mission>_kepler_10_phase_folded.png`:
the whole orbital phase cycle of Kepler-10 b (period 0.837491225 d) folded on the
published ephemeris, without a transit-center marker. These figures predate this
script in the repository (created by an earlier, since-removed fold script — see
reports/project_audit.md §4); this script makes them reproducible going forward.

Usage:
    python scripts/plot_full_phase_fold.py [suffix] [outdir]

    suffix  optional dataset variant, e.g. `quality_masked` reads
            `<mission>_kepler_10_quality_masked.csv` (default: original CSVs)
    outdir  optional output directory (default: reports/figures)
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
FIGURES = ROOT / "reports" / "figures"

# NASA Exoplanet Archive: Kepler-10 b ephemeris (see reports/dataset_metadata.json).
PERIOD_DAYS = 0.837491225
TRANSIT_EPOCH_BJD = 2454964.575
MISSION_BJDREF = {
    "kepler": 2454833.0,
    "tess": 2457000.0,
}


def main():
    suffix = f"_{sys.argv[1]}" if len(sys.argv) > 1 else ""
    outdir = Path(sys.argv[2]) if len(sys.argv) > 2 else FIGURES
    outdir.mkdir(parents=True, exist_ok=True)

    for mission, bjdref in MISSION_BJDREF.items():
        path = DATA / f"{mission}_kepler_10{suffix}.csv"
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

        epoch_relative = TRANSIT_EPOCH_BJD - bjdref
        phase = ((time - epoch_relative + PERIOD_DAYS / 2) % PERIOD_DAYS) - PERIOD_DAYS / 2
        order = np.argsort(phase)

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.scatter(phase[order], flux[order], s=5, alpha=0.55)
        ax.set_title(f"{mission.upper()} phase-folded light curve: Kepler-10")
        ax.set_xlabel("Relative orbital phase (days)")
        ax.set_ylabel("Normalized flux")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        output = outdir / f"{mission}_kepler_10{suffix}_phase_folded.png"
        fig.savefig(output, dpi=150)
        plt.close(fig)
        print(f"Saved plot: {output} ({len(time)} points)")


if __name__ == "__main__":
    main()
