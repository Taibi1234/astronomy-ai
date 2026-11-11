"""Stage 3 tests: overwrite safeguards, marker races/interruption, MMD consistency.

Everything here runs against temporary directories. No protected directory is used as a
write target, no test row is touched, and the legacy commands are never pointed at the real
``reports/phase11_generalization`` tree.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import generalization as gen  # noqa: E402
from research import phase11, safeguards, test_access  # noqa: E402
from research import phase11_v2 as v2  # noqa: E402
from research import run_phase11 as run  # noqa: E402

REAL_MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"
V23_PATH = REAL_MANIFEST_DIR / "protocol_v2_3.json"
needs_v23 = pytest.mark.skipif(not V23_PATH.is_file(), reason="v2.3 proposal is not present")


def _layout(root: Path) -> dict[str, Path]:
    base = root / "reports" / "phase11_generalization"
    return {
        "manifest": base,
        "smoke": base / "smoke",
        "quarantine": base / "smoke_invalid_scope_20261022",
    }


# --- guard unit behaviour ---------------------------------------------------


def test_guard_refuses_each_protected_directory(tmp_path):
    root = tmp_path / "repo"
    for label, path in _layout(root).items():
        path.mkdir(parents=True)
        with pytest.raises(safeguards.SafeguardError, match="protected"):
            safeguards.assert_safe_output(path, root=root, purpose="unit")
        assert label  # keep the loop variable meaningful


def test_guard_refuses_a_directory_that_already_holds_a_frozen_artifact(tmp_path):
    root = tmp_path / "repo"
    elsewhere = tmp_path / "copy" / "phase11_generalization"
    elsewhere.mkdir(parents=True)
    (elsewhere / "protocol_v2_2.json").write_text("{}", encoding="utf-8")
    with pytest.raises(safeguards.SafeguardError, match="already contains"):
        safeguards.assert_safe_output(elsewhere, root=root, purpose="unit")


def test_guard_allows_a_fresh_directory_and_leaves_it_empty(tmp_path):
    root = tmp_path / "repo"
    target = tmp_path / "fresh"
    target.mkdir()
    resolved = safeguards.assert_safe_output(target, root=root, purpose="unit")
    assert resolved == target.resolve()
    assert list(target.iterdir()) == []


def test_guard_allows_an_unrelated_new_subdirectory(tmp_path):
    root = tmp_path / "repo"
    target = root / "reports" / "phase11_generalization" / "campaign_future"
    target.mkdir(parents=True)
    safeguards.assert_safe_output(target, root=root, purpose="unit")


def test_refusal_does_not_touch_the_target(tmp_path):
    root = tmp_path / "repo"
    target = _layout(root)["smoke"]
    target.mkdir(parents=True)
    sentinel = target / "fitted.json"
    sentinel.write_text('{"keep": true}', encoding="utf-8")
    before = sorted(p.name for p in target.iterdir())
    with pytest.raises(safeguards.SafeguardError):
        safeguards.assert_safe_output(target, root=root, purpose="unit")
    assert sorted(p.name for p in target.iterdir()) == before
    assert json.loads(sentinel.read_text(encoding="utf-8")) == {"keep": True}


# --- CLI wiring -------------------------------------------------------------


def test_generalization_cli_refuses_its_default_protected_target(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    _layout(root)["manifest"].mkdir(parents=True)
    monkeypatch.setattr(gen, "project_root", lambda: root)
    monkeypatch.setattr(sys, "argv", ["generalization"])
    with pytest.raises(SystemExit) as excinfo:
        gen.main()
    assert "refused" in str(excinfo.value)
    assert list(_layout(root)["manifest"].iterdir()) == []


def test_phase11_stage0_cli_refuses_its_default_protected_target(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    _layout(root)["manifest"].mkdir(parents=True)
    monkeypatch.setattr(gen, "project_root", lambda: root)
    monkeypatch.setattr(sys, "argv", ["phase11"])
    with pytest.raises(SystemExit) as excinfo:
        phase11.main()
    assert "refused" in str(excinfo.value)
    assert list(_layout(root)["manifest"].iterdir()) == []


def test_smoke_execute_refuses_the_historical_smoke_directory(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    protected = _layout(root)["smoke"]
    protected.mkdir(parents=True)
    monkeypatch.setattr(gen, "project_root", lambda: root)
    monkeypatch.setattr(run, "preflight", lambda *a, **k: {"mode": "smoke"})
    with pytest.raises(phase11.GateError, match="protected historical smoke"):
        run.run_smoke(root / "reports" / "phase11_generalization", protected, execute=True)
    assert list(protected.iterdir()) == []


def test_smoke_cli_returns_three_when_the_guard_refuses(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repo"
    _layout(root)["smoke"].mkdir(parents=True)
    monkeypatch.setattr(gen, "project_root", lambda: root)
    monkeypatch.setattr(run, "preflight", lambda *a, **k: {"mode": "smoke"})
    code = run.main(["--execute"])
    captured = capsys.readouterr()
    assert code == 3
    assert "refused" in captured.err
    assert list(_layout(root)["smoke"].iterdir()) == []


def test_smoke_dry_run_is_not_affected_by_the_guard(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    monkeypatch.setattr(gen, "project_root", lambda: root)
    monkeypatch.setattr(run, "preflight", lambda *a, **k: {"mode": "smoke", "executed": False})
    result = run.run_smoke(
        root / "reports" / "phase11_generalization", tmp_path / "new", execute=False
    )
    assert result["executed"] is False
    assert not (tmp_path / "new").exists()


# --- marker completion race and interruption --------------------------------


def test_successful_completion_records_a_nonce(tmp_path):
    v2.begin_marker(tmp_path, v2.MARKER_ACCESS, {})
    record = v2.complete_marker(tmp_path, v2.MARKER_ACCESS)
    stored = json.loads((tmp_path / v2.MARKER_ACCESS).read_text(encoding="utf-8"))
    assert record["completion_nonce"] == stored["completion_nonce"]
    assert stored["status"] == "completed"
    with pytest.raises(v2.GateError, match="only started"):
        v2.complete_marker(tmp_path, v2.MARKER_ACCESS)


def test_completion_that_loses_a_race_fails_closed(tmp_path, monkeypatch):
    v2.begin_marker(tmp_path, v2.MARKER_ACCESS, {})

    def foreign_replace(path, payload):
        foreign = dict(payload)
        foreign["completion_nonce"] = "0" * 32
        path.write_text(json.dumps(foreign), encoding="utf-8")

    monkeypatch.setattr(test_access, "_replace_atomically", foreign_replace)
    with pytest.raises(v2.GateError, match="lost a race"):
        v2.complete_marker(tmp_path, v2.MARKER_ACCESS)
    assert v2.marker_state(tmp_path, v2.MARKER_ACCESS) == "completed"


def test_interrupted_completion_leaves_started_and_refuses_a_restart(tmp_path, monkeypatch):
    v2.begin_marker(tmp_path, v2.MARKER_GENERATION, {})

    def failing_replace(path, payload):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(test_access, "_replace_atomically", failing_replace)
    with pytest.raises(v2.GateError, match="could not be committed"):
        v2.complete_marker(tmp_path, v2.MARKER_GENERATION)
    assert v2.marker_state(tmp_path, v2.MARKER_GENERATION) == "started"
    with pytest.raises(v2.GateError, match="already exists"):
        v2.begin_marker(tmp_path, v2.MARKER_GENERATION, {})
    with pytest.raises(v2.GateError, match="never reset"):
        v2.assert_no_markers(tmp_path)


def test_zero_byte_marker_reads_as_invalid_and_blocks(tmp_path):
    (tmp_path / v2.MARKER_GENERATION).write_bytes(b"")
    assert v2.marker_state(tmp_path, v2.MARKER_GENERATION) == "invalid"
    with pytest.raises(v2.GateError, match="invalid"):
        v2.assert_no_markers(tmp_path)


def test_stray_temporary_file_does_not_mask_an_existing_marker(tmp_path):
    v2.begin_marker(tmp_path, v2.MARKER_GENERATION, {})
    (tmp_path / (v2.MARKER_GENERATION + ".tmp")).write_text("litter", encoding="utf-8")
    with pytest.raises(v2.GateError, match="one-way"):
        v2.assert_no_markers(tmp_path)


# --- MMD consistency --------------------------------------------------------


def _steady_frame() -> pd.DataFrame:
    rows = []
    for index, (l7, physics) in enumerate(
        [(1.0, 0.0), (1.0, 0.0), (1.0, 0.0), (0.9, 0.1), (0.9, 0.1)]
    ):
        quarter = f"Q{index:02d}"
        for repeat in range(2):
            rows.append(
                {
                    "quarter": quarter,
                    "trial_id": f"{quarter}-{repeat}",
                    "rec_l7": l7,
                    "rec_physics": physics,
                }
            )
    return pd.DataFrame(rows)


def test_classification_is_descriptive_only_with_the_flag_false():
    result = v2.paired_comparison(_steady_frame(), resamples=200)
    assert result["status"] == "descriptive_only"
    assert result["practical_superiority_claim"] is False
    assert result["mmd"] is None
    combined = v2.combine_confirmatory({"observed": result, "amplified_x2": dict(result)})
    assert combined["status"] == "descriptive_only"
    assert combined["practical_superiority_claim"] is False


def test_positive_mmd_override_is_also_refused():
    with pytest.raises(v2.GateError, match="caller-supplied overrides are refused"):
        v2.paired_comparison(_steady_frame(), mmd=0.25, resamples=100)


# --- v2.3 proposal ----------------------------------------------------------


@needs_v23
def test_v23_is_accepted_and_binds_its_predecessor():
    sidecar = V23_PATH.with_name("protocol_v2_3.sha256")
    assert sidecar.is_file()
    assert sidecar.read_text(encoding="utf-8").split()[0] == v2.sha256_file(V23_PATH)
    payload, digest = v2.load_protocol_v21(V23_PATH)
    assert digest == v2.AUTHORIZED_PROTOCOL_SHA256
    assert payload["version"] == "phase11b-protocol-v2.3-proposal"
    assert payload["immediate_predecessor"]["sha256"] == v2.sha256_file(
        REAL_MANIFEST_DIR / "protocol_v2_2.json"
    )
    # The frozen artifact still carries its proposal wording; adoption is recorded by the
    # code pin and the repin report, not by editing the protocol file.
    assert "not authorized" in payload["status"].lower()
    assert payload["proposal_record"]["status"].startswith("proposal")


@needs_v23
def test_v23_changes_only_the_environment_description():
    v22 = json.loads((REAL_MANIFEST_DIR / "protocol_v2_2.json").read_text(encoding="utf-8"))
    v23 = json.loads(V23_PATH.read_text(encoding="utf-8"))
    assert v23["immediate_predecessor"]["sha256"] == v2.sha256_file(
        REAL_MANIFEST_DIR / "protocol_v2_2.json"
    )
    for key in (
        "thresholds",
        "detection",
        "comparison",
        "fpr",
        "reporting",
        "data_roles",
        "test_access",
        "provenance",
        "frozen_inputs",
        "insufficient_data",
        "bootstrap",
        "approval_decisions",
        "campaign_requirements",
        "pre_registration_state",
    ):
        assert v23[key] == v22[key], f"{key} must be unchanged"
    assert v23["environment"]["authoritative_runtime"]["python"] == "3.14.3"
    assert v23["environment"]["authoritative_runtime"]["pin_file_matches"] is True


@needs_v23
def test_the_implementation_pins_v23():
    assert v2.AUTHORIZED_PROTOCOL_NAME == "protocol_v2_3.json"
    assert (
        v2.AUTHORIZED_PROTOCOL_SHA256
        == "e1dc5cc9ed4e6e2dc4645a82efc4f7638fb0f3128248b9810c67ba339f32c154"
    )
    assert v2.AUTHORIZED_PROTOCOL_VERSION == "phase11b-protocol-v2.3-proposal"
