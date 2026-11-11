"""Tests for the transit-injection endpoint and shared injection module."""

import hashlib
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app as backend  # noqa: E402
import transit_injection as ti  # noqa: E402

client = TestClient(backend.app)
ENDPOINT = "/api/transit-injection"

# Minimum of the batman model at rp = sqrt(150e-6), computed with the research
# environment (scripts/transit_analysis.py, batman 2.5.3, py3.11). The backend
# reproduces this to machine precision; the value is a regression guard against
# silently changing the transit physics.
RESEARCH_MIN_150PPM = 0.999829865082


def fetch(**params):
    return client.get(ENDPOINT, params=params)


def response(**params):
    result = fetch(**params)
    assert result.status_code == 200, result.text
    return result.json()


# --- zero depth ---------------------------------------------------------------


def test_zero_depth_returns_original_flux_unchanged():
    data = response(mission="tess", depth_ppm=0)
    assert data["points"], "expected at least one plotted observation"
    assert all(point["original"] == point["injected"] for point in data["points"])
    assert all(point["difference_ppm"] == 0.0 for point in data["points"])
    assert data["diagnostics"]["measured_depth_ppm"] == 0.0
    assert data["diagnostics"]["max_abs_change_ppm"] == 0.0


def test_zero_depth_module_returns_exact_copy():
    flux = np.array([1.0, 0.999, 1.001, 0.998])
    out = ti.inject_transit(flux, np.linspace(-0.01, 0.01, 4), 0)
    assert np.array_equal(out, flux)
    assert out is not flux, "must be a copy, never the caller's array"


# --- non-zero injection -------------------------------------------------------


def test_nonzero_injection_changes_only_in_transit_samples():
    dt = np.linspace(-0.2, 0.2, 401)  # days
    flux = np.ones_like(dt)
    injected = ti.inject_transit(flux, dt, 300)

    changed = np.abs(injected - flux) > 0
    assert changed.any(), "a 300 ppm injection must change some samples"

    # Well outside the transit the model is exactly 1, so nothing changes.
    far = np.abs(dt) > 0.06
    assert not changed[far].any(), "baseline samples must be untouched"

    # And the deepest change is close to the centre.
    deepest = dt[np.argmax(flux - injected)]
    assert abs(deepest) < 0.05


def test_injection_never_increases_flux():
    dt = np.linspace(-0.1, 0.1, 501)
    flux = 1.0 + 1e-4 * np.sin(dt * 50)
    injected = ti.inject_transit(flux, dt, 225)
    assert np.all(injected <= flux + 1e-15)


def test_model_matches_research_batman_configuration():
    dt = np.linspace(-0.1, 0.1, 2001)
    model = ti.transit_model(dt, 150)
    assert model.min() == pytest.approx(RESEARCH_MIN_150PPM, abs=1e-12)


def test_limb_darkening_makes_measured_depth_exceed_requested():
    """Requested depth is rp^2; the limb-darkened decrement is larger (~13%)."""
    dt = np.linspace(-0.1, 0.1, 4001)
    flux = np.ones_like(dt)
    measured = ti.measured_depth_ppm(flux, ti.inject_transit(flux, dt, 150))
    assert 160 < measured < 180
    assert measured == pytest.approx(170.0, abs=2.0)


# --- diagnostics --------------------------------------------------------------


def test_measured_depth_is_computed_from_returned_arrays():
    data = response(mission="tess", depth_ppm=300)
    original = np.array([p["original"] for p in data["points"]])
    injected = np.array([p["injected"] for p in data["points"]])

    expected = float(np.max(original - injected) * 1e6)
    assert data["diagnostics"]["measured_depth_ppm"] == pytest.approx(expected, abs=1e-9)
    assert data["diagnostics"]["max_abs_change_ppm"] == pytest.approx(expected, abs=1e-9)


def test_difference_series_matches_point_arrays():
    data = response(mission="tess", depth_ppm=150)
    for point in data["points"]:
        assert point["difference_ppm"] == pytest.approx(
            (point["injected"] - point["original"]) * 1e6, abs=1e-9
        )


def test_reported_point_count_matches_payload():
    data = response(mission="kepler", depth_ppm=150)
    assert data["diagnostics"]["n_points"] == len(data["points"])
    assert data["dataset"]["window_observations"] == len(data["points"])


# --- validation ---------------------------------------------------------------


@pytest.mark.parametrize("depth", [1, 100, 151, -75, 1000])
def test_unsupported_depths_are_rejected(depth):
    assert fetch(mission="kepler", depth_ppm=depth).status_code == 422


def test_unknown_mission_is_rejected():
    assert fetch(mission="mars", depth_ppm=150).status_code == 404


def test_unknown_center_index_is_rejected():
    assert fetch(mission="kepler", depth_ppm=150, center_index=10**6).status_code == 422


