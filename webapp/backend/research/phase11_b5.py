"""Phase 11 Stage B5: the readiness decision record (design §5.8, §7 risk 4).

B5 is a decision stage, not an authorization stage. It records **why** execution is not
authorized, checks that the protocol, the fitted-state contract, the denominator policy, the G12
refusal audit and the existing readiness gates do not contradict each other, and refuses to
produce a record when they do.

The decision taken is the design's external-readiness branch: no v2.4 revision is proposed and
no readiness flag is changed. ``campaign_ready`` and ``execution_ready`` stay false, and the
protocol text still declares itself proposal-only. The record names that documentation trap
explicitly, because a future operator must not read the frozen text as authorization.

This module adds no execution mode and no capability: it only reads and records.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path

from . import phase11_b1 as b1
from . import phase11_b3 as b3
from . import phase11_runner as runner
from . import phase11_v2 as v2
from . import safeguards
from .phase11 import GateError
from .phase11_runner import OutputIsolationError

DECISION_KIND = "external_readiness_not_granted"
DECISION_FILENAME = "readiness_decision.json"
EXPECTED_PAYLOAD_KEYS = (
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
EXPECTED_MODES = ("preflight", "synthetic")
OUTSTANDING = (
    "B6: the minimum meaningful difference is unset, so conclusions stay descriptive-only "
    "and practical-superiority claims remain prohibited",
    "no real-data campaign generator exists; the stage B2 generator produces synthetic arrays only",
    "the frozen denominator literals (76 nulls, 72 injections per depth per stratum, five test "
    "clusters) are not enforced by any runner yet",
    "the tracked tree is dirty and the source baseline is uncommitted, so a defensible run record "
    "cannot be captured yet",
    "no B7 authorization document exists",
    "the protocol text still declares PROPOSAL ONLY; a v2.4 revision is not proposed here, so the "
    "frozen text must not be read as readiness",
)


def _check_fitted_contract() -> dict:
    if tuple(b1.FITTED_PAYLOAD_KEYS) != EXPECTED_PAYLOAD_KEYS:
        raise GateError(
            "fitted-state contract disagrees with the recorded B4 payload: "
            f"{tuple(b1.FITTED_PAYLOAD_KEYS)!r}"
        )
    if not hasattr(v2, "detector_table"):
        raise GateError("the detector-table compactor is missing; the B4 amendment is not in force")
    return {
        "contract": "fitted_state",
        "status": "agrees",
        "evidence": "nine-key payload including detector_thresholds; freeze refuses it absent",
    }


def _check_denominator_policy(protocol: Mapping) -> dict:
    minima = protocol["insufficient_data"]
    disagreements = []
    if b3.MIN_TEST_CLUSTERS != minima["minimum_test_clusters"]:
        disagreements.append("minimum_test_clusters")
    if b3.MIN_TEST_NULLS_PER_STRATUM != minima["minimum_test_nulls_per_stratum"]:
        disagreements.append("minimum_test_nulls_per_stratum")
    if (
        b3.MIN_TEST_INJECTIONS_PER_DEPTH_PER_STRATUM
        != minima["minimum_test_injections_per_depth_per_stratum"]
    ):
        disagreements.append("minimum_test_injections_per_depth_per_stratum")
    if disagreements:
        raise GateError(f"denominator policy disagrees with the frozen protocol: {disagreements}")
    return {
        "contract": "denominator_policy",
        "status": "agrees",
        "evidence": (
            "evaluator enforces the protocol minima and reports observed counts; the campaign "
            "literals remain a real-campaign requirement"
        ),
    }


def _check_g12_audit(repo_root: Path) -> dict:
    if not hasattr(b3, "record_refusal"):
        raise GateError("the G12 refusal audit is missing")
    audit_dir = b3.default_audit_dir(Path(repo_root))
    frozen = Path(repo_root, "reports", "phase11_generalization")
    if audit_dir.resolve().is_relative_to(frozen.resolve()):
        raise GateError("the default refusal audit directory resolves inside the frozen tree")
    return {
        "contract": "g12_refusal_audit",
        "status": "agrees",
        "evidence": f"records are written to {audit_dir.as_posix()}, outside the frozen tree",
    }


def _check_readiness_gates(protocol: Mapping) -> dict:
    if tuple(runner.MODES) != EXPECTED_MODES:
        raise GateError(f"readiness gates changed: MODES = {tuple(runner.MODES)!r}")
    blockers = runner.execution_blockers(dict(protocol))
    if not blockers:
        raise GateError(
            "the protocol no longer reports any execution blocker; B5 cannot record a "
            "not-granted decision against a protocol that claims readiness"
        )
    return {
        "contract": "readiness_gates",
        "status": "agrees",
        "evidence": f"{len(blockers)} blocker(s): {'; '.join(blockers[:2])}",
    }


def _agreement_checks(protocol: Mapping, repo_root: Path) -> list[dict]:
    """Contract cross-checks. Any disagreement raises: B5 must not record agreement it lacks."""
    return [
        _check_fitted_contract(),
        _check_denominator_policy(protocol),
        _check_g12_audit(repo_root),
        _check_readiness_gates(protocol),
    ]


def assess_readiness(*, manifest_dir: Path, repo_root: Path) -> dict:
    """Return the readiness decision record. It never authorizes anything."""
    protocol, protocol_hash = v2.load_protocol_v21(Path(manifest_dir) / v2.AUTHORIZED_PROTOCOL_NAME)
    if protocol_hash != v2.AUTHORIZED_PROTOCOL_SHA256:
        raise GateError(f"protocol hash {protocol_hash} is not the authorized pin")
    checks = _agreement_checks(protocol, Path(repo_root))
    flags = {
        "campaign_ready": protocol.get("campaign_ready"),
        "execution_ready": protocol.get("execution_ready"),
        "status": protocol.get("status"),
    }
    return {
        "stage": "B5",
        "schema_version": 1,
        "decision_kind": DECISION_KIND,
        "decision": (
            "readiness is not granted by this stage: no v2.4 revision is proposed and the "
            "campaign_ready / execution_ready flags stay false"
        ),
        "protocol_sha256": protocol_hash,
        "protocol_version": protocol.get("version"),
        "flags": flags,
        "checks": checks,
        "outstanding": list(OUTSTANDING),
        "authorizes_execution": False,
        "protocol_revision_proposed": False,
        "required_approval": (
            "B7: an explicit owner authorization document plus a clean committed source "
            "baseline; a readiness revision would additionally need review and a repin"
        ),
        "documentation_trap": (
            "the frozen protocol text still declares PROPOSAL ONLY and its execution_ready_"
            "reason predates the B0-B4 hardening; neither the text nor a code pin is "
            "authorization, and this record is the operative decision"
        ),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _resolve_decision_dir(out_dir: Path, *, manifest_dir: Path, repo_root: Path) -> Path:
    resolved = Path(out_dir).resolve()
    frozen = Path(manifest_dir).resolve()
    if resolved == frozen or resolved.is_relative_to(frozen):
        raise OutputIsolationError(
            f"decision directory {resolved} is inside the frozen manifest tree {frozen}"
        )
    try:
        safeguards.assert_not_protected_directory(
            resolved, root=Path(repo_root).resolve(), purpose="B5 readiness decision"
        )
    except safeguards.SafeguardError as exc:
        raise OutputIsolationError(str(exc)) from exc
    if resolved.exists() and not resolved.is_dir():
        raise OutputIsolationError(f"decision path {resolved} exists and is not a directory")
    return resolved


def write_decision(decision: dict, out_dir: Path, *, manifest_dir: Path, repo_root: Path) -> dict:
    """Persist the decision record and its hash outside the protected tree."""
    if decision.get("authorizes_execution") is not False:
        raise GateError("a B5 decision record must never claim execution authority")
    resolved = _resolve_decision_dir(out_dir, manifest_dir=manifest_dir, repo_root=repo_root)
    resolved.mkdir(parents=True, exist_ok=True)
    digest = v2.write_json_with_sidecar(resolved / DECISION_FILENAME, decision)
    return {"path": str(resolved / DECISION_FILENAME), "sha256": digest}
