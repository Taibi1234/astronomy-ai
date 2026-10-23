"""Phase 11 Stage B7 tests: the guarded real-data `fit_real` entry point.

Synthetic fixtures only. The real manifests supply the quarter identities and the authorization
contract; the frame used end to end is generated from synthetic arrays and re-tagged, so no real
quarter is read, no model is fitted on scientific data and no test artifact is touched.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import (  # noqa: E402, I001
    generalization as gen,
    phase11,
    phase11_b1 as b1,
    phase11_b2a as b2a,
    phase11_b7 as b7,
    phase11_runner as runner,
    phase11_v2 as v2,
)
from research import phase11_authz as authz  # noqa: E402

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"
REPO_ROOT = gen.project_root()
FROZEN_NAMES = (
    "protocol_v2_3.json",
    "protocol_v2_3.sha256",
    "protocol.json",
    "protocol.sha256",
    "experiment_config.json",
)
CALIBRATION_GEOMETRY = {"windows_per_quarter": 34, "depths_ppm": (300.0,)}
TEST_QUARTERS = {"Q02", "Q09", "Q13", "Q14", "Q17"}


def _effective_or_skip() -> dict:
    missing = [name for name in FROZEN_NAMES if not (MANIFEST_DIR / name).is_file()]
    if missing:
        pytest.skip(f"frozen triple unavailable: {missing}")
    resolved, _ = v2.resolve_effective_protocol(MANIFEST_DIR)
    return resolved


@pytest.fixture(scope="module")
def effective() -> dict:
    missing = [name for name in FROZEN_NAMES if not (MANIFEST_DIR / name).is_file()]
    if missing:
        pytest.skip(f"frozen triple unavailable: {missing}")
    resolved, _ = v2.resolve_effective_protocol(MANIFEST_DIR)
    return resolved


@pytest.fixture(scope="module")
def quarters(effective) -> tuple[set[str], set[str]]:
    return b7.protocol_fit_quarters(MANIFEST_DIR, effective)


def _write_doc(
    tmp_path: Path,
    *,
    fit: set[str],
    test: set[str],
    scope: str = "fit_only",
    campaign_id: str = "synthetic-fixture-b7",
    overrides: dict | None = None,
) -> b7.authz.AuthorizationRef:
    protocol, _digest = v2.load_protocol_v21(MANIFEST_DIR / v2.AUTHORIZED_PROTOCOL_NAME)
    doc = {
        "campaign_id": campaign_id,
        "approver": "test-owner",
        "operator": "test-operator",
        "issued_at": "2026-10-22T00:00:00Z",
        "scope": scope,
        "authorized_quarters": sorted(fit),
        "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256,
        "manifest_hashes": v2.validate_manifests(MANIFEST_DIR, protocol),
        "single_run_ack": True,
    }
    if scope == "fit_and_evaluate":
        doc["authorized_test_quarters"] = sorted(test)
    doc.update(overrides or {})
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return authz.AuthorizationRef(path=path, sha256=v2.sha256_file(path), campaign_id=campaign_id)


@pytest.fixture
def authorization(tmp_path, quarters) -> b7.authz.AuthorizationRef:
    fit, test = quarters
    return _write_doc(tmp_path, fit=fit, test=test)


@pytest.fixture
def provenance() -> dict:
    return {
        "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256,
        "git": {"commit": "0" * 40, "branch": "main", "dirty": False, "dirty_paths": []},
    }


@pytest.fixture(scope="module")
def real_fit_frame(effective) -> pd.DataFrame:
    """Synthetic rows re-tagged as the real fit contract, on designated fit quarters."""
    frame = b2a.build_fit_split_frame(
        effective=effective,
        split_map={"Q00": "train", "Q04": "val"},
        seed=20261022,
        **CALIBRATION_GEOMETRY,
    )
    return frame.assign(
        source=b7.REAL_FIT_SOURCE,
        delta_true_days=0.0,
        delta_est_days=0.0,
    )


def _fit(effective, tmp_path, provenance, authorization, frame, monkeypatch, **overrides):
    monkeypatch.setattr(b7, "build_fit_frame", lambda **kwargs: frame)
    monkeypatch.setattr(v2, "capture_provenance", lambda *args, **kwargs: provenance)
    arguments = {
        "effective": effective,
        "manifest_dir": MANIFEST_DIR,
        "repo_root": REPO_ROOT,
        "out_dir": tmp_path / "fit",
        "authorization": authorization,
        "model_id": "L7_detector_plus_clean_flux",
    }
    arguments.update(overrides)
    return b7.fit_real(**arguments)


# --- protocol-designated quarters -------------------------------------------


def test_fit_quarters_are_the_designated_ten(quarters):
    fit, test = quarters

    assert len(fit) == 10
    assert test == TEST_QUARTERS
    assert not fit & test
    assert {"Q00", "Q04"} <= fit


def test_plain_dictionary_is_refused(effective, tmp_path):
    def check():
        b7.fit_real(
            effective=effective,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            out_dir=tmp_path / "x",
            authorization={"campaign_id": "plain"},
        )

    with pytest.raises(phase11.GateError, match="AuthorizationRef"):
        check()


def test_missing_document_is_refused(quarters, tmp_path, provenance, real_fit_frame, monkeypatch):
    fit, test = quarters
    ref = _write_doc(tmp_path, fit=fit, test=test)
    ref = authz.AuthorizationRef(
        path=tmp_path / "absent.json", sha256=ref.sha256, campaign_id=ref.campaign_id
    )
    calls = []
    monkeypatch.setattr(phase11, "fit_models", lambda *args, **kwargs: calls.append(args))

    with pytest.raises(phase11.GateError, match="missing"):
        _fit(
            effective=_effective_or_skip(),
            tmp_path=tmp_path,
            provenance=provenance,
            authorization=ref,
            frame=real_fit_frame,
            monkeypatch=monkeypatch,
        )

    assert calls == []


def test_fit_windows_exclude_test_windows_and_refuse_inconsistency(quarters):
    fit, test = quarters
    windows = b7.fit_windows(MANIFEST_DIR, _effective_or_skip(), fit, test)
    quarters_used = {str(window["quarter"]) for window in windows}

    assert len(windows) == 133
    assert quarters_used <= fit
    assert not quarters_used & test
    assert all(window["split"] in ("train", "val") for window in windows)

    window = {"quarter": "Q00", "split": "train", "role": "null", "start_index": 0, "end_index": 10}
    b7._validate_fit_window(window, fit, test)
    with pytest.raises(phase11.GateError, match="test quarter; refusing before any read"):
        b7._validate_fit_window({**window, "quarter": "Q02"}, fit, test)
    with pytest.raises(phase11.GateError, match="test quarter but declares split"):
        b7._classify_window({**window, "quarter": "Q02"}, fit, test)
    with pytest.raises(phase11.GateError, match="not a frozen fit quarter"):
        b7._classify_window({**window, "quarter": "Q99"}, fit, test)
    with pytest.raises(phase11.GateError, match="has split"):
        b7._classify_window({**window, "split": "holdout"}, fit, test)
    with pytest.raises(phase11.GateError, match="invalid slice"):
        b7._validate_fit_window({**window, "end_index": 0}, fit, test)


def test_plan_guard_refuses_test_and_foreign_rows(quarters):
    fit, test = quarters
    plan = pd.DataFrame(
        {
            "trial_id": ["a", "b"],
            "quarter": ["Q00", "Q04"],
            "split": ["train", "val"],
            "role": ["null_window", "injection"],
        }
    )
    b7.assert_plan_fit_only(plan, fit, test)

    with pytest.raises(phase11.GateError, match="contains test rows"):
        b7.assert_plan_fit_only(plan.assign(split=["train", "test"]), fit, test)
    with pytest.raises(phase11.GateError, match="test quarters"):
        b7.assert_plan_fit_only(plan.assign(quarter=["Q02", "Q04"]), fit, test)
    with pytest.raises(phase11.GateError, match="non-fit quarters"):
        b7.assert_plan_fit_only(plan.assign(quarter=["Q99", "Q04"]), fit, test)
    with pytest.raises(phase11.GateError, match="duplicate trial ids"):
        b7.assert_plan_fit_only(plan.assign(trial_id=["a", "a"]), fit, test)


def test_load_fit_series_refuses_test_quarters(quarters):
    fit, _test = quarters

    with pytest.raises(phase11.GateError, match="not a frozen fit quarter"):
        b7.load_fit_series("Q02", REPO_ROOT, fit)
    with pytest.raises(phase11.GateError, match="invalid quarter identifier"):
        b7.load_fit_series("../Q00", REPO_ROOT, fit)


# --- frame guard -------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda frame: frame.assign(split="test"), "contains test rows"),
        (lambda frame: frame.assign(quarter="Q02"), "non-fit quarters"),
        (lambda frame: frame.assign(source="synthetic-fixture"), "tag only"),
        (lambda frame: frame.assign(source="real-campaign-v2"), "tag only"),
        (
            lambda frame: frame.assign(injected=~frame["injected"].astype(bool)),
            "label invariant",
        ),
        (lambda frame: frame.drop(columns=["snr"]), "missing required columns"),
        (lambda frame: frame.iloc[0:0], "is empty"),
        (
            lambda frame: frame[~(frame["split"] == "val")],
            "validation nulls are required",
        ),
        (lambda frame: frame.assign(trial_id=frame["trial_id"].iloc[0]), "duplicate trial ids"),
    ],
)
def test_fit_frame_guard(effective, quarters, real_fit_frame, mutate, message):
    fit, _test = quarters

    with pytest.raises(phase11.GateError, match=message):
        b7.assert_fit_frame(mutate(real_fit_frame.copy()), effective, fit)


def test_synthetic_guard_still_refuses_real_frames(effective, real_fit_frame):
    with pytest.raises(phase11.GateError, match="synthetic fixtures only"):
        b1.assert_synthetic_frame(real_fit_frame, effective, model_id="L7_detector_plus_clean_flux")


# --- fit_real gates ----------------------------------------------------------


@pytest.mark.parametrize("artifact", ["trials_test.csv", "test_access.json", "metrics_test.json"])
def test_fit_real_refuses_test_artifacts_in_the_output(
    effective, tmp_path, provenance, authorization, real_fit_frame, monkeypatch, artifact
):
    calls = []
    monkeypatch.setattr(phase11, "fit_models", lambda *args, **kwargs: calls.append(args))
    out_dir = tmp_path / "contaminated"
    out_dir.mkdir()
    (out_dir / artifact).write_text("x", encoding="utf-8")

    with pytest.raises(phase11.GateError, match="sealed test artifacts"):
        _fit(
            effective,
            tmp_path,
            provenance,
            authorization,
            real_fit_frame,
            monkeypatch,
            out_dir=out_dir,
        )

    assert calls == []


def test_fit_real_refuses_a_test_artifact_in_the_parent(
    effective, tmp_path, provenance, authorization, real_fit_frame, monkeypatch
):
    monkeypatch.setattr(phase11, "fit_models", lambda *args, **kwargs: None)
    parent = tmp_path / "campaign"
    parent.mkdir()
    (parent / "trials_test.csv").write_text("x", encoding="utf-8")

    with pytest.raises(phase11.GateError, match="sealed test artifacts"):
        _fit(
            effective,
            tmp_path,
            provenance,
            authorization,
            real_fit_frame,
            monkeypatch,
            out_dir=parent / "fit",
        )


def test_fit_real_refuses_a_dirty_tree(
    effective, tmp_path, provenance, authorization, real_fit_frame, monkeypatch
):
    calls = []
    monkeypatch.setattr(phase11, "fit_models", lambda *args, **kwargs: calls.append(args))
    provenance["git"] = {"dirty": True, "dirty_paths": [" M research/phase11.py"]}

    with pytest.raises(phase11.GateError, match="clean tracked tree"):
        _fit(effective, tmp_path, provenance, authorization, real_fit_frame, monkeypatch)

    assert calls == []


def test_fit_real_refuses_a_protected_output(
    effective, provenance, authorization, real_fit_frame, monkeypatch
):
    monkeypatch.setattr(phase11, "fit_models", lambda *args, **kwargs: None)

    with pytest.raises(runner.OutputIsolationError):
        b7.fit_real(
            effective=effective,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            out_dir=MANIFEST_DIR,
            authorization=authorization,
            model_id="L7_detector_plus_clean_flux",
        )


def test_fit_real_refuses_a_contaminated_builder(
    effective, tmp_path, provenance, authorization, real_fit_frame, monkeypatch
):
    contaminated = real_fit_frame.copy()
    contaminated.loc[0, "split"] = "test"

    with pytest.raises(phase11.GateError, match="contains test rows"):
        _fit(effective, tmp_path, provenance, authorization, contaminated, monkeypatch)


# --- quarter integrity and path containment ----------------------------------


def _write_quarter(root: Path, quarter: str = "Q00", rows: int = 3) -> tuple[Path, str]:
    processed = root / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    path = processed / f"kepler_{quarter.lower()}_quality_masked.csv"
    lines = ["time,normalized_flux"] + [f"{index * 0.02:.2f},1.0000" for index in range(rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, v2.sha256_file(path)


def _symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform dependent
        pytest.skip(f"symlinks unavailable: {exc}")


def test_pinned_quarter_loads_when_hash_and_rows_match(quarters, tmp_path):
    fit, _test = quarters
    path, digest = _write_quarter(tmp_path, rows=3)

    times, flux = b7.load_fit_series(
        "Q00", tmp_path, fit, integrity={"Q00": {"sha256": digest, "rows": 3}}
    )

    assert times.size == 3 and flux.size == 3
    assert path.is_file()


def test_tampered_quarter_is_refused(quarters, tmp_path):
    fit, _test = quarters
    path, digest = _write_quarter(tmp_path, rows=3)
    integrity = {"Q00": {"sha256": digest, "rows": 3}}
    path.write_text(path.read_text(encoding="utf-8") + "5.00,1.0000\n", encoding="utf-8")

    with pytest.raises(phase11.GateError, match="does not match the frozen split manifest"):
        b7.load_fit_series("Q00", tmp_path, fit, integrity=integrity)


def test_incorrect_pinned_hash_is_refused(quarters, tmp_path):
    fit, _test = quarters
    _write_quarter(tmp_path, rows=3)

    with pytest.raises(phase11.GateError, match="does not match the frozen split manifest"):
        b7.load_fit_series("Q00", tmp_path, fit, integrity={"Q00": {"sha256": "0" * 64, "rows": 3}})


def test_row_count_mismatch_is_refused(quarters, tmp_path):
    fit, _test = quarters
    _path, digest = _write_quarter(tmp_path, rows=3)

    with pytest.raises(phase11.GateError, match="pins 4"):
        b7.load_fit_series("Q00", tmp_path, fit, integrity={"Q00": {"sha256": digest, "rows": 4}})


@pytest.mark.parametrize(
    "meta, message",
    [
        (None, "is not a mapping"),
        ({}, "no valid sha256 digest"),
        ({"sha256": "abc"}, "no valid sha256 digest"),
        ({"sha256": "g" * 64}, "no valid sha256 digest"),
        ({"sha256": "a" * 64, "rows": "3"}, "invalid row count"),
        ({"sha256": "a" * 64, "rows": 0}, "invalid row count"),
        ({"sha256": "a" * 64, "rows": True}, "invalid row count"),
    ],
)
def test_integrity_metadata_is_validated(meta, message):
    with pytest.raises(phase11.GateError, match=message):
        b7._integrity_entry("Q00", meta)


def test_missing_integrity_metadata_is_refused(quarters, tmp_path):
    fit, _test = quarters
    _write_quarter(tmp_path, rows=3)

    with pytest.raises(phase11.GateError, match="requires pinned integrity metadata"):
        b7.load_fit_series("Q00", tmp_path, fit)
    with pytest.raises(phase11.GateError, match="no pinned integrity metadata"):
        b7.load_fit_series("Q00", tmp_path, fit, integrity={"Q04": {"sha256": "a" * 64}})


def test_symlinked_quarter_file_is_refused(quarters, tmp_path):
    fit, _test = quarters
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    target = processed / "kepler_q00_source.csv"
    target.write_text("time,normalized_flux\n0.00,1.0\n", encoding="utf-8")
    digest = v2.sha256_file(target)
    _symlink(processed / "kepler_q00_quality_masked.csv", target)

    with pytest.raises(phase11.GateError, match="refusing to follow the symlinked quarter file"):
        b7.load_fit_series("Q00", tmp_path, fit, integrity={"Q00": {"sha256": digest, "rows": 1}})


def test_symlinked_data_root_escape_is_refused(quarters, tmp_path):
    fit, _test = quarters
    external = tmp_path.parent / f"{tmp_path.name}_external"
    external.mkdir(exist_ok=True)
    (external / "kepler_q00_quality_masked.csv").write_text(
        "time,normalized_flux\n0.00,1.0\n", encoding="utf-8"
    )
    data = tmp_path / "Data"
    data.mkdir()
    _symlink(data / "processed", external, directory=True)

    with pytest.raises(phase11.GateError, match="escapes the permitted repository root"):
        b7.load_fit_series("Q00", tmp_path, fit, integrity={"Q00": {"sha256": "a" * 64, "rows": 1}})


def test_output_exposure_is_detected_through_a_symlink(tmp_path):
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    (campaign / "trials_test.csv").write_text("x", encoding="utf-8")
    link = tmp_path / "out"
    _symlink(link, campaign, directory=True)

    with pytest.raises(phase11.GateError, match="sealed test artifacts"):
        b7._assert_no_test_exposure(link)


def test_output_file_is_refused_before_fitting(tmp_path):
    not_a_directory = tmp_path / "out"
    not_a_directory.write_text("x", encoding="utf-8")

    with pytest.raises(runner.OutputIsolationError, match="not a directory"):
        b7._assert_no_test_exposure(not_a_directory)


def test_real_fit_quarter_integrity_matches_the_frozen_manifest(effective, quarters):
    fit, _test = quarters
    processed = REPO_ROOT / "data" / "processed"
    if not (processed / "kepler_q00_quality_masked.csv").is_file():
        pytest.skip("real fit quarter file unavailable")
    integrity = b7.quarter_integrity(MANIFEST_DIR, effective, fit)

    assert set(integrity) == fit
    for entry in integrity.values():
        assert len(entry["sha256"]) == 64
        assert entry["rows"] > 0
    times, _flux = b7.load_fit_series("Q00", REPO_ROOT, fit, integrity=integrity)
    assert times.size > 0


# --- H1: provenance is captured, never trusted ---------------------------------


def test_fit_real_has_no_provenance_parameter():
    parameters = inspect.signature(b7.fit_real).parameters

    assert "provenance" not in parameters
    with pytest.raises(TypeError):
        b7.fit_real(
            effective={},
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            out_dir=Path("unused"),
            authorization=None,
            provenance={"git": {"dirty": False}},
        )


def test_capture_provenance_uses_the_verified_frozen_hashes(effective, monkeypatch):
    seen = {}

    def fake_capture(repo_root, **kwargs):
        seen["repo_root"] = repo_root
        seen.update(kwargs)
        return {"protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256, "git": {"dirty": False}}

    monkeypatch.setattr(v2, "capture_provenance", fake_capture)
    provenance = b7.capture_fit_provenance(MANIFEST_DIR, effective, REPO_ROOT)

    assert provenance["git"]["dirty"] is False
    assert seen["protocol_sha256"] == v2.AUTHORIZED_PROTOCOL_SHA256
    assert seen["manifest_hashes"] == v2.validate_manifests(MANIFEST_DIR, effective)
    assert len(seen["offsets_sha256"]) == 64
    names = {path.name for path in seen["source_paths"]}
    assert {"phase11_b7.py", "phase11_b1.py", "phase11_authz.py"} <= names


def test_dirty_captured_provenance_is_refused(
    effective, tmp_path, authorization, real_fit_frame, monkeypatch
):
    calls = []
    monkeypatch.setattr(phase11, "fit_models", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(
        v2,
        "capture_provenance",
        lambda *args, **kwargs: {
            "protocol_sha256": v2.AUTHORIZED_PROTOCOL_SHA256,
            "git": {"dirty": True, "dirty_paths": [" M research/phase11.py"]},
        },
    )

    with pytest.raises(phase11.GateError, match="clean tracked tree"):
        b7.fit_real(
            effective=effective,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            out_dir=tmp_path / "fit",
            authorization=authorization,
            model_id="L7_detector_plus_clean_flux",
        )

    assert calls == []
    assert not (tmp_path / "fit").exists()


# --- fitting, freeze, determinism -------------------------------------------


def test_fit_real_freezes_the_nine_key_contract(
    effective, tmp_path, provenance, authorization, real_fit_frame, monkeypatch
):
    result = _fit(effective, tmp_path, provenance, authorization, real_fit_frame, monkeypatch)

    assert result["mode"] == "real_fit"
    assert result["fit_quarters"] == sorted(b7.protocol_fit_quarters(MANIFEST_DIR, effective)[0])
    out_dir = Path(result["out_dir"])
    assert {path.name for path in out_dir.iterdir()} == {
        "fitted.json",
        "fitted.sha256",
        "model.pkl",
    }
    reloaded = v2.load_fitted_v21(out_dir, v2.AUTHORIZED_PROTOCOL_SHA256)
    for key in (
        "model_id",
        "features",
        "dropped_features",
        "imputation_medians",
        "thresholds",
        "detector_thresholds",
    ):
        assert key in reloaded, key
    for key in ("train_rows", "val_rows", "train_injected"):
        assert reloaded["counts"][key] > 0, key
    assert set(reloaded["detector_thresholds"]) == {"observed", "amplified_x2"}
    assert reloaded["provenance"] == {**provenance, "authorization": result["authorization"]}
    assert set(result["calibration_nulls"]["l7"]) == {"observed", "amplified_x2"}
    assert result["fitted_sha256"] == reloaded["_sha256"]


def test_fit_real_creates_no_markers_or_trials(
    effective, tmp_path, provenance, authorization, real_fit_frame, monkeypatch
):
    result = _fit(effective, tmp_path, provenance, authorization, real_fit_frame, monkeypatch)
    produced = {path.name for path in Path(result["out_dir"]).iterdir()}

    assert not produced & {"test_generation.json", "test_access.json", "metrics_test.json"}
    assert not produced & {"trials_test.csv", "trials_fit.csv"}


def test_fit_real_is_deterministic(
    effective, tmp_path, provenance, authorization, real_fit_frame, monkeypatch
):
    first = _fit(
        effective,
        tmp_path,
        provenance,
        authorization,
        real_fit_frame,
        monkeypatch,
        out_dir=tmp_path / "a",
    )
    second = _fit(
        effective,
        tmp_path,
        provenance,
        authorization,
        real_fit_frame,
        monkeypatch,
        out_dir=tmp_path / "b",
    )

    assert first["thresholds"] == second["thresholds"]
    assert (Path(first["out_dir"]) / "model.pkl").read_bytes() == (
        Path(second["out_dir"]) / "model.pkl"
    ).read_bytes()


def test_fit_real_artifact_is_tamper_evident(
    effective, tmp_path, provenance, authorization, real_fit_frame, monkeypatch
):
    result = _fit(effective, tmp_path, provenance, authorization, real_fit_frame, monkeypatch)
    model = Path(result["out_dir"]) / "model.pkl"
    model.write_bytes(model.read_bytes() + b"x")

    with pytest.raises(phase11.GateError, match="model file does not match"):
        v2.load_fitted_v21(Path(result["out_dir"]), v2.AUTHORIZED_PROTOCOL_SHA256)


# --- execution safety --------------------------------------------------------


def test_b7_adds_no_execution_or_test_path():
    assert runner.MODES == ("preflight", "synthetic")
    with pytest.raises(runner.ReadinessError):
        runner.execute_real()

    public = {name for name in vars(b7) if not name.startswith("_")}
    assert not any("evaluate" in name.lower() for name in public)
    assert not any("campaign" in name.lower() for name in public)
    assert "load_authorized_trials" not in public
    assert np.isfinite(b7.TIMING_TOLERANCE_DAYS if hasattr(b7, "TIMING_TOLERANCE_DAYS") else 1.0)
