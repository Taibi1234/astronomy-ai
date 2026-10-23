"""Phase 11 Stage B3 tests: gated test evaluation, one-shot access, and the G12 audit.

Synthetic fixtures only. A disposable git repository supplies clean provenance for the frozen
fitted state; the test artifact is produced by B2 from synthetic arrays. No quarter CSV is read,
no real trial is generated and no sealed data is touched.
"""

from __future__ import annotations

import inspect
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
    phase11_b3 as b3,
    phase11_runner as runner,
    phase11_v2 as v2,
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
TEST_QUARTERS = {"Q02": "test", "Q09": "test", "Q13": "test"}
FITTED_FILES = ("fitted.json", "fitted.sha256", "model.pkl")
RESAMPLES = 200
STATUSES = {"superior", "not_superior", "inconclusive", "descriptive_only"}


@pytest.fixture(scope="module")
def effective() -> dict:
    missing = [name for name in FROZEN_NAMES if not (MANIFEST_DIR / name).is_file()]
    if missing:
        pytest.skip(f"frozen triple unavailable: {missing}")
    resolved, _ = v2.resolve_effective_protocol(MANIFEST_DIR)
    return resolved


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture(scope="module")
def ready_campaign(tmp_path_factory, effective) -> Path:
    """A campaign directory holding a frozen fitted state plus generated synthetic trials."""
    base = tmp_path_factory.mktemp("b3_ready")
    repo = base / "fixture_repo"
    repo.mkdir()
    (repo / "source.py").write_text("# synthetic fixture source\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(
        repo,
        "-c",
        "user.email=b3@example.invalid",
        "-c",
        "user.name=B3 Fixture",
        "add",
        "source.py",
    )
    _git(
        repo,
        "-c",
        "user.email=b3@example.invalid",
        "-c",
        "user.name=B3 Fixture",
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
    fit_frame = b2a.build_fit_split_frame(
        effective=effective,
        split_map={"Q00": "train", "Q04": "val"},
        seed=20261022,
        windows_per_quarter=34,
        depths_ppm=(300.0,),
    )
    campaign = base / "campaign"
    b1.fit_synthetic(
        effective=effective,
        frame=fit_frame,
        out_dir=campaign,
        provenance=provenance,
        manifest_dir=MANIFEST_DIR,
        repo_root=REPO_ROOT,
        model_id="L7_detector_plus_clean_flux",
    )
    b2.generate_test_trials(
        effective=effective,
        out_dir=campaign,
        manifest_dir=MANIFEST_DIR,
        repo_root=REPO_ROOT,
        spec=b2.GenerationSpec(
            split_map=TEST_QUARTERS,
            seed=7,
            windows_per_quarter=20,
            depths_ppm=(300.0,),
        ),
    )
    return campaign


@pytest.fixture
def campaign(ready_campaign, tmp_path) -> Path:
    target = tmp_path / "campaign"
    shutil.copytree(ready_campaign, target)
    return target


@pytest.fixture
def audit(tmp_path) -> Path:
    return tmp_path / "refusals"


def _evaluate(effective, campaign: Path, audit: Path, **overrides) -> dict:
    arguments = {
        "effective": effective,
        "out_dir": campaign,
        "audit_dir": audit,
        "manifest_dir": MANIFEST_DIR,
        "repo_root": REPO_ROOT,
        "resamples": RESAMPLES,
    }
    arguments.update(overrides)
    return b3.evaluate_test(**arguments)


def _refusals(audit: Path) -> list[dict]:
    if not audit.is_dir():
        return []
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(audit.glob("*.json"))]


# --- happy path --------------------------------------------------------------


