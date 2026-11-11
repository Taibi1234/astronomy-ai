"""Phase 10 tests: detector, experiment integrity, and the recovery API.

Fast fixtures only; the full campaign is never run in the unit-test suite.
"""

import json
import os
import subprocess
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
from research import core, experiment  # noqa: E402

client = TestClient(backend.app)


# --- detector ----------------------------------------------------------------


def _chunk(mission="kepler", n_days=3.0, cadence_min=29.4):
    t = np.arange(0.0, n_days, cadence_min / 1440.0)
    rng = np.random.default_rng(7)
    f = 1.0 + rng.normal(0, 2e-4, len(t))
    return t, f


def test_zero_depth_injection_leaves_flux_unchanged():
    t, f = _chunk()
    dt = core.phase_offsets(t, "kepler", 0.05)
    assert np.array_equal(ti.inject_transit(f, dt, 0), f)


def test_nonzero_injection_only_changes_in_transit_samples():
    t, f = _chunk()
    dt = core.phase_offsets(t, "kepler", 0.05)
    out = ti.inject_transit(f, dt, 300)
    changed = out != f
    assert changed.any()
    assert np.all(np.abs(dt[changed]) < 0.06)
    assert np.all(out <= f + 1e-15)


def test_detector_recovers_a_deep_injection_without_truth():
    t, f = _chunk(n_days=6.0)
    truth = 0.07
    injected = ti.inject_transit(f, core.phase_offsets(t, "kepler", truth), 600)
    result = core.detect(t, injected, "kepler")
    assert result["snr"] > 5
    assert abs(result["delta"] - truth) < core.TOLERANCE_DAYS


def test_detector_ignores_a_pure_brightening():
    """Polarity: an upward spike must not score as a transit."""
    t, f = _chunk(n_days=6.0)
    spike = f.copy()
    idx = np.argsort(np.abs(core.phase_offsets(t, "kepler", 0.0)))[:4]
    spike[idx] += 5e-4
    assert core.detect(t, spike, "kepler")["snr"] < core.detect(t, f, "kepler")["snr"] + 3


def test_transit_duration_matches_the_fixed_geometry():
    duration_hours = core.transit_duration_days() * 24
    assert 1.5 < duration_hours < 2.2


# --- design guarantees --------------------------------------------------------


def test_split_is_grouped_by_chunk():
    rng = np.random.default_rng(1)
    split = experiment._split_map([f"c{i}" for i in range(8)], rng)
    groups = list(split)
    assert len(set(split.values())) >= 2
    assert all(split[g] in {"train", "val", "test"} for g in groups)
    sizes = pd.Series(split).value_counts()
    assert sizes.get("train", 0) == 4


def test_thresholds_use_non_test_controls_only():
    rows = []
    for _chunk_id, split in (("a", "train"), ("b", "val"), ("c", "test")):
        rows.append(
            {
                "dataset": "kepler",
                "noise_condition": "observed",
                "split": split,
                "requested_depth_ppm": 0.0,
                "snr": 1.0 if split != "test" else 99.0,
            }
        )
    frame = pd.DataFrame(rows)
    thresholds = experiment._thresholds(frame)
    assert thresholds["kepler|observed"]["threshold_snr"] < 5.0


def test_threshold_has_a_three_sigma_floor():
    frame = pd.DataFrame(
        [
            {
                "dataset": "kepler",
                "noise_condition": "observed",
                "split": "train",
                "requested_depth_ppm": 0.0,
                "snr": s,
            }
            for s in (0.1, 0.2, 0.3)
        ]
    )
    assert experiment._thresholds(frame)["kepler|observed"]["threshold_snr"] == 3.0


def test_noise_condition_is_reproducible():
    t, f = _chunk()
    a = core.apply_noise_condition(f, "amplified_x2")
    b = core.apply_noise_condition(f, "amplified_x2")
    assert np.array_equal(a, b)
    assert np.std(a) > np.std(f)


def test_published_transit_removal_uses_no_injection_truth():
    t, f = _chunk(n_days=6.0)
    injected = ti.inject_transit(f, core.phase_offsets(t, "kepler", 0.0), 400)
    cleaned, amplitude = core.remove_published_transit(t, injected, "kepler")
    assert amplitude == pytest.approx(400, abs=120)
    assert np.std(cleaned) <= np.std(injected)


