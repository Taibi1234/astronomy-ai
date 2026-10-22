"""Phase 11b stage 2 integration tests: the real numerical path on synthetic fixtures.

These tests fit actual scikit-learn models, but only on synthetic rows. No campaign
trial, no real light curve and no test row is read.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestClassifier

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import generalization as gen  # noqa: E402
from research import phase11  # noqa: E402

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"
MODEL_ID = "L7_detector_plus_clean_flux"
FEATURES = list(gen.DETECTOR_OUTPUTS + gen.FLUX_FEATURES_CLEAN)


def _synthetic_frame(
    *, n_train: int = 60, n_val: int = 30, nan_fraction: float = 0.0, seed: int = 11
) -> pd.DataFrame:
    """Synthetic trials with a learnable signal and optional missing values."""
    rng = np.random.default_rng(seed)
    rows = []
    for split, count in (("train", n_train), ("val", n_val)):
        for index in range(count):
            injected = index % 2 == 0
            signal = 1.0 if injected else 0.0
            rows.append(
                {
                    "trial_id": f"{split}-{index}",
                    "split": split,
                    "quarter": "Q03" if split == "train" else "Q10",
                    "role": "injection" if injected else "null_window",
                    "injected": injected,
                    "noise_condition": "observed",
                    "requested_depth_ppm": 150.0 if injected else 0.0,
                    "snr": float(signal * 2.0 + rng.normal(0, 1.0)),
                    "depth_est_ppm": float(signal * 150 + rng.normal(0, 20)),
                    "sigma_ppm": float(abs(rng.normal(300, 20))),
                    "min_depth_ppm": float(abs(rng.normal(120, 30))),
                    "std_ppm": float(abs(rng.normal(400, 30))),
                    "mad_ppm": float(abs(rng.normal(250, 20))),
                    "gap_fraction": float(rng.uniform(0, 0.05)),
                    "mean_flux": float(rng.normal(1.0, 1e-4)),
                    "n_points": 240,
                    "delta_true_days": float(rng.uniform(-0.1, 0.1)),
                    "delta_est_days": float(rng.uniform(-0.1, 0.1)),
                }
            )
    frame = pd.DataFrame(rows)
    if nan_fraction:
        rng_nan = np.random.default_rng(seed + 1)
        mask = rng_nan.random(len(frame)) < nan_fraction
        frame.loc[mask, "mad_ppm"] = np.nan
        train_nan = frame[frame["split"] == "train"].index[0]
        frame.loc[train_nan, "mad_ppm"] = np.nan  # guarantee train-side missingness
    return frame


@pytest.fixture(scope="module")
def protocol():
    return phase11.build_protocol(MANIFEST_DIR)


@pytest.fixture()
def frozen_protocol(tmp_path):
    phase11.write_stage0(tmp_path, MANIFEST_DIR)
    return phase11.load_frozen_json(tmp_path / "protocol.json")


def _fit(frame, protocol, model=None):
    model = model or phase11._default_factory(MODEL_ID, protocol)()
    fitted = phase11.fit_models(frame, protocol, MODEL_ID, model_factory=lambda: model)
    return fitted, model


def _matrix(frame, features, medians):
    values = frame[features].to_numpy(dtype=float)
    return np.where(np.isfinite(values), values, np.asarray(medians, dtype=float))


# --- feature preparation and train-only statistics ---------------------------


def test_constant_feature_is_dropped_and_recorded(protocol):
    frame = _synthetic_frame()
    frame["mean_flux"] = 1.0
    fitted, _model = _fit(frame, protocol)
    assert "mean_flux" in fitted["dropped_features"]
    assert "mean_flux" not in fitted["features"]
    assert set(fitted["features"]) == set(FEATURES) - {"mean_flux"}


def test_imputation_medians_come_from_train_rows_only(protocol):
    frame = _synthetic_frame(nan_fraction=0.15)
    train = frame[frame["split"] == "train"]
    expected = np.nanmedian(train[FEATURES].to_numpy(dtype=float), axis=0)
    fitted, _model = _fit(frame, protocol)
    kept = [FEATURES.index(feature) for feature in fitted["features"]]
    assert np.allclose(fitted["imputation_medians"], expected[kept])


def test_scaler_is_fitted_on_train_rows_only(protocol):
    frame = _synthetic_frame()
    for feature in FEATURES:  # shift validation far away from train
        frame.loc[frame["split"] == "val", feature] += 25.0
    fitted, model = _fit(frame, protocol)
    train = frame[frame["split"] == "train"]
    expected = np.nanmedian(train[fitted["features"]].to_numpy(dtype=float), axis=0)
    matrix = _matrix(train, fitted["features"], expected)
    scaler = model.named_steps["scale"]
    assert np.allclose(scaler.mean_, matrix.mean(axis=0))


# --- LR and RF numerical paths ----------------------------------------------


def test_logistic_regression_fits_and_separates_the_synthetic_signal(protocol):
    frame = _synthetic_frame()
    fitted, model = _fit(frame, protocol)
    val = frame[frame["split"] == "val"]
    matrix = _matrix(val, fitted["features"], fitted["imputation_medians"])
    scores = model.predict_proba(matrix)[:, 1]
    assert np.all((scores >= 0) & (scores <= 1))
    injected = val["injected"].to_numpy(bool)
    assert scores[injected].mean() > scores[~injected].mean()
    assert fitted["threshold"]["n"] == int((val["role"] == "null_window").sum())


def test_random_forest_fits_and_serializes(protocol, frozen_protocol, tmp_path):
    frame = _synthetic_frame()
    rf = RandomForestClassifier(**protocol["models"]["random_forest"]["params"])
    fitted = phase11.fit_models(frame, protocol, MODEL_ID, model_factory=lambda: rf)
    protocol_payload, protocol_hash = frozen_protocol
    frozen = phase11.freeze_fitted(
        tmp_path,
        fitted=fitted,
        model=rf,
        trials=frame,
        protocol=protocol_payload,
        protocol_hash=protocol_hash,
    )
    loaded = phase11.load_fitted(tmp_path, protocol_hash)
    assert loaded["model_id"] == MODEL_ID
    assert frozen["fitted.json"] == loaded["_sha256"]


def test_threshold_is_the_validation_null_p95(protocol):
    frame = _synthetic_frame()
    fitted, model = _fit(frame, protocol)
    val_nulls = frame[(frame["split"] == "val") & (frame["role"] == "null_window")]
    matrix = _matrix(val_nulls, fitted["features"], fitted["imputation_medians"])
    scores = model.predict_proba(matrix)[:, 1]
    expected = float(np.percentile(scores, 95, method="linear"))
    assert fitted["threshold"]["quantile_p95"] == pytest.approx(expected)
    assert fitted["threshold"]["threshold"] >= expected - 1e-12
    assert fitted["threshold"]["calibration_exceedance"] <= protocol["thresholds"]["target_fpr"]
    assert fitted["threshold"]["n"] == len(val_nulls)


def test_freeze_reload_predicts_identically(protocol, frozen_protocol, tmp_path):
    frame = _synthetic_frame()
    fitted, model = _fit(frame, protocol)
    protocol_payload, protocol_hash = frozen_protocol
    phase11.freeze_fitted(
        tmp_path,
        fitted=fitted,
        model=model,
        trials=frame,
        protocol=protocol_payload,
        protocol_hash=protocol_hash,
    )
    loaded = phase11.load_fitted(tmp_path, protocol_hash)
    reloaded = __import__("pickle").loads((tmp_path / loaded["model_file"]).read_bytes())
    check = frame[frame["split"] == "val"]
    matrix = _matrix(check, loaded["features"], loaded["imputation_medians"])
    assert np.allclose(
        reloaded.predict_proba(matrix)[:, 1], model.predict_proba(matrix)[:, 1]
    )


def test_fit_refuses_test_rows_with_a_real_factory(protocol):
    frame = _synthetic_frame()
    extra = frame[frame["split"] == "val"].head(4).assign(split="test")
    poisoned = pd.concat([frame, extra], ignore_index=True)
    with pytest.raises(phase11.GateError):
        phase11.fit_models(poisoned, protocol, MODEL_ID)


def test_feature_order_and_missingness_are_handled(protocol):
    frame = _synthetic_frame(nan_fraction=0.2)
    frame.loc[frame["split"] == "val", "snr"] = np.nan
    fitted, _model = _fit(frame, protocol)
    assert fitted["features"] == [f for f in FEATURES if f in fitted["features"]]
    assert all(np.isfinite(fitted["imputation_medians"]))


# --- protocol binding --------------------------------------------------------


def test_fitted_state_binds_to_the_protocol_hash(frozen_protocol, tmp_path):
    frame = _synthetic_frame()
    fitted, model = _fit(frame, phase11.build_protocol(MANIFEST_DIR))
    protocol_payload, protocol_hash = frozen_protocol
    phase11.freeze_fitted(
        tmp_path,
        fitted=fitted,
        model=model,
        trials=frame,
        protocol=protocol_payload,
        protocol_hash=protocol_hash,
    )
    other = copy.deepcopy(protocol_payload)
    other["seeds"]["model"] += 1
    with pytest.raises(phase11.GateError):
        phase11.load_fitted(tmp_path, "0" * 64)
    assert other["seeds"]["model"] != protocol_payload["seeds"]["model"]


def test_run_campaign_on_synthetic_quarters_uses_each_window(tmp_path, monkeypatch):
    """Exercise the real campaign path on a tiny synthetic repository.

    Two windows in one quarter carry deliberately different flux levels, so a window
    indexing bug (using the last window of the quarter for every trial) is visible.
    """
    repo = tmp_path / "repo"
    processed = repo / "data" / "processed"
    processed.mkdir(parents=True)
    cadence = 29.4 / 1440.0
    times = np.arange(0.0, 200 * cadence, cadence)[:200]
    flux = np.concatenate(
        [1.0 + 1e-5 * np.sin(np.arange(100)), 2.0 + 1e-5 * np.sin(np.arange(100))]
    )

    pd.DataFrame({"time": times, "normalized_flux": flux}).to_csv(
        processed / "kepler_q00_quality_masked.csv", index=False
    )

    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    windows = [
        {
            "quarter": "Q00",
            "split": "train",
            "role": "injection",
            "window_index": index,
            "piece_index": 0,
            "start_index": index * 100,
            "end_index": (index + 1) * 100,
        }
        for index in (0, 1)
    ]
    (manifest_dir / "windows_primary.json").write_text(
        json.dumps({"windows": windows}), encoding="utf-8"
    )
    offsets = {
        "phase": "11b",
        "schema_version": 1,
        "by_window_length": {
            "5.0": {
                "draws": [
                    {"quarter": "Q00", "window_index": 0, "offsets_days": [0.01, -0.01]},
                    {"quarter": "Q00", "window_index": 1, "offsets_days": [0.02, -0.02]},
                ]
            }
        },
    }
    phase11.write_json_with_sidecar(manifest_dir / "offsets.json", offsets)
    monkeypatch.setattr(phase11, "build_protocol", lambda _manifest_dir: {})

    out_dir = tmp_path / "out"
    frame = phase11.run_campaign(
        manifest_dir=manifest_dir,
        out_dir=out_dir,
        window_days=5.0,
        split_group="fit",
        root=repo,
        manifest_name="windows_primary.json",
    )
    assert len(frame) == 2 * (5 + 1) * 2 * 2
    assert set(frame["split"]) == {"train"}
    assert np.isfinite(frame["snr"]).all()
    assert set(frame["delta_true_days"]) == {0.01, -0.01, 0.02, -0.02}
    baseline = frame[
        (frame["requested_depth_ppm"] == 0)
        & (frame["offset_index"] == 0)
        & (frame["noise_condition"] == "observed")
    ]
    per_window = baseline.set_index("window_index")["mean_flux"]
    assert per_window.loc[0] == pytest.approx(1.0, abs=0.01)
    assert per_window.loc[1] == pytest.approx(2.0, abs=0.01)
    assert (out_dir / "trials_fit.csv").is_file()

    subset = phase11.run_campaign(
        manifest_dir=manifest_dir,
        out_dir=tmp_path / "out_subset",
        window_days=5.0,
        split_group="fit",
        root=repo,
        manifest_name="windows_primary.json",
        windows=[windows[0]],
    )
    assert len(subset) == (5 + 1) * 2 * 2
    assert set(subset["window_index"]) == {0}


def test_trial_role_survives_a_csv_roundtrip(tmp_path):
    """'null' is a pandas NA token, so the trial vocabulary must not use it."""
    windows = json.loads(
        (MANIFEST_DIR / "windows_primary.json").read_text(encoding="utf-8")
    )["windows"]
    null_window = next(
        window for window in windows if window["role"] == "null" and window["split"] == "train"
    )
    plan = phase11.plan_trials(
        [null_window], phase11.build_protocol(MANIFEST_DIR), "fit"
    )
    assert set(plan["role"]) == {"null_window"}
    path = tmp_path / "trials.csv"
    plan.to_csv(path, index=False)
    assert set(pd.read_csv(path)["role"]) == {"null_window"}
