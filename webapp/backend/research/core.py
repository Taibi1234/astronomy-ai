"""Phase 10 research core: folding detector, experiments, benchmark.

Scientific design (documented in reports/phase10_injection_recovery_benchmark.md):

* Kepler-10 b's period is published, so the recovery task is a *period-known*
  search: locate the transit in phase and measure its depth. Transits are
  injected coherently at ``epoch + delta`` for every orbit in a contiguous chunk,
  with ``delta`` drawn uniformly from +-SEARCH_HALF_DAYS and hidden from the
  detector.
* The detector folds the chunk at the published period, scans a grid of phase
  offsets, and computes a matched-filter amplitude and S/N using the same batman
  geometry as the injection. It never receives the injected depth or offset.
* A single transit gives S/N ~1.3 (150 ppm, TESS) to ~2.6 (300 ppm, Kepler), so
  per-transit detection would be uninformative; folding N transits multiplies
  S/N by sqrt(N), which is what makes the recovery curve measurable.
* Independent units are contiguous chunks (each with several transits), never
  individual cadences.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import transit_injection as ti

SEED = 20261022
TOLERANCE_DAYS = 0.0377  # half of the ~1.81 h transit duration (a/R*=3.4, i=84.5 deg)
SEARCH_HALF_DAYS = 0.20
SEARCH_STEP_DAYS = 0.0025
TEMPLATE_HALF_WIDTH_DAYS = 0.06
OUT_OF_TRANSIT_DAYS = 0.06
MIN_CHUNK_POINTS = 40


def transit_duration_days() -> float:
    """T14 from the fixed geometry (used to justify the timing tolerance)."""
    a, inc = ti.A_OVER_RSTAR, math.radians(ti.INCLINATION_DEG)
    arg = math.sqrt(max(1.0 - (a * math.cos(inc)) ** 2, 1e-12)) / (a * math.sin(inc))
    return ti.PERIOD_DAYS / math.pi * math.asin(min(arg, 1.0))


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    mission: str
    start_index: int
    end_index: int
    n_points: int


def load_curve(mission: str) -> tuple[np.ndarray, np.ndarray]:
    path = (
        Path(__file__).resolve().parents[3]
        / "data"
        / "processed"
        / ("kepler_kepler_10.csv" if mission == "kepler" else "tess_kepler_10.csv")
    )
    frame_times, frame_flux, _ = ti.load_light_curve(path, mission)
    return np.array(frame_times, dtype=float), np.array(frame_flux, dtype=float)


def make_chunks(times: np.ndarray, mission: str, n_chunks: int) -> list[Chunk]:
    """Split the light curve into contiguous, non-overlapping chunks."""
    n = len(times)
    if n_chunks < 1:
        raise ValueError("n_chunks must be >= 1")
    edges = np.linspace(0, n, n_chunks + 1).round().astype(int)
    chunks = []
    for i in range(n_chunks):
        lo, hi = int(edges[i]), int(edges[i + 1])
        chunks.append(Chunk(f"{mission}-c{i}", mission, lo, hi, hi - lo))
    return chunks


def phase_offsets(times: np.ndarray, mission: str, delta_days: float) -> np.ndarray:
    """Signed phase offset from the transit centre, in [-P/2, P/2)."""
    reference = ti.BJD_REFERENCE[mission]
    epoch = ti.TRANSIT_EPOCH_BJD_TDB - reference
    raw = times - (epoch + delta_days)
    return ((raw + ti.PERIOD_DAYS / 2) % ti.PERIOD_DAYS) - ti.PERIOD_DAYS / 2


_PROFILE_CACHE: dict[str, tuple[np.ndarray, np.ndarray]] = {}


def template_profile() -> tuple[np.ndarray, np.ndarray]:
    """Peak-normalised batman transit shape on phase offset (cached)."""
    if "p" not in _PROFILE_CACHE:
        grid = np.linspace(-TEMPLATE_HALF_WIDTH_DAYS, TEMPLATE_HALF_WIDTH_DAYS, 2001)
        model = ti.transit_model(grid, 150)
        peak = 1.0 - float(np.min(model))
        profile = (1.0 - model) / peak
        _PROFILE_CACHE["p"] = (grid, profile)
    return _PROFILE_CACHE["p"]


def detect(times: np.ndarray, flux: np.ndarray, mission: str) -> dict:
    """Fold, scan phase offsets, and return the best matched-filter result.

    The detector is given only times and flux. The injected centre and depth are
    never passed in; the scan starts from the published ephemeris and searches
    +/-SEARCH_HALF_DAYS.
    """
    grid, profile = template_profile()
    deltas = np.arange(-SEARCH_HALF_DAYS, SEARCH_HALF_DAYS + 1e-12, SEARCH_STEP_DAYS)

    best = {"snr": -np.inf, "delta": 0.0, "depth_ppm": 0.0, "sigma_ppm": float("nan")}

    for delta in deltas:
        dt = phase_offsets(times, mission, float(delta))
        w = np.interp(dt, grid, profile, left=0.0, right=0.0)
        out = np.abs(dt) > OUT_OF_TRANSIT_DAYS
        if out.sum() < 10:
            continue

        baseline = float(np.median(flux[out]))
        y = flux - baseline
        denom = float(np.sum(w * w))
        if denom <= 1e-12:
            continue

        amplitude = float(np.sum(w * y) / denom)
        sigma = 1.4826 * float(np.median(np.abs(y[out] - np.median(y[out]))))
        if not math.isfinite(sigma) or sigma <= 0:
            continue

        # A transit is a negative excursion: report the dip significance as a
        # positive S/N and the depth as a positive ppm value.
        snr = -amplitude * math.sqrt(denom) / sigma
        if snr > best["snr"]:
            best = {
                "snr": snr,
                "delta": float(delta),
                "depth_ppm": -amplitude * 1e6,
                "sigma_ppm": sigma * 1e6,
            }

    return best


def remove_published_transit(
    times: np.ndarray, flux: np.ndarray, mission: str
) -> tuple[np.ndarray, float]:
    """Subtract the published Kepler-10 b transit from a chunk.

    The real planet transits are present in these light curves. If left in, the
    detector can lock onto the real signal at delta=0 instead of the injection, and
    zero-depth controls would not be true nulls. The amplitude is estimated at the
    published ephemeris (no injection knowledge) and subtracted with the same batman
    shape used everywhere else. The fitted amplitude is returned in ppm for logging.
    """
    grid, profile = template_profile()
    dt = phase_offsets(times, mission, 0.0)
    w = np.interp(dt, grid, profile, left=0.0, right=0.0)
    denom = float(np.sum(w * w))
    if denom <= 1e-12:
        return flux.copy(), 0.0
    baseline = float(np.median(flux))
    amplitude = float(np.sum(w * (flux - baseline)) / denom)
    return flux - amplitude * w, -amplitude * 1e6


def wilson_interval(successes: int, total: int, z: float = 1.96) -> dict:
    """Wilson score interval for a binomial proportion."""
    if total <= 0:
        return {"low": None, "high": None, "n": 0, "k": successes}
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(max(p * (1 - p) / total + z * z / (4 * total * total), 0.0)) / denom
    return {
        "low": max(0.0, centre - half),
        "high": min(1.0, centre + half),
        "n": total,
        "k": successes,
    }


def apply_noise_condition(flux: np.ndarray, condition: str) -> np.ndarray:
    """Observed noise, or the same structure with residuals amplified (x2)."""
    if condition == "observed":
        return flux.copy()
    if condition == "amplified_x2":
        baseline = float(np.median(flux))
        return baseline + (flux - baseline) * 2.0
    raise ValueError(f"unknown noise condition: {condition}")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
