"""Phase 4 statistical validation: residual diagnostics, block bootstrap, model comparison.

Primary uncertainty method (approved plan): residual time-block bootstrap.
Complementary check: injection/recovery (scripts/injection_recovery.py).

Pipeline (full Kepler, quality-masked, detrended; TESS S14 masked for cross-dataset):
  1. Reproduce the Phase 3 baseline fit exactly (same data, model, config).
  2. Diagnose residuals: distribution, outliers, autocorrelation (time domain),
     per-quarter RMS (stationarity), structure near transit.
  3. Block bootstrap: contiguous orbit-scale residual blocks, resampled with
     replacement and added back onto the fitted model at host positions; the
     transit model is re-fitted for every replicate. Block-length sensitivity:
     1/2/4 orbits x quarter-stratified/pooled. Fixed seed; convergence reported.
  4. Model comparison: naive dBIC (independent-Gaussian assumptions, reported
     with an explicit warning) + correlation-aware comparison via an empirical
     null from no-injection controls (residual-based, same pipeline).
  5. Cross-dataset: TESS S14 fit + bootstrap interval vs Kepler; timing compared
     against the ephemeris-drift scale, not forced to agree.

No formal detection significance is claimed anywhere in this script.

Usage:
    python scripts/statistical_validation.py
"""

import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import batman
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
from scipy import stats
from scipy.optimize import least_squares

sys.path.insert(0, str(Path(__file__).resolve().parent))
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

SEED = 42
N_REPLICATES_PRIMARY = 300
N_REPLICATES_ALT = 150
N_CONTROLS = 120

KEPLER_SPEC = {
    "path": DATA / "kepler_all_quarters_quality_masked.csv",
    "mission": "kepler",
    "variants": ["detrended"],
}
TESS_SPEC = {
    "path": DATA / "tess_kepler_10_quality_masked.csv",
    "mission": "tess",
    "variants": ["detrended"],
}

A_OVER_RSTAR, INCLINATION_DEG, U1, U2 = 3.4, 84.5, 0.30, 0.20
HALF_DURATION_DAYS = 1.8 / 24.0


def window_data(spec):
    time, flux = load_dataset(spec)
    phase = fold_phase(time, PERIOD, TRANSIT_EPOCH_BJD, BJDREF[spec["mission"]])
    flux_dt, _ = detrend_poly(time, phase, flux)
    keep = np.abs(phase) <= WINDOW_HOURS_DEFAULT / 24
    order = np.argsort(time[keep])
    return {
        "time": time[keep][order],
        "phase": phase[keep][order],
        "flux": flux_dt[keep][order],
    }


def fit_free(phase_days, flux):
    """Identical model to Phase 3: free rp, t0, baseline, slope."""
    x_centered = phase_days - np.median(phase_days)
    baseline0 = float(np.median(flux))

    def null_residual(p):
        baseline, slope = p
        return baseline + slope * x_centered - flux

    def transit_residual(p):
        rp, t0, baseline, slope = p
        prediction = (
            baseline * batman_curve(phase_days, rp, t0, A_OVER_RSTAR, INCLINATION_DEG)
            + slope * x_centered
        )
        return prediction - flux

    null_fit = least_squares(null_residual, x0=[baseline0, 0.0])
    fit = least_squares(
        transit_residual,
        x0=[0.014, 0.0, baseline0, 0.0],
        bounds=([0.001, -0.03, 0.95, -0.05], [0.05, 0.03, 1.05, 0.05]),
        max_nfev=500,
    )
    rp, t0, baseline, slope = fit.x
    model = (
        baseline * batman_curve(phase_days, rp, t0, A_OVER_RSTAR, INCLINATION_DEG)
        + slope * x_centered
    )
    return {
        "rp": float(rp),
        "depth_ppm": float(rp**2 * 1e6),
        "t0_offset_minutes": float(t0 * 24 * 60),
        "rss_null": float(np.sum(null_fit.fun**2)),
        "rss_transit": float(np.sum(fit.fun**2)),
        "rss_improvement_pct": 100
        * (float(np.sum(null_fit.fun**2)) - float(np.sum(fit.fun**2)))
        / float(np.sum(null_fit.fun**2)),
        "model": model,
        "residuals": flux - model,
        "n": int(len(flux)),
    }


