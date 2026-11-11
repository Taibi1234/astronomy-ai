"""Phase 11 Stage B2 tests: the gated v2 test-split generator.

Synthetic fixtures only. A disposable git repository supplies clean provenance for the frozen
fitted state that generation requires; no quarter CSV is read, no real trial is generated and no
sealed data is touched. The real repository is read only through the frozen manifests.
"""

from __future__ import annotations

import json
import shutil
import subprocess
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
    phase11_b1 as b1,
    phase11_b2 as b2,
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
TEST_QUARTERS = {"Q02": "test", "Q09": "test"}
FITTED_FILES = ("fitted.json", "fitted.sha256", "model.pkl")
CALIBRATION_GEOMETRY = {"windows_per_quarter": 34, "depths_ppm": (300.0,)}


@pytest.fixture(scope="module")
def effective() -> dict:
    missing = [name for name in FROZEN_NAMES if not (MANIFEST_DIR / name).is_file()]
    if missing:
        pytest.skip(f"frozen triple unavailable: {missing}")
    resolved, _ = v2.resolve_effective_protocol(MANIFEST_DIR)
    return resolved


@pytest.fixture(scope="module")
def allowed_quarters(effective) -> set[str]:
    return b2.frozen_test_quarters(MANIFEST_DIR, effective)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture(scope="module")
def fitted_state(tmp_path_factory, effective) -> Path:
    """A campaign directory holding a synthetic frozen fitted state (built once)."""
    base = tmp_path_factory.mktemp("b2_fitted")
    repo = base / "fixture_repo"
    repo.mkdir()
    (repo / "source.py").write_text("# synthetic fixture source\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(
        repo,
        "-c",
        "user.email=b2@example.invalid",
        "-c",
        "user.name=B2 Fixture",
        "add",
        "source.py",
    )
    _git(
        repo,
        "-c",
        "user.email=b2@example.invalid",
        "-c",
        "user.name=B2 Fixture",
        "commit",
        "-q",
        "-m",
        "fixture",
    )

    protocol, _digest = v2.load_protocol_v21(MANIFEST_DIR / v2.AUTHORIZED_PROTOCOL_NAME)
    _offsets, offsets_hash = v2.load_frozen_offsets(MANIFEST_DIR, protocol)
    provenance = v2.capture_provenance(
        repo,
        source_paths=[repo / "source.py"],
        protocol_sha256=v2.AUTHORIZED_PROTOCOL_SHA256,
        manifest_hashes=v2.validate_manifests(MANIFEST_DIR, protocol),
        offsets_sha256=offsets_hash,
    )
    frame = b2a.build_fit_split_frame(
        effective=effective,
        split_map={"Q00": "train", "Q04": "val"},
        seed=20261022,
        **CALIBRATION_GEOMETRY,
    )
    campaign = base / "campaign"
    b1.fit_synthetic(
        effective=effective,
        frame=frame,
        out_dir=campaign,
        provenance=provenance,
        manifest_dir=MANIFEST_DIR,
        repo_root=REPO_ROOT,
        model_id="L7_detector_plus_clean_flux",
    )
    return campaign


@pytest.fixture
def campaign(fitted_state, tmp_path) -> Path:
    target = tmp_path / "campaign"
    target.mkdir()
    for name in FITTED_FILES:
        shutil.copy2(fitted_state / name, target / name)
    return target


def _generate(effective, campaign: Path, **spec_overrides) -> dict:
    spec = {"split_map": TEST_QUARTERS, "seed": 20261022}
    spec.update(spec_overrides)
    return b2.generate_test_trials(
        effective=effective,
        out_dir=campaign,
        manifest_dir=MANIFEST_DIR,
        repo_root=REPO_ROOT,
        spec=b2.GenerationSpec(**spec),
    )


def _marker(campaign: Path) -> dict:
    return json.loads((campaign / test_access.MARKER_GENERATION).read_text(encoding="utf-8"))


# --- happy path --------------------------------------------------------------


