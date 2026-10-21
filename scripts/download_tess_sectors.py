"""Download and validate selected TESS 120-second light curves for Kepler-10.

Approved selection (Phase 3 review): Sectors 40, 53, 74, 120 s SPOC products only.

Explicit selection criteria (asserted in code):
  - target resolved by name "Kepler-10"; mission = "TESS"; author = "SPOC"
  - exptime = "long" (120 s); exactly one matching product per requested sector
  - every product filename must belong to TIC 377780790

Each sector is validated after download (target identity, observation times,
cadence, flux columns, quality flags) and written to its own quality-masked CSV:

    data/processed/tess_s{sector}_quality_masked.csv

Sectors are NOT combined (per decision: validate time references separately).
Sector 14 and all existing files are preserved untouched. Provenance is written
to reports/tess_sectors_metadata.json.

Usage:
    python scripts/download_tess_sectors.py
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import lightkurve as lk
import numpy as np
import pandas as pd
from astropy.io import fits

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "mast_cache"
PROCESSED = ROOT / "data" / "processed"
METADATA_PATH = ROOT / "reports" / "tess_sectors_metadata.json"

REQUESTED_SECTORS = (40, 53, 74)
BJDREFI = 2457000  # verified against the S14 FITS header in Phase 2

QUALITY_POLICY = (
    "Keep only cadences with QUALITY == 0 and finite TIME/PDCSAP_FLUX; "
    "flux normalized by the median of the retained points (same policy as "
    "scripts/apply_quality_mask.py and prepare_kepler_quarters.py)."
)


def select_products():
    results = lk.search_lightcurve("Kepler-10", mission="TESS", author="SPOC", exptime="long")
    table = results.table
    by_sector = {}
    for row, product in zip(table, results, strict=True):
        sector = int(row["sequence_number"]) if "sequence_number" in table.colnames else None
        if sector is None:
            sector = int(str(row["mission"]).split()[-1])
        filename = str(row["productFilename"])
        if "0000000377780790" not in filename:
            raise ValueError(f"Unexpected target in {filename}; refusing to download.")
        if sector in REQUESTED_SECTORS:
            if sector in by_sector:
                raise ValueError(f"More than one 120 s SPOC product for sector {sector}.")
            by_sector[sector] = (product, filename, int(row["size"]))
    missing = [s for s in REQUESTED_SECTORS if s not in by_sector]
    if missing:
        raise ValueError(f"Requested sectors unavailable: {missing}. Reported, not substituted.")
    return by_sector


def validate_and_write(product_info):
    sector = product_info["sector"]
    fits_path = product_info["fits_path"]
    with fits.open(fits_path) as hdul:
        header = hdul[0].header
        ext = hdul[1].header
        data = hdul[1].data
        time = np.asarray(data["TIME"], dtype=float)
        quality = np.asarray(data["QUALITY"], dtype=int)
        flux = np.asarray(data["PDCSAP_FLUX"], dtype=float)
        columns = [c.name for c in hdul[1].columns]

    finite = np.isfinite(time) & np.isfinite(flux)
    keep = finite & (quality == 0)
    frame = pd.DataFrame(
        {
            "time": time[keep],
            "normalized_flux": flux[keep] / np.median(flux[keep]),
        }
    )
    csv_path = PROCESSED / f"tess_s{sector}_quality_masked.csv"
    frame.to_csv(csv_path, index=False)

    cadence_days = float(np.median(np.diff(time[keep]))) if keep.sum() > 1 else float("nan")
    dt = np.diff(time[keep])
    meta = {
        "sector": sector,
        "target_object": header.get("OBJECT", "unknown"),
        "ticid": int(header.get("TICID", -1)),
        "ra_deg": float(header.get("RA_OBJ", float("nan"))),
        "dec_deg": float(header.get("DEC_OBJ", float("nan"))),
        "archive_product": fits_path.name,
        "pipeline": header.get("PROCVER", "unknown"),
        "timesys": ext.get("TIMESYS", "unknown"),
        "bjdrefi": float(ext.get("BJDREFI", BJDREFI)),
        "rows_fits": int(len(time)),
        "removed_nonfinite": int((~finite).sum()),
        "removed_quality_flagged": int((finite & (quality != 0)).sum()),
        "rows_final": int(keep.sum()),
        "time_range": [float(time[keep].min()), float(time[keep].max())],
        "median_cadence_minutes": round(cadence_days * 24 * 60, 3),
        "intra_sector_gap_count": int((dt > 1.5 * cadence_days).sum()) if keep.sum() > 1 else 0,
        "duplicate_timestamps": int(frame["time"].duplicated().sum()),
        "flux_columns_present": ["PDCSAP_FLUX" in columns, "SAP_FLUX" in columns],
        "lightcurve_columns": columns,
        "csv": str(csv_path.relative_to(ROOT)),
        "validation": {
            "target_is_tic_377780790": int(header.get("TICID", -1)) == 377780790,
            "cadence_is_120s": abs(cadence_days * 24 * 60 * 60 - 120) < 5,
            "timesys_tdb": ext.get("TIMESYS") == "TDB",
            "bjdrefi_2457000": float(ext.get("BJDREFI", 0)) == 2457000.0,
            "csv_strictly_increasing": bool((dt > 0).all()) if keep.sum() > 1 else False,
            "csv_no_duplicates": int(frame["time"].duplicated().sum()) == 0,
        },
    }
    bad = [k for k, v in meta["validation"].items() if v is not True]
    status = "PASS" if not bad else f"FAIL {bad}"
    print(
        f"S{sector}: {meta['rows_final']} pts | "
        f"{meta['time_range'][0]:.3f}..{meta['time_range'][1]:.3f} TJD | "
        f"cadence {meta['median_cadence_minutes']:.1f} min | "
        f"flagged removed {meta['removed_quality_flagged']} | VALIDATION {status}"
    )
    return meta


def main():
    by_sector = select_products()
    print("Download scope (120 s SPOC, TIC 377780790):")
    for sector in sorted(by_sector):
        _, filename, size = by_sector[sector]
        print(f"  S{sector}: {size / 1e6:.2f} MB  {filename}")
    total = sum(size for _, _, size in by_sector.values())
    print(f"Total: {total / 1e6:.1f} MB")

    metas = []
    for sector in sorted(by_sector):
        product, filename, _ = by_sector[sector]
        path = product.download(download_dir=str(CACHE))
        metas.append(validate_and_write({"sector": sector, "fits_path": Path(path)}))

    payload = {
        "generated_by": "scripts/download_tess_sectors.py",
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "quality_policy": QUALITY_POLICY,
        "time_definition": f"TJD = BJD(TDB) - {BJDREFI}.0; absolute BJD = time + {BJDREFI}.0",
        "note": "Sectors kept as separate CSVs; not combined. Sector 14 preserved from Phase 1.",
        "sectors": metas,
    }
    METADATA_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nMetadata: {METADATA_PATH}")


if __name__ == "__main__":
    main()
