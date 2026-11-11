"""Phase 11 Stage B6: the MMD decision record (design §5.8, decision D1).

In this project "MMD" is the **minimum meaningful difference** — the effect size that would make
a recall difference practically meaningful — not a two-sample maximum-mean-discrepancy statistic.
The frozen protocol leaves it deliberately unset (decision D1, value ``null``), so the B6 branch
taken here is the design's second option: **a recorded decision to stay descriptive-only**.

No value is invented, no kernel or resampling diagnostic is introduced (none is specified
anywhere in the frozen design, protocol or code), and nothing here can turn an inconclusive
result into a pass: the decision record only reads state and probes the existing enforcement.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from . import phase11_v2 as v2
from .phase11 import GateError

DECISION_KIND = "mmd_stays_unset_descriptive_only"
DECISION = (
    "the minimum meaningful difference stays unset (protocol decision D1); conclusions are "
    "descriptive-only and no practical-superiority claim may be made"
)
CONSEQUENCES = (
    "paired comparisons can return descriptive_only or inconclusive, never superior",
    "statistical superiority may be described only where the pre-registered comparison supports "
    "it, with the limited power and the five-cluster structure disclosed",
    "an inconclusive stratum is never rescued by pooling, reweighting or a substitute denominator",
)
CHANGE_REQUIREMENTS = (
    "an explicit owner decision naming the substantive difference that matters",
    "a protocol revision carrying the value (v2.4 beyond the readiness question), its sidecar and "
    "an independent review",
    "a repin of the implementation to the revised protocol hash",
)
DIAGNOSTIC_NOTE = (
    "no MMD diagnostic is specified by the frozen design: MMD denotes the minimum meaningful "
    "difference (decision D1), not a kernel two-sample statistic, so no kernel, bandwidth, "
    "permutation scheme or diagnostic seed exists to implement"
)


def _probe_frame() -> pd.DataFrame:
    """A tiny paired frame whose comparison is well determined; synthetic only."""
    return pd.DataFrame(
        {
            "trial_id": [f"t{index}" for index in range(12)],
            "quarter": ["Q02"] * 4 + ["Q09"] * 4 + ["Q13"] * 4,
            "rec_l7": [1.0] * 9 + [0.0] * 3,
            "rec_physics": [0.0] * 12,
        }
    )


def _check_protocol_d1(protocol: Mapping) -> dict:
    decision = protocol["approval_decisions"]["D1_minimum_meaningful_difference"]
    value = decision.get("value")
    if value is not None:
        raise GateError(
            "the protocol now carries a minimum meaningful difference "
            f"({value!r}); B6 does not adopt a value — that needs a protocol revision and repin"
        )
    status = str(decision.get("status", "")).lower()
    if "unset" not in status:
        raise GateError(f"D1 status does not declare the value unset: {decision.get('status')!r}")
    return {
        "check": "protocol_decision_D1",
        "status": "agrees",
        "evidence": f"value is null; status {decision.get('status')!r}",
    }


def _check_code_constant() -> dict:
    if v2.MINIMUM_MEANINGFUL_DIFFERENCE is not None:
        raise GateError(
            "the implementation carries a minimum meaningful difference constant "
            f"({v2.MINIMUM_MEANINGFUL_DIFFERENCE!r}); the frozen protocol leaves it unset"
        )
    return {
        "check": "code_constant",
        "status": "agrees",
        "evidence": "phase11_v2.MINIMUM_MEANINGFUL_DIFFERENCE is None",
    }


def _check_enforcement() -> dict:
    """Probe the public comparison path: overrides refused, status capped at descriptive_only."""
    frame = _probe_frame()
    try:
        v2.paired_comparison(frame, mmd=0.1)
    except GateError:
        pass
    else:
        raise GateError(
            "paired_comparison accepted a caller-supplied minimum meaningful difference"
        )

    result = v2.paired_comparison(frame, fpr={"l7": 0.05, "physics": 0.05})
    if result["status"] == "superior":
        raise GateError("paired_comparison reported superiority with the difference unset")
    if result.get("practical_superiority_claim") is not False:
        raise GateError("paired_comparison claimed practical superiority with the difference unset")
    if result.get("mmd") is not None:
        raise GateError("paired_comparison echoed a non-null minimum meaningful difference")

    combined = v2.combine_confirmatory({"observed": result, "amplified_x2": result})
    if combined["status"] == "superior" or combined["practical_superiority_claim"]:
        raise GateError("the combined result claimed superiority with the difference unset")
    return {
        "check": "enforcement",
        "status": "agrees",
        "evidence": (
            "caller overrides refused; a clean comparison reports "
            f"{result['status']!r} and the combination {combined['status']!r}"
        ),
    }


def assess_mmd_decision(*, manifest_dir: Path, repo_root: Path) -> dict:
    """Return the B6 decision record. It grants nothing and changes no interpretation."""
    protocol, protocol_hash = v2.load_protocol_v21(Path(manifest_dir) / v2.AUTHORIZED_PROTOCOL_NAME)
    if protocol_hash != v2.AUTHORIZED_PROTOCOL_SHA256:
        raise GateError(f"protocol hash {protocol_hash} is not the authorized pin")
    checks = [_check_protocol_d1(protocol), _check_code_constant(), _check_enforcement()]
    return {
        "stage": "B6",
        "schema_version": 1,
        "decision_kind": DECISION_KIND,
        "decision": DECISION,
        "mmd_value": None,
        "mmd_meaning": "minimum meaningful difference (a practical-effect threshold), not a "
        "two-sample kernel statistic",
        "diagnostic": DIAGNOSTIC_NOTE,
        "consequences": list(CONSEQUENCES),
        "change_requirements": list(CHANGE_REQUIREMENTS),
        "checks": checks,
        "protocol_sha256": protocol_hash,
        "protocol_version": protocol.get("version"),
        "authorizes_execution": False,
        "overrides_confirmatory_semantics": False,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def describe_value(value: float | None) -> str:
    """Human-readable rendering used by reports; never used to select a value."""
    if value is None:
        return "unset (protocol decision D1): descriptive-only conclusions"
    if not np.isfinite(float(value)):
        raise GateError(f"a minimum meaningful difference must be finite, got {value!r}")
    return (
        f"{float(value)}: a one-off owner decision would still require a protocol revision, "
        "a sidecar and a repin before any code could apply it"
    )