def test_available_center_is_accepted_and_echoed():
    first = response(mission="kepler", depth_ppm=150)
    chosen = first["available_centers"][-1]["index"]
    second = response(mission="kepler", depth_ppm=150, center_index=chosen)
    assert second["center"]["index"] == chosen


# --- time handling ------------------------------------------------------------


def test_centre_times_follow_the_published_ephemeris():
    data = response(mission="kepler", depth_ppm=150)
    reference = ti.BJD_REFERENCE["kepler"]

    for centre in data["available_centers"]:
        expected_dataset_time = (ti.TRANSIT_EPOCH_BJD_TDB - reference) + (
            centre["index"] * ti.PERIOD_DAYS
        )
        assert centre["time_dataset_days"] == pytest.approx(expected_dataset_time, abs=1e-9)
        assert centre["bjd_tdb"] == pytest.approx(expected_dataset_time + reference, abs=1e-9)


def test_mission_time_systems_differ_by_their_reference_epoch():
    kepler = response(mission="kepler", depth_ppm=0)
    tess = response(mission="tess", depth_ppm=0)

    assert kepler["time"]["system"] == "BKJD"
    assert kepler["time"]["bjd_offset"] == 2454833.0
    assert tess["time"]["system"] == "TJD"
    assert tess["time"]["bjd_offset"] == 2457000.0

    point = kepler["points"][0]
    assert point["bjd_tdb"] == pytest.approx(point["time"] + 2454833.0, abs=1e-9)


def test_points_are_chronological_and_window_is_bounded():
    data = response(mission="tess", depth_ppm=150)
    times = [point["time"] for point in data["points"]]
    assert times == sorted(times)
    assert len(times) < data["dataset"]["total_observations"]
    assert abs(max(times) - min(times)) <= 2 * ti.HALF_WINDOW_DAYS + 0.01


# --- missing / malformed data -------------------------------------------------


def test_non_finite_rows_are_excluded(tmp_path):
    frame = pd.DataFrame(
        {
            "time": [100.0, 100.5, 101.0, 101.5, np.nan, 102.0],
            "normalized_flux": [1.0, np.nan, 1.0, 0.999, 1.0, 1.0],
        }
    )
    path = tmp_path / "dirty.csv"
    frame.to_csv(path, index=False)

    times, flux, excluded = ti.load_light_curve(path, "kepler")
    assert excluded == 2
    assert times.size == 4
    assert np.all(np.isfinite(times)) and np.all(np.isfinite(flux))


def test_injection_handles_empty_window():
    empty = np.array([], dtype=float)
    assert ti.inject_transit(empty, empty, 150).size == 0
    assert ti.measured_depth_ppm(empty, empty) == 0.0


# --- source integrity ---------------------------------------------------------


def test_source_csv_is_not_modified():
    path = Path(backend.PROJECT_ROOT) / backend.DATASETS["tess"]
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    stat_before = path.stat().st_mtime_ns

    response(mission="tess", depth_ppm=300)
    response(mission="tess", depth_ppm=0)

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert path.stat().st_mtime_ns == stat_before


def test_dataset_checksum_is_reported():
    data = response(mission="kepler", depth_ppm=0)
    path = Path(backend.PROJECT_ROOT) / backend.DATASETS["kepler"]
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert data["dataset"]["sha256"] == expected


# --- API contract (mirrors the TypeScript types) ------------------------------


def test_response_contract_for_frontend():
    data = response(mission="kepler", depth_ppm=150)

    assert set(data) == {
        "mission",
        "target",
        "dataset",
        "time",
        "flux",
        "ephemeris",
        "model",
        "center",
        "available_centers",
        "points",
        "diagnostics",
        "scientific_notice",
    }

    assert isinstance(data["mission"], str)
    assert data["target"] == "Kepler-10 b"
    assert isinstance(data["scientific_notice"], str) and data["scientific_notice"]

    for key in ("path", "sha256", "total_observations", "window_observations"):
        assert key in data["dataset"]
    for key in ("system", "definition", "axis_label", "bjd_offset"):
        assert key in data["time"]
    for key in ("axis_label", "unit"):
        assert key in data["flux"]
    for key in ("period_days", "t0_bjd_tdb"):
        assert key in data["ephemeris"]
    for key in ("a_over_rstar", "inclination_deg", "u1", "u2", "injection_formula"):
        assert key in data["model"]

    assert set(data["center"]) == {"index", "time_dataset_days", "bjd_tdb", "n_points"}
    assert isinstance(data["available_centers"], list)

    point = data["points"][0]
    assert set(point) == {"time", "bjd_tdb", "original", "injected", "difference_ppm"}
    for value in point.values():
        assert isinstance(value, float) and math.isfinite(value)

    diagnostics = data["diagnostics"]
    for key in (
        "n_points",
        "requested_depth_ppm",
        "measured_depth_ppm",
        "max_abs_change_ppm",
        "measured_depth_definition",
        "limitations",
    ):
        assert key in diagnostics
    assert isinstance(diagnostics["limitations"], list) and diagnostics["limitations"]