def test_evaluation_writes_hash_bound_metrics(effective, campaign, audit):
    result = _evaluate(effective, campaign, audit)

    assert result["mode"] == "synthetic"
    assert result["trials_rows"] > 0
    assert set(result["per_stratum"]) == set(effective["injection"]["noise_conditions"])
    assert result["comparison"]["status"] in STATUSES
    assert result["comparison"]["practical_superiority_claim"] is False

    metrics_path = campaign / b3.METRICS_FILENAME
    assert metrics_path.is_file()
    sidecar = metrics_path.with_name("metrics_test.sha256")
    assert sidecar.read_text(encoding="utf-8").split()[0] == v2.sha256_file(metrics_path)
    assert result["metrics_sha256"] == v2.sha256_file(metrics_path)

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics["protocol_sha256"] == v2.AUTHORIZED_PROTOCOL_SHA256
    assert metrics["fitted_sha256"]
    assert metrics["trials_sha256"] == v2.sha256_file(campaign / b2.TRIALS_FILENAME)
    assert metrics["timing_tolerance_days"] == phase11.TIMING_TOLERANCE_DAYS
    assert set(metrics["operating_points"]["detector"]) == set(metrics["per_stratum"])
    for stratum, report in metrics["per_stratum"].items():
        assert report["nulls"] >= b3.MIN_TEST_NULLS_PER_STRATUM, stratum
        assert report["clusters"] >= b3.MIN_TEST_CLUSTERS, stratum
        for method in ("l7", "physics"):
            assert report["fpr"][method]["false_positives"] >= 0
            assert report["fpr"][method]["wilson_label"].startswith("trial-level")
            assert report["recall"][method]["wilson"]["n"] == report["injections"]

    ledger = result["ledger"]
    assert ledger["status"] == "completed"
    assert ledger["metrics_sha256"] == result["metrics_sha256"]
    assert ledger["overall_status"] == result["comparison"]["status"]
    assert test_access.marker_state(campaign, test_access.MARKER_ACCESS) == "completed"
    assert _refusals(audit) == []


def test_access_is_claimed_before_the_trial_file_is_read(effective, campaign, audit, monkeypatch):
    seen = []
    real = b3.load_authorized_trials

    def spy(out_dir):
        seen.append(test_access.marker_state(out_dir, test_access.MARKER_ACCESS))
        return real(out_dir)

    monkeypatch.setattr(b3, "load_authorized_trials", spy)
    _evaluate(effective, campaign, audit)

    assert seen == ["started"]


def test_evaluator_accepts_no_caller_supplied_frame():
    signature = inspect.signature(b3.evaluate_test)
    forbidden = {"frame", "trials", "dataframe", "trial_frame"}

    assert not forbidden & set(signature.parameters)
    assert {"effective", "out_dir", "audit_dir", "manifest_dir", "repo_root"} <= set(
        signature.parameters
    )


# --- one-shot access and refusals -------------------------------------------


def test_second_evaluation_is_refused_and_audited(effective, campaign, audit):
    _evaluate(effective, campaign, audit)
    metrics_before = v2.sha256_file(campaign / b3.METRICS_FILENAME)

    with pytest.raises(phase11.GateError, match="one-shot"):
        _evaluate(effective, campaign, audit)

    assert v2.sha256_file(campaign / b3.METRICS_FILENAME) == metrics_before
    records = _refusals(audit)
    assert len(records) == 1
    assert records[0]["gate"] == "GateError"
    assert "one-shot" in records[0]["message"]


def test_tampered_trials_are_refused_and_the_claim_is_terminal(effective, campaign, audit):
    target = campaign / b2.TRIALS_FILENAME
    target.write_bytes(target.read_bytes() + b" \n")

    with pytest.raises(runner.IntegrityError, match="does not match the generation record"):
        _evaluate(effective, campaign, audit)

    assert test_access.marker_state(campaign, test_access.MARKER_ACCESS) == "started"
    assert not (campaign / b3.METRICS_FILENAME).exists()
    assert len(_refusals(audit)) == 1
    assert _refusals(audit)[0]["gate"] == "IntegrityError"

    with pytest.raises(phase11.GateError, match="one-shot"):
        _evaluate(effective, campaign, audit)


def test_missing_detector_table_is_refused_not_recalibrated(effective, campaign, audit):
    path = campaign / "fitted.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("detector_thresholds")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (campaign / "fitted.sha256").write_text(
        f"{v2.sha256_file(path)}  fitted.json\n", encoding="utf-8"
    )

    with pytest.raises(phase11.GateError, match="no detector_thresholds table"):
        _evaluate(effective, campaign, audit)

    assert test_access.marker_state(campaign, test_access.MARKER_ACCESS) is None
    records = _refusals(audit)
    assert len(records) == 1
    assert "detector_thresholds" in records[0]["message"]


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"mode": "real"}, "not approved for B1"),
        ({"mode": None}, "not approved for B1"),
    ],
)
def test_mode_gate_refuses_and_audits(effective, campaign, audit, overrides, message):
    with pytest.raises(phase11.GateError, match=message):
        _evaluate(effective, campaign, audit, **overrides)

    assert test_access.marker_state(campaign, test_access.MARKER_ACCESS) is None
    assert len(_refusals(audit)) == 1