def test_generation_writes_a_verified_artifact(effective, campaign):
    result = _generate(effective, campaign)

    assert result["mode"] == "synthetic"
    assert result["generator"] == b2.GENERATOR_NAME
    assert result["test_quarters"] == sorted(TEST_QUARTERS)
    assert result["trials_rows"] > 0
    assert result["trials_sha256"] == v2.sha256_file(campaign / b2.TRIALS_FILENAME)

    info = runner.verify_generated_trials(campaign)
    assert info["trials_sha256"] == result["trials_sha256"]
    assert info["trials_rows"] == result["trials_rows"]

    frame = runner.load_authorized_trials(campaign)
    assert len(frame) == result["trials_rows"]
    assert set(frame["split"].unique()) == {"test"}
    assert set(frame["source"].unique()) == {b2a.SOURCE}
    assert set(frame["role"].unique()) == {b2a.ROLE_NULL, b2a.ROLE_INJECTION}
    assert set(frame["quarter"].unique()) == set(TEST_QUARTERS)
    for column in (*b2.DELTA_COLUMNS, "snr", "depth_est_ppm", "sigma_ppm"):
        assert column in frame.columns, column

    record = _marker(campaign)
    assert record["status"] == "completed"
    assert record["generator"] == b2.GENERATOR_NAME
    assert record["protocol_sha256"] == v2.AUTHORIZED_PROTOCOL_SHA256
    assert record["trials_sha256"] == result["trials_sha256"]
    assert record["trials_rows"] == result["trials_rows"]


def test_generation_is_deterministic(effective, campaign, tmp_path):
    other = tmp_path / "second"
    other.mkdir()
    for name in FITTED_FILES:
        shutil.copy2(campaign / name, other / name)

    first = _generate(effective, campaign)
    second = _generate(effective, other)

    assert first["trials_sha256"] == second["trials_sha256"]
    assert (campaign / b2.TRIALS_FILENAME).read_bytes() == (other / b2.TRIALS_FILENAME).read_bytes()


def test_ground_truth_is_recorded_but_never_feeds_the_detector(effective, campaign, monkeypatch):
    seen = []
    real = core.detect

    def spy(*args, **kwargs):
        seen.append((args, tuple(kwargs)))
        return real(*args, **kwargs)

    monkeypatch.setattr(core, "detect", spy)
    _generate(effective, campaign)

    frame = runner.load_authorized_trials(campaign)
    assert len(seen) == len(frame)
    for args, kwargs in seen:
        assert kwargs == ()
        assert len(args) == 3
        assert args[2] in ti.BJD_REFERENCE
    assert np.isfinite(frame["delta_true_days"].to_numpy(dtype=float)).all()
    assert np.isfinite(frame["delta_est_days"].to_numpy(dtype=float)).all()


# --- refusal paths, all before any side effect -------------------------------


def test_missing_fitted_state_is_refused(effective, tmp_path):
    empty = tmp_path / "empty_campaign"
    empty.mkdir()

    with pytest.raises(phase11.GateError, match="before fitted.sha256 exists"):
        _generate(effective, empty)

    assert sorted(path.name for path in empty.iterdir()) == []


@pytest.mark.parametrize(
    "split_map, message",
    [
        ({}, "non-empty mapping"),
        (None, "non-empty mapping"),
        ({"Q00": "test"}, "not a test quarter"),
        ({"Q99": "test"}, "not a test quarter"),
        ({"Q02": "train"}, "is not 'test'"),
        ({"Q02": "val"}, "is not 'test'"),
        ({"Q02": 2}, "is not 'test'"),
    ],
)
def test_split_guards_refuse_before_any_side_effect(effective, campaign, split_map, message):
    before = sorted(path.name for path in campaign.iterdir())

    with pytest.raises(phase11.GateError, match=message):
        _generate(effective, campaign, split_map=split_map)

    assert sorted(path.name for path in campaign.iterdir()) == before
    assert not (campaign / b2.TRIALS_FILENAME).exists()


