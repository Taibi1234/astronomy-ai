"""Phase 3 transit-analysis workflow.

Fits the Kepler-10 b transit on several dataset/preprocessing combinations and
runs documented robustness grids (ephemeris uncertainty, transit-window width,
fixed geometry). Produces binned phase-folded figures with uncertainty bars,
fit + residual panels, and one machine-readable results file:

    reports/results/phase3_transit_analysis.json
    reports/figures/phase3_*.png

Framing: Kepler-10 b is a known planet; this is a re-detection / pipeline-
validation exercise. RSS improvements reported here are descriptive fit-quality
metrics, NOT detection significances (that is Phase 4 scope).

Models
------
Null model:      flux = baseline + slope * (t - t_center)          [2 params]
Transit model:   flux = baseline + slope * (t - t_center) + depth-shape  [4 params]
Free params: radius ratio rp, timing offset t0, baseline, slope.
Fixed params (diagnostic assumptions): a/R* = 3.4, inclination = 84.5 deg,
quadratic limb darkening u1 = 0.30, u2 = 0.20, period P (fixed within a run;
varied across the ephemeris grid).

Detrending (optional, deliberately mild)
---------------------------------------
Per contiguous segment (split where the time gap exceeds 1 day), fit a degree-2
polynomial to OUT-OF-TRANSIT points only (|phase| >= 3 h), subtract it, and add the
segment's median level back so the continuum stays near unity. The in-transit region
never enters the fit, so the signal cannot be fitted away; a low degree avoids
erasing the shallow transit along with stellar variability.

Usage:
    python scripts/transit_analysis.py
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import batman
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
FIGURES = ROOT / "reports" / "figures"
RESULTS = ROOT / "reports" / "results"
FIGURES.mkdir(parents=True, exist_ok=True)
RESULTS.mkdir(parents=True, exist_ok=True)

# Ephemeris (NASA Exoplanet Archive, verified in Phase 2; uncertainties used below).
PERIOD = 0.837491225  # d
TRANSIT_EPOCH_BJD = 2454964.575  # BJD TDB
EPHEM_PERIOD_SCATTER = 1.0e-6  # d; scatter between published solutions (measured)
EPHEM_T0_SIGMA = 2.82e-4  # d; archive 1-sigma on T0

BJDREF = {"kepler": 2454833.0, "tess": 2457000.0}

# Fixed transit geometry (diagnostic assumptions; varied in the geometry grid).
A_OVER_RSTAR = 3.4
INCLINATION_DEG = 84.5
U1, U2 = 0.30, 0.20

HALF_DURATION_DAYS = 1.8 / 24.0  # ~1.8 h duration assumption (fixed box half-width)
WINDOW_HOURS_DEFAULT = 6.0
DETREND_EXCLUDE_HOURS = 3.0
BIN_MINUTES = 30.0

DATASETS = {
    "kepler_q0_original": {
        "path": DATA / "kepler_kepler_10.csv",
        "mission": "kepler",
        "variants": ["raw"],
    },
    "kepler_q0_masked": {
        "path": DATA / "kepler_kepler_10_quality_masked.csv",
        "mission": "kepler",
        "variants": ["raw", "detrended"],
    },
    "kepler_all_masked": {
        "path": DATA / "kepler_all_quarters_quality_masked.csv",
        "mission": "kepler",
        "variants": ["raw", "detrended"],
    },
    "tess_s14_masked": {
        "path": DATA / "tess_kepler_10_quality_masked.csv",
        "mission": "tess",
        "variants": ["raw"],
    },
}


def load_dataset(spec):
    df = pd.read_csv(spec["path"])
    if list(df.columns) != ["time", "normalized_flux"]:
        raise ValueError(f"Unexpected columns in {spec['path']}")
    time = df["time"].to_numpy(float)
    flux = df["normalized_flux"].to_numpy(float)
    valid = np.isfinite(time) & np.isfinite(flux)
    return time[valid], flux[valid]


def fold_phase(time, period, t0_bjd, bjdref):
    epoch = t0_bjd - bjdref
    return ((time - epoch + period / 2) % period) - period / 2


def detrend_poly(time, phase_days, flux, degree=2, exclude_days=DETREND_EXCLUDE_HOURS / 24):
    """Subtract a per-segment polynomial fitted to out-of-transit points only.

    After subtraction, the segment continuum stays at its fitted level (near unity):
    only the zero-mean trend wiggle is removed, so the multiplicative transit model
    and the baseline bounds stay meaningful for detrended data.
    """
    trend = np.zeros_like(flux)
    split = np.where(np.diff(time) > 1.0)[0] + 1
    for segment in np.split(np.arange(len(time)), split):
        if len(segment) < 10:
            continue  # too few points to detrend; leave segment unchanged
        out = np.abs(phase_days[segment]) >= exclude_days
        if out.sum() < degree + 1:
            out = np.ones(len(segment), dtype=bool)
        coeffs = np.polyfit(time[segment][out], flux[segment][out], degree)
        segment_trend = np.polyval(coeffs, time[segment])
        trend[segment] = segment_trend - np.median(segment_trend)
    return flux - trend, trend


def batman_curve(phase_days, rp, t0, a_over_r=A_OVER_RSTAR, inc_deg=INCLINATION_DEG):
    """batman light curve on folded phase (days); dip centered at phase = t0."""
    params = batman.TransitParams()
    params.t0 = t0
    params.per = PERIOD
    params.rp = rp
    params.a = a_over_r
    params.inc = inc_deg
    params.ecc = 0.0
    params.w = 90.0
    params.limb_dark = "quadratic"
    params.u = [U1, U2]
    model = batman.TransitModel(params, phase_days)
    return model.light_curve(params)


def fit_transit(phase_days, flux, a_over_r=A_OVER_RSTAR, inc_deg=INCLINATION_DEG):
    """Fit transit vs linear-baseline null model on phase-folded data (days)."""
    x_centered = phase_days - np.median(phase_days)
    baseline0 = float(np.median(flux))
    slope0 = 0.0

    def null_residual(p):
        baseline, slope = p
        return baseline + slope * x_centered - flux

    def transit_residual(p):
        rp, t0, baseline, slope = p
        prediction = (
            baseline * batman_curve(phase_days, rp, t0, a_over_r, inc_deg) + slope * x_centered
        )
        return prediction - flux

    null_fit = least_squares(null_residual, x0=[baseline0, slope0])
    fit = least_squares(
        transit_residual,
        x0=[0.014, 0.0, baseline0, slope0],
        bounds=([0.001, -0.03, 0.95, -0.05], [0.05, 0.03, 1.05, 0.05]),
        max_nfev=500,
    )
    rp, t0, baseline, slope = fit.x
    model = baseline * batman_curve(phase_days, rp, t0, a_over_r, inc_deg) + slope * x_centered
    rss_null = float(np.sum(null_fit.fun**2))
    rss_transit = float(np.sum(fit.fun**2))
    in_transit = np.abs(phase_days - t0) <= HALF_DURATION_DAYS / 2
    resid = flux - model
    return {
        "rp": float(rp),
        "depth_ppm": float(rp**2 * 1e6),
        "t0_offset_minutes": float(t0 * 24 * 60),
        "baseline": float(baseline),
        "slope_per_day": float(slope),
        "rss_null": rss_null,
        "rss_transit": rss_transit,
        "rss_improvement_pct": 100 * (rss_null - rss_transit) / rss_null,
        "n_points": int(len(flux)),
        "n_params_transit": 4,
        "n_params_null": 2,
        "rms_residual_in_transit": float(np.sqrt(np.mean(resid[in_transit] ** 2))),
        "rms_residual_out_of_transit": float(
            np.sqrt(np.mean(resid[(np.abs(phase_days - t0) > 2 / 24)] ** 2))
        ),
        "model_flux": model,
        "residuals": resid,
        "in_transit_mask": in_transit,
        "converged": bool(fit.success),
    }


def bin_phase(phase_hours, flux, bin_minutes=BIN_MINUTES, window_hours=WINDOW_HOURS_DEFAULT):
    edges = np.arange(-window_hours, window_hours + bin_minutes / 60, bin_minutes / 60)
    centers = 0.5 * (edges[:-1] + edges[1:])
    means, errors, counts = [], [], []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        sel = (phase_hours >= lo) & (phase_hours < hi)
        if sel.sum() >= 2:
            means.append(float(np.mean(flux[sel])))
            errors.append(float(np.std(flux[sel]) / np.sqrt(sel.sum())))
            counts.append(int(sel.sum()))
        else:
            means.append(np.nan)
            errors.append(np.nan)
            counts.append(int(sel.sum()))
    return centers, np.array(means), np.array(errors), np.array(counts)


def analyze_dataset(name, spec, period=PERIOD, t0_bjd=TRANSIT_EPOCH_BJD):
    time, flux = load_dataset(spec)
    bjdref = BJDREF[spec["mission"]]
    phase = fold_phase(time, period, t0_bjd, bjdref)
    results = {}
    for variant in spec["variants"]:
        if variant == "detrended":
            flux_v, _ = detrend_poly(time, phase, flux)
        else:
            flux_v = flux
        window = np.abs(phase) <= WINDOW_HOURS_DEFAULT / 24
        fit = fit_transit(phase[window], flux_v[window])
        bins = bin_phase(phase[window] * 24, flux_v[window])
        results[variant] = {
            "n_total_points": int(len(time)),
            "time_span_days": float(time.max() - time.min()),
            "fit": {
                k: v
                for k, v in fit.items()
                if k not in ("model_flux", "residuals", "in_transit_mask")
            },
            "binned": {
                "bin_minutes": BIN_MINUTES,
                "centers_hours": [float(c) for c in bins[0]],
                "mean_flux": [float(v) for v in bins[1]],
                "error_bars": [float(v) for v in bins[2]],
                "counts": [int(v) for v in bins[3]],
                "error_definition": (
                    "std/sqrt(n) per bin; underestimates true uncertainty under correlated noise"
                ),
            },
            "_plot": {"phase": phase[window], "flux": flux_v[window], "fit": fit, "bins": bins},
        }
        print(
            f"{name}/{variant}: n={fit['n_points']} rp={fit['rp']:.5f} "
            f"depth={fit['depth_ppm']:.1f} ppm offset={fit['t0_offset_minutes']:+.2f} min "
            f"RSS impr={fit['rss_improvement_pct']:.3f}%"
        )
    return results, time, flux, phase


def run_grid(name, spec, variant, base, grid_name, param_grid):
    """Run fit_transit over a parameter grid; store compact metrics only."""
    time, flux = load_dataset(spec)
    bjdref = BJDREF[spec["mission"]]
    entries = []
    for params in param_grid:
        period = base.get("period", PERIOD)
        t0_bjd = base.get("t0_bjd", TRANSIT_EPOCH_BJD)
        a_over_r = base.get("a_over_r", A_OVER_RSTAR)
        inc = base.get("inc_deg", INCLINATION_DEG)
        window_hours = base.get("window_hours", WINDOW_HOURS_DEFAULT)
        if grid_name == "ephemeris":
            period += params["dP"]
            t0_bjd += params["dT0"]
        elif grid_name == "window":
            window_hours = params["window_hours"]
        elif grid_name == "geometry":
            a_over_r = params["a_over_r"]
            inc = params["inc_deg"]
        phase = fold_phase(time, period, t0_bjd, bjdref)
        if variant == "detrended":
            flux_v, _ = detrend_poly(time, phase, flux)
        else:
            flux_v = flux
        window = np.abs(phase) <= window_hours / 24
        fit = fit_transit(phase[window], flux_v[window], a_over_r=a_over_r, inc_deg=inc)
        entries.append(
            {
                **params,
                "rp": fit["rp"],
                "depth_ppm": fit["depth_ppm"],
                "t0_offset_minutes": fit["t0_offset_minutes"],
                "rss_improvement_pct": fit["rss_improvement_pct"],
            }
        )
        print(
            f"  [{grid_name}] {params} -> depth={fit['depth_ppm']:.1f} ppm, "
            f"offset={fit['t0_offset_minutes']:+.2f} min, impr={fit['rss_improvement_pct']:.3f}%"
        )
    return entries


def plot_folded(name, variant, result, out_path):
    plot = result["_plot"]
    fit = plot["fit"]
    centers, means, errors, counts = plot["bins"]
    model_binned = bin_phase(plot["phase"] * 24, fit["model_flux"])[1]

    fig, (ax, ax_res) = plt.subplots(
        2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    ax.scatter(plot["phase"] * 24, plot["flux"], s=4, alpha=0.25, label="Folded points")
    ax.errorbar(
        centers,
        means,
        yerr=errors,
        fmt="o",
        ms=4,
        lw=1,
        label=f"Binned ({BIN_MINUTES:.0f} min, std/√n)",
    )
    ax.plot(centers, model_binned, "r-", lw=1.5, label="Transit model (binned)")
    ax.axvline(0, color="k", ls="--", lw=0.8, alpha=0.5)
    ax.set_ylabel("Normalized flux")
    ax.set_title(
        f"{name} / {variant}: rp={fit['rp']:.5f}, depth≈{fit['depth_ppm']:.0f} ppm, "
        f"RSS improvement {fit['rss_improvement_pct']:.2f}% (descriptive, not significance)"
    )
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(alpha=0.3)

    ax_res.axhline(0, color="r", lw=1)
    ax_res.errorbar(centers, means - model_binned, yerr=errors, fmt="o", ms=3, lw=1)
    ax_res.set_xlabel("Hours from predicted transit center")
    ax_res.set_ylabel("Residual")
    ax_res.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_raw_vs_detrended(name, time, flux, phase):
    flux_dt, _ = detrend_poly(time, phase, flux)
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    axes[0].plot(time, flux, ".", ms=2)
    axes[0].set_ylabel("Normalized flux")
    axes[0].set_title(
        f"{name}: raw (top) vs detrended (bottom, out-of-transit deg-2 poly per segment)"
    )
    axes[1].plot(time, flux_dt, ".", ms=2)
    axes[1].set_ylabel("Detrended flux")
    axes[1].set_xlabel("BKJD − 2454833 (days)")
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / f"phase3_{name}_raw_vs_detrended.png", dpi=140)
    plt.close(fig)


def plot_coverage(time_all, flux_all):
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(time_all, flux_all, ".", ms=1.5)
    ax.set_xlabel("BKJD − 2454833 (days)")
    ax.set_ylabel("Normalized flux")
    ax.set_title(f"Kepler Q0–Q17 long-cadence coverage: {len(time_all)} quality-masked points")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase3_kepler_all_coverage.png", dpi=140)
    plt.close(fig)


def plot_robustness(grid_results):
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    for ax, grid_name in zip(axes, ("ephemeris", "window", "geometry"), strict=True):
        for key, style in (
            ("kepler_q0_masked/detrended", "o-"),
            ("kepler_all_masked/detrended", "s-"),
        ):
            entries = grid_results[key][grid_name]
            depths = [e["depth_ppm"] for e in entries]
            ax.plot(range(len(depths)), depths, style, ms=4, label=key.split("/")[0])
            for idx, entry in enumerate(entries):
                ax.annotate(
                    f"{entry['depth_ppm']:.0f}", (idx, depths[idx]), fontsize=6, rotation=45
                )
        ax.set_title(f"{grid_name} grid")
        ax.set_ylabel("Fitted depth (ppm)")
        ax.set_xticks(range(len(entries)))
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)
    fig.suptitle("Robustness of fitted depth to analysis choices (labels = depth ppm)")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase3_robustness_summary.png", dpi=140)
    plt.close(fig)


def main():
    all_results = {}
    runtime = {}

    for name, spec in DATASETS.items():
        results, time, flux, phase = analyze_dataset(name, spec)
        all_results[name] = {
            k: {kk: vv for kk, vv in v.items() if kk != "_plot"} for k, v in results.items()
        }
        for variant, res in results.items():
            plot_folded(name, variant, res, FIGURES / f"phase3_{name}_{variant}.png")
        runtime[name] = {"time": time, "flux": flux, "phase": phase}

    for name in ("kepler_q0_masked", "kepler_all_masked"):
        rt = runtime[name]
        plot_raw_vs_detrended(name, rt["time"], rt["flux"], rt["phase"])
    plot_coverage(runtime["kepler_all_masked"]["time"], runtime["kepler_all_masked"]["flux"])

    # Robustness grids on the two primary configurations.
    grids = {
        "ephemeris": [
            {"dP": dP, "dT0": dT0}
            for dP in (-EPHEM_PERIOD_SCATTER, 0.0, EPHEM_PERIOD_SCATTER)
            for dT0 in (-EPHEM_T0_SIGMA, 0.0, EPHEM_T0_SIGMA)
        ],
        "window": [{"window_hours": w} for w in (3.0, 6.0, 12.0)],
        "geometry": [
            {"a_over_r": a, "inc_deg": i} for a in (3.2, 3.4, 3.6) for i in (83.5, 84.5, 85.5)
        ],
    }
    grid_results = {}
    for name in ("kepler_q0_masked", "kepler_all_masked"):
        spec = DATASETS[name]
        key = f"{name}/detrended"
        grid_results[key] = {}
        for grid_name, param_grid in grids.items():
            grid_results[key][grid_name] = run_grid(
                name, spec, "detrended", {}, grid_name, param_grid
            )
    plot_robustness(grid_results)

    payload = {
        "generated_by": "scripts/transit_analysis.py",
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "framing": (
            "Kepler-10 b is a known planet; this is re-detection/pipeline validation. "
            "RSS improvements are descriptive, not detection significances (Phase 4)."
        ),
        "ephemeris": {
            "period_days": PERIOD,
            "transit_epoch_bjd": TRANSIT_EPOCH_BJD,
            "period_scatter_tested_days": EPHEM_PERIOD_SCATTER,
            "t0_sigma_tested_days": EPHEM_T0_SIGMA,
        },
        "fixed_parameters": {
            "a_over_r": A_OVER_RSTAR,
            "inclination_deg": INCLINATION_DEG,
            "u1": U1,
            "u2": U2,
            "half_duration_days_assumption": HALF_DURATION_DAYS,
        },
        "detrending": (
            "Per segment (split at >1 day gaps): degree-2 polynomial on |phase| >= 3 h "
            "points only, subtracted. In-transit data never enters the fit."
        ),
        "datasets": all_results,
        "robustness_grids": grid_results,
    }
    out = RESULTS / "phase3_transit_analysis.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nResults JSON: {out}")
    print("Figures: phase3_*.png in reports/figures")


if __name__ == "__main__":
    main()