def test_unapproved_protocol_is_refused(effective, campaign, audit):
    tampered = dict(effective, version="phase11b-protocol-v9")

    with pytest.raises(phase11.GateError, match="not the authorized"):
        _evaluate(tampered, campaign, audit)

    assert test_access.marker_state(campaign, test_access.MARKER_ACCESS) is None


def test_protected_campaign_destination_is_refused(effective, audit):
    before = sorted(path.name for path in MANIFEST_DIR.iterdir())

    with pytest.raises(runner.OutputIsolationError):
        _evaluate(effective, MANIFEST_DIR, audit)

    assert sorted(path.name for path in MANIFEST_DIR.iterdir()) == before


# --- trial-frame gates -------------------------------------------------------


def _test_frame(effective) -> pd.DataFrame:
    frame = b2.build_test_frame(
        effective=effective,
        split_map={"Q02": "test"},
        seed=3,
        allowed_quarters=b2.frozen_test_quarters(MANIFEST_DIR, effective),
        depths_ppm=(300.0,),
    )
    return frame


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda frame: frame.assign(split="train"), "test-split rows only"),
        (
            lambda frame: frame.assign(source="kepler-quarter-csv"),
            "synthetic generator or an authorized real artifact",
        ),
        (lambda frame: frame.assign(trial_id=frame["trial_id"].iloc[0]), "duplicate trial ids"),
        (lambda frame: frame.assign(noise_condition="undeclared"), "no frozen L7 threshold"),
        (lambda frame: frame.drop(columns=["delta_est_days"]), "missing required columns"),
        (lambda frame: frame.iloc[0:0], "is empty"),
    ],
)
def test_trial_frame_gates(effective, mutation, message):
    fitted = {"thresholds": {"observed": {"threshold": 0.5}}}

    with pytest.raises(phase11.GateError, match=message):
        b3.assert_test_trials(mutation(_test_frame(effective)), fitted)


def test_non_dataframe_is_refused():
    with pytest.raises(phase11.GateError, match="generated trial artifact only"):
        b3.assert_test_trials([{"split": "test"}], {"thresholds": {"observed": {}}})


def test_test_frame_can_never_be_a_fit_frame(effective):
    frame = _test_frame(effective)

    with pytest.raises(phase11.GateError, match="non-fitting splits"):
        phase11.assert_fit_splits(frame, effective)


def test_evaluation_never_reaches_training(effective, campaign, audit, monkeypatch):
    calls = []
    monkeypatch.setattr(phase11, "fit_models", lambda *args, **kwargs: calls.append(args))

    _evaluate(effective, campaign, audit)

    assert calls == []


# --- insufficient data and inconclusive gates --------------------------------


def test_insufficiency_gates_report_counts(effective):
    frame = _test_frame(effective)
    stratum_frame = frame[frame["noise_condition"].astype(str) == "observed"].copy()
    stratum_frame["l7_recovered"] = True
    stratum_frame["l7_false_positive"] = False
    stratum_frame["physics_recovered"] = True
    stratum_frame["physics_false_positive"] = False

    reasons = b3._insufficiency(stratum_frame)

    assert any("fewer than 3 test clusters" in reason for reason in reasons)
    assert any("null trials < 30" in reason for reason in reasons)

    report = b3._stratum_report(stratum_frame)
    comparison = b3._comparison(stratum_frame, report, reasons, degenerate=[], resamples=50)
    assert comparison["status"] == "inconclusive"
    assert comparison["practical_superiority_claim"] is False
    assert comparison["reasons"] == reasons


def test_zero_difference_forecloses_superiority():
    frame = pd.DataFrame(
        {
            "trial_id": [f"t{index}" for index in range(12)],
            "quarter": ["Q02", "Q02", "Q09", "Q09", "Q13", "Q13"] * 2,
            "rec_l7": [1.0] * 12,
            "rec_physics": [1.0] * 12,
        }
    )
    zero = v2.paired_comparison(frame, fpr={"l7": 0.05, "physics": 0.05})
    assert zero["status"] == "inconclusive"
    assert zero["reasons"]

    gate = v2._gate_reasons(0.0, {"Q02": np.zeros(2), "Q09": np.zeros(2)}, None, ())
    assert any("exactly zero" in reason for reason in gate)


