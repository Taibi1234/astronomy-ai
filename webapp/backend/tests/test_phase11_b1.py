"""Phase 11 Stage B1 tests: the synthetic-only guard and the gated fit/calibrate/freeze path.

Synthetic fixtures only. The success path uses a disposable git repository for provenance so a
clean tracked tree is genuine; the real repository is read only through the frozen manifests and
is never written. No campaign, no real trial, no sealed data, no scoring of scientific rows.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import (  # noqa: E402, I001
    generalization as gen,
    phase11,
    phase11_b1 as b1,
    phase11_b2a as b2a,
    phase11_runner as runner,
    phase11_v2 as v2,
    safeguards,
    test_access,
)

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"
REPO_ROOT = gen.project_root()
FROZEN_NAMES = (
    "protocol_v2_3.json",
    "protocol_v2_3.sha256",
    "protocol.json",
    "protocol.sha256",
    "experiment_config.json",
)
SPLIT_MAP = {"Q00": "train", "Q04": "val"}
# 34 windows per quarter with one injected depth gives 34 validation nulls per noise stratum,
# which clears the frozen min_calibration_n_per_stratum = 30 without relaxing it.
CALIBRATION_GEOMETRY = {"windows_per_quarter": 34, "depths_ppm": (300.0,)}


@pytest.fixture(scope="module")
def effective() -> dict:
    missing = [name for name in FROZEN_NAMES if not (MANIFEST_DIR / name).is_file()]
    if missing:
        pytest.skip(f"frozen triple unavailable: {missing}")
    resolved, _ = v2.resolve_effective_protocol(MANIFEST_DIR)
    return resolved


@pytest.fixture(scope="module")
def small_frame(effective) -> object:
    return b2a.build_fit_split_frame(
        effective=effective, split_map=SPLIT_MAP, seed=20261022, depths_ppm=(150.0, 300.0)
    )


@pytest.fixture(scope="module")
def calibration_frame(effective) -> object:
    """34 validation nulls per stratum, clearing the frozen minimum of 30."""
    return b2a.build_fit_split_frame(
        effective=effective, split_map=SPLIT_MAP, seed=20261022, **CALIBRATION_GEOMETRY
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def clean_repo(tmp_path) -> Path:
    """Disposable git repository with one committed source file: a genuinely clean tree."""
    repo = tmp_path / "fixture_repo"
    repo.mkdir()
    (repo / "source.py").write_text("# synthetic fixture source\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(
        repo,
        "-c",
        "user.email=b1@example.invalid",
        "-c",
        "user.name=B1 Fixture",
        "add",
        "source.py",
    )
    _git(
        repo,
        "-c",
        "user.email=b1@example.invalid",
        "-c",
        "user.name=B1 Fixture",
        "commit",
        "-q",
        "-m",
        "fixture",
    )
    return repo


def _provenance(repo: Path) -> dict:
    protocol, _digest = v2.load_protocol_v21(MANIFEST_DIR / v2.AUTHORIZED_PROTOCOL_NAME)
    manifest_hashes = v2.validate_manifests(MANIFEST_DIR, protocol)
    _offsets, offsets_hash = v2.load_frozen_offsets(MANIFEST_DIR, protocol)
    return v2.capture_provenance(
        repo,
        source_paths=[repo / "source.py"],
        protocol_sha256=v2.AUTHORIZED_PROTOCOL_SHA256,
        manifest_hashes=manifest_hashes,
        offsets_sha256=offsets_hash,
    )


# --- approved mode -----------------------------------------------------------


def test_approved_mode_is_synthetic_only():
    assert b1.APPROVED_MODES == ("synthetic",)
    assert b1.assert_approved_mode("synthetic") == "synthetic"


@pytest.mark.parametrize("mode", ["real", "campaign", "test", "full", "", None, 3])
def test_other_modes_are_refused_before_any_side_effect(
    effective, small_frame, tmp_path, monkeypatch, mode
):
    calls = []
    monkeypatch.setattr(phase11, "fit_models", lambda *a, **k: calls.append(a))
    out_dir = tmp_path / "mode_refused"

    with pytest.raises(phase11.GateError, match="not approved for B1"):
        b1.fit_synthetic(
            effective=effective,
            frame=small_frame,
            out_dir=out_dir,
            provenance={"protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256},
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            mode=mode,
            model_id="L7_detector_plus_clean_flux",
        )

    assert calls == []
    assert not out_dir.exists()


# --- input boundaries --------------------------------------------------------


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda frame: frame.assign(source="kepler-quarter-csv"), "synthetic fixtures only"),
        (lambda frame: frame.assign(source="phase10-campaign"), "synthetic fixtures only"),
        (lambda frame: frame.assign(split="test"), "must never see test-split rows"),
        (lambda frame: frame.assign(role="calibration"), "unexpected roles"),
        (
            lambda frame: frame.assign(injected=~frame["injected"].astype(bool)),
            "label invariant",
        ),
        (lambda frame: frame.assign(trial_id=frame["trial_id"].iloc[0]), "duplicate trial_id"),
        (lambda frame: frame.drop(columns=["snr"]), "missing the model feature columns"),
        (lambda frame: frame.drop(columns=["source"]), "missing required columns"),
        (lambda frame: frame.iloc[0:0], "is empty"),
    ],
)
def test_forbidden_frames_are_refused_before_fitting(
    effective, small_frame, tmp_path, monkeypatch, mutation, message
):
    calls = []
    monkeypatch.setattr(phase11, "fit_models", lambda *a, **k: calls.append(a))
    out_dir = tmp_path / "frame_refused"

    with pytest.raises(phase11.GateError, match=message):
        b1.fit_synthetic(
            effective=effective,
            frame=mutation(small_frame),
            out_dir=out_dir,
            provenance={"protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256},
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            model_id="L7_detector_plus_clean_flux",
        )

    assert calls == []
    assert not out_dir.exists()


def test_validation_split_without_nulls_is_refused(effective, small_frame, monkeypatch):
    without_val_nulls = small_frame[
        ~((small_frame["split"] == "val") & (small_frame["role"] == b1.ROLE_NULL))
    ]
    calls = []
    monkeypatch.setattr(phase11, "fit_models", lambda *a, **k: calls.append(a))

    with pytest.raises(phase11.GateError, match="validation nulls are required"):
        b1.assert_synthetic_frame(
            without_val_nulls, effective, model_id="L7_detector_plus_clean_flux"
        )
    assert calls == []


def test_non_dataframe_input_is_refused(effective):
    with pytest.raises(phase11.GateError, match="pandas DataFrame"):
        b1.assert_synthetic_frame([{"split": "train"}], effective)


def test_test_quarter_is_refused_before_row_construction(effective, monkeypatch):
    calls = []
    monkeypatch.setattr(b1, "build_fit_split_frame", lambda **kwargs: calls.append(kwargs))

    with pytest.raises(phase11.GateError, match="before row construction"):
        b1.build_frame_for_fit(
            effective=effective, split_map={"Q00": "train", "Q02": "test"}, seed=1
        )
    assert calls == []

    with pytest.raises(phase11.GateError, match="unsupported split"):
        b1.build_frame_for_fit(effective=effective, split_map={"Q00": "holdout"}, seed=1)
    assert calls == []


def test_approved_split_map_builds_rows(effective):
    frame = b1.build_frame_for_fit(effective=effective, split_map=SPLIT_MAP, seed=7)

    assert set(frame["split"].unique()) == {"train", "val"}
    assert set(frame["source"].unique()) == {b1.SYNTHETIC_SOURCE}


# --- protocol identity and output isolation ---------------------------------


def test_unapproved_protocol_hash_is_refused(effective, small_frame, tmp_path):
    with pytest.raises(phase11.GateError, match="not the authorized v2.3 pin"):
        b1.fit_synthetic(
            effective=effective,
            frame=small_frame,
            out_dir=tmp_path / "bad_hash",
            provenance={"protocol_sha256": "0" * 64},
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
        )
    assert not (tmp_path / "bad_hash").exists()


def test_unapproved_protocol_version_is_refused(effective, small_frame, tmp_path):
    tampered = dict(effective, version="phase11b-protocol-v9")
    with pytest.raises(phase11.GateError, match="not the authorized"):
        b1.fit_synthetic(
            effective=tampered,
            frame=small_frame,
            out_dir=tmp_path / "bad_version",
            provenance={"protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256},
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
        )
    assert not (tmp_path / "bad_version").exists()


def test_protected_output_destination_is_refused(effective, small_frame):
    before = sorted(path.name for path in MANIFEST_DIR.iterdir())

    with pytest.raises(runner.OutputIsolationError):
        b1.fit_synthetic(
            effective=effective,
            frame=small_frame,
            out_dir=MANIFEST_DIR,
            provenance={"protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256},
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
        )

    assert sorted(path.name for path in MANIFEST_DIR.iterdir()) == before
    assert not (MANIFEST_DIR / "fitted.json").exists()


# --- provenance --------------------------------------------------------------


def test_dirty_tree_aborts_before_writing(effective, tmp_path, clean_repo):
    provenance = _provenance(clean_repo)
    provenance["git"]["dirty"] = True
    provenance["git"]["dirty_paths"] = [" M research/phase11.py"]
    out_dir = tmp_path / "dirty_refused"

    with pytest.raises(phase11.GateError, match="clean tracked tree"):
        b1.fit_synthetic(
            effective=effective,
            frame=b2a.build_fit_split_frame(
                effective=effective, split_map=SPLIT_MAP, seed=3, depths_ppm=(300.0,)
            ),
            out_dir=out_dir,
            provenance=provenance,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
        )

    assert not out_dir.exists()


def test_missing_source_aborts_capture(clean_repo):
    with pytest.raises(phase11.GateError, match="does not exist"):
        v2.capture_provenance(
            clean_repo,
            source_paths=[clean_repo / "absent_source.py"],
            protocol_sha256=v2.AUTHORIZED_PROTOCOL_SHA256,
            manifest_hashes={},
            offsets_sha256="0" * 64,
        )


# --- round trip --------------------------------------------------------------


def test_synthetic_round_trip_fit_calibrate_freeze_load(
    effective, calibration_frame, tmp_path, clean_repo
):
    provenance = _provenance(clean_repo)
    frame = calibration_frame
    out_dir = tmp_path / "round_trip"

    result = b1.fit_synthetic(
        effective=effective,
        frame=frame,
        out_dir=out_dir,
        provenance=provenance,
        manifest_dir=MANIFEST_DIR,
        repo_root=REPO_ROOT,
        model_id="L7_detector_plus_clean_flux",
    )

    assert result["mode"] == "synthetic"
    assert result["payload_keys"] == list(b1.FITTED_PAYLOAD_KEYS)
    assert set(result["thresholds"]) == set(effective["injection"]["noise_conditions"])
    assert set(path.name for path in out_dir.iterdir()) == {
        "fitted.json",
        "fitted.sha256",
        "model.pkl",
    }

    reloaded = v2.load_fitted_v21(out_dir, v2.AUTHORIZED_PROTOCOL_SHA256)
    assert reloaded["protocol_sha256"] == v2.AUTHORIZED_PROTOCOL_SHA256
    assert reloaded["provenance"] == provenance
    assert reloaded["model_id"] == "L7_detector_plus_clean_flux"
    assert set(reloaded["thresholds"]) == set(effective["injection"]["noise_conditions"])
    assert set(reloaded["detector_thresholds"]) == set(effective["injection"]["noise_conditions"])
    for entry in reloaded["detector_thresholds"].values():
        assert entry["n"] > 0
        assert entry["threshold"] >= float(effective["thresholds"]["floor_snr_detector"])
    for key in ("train_rows", "val_rows", "train_injected"):
        assert reloaded["counts"][key] > 0


def test_round_trip_creates_no_campaign_markers(effective, calibration_frame, tmp_path, clean_repo):
    provenance = _provenance(clean_repo)
    frame = calibration_frame
    out_dir = tmp_path / "no_markers"

    b1.fit_synthetic(
        effective=effective,
        frame=frame,
        out_dir=out_dir,
        provenance=provenance,
        manifest_dir=MANIFEST_DIR,
        repo_root=REPO_ROOT,
        model_id="L7_detector_plus_clean_flux",
    )

    present = {path.name for path in out_dir.iterdir()}
    assert not present & {"test_generation.json", "test_access.json", "metrics_test.json"}
    assert present <= safeguards.CAMPAIGN_STATE_NAMES


def test_marked_directory_is_refused_before_fitting(effective, small_frame, tmp_path, monkeypatch):
    out_dir = tmp_path / "marked"
    out_dir.mkdir()
    test_access.begin_marker(out_dir, test_access.MARKER_ACCESS, {"trial_id": "synthetic"})
    calls = []
    monkeypatch.setattr(phase11, "fit_models", lambda *args, **kwargs: calls.append(args))

    with pytest.raises(runner.OutputIsolationError, match="campaign state"):
        b1.fit_synthetic(
            effective=effective,
            frame=small_frame,
            out_dir=out_dir,
            provenance={"protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256},
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
        )

    assert calls == []


# --- execution-safety regressions -------------------------------------------


def test_execution_safety_is_unchanged():
    assert runner.MODES == ("preflight", "synthetic")
    with pytest.raises(runner.ReadinessError):
        runner.execute_real()


def test_b1_module_has_no_real_execution_entry_point():
    public = {name for name in vars(b1) if not name.startswith("_")}

    assert "execute_real" not in public
    assert not any("campaign" in name.lower() for name in public)
    assert not any("evaluate" in name.lower() for name in public)


def test_scores_are_probabilities_for_validation_nulls(effective):
    frame = b2a.build_fit_split_frame(
        effective=effective, split_map=SPLIT_MAP, seed=2, depths_ppm=(300.0,)
    )
    fitted = phase11.fit_models(frame, dict(effective), "L7_detector_plus_clean_flux")

    calibration = b1._calibration_scores(frame, fitted)

    assert set(calibration["split"].unique()) == {"val"}
    assert set(calibration["role"].unique()) == {b1.ROLE_NULL}
    scores = calibration[b1.SCORE_COLUMN].to_numpy(dtype=float)
    assert np.isfinite(scores).all()
    assert ((scores >= 0.0) & (scores <= 1.0)).all()
