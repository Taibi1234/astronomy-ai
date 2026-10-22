"""Phase 11b stage 0-1 tests: protocol/offset integrity and leakage gates.

No campaign is run and no model is fitted on real data: the only fitted objects here
are stubs that record what they were given.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import generalization as gen  # noqa: E402
from research import phase11  # noqa: E402

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"


class StubModel:
    """Picklable stand-in: never trains, only records and scores."""

    def __init__(self, scale: float = 1.0) -> None:
        self.scale = scale
        self.fit_rows = 0
        self.fit_positive = 0

    def fit(self, X, y):
        self.fit_rows = int(len(X))
        self.fit_positive = int(np.sum(y))
        return self

    def predict_proba(self, X):
        z = np.asarray(X, dtype=float)[:, 0] * self.scale
        p = 1.0 / (1.0 + np.exp(-z))
        return np.column_stack([1.0 - p, p])


def _trial_frame(splits=("train", "val"), n_per_role=6, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for split in splits:
        for role in ("injection", "null_window"):
            for index in range(n_per_role):
                rows.append(
                    {
                        "trial_id": f"{split}-{role}-{index}",
                        "split": split,
                        "role": role,
                        "quarter": "Q03",
                        "window_index": index,
                        "injected": role == "injection",
                        "noise_condition": "observed",
                        "snr": float(rng.normal(2.0, 1.0)),
                        "depth_est_ppm": float(rng.normal(100, 30)),
                        "sigma_ppm": float(abs(rng.normal(300, 20))),
                        "min_depth_ppm": float(abs(rng.normal(150, 40))),
                        "std_ppm": float(abs(rng.normal(400, 30))),
                        "mad_ppm": float(abs(rng.normal(250, 20))),
                        "gap_fraction": float(rng.uniform(0, 0.1)),
                        "mean_flux": float(rng.normal(1.0, 1e-4)),
                        "n_points": 240,
                    }
                )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def stage0():
    return phase11.build_stage0(MANIFEST_DIR)


@pytest.fixture(scope="module")
def protocol(stage0):
    return stage0["protocol.json"]


@pytest.fixture(scope="module")
def windows():
    return json.loads(
        (MANIFEST_DIR / "windows_primary.json").read_text(encoding="utf-8")
    )["windows"]


# --- stage 0: protocol -------------------------------------------------------


def test_protocol_has_every_required_section(protocol):
    required = {
        "seeds",
        "features",
        "preprocessing",
        "models",
        "thresholds",
        "metrics",
        "bootstrap",
        "test_access",
        "campaign",
        "manifests",
    }
    assert required <= set(protocol)
    assert protocol["thresholds"]["target_fpr"] == pytest.approx(0.05)
    assert protocol["thresholds"]["comparison"] == "strict '>' (score > threshold means detected)"
    assert protocol["test_access"]["reads"] == 1
    assert protocol["preprocessing"]["fit_splits"] == ["train"]
    assert protocol["features"]["primary_model"] == "L7_detector_plus_clean_flux"


def test_protocol_feature_sets_match_the_frozen_config(protocol):
    config = json.loads((MANIFEST_DIR / "experiment_config.json").read_text(encoding="utf-8"))
    config_sets = {entry["id"]: entry["features"] for entry in config["ml_ladder"]}
    protocol_sets = {
        model_id: entry["features"] for model_id, entry in protocol["features"]["sets"].items()
    }
    assert protocol_sets == config_sets
    assert protocol["features"]["forbidden"] == config["forbidden_feature_columns"]


def test_protocol_manifest_hashes_match_disk(protocol):
    assert protocol["manifests"] == phase11.manifest_hashes(MANIFEST_DIR)


def test_protocol_is_deterministic(stage0):
    again = phase11.build_stage0(MANIFEST_DIR)
    assert json.dumps(stage0, sort_keys=True) == json.dumps(again, sort_keys=True)


# --- stage 0: offsets --------------------------------------------------------


def test_offsets_are_deterministic_and_bounded(stage0, windows):
    again = phase11.build_offsets(windows, 5.0)
    first = stage0["offsets.json"]["by_window_length"]["5.0"]
    assert json.dumps(first, sort_keys=True) == json.dumps(again, sort_keys=True)
    values = [value for draw in first["draws"] for value in draw["offsets_days"]]
    assert len(first["draws"]) == len(windows)
    assert len(values) == len(windows) * gen.OFFSET_DRAWS
    assert max(values) <= gen.OFFSET_HALF_DAYS + 1e-9
    assert min(values) >= -gen.OFFSET_HALF_DAYS - 1e-9


def test_offsets_do_not_depend_on_roles_or_splits(stage0, windows):
    baseline = phase11.build_offsets(windows, 5.0)
    flipped = copy.deepcopy(windows)
    for index, window in enumerate(flipped):
        window["role"] = "null" if window["role"] == "injection" else "injection"
        window["split"] = ["train", "val", "test"][index % 3]
    assert phase11.build_offsets(flipped, 5.0) == baseline


def test_offsets_are_independent_per_window_length(stage0):
    lengths = stage0["offsets.json"]["by_window_length"]
    first = [draw["offsets_days"][0] for draw in lengths["5.0"]["draws"][:20]]
    second = [draw["offsets_days"][0] for draw in lengths["3.0"]["draws"][:20]]
    assert first != second


# --- stage 0: hashes ---------------------------------------------------------


def test_stage0_hashes_verify_and_tampering_is_detected(tmp_path):
    hashes = phase11.write_stage0(tmp_path, MANIFEST_DIR)
    assert set(hashes) == {"protocol.json", "offsets.json"}
    protocol, digest = phase11.load_frozen_json(tmp_path / "protocol.json")
    assert digest == hashes["protocol.json"]
    assert protocol["seeds"]["model"] == phase11.MODEL_SEED

    tampered = tmp_path / "protocol.json"
    payload = json.loads(tampered.read_text(encoding="utf-8"))
    payload["seeds"]["model"] += 1
    tampered.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(phase11.GateError):
        phase11.load_frozen_json(tampered)


# --- stage 1: trial plan -----------------------------------------------------


def test_plan_trials_fit_group_never_contains_test_rows(windows, protocol):
    plan = phase11.plan_trials(windows, protocol, "fit")
    assert set(plan["split"]) == {"train", "val"}
    test_plan = phase11.plan_trials(windows, protocol, "test")
    assert set(test_plan["split"]) == {"test"}


def test_plan_trials_counts_match_the_projection(windows, protocol):
    fit = phase11.plan_trials(windows, protocol, "fit")
    test = phase11.plan_trials(windows, protocol, "test")
    config = json.loads((MANIFEST_DIR / "experiment_config.json").read_text(encoding="utf-8"))
    assert len(fit) + len(test) == config["projected_cost"]["primary"]["total_detector_trials"]
    # train+val injection windows 66, null windows 67; test 36 / 38
    assert len(fit) == 66 * (5 + 1) * 2 * 2 + 67 * 2 * 2
    assert len(test) == 36 * (5 + 1) * 2 * 2 + 38 * 2 * 2


def test_plan_trials_rejects_unknown_split_group(windows, protocol):
    with pytest.raises(ValueError):
        phase11.plan_trials(windows, protocol, "all")


# --- stage 1: feature and split gates ---------------------------------------


def test_forbidden_ground_truth_features_are_rejected(protocol):
    poisoned = copy.deepcopy(protocol)
    poisoned["features"]["sets"]["L4_flux_full"]["features"].append("delta_true_days")
    with pytest.raises(phase11.GateError):
        phase11.feature_columns(poisoned, "L4_flux_full")


def test_undeclared_features_are_rejected(protocol):
    poisoned = copy.deepcopy(protocol)
    poisoned["features"]["sets"]["L6_flux_clean"]["features"].append("bogus_feature")
    with pytest.raises(phase11.GateError):
        phase11.feature_columns(poisoned, "L6_flux_clean")


def test_feature_sets_are_clean_and_l7_excludes_proxies(protocol):
    l7 = phase11.feature_columns(protocol, "L7_detector_plus_clean_flux")
    assert "min_depth_ppm" not in l7
    assert {"n_points", "gap_fraction"} & set(l7) == set()
    assert {"snr", "depth_est_ppm", "sigma_ppm"} <= set(l7)
    forbidden = set(protocol["features"]["forbidden"])
    for model_id in protocol["features"]["sets"]:
        assert forbidden & set(phase11.feature_columns(protocol, model_id)) == set()


def test_fit_refuses_test_rows(protocol):
    frame = _trial_frame(splits=("train", "val", "test"))
    with pytest.raises(phase11.GateError):
        phase11.fit_models(frame, protocol, "L7_detector_plus_clean_flux", model_factory=StubModel)


# --- stage 1: fitting and threshold provenance -------------------------------


def test_fit_uses_train_only_and_calibrates_on_validation_nulls(protocol):
    frame = _trial_frame()
    stub = StubModel()
    fitted = phase11.fit_models(
        frame, protocol, "L7_detector_plus_clean_flux", model_factory=lambda: stub
    )
    train = frame[frame["split"] == "train"]
    val_nulls = frame[(frame["split"] == "val") & (frame["role"] == "null_window")]
    assert fitted["train_rows"] == len(train)
    assert stub.fit_rows == len(train)
    assert stub.fit_positive == int(train["injected"].sum())
    assert fitted["threshold"]["scope"] == "L7_detector_plus_clean_flux|validation nulls"
    assert fitted["threshold"]["n"] == len(val_nulls)
    assert fitted["threshold"]["floor"] is None


def test_threshold_tie_rule_respects_target_and_records_provenance():
    scores = np.array([1.0, 2.0, 2.0, 2.0, 3.0, 4.0])
    result = phase11.choose_threshold(scores, target_fpr=0.2, scope="unit-test")
    assert result["calibration_exceedance"] <= 0.2
    assert result["scope"] == "unit-test"
    assert result["comparison"] == ">"
    assert result["percentile_method"] == "linear"
    assert result["n"] == len(scores)


def test_threshold_floor_is_recorded_when_it_binds():
    result = phase11.choose_threshold(
        np.array([0.5, 1.0, 1.5]), target_fpr=0.05, scope="unit-test", floor=3.0
    )
    assert result["threshold"] == 3.0
    assert result["floor_applied"] is True


def test_threshold_rejects_non_strict_comparison():
    with pytest.raises(ValueError):
        phase11.choose_threshold(
            np.array([1.0, 2.0]), target_fpr=0.05, scope="unit-test", comparison=">="
        )


def test_detector_calibration_refuses_test_rows(protocol):
    frame = _trial_frame(splits=("train", "val", "test"))
    frame = frame[frame["role"] == "null_window"]
    with pytest.raises(phase11.GateError):
        phase11.calibrate_detector_thresholds(frame, protocol)


# --- stage 1: freeze, evaluate, single read ----------------------------------


def _frozen_setup(tmp_path):
    hashes = phase11.write_stage0(tmp_path, MANIFEST_DIR)
    protocol, protocol_hash = phase11.load_frozen_json(tmp_path / "protocol.json")
    frame = _trial_frame()
    stub = StubModel()
    fitted = phase11.fit_models(
        frame, protocol, "L7_detector_plus_clean_flux", model_factory=lambda: stub
    )
    frozen = phase11.freeze_fitted(
        tmp_path,
        fitted=fitted,
        model=stub,
        trials=frame,
        protocol=protocol,
        protocol_hash=protocol_hash,
    )
    return hashes, protocol, protocol_hash, frame, fitted, frozen


def test_freeze_writes_hash_state_and_model(tmp_path):
    _hashes, _protocol, _hash, _frame, fitted, frozen = _frozen_setup(tmp_path)
    assert (tmp_path / "fitted.json").is_file()
    assert (tmp_path / "fitted.sha256").is_file()
    assert frozen["model.pkl"] == json.loads((tmp_path / "fitted.json").read_text())["model_sha256"]
    state = json.loads((tmp_path / "fitted.json").read_text())
    assert state["features"] == fitted["features"]
    assert state["threshold"]["scope"].endswith("validation nulls")
    loaded = phase11.load_fitted(tmp_path, state["protocol_sha256"])
    assert loaded["model_id"] == fitted["model_id"]


def test_evaluate_requires_frozen_artifacts(tmp_path):
    phase11.write_stage0(tmp_path, MANIFEST_DIR)
    frame = _trial_frame(splits=("test",))
    with pytest.raises(phase11.GateError):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=frame,
            manifest_dir=MANIFEST_DIR,
        )


def test_evaluate_rejects_tampered_fitted_state(tmp_path):
    _hashes, _protocol, _hash, frame, _fitted, _frozen = _frozen_setup(tmp_path)
    path = tmp_path / "fitted.json"
    payload = json.loads(path.read_text())
    payload["threshold"]["threshold"] += 1.0
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(phase11.GateError):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=_trial_frame(splits=("test",)),
            manifest_dir=MANIFEST_DIR,
        )


def test_evaluate_allows_exactly_one_test_read(tmp_path):
    _hashes, _protocol, _hash, _frame, _fitted, _frozen = _frozen_setup(tmp_path)
    test_frame = _trial_frame(splits=("test",), seed=7)
    result = phase11.evaluate_test(
        tmp_path,
        protocol_path=tmp_path / "protocol.json",
        trials=test_frame,
        manifest_dir=MANIFEST_DIR,
    )
    assert result["metrics"]["n"] == len(test_frame)
    assert result["ledger"]["clusters"] == 1
    assert (tmp_path / "test_access.json").is_file()
    with pytest.raises(phase11.GateError):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=_trial_frame(splits=("test",), seed=8),
            manifest_dir=MANIFEST_DIR,
        )


def test_evaluate_refuses_mixed_splits(tmp_path):
    _hashes, _protocol, _hash, _frame, _fitted, _frozen = _frozen_setup(tmp_path)
    with pytest.raises(phase11.GateError):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=_trial_frame(splits=("train", "test")),
            manifest_dir=MANIFEST_DIR,
        )


def test_freeze_is_refused_after_test_access(tmp_path):
    _hashes, protocol, protocol_hash, frame, fitted, _frozen = _frozen_setup(tmp_path)
    phase11.evaluate_test(
        tmp_path,
        protocol_path=tmp_path / "protocol.json",
        trials=_trial_frame(splits=("test",)),
        manifest_dir=MANIFEST_DIR,
    )
    with pytest.raises(phase11.GateError):
        phase11.freeze_fitted(
            tmp_path,
            fitted=fitted,
            model=StubModel(),
            trials=frame,
            protocol=protocol,
            protocol_hash=protocol_hash,
        )


def test_test_generation_requires_frozen_fitted(tmp_path):
    with pytest.raises(phase11.GateError):
        phase11.assert_test_generation_allowed(tmp_path)
    _frozen_setup(tmp_path)
    phase11.assert_test_generation_allowed(tmp_path)


def _write_with_sidecar(path: Path, payload: dict) -> None:
    text = json.dumps(payload, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    digest = phase11.sha256_bytes(text.encode("utf-8"))
    path.with_name(path.name.replace(".json", ".sha256")).write_text(
        f"{digest}  {path.name}\n", encoding="utf-8"
    )


def test_protocol_mismatch_blocks_evaluation(tmp_path):
    _hashes, protocol, _hash, _frame, _fitted, _frozen = _frozen_setup(tmp_path)
    other = copy.deepcopy(protocol)
    other["seeds"]["model"] += 1
    # A correctly hashed but different protocol must still be refused: the fitted
    # state records the protocol hash it was produced under.
    _write_with_sidecar(tmp_path / "other_protocol.json", other)
    with pytest.raises(phase11.GateError):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "other_protocol.json",
            trials=_trial_frame(splits=("test",)),
            manifest_dir=MANIFEST_DIR,
        )


def test_protocol_frozen_against_other_manifests_is_refused(tmp_path):
    _hashes, protocol, _hash, _frame, _fitted, _frozen = _frozen_setup(tmp_path)
    other = copy.deepcopy(protocol)
    other["manifests"]["windows_primary.json"] = "0" * 64
    _write_with_sidecar(tmp_path / "other_manifests.json", other)
    with pytest.raises(phase11.GateError):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "other_manifests.json",
            trials=_trial_frame(splits=("test",)),
            manifest_dir=MANIFEST_DIR,
        )



def test_sidecar_hashes_match_raw_file_bytes(tmp_path):
    """sha256sum semantics: the recorded digest must hash the file as written."""
    hashes = phase11.write_stage0(tmp_path, MANIFEST_DIR)
    for name in ("protocol.json", "offsets.json"):
        raw = (tmp_path / name).read_bytes()
        assert b"\r\n" not in raw, f"{name} was written with CRLF translation"
        digest = phase11.sha256_bytes(raw)
        recorded = (tmp_path / name.replace(".json", ".sha256")).read_text().split()[0]
        assert recorded == digest == hashes[name]


def test_modes_resolve_to_pre_registered_trials():
    smoke = phase11.describe_mode("smoke", MANIFEST_DIR)
    assert smoke["window_days"] == 5.0
    assert smoke["groups"]["fit"]["trials"] == 168
    assert smoke["groups"]["fit"]["splits"] == ["train", "val"]
    assert "test" not in smoke["groups"]
    assert smoke["groups"]["fit"]["quarters"] == ["Q00", "Q01", "Q04"]

    full = phase11.describe_mode("full", MANIFEST_DIR)
    assert full["groups"]["fit"]["trials"] == 1852
    assert full["groups"]["test"]["trials"] == 1016
    assert full["groups"]["test"]["splits"] == ["test"]

    sensitivity = phase11.describe_mode("sensitivity", MANIFEST_DIR)
    assert sensitivity["window_days"] == 3.0
    assert sensitivity["groups"]["fit"]["trials"] == 3084
    assert sensitivity["groups"]["test"]["trials"] == 1756


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        phase11.describe_mode("turbo", MANIFEST_DIR)


# --- stage 2: fail-closed behaviour -----------------------------------------


def _write_raw_with_sidecar(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))
    digest = phase11.sha256_bytes(text.encode("utf-8"))
    path.with_name(path.name.replace(".json", ".sha256")).write_text(
        f"{digest}  {path.name}\n", encoding="utf-8"
    )


def test_corrupted_protocol_json_fails_closed(tmp_path):
    _frozen_setup(tmp_path)
    _write_raw_with_sidecar(tmp_path / "protocol.json", "{not json")
    with pytest.raises(phase11.GateError):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=_trial_frame(splits=("test",)),
            manifest_dir=MANIFEST_DIR,
        )


def test_corrupted_fitted_json_fails_closed(tmp_path):
    _frozen_setup(tmp_path)
    _write_raw_with_sidecar(tmp_path / "fitted.json", '{"broken": ')
    with pytest.raises(phase11.GateError):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=_trial_frame(splits=("test",)),
            manifest_dir=MANIFEST_DIR,
        )


def test_corrupted_model_file_fails_closed(tmp_path):
    _frozen_setup(tmp_path)
    (tmp_path / "model.pkl").write_bytes(b"not-a-pickle")
    with pytest.raises(phase11.GateError):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=_trial_frame(splits=("test",)),
            manifest_dir=MANIFEST_DIR,
        )


def test_ledger_is_written_before_metrics_and_blocks_retry(tmp_path, monkeypatch):
    _frozen_setup(tmp_path)

    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic metrics failure")

    monkeypatch.setattr(phase11, "detection_metrics", boom)
    with pytest.raises(RuntimeError):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=_trial_frame(splits=("test",)),
            manifest_dir=MANIFEST_DIR,
        )
    ledger = json.loads((tmp_path / "test_access.json").read_text())
    assert ledger["status"] == "started"
    monkeypatch.undo()
    with pytest.raises(phase11.GateError):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=_trial_frame(splits=("test",), seed=3),
            manifest_dir=MANIFEST_DIR,
        )


def test_restart_cannot_bypass_the_one_read_policy(tmp_path):
    _frozen_setup(tmp_path)
    phase11.evaluate_test(
        tmp_path,
        protocol_path=tmp_path / "protocol.json",
        trials=_trial_frame(splits=("test",)),
        manifest_dir=MANIFEST_DIR,
    )
    ledger = json.loads((tmp_path / "test_access.json").read_text())
    assert ledger["status"] == "completed"
    # A fresh call is the "restart": the on-disk ledger still blocks it.
    with pytest.raises(phase11.GateError):
        phase11.evaluate_test(
            tmp_path,
            protocol_path=tmp_path / "protocol.json",
            trials=_trial_frame(splits=("test",), seed=4),
            manifest_dir=MANIFEST_DIR,
        )


def test_test_campaign_is_blocked_before_freeze(tmp_path):
    with pytest.raises(phase11.GateError):
        phase11.run_campaign(
            manifest_dir=MANIFEST_DIR,
            out_dir=tmp_path,
            window_days=5.0,
            split_group="test",
        )
