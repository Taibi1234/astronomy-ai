"""Stage 4: API-level preservation guards, v2.3 audit, marker races, MMD invariants.

Every test uses temporary directories or synthetic monkeypatched payloads. No protected
directory is used as a write target, no campaign code runs, and no sealed trial is read.
"""

from __future__ import annotations

import importlib.metadata
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from research import generalization as gen  # noqa: E402
from research import phase11, safeguards, test_access  # noqa: E402
from research import phase11_v2 as v2  # noqa: E402

MANIFEST_DIR = gen.project_root() / "reports" / "phase11_generalization"
V22_PATH = MANIFEST_DIR / "protocol_v2_2.json"
V23_PATH = MANIFEST_DIR / "protocol_v2_3.json"
needs_v23 = pytest.mark.skipif(
    not (V22_PATH.is_file() and V23_PATH.is_file()), reason="v2.2/v2.3 not present"
)
AUTHORITATIVE_VENV = gen.project_root() / "webapp" / "backend" / ".venv"


def _layout(root: Path) -> dict[str, Path]:
    base = root / "reports" / "phase11_generalization"
    return {
        "manifest": base,
        "smoke": base / "smoke",
        "quarantine": base / "smoke_invalid_scope_20261022",
    }


# --- API-level guards on the two writers ------------------------------------


