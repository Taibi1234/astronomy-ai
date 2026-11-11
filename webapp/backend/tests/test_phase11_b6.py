"""Phase 11 Stage B6 tests: the minimum-meaningful-difference decision record.

No campaign, no trial, no sealed-test access. The tests prove the recorded decision, that the
implementation refuses an unset-difference override, and that no status above descriptive_only
is reachable while the difference stays unset.
"""

from __future__ import annotations

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
    phase11_b6 as b6,
    phase11_runner as runner,
    phase11_v2 as v2,
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


@pytest.fixture(scope="module")
def record() -> dict:
    missing = [name for name in FROZEN_NAMES if not (MANIFEST_DIR / name).is_file()]
    if missing:
        pytest.skip(f"frozen triple unavailable: {missing}")
    return b6.assess_mmd_decision(manifest_dir=MANIFEST_DIR, repo_root=REPO_ROOT)


@pytest.fixture(scope="module")
def protocol() -> dict:
    payload, _digest = v2.load_protocol_v21(MANIFEST_DIR / v2.AUTHORIZED_PROTOCOL_NAME)
    return payload


# --- the decision ------------------------------------------------------------


def test_decision_stays_descriptive_only(record):
    assert record["decision_kind"] == "mmd_stays_unset_descriptive_only"
    assert record["mmd_value"] is None
    assert "descriptive-only" in record["decision"]
    assert record["authorizes_execution"] is False
    assert record["overrides_confirmatory_semantics"] is False
    assert record["protocol_sha256"] == v2.AUTHORIZED_PROTOCOL_SHA256


def test_record_names_the_meaning_and_the_absent_diagnostic(record):
    assert "minimum meaningful difference" in record["mmd_meaning"]
    assert "not a two-sample kernel statistic" in record["mmd_meaning"]
    diagnostic = record["diagnostic"]
    assert "no MMD diagnostic is specified" in diagnostic
    assert "kernel" in diagnostic and "permutation" in diagnostic


def test_every_check_agrees(record):
    checks = {check["check"]: check["status"] for check in record["checks"]}

    assert checks == {
        "protocol_decision_D1": "agrees",
        "code_constant": "agrees",
        "enforcement": "agrees",
    }


def test_change_requirements_are_recorded(record):
    joined = " ".join(record["change_requirements"])

    assert "owner decision" in joined
    assert "protocol revision" in joined
    assert "repin" in joined
    assert "descriptive_only" in " ".join(record["consequences"])


def test_protocol_decision_d1_is_unset(protocol):
    decision = protocol["approval_decisions"]["D1_minimum_meaningful_difference"]

    assert decision["value"] is None
    assert "unset" in decision["status"]
    assert v2.MINIMUM_MEANINGFUL_DIFFERENCE is None


# --- enforcement (diagnostic-only, never overriding the gates) ---------------


def test_caller_supplied_difference_is_refused():
    frame = b6._probe_frame()

    with pytest.raises(phase11.GateError, match="minimum meaningful difference unset"):
        v2.paired_comparison(frame, mmd=0.1)


def test_reported_status_never_exceeds_descriptive_only():
    frame = b6._probe_frame()
    result = v2.paired_comparison(frame, fpr={"l7": 0.05, "physics": 0.05})

    assert result["status"] in {"descriptive_only", "inconclusive"}
    assert result["status"] != "superior"
    assert result["practical_superiority_claim"] is False
    assert result["mmd"] is None

    combined = v2.combine_confirmatory({"observed": result, "amplified_x2": result})
    assert combined["status"] in {"descriptive_only", "inconclusive"}
    assert combined["practical_superiority_claim"] is False


def test_an_inconclusive_gate_still_wins_over_the_diagnostic():
    frame = b6._probe_frame()
    zero = frame.assign(rec_l7=frame["rec_physics"])

    result = v2.paired_comparison(zero, fpr={"l7": 0.05, "physics": 0.05})

    assert result["status"] == "inconclusive"
    assert result["reasons"]
    assert result["practical_superiority_claim"] is False


# --- fail-closed contract checks --------------------------------------------


def test_protocol_carrying_a_value_is_refused(monkeypatch):
    protocol, digest = v2.load_protocol_v21(MANIFEST_DIR / v2.AUTHORIZED_PROTOCOL_NAME)
    decisions = dict(protocol["approval_decisions"])
    decisions["D1_minimum_meaningful_difference"] = {
        "value": 0.1,
        "status": "approved",
    }
    tampered = dict(protocol, approval_decisions=decisions)
    monkeypatch.setattr(v2, "load_protocol_v21", lambda *args, **kwargs: (tampered, digest))

    with pytest.raises(phase11.GateError, match="B6 does not adopt a value"):
        b6.assess_mmd_decision(manifest_dir=MANIFEST_DIR, repo_root=REPO_ROOT)


def test_code_constant_carrying_a_value_is_refused(monkeypatch):
    monkeypatch.setattr(v2, "MINIMUM_MEANINGFUL_DIFFERENCE", 0.25)

    with pytest.raises(phase11.GateError, match="implementation carries a minimum meaningful"):
        b6.assess_mmd_decision(manifest_dir=MANIFEST_DIR, repo_root=REPO_ROOT)


def test_override_acceptance_is_refused(monkeypatch):
    monkeypatch.setattr(v2, "paired_comparison", lambda *args, **kwargs: {"status": "superior"})

    with pytest.raises(phase11.GateError, match="accepted a caller-supplied"):
        b6._check_enforcement()


def test_describe_value_reports_unset_and_refuses_non_finite():
    assert b6.describe_value(None).startswith("unset")
    assert "protocol revision" in b6.describe_value(0.1)

    with pytest.raises(phase11.GateError, match="must be finite"):
        b6.describe_value(float("nan"))


def test_probe_frame_is_synthetic_and_pairable():
    frame = b6._probe_frame()

    assert list(frame.columns) == ["trial_id", "quarter", "rec_l7", "rec_physics"]
    assert not frame["trial_id"].duplicated().any()
    assert frame["quarter"].nunique() == 3
    assert pd.api.types.is_float_dtype(frame["rec_l7"])


# --- execution safety --------------------------------------------------------


def test_b6_adds_no_execution_or_scoring_path():
    assert runner.MODES == ("preflight", "synthetic")
    with pytest.raises(runner.ReadinessError):
        runner.execute_real()

    public = {name for name in vars(b6) if not name.startswith("_")}
    assert "execute_real" not in public
    assert not any("campaign" in name.lower() for name in public)
    assert not any("evaluate" in name.lower() for name in public)
