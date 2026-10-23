"""B2a extraction gate: the shared feature builder must be bit-identical to its predecessors.

The reference implementation is a verbatim copy of the pre-B2a body that lived in both
``phase11.time_domain_features`` and ``experiment.time_domain_features``. Synthetic arrays
only: no data file is opened and no real light curve is read.
"""

from __future__ import annotations

import inspect
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import (  # noqa: E402, I001
    core,
    experiment,
    features,
    phase11,
    phase11_b2a as b2a,
)


def _pre_extraction_reference(times: np.ndarray, flux: np.ndarray) -> dict:
    """Verbatim pre-B2a body (design §5.1); the bit-identity target."""
    baseline = float(np.median(flux))
    resid = flux - baseline
    gaps = np.diff(times) > 0.05
    return {
        "min_depth_ppm": float((baseline - float(np.min(flux))) * 1e6),
        "std_ppm": float(np.std(flux) * 1e6),
        "mad_ppm": float(np.median(np.abs(resid)) * 1e6),
        "gap_fraction": float(np.sum(gaps) / max(1, len(times) - 1)),
        "mean_flux": float(np.mean(flux)),
        "n_points": int(len(times)),
    }


def _bits(value: object) -> bytes:
    if isinstance(value, float):
        return b"f" + struct.pack(">d", value)
    if isinstance(value, int) and not isinstance(value, bool):
        return b"i" + struct.pack(">q", value)
    return b"o" + repr(value).encode()


def assert_bit_identical(left: dict, right: dict) -> None:
    """Same keys, same Python types, same IEEE-754 bytes — no tolerance."""
    assert set(left) == set(right)
    for key, value in left.items():
        assert type(value) is type(right[key]), f"{key}: type drift"
        assert _bits(value) == _bits(right[key]), f"{key}: bit drift"


def _standard() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(11)
    times = np.linspace(0.0, 5.0, 245)
    return times, 1.0 + rng.normal(0.0, 1.2e-4, times.size)


def _with_gaps() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(12)
    times = np.linspace(0.0, 5.0, 200)
    times = np.delete(times, np.s_[40:60])
    return times, 1.0 + rng.normal(0.0, 8.0e-5, times.size)


def _coarse_sampling() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(13)
    times = np.array([0.0, 0.3, 1.4, 2.2])
    return times, 1.0 + rng.normal(0.0, 3.0e-4, times.size)


def _two_points() -> tuple[np.ndarray, np.ndarray]:
    return np.array([0.0, 2.0]), np.array([1.0002, 0.9998])


def _single_point() -> tuple[np.ndarray, np.ndarray]:
    return np.array([3.5]), np.array([1.0001])


def _constant_flux() -> tuple[np.ndarray, np.ndarray]:
    return np.linspace(0.0, 5.0, 120), np.ones(120)


def _integer_flux() -> tuple[np.ndarray, np.ndarray]:
    times = np.arange(60, dtype=float) * 0.02
    return times, np.array([100 + (index % 3) for index in range(60)], dtype=float)


def _extreme_scale() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(14)
    times = np.linspace(0.0, 1.0, 90)
    return times, 1e-9 + rng.normal(0.0, 1e-12, times.size)


def _with_nan() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(15)
    times = np.linspace(0.0, 5.0, 80)
    flux = 1.0 + rng.normal(0.0, 1e-4, times.size)
    flux[7] = np.nan
    times[9] = np.nan
    return times, flux


CASES = {
    "standard": _standard,
    "with_gaps": _with_gaps,
    "coarse_sampling": _coarse_sampling,
    "two_points": _two_points,
    "single_point": _single_point,
    "constant_flux": _constant_flux,
    "integer_flux": _integer_flux,
    "extreme_scale": _extreme_scale,
    "with_nan": _with_nan,
}


def test_one_implementation_is_shared():
    assert phase11.time_domain_features is features.time_domain_features
    assert experiment.time_domain_features is features.time_domain_features


@pytest.mark.parametrize("case", sorted(CASES))
def test_shared_builder_is_bit_identical_to_the_pre_extraction_body(case):
    times, flux = CASES[case]()

    reference = _pre_extraction_reference(times, flux)
    for builder in (
        features.time_domain_features,
        phase11.time_domain_features,
        experiment.time_domain_features,
    ):
        assert_bit_identical(builder(times, flux), reference)


@pytest.mark.parametrize("case", sorted(CASES))
def test_field_order_and_names_are_preserved(case):
    times, flux = CASES[case]()

    reference = _pre_extraction_reference(times, flux)
    observed = features.time_domain_features(times, flux)

    assert list(observed) == list(reference)
    assert tuple(observed) == features.FEATURE_NAMES


def test_detector_result_is_bit_identical_to_a_direct_core_call():
    rng = np.random.default_rng(20261022)
    times, flux = b2a.synthetic_window(
        window_days=5.0,
        cadence_days=b2a.CADENCE_DAYS,
        noise_condition="observed",
        requested_depth_ppm=300.0,
        rng=rng,
        mission="kepler",
    )

    wired = b2a.detect_window(times, flux, "kepler")
    direct = core.detect(times, flux, "kepler")

    assert set(wired) == set(direct)
    for key in direct:
        assert type(wired[key]) is type(direct[key]), key
        assert _bits(wired[key]) == _bits(direct[key]), key


def test_neutral_module_holds_no_file_or_detector_access():
    source = inspect.getsource(features)

    for forbidden in ("read_csv", "open(", "Path(", "to_csv", "json.load"):
        assert forbidden not in source, forbidden
    imported = {name for name in features.__dict__ if not name.startswith("_")}
    assert imported == {"annotations", "np", "FEATURE_NAMES", "time_domain_features"}