def test_write_manifests_refuses_the_protected_directory(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    protected = _layout(root)["manifest"]
    protected.mkdir(parents=True)
    monkeypatch.setattr(gen, "project_root", lambda: root)
    with pytest.raises(safeguards.SafeguardError, match="protected"):
        gen.write_manifests(protected)
    assert list(protected.iterdir()) == []


def test_write_manifests_allows_a_fresh_directory_and_is_repeatable(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "build_manifests", lambda root=None: {"a.json": {"phase": "11a"}})
    target = tmp_path / "fresh"
    first = gen.write_manifests(target)
    second = gen.write_manifests(target)
    assert first == second
    assert json.loads((target / "a.json").read_text(encoding="utf-8")) == {"phase": "11a"}


def test_write_stage0_refuses_before_reading_its_manifests(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    protected = _layout(root)["smoke"]
    protected.mkdir(parents=True)
    monkeypatch.setattr(gen, "project_root", lambda: root)
    # A nonexistent manifest directory would raise FileNotFoundError if the guard ran late.
    with pytest.raises(safeguards.SafeguardError, match="protected"):
        phase11.write_stage0(protected, tmp_path / "no-such-manifests")
    assert list(protected.iterdir()) == []


@pytest.mark.parametrize("name", ["manifest", "smoke", "quarantine"])
def test_write_stage0_refuses_each_protected_directory(tmp_path, monkeypatch, name):
    root = tmp_path / "repo"
    protected = _layout(root)[name]
    protected.mkdir(parents=True)
    monkeypatch.setattr(gen, "project_root", lambda: root)
    monkeypatch.setattr(phase11, "build_stage0", lambda manifest_dir: {"protocol.json": {}})
    with pytest.raises(safeguards.SafeguardError, match="protected"):
        phase11.write_stage0(protected, tmp_path)
    assert list(protected.iterdir()) == []


def test_write_stage0_allows_a_fresh_directory_and_is_repeatable(tmp_path, monkeypatch):
    monkeypatch.setattr(phase11, "build_stage0", lambda manifest_dir: {"protocol.json": {"a": 1}})
    target = tmp_path / "stage0"
    first = phase11.write_stage0(target, tmp_path)
    second = phase11.write_stage0(target, tmp_path)
    assert first == second
    assert (target / "protocol.json").is_file()
    assert (target / "protocol.sha256").is_file()


# --- marker concurrency and interruption ------------------------------------


def test_simultaneous_completion_attempts_leave_exactly_one_marker(tmp_path, monkeypatch):
    v2.begin_marker(tmp_path, v2.MARKER_ACCESS, {})
    original = test_access._replace_atomically
    state = {"nested_done": False}

    def interleaved(path, payload):
        # The "second process" completes first, then our own replace lands.
        if not state["nested_done"]:
            state["nested_done"] = True
            v2.complete_marker(tmp_path, v2.MARKER_ACCESS)
        original(path, payload)

    monkeypatch.setattr(test_access, "_replace_atomically", interleaved)
    record = v2.complete_marker(tmp_path, v2.MARKER_ACCESS)

    assert record["status"] == "completed"
    assert [p.name for p in tmp_path.iterdir()] == [v2.MARKER_ACCESS]
    stored = json.loads((tmp_path / v2.MARKER_ACCESS).read_text(encoding="utf-8"))
    assert stored["completion_nonce"] == record["completion_nonce"]
    with pytest.raises(v2.GateError, match="already exists"):
        v2.begin_marker(tmp_path, v2.MARKER_ACCESS, {})


def test_second_completion_after_a_race_is_refused(tmp_path):
    v2.begin_marker(tmp_path, v2.MARKER_GENERATION, {})
    v2.complete_marker(tmp_path, v2.MARKER_GENERATION)
    with pytest.raises(v2.GateError, match="only started"):
        v2.complete_marker(tmp_path, v2.MARKER_GENERATION)


def test_crash_after_temp_write_keeps_the_marker_started(tmp_path, monkeypatch):
    v2.begin_marker(tmp_path, v2.MARKER_GENERATION, {})

    def crash_after_temp(path, payload):
        (path.parent / (path.name + ".tmp")).write_text("partial", encoding="utf-8")
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(test_access, "_replace_atomically", crash_after_temp)
    with pytest.raises(v2.GateError, match="could not be committed"):
        v2.complete_marker(tmp_path, v2.MARKER_GENERATION)
    assert v2.marker_state(tmp_path, v2.MARKER_GENERATION) == "started"
    with pytest.raises(v2.GateError, match="already exists"):
        v2.begin_marker(tmp_path, v2.MARKER_GENERATION, {})
    with pytest.raises(v2.GateError, match="never reset"):
        v2.assert_no_markers(tmp_path)


@pytest.mark.parametrize("state", ["started", "completed", "invalid"])
def test_marker_existence_gate_is_status_independent(tmp_path, state):
    path = tmp_path / v2.MARKER_ACCESS
    if state == "invalid":
        path.write_text("{not json", encoding="utf-8")
    else:
        path.write_text(json.dumps({"status": state}), encoding="utf-8")
    with pytest.raises(v2.GateError, match="one-way|invalid"):
        v2.assert_no_markers(tmp_path)


def test_completed_marker_blocks_any_further_preflight(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    v2.begin_marker(out_dir, v2.MARKER_ACCESS, {})
    v2.complete_marker(out_dir, v2.MARKER_ACCESS)

    monkeypatch.setattr(v2, "load_protocol_v21", lambda path, **kwargs: ({}, "abc"))
    monkeypatch.setattr(v2, "validate_manifests", lambda d, p: {})
    monkeypatch.setattr(v2, "load_frozen_offsets", lambda d, p: ({}, "abc"))
    with pytest.raises(v2.GateError, match="one-way"):
        v2.campaign_preconditions(tmp_path / "manifests", out_dir, tmp_path, source_paths=[])


def test_module_exposes_no_evaluation_or_campaign_api():
    for name in ("evaluate_test", "run_campaign", "generate_test_trials", "metrics_test"):
        assert not hasattr(v2, name), f"{name} must not exist in the v2 module"
    source = Path(v2.__file__).read_text(encoding="utf-8")
    assert "evaluate_test(" not in source
    assert "run_campaign(" not in source


# --- MMD invariants ---------------------------------------------------------


def _frame(values: list[tuple[float, float]]) -> pd.DataFrame:
    rows = []
    for index, (l7, physics) in enumerate(values):
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


@pytest.mark.parametrize(
    "values",
    [
        [(1.0, 0.0), (1.0, 0.0), (1.0, 0.0), (0.9, 0.1), (0.9, 0.1)],
        [(0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0)],
        [(1.0, 0.0), (0.0, 1.0), (1.0, 0.0), (0.0, 1.0), (0.5, 0.5)],
        [(0.2, 0.8), (0.9, 0.1), (0.3, 0.7), (0.8, 0.2), (0.6, 0.4)],
    ],
)
def test_unset_mmd_never_yields_a_confirmatory_classification(values):
    result = v2.paired_comparison(_frame(values), resamples=200)
    # Numerical degeneracy or heterogeneity is reported as inconclusive; both are
    # non-confirmatory. The invariant under test is that "superior" is unreachable.
    assert result["status"] in {"descriptive_only", "inconclusive"}
    assert result["status"] != "superior"
    assert result["practical_superiority_claim"] is False
    assert result["mmd"] is None


def test_any_mmd_override_is_refused():
    for value in (-1.0, 0.0, 0.05, 1.0):
        with pytest.raises(v2.GateError, match="caller-supplied overrides are refused"):
            v2.paired_comparison(_frame([(1.0, 0.0)] * 5), mmd=value)


def test_combine_confirmatory_cannot_upgrade_descriptive_results():
    descriptive = v2.paired_comparison(
        _frame([(1.0, 0.0), (1.0, 0.0), (1.0, 0.0), (0.9, 0.1), (0.9, 0.1)]),
        resamples=200,
    )
    assert descriptive["status"] == "descriptive_only"
    combined = v2.combine_confirmatory(
        {"observed": descriptive, "amplified_x2": {"status": "superior"}}
    )
    assert combined["status"] == "descriptive_only"
    assert combined["practical_superiority_claim"] is False


def test_module_constant_is_still_unset():
    assert v2.MINIMUM_MEANINGFUL_DIFFERENCE is None


# --- protocol v2.3 audit ----------------------------------------------------


def _diff(left, right, prefix=""):
    paths = []
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in left or key not in right:
                paths.append(path)
            else:
                paths.extend(_diff(left[key], right[key], path))
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            paths.append(f"{prefix}[len]")
        else:
            for index, (a, b) in enumerate(zip(left, right, strict=True)):
                paths.extend(_diff(a, b, f"{prefix}[{index}]"))
    elif left != right:
        paths.append(prefix)
    return paths


@needs_v23
def test_v23_sidecar_and_predecessor_binding():
    sidecar = MANIFEST_DIR / "protocol_v2_3.sha256"
    assert sidecar.read_text(encoding="utf-8").split()[0] == v2.sha256_file(V23_PATH)
    payload = json.loads(V23_PATH.read_text(encoding="utf-8"))
    assert payload["immediate_predecessor"]["sha256"] == v2.sha256_file(V22_PATH)
    assert payload["immediate_predecessor"]["version"] == "phase11b-protocol-v2.2"
    assert payload["supersedes"]["sha256"] == v2.sha256_file(MANIFEST_DIR / "protocol.json")


@needs_v23
def test_v23_recursive_diff_is_confined_to_environment_and_provenance():
    v22 = json.loads(V22_PATH.read_text(encoding="utf-8"))
    v23 = json.loads(V23_PATH.read_text(encoding="utf-8"))
    changed = _diff(v22, v23)
    allowed_exact = {
        "version",
        "status",
        "frozen_at",
        "input_verification.verified_at",
    }
    allowed_prefixes = (
        "environment",
        "immediate_predecessor",
        "changelog_vs_v1",
        "proposal_record",
    )
    unexpected = [
        path
        for path in changed
        if path not in allowed_exact and not path.startswith(allowed_prefixes)
    ]
    assert unexpected == [], f"unauthorized changes: {unexpected}"
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


@needs_v23
def test_v23_recorded_versions_match_the_running_authoritative_venv():
    if not Path(sys.executable).resolve().is_relative_to(AUTHORITATIVE_VENV.resolve()):
        pytest.skip("not running under webapp/backend/.venv")
    recorded = json.loads(V23_PATH.read_text(encoding="utf-8"))["environment"][
        "authoritative_runtime"
    ]
    assert (
        recorded["python"]
        == f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    assert recorded["numpy"] == np.__version__
    assert recorded["pandas"] == pd.__version__
    assert recorded["scipy"] == importlib.metadata.version("scipy")
    assert recorded["scikit-learn"] == importlib.metadata.version("scikit-learn")
    assert recorded["batman-package"] == importlib.metadata.version("batman-package")
    assert recorded["pytest"] == importlib.metadata.version("pytest")
    assert recorded["pin_file_matches"] is True


@needs_v23
def test_implementation_is_pinned_to_v2_3_and_refuses_v2_2():
    assert v2.AUTHORIZED_PROTOCOL_NAME == "protocol_v2_3.json"
    assert v2.AUTHORIZED_PROTOCOL_SHA256 == v2.sha256_file(V23_PATH)
    assert v2.AUTHORIZED_PROTOCOL_VERSION == "phase11b-protocol-v2.3-proposal"
    # The predecessor is preserved but must not be silently accepted by the new pin.
    with pytest.raises(v2.GateError, match="not the authorized protocol"):
        v2.load_protocol_v21(V22_PATH)
