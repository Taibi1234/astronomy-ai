from pathlib import Path

import lightkurve as lk
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "mast_cache"
PROCESSED = ROOT / "data" / "processed"
FIGURES = ROOT / "reports" / "figures"

for folder in (CACHE, PROCESSED, FIGURES):
    folder.mkdir(parents=True, exist_ok=True)


def analyze_target(target, mission):
    print(f"\nSearching {mission} observations for {target}...", flush=True)

    search_args = {
        "target": target,
        "mission": mission,
        "limit": 5,
    }

    if mission == "Kepler":
        search_args["author"] = "Kepler"
        search_args["exptime"] = "long"
    else:
        search_args["author"] = "SPOC"

    products = lk.search_lightcurve(**search_args)
    print(f"Products found: {len(products)}")

    if len(products) == 0:
        print(f"No products found for {mission}. Skipping.")
        return

    curve = products[0].download(download_dir=str(CACHE))

    if curve is None:
        print(f"Download failed for {mission}. Skipping.")
        return

    # Remove invalid observations and normalize flux.
    curve = curve.remove_nans().normalize()

    time = np.asarray(curve.time.value, dtype=float)
    flux = np.asarray(curve.flux.value, dtype=float)

    valid = np.isfinite(time) & np.isfinite(flux)
    time = time[valid]
    flux = flux[valid]

    if len(time) == 0:
        print("No valid observations remain.")
        return

    prefix = f"{mission.lower()}_{target.lower().replace('-', '_')}"

    dataframe = pd.DataFrame(
        {
            "time": time,
            "normalized_flux": flux,
        }
    )

    csv_path = PROCESSED / f"{prefix}.csv"
    dataframe.to_csv(csv_path, index=False)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(time, flux, ".", markersize=2)
    ax.set_title(f"{mission} light curve: {target}")
    ax.set_xlabel("Time (mission time units)")
    ax.set_ylabel("Normalized flux")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    figure_path = FIGURES / f"{prefix}.png"
    fig.savefig(figure_path, dpi=150)
    plt.close(fig)

    print(f"Valid observations: {len(time)}")
    print(f"CSV saved: {csv_path}")
    print(f"Plot saved: {figure_path}")


if __name__ == "__main__":
    analyze_target("Kepler-10", "Kepler")
    analyze_target("Kepler-10", "TESS")
    print("\nExploratory analysis finished.")
