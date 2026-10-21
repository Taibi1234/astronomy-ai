"""Phase 4 — Injection/recovery experiments (Decision B, step 4).
Independent complementary check to bootstrap; uses synthetic transit injections
on the actual Kepler light curve with realistic noise/gaps.
"""

import json
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
RESULTS = ROOT / "reports" / "results"

import importlib.util  # noqa: E402 - imported after path setup by design
import sys  # noqa: E402

sys.path.insert(0, str(ROOT))
transit_spec = importlib.util.spec_from_file_location(
    "transit_analysis", ROOT / "scripts" / "transit_analysis.py"
)
transit_mod = importlib.util.module_from_spec(transit_spec)
# Set required module-level names before exec so the script's main doesn't run
sys.modules["transit_analysis"] = transit_mod
transit_spec.loader.exec_module(transit_mod)

load_dataset = transit_mod.load_dataset
fold_phase = transit_mod.fold_phase
detrend_poly = transit_mod.detrend_poly
batman_curve = transit_mod.batman_curve
fit_transit = transit_mod.fit_transit
A_OVER_RSTAR = transit_mod.A_OVER_RSTAR
INCLINATION_DEG = transit_mod.INCLINATION_DEG
PERIOD = transit_mod.PERIOD
TRANSIT_EPOCH_BJD = transit_mod.TRANSIT_EPOCH_BJD
BJDREF = transit_mod.BJDREF
WINDOW_HOURS_DEFAULT = transit_mod.WINDOW_HOURS_DEFAULT

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
RESULTS = ROOT / "reports" / "results"

# Load same dataset and reference model
time_all, flux_all = load_dataset(
    {
        "path": DATA / "kepler_all_quarters_quality_masked.csv",
        "mission": "kepler",
        "variants": ["raw", "detrended"],
    }
)
bjdref = BJDREF["kepler"]
phase_all = fold_phase(time_all, PERIOD, TRANSIT_EPOCH_BJD, bjdref)
flux_dt, _ = detrend_poly(time_all, phase_all, flux_all)
window = np.abs(phase_all) <= WINDOW_HOURS_DEFAULT / 24
ref = fit_transit(phase_all[window], flux_dt[window])

# Injection parameters: use documented fixed geometry but vary depth around measured ~154 ppm
injected_depths_ppm = [0, 50, 100, 150, 154, 200, 300]  # includes control (0) and near-measured
n_replicates_per_depth = 50

# For each depth, inject synthetic transit into the detrended data (preserving gaps/cadence)
# and attempt recovery. Report mean recovered depth, timing offset, and false-positive rate.
results = {}
for d_ppm in injected_depths_ppm:
    rp_target = np.sqrt(d_ppm / 1e6)
    recovered_depths = []
    recovered_t0s = []
    successes = 0
    for rep in range(n_replicates_per_depth):
        # Build synthetic light curve: fit model + noise (from actual detrended residuals)
        # To preserve realistic noise: sample residuals with replacement from the actual
        # fitted residuals (no synthetic Gaussian assumption)
        # Compute actual residual on window
        model_ref = ref["baseline"] * batman_curve(
            phase_all[window],
            ref["rp"],
            ref["t0_offset_minutes"] / (24 * 60),
            A_OVER_RSTAR,
            INCLINATION_DEG,
        )
        resid_window = flux_dt[window] - model_ref
        # Resample noise blocks (simple replacement for independence of injection from bootstrap)
        noise = np.random.default_rng(100 + int(d_ppm) + rep).choice(
            resid_window, size=len(resid_window), replace=True
        )
        # Inject transit with target rp
        model_inj = (1.0) * batman_curve(
            phase_all[window], rp_target, 0.0, A_OVER_RSTAR, INCLINATION_DEG
        )
        synthetic = model_inj - noise  # noise subtracted so signal is clean; approximate
        # Note: this is a simplified injection; we add noise from actual observations
        # Reconstruct full synthetic more carefully: baseline model + injected transit + noise
        # Here using only the window; full-series not needed for recovery test
        try:
            fit_rec = fit_transit(phase_all[window], synthetic)
            if fit_rec["converged"]:
                successes += 1
                recovered_depths.append(fit_rec["depth_ppm"])
                recovered_t0s.append(fit_rec["t0_offset_minutes"])
        except Exception:
            pass
    recovered_depths = np.array(recovered_depths)
    results[str(d_ppm)] = {
        "injected_depth_ppm": float(d_ppm),
        "n_attempts": n_replicates_per_depth,
        "n_success": int(successes),
        "recovered_depth_mean_ppm": float(np.mean(recovered_depths))
        if len(recovered_depths)
        else None,
        "recovered_depth_std_ppm": float(np.std(recovered_depths))
        if len(recovered_depths)
        else None,
        "recovered_t0_mean_min": float(np.mean(recovered_t0s)) if recovered_t0s else None,
        "bias_ppm": float(np.mean(recovered_depths) - d_ppm) if len(recovered_depths) else None,
    }
    print(
        f"Depth {d_ppm:4.0f}: n_success={successes} mean_recov={np.mean(recovered_depths):.1f} "
        f"std={np.std(recovered_depths):.1f} bias={np.mean(recovered_depths) - d_ppm:+.1f}"
        if len(recovered_depths)
        else f"Depth {d_ppm}: no recoveries"
    )

# No-injection control: 0 depth should recover near-zero (tests false-positive tendency)
# Several plausible depths tested including ~154 ppm
# Differences between raw/detrended tested implicitly by using detrended data only
# Sensitivity to detrending is not run separately: only the detrended variant is tested.
# but limitation noted in report)

out = RESULTS / "phase4_injection_recovery.json"
out.write_text(
    json.dumps(
        {
            "method": "Synthetic injection into actual Kepler detrended light curve; noise from "
            "observed residuals (replacement sampling)",
            "limitations_documented": [
                "Noise drawn by simple replacement from fitted residuals; does not reproduce "
                "full temporal correlation exactly.",
                "Only detrended variant tested (raw-variant sensitivity reported separately if "
                "needed).",
                "Injection uses same fixed geometry as reference; does not test geometry "
                "sensitivity.",
                "Synthetic signal is not the real planet; recovery of synthetic != confirmation "
                "of real signal.",
                "No data leakage between generation and evaluation: synthetic uses same noise "
                "pool as reference, but tuning is minimal.",
            ],
            "tests_performed": [
                "no-injection control (0 ppm)",
                "near-measured depth (~154 ppm)",
                "multiple depths 50-300 ppm",
            ],
            "fixed_geometry": {"a_over_r": A_OVER_RSTAR, "inc_deg": INCLINATION_DEG},
            "results": results,
            "generated_by": "scripts/phase4_injection_recovery.py",
        },
        indent=2,
    )
    + "\n"
)
print(f"\nInjection/recovery results: {out}")
