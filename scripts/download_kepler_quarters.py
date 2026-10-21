"""Download all available Kepler long-cadence light curves for Kepler-10.

Explicit, documented selection criteria (no silent products[0] pick):
  - target resolved by name: "Kepler-10" (KIC 11904151)
  - mission = "Kepler", author/provenance = "Kepler" (SOC pipeline)
  - exptime = "long" (1800 s)
  - exactly ONE product per quarter; every quarter returned by the search is kept
  - every product filename must belong to KIC 11904151

Files land in the lightkurve cache under data/raw/mast_cache. Existing cached
files are reused, never re-downloaded or modified. Prints the scope (per-quarter
sizes and total) BEFORE downloading and verifies the cache afterwards.

Usage:
    python scripts/download_kepler_quarters.py
"""

from pathlib import Path

import lightkurve as lk

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "mast_cache"

EXPECTED_QUARTERS = 15  # measured from the Phase 2 MAST search; asserted below


def main():
    results = lk.search_lightcurve("Kepler-10", mission="Kepler", author="Kepler", exptime="long")
    table = results.table

    # --- explicit selection: one product per quarter, correct target only ---
    by_quarter = {}
    for row, product in zip(table, results, strict=True):
        label = str(row["mission"])  # e.g. "Kepler Quarter 03"
        filename = str(row["productFilename"])
        if "kplr011904151" not in filename:
            raise ValueError(f"Unexpected target in product {filename}; refusing to download.")
        if label in by_quarter:
            raise ValueError(
                f"More than one product for {label}; selection criteria are ambiguous."
            )
        by_quarter[label] = (product, filename, int(row["size"]))

    if len(by_quarter) != EXPECTED_QUARTERS:
        raise ValueError(
            f"Expected {EXPECTED_QUARTERS} quarters from the Phase 2 search, "
            f"got {len(by_quarter)}. Re-check available products before downloading."
        )

    total_bytes = sum(size for _, _, size in by_quarter.values())
    print("Download scope (explicit criteria: Kepler mission, Kepler author, long cadence,")
    print("one product per quarter, KIC 119041151 products only):\n")
    for label in sorted(by_quarter):
        _, filename, size = by_quarter[label]
        print(f"  {label}: {size / 1e6:5.2f} MB  {filename}")
    print(
        f"\nTotal new data to fetch: {total_bytes / 1e6:.1f} MB across {len(by_quarter)} products"
    )

    for label in sorted(by_quarter):
        product, filename, _ = by_quarter[label]
        product.download(download_dir=str(CACHE))
        print(f"fetched/cached: {label} ({filename})")

    # --- verify every selected product exists in the cache ---
    cached = sorted(CACHE.rglob("kplr011904151-*.fits"))
    print(f"\nVerification: {len(cached)} KIC 11904151 light-curve FITS files in cache")
    for path in cached:
        print(f"  {path.name} ({path.stat().st_size / 1e6:.2f} MB)")
    if len(cached) < EXPECTED_QUARTERS:
        raise RuntimeError(
            f"Only {len(cached)} of {EXPECTED_QUARTERS} quarters present after download."
        )


if __name__ == "__main__":
    main()
