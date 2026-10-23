"""B2a builder tests: synthetic fit-split rows for B1, with every gate asserted.

Synthetic fixtures only. The authenticated B0 view is read from the frozen triple (skipped
when absent); no model is fitted, no trial is generated, no sealed data is read and no
campaign runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import transit_injection as ti

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import (  # noqa: E402, I001
    core,
    generalization as gen,
    phase11,
    phase11_b2a as b2a,
    phase11_v2 as v2,
    safeguards,
)

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"
FROZEN_NAMES = (
    "protocol_v2_3.json",
    "protocol_v2_3.sha256",
    "protocol.json",
    "protocol.sha256",
    "experiment_config.json",
)
SPLIT_MAP = {"Q00": "train", "Q04": "val"}


@pytest.fixture(scope="module")
def effective() -> dict:
    missing = [name for name in FROZEN_NAMES if not (MANIFEST_DIR / name).is_file()]
    if missing:
        pytest.skip(f"frozen triple unavailable: {missing}")
    resolved, _ = v2.resolve_effective_protocol(MANIFEST_DIR)
    return resolved


def _build(effective: dict, **overrides) -> object:
    arguments = {
        "effective": effective,
        "split_map": SPLIT_MAP,
        "seed": 20261022,
    }
    arguments.update(overrides)
    return b2a.build_fit_split_frame(**arguments)


# --- happy path --------------------------------------------------------------


def test_builds_fit_split_rows(effective):
    frame = _build(effective)

    assert set(frame["split"].unique()) == {"train", "val"}
    assert set(frame["role"].unique()) == {b2a.ROLE_NULL, b2a.ROLE_INJECTION}
    assert set(frame["source"].unique()) == {b2a.SOURCE}
    assert set(frame["noise_condition"].unique()) <= set(effective["injection"]["noise_conditions"])
    for column in b2a.METADATA_COLUMNS:
        assert column in frame.columns, column
    model_id = effective["features"]["primary_model"]
    for column in phase11.feature_columns(effective, model_id):
        assert column in frame.columns, column
    assert np.isfinite(frame[["snr", "depth_est_ppm", "sigma_ppm"]].to_numpy(dtype=float)).all()


def test_labels_and_null_windows_follow_the_contract(effective):
    frame = _build(effective)

    assert bool((frame["injected"] == (frame["requested_depth_ppm"] > 0)).all())
    nulls = frame[frame["role"] == b2a.ROLE_NULL]
    assert not nulls.empty
    assert bool((nulls["requested_depth_ppm"] == 0.0).all())
    assert not bool(nulls["injected"].any())
    for split in b2a.FIT_SPLITS:
        split_nulls = nulls[nulls["split"] == split]
        assert not split_nulls.empty, split


def test_frame_is_consumable_by_the_fit_and_calibration_contract(effective):
    frame = _build(effective)

    for column in ("split", "role", "noise_condition"):
        assert column in frame.columns, column
    for column in ("injected", *phase11.feature_columns(effective, "L2_snr_only")):
        assert column in frame.columns, column
    assert "test" not in set(frame["split"].unique())


# --- split and label guards --------------------------------------------------


def test_test_split_is_refused_before_construction(effective, monkeypatch):
    calls = []

    def spy(**kwargs):
        calls.append(kwargs)
        raise AssertionError("synthetic_window must not run for a refused split map")

    monkeypatch.setattr(b2a, "synthetic_window", spy)
    with pytest.raises(phase11.GateError, match="test-split input is refused"):
        _build(effective, split_map={"Q00": "train", "Q02": "test"})
    assert calls == []


def test_assert_fit_splits_turns_red_on_an_injected_test_row(effective):
    frame = _build(effective)
    phase11.assert_fit_splits(frame, effective)

    contaminated = frame.copy()
    contaminated.loc[0, "split"] = "test"
    with pytest.raises(phase11.GateError, match="non-fitting splits"):
        phase11.assert_fit_splits(contaminated, effective)


def test_label_invariant_mutation_is_caught(effective):
    frame = _build(effective)

    broken = frame.copy()
    broken.loc[0, "injected"] = not bool(broken.loc[0, "injected"])
    with pytest.raises(phase11.GateError, match="label invariant"):
        b2a._assert_label_invariant(broken)


def test_missing_null_windows_are_caught(effective):
    frame = _build(effective)

    without_nulls = frame[frame["role"] != b2a.ROLE_NULL]
    with pytest.raises(phase11.GateError, match="no null windows"):
        b2a._assert_null_windows(without_nulls)


# --- determinism -------------------------------------------------------------


def test_fixed_seed_is_reproducible(effective):
    first = _build(effective)
    second = _build(effective)

    assert first.to_csv(index=False) == second.to_csv(index=False)

    other = _build(effective, seed=20261023)
    assert other.to_csv(index=False) != first.to_csv(index=False)


# --- leakage prevention ------------------------------------------------------


def test_detector_never_receives_ground_truth(effective, monkeypatch):
    seen = []
    real = core.detect

    def spy(*args, **kwargs):
        seen.append((args, tuple(kwargs)))
        return real(*args, **kwargs)

    monkeypatch.setattr(core, "detect", spy)
    frame = _build(effective)

    assert len(seen) == len(frame)
    for args, kwargs in seen:
        assert kwargs == ()
        assert len(args) == 3
        times, flux, mission = args
        assert isinstance(times, np.ndarray)
        assert isinstance(flux, np.ndarray)
        assert times.size == flux.size
        assert mission in ti.BJD_REFERENCE


def test_feature_builder_receives_only_times_and_flux(effective, monkeypatch):
    calls = []
    real = b2a.time_domain_features

    def spy(*args, **kwargs):
        calls.append((len(args), tuple(kwargs)))
        return real(*args, **kwargs)

    monkeypatch.setattr(b2a, "time_domain_features", spy)
    frame = _build(effective)

    assert len(calls) == len(frame)
    assert all(argument_count == 2 and not kwargs for argument_count, kwargs in calls)


# --- fail-closed input validation -------------------------------------------


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"split_map": None}, "non-empty mapping"),
        ({"split_map": {}}, "non-empty mapping"),
        ({"split_map": [("Q00", "train")]}, "non-empty mapping"),
        ({"split_map": {"Q00": "holdout"}}, "unsupported split"),
        ({"split_map": {"Q00": 1}}, "not a string"),
        ({"split_map": {"": "train"}}, "non-empty quarter identifiers"),
        ({"split_map": {"Q00": "train"}}, "missing \\['val'\\]"),
        ({"seed": True}, "seed must be an integer"),
        ({"seed": 1.5}, "seed must be an integer"),
        ({"windows_per_quarter": 0}, "positive integer"),
        ({"windows_per_quarter": "2"}, "positive integer"),
        ({"depths_ppm": ()}, "at least one positive depth"),
        ({"depths_ppm": (0.0,)}, "finite and positive"),
        ({"depths_ppm": (-5.0,)}, "finite and positive"),
        ({"depths_ppm": (float("nan"),)}, "finite and positive"),
        ({"window_days": 0.0}, "finite and positive"),
        ({"cadence_days": 0.25}, "fewer than 40 cadences"),
        ({"mission": "jwst"}, "unknown mission"),
        ({"noise_ppm": 0.0}, "noise_ppm"),
        ({"geometry": "five"}, "must be a phase11_b2a.Geometry"),
        ({"model_id": "L9_no_such_model"}, "unknown model id"),
    ],
)
def test_invalid_inputs_fail_closed(effective, overrides, message):
    geometry_overrides = {
        key: overrides.pop(key)
        for key in ("window_days", "cadence_days", "mission", "noise_ppm")
        if key in overrides
    }
    if geometry_overrides:
        overrides["geometry"] = b2a.Geometry(**geometry_overrides)
    with pytest.raises(phase11.GateError, match=message):
        _build(effective, **overrides)


def _drop_features(protocol: dict) -> None:
    protocol.pop("features")


def _drop_primary_model(protocol: dict) -> None:
    protocol["features"].pop("primary_model")


def _add_unbuildable_detector_output(protocol: dict) -> None:
    protocol["features"]["detector_outputs"].append("delta_true_days")


def _add_unknown_noise(protocol: dict) -> None:
    protocol["injection"]["noise_conditions"] = ["unknown_noise"]


def _drop_noise_conditions(protocol: dict) -> None:
    protocol["injection"].pop("noise_conditions")


def _minimal_effective(effective: dict) -> dict:
    return {
        "features": {
            key: (list(value) if isinstance(value, list) else value)
            for key, value in effective["features"].items()
        },
        "injection": dict(effective["injection"]),
        "preprocessing": dict(effective["preprocessing"]),
    }


@pytest.mark.parametrize(
    "mutate, message",
    [
        (_drop_features, "no features block"),
        (_drop_primary_model, "primary_model"),
        (_add_unbuildable_detector_output, "cannot produce the declared feature columns"),
        (_add_unknown_noise, "unsupported noise conditions"),
        (_drop_noise_conditions, "noise_conditions"),
    ],
)
def test_invalid_effective_view_fails_closed(effective, mutate, message):
    protocol = _minimal_effective(effective)
    mutate(protocol)

    with pytest.raises(phase11.GateError, match=message):
        b2a.build_fit_split_frame(effective=protocol, split_map=SPLIT_MAP, seed=1)


def test_non_mapping_effective_view_fails_closed():
    with pytest.raises(phase11.GateError, match="must be a mapping"):
        b2a.build_fit_split_frame(effective=None, split_map=SPLIT_MAP, seed=1)


# --- output isolation --------------------------------------------------------


def test_write_helper_isolates_destinations(effective, tmp_path):
    frame = _build(effective)
    target = tmp_path / "synthetic_run"
    written = b2a.write_fit_split_csv(
        frame, target, manifest_dir=MANIFEST_DIR, repo_root=gen.project_root()
    )

    assert written.is_file()
    assert written.parent == target.resolve()
    assert not (target / "test_generation.json").exists()
    assert not (target / "test_access.json").exists()
    assert not (target / "fitted.json").exists()


@pytest.mark.parametrize("protected", ["", "smoke", "smoke_invalid_scope_20261022"])
def test_write_helper_refuses_protected_destinations(effective, protected):
    frame = _build(effective)
    destination = MANIFEST_DIR / protected if protected else MANIFEST_DIR
    before = sorted(path.name for path in destination.iterdir())

    with pytest.raises(RuntimeError, match="frozen manifest tree|protected"):
        b2a.write_fit_split_csv(
            frame, destination, manifest_dir=MANIFEST_DIR, repo_root=gen.project_root()
        )

    assert sorted(path.name for path in destination.iterdir()) == before
    assert not (destination / b2a.OUTPUT_FILENAME).exists()


def test_builder_creates_no_campaign_markers(effective, tmp_path):
    frame = _build(effective)
    destination = tmp_path / "markers"
    b2a.write_fit_split_csv(
        frame, destination, manifest_dir=MANIFEST_DIR, repo_root=gen.project_root()
    )

    present = sorted(path.name for path in destination.iterdir())
    assert present == [b2a.OUTPUT_FILENAME]
    assert not set(present) & set(safeguards.CAMPAIGN_STATE_NAMES)


# --- design §5.5 synthetic-only guard ----------------------------------------

REAL_DATA_FUNNELS = (
    (gen, "load_quarter"),
    (gen, "quarter_files"),
    (gen, "build_manifests"),
    (phase11, "_load_window_series"),
    (core, "load_curve"),
    (ti, "load_light_curve"),
    (ti, "_load_cached"),
)


def _install_guard(monkeypatch) -> Path:
    """Block every enumerated real-data funnel and any read under data/processed."""

    def blocked(*_args, **_kwargs):
        raise AssertionError("B2a must not open real source data")

    for module, name in REAL_DATA_FUNNELS:
        if hasattr(module, name):
            monkeypatch.setattr(module, name, blocked)

    processed = (gen.project_root() / "data" / "processed").resolve()
    real_read_csv = pd.read_csv

    def guarded_read_csv(path, *args, **kwargs):
        resolved = Path(path).resolve()
        if resolved == processed or resolved.is_relative_to(processed):
            raise AssertionError(f"B2a opened real source data: {resolved}")
        return real_read_csv(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", guarded_read_csv)
    return processed


def test_b2a_runs_behind_the_synthetic_only_guard(effective, tmp_path, monkeypatch):
    processed = _install_guard(monkeypatch)

    frame = _build(effective)
    written = b2a.write_fit_split_csv(
        frame, tmp_path / "guarded", manifest_dir=MANIFEST_DIR, repo_root=gen.project_root()
    )

    reloaded = pd.read_csv(written)
    assert len(reloaded) == len(frame)
    assert set(reloaded["split"].unique()) == {"train", "val"}

    with pytest.raises(AssertionError, match="opened real source data"):
        pd.read_csv(processed / "kepler_kepler_10.csv")