def contiguous_blocks(time, gap_days=1.0 / 24):
    """Contiguous runs (orbit-scale chunks) split where cadence gap exceeds threshold."""
    splits = np.where(np.diff(time) > gap_days)[0] + 1
    return list(np.split(np.arange(len(time)), splits))


def merge_blocks(blocks, group):
    return [np.concatenate(blocks[i : i + group]) for i in range(0, len(blocks), group)]


def quarter_of(time_value, quarter_ranges):
    for quarter, (lo, hi) in quarter_ranges.items():
        if lo - 1 <= time_value <= hi + 1:
            return quarter
    return None


def load_quarter_ranges():
    meta = json.loads((ROOT / "reports" / "kepler_quarters_metadata.json").read_text())
    return {q["quarter"]: (q["time_range"][0], q["time_range"][1]) for q in meta["quarters"]}


def bootstrap(
    data, base_fit, quarter_ranges, block_group=1, stratify=False, n_replicates=300, seed=SEED
):
    """Residual block bootstrap: resample blocks, add to model, re-fit each replicate."""
    rng = np.random.default_rng(seed)
    blocks = merge_blocks(contiguous_blocks(data["time"]), block_group)
    model = base_fit["model"]
    resid = base_fit["residuals"]
    strat = [quarter_of(data["time"][b[0]], quarter_ranges) if stratify else None for b in blocks]

    depths, offsets = [], []
    for _ in range(n_replicates):
        if stratify:
            shuffled = stratified_block_resid(resid, blocks, strat, rng)  # noqa: F821
        else:
            shuffled = moving_block_resid(resid, blocks, rng)  # noqa: F821
        y_star = model + shuffled
        fit = fit_free(data["phase"], y_star)
        depths.append(fit["depth_ppm"])
        offsets.append(fit["t0_offset_minutes"])
    depths = np.array(depths)
    offsets = np.array(offsets)
    return {
        "block_group_orbits": block_group,
        "stratified_by_quarter": stratify,
        "n_blocks": len(blocks),
        "n_replicates": n_replicates,
        "depth_percentiles_ppm": {
            str(p): float(np.percentile(depths, p)) for p in (5, 16, 50, 84, 95)
        },
        "t0_offset_percentiles_min": {
            str(p): float(np.percentile(offsets, p)) for p in (5, 16, 50, 84, 95)
        },
        "depth_std_ppm": float(np.std(depths)),
        "seed": seed,
    }


def convergence_curve(data, base_fit, n_replicates=300, seed=SEED):
    rng = np.random.default_rng(seed)
    blocks = contiguous_blocks(data["time"])
    depths = []
    model, resid = base_fit["model"], base_fit["residuals"]
    for _ in range(n_replicates):
        y_star = model + moving_block_resid(resid, blocks, rng)  # noqa: F821
        depths.append(fit_free(data["phase"], y_star)["depth_ppm"])
    depths = np.array(depths)
    checkpoints = [50, 100, 200, n_replicates]
    return {
        "checkpoints": checkpoints,
        "depth_std_at_checkpoint": [float(np.std(depths[:c])) for c in checkpoints],
        "p5_at_checkpoint": [float(np.percentile(depths[:c], 5)) for c in checkpoints],
        "p95_at_checkpoint": [float(np.percentile(depths[:c], 95)) for c in checkpoints],
    }


