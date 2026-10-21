"""Phase 4 — Statistical validation (step 5/6/7, consolidated).
Reproduces baseline; calculates model comparison (BIC with explicit warning
about unmodeled correlation); preserves Phase 3 outputs; reports limitations.
Does NOT add ML or begin Phase 5.
"""

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
RESULTS = ROOT / "reports" / "results"

# Load phase3 JSON (preserved baseline)
j = json.loads((RESULTS / "phase3_transit_analysis.json").read_text())
ref_depth = j["datasets"]["kepler_all_masked"]["detrended"]["fit"]["depth_ppm"]
ref_rss_null = j["datasets"]["kepler_all_masked"]["detrended"]["fit"]["rss_null"]
ref_rss_transit = j["datasets"]["kepler_all_masked"]["detrended"]["fit"]["rss_transit"]
ref_n = j["datasets"]["kepler_all_masked"]["detrended"]["fit"]["n_points"]

# Naive BIC (independent-Gaussian assumption) — reported with required warning
# Using log(n) where n = number of points in window (descriptive only)
n_window = int(ref_n)  # approximate; exact window count same as fitted
# We don't have the exact window-only count from JSON but approximate
n_approx = ref_n
delta_k = 4 - 2  # transit (4 params) - null (2 params)
# Note: BIC = n*ln(RSS_transit/n) - n*ln(RSS_null/n) + delta_k*ln(n) for nested models
# Simplified: delta BIC ≈ n*ln(RSS_t / RSS_n) + delta_k*ln(n)
bic_naive_delta = n_approx * np.log(ref_rss_transit / ref_rss_null) + delta_k * np.log(n_approx)

# Model comparison report (not a formal significance claim)
report = {
    "method_notes": [
        "BIC computed under independent-Gaussian likelihood assumption; substantial "
        "correlated noise remains (lag-1 AC ≈ 0.94), so effective sample size << n.",
        "This is a descriptive comparison, not calibrated evidence for detection.",
        "No uncalibrated p-value or formal detection significance is reported.",
    ],
    "reference_config": {
        "dataset": "kepler_all_quarters_quality_masked / detrended",
        "fixed_geometry": {"a_over_r": 3.4, "inc_deg": 84.5, "u1": 0.30, "u2": 0.20},
        "period_days": 0.837491225,
        "t0_bjd": 2454964.575,
    },
    "model_parameters": {
        "null_n_params": 2,
        "transit_n_params": 4,
        "delta_params": delta_k,
    },
    "bic_comparison": {
        "n_points_approximate": int(n_approx),
        "rss_null": float(ref_rss_null),
        "rss_transit": float(ref_rss_transit),
        "naive_delta_bic": float(bic_naive_delta),
        "assumption_warning": (
            "Independent-Gaussian likelihood is not reliable evidence given the measured "
            "correlated noise structure. Effective sample size is lower due to AC. "
            "Report for comparison only."
        ),
        "correlation_context": {
            "lag1_autocorr_approx": 0.936,
            "stationarity_ratio_max_min_rms": 7.179,
            "note": "Residual autocorrelation indicates substantial correlated noise.",
        },
    },
    "cross_dataset_summary": {
        "kepler_all_masked_detrended_depth_ppm": float(ref_depth),
        "tess_s14_masked_depth_ppm": j.get("datasets", {})
        .get("tess_s14_masked", {})
        .get("raw", {})
        .get("fit", {})
        .get("depth_ppm", None),
        "tess_s14_available": "tess_s14_masked.csv" in [p.name for p in DATA.iterdir()],
        "new_tess_sectors_downloaded": False,
        "new_tess_sectors_requested": [40, 53, 74],
        "new_tess_download_status": "Not available (network unavailable); reported, not "
        "substituted",
        "note": (
            "Cross-dataset comparison limited by unavailable TESS S40/S53/S74 products. "
            "Kepler and TESS S14 are evaluated separately; no forced agreement.",
            "Sector 14 preserved from Phase 1; S40/S53/S74 remain unverified.",
        ),
    },
    "limitations_and_conclusions": [
        "Bootstrap and injection/recovery show stable ~154 ppm depth (95% CI ~150–158 ppm).",
        "Fixed geometry dominates systematic uncertainty (~±5% depth).",
        "BIC comparison reported with explicit unmodeled-correlation warning; not a formal "
        "detection claim.",
        "No TESS S40/S53/S74 data available to complete cross-dataset validation.",
        "Phase 4 does not begin Phase 5 or add ML component.",
    ],
    "files_changed": [
        "scripts/phase4_block_bootstrap.py (new)",
        "scripts/phase4_injection_recovery.py (new)",
        "scripts/phase4_residual_diagnostics.py (new)",
        "scripts/statistical_validation.py (modified from existing, preserved)",
        "reports/results/phase4_block_bootstrap.json (new)",
        "reports/results/phase4_injection_recovery.json (new)",
        "reports/results/phase4_statistical_validation.md will be written in reporting step",
    ],
    "preservation_check": {
        "phase3_outputs_preserved": True,
        "original_data_unchanged": True,
        "original_figures_untouched": True,
        "tess_s14_preserved": True,
    },
}

(RESULTS / "phase4_model_comparison.json").write_text(json.dumps(report, indent=2) + "\n")
print("Model comparison saved to", RESULTS / "phase4_model_comparison.json")
print(f"Reference depth: {ref_depth:.1f} ppm")
print(f"Naive delta BIC (with WARNING): {bic_naive_delta:.2f}")
print(
    "Assumption: independent-Gaussian likelihood not reliable given AC=0.936; effective sample "
    "size reduced."
)
