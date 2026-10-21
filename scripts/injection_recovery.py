"""Phase 4 injection/recovery experiments (complementary check to the bootstrap).

Synthetic transits are injected into the REAL quality-masked, detrended full-Kepler
light curve, preserving its cadence, gaps, and residual correlations. Each replicate
is then passed through the same fitting pipeline as the real data. Depth-0 replicates
are no-injection controls and quantify false-positive behavior.

Recovery is defined against thresholds derived from the bootstrap (read from
reports/results/phase4_statistical_validation.json): a replicate "recovers" when its
fitted depth lies within +-2 bootstrap-sigmas of the injected depth. This measures
pipeline recovery of a SYNTHETIC signal; it is not confirmation of the real planet.

Depths tested: 0 (controls, n=120), 75/150/225/300 ppm (n=60 each).
Fixed seed; batman model with the same fixed geometry as the main pipeline.

Usage:
    python scripts/injection_recovery.py
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from statistical_validation import fit_free, software_versions  # noqa: E402
from transit_analysis import (  # noqa: E402
    BJDREF,
    PERIOD,
    TRANSIT_EPOCH_BJD,
    WINDOW_HOURS_DEFAULT,
    batman_curve,
    detrend_poly,
    fold_phase,
    load_dataset,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
FIGURES = ROOT / "reports" / "figures"
RESULTS = ROOT / "reports" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

SEED = 1234
A_OVER_RSTAR, INCLINATION_DEG = 3.4, 84.5
KEPLER_SPEC = {
    "path": DATA / "kepler_all_quarters_quality_masked.csv",
    "mission": "kepler",
    "variants": ["detrended"],
}

INJECTION_DEPTHS_PPM = [0, 75, 150, 225, 300]
N_REPLICATES = {0: 120, 75: 60, 150: 60, 225: 60, 300: 60}
RECOVERY_SIGMA = 2.0  # within +-2 bootstrap sigmas counts as recovered


def depth_to_rp(depth_ppm):
    return float(np.sqrt(depth_ppm * 1e-6))


def inject_signal(phase_days, flux, depth_ppm, t0_days=0.0):
    if depth_ppm == 0:
        return flux.copy()
    signal = batman_curve(
        phase_days, depth_to_rp(depth_ppm), t0_days, A_OVER_RSTAR, INCLINATION_DEG
    )
    continuum = np.median(flux)
    return flux + continuum * (signal - 1.0)


def run_injection(flux, phase, depth_ppm, rng):
    t0_injected = 0.0  # at the published ephemeris center
    y = inject_signal(phase, flux, depth_ppm, t0_injected)
    window = np.abs(phase) <= WINDOW_HOURS_DEFAULT / 24
    order = np.argsort(phase)  # keep a stable ordering; fit needs no time order
    fit = fit_free(phase[window][order], y[window][order])
    return {
        "injected_depth_ppm": depth_ppm,
        "fitted_depth_ppm": fit["depth_ppm"],
        "fitted_offset_min": fit["t0_offset_minutes"],
        "rss_improvement_pct": fit["rss_improvement_pct"],
    }


def summarize(results, sigma_boot):
    by_depth = {}
    for depth in INJECTION_DEPTHS_PPM:
        rows = [r for r in results if r["injected_depth_ppm"] == depth]
        fitted = np.array([r["fitted_depth_ppm"] for r in rows])
        offsets = np.array([r["fitted_offset_min"] for r in rows])
        impr = np.array([r["rss_improvement_pct"] for r in rows])
        half_window = RECOVERY_SIGMA * sigma_boot if sigma_boot else 15.0
        recovered = np.abs(fitted - depth) <= half_window
        by_depth[str(depth)] = {
            "n": len(rows),
            "fitted_depth_mean_ppm": float(np.mean(fitted)),
            "fitted_depth_std_ppm": float(np.std(fitted)),
            "depth_bias_ppm": float(np.mean(fitted - depth)),
            "offset_mean_min": float(np.mean(offsets)),
            "offset_std_min": float(np.std(offsets)),
            "rss_improvement_median_pct": float(np.median(impr)),
            "recovery_fraction": float(np.mean(recovered)),
            "recovery_rule": f"|fitted - injected| <= {half_window:.1f} ppm",
        }
        print(
            f"depth {depth:>3} ppm: fitted {np.mean(fitted):7.1f} +/- {np.std(fitted):5.1f} ppm | "
            f"bias {np.mean(fitted - depth):+6.1f} ppm | offset {np.mean(offsets):+5.2f} +/- "
            f"{np.std(offsets):4.2f} min | recovery {100 * np.mean(recovered):.0f}%"
        )
    return by_depth


def main():
    print("== Phase 4 injection/recovery ==")
    time, flux = load_dataset(KEPLER_SPEC)
    phase_all = fold_phase(time, PERIOD, TRANSIT_EPOCH_BJD, BJDREF["kepler"])
    flux_dt, _ = detrend_poly(time, phase_all, flux)

    # Window points only (same region as the real analysis), in time order.
    window = np.abs(phase_all) <= WINDOW_HOURS_DEFAULT / 24
    order = np.argsort(time[window])
    phase_w = phase_all[window][order]
    flux_w = flux_dt[window][order]

    bootstrap_json = RESULTS / "phase4_statistical_validation.json"
    sigma_boot = None
    if bootstrap_json.exists():
        payload = json.loads(bootstrap_json.read_text())
        sigma_boot = payload["bootstrap"]["1orbit_strat"]["depth_std_ppm"]
        print(
            f"bootstrap sigma (1orbit_strat) = {sigma_boot:.1f} ppm (from statistical_validation)"
        )
    else:
        print(
            "WARNING: bootstrap JSON not found; recovery fractions use a fixed 15 ppm half-window."
        )

    rng = np.random.default_rng(SEED)
    results = []
    for depth in INJECTION_DEPTHS_PPM:
        for _rep in range(N_REPLICATES[depth]):
            results.append(run_injection(flux_w, phase_w, depth, rng))
        print(f"  depth {depth} ppm: {N_REPLICATES[depth]} replicates done")
    by_depth = summarize(results, sigma_boot)

    payload = {
        "generated_by": "scripts/injection_recovery.py",
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "software_versions": software_versions(),
        "seed": SEED,
        "injection": {
            "depths_ppm": INJECTION_DEPTHS_PPM,
            "n_replicates": N_REPLICATES,
            "t0_injected": "ephemeris center (offset 0)",
            "noise": (
                "real quality-masked detrended Kepler light curve "
                "(cadence, gaps, correlations preserved)"
            ),
            "geometry": {"a_over_r": A_OVER_RSTAR, "inclination_deg": INCLINATION_DEG},
        },
        "results_by_depth": by_depth,
        "false_positive_note": (
            "At injected depth 0, recovery_fraction is the fraction of no-signal "
            "replicates passing the recovery rule, i.e. the false-positive rate of "
            "the recovery criterion itself (not a detection significance)."
        ),
        "distinction": (
            "These experiments measure recovery of SYNTHETIC signals through the "
            "pipeline; they do not confirm the real planet's signal."
        ),
        "raw_replicates": results,
    }
    out = RESULTS / "phase4_injection_recovery.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    depths = INJECTION_DEPTHS_PPM[1:]
    bias = [by_depth[str(d)]["depth_bias_ppm"] for d in depths]
    rec = [100 * by_depth[str(d)]["recovery_fraction"] for d in depths]
    stds = [by_depth[str(d)]["fitted_depth_std_ppm"] for d in depths]
    axes[0].errorbar(depths, bias, yerr=stds, fmt="o-")
    axes[0].axhline(0, color="k", lw=0.8)
    axes[0].set_xlabel("Injected depth (ppm)")
    axes[0].set_ylabel("Fitted - injected (ppm)")
    axes[0].set_title("Recovery bias (error bars = replicate scatter)")
    axes[0].grid(alpha=0.3)
    axes[1].plot(depths, rec, "s-")
    for d, r in zip(depths, rec, strict=True):
        axes[1].annotate(f"{r:.0f}%", (d, r), textcoords="offset points", xytext=(0, 6))
    axes[1].set_xlabel("Injected depth (ppm)")
    axes[1].set_ylabel("Recovery fraction (%)")
    axes[1].set_ylim(0, 105)
    axes[1].set_title(f"Recovery (within +/-{RECOVERY_SIGMA:g} bootstrap-sigma)")
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase4_injection_recovery.png", dpi=140)
    plt.close(fig)
    print(f"\nResults JSON: {out}")
    print("Figure: phase4_injection_recovery.png")


if __name__ == "__main__":
    main()
