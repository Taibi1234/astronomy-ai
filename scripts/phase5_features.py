"""Phase 5 — Feature extraction (7 documented features) from dataset JSON.
Includes segment-level variability metadata feature (segment_std_ppm) as requested.

Status: historical pipeline. It copies the features already computed in
`reports/phase5_dataset.json` and imputes the 9 undefined `matched_filter_corr`
values with a median taken over ALL 26 windows (line below), which includes the test
split — a known cross-split preprocessing defect, documented in
reports/phase8_ml_pipeline_audit.md §2.1 and left in place so the frozen
`reports/phase5_features.csv` stays reproducible. For new work use
scripts/phase8_features.py, which records the split per row and fits that median on
training rows only.
"""

import json
from pathlib import Path

import pandas as pd

DATA_FILE = Path("reports") / "phase5_dataset.json"
j = json.loads(DATA_FILE.read_text())
windows = j["windows"]

# Handle NaN in matched_filter_corr after creating df; the fill is applied before the
# CSV is written, so downstream readers never see an undefined correlation.
print("Note: NaN in matched_filter_corr will be filled with median after CSV creation.")
rows = []
for w in windows:
    rows.append(
        {
            "depth_rel_ppm": w["depth_rel_ppm"],
            "contrast_ppm": w["contrast_ppm"],
            "mad_scatter": w["mad_scatter"],
            "gap_fraction": w["gap_fraction"],
            "matched_filter_corr": w["matched_filter_corr"],
            "segment_std_ppm": w["segment_std_ppm"],
            "mean_flux": w["mean_flux"],
            "label": w["label"],
            "segment_id": w["segment_id"],
            "injected_depth_ppm": w["injected_depth_ppm"],
            "n_points": w["n_points"],
        }
    )

df = pd.DataFrame(rows)
# Fill NaN in matched_filter_corr (can occur for windows with near-constant flux or 1 point)
median_corr = df["matched_filter_corr"].median()
df = df.fillna({"matched_filter_corr": median_corr})
df.to_csv("reports/phase5_features.csv", index=False)
print(f"Features extracted: {len(df)} rows; columns: {list(df.columns)}")
print(f"Positive: {df['label'].sum()} / Negative: {(df['label'] == 0).sum()}")
print(
    "Segment-level feature included: segment_std_ppm (describes parent segment variability from "
    "Phase 4 diagnostics)"
)
# Save feature definitions
feature_defs = {
    "features": {
        "depth_rel_ppm": "median - min of normalized flux (approximate depth indicator)",
        "contrast_ppm": "mean out-of-transit (|phase|>3h) minus mean in-transit (|phase|<=1.8h)",
        "mad_scatter": "median absolute deviation from median (robust scatter)",
        "gap_fraction": "fraction of cadences with gap > 0.05 d",
        "matched_filter_corr": "correlation with batman template (150 ppm depth) at published "
        "ephemeris",
        "segment_std_ppm": "standard deviation of flux within window (includes variability from "
        "parent segment)",
        "mean_flux": "mean normalized flux in window",
    },
    "segment_metadata_feature": "segment_std_ppm captures parent-continuous-segment variability "
    "(from phase4_residual_diagnostics); it serves as the requested "
    "segment-level feature.",
    "label_source": "simulated injection only (positive=depth>0, negative=depth=0)",
    "split_method": "segment-level split (same segment ID never appears in both train/test); "
    "verified in test_phase5_leakage",
    "no_real_planet_labels": True,
}
with open("reports/phase5_feature_config.json", "w") as f:
    json.dump(feature_defs, f, indent=2)
print("Saved: reports/phase5_features.csv, reports/phase5_feature_config.json")
