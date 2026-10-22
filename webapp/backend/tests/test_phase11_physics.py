"""Phase 11b stage 2 tests: physics operating-point reporting and calibration.

Synthetic trial tables only; no campaign data and no real light curves.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import core, phase11  # noqa: E402

THRESHOLDS = {"observed": {"threshold": 3.0}, "amplified_x2": {"threshold": 3.0}}


def _trial(**overrides) -> dict:
    base = {
        "trial_id": "t",
        "split": "test",
        "quarter": "Q09",
        "noise_condition": "observed",
        "requested_depth_ppm": 150.0,
        "injected": True,
        "snr": 4.0,
        "delta_true_days": 0.05,
        "delta_est_days": 0.05,
    }
    base.update(overrides)
    return base


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_spec_matches_the_detector_constants():
    spec = phase11.DETECTOR_REPORT_SPEC
    assert spec["timing_tolerance_days"] == core.TOLERANCE_DAYS
    assert spec["score"] == "snr"
    assert spec["clusters"] == "quarter"
    assert "strict" not in spec["detected"]  # rule is expressed as '>' in the string


def test_operating_point_counts_fpr_and_recall_exactly():
    rows = [
        _trial(trial_id="n1", injected=False, snr=4.0),
        _trial(trial_id="n2", injected=False, snr=2.0),
        _trial(trial_id="n3", injected=False, snr=5.0),
        _trial(trial_id="n4", injected=False, snr=1.0),
        _trial(trial_id="i1", snr=4.0, delta_true_days=0.05, delta_est_days=0.05),
        _trial(trial_id="i2", snr=4.0, delta_true_days=-0.05, delta_est_days=-0.04),
        _trial(trial_id="i3", snr=4.0, delta_true_days=0.10, delta_est_days=0.00),
        _trial(trial_id="i4", snr=2.0, delta_true_days=0.00, delta_est_days=0.00),
    ]
    report = phase11.physics_operating_point(
        _frame(rows), THRESHOLDS, resamples=200
    )
    pooled = report["pooled"]
    assert pooled["null_trials"] == 4
    assert pooled["false_positives"] == 2
    assert pooled["fpr"] == pytest.approx(0.5)
    assert pooled["injected_trials"] == 4
    # i3 is detected but outside the timing tolerance; i4 is below threshold.
    assert pooled["recovered"] == 2
    assert pooled["recall"] == pytest.approx(0.5)
    assert pooled["fpr_wilson"]["k"] == 2 and pooled["fpr_wilson"]["n"] == 4
    assert report["timing_tolerance_days"] == core.TOLERANCE_DAYS


def test_timing_tolerance_is_applied():
    outside = _trial(delta_true_days=0.0, delta_est_days=core.TOLERANCE_DAYS + 0.01, snr=5.0)
    inside = _trial(delta_true_days=0.0, delta_est_days=core.TOLERANCE_DAYS - 0.001, snr=5.0)
    report = phase11.physics_operating_point(
        _frame([outside, inside]), THRESHOLDS, resamples=100
    )
    assert report["pooled"]["recovered"] == 1


def test_threshold_is_applied_per_noise_condition():
    thresholds = {"observed": {"threshold": 3.0}, "amplified_x2": {"threshold": 4.5}}
    rows = [
        _trial(trial_id="a", injected=False, snr=4.0, noise_condition="observed"),
        _trial(trial_id="b", injected=False, snr=4.0, noise_condition="amplified_x2"),
    ]
    report = phase11.physics_operating_point(_frame(rows), thresholds, resamples=100)
    assert report["by_noise"]["observed"]["false_positives"] == 1
    assert report["by_noise"]["amplified_x2"]["false_positives"] == 0
    assert report["thresholds"]["amplified_x2"] == 4.5


def test_by_depth_table_is_reported():
    rows = [
        _trial(trial_id="d75a", requested_depth_ppm=75.0, snr=4.0),
        _trial(trial_id="d75b", requested_depth_ppm=75.0, snr=2.0),
        _trial(trial_id="d300a", requested_depth_ppm=300.0, snr=6.0),
    ]
    report = phase11.physics_operating_point(_frame(rows), THRESHOLDS, resamples=100)
    depths = {row["requested_depth_ppm"]: row for row in report["pooled"]["by_depth"]}
    assert depths[75.0]["recovered"] == 1 and depths[75.0]["trials"] == 2
    assert depths[300.0]["fraction"] == pytest.approx(1.0)


def test_operating_point_refuses_non_test_rows():
    rows = [_trial(split="val"), _trial(split="test")]
    with pytest.raises(phase11.GateError):
        phase11.physics_operating_point(_frame(rows), THRESHOLDS, resamples=100)


def test_cluster_interval_reports_its_method_and_clusters():
    clusters = [np.array([1.0, 0.0, 1.0]), np.array([0.0, 0.0]), np.array([1.0, 1.0])]
    interval = phase11.cluster_bootstrap_ci(clusters, resamples=500, seed=7)
    assert interval["clusters"] == 3
    assert interval["method"] in {"bca", "percentile"}
    assert interval["low"] <= interval["high"]
    assert interval["estimate"] == pytest.approx(4 / 7)
    again = phase11.cluster_bootstrap_ci(clusters, resamples=500, seed=7)
    assert again["low"] == interval["low"] and again["high"] == interval["high"]


def test_single_cluster_returns_no_interval():
    interval = phase11.cluster_bootstrap_ci([np.array([1.0, 0.0])], resamples=100)
    assert interval["clusters"] == 1
    assert interval["low"] is None and interval["high"] is None


def test_wilson_interval_is_bounded_and_sane():
    interval = phase11.wilson_interval(0, 10)
    assert interval["low"] == 0.0
    assert 0.2 < interval["high"] < 0.35
    full = phase11.wilson_interval(10, 10)
    assert full["high"] == 1.0