def test_mode_gate_refuses_before_any_side_effect(effective, campaign):
    before = sorted(path.name for path in campaign.iterdir())

    with pytest.raises(phase11.GateError, match="not approved for B1"):
        b2.generate_test_trials(
            effective=effective,
            out_dir=campaign,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            spec=b2.GenerationSpec(split_map=TEST_QUARTERS, seed=1),
            mode="real",
        )

    assert sorted(path.name for path in campaign.iterdir()) == before


def test_unapproved_protocol_version_is_refused(effective, campaign):
    tampered = dict(effective, version="phase11b-protocol-v9")

    with pytest.raises(phase11.GateError, match="not the authorized"):
        _generate(tampered, campaign)

    assert not (campaign / test_access.MARKER_GENERATION).exists()


def test_protected_and_frozen_destinations_are_refused(effective):
    before = sorted(path.name for path in MANIFEST_DIR.iterdir())

    for destination in (MANIFEST_DIR, MANIFEST_DIR / "smoke"):
        with pytest.raises(runner.OutputIsolationError):
            b2.generate_test_trials(
                effective=effective,
                out_dir=destination,
                manifest_dir=MANIFEST_DIR,
                repo_root=REPO_ROOT,
                spec=b2.GenerationSpec(split_map=TEST_QUARTERS, seed=1),
            )

    assert sorted(path.name for path in MANIFEST_DIR.iterdir()) == before
    assert not (MANIFEST_DIR / b2.TRIALS_FILENAME).exists()
    assert not (MANIFEST_DIR / test_access.MARKER_GENERATION).exists()


def test_file_destination_is_refused(effective, tmp_path):
    target = tmp_path / "not_a_directory"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(runner.OutputIsolationError, match="not a directory"):
        b2.generate_test_trials(
            effective=effective,
            out_dir=target,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            spec=b2.GenerationSpec(split_map=TEST_QUARTERS, seed=1),
        )


def test_fitted_state_must_bind_the_pinned_protocol(campaign):
    path = campaign / "fitted.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["protocol_sha256"] = "1" * 64
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (campaign / "fitted.sha256").write_text(
        f"{v2.sha256_file(path)}  fitted.json\n", encoding="utf-8"
    )

    with pytest.raises(phase11.GateError, match="different protocol"):
        b2._assert_fitted_state(campaign)

    assert not (campaign / test_access.MARKER_GENERATION).exists()


# --- one-shot claim semantics ------------------------------------------------


def test_duplicate_generation_is_refused(effective, campaign):
    first = _generate(effective, campaign)
    digest_after_first = v2.sha256_file(campaign / b2.TRIALS_FILENAME)

    with pytest.raises(phase11.GateError, match="markers are one-way"):
        _generate(effective, campaign)

    assert v2.sha256_file(campaign / b2.TRIALS_FILENAME) == first["trials_sha256"]
    assert v2.sha256_file(campaign / b2.TRIALS_FILENAME) == digest_after_first


def test_interrupted_generation_is_terminal(effective, campaign):
    test_access.claim_generation(campaign, {"generator": "interrupted-test"})

    with pytest.raises(phase11.GateError, match="in state 'started'"):
        _generate(effective, campaign)

    with pytest.raises(runner.IntegrityError, match="only a completed generation record"):
        runner.verify_generated_trials(campaign)
    assert not (campaign / b2.TRIALS_FILENAME).exists()


def test_access_claim_blocks_generation(effective, campaign):
    test_access.begin_marker(campaign, test_access.MARKER_ACCESS, {"trial_id": "synthetic"})

    with pytest.raises(phase11.GateError, match="markers are one-way"):
        _generate(effective, campaign)

    assert not (campaign / b2.TRIALS_FILENAME).exists()


def test_tampered_trials_fail_integrity(effective, campaign):
    result = _generate(effective, campaign)
    target = campaign / b2.TRIALS_FILENAME
    target.write_bytes(target.read_bytes() + b" \n")

    with pytest.raises(runner.IntegrityError, match="does not match the generation record"):
        runner.verify_generated_trials(campaign)
    with pytest.raises(runner.IntegrityError, match="does not match the generation record"):
        runner.load_authorized_trials(campaign)
    assert v2.sha256_file(target) != result["trials_sha256"]


