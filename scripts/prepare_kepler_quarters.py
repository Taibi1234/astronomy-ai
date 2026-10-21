"""Build per-quarter and combined quality-masked Kepler CSVs from the FITS cache.

Applies exactly the same quality policy as scripts/apply_quality_mask.py
(keep SAP_QUALITY == 0 and finite TIME/PDCSAP_FLUX; median-normalize). Each quarter
is normalized by ITS OWN median, processed independently, and kept identifiable:

    data/processed/kepler_q{quarter:02d}_quality_masked.csv     (15 files)
    data/processed/kepler_all_quarters_quality_masked.csv       (combined, time-sorted)

Overlap/duplicate check: the combined table must be strictly increasing in time
(quarters are disjoint; any duplicate or overlap would fail this and raise).
Intra-quarter data gaps (consecutive cadence gap > 1.5x the median cadence) and
inter-quarter gaps are measured and recorded.

Writes provenance to reports/kepler_quarters_metadata.json. Offline; network-free.

Usage:
    python scripts/prepare_kepler_quarters.py
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
METADATA_PATH = ROOT / "reports" / "kepler_quarters_metadata.json"

BJDREFI = 2454833  # verified against FITS headers in Phase 2


def load_quarter(path):
    """Return header, ext header, and raw columns for one Kepler LC FITS file."""
    with fits.open(path) as hdul:
        header = hdul[0].header
        ext = hdul[1].header
        data = hdul[1].data
        time = np.asarray(data["TIME"], dtype=float)
        quality = np.asarray(data["SAP_QUALITY"], dtype=int)
        flux = np.asarray(data["PDCSAP_FLUX"], dtype=float)
    return header, ext, time, quality, flux


def observed_bits(quality):
    flagged = quality[quality != 0]
    if len(flagged) == 0:
        return []
    return [int(b) for b in np.arange(16) if np.any((flagged >> b) & 1 == 1)]


def process_quarter(path):
    """Mask, normalize, and save one quarter; return its metadata and frame."""
    header, ext, time, quality, flux = load_quarter(path)
    quarter = int(header["QUARTER"])

    finite = np.isfinite(time) & np.isfinite(flux)
    keep = finite & (quality == 0)
    if keep.sum() < 2:
        raise ValueError(f"Quarter {quarter}: fewer than 2 valid cadences.")

    flux_clean = flux[keep]
    normalized = flux_clean / np.median(flux_clean)
    frame = pd.DataFrame({"time": time[keep], "normalized_flux": normalized})

    cadence_days = float(np.median(np.diff(time[keep])))
    gaps = int((np.diff(time[keep]) > 1.5 * cadence_days).sum())

    out_path = PROCESSED / f"kepler_q{quarter:02d}_quality_masked.csv"
    frame.to_csv(out_path, index=False)

    meta = {
        "quarter": quarter,
        "archive_product": path.name,
        "pipeline": header.get("PROCVER", "unknown"),
        "rows_fits": int(len(time)),
        "removed_nonfinite": int((~finite).sum()),
        "removed_quality_flagged": int((finite & (quality != 0)).sum()),
        "rows_final": int(keep.sum()),
        "time_range": [float(time[keep].min()), float(time[keep].max())],
        "median_cadence_minutes": round(cadence_days * 24 * 60, 3),
        "intra_quarter_gap_count": gaps,
        "quality_bits_observed": observed_bits(quality),
        "csv": str(out_path.relative_to(ROOT)),
    }
    print(
        f"Q{quarter:02d}: {meta['rows_final']:5d} pts | "
        f"{meta['time_range'][0]:9.3f}..{meta['time_range'][1]:9.3f} d | "
        f"cadence {meta['median_cadence_minutes']:.1f} min | "
        f"removed {meta['removed_quality_flagged']} flagged | gaps {gaps}"
    )
    return meta, frame


def validate_frame(frame):
    return bool(
        list(frame.columns) == ["time", "normalized_flux"]
        and np.isfinite(frame.to_numpy(float)).all()
        and (np.diff(frame["time"].to_numpy(float)) > 0).all()
        and frame["time"].duplicated().sum() == 0
    )


def main():
    files = sorted(CACHE.rglob("kplr011904151-*.fits"))
    if len(files) < 15:
        raise FileNotFoundError(f"Expected 15 quarter FITS files, found {len(files)}.")

    quarters, frames = [], []
    for path in files:
        meta, frame = process_quarter(path)
        quarters.append(meta)
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True).sort_values("time", kind="mergesort")
    combined = combined.reset_index(drop=True)
    dt = np.diff(combined["time"].to_numpy(float))
    strictly_increasing = bool((dt > 0).all())
    if not strictly_increasing:
        raise ValueError("Combined quarters contain duplicate/overlapping timestamps.")
    inter_gaps = int((dt > 1.5 * 0.02044).sum())  # >1.5x ~29.4 min cadence

    combined_path = PROCESSED / "kepler_all_quarters_quality_masked.csv"
    combined.to_csv(combined_path, index=False)

    if not validate_frame(combined):
        raise ValueError("Combined CSV failed validation.")

    payload = {
        "generated_by": "scripts/prepare_kepler_quarters.py",
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "policy": (
            "Same as apply_quality_mask.py: SAP_QUALITY == 0 and finite TIME/PDCSAP_FLUX; "
            "flux normalized by the median of that quarter. Quarters are disjoint in time "
            "(verified strictly increasing combined timestamps; no duplicates/overlaps)."
        ),
        "timesys": "TDB",
        "time_definition": f"BKJD = BJD(TDB) - {BJDREFI}.0; absolute BJD = time + {BJDREFI}.0",
        "quarters": sorted(quarters, key=lambda m: m["quarter"]),
        "combined": {
            "csv": str(combined_path.relative_to(ROOT)),
            "rows": int(len(combined)),
            "time_range": [float(combined["time"].min()), float(combined["time"].max())],
            "inter_quarter_gap_count": inter_gaps,
            "strictly_increasing_no_overlaps": strictly_increasing,
        },
    }
    METADATA_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nCombined: {len(combined)} rows, {inter_gaps} inter-quarter gaps, no overlaps.")
    print(f"Combined CSV: {combined_path}")
    print(f"Metadata: {METADATA_PATH}")


if __name__ == "__main__":
    main()