def test_fpr_mismatch_forces_inconclusive():
    frame = pd.DataFrame(
        {
            "trial_id": [f"t{index}" for index in range(12)],
            "quarter": ["Q02"] * 4 + ["Q09"] * 4 + ["Q13"] * 4,
            "rec_l7": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0],
            "rec_physics": [0.0] * 12,
        }
    )
    matched = v2.paired_comparison(frame, fpr={"l7": 0.05, "physics": 0.05})
    assert matched["status"] == "descriptive_only"
    assert matched["practical_superiority_claim"] is False

    mismatch = v2.paired_comparison(frame, fpr={"l7": 0.0, "physics": 0.5})
    assert mismatch["status"] == "inconclusive"
    assert any("false-positive-rate mismatch" in reason for reason in mismatch["reasons"])


# --- G12 refusal audit -------------------------------------------------------


def test_refusal_record_carries_the_required_fields(effective, campaign, audit):
    with pytest.raises(phase11.GateError):
        _evaluate(effective, campaign, audit, mode="real")

    record = _refusals(audit)[0]
    assert record["stage"] == "B3"
    assert record["protocol_sha256"] == v2.AUTHORIZED_PROTOCOL_SHA256
    assert record["configuration_sha256"] == b3.configuration_hash(effective)
    assert record["campaign_dir"] == str(campaign.resolve())
    assert record["recorded_at"].endswith("Z")
    assert record["gate"] == "GateError"


def test_audit_inside_the_frozen_tree_is_refused(effective, campaign):
    before = sorted(path.name for path in MANIFEST_DIR.iterdir())
    inside = MANIFEST_DIR / "refusals"

    with pytest.raises(phase11.GateError, match="inside the frozen manifest tree"):
        b3.record_refusal(
            inside,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            gate="GateError",
            message="synthetic probe",
            effective=effective,
        )
    assert not inside.exists()

    with pytest.raises(phase11.GateError, match="could not be written"):
        _evaluate(effective, campaign, inside, mode="real")

    assert sorted(path.name for path in MANIFEST_DIR.iterdir()) == before


def test_configuration_hash_is_deterministic(effective):
    assert b3.configuration_hash(effective) == b3.configuration_hash(dict(effective))
    assert b3.configuration_hash(None) is None
    assert len(b3.configuration_hash(effective)) == 64


# --- execution safety --------------------------------------------------------


def test_execution_safety_is_unchanged():
    assert runner.MODES == ("preflight", "synthetic")
    with pytest.raises(runner.ReadinessError):
        runner.execute_real()

    public = {name for name in vars(b3) if not name.startswith("_")}
    assert "execute_real" not in public
    assert not any("campaign" in name.lower() and "run" in name.lower() for name in public)


# --- design §5.5 synthetic-only guard ----------------------------------------


def _install_guard(monkeypatch) -> Path:
    def blocked(*_args, **_kwargs):
        raise AssertionError("B3 must not open real source data")

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
            raise AssertionError(f"B3 opened real source data: {resolved}")
        return real_read_csv(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", guarded_read_csv)
    return processed


def test_evaluation_runs_behind_the_synthetic_only_guard(effective, campaign, audit, monkeypatch):
    processed = _install_guard(monkeypatch)

    result = _evaluate(effective, campaign, audit)

    assert result["trials_rows"] > 0
    with pytest.raises(AssertionError, match="opened real source data"):
        pd.read_csv(processed / "kepler_kepler_10.csv")


def test_campaign_holds_only_expected_artifacts(effective, campaign, audit):
    _evaluate(effective, campaign, audit)

    present = {path.name for path in campaign.iterdir()}
    assert present == {
        *FITTED_FILES,
        b2.TRIALS_FILENAME,
        test_access.MARKER_GENERATION,
        test_access.MARKER_ACCESS,
        b3.METRICS_FILENAME,
        "metrics_test.sha256",
    }
    assert np.isfinite(json.loads((campaign / b3.METRICS_FILENAME).read_text())["clusters"])