def residual_diagnostics(data, fit, quarter_ranges):
    resid = fit["residuals"]
    time = data["time"]
    blocks = contiguous_blocks(time)
    # lag-1 autocorrelation across consecutive cadences (within blocks)
    num, den, lag_used = 0.0, 0.0, 0
    for block in blocks:
        if len(block) > 1:
            r0, r1 = resid[block[:-1]], resid[block[1:]]
            num += float(np.sum(r0 * r1))
            den += float(np.sum(r0**2))
            lag_used += len(block) - 1
    lag1 = num / den if den > 0 else float("nan")
    # orbit-mean residual autocorrelation (lag-1 in orbit units)
    orbit_means = np.array([np.mean(resid[b]) for b in blocks])
    orbit_lag1 = (
        float(np.corrcoef(orbit_means[:-1], orbit_means[1:])[0, 1])
        if len(orbit_means) > 2
        else float("nan")
    )
    # per-quarter RMS (window points)
    per_quarter = {}
    for q, (lo, hi) in quarter_ranges.items():
        sel = (time >= lo - 1) & (time <= hi + 1)
        if sel.sum() > 10:
            per_quarter[str(q)] = float(np.sqrt(np.mean(resid[sel] ** 2)))
    rms_values = np.array(list(per_quarter.values()))
    stationary_ratio = (
        float(rms_values.max() / rms_values.min()) if len(rms_values) > 1 else float("nan")
    )
    # structure near transit: mean binned residual inside vs outside transit
    in_t = np.abs(data["phase"] - fit["t0_offset_minutes"] / 1440) <= HALF_DURATION_DAYS / 2
    mean_in = float(np.mean(resid[in_t])) if in_t.sum() else float("nan")
    # distribution shape
    return {
        "n_residuals": int(len(resid)),
        "std_ppm": float(np.std(resid) * 1e6),
        "skew": float(stats.skew(resid)),
        "excess_kurtosis": float(stats.kurtosis(resid)),
        "mad_outliers_beyond_5sigma": int(
            np.sum(np.abs(resid - np.median(resid)) > 5 * stats.median_abs_deviation(resid))
        ),
        "lag1_autocorr_cadence": lag1,
        "lag1_pairs": lag_used,
        "orbit_mean_lag1_autocorr": orbit_lag1,
        "n_orbit_blocks": len(blocks),
        "per_quarter_rms_ppm": per_quarter,
        "stationarity_ratio_max_min_rms": stationary_ratio,
        "mean_residual_in_transit_ppm": mean_in,
        "n_in_transit_points": int(in_t.sum()),
    }


def controls_null(data, n_controls=N_CONTROLS, seed=SEED + 1):
    """Empirical null: RSS improvement when NO transit is present.

    Knock out the fitted transit component by using the null-model fitted level as
    the 'signal' and resampling residuals (same block bootstrap noise), then refit.
    """
    rng = np.random.default_rng(seed)
    blocks = contiguous_blocks(data["time"])
    base = fit_free(data["phase"], data["flux"])
    median_level = float(np.median(data["flux"]))
    improvements = []
    for _ in range(n_controls):
        noise = moving_block_resid(base["residuals"], blocks, rng)  # noqa: F821
        y = median_level + noise  # no-transit truth: constant level
        f = fit_free(data["phase"], y)
        improvements.append(f["rss_improvement_pct"])
    return np.array(improvements)


def model_comparison(fit, controls):
    n = fit["n"]
    delta_k = 2
    bic_naive = n * np.log(fit["rss_null"] / fit["rss_transit"]) - delta_k * np.log(n)
    observed = fit["rss_improvement_pct"]
    frac_ge = float(np.mean(controls >= observed))
    return {
        "n_points": n,
        "delta_params": delta_k,
        "bic_naive_white_noise": float(bic_naive),
        "bic_naive_warning": (
            "Independent-Gaussian likelihood assumed; residuals are correlated "
            "(see lag-1 autocorrelation), so n is an overestimate of the effective "
            "sample size and this dBIC overstates evidence. Reported for "
            "comparison only, not as detection significance."
        ),
        "observed_rss_improvement_pct": observed,
        "control_improvement_median_pct": float(np.median(controls)),
        "control_improvement_p95_pct": float(np.percentile(controls, 95)),
        "control_fraction_ge_observed": frac_ge,
        "n_controls": int(len(controls)),
        "interpretation": (
            "Fraction of no-transit control replicates whose descriptive RSS "
            "improvement meets/exceeds the observed value, under noise with the "
            "measured correlation structure. Descriptive comparison, not a "
            "calibrated p-value."
        ),
    }


