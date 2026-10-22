"""Physical transit injection shared by the transit-injection API.

Why this module exists instead of importing the research scripts
----------------------------------------------------------------
The injection arithmetic lives inline in ``scripts/phase5_build_dataset.py`` and
its batman configuration in ``scripts/transit_analysis.py``. Importing either
module has side effects: ``transit_analysis`` switches matplotlib to the Agg
backend and creates report directories at import time, and the Phase 5 script has
no ``__main__`` guard at all - importing it re-runs the whole dataset build and
overwrites ``reports/phase5_dataset.json``. Neither is acceptable inside a web
request handler, so the two formulas are mirrored here, each constant annotated
with the research file and line it comes from.

Numerical equivalence was verified rather than assumed (see
``tests/test_transit_injection.py``): for rp = sqrt(75|150|225|300 ppm) the model
matches ``transit_analysis.batman_curve`` with a maximum absolute difference of
0.0e+00 across batman 2.5.3 / numpy 2.4.6 / CPython 3.11 (research venv) and
batman 2.5.2 / numpy 2.5.4 / CPython 3.14 (backend venv).

The injection is NEVER applied to the source CSV: callers pass an array, and a
new array is returned.
"""

from __future__ import annotations

import math
from functools import lru_cache

import batman
import numpy as np
import pandas as pd

# --- Ephemeris and fixed transit geometry (scripts/transit_analysis.py:58-68) --
PERIOD_DAYS = 0.837491225
TRANSIT_EPOCH_BJD_TDB = 2454964.575
BJD_REFERENCE = {"kepler": 2454833.0, "tess": 2457000.0}
A_OVER_RSTAR = 3.4
INCLINATION_DEG = 84.5
U1, U2 = 0.30, 0.20

# --- Explorer window ----------------------------------------------------------
# +-0.1 d = +-2.4 h around the transit centre: covers the ~1.8 h Kepler-10 b
# transit plus baseline on both sides.
HALF_WINDOW_DAYS = 0.1
MIN_CENTRE_POINTS = 3

SUPPORTED_DEPTHS_PPM = (0, 75, 150, 225, 300)


def transit_model(dt_days: np.ndarray, depth_ppm: float) -> np.ndarray:
    """batman model centred on the transit, in relative flux.

    Mirrors ``scripts/transit_analysis.py`` ``batman_curve(phase_days, rp, 0, ...)``:
    period fixed, eccentricity 0, w = 90 deg, quadratic limb darkening.

    ``depth_ppm`` parameterises ``rp = sqrt(depth * 1e-6)`` exactly as the Phase 5
    builder does, i.e. it is the geometric area ratio, not the limb-darkened
    central flux decrement (reported separately as the measured depth).
    """
    dt_days = np.asarray(dt_days, dtype=float)

    if depth_ppm == 0:
        # No transit: returning exactly ones guarantees zero change in the caller.
        return np.ones_like(dt_days)

    rp = math.sqrt(depth_ppm * 1e-6)

    params = batman.TransitParams()
    params.t0 = 0.0
    params.per = PERIOD_DAYS
    params.rp = rp
    params.a = A_OVER_RSTAR
    params.inc = INCLINATION_DEG
    params.ecc = 0.0
    params.w = 90.0
    params.limb_dark = "quadratic"
    params.u = [U1, U2]

    model = batman.TransitModel(params, dt_days)
    return np.asarray(model.light_curve(params), dtype=float)


def inject_transit(flux, dt_days, depth_ppm: float) -> np.ndarray:
    """Return a new flux array with a synthetic transit added.

    Formula copied from ``scripts/phase5_build_dataset.py``::

        synthetic = flux + median(flux) * (batman_model - 1.0)

    ``flux`` is never modified; depth 0 returns an exact copy.
    """
    flux = np.asarray(flux, dtype=float)

    if depth_ppm == 0 or flux.size == 0:
        return flux.copy()

    model = transit_model(dt_days, depth_ppm)
    median_flux = float(np.median(flux))
    return flux + median_flux * (model - 1.0)


def measured_depth_ppm(original: np.ndarray, injected: np.ndarray) -> float:
    """Peak flux decrement caused by the injection, in ppm, from the arrays.

    ``max(original - injected) * 1e6``. Because the injection only ever removes
    flux, this equals ``max|injected - original| * 1e6``; the API reports both and
    says so rather than implying two independent measurements.
    """
    original = np.asarray(original, dtype=float)
    injected = np.asarray(injected, dtype=float)
    if original.size == 0:
        return 0.0
    return float(np.max(original - injected) * 1e6)


def max_abs_change_ppm(original: np.ndarray, injected: np.ndarray) -> float:
    original = np.asarray(original, dtype=float)
    injected = np.asarray(injected, dtype=float)
    if original.size == 0:
        return 0.0
    return float(np.max(np.abs(injected - original)) * 1e6)


def bjd_reference(mission: str) -> float:
    return BJD_REFERENCE[mission]


def transit_centres(times: np.ndarray, mission: str) -> list[dict]:
    """Ephemeris-predicted transit centres that the observations actually cover.

    A centre is offered only when at least ``MIN_CENTRE_POINTS`` finite
    observations fall within ``HALF_WINDOW_DAYS`` of it, so the explorer cannot be
    pointed at an empty window.
    """
    times = np.asarray(times, dtype=float)
    if times.size == 0:
        return []

    reference = bjd_reference(mission)
    epoch_in_dataset_days = TRANSIT_EPOCH_BJD_TDB - reference

    first = int(math.ceil((times.min() - epoch_in_dataset_days) / PERIOD_DAYS))
    last = int(math.floor((times.max() - epoch_in_dataset_days) / PERIOD_DAYS))

    centres = []
    for k in range(first, last + 1):
        centre = epoch_in_dataset_days + k * PERIOD_DAYS
        count = int(np.count_nonzero(np.abs(times - centre) <= HALF_WINDOW_DAYS))
        if count >= MIN_CENTRE_POINTS:
            centres.append(
                {
                    "index": k,
                    "time_dataset_days": float(centre),
                    "bjd_tdb": float(centre + reference),
                    "n_points": count,
                }
            )
    return centres


@lru_cache(maxsize=4)
def _load_cached(path_str: str, mtime_ns: int):
    """Read a two-column light curve once per file version. Arrays are read-only."""

    frame = pd.read_csv(path_str, usecols=["time", "normalized_flux"])
    times = pd.to_numeric(frame["time"], errors="coerce")
    flux = pd.to_numeric(frame["normalized_flux"], errors="coerce")

    finite = np.isfinite(times) & np.isfinite(flux)
    excluded = int((~finite).sum())

    t = np.ascontiguousarray(times[finite].to_numpy(dtype=float))
    f = np.ascontiguousarray(flux[finite].to_numpy(dtype=float))

    order = np.argsort(t, kind="stable")
    t, f = t[order], f[order]

    t.flags.writeable = False
    f.flags.writeable = False
    return t, f, excluded


def load_light_curve(csv_path, mission: str):
    """Cached, validated, time-sorted light curve for one mission.

    Returns ``(times, flux, excluded_non_finite)``. Missing or infinite values are
    dropped exactly as the existing ``/api/lightcurve`` endpoint does; these
    processed CSVs carry no quality column, so the project's quality-bit mask
    cannot be applied here and is not claimed.
    """
    path = csv_path
    stat = path.stat()
    return _load_cached(str(path), stat.st_mtime_ns)
