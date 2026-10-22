"""Phase 11 baseline hardening tests: path, schema and stratum validation.

These tests exercise validators and loaders only. They do not fit models, run a
campaign, evaluate test data, or read any held-out trial.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import phase11  # noqa: E402

# --- model filename ----------------------------------------------------------


def test_safe_model_filename_accepts_only_the_expected_name():
    assert phase11._safe_model_filename("model.pkl") == "model.pkl"


@pytest.mark.parametrize(
    "name",
    ["../model.pkl", "../../etc/passwd", "C:/tmp/model.pkl", "/abs/model.pkl",
     "models/model.pkl", "other.pkl", "", None, 7],
)
def test_safe_model_filename_rejects_traversal_and_absolutes(name):
    with pytest.raises(phase11.GateError):
        phase11._safe_model_filename(name)


def test_load_fitted_rejects_traversal_model_file(tmp_path):
    payload = {
        "model_file": "../evil.pkl",
        "model_sha256": "0" * 64,
        "protocol_sha256": "deadbeef",
    }
    phase11.write_json_with_sidecar(tmp_path / "fitted.json", payload)
    with pytest.raises(phase11.GateError, match="model.pkl"):
        phase11.load_fitted(tmp_path, "deadbeef")


def test_load_fitted_rejects_absolute_model_file(tmp_path):
    payload = {
        "model_file": "C:/tmp/evil.pkl",
        "model_sha256": "0" * 64,
        "protocol_sha256": "deadbeef",
    }
    phase11.write_json_with_sidecar(tmp_path / "fitted.json", payload)
    with pytest.raises(phase11.GateError, match="model.pkl"):
        phase11.load_fitted(tmp_path, "deadbeef")


# --- quarter identifiers -----------------------------------------------------


@pytest.mark.parametrize("quarter", ["Q00", "Q01", "Q17", "Q99"])
def test_validate_quarter_accepts_expected_form(quarter):
    assert phase11.validate_quarter(quarter) == quarter


@pytest.mark.parametrize(
    "quarter",
    ["../Q00", "q00", "Q0", "Q000", "Q0a", "Q00/../x", "Q00\n", "", None, 17],
)
def test_validate_quarter_rejects_other_forms(quarter):
    with pytest.raises(phase11.GateError):
        phase11.validate_quarter(quarter)


def test_window_series_rejects_bad_quarter_before_io(tmp_path):
    with pytest.raises(phase11.GateError):
        phase11._load_window_series("../etc", tmp_path)


def test_index_windows_rejects_bad_quarter():
    windows = [{"quarter": "../../x", "window_index": 0}]
    with pytest.raises(phase11.GateError):
        phase11.index_windows(windows)


# --- frozen JSON schema ------------------------------------------------------


def _write(tmp_path, name, payload):
    phase11.write_json_with_sidecar(tmp_path / name, payload)
    return tmp_path / name


def test_load_frozen_json_checks_phase_and_schema(tmp_path):
    good = _write(
        tmp_path, "good.json", {"phase": "11b", "schema_version": 1, "body": {}}
    )
    payload, digest = phase11.load_frozen_json(
        good, expected_phase="11b", expected_schema=1
    )
    assert payload["body"] == {}
    assert digest == phase11.sha256_file(good)

    wrong_phase = _write(
        tmp_path, "phase.json", {"phase": "10", "schema_version": 1}
    )
    with pytest.raises(phase11.GateError, match="phase"):
        phase11.load_frozen_json(
            wrong_phase, expected_phase="11b", expected_schema=1
        )

    wrong_schema = _write(
        tmp_path, "schema.json", {"phase": "11b", "schema_version": 2}
    )
    with pytest.raises(phase11.GateError, match="schema_version"):
        phase11.load_frozen_json(
            wrong_schema, expected_phase="11b", expected_schema=1
        )

    missing = _write(tmp_path, "missing.json", {"body": {}})
    with pytest.raises(phase11.GateError, match="phase"):
        phase11.load_frozen_json(missing, expected_phase="11b")


# --- noise strata ------------------------------------------------------------


def test_require_noise_strata_accepts_complete_sets():
    phase11.require_noise_strata(["observed", "amplified_x2"], ["observed", "amplified_x2"],
                                 context="unit")


def test_require_noise_strata_rejects_missing_stratum():
    with pytest.raises(phase11.GateError, match="missing noise strata"):
        phase11.require_noise_strata(["observed"], ["observed", "amplified_x2"], context="unit")


def test_require_noise_strata_rejects_unexpected_stratum_unless_allowed():
    with pytest.raises(phase11.GateError, match="unexpected noise strata"):
        phase11.require_noise_strata(["observed", "extra"], ["observed"], context="unit")
    phase11.require_noise_strata(
        ["observed", "extra"], ["observed"], context="unit", allow_extra=True
    )


def test_threshold_value_missing_stratum_is_a_gate_error():
    with pytest.raises(phase11.GateError, match="missing noise stratum"):
        phase11._threshold_value({"observed": {"threshold": 3.0}}, "amplified_x2")


# --- wiring: calibration and physics require declared strata -----------------


def test_calibration_requires_all_declared_strata():
    frame = pd.DataFrame(
        {
            "role": ["null_window", "null_window"],
            "split": ["train", "val"],
            "noise_condition": ["observed", "observed"],
            "snr": [1.0, 2.0],
        }
    )
    protocol = {
        "injection": {"noise_conditions": ["observed", "amplified_x2"]},
        "thresholds": {"target_fpr": 0.05, "detector": {"floor_snr": 3.0}},
    }
    with pytest.raises(phase11.GateError, match="missing noise strata"):
        phase11.calibrate_detector_thresholds(frame, protocol)


def test_physics_requires_a_threshold_for_each_present_stratum():
    frame = pd.DataFrame(
        {
            "split": ["test", "test"],
            "noise_condition": ["observed", "amplified_x2"],
            "injected": [False, False],
            "snr": [1.0, 1.0],
            "delta_true_days": [0.0, 0.0],
            "delta_est_days": [0.0, 0.0],
            "quarter": ["Q09", "Q09"],
            "requested_depth_ppm": [0.0, 0.0],
        }
    )
    with pytest.raises(phase11.GateError, match="missing noise strata"):
        phase11.physics_operating_point(
            frame, {"observed": {"threshold": 3.0}}, resamples=100
        )