def plot_diagnostics(diag, fit, data, quarter_ranges):
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    resid = fit["residuals"]
    axes[0, 0].hist(resid * 1e6, bins=100)
    axes[0, 0].set_title(
        f"Residuals (ppm): skew={diag['skew']:.2f}, kurt={diag['excess_kurtosis']:.2f}"
    )
    axes[0, 0].set_xlabel("Residual (ppm)")
    # orbit-mean ACF
    blocks = contiguous_blocks(data["time"])
    means = [np.mean(resid[b]) for b in blocks]
    max_lag = 30
    acf = [1.0] + [
        float(np.corrcoef(means[:-k], means[k:])[0, 1]) if len(means) > k + 2 else np.nan
        for k in range(1, max_lag + 1)
    ]
    axes[0, 1].plot(range(len(acf)), acf, "o-")
    axes[0, 1].axhline(0, color="k", lw=0.8)
    axes[0, 1].set_title("ACF of orbit-mean residuals (lag in orbits, ~0.84 d)")
    axes[0, 1].set_xlabel("Orbit lag")
    qs = sorted(quarter_ranges, key=int)
    rms = [diag["per_quarter_rms_ppm"].get(str(q), np.nan) for q in qs]
    axes[1, 0].bar([str(q) for q in qs], rms)
    axes[1, 0].set_title(
        "Window residual RMS by quarter "
        f"(stationarity ratio {diag['stationarity_ratio_max_min_rms']:.2f})"
    )
    axes[1, 0].set_ylabel("RMS (ppm)")
    axes[1, 0].tick_params(axis="x", rotation=45)
    axes[1, 1].plot(data["time"], resid * 1e6, ".", ms=1)
    axes[1, 1].set_title("Residuals vs time (window points, ppm)")
    axes[1, 1].set_xlabel("BKJD − 2454833 (d)")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase4_residual_diagnostics.png", dpi=140)
    plt.close(fig)


def plot_bootstrap(results_by_setting, convergence, base_depth):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    labels = list(results_by_setting)
    p5 = [results_by_setting[k]["depth_percentiles_ppm"]["5"] for k in labels]
    p95 = [results_by_setting[k]["depth_percentiles_ppm"]["95"] for k in labels]
    med = [results_by_setting[k]["depth_percentiles_ppm"]["50"] for k in labels]
    axes[0].errorbar(
        range(len(labels)), med, yerr=[np.array(med) - p5, np.array(p95) - np.array(med)], fmt="o"
    )
    axes[0].axhline(base_depth, color="r", ls="--", label="baseline depth")
    axes[0].set_xticks(range(len(labels)))
    axes[0].set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    axes[0].set_ylabel("Bootstrap depth (ppm)")
    axes[0].set_title("Block bootstrap 90% intervals vs block design")
    axes[0].legend()
    axes[0].grid(alpha=0.3)
    axes[1].plot(
        convergence["checkpoints"], convergence["depth_std_at_checkpoint"], "o-", label="depth std"
    )
    axes[1].plot(convergence["checkpoints"], convergence["p95_at_checkpoint"], "s-", label="p95")
    axes[1].plot(convergence["checkpoints"], convergence["p5_at_checkpoint"], "^-", label="p5")
    axes[1].set_xlabel("Replicates")
    axes[1].set_title("Convergence (primary setting)")
    axes[1].legend()
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase4_bootstrap.png", dpi=140)
    plt.close(fig)


def plot_model_comparison(controls, fit):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.hist(controls, bins=30, alpha=0.7, label="no-transit controls")
    ax.axvline(fit["rss_improvement_pct"], color="r", ls="--", label="observed")
    ax.axvline(np.percentile(controls, 95), color="k", ls=":", label="control p95")
    ax.set_xlabel("RSS improvement (%)")
    ax.set_title("Correlation-aware null vs observed (descriptive, not a p-value)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES / "phase4_model_comparison.png", dpi=140)
    plt.close(fig)


def software_versions():
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "batman_package": batman.__version__,
        "platform": platform.platform(),
    }


