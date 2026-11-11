"""Phase 11 Stage B5 tests: the readiness decision record and its fail-closed checks.

No campaign, no trial, no sealed-test access. The tests prove that B5 records a not-granted
decision, refuses to record agreement when a contract disagrees, and never authorizes execution.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import (  # noqa: E402, I001
    generalization as gen,
    phase11,
    phase11_b1 as b1,
    phase11_b3 as b3,
    phase11_b5 as b5,
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
def decision() -> dict:
    missing = [name for name in FROZEN_NAMES if not (MANIFEST_DIR / name).is_file()]
    if missing:
        pytest.skip(f"frozen triple unavailable: {missing}")
    return b5.assess_readiness(manifest_dir=MANIFEST_DIR, repo_root=REPO_ROOT)


# --- the decision itself -----------------------------------------------------


def test_decision_never_authorizes_execution(decision):
    assert decision["decision_kind"] == "external_readiness_not_granted"
    assert decision["authorizes_execution"] is False
    assert decision["protocol_revision_proposed"] is False
    assert "not granted" in decision["decision"]
    assert decision["protocol_sha256"] == v2.AUTHORIZED_PROTOCOL_SHA256
    assert decision["protocol_version"] == v2.AUTHORIZED_PROTOCOL_VERSION


def test_protocol_flags_stay_false(decision):
    flags = decision["flags"]
    assert flags["campaign_ready"] is False
    assert flags["execution_ready"] is False
    assert "PROPOSAL ONLY" in flags["status"]


def test_every_contract_agrees(decision):
    contracts = {check["contract"]: check["status"] for check in decision["checks"]}

    assert contracts == {
        "fitted_state": "agrees",
        "denominator_policy": "agrees",
        "g12_refusal_audit": "agrees",
        "readiness_gates": "agrees",
    }


def test_outstanding_requirements_are_enumerated(decision):
    outstanding = " ".join(decision["outstanding"])

    for required in ("B6", "campaign generator", "denominator literals", "uncommitted", "B7"):
        assert required in outstanding, required
    assert "required_approval" in decision
    assert "B7" in decision["required_approval"]


def test_documentation_trap_is_recorded(decision):
    trap = decision["documentation_trap"]

    assert "PROPOSAL ONLY" in trap
    assert "authorization" in trap
    assert "predates" in trap
    assert decision["recorded_at"].endswith("Z")


# --- fail-closed contract checks --------------------------------------------


def test_fitted_contract_drift_is_refused(monkeypatch):
    monkeypatch.setattr(b1, "FITTED_PAYLOAD_KEYS", b1.FITTED_PAYLOAD_KEYS[:-1])

    with pytest.raises(phase11.GateError, match="fitted-state contract disagrees"):
        b5.assess_readiness(manifest_dir=MANIFEST_DIR, repo_root=REPO_ROOT)


def test_denominator_drift_is_refused(monkeypatch):
    monkeypatch.setattr(b3, "MIN_TEST_NULLS_PER_STRATUM", 31)

    with pytest.raises(phase11.GateError, match="denominator policy disagrees"):
        b5.assess_readiness(manifest_dir=MANIFEST_DIR, repo_root=REPO_ROOT)


def test_readiness_gate_drift_is_refused(monkeypatch):
    monkeypatch.setattr(runner, "MODES", ("preflight", "synthetic", "execute"))

    with pytest.raises(phase11.GateError, match="readiness gates changed"):
        b5.assess_readiness(manifest_dir=MANIFEST_DIR, repo_root=REPO_ROOT)


def test_protocol_claiming_readiness_is_refused(monkeypatch):
    protocol, digest = v2.load_protocol_v21(MANIFEST_DIR / v2.AUTHORIZED_PROTOCOL_NAME)
    ready = dict(
        protocol,
        campaign_ready=True,
        execution_ready=True,
        status="ready",
        proposal_record={"status": "adopted"},
    )
    monkeypatch.setattr(v2, "load_protocol_v21", lambda *args, **kwargs: (ready, digest))

    with pytest.raises(phase11.GateError, match="no longer reports any execution blocker"):
        b5.assess_readiness(manifest_dir=MANIFEST_DIR, repo_root=REPO_ROOT)


# --- output handling ---------------------------------------------------------


def test_decision_is_written_with_a_hash(decision, tmp_path):
    written = b5.write_decision(
        decision, tmp_path / "out", manifest_dir=MANIFEST_DIR, repo_root=REPO_ROOT
    )

    path = Path(written["path"])
    assert path.name == b5.DECISION_FILENAME
    assert path.is_file()
    assert v2.sha256_file(path) == written["sha256"]
    sidecar = path.with_name("readiness_decision.sha256")
    assert sidecar.read_text(encoding="utf-8").split()[0] == written["sha256"]
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["authorizes_execution"] is False


def test_decision_writer_refuses_authority_claims(decision, tmp_path):
    forged = dict(decision, authorizes_execution=True)

    with pytest.raises(phase11.GateError, match="never claim execution authority"):
        b5.write_decision(forged, tmp_path / "out", manifest_dir=MANIFEST_DIR, repo_root=REPO_ROOT)


def test_decision_writer_refuses_protected_destinations(decision):
    before = sorted(path.name for path in MANIFEST_DIR.iterdir())

    for destination in (MANIFEST_DIR, MANIFEST_DIR / "smoke"):
        with pytest.raises(runner.OutputIsolationError):
            b5.write_decision(decision, destination, manifest_dir=MANIFEST_DIR, repo_root=REPO_ROOT)

    assert sorted(path.name for path in MANIFEST_DIR.iterdir()) == before


def test_decision_writer_refuses_a_file_destination(decision, tmp_path):
    target = tmp_path / "not_a_directory"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(runner.OutputIsolationError, match="not a directory"):
        b5.write_decision(decision, target, manifest_dir=MANIFEST_DIR, repo_root=REPO_ROOT)


# --- execution safety --------------------------------------------------------


def test_b5_adds_no_execution_path():
    assert runner.MODES == ("preflight", "synthetic")
    with pytest.raises(runner.ReadinessError):
        runner.execute_real()

    public = {name for name in vars(b5) if not name.startswith("_")}
    assert "execute_real" not in public
    assert not any("campaign" in name.lower() for name in public)
    assert not any("evaluate" in name.lower() for name in public)
