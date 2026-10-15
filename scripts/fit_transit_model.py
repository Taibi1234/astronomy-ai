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
FIGURES.mkdir(parents=True, exist_ok=True)

PERIOD = 0.837491225
EPOCH_BJD = 2454964.575
BJDREF = {"kepler": 2454833.0, "tess": 2457000.0}

# Initial geometric assumptions for a diagnostic fit.
# These are held fixed, not claimed as newly measured parameters.
A_OVER_RSTAR = 3.4
INCLINATION_DEG = 84.5
U1, U2 = 0.30, 0.20
DURATION_WINDOW_HOURS = 6.0


def make_transit_model(times, rp, t0):
    params = batman.TransitParams()
    params.t0 = t0
    params.per = PERIOD
    params.rp = rp
    params.a = A_OVER_RSTAR
    params.inc = INCLINATION_DEG
    params.ecc = 0.0
    params.w = 90.0
    params.limb_dark = "quadratic"
    params.u = [U1, U2]

    model = batman.TransitModel(params, times)
    return model.light_curve(params)


def load_phase_window(mission, bjdref):
    path = DATA / f"{mission}_kepler_10.csv"
    df = pd.read_csv(path)

    time = df["time"].to_numpy(float)
    flux = df["normalized_flux"].to_numpy(float)

    valid = np.isfinite(time) & np.isfinite(flux)
    time, flux = time[valid], flux[valid]

    epoch_relative = EPOCH_BJD - bjdref
    phase = ((time - epoch_relative + PERIOD / 2) % PERIOD) - PERIOD / 2

    window = np.abs(phase) <= DURATION_WINDOW_HOURS / 24
    return phase[window], flux[window]


def fit_mission(mission, bjdref):
    x, y = load_phase_window(mission, bjdref)

    if len(x) < 20:
        print(f"{mission}: insufficient observations for fitting.")
        return

    # Fit a local linear baseline for both models.
    # The baseline slope is in normalized-flux units per day.
    x_centered = x - np.median(x)

    def null_residual(p):
        baseline, slope = p
        return baseline + slope * x_centered - y

    null_fit = least_squares(
        null_residual,
        x0=[np.median(y), 0.0],
    )
    rss_null = np.sum(null_fit.fun**2)

    # Parameters: radius ratio, timing offset (days), baseline, slope.
    def transit_residual(p):
        rp, t0, baseline, slope = p
        transit = make_transit_model(x, rp, t0)
        prediction = baseline * transit + slope * x_centered
        return prediction - y

    fit = least_squares(
        transit_residual,
        x0=[0.014, 0.0, np.median(y), 0.0],
        bounds=(
            [0.001, -0.03, 0.95, -0.05],
            [0.05, 0.03, 1.05, 0.05],
        ),
        max_nfev=500,
    )

    rp, t0, baseline, slope = fit.x
    transit = make_transit_model(x, rp, t0)
    prediction = baseline * transit + slope * x_centered
    rss_transit = np.sum((prediction - y) ** 2)

    # Fit improvement is descriptive; it is not a significance estimate.
    improvement = 100 * (rss_null - rss_transit) / rss_null

    print(f"\n===== {mission.upper()} =====")
    print(f"Points in +/-{DURATION_WINDOW_HOURS:.0f}h: {len(x)}")
    print(f"Radius ratio Rp/R*: {rp:.6f}")
    print(f"Model depth approximation: {rp**2 * 1e6:.1f} ppm")
    print(f"Timing offset from published epoch: {t0 * 24 * 60:+.2f} minutes")
    print(f"Local baseline: {baseline:.8f}")
    print(f"Null-model RSS: {rss_null:.8g}")
    print(f"Transit-model RSS: {rss_transit:.8g}")
    print(f"RSS improvement: {improvement:.3f}%")
    print("Fixed assumptions: a/R*=3.4, inclination=84.5 deg,")
    print("quadratic limb darkening u1=0.30, u2=0.20.")
    print("Do not interpret RSS improvement as detection significance.")

    order = np.argsort(x)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.scatter(x * 24, y, s=7, alpha=0.35, label="Observed flux")
    ax.plot(
        x[order] * 24,
        prediction[order],
        linewidth=2,
        label="Fitted transit + local baseline",
    )
    ax.axvline(0, color="red", linestyle="--", alpha=0.7, label="Published transit center")
    ax.set_xlabel("Hours from predicted transit center")
    ax.set_ylabel("Normalized flux")
    ax.set_title(f"{mission.upper()} physical transit-model diagnostic")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()

    output = FIGURES / f"{mission}_kepler_10_transit_fit.png"
    fig.savefig(output, dpi=160)
    plt.close(fig)
    print(f"Saved plot: {output}")


if __name__ == "__main__":
    for mission, bjdref in BJDREF.items():
        fit_mission(mission, bjdref)