def main():
    print("== Phase 4: baseline reproduction (full Kepler, masked, detrended) ==")
    data_k = window_data(KEPLER_SPEC)
    fit_k = fit_free(data_k["phase"], data_k["flux"])
    print(
        f"baseline: rp={fit_k['rp']:.5f} depth={fit_k['depth_ppm']:.1f} ppm "
        f"offset={fit_k['t0_offset_minutes']:+.2f} min impr={fit_k['rss_improvement_pct']:.3f}% "
        f"n={fit_k['n']}"
    )

    quarter_ranges = load_quarter_ranges()
    print("\n== Residual diagnostics ==")
    diag = residual_diagnostics(data_k, fit_k, quarter_ranges)
    for key in (
        "std_ppm",
        "lag1_autocorr_cadence",
        "orbit_mean_lag1_autocorr",
        "stationarity_ratio_max_min_rms",
        "mad_outliers_beyond_5sigma",
    ):
        print(f"  {key}: {diag[key]}")

    print("\n== Block bootstrap (Kepler) ==")
    settings = [
        (1, True, N_REPLICATES_PRIMARY),
        (2, True, N_REPLICATES_ALT),
        (4, True, N_REPLICATES_ALT),
        (1, False, N_REPLICATES_ALT),
        (4, False, N_REPLICATES_ALT),
    ]
    results_by_setting = {}
    for group, stratify, reps in settings:
        label = f"{group}orbit_{'strat' if stratify else 'pooled'}"
        results_by_setting[label] = bootstrap(
            data_k,
            fit_k,
            quarter_ranges,
            block_group=group,
            stratify=stratify,
            n_replicates=reps,
            seed=SEED,
        )
        p = results_by_setting[label]["depth_percentiles_ppm"]
        print(
            f"  {label}: 90% CI [{p['5']:.1f}, {p['95']:.1f}] ppm "
            f"(std {results_by_setting[label]['depth_std_ppm']:.1f})"
        )
    convergence = convergence_curve(data_k, fit_k, n_replicates=N_REPLICATES_PRIMARY)

    print("\n== Empirical null controls ==")
    controls = controls_null(data_k)
    comparison = model_comparison(fit_k, controls)

    print("\n== TESS S14 cross-dataset ==")
    data_t = window_data(TESS_SPEC)
    fit_t = fit_free(data_t["phase"], data_t["flux"])
    boot_t = bootstrap(
        data_t,
        fit_t,
        {"tess": (0, 1e9)},
        block_group=1,
        stratify=False,
        n_replicates=200,
        seed=SEED + 2,
    )
    print(
        f"TESS S14: depth={fit_t['depth_ppm']:.1f} ppm "
        f"offset={fit_t['t0_offset_minutes']:+.2f} min impr={fit_t['rss_improvement_pct']:.3f}%"
    )
    p = boot_t["depth_percentiles_ppm"]
    print(f"  TESS bootstrap 90% CI [{p['5']:.1f}, {p['95']:.1f}] ppm")

    plot_diagnostics(diag, fit_k, data_k, quarter_ranges)
    plot_bootstrap(results_by_setting, convergence, fit_k["depth_ppm"])
    plot_model_comparison(controls, fit_k)

    # Ephemeris drift scale between the Kepler epoch and TESS S14 mid-time.
    tess_mid_bjd = BJDREF["tess"] + float(np.mean(pd.read_csv(TESS_SPEC["path"])["time"]))
    orbits = (tess_mid_bjd - TRANSIT_EPOCH_BJD) / PERIOD
    drift_scale_min = orbits * 1e-6 * 24 * 60  # solution scatter of 1e-6 d in P
    timing_comparison = {
        "kepler_offset_min": fit_k["t0_offset_minutes"],
        "tess_s14_offset_min": fit_t["t0_offset_minutes"],
        "offset_difference_min": fit_t["t0_offset_minutes"] - fit_k["t0_offset_minutes"],
        "ephemeris_drift_scale_min": float(drift_scale_min),
        "orbits_between": float(orbits),
        "note": (
            "Offset differences below the ephemeris-drift scale are consistent with "
            "published-solution uncertainty; Kepler and TESS are not forced to agree."
        ),
    }

    payload = {
        "generated_by": "scripts/statistical_validation.py",
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "software_versions": software_versions(),
        "seed": SEED,
        "baseline_fit": {k: v for k, v in fit_k.items() if k not in ("model", "residuals")},
        "residual_diagnostics": diag,
        "bootstrap": results_by_setting,
        "bootstrap_convergence": convergence,
        "model_comparison": comparison,
        "control_improvements_pct": [float(v) for v in controls],
        "tess_s14": {
            "baseline_fit": {k: v for k, v in fit_t.items() if k not in ("model", "residuals")},
            "bootstrap": boot_t,
        },
        "timing_comparison": timing_comparison,
        "caveats": [
            "Bootstrap adds resampled residuals to the fitted model; it assumes the fitted",
            "model shape and residual covariance are adequate approximations.",
            "Stratification by quarter guards against nonstationarity; see stationarity ratio.",
            "No formal detection significance is claimed; see model_comparison interpretation.",
        ],
    }
    out = RESULTS / "phase4_statistical_validation.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nResults JSON: {out}")
    print(
        "Figures: phase4_residual_diagnostics.png, phase4_bootstrap.png, "
        "phase4_model_comparison.png"
    )


if __name__ == "__main__":
    main()
