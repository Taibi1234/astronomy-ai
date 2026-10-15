"""Create quality-masked light-curve CSVs from the cached FITS files.

Reads the locally cached FITS light curves (no network access), applies the
mission quality mask (SAP_QUALITY == 0 for Kepler, QUALITY == 0 for TESS),
normalizes flux by its median, and writes NEW CSV files alongside the existing
ones:

    data/processed/<mission>_kepler_10_quality_masked.csv

The original CSVs are never touched. Row accounting, quality-flag observations,
provenance, and validation results are written to reports/dataset_metadata.json.

Quality-flag policy
-------------------
We keep only cadences with the mission quality bitmask equal to 0, i.e. no flags
set. This is the conservative standard choice for quick-look analysis: flagged
cadences include attitude tweaks, safe-mode/coarse-point/earth-point periods,
and other spacecraft or detector anomalies. Bit definitions:
  - Kepler: Kepler Archive Manual (SAP_QUALITY column)
  - TESS: TESS SPOC Data Products Description (QUALITY column)
The bits actually present in these files are measured and recorded in the
metadata (quality_bits_observed) rather than assumed.

Time system
-----------
The `time` column is mission-relative BJD in days, TDB: BKJD = BJD - 2454833.0
(Kepler) and TJD = BJD - 2457000.0 (TESS), matching the FITS keywords
TIMESYS=TDB and BJDREFI. To get absolute BJD: bjd = time + bjdref.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.io import fits

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "mast_cache"
PROCESSED = ROOT / "data" / "processed"
METADATA_PATH = ROOT / "reports" / "dataset_metadata.json"

# Mission-specific settings derived from the FITS standard, keyed by filename prefix.
MISSIONS = {
    "kplr": {"mission": "kepler", "quality_column": "SAP_QUALITY", "bjdrefi": 2454833},
    "tess": {"mission": "tess", "quality_column": "QUALITY", "bjdrefi": 2457000},
}


def find_fits_files():
    files = sorted(CACHE.rglob("*.fits"))
    if not files:
        raise FileNotFoundError(
            f"No cached FITS files under {CACHE}. "
            "Run scripts/prepare_lightcurves.py (network) first."
        )
    return files


def load_fits(path):
    """Return time, quality flags, and PDCSAP flux from a light-curve FITS file."""
    with fits.open(path) as hdul:
        header = hdul[0].header
        ext = hdul[1].header
        data = hdul[1].data
        mission_key = next(k for k in MISSIONS if path.name.startswith(k))
        mission = MISSIONS[mission_key]
        time = np.asarray(data["TIME"], dtype=float)
        quality = np.asarray(data[mission["quality_column"]], dtype=int)
        flux = np.asarray(data["PDCSAP_FLUX"], dtype=float)
    return mission, header, ext, time, quality, flux


def observed_quality_bits(quality):
    """Measured list of quality bitmask bits set on at least one flagged cadence."""
    flagged = quality[quality != 0]
    if len(flagged) == 0:
        return []
    bits = np.arange(16)
    return [int(b) for b in bits if np.any((flagged >> b) & 1 == 1)]


def validate_csv(path):
    """Check columns, numeric types, finiteness, ordering, and duplicates."""
    df = pd.read_csv(path)
    checks = {
        "columns": list(df.columns),
        "columns_ok": list(df.columns) == ["time", "normalized_flux"],
        "rows": int(len(df)),
        "numeric_dtypes": bool(
            pd.api.types.is_float_dtype(df["time"])
            and pd.api.types.is_float_dtype(df["normalized_flux"])
        ),
        "finite": bool(np.isfinite(df.to_numpy(float)).all()),
        "monotonic_increasing": bool(np.all(np.diff(df["time"].to_numpy(float)) > 0)),
        "duplicate_times": int(df["time"].duplicated().sum()),
    }
    checks["valid"] = (
        checks["columns_ok"]
        and checks["numeric_dtypes"]
        and checks["finite"]
        and checks["monotonic_increasing"]
        and checks["duplicate_times"] == 0
    )
    return checks


def process_mission(path, original_csv):
    mission, header, ext, time, quality, flux = load_fits(path)

    finite = np.isfinite(time) & np.isfinite(flux)
    unflagged = quality == 0
    keep = finite & unflagged

    # Match prepare_lightcurves.py: drop invalid rows first, then median-normalize.
    flux_clean = flux[keep]
    normalized = flux_clean / np.median(flux_clean)

    suffix = "quality_masked"
    out_path = PROCESSED / f"{mission['mission']}_kepler_10_{suffix}.csv"
    pd.DataFrame({"time": time[keep], "normalized_flux": normalized}).to_csv(out_path, index=False)

    dt_minutes = float(np.median(np.diff(time[keep])) * 24 * 60) if keep.sum() > 1 else float("nan")

    meta = {
        "target": {
            "name": "Kepler-10",
            "archive_id": header.get("OBJECT", "unknown"),
            "ra_deg": float(header.get("RA_OBJ", float("nan"))),
            "dec_deg": float(header.get("DEC_OBJ", float("nan"))),
        },
        "mission": mission["mission"].upper(),
        "quarter" if mission["mission"] == "kepler" else "sector": int(
            header.get("QUARTER", header.get("SECTOR", -1))
        ),
        "archive_product": path.name,
        "pipeline": header.get("PROCVER", "unknown"),
        "cadence_minutes": round(dt_minutes, 3),
        "timesys": ext.get("TIMESYS", "unknown"),
        "time_unit": ext.get("TIMEUNIT", "d"),
        "time_definition": (
            f"Mission-relative BJD ({'BKJD' if mission['mission'] == 'kepler' else 'TJD'}) "
            f"= BJD(TDB) - {mission['bjdrefi']}.0; absolute BJD = time + {mission['bjdrefi']}.0"
        ),
        "bjdrefi": float(ext.get("BJDREFI", mission["bjdrefi"])),
        "fits_time_range": [
            float(ext.get("TSTART", time[finite].min())),
            float(ext.get("TSTOP", time[finite].max())),
        ],
        "csv_time_range": [float(time[keep].min()), float(time[keep].max())],
        "rows": {
            "fits": int(len(time)),
            "removed_nonfinite": int((~finite).sum()),
            "removed_quality_flagged": int((finite & ~unflagged).sum()),
            "final": int(keep.sum()),
        },
        "quality_bits_observed": observed_quality_bits(quality),
        "files": {
            "fits_cache": str(path.relative_to(ROOT)),
            "original_csv": str(original_csv.relative_to(ROOT)),
            "masked_csv": str(out_path.relative_to(ROOT)),
        },
        "original_csv_validation": validate_csv(original_csv),
        "masked_csv_validation": validate_csv(out_path),
        "download_command": "python scripts/prepare_lightcurves.py",
    }

    print(f"\n=== {mission['mission'].upper()} ({path.name}) ===")
    print(f"FITS rows: {meta['rows']['fits']}")
    print(f"removed non-finite: {meta['rows']['removed_nonfinite']}")
    print(f"removed quality-flagged: {meta['rows']['removed_quality_flagged']}")
    print(f"final rows: {meta['rows']['final']} -> {out_path.name}")
    print(f"quality bits observed on flagged rows: {meta['quality_bits_observed']}")
    print(f"original CSV valid: {meta['original_csv_validation']['valid']}")
    print(f"masked CSV valid:   {meta['masked_csv_validation']['valid']}")

    if not meta["masked_csv_validation"]["valid"]:
        raise ValueError(f"Masked CSV failed validation: {out_path}")

    return mission["mission"], meta


def main():
    datasets = {}
    for path in find_fits_files():
        mission = MISSIONS[next(k for k in MISSIONS if path.name.startswith(k))]["mission"]
        original_csv = PROCESSED / f"{mission}_kepler_10.csv"
        if not original_csv.exists():
            raise FileNotFoundError(f"Missing original CSV: {original_csv}")
        key, meta = process_mission(path, original_csv)
        datasets[key] = meta

    payload = {
        "generated_by": "scripts/apply_quality_mask.py",
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "quality_policy": (
            "Keep only cadences with the mission quality bitmask == 0 (no flags). "
            "Flagged cadences (attitude tweaks, safe mode, coarse point, earth point, "
            "detector anomalies, etc.) are excluded. Bit definitions: Kepler Archive "
            "Manual (SAP_QUALITY) and TESS SPOC Data Products Description (QUALITY). "
            "The bits actually present in each file are listed per dataset under "
            "quality_bits_observed (measured, not assumed)."
        ),
        "normalization": (
            "normalized_flux = PDCSAP_FLUX / median(PDCSAP_FLUX) computed after removing "
            "non-finite rows, matching lightkurve .remove_nans().normalize()."
        ),
        "datasets": datasets,
    }
    METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    METADATA_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nMetadata written: {METADATA_PATH}")


if __name__ == "__main__":
    main()
