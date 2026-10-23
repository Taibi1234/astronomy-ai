"""Stage B readiness tests: gate logic and the separation between reporting and authority.

Synthetic fixtures only. No campaign runs, no model is fitted, no trial is generated and no
sealed data is read.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import generalization as gen  # noqa: E402
from research import phase11_runner as runner  # noqa: E402
from research import phase11_v2 as v2  # noqa: E402

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"

READY = {
    "version": "synthetic-ready-protocol",
    "campaign_ready": True,
    "execution_ready": True,
    "status": "ready for execution",
    "proposal_record": {"status": "adopted"},
}


@pytest.mark.parametrize(
    "mutation, expected",
    [
        ({"campaign_ready": False}, "campaign_ready"),
        ({"execution_ready": False}, "execution_ready"),
        ({"status": "PROPOSAL ONLY, not authorized"}, "not authorized"),
        ({"proposal_record": {"status": "proposal; NOT authorized"}}, "proposal_record"),
    ],
)
def test_each_readiness_condition_is_required(mutation, expected):
    blockers = runner.execution_blockers({**READY, **mutation})
    assert blockers, "a failing readiness condition must produce a blocker"
    assert any(expected in blocker for blocker in blockers)


def test_no_blockers_when_every_readiness_condition_is_satisfied():
    assert runner.execution_blockers(dict(READY)) == []


def test_execute_real_refuses_even_when_the_protocol_claims_ready(monkeypatch):
    monkeypatch.setattr(v2, "load_protocol_v21", lambda *a, **k: (dict(READY), "hash"))
    with pytest.raises(runner.ReadinessError) as excinfo:
        runner.execute_real(MANIFEST_DIR)
    message = str(excinfo.value)
    assert "readiness flags alone are not execution authorization" in message
    assert "preflight and synthetic validation only" in message


def test_preflight_may_report_authorized_but_execution_still_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(v2, "load_protocol_v21", lambda *a, **k: (dict(READY), "hash"))
    monkeypatch.setattr(
        v2,
        "campaign_preconditions",
        lambda *a, **k: {
            "protocol_version": "synthetic",
            "protocol_hash": "hash",
            "offsets_sha256": "offsets",
            "manifests": {},
            "provenance": {"git": {"commit": "abc", "branch": "main", "dirty": False}},
        },
    )
    out = tmp_path / "out"
    out.mkdir()

    result = runner.preflight(MANIFEST_DIR, out, gen.project_root())

    assert result["execution_blockers"] == []
    assert result["execution_authorized"] is True
    assert result["reads_test"] is False
    assert result["writes"] == []
    assert list(out.iterdir()) == []

    # Reporting is not authority: even with every flag satisfied the runner refuses.
    with pytest.raises(runner.ReadinessError):
        runner.execute_real(MANIFEST_DIR)