# --- frame builder and execution safety --------------------------------------


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"depths_ppm": ()}, "at least one positive depth"),
        ({"depths_ppm": (0.0,)}, "finite and positive"),
        ({"depths_ppm": (-5.0,)}, "finite and positive"),
        ({"depths_ppm": (float("nan"),)}, "finite and positive"),
        ({"seed": True}, "seed must be an integer"),
        ({"windows_per_quarter": 0}, "positive integer"),
        ({"windows_per_quarter": "2"}, "positive integer"),
        ({"geometry": "coarse"}, "phase11_b2a.Geometry"),
        ({"geometry": b2a.Geometry(window_days=0.0)}, "finite and positive"),
        ({"geometry": b2a.Geometry(cadence_days=0.5)}, "too few cadences"),
        ({"geometry": b2a.Geometry(mission="jwst")}, "unknown mission"),
        ({"geometry": b2a.Geometry(noise_ppm=0.0)}, "finite and positive"),
    ],
)
def test_build_test_frame_rejects_invalid_inputs(effective, allowed_quarters, overrides, message):
    arguments = {
        "effective": effective,
        "split_map": TEST_QUARTERS,
        "seed": 1,
        "allowed_quarters": allowed_quarters,
    }
    arguments.update(overrides)

    with pytest.raises(phase11.GateError, match=message):
        b2.build_test_frame(**arguments)


def test_unbuildable_feature_column_is_refused(effective, allowed_quarters):
    protocol = dict(
        effective,
        features=dict(
            effective["features"],
            detector_outputs=[*effective["features"]["detector_outputs"], "delta_est_days"],
        ),
    )

    with pytest.raises(phase11.GateError, match="cannot produce the declared feature columns"):
        b2.build_test_frame(
            effective=protocol,
            split_map=TEST_QUARTERS,
            seed=1,
            allowed_quarters=allowed_quarters,
        )


def test_execution_safety_is_unchanged():
    assert runner.MODES == ("preflight", "synthetic")
    with pytest.raises(runner.ReadinessError):
        runner.execute_real()

    public = {name for name in vars(b2) if not name.startswith("_")}
    assert not any("evaluate" in name.lower() for name in public)
    assert "execute_real" not in public


def test_local_test_quarters_match_the_frozen_manifest(allowed_quarters):
    assert set(TEST_QUARTERS) <= allowed_quarters
    assert "Q00" not in allowed_quarters


# --- design §5.5 synthetic-only guard ----------------------------------------


def _install_guard(monkeypatch) -> Path:
    def blocked(*_args, **_kwargs):
        raise AssertionError("B2 must not open real source data")

    for module, name in (
        (gen, "load_quarter"),
        (gen, "quarter_files"),
        (gen, "build_manifests"),
        (phase11, "_load_window_series"),
        (core, "load_curve"),
        (ti, "load_light_curve"),
        (ti, "_load_cached"),
    ):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, blocked)

    processed = (gen.project_root() / "data" / "processed").resolve()
    real_read_csv = pd.read_csv

    def guarded_read_csv(path, *args, **kwargs):
        resolved = Path(path).resolve()
        if resolved == processed or resolved.is_relative_to(processed):
            raise AssertionError(f"B2 opened real source data: {resolved}")
        return real_read_csv(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", guarded_read_csv)
    return processed


def test_generation_runs_behind_the_synthetic_only_guard(effective, campaign, monkeypatch):
    processed = _install_guard(monkeypatch)

    result = _generate(effective, campaign)
    frame = runner.load_authorized_trials(campaign)

    assert len(frame) == result["trials_rows"]
    with pytest.raises(AssertionError, match="opened real source data"):
        pd.read_csv(processed / "kepler_kepler_10.csv")


def test_generated_artifact_holds_no_campaign_marker_beyond_generation(campaign, effective):
    _generate(effective, campaign)

    present = {path.name for path in campaign.iterdir()}
    assert present == {*FITTED_FILES, b2.TRIALS_FILENAME, test_access.MARKER_GENERATION}
    assert present <= safeguards.CAMPAIGN_STATE_NAMES