# --- statistics ---------------------------------------------------------------


def test_wilson_interval_matches_reference_values():
    interval = core.wilson_interval(9, 10)
    assert 0.55 < interval["low"] < 0.62
    assert 0.96 < interval["high"] <= 1.0
    empty = core.wilson_interval(0, 0)
    assert empty["low"] is None and empty["n"] == 0


def test_metric_block_marks_undefined_metrics():
    block = experiment._metric_block(np.array([1, 1]), np.array([1, 1]), np.array([0.9, 0.8]))
    assert block["roc_auc"] is None and block["note"]
    assert block["f1_no_skill_predict_all_positive"] == pytest.approx(1.0)


def test_metric_block_reports_prevalence():
    block = experiment._metric_block(
        np.array([1, 1, 0, 0]), np.array([1, 0, 0, 0]), np.array([0.9, 0.4, 0.2, 0.1])
    )
    assert block["prevalence"] == 0.5
    assert block["f1_no_skill_predict_all_positive"] == pytest.approx(2 / 3)


# --- API ----------------------------------------------------------------------


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    (tmp_path / "figures").mkdir()
    summary = {
        "mode": "smoke",
        "status": "completed",
        "runtime_seconds": 1.0,
        "started_at": "x",
        "finished_at": "y",
        "counts": {"trials_total": 2},
        "thresholds": {},
        "benchmark": {"methods": {}},
        "limitations": [],
        "provenance": {},
    }
    (tmp_path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (tmp_path / "plot_data.json").write_text(
        json.dumps({"recovery_by_depth": []}), encoding="utf-8"
    )
    (tmp_path / "recovery_report.md").write_text("# report\n", encoding="utf-8")
    pd.DataFrame([{"trial_id": "t1", "snr": 1.0}]).to_csv(
        tmp_path / "trial_results.csv", index=False
    )
    (tmp_path / "figures" / "recovery_vs_depth.png").write_bytes(b"\x89PNG\r\n")
    monkeypatch.setattr(backend, "RECOVERY_DIR", tmp_path)
    return tmp_path


def test_status_reports_completed_from_artifacts(artifacts):
    body = client.get("/api/injection-recovery/status").json()
    assert body["status"] == "completed"
    assert body["source"] == "artifacts"


def test_results_returns_summary_and_preview(artifacts):
    body = client.get("/api/injection-recovery/results").json()
    assert body["status"] == "completed"
    assert body["summary"]["mode"] == "smoke"
    assert body["trials_preview"][0]["trial_id"] == "t1"
    assert "trial_results.csv" in body["artifacts"]


def test_report_is_markdown(artifacts):
    response = client.get("/api/injection-recovery/report")
    assert response.status_code == 200
    assert response.text.startswith("# report")


def test_artifact_download_is_allowlisted(artifacts):
    assert client.get("/api/injection-recovery/artifacts/summary.json").status_code == 200
    assert client.get("/api/injection-recovery/artifacts/../../app.py").status_code == 404
    assert client.get("/api/injection-recovery/artifacts/unknown.json").status_code == 404


def test_artifact_download_is_not_heuristically_cached(artifacts):
    """Artifacts are rewritten in place by every run, so browsers must revalidate.

    Without Cache-Control, Chrome served the previous run's summary.json to the
    download links (Phase 10 browser acceptance).
    """
    response = client.get("/api/injection-recovery/artifacts/summary.json")
    cache_control = response.headers["cache-control"]
    assert "no-cache" in cache_control
    assert response.headers["etag"]


def test_missing_artifacts_are_reported_not_crashed(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "RECOVERY_DIR", tmp_path)
    status = client.get("/api/injection-recovery/status").json()
    assert status["status"] in {"not_run", "failed"}
    results = client.get("/api/injection-recovery/results").json()
    assert results["status"] == "not_run"
    assert client.get("/api/injection-recovery/report").status_code == 404


def test_invalid_run_mode_is_rejected():
    assert client.post("/api/injection-recovery/run", json={"mode": "turbo"}).status_code == 422
    assert client.post("/api/injection-recovery/run", json={"mode": "../etc"}).status_code == 422


def test_duplicate_run_is_refused(monkeypatch):
    monkeypatch.setattr(
        backend.recovery_manager, "start", lambda mode: (False, {"status": "running"})
    )
    response = client.post("/api/injection-recovery/run", json={"mode": "smoke"})
    assert response.status_code == 409


def test_cors_preflight_allows_the_browser_to_start_a_run():
    """The UI posts JSON from :5173, so the POST preflight must succeed.

    A GET-only allowlist passed every API-level test while making "Run smoke"
    fail in the browser with "Failed to fetch" (Phase 10 browser acceptance).
    """
    response = client.options(
        "/api/injection-recovery/run",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert "POST" in response.headers["access-control-allow-methods"]
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_preflight_still_rejects_unused_methods_and_origins():
    disallowed_method = client.options(
        "/api/injection-recovery/run",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "DELETE",
        },
    )
    assert disallowed_method.status_code == 400

    unknown_origin = client.options(
        "/api/injection-recovery/run",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert unknown_origin.status_code == 400
    assert "access-control-allow-origin" not in unknown_origin.headers


def test_existing_endpoints_still_work():
    for path in (
        "/api/health",
        "/api/project",
        "/api/artifacts",
        "/api/ml-results",
        "/api/lightcurve/kepler?max_points=100",
        "/api/transit-injection?mission=kepler&depth_ppm=0",
    ):
        assert client.get(path).status_code == 200, path


def test_runner_is_disabled_by_default():
    """The run route must not exist without an explicit operator opt-in.

    The suite opts in via conftest.py (ASTRONOMY_ENABLE_RUNNER=1), so this
    check needs a clean interpreter that never sees that variable.
    """
    env = {k: v for k, v in os.environ.items() if k != "ASTRONOMY_ENABLE_RUNNER"}
    result = subprocess.run(
        [sys.executable, "-c", "import app; print(app.RUNNER_ENABLED)"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


# --- report-generation regressions (Phase 10 audit) ---------------------------

from research import reports  # noqa: E402


def _audit_summary():
    return {
        "mode": "smoke",
        "status": "completed",
        "runtime_seconds": 1.0,
        "started_at": "a",
        "finished_at": "b",
        "counts": {
            "trials_total": 4,
            "trials_valid": 4,
            "trials_invalid": 0,
            "controls_evaluated_for_fpr": 2,
            "chunks": {"kepler": 2},
            "splits": {"kepler": {"chunks": {"train": 1, "val": 0, "test": 1}}},
        },
        "thresholds": {
            "kepler|observed": {"threshold_snr": 3.0, "source": "x", "n_calibration_controls": 2}
        },
        "recovery_by_depth_all_splits": [
            {
                "requested_depth_ppm": 150.0,
                "recovered": 1,
                "trials": 2,
                "fraction": 0.5,
                "wilson_low": 0.09,
                "wilson_high": 0.91,
                "median_recovered_depth_ppm": 150.0,
                "median_timing_error_days": 0.01,
            }
        ],
        "recovery_by_depth_test_split": [],
        "recovery_by_dataset_and_noise": [],
        "false_positive_rate": {
            "controls": 2,
            "false_positives": 0,
            "rate": 0.0,
            "wilson_low": 0.0,
            "wilson_high": 0.7,
            "definition": "x",
        },
        "benchmark": {
            "status": "ok",
            "splits": {"test": {"windows": 4, "groups": 1, "positive": 3, "negative": 1}},
            "methods": {
                "physics_matched_filter": {
                    "n": 4,
                    "prevalence": 0.75,
                    "precision": 1.0,
                    "recall": 0.5,
                    "f1": 0.667,
                    "roc_auc": 0.9,
                    "pr_auc": 0.95,
                    "f1_no_skill_predict_all_positive": 0.857,
                },
                "logistic_regression": {
                    "n": 4,
                    "prevalence": 0.75,
                    "precision": 0.75,
                    "recall": 1.0,
                    "f1": 0.857,
                    "roc_auc": 0.6,
                    "pr_auc": 0.8,
                    "f1_no_skill_predict_all_positive": 0.857,
                    "__note": "constant-positive",
                },
            },
        },
        "limitations": ["x"],
        "config": {
            "tolerance_days": 0.0377,
            "datasets": ["kepler"],
            "search_half_days": 0.2,
            "search_step_days": 0.0025,
        },
        "provenance": {
            "source_hashes": {"kepler": "a" * 64},
            "seed": 1,
            "python": "3",
            "packages": {"numpy": "1", "pandas": "1", "scikit-learn": "1", "batman": "1"},
            "git_commit": None,
            "command": "c",
        },
    }


def _audit_trials():
    return pd.DataFrame(
        [
            {
                "trial_id": "a",
                "dataset": "kepler",
                "chunk_id": "k0",
                "split": "train",
                "noise_condition": "observed",
                "requested_depth_ppm": 0.0,
                "injected": False,
                "valid": True,
                "snr": 1.2,
                "detected": False,
                "recovered": False,
                "false_positive": False,
                "timing_error_days": 0.0,
                "depth_est_ppm": 10.0,
            },
            {
                "trial_id": "b",
                "dataset": "kepler",
                "chunk_id": "k0",
                "split": "train",
                "noise_condition": "observed",
                "requested_depth_ppm": 0.0,
                "injected": False,
                "valid": True,
                "snr": 2.0,
                "detected": False,
                "recovered": False,
                "false_positive": False,
                "timing_error_days": 0.0,
                "depth_est_ppm": 20.0,
            },
            {
                "trial_id": "c",
                "dataset": "kepler",
                "chunk_id": "k1",
                "split": "test",
                "noise_condition": "observed",
                "requested_depth_ppm": 0.0,
                "injected": False,
                "valid": True,
                "snr": 9.0,
                "detected": True,
                "recovered": False,
                "false_positive": True,
                "timing_error_days": 0.0,
                "depth_est_ppm": 90.0,
            },
            {
                "trial_id": "d",
                "dataset": "kepler",
                "chunk_id": "k1",
                "split": "test",
                "noise_condition": "observed",
                "requested_depth_ppm": 150.0,
                "injected": True,
                "valid": True,
                "snr": 5.0,
                "detected": True,
                "recovered": True,
                "false_positive": False,
                "timing_error_days": 0.01,
                "depth_est_ppm": 160.0,
            },
        ]
    )


def test_generated_report_states_the_no_skill_baseline():
    summary = _audit_summary()
    plot_data = reports.plot_data_from_summary(summary, _audit_trials())
    markdown = reports.render_markdown(summary, plot_data)
    assert "no-skill F1" in markdown
    assert "0.857" in markdown
    assert "positive prevalence" in markdown
    assert "demonstrated no skill" in markdown


def test_control_figure_scope_matches_fpr_denominator():
    summary = _audit_summary()
    plot_data = reports.plot_data_from_summary(summary, _audit_trials())
    controls = plot_data["controls"]
    assert controls["n"] == 3  # all valid zero-depth trials
    assert controls["n_test"] == 2  # matches the FPR denominator in summary.json
    assert controls["false_positives"] == summary["false_positive_rate"]["false_positives"]
    assert "test-split controls only" in controls["scope"]


def test_regeneration_rebuilds_plot_data_and_is_deterministic(tmp_path):
    (tmp_path / "figures").mkdir()
    (tmp_path / "summary.json").write_text(json.dumps(_audit_summary()), encoding="utf-8")
    _audit_trials().to_csv(tmp_path / "trial_results.csv", index=False)
    # Deliberately stale derived artifact: regeneration must not trust it.
    (tmp_path / "plot_data.json").write_text("{}", encoding="utf-8")

    reports.regenerate_from_artifacts(tmp_path)
    first = (tmp_path / "recovery_report.md").read_bytes()
    rebuilt = json.loads((tmp_path / "plot_data.json").read_text(encoding="utf-8"))
    assert rebuilt["recovery_by_depth"][0]["requested_depth_ppm"] == 150.0

    reports.regenerate_from_artifacts(tmp_path)
    assert (tmp_path / "recovery_report.md").read_bytes() == first
