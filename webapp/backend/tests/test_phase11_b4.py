"""Phase 11 Stage B4 verification tests: the review's own assertions.

These pin the findings of the B4 review rather than adding capability: the nine-key payload
amendment and its fail-closed behaviour, the G12 refusal-record contract (including the frozen
fitted hash and audit-write failure), the confirmatory decision logic, the denominator rule, and
the §5.3 no-execution invariant.

Synthetic fixtures only; a disposable git repository supplies clean provenance.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import (  # noqa: E402, I001
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
NINE_KEYS = (
    "model_id",
    "features",
    "dropped_features",
    "imputation_medians",
    "thresholds",
    "detector_thresholds",
    "train_rows",
    "val_rows",
    "train_injected",
)
RESAMPLES = 200


@pytest.fixture(scope="module")
def effective() -> dict:
    missing = [name for name in FROZEN_NAMES if not (MANIFEST_DIR / name).is_file()]
    if missing:
        pytest.skip(f"frozen triple unavailable: {missing}")
    resolved, _ = v2.resolve_effective_protocol(MANIFEST_DIR)
    return resolved


@pytest.fixture(scope="module")
def protocol(effective) -> dict:
    payload, _digest = v2.load_protocol_v21(MANIFEST_DIR / v2.AUTHORIZED_PROTOCOL_NAME)
    return payload


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture(scope="module")
def ready_campaign(tmp_path_factory, effective, protocol) -> Path:
    base = tmp_path_factory.mktemp("b4_ready")
    repo = base / "fixture_repo"
    repo.mkdir()
    (repo / "source.py").write_text("# synthetic fixture source\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(
        repo,
        "-c",
        "user.email=b4@example.invalid",
        "-c",
        "user.name=B4 Fixture",
        "add",
        "source.py",
    )
    _git(
        repo,
        "-c",
        "user.email=b4@example.invalid",
        "-c",
        "user.name=B4 Fixture",
        "commit",
        "-q",
        "-m",
        "fixture",
    )

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
            split_map={"Q02": "test", "Q09": "test", "Q13": "test"},
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


# --- 1. nine-key payload amendment -------------------------------------------


def test_payload_is_nine_keys_and_the_schema_version_is_unchanged():
    assert b1.FITTED_PAYLOAD_KEYS == NINE_KEYS
    assert v2.FITTED_SCHEMA_VERSION == 2


def test_freeze_refuses_a_payload_without_the_detector_table(tmp_path):
    frame = pd.DataFrame({"split": ["train"], "trial_id": ["t"], "snr": [1.0], "injected": [1]})
    fitted = {
        "model_id": "L7_detector_plus_clean_flux",
        "features": ["snr"],
        "dropped_features": [],
        "imputation_medians": [0.0],
        "thresholds": {
            "observed": {
                "threshold": 0.5,
                "threshold_source": "quantile",
                "n": 42,
                "calibration_exceedance": 0.02,
                "floor_binding": False,
                "threshold_degenerate": False,
                "distinct_scores": 30,
            }
        },
        "train_rows": 1,
        "val_rows": 0,
        "train_injected": 1,
    }

    with pytest.raises(phase11.GateError, match="detector threshold table"):
        v2.freeze_fitted_v21(
            tmp_path,
            fitted=fitted,
            model=object(),
            trials=frame,
            protocol={
                "version": "phase11b-protocol-v2.3-proposal",
                "preprocessing": {"fit_splits": ["train"]},
            },
            protocol_hash="abc",
            provenance={},
        )

    assert not (tmp_path / "fitted.json").exists()
    assert not (tmp_path / "model.pkl").exists()


def test_evaluation_refuses_a_payload_without_the_detector_table(effective, campaign, audit):
    path = campaign / "fitted.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("detector_thresholds")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (campaign / "fitted.sha256").write_text(
        f"{v2.sha256_file(path)}  fitted.json\n", encoding="utf-8"
    )

    with pytest.raises(phase11.GateError, match="no detector_thresholds table"):
        b3.evaluate_test(
            effective=effective,
            out_dir=campaign,
            audit_dir=audit,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            resamples=RESAMPLES,
        )

    assert test_access.marker_state(campaign, test_access.MARKER_ACCESS) is None
    assert len(list(audit.glob("*.json"))) == 1


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda fitted: fitted.pop("thresholds"), "no L7 threshold table"),
        (lambda fitted: fitted.pop("features"), "no feature list"),
        (lambda fitted: fitted.update(imputation_medians=[1.0, 2.0]), "inconsistent with features"),
        (lambda fitted: fitted.pop("model_file"), "no model file reference"),
        (
            lambda fitted: fitted.update(thresholds={"observed": {"n": 1}}),
            "has no threshold value",
        ),
        (
            lambda fitted: fitted.update(thresholds={"observed": {"threshold": float("nan")}}),
            "is not finite",
        ),
    ],
)
def test_score_table_validation_fails_closed(mutate, message):
    fitted = {
        "features": ["snr"],
        "imputation_medians": [0.0],
        "model_file": "model.pkl",
        "thresholds": {"observed": {"threshold": 0.5}},
    }
    mutate(fitted)

    with pytest.raises(phase11.GateError, match=message):
        b3.require_score_table(fitted)


def test_missing_model_file_is_a_gate_error(tmp_path):
    with pytest.raises(phase11.GateError, match="model file is missing"):
        b3._load_model(tmp_path, {"model_file": "model.pkl"})

    (tmp_path / "model.pkl").write_bytes(b"not a pickle")
    with pytest.raises(phase11.GateError, match="unreadable"):
        b3._load_model(tmp_path, {"model_file": "model.pkl"})


# --- 2. G12 refusal records --------------------------------------------------


def test_refusal_record_identifies_the_frozen_fitted_state(effective, campaign, audit):
    b3.evaluate_test(
        effective=effective,
        out_dir=campaign,
        audit_dir=audit,
        manifest_dir=MANIFEST_DIR,
        repo_root=REPO_ROOT,
        resamples=RESAMPLES,
    )
    with pytest.raises(phase11.GateError, match="one-shot"):
        b3.evaluate_test(
            effective=effective,
            out_dir=campaign,
            audit_dir=audit,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            resamples=RESAMPLES,
        )

    records = [json.loads(path.read_text(encoding="utf-8")) for path in audit.glob("*.json")]
    assert len(records) == 1
    record = records[0]
    assert record["gate"] == "GateError"
    assert record["protocol_sha256"] == v2.AUTHORIZED_PROTOCOL_SHA256
    assert record["configuration_sha256"] == b3.configuration_hash(effective)
    assert len(record["configuration_sha256"]) == 64
    assert record["campaign_dir"] == str(campaign.resolve())
    assert record["fitted_sha256"] == v2.sha256_file(campaign / "fitted.json")
    assert record["recorded_at"].endswith("Z")


def test_refusal_without_a_fitted_state_records_null(effective, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    audit = tmp_path / "refusals"

    with pytest.raises(phase11.GateError):
        b3.evaluate_test(
            effective=effective,
            out_dir=empty,
            audit_dir=audit,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            resamples=RESAMPLES,
        )

    record = json.loads(next(iter(audit.glob("*.json"))).read_text(encoding="utf-8"))
    assert record["fitted_sha256"] is None


def test_unwritable_audit_path_is_a_gate_error(effective):
    blocker = gen.project_root() / "reports" / "phase11_generalization" / "refusals"

    with pytest.raises(phase11.GateError, match="frozen manifest tree"):
        b3.record_refusal(
            blocker,
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            gate="GateError",
            message="synthetic probe",
            effective=effective,
        )
    assert not blocker.exists()


def test_audit_write_failure_is_surfaced_not_swallowed(effective, campaign, tmp_path):
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("x", encoding="utf-8")

    with pytest.raises(phase11.GateError, match="could not write the refusal record"):
        b3.record_refusal(
            not_a_directory / "refusals",
            manifest_dir=MANIFEST_DIR,
            repo_root=REPO_ROOT,
            gate="GateError",
            message="synthetic probe",
            effective=effective,
        )


def test_refusal_record_fields_are_validated_by_the_schema(effective, tmp_path):
    path = b3.record_refusal(
        tmp_path / "audit",
        manifest_dir=MANIFEST_DIR,
        repo_root=REPO_ROOT,
        gate="IntegrityError",
        message="synthetic probe",
        effective=effective,
        campaign=tmp_path,
        fitted_sha256="a" * 64,
    )
    record = json.loads(path.read_text(encoding="utf-8"))

    assert set(record) == {
        "stage",
        "evaluator",
        "gate",
        "message",
        "protocol_sha256",
        "configuration_sha256",
        "campaign_dir",
        "fitted_sha256",
        "recorded_at",
        "schema_version",
    }
    assert record["schema_version"] == 1
    assert record["stage"] == "B3"


# --- 3. confirmatory decision logic -----------------------------------------


def test_combine_confirmatory_is_intersection_union():
    combine = v2.combine_confirmatory

    assert combine({"a": {"status": "superior"}, "b": {"status": "superior"}})["status"] == (
        "superior"
    )
    assert combine({"a": {"status": "descriptive_only"}, "b": {"status": "descriptive_only"}})[
        "status"
    ] == ("descriptive_only")
    assert combine({"a": {"status": "superior"}, "b": {"status": "inconclusive"}})["status"] == (
        "inconclusive"
    )
    assert combine({"a": {"status": "superior"}, "b": {"status": "not_superior"}})["status"] == (
        "not_superior"
    )
    with pytest.raises(phase11.GateError, match="unrecognised comparison status"):
        combine({"a": {"status": "much_better"}})


def test_paired_comparison_cannot_claim_practical_superiority():
    frame = pd.DataFrame(
        {
            "trial_id": [f"t{index}" for index in range(12)],
            "quarter": ["Q02"] * 4 + ["Q09"] * 4 + ["Q13"] * 4,
            "rec_l7": [1.0] * 9 + [0.0] * 3,
            "rec_physics": [0.0] * 12,
        }
    )
    result = v2.paired_comparison(frame, fpr={"l7": 0.05, "physics": 0.05})

    assert result["status"] in {"descriptive_only", "inconclusive"}
    assert result["practical_superiority_claim"] is False
    assert result["mmd"] is None
    with pytest.raises(phase11.GateError, match="minimum meaningful difference unset"):
        v2.paired_comparison(frame, mmd=0.1)


def test_evaluated_artifact_reports_descriptive_only_or_inconclusive(effective, campaign, audit):
    result = b3.evaluate_test(
        effective=effective,
        out_dir=campaign,
        audit_dir=audit,
        manifest_dir=MANIFEST_DIR,
        repo_root=REPO_ROOT,
        resamples=RESAMPLES,
    )

    assert result["comparison"]["status"] in {"descriptive_only", "inconclusive"}
    assert result["comparison"]["practical_superiority_claim"] is False
    metrics = json.loads((campaign / b3.METRICS_FILENAME).read_text(encoding="utf-8"))
    for report in metrics["per_stratum"].values():
        fpr = report["fpr"]["l7"]
        assert fpr["target_fpr"] == 0.05
        assert fpr["wilson_label"].startswith("trial-level")
        assert report["recall"]["l7"]["injections"] == report["injections"]


# --- 4. denominator rule -----------------------------------------------------


def test_b3_minima_match_the_frozen_protocol_minima(protocol):
    minimum = protocol["insufficient_data"]

    assert b3.MIN_TEST_CLUSTERS == minimum["minimum_test_clusters"]
    assert b3.MIN_TEST_NULLS_PER_STRATUM == minimum["minimum_test_nulls_per_stratum"]
    assert (
        b3.MIN_TEST_INJECTIONS_PER_DEPTH_PER_STRATUM
        == minimum["minimum_test_injections_per_depth_per_stratum"]
    )
    assert b3.TIMING_TOLERANCE_DAYS == phase11.TIMING_TOLERANCE_DAYS


def test_denominator_rule_is_recorded_and_not_relaxed(effective, campaign, audit):
    result = b3.evaluate_test(
        effective=effective,
        out_dir=campaign,
        audit_dir=audit,
        manifest_dir=MANIFEST_DIR,
        repo_root=REPO_ROOT,
        resamples=RESAMPLES,
    )
    metrics = json.loads((campaign / b3.METRICS_FILENAME).read_text(encoding="utf-8"))

    policy = metrics["denominator_policy"]
    assert "76 nulls" in policy
    assert "72 injections per depth per stratum" in policy
    assert "real-campaign requirement" in policy
    assert "insufficient_data minima enforced" in policy
    assert metrics["clusters"] == result["ledger"]["clusters"]
    assert metrics["clusters"] <= 5
    observed = sum(report["nulls"] for report in result["per_stratum"].values())
    assert observed < 152  # a synthetic fixture, never the frozen campaign denominator


# --- 5. §5.3 no-execution invariant -----------------------------------------


def test_no_execution_path_was_added():
    assert runner.MODES == ("preflight", "synthetic")
    with pytest.raises(runner.ReadinessError):
        runner.execute_real()

    for module in (b1, b2, b3):
        public = {name for name in vars(module) if not name.startswith("_")}
        assert "execute_real" not in public
